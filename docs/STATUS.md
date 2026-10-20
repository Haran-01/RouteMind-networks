# Implementation status

The executable foundation and expanded measurement/evaluation stage are working
on this Windows machine. All source,
tools and generated results are in `D:\Projects\networks-project`. The repository
is initialized on `main`; no commits have been created.

## Executed verification

- CMake/MinGW build of the portable core and genuine NS-3 3.46.1 executable passed.
- 46 core contract checks passed: paths, disconnected destinations, failure/dwell
  bypasses, restoration, smoothing, policy validation, destination trees and rank.
- Nine Python regression tests passed, including end-to-end report CSV checks,
  deterministic confidence-interval suppression and exclusion of packets already
  in flight from recovery measurements.
- Invalid mode, policy, threshold and sampling-interval CLI inputs were rejected.
- Eight mode/scenario smoke runs completed and passed artifact verification.
- Twelve congestion pilot runs (four modes, three workload realizations) completed
  and passed artifact verification.
- Three additional steady/burst/combined scenario runs completed and passed checks.
- One explicit unconstrained adaptive/failure ablation completed; it recorded 15
  actual realtime router revisits. The 23 default constrained matrix runs recorded
  zero realtime revisits. Both the acyclic-tree and in-flight update cases matter.
- All verified runs drained with zero unaccounted FlowMonitor packets. Their
  application delay percentiles and actual ingress forwarding matched artifacts.
- Measurement extension: four constant-rate NS-3 calibration cases passed byte/queue
  journal reconstruction and analytic rate checks, at 0.25/0.37 second intervals.
  Low-load utilization matched 4.6667%; 8 Mbps load saturated the 6 Mbps link and
  produced bounded backlog and drops. The final rebuilt-source evidence is in
  `results/validation/calibration/CALIBRATION.md` (four verified cases).
- Eight updated smoke cases and eight unaligned failure/combined checks passed.
  In the 0.37 s / 100 s dwell stable failure case, detection/repair took 60 ms;
  the first qualifying post-repair realtime packet arrived after 70.526572 ms.
  Default class-aware failure routing was already on another corridor, so its
  realtime repair/recovery latency is null, not a zero-latency recovery claim.
- The rebuilt-source unaligned checks passed in `results/validation/recovery`
  using four independent simulator processes; every case retained its own output.
- The full 200-case matrix completed in `results/evaluation`: four modes, five
  scenarios, ten run indices each. All 200 cases passed packet, forwarding,
  recovery-timing and drain checks, with zero realtime router revisits.
- The final audit checked all expected cases, per-run verification logs, paired
  workload/configuration equality, and deterministic confidence-interval suppression.
  All eight original smoke outcomes (p95, delivery, TCP goodput and route changes)
  were exactly preserved by the new measurement instrumentation.
- Invalid calibration combinations and a parallel matrix containing an invalid mode
  were rejected. The latter retained a failed manifest and produced no comparison
  report. Existing matrix/calibration evidence was rejected without overwrite.

## Expanded evaluation - 2026-10-20

See `results/evaluation/REPORT.md`, `comparison.csv`, `paired-differences.csv`,
`recovery-summary.csv` and `manifest.json`. Each run's artifacts were verified
before the matrix was marked complete. Source/build hashes matched at the final
audit; subsequent status/plan documentation updates do not rewrite those manifests.

The congestion, burst and combined cases have ten varied workload realizations per
mode. Steady/failure runs are deterministic consistency repetitions, not ten
independent observations; both descriptive and paired intervals are omitted there.
The same seed/run workloads are matched across all four modes. No parameters were
tuned using these evaluation outcomes.

Observed class-aware versus naive adaptive trade-offs (run-level means):

| Scenario | Realtime p95 ms: adaptive / class-aware | TCP Mbps: adaptive / class-aware | Route changes: adaptive / class-aware |
|---|---:|---:|---:|
| Congestion | 22.982 / 30.374 | 4.841 / 7.772 | 175.6 / 23.0 |
| Burst | 77.512 / 30.133 | 3.484 / 7.779 | 154.6 / 23.0 |
| Combined | 23.069 / 30.326 | 4.595 / 8.623 | 156.8 / 21.0 |

In congestion, the paired class-aware-minus-adaptive differences are +7.393 ms
p95 (95% t interval +7.316 to +7.469), +2.930 Mbps TCP (+2.770 to +3.091),
and -152.6 route changes (-155.749 to -149.451). Under bursts, class-aware has
lower p95 as well as higher goodput and fewer changes. This is evidence of a
workload-dependent trade-off on this fabric, not universal superiority.
Stable balanced routing has congestion p95 80.236 ms despite only 30 path changes.
The 100-second dwell diagnostic also has poor congestion delay: failure bypass
works, but suppressing normal adaptation is not a good performance setting.

