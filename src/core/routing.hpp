#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <limits>
#include <map>
#include <queue>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace routemind {
constexpr double Infinity = std::numeric_limits<double>::infinity();

struct Weights {
    double hop = 0.1;
    double delay = 1;
    double utilization = 2;
    double queue = 3;
    double loss = 5;
    double delayReferenceMs = 10;

    void Validate() const {
        if (!std::isfinite(hop) || hop <= 0 || !std::isfinite(delayReferenceMs) ||
            delayReferenceMs <= 0) {
            throw std::invalid_argument("hop and delay reference must be positive and finite");
        }
        for (double value : {delay, utilization, queue, loss}) {
            if (!std::isfinite(value) || value < 0) {
                throw std::invalid_argument("policy weights must be finite and nonnegative");
            }
        }
    }
};

inline Weights Policy(const std::string& name) {
    if (name == "shortest") return {1, 0, 0, 0, 0, 10};
    if (name == "latency") return {0.1, 4, 0.3, 0.5, 2, 10};
    if (name == "congestion") return {0.1, 0.2, 6, 8, 2, 10};
    if (name == "reliability") return {0.1, 0.2, 0.5, 1, 20, 10};
    if (name == "balanced") return {};
    throw std::invalid_argument("unknown policy: " + name);
}

struct Edge {
    uint32_t from = 0;
    uint32_t to = 0;
    double propagationMs = 0;
    double capacityMbps = 1;
    double queueBytes = 0;
    double queueLimitBytes = 1;
    double utilization = 0;
    double loss = 0;
    bool up = true;
};

inline void Validate(const Edge& e) {
    for (double value : {e.propagationMs, e.queueBytes, e.utilization, e.loss}) {
        if (!std::isfinite(value) || value < 0) {
            throw std::invalid_argument("edge telemetry must be finite and nonnegative");
        }
    }
    if (!std::isfinite(e.capacityMbps) || e.capacityMbps <= 0 ||
        !std::isfinite(e.queueLimitBytes) || e.queueLimitBytes <= 0 || e.loss > 1) {
        throw std::invalid_argument("invalid capacity, queue limit or loss probability");
    }
}

inline double Cost(const Edge& e, const Weights& w) {
    Validate(e);
    w.Validate();
    if (!e.up) return Infinity;
    const double waitingMs = e.queueBytes * 8.0 / (e.capacityMbps * 1000.0);
    return w.hop + w.delay * (e.propagationMs + waitingMs) / w.delayReferenceMs +
           w.utilization * std::min(e.utilization, 1.0) +
           w.queue * std::min(e.queueBytes / e.queueLimitBytes, 1.0) + w.loss * e.loss;
}

struct Tree {
    uint32_t destination = 0;
    std::vector<int> next;
    std::vector<double> distance;
};

// A fixed destination potential strictly decreases on every permitted edge.
// Keeping that rank fixed across updates prevents even packets in flight from
// revisiting a node. The trade-off is a restricted set of eligible detours.
inline std::vector<Edge> ProgressiveEdges(const std::vector<Edge>& edges,
                                         const std::vector<double>& rank) {
    auto result = edges;
    for (auto& edge : result) {
        if (edge.from >= rank.size() || edge.to >= rank.size())
            throw std::invalid_argument("rank does not cover graph");
        edge.up = edge.up && std::isfinite(rank[edge.from]) && std::isfinite(rank[edge.to]) &&
                  rank[edge.from] > rank[edge.to];
    }
    return result;
}

// Reverse Dijkstra produces one coherent destination tree, not independently
// chosen per-router paths. Positive costs guarantee decreasing distance per hop.
inline Tree ShortestTree(uint32_t nodes, const std::vector<Edge>& edges,
                         uint32_t destination, const Weights& weights) {
    if (nodes == 0 || destination >= nodes) throw std::invalid_argument("invalid destination");
    weights.Validate();
    std::vector<std::vector<std::pair<uint32_t, double>>> incoming(nodes);
    for (const auto& edge : edges) {
        if (edge.from >= nodes || edge.to >= nodes) throw std::invalid_argument("invalid edge endpoint");
        const double cost = Cost(edge, weights);
        if (std::isfinite(cost)) incoming[edge.to].emplace_back(edge.from, cost);
    }
    Tree tree{destination, std::vector<int>(nodes, -1), std::vector<double>(nodes, Infinity)};
    using Entry = std::pair<double, uint32_t>;
    std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> pending;
    tree.distance[destination] = 0;
    pending.emplace(0, destination);
    while (!pending.empty()) {
        auto [distance, current] = pending.top();
        pending.pop();
        if (distance > tree.distance[current]) continue;
        for (const auto& [previous, cost] : incoming[current]) {
            const double candidate = distance + cost;
            if (candidate < tree.distance[previous] - 1e-12) {
                tree.distance[previous] = candidate;
                tree.next[previous] = static_cast<int>(current);
                pending.emplace(candidate, previous);
            }
        }
    }
    return tree;
}

