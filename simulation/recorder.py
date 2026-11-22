"""CSV export / import of simulation records and algorithm benchmarks."""
import csv
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

SIM_FIELDS = ["scenario", "time_h", "event", "incident", "incident_type", "location",
              "severity", "vehicle", "algorithm", "distance_km", "nodes_expanded",
              "search_ms", "response_h", "detail"]
BENCH_FIELDS = ["algorithm", "start", "goal", "distance_km", "nodes_expanded", "search_ms"]


def save_csv(rows, path, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