All adaptive realtime paths in the default failure/combined matrix were already
off the failed corridor at link-down. Those cases do not measure repair of an
affected realtime path. Static paths were affected but did not reroute; their
repair/recovery values are null. The separate 100-second dwell diagnostic forces
stable/class-aware paths to remain on the fast corridor before failure, showing
60 ms observation/repair and 70.526572 ms first qualifying delivery after failure.
The main matrix's zero detection delay comes from the 14-second event aligning
with the 0.25-second sample grid, not a general instant-detection guarantee.

The evaluation still covers one fixed fabric and initial cost weights. Complete
independent mechanism ablations, parameter sensitivity and additional topologies
are required before selecting general course-report claims.

## Observed pilot, not a general performance claim

See `results/pilot/REPORT.md`, its paired-difference CSV and the source/workload
manifest. The three varied congestion workloads show trade-offs: class-aware
routing has fewer changes and higher TCP goodput than naive adaptation, while
naive adaptation has lower UDP p95 delay. Stable balanced routing does not
consistently match class-aware realtime delay. No mode wins every metric.

The fixed-rank constraint is identical across default baselines and can exclude
useful detours outside the configured parallel-corridor fabric. The unconstrained
ablation is explicitly marked in its summary. Static intentionally has no alternate
failure rerouting. Interpret delay together with delivery, including lost packets.

## Environment notes

The machine had no WSL, CMake or C++ compiler available. Native tools are installed
locally under `.tools`; machine PATH and system settings were not changed. The
`py` launcher on this machine did not find Python, so `routemind.cmd` selects the
available bundled interpreter. See README for a manual interpreter override.

A small first-use initialization patch was needed for the pinned NS-3 time mutex
with this MinGW compiler. Its exact diff and diagnosis are documented in
`NS3_WINDOWS_FIX.md` and `ns3-mingw-time.patch`; it is applied by the build script.
The delivered runtime uses the standard NS-3 shared-library build. Initial failed
MSYS/source downloads and diagnostic binaries remain ignored inside `.tools`/build;
automatic approval policy blocked cleanup of the unused setup downloads.
NS-3 configuration still warns that its `python3` permission-check helper is not
available and that the output directory lies outside the NS-3 source tree. The
project uses its bundled interpreter explicitly; native build and execution pass.
Tests use project-local temporary folders because the sandbox's default Windows
temporary directory denied nested writes.

## Sequential evidence extension

### Sequential phase 1 completed

`results/phase1-correctness-v2` contains 12 verified default-setting cases: all four
modes with active-path failure, full receiver disconnection and missing-route probes.
The new low-load workload uses fresh 256 kbps UDP datagrams and 64 kbps TCP.
The same active fast link fails at 14.07 s and returns at 20.11 s across modes;
the 0.25 s default sampler observes failure at 14.25 s. Adaptive/stable/class-aware
repair in 180 ms and first qualifying realtime delivery occurs after 190.522666 ms.
All modes' realtime paths were affected. Static does not repair during the outage.

In a full disconnection, all modes receive 1,581 of the same 2,199 offered UDP
sequences (71.8963%). Adaptive modes reject 600 offers at the source and lose 18
accepted IP packets; static accepts all offers and loses 618 later. Source
rejections are explicit and excluded from FlowMonitor's IP denominator, but included
in offered-traffic delivery. Every accepted IP packet is accounted for after drain.
NS-3 OnOff caches a failed UDP send; new correctness scenarios therefore use a
fresh datagram for each offer. Existing performance scenarios retain their original
generator and historical manifests/results. The initial diagnostic matrix is
retained as failed evidence in `results/phase1-correctness`.

Each case validates 416 controlled destination trees, table-epoch compliance,
reverse-path bulk classification and 73--75 TCP ACK delivery paths. Explicit
unknown-destination probes exercise both RouteOutput rejection and RouteInput's
missing-route error callback. Disconnected routes become unreachable and restore
after link-up; no packet delivery during disconnection is mislabeled as recovery.

### Sequential phase 2 completed

`results/phase2-ablations` contains 75 verified runs: five declared variants,
three scenarios, five paired workload realizations, seed 314159. Each variant
removes only one mechanism relative to class-aware defaults; fixed-rank safety
remains enabled. `variants.csv` records settings and `paired-differences.csv`
reports effects relative to the default controller, with n=5 per scenario.

