"""
EU AI Act Compliance Analyzer

This module analyzes data processing pipelines for compliance with EU AI Act requirements.
It analyzes datasets against three specific requirements:
1. Data collection processes and origin of data
2. Data-preparation processing operations
3. Examination for biases
"""

import json
import os
from openai import OpenAI


class LineageReader:
    """Reads lineage data stored by lineage_spark"""

    def __init__(self, lineage_path="/tmp/lineage"):
        self.lineage_path = lineage_path

    def get_lineage_by_hash(self, row_hash: str) -> dict | None:
        """Find lineage record for a specific row hash"""
        if not os.path.exists(self.lineage_path):
            return None

        for filename in os.listdir(self.lineage_path):
            if filename.endswith('.jsonl'):
                filepath = os.path.join(self.lineage_path, filename)
                with open(filepath, 'r') as f:
                    for line in f:
                        record = json.loads(line)
                        if record.get('output_row_hash') == row_hash:
                            return record
        return None


class ComplianceAnalyzer:
    """Analyzes data pipelines for EU AI Act compliance"""

    def __init__(self, api_key: str, lineage_path="/tmp/lineage"):
        self.client = OpenAI(api_key=api_key)
        self.lineage_reader = LineageReader(lineage_path)

    def _enrich_records_with_origin_and_lineage(self, materialized_rows: list[dict], conversation_history: list[dict]) -> list[dict]:
        """
        Enrich records with origin and lineage metadata from Requirements 1 & 2

        Uses AI to extract structured metadata from conversation history
        """
        print("\nExtracting origin and lineage metadata from conversations...")

        enriched_records = []

        # Check if any records are missing data_origin_metadata
        missing_origin_metadata = any(not record.get('data_origin_metadata') for record in materialized_rows)

        # Extract unique lineage sequences for Requirement 2
        unique_sequences = {}
        for record in materialized_rows:
            lineage_chain = record.get('lineage_chain', [])
            sequence_key = tuple((step.get('op'), step.get('expr')) for step in lineage_chain)
            if sequence_key not in unique_sequences:
                unique_sequences[sequence_key] = lineage_chain

        # Extract metadata from Requirements 1 & 2
        req1_metadata = {}
        if missing_origin_metadata:
            req1_metadata = self._extract_origin_metadata(conversation_history, materialized_rows)

        req2_metadata = self._extract_lineage_metadata(conversation_history, unique_sequences)

        # Enrich each record
        for record in materialized_rows:
            enriched_record = record.copy()

            # Add data_origin_metadata from Requirement 1 (if not already set)
            if not enriched_record.get('data_origin_metadata'):
                row_hash = enriched_record.get('hash')
                enriched_record['data_origin_metadata'] = req1_metadata.get(row_hash, "")

            # Add lineage_chain_metadata from Requirement 2
            lineage_chain = enriched_record.get('lineage_chain', [])
            sequence_key = tuple((step.get('op'), step.get('expr')) for step in lineage_chain)
            current_lineage_metadata = req2_metadata.get(sequence_key, "")

            # Combine with historical lineage metadata if it exists
            historical_lineage_metadata = enriched_record.get('historical_lineage_chain_metadata', '')
            if historical_lineage_metadata and current_lineage_metadata:
                # Combine historical and current transformations
                combined_metadata = f"{historical_lineage_metadata} → {current_lineage_metadata}"
                enriched_record['lineage_chain_metadata'] = combined_metadata
            elif historical_lineage_metadata:
                enriched_record['lineage_chain_metadata'] = historical_lineage_metadata
            else:
                enriched_record['lineage_chain_metadata'] = current_lineage_metadata

            # Remove the temporary historical metadata field
            if 'historical_lineage_chain_metadata' in enriched_record:
                del enriched_record['historical_lineage_chain_metadata']

            enriched_records.append(enriched_record)

        return enriched_records

    def _extract_origin_metadata(self, conversation_history: list[dict], materialized_rows: list[dict]) -> dict:
        """Extract origin metadata from Requirement 1 conversation"""
        req1_conv = next((c for c in conversation_history if "REQUIREMENT 1" in c["requirement"]), None)
        if not req1_conv:
            return {}

        # Get unique hashes and example record schema
        unique_hashes = list(set(record.get('hash') for record in materialized_rows))

        # Ask AI to extract general origin metadata
        extract_prompt = f"""Based on the conversation above about data origins, provide a general description of the data origin and collection purpose that applies to all rows in this dataset.

                            Return ONLY the description as a plain string (not a JSON object). If the conversation did not provide clarity on data origins, return an empty string."""

        conversation = req1_conv["conversation"] + [{"role": "user", "content": extract_prompt}]

        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=conversation,
            temperature=0
        )

        general_description = response.choices[0].message.content.strip()

        # If no general description was provided, use fallback
        if not general_description:
            general_description = "Origin and purpose not specified during analysis."

        # Apply general description to all hashes
        metadata = {hash_val: general_description for hash_val in unique_hashes}
        return metadata

    def _extract_lineage_metadata(self, conversation_history: list[dict], unique_sequences: dict) -> dict:
        """Extract lineage metadata from Requirement 2 conversation"""
        req2_conv = next((c for c in conversation_history if "REQUIREMENT 2" in c["requirement"]), None)
        if not req2_conv:
            return {}

        # Prepare list of sequences for the AI
        unique_sequences_list = list(unique_sequences.values())
        sequences_json = json.dumps(unique_sequences_list, indent=2)

        # Ask AI to extract structured metadata
        extract_prompt = f"""Based on the conversation above about transformation sequences, extract metadata for EACH unique sequence listed below.

                            UNIQUE TRANSFORMATION SEQUENCES (you must provide metadata for ALL of these):
                            {sequences_json}

                            Total sequences: {len(unique_sequences_list)}

                            For EACH sequence, provide:
                            1. The purpose of the transformation sequence
                            2. The category (annotation, labelling, cleaning, updating, enrichment, aggregation)
                            3. Any additional context from the human feedback

                            IMPORTANT: You MUST provide metadata for EVERY sequence listed above. Do not skip any.

                            Return a JSON object where each key is a JSON string representation of the sequence (array of {{"op": ..., "expr": ...}} objects), and each value is the metadata description.

                            Example format:
                            {{
                            "[{{\\"op\\": \\"withColumn\\", \\"expr\\": \\"...\\"}}]": "Purpose: Calculate metrics. Category: enrichment. Context: ..."
                            }}

                            CRITICAL: Return ONLY the JSON object with no additional text. Start your response with {{ and end with }}.

                            If metadata was not clarified for a sequence, provide a general categorization based on the transformations: "Purpose: [inferred purpose]. Category: [inferred category]. Clarity: UNCLEAR" """

        conversation = req2_conv["conversation"] + [{"role": "user", "content": extract_prompt}]

        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=conversation,
            temperature=0
        )

        try:
            ai_response = response.choices[0].message.content

            # Strip any text before the JSON starts
            json_start = ai_response.find('{')
            if json_start > 0:
                ai_response = ai_response[json_start:]

            raw_metadata = json.loads(ai_response)

            # Convert string keys back to tuple keys for matching
            metadata = {}
            for seq_str, description in raw_metadata.items():
                try:
                    seq_list = json.loads(seq_str)
                    seq_key = tuple((step.get('op'), step.get('expr')) for step in seq_list)
                    metadata[seq_key] = description
                except Exception as e:
                    continue
            return metadata
        except Exception as e:
            return {}

    def _extract_dataset_bias_metadata(self, req3_conversation: list[dict]) -> str:
        """Extract dataset-level bias metadata from Requirement 3 conversation"""
        # Ask AI to extract dataset-level biases metadata
        extract_prompt = """Based on the conversation above about biases, provide a comprehensive description of the identified biases that applies to the dataset as a whole.

                            Include:
                            1. Summary of potential biases identified
                            2. How data origin and collection might introduce bias
                            3. How transformations might amplify or reduce bias
                            4. Potential impacts on health, safety, and fundamental rights

                            Return ONLY the description as a plain string (not a JSON object). If no biases were identified or discussed, return an empty string."""

        conversation = req3_conversation + [{"role": "user", "content": extract_prompt}]

        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=conversation,
            temperature=0
        )

        bias_metadata = response.choices[0].message.content.strip()

        # If no description was provided, use fallback
        if not bias_metadata:
            bias_metadata = "No specific biases identified during analysis."

        return bias_metadata

    def _generate_governance_report(self, enriched_records: list[dict], dataset_bias_metadata: str) -> str:
        """
        Generate an AI-written data governance report combining origin, lineage, and bias metadata

        Args:
            enriched_records: Records with data_origin_metadata and lineage_chain_metadata
            dataset_bias_metadata: Dataset-level bias analysis

        Returns:
            Path to the saved governance report
        """
        from datetime import datetime

        # Extract unique metadata values for the AI to synthesize
        origin_metadata_set = set()
        lineage_metadata_set = set()

        for record in enriched_records:
            origin = record.get('data_origin_metadata', '')
            if origin:
                origin_metadata_set.add(origin)

            lineage = record.get('lineage_chain_metadata', '')
            if lineage:
                lineage_metadata_set.add(lineage)

        # Prepare metadata for AI
        metadata_summary = {
            "total_records": len(enriched_records),
            "data_origins": list(origin_metadata_set),
            "transformation_sequences": list(lineage_metadata_set),
            "bias_analysis": dataset_bias_metadata
        }

        metadata_json = json.dumps(metadata_summary, indent=2)

        # Ask AI to generate comprehensive governance report
        report_prompt = f"""You are generating a Data Governance Report for EU AI Act compliance.

                            METADATA SUMMARY:
                            {metadata_json}

                            Generate a comprehensive data governance report that includes:

                            1. **Data Origin and Collection**
                            - Synthesize information from the data_origins
                            - Describe where the data came from and why it was collected
                            - Assess adequacy of documentation

                            2. **Data Transformation Lineage**
                            - Synthesize information from the transformation_sequences
                            - Describe the complete transformation pipeline
                            - Explain purpose and categorization of transformations
                            - Highlight any gaps in documentation

                            3. **Bias Analysis**
                            - Summarize the bias_analysis findings
                            - Assess potential impacts on fundamental rights
                            - Recommend mitigations if needed

                            Format the report as a well-structured JSON object with the following top-level keys:
                            - "report_type": "EU AI Act Data Governance Report"
                            - "generated_at": (current ISO timestamp)
                            - "data_origin_and_collection": (object with "summary" and "assessment" fields)
                            - "transformation_lineage": (object with "summary" and "assessment" fields)
                            - "bias_analysis": (object with "summary" and "recommendations" fields)

                            Return ONLY the JSON object, no additional text."""

        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": report_prompt}],
            temperature=0
        )

        try:
            # Parse AI-generated report
            report = json.loads(response.choices[0].message.content)

            # Add timestamp if not present
            if "generated_at" not in report:
                report["generated_at"] = datetime.now().isoformat()

        except json.JSONDecodeError:
            # Fallback if AI didn't return valid JSON
            report = {
                "report_type": "EU AI Act Data Governance Report",
                "generated_at": datetime.now().isoformat(),
                "error": "Failed to parse AI-generated report",
                "raw_response": response.choices[0].message.content
            }

        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = f"/tmp/data_governance_report_{timestamp}.json"

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        return report_path

    def analyze_pipeline(self, materialized_rows: list[dict]) -> dict:
        """
        Analyze a data pipeline for EU AI Act compliance

        Args:
            materialized_rows: List of complete lineage records from lineage_spark
                Each record contains: data, data_origin_metadata, hash, input_data_hash, lineage_chain

        Returns:
            Dict with analysis results
        """
        print("\n" + "="*80)
        print("STARTING COMPLIANCE ANALYSIS")
        print("="*80)
        print(f"Number of rows: {len(materialized_rows)}")

        # Use records directly - no preprocessing needed
        dataset_info = json.dumps(materialized_rows, indent=2)
        print(f"Prepared dataset with lineage ({len(dataset_info)} chars)")

        # Extract unique lineage sequences for Requirement 2
        print("\nExtracting unique transformation sequences...")
        unique_sequences = {}
        for record in materialized_rows:
            lineage_chain = record.get('lineage_chain', [])
            # Convert to tuple of tuples for hashability
            sequence_key = tuple((step.get('op'), step.get('expr')) for step in lineage_chain)
            if sequence_key not in unique_sequences:
                unique_sequences[sequence_key] = lineage_chain

        # Convert to list format for display
        unique_sequences_list = list(unique_sequences.values())
        print(f"Found {len(unique_sequences_list)} unique transformation sequences")

        # Interactive analysis with human-in-the-loop
        print("\nStarting interactive analysis...")
        try:
            conversation_history = []

            # Analyze each requirement separately with human feedback
            requirements = [
                ("REQUIREMENT 1: Data Collection Processes and Origin of Data", 
                 """
                - For EACH record, check if the "data_origin_metadata" field is set (non-empty string):
                - If data_origin_metadata is SET: The origin and collection purpose are documented. Summarize what is known about where this data came from and why it was collected.
                - If data_origin_metadata is EMPTY or not set: The data origin and collection purpose are AMBIGUOUS. State this clearly.
                - Output: For each record, clearly state whether origin/purpose is CLEAR or AMBIGUOUS, and provide any available information.
                - IMPORTANT: Do NOT mention the "data_origin_metadata" field or any other implementation details in your response. Frame your findings in user-friendly terms."""),

                ("REQUIREMENT 2: Data-Preparation Processing Operations",
                 """
                - You will be provided with ALL unique transformation SEQUENCES found across all rows
                - A sequence is the complete ordered list of (op, expr) pairs that represent the full transformation pipeline for a row
                - For EACH unique sequence provided:
                a) Describe what you believe the PURPOSE of this transformation sequence is
                b) Look at the columns/fields involved in each step of the sequence
                c) Categorize the OVERALL sequence into ONE of these buckets: annotation, labelling, cleaning, updating, enrichment, aggregation
                d) State whether the categorization is CLEAR or UNCLEAR
                - IMPORTANT: You MUST analyze EVERY sequence provided. Do not skip any.
                - Output: A list of ALL unique transformation sequences with their assessed purpose, category, and clarity assessment.""")
            ]

            for req_name, req_instructions in requirements:
                print("\n" + "="*80)
                print(f"ANALYZING: {req_name}")
                print("="*80)

                # Start fresh conversation for this requirement to avoid context length issues
                req_conversation = []

                # Build the base prompt
                req_prompt = f"""You are analyzing a DATASET for EU AI Act compliance.

                                DATASET:
                                {dataset_info}

                                Each record in the dataset includes:
                                - "data": The final row values (actual data)
                                - "data_origin_metadata": Metadata about the data origin and collection purpose
                                - "hash": SHA256 hash of this row
                                - "input_data_hash": Hash of the input data (before any transformations)
                                - "lineage_chain": Complete transformation history in chronological order
                                - Each transformation shows: {{"op": operation_type, "expr": transformation_expression}}
                                - lineage_chain[0] = first transformation (from input data)
                                - lineage_chain[-1] = most recent transformation (produced the final row)
                                """

                # Add unique sequences for Requirement 2
                if "REQUIREMENT 2" in req_name:
                    sequences_json = json.dumps(unique_sequences_list, indent=2)
                    req_prompt += f"""
                                    UNIQUE TRANSFORMATION SEQUENCES (extracted from all rows):
                                    {sequences_json}

                                    There are {len(unique_sequences_list)} unique sequences total.
                                    """
                req_prompt += f"""
                                {req_name}
                                {req_instructions}

                                Provide your findings for this requirement."""
                req_conversation.append({"role": "user", "content": req_prompt})

                response = self.client.chat.completions.create(
                    model="gpt-4",
                    messages=req_conversation,
                    temperature=0
                )

                finding = response.choices[0].message.content
                req_conversation.append({"role": "assistant", "content": finding})

                print("\nAI FINDINGS:")
                print("-"*80)
                print(finding)
                print("-"*80)

                # Always ask clarifying questions for all requirements
                # Ask AI to generate a clarifying question (not a statement)
                clarify_prompt = f"""Based on your findings above, ask a clarifying question to verify your understanding with the human or clarify any ambiguities.

                                    IMPORTANT: You must ask a QUESTION. Frame it as something you want to confirm or clarify.

                                    Keep it concise (1-2 sentences) and end with a question mark."""

                req_conversation.append({"role": "user", "content": clarify_prompt})

                clarify_response = self.client.chat.completions.create(
                    model="gpt-4",
                    messages=req_conversation,
                    temperature=0
                )

                clarification = clarify_response.choices[0].message.content
                req_conversation.append({"role": "assistant", "content": clarification})

                print(f"\nAI: {clarification}")

                # Get human feedback
                human_input = input("\nYour response: ").strip()

                if human_input:
                    acknowledgment_prompt = f"""The human responded: "{human_input}"

                                                Acknowledge their response briefly (1 sentence) and indicate you'll proceed to the next requirement."""

                    req_conversation.append({"role": "user", "content": acknowledgment_prompt})

                    ack_response = self.client.chat.completions.create(
                        model="gpt-4",
                        messages=req_conversation,
                        temperature=0
                    )

                    acknowledgment = ack_response.choices[0].message.content
                    req_conversation.append({"role": "assistant", "content": acknowledgment})

                    print(f"\nAI: {acknowledgment}")
                else:
                    print("\n✓ Proceeding to next requirement...")

                # Store this requirement's conversation
                conversation_history.append({
                    "requirement": req_name,
                    "conversation": req_conversation,
                })

            # Enrich records with origin and lineage metadata from Requirements 1 & 2
            print("\n" + "="*80)
            print("ENRICHING RECORDS WITH ORIGIN AND LINEAGE METADATA")
            print("="*80)

            enriched_records = self._enrich_records_with_origin_and_lineage(
                materialized_rows,
                conversation_history
            )
            print(f"✅ Enriched {len(enriched_records)} records with origin and lineage metadata")

            # After Requirements 1 & 2, ask about data governance report generation
            print("\n" + "="*80)
            print("DATA GOVERNANCE REPORT")
            print("="*80)
            print("\nA data governance report documents:")
            print("  • Data origin and collection purpose")
            print("  • Complete transformation lineage")
            print("  • Dataset-level bias analysis")
            print("\nThis is required if you plan to use this dataset to train a model in production.")

            governance_response = input("\nWould you like to generate a data governance report? (yes/no): ").strip().lower()

            dataset_bias_metadata = None
            if governance_response in ['yes', 'y']:
                print("\n✓ Will generate data governance report with bias analysis...")

                # Run bias analysis for the governance report using enriched data
                print("\n" + "="*80)
                print("ANALYZING: REQUIREMENT 3 - Examination for Biases (for Data Governance Report)")
                print("="*80)

                # Prepare enriched dataset for bias analysis
                enriched_dataset_info = json.dumps(enriched_records, indent=2)

                req_conversation = []
                req_prompt = f"""You are analyzing a DATASET for EU AI Act compliance.

                                ENRICHED DATASET (with origin and lineage metadata):
                                {enriched_dataset_info}

                                Each record in the dataset includes:
                                - "data": The final row values (actual data)
                                - "data_origin_metadata": Metadata about the data origin and collection purpose
                                - "lineage_chain_metadata": Metadata about transformation operations applied to this data
                                - "hash": SHA256 hash of this row

                                REQUIREMENT 3: Examination for Biases

                                - Examine the data attributes, origins, and transformations across the ENTIRE DATASET (not individual records)
                                - Consider how the data origin, collection purpose, and transformations might introduce or amplify biases
                                - For the dataset as a whole, identify potential biases that could:
                                a) Affect health and safety of persons
                                b) Have negative impact on fundamental rights
                                c) Lead to discrimination on the basis of race, color, religion, sex, national origin, age, disability, and genetic information
                                - Output: Dataset-level bias analysis with explanations of how biases could manifest

                                Provide your findings for this requirement."""

                req_conversation.append({"role": "user", "content": req_prompt})

                response = self.client.chat.completions.create(
                    model="gpt-4",
                    messages=req_conversation,
                    temperature=0
                )

                bias_finding = response.choices[0].message.content
                req_conversation.append({"role": "assistant", "content": bias_finding})

                print("\nAI FINDINGS:")
                print("-"*80)
                print(bias_finding)
                print("-"*80)

                # Ask clarifying question
                clarify_prompt = """Based on your findings above, ask a clarifying question to verify your understanding with the human.

                                    IMPORTANT: You must ask a QUESTION (even if it's as simple as clarifying your understanding). Frame it as something you want to confirm or clarify.

                                    Keep it concise (1-2 sentences) and end with a question mark."""

                req_conversation.append({"role": "user", "content": clarify_prompt})

                clarify_response = self.client.chat.completions.create(
                    model="gpt-4",
                    messages=req_conversation,
                    temperature=0
                )

                clarification = clarify_response.choices[0].message.content
                req_conversation.append({"role": "assistant", "content": clarification})

                print(f"\nAI: {clarification}")

                # Get human feedback
                human_input = input("\nYour response: ").strip()

                if human_input:
                    acknowledgment_prompt = f"""The human responded: "{human_input}"

                                                Acknowledge their response briefly (1 sentence)."""

                    req_conversation.append({"role": "user", "content": acknowledgment_prompt})

                    ack_response = self.client.chat.completions.create(
                        model="gpt-4",
                        messages=req_conversation,
                        temperature=0
                    )

                    acknowledgment = ack_response.choices[0].message.content
                    req_conversation.append({"role": "assistant", "content": acknowledgment})

                    print(f"\nAI: {acknowledgment}")
                else:
                    print("\n✓ Proceeding...")

                # Store bias conversation
                conversation_history.append({
                    "requirement": "REQUIREMENT 3: Examination for Biases",
                    "conversation": req_conversation,
                })

                # Extract dataset-level bias metadata
                dataset_bias_metadata = self._extract_dataset_bias_metadata(req_conversation)

                # Generate and save data governance report
                print("\n" + "="*80)
                print("GENERATING DATA GOVERNANCE REPORT")
                print("="*80)

                governance_report_path = self._generate_governance_report(
                    enriched_records,
                    dataset_bias_metadata
                )

                print(f"\n✅ Data governance report saved to: {governance_report_path}")

            else:
                print("\n✓ Skipping data governance report generation...")

            return {
                "enriched_records": enriched_records,
            }

        except Exception as e:
            print(f"\n❌ ERROR during analysis: {e}")
            import traceback
            traceback.print_exc()
            return {
                "analysis": f"Error during analysis: {e}",
                "error": str(e)
            }
