from pyspark.sql.functions import sha2, concat_ws, col
from . import originals

ROW_HASH_COL = "__row_hash__"

def ensure_row_hash(df):
    """
    df: pyspark.sql.DataFrame (classic)
    returns: pyspark.sql.DataFrame
    """
    if ROW_HASH_COL in df.schema.fieldNames():
        return df

    if originals.ORIG_WITHCOLUMN is None:
        raise RuntimeError("ORIG_WITHCOLUMN is not set. Did you import lineage_spark before creating SparkSession?")

    # Exclude internal columns (starting with __) to match Python hash computation
    cols = [col(f.name).cast("string") for f in df.schema.fields
            if not f.name.startswith('__')]
    expr = sha2(concat_ws("||", *cols), 256)

    # Bypass patched withColumn to avoid recursion
    return originals.ORIG_WITHCOLUMN(df, ROW_HASH_COL, expr)
