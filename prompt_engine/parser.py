"""Keyword / regex interpretation of a natural-language scenario.

    "Major fire in Jaipur, 200 people affected. At 2 hours the Jaipur-Ajmer road closes."
        -> [{"time": 0.0, "type": "new_incident", "incident_type": "Fire",
             "location": "Jaipur", "severity": 4, "people": 200},
            {"time": 2.0, "type": "road_closure", "edge": ["Jaipur", "Ajmer"]}]

The output is the same event format as data/scenarios.json. This layer only
interprets text; every decision after it is made by the AI engine. No network,
no model: the demo never depends on an API.

Conventions: times are hours since the simulation start ("at 2 hours", "after
90 minutes", "t=2"); "N hours later" is relative to the previous sentence; a
sentence with no time inherits the previous sentence's time. A clause with a
city but no keyword continues the previous incident's type ("fires in Jaipur
and Agra"); a clause with only a number of people or a severity word refines
the previous incident ("Fire in Jaipur, 200 people affected").
"""
import re
from dataclasses import dataclass, field

from ai.rules import MAX_SEVERITY

INCIDENT_TYPES = ("Fire", "Accident", "Medical")
EVENT_KINDS = ("new_incident", "road_closure", "road_reopen")
DEFAULT_SEVERITY, DEFAULT_PEOPLE = 3, 10

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20,
                "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                "eighty": 80, "ninety": 90, "hundred": 100}
_WORDS = "|".join(NUMBER_WORDS)
_NUM = rf"(\d+(?:\.\d+)?|{_WORDS})"
_UNIT = r"(hours?|hrs?|h|minutes?|mins?)"
TIME_REL = re.compile(rf"\b{_NUM}\s*{_UNIT}\s+(?:later|afterwards)\b", re.I)
TIME_ABS = re.compile(rf"\b(?:at|after|in|by|around)\s+(?:t\s*=\s*)?{_NUM}\s*{_UNIT}\b", re.I)
TIME_T = re.compile(r"\bt\s*=\s*(\d+(?:\.\d+)?)\b", re.I)

PEOPLE = re.compile(
    rf"\b(\d[\d,]*|{_WORDS})\s*\+?\s*(?:people|persons?|injured|casualties|victims|residents|"
    r"passengers|patients|trapped|stranded|civilians|affected|dead|wounded)\b", re.I)
SEV_EXPLICIT = re.compile(r"\b(?:severity|sev|level)\s*(?:level\s*)?[:=]?\s*([1-5])\b", re.I)
SEV_WORDS = [(5, r"\b(?:massive|critical|catastrophic|huge|devastating|deadly)\b"),
             (4, r"\b(?:major|serious|severe|large|big|significant)\b"),
             (3, r"\b(?:moderate|medium)\b"),
             (2, r"\b(?:minor|small|slight|light|contained)\b")]

KEYWORDS = {
    "Fire": re.compile(r"\b(?:fires?|blaze|burning|flames?|arson|wildfire)\b", re.I),
    "Accident": re.compile(r"\b(?:accidents?|crash(?:es|ed)?|collision|collided|pile-?up|"
                           r"derail\w*|overturned)\b", re.I),
    "Medical": re.compile(r"\b(?:medical|ambulance|heart attack|cardiac|outbreak|epidemic|"
                          r"poisoning|stampede|patients?)\b", re.I),
}
ROAD = re.compile(r"\b(?:roads?|highways?|routes?|links?|bridges?|expressways?|nh\s?\d+|"
                  r"corridor|stretch)\b", re.I)
REOPEN = re.compile(r"\b(?:re-?open\w*|clear(?:s|ed)?|restored?|open(?:s|ed)? again|back open)\b",
                    re.I)
CLOSE = re.compile(r"\b(?:clos(?:e|es|ed|ure|ing)|block(?:s|ed|age|ing)?|shut(?:s|down)?|"
                   r"flood(?:s|ed|ing)?|washed out|impassable|landslide|cut off|collapsed?)\b",
                   re.I)
SENTENCES = re.compile(r"(?<=[.;!?])\s+|\n+")
CLAUSES = re.compile(r",|\bwhile\b|\bbut\b|\bthen\b|\band\b|\bwhere\b|\bwhich\b", re.I)
BETWEEN_AND = re.compile(r"(\bbetween\b[^,;]*?)\band\b", re.I)
ALIASES = {"gurgaon": "Gurugram", "new delhi": "Delhi"}


@dataclass
class ParseResult:
    events: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    method: str = "rules"


class _Cities:
    def __init__(self, cities):
        self.canonical = {c.lower(): c for c in cities}
        self.canonical.update({a: c for a, c in ALIASES.items() if c.lower() in self.canonical})
        names = sorted(self.canonical, key=len, reverse=True)
        self.pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.I)

    def find(self, text):
        return [(m.start(), self.canonical[m.group(1).lower()]) for m in self.pattern.finditer(text)]


def _number(token):
    token = token.lower().replace(",", "")
    return float(NUMBER_WORDS[token]) if token in NUMBER_WORDS else float(token)


def _extract_time(sentence, cursor):
    """Returns (time in hours, sentence with the time phrase removed)."""
    for pattern, relative in ((TIME_REL, True), (TIME_ABS, False), (TIME_T, False)):
        m = pattern.search(sentence)
        if not m:
            continue
        value = _number(m.group(1))
        if len(m.groups()) > 1 and m.group(2).lower().startswith("m"):
            value /= 60
        return (cursor + value if relative else value), sentence[:m.start()] + sentence[m.end():]
    return cursor, sentence


