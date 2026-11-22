"""Knowledge-based rules: (condition, action) pairs over incident and city facts.

Forward chaining, evaluated every tick. Each rule fires at most once per
incident, so repeated evaluation never stacks a boost twice.
"""
from dataclasses import dataclass
from typing import Callable

MAX_SEVERITY = 5


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    when: Callable      # (incident, tags) -> bool; tags = facilities of the incident's city
    then: Callable      # (incident) -> None


def boost(incident, levels=1):
    incident.severity = min(MAX_SEVERITY, incident.severity + levels)


RULES = [
    Rule("fire_at_fuel_depot", "fire at a fuel depot: explosion risk, treat as maximum severity",
         lambda i, tags: i.type == "Fire" and "fuel_depot" in tags,
         lambda i: setattr(i, "severity", MAX_SEVERITY)),
    Rule("medical_at_hospital", "medical call in a hospital city: boost priority",
         lambda i, tags: i.type == "Medical" and "hospital" in tags,
         lambda i: boost(i)),
    Rule("mass_casualty", "100+ people affected: mass-casualty event, boost priority",
         lambda i, tags: i.people_affected >= 100,
         lambda i: boost(i)),
    Rule("crowded_tourist_hub", "accident in a tourist hub: assume at least 60 people affected",
         lambda i, tags: i.type == "Accident" and "tourist_hub" in tags and i.people_affected < 60,
         lambda i: setattr(i, "people_affected", 60)),
]


def apply_rules(incidents, graph, rules=RULES):
    """Fire every applicable rule that has not yet fired on its incident.
    Returns [(incident, rule), ...] in firing order."""
    fired = []
    for inc in incidents:
        tags = graph.tags.get(inc.location, ())
        for rule in rules:
            if rule.name not in inc.fired and rule.when(inc, tags):
                rule.then(inc)
                inc.fired.add(rule.name)
                fired.append((inc, rule))
    return fired
