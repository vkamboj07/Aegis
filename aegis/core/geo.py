"""Map geometry, shared by every front end.

The desktop control centre and the browser one draw the same map, so the
projection, the scenery and the rules for where a vehicle sits on a road live
here - in the core, with no drawing library attached - instead of being written
twice and drifting apart. Both UIs work in the same 800x720 map space: the
browser scales that space to the canvas, so a position computed on the server
lands exactly where the Pygame build would put it.
"""
import math

MAP_W, MAP_H = 800, 720         # canonical map space, in "map pixels"
PAD_X, PAD_Y = 70, 60           # margin kept clear of the outermost cities

# Where the base box sits relative to the depot city, and how vehicles park in it.
BASE_BOX = (-205, -66, 160, 50)     # dx, dy, width, height
BASE_SLOT = (22, 33, 29)            # first slot x, slot y, spacing - all from the box corner

# Ghost routes are drawn in their own lane beside the real one, in map pixels.
GHOST_OFFSET = {"UCS": 7, "BFS": -7, "DFS": 13}

# One colour per algorithm, so a route, its ghost truck and its row in the race
# card always agree - in both front ends.
ALGO_COLOR = {"A*": (37, 110, 214), "UCS": (20, 150, 100),
              "BFS": (110, 84, 214), "DFS": (210, 70, 145)}
STATUS_COLOR = {"active": (214, 45, 45), "assigned": (226, 140, 0), "resolved": (40, 160, 90)}

# Rough geography (lat, lon), drawn only as scenery.
RIVERS = {
    "Yamuna": [(30.6, 77.6), (30.1, 77.35), (29.45, 77.12), (28.9, 77.2), (28.62, 77.27),
               (28.35, 77.38), (27.95, 77.55), (27.55, 77.68), (27.3, 77.85), (27.17, 78.03),
               (26.95, 78.4)],
    "Chambal": [(24.9, 75.6), (25.18, 75.84), (25.55, 76.35), (25.95, 76.85), (26.35, 77.4),
                (26.62, 77.9), (26.75, 78.35)],
}
ARAVALLI = [(28.45, 77.08), (28.05, 76.75), (27.6, 76.45), (27.15, 76.05), (26.75, 75.45),
            (26.45, 74.95), (26.0, 74.4)]
STATES = [("HARYANA", 29.75, 76.25), ("RAJASTHAN", 27.95, 75.4),
          ("UTTAR PRADESH", 28.12, 77.85)]
MAJOR = {"Delhi": 11, "Jaipur": 9, "Agra": 9, "Chandigarh": 9}      # city dot radius
LABEL_SIDE = {"Delhi": "top", "Gurugram": "left", "Faridabad": "right", "Meerut": "right",
              "Panipat": "left", "Mathura": "right", "Bharatpur": "left", "Agra": "right"}