inline std::vector<uint32_t> Path(const Tree& tree, uint32_t source) {
    if (source >= tree.next.size()) throw std::invalid_argument("invalid source");
    std::vector<uint32_t> result;
    std::vector<bool> seen(tree.next.size(), false);
    uint32_t node = source;
    while (true) {
        if (seen[node]) throw std::logic_error("forwarding loop");
        seen[node] = true;
        result.push_back(node);
        if (node == tree.destination) return result;
        if (tree.next[node] < 0) return {};
        node = static_cast<uint32_t>(tree.next[node]);
        if (node >= tree.next.size()) throw std::logic_error("next hop out of range");
    }
}

inline double PathCost(const Tree& tree, uint32_t source, const std::vector<Edge>& edges,
                       const Weights& weights) {
    const auto path = Path(tree, source);
    if (path.empty()) return Infinity;
    double total = 0;
    for (size_t i = 1; i < path.size(); ++i) {
        double best = Infinity;
        for (const auto& edge : edges) {
            if (edge.from == path[i - 1] && edge.to == path[i]) {
                best = std::min(best, Cost(edge, weights));
            }
        }
        total += best;
    }
    return total;
}

class Smoother {
  public:
    explicit Smoother(double alpha) : m_alpha(alpha) {
        if (!std::isfinite(alpha) || alpha <= 0 || alpha > 1) {
            throw std::invalid_argument("EWMA alpha must be in (0,1]");
        }
    }
    std::vector<Edge> Update(const std::vector<Edge>& input) {
        std::vector<Edge> output;
        for (auto edge : input) {
            Validate(edge);
            const auto key = std::make_pair(edge.from, edge.to);
            const auto found = m_previous.find(key);
            // Do not smooth topology state or retain stale congestion across an outage.
            if (found != m_previous.end() && found->second.up && edge.up) {
                const auto& previous = found->second;
                edge.queueBytes = Blend(previous.queueBytes, edge.queueBytes);
                edge.utilization = Blend(previous.utilization, edge.utilization);
                edge.loss = Blend(previous.loss, edge.loss);
            }
            m_previous[key] = edge;
            output.push_back(edge);
        }
        return output;
    }
  private:
    double Blend(double previous, double current) const {
        return m_alpha * current + (1 - m_alpha) * previous;
    }
    double m_alpha;
    std::map<std::pair<uint32_t, uint32_t>, Edge> m_previous;
};

struct Decision {
    bool install = false;
    std::string reason;
    double oldCost = Infinity;
    double newCost = Infinity;
    double improvement = 0;
};

// The entire tree is accepted or retained together. First milestone assumes one
// controlled ingress per class/destination; source is that ingress, not any router.
inline Decision Decide(const Tree* current, const Tree& candidate, uint32_t source,
                       const std::vector<Edge>& snapshot, const Weights& weights,
                       double now, double lastChange, double dwell, double threshold) {
    if (!std::isfinite(now) || !std::isfinite(lastChange) || !std::isfinite(dwell) ||
        !std::isfinite(threshold) || dwell < 0 || threshold < 0 || threshold >= 1) {
        throw std::invalid_argument("invalid stability configuration");
    }
    const double nextCost = PathCost(candidate, source, snapshot, weights);
    if (!current) return {true, "initial", Infinity, nextCost, 0};
    const double oldCost = PathCost(*current, source, snapshot, weights);
    const bool same = current->next == candidate.next;
    if (same) return {false, "unchanged", oldCost, nextCost, 0};
    // Repair any invalid branch, including a failed link away from the main flow.
    bool broken = false;
    for (uint32_t n = 0; n < current->next.size(); ++n) {
        if (n != current->destination && current->next[n] >= 0 &&
            !std::isfinite(PathCost(*current, n, snapshot, weights))) broken = true;
    }
    if (broken) return {true, "failure-bypass", oldCost, nextCost, 1};
    if (!std::isfinite(oldCost) && std::isfinite(nextCost)) {
        return {true, "reachability-restored", oldCost, nextCost, 1};
    }
    if (!std::isfinite(nextCost)) return {false, "no-candidate", oldCost, nextCost, 0};
    const double improvement = (oldCost - nextCost) / std::max(oldCost, 1e-12);
    if (now - lastChange < dwell) return {false, "dwell", oldCost, nextCost, improvement};
    if (improvement <= threshold) return {false, "hysteresis", oldCost, nextCost, improvement};
    return {true, "better-path", oldCost, nextCost, improvement};
}
} // namespace routemind
