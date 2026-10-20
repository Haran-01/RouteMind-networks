# RouteMind project instructions

- Keep the actual packet backend in NS-3; do not substitute synthetic metrics.
- Keep policy algorithms in `src/core` independent of NS-3.
- Treat `docs/IMPLEMENTATION_PLAN.md` as the architecture and milestone record.
- Before claiming success, build, run the changed scenario and verify its artifacts.
- Keep generated tools, binaries and results out of version control.
- Preserve matched workloads and source manifests in comparative experiments.
- Record observed trade-offs and environment limitations honestly in `docs/STATUS.md`.
- Use existing native tools in `.tools` and scripts/build.py on this Windows machine.
- Do not install WSL or change global PATH as a routine project action.
