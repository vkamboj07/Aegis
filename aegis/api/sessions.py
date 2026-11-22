"""Per-visitor simulations, and the clock that advances them.

Every visitor to the hosted control centre gets a simulation of their own:
closing a road or breaking a truck must not reach into anyone else's run, and
the city graph is mutable (`Road.closed`), so each session loads its own copy
of it rather than sharing one.

The clock is pulled, not pushed. There is no thread per session ticking away in
the background; a simulation advances when its owner asks for state, by exactly
as much wall time as has passed since the last ask. A session nobody is
watching costs nothing, which is what makes this cheap enough to leave running
on a free tier - and it means a container that gets suspended and resumed wakes
up coherent instead of owing hours of simulated time.
"""
import os
import threading
import time
import uuid

from aegis.core import clock, geo
from aegis.core.environment.city import CityGraph
from aegis.core.simulation.engine import Simulation

# Defaults are sized for a small free-tier instance; override by environment.
MAX_SESSIONS = int(os.environ.get("AEGIS_MAX_SESSIONS", "50"))
SESSION_TTL_S = float(os.environ.get("AEGIS_SESSION_TTL_S", "1800"))
MAX_CATCHUP_S = float(os.environ.get("AEGIS_MAX_CATCHUP_S", "1.0"))


class SessionLimit(Exception):
    """Raised when the instance is already holding as many runs as it allows."""


class Session:
    """One simulation, its presentation state, and its own lock.

    Hold `lock` around anything that advances or mutates the simulation: the
    engine is ordinary synchronous Python, and two requests from the same page
    (a poll and a button) can land at once.
    """

    def __init__(self, session_id):
        self.id = session_id
        self.lock = threading.Lock()
        self.graph = CityGraph.load()        # this session's own, mutable graph
        self.proj = geo.Projection(self.graph.coords)
        self.speed = clock.DEFAULT_SPEED
        self.paused = False
        self.random_events = False
        self.batch = []                     # incidents staged to report together
        self.created = time.time()
        self.last_seen = self.created
        self._wall = time.monotonic()
        self.sim = Simulation(self.graph)

    # ---- lifecycle ----------------------------------------------------
    def reset(self):
        """Start the run over, keeping the visitor's speed and toggles."""
        for road in self.graph.roads.values():
            road.closed = False
        self.sim = Simulation(self.graph)
        self.sim.random_events = self.random_events
        self.batch = []
        self._wall = time.monotonic()

    def touch(self):
        self.last_seen = time.time()

    @property
    def idle_s(self):
        return time.time() - self.last_seen

    # ---- clock --------------------------------------------------------
    def advance(self):
        """Step the simulation by the wall time since the last advance.

        Returns the simulated hours added. Always resets the wall mark, so time
        spent paused is dropped rather than banked up for a lurch on resume.
        """
        now = time.monotonic()
        elapsed, self._wall = now - self._wall, now
        if self.paused:
            return 0.0
        before = self.sim.now
        for slice_s in clock.slices(elapsed, max_catchup=MAX_CATCHUP_S):
            self.sim.step(clock.sim_hours(slice_s, self.speed))
        return self.sim.now - before

    def set_paused(self, paused):
        """Pausing and resuming both re-mark the clock, so neither jumps."""
        self.advance()
        self.paused = bool(paused)

    def set_speed(self, speed):
        self.advance()              # finish the old speed's interval first
        self.speed = clock.nearest_speed(speed)

    def set_random_events(self, on):
        self.advance()
        self.random_events = bool(on)
        self.sim.random_events = self.random_events
        self.sim.note(f"Random disruptions switched {'on' if on else 'off'}.")


class SessionStore:
    """The instance's live sessions, with idle eviction and a hard cap.

    The cap is the point: a public URL is an open invitation to create state,
    and an unbounded dict of simulations is an unbounded memory leak. Idle runs
    are swept first, and only if that frees nothing is a new run refused.
    """

    def __init__(self, max_sessions=MAX_SESSIONS, ttl_s=SESSION_TTL_S):
        self.max_sessions = max_sessions
        self.ttl_s = ttl_s
        self._sessions = {}
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._sessions)

    def create(self):
        with self._lock:
            self._sweep()
            if len(self._sessions) >= self.max_sessions:
                raise SessionLimit(
                    f"this instance is already running {len(self._sessions)} simulations")
            session = Session(uuid.uuid4().hex)
            self._sessions[session.id] = session
            return session

    def get(self, session_id):
        """The session, or None if it never existed or has been swept."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.idle_s > self.ttl_s:
                del self._sessions[session_id]
                return None
            session.touch()
            return session

    def drop(self, session_id):
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def stats(self):
        with self._lock:
            return {"sessions": len(self._sessions), "max_sessions": self.max_sessions,
                    "ttl_s": self.ttl_s}

    def _sweep(self):
        """Forget sessions nobody has asked about in a while. Caller holds the lock."""
        stale = [k for k, s in self._sessions.items() if s.idle_s > self.ttl_s]
        for k in stale:
            del self._sessions[k]
        return len(stale)
