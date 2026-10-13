from dataclasses import dataclass


@dataclass
class Road:
    a: str
    b: str
    distance: float
    closed: bool = False

    @property
    def key(self):
        return frozenset((self.a, self.b))

    def other(self, node):
        return self.b if node == self.a else self.a
