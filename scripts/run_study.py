"""Run declared variants sequentially, with matched NS-3 matrices inside each variant."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from build import ROOT, load_runtime
from run_matrix import source_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    variants = config["variants"]
    identifiers = [variant["id"] for variant in variants]
    if not variants or len(set(identifiers)) != len(identifiers) or any(
            not identifier or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in identifier)
            for identifier in identifiers):
        raise SystemExit("Variant ids must be unique lowercase names")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / "manifest.json"
    if path.exists():
        raise SystemExit("Study already exists; choose a fresh output directory")
    runtime = load_runtime()
    manifest = {"kind": "study", "config": config, "runtime": runtime,
                "source_sha256": source_hashes(), "status": "running", "completed": []}
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    for variant in variants:
        matrix = {key: config[key] for key in ["seed", "runs", "scenarios"]}
        matrix["modes"] = variant.get("modes", [variant.get("mode", "class-aware")])
        matrix["parameters"] = {**config.get("parameters", {}), **variant.get("parameters", {})}
        matrix_path = output / f"{variant['id']}-config.json"
        matrix_path.write_text(json.dumps(matrix, indent=2) + "\n")
        print("Variant:", variant["id"], flush=True)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/run_matrix.py"),
                                 "--config", str(matrix_path), "--output", str(output / variant["id"]),
                                 "--jobs", str(args.jobs)], cwd=ROOT)
        if result.returncode:
            manifest.update(status="failed", failed_variant=variant["id"])
            path.write_text(json.dumps(manifest, indent=2) + "\n")
            raise SystemExit(result.returncode)
        manifest["completed"].append(variant["id"])
        path.write_text(json.dumps(manifest, indent=2) + "\n")
    if load_runtime() != runtime:
        manifest.update(status="failed", failed_stage="build-changed")
        path.write_text(json.dumps(manifest, indent=2) + "\n")
        raise SystemExit("Build changed during study")
    manifest["status"] = "complete"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    result = subprocess.run([sys.executable, str(ROOT / "analysis/study_report.py"), str(output)], cwd=ROOT)
    if result.returncode:
        manifest.update(status="failed", failed_stage="study-report")
        path.write_text(json.dumps(manifest, indent=2) + "\n")
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
