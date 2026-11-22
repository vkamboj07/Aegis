"""Tick loop: fires due events, runs every vehicle agent, dispatches via CSP.

All vehicles start at one depot. For every trip all four search algorithms
are run: the vehicle drives the best route (shortest, then fewest nodes
expanded) and the other routes race alongside as ghosts for comparison.
After a job the vehicle spends some time on scene, then drives back to base.
"""
import math
import random

from ai.agents import VehicleAgent
from ai.csp import allocate
from ai.heuristics import rank, urgency
from ai.planning import escalate
from ai.routing import plan_routes
from ai.rules import apply_rules
from environment.events import EventQueue
from environment.incidents import Incident
from environment.vehicles import default_fleet
from simulation.race import Race

AVG_SPEED_KMH = 60
ON_SCENE_H = 1.0        # time spent at an incident before driving back to base
REPAIR_H = 2.0          # time a broken-down vehicle is out of service
CHAOS_PER_HOUR = 0.3    # random disruptions per simulated hour, when switched on
REOPEN_AFTER_H = 4.0    # a randomly blocked road reopens after this long
INF = float("inf")


class Simulation:
    def __init__(self, graph, fleet=None, seed=1):
        self.graph = graph
        self.depot = graph.depot
        self.fleet = fleet if fleet is not None else default_fleet(graph.depot)
        self.agents = [VehicleAgent(v) for v in self.fleet]
        self.queue = EventQueue()
        self.incidents = []
        self.races = []             # route races, newest last
        self.now = 0.0              # simulation hours
        self.events = []            # human-readable log, newest last
        self.records = []           # structured log, for CSV / charts
        self.allocation = None      # latest CSP result
        self._dirty = False         # re-run the CSP only when something changed
        self.random_events = False  # random road blockages and breakdowns
        self.rng = random.Random(seed)

    # ---- queries -------------------------------------------------------
    def open_incidents(self):
        return [i for i in self.incidents if i.status != "resolved"]

    def ranked(self):
        """Open incidents, most urgent first."""
        return rank(self.open_incidents(), self.now)

    def incident_at(self, node):
        return next((i for i in self.open_incidents() if i.location == node), None)

    def vehicle_for(self, incident):
        return next((v for v in self.fleet if v.incident == incident.id), None)

    def incident(self, incident_id):
        return next((i for i in self.incidents if i.id == incident_id), None)

    def vehicle(self, name):
        return next((v for v in self.fleet if v.name == name), None)

    def latest_race(self):
        return self.races[-1] if self.races else None

    # ---- actions -------------------------------------------------------
    def report(self, kind, location, severity=3, people=10):
        inc = self._add_incident(kind, location, severity, people)
        self.think()
        self.dispatch()
        return inc

    def report_batch(self, items):
        """Several incidents at the same moment. All of them are known before
        allocation runs, so the CSP serves them in priority order.
        items: [{"kind", "location", "severity", "people"}, ...]"""
        incidents = [self._add_incident(**item) for item in items]
        self.think()
        self.dispatch()
        return incidents

    def think(self):
        """Knowledge rules, then escalation planning, over all open incidents.
        Re-allocation is requested if any priority changed."""
        open_ = self.open_incidents()
        for inc, rule in apply_rules(open_, self.graph):
            self._log(f"Rule '{rule.name}' fired on {inc.type} #{inc.id} in "
                      f"{inc.location}: now severity {inc.severity}, {inc.people_affected} people.",
                      "rule", inc)
            self._dirty = True
        for inc in escalate(open_, self.now):
            self._log(f"{inc.type} #{inc.id} in {inc.location} unresolved: "
                      f"escalated to severity {inc.severity}.", "escalation", inc)
            self._dirty = True

    def dispatch(self):
        """Allocate free vehicles to waiting incidents with the CSP solver.
        Each (incident, vehicle) pair is priced by the best of all four searches."""
        self._dirty = False
        waiting = [i for i in self.ranked() if i.status == "active"]
        free = [v for v in self.fleet if v.free]
        if not waiting or not free:
            return
        plans, domains = {}, {}
        for inc in waiting:
            domains[inc.id] = []
            for v in free:
                if not v.can_serve(inc.type):
                    continue
                start, extra = self._start_point(v)
                best, options = plan_routes(self.graph, start, inc.location)
                if options[best][1] != INF:
                    plans[inc.id, v.name] = (extra + options[best][1], best, options)
                    domains[inc.id].append(v.name)
        weights = {i.id: urgency(i, self.now) for i in waiting}
        alloc = allocate(weights, domains, lambda i, name: plans[i, name][0])
        self.allocation = alloc
        summary = (f"CSP: {len(alloc.assignment)} of {len(waiting)} incidents assigned "
                   f"({alloc.nodes} nodes, {alloc.pruned} values pruned).")
        if alloc.assignment:            # "nothing assignable" re-runs stay out of the visible log
            self._log(summary, "csp")
        else:
            self._record("csp", detail=summary)
        by_name = {v.name: v for v in free}
        for inc in waiting:
            name = alloc.assignment.get(inc.id)
            if name:
                self._send(by_name[name], inc, *plans[inc.id, name])

    def set_road(self, a, b, closed):
        if self.graph.road(a, b).closed == closed:
            return
        self.graph.set_closed(a, b, closed)
        self._dirty = True          # waiting incidents may be (un)reachable now
        self._log(f"Road {a}-{b} {'CLOSED' if closed else 'reopened'}.",
                  "road_closed" if closed else "road_reopened")

    def toggle_road(self, a, b):
        self.set_road(a, b, not self.graph.road(a, b).closed)

    def break_down(self, name):
        """A vehicle on the road breaks down: it stops where it is for REPAIR_H
        hours and its incident goes back to the CSP for another vehicle."""
        v = self.vehicle(name)
        if not v or v.status not in ("dispatched", "returning"):
            self._log(f"{name} can only break down while it is driving.")
            return False
        inc = self._incident(v.incident) if v.status == "dispatched" else None
        self._end_races(v)
        v.status, v.moving, v.pending, v.backtrack = "broken", False, None, False
        v.until, v.incident = self.now + REPAIR_H, 0
        self._log(f"{v.name} BROKE DOWN after {v.location}; out of service for "
                  f"{REPAIR_H:g} h.", "breakdown", inc, v)
        if inc:
            inc.status, inc.assigned_to = "active", ""
            self._log(f"{inc.type} #{inc.id} in {inc.location} needs another vehicle: "
                      "re-allocating.", "requeued", inc)
        self._dirty = True
        return True

    def note(self, text):
        """Add a free-text line to the decision log."""
        self._log(text)

    def step(self, hours):
        self.now += hours
        for event in self.queue.pop_due(self.now):
            self._apply(event)
        if self.random_events:
            self._random_disruption(hours)
        for v in self.fleet:
            if v.status == "on_scene" and self.now >= v.until:
                self._dirty = True
                self._go_home(v)
            elif v.status == "broken" and self.now >= v.until:
                self._repair(v)
        self.think()
        km = hours * AVG_SPEED_KMH
        for race in self.races:         # before the agents, so a race started this tick
            race.advance(km, self.now)  # does not get a head start on its vehicle
        for agent in self.agents:
            agent.perceive(self.graph)
            note = agent.decide(self.graph)
            if note:
                v = agent.v
                best, options = v.pending
                path, cost, expanded, secs = options[best]
                self._log(note, "replan", self._incident(v.incident), v, algorithm=best,
                          distance_km=round(cost, 1), nodes_expanded=expanded,
                          search_ms=round(secs * 1000, 3))
            agent.act(km, self)
        if self._dirty:
            self.dispatch()

    # ---- called by agents ----------------------------------------------
    def route_switched(self, v, best, options):
        """A vehicle started driving a new route; on a job, that starts a new race."""
        self._end_races(v)
        if v.status == "dispatched":
            self.races.append(Race.begin(v.name, v.incident, self.now, best, options,
                                         v.seg_progress))

    def arrive(self, v):
        self._dirty = True          # a vehicle changed state: allocation may change
        if v.status == "returning":
            v.status = "idle"
            if v.location == self.depot:
                self._log(f"{v.name} is back at base.", "at_base", vehicle=v)
            return
        for race in self.races:
            if race.vehicle == v.name and race.arrived_at is None and not race.ended:
                race.arrived_at = self.now
        inc = self._incident(v.incident)
        v.status, v.until = "on_scene", self.now + ON_SCENE_H
        if inc:
            inc.status, inc.time_resolved = "resolved", self.now
            self._log(f"{v.name} reached {inc.location}: {inc.type} resolved.",
                      "resolved", inc, v, response_h=round(self.now - inc.time_reported, 3))

    def abandon(self, v):
        """No route to the destination any more: requeue the incident, head home."""
        self._end_races(v)
        inc = self._incident(v.incident) if v.status == "dispatched" else None
        v.moving, v.seg_progress, v.pending, v.backtrack = False, 0.0, None, False
        self._dirty = True
        if inc:
            inc.status, inc.assigned_to = "active", ""
            self._log(f"{v.name}: no route to {inc.location} left, "
                      f"{inc.type} #{inc.id} requeued.", "requeued", inc, v)
        self._go_home(v)

    # ---- internals -----------------------------------------------------
    def _add_incident(self, kind, location, severity=3, people=10):
        inc = Incident(kind, location, severity, people, time_reported=self.now)
        self.incidents.append(inc)
        self._log(f"{kind} reported in {location} (severity {severity}, "
                  f"{people} people).", "incident_reported", inc)
        return inc

    def _start_point(self, v):
        """(node a new route starts from, km still to drive to reach it)."""
        if not v.moving:
            return v.location, 0.0
        if v.backtrack:
            return v.path[v.seg], v.seg_progress
        road = self.graph.road(v.path[v.seg], v.path[v.seg + 1])
        return v.path[v.seg + 1], road.distance - v.seg_progress

    def _send(self, v, inc, total_km, best, options):
        v.incident, v.target, v.status, v.replans = inc.id, inc.location, "dispatched", 0
        inc.status, inc.assigned_to = "assigned", v.name
        path, cost, expanded, secs = options[best]
        extra = total_km - cost          # km still to drive to the junction the route starts at
        others = ", ".join(f"{a} {extra + r[1]:.0f} km" for a, r in options.items() if a != best)
        self._log(f"{v.name} sent to {inc.type} in {inc.location}: {best} route, "
                  f"{total_km:.0f} km, {expanded} nodes expanded (others: {others}).",
                  "dispatch", inc, v, algorithm=best, distance_km=round(total_km, 1),
                  nodes_expanded=expanded, search_ms=round(secs * 1000, 3))
        for algo, (p, c, e, s) in options.items():
            self._record("route_option", inc, v, algorithm=algo, distance_km=round(extra + c, 1),
                         nodes_expanded=e, search_ms=round(s * 1000, 3),
                         detail="chosen" if algo == best else "")
        if v.moving:                    # re-tasked on its way home: switch at the next junction
            v.pending = (best, options)
            return
        v.set_route(best, options)
        self.route_switched(v, best, options)
        if not v.moving:
            self.arrive(v)

    def _go_home(self, v):
        v.incident, v.pending, v.backtrack = 0, None, False
        if v.location == self.depot:
            v.status, v.moving, v.path = "idle", False, []
            return
        best, options = plan_routes(self.graph, v.location, self.depot)
        if not options[best][0]:
            v.status, v.moving, v.path = "idle", False, []
            self._log(f"{v.name} cannot reach base; waiting at {v.location}.", vehicle=v)
            return
        v.status, v.target = "returning", self.depot
        v.set_route(best, options)
        self._log(f"{v.name} returning to base ({best} route, {options[best][1]:.0f} km).",
                  "returning", vehicle=v)

    def _repair(self, v):
        self._log(f"{v.name} repaired.", "repaired", vehicle=v)
        self._dirty = True
        if v.path and v.seg < len(v.path) - 1 and v.seg_progress > 0:
            # stopped mid-road: finish this road, then head home from the junction
            v.status, v.target, v.moving = "returning", self.depot, True
            v.pending = plan_routes(self.graph, v.path[v.seg + 1], self.depot)
        else:
            self._go_home(v)

    def _end_races(self, v):
        for race in self.races:
            if race.vehicle == v.name and race.arrived_at is None:
                race.ended = True

    def _apply(self, event):
        d = event.data
        if event.kind == "new_incident":
            # no dispatch here: the CSP runs once at the end of the tick, so
            # incidents reported at the same time are allocated by priority
            self._add_incident(d["incident_type"], d["location"],
                               d.get("severity", 3), d.get("people", 10))
            self._dirty = True
        elif event.kind == "road_closure":
            self.set_road(*d["edge"], closed=True)
        elif event.kind == "road_reopen":
            self.set_road(*d["edge"], closed=False)
        elif event.kind == "vehicle_breakdown":
            self.break_down(d["vehicle"])

    def _random_disruption(self, hours):
        if self.rng.random() >= 1 - math.exp(-CHAOS_PER_HOUR * hours):
            return
        driving = [v for v in self.fleet if v.moving and v.status in ("dispatched", "returning")]
        if driving and self.rng.random() < 0.4:
            v = self.rng.choice(driving)
            self._log(f"Random event: {v.name} has a mechanical fault.", "random_event", vehicle=v)
            self.break_down(v.name)
            return
        on_routes = [frozenset(p) for v in self.fleet if v.moving and v.status == "dispatched"
                     for p in zip(v.path[v.seg:], v.path[v.seg + 1:])]
        candidates = ([k for k in on_routes if not self.graph.roads[k].closed]
                      or [k for k, r in self.graph.roads.items() if not r.closed])
        if not candidates:
            return
        a, b = sorted(self.rng.choice(candidates))
        self._log(f"Random event: road {a}-{b} blocked for {REOPEN_AFTER_H:g} h.", "random_event")
        self.set_road(a, b, True)
        self.queue.schedule(self.now + REOPEN_AFTER_H, "road_reopen", edge=[a, b])

    def _incident(self, incident_id):
        return self.incident(incident_id)

    def _record(self, event, inc=None, vehicle=None, **fields):
        row = {"time_h": round(self.now, 3), "event": event}
        if inc:
            row.update(incident=inc.id, incident_type=inc.type,
                       location=inc.location, severity=inc.severity)
        if vehicle:
            row.update(vehicle=vehicle.name, algorithm=vehicle.algorithm)
        self.records.append({**row, **fields})

    def _log(self, text, event="note", inc=None, vehicle=None, **fields):
        """Append to the human-readable log and to the structured record list."""
        self.events.append(text)
        self._record(event, inc, vehicle, detail=text, **fields)
