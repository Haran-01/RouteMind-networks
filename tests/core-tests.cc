#include "routing.hpp"
#include <iostream>
#include <stdexcept>

using namespace routemind;
static int checks = 0;
void Check(bool condition, const std::string& message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}
template <typename F> void Reject(F fn, const std::string& message) {
    bool rejected = false;
    try { fn(); } catch (const std::invalid_argument&) { rejected = true; }
    Check(rejected, message);
}
std::vector<Edge> Diamond() {
    return {{0,1,1,10,0,10000,0,0,true}, {1,3,1,10,0,10000,0,0,true},
            {0,2,5,10,0,10000,0,0,true}, {2,3,5,10,0,10000,0,0,true}};
}
int main() {
    try {
        auto edges = Diamond();
        auto weights = Policy("latency");
        const auto first = ShortestTree(5, edges, 3, weights);
        Check(Path(first, 0) == std::vector<uint32_t>({0,1,3}), "prefer lower delay");
        Check(Path(first, 4).empty(), "isolated node has no route");
        Check(Path(first, 3) == std::vector<uint32_t>({3}), "local delivery path");
        edges[0].queueBytes = 10000;
        edges[1].queueBytes = 10000;
        auto candidate = ShortestTree(5, edges, 3, weights);
        Check(Path(candidate, 0) == std::vector<uint32_t>({0,2,3}), "congestion changes route");
        auto held = Decide(&first, candidate, 0, edges, weights, 1, 0, 2, .1);
        Check(!held.install && held.reason == "dwell", "dwell suppresses ordinary change");
        auto changed = Decide(&first, candidate, 0, edges, weights, 3, 0, 2, .1);
        Check(changed.install && changed.reason == "better-path", "material improvement accepted");
        edges[0].up = false;
        auto failure = Decide(&first, candidate, 0, edges, weights, .1, 0, 10, .9);
        Check(failure.install && failure.reason == "failure-bypass", "failure bypasses dwell");
        edges[2].up = false;
        auto disconnected = ShortestTree(5, edges, 3, weights);
        Check(Path(disconnected, 0).empty(), "all failed paths are unreachable");
        Check(Decide(&candidate, disconnected, 0, edges, weights, .2, 0, 10, .1).install,
              "disconnection removes stale forwarding even in dwell");
        auto restoredEdges = Diamond();
        auto restored = ShortestTree(5, restoredEdges, 3, weights);
        Check(Decide(&disconnected, restored, 0, restoredEdges, weights, .3, 0, 10, .1).install,
              "restored reachability bypasses dwell");
        auto close = Diamond();
        close[2].propagationMs = .99; close[3].propagationMs = .99;
        auto closeTree = ShortestTree(5, close, 3, weights);
        auto marginal = Decide(&first, closeTree, 0, close, weights, 3, 0, 0, .1);
        Check(!marginal.install && marginal.reason == "hysteresis", "reject negligible improvement");
        Smoother smoother(.25);
        auto raw = Diamond(); smoother.Update(raw);
        raw[0].utilization = 1;
        Check(std::abs(smoother.Update(raw)[0].utilization - .25) < 1e-9, "EWMA calculation");
        raw[0].up = false;
        Check(!smoother.Update(raw)[0].up, "availability is never smoothed");
        raw[0].up = true; raw[0].utilization = 0;
        Check(smoother.Update(raw)[0].utilization == 0, "recovery resets stale telemetry");
        Reject([] { Smoother bad(0); }, "reject invalid EWMA");
        Reject([] { Policy("missing"); }, "reject unknown policy");
        Reject([&] { auto bad=weights; bad.hop=-1; Cost(raw[0],bad); }, "reject negative weights");
        Reject([&] { auto bad=raw[0]; bad.capacityMbps=0; Cost(bad,weights); }, "reject zero capacity");
        Reject([&] { auto bad=raw[0]; bad.loss=2; Cost(bad,weights); }, "reject invalid loss");
        Reject([&] { auto bad=raw; bad[0].to=100; ShortestTree(5,bad,3,weights); }, "validate endpoints");
        // All destination trees on a bidirectional cyclic graph must terminate.
        auto cyclic = Diamond();
        const auto forward = cyclic;
        for (auto e : forward) { std::swap(e.from,e.to); cyclic.push_back(e); }
        cyclic.push_back({1,2,1,10,0,10000,0,0,true});
        for (uint32_t d=0; d<4; ++d) {
            const auto tree=ShortestTree(4,cyclic,d,Policy("balanced"));
            for(uint32_t s=0;s<4;++s) Check(!Path(tree,s).empty(), "loop-free connected tree");
        }
        const auto rank = ShortestTree(4,cyclic,3,Policy("shortest")).distance;
        const auto progressive = ProgressiveEdges(cyclic,rank);
        for (const auto& edge : progressive) {
            if (edge.up) Check(rank[edge.from] > rank[edge.to], "all update paths make fixed progress");
        }
        auto loaded = progressive;
        loaded[0].queueBytes = 10000;
        loaded[1].queueBytes = 10000;
        const auto alternate = ShortestTree(4,loaded,3,weights);
        Check(Path(alternate,0) == std::vector<uint32_t>({0,2,3}), "rank permits parallel alternate route");
        Check(Path(alternate,1) == std::vector<uint32_t>({1,3}), "branch never hairpins through ingress");
        auto detour = std::vector<Edge>{{0,1,1,10,0,10000,0,0,true}, {1,3,1,10,0,10000,0,0,true},
            {0,2,1,10,0,10000,0,0,true}, {2,4,1,10,0,10000,0,0,true}, {4,3,1,10,0,10000,0,0,true}};
        const auto detourRank = ShortestTree(5,detour,3,Policy("shortest")).distance;
        Check(detourRank[0] == detourRank[2], "long detour starts with equal fixed rank");
        detour[1].up = false;
        Check(Path(ShortestTree(5,detour,3,weights),0) == std::vector<uint32_t>({0,2,4,3}), "physical detour repairs failed short path");
        Check(Path(ShortestTree(5,ProgressiveEdges(detour,detourRank),3,weights),0).empty(), "fixed rank explicitly restricts failure reachability");
        detour[1].up = true;
        Check(Path(ShortestTree(5,ProgressiveEdges(detour,detourRank),3,weights),0) == std::vector<uint32_t>({0,1,3}), "fixed-rank reachability returns on restoration");
        std::cout << "PASS " << checks << " core contract checks\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
