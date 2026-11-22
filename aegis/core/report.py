"""Human-readable one-liners about simulation state.

Both control centres show the same sentences for a vehicle or an incident, so
they are written once here. Each returns a (text, level) pair; `level` is a
meaning - not a colour - that each front end renders in its own palette.
"""
from aegis.core import geo
from aegis.core.ai.heuristics import urgency

# level -> what it means, for whoever is picking colours:
#   quiet   nothing happening        active  under way
#   good    finished well            warn    needs attention
#   bad     something went wrong
LEVELS = ("quiet", "active", "good", "warn", "bad")


def vehicle_status(sim, v):
    """What a vehicle is doing right now, as (text, level)."""
    if v.status == "idle":
        at_base = v.location == sim.depot
        return ("At base" if at_base else f"Idle at {v.location}"), "quiet"
    if v.status == "dispatched":
        if v.backtrack:
            how = f"turning back to {v.path[v.seg]}"
        elif v.pending:
            how = f"new route from {v.path[v.seg + 1]}"
        else:
            how = f"{v.algorithm} · {geo.remaining_km(sim.graph, v):.0f} km left"
        return f"To {v.target} · {how}", "active"
    if v.status == "on_scene":
        return f"On scene at {v.location} · {max(0, v.until - sim.now):.1f} h", "good"
    if v.status == "returning":
        return f"Returning to base · {geo.remaining_km(sim.graph, v):.0f} km", "quiet"
    return f"BROKEN DOWN · repaired in {max(0, v.until - sim.now):.1f} h", "bad"


def incident_line(sim, inc):
    """An incident's place in the queue, as (text, level)."""
    who = inc.assigned_to or "WAITING"
    text = (f"{inc.type} · {inc.location} · S{inc.severity} · "
            f"{inc.people_affected} ppl · urg {urgency(inc, sim.now):.0f} · {who}")
    level = {"active": "bad", "assigned": "warn"}.get(inc.status, "good")
    return text, level
