"""Vehicle agents: each simulation tick every vehicle runs perceive -> decide -> act."""
from aegis.core.ai.routing import plan_routes


class VehicleAgent:
    def __init__(self, vehicle):
        self.v = vehicle
        self.needs_replan = False

    def perceive(self, graph):
        """Flag the route as stale if a road it still has to use has closed."""
        v = self.v
        self.needs_replan = False
        if not v.moving:
            return
        if v.pending:
            # already switching routes: stale only if the new route or the
            # segment we are driving on has since closed
            best, options = v.pending
            self.needs_replan = (_blocked(graph, options[best][0])
                                 or (not v.backtrack and _blocked(graph, v.path[v.seg:v.seg + 2])))
        else:
            self.needs_replan = _blocked(graph, v.path[v.seg:])

    def decide(self, graph):
        """Re-run every search algorithm on the updated graph and keep the best.
        Returns a log line when a replan happened."""
        if not self.needs_replan:
            return None
        v = self.v
        here, ahead = v.path[v.seg], v.path[v.seg + 1]
        if v.backtrack or graph.road(here, ahead).closed:
            # the road under the wheels is closed: turn back to the last junction
            start, v.backtrack = here, True
            how = "turning back to"
        else:
            start = ahead               # finish this segment, replan from the next junction
            how = "rerouting from"
        v.pending = plan_routes(graph, start, v.target)
        v.replans += 1
        return (f"{v.name}: road ahead closed, {how} {start} - REPLANNING "
                f"(new route by {v.pending[0]}).")

    def act(self, km, env):
        """Advance `km` along the route; switch routes at junctions."""
        v = self.v
        if not v.moving:
            return
        if v.backtrack:
            v.seg_progress -= km
            if v.seg_progress > 0:
                return
            v.seg_progress, v.backtrack = 0.0, False
            self._switch(env)
            return
        v.seg_progress += km
        while v.moving:
            dist = env.graph.road(v.path[v.seg], v.path[v.seg + 1]).distance
            if v.seg_progress < dist:
                return
            v.seg_progress -= dist
            v.seg += 1
            v.location = v.path[v.seg]
            if v.pending:
                self._switch(env)
            elif v.seg >= len(v.path) - 1:
                v.moving, v.seg_progress = False, 0.0
                env.arrive(v)

    def _switch(self, env):
        v = self.v
        (best, options), v.pending = v.pending, None
        if not options[best][0]:
            env.abandon(v)              # no route left to the destination
            return
        v.set_route(best, options, progress=v.seg_progress)
        env.route_switched(v, best, options)
        if not v.moving:
            env.arrive(v)


def _blocked(graph, path):
    return any(graph.road(a, b).closed for a, b in zip(path, path[1:]))
