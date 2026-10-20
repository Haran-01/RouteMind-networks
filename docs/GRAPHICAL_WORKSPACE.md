# RouteMind graphical workspace

## Launch

From the project directory:

```powershell
.\routemind.cmd build --jobs 4
.\routemind.cmd gui
```

The launcher opens `http://127.0.0.1:8765` in the default browser. Keep its terminal
open; the application runs entirely on this computer. Use Ctrl+C in that terminal
to stop it. `--port 8766` chooses another port; `--no-browser` leaves opening the
page to you. There are no frontend packages to install or external assets to fetch.
The build step is needed after changing simulation source, not before every run.

## First demonstration

1. Keep **Parallel corridors**, **Burst traffic**, and **Class-aware** selected.
2. Click **Compare all four modes**. Modes execute sequentially with identical
   network/traffic settings, seed and run stream. Sampling progress comes from
   the native simulator's `progress.csv`; it is simulation time, not elapsed time.
3. Wait for **Experiment verified**. Cases appear only after their artifact
   verifier passes. Inspect all four metrics together, including delivery.
4. Select a results row or the mode selector to view that case. Scrub or play
   the recorded timeline: actual selected realtime/bulk routes are highlighted,
   and failed links appear muted red during their recorded outage.
5. Inspect **Routes & events** and download files from **Artifacts**. Completed,
   failed, cancelled and interrupted jobs are retained in **Run history**.

The delay chart shows mean received-packet delay in half-second bins. Utilization
shows the highest measured directed-link value at each telemetry sample; charging
whole wire frames at transmission start can produce slight boundary overshoots.
This is recorded NS-3 evidence playback, not a live packet animation or fabricated
real-time feed. During simulation the UI shows measured simulation-clock progress.
Stability/traffic settings can be changed for a new experiment; editing them clears
the displayed results so prior metrics are not attached to new inputs.

For an actual route-repair demonstration, choose **Active-path failure** with
customization off. **Link failure** and **Congestion + failure** cut a specified
corridor which may already be unused by the realtime path. **Disconnection** has
no physical alternative. **Missing-route probes** exercise source and transit
errors. **Telemetry calibration** automatically selects static/parallel, exposes
the UDP calibration rate and runs a single verified UDP-only case.

## Custom networks and traffic

Enable **Customize network & traffic**, or click **Edit network**. A custom
experiment accepts:

- 8–24 nodes, including the existing canonical hosts/routers; 7–80 undirected links.
- Link capacity 1–1,000 Mbps, propagation delay 0.01–20 ms and byte queues
  from 2,000–120,000 bytes, applied independently to both directions.
- Realtime UDP 0.032–2 Mbps with 64–1,400-byte application packets, including
  the 20-byte sequence/timestamp/size header.
- Background UDP rate, start/stop times and burst on/off durations.
- A selected link-down/restoration schedule for failure/combined experiments.
- The routing, sampling, stability, seed/run and diagnostics settings used by
  template experiments.

**+ Router** adds one node and connects it to ingress/egress. **+ Link** adds a
router link; the link table edits capacities, delays and queues. Router links
can be removed; **Remove last router** removes the highest-numbered router and
its links. Dragging a node changes its visual position only. Validation requires
an initially connected graph with no duplicate or self-links.

Sender **0**, receiver **6**, background host **7**, and host attachments **0–1**,
**5–6**, **7–2** remain fixed to preserve the routing and forwarding-audit contract.
TCP NewReno is saturated in performance experiments. This version does not accept
arbitrary host roles, multiple user-defined application pairs or a configurable
TCP rate. Custom networks support steady/congestion/burst/failure/combined;
specialized correctness and calibration scenarios use the existing templates.
The GUI caps duration at 120 seconds; the native CLI still supports up to 3,600.

Export/import uses a validated JSON configuration containing `network.links`,
`traffic`, `failure`, routing controls and reproducibility settings. Import does
not execute anything. **Run experiment** executes the chosen mode; **Compare all
four modes** executes a matched comparison. The API and native file parser both
validate inputs. Long queues, low capacities or unsuitable failures can cause
verification failure; the application retains the failed evidence and error.

## Implementation and evidence

`web/` contains buildless HTML/CSS/JavaScript with local SVG topology/charts.
`scripts/gui.py` serves it on loopback and controls one experiment at a time.
`scripts/scenario_config.py` validates JSON and emits a bounded numeric network
file. NS-3 builds links, applications and scheduled failures from that file;
the portable policy algorithms remain unchanged in `src/core`.

Each job has a unique directory in ignored `results/gui/`, including:

- `scenario.json`: exact normalized user inputs, including the edited network.
- `network.txt`: native configuration for custom experiments.
- `manifest.json`: matrix settings, source/build hashes, scenario hash and custom
  network-file hash, completed case list and final state.
- A directory per native case with real measurements, tables, routes, flow
  accounting, error callbacks, optional PCAPs and `verification.log`.
- `REPORT.md` and CSV comparisons after all native cases pass verification.
- `run.json`: UI history, state and error record.

Stopping terminates the active native simulation or verifier. Cancelled runs
retain their files and are never certified complete. Interrupted jobs are marked
on server restart. Historical results remain visible even if the current build
later changes; new jobs must pass the source/executable runtime guard.

The server binds only to `127.0.0.1`, checks Host/Origin on API requests, accepts
bounded JSON bodies and restricts artifact downloads to each job's directory.
It runs processes with argument arrays and never accepts shell commands.
This is a local single-user application, not a deployed multi-user service.

## Verified implementation checks

Native build and the core contracts passed, along with 16 Python tests. Browser
checks exercised four-mode burst comparison, a nine-node custom network with
9 Mbps edited capacity, 0.512 Mbps / 640-byte UDP and link events at 12/19 seconds,
recorded failure coloring, downloads, import/export, cancellation, run history,
invalid-input handling, artifact path restriction and a 390-pixel mobile layout.
Custom verification independently compares the executed graph, capacities,
delays, queues, packet size/rate and failure schedule to the saved user inputs.
Twelve original correctness cases and eight baseline smoke cases passed with
the updated backend. Earlier smoke metrics remain unchanged.

Windows sandbox previews could bind a port but could not serve the host browser.
Browser QA used an approved host-side local server and the already installed
Chrome. Ordinary launch from the user's PowerShell uses that host environment.
No WSL, package installs or global PATH changes were required.