def offset(a, b, px):
    """Shift the segment a-b sideways by px (for parallel lanes)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1
    ox, oy = -dy / n * px, dx / n * px
    return (a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)


def mercator_y(lat):
    """Web Mercator northing of a latitude, in radians (the y of EPSG:3857 before scaling)."""
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


class Projection:
    """(lat, lon) -> map pixels, and the path geometry that follows from it.

    Web Mercator with one scale for both axes, the projection that online map
    tiles use. That matters: the browser draws the roads and vehicles on top of
    real map tiles, and it can only line them up if the mapping is a plain
    scale-and-shift of Mercator. `params()` hands the browser the constants.
    """

    def __init__(self, coords, width=MAP_W, height=MAP_H, pad_x=PAD_X, pad_y=PAD_Y):
        lats = [c[0] for c in coords.values()]
        lons = [c[1] for c in coords.values()]
        self.lat0, self.lon0 = max(lats), min(lons)           # top-left corner of the data
        span_x = math.radians(max(lons) - self.lon0)
        span_y = mercator_y(self.lat0) - mercator_y(min(lats))
        self.k = min((width - 2 * pad_x) / span_x, (height - 2 * pad_y) / span_y)   # px per radian
        self.x0 = pad_x + ((width - 2 * pad_x) - span_x * self.k) / 2     # centred in the box
        self.y0 = pad_y + ((height - 2 * pad_y) - span_y * self.k) / 2
        self.pos = {n: self.project(*c) for n, c in coords.items()}

    def project(self, lat, lon):
        return (self.x0 + math.radians(lon - self.lon0) * self.k,
                self.y0 + (mercator_y(self.lat0) - mercator_y(lat)) * self.k)

    def params(self):
        """What the browser needs to invert the mapping and place tiles under it."""
        return {"lat0": self.lat0, "lon0": self.lon0, "x0": self.x0, "y0": self.y0, "k": self.k}

    def line(self, points):
        """Project a list of (lat, lon) scenery points."""
        return [self.project(*p) for p in points]

    def lerp(self, a, b, t):
        """(x, y, heading degrees) a fraction t along the road from city a to b."""
        (ax, ay), (bx, by) = self.pos[a], self.pos[b]
        return ax + (bx - ax) * t, ay + (by - ay) * t, math.degrees(math.atan2(by - ay, bx - ax))

    def point_on(self, graph, path, km):
        """(x, y, heading) km along a path of city names."""
        for a, b in zip(path, path[1:]):
            dist = graph.road(a, b).distance
            if km <= dist:
                return self.lerp(a, b, km / dist)
            km -= dist
        x, y = self.pos[path[-1]]
        return x, y, 0.0

    def segment_at(self, graph, path, km):
        """The (a, b) road a route is on km into it."""
        for a, b in zip(path, path[1:]):
            dist = graph.road(a, b).distance
            if km <= dist:
                return a, b
            km -= dist
        return path[-2], path[-1]

    def lane_shift(self, a, b, px):
        """How far to move a point on road a-b to put it in a parallel lane."""
        (ox, oy), _ = offset(self.pos[a], self.pos[b], px)
        return ox - self.pos[a][0], oy - self.pos[a][1]

    def base_rect(self, depot):
        """(x, y, w, h) of the base box beside the depot city."""
        dx, dy = self.pos[depot]
        bx, by, w, h = BASE_BOX
        return dx + bx, dy + by, w, h

    def parked_pose(self, depot, slot):
        """Where the slot-th vehicle waiting at base is drawn."""
        x, y, _, _ = self.base_rect(depot)
        sx, sy, step = BASE_SLOT
        return x + sx + slot * step, y + sy, 0.0

    def vehicle_pose(self, graph, index, vehicle, fleet, depot):
        """(x, y, heading) for a vehicle, whatever its state.

        index is its position in the fleet, used only to fan vehicles out so
        several on the same road do not overlap.
        """
        v = vehicle
        on_road = v.path and v.seg < len(v.path) - 1 and (v.moving or v.status == "broken")
        if on_road:
            a, b = v.path[v.seg], v.path[v.seg + 1]
            t = v.seg_progress / graph.road(a, b).distance
            x, y, ang = self.lerp(a, b, t)
            ox, oy = self.lane_shift(a, b, (index - 2) * 3)
            return x + ox, y + oy, ang + (180 if v.backtrack else 0)
        if v.status == "idle" and v.location == depot:
            waiting = [u for u in fleet if u.status == "idle" and u.location == depot]
            return self.parked_pose(depot, waiting.index(v))
        x, y = self.pos[v.location]
        ang = math.radians(200 + 50 * index)        # fan out around the city dot
        return x + 24 * math.cos(ang), y + 24 * math.sin(ang), 0.0

    def ghost_pose(self, graph, ghost):
        """(x, y, heading) of a racing ghost, in its own lane."""
        x, y, ang = self.point_on(graph, ghost.path, ghost.km)
        a, b = self.segment_at(graph, ghost.path, ghost.km)
        ox, oy = self.lane_shift(a, b, GHOST_OFFSET[ghost.algorithm])
        return x + ox, y + oy, ang


def remaining_km(graph, v):
    """Distance a vehicle still has to drive on its current route."""
    if not v.moving or len(v.path) < 2:
        return 0.0
    if v.backtrack:
        return v.seg_progress
    rest = sum(graph.road(a, b).distance for a, b in zip(v.path[v.seg:], v.path[v.seg + 1:]))
    return rest - v.seg_progress
