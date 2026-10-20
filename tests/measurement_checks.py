"""Independent checks of NS-3 calibration journals and failure/delivery timing."""
import csv
import json
import math
from collections import defaultdict


def rows(path):
    with path.open(newline="") as stream:
        yield from csv.DictReader(stream)


def equal_optional(actual, expected, label, tolerance=1e-6):
    assert (actual is None) == (expected is None), f"{label}: null/value mismatch"
    if actual is not None:
        assert math.isfinite(actual) and abs(actual - expected) < tolerance, f"{label}: {actual} != {expected}"


def verify_recovery(directory, summary, packets, routes, telemetry):
    events = list(rows(directory / "events.csv"))
    names = {row["event"]: float(row["time"]) for row in events}
    failure = names.get("link-down")
    restoration = names.get("link-up")
    equal_optional(summary["failure_time_s"], failure, "failure event")
    equal_optional(summary["link_restoration_time_s"], restoration, "restoration event")
    equal_optional(summary["recovery_time_s"], restoration, "legacy restoration alias")
    failed = (summary.get("failure_from", 2), summary.get("failure_to", 5))
    expected_failure = summary["scenario"] in {"failure", "combined", "active-failure", "disconnected"}
    assert expected_failure == (failure is not None), "missing/unexpected failure event"
    if expected_failure and not summary.get("custom_config"):
        assert (failure, restoration) == ((14.07, 20.11) if summary["scenario"] in
                                         {"active-failure", "disconnected"} else (14, 20))

    def observed(up, after):
        return next((float(row["time"]) for row in telemetry if after is not None and
                     (int(row["from"]), int(row["to"])) == failed and row["up"] == str(up) and
                     float(row["time"]) >= after), None)

    detected = observed(0, failure)
    restored = observed(1, restoration)
    equal_optional(summary["failure_observed_time_s"], detected, "failure observation")
    equal_optional(summary["restoration_observed_time_s"], restored, "restoration observation")
    equal_optional(names.get("observed-down"), detected, "failure event journal")
    equal_optional(names.get("observed-up"), restored, "restoration event journal")
    equal_optional(summary["failure_detection_delay_ms"], None if detected is None else
                   (detected - failure) * 1000, "failure detection delay", 1e-5)
    for occurrence, observation in [(failure, detected), (restoration, restored)]:
        if occurrence is not None:
            assert 0 <= observation - occurrence <= summary["interval_s"] + 1e-8

    realtime = [row for row in routes if row["class"] == "1"]

    def path_at(stamp, before=False):
        applicable = [row for row in realtime if float(row["time"]) < stamp or
                      (not before and float(row["time"]) == stamp)]
        return applicable[-1]["path"].split("-") if applicable else []

    def broken(path):
        return not path or path == ["unreachable"] or any(
            {int(a), int(b)} == set(failed) for a, b in zip(path, path[1:]))

    affected = None if failure is None else broken(path_at(failure, before=True))
    assert summary["realtime_path_affected_by_failure"] == affected
    ready = next((float(row["time"]) for row in telemetry if detected is not None and
                  (int(row["from"]), int(row["to"])) == failed and
                  detected <= float(row["time"]) < restoration and
                  not broken(path_at(float(row["time"])))), None)
    equal_optional(summary["realtime_route_ready_time_s"], ready, "route readiness")
    equal_optional(names.get("realtime-route-ready"), ready, "route readiness event journal")
    equal_optional(summary["realtime_route_repair_delay_ms"],
                   (ready - failure) * 1000 if affected and ready is not None else None,
                   "route repair delay", 1e-5)

    def first_delivery(after, until=None):
        return next((float(row["time"]) for row in packets if after is not None and
                     float(row["tx_time"]) >= after and
                     (until is None or float(row["time"]) < until)), None)

    first_failure = first_delivery(failure, restoration)
    first_ready = first_delivery(ready, restoration)
    first_restored = first_delivery(restoration)
    equal_optional(summary["realtime_first_delivery_after_failure_time_s"], first_failure, "post-failure delivery")
    equal_optional(summary["realtime_first_delivery_after_route_ready_time_s"], first_ready, "post-ready delivery")
    equal_optional(summary["realtime_first_delivery_after_restoration_time_s"], first_restored, "post-restoration delivery")
    equal_optional(summary["realtime_recovery_delay_ms"],
                   (first_ready - failure) * 1000 if affected and first_ready is not None else None,
                   "packet recovery delay", 1e-5)


