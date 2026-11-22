"""CSV export / import of simulation records and algorithm benchmarks."""
import csv
import os
from pathlib import Path

# Written output lives outside the package so a read-only or containerised
# install can redirect it: AEGIS_RESULTS_DIR=/data/results
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = Path(os.environ.get("AEGIS_RESULTS_DIR") or PROJECT_ROOT / "results")

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
