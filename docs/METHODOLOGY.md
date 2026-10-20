# Experimental method

## Default network and offered traffic

    sender 0 -- ingress 1 -- fast 2 -------- egress 5 -- receiver 6
                         |                  |
                         +-- moderate 3 ----+
                         |                  |
                         +-- capacity 4 ----+
                              background 7 -- fast 2

Host links are 100 Mbps / 1 ms. The two links in each core corridor are respectively
6 Mbps / 1 ms, 12 Mbps / 4 ms, or 30 Mbps / 10 ms. Every directed device queue is
60,000 bytes. Point-to-point flow control is disabled so the instrumented device
queue is the relevant queue, rather than an unseen additional traffic-control queue.
There is no class-priority queue scheduling in the first implementation.

Realtime UDP uses DSCP 46, bulk TCP uses DSCP 0 and background UDP uses DSCP 8.
The source DSCP is read from SocketIpTosTag during the initial route query and
from the IPv4 header at transit routers. Routing is hop-by-hop using installed
traffic-class/destination tables; it is not just an offline path computation.

## Cost profiles

| Profile | Hop | Delay | Utilization | Queue fraction | Local drop proxy |
|---|---:|---:|---:|---:|---:|
| shortest | 1 | 0 | 0 | 0 | 0 |
| latency | 0.1 | 4 | 0.3 | 0.5 | 2 |
| congestion | 0.1 | 0.2 | 6 | 8 | 2 |
| reliability | 0.1 | 0.2 | 0.5 | 1 | 20 |
| balanced | 0.1 | 1 | 2 | 3 | 5 |

Delay is normalized by a fixed 10 ms reference. Queue waiting time is estimated as
mean queued bytes * 8 / link rate. Estimated delay adds configured propagation.
The queue fraction divides by 60,000 bytes. Utilization counts bytes at PhyTxBegin,
including point-to-point framing, divided by interval capacity. At interval edges,
whole-packet counting can slightly exceed 1; cost utilization is capped at 1 while
raw telemetry is retained. Local drop proxy is queue drops / (transmitted packets
+ queue drops) in an interval. Queue residence crossing intervals makes this an
approximate local indicator, not an exact loss probability. Down edges have infinite
cost. Every available edge has a positive hop contribution.

The weights are initial design choices, not learned optima. Correlated delay,
queue and utilization terms can count related congestion signals more than once.
Sensitivity experiments must precede any general claim of superiority.

## Control loop

At each interval boundary, integrate queue occupancy over elapsed simulation time,
read/reset counters, optionally smooth congestion measurements, then compute
reverse-Dijkstra destination trees. Availability is never smoothed. A down/up
transition resets the EWMA history for that edge.

The stable controller keeps one whole destination tree until the representative
ingress path improves by more than the fractional threshold and the dwell expires.
Any invalid installed branch permits a failure repair regardless of dwell. A
disconnected ingress becoming reachable also bypasses dwell. Ordinary changes are
evaluated with both old and new paths scored on the same current snapshot.

All trees for all routers are installed synchronously in one simulator callback.
No packet event executes halfway through that callback. This assumption avoids
partial-installation states but does not prove arbitrary asynchronous network
updates safe, or preclude every transient effect on packets already in flight.

The initial unconstrained experiment exposed real router revisits while packets
crossed two different acyclic trees. Default controlled routing therefore also
restricts edges to strictly decreasing initial destination hop rank. That rank
does not change during the experiment, so every permitted forwarding hop makes
fixed progress even across table updates. The constraint is identical in all four
modes and covers realtime and bulk; background retains its fixed shortest-path
objective. It can be disabled with `--loop-safe=0` and is recorded in summaries.
It can exclude useful detours in general topologies and is not a general solution
to arbitrary failure reachability. Report measured router revisits from packet
traces in both default and unconstrained experiments.

## Fair comparisons

Static keeps initial shortest paths; it has no adaptive failure rerouting. All
adaptive modes can use alternate live paths on failure. Do not claim a new failure
recovery algorithm solely by comparing against static blackholing.

Adaptive and stable share the selected global objective (balanced by default).
Class-aware uses latency for realtime and congestion for bulk, with the same stable
controller. Thus adaptive/stable studies stability; stable/class-aware studies the
effect of objectives. Use alpha=1, dwell=0 or threshold=0 for further ablations.

