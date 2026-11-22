# Responsible AI in Aegis

This note records what the system does to the people it is meant to serve, what we measured,
and what we did not measure.

## 1. Who the system serves

Aegis dispatches emergency vehicles from one base (Delhi) to 14 cities. The people affected are
the residents of those cities. The system does not use personal data: incidents are described by
type, city, severity and an estimated number of people affected, all entered by an operator.

## 2. Service by location (measured)

`python main.py --fairness` reports one standard incident (Fire, severity 3, 50 people) in each
city and the hours from report to arrival, with no other traffic in the system.

| Measure | Value |
|---|---|
| Median response | 3.15 h |
| Slowest city | Kota, 9.7 h (3.1 × median) |
| Cities flagged (≥ 1.5 × median) | Kota, Ajmer, Jaipur, Gwalior |
| Correlation of response with road distance from base | 1.00 |

**Finding.** Response time is fully explained by distance from the base. Because every vehicle is
stationed in Delhi and drives at the same speed, residents of Kota wait about 9.7 h while residents
of Gurugram wait about 0.55 h. The system is not biased against any city in its logic, but its
structure gives remote cities a worse service. This is the main responsible-AI risk of the design.

**Mitigations (not built).**
- Station a second set of vehicles in a remote hub (Jaipur or Kota), and let the allocator choose the
  nearest vehicle. Plan 1's per-road travel times would make the gain realistic.
- Report the flagged cities in the operator's view, so the trade-off is visible when resources
  are assigned.

## 3. Priority and urgency

The urgency score is `severity × people affected ÷ hours waiting` (`ai/heuristics.py`). It favours
incidents with many people affected. This is a deliberate choice, but it has a side effect: an
incident with few people in a remote city can wait behind a large incident in a city near base.
Escalation (+1 severity per 2 h unresolved, `ai/planning.py`) limits how long this can last.

We did not measure this effect in a test batch. It is a known risk, not a measured result.

## 4. The "people affected" figure

The number of people affected is typed in by the operator or inferred by a rule
(`crowded_tourist_hub` assumes at least 60 people at an accident in a tourist hub). That inference
is a stated assumption. It can raise priority for a tourist hub without evidence. The rule is
written in `ai/rules.py` and its logic is checked in `tests/test_logic.py`.

## 5. The optional language model

The scenario parser is keyword-based and runs without a network. The LLM fallback (`--llm`, off by
default) sends only the scenario text and the list of city and road names. It sends no personal
data. Its replies go through the same validator as the parser, so unknown cities, roads or
values are dropped. The text is treated as data, not as instructions.

## 6. Limits of this assessment

- No population data for the cities, so we cannot test fairness across population groups.
- One standard incident per city, not a realistic mix of incidents.
- Travel speed is uniform, so the results describe distance, not road quality or traffic.
- The system has not been evaluated with emergency-service staff.
