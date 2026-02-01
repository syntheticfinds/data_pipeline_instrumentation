from pyspark.sql.classic.dataframe import DataFrame
from pyspark.sql.readwriter import DataFrameWriter
from lineage_spark.emit import persist_lineage


def patch_action(method_name):
    original = getattr(DataFrame, method_name)

    def wrapped(self, *args, **kwargs):
        cleaned_df = persist_lineage(self)
        return original(cleaned_df, *args, **kwargs)

    setattr(DataFrame, method_name, wrapped)

def patch_csv():
    original = getattr(DataFrameWriter, "csv")

    def wrapped(self, path, *args, **kwargs):
        cleaned_df = persist_lineage(self._df)
        self._df = cleaned_df
        return original(self, path, *args, **kwargs)

    setattr(DataFrameWriter, "csv", wrapped)


def install():
    for action in ["show", "collect", "count", "toPandas"]:
        patch_action(action)
    patch_csv()
