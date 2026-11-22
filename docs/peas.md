# PEAS description of Aegis agents

PEAS (Performance, Environment, Actuators, Sensors) describes each agent in the system. The
simulation has three agent types, plus two decision components that act on their behalf.

## 1. Vehicle agent (fire truck, ambulance, police)

Implemented in `ai/agents.py` (perceive → decide → act every tick).

| | |
|---|---|
| Performance | Reach the incident quickly, resolve it, return to base; avoid routes that are closed |
| Environment | City road graph with closures, breakdowns of other vehicles, incidents across 14 cities |
| Actuators | Drive a route, switch route at the next junction, stop on scene for 1 h, return to base |
| Sensors | Own location and status, status of the roads on its route (open or closed), assigned incident |

Decision: run all four searches (BFS, DFS, UCS, A*) on the current graph and drive the route with
the lowest distance, breaking ties by the fewest nodes searched (`ai/routing.py`).

## 2. Incident (the object the system responds to)

Not an agent, but part of the environment. Its state: type, location, severity, people affected,
time reported, status (active, assigned, resolved).

## 3. Allocator (acts for the operations centre)

Implemented in `ai/csp.py`. Given the open incidents and the free vehicles, it chooses which
vehicle serves which incident.

| | |
|---|---|
| Performance | Serve the most urgent incidents first, with the least total travel |
| Environment | Open incidents, free vehicles, vehicle-type compatibility |
| Actuators | Assign a vehicle to an incident, or leave the incident waiting |
| Sensors | Urgency scores (`ai/heuristics.py`), vehicle status |

## 4. Rule engine (knowledge base)

Implemented in `ai/rules.py`, with a propositional form and proofs in `ai/logic.py`.

| | |
|---|---|
| Performance | Apply the facts of the domain to each incident, once per incident |
| Environment | Incident type and people affected, facility tags of the city (hospital, fuel depot, tourist hub) |
| Actuators | Raise severity or the number of people affected |
| Sensors | Incident fields and city tags |

Forward chaining runs in the simulation. Backward chaining (`python main.py --explain TYPE CITY
PEOPLE`) shows why a rule fires, as a chain of facts. Resolution checks that the rules in code and
the propositional form agree for every combination of inputs (`tests/test_logic.py`).

## 5. Planner (escalation)

Implemented in `ai/planning.py`. Raises the severity of an incident that has waited more than
2 h, then asks the allocator to run again.

| | |
|---|---|
| Performance | Keep long-waiting incidents from being forgotten |
| Environment | Open incidents and how long each has waited |
| Actuators | Raise severity by 1 (capped at 5) and request re-allocation |
| Sensors | Time reported and the current time |

## Environment properties

- **Partially observable**: a vehicle sees only the status of its own route, not the whole city.
- **Dynamic**: roads close and vehicles break down during the run.
- **Stochastic** (optional): random disruptions, seeded for repeatable runs.
- **Discrete time**: the engine advances in fractions of an hour.
- **Multi-agent**: several vehicles act at once and compete for incidents.
