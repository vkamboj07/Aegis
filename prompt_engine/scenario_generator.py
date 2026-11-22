"""Natural-language text -> structured scenario (JSON) -> simulation event queue."""
import json

from environment.events import DEFAULT_SCENARIOS
from prompt_engine.llm import parse_with_llm
from prompt_engine.parser import parse


def build_scenario(text, graph, use_llm=False, client=None):
    """Interpret `text` with the keyword parser; if it finds nothing and
    use_llm is set, try the optional LLM fallback. Returns a scenario dict:
    {description, events, method, warnings}."""
    result = parse(text, graph.nodes, set(graph.roads))
    if not result.events and use_llm:
        llm = parse_with_llm(text, graph.nodes, set(graph.roads), client)
        if llm and llm.events:
            result = llm
        else:
            result.warnings.append("LLM fallback unavailable or found nothing.")
    return {"description": text.strip(), "events": result.events,
            "method": result.method, "warnings": result.warnings}


def schedule(sim, scenario, offset=None):
    """Queue a scenario's events on a simulation, starting `offset` hours from
    now (default: right now)."""
    sim.queue.load_events(scenario["events"], sim.now if offset is None else offset)


def save_scenario(name, scenario, path=DEFAULT_SCENARIOS):
    """Add a scenario to the scenarios file so `--analyze` and the runner can use it."""
    data = json.loads(path.read_text())
    data[name] = {"description": scenario["description"], "events": scenario["events"]}
    path.write_text(json.dumps(data, indent=2) + "\n")