def _people(clause):
    m = PEOPLE.search(clause)
    return max(1, int(_number(m.group(1)))) if m else None


def _severity(clause):
    m = SEV_EXPLICIT.search(clause)
    if m:
        return int(m.group(1))
    for level, pattern in SEV_WORDS:
        if re.search(pattern, clause, re.I):
            return level
    return None


def _nearest_city(cities, position):
    """Closest city to `position`; on a tie, the one after it."""
    return min(cities, key=lambda c: (abs(c[0] - position), c[0] < position))[1]


def _distinct(cities):
    names = []
    for _, name in cities:
        if name not in names:
            names.append(name)
    return names


def _sentence_events(body, time, finder, warnings, memory):
    """Events from one sentence. `memory["edge"]` carries the last road mentioned,
    so "the road reopens" can refer back to it."""
    protected = BETWEEN_AND.sub(r"\1_AND_", body)   # underscores keep it from splitting on "and"
    events = []
    group = []      # incidents from the current keyword clause and its continuations;
                    # each entry: [event, people given explicitly, severity given explicitly]
    for clause in (c.replace("_AND_", "and") for c in CLAUSES.split(protected)):
        cities = finder.find(clause)
        names = _distinct(cities)
        reopen, close = REOPEN.search(clause), CLOSE.search(clause)
        if (reopen or close) and (ROAD.search(clause) or len(names) >= 2):
            if len(names) >= 2:
                memory["edge"] = names[:2]
            elif not (reopen and memory.get("edge")):
                warnings.append(f"Road event needs two cities: '{clause.strip()}'")
                continue
            events.append({"time": time, "type": "road_reopen" if reopen else "road_closure",
                           "edge": list(memory["edge"])})
            continue
        hits = sorted((m.start(), kind) for kind, p in KEYWORDS.items() for m in p.finditer(clause))
        people, severity = _people(clause), _severity(clause)
        if hits:
            position, kind = hits[0]
            if not cities:
                warnings.append(f"No known city in: '{clause.strip()}'")
                continue
            event = {"time": time, "type": "new_incident", "incident_type": kind,
                     "location": _nearest_city(cities, position),
                     "severity": severity or DEFAULT_SEVERITY, "people": people or DEFAULT_PEOPLE}
            events.append(event)
            group = [[event, people is not None, severity is not None]]
        elif cities and group and not (reopen or close):
            base = group[0][0]          # continuation: same type at another city
            event = {**base, "location": names[0],
                     "severity": severity or base["severity"], "people": people or base["people"]}
            events.append(event)
            group.append([event, people is not None, severity is not None])
        elif group and not cities and (people or severity):
            for entry in group:         # refinement of every incident in the group
                if people and not entry[1]:
                    entry[0]["people"] = people
                if severity and not entry[2]:
                    entry[0]["severity"] = severity
    return events


def validate_events(events, cities, roads):
    """Normalise and check events from any source (rules or an LLM).
    Returns (clean events sorted by time, warnings)."""
    canonical = {c.lower(): c for c in cities}
    clean, warnings = [], []
    for e in events:
        try:
            kind, time = e["type"], max(0.0, float(e["time"]))
            if kind == "new_incident":
                itype = str(e["incident_type"]).strip().capitalize()
                city = canonical.get(str(e["location"]).strip().lower())
                if itype not in INCIDENT_TYPES or not city:
                    raise ValueError(f"unknown incident type or city in {e}")
                clean.append({"time": time, "type": kind, "incident_type": itype, "location": city,
                              "severity": min(MAX_SEVERITY, max(1, int(e.get("severity", DEFAULT_SEVERITY)))),
                              "people": max(1, int(e.get("people", DEFAULT_PEOPLE)))})
            elif kind in ("road_closure", "road_reopen"):
                a, b = (canonical.get(str(x).strip().lower()) for x in e["edge"])
                if not a or not b or a == b:
                    raise ValueError(f"unknown city in edge {e['edge']}")
                if frozenset((a, b)) not in roads:
                    raise ValueError(f"there is no direct road {a}-{b}")
                clean.append({"time": time, "type": kind, "edge": [a, b]})
            else:
                raise ValueError(f"unknown event type '{kind}'")
        except (KeyError, TypeError, ValueError) as err:
            warnings.append(f"Skipped event: {err}")
    return sorted(clean, key=lambda e: e["time"]), warnings


def parse(text, cities, roads):
    """Turn scenario text into validated events. `cities`: names; `roads`: set of
    frozenset({a, b}) pairs that exist."""
    finder = _Cities(cities)
    raw, warnings, cursor, memory = [], [], 0.0, {}
    for sentence in SENTENCES.split(text.strip()):
        if not sentence.strip():
            continue
        cursor, body = _extract_time(sentence, cursor)
        found = _sentence_events(body, cursor, finder, warnings, memory)
        if not found:
            warnings.append(f"Could not interpret: '{sentence.strip()}'")
        raw += found
    events, problems = validate_events(raw, cities, roads)
    return ParseResult(events, warnings + problems)


def describe(event):
    """One-line human summary of an event."""
    when = f"t={event['time']:g}h"
    if event["type"] == "new_incident":
        return (f"{when} {event['incident_type']} in {event['location']} "
                f"(severity {event['severity']}, {event['people']} people)")
    verb = "closes" if event["type"] == "road_closure" else "reopens"
    return f"{when} road {event['edge'][0]}-{event['edge'][1]} {verb}"
