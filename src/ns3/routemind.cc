#include "policy-routing.hpp"
#include "../core/routing.hpp"
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>

using namespace ns3;
namespace rm = routemind;

struct Direction {
    rm::Edge edge;
    Ptr<PointToPointNetDevice> device;
    uint32_t interface = 0;
    Ipv4Address neighbor;
    uint64_t bytes = 0, packets = 0, drops = 0;
    double changedAt = 0, queueArea = 0, queueNow = 0;
    bool observedUp = true;
    std::ostream* wireEvents = nullptr;
    std::ostream* queueEvents = nullptr;
};

static double TimeSeconds() { return Simulator::Now().GetSeconds(); }
static void QueueChanged(Direction* state, uint32_t, uint32_t value) {
    state->queueArea += state->queueNow * (TimeSeconds() - state->changedAt);
    state->changedAt = TimeSeconds();
    state->queueNow = value;
    if (state->queueEvents) *state->queueEvents << TimeSeconds() << ',' << state->edge.from
        << ',' << state->edge.to << ',' << value << '\n';
}
static void Transmit(Direction* state, Ptr<const Packet> packet) {
    state->bytes += packet->GetSize();
    ++state->packets;
    if (state->wireEvents) *state->wireEvents << TimeSeconds() << ',' << state->edge.from
        << ',' << state->edge.to << ',' << packet->GetSize() << '\n';
}
static void QueueDrop(Direction* state, Ptr<const Packet>) { ++state->drops; }
static std::string PathString(const rm::Tree& tree, uint32_t source) {
    std::ostringstream text;
    const auto path = rm::Path(tree, source);
    if (path.empty()) return "unreachable";
    for (size_t i = 0; i < path.size(); ++i) text << (i ? "-" : "") << path[i];
    return text.str();
}

static std::string JsonTime(double value) {
    if (value < 0) return "null";
    std::ostringstream text;
    text << std::setprecision(17) << value;
    return text.str();
}

struct Controller {
    NodeContainer nodes;
    std::deque<Direction> links;
    std::map<uint32_t, uint32_t> addressOwner;
    std::vector<Ptr<RouteMindRouting>> routers;
    std::map<std::pair<uint8_t, uint32_t>, rm::Tree> installed;
    std::map<std::pair<uint8_t, uint32_t>, double> lastChange;
    std::map<uint32_t, std::vector<double>> rank;
    std::string mode, policy = "balanced";
    bool loopSafe = true, auditForwarding = false;
    double interval = .25, duration = 26, previous = 0, dwell = 1.5, threshold = .12;
    rm::Smoother smoother{.3};
    std::ofstream telemetry, decisions, routes, forwarding, events, wireEvents, queueEvents;
    std::ofstream tables, routingErrors, ackReceipts, probes, progress;
    uint64_t epoch = 0, receivedAcks = 0;
    uint64_t routeChanges = 0, forwardingSamples = 0;
    double failureTime = -1, restorationTime = -1, failureObserved = -1, restorationObserved = -1;
    double realtimeRouteReady = -1;
    bool realtimeAffected = false;
    uint32_t failureFrom = 2, failureTo = 5;

