# lineage_spark/sql/session.py

from pyspark.sql import SparkSession as _SparkSession
import lineage_spark  # ensures patches are installed

class SparkSession:
    # Expose builder as a property, just like PySpark
    builder = _SparkSession.builder
