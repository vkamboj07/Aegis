"""AEGIS control centre: the map on the left, a control panel on the right.

The panel sets up incidents (type, location, severity, people), can report
several at once as a batch, triggers disruptions (road closures, vehicle
breakdowns, random events) and shows the priority order, the fleet and the
decision log."""
import pygame

from ai.heuristics import urgency
from prompt_engine.parser import describe
from prompt_engine.scenario_generator import build_scenario, schedule
from simulation.engine import AVG_SPEED_KMH, Simulation
from visualization.map_view import MAP_W, MapView
from visualization.widgets import Button, Cycler, Stepper

W, H = 1280, 720
PX, PANEL_W = MAP_W, W - MAP_W
X0, CW = PX + 16, PANEL_W - 32
PANEL_BG, SECTION, RULE = (24, 28, 37), (32, 37, 49), (52, 58, 74)
TEXT, DIM, ACCENT = (232, 235, 242), (150, 158, 175), (110, 175, 255)
RED, AMBER, GREEN = (236, 90, 90), (240, 170, 60), (90, 200, 130)
BASE_SPEED_KMPS = 110           # simulated km covered per real second at 1x
SPEEDS = [0.25, 0.5, 1, 2, 4, 8]
INCIDENT_TYPES = ["Fire", "Accident", "Medical"]
DEMO = "showcase"
HIGHLIGHT_MS = 5000             # a road / vehicle picked in the panel stays highlighted this long
TOAST_MS = 4000                 # on-map notification lifetime
TOAST_EVENTS = {"resolved": GREEN, "repaired": GREEN, "breakdown": RED, "random_event": RED,
                "replan": ACCENT, "rule": AMBER, "escalation": AMBER}
HELP = [("Space", "pause / resume"), ("+ / -", "speed"), ("Enter", "report now"),
        ("Tab", "select next vehicle"), ("C", "close / reopen selected road"),
        ("B", "break down selected vehicle"), ("R", "reset"), ("D", "run demo"),
        ("T", "type a scenario (beta)"), ("H", "show or hide this help"), ("Esc", "quit")]


