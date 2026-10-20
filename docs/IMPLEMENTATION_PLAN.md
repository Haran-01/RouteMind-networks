# RouteMind implementation plan

## Goal and contribution

Build a genuine NS-3 packet-level routing experiment, not an abstract graph animation.
The contribution is an application-aware, stability-controlled policy framework with
reproducible evidence about the trade-off between QoS and route churn. Adaptive
weighted shortest-path routing itself is established work; do not claim otherwise.

Research question: **Can traffic-class-specific routing with smoothing, hysteresis,
and a minimum dwell time reduce delay and route churn under changing load without
unacceptable bulk-transfer degradation?** A negative result is a valid result.

## Decisions

- Pin NS-3 3.46.1. Use C++17 or later for the simulator and portable policy core.
- Use a project-local MSYS2/MinGW64 toolchain on Windows; also support Linux builds.
  Do not require WSL, administrator access, Python bindings, or system PATH changes.
- Keep the policy core independent of NS-3 so algorithm behavior can be tested.
- Use Python's standard library for experiment orchestration and initial reporting.
- Wire genuine TCP/UDP applications through a custom Ipv4RoutingProtocol.
- Classify IPv4 DSCP EF (46) as realtime, default/other traffic as bulk. TCP ACKs
  use bulk routes. Do not imply that routing alone provides reserved bandwidth.
- Use one directed forwarding tree per traffic class and destination. Compute from
  a common immutable measurement snapshot. A controller callback installs all tables
  synchronously in one simulator event; model delayed/partial installation later.
- By default, controlled routes must strictly decrease a fixed destination hop
  rank. This prevents transient packet loops across successive trees. Keep this
  restriction identical across baselines and expose an unconstrained ablation.
  Document that it reduces the eligible detour space in general topologies.
- Controller has centralized direct access to trace measurements. Initial results
  exclude telemetry-message overhead and controller CPU time from simulated latency.

## Architecture and data flow

1. Scenario builder: router graph, host links, capacities, delay, bounded queues,
   timed cross-traffic, failure and recovery events, random seed/run number.
2. Telemetry: directed device transmit counters, queue occupancy and drop traces,
   interval utilization, smoothed queue waiting estimate, link availability.
3. Policy core: normalized nonnegative link costs for shortest, latency, congestion,
   reliability and balanced objectives; Dijkstra destination trees.
4. Stability controller: EWMA, improvement threshold, minimum dwell time; failed
   paths bypass normal dwell limits. Preserve destination-tree consistency rather
   than independently retaining arbitrary next hops, which could create loops.
5. Forwarding adapter: DSCP classification and actual RouteOutput/RouteInput lookups.
6. Evaluation: FlowMonitor, timestamped application samples, route/decision/telemetry
   CSVs, run manifest, paired repeated trials and confidence intervals.

## Cost model

For directed edge e and class k:

    c_k(e) = hop_weight + delay_weight * estimated_delay_ms / delay_reference_ms
             + utilization_weight * utilization
             + queue_weight * queue_fraction
             + loss_weight * loss_estimate

Use fixed normalization references across compared runs, strictly positive hop cost,
and nonnegative weights. Estimated delay includes configured propagation plus an
estimated queuing/serialization contribution; it is not a claim of measured one-way
per-link delay. Utilization uses transmitted bytes over interval link capacity.
Queue occupancy is time-weighted, not just a potentially misleading last sample.
Link drop estimates are explicit local proxies, not end-to-end reliability guarantees.
Correlated queue/utilization/delay terms are a tunable heuristic; report sensitivity.

Bandwidth is a bottleneck property, so do not sum bandwidths or label weighted
Dijkstra a multi-constraint QoS solver. Hard bandwidth reservations, admission control,
and end-to-end delay guarantees are out of scope for the first implementation.

## Baselines and experimental design

- `static`: initial fixed-cost shortest path, no load-driven updates. In failure
  scenarios distinguish its intentionally absent recovery from adaptive baselines.
- `adaptive`: common balanced cost, raw telemetry, no hysteresis/dwell suppression.
- `stable`: same balanced cost with smoothing/hysteresis/dwell (isolates stability).
- `class-aware`: stable controller with separate realtime/bulk cost profiles.

Compare within the same topology, application timing, packet sizes, queue settings,
seed, run index, TCP implementation and failure schedule. Use multiple run indices;
introduce stochastic background start/load variation explicitly rather than calling
identical deterministic runs independent evidence.

Start with a small diamond/parallel-path fabric. Expand to 8-12 router/host nodes and
three alternative corridors. Test steady load, burst congestion, sustained congestion,
link failure, recovery, and near-equal path costs. Run no-congestion cases too.

Outputs: application goodput (payload bytes, separately from IP throughput), mean/p95
delay and jitter for realtime traffic, packet delivery, TCP goodput/completion where
applicable, time-weighted utilization/queue occupancy, route-change count, route
stretch, failure detection/recovery time, and time above a stated QoS threshold.
Count initial installation separately from route changes. Distinguish decision time
from first packet delivery after recovery. Stop applications before simulation end
and allow queues and FlowMonitor tracking to drain.

## Milestones and acceptance gates

### M1 - executable foundation (first implementation)

- [x] Portable C++ policy core with deterministic shortest-path tests.
- [x] Typed policies, validated telemetry, smoothing and hysteresis decisions.
- [x] Genuine NS-3 custom forwarding and two traffic classes.
- [x] Multipath congestion scenario, failure/recovery, actual route trace.
- [x] CSV/JSON artifacts, reproducible CLI and a comparison report.
- [x] Compile and execute on this machine; document observed outcomes honestly.

### M2 - measurement and forwarding correctness

