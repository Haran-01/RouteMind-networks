"""Create descriptive and paired statistical summaries from measured NS-3 runs."""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics

METRICS = ["realtime_p95_delay_ms", "realtime_pdr", "bulk_payload_goodput_mbps", "route_changes", "realtime_router_revisits"]
# Two-sided Student t 97.5% critical values; n-1 degrees of freedom.
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
        7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
        13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
        19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
        25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}


def interval(values):
    mean = statistics.mean(values)
    if len(values) < 2:
        return mean, None, None
    df = len(values)-1
    # Conservative df=30 critical value for larger samples.
    half = T975[min(df, 30)] * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean-half, mean+half


def scenario_interval(values, scenario):
    mean, low, high = interval(values)
    # These scenarios use deterministic traffic; changing RNG run alone is not replication.
    return (mean, None, None) if scenario in {"steady", "failure", "calibration", "active-failure", "disconnected", "missing-route"} else (mean, low, high)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.directory / "manifest.json").read_text())
    if manifest["status"] != "complete":
        raise SystemExit("Matrix is incomplete; a comparison report would be misleading")
    runs = [json.loads((args.directory / name / "summary.json").read_text())
            for name in manifest["completed"]]
    groups = {}
    indexed = {}
    for run in runs:
        run_name = f"{run['scenario']}-run{run['run']}-{run['mode']}"
        seen = set()
        revisits = 0
        with (args.directory / run_name / "forwarding.csv").open(newline="") as stream:
            for event in csv.DictReader(stream):
                if event["class"] == "1":
                    key = (event["packet_uid"],event["node"])
                    revisits += key in seen
                    seen.add(key)
        run["realtime_router_revisits"] = revisits
        groups.setdefault((run["scenario"], run["mode"]), []).append(run)
        key = (run["scenario"], run["seed"], run["run"], run["mode"])
        if key in indexed:
            raise SystemExit("Duplicate run key")
        indexed[key] = run
    rows = []
    lines = ["# RouteMind measured NS-3 results", "",
             "These are packet-level simulation results, not guarantees for deployed networks.", "",
             "| Scenario | Mode | Runs | UDP p95 delay (ms) | UDP delivery | TCP payload goodput (Mbps) | Route changes | UDP router revisits |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for (scenario, mode), group in sorted(groups.items()):
        means = {}
        for metric in METRICS:
            mean, low, high = scenario_interval([r[metric] for r in group], scenario)
            means[metric] = mean
            rows.append({"scenario": scenario, "mode": mode, "metric": metric,
                         "n": len(group), "mean": mean, "ci95_low": low, "ci95_high": high})
        lines.append(f"| {scenario} | {mode} | {len(group)} | {means[METRICS[0]]:.3f} | "
                     f"{means[METRICS[1]]:.2%} | {means[METRICS[2]]:.3f} | {means[METRICS[3]]:.1f} | {means[METRICS[4]]:.1f} |")
    with (args.directory / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    paired = []
    for scenario in manifest["config"]["scenarios"]:
        for mode in manifest["config"]["modes"]:
            if mode == "adaptive":
                continue
            pairs = []
            for run in runs:
                if run["scenario"] != scenario or run["mode"] != mode:
                    continue
                reference = indexed.get((scenario, run["seed"], run["run"], "adaptive"))
                if reference:
                    common = ["duration_s", "interval_s", "alpha", "dwell_s", "threshold", "loop_safe", "policy",
                              "realtime_application_rate_mbps", "realtime_offered_packets", "udp_generator",
                              "failure_time_s", "link_restoration_time_s", "tcp_workload", "failure_from", "failure_to", "topology"]
                    if any(run.get(key) != reference.get(key) for key in common):
                        raise SystemExit("Paired configuration mismatch")
                    if (run["background_start_s"],run["background_rate_mbps"]) != (
                            reference["background_start_s"], reference["background_rate_mbps"]):
                        raise SystemExit("Paired workload mismatch")
                    pairs.append((run,reference))
            if not pairs:
                continue
            for metric in METRICS:
                mean, low, high = scenario_interval([a[metric]-b[metric] for a,b in pairs], scenario)
                paired.append({"scenario":scenario,"mode":mode,"reference":"adaptive","metric":metric,
                               "n":len(pairs),"mean_difference":mean,"ci95_low":low,"ci95_high":high})
    if paired:
        with (args.directory / "paired-differences.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(paired[0]))
            writer.writeheader(); writer.writerows(paired)
    recovery_rows = []
    recovery_lines = []
    for (scenario, mode), group in sorted(groups.items()):
        eligible = [run for run in group if run.get("failure_observed_time_s") is not None]
        if not eligible:
            continue
        if not recovery_lines:
            recovery_lines = ["", "## Failure observation and realtime recovery", "",
                "| Scenario | Mode | Affected / total runs | Detection (ms) | Route repair (ms, affected) | Packet recovery (ms, affected) |",
                "|---|---|---:|---:|---:|---:|"]
        affected = sum(bool(run["realtime_path_affected_by_failure"]) for run in eligible)
        formatted = []
        for metric in ["failure_detection_delay_ms", "realtime_route_repair_delay_ms", "realtime_recovery_delay_ms"]:
            values = [run[metric] for run in eligible if run[metric] is not None]
            mean, low, high = scenario_interval(values, scenario) if values else (None, None, None)
            formatted.append(f"{mean:.3f}" if mean is not None else "—")
            recovery_rows.append({"scenario": scenario, "mode": mode, "metric": metric,
                                  "n": len(values), "total_runs": len(eligible), "affected_runs": affected,
                                  "mean": mean, "ci95_low": low, "ci95_high": high})
        recovery_lines.append(f"| {scenario} | {mode} | {affected}/{len(eligible)} | " + " | ".join(formatted) + " |")
    if recovery_rows:
        with (args.directory / "recovery-summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(recovery_rows[0]))
            writer.writeheader(); writer.writerows(recovery_rows)
        recovery_lines += ["", "All times are measured from link-down. Packet recovery uses the first received realtime packet",
            "transmitted at or after route readiness and received before restoration. Pre-repair packets are excluded.",
            "Repair/recovery means condition on affected paths and successful repair during the outage; n is in recovery-summary.csv.",
            "An unaffected path or an unrepaired static path has no repair/recovery latency (—), not zero.",
            "Conditioned groups can differ between modes; these recovery means are descriptive, not paired effects.",
            "The legacy recovery_time_s field denotes scheduled link restoration, not measured packet recovery."]
        lines += recovery_lines
    lines += ["", "## Interpretation and limits", "",
              "- The p95 column is the mean of each run's p95, not a pooled-packet percentile.",
              "- TCP goodput is sink payload bytes over [1s, simulation end], including the drain window.",
              "- Route changes count controlled source-to-receiver path changes for realtime and bulk; initial installation is excluded.",
              "- A single run has no confidence interval. CSV intervals use Student t and require independent workload realizations.",
              "- Steady and failure workloads have no stochastic traffic variation; repeated run indices there do not establish independent uncertainty.",
              "- Paired differences are mode minus adaptive for the same scenario, seed and run. Lower delay/churn and higher delivery/goodput are favorable.",
              "- Missing telemetry/control-message costs, atomic controller updates and a single fabric limit generalization.",
              "- Static intentionally has no failure recovery. Use adaptive versus stable to isolate stability effects.",
              "- Class-aware changes both traffic objectives and stability relative to adaptive; compare stable versus class-aware to study class separation.",
              "- The 40ms delay threshold is an experimental target, not a standard or QoS guarantee.",
              "- A policy may improve one metric and worsen another. No universal improvement is assumed.", ""]
    lines += ["- Default controlled routes strictly decrease a fixed destination hop rank, preventing transient revisits during updates.",
              "- Disable loop-safe for an unconstrained-routing ablation; it may exhibit real transient revisits even when every individual tree is acyclic.",
              "- The rank restriction can exclude useful detours in other topologies; these results apply to the configured fabric and candidate-path space.", ""]
    (args.directory / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("Report:", args.directory / "REPORT.md")


if __name__ == "__main__":
    main()
