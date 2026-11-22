"""Simulation state -> JSON for the browser control centre.

Two kinds of payload:

`map_payload` is the part that never changes during a run - the projected
cities, roads and scenery. It is fetched once and cached by the client.

`state_payload` is the per-frame part, and it is deliberately *drawn*, not raw:
positions arrive already projected into the 800x720 map space from
`aegis.core.geo`, the same code the Pygame build uses. The browser therefore
plots the same pixels rather than reimplementing the projection, the lane
offsets and the parking slots - and the two front ends cannot drift apart.
"""
from aegis.core import geo, report
from aegis.core.ai.heuristics import urgency
from aegis.core.ai.routing import PREFERENCE
from aegis.core.environment.vehicles import KINDS
from aegis.core.simulation.engine import AVG_SPEED_KMH

LOG_TAIL = 200          # most recent log lines a late-joining client is given


def _rgb(c):
    return "#%02x%02x%02x" % tuple(c)


def _xy(p):
    return {"x": round(p[0], 2), "y": round(p[1], 2)}


def map_payload(graph, proj):
    """Everything static the client needs to draw the map once."""
    return {
        "width": geo.MAP_W,
        "height": geo.MAP_H,
        "projection": proj.params(),
        "depot": graph.depot,
        "base": dict(zip(("x", "y", "w", "h"), [round(v, 2) for v in proj.base_rect(graph.depot)])),
        "avg_speed_kmh": AVG_SPEED_KMH,
        "algorithms": PREFERENCE,
        "algorithm_colors": {a: _rgb(c) for a, c in geo.ALGO_COLOR.items()},
        "status_colors": {k: _rgb(c) for k, c in geo.STATUS_COLOR.items()},
        "vehicle_kinds": {kind: {"handles": list(handles), "color": _rgb(color)}
                          for kind, (handles, color) in KINDS.items()},
        "cities": [{"name": n, **_xy(proj.pos[n]),
                    "lat": graph.coords[n][0], "lon": graph.coords[n][1],
                    "radius": geo.MAJOR.get(n, 7),
                    "label": geo.LABEL_SIDE.get(n, "bottom"),
                    "tags": sorted(graph.tags.get(n, ()))}
                   for n in graph.nodes],
        "roads": [{"a": r.a, "b": r.b, "distance": r.distance,
                   "from": _xy(proj.pos[r.a]), "to": _xy(proj.pos[r.b])}
                  for r in sorted(graph.roads.values(), key=lambda r: (r.a, r.b))],
        "scenery": {
            "rivers": [{"name": name, "points": [_xy(p) for p in proj.line(pts)]}
                       for name, pts in geo.RIVERS.items()],
            "hills": {"name": "Aravalli Range",
                      "points": [_xy(p) for p in proj.line(geo.ARAVALLI)]},
            "states": [{"name": name, **_xy(proj.project(lat, lon))}
                       for name, lat, lon in geo.STATES],
            "graticule": {
                "lat": [{"label": f"{lat}°N", "y": round(proj.project(lat, 76)[1], 2)}
                        for lat in range(26, 31)],
                "lon": [{"label": f"{lon}°E", "x": round(proj.project(28, lon)[0], 2)}
                        for lon in range(75, 79)],
            },
        },
    }


def _route_ahead(sim, proj, index, v):
    """The stretch of route still to drive, from the truck's nose onwards."""
    if not v.moving:
        return []
    x, y, _ = proj.vehicle_pose(sim.graph, index, v, sim.fleet, sim.depot)
    if v.backtrack:
        rest = [v.path[v.seg]]
    elif v.pending:
        rest = [v.path[v.seg + 1]]          # the old route ends at the junction
    else:
        rest = v.path[v.seg + 1:]
    return [{"x": round(x, 2), "y": round(y, 2)}] + [_xy(proj.pos[n]) for n in rest]


def _vehicle(sim, proj, index, v):
    x, y, heading = proj.vehicle_pose(sim.graph, index, v, sim.fleet, sim.depot)
    text, level = report.vehicle_status(sim, v)
    pending_path = []
    if v.pending and v.pending[1][v.pending[0]][0]:
        best, options = v.pending
        pending_path = [_xy(proj.pos[n]) for n in options[best][0]]
    return {
        "name": v.name, "kind": v.kind, "status": v.status, "algorithm": v.algorithm,
        "x": round(x, 2), "y": round(y, 2), "heading": round(heading, 1),
        "moving": v.moving, "backtrack": v.backtrack, "incident": v.incident,
        "target": v.target, "location": v.location, "replans": v.replans,
        "remaining_km": round(geo.remaining_km(sim.graph, v), 1),
        "repair_left_h": round(max(0.0, v.until - sim.now), 2) if v.status == "broken" else 0.0,
        "on_scene_left_h": round(max(0.0, v.until - sim.now), 2) if v.status == "on_scene" else 0.0,
        "status_text": text, "level": level,
        "route": _route_ahead(sim, proj, index, v),
        "pending_route": pending_path,
    }


