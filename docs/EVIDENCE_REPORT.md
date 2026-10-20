# RouteMind evidence report

Date: 2026-10-20. Backend: genuine NS-3 3.46.1 packet simulation on native Windows.

The evidence supports a conditional trade-off: traffic-class objectives and a
stability controller can improve TCP goodput and reduce route changes, while their
delay benefit depends on load, parameters and the eligible path space. No policy
wins every metric, and fixed-rank safety can exclude a necessary detour.

## Executed evidence

The original evaluation has 200 cases. The subsequent sequential extension has
351 verified successful scenario runs, including deterministic correctness and
regression cases. These counts are not counts of independent workload replicates.

| Stage | Native cases | Evidence |
|---|---:|---|
| Default-setting correctness | 12 | [Packet/ACK/error checks](../results/phase1-correctness-v2/REPORT.md) |
| Independent mechanism removals | 75 | [Ablation report](../results/phase2-ablations/REPORT.md) |
| Predefined sensitivity screening | 63 | [Screening report](../results/phase3-screen/REPORT.md) |
| Identical grid on held-out seed | 105 | [Held-out report](../results/phase3-heldout/REPORT.md) |
| Three-topology policy comparisons | 72 | [Topology report](../results/phase4-topologies/REPORT.md) |
| Fixed-rank reachability boundary | 4 | [Rank diagnostic](../results/phase4-rank/REPORT.md) |
| Extended-topology correctness | 12 | [11-node correctness](../results/phase4-extended-correctness/REPORT.md) |
| Original smoke regression | 8 | [Regression results](../results/phase4-regression/REPORT.md) |

Each case passed artifact verification before its matrix completed. All accepted
IP packets were accounted for after drain. Default-rank cases had zero measured
realtime router revisits. The portable core has 46 contract checks and Python has
nine reporting/recovery regressions. Manifests preserve native source/build hashes,
configuration, matched seed/run workloads and per-case verification logs.

## Correctness before performance

The default-setting low-load test fails the fast link at 14.07 s. All four realtime
paths are affected; the controller observes the failure at 14.25 s. Adaptive,
stable and class-aware modes repair in 180 ms; the first qualifying realtime
delivery occurs after 190.522666 ms. Static does not repair during the outage.
The 11-node class-aware test observes first qualifying delivery after 191.755999 ms.
These are simulation timings for directly observable availability, not a distributed
failure-detection protocol or a zero-overhead deployed-network guarantee.

Full receiver disconnection produces no false repair claim. Fresh UDP offers remain
identical across modes: 2,199 scheduled sequences; 1,581 received. Adaptive modes
reject 600 at the source and lose 18 accepted packets; static accepts all and loses
618 later. Reported delivery uses offered sequences, while FlowMonitor accounts for
accepted IP transmissions. Original performance scenarios retain their original
OnOff generator; correctness scenarios avoid its cached-send behavior.

Table epochs prove actual next-hop compliance, and pure TCP ACKs are traced through
the reverse bulk route and local delivery at the sender. Explicit probes exercise
both source RouteOutput rejection and transit RouteInput's missing-route callback.

## Mechanism removals

Five paired realizations per congestion/burst/combined scenario use seed 314159.
Each variant removes one mechanism; fixed-rank safety is held constant.

| Congestion variant | UDP p95 ms | TCP Mbps | Path changes |
|---|---:|---:|---:|
| Class-aware default | 30.374 | 7.772 | 23.0 |
| No smoothing | 83.444 | 7.077 | 27.2 |
| No hysteresis | 30.374 | 7.764 | 29.0 |
| No dwell | 16.168 | 5.478 | 63.0 |
| Shared balanced objective | 83.285 | 7.474 | 30.8 |

The paired no-smoothing p95 increase is 53.070 ms, with 95% t interval
52.813--53.326 ms. Removing dwell lowers delay while increasing churn and reducing
TCP goodput. Mean TCP differences with intervals crossing zero should not be treated
as established gains or regressions. Full delivery and paired intervals are in the CSVs.

![Mechanism removal measurements](../results/figures/ablations.png)

## Sensitivity without post-hoc tuning

Both grids were saved before screening. Screening uses seed 271828 and runs 1--3;
held-out validation uses seed 161803 and runs 1--5. The same seven-setting one-factor
grid tests alpha {0.1,0.3,1}, dwell {0,1.5,3} seconds and threshold {0,0.12,0.25}.
The default is counted once; original defaults and cost weights remain unchanged.

Held-out congestion illustrates the competing objectives. Alpha 0.1 gives
35.282 ms / 8.981 Mbps / 15 changes; the default gives 30.374 / 7.772 / 23.
Dwell zero gives 16.064 / 5.424 / 63; dwell three seconds gives 84.265 / 7.998 / 15.
There is no declared combined objective that makes one of these a universal winner.

![Held-out dwell sensitivity](../results/figures/sensitivity-dwell.png)

## Topology dependence and the rank boundary

The 11-node extended fabric preserves three equal-hop corridors. Its congestion
adaptive/class-aware means are 21.274/30.796 ms p95, 5.682/7.762 Mbps TCP and
180/22 path changes. This preserves a throughput/churn versus delay trade-off on
another small topology; three realizations per scenario remain exploratory.

![Topology congestion measurements](../results/figures/topologies-congestion.png)

The unequal-hop fabric has a fast short corridor and a longer 18 Mbps alternative.
Ingress and the detour's first router have the same initial destination rank, so
the constrained controller cannot take that first detour hop. Under congestion all
constrained policies behave like static routing on the sole eligible corridor.

The separate deterministic outage test leaves that physical detour available.
Constrained adaptive and class-aware routing deliver 71.8963% of offered realtime
packets and cannot repair during the outage; unconstrained versions deliver
99.1814% and repair via the detour. The lower constrained received-packet p95
(6.314 versus 11.523 ms) does not compensate for the missing delivery samples.

![Rank constraint delivery boundary](../results/figures/rank-boundary.png)

This is a boundary diagnostic with one trial per condition and no uncertainty
interval. It does not establish unconstrained update safety: an earlier explicit
unconstrained test recorded 15 actual realtime router revisits. The useful finding
is the safety/reachability trade-off, not a recommendation to disable the restriction.

## Limits and reproducibility

The simulator uses centralized direct telemetry, synchronous installations and no
simulated telemetry/control traffic or controller CPU cost. Costs are heuristic;
there are no bandwidth reservations or end-to-end QoS guarantees. Evidence covers
three small native templates, bounded workload ranges and one-factor sweeps rather
than parameter interactions or arbitrary graph families. Intervals are nominal
per-comparison intervals without multiplicity adjustment; the studies are exploratory.
Deterministic repetitions have no confidence intervals. Delay always excludes lost packets and must be read
with delivery. TCP goodput uses the common observation window including drain.

See [methodology](METHODOLOGY.md), [status](STATUS.md), experiment JSON files and
the retained native manifests for exact settings. `routemind.cmd study` runs declared
variants, `verify` audits a matrix or whole study, and `plots` rebuilds seven SVG/PNG
figures using bundled ReportLab charts and Sharp rendering. The figure manifest
hashes the plotter, each input and every exported image. Generated results remain
ignored by version control. The final course presentation and more realistic
control/installation modeling remain future work.
