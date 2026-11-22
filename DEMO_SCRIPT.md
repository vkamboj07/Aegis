# AEGIS - Live demo script (about 7 minutes)

One story, told in order: **incidents come in, the AI ranks them, picks vehicles, races every
search algorithm, and recovers when a road closes or a truck breaks down.** Every number below
comes from a run of this code.

## Before you start

```
cd Aegis
python -m unittest discover -s tests      # expect: Ran 65 tests ... OK
python main.py --analyze                  # regenerates results/*.png (charts are not committed)
python main.py
```

The window opens at 0.5x speed. For the scripted demo press `-` once (0.25x) first. Speed is
kept when you press *Run demo*. At 0.25x the road closes about 3.3 s in, the breakdown happens
at about 5.5 s, and the whole run takes about 27 s.

## 1. The setup (30 s)

Point at the map: 14 cities, 21 highways, rivers and the Aravalli hills for orientation, and
hospital, fuel-depot and tourist badges (facts the rule engine uses). Every vehicle is parked
at **AEGIS BASE** in Delhi. Nothing is assigned an algorithm in advance.

## 2. One incident, four algorithms (90 s)

In the panel: Type *Fire*, click **Agra** on the map, Severity 3, then **Report now**.

- A fire truck leaves base. Its blue route is **A\***: 203 km, 4 nodes searched.
- Three faded trucks leave with it: **UCS** (same 203 km, but 9 nodes searched), **BFS**
  (230 km) and **DFS** (352 km).
- The route-race card (top left) shows distance, nodes and progress for each. Say: "Every
  trip runs all four searches. The truck drives the shortest route, and A\* wins the tie with
  UCS because it searched fewer nodes. DFS is the honest failure case: it arrives about 2.5 h
  later."
- After arriving the truck stays on scene for an hour, then drives home.

Press **Reset**.

## 3. Priority: several incidents at once (60 s)

Add three fires to the batch: Jaipur S4 60 people, Agra S3 30 people, Meerut S2 10 people
(choose each, then **Add to batch**). Then **Dispatch batch**.

- There are only two fire trucks. The **Priority order** list ranks the incidents by urgency and
  the CSP gives the trucks to Jaipur and Agra. **Meerut shows WAITING** in red.
- Say: "The incidents were reported at the same moment, so they compete. The CSP serves the
  most urgent first and minimises total travel. Meerut is served as soon as a truck frees up,
  and if it waits long enough the escalation rule raises its severity."

Press **Reset**.

## 4. The full story: Run demo (2 min)

Press `-` once (0.25x), then **Run demo**.

| Real time | What happens | What to say |
|---|---|---|
| 0 s | Fires at Jaipur, Agra and Meerut plus a Medical call at Kota (120 people). Meerut waits. The mass-casualty rule raises Kota's severity. | "Rules and priority before anything moves." |
| about 3.3 s | **Alwar-Jaipur closes** (red with an X). Fire Truck 1 and the ambulance both had it on their route. Both show *new route from Alwar*, with the new route dashed. | **SPACE.** "Perceive: the road ahead closed. Decide: rerun all four searches from the next junction. Act: switch routes there." |
| about 5.5 s | **Fire Truck 2 breaks down** near Mathura (red !, *repair 2 h*). Agra goes back to WAITING. | "The CSP gets the incident back. No fire truck is free, so it waits and escalates." |
| later | Fire Truck 2 is repaired mid-road, gets re-tasked to Agra from where it stands, and later goes to Meerut. All four incidents are resolved by about 12 h. | "Recalculate everything, then move on." |

Live variation: while a truck is driving, right-click a road on its route. The truck either
reroutes from the next junction or, if that road is under its wheels, turns back.

## 5. Chaos mode (30 s)

**Random disruptions: ON**, report a few incidents, and let it run. Roads get blocked for 4 h
and trucks break down at random; every incident still gets resolved. In a test run with three
incidents and heavy chaos (17 random events, 6 breakdowns, 11 replans), all were resolved
and every vehicle ended back at base.

## 6. Results (30 s)

Show `results/algorithm_distance.png` (UCS and A\* shortest on 100% of 182 city pairs, BFS 76%,
DFS 62%), `results/algorithm_nodes.png` and `results/scenario_resolution.png`.

## Limits to state yourself

| Topic | What we built | What it is not |
|---|---|---|
| Planning | Escalation: +1 severity per 2 h unresolved, then re-allocate | Not an MDP |
| CSP | Backtracking, forward checking, branch-and-bound; vehicles heading home can be re-tasked | Never pulls a vehicle off a job it is on |
| Map | 14 cities, 21 roads, constant 60 km/h; terrain is decoration | No traffic model; the layout is schematic |
| Urgency | severity x people / hours waiting | Falls with waiting time; escalation only partly offsets it |
| Prompt bar | `T` (beta) and `--parse` read plain English with keyword rules | Not yet the main input; the panel is |

## If something breaks

1. The window will not open: run `python main.py --compare Delhi Kota` and show the charts.
2. The charts are missing: run `python main.py --analyze` (about 10 s).
3. It is too fast: press `-` or `SPACE`. *Reset* keeps the speed you chose.