    explicit Controller(const std::string& output, const std::string& selected,
                        double alpha, bool calibration = false) : mode(selected), smoother(alpha) {
        telemetry.open(output + "/telemetry.csv");
        decisions.open(output + "/decisions.csv");
        routes.open(output + "/routes.csv");
        forwarding.open(output + "/forwarding.csv");
        events.open(output + "/events.csv");
        tables.open(output + "/tables.csv");
        routingErrors.open(output + "/routing-errors.csv");
        ackReceipts.open(output + "/ack-receipts.csv");
        probes.open(output + "/probes.csv");
        progress.open(output + "/progress.csv");
        progress << "time,total\n";
        if (!telemetry || !decisions || !routes || !forwarding || !events || !tables ||
            !routingErrors || !ackReceipts || !probes) throw std::runtime_error("cannot open outputs");
        telemetry << std::setprecision(17); decisions << std::setprecision(17);
        routes << std::setprecision(17); forwarding << std::setprecision(17);
        events << std::setprecision(17) << "time,event,from,to\n";
        tables << std::setprecision(17) << "epoch,time,node,class,destination,next,interface\n";
        routingErrors << std::setprecision(17) << "time,node,stage,class,destination,packet_uid\n";
        ackReceipts << std::setprecision(17) << "time,packet_uid,source,destination,class,ack_number\n";
        probes << std::setprecision(17) << "time,kind,destination,packet_uid,send_result,socket_error\n";
        if (calibration) {
            wireEvents.open(output + "/wire-events.csv");
            queueEvents.open(output + "/queue-events.csv");
            if (!wireEvents || !queueEvents) throw std::runtime_error("cannot open calibration outputs");
            wireEvents << std::setprecision(17) << "time,from,to,bytes\n";
            queueEvents << std::setprecision(17) << "time,from,to,queue_bytes\n";
        }
        telemetry << "time,from,to,up,utilization,mean_queue_bytes,queue_limit_bytes,local_drop_ratio\n";
        decisions << "time,class,destination,install,reason,old_cost,new_cost,improvement\n";
        routes << "time,class,source,destination,path,reason,changed\n";
        forwarding << "time,node,class,destination,interface,packet_uid,epoch,source,protocol,source_port,destination_port,tcp_flags,tcp_payload_bytes\n";
    }
    void AddLink(uint32_t a, uint32_t b, double capacity, double delay, uint32_t queueBytes = 60000) {
        PointToPointHelper helper;
        helper.SetDeviceAttribute("DataRate", DataRateValue(DataRate(uint64_t(capacity * 1e6))));
        helper.SetChannelAttribute("Delay", TimeValue(MilliSeconds(delay)));
        helper.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", QueueSizeValue(QueueSize(std::to_string(queueBytes)+"B")));
        // One bounded device queue per direction: no hidden queue-disc backlog.
        helper.DisableFlowControl();
        auto devices = helper.Install(nodes.Get(a), nodes.Get(b));
        Ipv4AddressHelper addresses;
        const auto subnet = "10.1." + std::to_string(links.size() / 2 + 1) + ".0";
        addresses.SetBase(subnet.c_str(), "255.255.255.0");
        const auto assigned = addresses.Assign(devices);
        for (uint32_t side = 0; side < 2; ++side) {
            const uint32_t from = side ? b : a, to = side ? a : b;
            auto device = DynamicCast<PointToPointNetDevice>(devices.Get(side));
            auto ipv4 = nodes.Get(from)->GetObject<Ipv4>();
            const auto interface = uint32_t(ipv4->GetInterfaceForDevice(device));
            ipv4->SetForwarding(interface, true);
            links.emplace_back();
            auto& state = links.back();
            state.edge = {from, to, delay, capacity, 0, double(queueBytes), 0, 0, true};
            state.device = device;
            state.interface = interface;
            state.neighbor = assigned.GetAddress(1 - side);
            if (wireEvents.is_open()) state.wireEvents = &wireEvents;
            if (queueEvents.is_open()) state.queueEvents = &queueEvents;
            addressOwner[assigned.GetAddress(side).Get()] = from;
            device->TraceConnectWithoutContext("PhyTxBegin", MakeBoundCallback(&Transmit, &state));
            device->GetQueue()->TraceConnectWithoutContext("BytesInQueue", MakeBoundCallback(&QueueChanged, &state));
            device->GetQueue()->TraceConnectWithoutContext("Drop", MakeBoundCallback(&QueueDrop, &state));
        }
    }
    rm::Weights Weights(uint8_t trafficClass) const {
        if (trafficClass == 2 || mode == "static") return rm::Policy("shortest");
        if (mode == "class-aware") return rm::Policy(trafficClass == 1 ? "latency" : "congestion");
        return rm::Policy(policy);
    }
    uint32_t Source(uint32_t destination) const {
        return destination == 6 ? 0 : (destination == 0 ? 6 : 7);
    }
    std::vector<rm::Edge> Snapshot() {
        const double dt = TimeSeconds() - previous;
        // Boundary markers preserve event ordering when a transmit shares a sample timestamp.
        if (wireEvents.is_open()) wireEvents << TimeSeconds() << ",-1,-1,0\n";
        if (queueEvents.is_open()) queueEvents << TimeSeconds() << ",-1,-1,0\n";
        std::vector<rm::Edge> snapshot;
        for (auto& state : links) {
            state.queueArea += state.queueNow * (TimeSeconds() - state.changedAt);
            state.changedAt = TimeSeconds();
            state.edge.queueBytes = dt > 0 ? state.queueArea / dt : 0;
            state.edge.utilization = dt > 0 ? state.bytes * 8.0 / (dt * state.edge.capacityMbps * 1e6) : 0;
            const auto attempts = state.packets + state.drops;
            state.edge.loss = attempts ? double(state.drops) / attempts : 0;
            telemetry << TimeSeconds() << ',' << state.edge.from << ',' << state.edge.to << ',' << state.edge.up
                << ',' << state.edge.utilization << ',' << state.edge.queueBytes << ',' << state.edge.queueLimitBytes
                << ',' << state.edge.loss << '\n';
            if (state.edge.from == failureFrom && state.edge.to == failureTo && state.edge.up != state.observedUp) {
                if (state.edge.up) restorationObserved = TimeSeconds();
                else failureObserved = TimeSeconds();
                events << TimeSeconds() << ',' << (state.edge.up ? "observed-up" : "observed-down")
                    << ',' << failureFrom << ',' << failureTo << '\n';
            }
            state.observedUp = state.edge.up;
            snapshot.push_back(state.edge);
            state.bytes = state.packets = state.drops = 0;
            state.queueArea = 0;
        }
        previous = TimeSeconds();
        return snapshot;
    }
    void Compute(const std::vector<rm::Edge>& snapshot) {
        std::set<uint32_t> destinations;
        for (auto [address, owner] : addressOwner) destinations.insert(owner);
        for (uint8_t trafficClass = 0; trafficClass < 3; ++trafficClass) {
            for (uint32_t destination : destinations) {
                const auto key = std::make_pair(trafficClass, destination);
                const auto found = installed.find(key);
                const rm::Tree* current = found == installed.end() ? nullptr : &found->second;
                if (mode == "static" && current) continue;
                const auto weights = Weights(trafficClass);
                if (!rank.count(destination)) {
                    rank[destination] = rm::ShortestTree(nodes.GetN(), snapshot, destination, rm::Policy("shortest")).distance;
                }
                const auto eligible = loopSafe && trafficClass != 2
                    ? rm::ProgressiveEdges(snapshot, rank.at(destination)) : snapshot;
                auto candidate = rm::ShortestTree(nodes.GetN(), eligible, destination, weights);
                const bool stable = mode == "stable" || mode == "class-aware";
                const auto source = Source(destination);
                auto decision = rm::Decide(current, candidate, source, eligible, weights, TimeSeconds(), lastChange[key],
                                           stable && trafficClass != 2 ? dwell : 0,
                                           stable && trafficClass != 2 ? threshold : 0);
                // Adaptive baseline installs the recomputed complete tree even when
                // a branch changes without changing the representative ingress path.
                if (current && !stable && current->next != candidate.next) {
                    decision.install = true;
                    decision.reason = "adaptive-update";
                }
                if (destination == 6 && trafficClass < 2) {
                    decisions << TimeSeconds() << ',' << unsigned(trafficClass) << ',' << destination << ',' << decision.install
                        << ',' << decision.reason << ',' << decision.oldCost << ',' << decision.newCost
                        << ',' << decision.improvement << '\n';
                }
                if (decision.install) {
                    const bool changed = current && rm::Path(*current, source) != rm::Path(candidate, source);
                    if (changed && destination == 6 && trafficClass < 2) ++routeChanges;
                    if (destination == 6 && trafficClass < 2) {
                        routes << TimeSeconds() << ',' << unsigned(trafficClass) << ',' << source << ',' << destination
                            << ',' << PathString(candidate, source) << ',' << decision.reason << ',' << changed << '\n';
                    }
                    installed[key] = std::move(candidate);
                    lastChange[key] = TimeSeconds();
                }
            }
        }
        std::vector<RouteMindRouting::Table> tables(nodes.GetN());
        for (const auto& [key, tree] : installed) {
            for (const auto& [address, owner] : addressOwner) {
                if (owner != key.second) continue;
                for (const auto& state : links) {
                    if (tree.next[state.edge.from] == int(state.edge.to) && state.edge.up) {
                        tables[state.edge.from][{address, key.first}] = {state.neighbor, state.interface};
                    }
                }
            }
        }
        // No packet events execute halfway through this synchronous callback.
        ++epoch;
        for (uint32_t node = 0; node < nodes.GetN(); ++node) {
            for (const auto& [address, owner] : addressOwner) {
                if (owner != 0 && owner != 6) continue;
                for (uint8_t trafficClass = 0; trafficClass < 2; ++trafficClass) {
                    const auto entry = tables[node].find({address, trafficClass});
                    int next = -1, interface = -1;
                    if (entry != tables[node].end()) {
                        interface = int(entry->second.interface);
                        for (const auto& link : links)
                            if (link.edge.from == node && link.interface == entry->second.interface) next = int(link.edge.to);
                    }
                    this->tables << epoch << ',' << TimeSeconds() << ',' << node << ',' << unsigned(trafficClass)
                        << ',' << Ipv4Address(address) << ',' << next << ',' << interface << '\n';
                }
            }
        }
        for (uint32_t n = 0; n < nodes.GetN(); ++n) routers[n]->Install(std::move(tables[n]));
    }
    void Tick() {
        auto snapshot = Snapshot();
        if (mode == "stable" || mode == "class-aware") snapshot = smoother.Update(snapshot);
        Compute(snapshot);
        progress << std::setprecision(17) << TimeSeconds() << ',' << duration << '\n' << std::flush;
        if (failureObserved >= 0 && restorationTime < 0 && realtimeRouteReady < 0 &&
            std::isfinite(rm::PathCost(installed.at({1,6}), 0, snapshot, Weights(1)))) {
            realtimeRouteReady = TimeSeconds();
            events << TimeSeconds() << ",realtime-route-ready," << failureFrom << ',' << failureTo << '\n';
        }
        if (TimeSeconds() + interval < duration) Simulator::Schedule(Seconds(interval), &Controller::Tick, this);
    }
    void SetLink(uint32_t a, uint32_t b, bool up) {
        if (up) restorationTime = TimeSeconds();
        else {
            failureTime = TimeSeconds();
            const auto path = rm::Path(installed.at({1,6}), 0);
            for (size_t i = 1; i < path.size(); ++i) {
                if ((path[i-1] == a && path[i] == b) || (path[i-1] == b && path[i] == a))
                    realtimeAffected = true;
            }
        }
        events << TimeSeconds() << ',' << (up ? "link-up" : "link-down") << ',' << a << ',' << b << '\n';
        for (auto& state : links) {
            if ((state.edge.from == a && state.edge.to == b) || (state.edge.from == b && state.edge.to == a)) {
                state.edge.up = up;
                auto ipv4 = nodes.Get(state.edge.from)->GetObject<Ipv4>();
                if (up) ipv4->SetUp(state.interface); else ipv4->SetDown(state.interface);
            }
        }
        // Availability is observed at the next periodic sample, not an oracle-triggered
        // instant reroute. Detection delay is therefore bounded by interval.
    }
};

