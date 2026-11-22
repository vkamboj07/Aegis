"""Matplotlib analytics from the CSV rows written by simulation.recorder.

  algorithm_nodes.png      mean nodes expanded per algorithm (benchmark)
  algorithm_distance.png   mean route distance per algorithm (benchmark)
  response_time.png        response time of each resolved incident over the run
  scenario_resolution.png  mean response time and incidents resolved per scenario
"""
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
# categorical slots 1-5, fixed order: colour follows the entity, never its rank
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
ALGO_ORDER = ["BFS", "DFS", "UCS", "A*"]
ALGO_COLOR = dict(zip(ALGO_ORDER, SERIES))

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": ["Segoe UI", "DejaVu Sans"], "text.color": INK,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "xtick.major.size": 0, "ytick.major.size": 0,
})


def _frame(title, subtitle, size=(7.5, 4.6)):
    fig, ax = plt.subplots(figsize=size)
    fig.subplots_adjust(top=0.80, left=0.11, right=0.97, bottom=0.17)
    fig.text(0.11, 0.93, title, fontsize=14, fontweight="bold", color=INK, ha="left")
    fig.text(0.11, 0.875, subtitle, fontsize=9.5, color=INK2, ha="left")
    return fig, ax


def _save(fig, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _bars(ax, labels, values, colors, fmt):
    bars = ax.bar(labels, values, color=colors, width=0.55, edgecolor=SURFACE, linewidth=2)
    top = max(values) or 1
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v + top * 0.02, fmt(v),
                ha="center", va="bottom", fontsize=10, color=INK, fontweight="bold")
    ax.set_ylim(0, top * 1.15)


def _group(bench_rows, field):
    groups = defaultdict(list)
    for r in bench_rows:
        groups[r["algorithm"]].append(float(r[field]))
    return {a: sum(v) / len(v) for a, v in groups.items()}


def chart_nodes(bench_rows, path, journeys=5):
    """Grouped bars for the longest journeys. A mean over all pairs cannot tell
    BFS, DFS and UCS apart: each pops every node once in some order, so each
    averages (n + 2) / 2 expansions over all goals. Only A* differs."""
    mean = _group(bench_rows, "nodes_expanded")
    algos = [a for a in ALGO_ORDER if a in mean]
    dist = {}
    for r in bench_rows:
        if r["algorithm"] == "UCS" and frozenset((r["start"], r["goal"])) not in dist:
            dist[frozenset((r["start"], r["goal"]))] = (float(r["distance_km"]), r["start"], r["goal"])
    far = sorted(dist.values(), reverse=True)[:journeys]
    nodes = {(r["algorithm"], r["start"], r["goal"]): float(r["nodes_expanded"]) for r in bench_rows}
    means = ", ".join(f"{a} {mean[a]:.1f}" for a in algos)
    fig, ax = _frame("Nodes expanded per search",
                     f"The {journeys} longest journeys (fewer is less search effort). "
                     f"Mean over all city pairs: {means}", size=(9.5, 4.8))
    width = 0.8 / len(algos)
    for k, a in enumerate(algos):
        xs = [i + (k - (len(algos) - 1) / 2) * width for i in range(len(far))]
        vals = [nodes[a, s, g] for _, s, g in far]
        ax.bar(xs, vals, width=width, color=ALGO_COLOR[a], edgecolor=SURFACE, linewidth=2, label=a)
        for x, v in zip(xs, vals):
            ax.text(x, v + 0.2, f"{v:.0f}", ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(range(len(far)))
    ax.set_xticklabels([f"{s} to {g}\n{d:.0f} km" for d, s, g in far])
    ax.set_ylabel("nodes expanded")
    ax.legend(frameon=False, ncol=len(algos), fontsize=9, labelcolor=INK2,
              loc="lower left", bbox_to_anchor=(0, 1.0))
    return _save(fig, path)


def chart_distance(bench_rows, path):
    mean = _group(bench_rows, "distance_km")
    best = {(r["start"], r["goal"]): float(r["distance_km"])
            for r in bench_rows if r["algorithm"] == "UCS"}     # UCS is optimal
    hits = defaultdict(int)
    for r in bench_rows:
        hits[r["algorithm"]] += float(r["distance_km"]) <= best[r["start"], r["goal"]] + 1e-6
    pairs = len(best)
    fig, ax = _frame("Route distance per algorithm",
                     f"Mean over all {pairs} ordered city pairs; the % row is how often the route is shortest")
    algos = [a for a in ALGO_ORDER if a in mean]
    _bars(ax, [f"{a}\n{100 * hits[a] / pairs:.0f}% shortest" for a in algos],
          [mean[a] for a in algos], [ALGO_COLOR[a] for a in algos], lambda v: f"{v:.0f} km")
    ax.set_ylabel("distance (km)")
    return _save(fig, path)


def _scenarios(sim_rows):
    names = []
    for r in sim_rows:
        if r["scenario"] not in names:
            names.append(r["scenario"])
    return names


def _colors(names):
    return {n: SERIES[i % len(SERIES)] for i, n in enumerate(names)}


def chart_response(sim_rows, path):
    names = _scenarios(sim_rows)
    color = _colors(names)
    fig, ax = _frame("Response time over the simulation",
                     "Each marker is a resolved incident: hours from report to arrival, by time resolved")
    for i, n in enumerate(names):
        pts = sorted((float(r["time_h"]), float(r["response_h"]))
                     for r in sim_rows if r["scenario"] == n and r["event"] == "resolved")
        if not pts:
            continue
        xs, ys = zip(*pts)
        # earlier series get bigger markers, so identical points from two
        # scenarios show as nested rings instead of one hiding the other
        ax.plot(xs, ys, color=color[n], linewidth=2, marker="o",
                markersize=8 + 3 * (len(names) - 1 - i), markeredgecolor=SURFACE,
                markeredgewidth=2, label=n, zorder=3 + i)
    ax.set_xlabel("simulation time (h)")
    ax.set_ylabel("response time (h)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper left")
    return _save(fig, path)


def chart_resolution(sim_rows, path):
    names = _scenarios(sim_rows)
    color = _colors(names)
    mean, counts = [], []
    for n in names:
        rows = [r for r in sim_rows if r["scenario"] == n]
        resp = [float(r["response_h"]) for r in rows if r["event"] == "resolved"]
        reported = sum(r["event"] == "incident_reported" for r in rows)
        mean.append(sum(resp) / len(resp) if resp else 0.0)
        counts.append(f"{len(resp)}/{reported} resolved")
    fig, ax = _frame("Incident resolution by scenario",
                     "Mean response time (hours from report to arrival) and incidents resolved",
                     size=(8.5, 4.6))
    _bars(ax, [f"{n}\n{c}" for n, c in zip(names, counts)], mean,
          [color[n] for n in names], lambda v: f"{v:.1f} h")
    ax.set_ylabel("mean response time (h)")
    return _save(fig, path)


def make_all(bench_rows, sim_rows, out_dir):
    out = Path(out_dir)
    return [chart_nodes(bench_rows, out / "algorithm_nodes.png"),
            chart_distance(bench_rows, out / "algorithm_distance.png"),
            chart_response(sim_rows, out / "response_time.png"),
            chart_resolution(sim_rows, out / "scenario_resolution.png")]
