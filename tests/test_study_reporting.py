"""Independent paired-effect arithmetic and workload-mismatch regression."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class StudyReportingTests(unittest.TestCase):
    def test_paired_variant_effect_and_rejection_of_changed_workload(self):
        project = Path(__file__).resolve().parents[1]
        temporary_root = project / "build/test-tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
            root = Path(temporary)
            config = {"description": "Analysis-only fixture; not simulated packet evidence",
                      "scenarios": ["congestion"], "reference": "base", "variants": [{"id": "base"}, {"id": "changed"}]}
            (root / "manifest.json").write_text(json.dumps({"status": "complete", "config": config,
                                                           "completed": ["base", "changed"]}))
            for name, delays in [("base", [10, 20]), ("changed", [12, 24])]:
                child = root / name
                child.mkdir()
                completed = []
                for index, delay in enumerate(delays, 1):
                    case = f"congestion-run{index}-class-aware"
                    completed.append(case)
                    target = child / case
                    target.mkdir()
                    (target / "verification.log").write_text("PASS analysis-fixture\n")
                    summary = {"mode": "class-aware", "scenario": "congestion", "seed": 77, "run": index,
                               "alpha": .3 if name == "base" else 1, "background_rate_mbps": 9,
                               "realtime_p95_delay_ms": delay, "realtime_pdr": .99,
                               "bulk_payload_goodput_mbps": 5, "route_changes": 20}
                    (target / "summary.json").write_text(json.dumps(summary))
                (child / "manifest.json").write_text(json.dumps({"status": "complete", "completed": completed,
                    "config": {"modes": ["class-aware"], "parameters": {"alpha": .3 if name == "base" else 1}}}))
            command = [sys.executable, str(project / "analysis/study_report.py"), str(root)]
            subprocess.run(command, check=True, capture_output=True)
            with (root / "paired-differences.csv").open(newline="") as stream:
                result = next(row for row in csv.DictReader(stream) if row["metric"] == "realtime_p95_delay_ms")
            self.assertAlmostEqual(float(result["mean_difference"]), 3)
            self.assertAlmostEqual(float(result["ci95_low"]), -9.706)
            self.assertAlmostEqual(float(result["ci95_high"]), 15.706)
            changed = root / "changed/congestion-run1-class-aware/summary.json"
            summary = json.loads(changed.read_text())
            summary["background_rate_mbps"] = 10
            changed.write_text(json.dumps(summary))
            rejected = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("paired study workload mismatch", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