def verify_calibration(directory, summary, telemetry):
    topology = json.loads((directory / "topology.json").read_text())
    links = {(link["from"], link["to"]): link for link in topology["directed_links"]}
    measured = {(float(row["time"]), int(row["from"]), int(row["to"])): row for row in telemetry}
    pending_bytes = defaultdict(int)
    totals = defaultdict(int)
    previous = 0.0
    samples = 0
    for row in rows(directory / "wire-events.csv"):
        stamp, a, b, size = float(row["time"]), int(row["from"]), int(row["to"]), int(row["bytes"])
        if a != -1:
            # 320 application bytes + UDP(8) + IPv4(20) + PPP(2).
            assert size == 350, "unexpected calibration wire packet size"
            pending_bytes[a, b] += size
            totals[a, b] += 1
            continue
        for (a, b), link in links.items():
            dt = stamp - previous
            expected = pending_bytes[a, b] * 8 / (dt * link["capacity_mbps"] * 1e6) if dt else 0
            actual = float(measured[stamp, a, b]["utilization"])
            assert abs(actual - expected) < 1e-10, "wire-byte utilization mismatch"
            pending_bytes[a, b] = 0
        previous = stamp
        samples += 1
    assert samples > 10 and sum(pending_bytes.values()) == 0, "transmits outside sampled/drained window"

    # Reconstruct piecewise-constant occupancy from raw queue changes, independently
    # of the controller's accumulator; sample markers preserve equal-time ordering.
    state = {key: (0.0, 0, 0.0) for key in links}  # last time, occupancy, area
    previous = 0.0
    queue_samples = 0
    for row in rows(directory / "queue-events.csv"):
        stamp, a, b, size = float(row["time"]), int(row["from"]), int(row["to"]), int(row["queue_bytes"])
        keys = list(links) if a == -1 else [(a, b)]
        for key in keys:
            last, occupancy, area = state[key]
            area += (stamp - last) * occupancy
            if a == -1:
                expected = area / (stamp - previous) if stamp > previous else 0
                actual = float(measured[(stamp, *key)]["mean_queue_bytes"])
                assert abs(actual - expected) < 1e-6, "time-weighted queue integral mismatch"
                state[key] = stamp, occupancy, 0.0
            else:
                assert 0 <= size <= 60000
                state[key] = stamp, size, area
        if a == -1:
            previous = stamp
            queue_samples += 1
    assert queue_samples == samples
    assert all(occupancy == 0 for _, occupancy, _ in state.values()), "calibration queue did not drain"

    low_load = summary["realtime_application_rate_mbps"] <= 6 * 320 / 350
    path = [(0, 1), (1, 2), (2, 5), (5, 6)]
    assert not set(totals).difference(path), "unexpected calibration traffic/path"
    assert totals[0, 1] == summary["realtime_tx_packets"]
    assert totals[5, 6] == summary["realtime_rx_packets"]
    if low_load:
        assert all(totals[key] == summary["realtime_tx_packets"] for key in path)
    previous = 0.0
    checked = 0
    for row in telemetry:
        a, b, stamp = int(row["from"]), int(row["to"]), float(row["time"])
        if (a, b) != (1, 2):
            continue
        dt = stamp - previous
        if previous >= 2 and stamp <= summary["duration_s"] - 4:
            expected = min(1, summary["realtime_application_rate_mbps"] * 350 / 320 / 6)
            # Whole packets are charged at TxBegin; one packet can cross an interval edge.
            assert abs(float(row["utilization"]) - expected) <= 350 * 8 / (dt * 6e6) + 1e-8
            queue = float(row["mean_queue_bytes"])
            if low_load:
                assert queue < 1e-6
            else:
                fill_seconds = 60000 * 8 / ((summary["realtime_application_rate_mbps"] * 350 / 320 - 6) * 1e6)
                if previous >= 2 + fill_seconds:
                    assert queue > 50000
            checked += 1
        previous = stamp
    assert checked > 10
    if not low_load and fill_seconds < summary["duration_s"] - 5:
        assert summary["realtime_pdr"] < 1, "saturated calibration should drop packets"
    print(f"  calibration: {samples} byte/queue intervals reconstructed, {checked} analytic rate checks")
