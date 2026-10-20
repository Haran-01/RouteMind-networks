# Faculty demonstration

RouteMind computes and installs application-aware IPv4 routes in NS-3 3.46.1.
Present it as a reproducible packet simulation, with actual TCP NewReno and UDP,
measured link telemetry, and checked forwarding artifacts. There is no live GUI.

## Run the complete showcase

In PowerShell:

```powershell
cd D:\Projects\networks-project
.\routemind.cmd build --jobs 4
.\routemind.cmd demo --jobs 4
```

The demo runs **55 simulations**, verifies every case, and prints the path to
`DEMO.md` in a fresh timestamped directory under `results/`. Keep that report
ready before the presentation; show a few live commands below during the talk.
26 seconds is simulated time, not a promise about wall-clock runtime.
An explicit `--output=results/my-faculty-demo` is supported; it must be fresh.
No downloads, setup, WSL, global PATH changes or chart packages are required on
this prepared machine. The demo uses the existing native runtime and fails if
it does not match the simulation sources.

The 55 cases cover all nine scenarios (including calibration), all four modes,
all five cost profiles, three topologies, independent mechanism removals, native
missing-route callbacks, both forwarding directions, and populated PCAP output.
The generated JSON configurations and per-section manifests preserve exact
inputs, paired workloads and source/build hashes. This is one trial per setting;
use the existing evidence report for repeated-trial research results and plots.

## A 10–15 minute presentation

1. **Problem and topology (2 minutes).** Show the three alternative corridors in
   `topology.json`: fast/narrow, medium, slow/wide. Explain that latency-sensitive
   UDP and bulk TCP can prefer different paths. The core computes destination
   trees; the NS-3 adapter installs the resulting actual IPv4 forwarding tables.
2. **Matched policy comparison (3 minutes).** Open `policies/REPORT.md` from the
   demo output. Start with **burst**: compare static, adaptive, stable and
   class-aware p95 delay, delivery, TCP goodput and route changes. Then show
   congestion: raw adaptive can have lower delay, while class-aware can improve
   bulk throughput and reduce route churn. There is no universally winning mode.
3. **Failure and correctness (3 minutes).** Use **active-failure**, which actually
   cuts the selected realtime path. Compare static against class-aware repair.
   Explain **disconnected** has no live alternative and therefore cannot repair.
   Show the two **missing-route** probes and native source/transit error records.
4. **Policy controls (2 minutes).** Open `controls/REPORT.md`: removing dwell
   can improve delay at the expense of route churn and TCP throughput. Show the
   `objectives/REPORT.md` profiles: shortest, latency, congestion, reliability,
   balanced. Profile selection affects shared adaptive/stable modes; class-aware
   uses separate realtime latency and bulk congestion objectives.
5. **Evidence and limits (2–3 minutes).** Show the 11-node extended fabric,
   `calibration/CALIBRATION.md`, actual route/packet traces and PCAPs. Close with
   the detour rank-boundary report: fixed rank prevents backward forwarding but
   can exclude a longer physical alternative. Disabling it is diagnostic and
   does not establish general transient-loop safety.

## Exact inputs for individual live demonstrations

### Importable GUI example with strong path contrast

Import `experiments/gui-path-contrast.json` in the graphical workspace, then
click **Compare all four modes**. This is a 30-second parallel-fabric burst
experiment, seed 42/run 1, with customization enabled. Both fast-corridor links
(1–2 and 2–5) are 3 Mbps / 1 ms. The other corridors remain 12 Mbps / 4 ms and
30 Mbps / 10 ms per link; all queues remain 60,000 bytes. Realtime UDP is
0.512 Mbps with 640-byte application packets; background UDP is 12 Mbps from
6–24 seconds with 0.4-second on/off bursts. Sampling/stability remain
0.25 s / alpha 0.3 / dwell 1.5 s / threshold 0.12, with rank protection enabled.

The rebuilt native backend produced four verified cases in
`results/gui-path-contrast-20261020`. Static/adaptive/stable/class-aware p95 delays
are 167.177/42.944/76.118/25.005 ms; delivery is 81.26/95.96/98.58/99.77%; TCP
goodput is 0.740/3.299/8.260/9.511 Mbps; route changes are 0/182/36/22.

At recorded time **22.00 seconds**, static uses 0–1–2–5–6 for both classes,
adaptive uses 0–1–3–5–6, stable uses 0–1–4–5–6, and class-aware uses
0–1–3–5–6 for UDP and 0–1–4–5–6 for TCP. Switch result modes at that same
timestamp to show the distinction. These are selected paths at one instant;
adaptive paths change throughout the run. This is one illustrative workload,
not proof of universal superiority. The exact scenario JSON and native network
file are retained alongside the comparison manifest and packet artifacts.

Run the commands below from the project directory. Output directories are
examples for this presentation; change them for subsequent demonstrations so
you preserve earlier evidence. For each single run, invoke `verify` on its output.