For congestion, default p95/TCP/path changes are 30.374 ms / 7.772 Mbps / 23.
Without EWMA they become 83.444 ms / 7.077 Mbps / 27.2; the p95 increase is
53.070 ms (paired 95% t interval 52.813--53.326). Removing hysteresis retains
30.374 ms p95 but increases changes to 29. Removing dwell yields 16.168 ms p95,
5.478 Mbps TCP and 63 changes. A shared balanced objective yields 83.285 ms p95,
7.474 Mbps TCP and 30.8 changes. Mechanisms have distinct and sometimes opposing
effects; no universally best setting follows from this small single-fabric study.

### Sequential phase 3 completed

`results/phase3-screen` (63 cases, seed 271828, runs 1--3) and
`results/phase3-heldout` (105 cases, seed 161803, runs 1--5) completed with all cases
verified. Both configurations were saved before screening began, with the same
seven-setting one-factor grid: alpha {0.1,0.3,1}, dwell {0,1.5,3} seconds and
threshold {0,0.12,0.25}. The default is included once; only one factor changes at
a time. No weights/defaults were retuned or post-hoc winner selected.

Held-out congestion means (p95 ms / TCP Mbps / changes): default 30.374/7.772/23;
alpha=0.1 35.282/8.981/15; alpha=1 80.007/6.674/26.8; dwell=0 16.064/5.424/63;
dwell=3 84.265/7.998/15; threshold=0 30.374/7.764/29; threshold=0.25
31.654/7.867/23. These independent workloads retain clear delay/churn/goodput
trade-offs. Small n=5 paired intervals and fixed workload ranges limit extrapolation.

### Sequential phase 4 completed

`results/phase4-topologies` contains 72 verified cases: three topologies, four modes,
two load scenarios and three paired workload realizations (seed 424242). The extended
11-node fabric adds one router to each corridor, keeping corridor hop lengths equal.
Its congestion adaptive/class-aware p95 means are 21.274/30.796 ms, TCP means
5.682/7.762 Mbps and path-change means 180/22. The trade-off persists in this
additional fabric; n=3 per scenario remains exploratory rather than broad generality.

The unequal-hop detour fabric exposes the fixed-rank boundary. All four constrained
modes have the same congestion behavior because ingress cannot use the longer
alternative at all. Four deterministic active-path cases in `results/phase4-rank`
compare the same adaptive/class-aware algorithms with and without this constraint.
Both constrained modes deliver 1,581/2,199 offered UDP packets (71.8963%) and cannot
repair during the outage. Both unconstrained modes deliver 2,181/2,199 (99.1814%)
and repair via the physical detour. Their higher received-packet p95 (11.523 ms
versus 6.314 ms) must not be interpreted as worse overall QoS without considering
the constrained case's lost packets. This diagnostic does not prove unconstrained
updates safe: the earlier unconstrained matrix observed actual router revisits.

Twelve additional extended-topology correctness cases passed in
`results/phase4-extended-correctness`, including 191.755999 ms first qualifying
post-failure delivery for class-aware routing. Eight fresh baseline regression
cases in `results/phase4-regression` preserve all original smoke values exactly
(p95, delivery, TCP goodput and route-change counts).

The sequential extension totals 351 verified successful scenario runs, including
deterministic correctness/regression checks; this is not 351 independent replicates.
Every successful case drained with zero unaccounted IP packets. All default-rank
cases recorded zero realtime revisits. Source and workload manifests are retained
per stage; documentation and plotting updates do not rewrite native evidence.
Seven SVG/PNG figures in `results/figures` include input hashes and plotter hashes.
They use the bundled ReportLab chart library and Node/Sharp renderer because
Matplotlib is not installed in this environment. No new packages or global PATH
changes were needed.

## Faculty showcase completed - 2026-10-20

`routemind.cmd demo --jobs 4` now orchestrates the existing native runners and
produces a timestamped consolidated `DEMO.md`. The tested output is
`results/faculty-demo-ready-20261020`: 55 successful cases covering eight regular
scenarios across four modes (32), independent mechanism removals (5), five shared
cost profiles (5), extended-topology comparison (4), rank-boundary diagnostics (4),
telemetry calibration (4), and active-failure packet capture (1). Each case passed
its normal artifact verifier; paired workloads and source/runtime manifests remain
in the section directories. This is one trial per setting, not 55 independent
replicates or evidence of universal performance. The native build, C++ contracts,
and nine Python tests passed. No simulator/core source changes were required.

