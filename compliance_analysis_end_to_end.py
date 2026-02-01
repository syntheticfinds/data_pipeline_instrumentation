import os
import json

from dotenv import load_dotenv

load_dotenv()


def step2_extract_data():
    """Step 2: Extract materialized data from lineage"""
    print("\n" + "="*80)
    print("STEP 2: EXTRACTING MATERIALIZED DATA FROM LINEAGE")
    print("="*80)

    lineage_path = "/tmp/lineage"
    all_lineage_path = "/tmp/all_lineage"
    materialized_records = []

    if not os.path.exists(lineage_path):
        print(f"❌ Error: Lineage path {lineage_path} does not exist")
        print("   Did you run the pipeline first?")
        return None

    # Build index of all historical lineage by hash
    print("\nIndexing historical lineage from /tmp/all_lineage...")
    all_lineage_index = {}
    if os.path.exists(all_lineage_path):
        for filename in os.listdir(all_lineage_path):
            if filename.endswith('.jsonl'):
                filepath = os.path.join(all_lineage_path, filename)
                with open(filepath, 'r') as f:
                    for line in f:
                        historical_record = json.loads(line)
                        record_hash = historical_record.get('hash')
                        if record_hash:
                            all_lineage_index[record_hash] = historical_record
        print(f"✅ Indexed {len(all_lineage_index)} historical records")
    else:
        print(f"⚠️  /tmp/all_lineage does not exist, skipping historical lookup")

    # Read all lineage files and deduplicate by hash
    print(f"\nReading current pipeline lineage from {lineage_path}...")
    file_count = 0
    seen_hashes = set()

    for filename in os.listdir(lineage_path):
        if filename.endswith('.jsonl'):
            file_count += 1
            filepath = os.path.join(lineage_path, filename)
            with open(filepath, 'r') as f:
                for line in f:
                    record = json.loads(line)
                    # Deduplicate by hash (each unique row)
                    record_hash = record.get('hash')
                    if record_hash and record_hash not in seen_hashes:
                        seen_hashes.add(record_hash)

                        # Look up origin and lineage metadata in historical lineage
                        input_data_hash = record.get('input_data_hash')
                        historical_lineage_metadata = None
                        if input_data_hash and input_data_hash in all_lineage_index:
                            historical_record = all_lineage_index[input_data_hash]
                            # Copy over data_origin_metadata if it exists
                            if 'data_origin_metadata' in historical_record:
                                record['data_origin_metadata'] = historical_record['data_origin_metadata']
                            # Copy over lineage_chain_metadata to combine with current
                            if 'lineage_chain_metadata' in historical_record:
                                historical_lineage_metadata = historical_record['lineage_chain_metadata']

                        # Ensure data_origin_metadata exists (empty string if not found)
                        if 'data_origin_metadata' not in record:
                            record['data_origin_metadata'] = ""

                        # Store historical lineage metadata for later combination
                        if historical_lineage_metadata:
                            record['historical_lineage_chain_metadata'] = historical_lineage_metadata

                        materialized_records.append(record)

    print(f"\n✅ Loaded {len(materialized_records)} unique materialized records from {file_count} files")

    if materialized_records:
        print(f"\nSample record:")
        print(json.dumps(materialized_records[0], indent=2))

    return materialized_records


def step3_analyze_compliance(materialized_rows, pipeline_name=""):
    """Step 3: Run AI compliance analysis and generate artifacts"""
    print("\n" + "="*80)
    print(f"STEP 3: RUNNING EU AI ACT COMPLIANCE ANALYSIS {pipeline_name}")
    print("="*80)

    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\n❌ Error: OPENAI_API_KEY not set")
        print("\nTo run compliance analysis, set your OpenAI API key:")
        print("  export OPENAI_API_KEY='sk-...'")
        print("\nSkipping analysis step.")
        return None

    from compliance_analyzer import ComplianceAnalyzer

    analyzer = ComplianceAnalyzer(api_key=api_key)

    print("\n📋 The AI will autonomously:")
    print("  • Examine the data and lineage")
    print("  • Search for relevant EU AI Act regulations")
    print("  • Identify compliance risks")
    print("  • Generate actual compliance artifacts")
    print("\n⏳ This may take 1-2 minutes as the AI queries regulations...")

    results = analyzer.analyze_pipeline(materialized_rows=materialized_rows)

    print("\n✅ Analysis complete!")

    # Write enriched records to /tmp/all_lineage
    if 'enriched_records' in results:
        print("\n" + "="*80)
        print("SAVING PIPELINE RECORDS TO /tmp/all_lineage")
        print("="*80)

        all_lineage_path = "/tmp/all_lineage"
        os.makedirs(all_lineage_path, exist_ok=True)

        # Write enriched records to a timestamped file
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        enriched_file = os.path.join(all_lineage_path, f"enriched_{timestamp}.jsonl")

        with open(enriched_file, 'w') as f:
            for record in results['enriched_records']:
                f.write(json.dumps(record) + '\n')

        print(f"✅ Wrote {len(results['enriched_records'])} enriched records to {enriched_file}")

    return results
