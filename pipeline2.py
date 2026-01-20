from lineage_spark.sql import SparkSession
from lineage_spark.sql.functions import col
import pandas as pd

spark = SparkSession.builder.getOrCreate()

# Read CSV from Pipeline 1
input_path = "/tmp/pipeline1_output.csv"
pdf = pd.read_csv(input_path)
df = spark.createDataFrame(pdf)

result_df = df.withColumn("value_tier",
    (col("ctr") * 100).cast("int")
)

# Write to CSV
output_path = "/tmp/pipeline2_output.csv"
result_df.toPandas().to_csv(output_path, index=False)