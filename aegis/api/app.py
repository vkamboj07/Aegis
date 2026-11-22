"""The AEGIS web service: the simulation as JSON, plus the browser front end.

Shape of the thing
------------------
Every route that touches a simulation does the same three steps, in order:
hold the session's lock, bring its clock up to now, then act. Acting before
advancing would apply a command at a stale simulated time - an incident
reported "at t=3.0 h" when the run is really at t=4.2 h - and the CSP would
prioritise it against the wrong queue.

Routes are plain `def`, not `async def`, on purpose. The engine is synchronous
CPU work - the CSP does real backtracking search - so Starlette running each
call in its worker threadpool is exactly right; an `async def` would block the
event loop for every other visitor while one allocation ran.
"""
import json
import os
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from aegis import __version__
from aegis.api import serialize
from aegis.api.schemas import BatchIn, ControlIn, DemoIn, IncidentIn, RoadIn, ScenarioIn
from aegis.api.sessions import SessionLimit, SessionStore
from aegis.core import clock
from aegis.core.ai.logic import explain, incident_facts
from aegis.core.algorithms import ALGORITHMS
from aegis.core.environment.events import DEFAULT_SCENARIOS
from aegis.core.prompt_engine.parser import describe
from aegis.core.prompt_engine.scenario_generator import build_scenario, schedule
from aegis.core.simulation.engine import AVG_SPEED_KMH
from aegis.core.simulation.fairness import fairness_rows, summary

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
INCIDENT_TYPES = ["Fire", "Accident", "Medical"]

app = FastAPI(
    title="AEGIS",
    version=__version__,
    description="Multi-agent emergency response simulation: search, CSP allocation, "
                "knowledge rules and replanning, over 14 north-Indian cities.",
)
store = SessionStore()

