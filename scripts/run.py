"""Run one NS-3 experiment with the native library search path configured."""
import subprocess
import sys
from build import ROOT, environment, load_runtime


def main():
    executable = load_runtime()["executable"]
    raise SystemExit(subprocess.call([executable, *sys.argv[1:]], cwd=ROOT, env=environment()))


if __name__ == "__main__":
    main()
