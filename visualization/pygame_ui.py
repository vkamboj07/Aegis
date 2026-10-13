"""Pygame map: static city graph, animated vehicles, click-to-spawn incidents,
and a side panel that exposes each agent's algorithm / route / metrics."""
import math

import pygame

from algorithms import ALGORITHMS
from environment.incidents import Incident
from environment.vehicles import default_fleet

MAP_W, PANEL_W, H = 820, 400, 720
BG, PANEL_BG = (22, 26, 34), (30, 35, 46)
EDGE, EDGE_CLOSED = (70, 78, 95), (150, 50, 50)
TEXT, DIM = (230, 233, 240), (140, 148, 165)
INCIDENT = (255, 70, 70)
LABEL_SIDE = {"Delhi": "top", "Gurugram": "left", "Faridabad": "right",
              "Meerut": "right", "Panipat": "left", "Mathura": "right",
              "Bharatpur": "left", "Agra": "right"}
INCIDENT_TYPES = ["Fire", "Accident", "Medical"]
BASE_SPEED_KMPS = 110          # simulated km covered per real second at 1x


class App:
    def __init__(self, graph):
        pygame.init()
        pygame.display.set_caption("AEGIS - Emergency Response Simulation")
        self.screen = pygame.display.set_mode((MAP_W + PANEL_W, H))
        self.clock = pygame.time.Clock()
        self.graph = graph
        self.font = pygame.font.SysFont("segoeui", 15)
        self.small = pygame.font.SysFont("segoeui", 12)
        self.bold = pygame.font.SysFont("segoeui", 16, bold=True)
        self.title = pygame.font.SysFont("segoeui", 20, bold=True)
        self.pos = self._project()
        self.reset()

    # ---- state -------------------------------------------------------
    def reset(self):
        self.fleet = default_fleet()
        self.incident = None
        self.incident_count = 0
        self.paused = False
        self.time_scale = 1.0
        self.message = "Click a city to report an incident."

    def _project(self):
        coords = self.graph.coords
        lats = [c[0] for c in coords.values()]
        lons = [c[1] for c in coords.values()]
        kx = math.cos(math.radians(sum(lats) / len(lats)))
        w = (max(lons) - min(lons)) * kx
        h = max(lats) - min(lats)
        pad = 70
        # schematic map: x and y scaled independently so the dense Delhi
        # cluster gets room to breathe
        sx, sy = (MAP_W - 2 * pad) / w, (H - 2 * pad) / h
        return {n: (pad + (lon - min(lons)) * kx * sx,
                    pad + (max(lats) - lat) * sy)
                for n, (lat, lon) in coords.items()}

    # ---- simulation ----------------------------------------------------
    def node_at(self, pos, radius=20):
        best, best_d = None, radius
        for n, p in self.pos.items():
            d = math.dist(pos, p)
            if d <= best_d:
                best, best_d = n, d
        return best

    def spawn_incident(self, node):
        if any(v.moving for v in self.fleet):
            self.message = "Vehicles still en route - wait for arrival."
            return
        kind = INCIDENT_TYPES[self.incident_count % len(INCIDENT_TYPES)]
        self.incident_count += 1
        self.incident = Incident(kind, node, severity=3 + self.incident_count % 3)
        for v in self.fleet:
            v.dispatch(ALGORITHMS[v.algorithm](self.graph, v.location, node))
        self.message = f"{kind} reported in {node}. All units dispatched."

    def step(self, dt):
        if self.paused:
            return
        advance = BASE_SPEED_KMPS * self.time_scale * dt
        for v in self.fleet:
            if not v.moving:
                continue
            v.seg_progress += advance
            while v.moving:
                dist = self.graph.road(v.path[v.seg], v.path[v.seg + 1]).distance
                if v.seg_progress < dist:
                    break
                v.seg_progress -= dist
                v.seg += 1
                v.location = v.path[v.seg]
                if v.seg >= len(v.path) - 1:
                    v.moving, v.seg_progress = False, 0.0
        if self.incident and self.incident.status == "active":
            if not any(v.moving for v in self.fleet):
                self.incident.status = "resolved"
                self.message = f"All units arrived at {self.incident.location}."

    def vehicle_xy(self, i, v):
        if v.moving:
            a, b = self.pos[v.path[v.seg]], self.pos[v.path[v.seg + 1]]
            dist = self.graph.road(v.path[v.seg], v.path[v.seg + 1]).distance
            t = v.seg_progress / dist
            base = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            off = self._lane_offset(a, b, i)
            return base[0] + off[0], base[1] + off[1]
        x, y = self.pos[v.location]
        ang = math.radians(45 + 90 * i)
        return x + 15 * math.cos(ang), y + 15 * math.sin(ang)

    @staticmethod
    def _lane_offset(a, b, i):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1
        k = (i - 1.5) * 4
        return -dy / n * k, dx / n * k

    # ---- drawing -------------------------------------------------------
    def draw(self):
        s = self.screen
        s.fill(BG)
        self._draw_roads(s)
        self._draw_routes(s)
        self._draw_nodes(s)
        self._draw_incident(s)
        self._draw_vehicles(s)
        self._draw_panel(s)

    def _draw_roads(self, s):
        for r in self.graph.roads.values():
            a, b = self.pos[r.a], self.pos[r.b]
            pygame.draw.line(s, EDGE_CLOSED if r.closed else EDGE, a, b, 2)
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            label = self.small.render(f"{r.distance:g}", True, DIM)
            rect = label.get_rect(center=(mx, my))
            pygame.draw.rect(s, BG, rect.inflate(6, 2))
            s.blit(label, rect)

    def _draw_routes(self, s):
        for i, v in enumerate(self.fleet):
            for u, w in zip(v.path, v.path[1:]):
                a, b = self.pos[u], self.pos[w]
                o = self._lane_offset(a, b, i)
                pygame.draw.line(s, v.color, (a[0] + o[0], a[1] + o[1]),
                                 (b[0] + o[0], b[1] + o[1]), 3)

    def _draw_nodes(self, s):
        for n, (x, y) in self.pos.items():
            pygame.draw.circle(s, (45, 52, 68), (x, y), 10)
            pygame.draw.circle(s, (170, 180, 200), (x, y), 10, 2)
            label = self.font.render(n, True, TEXT)
            side = LABEL_SIDE.get(n, "bottom")
            if side == "left":
                rect = label.get_rect(midright=(x - 14, y))
            elif side == "right":
                rect = label.get_rect(midleft=(x + 14, y))
            elif side == "top":
                rect = label.get_rect(midbottom=(x, y - 13))
            else:
                rect = label.get_rect(midtop=(x, y + 13))
            s.blit(label, rect)

    def _draw_incident(self, s):
        inc = self.incident
        if not inc:
            return
        x, y = self.pos[inc.location]
        color = INCIDENT if inc.status == "active" else (90, 190, 120)
        pulse = 4 * math.sin(pygame.time.get_ticks() / 150) if inc.status == "active" else 0
        pygame.draw.circle(s, color, (x, y), 20 + pulse, 3)
        pygame.draw.circle(s, color, (x, y), 6)
        tag = self.bold.render(inc.type.upper(), True, color)
        s.blit(tag, tag.get_rect(midbottom=(x, y - 24)))

    def _draw_vehicles(self, s):
        for i, v in enumerate(self.fleet):
            x, y = self.vehicle_xy(i, v)
            pygame.draw.circle(s, (10, 10, 14), (x, y), 8)
            pygame.draw.circle(s, v.color, (x, y), 6)

    def _draw_panel(self, s):
        x0 = MAP_W
        pygame.draw.rect(s, PANEL_BG, (x0, 0, PANEL_W, H))
        x, y = x0 + 18, 16
        s.blit(self.title.render("AEGIS - AI Decision Panel", True, TEXT), (x, y))
        y += 34
        y = self._text(s, self.message, x, y, DIM, PANEL_W - 36) + 8

        inc = self.incident
        if inc:
            line = f"{inc.type} - {inc.location}   [{inc.status}]   severity {inc.severity}"
            s.blit(self.bold.render("Priority Incident", True, INCIDENT), (x, y))
            y += 22
            y = self._text(s, line, x, y, TEXT, PANEL_W - 36) + 8

        for v in self.fleet:
            pygame.draw.circle(s, v.color, (x + 6, y + 10), 6)
            head = f"{v.name}  -  {v.algorithm}"
            s.blit(self.bold.render(head, True, TEXT), (x + 20, y))
            y += 22
            if v.path:
                action = "EN ROUTE" if v.moving else "ARRIVED"
                route = " > ".join(v.path)
                y = self._text(s, f"Route: {route}", x + 20, y, TEXT, PANEL_W - 56)
                stats = (f"{action}   {v.cost:.0f} km   "
                         f"{v.cost / 60:.1f} h   expanded {v.nodes_expanded}")
                y = self._text(s, stats, x + 20, y, DIM, PANEL_W - 56)
            else:
                y = self._text(s, f"Idle at {v.location}", x + 20, y, DIM, PANEL_W - 56)
            y += 8

        closed = [f"{r.a}-{r.b}" for r in self.graph.roads.values() if r.closed]
        status = ", ".join(closed) if closed else "all roads open"
        y = self._text(s, f"Road status: {status}", x, y, DIM, PANEL_W - 36)

        help_lines = ["Click city: report incident", "SPACE pause   +/- speed   R reset",
                      f"Speed {self.time_scale:g}x" + ("   PAUSED" if self.paused else "")]
        y = H - 20 - 18 * len(help_lines)
        for line in help_lines:
            s.blit(self.small.render(line, True, DIM), (x, y))
            y += 18

    def _text(self, s, text, x, y, color, width):
        words, line = text.split(" "), ""
        for w in words:
            trial = f"{line} {w}".strip()
            if self.font.size(trial)[0] > width and line:
                s.blit(self.font.render(line, True, color), (x, y))
                y += 19
                line = w
            else:
                line = trial
        s.blit(self.font.render(line, True, color), (x, y))
        return y + 19

    # ---- main loop -----------------------------------------------------
    def handle(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self.paused = not self.paused
            elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                self.time_scale = min(8, self.time_scale * 2)
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.time_scale = max(0.25, self.time_scale / 2)
            elif event.key == pygame.K_r:
                self.reset()
            elif event.key == pygame.K_ESCAPE:
                return False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            node = self.node_at(event.pos)
            if node:
                self.spawn_incident(node)
        return event.type != pygame.QUIT

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                running = self.handle(event) and running
            self.step(self.clock.tick(60) / 1000)
            self.draw()
            pygame.display.flip()
        pygame.quit()
