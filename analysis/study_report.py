"""Descriptive and paired variant effects from verified native experiment matrices."""
import argparse
import csv
import json
from pathlib import Path

from report import scenario_interval

METRICS = ["realtime_p95_delay_ms", "realtime_pdr", "bulk_payload_goodput_mbps", "route_changes"]
WORKLOAD = ["seed", "run", "scenario", "duration_s", "interval_s", "background_start_s", "background_rate_mbps",
            "realtime_application_rate_mbps", "realtime_offered_packets", "tcp_workload", "udp_generator", "topology", "loop_safe",
            "failure_time_s", "link_restoration_time_s", "failure_from", "failure_to"]


def write_csv(path, rows):
    if rows:
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    manifest = json.loads((root / "manifest.json").read_text())
    config = manifest["config"]
    assert manifest["status"] == "complete" and set(manifest["completed"]) == {v["id"] for v in config["variants"]}
    indexed = {}
    parameters = []
    for variant in config["variants"]:
        name = variant["id"]
        matrix = json.loads((root / name / "manifest.json").read_text())
        assert matrix["status"] == "complete"
        settings = matrix["config"]["parameters"]
        parameters.append({"variant": name, "modes": ",".join(matrix["config"]["modes"]), **settings})
        trials = {}
        for case in matrix["completed"]:
            assert "PASS " in (root / name / case / "verification.log").read_text()
            run = json.loads((root / name / case / "summary.json").read_text())
            key = run["scenario"], run["seed"], run["run"], run["mode"]
            assert key not in trials
            trials[key] = run
        indexed[name] = trials
    descriptive, paired = [], []
    lines = ["# RouteMind declared-variant study", "", config["description"], "",
             "Every case uses the NS-3 packet backend and passed artifact verification.", "",
             "| Variant | Scenario | Mode | n | UDP p95 ms | UDP delivery | TCP Mbps | Changes |",
             "|---|---|---|---:|---:|---:|---:|---:|"]
    for variant in config["variants"]:
        name = variant["id"]
        trials = indexed[name]
        for scenario in config["scenarios"]:
            modes = sorted({key[3] for key in trials})
            for mode in modes:
                group = [run for key, run in trials.items() if key[0] == scenario and key[3] == mode]
                means = []
                for metric in METRICS:
                    mean, low, high = scenario_interval([run[metric] for run in group], scenario)
                    means.append(mean)
                    descriptive.append({"variant": name, "scenario": scenario, "mode": mode, "metric": metric,
                                        "n": len(group), "mean": mean, "ci95_low": low, "ci95_high": high})
                lines.append(f"| {name} | {scenario} | {mode} | {len(group)} | {means[0]:.3f} | {means[1]:.2%} | {means[2]:.3f} | {means[3]:.1f} |")
        reference = variant.get("reference", config.get("reference"))
        if not reference or reference == name:
            continue
        reference_trials = indexed[reference]
        allowed = set(variant.get("allowed_differences", []))
        for scenario in config["scenarios"]:
            differences = {metric: [] for metric in METRICS}
            for key, run in trials.items():
                if key[0] != scenario:
                    continue
                candidates = [other for other_key, other in reference_trials.items() if other_key[:3] == key[:3]]
                assert len(candidates) == 1, "reference must have one mode per matched workload"
                other = candidates[0]
                assert all(run.get(field) == other.get(field) for field in WORKLOAD if field not in allowed), "paired study workload mismatch"
                for metric in METRICS:
                    differences[metric].append(run[metric] - other[metric])
            for metric, values in differences.items():
                mean, low, high = scenario_interval(values, scenario)
                paired.append({"variant": name, "reference": reference, "scenario": scenario, "metric": metric,
                               "n": len(values), "mean_difference": mean, "ci95_low": low, "ci95_high": high})
    # Variant dictionaries can have different explicit overrides; write a common union of columns.
    fields = list(dict.fromkeys(key for row in parameters for key in row))
    write_csv(root / "variants.csv", [{key: row.get(key, "") for key in fields} for row in parameters])
    write_csv(root / "comparison.csv", descriptive)
    write_csv(root / "paired-differences.csv", paired)
    lines += ["", "## Interpretation", "",
              "- Paired effects are variant minus its declared reference for the same seed/run/scenario workload.",
              "- Parameter changes are recorded in variants.csv. Only explicitly declared workload differences are permitted.",
              "- Lower p95/churn and higher delivery/goodput are favorable; there is no single combined objective.",
              "- Intervals use run-level paired Student-t differences; deterministic scenarios have no interval.",
              "- Small samples, the configured topology and correlated cost terms limit generalization.",
              "- Defaults are retained. These studies do not select a post-hoc performance winner.", ""]
    (root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("Study report:", root / "REPORT.md")


if __name__ == "__main__":
    main()
