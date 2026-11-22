"""Map rendering: an atlas-style background (terrain, rivers, hills, states),
highways, cities with facility badges, the base, incidents, vehicles and
their route race (faded ghost trucks driving the other algorithms' routes)."""
import math
import random

import pygame

from ai.routing import PREFERENCE
from environment.vehicles import KINDS

MAP_W, H = 800, 720
PAD_X, PAD_Y = 70, 60

LAND, LAND_DOT, GRID = (236, 231, 217), (226, 219, 202), (223, 216, 199)
WATER, WATER_EDGE = (154, 198, 226), (112, 164, 204)
HILLS, STATE = (214, 198, 160), (188, 177, 153)
ROAD_CASE, ROAD_FILL = (176, 146, 84), (246, 212, 118)
CLOSED_CASE, CLOSED_FILL = (130, 20, 20), (214, 58, 58)
INK, INK_SOFT, WHITE = (40, 40, 50), (112, 106, 94), (255, 255, 255)
SELECT = (0, 150, 210)
STATUS = {"active": (214, 45, 45), "assigned": (226, 140, 0), "resolved": (40, 160, 90)}
ALGO_COLOR = {"A*": (37, 110, 214), "UCS": (20, 150, 100), "BFS": (110, 84, 214), "DFS": (210, 70, 145)}
GHOST_OFFSET = {"UCS": 7, "BFS": -7, "DFS": 13}      # px beside the real truck

# rough geography (lat, lon), drawn only as scenery
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
MAJOR = {"Delhi": 11, "Jaipur": 9, "Agra": 9, "Chandigarh": 9}
LABEL_SIDE = {"Delhi": "top", "Gurugram": "left", "Faridabad": "right", "Meerut": "right",
              "Panipat": "left", "Mathura": "right", "Bharatpur": "left", "Agra": "right"}


def dashed(s, color, a, b, width=2, dash=9, gap=6):
    length = math.dist(a, b)
    if not length:
        return
    dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    d = 0.0
    while d < length:
        e = min(d + dash, length)
        pygame.draw.line(s, color, (a[0] + dx * d, a[1] + dy * d), (a[0] + dx * e, a[1] + dy * e), width)
        d = e + gap


