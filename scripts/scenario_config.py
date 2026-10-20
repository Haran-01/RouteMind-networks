"""Validated local workspace inputs; all measurements still come from NS-3."""
import copy
import math

MODES = ["static", "adaptive", "stable", "class-aware"]
SCENARIOS = ["steady", "congestion", "burst", "failure", "combined", "active-failure", "disconnected", "missing-route", "calibration"]


def template(name="parallel"):
    links = [[0, 1, 100, 1], [1, 2, 6, 1]]
    if name == "extended":
        links += [[2, 8, 6, 1], [8, 5, 6, 1], [1, 3, 12, 3], [3, 9, 12, 3], [9, 5, 12, 3],
                  [1, 4, 30, 6], [4, 10, 30, 6], [10, 5, 30, 6]]
    elif name == "detour":
        links += [[2, 5, 6, 1], [1, 3, 18, 3], [3, 4, 18, 3], [4, 5, 18, 3]]
    elif name == "parallel":
        links += [[2, 5, 6, 1], [1, 3, 12, 4], [3, 5, 12, 4], [1, 4, 30, 10], [4, 5, 30, 10]]
    else:
        raise ValueError("Unknown topology")
    links += [[5, 6, 100, 1], [7, 2, 100, 1]]
    return {"nodes": 11 if name == "extended" else 8,
            "links": [dict(zip(["from", "to", "capacity", "delay"], values), queue=60000) for values in links]}


DEFAULT = {"name": "Burst traffic experiment", "topology": "parallel", "custom": False,
           "mode": "class-aware", "scenario": "burst", "policy": "balanced",
           "duration": 26, "interval": .25, "alpha": .3, "dwell": 1.5, "threshold": .12,
           "seed": 42, "run": 1, "pcap": False, "loop_safe": True, "audit": False,
           "calibration_rate": .256,
           "network": template(), "traffic": {"udp_rate": .256, "packet_bytes": 320,
               "background_rate": 9.5, "background_start": 6.2, "background_stop": 18,
               "burst_on": .4, "burst_off": .4},
           "failure": {"from": 2, "to": 5, "down": 14, "up": 20}}


def validate(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT):
        raise ValueError("Configuration must be an object with supported fields")
    config = copy.deepcopy(DEFAULT)
    config.update(copy.deepcopy(raw))

    def number(obj, key, low, high, integer=False):
        value = obj.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        if integer and int(value) != value:
            raise ValueError(f"{key} must be an integer")
        obj[key] = int(value) if integer else float(value)

    if not isinstance(config["name"], str) or not 1 <= len(config["name"].strip()) <= 80:
        raise ValueError("Experiment name must have 1–80 characters")
    for key in ["custom", "pcap", "loop_safe", "audit"]:
        if type(config[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    for key, choices in [("topology", ["parallel", "extended", "detour"]), ("mode", MODES),
                         ("scenario", SCENARIOS), ("policy", ["shortest", "latency", "congestion", "reliability", "balanced"])]:
        if config[key] not in choices:
            raise ValueError(f"Unknown {key}")
    for key, low, high, integer in [("duration",24,120,False), ("interval",.01,2,False),
            ("alpha",.001,1,False), ("dwell",0,120,False), ("threshold",0,.99,False),
            ("seed",1,4294967295,True), ("run",1,4294967295,True), ("calibration_rate",.001,20,False)]:
        number(config,key,low,high,integer)
    if not config["custom"]:
        config["network"] = template(config["topology"])
        if config["scenario"] == "calibration" and (config["mode"] != "static" or config["topology"] != "parallel"):
            raise ValueError("Calibration requires static routing and the parallel topology")
        return config
    if config["scenario"] not in SCENARIOS[:5]:
        raise ValueError("Custom networks support steady, congestion, burst, failure and combined. Use templates for correctness/calibration scenarios.")
    net, traffic, failure = config["network"], config["traffic"], config["failure"]
    if not all(isinstance(value, dict) for value in [net, traffic, failure]):
        raise ValueError("Network, traffic and failure must be objects")
    number(net,"nodes",8,24,True)
    if not isinstance(net.get("links"), list) or not 7 <= len(net["links"]) <= 80:
        raise ValueError("Use 7–80 links")
    pairs = set()
    for link in net["links"]:
        if not isinstance(link, dict) or set(link) != {"from", "to", "capacity", "delay", "queue"}:
            raise ValueError("Every link needs from, to, capacity, delay and queue")
        for key, low, high, integer in [("from",0,net["nodes"]-1,True), ("to",0,net["nodes"]-1,True),
                ("capacity",1,1000,False), ("delay",.01,20,False), ("queue",2000,120000,True)]:
            number(link,key,low,high,integer)
        a, b = link["from"], link["to"]
        pair = tuple(sorted([a,b]))
        if a == b or pair in pairs:
            raise ValueError("Self-links and duplicate links are not supported")
        pairs.add(pair)
        for host, neighbor in [(0,1),(6,5),(7,2)]:
            if host in pair and neighbor not in pair:
                raise ValueError("Host attachments remain 0–1, 5–6 and 7–2")
    if not {(0,1),(5,6),(2,7)} <= pairs:
        raise ValueError("Keep the three host attachment links")
    reached = {0}
    for _ in range(net["nodes"]):
        for a,b in pairs:
            if a in reached or b in reached:
                reached.update([a,b])
    if len(reached) != net["nodes"]:
        raise ValueError("All nodes must be connected before the experiment starts")
    for key,low,high,integer in [("udp_rate",.032,2,False),("packet_bytes",64,1400,True),
            ("background_rate",.1,30,False),("background_start",2,config["duration"]-4,False),
            ("background_stop",3,config["duration"]-3,False),("burst_on",.05,5,False),("burst_off",.05,5,False)]:
        number(traffic,key,low,high,integer)
    if traffic["background_start"] >= traffic["background_stop"]:
        raise ValueError("Background stop must follow its start")
    for key in ["from", "to"]:
        number(failure,key,0,net["nodes"]-1,True)
    for key in ["down", "up"]:
        number(failure,key,3,config["duration"]-3,False)
    if failure["up"] <= failure["down"] + config["interval"]:
        raise ValueError("Restoration must follow failure by more than one measurement interval")
    if tuple(sorted([failure["from"],failure["to"]])) not in pairs:
        raise ValueError("The failure link must exist")
    return config


def write_network(config, path):
    net, traffic, failure = config["network"], config["traffic"], config["failure"]
    lines = [f"{net['nodes']} {len(net['links'])}"]
    lines += [" ".join(str(link[key]) for key in ["from","to","capacity","delay","queue"]) for link in net["links"]]
    lines.append(" ".join(map(str,[traffic[key] for key in ["udp_rate","packet_bytes","background_rate",
        "background_start","background_stop","burst_on","burst_off"]]+[failure[key] for key in ["from","to","down","up"]])))
    path.write_text("\n".join(lines)+"\n")