struct Samples {
    Controller* controller;
    std::ofstream packets;
    std::ofstream offers;
    std::vector<double> delays;
    uint64_t tx = 0, payload = 0;
    uint64_t offered = 0, rejected = 0;
    std::set<uint32_t> sequences;
    double firstAfterFailure = -1, firstAfterReady = -1, firstAfterRestoration = -1;
    explicit Samples(const std::string& output, Controller* owner)
        : controller(owner), packets(output + "/realtime-packets.csv"), offers(output + "/udp-offers.csv") {
        packets << std::setprecision(17) << "time,sequence,delay_ms,payload_bytes,tx_time\n";
        offers << std::setprecision(17) << "time,sequence,packet_uid,accepted,socket_error\n";
    }
    void Tx(Ptr<const Packet>) { ++tx; }
    void Rx(Ptr<const Packet> packet, const Address&, const Address&, const SeqTsSizeHeader& header) {
        if (!sequences.insert(header.GetSeq()).second) return;
        const double delay = (Simulator::Now() - header.GetTs()).GetSeconds() * 1000;
        delays.push_back(delay);
        payload += packet->GetSize();
        const double sent = header.GetTs().GetSeconds();
        const bool duringOutage = controller->failureTime >= 0 && controller->restorationTime < 0;
        if (duringOutage && sent >= controller->failureTime && firstAfterFailure < 0)
            firstAfterFailure = TimeSeconds();
        if (duringOutage && controller->realtimeRouteReady >= 0 &&
            sent >= controller->realtimeRouteReady && firstAfterReady < 0)
            firstAfterReady = TimeSeconds();
        if (controller->restorationTime >= 0 && sent >= controller->restorationTime && firstAfterRestoration < 0)
            firstAfterRestoration = TimeSeconds();
        packets << TimeSeconds() << ',' << header.GetSeq() << ',' << delay << ',' << packet->GetSize() << ',' << sent << '\n';
    }
};

