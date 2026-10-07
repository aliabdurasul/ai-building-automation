"""S7 run-vs-run semantic comparison: the S2 comparator over the S7 stage and stores.

Trace timing (sample times, run timelines, measured durations, sample counts, raw observed value runs that may or
may not contain one-cycle states) is volatile and dropped; the filtered state sequences, the duration tolerance
verdicts and every Modbus / PLC value stay compared.
Usage: python compare_s7.py [runA runB]   (default run1 run2)
Output: docs/phase0/S7_comparison_<a>_<b>.json
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "s2", "harness")))
import compare_s2  # noqa: E402

compare_s2.configure("S7", r"C:\AI_BMS_PHASE0\s7\{run}", ("pump", "combined", "ahu_s1", "ahu_seq"),
                     ("t_ms", "measured_ms", "timeline", "samples", "observed_runs"))

if __name__ == "__main__":
    sys.exit(compare_s2.main())
