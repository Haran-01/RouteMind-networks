"""Fetch native MinGW packages without running a POSIX/MSYS shell.

All packages come from the official MSYS2 repository and are checked against its
repository SHA-256 metadata. No administrator or machine PATH changes are needed.
The metadata is fetched over HTTPS; this is not detached-signature verification.
"""
import concurrent.futures
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
sys.path.insert(0, str(TOOLS / "python-packages"))
REPOSITORY = "https://repo.msys2.org/mingw/mingw64/"


def fetch(url, path):
    if not path.exists():
        with urllib.request.urlopen(url, timeout=120) as response:
            path.write_bytes(response.read())
    return path.read_bytes()


def main():
    packages_dir = TOOLS / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    fetch(REPOSITORY + "mingw64.db", packages_dir / "mingw64.db")
    metadata = packages_dir / "metadata"
    metadata.mkdir(exist_ok=True)
    subprocess.run(["tar.exe", "-xf", str(packages_dir / "mingw64.db"),
                    "-C", str(metadata)], check=True)
    packages = {}
    for entry in metadata.glob("*/desc"):
        fields = {}
        for block in entry.read_text(encoding="utf-8").strip().split("\n\n"):
            lines = block.splitlines()
            fields[lines[0].strip("%")] = lines[1:]
        packages[fields["NAME"][0]] = fields
    selected = {}

    def resolve(name):
        name = name.split(">=")[0].split("<=")[0].split("=")[0].split(">")[0].split("<")[0]
        if name in selected:
            return
        if name not in packages:
            providers = [p for p in packages.values()
                         if any(item.split("=")[0] == name for item in p.get("PROVIDES", []))]
            if not providers:
                raise RuntimeError("Unresolved compiler dependency: " + name)
            name = providers[0]["NAME"][0]
        package = packages[name]
        selected[name] = package
        for dependency in package.get("DEPENDS", []):
            resolve(dependency)

    resolve("mingw-w64-x86_64-gcc")
    lock = ROOT / "docs/toolchain-lock.json"
    manifest = (json.loads(lock.read_text()) if lock.exists() else
                [{"name": p["NAME"][0], "file": p["FILENAME"][0],
                  "sha256": p["SHA256SUM"][0]} for p in selected.values()])

    def download(package):
        path = packages_dir / package["file"]
        payload = fetch(REPOSITORY + package["file"], path)
        if hashlib.sha256(payload).hexdigest() != package["sha256"]:
            raise RuntimeError("SHA256 mismatch: " + package["file"])
        print("verified", package["name"], flush=True)
        return path

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(download, manifest))
    destination = TOOLS / "native"
    destination.mkdir(exist_ok=True)
    import zstandard
    links = []
    for path in paths:
        with path.open("rb") as compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
            with tarfile.open(fileobj=stream, mode="r|") as archive:
                for member in archive:
                    if not member.name.startswith("mingw64/"):
                        continue
                    target = (destination / member.name).resolve()
                    if not target.is_relative_to(destination.resolve()):
                        raise RuntimeError("Unsafe package path")
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
                    elif member.issym() or member.islnk():
                        source = (target.parent / member.linkname if member.issym()
                                  else destination / member.linkname).resolve()
                        if not source.is_relative_to(destination.resolve()):
                            raise RuntimeError("Unsafe package link")
                        links.append((target, source))
    # Materialize archive aliases as ordinary files: Windows symlink privileges
    # are unnecessary, and compiler executables can be launched natively.
    while links:
        remaining = []
        for target, source in links:
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            else:
                remaining.append((target, source))
        if len(remaining) == len(links):
            raise RuntimeError("Unresolved archive aliases: " + str(remaining))
        links = remaining
    (TOOLS / "compiler-lock.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Native GCC:", destination / "mingw64/bin/g++.exe")


if __name__ == "__main__":
    main()