// A fresh datagram is offered every 10 ms even when RouteOutput fails. Unlike
// OnOff's cached-send behavior, a disconnection cannot change the offered workload.
struct FixedRateDatagrams {
    Ptr<Node> node;
    Ipv4Address destination;
    Samples* samples;
    Ptr<Socket> socket;
    EventId next;
    uint32_t sequence = 0;
    void Start() {
        socket = Socket::CreateSocket(node, UdpSocketFactory::GetTypeId());
        socket->Bind();
        socket->SetIpTos(46 << 2);
        socket->Connect(InetSocketAddress(destination, 9000));
        next = Simulator::Schedule(MilliSeconds(10), &FixedRateDatagrams::Send, this);
    }
    void Send() {
        SeqTsSizeHeader header;
        header.SetSeq(sequence++);
        header.SetSize(320);
        auto packet = Create<Packet>(320 - header.GetSerializedSize());
        packet->AddHeader(header);
        ++samples->offered;
        const int sent = socket->Send(packet);
        const bool accepted = sent == 320;
        if (accepted) samples->Tx(packet);
        else ++samples->rejected;
        samples->offers << TimeSeconds() << ',' << header.GetSeq() << ',' << packet->GetUid() << ','
            << accepted << ',' << unsigned(socket->GetErrno()) << '\n';
        next = Simulator::Schedule(MilliSeconds(10), &FixedRateDatagrams::Send, this);
    }
    void Stop() { next.Cancel(); if (socket) socket->Close(); }
};

static void ForwardTrace(Controller* controller, uint32_t node, const Ipv4Header& header,
                         Ptr<const Packet> packet, uint32_t interface) {
    // Keep all realtime forwarding events; sample bulk data to bound artifact size.
    const uint8_t trafficClass = RouteMindRouting::Classify(header.GetTos());
    if (trafficClass == 1 || (trafficClass == 0 && (controller->auditForwarding || packet->GetUid() % 100 == 0))) {
        TcpHeader tcp;
        const bool isTcp = header.GetProtocol() == 6 && packet->PeekHeader(tcp) > 0;
        controller->forwarding << TimeSeconds() << ',' << node << ',' << unsigned(trafficClass) << ','
            << header.GetDestination() << ',' << interface << ',' << packet->GetUid() << ',' << controller->epoch
            << ',' << header.GetSource() << ',' << unsigned(header.GetProtocol()) << ','
            << (isTcp ? tcp.GetSourcePort() : 0) << ',' << (isTcp ? tcp.GetDestinationPort() : 0) << ','
            << (isTcp ? unsigned(tcp.GetFlags()) : 0) << ','
            << (isTcp ? packet->GetSize() - tcp.GetSerializedSize() : 0) << '\n';
        ++controller->forwardingSamples;
    }
}

static void LocalTrace(Controller* controller, uint32_t node, const Ipv4Header& header,
                       Ptr<const Packet> packet, uint32_t) {
    if (node != 0 || header.GetProtocol() != 6) return;
    TcpHeader tcp;
    if (!packet->PeekHeader(tcp) || tcp.GetSourcePort() != 9001 || tcp.GetFlags() != TcpHeader::ACK ||
        packet->GetSize() != tcp.GetSerializedSize()) return;
    ++controller->receivedAcks;
    controller->ackReceipts << TimeSeconds() << ',' << packet->GetUid() << ',' << header.GetSource() << ','
        << header.GetDestination() << ',' << unsigned(RouteMindRouting::Classify(header.GetTos())) << ','
        << tcp.GetAckNumber().GetValue() << '\n';
}

static void MissingRouteProbes(Controller* controller) {
    const Ipv4Address destination("10.254.0.1");
    auto socket = Socket::CreateSocket(controller->nodes.Get(0), UdpSocketFactory::GetTypeId());
    socket->Bind();
    auto attempt = [&](const char* kind) {
        auto packet = Create<Packet>(16);
        const int result = socket->SendTo(packet, 0, InetSocketAddress(destination, 9010));
        controller->probes << TimeSeconds() << ',' << kind << ',' << destination << ',' << packet->GetUid()
            << ',' << result << ',' << unsigned(socket->GetErrno()) << '\n';
    };
    attempt("output-missing");
    for (const auto& link : controller->links) {
        if (link.edge.from == 0 && link.edge.to == 1)
            controller->routers[0]->AddProbeRoute(destination, {link.neighbor, link.interface});
    }
    attempt("input-missing");
    socket->Close();
}

