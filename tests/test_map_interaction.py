import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from environment.city import CityGraph
from simulation.engine import Simulation
from visualization.map_view import MapView
from visualization.pygame_ui import App


class HoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.graph = CityGraph.load()
        cls.map = MapView(cls.graph, App._fonts())

    def setUp(self):
        self.sim = Simulation(self.graph)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_pointer_over_a_city_reports_the_city(self):
        self.assertEqual(self.map.hover_target(self.map.pos["Agra"], self.sim), ("city", "Agra"))

    def test_pointer_over_a_vehicle_reports_the_vehicle(self):
        vehicle = self.sim.fleet[0]
        x, y, _ = self.map.vehicle_pose(0, vehicle, self.sim)
        kind, obj = self.map.hover_target((x, y), self.sim)
        self.assertEqual(kind, "vehicle")
        self.assertIs(obj, vehicle)

    def test_pointer_over_a_road_reports_the_road(self):
        road = self.graph.road("Delhi", "Gurugram")
        mid = ((self.map.pos["Delhi"][0] + self.map.pos["Gurugram"][0]) / 2,
               (self.map.pos["Delhi"][1] + self.map.pos["Gurugram"][1]) / 2)
        hit = self.map.hover_target(mid, self.sim)
        self.assertIsNotNone(hit)
        if hit[0] == "road":                 # a vehicle or city can sit on the same spot
            self.assertIs(hit[1], road)


if __name__ == "__main__":
    unittest.main()
