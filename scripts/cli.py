"""Small command dispatcher used by the Windows project launcher."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {"setup": "scripts/bootstrap.py", "build": "scripts/build.py",
            "run": "scripts/run.py", "compare": "scripts/run_matrix.py",
            "verify": "tests/verify_results.py", "report": "analysis/report.py", "calibrate": "scripts/calibrate.py",
            "study": "scripts/run_study.py", "plots": "analysis/plot_studies.py",
            "demo": "scripts/faculty_demo.py", "gui": "scripts/gui.py"}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ["help", "--help", "-h"]:
        print("RouteMind: setup | build | run | compare | study | calibrate | verify | report | plots | demo | gui | test")
        print("Examples:\n  routemind.cmd build\n  routemind.cmd run --mode=class-aware --output=results/demo")
        return
    command, arguments = sys.argv[1], sys.argv[2:]
    if command == "test":
        subprocess.run([sys.executable, str(ROOT / COMMANDS["build"]), "--core-only"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], cwd=ROOT, check=True)
        return
    if command not in COMMANDS:
        raise SystemExit("Unknown command: " + command)
    raise SystemExit(subprocess.call([sys.executable, str(ROOT / COMMANDS[command]), *arguments], cwd=ROOT))


if __name__ == "__main__":
    main()
