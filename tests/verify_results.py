"""Verify simulator artifacts against independent packet/forwarding evidence."""
import argparse
import csv
import json
import math
import itertools
from collections import deque
from pathlib import Path
from measurement_checks import verify_calibration, verify_recovery
from forwarding_checks import verify_forwarding


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def verify(directory):
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["backend"] == "ns-3.46.1", "wrong backend"
    assert 0 < summary["realtime_rx_packets"] <= summary["realtime_tx_packets"]
    assert 0 < summary["realtime_pdr"] <= 1
    if summary["scenario"] == "calibration":
        assert summary["mode"] == "static" and summary["bulk_received_bytes"] == 0
    else:
        assert summary["bulk_received_bytes"] > 0, "TCP never delivered"
    assert summary["unaccounted_flow_packets"] == 0, "queues/FlowMonitor did not drain"
    packets = read_csv(directory / "realtime-packets.csv")
    assert len(packets) == summary["realtime_rx_packets"]
    assert len({p["sequence"] for p in packets}) == len(packets)
    delays = sorted(float(p["delay_ms"]) for p in packets)
    p95 = delays[math.ceil(.95*len(delays))-1]
    assert abs(p95-summary["realtime_p95_delay_ms"]) < .001, "tail delay mismatch"
    routes = read_csv(directory / "routes.csv")
    if summary.get("schema_version", 1) >= 2:
        telemetry = read_csv(directory / "telemetry.csv")
        verify_recovery(directory, summary, packets, routes, telemetry)
        flows = read_csv(directory / "flows.csv")
        for flow in flows:
            assert int(flow["tx_packets"]) == int(flow["rx_packets"]) + int(flow["lost_packets"]), "IP packet accounting mismatch"
        realtime_flows = [flow for flow in flows if flow["destination_port"] == "9000"]
        assert sum(int(flow["tx_packets"]) for flow in realtime_flows) == summary["realtime_tx_packets"]
        assert sum(int(flow["rx_packets"]) for flow in realtime_flows) == len(packets)
        for packet in packets:
            assert abs((float(packet["time"]) - float(packet["tx_time"])) * 1000 - float(packet["delay_ms"])) < 1e-6
        if summary["scenario"] == "calibration":
            verify_calibration(directory, summary, telemetry)
    assert sum(int(row["changed"]) for row in routes) == summary["route_changes"]
    for route in routes:
        if route["path"] == "unreachable":
            continue
        path = route["path"].split("-")
        assert path[0] == "0" and path[-1] == "6"
        assert len(path) == len(set(path)), "loop in installed path"
    topology = json.loads((directory / "topology.json").read_text())
    if summary.get("custom_config"):
        requested = json.loads((directory.parent / "scenario.json").read_text())
        assert requested["custom"] and topology["nodes"] == requested["network"]["nodes"]
        expected_links = {(min(link["from"],link["to"]),max(link["from"],link["to"])):link
                          for link in requested["network"]["links"]}
        actual_links = {(min(link["from"],link["to"]),max(link["from"],link["to"]))
                        for link in topology["directed_links"]}
        assert actual_links == set(expected_links), "custom connectivity differs from requested network"
        for link in topology["directed_links"]:
            expected = expected_links[min(link["from"],link["to"]),max(link["from"],link["to"])]
            assert link["capacity_mbps"] == expected["capacity"] and link["delay_ms"] == expected["delay"]
        for row in telemetry:
            expected = expected_links[min(int(row["from"]),int(row["to"])),max(int(row["from"]),int(row["to"]))]
            assert float(row["queue_limit_bytes"]) == expected["queue"]
        traffic = requested["traffic"]
        assert summary["realtime_application_rate_mbps"] == traffic["udp_rate"]
        assert summary["realtime_packet_bytes"] == traffic["packet_bytes"]
        assert summary["background_rate_mbps"] == traffic["background_rate"]
        assert summary["background_start_s"] == traffic["background_start"]
        assert all(int(row["payload_bytes"]) == traffic["packet_bytes"] - 20 for row in packets)
        if summary["scenario"] in {"failure","combined"}:
            assert summary["failure_time_s"] == requested["failure"]["down"]
            assert summary["link_restoration_time_s"] == requested["failure"]["up"]
            assert (summary["failure_from"],summary["failure_to"]) == (requested["failure"]["from"],requested["failure"]["to"])
    next_hops = {(int(link["from"]),int(link["interface"])):int(link["to"])
                 for link in topology["directed_links"]}
    incoming = {node: [] for node in range(topology["nodes"])}
    for link in topology["directed_links"]:
        incoming[link["to"]].append(link["from"])
    ranks = {topology["receiver"]: 0}
    pending = deque([topology["receiver"]])
    while pending:
        target = pending.popleft()
        for previous in incoming[target]:
            if previous not in ranks:
                ranks[previous] = ranks[target]+1
                pending.append(previous)
    realtime_routes = [r for r in routes if r["class"] == "1"]
    verified = 0
    forwarding = read_csv(directory / "forwarding.csv")
    if summary.get("schema_version", 1) >= 3:
        verify_forwarding(directory, summary, topology, forwarding, packets)
    visits = set()
    revisits = 0
    for event in forwarding:
        if event["class"] == "1":
            node, interface = int(event["node"]), int(event["interface"])
            next_node = next_hops[(node,interface)]
            if summary.get("loop_safe", False):
                assert ranks[node] > ranks[next_node], "actual forwarding violated fixed destination rank"
            if summary["failure_time_s"] is not None and summary["failure_time_s"] <= float(event["time"]) < summary.get("link_restoration_time_s", summary["recovery_time_s"]):
                assert {node,next_node} != {summary.get("failure_from", 2),summary.get("failure_to", 5)}, "forwarded through down interface"
            visit = (event["packet_uid"],event["node"])
            revisits += visit in visits
            visits.add(visit)
        if event["class"] != "1" or event["node"] != "1":
            continue
        stamp = float(event["time"])
        applicable = [r for r in realtime_routes if float(r["time"]) <= stamp+1e-9]
        assert applicable, "forwarding predates installation"
        expected = applicable[-1]["path"].split("-")
        assert expected != ["unreachable"], "forwarded an unreachable route"
        assert next_hops[(1,int(event["interface"]))] == int(expected[2]), "packets ignored policy route"
        verified += 1
    assert verified > 50, "insufficient actual realtime forwarding evidence"
    if summary.get("loop_safe", False):
        assert revisits == 0, "rank-constrained realtime packet revisited a forwarding node"
    if summary["scenario"] in ["failure","combined"] and summary["mode"] != "static" and not summary.get("custom_config"):
        # This specific scenario has alternate live paths: all installed controlled
        # routes after detection must exclude the failed 2->5 edge until recovery.
        for row in routes:
            if 14+summary["interval_s"] <= float(row["time"]) < 20:
                assert "2-5" not in row["path"], "route still uses failed link"
    print(f"PASS {directory.name}: {len(packets)} delivery samples, {verified} forwarding checks, {revisits} revisits")


