"""Verify installed trees, actual forwarding, TCP ACK arrivals and missing-route probes."""
import csv
from collections import defaultdict, deque


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def verify_forwarding(directory, summary, topology, forwarding, packets):
    owners = {link["neighbor_ip"]: link["to"] for link in topology["directed_links"]}
    neighbors = {(link["from"], link["interface"]): link["to"] for link in topology["directed_links"]}
    incoming = defaultdict(list)
    for link in topology["directed_links"]:
        incoming[link["to"]].append(link["from"])
    ranks = {}
    for owner in [0, 6]:
        rank = {owner: 0}
        pending = deque([owner])
        while pending:
            current = pending.popleft()
            for previous in incoming[current]:
                if previous not in rank:
                    rank[previous] = rank[current] + 1
                    pending.append(previous)
        ranks[owner] = rank

    entries, trees = {}, defaultdict(dict)
    for row in rows(directory / "tables.csv"):
        epoch, node, traffic_class = int(row["epoch"]), int(row["node"]), int(row["class"])
        destination, next_hop = row["destination"], int(row["next"])
        key = epoch, node, traffic_class, destination
        assert key not in entries, "duplicate table entry"
        entries[key] = row
        trees[epoch, traffic_class, destination][node] = next_hop
        if next_hop < 0:
            assert int(row["interface"]) == -1
            continue
        assert neighbors[node, int(row["interface"])] == next_hop
        if summary["loop_safe"]:
            assert ranks[owners[destination]][node] > ranks[owners[destination]][next_hop]
        failure, restoration = summary["failure_time_s"], summary["link_restoration_time_s"]
        if failure is not None and failure <= float(row["time"]) < restoration:
            assert {node, next_hop} != {summary["failure_from"], summary["failure_to"]}, "installed down-link entry"
    for (_, _, destination), tree in trees.items():
        assert len(tree) == topology["nodes"], "incomplete tree journal"
        for source in tree:
            seen, node = set(), source
            while node != owners[destination] and tree[node] >= 0:
                assert node not in seen, "loop in installed destination tree"
                seen.add(node)
                node = tree[node]

    acknowledgments = defaultdict(list)
    checked = 0
    for event in forwarding:
        if event["destination"] not in owners or owners[event["destination"]] not in {0, 6}:
            continue  # Explicit unknown-destination integration probes are checked separately.
        node, interface = int(event["node"]), int(event["interface"])
        installed = entries[int(event["epoch"]), node, int(event["class"]), event["destination"]]
        assert int(installed["interface"]) == interface, "actual forwarding ignored installed table epoch"
        assert float(installed["time"]) <= float(event["time"])
        checked += 1
        if event["protocol"] == "6" and event["source_port"] == "9001" and event["tcp_flags"] == "16" and event["tcp_payload_bytes"] == "0":
            assert event["class"] == "0" and owners[event["destination"]] == 0, "TCP ACK classified/routed incorrectly"
            acknowledgments[event["packet_uid"]].append(event)
    assert checked > 50
    receipts = rows(directory / "ack-receipts.csv")
    assert len(receipts) == summary["tcp_ack_ip_receipts"]
    assert bool(receipts) == (summary["tcp_workload"] != "disabled")
    verified_acks = 0
    for receipt in receipts:
        assert receipt["class"] == "0" and owners[receipt["source"]] == 6 and owners[receipt["destination"]] == 0
        assert int(receipt["ack_number"]) > 0
        path = acknowledgments.get(receipt["packet_uid"], [])
        if summary["audit_forwarding"]:
            assert path, "ACK receipt lacks complete forwarding evidence"
        if not path:
            continue
        assert int(path[0]["node"]) == 5 and int(path[-1]["node"]) == 1
        for previous, following in zip(path, path[1:]):
            assert neighbors[int(previous["node"]), int(previous["interface"])] == int(following["node"])
        assert neighbors[int(path[-1]["node"]), int(path[-1]["interface"])] == 0
        assert float(path[-1]["time"]) <= float(receipt["time"])
        verified_acks += 1
    if summary["tcp_workload"] != "disabled":
        assert verified_acks > 0, "no reverse-path TCP ACK independently verified"

    scenario = summary["scenario"]
    if scenario == "active-failure":
        assert summary["realtime_path_affected_by_failure"], "failure missed the active realtime path"
        if summary["mode"] != "static":
            # Independent reachability reference: apply the same fixed-rank restriction,
            # then remove the failed physical link. A real detour can be ineligible.
            def reachable(constrained):
                adjacency = defaultdict(list)
                for link in topology["directed_links"]:
                    a, b = link["from"], link["to"]
                    if {a, b} == {summary["failure_from"], summary["failure_to"]}:
                        continue
                    if not constrained or ranks[6][a] > ranks[6][b]:
                        adjacency[a].append(b)
                seen, pending = {0}, deque([0])
                while pending:
                    for node in adjacency[pending.popleft()]:
                        if node not in seen:
                            seen.add(node); pending.append(node)
                return 6 in seen
            assert reachable(False), "active-failure scenario should retain a physical alternate"
            if reachable(summary["loop_safe"]):
                assert summary["realtime_recovery_delay_ms"] is not None
                assert summary["realtime_route_ready_time_s"] <= summary["failure_time_s"] + summary["interval_s"] + 1e-8
            else:
                assert summary["realtime_route_ready_time_s"] is None and summary["realtime_recovery_delay_ms"] is None
        else:
            assert summary["realtime_route_ready_time_s"] is None
    if scenario == "disconnected":
        assert summary["realtime_path_affected_by_failure"] and summary["realtime_route_ready_time_s"] is None
        assert summary["realtime_first_delivery_after_failure_time_s"] is None
        if summary["mode"] != "static":
            routes = rows(directory / "routes.csv")
            assert any(row["class"] == "1" and row["path"] == "unreachable" for row in routes)
            assert any(row["class"] == "1" and row["path"] != "unreachable" and
                       float(row["time"]) >= summary["restoration_observed_time_s"] for row in routes)
        assert summary["realtime_first_delivery_after_restoration_time_s"] is not None
        assert any(float(row["time"]) > summary["link_restoration_time_s"] for row in packets)
    if scenario == "missing-route":
        probes = rows(directory / "probes.csv")
        errors = rows(directory / "routing-errors.csv")
        assert {row["kind"] for row in probes} == {"output-missing", "input-missing"}
        for probe in probes:
            output = probe["kind"] == "output-missing"
            assert (int(probe["send_result"]) < 0) == output
            assert any(row["stage"] == ("output" if output else "input") and
                       row["node"] == ("0" if output else "1") and row["packet_uid"] == probe["packet_uid"] and
                       row["destination"] == probe["destination"] for row in errors), "missing-route callback not exercised"
    if summary["udp_generator"] == "fresh-datagram":
        offered = rows(directory / "udp-offers.csv")
        assert len(offered) == summary["realtime_offered_packets"]
        assert len({row["sequence"] for row in offered}) == len(offered)
        assert len(offered) == round((summary["duration_s"] - 4) * 100) - 1
        assert all(int(row["sequence"]) == index and abs(float(row["time"]) - (1.01 + .01*index)) < 1e-8
                   for index, row in enumerate(offered)), "offered UDP workload changed"
        assert sum(int(row["accepted"]) for row in offered) == summary["realtime_tx_packets"]
        assert sum(row["accepted"] == "0" for row in offered) == summary["realtime_source_rejected_packets"]
        assert abs(summary["realtime_pdr"] - len(packets)/len(offered)) < 1e-9
    print(f"  tables/ACKs: {len(trees)} installed trees, {checked} forwarding events, {verified_acks} ACK delivery paths")