The background start time and offered rate are drawn before traffic generators are
installed, using the same explicit stream across modes. Applications have explicitly
assigned streams. Record seed and run index and verify matched workloads in the
report. Steady and failure scenarios have no varied stochastic workload, so repeated
run indices for them are consistency checks, not independent experimental evidence.

## Metrics and artifacts

Realtime samples use SeqTsSizeHeader and unique received sequence numbers. Delay is
simulation receive time minus application transmit timestamp. P95 uses nearest rank,
ceil(0.95*N). Mean absolute successive delay variation is reported under that exact
name. Delivery counts unique app packets received divided by app packets transmitted.
Missing/dropped packets have no delay sample; always interpret delay with delivery.

Realtime payload goodput excludes the sequence/timestamp header. TCP goodput is
PacketSink payload bytes. Both divide by the common [1 s, simulation end] observation
window; this includes the drain period and is different from active-period throughput.
FlowMonitor IP bytes are recorded separately and include IP headers. The summary
reports unaccounted IP packets after drain; integration verification requires zero.

Route-change count covers source 0 to receiver 6 in both realtime and bulk classes;
initial table installation is excluded. A table rebuild with the same controlled
path is recorded but not counted as a source path change. Actual realtime forwarding
events and a deterministic sample of bulk events are exported. Verification maps
interface IDs back to topology neighbors and checks policy compliance at ingress.

Comparison CSVs report means of run-level statistics. Paired-difference intervals
use differences within matched seed/run workloads. Single runs have no interval.
Student-t intervals assume independently varied workloads; they do not eliminate
small-sample or distribution-shape limitations. Report both benefits and regressions.
Both descriptive and paired CSVs omit intervals for deterministic steady/failure
workloads. Repeating their RNG run index does not create independent observations.

## Telemetry calibration

`routemind.cmd calibrate` uses the same NS-3 point-to-point fabric and measurement
callbacks, with static routing, realtime UDP only, and no TCP/background traffic.
It runs 0.256 and 8 Mbps application loads at 0.25 and 0.37 second sample intervals.
Application packet size is 320 bytes, including the sequence/timestamp header;
UDP, IPv4 and PPP produce 350-byte wire frames. At low load the expected fast-link
utilization is 0.256 * (350/320) / 6 = 0.04666667, with no queued residence or loss.
The 8 Mbps case saturates the 6 Mbps corridor and exercises backlog and drops.

Calibration-only `wire-events.csv` and `queue-events.csv` export raw device bytes
and queue transitions. Sample-boundary markers preserve simulator event ordering
when a transmission shares a timestamp with a sample. Offline verification sums
bytes and integrates piecewise-constant queue occupancy independently for every
sample and directed link. Analytic steady-rate checks allow one wire packet of
interval-boundary counting error. Queues must drain and per-flow packets must be
fully accounted for. This calibrates this configured device/queue setup only.

## Failure observation and packet recovery

For the scheduled 2--5 outage, `events.csv` records link-down/up, the first periodic
sample observing each availability transition, and the first sample with a usable
installed realtime ingress path during the outage. `realtime_path_affected_by_failure`
records whether the installed realtime path used the failed link before it went down.
Failure observation remains a centralized direct availability observation; no
distributed hello/probe protocol or telemetry-message delay is modeled.

Summary fields distinguish `failure_time_s`, `failure_observed_time_s`,
`realtime_route_ready_time_s` and actual realtime delivery times. Detection delay
is observation minus link-down. Route repair delay is readiness minus link-down,
only for an affected path. Realtime packet recovery delay is the first receive
time of a packet transmitted at or after readiness, minus link-down, with reception
strictly before link restoration. This excludes packets already in flight before
repair. The first delivery of a packet transmitted after failure is also recorded
separately, even if it precedes the controller's observation on an unaffected path.
First delivery after restoration similarly requires transmission at/after link-up.

Unaffected paths have null repair/recovery latency. An affected static path that
remains broken until link-up also has null repair/recovery latency, rather than an
artificial zero or a restoration time labeled as adaptive recovery. `recovery-summary.csv`
reports sample counts and affected counts; its repair/recovery means condition on
affected, successfully repaired paths. These groups may differ across modes, so
these means are descriptive and are not treated as paired causal effects.
The old `recovery_time_s` field is retained only as an alias for the new explicit
`link_restoration_time_s` field (scheduled link-up at 20 seconds).

