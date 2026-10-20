# RouteMind

Policy-driven, application-aware adaptive routing in **NS-3 3.46.1**.
The framework measures directed link state, computes actual IPv4 forwarding trees,
and compares QoS and route stability using real simulated TCP and UDP packets.

Read [the implementation plan](docs/IMPLEMENTATION_PLAN.md) for the research question,
architecture, acceptance gates, evaluation design and remaining milestones.
See [the consolidated evidence report](docs/EVIDENCE_REPORT.md) for the completed
correctness, ablation, held-out sensitivity and topology studies.
For a faculty presentation, use the [tested demo inputs and walkthrough](docs/FACULTY_DEMO.md).
Run `.\routemind.cmd demo --jobs 4` after building to produce a fresh 55-case
showcase with verified packet artifacts and a consolidated `DEMO.md` report.

The [graphical workspace](docs/GRAPHICAL_WORKSPACE.md) configures and runs native
experiments, edits custom network/traffic inputs, compares policies and displays
verified measurements and recorded routing paths. Launch it with:

```powershell
.\routemind.cmd gui
```

## What is implemented

- Portable C++ policy core: weighted reverse Dijkstra, unreachable destinations,
  validated cost profiles, EWMA smoothing, hysteresis and minimum dwell time.
- Configurable fixed destination-rank constraint, enabled for controlled traffic
  in every mode, to prevent transient backward forwarding across route updates.
- Custom `Ipv4RoutingProtocol`: traffic-class lookup from IPv4 DSCP, real routing
  tables, local delivery, forwarding errors, and down-interface handling.
- Eight-node fabric with three alternative corridors: 6 Mbps / 2 ms, 12 Mbps /
  8 ms, and 30 Mbps / 20 ms across their two core links. Host links add delay.
- Realtime UDP (256 kbps, 320-byte application packets including timestamp header),
  saturated TCP NewReno bulk transfer, and separately marked UDP cross-traffic.
- Static, naive adaptive, stable adaptive and class-aware modes; steady,
  congestion, burst, failure and combined scenarios.
- Time-weighted device queue occupancy, wire transmit utilization, local queue-drop
  proxy, application timestamps, FlowMonitor and real forwarding traces.
- Matched experiment matrices, source hashes, descriptive comparisons, paired
  differences and Student-t confidence intervals where replication is meaningful.

## Setup and build

Python 3.12+ is recommended (3.10+ is supported by the scripts). On this Windows
machine the project launcher uses the bundled Codex interpreter. On other machines
set `ROUTEMIND_PYTHON` to a real Python executable if automatic detection fails.
All compiler/source downloads live in `.tools/` on this drive. Setup does not
change the machine PATH or require administrator privileges.

```powershell
cd D:\Projects\networks-project
.\routemind.cmd setup
.\routemind.cmd build --jobs 4
```

The current checkout may already contain its downloaded tools and compiled binary;
in that case skip bootstrap. On Linux install GCC 11+, CMake 3.20+, Ninja and Python
using your package manager, then run the same bootstrap/build scripts with
`python3`. The compiler must support NS-3's C++23 features. Linux compatibility is
designed into the scripts; the initial local validation is on Windows.

The NS-3 release archive is checked against its published pinned checksum. Native
MinGW packages are checked against the official HTTPS repository SHA-256 metadata,
then extracted with executable aliases materialized as normal files. This avoids
MSYS shell execution and Windows symlink privileges. Repository metadata is not
verified with detached package signatures. `.tools/compiler-lock.json` records
the exact downloaded package set.

The Windows build applies a narrow, documented NS-3 time-mutex initialization
fix for this compiler. See [the diagnosis and exact patch](docs/NS3_WINDOWS_FIX.md).

## Run an experiment

```powershell
.\routemind.cmd run --mode=class-aware --scenario=congestion --output=results/demo
.\routemind.cmd verify results/demo
```

Important simulator arguments:

| Argument | Default | Meaning |
|---|---:|---|
| `--mode` | class-aware | static, adaptive, stable, class-aware |
| `--scenario` | congestion | steady, congestion, burst, failure, combined, active-failure, disconnected, missing-route, calibration (static mode) |
| `--policy` | balanced | shared adaptive/stable objective: shortest, latency, congestion, reliability, balanced |
| `--duration` | 26 | simulation seconds; minimum 24 |
| `--interval` | 0.25 | telemetry/controller sampling interval |
| `--alpha` | 0.3 | EWMA new-sample weight; use 1 to remove smoothing |
| `--dwell` | 1.5 | ordinary route dwell in seconds |
| `--threshold` | 0.12 | required fractional cost improvement |
| `--seed`, `--run` | 42, 1 | fixed seed and independent RNG run stream |
| `--pcap` | false | optional point-to-point packet captures |
| `--loop-safe` | true | require fixed destination-rank progress for controlled traffic; use 0 for the unconstrained ablation |
| `--topology` | parallel | parallel, extended (11 nodes), or unequal-hop detour |
| `--audit-forwarding` | false | retain all controlled forwarding events; enabled by correctness scenarios |

Applications stop three seconds before simulation end. Sinks remain active during
draining. Realtime starts at 1 s; TCP starts at 1.2 s. Congestion starts at a seeded
random time in [6, 6.5] s and ends at 18 s, with a seeded offered rate in
[8.5, 10.5] Mbps. Failure takes core link 2--5 down at 14 s and restores it at 20 s.
Periodic telemetry observes availability; ordinary stability limits do not block
repair of a failed installed tree.

Failure runs also export `events.csv` and measured observation, route-readiness and
realtime packet-recovery times in `summary.json`. `link_restoration_time_s` is the
scheduled link-up time; the old `recovery_time_s` remains its compatibility alias.
Neither denotes measured packet recovery. Repair/recovery latencies are null for
unaffected realtime paths or paths not repaired before restoration. Packet recovery
requires a packet transmitted at or after route readiness, received during the outage.

Calibrate telemetry independently before a larger evaluation:

```powershell
.\routemind.cmd calibrate --output results/calibration
.\routemind.cmd verify results/calibration
.\routemind.cmd compare --config experiments/recovery_checks.json --output results/recovery-checks
```

Calibration uses the genuine NS-3 fabric with UDP only and static routing, at 0.256
and 8 Mbps offered application load, sampled every 0.25 and 0.37 seconds. Raw wire
and queue event journals permit independent reconstruction of utilization and queue
integrals. It adds a `calibration` scenario; direct use requires `--mode=static` and
optionally `--calibration-rate-mbps`. The recovery checks use an unaligned 0.37-second
interval and a 100-second dwell to exercise failure bypass during the simulation.

## Compare policies

```powershell
.\routemind.cmd compare --config experiments/smoke.json --output results/smoke
.\routemind.cmd verify results/smoke
.\routemind.cmd compare --config experiments/evaluation.json --output results/evaluation --jobs 4
```

`smoke.json` has eight short runs and checks basic behavior. `evaluation.json` has
200 runs. See `docs/STATUS.md` for executed evaluation evidence and limitations.
Matrix runs are verified before being marked complete. Choose a fresh output
directory for each matrix/calibration so prior manifests and measurements are preserved.
Run commands reject a binary whose recorded simulation-source or executable hash
differs from the current build; rebuild after changing simulation source.
`--jobs` runs independent simulator processes; each retains its own output, seed
and run index. It does not change the simulated controller or workload timing.

Use the following comparisons to avoid conflating mechanisms:

| Comparison | What it investigates |
|---|---|
| static vs adaptive | response to load changes; static deliberately lacks failure recovery |
| adaptive vs stable | smoothing, hysteresis and dwell with the same balanced objective |
| stable vs class-aware | separate realtime latency and bulk congestion objectives |

All modes share topology, queues, TCP, offered traffic and random workload settings.
DSCP EF (46) is realtime; CS1 (8) is background with shortest-path routing; other
traffic, including TCP ACKs, is bulk. Background paths do not respond to load but
are recomputed for availability in adaptive modes.

## Artifacts

Each run contains:

- `summary.json`: parameters and measured application metrics.
- `topology.json`: directed links, interface IDs, capacities and addresses.
- `telemetry.csv`: interval utilization, time-average queue occupancy, availability
  and local drop proxy for every directed link.
