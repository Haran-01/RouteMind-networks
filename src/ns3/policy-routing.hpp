#pragma once
#include "ns3/ipv4-routing-protocol.h"
#include "ns3/ipv4-route.h"
#include "ns3/node.h"
#include "ns3/simulator.h"
#include <map>
#include <functional>

namespace ns3 {
// NS-3 routing adapter: each installed entry is used by the actual IPv4 stack.
class RouteMindRouting : public Ipv4RoutingProtocol {
  public:
    struct Entry { Ipv4Address gateway; uint32_t interface; };
    using Key = std::pair<uint32_t, uint8_t>;
    using Table = std::map<Key, Entry>;
    using ErrorObserver = std::function<void(const char*, const Ipv4Header&, uint64_t)>;
    void ObserveErrors(ErrorObserver observer) { m_errorObserver = std::move(observer); }
    // Used by the explicit missing-route integration probe to reach a router
    // that has no entry. Normal controller installation still replaces the table.
    void AddProbeRoute(Ipv4Address destination, Entry entry) { m_table[{destination.Get(), 0}] = entry; }
    static TypeId GetTypeId() {
        static TypeId tid = TypeId("ns3::RouteMindRouting")
            .SetParent<Ipv4RoutingProtocol>().SetGroupName("Internet")
            .AddConstructor<RouteMindRouting>();
        return tid;
    }
    static uint8_t Classify(uint8_t tos) {
        const auto dscp = tos >> 2;
        return dscp == 46 ? 1 : (dscp == 8 ? 2 : 0);
    }
    void Install(Table table) { m_table = std::move(table); }
    Ptr<Ipv4Route> Lookup(const Ipv4Header& header, Ptr<NetDevice> requested = nullptr) const {
        auto it = m_table.find({header.GetDestination().Get(), Classify(header.GetTos())});
        if (it == m_table.end() || !m_ipv4->IsUp(it->second.interface)) return nullptr;
        auto device = m_ipv4->GetNetDevice(it->second.interface);
        if (requested && requested != device) return nullptr;
        auto route = Create<Ipv4Route>();
        route->SetDestination(header.GetDestination());
        route->SetGateway(it->second.gateway);
        route->SetOutputDevice(device);
        route->SetSource(m_ipv4->GetAddress(it->second.interface, 0).GetLocal());
        return route;
    }
    Ptr<Ipv4Route> RouteOutput(Ptr<Packet> packet, const Ipv4Header& header,
                              Ptr<NetDevice> output, Socket::SocketErrno& error) override {
        // UDP's initial route query precedes IPv4 header construction. Its TOS
        // lives in a socket tag at this point, while transit packets use the header.
        auto classifiedHeader = header;
        SocketIpTosTag tag;
        if (packet && packet->PeekPacketTag(tag)) classifiedHeader.SetTos(tag.GetTos());
        auto route = Lookup(classifiedHeader, output);
        error = route ? Socket::ERROR_NOTERROR : Socket::ERROR_NOROUTETOHOST;
        if (!route && m_errorObserver) m_errorObserver("output", classifiedHeader, packet ? packet->GetUid() : 0);
        return route;
    }
    bool RouteInput(Ptr<const Packet> packet, const Ipv4Header& header,
                    Ptr<const NetDevice> input, const UnicastForwardCallback& forward,
                    const MulticastForwardCallback&, const LocalDeliverCallback& local,
                    const ErrorCallback& error) override {
        const int32_t interface = m_ipv4->GetInterfaceForDevice(input);
        if (interface < 0) return false;
        if (m_ipv4->IsDestinationAddress(header.GetDestination(), interface)) {
            if (!local.IsNull()) local(packet, header, interface);
            return true;
        }
        if (!m_ipv4->IsForwarding(interface)) {
            error(packet, header, Socket::ERROR_NOROUTETOHOST);
            return true;
        }
        auto route = Lookup(header);
        if (route) forward(route, packet, header);
        else {
            if (m_errorObserver) m_errorObserver("input", header, packet->GetUid());
            error(packet, header, Socket::ERROR_NOROUTETOHOST);
        }
        return true;
    }
    void NotifyInterfaceUp(uint32_t) override {}
    void NotifyInterfaceDown(uint32_t) override {}
    void NotifyAddAddress(uint32_t, Ipv4InterfaceAddress) override {}
    void NotifyRemoveAddress(uint32_t, Ipv4InterfaceAddress) override {}
    void SetIpv4(Ptr<Ipv4> ipv4) override { m_ipv4 = ipv4; }
    void PrintRoutingTable(Ptr<OutputStreamWrapper> stream, Time::Unit = Time::S) const override {
        for (const auto& [key, route] : m_table) {
            *stream->GetStream() << Ipv4Address(key.first) << " class=" << unsigned(key.second)
                << " via " << route.gateway << " interface=" << route.interface << '\n';
        }
    }
  protected:
    void DoDispose() override {
        m_ipv4 = nullptr;
        m_table.clear();
        m_errorObserver = {};
        Ipv4RoutingProtocol::DoDispose();
    }
  private:
    Ptr<Ipv4> m_ipv4;
    Table m_table;
    ErrorObserver m_errorObserver;
};
} // namespace ns3
