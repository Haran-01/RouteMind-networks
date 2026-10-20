"""Run a faculty showcase using existing verified NS-3 experiment runners."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from build import ROOT, load_runtime
from run_matrix import source_hashes


MODES = ["static", "adaptive", "stable", "class-aware"]
PARAMETERS = {"duration": 26, "interval": .25, "alpha": .3,
              "dwell": 1.5, "threshold": .12, "loop-safe": 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / datetime.now().strftime("faculty-demo-%Y%m%d-%H%M%S"))
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Choose a fresh output directory; previous evidence is preserved")
    output.mkdir(parents=True, exist_ok=True)
    runtime = load_runtime()
    index = {"kind": "faculty-demo", "runtime": runtime, "source_sha256": source_hashes(),
             "status": "running", "completed": []}

    def save():
        (output / "demo-index.json").write_text(json.dumps(index, indent=2) + "\n")

    def execute(name, script, *arguments):
        print(f"\n=== {name} ===", flush=True)
        result = subprocess.run([sys.executable, str(ROOT / script), *map(str, arguments)], cwd=ROOT)
        if result.returncode:
            index.update(status="failed", failed_stage=name)
            save()
            raise SystemExit(result.returncode)
        index["completed"].append(name)
        save()

    def experiment(name, config, study=False):
        path = output / f"{name}-config.json"
        path.write_text(json.dumps(config, indent=2) + "\n")
        execute(name, "scripts/run_study.py" if study else "scripts/run_matrix.py",
                "--config", path, "--output", output / name, "--jobs", args.jobs)

    save()
    base = {"seed": 42, "runs": [1], "parameters": PARAMETERS}
    experiment("policies", {**base, "modes": MODES, "scenarios": [
        "steady", "congestion", "burst", "failure", "combined", "active-failure",
        "disconnected", "missing-route"]})
    experiment("controls", {**base, "scenarios": ["congestion"], "reference": "default",
        "description": "Matched mechanism demonstrations, one trial each; no general optimality claim.",
        "variants": [{"id": "default", "mode": "class-aware"},
                     {"id": "no-smoothing", "parameters": {"alpha": 1}},
                     {"id": "no-hysteresis", "parameters": {"threshold": 0}},
                     {"id": "no-dwell", "parameters": {"dwell": 0}},
                     {"id": "shared-objective", "mode": "stable"}]}, study=True)
    experiment("objectives", {**base, "scenarios": ["congestion"],
        "reference": "balanced",
        "description": "Shared stable-mode cost profiles under identical offered traffic; one trial each.",
        "variants": [{"id": policy, "mode": "stable", "parameters": {"policy": policy}}
                     for policy in ["shortest", "latency", "congestion", "reliability", "balanced"]]}, study=True)
    experiment("extended", {**base, "parameters": {**PARAMETERS, "topology": "extended"},
                            "modes": MODES, "scenarios": ["congestion"]})
    execute("rank-boundary", "scripts/run_study.py", "--config", ROOT / "experiments/rank-boundary.json",
            "--output", output / "rank-boundary", "--jobs", args.jobs)
    execute("calibration", "scripts/calibrate.py", "--output", output / "calibration")
    experiment("packet-capture", {**base, "parameters": {**PARAMETERS, "pcap": 1},
                                  "modes": ["class-aware"], "scenarios": ["active-failure"]})
    if load_runtime() != runtime:
        index.update(status="failed", failed_stage="build-changed")
        save()
        raise SystemExit("Build changed during demonstration")
    cases = sorted(output.glob("**/summary.json"))
    if len(cases) != 55 or any("PASS " not in (case.parent / "verification.log").read_text() for case in cases):
        index.update(status="failed", failed_stage="coverage")
        save()
        raise SystemExit("Expected 55 verified native cases")
    captures = sorted(output.glob("**/*.pcap"))
    populated = [path for path in captures if path.stat().st_size > 24]
    # EnablePcapAll also creates header-only files on interfaces with no packets.
    if not populated or any(path.stat().st_size < 24 for path in captures):
        index.update(status="failed", failed_stage="packet-capture")
        save()
        raise SystemExit("Missing/non-populated packet captures")
    lines = ["# RouteMind faculty demonstration", "",
             "55 actual NS-3 runs passed artifact verification. Seed/run pairs are matched within each comparison.",
             "One trial per setting: these are demonstrations, not estimates of general performance.", "",
             "| Section | Scenario / variant | Mode | UDP p95 ms | Delivery % | TCP Mbps | Changes | Repair ms |",
             "|---|---|---|---:|---:|---:|---:|---:|"]
    for path in cases:
        run = json.loads(path.read_text())
        parts = path.relative_to(output).parts
        label = run["scenario"] if len(parts) == 3 else f"{parts[1]} / {run['scenario']}"
        repair = run["realtime_route_repair_delay_ms"]
        lines.append(f"| {parts[0]} | {label} | {run['mode']} | {run['realtime_p95_delay_ms']:.3f} | "
                     f"{100*run['realtime_pdr']:.2f} | {run['bulk_payload_goodput_mbps']:.3f} | "
                     f"{run['route_changes']} | {repair if repair is not None else '-'} |")
    lines += ["", "## Presentation order", "",
              "1. Compare the four burst rows: latency, delivered packets, TCP goodput and route churn.",
              "2. Compare congestion rows: adaptive routing can have lower delay while class-aware routing improves throughput/stability.",
              "3. Active-failure: link fails at 14.07 s, observation/repair at 14.25 s; restoration is at 20.11 s.",
              "4. Disconnected: no physical repair exists; source-rejected offers remain in the delivery denominator.",
              "5. Missing-route: inspect probes.csv and routing-errors.csv for source and transit failures.",
              "6. Controls/objectives: show the cost and stability trade-offs; class-aware uses separate latency/congestion profiles.",
              "7. Extended and rank-boundary: show portability and the fixed-rank detour restriction together.",
              "8. Calibration and packet captures: demonstrate measured link utilization and real TCP/UDP packets.", "",
              "## Evidence", "",
              "- [Matched policy comparison](policies/REPORT.md)",
              "- [Mechanism comparison](controls/REPORT.md)",
              "- [Cost profiles](objectives/REPORT.md)",
              "- [Extended topology](extended/REPORT.md)",
              "- [Rank constraint limitation](rank-boundary/REPORT.md)",
              "- [Telemetry calibration](calibration/CALIBRATION.md)",
              f"- {len(populated)} populated PCAP files out of {len(captures)} in packet-capture/active-failure-run1-class-aware (idle interfaces have header-only captures).",
              "- Each case retains summary.json, topology.json, CSV traces, FlowMonitor and verification.log.",
              "- Each matrix/study retains source hashes, runtime hashes and exact inputs.", "",
              "The native backend is an NS-3 simulation with centralized direct telemetry and synchronous table installs.",
              "It does not model control traffic, controller CPU or installation latency and offers no reserved QoS guarantee.",
              "Rank-disabled cases are diagnostics, not a generally safe routing configuration.", ""]
    (output / "DEMO.md").write_text("\n".join(lines), encoding="utf-8")
    index.update(status="complete", verified_cases=len(cases), pcap_files=len(captures), populated_pcap_files=len(populated))
    save()
    print(f"\nPASS: {len(cases)} verified NS-3 cases, {len(populated)}/{len(captures)} captures contain packets.\nReport: {output / 'DEMO.md'}")


if __name__ == "__main__":
    main()
