"""Run low-load and saturated NS-3 telemetry checks at aligned/unaligned intervals."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess

from build import ROOT, environment, load_runtime
from run_matrix import source_hashes, verify_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/calibration")
    args = parser.parse_args()
    output = args.output.resolve()
    if (output / "manifest.json").exists():
        raise SystemExit("Calibration output already exists; choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    runtime = load_runtime()
    cases = [{"name": f"{name}-interval{interval}", "rate": rate, "interval": interval}
             for name, rate in [("low", .256), ("saturated", 8)] for interval in [.25, .37]]
    manifest = {"kind": "calibration", "config": {"cases": cases}, "runtime": runtime,
                "source_sha256": source_hashes(), "status": "running", "completed": [],
                "executable_sha256": hashlib.sha256(Path(runtime["executable"]).read_bytes()).hexdigest()}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    lines = ["# NS-3 telemetry calibration", "", "UDP only, static fast corridor, 320-byte application packets.",
             "Wire frames are 350 bytes (UDP + IPv4 + PPP included).", "",
             "| Case | Offered application Mbps | Sample interval s | Mean 1->2 utilization | Mean queue bytes |",
             "|---|---:|---:|---:|---:|"]
    for case in cases:
        target = output / case["name"]
        target.mkdir()
        command = [runtime["executable"], "--scenario=calibration", "--mode=static",
                   f"--calibration-rate-mbps={case['rate']}", f"--interval={case['interval']}",
                   f"--output={target}"]
        result = subprocess.run(command, cwd=ROOT, env=environment(), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (target / "console.log").write_text(result.stdout)
        print(result.stdout.strip(), flush=True)
        returncode = result.returncode or verify_run(target)
        if returncode:
            manifest.update(status="failed", failed_run=case["name"])
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            raise SystemExit(returncode)
        with (target / "telemetry.csv").open(newline="") as stream:
            steady = [row for row in csv.DictReader(stream) if row["from"] == "1" and row["to"] == "2"
                      and 3 <= float(row["time"]) <= 20]
        utilization = sum(float(row["utilization"]) for row in steady) / len(steady)
        queue = sum(float(row["mean_queue_bytes"]) for row in steady) / len(steady)
        lines.append(f"| {case['name']} | {case['rate']} | {case['interval']} | {utilization:.8f} | {queue:.3f} |")
        manifest["completed"].append(case["name"])
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    lines += ["", "Low-load expected utilization: 0.256 * 350/320 / 6 = 0.04666667; saturated: 1.",
              "Each interval permits one whole wire packet of boundary counting error.",
              "The verifier independently reconstructs every sampled link's byte count and queue integral",
              "from raw event journals, checks analytic rates, packet accounting, and queue drain.",
              "This calibrates the configured point-to-point setup, not arbitrary device models.", ""]
    (output / "CALIBRATION.md").write_text("\n".join(lines))
    manifest["status"] = "complete"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("Calibration report:", output / "CALIBRATION.md")


if __name__ == "__main__":
    main()
