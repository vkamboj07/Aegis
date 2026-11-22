# Plan 1: Road-level travel time and congestion

## Why

The simulation moves every vehicle at a flat 60 km/h (`simulation/engine.py`, `AVG_SPEED_KMH`),
and the searches minimise distance. The README's own limits table lists this as "no traffic
model". Response times are therefore just distance divided by one number, and the analytics
charts cannot show anything about congestion or road quality. This plan makes travel time a
real property of each road, without breaking the four search algorithms or the demo.

## Current state (what the code does today)

- `data/cities.json` stores roads as `[a, b, distance_km]` triples.
- `environment/roads.py` `Road` has `distance` and `closed` only.
- `CityGraph.neighbors` yields `(neighbor, distance)`; `heuristic` is straight-line km
  (`environment/city.py`), and `validate()` rejects any road shorter than its straight line.
- `algorithms/*.py` all use `graph.neighbors` with distance as the edge weight.
- `simulation/engine.py` converts hours to km with one constant (around line 182).
- `simulation/race.py` moves ghost vehicles at the vehicle's speed, so they arrive later only
  because their routes are longer.

## Goals

1. Each road has its own free-flow speed (for example highway 80 km/h, state road 50 km/h,
   district road 40 km/h), with an optional congestion profile by hour of the simulation clock.
2. The vehicle drives at the speed of each road it is on, so travel time is the real arrival
   measure.
3. The search algorithms keep their signature and still work. A* stays admissible.
4. The demo still runs. The numbers in `DEMO_SCRIPT.md` may change, and that is acceptable only
   if they are regenerated and rechecked.

## Design decisions

**D1. Keep distance as the default search cost; add time as an option.**
The benchmark (`--analyze`, `algorithm_distance.png`) compares algorithms on distance, and the
report already uses those results. Changing the default cost would silently change the benchmark.
So each `search` gets an optional `cost` argument: `"distance"` (default) or `"time"`. The
signature stays `search(graph, start, goal, cost="distance")`. `ALGORITHMS` in `algorithms/`
keeps the plain form for the benchmark.

**D2. Admissible time heuristic.**
For time cost the heuristic is `haversine(a, b) / MAX_SPEED_KMH`, where `MAX_SPEED_KMH` is the
fastest free-flow speed in the data. Congestion only slows roads, so the bound holds. Replace the
current "roads are never shorter" check in `validate()` with a per-road check:
`distance >= straight_line` (unchanged) and, for time, `time_per_road >= straight_line / MAX_SPEED`.

**D3. Road speed and congestion live in the data, not the code.**
Extend the road entry to `[a, b, distance_km]` plus an optional dict
`{"speed": 80, "class": "highway", "peak": 0.7}`. Old triples must still load, defaulting to
60 km/h, so nothing breaks while the data is migrated.

**D4. Congestion is a multiplier on a schedule, not a traffic model.**
Each road class has a multiplier by hour of day (for example 0.6 at 08:00–10:00 and 17:00–20:00).
The simulation clock starts at 0 h, so add a `start_hour` setting (default 8) so the morning peak
falls in the demo. This is a schedule, so runs stay deterministic. No random traffic.

**D5. Vehicles move per road.**
`engine.py` advances each vehicle along its path edge by edge, and the speed on each edge comes
from the road at the moment the vehicle enters it. `race.py` ghosts use the same rule, so the race
card compares real arrival times.

## Work breakdown

| # | Step | Files | Done when |
|---|---|---|---|
| 1 | Extend road data and loader (backward compatible) | `environment/roads.py`, `environment/city.py`, `data/cities.json` | Old and new formats both load; a test loads both |
| 2 | Time cost in the searches (`cost` argument) | `algorithms/*.py` | UCS and A* with `cost="time"` return the same optimal time on every city pair |
| 3 | Admissibility check for time | `environment/city.py` `validate()` | Test fails if a road is set faster than its straight line allows |
| 4 | Congestion schedule | new `environment/traffic.py`, `simulation/engine.py` | Same route takes longer at 08:00 than at 12:00 |
| 5 | Per-road movement in engine and ghosts | `simulation/engine.py`, `simulation/race.py` | Arrival time equals sum of edge times within 1 %; ghost arrivals match |
| 6 | Analytics: add time metrics | `simulation/recorder.py`, `visualization/charts.py` | `algorithm_time.png` written by `--analyze`; response-time chart uses hours from dispatch |
| 7 | Demo regeneration | `DEMO_SCRIPT.md`, `results/` | Every number in the script is regenerated and rechecked |

Steps 1–3 are pure data and search work and can be merged first. Steps 4–5 touch the engine and
need the existing replanning tests to stay green.

## Tests to add

- Every road: `time_cost >= straight_line / MAX_SPEED` (admissibility over the real dataset).
- A* and UCS return equal time cost on all 182 city pairs (the benchmark already iterates pairs).
- Old triple format still loads with 60 km/h.
- Congestion: peak-hour travel time > off-peak for the same route.
- Replanning still fires when a closed road is on the route (`tests/test_replanning.py`).
- Ghost arrival time equals the search's time cost for that route.

## Risks and mitigations

- **Demo numbers change.** Keep the flat profile as `--profile flat` (default until the demo is
  rehearsed), so the current script still holds. Switch to `--profile realistic` only after
  regenerating the script.
- **Admissibility silently breaks.** The per-road validator runs at load time, so bad data fails
  fast instead of giving wrong routes.
- **Scope creep into a traffic simulator.** Out of scope: vehicle-to-vehicle interaction, queues,
  incidents on roads, weather. Say so in the report's limits table.

## Effort

Roughly 2–3 focused days: about half a day for steps 1–3, a day for steps 4–5, and the rest for
analytics, tests and demo regeneration.