The seed-42 burst example shows static/adaptive/stable/class-aware p95 delays of
84.841/83.975/44.697/30.133 ms and TCP goodput of 2.144/3.307/8.164/7.778 Mbps.
Class-aware improves delay/delivery/churn relative to stable, while stable has
higher TCP throughput in this example. Congestion class-aware defaults versus
zero dwell give p95 30.374 versus 16.043 ms, TCP 7.772 versus 5.424 Mbps, and
23 versus 63 route changes. Parallel active-failure repair remains 180 ms with
190.523 ms first qualifying post-repair packet delivery; physical disconnection
and fixed-rank detour restrictions remain explicit in the demonstration.

Independent PCAP parsing confirmed 18 valid PPP capture files: 12 contain traffic
and six idle-interface files contain only the 24-byte header. Across interfaces
there are 19,312 packet observations, including TCP/ACK and DSCP-46 UDP; these
include repeated observations of packets at different interfaces, not unique
packet counts. The first showcase attempt in `results/faculty-demo-20261020`
passed all native case verifiers but its final orchestration check incorrectly
required every capture to contain traffic. That failed attempt is retained; the
check was corrected before the successful full rerun. Calibration matches 4.6667%
low-load utilization and approximately full saturation with a roughly 59.7 KB
mean queue. No WSL, package installations or global PATH changes were needed.

`docs/FACULTY_DEMO.md` supplies the presentation order, exact live inputs, artifact
explanations and limitations. Existing repeated-trial figures/evidence remain
separate from these illustrative demonstration runs.

## Graphical workspace completed - 2026-10-20

`routemind.cmd gui` launches a local browser application with white/light-grey
panels, square boundaries and a restrained blue routing accent. It exposes the
template modes/scenarios/parameters, matched four-mode comparison, live native
simulation-clock progress, verified metrics/charts, recorded route/event playback,
artifact downloads, import/export, cancellation and persistent run history.
The backend stays NS-3; no policy/core changes or synthetic packet metrics were
introduced. Source manifests now include the frontend as well.

Validated custom configuration adds 8–24 nodes and editable router connectivity,
link rates/delays/queues, UDP rate/size, background load/burst timing and a chosen
failure/restoration schedule. Existing host roles and attachment edges remain
fixed; custom experiments support the five performance scenarios. Arbitrary host
roles, multiple application pairs and configurable TCP rates remain future work.
Custom verification checks executed settings against the retained scenario JSON,
in addition to the existing actual forwarding, ACK, recovery and packet checks.
See `docs/GRAPHICAL_WORKSPACE.md` for exact bounds and model limitations.

Native build/core contracts and 16 Python tests passed. Browser tests ran a real
matched burst comparison plus a nine-node custom combined case (9 Mbps edited
link, 0.512 Mbps UDP, 640-byte packets, failure/restoration at 12/19 seconds).
All five cases passed artifact verification, including independent custom-input
checks. Playback/down-link coloring, downloads, import/export, cancellation,
history, invalid inputs, path restrictions and the mobile layout passed without
browser script errors. Twelve original correctness cases passed in
`results/gui-correctness-20261020`; eight original smoke cases passed in
`results/gui-smoke-20261020` and preserved prior p95/delivery/TCP/churn values.
These are functional checks, not additional independent performance claims.

The server is local and single-user. Windows sandbox loopback isolation blocked
host-browser access to the initial sandbox server; QA used an approved host-side
server and the installed Chrome. No new packages, WSL or global PATH changes were
needed. Runs/queue verification can take longer than simulated time, especially
calibration or large trace exports; the UI separates running from verification.

An additional GUI-importable example, `experiments/gui-path-contrast.json`, was
built and run across all four modes in `results/gui-path-contrast-20261020`.
All four cases passed packet, forwarding and custom-input verification. Reducing
both fast-corridor links to 3 Mbps and applying a fixed 12 Mbps burst background
exposes clear mode differences: p95 167.177/42.944/76.118/25.005 ms and TCP
0.740/3.299/8.260/9.511 Mbps for static/adaptive/stable/class-aware. At 22 seconds
the first three modes occupy different corridors, while class-aware splits UDP
and TCP across the medium/wide corridors. This is an illustrative single trial,
with no inference of general optimality; inputs and source manifests are retained.

## Remaining work

1. Arbitrary host roles/application pairs, larger graph families, additional seeds and
   ranges, and cost-weight/interaction sweeps beyond the declared one-factor study.
2. Extend table/forwarding audits to background/non-controlled destinations; add
   route stretch and time-above-target measurements and full bulk data traces.
3. Model telemetry traffic, CPU/installation delay, asynchronous updates and actual
   probing-based failure detection. Study safe updates with a broader detour space.
4. Prepare the final course presentation using the evidence report and plots,
   retaining delivery, trade-offs and environment/model limitations.

The local GUI controls simulation experiments; deployed-network integration is not implemented.
