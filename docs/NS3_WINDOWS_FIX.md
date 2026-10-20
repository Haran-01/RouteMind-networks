# NS-3 3.46.1 native Windows initialization fix

The project uses the checksum-verified NS-3 3.46.1 release and the native MinGW64
GCC 16.2.0 package set recorded in `toolchain-lock.json`.

The initial shared-library build completed but the process exited with Windows
status `0xc0000142`. Loading just the NS-3 core DLL reproduced error 1114, while
the C++ runtime and an independent mutex test worked. Linking the same NS-3 objects
into a diagnostic executable exposed `std::system_error: Invalid argument` during
initialization, before main.

In this release, `nstime.h` calls `Time::StaticInit()` through a static initializer
in every translation unit. That function locks `g_markingMutex` in `time.cc`, but
the mutex is itself a namespace-scope object with a dynamic constructor on this
toolchain. It can therefore be used before its constructor runs.

`scripts/patch_ns3.py` changes just this mutex into a function-local static and
updates its five lock sites. The constructor then runs before the first lock.
The algorithm, locking scope, time representation, routing and event scheduling
remain the upstream implementation. The exact diff is saved in
`docs/ns3-mingw-time.patch` and applied idempotently by the Windows build script.
Unexpected upstream patch context is rejected instead of guessed.

After rebuilding the affected core DLL, the standard shared-library executable
successfully ran the actual TCP/UDP congestion experiment and passed packet and
forwarding verification. The delivered runtime uses the normal CMake-built NS-3
shared libraries; the diagnostic object-link experiment is not used.

This is a local compatibility patch. It has not been submitted to or confirmed by
upstream NS-3. The original archive is retained in `.tools` for reproducibility.
