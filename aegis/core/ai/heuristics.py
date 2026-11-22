"""Incident prioritisation."""


def urgency(incident, now):
    """severity * people_affected / max(1, hours since reported)."""
    elapsed = now - incident.time_reported
    return incident.severity * incident.people_affected / max(1.0, elapsed)


def rank(incidents, now):
    """Most urgent first; ties keep report order."""
    return sorted(incidents, key=lambda i: urgency(i, now), reverse=True)
