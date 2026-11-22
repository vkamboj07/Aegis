"""Escalation lookahead: an unresolved incident gets worse, so re-prioritise.

Deliberately simple (not an MDP): predict that severity rises by one level
for every ESCALATE_EVERY_H hours an incident stays unresolved, apply that
prediction, and let the caller re-rank the queue / re-run allocation.
"""
from aegis.core.ai.rules import MAX_SEVERITY

ESCALATE_EVERY_H = 2.0


def escalate(incidents, now, every=ESCALATE_EVERY_H):
    """Raise severity one level for each incident unresolved for `every` hours
    since it last escalated. Returns the incidents that changed."""
    changed = []
    for inc in incidents:
        if inc.severity < MAX_SEVERITY and now - inc.escalated_at >= every:
            inc.severity += 1
            inc.escalated_at = now
            changed.append(inc)
    return changed
