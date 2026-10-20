"""Configure/build the portable core and genuine NS-3 executable."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from patch_ns3 import apply as patch_ns3

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"


def simulation_hashes():
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "src").rglob("*")) if path.is_file()}


def load_runtime():
    path = ROOT / "build/runtime.json"
    if not path.exists():
        raise SystemExit("Build first: routemind.cmd build")
    runtime = json.loads(path.read_text())
    if runtime.get("simulation_source_sha256") != simulation_hashes():
        raise SystemExit("Simulation source differs from the build manifest; run routemind.cmd build")
    if hashlib.sha256(Path(runtime["executable"]).read_bytes()).hexdigest() != runtime.get("executable_sha256"):
        raise SystemExit("Executable differs from the build manifest; rebuild before running")
    return runtime


def environment():
    env = os.environ.copy()
    paths = [str(Path(sys.executable).parent)]
    if os.name == "nt":
        paths += [str(TOOLS / "native/mingw64/bin"),
                  str(TOOLS / "python-packages/cmake/data/bin"),
                  str(TOOLS / "python-packages/bin")]
    paths += [str(ROOT / "build/ns3-output/lib")]
    env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    env["TEMP"] = env["TMP"] = str(TOOLS / "tmp")
    env["PYTHONPATH"] = str(TOOLS / "python-packages") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def execute(args, env):
    print("+", subprocess.list2cmdline([str(a) for a in args]), flush=True)
    subprocess.run([str(a) for a in args], cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    (TOOLS / "tmp").mkdir(parents=True, exist_ok=True)
    env = environment()
    cmake = shutil.which("cmake", path=env["PATH"])
    ninja = shutil.which("ninja", path=env["PATH"])
    compiler = shutil.which("g++", path=env["PATH"])
    if not all([cmake, ninja, compiler]):
        raise SystemExit("Compiler/CMake/Ninja missing. See README.md setup instructions.")
    common = ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_CXX_COMPILER={compiler}",
              f"-DCMAKE_MAKE_PROGRAM={ninja}"]
    execute([cmake, "-S", ROOT, "-B", ROOT / "build/core", *common], env)
    execute([cmake, "--build", ROOT / "build/core", "--parallel", args.jobs], env)
    ctest = str(Path(cmake).with_name("ctest.exe" if os.name == "nt" else "ctest"))
    execute([ctest, "--test-dir", ROOT / "build/core", "--output-on-failure"], env)
    if args.core_only:
        return
    ns3 = TOOLS / "ns-3.46.1"
    if not (ns3 / "CMakeLists.txt").exists():
        raise SystemExit("NS-3 sources missing. Run scripts/bootstrap.py.")
    patch_ns3(ns3)
    extension = ns3 / "scratch/routemind"
    extension.mkdir(parents=True, exist_ok=True)
    extension.joinpath("CMakeLists.txt").write_text(
        'build_exec(\n  EXECNAME routemind\n'
        f'  SOURCE_FILES "{(ROOT / "src/ns3/routemind.cc").as_posix()}"\n'
        '  LIBRARIES_TO_LINK ${libcore} ${libnetwork} ${libinternet} ${libpoint-to-point} ${libapplications} ${libflow-monitor}\n'
        '  EXECUTABLE_DIRECTORY_PATH ${CMAKE_OUTPUT_DIRECTORY}/scratch/\n)\n', encoding="utf-8")
    execute([cmake, "-S", ns3, "-B", ROOT / "build/ns3", *common,
             "-DNS3_ENABLED_MODULES=core;network;internet;point-to-point;applications;flow-monitor",
             "-DNS3_EXAMPLES=OFF", "-DNS3_TESTS=OFF", "-DNS3_WARNINGS_AS_ERRORS=OFF",
             "-DNS3_GSL=OFF", "-DNS3_GTK3=OFF", "-DNS3_SQLITE=OFF", "-DNS3_EIGEN=OFF",
             "-DNS3_PYTHON_BINDINGS=OFF", "-DNS3_VISUALIZER=OFF", "-DNS3_PRECOMPILE_HEADERS=OFF",
             "-DNS3_CCACHE=OFF", "-DNS3_FAST_LINKERS=OFF", "-DNS3_ASSERT=ON",
             f"-DNS3_OUTPUT_DIRECTORY={(ROOT / 'build/ns3-output').as_posix()}"], env)
    execute([cmake, "--build", ROOT / "build/ns3", "--target", "scratch_routemind_routemind", "--parallel", args.jobs], env)
    matches = [p for p in (ROOT / "build/ns3-output/scratch").glob("ns3*routemind*")
               if p.is_file() and (p.suffix == ".exe" if os.name == "nt" else os.access(p, os.X_OK))]
    if len(matches) != 1:
        raise SystemExit(f"Expected one executable, found {matches}")
    compiler_version = subprocess.check_output([compiler, "--version"], env=env, text=True).splitlines()[0]
    manifest = {"executable": str(matches[0]), "ns3_version": "3.46.1",
                "compiler": compiler, "compiler_version": compiler_version,
                "python": sys.executable, "platform": sys.platform}
    manifest["simulation_source_sha256"] = simulation_hashes()
    manifest["executable_sha256"] = hashlib.sha256(matches[0].read_bytes()).hexdigest()
    patch = ROOT / "docs/ns3-mingw-time.patch"
    if os.name == "nt" and patch.exists():
        manifest["ns3_patch_sha256"] = hashlib.sha256(patch.read_bytes()).hexdigest()
    (ROOT / "build/runtime.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Built", matches[0])


if __name__ == "__main__":
    main()
