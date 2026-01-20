"""
Compliance Monitor: Automatic Analysis Trigger

This module triggers compliance analysis for pipeline runs.
Called automatically by lineage_spark hooks after pipeline completion.

Usage (called automatically by hooks):
    python compliance_monitor.py run
"""

import os
from dotenv import load_dotenv

load_dotenv()


class ComplianceMonitor:
    """Trigger compliance analysis for completed pipeline runs"""

    def __init__(self, lineage_path="/tmp/lineage"):
        """
        Initialize the compliance monitor

        Args:
            lineage_path: Path where lineage files are stored
        """
        self.lineage_path = lineage_path

    def _get_lineage_files(self):
        """Get list of lineage files in the lineage directory"""
        if not os.path.exists(self.lineage_path):
            return []

        files = []
        for filename in os.listdir(self.lineage_path):
            if filename.endswith('.jsonl'):
                filepath = os.path.join(self.lineage_path, filename)
                files.append(filepath)

        return files

    def _run_analysis(self):
        """Execute the compliance analysis"""
        try:
            # Import here to avoid circular dependencies
            from compliance_analysis_end_to_end import step2_extract_data, step3_analyze_compliance

            # Extract data
            materialized_rows = step2_extract_data()

            if not materialized_rows:
                print("❌ No data to analyze. Skipping compliance analysis.")
                return False

            # Run compliance analysis
            results = step3_analyze_compliance(materialized_rows, "(Auto-triggered)")

            if results:
                print("\n✅ Automatic compliance analysis complete!")
                return True
            else:
                print("\n⚠️  Compliance analysis was skipped (no API key?).")
                return False

        except Exception as e:
            print(f"\n❌ Error during automatic analysis: {e}")
            import traceback
            traceback.print_exc()
            return False

    def run(self):
        """Run compliance analysis for the current pipeline"""
        # Check if lineage data exists
        lineage_files = self._get_lineage_files()

        if not lineage_files:
            # No lineage data, nothing to analyze
            return

        # Run analysis
        self._run_analysis()


def main():
    """CLI entry point"""
    monitor = ComplianceMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
