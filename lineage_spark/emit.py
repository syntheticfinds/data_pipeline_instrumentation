from lineage_spark.config import LINEAGE_SINK
from lineage_spark.hashing import ensure_row_hash

LINEAGE_COL = "__lineage__"


def persist_lineage(df):
    def emit_partition(rows):
        batch = []
        for row in rows:
            lineage = None
            if LINEAGE_COL in row.asDict():
                lineage = row[LINEAGE_COL]
            row_dict = row.asDict()
            # Remove internal columns
            row_contents = {k: v for k, v in row_dict.items()
                            if not k.startswith('__')}
            # Get row hash (output hash of last transformation)
            row_hash = row_dict.get('__row_hash__')
            if row_hash and LINEAGE_SINK.has_row_hash(row_hash):
                continue
            lineage_chain = []
            input_data_hash = None

            if lineage is not None:
                for lineage_record in lineage:
                    lineage_dict = lineage_record.asDict()
                    lineage_chain.append({
                        'op': lineage_dict.get('op'),
                        'expr': lineage_dict.get('expr')
                    })
                    # The input_hash of the first transformation is the input data
                    if input_data_hash is None:
                        input_data_hash = lineage_dict.get('input_row_hash')

            # Combine into single record per row
            combined_record = {
                'data': row_contents,
                'hash': row_hash,
                'input_data_hash': input_data_hash,
                'lineage_chain': lineage_chain,
            }
            batch.append(combined_record)

        if batch:
            LINEAGE_SINK.write_batch(batch)

    # side-effect only
    df = ensure_row_hash(df)
    df.select('*').foreachPartition(emit_partition)

    # Trigger post-persist hooks
    if not LINEAGE_SINK.all_hashes_in_historical_lineage():
        try:
            from lineage_spark.hooks import auto_trigger_compliance_analysis
            auto_trigger_compliance_analysis()
        except Exception as e:
            # Don't fail the pipeline if hooks fail
            print(f"⚠️  Hook execution warning: {e}")
    else:
        LINEAGE_SINK.clear_lineage()

    cols_to_keep = [
        c for c in df.columns
        if not c.startswith('__')
    ]
    return df.select(*cols_to_keep)