class App:
    def __init__(self, graph, use_llm=False):
        pygame.init()
        pygame.display.set_caption("AEGIS - Emergency Response Control Centre")
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.graph, self.use_llm = graph, use_llm
        self.f = self._fonts()
        self.map = MapView(graph, self.f)
        self.speed_i, self.paused, self.random_on = 1, False, False
        self.batch, self.typing, self.buffer = [], False, ""
        self.touched = {"road": -HIGHLIGHT_MS, "vehicle": -HIGHLIGHT_MS}
        self.toasts, self.help_on, self._seen = [], False, 0
        self.reset()
        self._build_widgets()

    @staticmethod
    def _fonts():
        def sys(size, bold=False, italic=False):
            return pygame.font.SysFont("segoeui", size, bold=bold, italic=italic)
        return {"title": sys(19, True), "head": sys(11, True), "body": sys(13), "body_bold": sys(13, True),
                "small": sys(12), "small_bold": sys(12, True), "tiny": sys(11), "tiny_bold": sys(11, True),
                "city": sys(13, True), "state": sys(15, True), "italic": sys(12, italic=True)}

    # ---- state -------------------------------------------------------
    def reset(self):
        for road in self.graph.roads.values():
            road.closed = False
        self.sim = Simulation(self.graph)
        self.sim.random_events = self.random_on
        self._seen, self.toasts = 0, []

    @property
    def speed(self):
        return SPEEDS[self.speed_i]

    # ---- widgets -----------------------------------------------------
    def _build_widgets(self):
        roads = sorted(self.graph.roads.values(), key=lambda r: (r.a, r.b))
        c1, c2 = X0 + 62, X0 + 298
        self.kind = Cycler((c1, 70, 160, 26), INCIDENT_TYPES)
        self.severity = Stepper((c2, 70, 150, 26), 3, 1, 5)
        self.loc = Cycler((c1, 102, 160, 26), self.graph.nodes)
        self.loc.set("Jaipur")
        self.people = Stepper((c2, 102, 150, 26), 40, 10, 500, 10)
        self.road = Cycler((c1, 238, 258, 26), roads,
                           label=lambda r: f"{r.a} - {r.b}  ({r.distance:g} km)"
                           + ("  CLOSED" if r.closed else ""), on_change=lambda _: self.touch("road"))
        self.vehicle = Cycler((c1, 270, 258, 26), lambda: [v.name for v in self.sim.fleet],
                              on_change=lambda _: self.touch("vehicle"))
        self.widgets = [
            self.kind, self.severity, self.loc, self.people, self.road, self.vehicle,
            Button((X0, 150, 144, 28), "Report now", self.report_now, "primary"),
            Button((X0 + 152, 150, 144, 28), "Add to batch", self.add_to_batch),
            Button((X0 + 304, 150, 144, 28), lambda: f"Dispatch batch ({len(self.batch)})",
                   self.dispatch_batch, "ok", enabled=lambda: bool(self.batch)),
            Button((X0 + 388, 184, 60, 22), "Clear", self.batch.clear, enabled=lambda: bool(self.batch)),
            Button((X0 + 328, 238, 120, 26),
                   lambda: "Reopen road" if self.road.value.closed else "Close road",
                   self.toggle_road, lambda: "ok" if self.road.value.closed else "danger"),
            Button((X0 + 328, 270, 120, 26), "Break down", self.break_down, "danger",
                   enabled=lambda: self._selected_vehicle().status in ("dispatched", "returning")),
            Button((X0, 302, 236, 26),
                   lambda: f"Random disruptions: {'ON' if self.random_on else 'OFF'}",
                   self.toggle_random, lambda: "danger" if self.random_on else "normal"),
            Button((X0, 360, 96, 28), lambda: "Resume" if self.paused else "Pause", self.toggle_pause),
            Button((X0 + 104, 360, 30, 28), "-", lambda: self.change_speed(-1)),
            Button((X0 + 196, 360, 30, 28), "+", lambda: self.change_speed(1)),
            Button((X0 + 234, 360, 96, 28), "Reset", self.reset),
            Button((X0 + 338, 360, 110, 28), "Run demo", self.start_demo, "primary"),
        ]

    def touch(self, what):
        self.touched[what] = pygame.time.get_ticks()

    def _recent(self, what, row_y):
        """Highlight while recently picked, or while the mouse is on its panel row."""
        mx, my = pygame.mouse.get_pos()
        hovering = mx >= PX and row_y <= my <= row_y + 26
        return hovering or pygame.time.get_ticks() - self.touched[what] < HIGHLIGHT_MS

    def _selected_vehicle(self):
        return self.sim.vehicle(self.vehicle.value)

    # ---- actions -----------------------------------------------------
    def _form(self):
        return dict(kind=self.kind.value, location=self.loc.value,
                    severity=self.severity.value, people=self.people.value)

    def report_now(self):
        self.sim.report(**self._form())

    def add_to_batch(self):
        self.batch.append(self._form())

    def dispatch_batch(self):
        self.sim.report_batch(list(self.batch))
        self.batch.clear()

    def toggle_road(self):
        r = self.road.value
        self.sim.toggle_road(r.a, r.b)

    def break_down(self):
        self.sim.break_down(self.vehicle.value)

    def toggle_random(self):
        self.random_on = not self.random_on
        self.sim.random_events = self.random_on
        self.sim.note(f"Random disruptions switched {'on' if self.random_on else 'off'}.")

    def toggle_pause(self):
        self.paused = not self.paused

    def toggle_help(self):
        self.help_on = not self.help_on

    def cycle_vehicle(self):
        """Tab: select the next vehicle in the fleet (and highlight it on the map)."""
        names = [v.name for v in self.sim.fleet]
        current = names.index(self.vehicle.value) if self.vehicle.value in names else -1
        self.vehicle.set(names[(current + 1) % len(names)])
        self.touch("vehicle")

    def change_speed(self, d):
        self.speed_i = max(0, min(len(SPEEDS) - 1, self.speed_i + d))

    def start_demo(self):
        self.reset()
        self.paused = False
        scenario = self.sim.queue.load_scenario(DEMO)
        self.sim.note(f"DEMO: {scenario['description']}")

    def submit_scenario(self):
        """Typed scenario (beta): interpret it and queue its events from now."""
        text, self.buffer, self.typing = self.buffer.strip(), "", False
        if not text:
            return
        scenario = build_scenario(text, self.graph, use_llm=self.use_llm)
        for warning in scenario["warnings"]:
            self.sim.note(f"Prompt engine: {warning}")
        if scenario["events"]:
            schedule(self.sim, scenario)
            self.sim.note("Prompt engine queued: " + "; ".join(describe(e) for e in scenario["events"]))
        else:
            self.sim.note("Prompt engine: could not interpret that scenario.")

    # ---- input -------------------------------------------------------
    def handle(self, event):
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            return self._key(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            if event.pos[0] < MAP_W:
                self._map_click(event.pos, event.button)
            elif event.button == 1:
                any(w.click(event.pos) for w in self.widgets)
        return True

    def _key(self, event):
        if self.typing:
            if event.key == pygame.K_ESCAPE:
                self.typing, self.buffer = False, ""
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.submit_scenario()
            elif event.key == pygame.K_BACKSPACE:
                self.buffer = self.buffer[:-1]
            elif event.unicode and event.unicode.isprintable() and len(self.buffer) < 240:
                self.buffer += event.unicode
            return True
        keys = {pygame.K_SPACE: self.toggle_pause, pygame.K_r: self.reset, pygame.K_d: self.start_demo,
                pygame.K_RETURN: self.report_now, pygame.K_EQUALS: lambda: self.change_speed(1),
                pygame.K_PLUS: lambda: self.change_speed(1), pygame.K_KP_PLUS: lambda: self.change_speed(1),
                pygame.K_MINUS: lambda: self.change_speed(-1), pygame.K_KP_MINUS: lambda: self.change_speed(-1),
                pygame.K_h: self.toggle_help, pygame.K_TAB: self.cycle_vehicle,
                pygame.K_c: self.toggle_road, pygame.K_b: self.break_down}
        if event.key == pygame.K_ESCAPE:
            if self.help_on:            # Esc closes the help first, then quits
                self.help_on = False
                return True
            return False
        if event.key == pygame.K_t:
            self.typing = True
        elif event.key in keys:
            keys[event.key]()
        return True

    def _map_click(self, pos, button):
        if button == 3:
            road = self.map.road_at(pos)
            if road:
                self.road.set(road)
                self.touch("road")
                self.sim.toggle_road(road.a, road.b)
            return
        for i, v in enumerate(self.sim.fleet):
            x, y, _ = self.map.vehicle_pose(i, v, self.sim)
            if abs(pos[0] - x) < 15 and abs(pos[1] - y) < 11:
                self.vehicle.set(v.name)
                self.touch("vehicle")
                return
        node = self.map.node_at(pos)
        if node:
            self.loc.set(node)
            return
        road = self.map.road_at(pos)
        if road:
            self.road.set(road)
            self.touch("road")

    # ---- drawing -----------------------------------------------------
    def draw(self):
        s = self.screen
        s.set_clip(pygame.Rect(0, 0, MAP_W, H))
        self.map.draw(s, self.sim, self)
        if self.typing:
            self._draw_prompt(s)
        elif not self.help_on:
            self._draw_hover(s)
        self._update_toasts()
        self._draw_toasts(s)
        if self.help_on:
            self._draw_help(s)
        s.set_clip(None)
        self._draw_panel(s)

    # ---- map feedback: hover details, notifications, help --------------
    def _update_toasts(self):
        now = pygame.time.get_ticks()
        for rec in self.sim.records[self._seen:]:
            if rec["event"] in TOAST_EVENTS:
                self.toasts.append((rec.get("detail", rec["event"]), now + TOAST_MS,
                                    TOAST_EVENTS[rec["event"]]))
        self._seen = len(self.sim.records)
        self.toasts = [t for t in self.toasts if t[1] > now][-4:]

    def _draw_toasts(self, s):
        for i, (text, _, color) in enumerate(self.toasts):
            text = text if len(text) <= 80 else text[:77] + "..."
            label = self.f["small_bold"].render(text, True, TEXT)
            box = pygame.Rect(0, 0, label.get_width() + 24, 26)
            box.topright = (MAP_W - 12, 64 + i * 32)      # below the compass, clear of the race card
            pygame.draw.rect(s, PANEL_BG, box, border_radius=6)
            pygame.draw.rect(s, color, box, 2, border_radius=6)
            s.blit(label, label.get_rect(center=box.center))

    def _tooltip_lines(self, kind, obj):
        if kind == "vehicle":
            v = obj
            lines = [v.name, self._status(v)[0],
                     f"algorithm: {v.algorithm}" if v.algorithm else "no route yet"]
            if v.incident:
                lines.append(f"incident #{v.incident}")
            return lines
        if kind == "city":
            city = obj
            tags = sorted(t.replace("_", " ") for t in self.graph.tags.get(city, ()))
            lines = [city + (" (base)" if city == self.sim.depot else ""),
                     "facilities: " + (", ".join(tags) or "none")]
            here = [i for i in self.sim.open_incidents() if i.location == city]
            for inc in here[:3]:
                lines.append(f"{inc.type} #{inc.id}: S{inc.severity}, {inc.people_affected} ppl, {inc.status}")
            if not here:
                lines.append("no open incidents")
            return lines
        r = obj
        return [f"{r.a} - {r.b}", f"{r.distance:g} km, {'CLOSED' if r.closed else 'open'}",
                "click to select, right-click to close / reopen"]

    def _draw_hover(self, s):
        mx, my = pygame.mouse.get_pos()
        if mx >= MAP_W:
            return
        hit = self.map.hover_target((mx, my), self.sim)
        if not hit:
            s.blit(self.f["tiny"].render("Hover for details  -  H for shortcuts", True, DIM), (14, H - 20))
            return
        lines = self._tooltip_lines(*hit)
        font = self.f["small"]
        w = max(font.size(line)[0] for line in lines) + 16
        h = len(lines) * 18 + 10
        x = min(mx + 14, MAP_W - w - 6)
        y = min(my + 14, H - h - 6)
        box = pygame.Rect(x, y, w, h)
        pygame.draw.rect(s, PANEL_BG, box, border_radius=6)
        pygame.draw.rect(s, ACCENT, box, 1, border_radius=6)
        for k, line in enumerate(lines):
            s.blit(font.render(line, True, TEXT if k == 0 else DIM), (x + 8, y + 5 + k * 18))

    def _draw_help(self, s):
        panel = pygame.Surface((MAP_W, H), pygame.SRCALPHA)
        panel.fill((10, 13, 18, 200))
        s.blit(panel, (0, 0))
        box = pygame.Rect(0, 0, 420, 62 + 26 * len(HELP))
        box.center = (MAP_W // 2, H // 2)
        pygame.draw.rect(s, PANEL_BG, box, border_radius=10)
        pygame.draw.rect(s, ACCENT, box, 2, border_radius=10)
        s.blit(self.f["title"].render("Keyboard shortcuts", True, TEXT), (box.x + 20, box.y + 14))
        for k, (key, text) in enumerate(HELP):
            y = box.y + 50 + k * 26
            s.blit(self.f["small_bold"].render(key, True, ACCENT), (box.x + 24, y))
            s.blit(self.f["small"].render(text, True, TEXT), (box.x + 130, y))

    @property
    def location(self):
        return self.loc.value

    @property
    def selected_road(self):
        return self.road.value if self._recent("road", 238) else None

    @property
    def selected_vehicle(self):
        return self.vehicle.value if self._recent("vehicle", 270) else None

    @property
    def focus_vehicle(self):
        return self.vehicle.value

    def _head(self, s, text, y, right=""):
        s.blit(self.f["head"].render("  ".join(text.split(" ")).upper(), True, ACCENT), (X0, y))
        if right:
            label = self.f["tiny"].render(right, True, DIM)
            s.blit(label, label.get_rect(topright=(X0 + CW, y)))

    def _label(self, s, text, x, y):
        label = self.f["small"].render(text, True, DIM)
        s.blit(label, label.get_rect(midleft=(x, y + 13)))

    def _draw_panel(self, s):
        mouse = pygame.mouse.get_pos()
        pygame.draw.rect(s, PANEL_BG, (PX, 0, PANEL_W, H))
        pygame.draw.line(s, RULE, (PX, 0), (PX, H), 2)
        s.blit(self.f["title"].render("AEGIS Control Centre", True, TEXT), (X0, 12))
        state = "PAUSED" if self.paused else f"{self.speed:g}x"
        clock = self.f["body_bold"].render(f"t = {self.sim.now:5.1f} h   {state}", True,
                                           AMBER if self.paused else GREEN)
        s.blit(clock, clock.get_rect(topright=(X0 + CW, 17)))

        self._head(s, "1 Report an incident", 50)
        self._label(s, "Type", X0, 70)
        self._label(s, "Severity", X0 + 236, 70)
        self._label(s, "Location", X0, 102)
        self._label(s, "People", X0 + 236, 102)
        tip = "Click a city on the map to choose the location.  Enter = Report now."
        s.blit(self.f["tiny"].render(tip, True, DIM), (X0, 132))
        batch = ", ".join(f"{b['kind']} {b['location']} S{b['severity']}" for b in self.batch)
        s.blit(self.f["small"].render(f"Batch: {batch or 'empty - incidents added here happen together'}"[:70],
                                      True, TEXT if self.batch else DIM), (X0, 186))

        self._head(s, "2 Disruptions", 218)
        self._label(s, "Road", X0, 238)
        self._label(s, "Vehicle", X0, 270)
        hint = self.f["tiny"].render("roads get blocked, trucks break down", True, DIM)
        s.blit(hint, hint.get_rect(midleft=(X0 + 246, 315)))

        self._head(s, "3 Simulation", 340)
        speed = self.f["body_bold"].render(f"{self.speed:g}x", True, TEXT)
        s.blit(speed, speed.get_rect(center=(X0 + 165, 374)))

        for w in self.widgets:
            w.draw(s, self.f["small_bold"] if isinstance(w, Button) else self.f["small"], mouse)

        pygame.draw.line(s, RULE, (X0, 400), (X0 + CW, 400))
        self._draw_priority(s, 408)
        self._draw_fleet(s, 506)
        self._draw_log(s, 620)

    def _draw_priority(self, s, y):
        self._head(s, "Priority order", y, "urgency = severity x people / hours waiting")
        queue = self.sim.ranked()
        y += 18
        if not queue:
            s.blit(self.f["small"].render("No open incidents.", True, DIM), (X0, y))
        for rank, inc in enumerate(queue[:4], 1):
            color = RED if inc.status == "active" else AMBER
            pygame.draw.circle(s, color, (X0 + 5, y + 8), 4)
            s.blit(self.f["small_bold"].render(f"{rank}. {inc.type} · {inc.location}", True, TEXT), (X0 + 14, y))
            detail = f"S{inc.severity} · {inc.people_affected} ppl · urg {urgency(inc, self.sim.now):.0f}"
            s.blit(self.f["small"].render(detail, True, DIM), (X0 + 168, y))
            who = inc.assigned_to or "WAITING"
            label = self.f["small_bold"].render(who, True, color)
            s.blit(label, label.get_rect(topright=(X0 + CW, y)))
            y += 18
        if len(queue) > 4:
            s.blit(self.f["tiny"].render(f"+{len(queue) - 4} more", True, DIM), (X0 + 14, y))

    def _draw_fleet(self, s, y):
        self._head(s, "Fleet", y, f"base: {self.sim.depot}")
        y += 18
        for v in self.sim.fleet:
            spr = self.map.sprite(v.kind, 0)
            s.blit(spr, (X0, y))
            s.blit(self.f["small_bold"].render(v.name, True, TEXT), (X0 + 36, y))
            text, color = self._status(v)
            s.blit(self.f["small"].render(text, True, color), (X0 + 136, y))
            y += 19

    def _status(self, v):
        now = self.sim.now
        if v.status == "idle":
            return ("At base" if v.location == self.sim.depot else f"Idle at {v.location}"), DIM
        if v.status == "dispatched":
            if v.backtrack:
                how = f"turning back to {v.path[v.seg]}"
            elif v.pending:
                how = f"new route from {v.path[v.seg + 1]}"
            else:
                how = f"{v.algorithm} · {self.map.remaining_km(v):.0f} km left"
            return f"To {v.target} · {how}", ACCENT
        if v.status == "on_scene":
            return f"On scene at {v.location} · {max(0, v.until - now):.1f} h", GREEN
        if v.status == "returning":
            return f"Returning to base · {self.map.remaining_km(v):.0f} km", DIM
        return f"BROKEN DOWN · repaired in {max(0, v.until - now):.1f} h", RED

    def _draw_log(self, s, y):
        self._head(s, "Decision log", y, "T: type a scenario (beta)")
        y += 18
        lines = []
        for e in self.sim.events[-8:]:
            lines += self._wrap(e, self.f["tiny"], CW)
        room = (H - 6 - y) // 15
        for k, line in enumerate(lines[-room:]):
            newest = k == len(lines[-room:]) - 1
            s.blit(self.f["tiny"].render(line, True, TEXT if newest else DIM), (X0, y))
            y += 15

    def _draw_prompt(self, s):
        rect = pygame.Rect(12, H - 62, MAP_W - 24, 50)
        pygame.draw.rect(s, (24, 28, 37), rect, border_radius=10)
        pygame.draw.rect(s, ACCENT, rect, 2, border_radius=10)
        s.blit(self.f["tiny"].render("Describe a scenario (beta)  -  Enter to run, Esc to cancel", True, DIM),
               (rect.x + 12, rect.y + 6))
        line = self._wrap(self.buffer + "_", self.f["body"], rect.w - 24)[-1]
        s.blit(self.f["body"].render(line, True, TEXT), (rect.x + 12, rect.y + 23))

    @staticmethod
    def _wrap(text, font, width):
        lines, line = [], ""
        for word in text.split(" "):
            trial = f"{line} {word}".strip()
            if font.size(trial)[0] > width and line:
                lines.append(line)
                line = word
            else:
                line = trial
        return lines + [line]

    # ---- main loop ---------------------------------------------------
    def step(self, dt):
        if not self.paused:
            self.sim.step(BASE_SPEED_KMPS * self.speed * min(dt, 0.1) / AVG_SPEED_KMH)

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                running = self.handle(event) and running
            self.step(self.clock.tick(60) / 1000)
            self.draw()
            pygame.display.flip()
        pygame.quit()