# Same-origin by default: the service serves its own front end, so no browser
# needs cross-origin access unless someone deliberately opens it up.
_origins = [o.strip() for o in os.environ.get("AEGIS_ALLOW_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins,
                       allow_methods=["*"], allow_headers=["*"])


# ---- helpers -----------------------------------------------------------
def _session(session_id):
    session = store.get(session_id)
    if session is None:
        # 404 is the signal the client watches for: its run has expired or the
        # instance restarted, so it should create a new session and carry on.
        raise HTTPException(404, "no such session; create a new one")
    return session


def _city(session, name):
    if name not in session.graph.coords:
        raise HTTPException(422, f"unknown city: {name}")
    return name


def _road(session, a, b):
    road = session.graph.road(a, b)
    if road is None:
        raise HTTPException(422, f"no road between {a} and {b}")
    return road


def _incident_args(session, item):
    if item.kind not in INCIDENT_TYPES:
        raise HTTPException(422, f"unknown incident type: {item.kind}")
    return dict(kind=item.kind, location=_city(session, item.location),
                severity=item.severity, people=item.people)


def _state(session, since=0):
    return serialize.state_payload(session, since)


# ---- service -----------------------------------------------------------
@app.get("/healthz", tags=["service"])
def healthz():
    """Liveness and capacity, for a load balancer or an uptime check."""
    return {"status": "ok", "version": __version__, **store.stats()}


@app.get("/api/meta", tags=["service"])
def meta():
    """What the front end needs to build its controls."""
    scenarios = json.loads(DEFAULT_SCENARIOS.read_text())
    return {
        "version": __version__,
        "incident_types": INCIDENT_TYPES,
        "speeds": clock.SPEEDS,
        "default_speed": clock.DEFAULT_SPEED,
        "avg_speed_kmh": AVG_SPEED_KMH,
        "algorithms": list(ALGORITHMS),
        "scenarios": [{"name": k, "description": v.get("description", "")}
                      for k, v in scenarios.items()],
    }


# ---- sessions ----------------------------------------------------------
@app.post("/api/sessions", status_code=201, tags=["session"])
def create_session():
    """Start a new run. The map is returned with it, since it never changes."""
    try:
        session = store.create()
    except SessionLimit as e:
        raise HTTPException(503, f"{e}; try again in a few minutes")
    return {"map": serialize.map_payload(session.graph, session.proj),
            "state": _state(session)}


@app.delete("/api/sessions/{session_id}", tags=["session"])
def delete_session(session_id: str):
    return {"dropped": store.drop(session_id)}


@app.get("/api/sessions/{session_id}/map", tags=["session"])
def get_map(session_id: str):
    session = _session(session_id)
    return serialize.map_payload(session.graph, session.proj)


@app.get("/api/sessions/{session_id}/state", tags=["session"])
def get_state(session_id: str,
              since: int = Query(0, description="records already seen; -1 for none")):
    """Advance the clock to now and return the current state.

    This is the only thing the browser polls, and the only thing that makes
    simulated time pass.
    """
    session = _session(session_id)
    with session.lock:
        session.advance()
        return _state(session, since)


@app.post("/api/sessions/{session_id}/reset", tags=["session"])
def reset(session_id: str):
    session = _session(session_id)
    with session.lock:
        session.reset()
        return _state(session, -1)


# ---- commands ----------------------------------------------------------
@app.post("/api/sessions/{session_id}/incidents", tags=["command"])
def report_incident(session_id: str, item: IncidentIn):
    """Report one incident now: rules fire, then the CSP allocates."""
    session = _session(session_id)
    with session.lock:
        session.advance()
        args = _incident_args(session, item)
        inc = session.sim.report(**args)
        return {"incident": inc.id, "state": _state(session)}


@app.post("/api/sessions/{session_id}/incidents/batch", tags=["command"])
def report_batch(session_id: str, batch: BatchIn):
    """Report several incidents at the same simulated moment."""
    session = _session(session_id)
    with session.lock:
        session.advance()
        args = [_incident_args(session, item) for item in batch.items]
        incidents = session.sim.report_batch(args)
        session.batch = []
        return {"incidents": [i.id for i in incidents], "state": _state(session)}


@app.put("/api/sessions/{session_id}/batch", tags=["command"])
def stage_batch(session_id: str, batch: BatchIn = Body(None)):
    """Hold incidents on the server so a reconnecting page keeps its staging list."""
    session = _session(session_id)
    with session.lock:
        items = [] if batch is None else [_incident_args(session, i) for i in batch.items]
        session.batch = items
        return {"batch": session.batch}


@app.post("/api/sessions/{session_id}/roads", tags=["command"])
def set_road(session_id: str, item: RoadIn):
    """Close or reopen a road; omit `closed` to toggle it."""
    session = _session(session_id)
    with session.lock:
        session.advance()
        road = _road(session, item.a, item.b)
        closed = (not road.closed) if item.closed is None else item.closed
        session.sim.set_road(road.a, road.b, closed)
        return {"road": sorted(road.key), "closed": road.closed, "state": _state(session)}


@app.post("/api/sessions/{session_id}/vehicles/{name}/breakdown", tags=["command"])
def break_down(session_id: str, name: str):
    """Break a driving vehicle down: its incident goes back to the CSP."""
    session = _session(session_id)
    with session.lock:
        session.advance()
        if session.sim.vehicle(name) is None:
            raise HTTPException(422, f"unknown vehicle: {name}")
        ok = session.sim.break_down(name)
        return {"broken": ok, "state": _state(session)}


@app.post("/api/sessions/{session_id}/control", tags=["command"])
def control(session_id: str, item: ControlIn):
    """Pause, change speed, or switch random disruptions on and off."""
    session = _session(session_id)
    with session.lock:
        if item.speed is not None:
            session.set_speed(item.speed)
        if item.paused is not None:
            session.set_paused(item.paused)
        if item.random_events is not None:
            session.set_random_events(item.random_events)
        return _state(session)


@app.post("/api/sessions/{session_id}/demo", tags=["command"])
def demo(session_id: str, item: DemoIn):
    """Queue a scripted scenario from the scenarios file."""
    session = _session(session_id)
    with session.lock:
        session.advance()
        try:
            if item.reset:
                session.reset()
            scenario = session.sim.queue.load_scenario(item.name)
        except KeyError:
            raise HTTPException(422, f"unknown scenario: {item.name}")
        session.paused = False
        session.sim.note(f"DEMO: {scenario['description']}")
        return {"scenario": item.name, "state": _state(session, -1 if item.reset else 0)}


@app.post("/api/sessions/{session_id}/scenario", tags=["command"])
def scenario(session_id: str, item: ScenarioIn):
    """Interpret a plain-English scenario and, by default, queue its events."""
    session = _session(session_id)
    with session.lock:
        session.advance()
        parsed = build_scenario(item.text, session.graph, use_llm=item.use_llm)
        if item.run and parsed["events"]:
            schedule(session.sim, parsed)
            session.sim.note("Prompt engine queued: "
                             + "; ".join(describe(e) for e in parsed["events"]))
        elif item.run:
            session.sim.note("Prompt engine: could not interpret that scenario.")
        for warning in parsed["warnings"]:
            session.sim.note(f"Prompt engine: {warning}")
        return {"scenario": {**parsed, "described": [describe(e) for e in parsed["events"]]},
                "state": _state(session)}


# ---- read-only analysis ------------------------------------------------
@app.get("/api/sessions/{session_id}/compare", tags=["analysis"])
def compare(session_id: str, start: str, goal: str):
    """Every algorithm's route for one trip, on this session's current graph."""
    session = _session(session_id)
    _city(session, start)
    _city(session, goal)
    with session.lock:
        rows = []
        for name, search in ALGORITHMS.items():
            path, cost, expanded, secs = search(session.graph, start, goal)
            rows.append({"algorithm": name, "path": path,
                         "distance_km": round(cost, 1) if path else None,
                         "hours": round(cost / AVG_SPEED_KMH, 2) if path else None,
                         "nodes_expanded": expanded, "search_ms": round(secs * 1000, 3),
                         "reachable": bool(path)})
        return {"start": start, "goal": goal, "rows": rows}


@app.get("/api/sessions/{session_id}/explain", tags=["analysis"])
def explain_rules(session_id: str, kind: str, city: str, people: int = Query(10, ge=1)):
    """Which knowledge rules fire for an incident, with the backward-chaining proof."""
    session = _session(session_id)
    _city(session, city)
    if kind not in INCIDENT_TYPES:
        raise HTTPException(422, f"unknown incident type: {kind}")
    facts = incident_facts(kind, session.graph.tags[city], people)
    return {"kind": kind, "city": city, "people": people,
            "facts": sorted(facts),
            "rules": [{"name": name, "fires": proof is not None, "proof": proof or []}
                      for name, proof in explain(facts).items()]}


_fairness_result = {}


@app.get("/api/fairness", tags=["analysis"])
def fairness():
    """Response time per city for one standard incident, against distance from base.
    The result does not depend on any session, so it is computed once per process."""
    if not _fairness_result:
        rows = fairness_rows()
        _fairness_result.update(rows=rows, summary=summary(rows))
    return _fairness_result


@app.exception_handler(SessionLimit)
def _limit_handler(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=503)


# ---- front end ---------------------------------------------------------
# Mounted last and at the root, so every API route above is matched first and
# the browser control centre is served from the same origin as the API it calls
# - no CORS, no second deployment, one URL to hand out.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
