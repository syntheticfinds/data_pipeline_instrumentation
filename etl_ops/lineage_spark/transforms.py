from pyspark.sql import functions as F
from pyspark.sql.column import Column

from .hashing import ensure_row_hash, ROW_HASH_COL
from pyspark.sql.classic.dataframe import DataFrame as ClassicDataFrame
from . import originals  # <-- new

INPUT_HASH_COL = "__input_row_hash__"
LINEAGE_COL = "__lineage__"

def install():
    if originals.ORIG_WITHCOLUMN is None:
        originals.ORIG_WITHCOLUMN = ClassicDataFrame.withColumn

    orig_withcolumn = originals.ORIG_WITHCOLUMN

    def patched_withColumn(self, name: str, col_expr: Column):
        # IMPORTANT: ensure_row_hash must bypass patch internally
        df = ensure_row_hash(self)

        # Drop old INPUT_HASH_COL if it exists (from previous withColumn)
        # We'll get the current row hash which becomes our input
        if INPUT_HASH_COL in df.schema.fieldNames():
            df = df.drop(INPUT_HASH_COL)

        # Preserve input hash (avoid name collisions)
        if ROW_HASH_COL in df.schema.fieldNames():
            df = df.withColumnRenamed(ROW_HASH_COL, INPUT_HASH_COL)

        # Apply *original* withColumn for user expression
        out_df = orig_withcolumn(df, name, col_expr)

        # Add output hash (bypassing patch)
        out_df = ensure_row_hash(out_df)

        # Create new lineage record
        new_lineage_record = F.struct(
            F.lit("withColumn").alias("op"),
            F.lit(col_expr._jc.toString()).alias("expr"),
            F.col(INPUT_HASH_COL).alias("input_row_hash"),
            F.col(ROW_HASH_COL).alias("output_row_hash"),
        )

        # Append to existing lineage array or create new one
        if LINEAGE_COL in out_df.schema.fieldNames():
            # Append new record to existing lineage array
            lineage_expr = F.array_union(
                F.col(LINEAGE_COL),
                F.array(new_lineage_record)
            )
        else:
            # Create new lineage array with this record
            lineage_expr = F.array(new_lineage_record)

        # Clean up INPUT_HASH_COL and add/update lineage
        # Use select to avoid withColumn recursion
        cols_to_select = [c for c in out_df.columns if c not in [INPUT_HASH_COL, LINEAGE_COL]]
        out_df = out_df.select(*cols_to_select, lineage_expr.alias(LINEAGE_COL))
        return out_df

    ClassicDataFrame.withColumn = patched_withColumn
    