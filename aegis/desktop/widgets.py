"""Small Pygame widgets for the control panel: Button, Cycler, Stepper."""
import pygame

BG, HOVER, BORDER = (44, 50, 64), (58, 66, 84), (72, 80, 98)
TEXT, DISABLED = (232, 235, 242), (100, 106, 120)
STYLES = {                       # background, hover, text
    "normal": (BG, HOVER, TEXT),
    "primary": ((38, 108, 208), (56, 128, 228), (255, 255, 255)),
    "danger": ((168, 48, 48), (196, 62, 62), (255, 255, 255)),
    "ok": ((34, 128, 82), (44, 152, 98), (255, 255, 255)),
}


def _value(x):
    return x() if callable(x) else x


def _fit(font, text, width):
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "…")[0] > width:
        text = text[:-1]
    return text + "…"


class Button:
    def __init__(self, rect, text, action, style="normal", enabled=True):
        self.rect, self.text, self.action = pygame.Rect(rect), text, action
        self.style, self.enabled = style, enabled

    def draw(self, s, font, mouse):
        on = _value(self.enabled)
        bg, hover, fg = STYLES[_value(self.style)]
        if not on:
            bg, fg = BG, DISABLED
        elif self.rect.collidepoint(mouse):
            bg = hover
        pygame.draw.rect(s, bg, self.rect, border_radius=6)
        pygame.draw.rect(s, BORDER, self.rect, 1, border_radius=6)
        label = font.render(_fit(font, _value(self.text), self.rect.w - 10), True, fg)
        s.blit(label, label.get_rect(center=self.rect.center))

    def click(self, pos):
        if self.rect.collidepoint(pos) and _value(self.enabled):
            self.action()
            return True
        return False


class Cycler:
    """[<] value [>] over a list of options; clicking the middle steps forward."""

    def __init__(self, rect, options, label=str, on_change=None):
        self.rect, self.options, self.label = pygame.Rect(rect), options, label
        self.on_change, self.index = on_change, 0

    @property
    def value(self):
        opts = _value(self.options)
        return opts[self.index % len(opts)] if opts else None

    def set(self, value):
        opts = _value(self.options)
        if value in opts:
            self.index = opts.index(value)

    def step(self, d):
        opts = _value(self.options)
        if opts:
            self.index = (self.index + d) % len(opts)
            if self.on_change:
                self.on_change(self.value)

    def draw(self, s, font, mouse):
        r = self.rect
        pygame.draw.rect(s, HOVER if r.collidepoint(mouse) else BG, r, border_radius=6)
        pygame.draw.rect(s, BORDER, r, 1, border_radius=6)
        cy = r.centery
        pygame.draw.polygon(s, TEXT, [(r.x + 9, cy), (r.x + 15, cy - 5), (r.x + 15, cy + 5)])
        pygame.draw.polygon(s, TEXT, [(r.right - 9, cy), (r.right - 15, cy - 5), (r.right - 15, cy + 5)])
        text = _fit(font, self.label(self.value) if self.value is not None else "-", r.w - 44)
        label = font.render(text, True, TEXT)
        s.blit(label, label.get_rect(center=r.center))

    def click(self, pos):
        if not self.rect.collidepoint(pos):
            return False
        self.step(-1 if pos[0] < self.rect.x + 24 else 1)
        return True


class Stepper:
    """[-] value [+] for a bounded number."""

    def __init__(self, rect, value, lo, hi, step=1):
        self.rect, self.value, self.lo, self.hi, self.inc = pygame.Rect(rect), value, lo, hi, step

    def draw(self, s, font, mouse):
        r = self.rect
        pygame.draw.rect(s, BG, r, border_radius=6)
        pygame.draw.rect(s, BORDER, r, 1, border_radius=6)
        for x, plus in ((r.x + 14, False), (r.right - 14, True)):
            hot = abs(mouse[0] - x) < 13 and r.collidepoint(mouse)
            if hot:
                pygame.draw.circle(s, HOVER, (x, r.centery), 10)
            pygame.draw.line(s, TEXT, (x - 5, r.centery), (x + 5, r.centery), 2)
            if plus:
                pygame.draw.line(s, TEXT, (x, r.centery - 5), (x, r.centery + 5), 2)
        label = font.render(str(self.value), True, TEXT)
        s.blit(label, label.get_rect(center=r.center))

    def click(self, pos):
        if not self.rect.collidepoint(pos):
            return False
        d = -self.inc if pos[0] < self.rect.centerx else self.inc
        self.value = max(self.lo, min(self.hi, self.value + d))
        return True