| Demonstration | Input flags after `.\routemind.cmd run` | What to inspect |
|---|---|---|
| Class-aware under bursts | `--mode=class-aware --scenario=burst --seed=42 --run=1 --output=results/live-burst` | summary.json: delay, delivery, TCP goodput; routes.csv: class-specific paths |
| Static baseline | `--mode=static --scenario=burst --seed=42 --run=1 --output=results/live-static` | Same offered workload; no adaptation |
| Naive adaptation | `--mode=adaptive --scenario=burst --seed=42 --run=1 --output=results/live-adaptive` | Frequent route changes; compare all metrics |
| Stable shared objective | `--mode=stable --policy=balanced --scenario=congestion --output=results/live-stable` | Smoothing and stability with a shared profile |
| Active-path repair + PCAP | `--mode=class-aware --scenario=active-failure --pcap=1 --output=results/live-repair` | failure at 14.07 s, observed repair at 14.25 s; first qualifying delivery after repair |
| Physical disconnection | `--mode=class-aware --scenario=disconnected --output=results/live-disconnected` | No route during outage; source-rejected offers still count in delivery |
| Source/transit missing route | `--mode=class-aware --scenario=missing-route --output=results/live-missing` | probes.csv and routing-errors.csv at 10.123 s |
| Remove dwell | `--mode=class-aware --scenario=congestion --dwell=0 --output=results/live-no-dwell` | More switching; compare with default congestion, not another workload |
| Remove smoothing | `--mode=class-aware --scenario=congestion --alpha=1 --output=results/live-no-smoothing` | Delay and route-choice effects |
| Remove hysteresis | `--mode=class-aware --scenario=congestion --threshold=0 --output=results/live-no-hysteresis` | Increased willingness to change routes |
| Choose a cost profile | `--mode=stable --policy=latency --scenario=congestion --output=results/live-latency` | Compare shortest/congestion/reliability/balanced with the same seed/run |
| Additional fabric | `--mode=class-aware --scenario=congestion --topology=extended --output=results/live-extended` | topology.json: 11 nodes and longer corridors |
| Rank limitation | `--mode=class-aware --scenario=active-failure --topology=detour --output=results/live-detour` | Physical alternative excluded by initial hop ranks |
| Diagnostic detour | `--mode=class-aware --scenario=active-failure --topology=detour --loop-safe=0 --output=results/live-detour-open` | Repair becomes possible; diagnostic only |

Example copyable live command and verification:

```powershell
.\routemind.cmd run --mode=class-aware --scenario=active-failure --pcap=1 --output=results/live-repair
.\routemind.cmd verify results/live-repair
Get-Content results/live-repair/summary.json
Import-Csv results/live-repair/routes.csv | Format-Table
```

Additional inputs: `--interval=0.5` changes sampling frequency; `--duration=30`
changes simulation length; `--seed=42 --run=2` changes the workload realization.
Hold these identical across compared policies. A larger interval can change
failure detection delay. Remaining load scenarios are `steady`, `failure`, and
`combined`. `failure`/`combined` cut a predetermined corridor; an adaptive realtime
path may already avoid it, so use `active-failure` to demonstrate measured repair.

Calibration checks low and saturated UDP loads at aligned/unaligned sampling
intervals and independently verifies telemetry against raw event journals:

```powershell
.\routemind.cmd calibrate --output=results/live-calibration
```

## Evidence to put on screen

| File | Purpose |
|---|---|
| DEMO.md / section REPORT.md | Side-by-side measurements and exact parameter records |
| summary.json | Aggregate packet metrics, source rejections, measured failure/repair times |
| topology.json | Nodes, directed links, capacity, propagation delay and interfaces |
| routes.csv / decisions.csv | Selected realtime/bulk paths; dwell, hysteresis, failure decisions |
| telemetry.csv | Measured per-link utilization, queue occupancy and local drop proxy |
| tables.csv / forwarding.csv | Installed table epochs and actual IPv4 forwarding |
| ack-receipts.csv | Actual reverse-direction TCP ACK delivery |
| realtime-packets.csv / udp-offers.csv | Received delays and correctness-scenario fixed offers |
| probes.csv / routing-errors.csv | Unknown-destination socket send and native routing callbacks |
| flow-monitor.xml / flows.csv | IP flow accounting after drain |
| capture*.pcap | Packet inspection in Wireshark if already available |
| verification.log / manifest.json | Passed invariants, matched inputs and source/build provenance |

For the missing-route probes, `send_result=-1` identifies the rejected source
send; a positive result means the socket accepted the transit probe, which is
then dropped at the next router. Socket error values can remain stale after a
successful send. PCAPs on idle interfaces can contain only the 24-byte header.

Existing presentation-ready charts are in `results/figures/`; explanations and
limits are in [EVIDENCE_REPORT.md](EVIDENCE_REPORT.md). They describe the prior
replicated studies, not newly estimated uncertainty from this one-trial demo.

## Statements to keep precise

- p95 delay includes received packets only: always show delivery alongside it.
- The native console's `received=rx/tx` uses accepted source sends. For outage
  cases, use `realtime_pdr` and `realtime_offered_packets` in the report/summary
  to include source-rejected offers in the delivery denominator.
- Route changes count accepted source path changes after initial installation;
  this is a churn proxy, not measured control-plane traffic.
- `link_restoration_time_s` is scheduled link-up. The legacy `recovery_time_s`
  aliases it; use `realtime_route_repair_delay_ms` and `realtime_recovery_delay_ms`
  for measured route repair and qualifying post-repair packet delivery.
- DSCP classification and separate objectives do not reserve bandwidth or promise QoS.
- Telemetry is direct and centralized; tables install synchronously. Control
  traffic, CPU costs and installation delays are not modeled. The drop term is
  a local queue-drop proxy, not an independently measured end-to-end reliability guarantee.
- Controlled realtime/bulk routes have rank/table/ACK checks. Do not generalize
  that audit to all background destinations or claim deployment readiness.