def _incident(sim, proj, inc):
    text, level = report.incident_line(sim, inc)
    return {
        "id": inc.id, "type": inc.type, "location": inc.location,
        "severity": inc.severity, "people": inc.people_affected,
        "status": inc.status, "assigned_to": inc.assigned_to,
        "reported_h": round(inc.time_reported, 2),
        "resolved_h": round(inc.time_resolved, 2) if inc.status == "resolved" else None,
        "urgency": round(urgency(inc, sim.now), 1),
        "summary": text, "level": level,
        **_xy(proj.pos[inc.location]),
    }


def _ghost(sim, proj, g):
    x, y, heading = proj.ghost_pose(sim.graph, g)
    return {"algorithm": g.algorithm, "x": round(x, 2), "y": round(y, 2),
            "heading": round(heading, 1), "km": round(g.km, 1), "cost": round(g.cost, 1)}


def _race(sim, proj, race):
    """A route race: one row per algorithm, plus where each ghost has got to."""
    ghosts = {g.algorithm: g for g in race.ghosts}
    rows = []
    for algo in PREFERENCE:
        if algo not in race.options:
            continue
        path, cost, expanded, secs = race.options[algo]
        if algo == race.chosen:
            arrived, done_km = race.arrived_at, None
        else:
            g = ghosts.get(algo)
            arrived, done_km = (g.arrived_at, g.km) if g else (None, None)
        rows.append({
            "algorithm": algo, "chosen": algo == race.chosen,
            "distance_km": round(cost, 1), "nodes_expanded": expanded,
            "search_ms": round(secs * 1000, 3), "hops": max(0, len(path) - 1),
            "reachable": bool(path),
            "arrived_h": round(arrived, 2) if arrived is not None else None,
            "progress": round(min(1.0, done_km / cost), 3) if done_km and cost else None,
            "path": [_xy(proj.pos[n]) for n in path],
        })
    return {
        "vehicle": race.vehicle, "incident": race.incident, "chosen": race.chosen,
        "destination": race.destination, "started_h": round(race.start, 2),
        "running": race.running, "ended": race.ended, "rows": rows,
        "ghosts": [_ghost(sim, proj, g) for g in race.ghosts
                   if g.arrived_at is None and len(g.path) > 1],
    }


def state_payload(session, since=0):
    """Everything that changes, plus log and record lines newer than `since`.

    `since` is a count of structured records the client has already seen, so a
    poll carries only what is new. A client that has fallen far behind - or has
    just joined - gets the tail rather than the whole history.
    """
    sim = session.sim
    proj = session.proj
    total = len(sim.records)
    since = total if since < 0 else min(max(since, 0), total)
    if total - since > LOG_TAIL:
        since = total - LOG_TAIL
    new = sim.records[since:]
    alloc = sim.allocation
    return {
        "session": session.id,
        "t": round(sim.now, 3),
        "paused": session.paused,
        "speed": session.speed,
        "random_events": session.random_events,
        "batch": list(session.batch),
        "depot": sim.depot,
        "ready": sum(v.status == "idle" and v.location == sim.depot for v in sim.fleet),
        "vehicles": [_vehicle(sim, proj, i, v) for i, v in enumerate(sim.fleet)],
        "incidents": [_incident(sim, proj, i) for i in sim.incidents],
        "ranked": [i.id for i in sim.ranked()],
        "closed_roads": [sorted(r.key) for r in sim.graph.roads.values() if r.closed],
        "races": [_race(sim, proj, r) for r in sim.races[-6:]],
        "handled": [{"vehicle": v.name, "incident": v.incident,
                     **_xy(proj.pos[v.location])}
                    for v in sim.fleet
                    if v.status == "on_scene" and not sim.incident_at(v.location)],
        "allocation": None if alloc is None else {
            "assignment": {str(k): v for k, v in alloc.assignment.items()},
            "served": round(alloc.served, 1), "cost": round(alloc.cost, 1),
            "nodes": alloc.nodes, "pruned": alloc.pruned},
        "queued_events": len(sim.queue),
        "cursor": total,
        "records": new,
        "resolved": sum(i.status == "resolved" for i in sim.incidents),
    }
