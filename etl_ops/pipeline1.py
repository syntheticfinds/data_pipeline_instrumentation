from lineage_spark.sql import SparkSession
from lineage_spark.sql.functions import col

spark = SparkSession.builder.getOrCreate()

df = spark.createDataFrame(
    [
        (1, 50, 1000, "US", 25),
        (2, 0, 500, "EU", 65),
        (3, 75, 1500, "US", 30),
    ],
    ["user_id", "clicks", "impressions", "region", "age"]
)

# Apply transformations
result_df = df.withColumn("ctr", col("clicks") / col("impressions"))

output_path = "/tmp/pipeline1_output.csv"
result_df.toPandas().to_csv(output_path, index=False)