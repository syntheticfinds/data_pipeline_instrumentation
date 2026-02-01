from abc import ABC, abstractmethod
from typing import Iterable, Dict


class LineageSink(ABC):
    @abstractmethod
    def write_batch(self, rows: Iterable[Dict]):
        """
        Persist a batch of lineage records.
        Must be executor-safe.
        """
        pass

    @abstractmethod
    def has_row_hash(self, row_hash: str) -> bool:
        """
        Check if a row hash already exists in the lineage store.
        Must be executor-safe.
        """
        pass

    @abstractmethod
    def all_hashes_in_historical_lineage(self) -> bool:
        """
        Check if all hashes from the current lineage are already in historical lineage.
        Must be executor-safe.
        """
        pass

    @abstractmethod
    def clear_lineage(self):
        """
        Clear the current lineage data.
        Must be executor-safe.
        """
        pass