int main(int argc, char** argv) {
    std::string mode = "class-aware", scenario = "congestion", output = "results/single", policy = "balanced", topologyName = "parallel";
    double duration = 26, interval = .25, dwell = 1.5, threshold = .12, alpha = .3;
    double calibrationRate = .256;
    std::string networkFile;
    double realtimeRate = .256, backgroundOverride = -1, backgroundBegin = -1, backgroundEnd = 18;
    double burstOn = .4, burstOff = .4, failureAt = -1, restoreAt = -1;
    uint32_t packetBytes = 320, customNodes = 0, customFailureFrom = 2, customFailureTo = 5;
    struct CustomLink { uint32_t a, b, queue; double capacity, delay; };
    std::vector<CustomLink> customLinks;
    uint32_t seed = 42, run = 1;
    bool pcap = false, loopSafe = true, auditForwarding = false;
    CommandLine cli(__FILE__);
    cli.AddValue("network-file", "Validated numeric network configuration from the local application", networkFile);
    cli.AddValue("mode", "static|adaptive|stable|class-aware", mode);
    cli.AddValue("scenario", "steady|congestion|burst|failure|combined|calibration|active-failure|disconnected|missing-route", scenario);
    cli.AddValue("audit-forwarding", "Record all controlled forwarding events", auditForwarding);
    cli.AddValue("topology", "parallel|extended|detour", topologyName);
    cli.AddValue("calibration-rate-mbps", "Calibration-only UDP application rate (static routing, no TCP)", calibrationRate);
    cli.AddValue("policy", "Shared adaptive/stable policy: shortest|latency|congestion|reliability|balanced", policy);
    cli.AddValue("output", "Artifact directory", output);
    cli.AddValue("duration", "Simulation seconds, at least 24", duration);
    cli.AddValue("interval", "Telemetry interval seconds", interval);
    cli.AddValue("dwell", "Minimum ordinary route dwell seconds", dwell);
    cli.AddValue("threshold", "Minimum fractional cost improvement", threshold);
    cli.AddValue("alpha", "EWMA new-sample weight in (0,1]", alpha);
    cli.AddValue("seed", "NS-3 RNG seed", seed);
    cli.AddValue("run", "NS-3 RNG run index", run);
    cli.AddValue("pcap", "Enable point-to-point packet captures", pcap);
    cli.AddValue("loop-safe", "Fixed destination-rank forwarding constraint for controlled classes", loopSafe);
    cli.Parse(argc, argv);
    try {
        if (mode != "static" && mode != "adaptive" && mode != "stable" && mode != "class-aware")
            throw std::invalid_argument("unknown mode");
        if (scenario != "steady" && scenario != "congestion" && scenario != "burst" && scenario != "failure" && scenario != "combined" && scenario != "calibration" &&
            scenario != "active-failure" && scenario != "disconnected" && scenario != "missing-route")
            throw std::invalid_argument("unknown scenario");
        const bool calibration = scenario == "calibration";
        const bool correctness = scenario == "active-failure" || scenario == "disconnected" || scenario == "missing-route";
        if (topologyName != "parallel" && topologyName != "extended" && topologyName != "detour")
            throw std::invalid_argument("unknown topology");
        if (calibration && topologyName != "parallel") throw std::invalid_argument("calibration requires parallel topology");
        if (!std::isfinite(calibrationRate) || calibrationRate <= 0 || calibrationRate > 20 ||
            (calibration && mode != "static") || (!calibration && calibrationRate != .256))
            throw std::invalid_argument("calibration requires static mode and a rate in (0,20] Mbps; rate overrides require calibration scenario");
        rm::Policy(policy).Validate();
        if (!networkFile.empty()) {
            if (calibration || correctness) throw std::invalid_argument("custom networks support steady, congestion, burst, failure and combined scenarios");
            std::ifstream input(networkFile);
            uint32_t count = 0;
            if (!(input >> customNodes >> count) || customNodes < 8 || customNodes > 24 || count < 7 || count > 80)
                throw std::invalid_argument("invalid custom node/link count");
            std::set<std::pair<uint32_t,uint32_t>> pairs;
            for (uint32_t i = 0; i < count; ++i) {
                CustomLink link{};
                if (!(input >> link.a >> link.b >> link.capacity >> link.delay >> link.queue) ||
                    link.a >= customNodes || link.b >= customNodes || link.a == link.b ||
                    !std::isfinite(link.capacity) || link.capacity < 1 || link.capacity > 1000 ||
                    !std::isfinite(link.delay) || link.delay < .01 || link.delay > 20 ||
                    link.queue < 2000 || link.queue > 120000 ||
                    !pairs.insert(std::minmax(link.a, link.b)).second)
                    throw std::invalid_argument("invalid custom link");
                for (auto host : {0u,6u,7u}) {
                    const auto neighbor = host == 0 ? 1u : (host == 6 ? 5u : 2u);
                    if ((link.a == host && link.b != neighbor) || (link.b == host && link.a != neighbor))
                        throw std::invalid_argument("custom host attachments must remain 0--1, 5--6, 7--2");
                }
                customLinks.push_back(link);
            }
            if (!(input >> realtimeRate >> packetBytes >> backgroundOverride >> backgroundBegin >> backgroundEnd
                        >> burstOn >> burstOff >> customFailureFrom >> customFailureTo >> failureAt >> restoreAt) ||
                !std::isfinite(realtimeRate) || realtimeRate < .032 || realtimeRate > 2 || packetBytes < 64 || packetBytes > 1400 ||
                !std::isfinite(backgroundOverride) || backgroundOverride < .1 || backgroundOverride > 30 ||
                !std::isfinite(backgroundBegin) || !std::isfinite(backgroundEnd) || backgroundBegin < 2 || backgroundEnd <= backgroundBegin || backgroundEnd > duration-3 ||
                !std::isfinite(burstOn) || !std::isfinite(burstOff) || burstOn < .05 || burstOn > 5 || burstOff < .05 || burstOff > 5 ||
                !std::isfinite(failureAt) || !std::isfinite(restoreAt) || failureAt < 3 || restoreAt <= failureAt+interval || restoreAt > duration-3 ||
                !pairs.count(std::minmax(customFailureFrom, customFailureTo)) ||
                !pairs.count({0,1}) || !pairs.count({5,6}) || !pairs.count({2,7}))
                throw std::invalid_argument("invalid custom traffic, failure schedule or host attachments");
            std::set<uint32_t> reached{0};
            for (uint32_t pass = 0; pass < customNodes; ++pass)
                for (auto [a,b] : pairs) if (reached.count(a) || reached.count(b)) { reached.insert(a); reached.insert(b); }
            if (reached.size() != customNodes) throw std::invalid_argument("custom network must initially be connected");
            topologyName = "custom";
        }
        if (!std::isfinite(duration) || duration < 24 || duration > 3600 ||
            !std::isfinite(interval) || interval < .01 || interval > 2 ||
            !std::isfinite(dwell) || dwell < 0 || !std::isfinite(threshold) || threshold < 0 || threshold >= 1 ||
            !std::isfinite(alpha) || alpha <= 0 || alpha > 1 || seed == 0 || run == 0)
            throw std::invalid_argument("invalid duration, interval, stability setting or random seed/run");
        std::filesystem::create_directories(output);
        RngSeedManager::SetSeed(seed);
        RngSeedManager::SetRun(run);
        Config::SetDefault("ns3::TcpL4Protocol::SocketType", TypeIdValue(TcpNewReno::GetTypeId()));
        Config::SetDefault("ns3::TcpSocket::SegmentSize", UintegerValue(1200));
        Controller controller(output, mode, alpha, calibration);
        controller.duration = duration;
        controller.policy = policy;
        controller.loopSafe = loopSafe;
        controller.interval = interval;
        controller.dwell = dwell;
        controller.threshold = threshold;
        controller.auditForwarding = auditForwarding || correctness;
        if (topologyName == "extended") controller.failureTo = 8;
        if (scenario == "disconnected") { controller.failureFrom = 5; controller.failureTo = 6; }
        if (customNodes) { controller.failureFrom = customFailureFrom; controller.failureTo = customFailureTo; }
        controller.nodes.Create(customNodes ? customNodes : (topologyName == "extended" ? 11 : 8));
        InternetStackHelper stack;
        stack.Install(controller.nodes);
        for (uint32_t n = 0; n < controller.nodes.GetN(); ++n) {
            auto protocol = CreateObject<RouteMindRouting>();
            controller.nodes.Get(n)->GetObject<Ipv4>()->SetRoutingProtocol(protocol);
            controller.routers.push_back(protocol);
            protocol->ObserveErrors([&controller, n](const char* stage, const Ipv4Header& header, uint64_t uid) {
                controller.routingErrors << TimeSeconds() << ',' << n << ',' << stage << ','
                    << unsigned(RouteMindRouting::Classify(header.GetTos())) << ',' << header.GetDestination() << ',' << uid << '\n';
            });
            controller.nodes.Get(n)->GetObject<Ipv4L3Protocol>()->TraceConnectWithoutContext(
                "UnicastForward", MakeBoundCallback(&ForwardTrace, &controller, n));
            controller.nodes.Get(n)->GetObject<Ipv4L3Protocol>()->TraceConnectWithoutContext(
                "LocalDeliver", MakeBoundCallback(&LocalTrace, &controller, n));
        }
        if (customNodes) {
            // Install canonical host links first to preserve source/sink interface addresses.
            for (auto wanted : {std::pair{0u,1u}, std::pair{5u,6u}, std::pair{2u,7u}})
                for (const auto& link : customLinks)
                    if (std::minmax(link.a,link.b) == std::minmax(wanted.first,wanted.second))
                        controller.AddLink(wanted.first,wanted.second,link.capacity,link.delay,link.queue);
            for (const auto& link : customLinks)
                if (link.a != 0 && link.b != 0 && link.a != 6 && link.b != 6 && link.a != 7 && link.b != 7)
                    controller.AddLink(link.a,link.b,link.capacity,link.delay,link.queue);
        } else {
        controller.AddLink(0,1,100,1);
        controller.AddLink(1,2,6,1);
        if (topologyName == "extended") {
            controller.AddLink(2,8,6,1); controller.AddLink(8,5,6,1);
            controller.AddLink(1,3,12,3); controller.AddLink(3,9,12,3); controller.AddLink(9,5,12,3);
            controller.AddLink(1,4,30,6); controller.AddLink(4,10,30,6); controller.AddLink(10,5,30,6);
        } else if (topologyName == "detour") {
            controller.AddLink(2,5,6,1);
            controller.AddLink(1,3,18,3); controller.AddLink(3,4,18,3); controller.AddLink(4,5,18,3);
        } else {
            controller.AddLink(2,5,6,1);
            controller.AddLink(1,3,12,4); controller.AddLink(3,5,12,4);
            controller.AddLink(1,4,30,10); controller.AddLink(4,5,30,10);
        }
        controller.AddLink(5,6,100,1);
        controller.AddLink(7,2,100,1);
        }
        std::ofstream topology(output+"/topology.json");
        topology << "{\"nodes\":" << controller.nodes.GetN() << ",\"name\":\"" << topologyName
            << "\",\"sender\":0,\"receiver\":6,\"directed_links\":[";
        bool firstLink = true;
        for (const auto& link : controller.links) {
            topology << (firstLink ? "" : ",") << "{\"from\":" << link.edge.from
                << ",\"to\":" << link.edge.to << ",\"interface\":" << link.interface
                << ",\"neighbor_ip\":\"" << link.neighbor << "\",\"capacity_mbps\":" << link.edge.capacityMbps
                << ",\"delay_ms\":" << link.edge.propagationMs << '}';
            firstLink = false;
        }
        topology << "]}\n";
        const auto receiver = controller.nodes.Get(6)->GetObject<Ipv4>()->GetAddress(1,0).GetLocal();
        const auto backgroundReceiver = controller.nodes.Get(5)->GetObject<Ipv4>()->GetAddress(1,0).GetLocal();
        auto random = CreateObject<UniformRandomVariable>();
        random->SetStream(17);
        const double backgroundStart = customNodes ? backgroundBegin : random->GetValue(6,6.5);
        const double backgroundRate = customNodes ? backgroundOverride : random->GetValue(8.5,10.5);
        controller.Tick();
        Samples samples(output, &controller);
        PacketSinkHelper realtimeSink("ns3::UdpSocketFactory", InetSocketAddress(Ipv4Address::GetAny(),9000));
        realtimeSink.SetAttribute("EnableSeqTsSizeHeader", BooleanValue(true));
        auto realtimeRx = realtimeSink.Install(controller.nodes.Get(6));
        realtimeRx.Start(Seconds(.2)); realtimeRx.Stop(Seconds(duration));
        realtimeRx.Get(0)->TraceConnectWithoutContext("RxWithSeqTsSize", MakeCallback(&Samples::Rx,&samples));
        OnOffHelper realtime("ns3::UdpSocketFactory", InetSocketAddress(receiver,9000));
        realtime.SetAttribute("DataRate", DataRateValue(DataRate(uint64_t((calibration ? calibrationRate : realtimeRate) * 1e6))));
        realtime.SetAttribute("PacketSize", UintegerValue(packetBytes));
        realtime.SetAttribute("Tos", UintegerValue(46 << 2));
        realtime.SetAttribute("OnTime", StringValue("ns3::ConstantRandomVariable[Constant=1]"));
        realtime.SetAttribute("OffTime", StringValue("ns3::ConstantRandomVariable[Constant=0]"));
        realtime.SetAttribute("EnableSeqTsSizeHeader", BooleanValue(true));
        FixedRateDatagrams fixed{controller.nodes.Get(0), receiver, &samples, nullptr, EventId(), 0};
        if (correctness) {
            Simulator::Schedule(Seconds(1), &FixedRateDatagrams::Start, &fixed);
            Simulator::Schedule(Seconds(duration-3), &FixedRateDatagrams::Stop, &fixed);
        } else {
            auto realtimeTx = realtime.Install(controller.nodes.Get(0));
            DynamicCast<OnOffApplication>(realtimeTx.Get(0))->AssignStreams(30);
            realtimeTx.Get(0)->TraceConnectWithoutContext("Tx", MakeCallback(&Samples::Tx,&samples));
            realtimeTx.Start(Seconds(1)); realtimeTx.Stop(Seconds(duration-3));
        }
        PacketSinkHelper bulkSink("ns3::TcpSocketFactory", InetSocketAddress(Ipv4Address::GetAny(),9001));
        auto bulkRx = bulkSink.Install(controller.nodes.Get(6));
        bulkRx.Start(Seconds(.2)); bulkRx.Stop(Seconds(duration));
        BulkSendHelper bulk("ns3::TcpSocketFactory", InetSocketAddress(receiver,9001));
        bulk.SetAttribute("MaxBytes", UintegerValue(0));
        bulk.SetAttribute("SendSize", UintegerValue(1200));
        if (correctness) {
            OnOffHelper probe("ns3::TcpSocketFactory", InetSocketAddress(receiver,9001));
            probe.SetAttribute("DataRate", DataRateValue(DataRate("64kbps")));
            probe.SetAttribute("PacketSize", UintegerValue(1200));
            probe.SetAttribute("OnTime", StringValue("ns3::ConstantRandomVariable[Constant=1]"));
            probe.SetAttribute("OffTime", StringValue("ns3::ConstantRandomVariable[Constant=0]"));
            auto traffic = probe.Install(controller.nodes.Get(0));
            DynamicCast<OnOffApplication>(traffic.Get(0))->AssignStreams(50);
            traffic.Start(Seconds(1.2)); traffic.Stop(Seconds(duration-3));
        } else if (!calibration) {
            auto bulkTx = bulk.Install(controller.nodes.Get(0));
            bulkTx.Start(Seconds(1.2)); bulkTx.Stop(Seconds(duration-3));
        }
        if (scenario == "congestion" || scenario == "burst" || scenario == "combined") {
            PacketSinkHelper backgroundSink("ns3::UdpSocketFactory", InetSocketAddress(Ipv4Address::GetAny(),9002));
            auto sink = backgroundSink.Install(controller.nodes.Get(5));
            sink.Start(Seconds(.2)); sink.Stop(Seconds(duration));
            OnOffHelper background("ns3::UdpSocketFactory", InetSocketAddress(backgroundReceiver,9002));
            background.SetAttribute("DataRate", DataRateValue(DataRate(uint64_t(backgroundRate * 1e6))));
            background.SetAttribute("PacketSize", UintegerValue(1200));
            background.SetAttribute("Tos", UintegerValue(8 << 2));
            const std::string on = scenario == "burst" ? std::to_string(burstOn) : "1";
            const std::string off = scenario == "burst" ? std::to_string(burstOff) : "0";
            background.SetAttribute("OnTime", StringValue("ns3::ConstantRandomVariable[Constant="+on+"]"));
            background.SetAttribute("OffTime", StringValue("ns3::ConstantRandomVariable[Constant="+off+"]"));
            auto traffic = background.Install(controller.nodes.Get(7));
            DynamicCast<OnOffApplication>(traffic.Get(0))->AssignStreams(40);
            traffic.Start(Seconds(backgroundStart)); traffic.Stop(Seconds(backgroundEnd));
        }
        if (scenario == "failure" || scenario == "combined") {
            Simulator::Schedule(Seconds(customNodes ? failureAt : 14), &Controller::SetLink, &controller, controller.failureFrom,controller.failureTo,false);
            Simulator::Schedule(Seconds(customNodes ? restoreAt : 20), &Controller::SetLink, &controller, controller.failureFrom,controller.failureTo,true);
        }
        if (scenario == "active-failure" || scenario == "disconnected") {
            Simulator::Schedule(Seconds(14.07), &Controller::SetLink, &controller,
                                controller.failureFrom, controller.failureTo, false);
            Simulator::Schedule(Seconds(20.11), &Controller::SetLink, &controller,
                                controller.failureFrom, controller.failureTo, true);
        }
        if (scenario == "missing-route") Simulator::Schedule(Seconds(10.123), &MissingRouteProbes, &controller);
        if (pcap) { PointToPointHelper capture; capture.EnablePcapAll(output+"/capture"); }
        FlowMonitorHelper flowHelper;
        flowHelper.SetMonitorAttribute("MaxPerHopDelay", TimeValue(Seconds(2)));
        auto monitor = flowHelper.InstallAll();
        Simulator::Stop(Seconds(duration));
        Simulator::Run();
        monitor->CheckForLostPackets();
        auto classifier = DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
        std::ofstream flowCsv(output+"/flows.csv");
        flowCsv << "flow,source,destination,source_port,destination_port,protocol,tx_packets,rx_packets,lost_packets,unaccounted_packets,ip_rx_bytes,mean_delay_ms\n";
        uint64_t unaccounted = 0;
        for (const auto& [id, stats] : monitor->GetFlowStats()) {
            const auto tuple = classifier->FindFlow(id);
            const auto remainder = int64_t(stats.txPackets)-stats.rxPackets-stats.lostPackets;
            unaccounted += uint64_t(std::max<int64_t>(0,remainder));
            flowCsv << id << ',' << tuple.sourceAddress << ',' << tuple.destinationAddress << ',' << tuple.sourcePort
                << ',' << tuple.destinationPort << ',' << unsigned(tuple.protocol) << ',' << stats.txPackets
                << ',' << stats.rxPackets << ',' << stats.lostPackets << ',' << remainder << ',' << stats.rxBytes
                << ',' << (stats.rxPackets ? stats.delaySum.GetSeconds()*1000/stats.rxPackets : 0) << '\n';
        }
        monitor->SerializeToXmlFile(output+"/flow-monitor.xml", true, true);
        auto sorted = samples.delays;
        std::sort(sorted.begin(), sorted.end());
        double sum = 0, jitter = 0;
        uint64_t over40 = 0;
        for (size_t i=0;i<samples.delays.size();++i) {
            sum += samples.delays[i];
            over40 += samples.delays[i] > 40;
            if (i) jitter += std::abs(samples.delays[i]-samples.delays[i-1]);
        }
        const double p95 = sorted.empty() ? 0 : sorted[size_t(std::ceil(.95*sorted.size()))-1];
        const auto bulkBytes = DynamicCast<PacketSink>(bulkRx.Get(0))->GetTotalRx();
        const double observationWindow = duration-1;
        std::ofstream summary(output+"/summary.json");
        summary << std::setprecision(10)
            << "{\n  \"schema_version\": 3,\n  \"backend\": \"ns-3.46.1\",\n  \"mode\": \"" << mode << "\",\n  \"scenario\": \"" << scenario
            << "\",\n  \"policy\": \"" << policy << "\",\n  \"seed\": " << seed << ",\n  \"run\": " << run << ",\n  \"duration_s\": " << duration
            << ",\n  \"topology\": \"" << topologyName << "\""
            << ",\n  \"custom_config\": " << (customNodes?"true":"false")
            << ",\n  \"realtime_packet_bytes\": " << packetBytes
            << ",\n  \"interval_s\": " << interval << ",\n  \"alpha\": " << alpha << ",\n  \"dwell_s\": " << dwell
            << ",\n  \"threshold\": " << threshold << ",\n  \"loop_safe\": " << (loopSafe?"true":"false")
            << ",\n  \"background_start_s\": " << backgroundStart
            << ",\n  \"background_rate_mbps\": " << backgroundRate << ",\n  \"realtime_tx_packets\": " << samples.tx
            << ",\n  \"realtime_application_rate_mbps\": " << (calibration ? calibrationRate : realtimeRate)
            << ",\n  \"realtime_rx_packets\": " << sorted.size()
            << ",\n  \"realtime_offered_packets\": " << (correctness ? samples.offered : samples.tx)
            << ",\n  \"realtime_source_rejected_packets\": " << samples.rejected
            << ",\n  \"udp_generator\": \"" << (correctness ? "fresh-datagram" : "onoff") << "\""
            << ",\n  \"realtime_pdr\": " << (correctness ? (samples.offered ? double(sorted.size())/samples.offered : 0) : (samples.tx ? double(sorted.size())/samples.tx : 0))
            << ",\n  \"realtime_mean_delay_ms\": " << (sorted.empty()?0:sum/sorted.size())
            << ",\n  \"realtime_p95_delay_ms\": " << p95
            << ",\n  \"realtime_mean_abs_delay_variation_ms\": " << (sorted.size()>1?jitter/(sorted.size()-1):0)
            << ",\n  \"realtime_packets_above_40ms\": " << over40
            << ",\n  \"realtime_payload_goodput_mbps\": " << samples.payload*8.0/(observationWindow*1e6)
            << ",\n  \"bulk_payload_goodput_mbps\": " << bulkBytes*8.0/(observationWindow*1e6)
            << ",\n  \"bulk_received_bytes\": " << bulkBytes
            << ",\n  \"goodput_window_s\": " << observationWindow
            << ",\n  \"route_changes\": " << controller.routeChanges
            << ",\n  \"forwarding_samples\": " << controller.forwardingSamples
            << ",\n  \"audit_forwarding\": " << (controller.auditForwarding ? "true" : "false")
            << ",\n  \"tcp_ack_ip_receipts\": " << controller.receivedAcks
            << ",\n  \"tcp_workload\": \"" << (calibration ? "disabled" : (correctness ? "64kbps" : "saturated")) << "\""
            << ",\n  \"unaccounted_flow_packets\": " << unaccounted
            << ",\n  \"failure_time_s\": " << JsonTime(controller.failureTime)
            << ",\n  \"failure_from\": " << controller.failureFrom
            << ",\n  \"failure_to\": " << controller.failureTo
            << ",\n  \"recovery_time_s\": " << JsonTime(controller.restorationTime)
            << ",\n  \"link_restoration_time_s\": " << JsonTime(controller.restorationTime)
            << ",\n  \"failure_observed_time_s\": " << JsonTime(controller.failureObserved)
            << ",\n  \"failure_detection_delay_ms\": " << JsonTime(controller.failureObserved < 0 ? -1 : (controller.failureObserved-controller.failureTime)*1000)
            << ",\n  \"restoration_observed_time_s\": " << JsonTime(controller.restorationObserved)
            << ",\n  \"realtime_path_affected_by_failure\": " << (controller.failureTime < 0 ? "null" : (controller.realtimeAffected ? "true" : "false"))
            << ",\n  \"realtime_route_ready_time_s\": " << JsonTime(controller.realtimeRouteReady)
            << ",\n  \"realtime_route_repair_delay_ms\": " << JsonTime(controller.realtimeAffected && controller.realtimeRouteReady >= 0 ? (controller.realtimeRouteReady-controller.failureTime)*1000 : -1)
            << ",\n  \"realtime_first_delivery_after_failure_time_s\": " << JsonTime(samples.firstAfterFailure)
            << ",\n  \"realtime_first_delivery_after_route_ready_time_s\": " << JsonTime(samples.firstAfterReady)
            << ",\n  \"realtime_recovery_delay_ms\": " << JsonTime(controller.realtimeAffected && samples.firstAfterReady >= 0 ? (samples.firstAfterReady-controller.failureTime)*1000 : -1)
            << ",\n  \"realtime_first_delivery_after_restoration_time_s\": " << JsonTime(samples.firstAfterRestoration)
            << ",\n  \"assumptions\": [\"centralized direct telemetry\",\"synchronous table installation\",\"no control traffic overhead\",\"unreserved QoS\"]\n}\n";
        std::cout << "RouteMind " << mode << " / " << scenario << ": realtime p95=" << p95
                  << "ms, received=" << sorted.size() << '/' << samples.tx
                  << ", bulk=" << bulkBytes*8.0/(observationWindow*1e6)
                  << "Mbps, route changes=" << controller.routeChanges << '\n';
        Simulator::Destroy();
        return sorted.empty() || (!calibration && bulkBytes == 0) ? 2 : 0;
    } catch (const std::exception& error) {
        std::cerr << "RouteMind error: " << error.what() << '\n';
        Simulator::Destroy();
        return 1;
    }
}
