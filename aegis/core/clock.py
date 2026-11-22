"""How real time becomes simulation time.

The simulation measures everything in hours and kilometres; a front end has to
decide how fast those hours should pass on a screen. Both front ends use the
same tempo from here, so 1x means the same thing in the window and in the
browser, and a recorded run lines up with a live one.
"""
from aegis.core.simulation.engine import AVG_SPEED_KMH

BASE_SPEED_KMPS = 110       # simulated km covered per real second at 1x
SPEEDS = [0.25, 0.5, 1, 2, 4, 8]
DEFAULT_SPEED = 1
MAX_SLICE_S = 0.1           # longest real interval fed to the engine in one step


def sim_hours(real_seconds, speed=1.0):
    """Simulation hours that pass in `real_seconds` of wall clock at `speed`."""
    return BASE_SPEED_KMPS * speed * real_seconds / AVG_SPEED_KMH


def slices(real_seconds, max_catchup=None):
    """Split a real interval into steps of at most MAX_SLICE_S.

    One long step is not the same as many short ones: events fire, vehicles
    arrive and the CSP re-runs between steps, so a 5-second jump would skip
    over road closures and overshoot junctions. `max_catchup` caps how much of
    a backlog is replayed at all - a browser tab that was hidden for a minute
    should resume, not spend a minute of CPU catching up.
    """
    if max_catchup is not None:
        real_seconds = min(real_seconds, max_catchup)
    while real_seconds > 1e-9:
        step = min(MAX_SLICE_S, real_seconds)
        real_seconds -= step
        yield step


def nearest_speed(value):
    """Snap an arbitrary requested speed to the nearest offered one."""
    return min(SPEEDS, key=lambda s: abs(s - float(value)))