- [x] Verify selected next hops against device/IP packet traces, including table epochs.
- [x] Verify acyclicity of controlled installed destination trees and no actual
  forwarding across down links. Background/non-controlled table trace expansion
  remains a separate validation extension.
- [x] Test disconnected topology and missing-route forwarding behavior.
- [x] Check measured utilization against a known constant-rate flow (low/saturated
  UDP calibration, raw byte/queue journals, aligned/unaligned sample intervals).
- [x] Account for all received application sequences and packets still in flight;
  fresh correctness datagrams also account for source rejections explicitly.
- [x] Check tail-delay computation, class marking, and reverse-path TCP ACK delivery.
- [x] Verify failure bypasses dwell time and validate invalid CLI/config inputs.

### M3 - experimental evidence

- [x] Run paired repeated seed/run trials for every baseline and scenario (200 cases;
  steady/failure repetitions are consistency checks, not independent evidence).
- [x] Produce descriptive summaries, paired differences and uncertainty intervals
  for independently varied workloads.
- [x] Ablate smoothing, hysteresis, dwell and class separation independently (75 cases).
- [x] Sweep dwell time, improvement threshold and smoothing; report bad cases and
  trade-offs (63 screening and 105 held-out cases, predefined one-factor ranges).
- [x] Avoid parameter tuning against only the final evaluation workload; retain defaults.

### Measurement progress - 2026-10-20

- Added low-load and saturated constant-rate NS-3 calibration with analytic wire-rate
  checks and independently reconstructed byte/queue event journals at 0.25/0.37 s.
- Added separate scheduled, periodically observed, route-ready and first qualifying
  realtime delivery times. Unaffected/unrepaired paths have null repair latency.
- Added unaligned observation tests with dwell longer than the simulation, plus
  regression checks excluding pre-repair packets from packet recovery.
- Corrected both descriptive and paired confidence intervals for deterministic
  workloads. Each matrix run must pass artifact verification before completion.
- Added executable/source consistency checks and expanded experiment source manifests.
- Completed the 200-case matrix and verified every case. Default adaptive realtime
  paths were unaffected by the scheduled outage; targeted checks separately verify
  actual repair with 60 ms observation and 70.526572 ms first qualifying delivery.
- Broader evaluation outcomes and limitations are recorded in STATUS.md. The
  sequential extension below records further ablations, sensitivity and topology checks.

### Sequential evidence extension - 2026-10-20

1. [x] Default-setting active-path recovery, receiver disconnection and missing-route
   callbacks: 12 native cases, with table epochs, complete forwarding and TCP ACK
   local-delivery evidence. Fresh UDP offers remain matched when RouteOutput rejects.
2. [x] Independent removal of EWMA, hysteresis, dwell and class-specific objectives,
   using five paired workload realizations per congestion/burst/combined scenario.
3. [x] Predefined one-factor sensitivity ranges, screening workloads and a separate
   held-out seed. Retain the original defaults; do not select a post-hoc winner.
4. [x] Additional equal-length extended and unequal-length detour topologies,
   explicit fixed-rank reachability ablation, and plots of measured artifacts.

### Faculty showcase - 2026-10-20

- [x] One-command native showcase (`routemind.cmd demo`) and documented live
  inputs in `docs/FACULTY_DEMO.md`, covering all modes/scenarios, five shared
  objectives, stability removals, three topologies, failure/error handling,
  calibration and PCAP output. Fresh output directories preserve prior evidence.
- [x] Built and ran `results/faculty-demo-ready-20261020`: 55 verified NS-3 cases
  with matched comparisons and source/runtime manifests. One trial per setting;
  this is presentation coverage, not another independent statistical study.

### M4 - extensions after core evidence

- [x] Local graphical workspace with template/custom experiment inputs, native
  runs and cancellation, matched comparisons, verified metrics, recorded routing
  playback, artifact export and history. Custom links/traffic/failure settings
  retain canonical host roles; arbitrary role/application editing remains future
  work. Acceptance: native build, core/Python contracts, browser interactions,
  custom-input artifact checks and 20 baseline/correctness regression cases.

- [x] Larger native topology templates selectable by CLI (parallel, 11-node extended,
  unequal-hop detour). Arbitrary topology/scenario files remain future work.
- Separate timed telemetry collection and installation delays.
- [x] Periodic observations of directly accessible availability, separately timed
  from link callbacks. A distributed probing/detection protocol remains future work.
- [x] Optional packet captures and offline plots of measured results.
- Optional scheduling/queue differentiation as a separately evaluated mechanism.

## Repository layout

    src/core/          simulator-independent graph/policy/control code
    src/ns3/           forwarding adapter and experiment
    tests/             meaningful core and result-contract checks
    scripts/           bootstrap, build, smoke and batch commands
    experiments/       explicit experiment configurations
    analysis/          summaries and report generation
    docs/              architecture, methodology and implementation status
    results/           ignored generated runs and reports
    .tools/            ignored downloaded runtime/compiler and NS-3 sources

## Risks and boundaries

Native Windows NS-3 compilation is the first environment risk. Use the documented
MinGW route, retain build logs, and support Linux with the same project sources.
Do not replace NS-3 with a synthetic simulator and present it as the real backend.
Small topologies can favor one policy; generality requires multiple topologies.
Centralized global knowledge is an explicit assumption, not a distributed protocol.
Synchronous simulator updates avoid partial-update loops but do not establish safe
asynchronous real-network deployment. Keep these limits in the report.

## References

- https://www.nsnam.org/releases/ns-3-46/download/
- https://www.nsnam.org/docs/release/3.46/installation/ns-3-installation.pdf
- https://www.nsnam.org/docs/models/html/routing-overview.html
- https://www.nsnam.org/docs/models/html/flow-monitor.html
- https://www.rfc-editor.org/rfc/rfc9522.html
