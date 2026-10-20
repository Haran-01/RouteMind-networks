"""Small independent contracts for the statistical summaries."""
import importlib.util
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("report", Path(__file__).resolve().parents[1] / "analysis/report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class ReportingTests(unittest.TestCase):
    def test_single_run_does_not_invent_uncertainty(self):
        self.assertEqual(report.interval([7]), (7, None, None))

    def test_two_trials_use_student_t_not_normal_critical_value(self):
        mean, low, high = report.interval([1,3])
        self.assertAlmostEqual(mean, 2)
        self.assertAlmostEqual(low, -10.706)
        self.assertAlmostEqual(high, 14.706)

    def test_constant_samples_have_zero_spread(self):
        self.assertEqual(report.interval([5,5,5]), (5,5,5))

    def test_interval_is_centered_on_sample_mean(self):
        mean, low, high = report.interval([1,2,7])
        self.assertAlmostEqual(mean, 10/3)
        self.assertAlmostEqual(mean-low, high-mean)

    def test_reports_only_assign_intervals_to_varied_workloads(self):
        # Exercise both CSV output paths, including the previously inconsistent paired one.
        temporary_root = Path(__file__).resolve().parents[1] / "build/test-tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
            root = Path(temporary)
            names = []
            for scenario in ["steady", "failure", "congestion"]:
                for index in [1, 2]:
                    for mode in ["adaptive", "stable"]:
                        name = f"{scenario}-run{index}-{mode}"
                        names.append(name)
                        target = root / name
                        target.mkdir()
                        summary = {"scenario": scenario, "run": index, "seed": 42, "mode": mode,
                                   "background_start_s": 6.1 + index / 10, "background_rate_mbps": 9}
                        summary.update({key: index * (1 if mode == "adaptive" else 2)
                                        for key in report.METRICS})
                        (target / "summary.json").write_text(json.dumps(summary))
                        (target / "forwarding.csv").write_text("class,packet_uid,node\n1,1,1\n")
            (root / "manifest.json").write_text(json.dumps({"status": "complete", "completed": names,
                "config": {"scenarios": ["steady", "failure", "congestion"],
                           "modes": ["adaptive", "stable"]}}))
            subprocess.run([sys.executable, report.__file__, str(root)], check=True, capture_output=True)
            for filename in ["comparison.csv", "paired-differences.csv"]:
                with (root / filename).open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertTrue(rows)
                for row in rows:
                    for bound in ["ci95_low", "ci95_high"]:
                        self.assertEqual(row[bound] == "", row["scenario"] in {"steady", "failure"})
            target = root / "congestion-run1-stable/summary.json"
            summary = json.loads(target.read_text())
            summary["duration_s"] = 27
            target.write_text(json.dumps(summary))
            rejected = subprocess.run([sys.executable, report.__file__, str(root)], capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Paired configuration mismatch", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