def verify_directory(directory):
    if (directory / "manifest.json").exists():
        manifest = json.loads((directory / "manifest.json").read_text())
        assert manifest["status"] == "complete"
        config = manifest["config"]
        if manifest.get("kind") == "study":
            expected = {variant["id"] for variant in config["variants"]}
            assert len(manifest["completed"]) == len(expected) and set(manifest["completed"]) == expected
            for name in manifest["completed"]:
                child = json.loads((directory / name / "manifest.json").read_text())
                assert child["runtime"] == manifest["runtime"], "build changed between variants"
                verify_directory(directory / name)
            return
        if manifest.get("kind") == "calibration":
            expected = {case["name"] for case in config["cases"]}
        else:
            expected = {f"{scenario}-run{run}-{mode}" for scenario, run, mode in
                        itertools.product(config["scenarios"], config["runs"], config["modes"])}
        assert len(manifest["completed"]) == len(expected) and set(manifest["completed"]) == expected, "matrix case coverage mismatch"
        runtime = manifest.get("runtime", {})
        if "simulation_source_sha256" in runtime:
            assert all(manifest["source_sha256"].get(path) == digest for path, digest in
                       runtime["simulation_source_sha256"].items()), "manifest source/build mismatch"
            assert manifest["executable_sha256"] == runtime["executable_sha256"], "manifest executable mismatch"
        for name in manifest["completed"]:
            verify(directory / name)
    else:
        verify(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    verify_directory(args.directory)


if __name__ == "__main__":
    main()
