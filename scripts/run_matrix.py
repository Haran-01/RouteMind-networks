"""Run matched experiments, preserving workload settings and source hashes."""
import argparse
import concurrent.futures
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
from build import ROOT, environment, load_runtime


def source_hashes():
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for folder in ["src", "scripts", "analysis", "experiments", "tests", "docs", "web"]
              for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    for relative in ["CMakeLists.txt", "README.md", "routemind.cmd", "AGENTS.md", ".gitignore"]:
        path = ROOT / relative
        if path.exists():
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def verify_run(target):
    result = subprocess.run([sys.executable, str(ROOT / "tests/verify_results.py"), str(target)],
                            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (target / "verification.log").write_text(result.stdout)
    if result.returncode:
        print(result.stdout, flush=True)
    return result.returncode


def execute_case(runtime, config, output, case):
    scenario, run, mode = case
    target = output / f"{scenario}-run{run}-{mode}"
    target.mkdir()
    command = [runtime["executable"], f"--mode={mode}", f"--scenario={scenario}",
               f"--seed={config['seed']}", f"--run={run}", f"--output={target}"]
    command += [f"--{key}={value}" for key, value in config.get("parameters", {}).items()]
    result = subprocess.run(command, cwd=ROOT, env=environment(), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (target / "console.log").write_text(result.stdout)
    return target.name, result.stdout.strip(), result.returncode or verify_run(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/smoke.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/smoke")
    parser.add_argument("--jobs", type=int, default=1, help="Independent simulator processes (default: 1)")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    config = json.loads(args.config.read_text())
    output = args.output.resolve()
    if (output / "manifest.json").exists():
        raise SystemExit("Output already contains a matrix; choose a new directory to preserve its evidence")
    output.mkdir(parents=True, exist_ok=True)
    runtime = load_runtime()
    manifest = {"config": config, "runtime": runtime, "source_sha256": source_hashes(),
                "executable_sha256": hashlib.sha256(Path(runtime["executable"]).read_bytes()).hexdigest(),
                "workers": args.jobs, "status": "running", "completed": []}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    cases = list(itertools.product(config["scenarios"], config["runs"], config["modes"]))
    names = [f"{scenario}-run{run}-{mode}" for scenario, run, mode in cases]
    if not cases or len(set(names)) != len(names):
        raise SystemExit("Matrix must contain unique, nonempty scenario/run/mode cases")
    failure = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(execute_case, runtime, config, output, case) for case in cases]
        for future in concurrent.futures.as_completed(futures):
            if future.cancelled():
                continue
            name, console, returncode = future.result()
            print(f"{name}: {console}", flush=True)
            if returncode:
                failure = failure or returncode
                manifest["status"] = "failed"
                manifest.setdefault("failed_runs", []).append(name)
                for pending in futures:
                    pending.cancel()
            else:
                manifest["completed"].append(name)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if failure:
        raise SystemExit(failure)
    if load_runtime() != runtime:
        manifest.update(status="failed", failed_stage="build-changed")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        raise SystemExit("Build changed during matrix execution")
    manifest["status"] = "complete"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        subprocess.run([sys.executable, str(ROOT / "analysis/report.py"), str(output)], check=True)
    except subprocess.CalledProcessError:
        manifest.update(status="failed", failed_stage="report")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
