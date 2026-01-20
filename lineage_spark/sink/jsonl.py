# lineage_spark/sink/jsonl.py
import json
import os
import uuid
from .base import LineageSink


class JsonlSink(LineageSink):
    def __init__(self, base_path="/tmp/lineage"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)
        # Cache of row hashes that have been written in this session
        self._written_hashes = set()

    def has_row_hash(self, row_hash):
        """Check if a row hash already exists in the current lineage files"""
        # Check in-memory cache first
        if row_hash in self._written_hashes:
            return True

        # Check current lineage path only
        if not os.path.exists(self.base_path):
            return False

        for filename in os.listdir(self.base_path):
            if filename.endswith('.jsonl'):
                filepath = os.path.join(self.base_path, filename)
                try:
                    with open(filepath, 'r') as f:
                        for line in f:
                            try:
                                record = json.loads(line)
                                if record.get('hash') == row_hash:
                                    # Add to cache for faster future lookups
                                    self._written_hashes.add(row_hash)
                                    return True
                            except json.JSONDecodeError:
                                continue
                except (IOError, OSError):
                    continue

        return False

    def all_hashes_in_historical_lineage(self):
        """Check if all hashes from /tmp/lineage are already in /tmp/all_lineage"""
        all_lineage_path = "/tmp/all_lineage"

        # If no historical lineage exists, hashes are not there
        if not os.path.exists(all_lineage_path):
            return False

        # If current lineage doesn't exist, consider it as "all in historical"
        if not os.path.exists(self.base_path):
            return True

        # Build set of all hashes in historical lineage
        historical_hashes = set()
        for filename in os.listdir(all_lineage_path):
            if filename.endswith('.jsonl'):
                filepath = os.path.join(all_lineage_path, filename)
                try:
                    with open(filepath, 'r') as f:
                        for line in f:
                            try:
                                record = json.loads(line)
                                row_hash = record.get('hash')
                                if row_hash:
                                    historical_hashes.add(row_hash)
                            except json.JSONDecodeError:
                                continue
                except (IOError, OSError):
                    continue

        # Check if all current lineage hashes are in historical lineage
        for filename in os.listdir(self.base_path):
            if filename.endswith('.jsonl'):
                filepath = os.path.join(self.base_path, filename)
                try:
                    with open(filepath, 'r') as f:
                        for line in f:
                            try:
                                record = json.loads(line)
                                row_hash = record.get('hash')
                                if row_hash and row_hash not in historical_hashes:
                                    # Found a hash not in historical lineage
                                    return False
                            except json.JSONDecodeError:
                                continue
                except (IOError, OSError):
                    continue

        # All hashes from current lineage are in historical lineage
        return True

    def write_batch(self, rows):
        filename = f"part-{uuid.uuid4().hex}.jsonl"
        path = os.path.join(self.base_path, filename)

        with open(path, "a") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
                # Cache the hash for future lookups
                if 'hash' in row:
                    self._written_hashes.add(row['hash'])
    
    def clear_lineage(self):
        """Clear all lineage files in the current lineage path"""
        if not os.path.exists(self.base_path):
            return

        for filename in os.listdir(self.base_path):
            if filename.endswith('.jsonl'):
                filepath = os.path.join(self.base_path, filename)
                try:
                    os.remove(filepath)
                except (IOError, OSError):
                    continue
