# Aegis

AI-based multi-agent emergency response simulation over 14 north-Indian cities: BFS / DFS /
UCS / A* route racing, CSP vehicle allocation, urgency priority, replanning after road
closures and breakdowns, rule-based reasoning and escalation planning, with a Pygame control
centre.

```
pip install -r requirements.txt
python main.py                         # control centre (map + control panel)
python main.py --compare Delhi Kota    # algorithm comparison for one route
python main.py --analyze               # scenarios + benchmark -> results/ (CSVs, charts)
python main.py --parse "Fire in Jaipur, 200 people affected. At 2 hours the Jaipur-Ajmer road closes."
python -m unittest discover -s tests   # tests
```

## How it works

- Every vehicle is stationed at one base (Delhi): 2 fire trucks, 2 ambulances, 1 police.
- For every trip the vehicle runs **all four** search algorithms and drives the best route
  (shortest, then fewest nodes searched). The other three routes are driven by faded "ghost"
  trucks at the same speed, and the route-race card on the map compares them.
- When several incidents are open, they are ranked by urgency (severity x people / hours
  waiting) and a CSP assigns compatible vehicles, serving the most urgent first.
- Disruptions (road closures, vehicle breakdowns, random events) make the affected vehicles
  replan and send the incident back to the CSP when a vehicle can no longer serve it.
- After a job a vehicle spends an hour on scene, then drives back to base; it can be re-tasked
  on the way.

## Control panel

1. **Report an incident**: type, location (or click a city on the map), severity, people.
   *Report now* dispatches immediately; *Add to batch* + *Dispatch batch* reports several
   incidents at the same moment, so they are prioritised against each other.
2. **Disruptions**: close or reopen a road (or right-click it on the map), break down a
   driving vehicle (or click it on the map to select it), switch random disruptions on.
3. **Simulation**: pause, speed, reset, and *Run demo* (the scripted `showcase` scenario).

Keys: `SPACE` pause, `+`/`-` speed, `Enter` report now, `R` reset, `D` demo, `T` type a scenario
in plain English (beta, the future prompt bar), `Esc` quit.

See `DEMO_SCRIPT.md` for the presentation walkthrough and `AEGIS_IMPLEMENTATION_PLAN.md`
(one level up) for the module plan and status.