- `decisions.csv`: accepted and rejected decisions for controlled destination 6.
- `routes.csv`: initial and subsequent tree installations and source paths.
- `forwarding.csv`: every realtime forwarding event and a bulk sample; proves actual
  interface selection rather than just logging a graph path.
- `realtime-packets.csv`: unique received sequence numbers, payloads and one-way delays.
- `events.csv`: scheduled link transitions, periodic observations and realtime route readiness.
- `flows.csv`, `flow-monitor.xml`: independent IP-layer flow accounting.

A matrix adds `manifest.json`, `comparison.csv`, `paired-differences.csv` and
`REPORT.md`; failure matrices also add `recovery-summary.csv`. Manifests include
the executable hash and source hashes, including tests and methodology documents.
Goodput counts sink payload, while FlowMonitor bytes include IP headers.
The realtime timestamp/sequence header is excluded from reported realtime payload.
Mean absolute delay variation is explicitly labeled and is not RFC 3550 jitter.
The reported p95 is the nearest-rank per-run percentile. The 40 ms target is an
experimental threshold. A missing/dropped packet is not counted as meeting it.

## Validation and limitations

```powershell
.\routemind.cmd test
.\routemind.cmd verify results/smoke
```

Core tests check path selection, disconnected graphs, failure and restoration
bypasses, hysteresis, dwell, smoothing, invalid telemetry and loop-free trees.
Result checks independently recompute percentiles, check packet accounting,
audit controlled destination trees/table epochs, and verify actual forwarding and
reverse TCP ACK delivery. Correctness scenarios use fresh datagrams with explicit
source-rejection accounting, preventing failed sends from changing offered traffic.

Run the declared studies in fresh output folders:

```powershell
.\routemind.cmd compare --config experiments/correctness.json --output results/correctness-new --jobs 4
.\routemind.cmd study --config experiments/ablation.json --output results/ablations-new --jobs 4
.\routemind.cmd study --config experiments/sensitivity-screen.json --output results/screen-new --jobs 4
.\routemind.cmd study --config experiments/sensitivity-heldout.json --output results/heldout-new --jobs 4
.\routemind.cmd study --config experiments/topology.json --output results/topologies-new --jobs 4
.\routemind.cmd study --config experiments/rank-boundary.json --output results/rank-new --jobs 4
.\routemind.cmd verify results/ablations-new
.\routemind.cmd plots --output results/figures
```

The plot command reads the recorded `phase2-ablations`, `phase3-heldout`,
`phase4-topologies` and `phase4-rank` folders by default. It uses this desktop's
bundled Python/ReportLab and Node/Sharp, exports seven SVG/PNG figures, and records
their input/code hashes. Native orchestration and statistical reporting still use
Python's standard library. See methodology for exact topology and workload definitions.

The first implementation uses centralized direct telemetry and synchronous table
installation with no simulated control packets or controller CPU cost. It supports
one representative controlled ingress per traffic class and destination for the
stability decision. Route costs are heuristic and do not reserve bandwidth or
guarantee end-to-end QoS. Local queue drop estimates are not independent link
failure probabilities. Instantaneous trees are consistent; safe asynchronous
deployment requires further study. Fixed-rank safety is restrictive:
the detour diagnostic demonstrates that it can prevent recovery along an otherwise
available physical route. Interpret delay alongside delivery.

The default rank constraint allows a hop only when it reduces a destination's
initial hop distance. Since that rank remains fixed, packets cannot revisit a
router even when tables change in flight. This restricts eligible detours and
can exclude viable paths in general topologies; it is appropriate to the initial
parallel-corridor fabric. `--loop-safe=0` retains unconstrained adaptive routing
for explicit experiments with transient revisits. It is recorded in each summary.

Do not assume adaptive routing always wins: route changes can hurt TCP and can
shift congestion elsewhere. Report those trade-offs. Further work includes broader
graph families, cost-weight and interaction sweeps, control/installation delays and
all-destination audits. See `docs/STATUS.md` for executed checks and remaining work.
