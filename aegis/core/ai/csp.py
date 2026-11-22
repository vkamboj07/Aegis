"""Vehicle allocation as a constraint-optimisation problem.

Variables   incidents, in priority (urgency) order.
Domains     free, type-compatible, reachable vehicles.
Constraints each incident gets at most one vehicle, each vehicle serves at
            most one incident (no double-booking).
Objective   lexicographic: serve as much urgency as possible, then travel as
            little as possible.

Search is plain backtracking with forward checking (assigning a vehicle
removes it from every later incident's domain) and branch-and-bound on the
objective. An incident may be left unserved, because there can be more
incidents than usable vehicles; forward checking exposes this early, when a
domain empties, so the bound stops counting that incident.
"""
from dataclasses import dataclass, field

EPS = 1e-9


@dataclass
class Allocation:
    assignment: dict = field(default_factory=dict)  # variable -> value; unserved omitted
    served: float = 0.0                             # total weight of served variables
    cost: float = 0.0
    nodes: int = 0                                  # search nodes visited
    pruned: int = 0                                 # domain values removed by forward checking


def allocate(weights, domains, cost):
    """weights: {var: priority weight}, in priority order.
    domains: {var: [value, ...]}. cost: cost(var, value) -> float."""
    order = list(weights)
    result = Allocation()
    best = [-1.0, float("inf")]                     # (served, cost) of best leaf so far
    assigned = {}

    def visit(k, doms, served, spent):
        result.nodes += 1
        bound = served + sum(weights[j] for j in order[k:] if doms[j])
        if bound < best[0] - EPS or (bound < best[0] + EPS and spent >= best[1]):
            return
        if k == len(order):
            best[:] = [served, spent]
            result.assignment = dict(assigned)
            return
        var = order[k]
        for val in sorted(doms[var], key=lambda x: cost(var, x)):
            nxt = {j: [x for x in doms[j] if x != val] for j in order[k + 1:]}
            result.pruned += sum(len(doms[j]) - len(nxt[j]) for j in nxt)
            assigned[var] = val
            visit(k + 1, nxt, served + weights[var], spent + cost(var, val))
            del assigned[var]
        visit(k + 1, {j: doms[j] for j in order[k + 1:]}, served, spent)  # leave unserved

    visit(0, {v: list(domains[v]) for v in order}, 0.0, 0.0)
    result.served, result.cost = max(best[0], 0.0), best[1]
    return result
