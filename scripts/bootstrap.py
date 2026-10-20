"""Install project-local build prerequisites and the pinned NS-3 source release."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
NS3_URL = "https://www.nsnam.org/releases/ns-3.46.1.tar.bz2"
NS3_SHA1 = "a02ce48bf2cb46ab8bcc0da10e47bfca1e13cdf3"


def main():
    (TOOLS / "tmp").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEMP"] = env["TMP"] = str(TOOLS / "tmp")
    env["PIP_CACHE_DIR"] = str(TOOLS / "pip-cache")
    if os.name == "nt":
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(TOOLS / "python-packages"),
                        "cmake==3.31.6", "ninja==1.11.1.4", "zstandard>=0.23,<1",
                        "--disable-pip-version-check"], env=env, check=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/bootstrap_compiler.py")], env=env, check=True)
    archive = TOOLS / "ns-3.46.1.tar.bz2"
    if not archive.exists() or hashlib.sha1(archive.read_bytes()).hexdigest() != NS3_SHA1:
        print("Downloading", NS3_URL, flush=True)
        with urllib.request.urlopen(NS3_URL, timeout=180) as response:
            payload = response.read()
        if hashlib.sha1(payload).hexdigest() != NS3_SHA1:
            raise SystemExit("NS-3 archive checksum does not match the pinned release")
        archive.write_bytes(payload)
    destination = TOOLS.resolve()
    if not (TOOLS / "ns-3.46.1/CMakeLists.txt").exists():
        with tarfile.open(archive, "r:bz2") as source:
            for member in source:
                target = (TOOLS / member.name).resolve()
                if not target.is_relative_to(destination):
                    raise SystemExit("Unsafe archive path")
                # Source release documentation aliases do not require symlinks.
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.extractfile(member).read())
    print("Ready. Build with:", sys.executable, "scripts/build.py")


if __name__ == "__main__":
    main()
