"""Apply the documented, narrow NS-3 3.46.1 MinGW initialization fix."""
import difflib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def apply(ns3):
    if os.name != "nt":
        return
    source = ns3 / "src/core/model/time.cc"
    original = source.read_text(encoding="utf-8")
    if "RouteMindMarkingMutex" in original:
        return
    declaration = "static std::mutex g_markingMutex;"
    if original.count(declaration) != 1 or original.count("lock{g_markingMutex}") != 5:
        raise RuntimeError("Pinned NS-3 time.cc does not match the expected patch context")
    replacement = """// Function-local initialization is required when the toolchain's std::mutex
// constructor is dynamic: nstime.h calls StaticInit before this TU's globals.
static std::mutex& RouteMindMarkingMutex()
{
    static std::mutex mutex;
    return mutex;
}"""
    updated = original.replace(declaration, replacement).replace("lock{g_markingMutex}", "lock{RouteMindMarkingMutex()}")
    patch = "".join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                                       fromfile="a/src/core/model/time.cc", tofile="b/src/core/model/time.cc"))
    (ROOT / "docs/ns3-mingw-time.patch").write_text(patch, encoding="utf-8")
    source.write_text(updated, encoding="utf-8")
    print("Applied NS-3 MinGW time initialization fix", flush=True)


if __name__ == "__main__":
    apply(ROOT / ".tools/ns-3.46.1")