def offset(a, b, px):
    """Shift the segment a-b sideways by px (for parallel lanes)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1
    ox, oy = -dy / n * px, dx / n * px
    return (a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)


def shade(color, k):
    return tuple(max(0, min(255, int(c * k))) for c in color)


class MapView:
    def __init__(self, graph, fonts):
        self.graph, self.f = graph, fonts
        self._init_projection()
        self.pos = {n: self.project(*c) for n, c in graph.coords.items()}
        self._labels, self._sprites = {}, {}
        self.background = self._render_background()
        dx, dy = self.pos[graph.depot]
        self.base_rect = pygame.Rect(dx - 205, dy - 66, 160, 50)

    # ---- geometry ------------------------------------------------------
    def _init_projection(self):
        lats = [c[0] for c in self.graph.coords.values()]
        lons = [c[1] for c in self.graph.coords.values()]
        self._lat_max, self._lon_min = max(lats), min(lons)
        self._kx = math.cos(math.radians(sum(lats) / len(lats)))
        # schematic: x and y scaled independently so the Delhi cluster gets room
        self._sx = (MAP_W - 2 * PAD_X) / ((max(lons) - min(lons)) * self._kx)
        self._sy = (H - 2 * PAD_Y) / (max(lats) - min(lats))

    def project(self, lat, lon):
        return (PAD_X + (lon - self._lon_min) * self._kx * self._sx,
                PAD_Y + (self._lat_max - lat) * self._sy)

    def node_at(self, p, radius=16):
        hits = [(math.dist(p, q), n) for n, q in self.pos.items() if math.dist(p, q) <= radius]
        return min(hits)[1] if hits else None

    def road_at(self, p, radius=8):
        best, best_d = None, radius
        for r in self.graph.roads.values():
            d = _dist_to_segment(p, self.pos[r.a], self.pos[r.b])
            if d <= best_d:
                best, best_d = r, d
        return best

    def vehicle_at(self, p, sim):
        for i, v in enumerate(sim.fleet):
            x, y, _ = self.vehicle_pose(i, v, sim)
            if abs(p[0] - x) < 15 and abs(p[1] - y) < 11:
                return v
        return None

    def hover_target(self, p, sim):
        """What is under the pointer: ("vehicle", v), ("city", name), ("road", road) or None.
        Vehicles win over cities, and cities over roads, as they are drawn on top."""
        v = self.vehicle_at(p, sim)
        if v:
            return "vehicle", v
        node = self.node_at(p)
        if node:
            return "city", node
        road = self.road_at(p)
        if road:
            return "road", road
        return None

    def point_on(self, path, km):
        """(x, y, heading degrees) km along a path of city names."""
        for a, b in zip(path, path[1:]):
            dist = self.graph.road(a, b).distance
            if km <= dist:
                return self._lerp(a, b, km / dist)
            km -= dist
        x, y = self.pos[path[-1]]
        return x, y, 0.0

    def _lerp(self, a, b, t):
        (ax, ay), (bx, by) = self.pos[a], self.pos[b]
        return ax + (bx - ax) * t, ay + (by - ay) * t, math.degrees(math.atan2(by - ay, bx - ax))

    def remaining_km(self, v):
        if not v.moving or len(v.path) < 2:
            return 0.0
        if v.backtrack:
            return v.seg_progress
        rest = sum(self.graph.road(a, b).distance for a, b in zip(v.path[v.seg:], v.path[v.seg + 1:]))
        return rest - v.seg_progress

    def vehicle_pose(self, i, v, sim):
        """(x, y, heading) for a vehicle, whatever its state."""
        on_road = v.path and v.seg < len(v.path) - 1 and (v.moving or v.status == "broken")
        if on_road:
            a, b = v.path[v.seg], v.path[v.seg + 1]
            t = v.seg_progress / self.graph.road(a, b).distance
            x, y, ang = self._lerp(a, b, t)
            (ox, oy), _ = offset(self.pos[a], self.pos[b], (i - 2) * 3)
            x, y = x + ox - self.pos[a][0], y + oy - self.pos[a][1]
            return x, y, ang + (180 if v.backtrack else 0)
        if v.status == "idle" and v.location == sim.depot:
            slot = [u for u in sim.fleet if u.status == "idle" and u.location == sim.depot].index(v)
            return self.base_rect.x + 22 + slot * 29, self.base_rect.y + 33, 0.0
        x, y = self.pos[v.location]
        ang = math.radians(200 + 50 * i)
        return x + 24 * math.cos(ang), y + 24 * math.sin(ang), 0.0

    # ---- static background --------------------------------------------
    def _render_background(self):
        s = pygame.Surface((MAP_W, H))
        s.fill(LAND)
        rng = random.Random(7)
        for _ in range(2600):
            pygame.draw.circle(s, LAND_DOT, (rng.random() * MAP_W, rng.random() * H),
                               rng.choice((1, 1, 2)))
        tiny = self.f["tiny"]
        for lat in range(26, 31):
            y = self.project(lat, 76)[1]
            pygame.draw.line(s, GRID, (0, y), (MAP_W, y))
            s.blit(tiny.render(f"{lat}°N", True, STATE), (4, y - 13))
        for lon in range(75, 79):
            x = self.project(28, lon)[0]
            pygame.draw.line(s, GRID, (x, 0), (x, H))
            s.blit(tiny.render(f"{lon}°E", True, STATE), (x + 3, H - 15))
        hills = pygame.Surface((MAP_W, H), pygame.SRCALPHA)
        pts = [self.project(*p) for p in ARAVALLI]
        for width, alpha in ((58, 55), (34, 80)):
            pygame.draw.lines(hills, (*HILLS, alpha), False, pts, width)
            for p in pts:
                pygame.draw.circle(hills, (*HILLS, alpha), p, width // 2)
        s.blit(hills, (0, 0))
        self._along(s, "Aravalli Range", pts[3], pts[4], INK_SOFT, -22)
        for name, coords in RIVERS.items():
            pts = [self.project(*p) for p in coords]
            pygame.draw.lines(s, WATER_EDGE, False, pts, 6)
            pygame.draw.lines(s, WATER, False, pts, 4)
            for p in pts:
                pygame.draw.circle(s, WATER, p, 2)
            k = len(pts) // 3
            self._along(s, name, pts[k], pts[k + 1], WATER_EDGE, 12)
        for text, lat, lon in STATES:
            label = self.f["state"].render(" ".join(text), True, STATE)
            s.blit(label, label.get_rect(center=self.project(lat, lon)))
        return s

    def _along(self, s, text, a, b, color, px):
        """Italic label rotated along a-b, shifted px sideways."""
        font = self.f["italic"]
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if ang > 90 or ang < -90:
            ang += 180
        label = pygame.transform.rotate(font.render(text, True, color), -ang)
        (mx, my), _ = offset(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), b, px)
        s.blit(label, label.get_rect(center=(mx, my)))

    # ---- per-frame layers ---------------------------------------------
    def draw(self, s, sim, ui):
        """ui supplies location, selected_road, selected_vehicle and focus_vehicle."""
        s.blit(self.background, (0, 0))
        self.draw_roads(s, ui.selected_road)
        self.draw_routes(s, sim)
        self.draw_cities(s, sim, ui.location)
        self.draw_base(s, sim)
        self.draw_incidents(s, sim)
        self.draw_ghosts(s, sim)
        self.draw_vehicles(s, sim, ui.selected_vehicle)
        self.draw_race_card(s, sim, ui.focus_vehicle)
        self.draw_legend(s)
        self.draw_compass(s)

    def draw_roads(self, s, selected):
        if selected:
            pygame.draw.line(s, SELECT, self.pos[selected.a], self.pos[selected.b], 16)
        for r in self.graph.roads.values():
            a, b = self.pos[r.a], self.pos[r.b]
            pygame.draw.line(s, CLOSED_CASE if r.closed else ROAD_CASE, a, b, 9)
            pygame.draw.line(s, CLOSED_FILL if r.closed else ROAD_FILL, a, b, 6)
            if r.closed:
                dashed(s, WHITE, a, b, 2, 7, 7)
        for r in self.graph.roads.values():
            a, b = self.pos[r.a], self.pos[r.b]
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if r.closed:
                pygame.draw.circle(s, CLOSED_FILL, mid, 10)
                pygame.draw.circle(s, WHITE, mid, 10, 2)
                for d in (-1, 1):
                    pygame.draw.line(s, WHITE, (mid[0] - 4, mid[1] - 4 * d), (mid[0] + 4, mid[1] + 4 * d), 3)
                continue
            label = self.f["tiny"].render(f"{r.distance:g}", True, INK_SOFT)
            rect = label.get_rect(center=mid).inflate(8, 2)
            pygame.draw.rect(s, WHITE, rect, border_radius=6)
            pygame.draw.rect(s, (205, 192, 160), rect, 1, border_radius=6)
            s.blit(label, label.get_rect(center=mid))

    def draw_cities(self, s, sim, selected):
        for n, (x, y) in self.pos.items():
            r = MAJOR.get(n, 7)
            if n == selected:
                pygame.draw.circle(s, SELECT, (x, y), r + 9, 3)
            pygame.draw.circle(s, WHITE, (x, y), r)
            pygame.draw.circle(s, INK, (x, y), r, 2)
            pygame.draw.circle(s, INK, (x, y), 2)
            for k, tag in enumerate(sorted(self.graph.tags.get(n, ()))):
                self._badge(s, tag, (x + r + 4 + k * 15, y - r - 3))
            side = LABEL_SIDE.get(n, "bottom")
            anchor = {"left": {"midright": (x - r - 5, y)}, "right": {"midleft": (x + r + 5, y)},
                      "top": {"midbottom": (x, y - r - 4)}}.get(side, {"midtop": (x, y + r + 3)})
            if side == "right" and self.graph.tags.get(n):
                anchor = {"midleft": (x + r + 5, y + 9)}
            self.text(s, n, "city", INK, **anchor)

    def _badge(self, s, tag, c):
        x, y = c
        if tag == "hospital":
            pygame.draw.circle(s, WHITE, c, 7)
            pygame.draw.circle(s, (200, 40, 40), c, 7, 2)
            pygame.draw.rect(s, (200, 40, 40), (x - 1.5, y - 4, 3, 8))
            pygame.draw.rect(s, (200, 40, 40), (x - 4, y - 1.5, 8, 3))
        elif tag == "fuel_depot":
            pygame.draw.circle(s, (232, 120, 20), c, 7)
            pygame.draw.polygon(s, WHITE, [(x, y - 5), (x + 3, y), (x - 3, y)])
            pygame.draw.circle(s, WHITE, (x, y + 1), 3)
        elif tag == "tourist_hub":
            pygame.draw.circle(s, (120, 80, 190), c, 7)
            star = [(x + (5 if k % 2 == 0 else 2.2) * math.cos(math.radians(-90 + 36 * k)),
                     y + (5 if k % 2 == 0 else 2.2) * math.sin(math.radians(-90 + 36 * k)))
                    for k in range(10)]
            pygame.draw.polygon(s, WHITE, star)

    def draw_base(self, s, sim):
        r = self.base_rect
        dx, dy = self.pos[sim.depot]
        dashed(s, (40, 90, 170), (r.right, r.centery), (dx - 10, dy - 6), 2, 5, 4)
        shadow = r.move(2, 3)
        pygame.draw.rect(s, (200, 192, 172), shadow, border_radius=8)
        pygame.draw.rect(s, WHITE, r, border_radius=8)
        pygame.draw.rect(s, (40, 90, 170), r, 2, border_radius=8)
        head = pygame.Rect(r.x, r.y, r.w, 17)
        pygame.draw.rect(s, (40, 90, 170), head, border_top_left_radius=8, border_top_right_radius=8)
        at_base = sum(v.status == "idle" and v.location == sim.depot for v in sim.fleet)
        label = self.f["tiny_bold"].render(f"AEGIS BASE  ·  {at_base}/{len(sim.fleet)} ready", True, WHITE)
        s.blit(label, label.get_rect(center=head.center))

    def draw_routes(self, s, sim):
        for race in sim.races:
            if not race.running:
                continue
            for g in race.ghosts:
                if g.arrived_at is not None:
                    continue
                for a, b in zip(g.path, g.path[1:]):
                    pa, pb = offset(self.pos[a], self.pos[b], GHOST_OFFSET[g.algorithm])
                    dashed(s, ALGO_COLOR[g.algorithm], pa, pb, 2, 6, 6)
        for i, v in enumerate(sim.fleet):
            if not v.moving:
                continue
            x, y, _ = self.vehicle_pose(i, v, sim)
            if v.backtrack:
                rest = [v.path[v.seg]]
            elif v.pending:
                rest = [v.path[v.seg + 1]]          # old route is abandoned at the junction
            else:
                rest = v.path[v.seg + 1:]
            pts = [(x, y)] + [self.pos[n] for n in rest]
            if v.status == "dispatched":
                color = ALGO_COLOR.get(v.algorithm, INK)
                if len(pts) > 1:
                    pygame.draw.lines(s, WHITE, False, pts, 8)
                    pygame.draw.lines(s, color, False, pts, 4)
            else:
                for a, b in zip(pts, pts[1:]):
                    dashed(s, (120, 120, 130), a, b, 2, 4, 5)
            if v.pending and v.pending[1][v.pending[0]][0]:
                best, options = v.pending
                path = options[best][0]
                for a, b in zip(path, path[1:]):
                    dashed(s, ALGO_COLOR[best], self.pos[a], self.pos[b], 4, 10, 6)

    def draw_incidents(self, s, sim):
        t = pygame.time.get_ticks() / 160
        for inc in sim.open_incidents():
            self._incident_marker(s, inc.type, self.pos[inc.location], STATUS[inc.status],
                                  f"{inc.type.upper()} #{inc.id}  S{inc.severity}", 3 * math.sin(t))
        for v in sim.fleet:
            if v.status == "on_scene":
                inc = sim.incident(v.incident)
                if inc and not sim.incident_at(v.location):
                    self._incident_marker(s, inc.type, self.pos[v.location], STATUS["resolved"],
                                          f"HANDLED  #{inc.id}", 0)

    def _incident_marker(self, s, kind, c, color, tag, pulse):
        x, y = c
        ring = pygame.Surface((70, 70), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*color, 70), (35, 35), 24 + pulse)
        pygame.draw.circle(ring, (*color, 220), (35, 35), 24 + pulse, 3)
        s.blit(ring, (x - 35, y - 35))
        pygame.draw.circle(s, WHITE, c, 13)
        pygame.draw.circle(s, color, c, 13, 3)
        if kind == "Fire":
            pygame.draw.polygon(s, (238, 104, 20), [(x, y - 9), (x + 6, y - 1), (x + 5, y + 5),
                                                    (x, y + 8), (x - 5, y + 5), (x - 6, y - 1)])
            pygame.draw.polygon(s, (252, 196, 40), [(x, y - 2), (x + 3, y + 3), (x, y + 6), (x - 3, y + 3)])
        elif kind == "Medical":
            pygame.draw.rect(s, (205, 35, 35), (x - 2.5, y - 7, 5, 14))
            pygame.draw.rect(s, (205, 35, 35), (x - 7, y - 2.5, 14, 5))
        else:
            pygame.draw.polygon(s, (240, 175, 0), [(x, y - 8), (x + 8, y + 6), (x - 8, y + 6)])
            mark = self.f["tiny_bold"].render("!", True, INK)
            s.blit(mark, mark.get_rect(center=(x, y + 1)))
        label = self.f["tiny_bold"].render(tag, True, WHITE)
        rect = label.get_rect(midbottom=(x, y - 30)).inflate(10, 4)
        pygame.draw.rect(s, color, rect, border_radius=5)
        s.blit(label, label.get_rect(center=rect.center))

    def draw_ghosts(self, s, sim):
        for race in sim.races:
            if not race.running:
                continue
            for g in race.ghosts:
                if g.arrived_at is not None or len(g.path) < 2:
                    continue
                x, y, ang = self.point_on(g.path, g.km)
                seg = self._segment_at(g.path, g.km)
                (ox, oy), _ = offset(self.pos[seg[0]], self.pos[seg[1]], GHOST_OFFSET[g.algorithm])
                x, y = x + ox - self.pos[seg[0]][0], y + oy - self.pos[seg[0]][1]
                kind = sim.vehicle(race.vehicle).kind
                spr = self.sprite(kind, ang, g.algorithm)
                s.blit(spr, spr.get_rect(center=(x, y)))
                tag = self.f["tiny_bold"].render(g.algorithm, True, WHITE)
                rect = tag.get_rect(midbottom=(x, y - 11)).inflate(6, 2)
                pygame.draw.rect(s, ALGO_COLOR[g.algorithm], rect, border_radius=4)
                s.blit(tag, tag.get_rect(center=rect.center))

    def _segment_at(self, path, km):
        for a, b in zip(path, path[1:]):
            d = self.graph.road(a, b).distance
            if km <= d:
                return a, b
            km -= d
        return path[-2], path[-1]

    def draw_vehicles(self, s, sim, selected):
        for i, v in enumerate(sim.fleet):
            x, y, ang = self.vehicle_pose(i, v, sim)
            if v.name == selected:
                pygame.draw.circle(s, SELECT, (x, y), 18, 3)
            spr = self.sprite(v.kind, ang)
            s.blit(spr, spr.get_rect(center=(x, y)))
            if v.status == "dispatched" and v.moving:
                tag = self.f["tiny_bold"].render(v.algorithm, True, WHITE)
                rect = tag.get_rect(midbottom=(x, y - 11)).inflate(6, 2)
                pygame.draw.rect(s, ALGO_COLOR.get(v.algorithm, INK), rect, border_radius=4)
                s.blit(tag, tag.get_rect(center=rect.center))
            if v.status == "broken":
                pygame.draw.circle(s, (205, 35, 35), (x, y - 17), 8)
                pygame.draw.circle(s, WHITE, (x, y - 17), 8, 2)
                mark = self.f["tiny_bold"].render("!", True, WHITE)
                s.blit(mark, mark.get_rect(center=(x, y - 17)))
                left = self.f["tiny_bold"].render(f"repair {max(0, v.until - sim.now):.1f} h", True, (170, 20, 20))
                s.blit(left, left.get_rect(midtop=(x, y + 10)))

    def sprite(self, kind, angle, ghost=None):
        key = (kind, round(angle / 6) * 6 % 360, ghost)
        if key in self._sprites:
            return self._sprites[key]
        body = KINDS[kind][1]
        alpha = 105 if ghost else 255
        base = pygame.Surface((30, 16), pygame.SRCALPHA)
        pygame.draw.rect(base, (*body, alpha), (1, 2, 28, 12), border_radius=3)
        pygame.draw.rect(base, (*shade(body, 0.8), alpha), (21, 3, 7, 10), border_radius=2)
        pygame.draw.rect(base, (185, 215, 235, alpha), (24, 4, 3, 8))
        if kind == "Fire Truck":
            for yy in (6, 10):
                pygame.draw.line(base, (235, 235, 235, alpha), (4, yy), (19, yy))
            for xx in range(5, 19, 3):
                pygame.draw.line(base, (235, 235, 235, alpha), (xx, 6), (xx, 10))
        elif kind == "Ambulance":
            pygame.draw.rect(base, (210, 35, 35, alpha), (9, 6, 7, 3))
            pygame.draw.rect(base, (210, 35, 35, alpha), (11, 4, 3, 7))
        else:
            pygame.draw.rect(base, (220, 40, 40, alpha), (10, 5, 3, 6))
            pygame.draw.rect(base, (60, 130, 240, alpha), (13, 5, 3, 6))
        edge = ALGO_COLOR[ghost] if ghost else (25, 25, 30)
        pygame.draw.rect(base, (*edge, 255), (1, 2, 28, 12), 2 if ghost else 1, border_radius=3)
        self._sprites[key] = pygame.transform.rotate(base, -key[1])
        return self._sprites[key]

    # ---- overlays -----------------------------------------------------
    def _card(self, s, rect):
        shadow = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 40), shadow.get_rect(), border_radius=10)
        s.blit(shadow, rect.move(2, 3))
        card = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(card, (255, 255, 255, 238), card.get_rect(), border_radius=10)
        pygame.draw.rect(card, (200, 190, 168, 255), card.get_rect(), 1, border_radius=10)
        s.blit(card, rect)

    def draw_race_card(self, s, sim, focus):
        """Race of the focused vehicle, else the newest running race, else the newest."""
        mine = [r for r in sim.races if r.vehicle == focus]
        running = [r for r in sim.races if r.running]
        race = mine[-1] if mine else (running[-1] if running else sim.latest_race())
        if not race:
            return
        rows = [a for a in PREFERENCE if a in race.options]
        rect = pygame.Rect(12, 12, 330, 54 + 22 * len(rows))
        self._card(s, rect)
        title = f"Route race: {race.vehicle} to {race.destination}"
        s.blit(self.f["small_bold"].render(title, True, INK), (rect.x + 12, rect.y + 9))
        v = sim.vehicle(race.vehicle)
        ghosts = {g.algorithm: g for g in race.ghosts}
        y = rect.y + 32
        for algo in rows:
            path, cost, expanded, _ = race.options[algo]
            color = ALGO_COLOR[algo]
            pygame.draw.line(s, color, (rect.x + 12, y + 8), (rect.x + 30, y + 8), 4)
            s.blit(self.f["small_bold"].render(algo, True, INK), (rect.x + 36, y))
            km = f"{cost:.0f} km" if path else "no route"
            s.blit(self.f["small"].render(km, True, INK), (rect.x + 78, y))
            s.blit(self.f["small"].render(f"{expanded} nodes", True, INK_SOFT), (rect.x + 140, y))
            if algo == race.chosen:
                done = race.options[algo][1] if race.arrived_at is not None else self._driven(v, race)
                state = "ARRIVED" if race.arrived_at is not None else ("STOPPED" if race.ended else "DRIVING")
            else:
                g = ghosts.get(algo)
                done = g.km if g else 0
                state = "arrived" if g and g.arrived_at is not None else ("" if g else "-")
            frac = (done / cost) if path and cost else 1.0
            bar = pygame.Rect(rect.x + 212, y + 4, 60, 9)
            pygame.draw.rect(s, (232, 226, 210), bar, border_radius=4)
            pygame.draw.rect(s, color, (bar.x, bar.y, max(2, bar.w * min(1, frac)), bar.h), border_radius=4)
            s.blit(self.f["tiny_bold" if algo == race.chosen else "tiny"].render(state, True, INK_SOFT),
                   (rect.x + 278, y + 1))
            y += 22
        note = (f"{race.chosen} drives: shortest route, fewest nodes searched" if not race.ended
                else "Superseded by a replan or breakdown")
        note += "   ·   click a truck to switch"
        s.blit(self.f["tiny"].render(note, True, INK_SOFT), (rect.x + 12, y + 2))

    def _driven(self, v, race):
        route = race.options[race.chosen][0]
        if not v or v.path != route or not v.moving:
            return 0.0
        return sum(self.graph.road(a, b).distance for a, b in zip(route[:v.seg], route[1:v.seg + 1])) + v.seg_progress

    def draw_legend(self, s):
        rect = pygame.Rect(MAP_W - 254, H - 114, 242, 104)
        self._card(s, rect)
        x, y = rect.x + 10, rect.y + 8
        for k, kind in enumerate(KINDS):
            spr = self.sprite(kind, 0)
            s.blit(spr, (x, y + k * 18))
            s.blit(self.f["tiny"].render(kind, True, INK), (x + 34, y + 1 + k * 18))
        spr = self.sprite("Fire Truck", 0, "BFS")
        s.blit(spr, (x, y + 54))
        s.blit(self.f["tiny"].render("other algorithm", True, INK), (x + 34, y + 55))
        pygame.draw.line(s, CLOSED_FILL, (x + 1, y + 80), (x + 29, y + 80), 6)
        s.blit(self.f["tiny"].render("closed road", True, INK), (x + 34, y + 73))
        cx = rect.x + 124
        for k, algo in enumerate(PREFERENCE):
            pygame.draw.line(s, ALGO_COLOR[algo], (cx, y + 8 + k * 16), (cx + 18, y + 8 + k * 16), 4)
            s.blit(self.f["tiny"].render(algo, True, INK), (cx + 23, y + 1 + k * 16))
        for k, tag in enumerate(("hospital", "fuel_depot", "tourist_hub")):
            self._badge(s, tag, (cx + 62, y + 8 + k * 18))
            s.blit(self.f["tiny"].render(tag.split("_")[0], True, INK), (cx + 72, y + 1 + k * 18))

    def draw_compass(self, s):
        x, y = MAP_W - 34, 38
        pygame.draw.circle(s, WHITE, (x, y), 18)
        pygame.draw.circle(s, (200, 190, 168), (x, y), 18, 1)
        pygame.draw.polygon(s, (200, 50, 50), [(x, y - 14), (x + 5, y), (x - 5, y)])
        pygame.draw.polygon(s, INK_SOFT, [(x, y + 14), (x + 5, y), (x - 5, y)])
        s.blit(self.f["tiny_bold"].render("N", True, INK), (x - 4, y - 34 + 0))

    def text(self, s, text, font, color, **anchor):
        """Text with a white halo so it stays readable over roads and terrain."""
        key = (text, font, color)
        if key not in self._labels:
            f = self.f[font]
            fg, halo = f.render(text, True, color), f.render(text, True, WHITE)
            surf = pygame.Surface((fg.get_width() + 4, fg.get_height() + 4), pygame.SRCALPHA)
            for dx in (0, 2, 4):
                for dy in (0, 2, 4):
                    surf.blit(halo, (dx, dy))
            surf.blit(fg, (2, 2))
            self._labels[key] = surf
        surf = self._labels[key]
        s.blit(surf, surf.get_rect(**anchor))


def _dist_to_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1)
    t = max(0.0, min(1.0, t))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))
