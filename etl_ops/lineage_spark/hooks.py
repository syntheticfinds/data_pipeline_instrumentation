"""
Allows automatic triggering of compliance analysis after pipeline completion.
"""

import os
import subprocess


def auto_trigger_compliance_analysis():
    """
    Hook that triggers compliance analysis after pipeline completion

    This is registered by default and runs automatically after each pipeline.
    """
    compliance_monitor_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "compliance_monitor.py"
    )

    if not os.path.exists(compliance_monitor_path):
        # Silently skip if compliance_monitor.py is not available
        return

    print("\n" + "="*80)
    print("PIPELINE COMPLETE - TRIGGERING COMPLIANCE ANALYSIS")
    print("="*80)

    try:
        # Run compliance monitor in "run once" mode
        result = subprocess.run(
            ["python", compliance_monitor_path, "run"],
            capture_output=False,
            text=True
        )

        if result.returncode != 0:
            print(f"⚠️  Compliance analysis trigger failed with code {result.returncode}")

    except Exception as e:
        print(f"⚠️  Failed to trigger compliance analysis: {e}")
