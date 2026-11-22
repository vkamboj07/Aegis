"""AEGIS: AI-based multi-agent emergency response simulation.

Layers, in dependency order - each one only imports from the ones above it:

    aegis.core      the simulation itself: city graph, search algorithms, agents,
                    CSP allocation, knowledge rules, prompt engine. Pure standard
                    library, no third-party imports, no I/O beyond its data files.
    aegis.charts    matplotlib analytics over the recorded CSV rows.   [charts]
    aegis.desktop   the Pygame control centre.                        [desktop]
    aegis.api       FastAPI service exposing the simulation as JSON.   [api]
    aegis.web       browser control centre served by aegis.api.

The names in brackets are the optional dependency extras that layer needs, so a
deployment installs only what it runs: `pip install .[api]` for the web service.
"""
__version__ = "1.0.0"