`experiments/recovery_checks.json` samples at 0.37 seconds, so link-down at 14 seconds
is first observed at 14.06 seconds and restoration at 20 seconds at 20.35 seconds.
A 100-second dwell exceeds the simulation duration: an affected stable path must
still repair on failure. Artifact checks independently reconstruct observations,
readiness and first qualifying delivery from telemetry, routes and packet timestamps.

## Correctness and forwarding evidence

The active-failure/disconnected/missing-route correctness scenarios use fresh
320-byte UDP datagrams offered every 10 ms, independently of socket acceptance,
and 64 kbps TCP. `udp-offers.csv` records the same sequence/timing workload for
every mode, including source route rejections. Their delivery denominator is all
offers; `realtime_tx_packets` and FlowMonitor retain only accepted IP transmissions.
Existing scenarios retain NS-3 OnOff, whose failed sends are cached for retry.
`tcp_workload` and `udp_generator` identify these distinct workloads explicitly.
`tables.csv` records controlled destination table epochs; `forwarding.csv` records
the actual epoch and TCP headers. `ack-receipts.csv` proves local IP delivery of
pure TCP ACKs at the sender. Complete audits match each ACK's forwarding chain to
its receipt and verify every controlled installed tree is acyclic. `probes.csv`
and `routing-errors.csv` separately identify missing-route rejection at the source
and transit router. These diagnostics exercise NS-3 sockets and routing callbacks.

## Declared studies and additional topologies

The ablation study uses seed 314159, runs 1--5, and independently removes EWMA,
hysteresis, dwell or class-specific objectives. Both sensitivity grids were written
before screening: screening seed 271828/runs 1--3 and held-out seed 161803/runs 1--5.
The same seven-setting one-factor grid includes alpha {0.1,0.3,1}, dwell {0,1.5,3},
and threshold {0,0.12,0.25}, with defaults counted once. All profiles run congestion,
burst and combined scenarios. Defaults/weights remain unchanged and no winner is
selected from the held-out set. Small-sample paired intervals describe the tested
workload distribution; they do not establish general optimality.

`run_study.py` executes declared variants sequentially and each variant's matched
matrix with independent native processes. Each native case is artifact-verified.
Study comparisons validate seed/run, timing, load, generator, offered count,
topology and failure schedule. Deliberately changed parameters are recorded in
`variants.csv`; fixed-rank differences are allowed only when explicitly declared.
Comparison matrices also reject mismatched offered counts/generators. Raw manifests
and source/build hashes remain attached to the native runs, even after later code
or documentation updates.

`--topology=parallel` retains the original eight-node fabric. `extended` uses 11
nodes with corridors 1-2-8-5 (6 Mbps / 1 ms per link), 1-3-9-5 (12 Mbps / 3 ms),
and 1-4-10-5 (30 Mbps / 6 ms). Host and background links retain their original
settings. All corridor lengths are equal, so fixed destination rank admits them.

`detour` has an eight-node short corridor 1-2-5 (6 Mbps / 1 ms per link) and an
alternative 1-3-4-5 (18 Mbps / 3 ms per link). Ingress 1 and node 3 both initially
have destination-6 rank 3, so 1->3 is prohibited by strict rank decrease. A 2--5
failure leaves a physical route that the constrained controller cannot select.
The rank diagnostic compares this precise reachability trade-off under identical
fresh-datagram workloads and default stability parameters. It is one deterministic
case per mode/constraint, with no statistical interval or broad deployment claim.

The topology study uses seed 424242 and three runs per policy/scenario, comparing
policies within each topology. Its 72 cases cover congestion/burst, not arbitrary
graphs. Twelve further correctness cases exercise the 11-node fabric, including
failure of 2--8, full receiver disconnection and source/transit missing routes.

Figures use ReportLab's chart primitives and bundled Sharp SVG-to-PNG rendering.
Inputs, exported SVG/PNG files and plotter code are hashed in the figure manifest.
P95/TCP/churn plots show run-level means and Student-t intervals; deterministic
rank plots show the delivery fraction for each one-second transmit cohort, including
source rejections. Lost packets have no delay sample. Curves join tested settings
only; interpolation is a visual guide, not additional simulation evidence.

## Remaining validation

Future work includes broader graph families and interaction sweeps, all-destination
background auditing, route stretch/time-above-target metrics, telemetry/control
costs, delayed installation and asynchronous/probing-based recovery.
