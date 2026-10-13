"""Price-performance and speed-performance frontiers for the leaderboard.

A system is on the frontier when no other system is both at least as accurate and
cheaper (or faster). Accuracy per task:

- paved-area takeoff: mean IoU over every attempt, invalid polygons scoring 0;
- stall counting: count accuracy = 1 - mean absolute count error, floored at 0.

Charts are dependency-free SVG with a log-scaled cost or latency axis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FrontierPoint:
    system: str
    x: float  # cost (USD) or latency (s); lower is better
    y: float  # accuracy in [0, 1]; higher is better


def area_accuracy(summary: dict[str, Any]) -> float | None:
    if not summary.get("cases"):
        return None
    return float(summary.get("meanIou", 0.0))


def stall_accuracy(summary: dict[str, Any]) -> float | None:
    err = summary.get("meanAbsCountErrorPct")
    if err is None:
        return None
    return max(0.0, 1.0 - float(err) / 100.0)


def pareto_front(points: list[FrontierPoint]) -> list[FrontierPoint]:
    """Points not dominated by a cheaper-or-equal, at-least-as-accurate point, cheapest first."""

    front: list[FrontierPoint] = []
    best = -math.inf
    for point in sorted(points, key=lambda p: (p.x, -p.y)):
        if point.y > best:
            front.append(point)
            best = point.y
    return front


def _log_ticks(lo: float, hi: float) -> list[float]:
    ticks: list[float] = []
    exp = math.floor(math.log10(lo))
    while 10**exp <= hi * 1.0001:
        for m in (1, 2, 5):
            v = m * 10**exp
            if lo <= v <= hi:
                ticks.append(v)
        exp += 1
    return ticks


def _fmt(v: float, unit: str) -> str:
    if unit == "$":
        return f"${v:.3f}".rstrip("0").rstrip(".") if v < 1 else f"${v:g}"
    return f"{v:g} s"


def render_frontier_svg(points: list[FrontierPoint], x_label: str, y_label: str, unit: str, title: str) -> str:
    """A scatter of all systems with the frontier drawn as a step line."""

    width, height = 820, 440
    left, right, top, bottom = 70, 290, 46, 56
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = [p.x for p in points if p.x > 0]
    lo, hi = (min(xs) / 1.6, max(xs) * 1.6) if xs else (0.01, 1.0)
    y_lo = max(0.0, math.floor((min(p.y for p in points) - 0.05) * 10) / 10) if points else 0.0
    y_hi = 1.0

    def sx(v: float) -> float:
        return left + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * plot_w

    def sy(v: float) -> float:
        return top + (1 - (v - y_lo) / (y_hi - y_lo)) * plot_h

    front = pareto_front([p for p in points if p.x > 0])
    front_names = {p.system for p in front}
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{left}" y="26" font-size="16" font-weight="700" fill="#1b1f22">{escape(title)}</text>',
    ]
    for t in _log_ticks(lo, hi):
        x = sx(t)
        out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" stroke="#e3e6e8"/>')
        out.append(f'<text x="{x:.1f}" y="{top + plot_h + 18}" font-size="11" text-anchor="middle" fill="#5a6166">{escape(_fmt(t, unit))}</text>')
    steps = int(round((y_hi - y_lo) / 0.1))
    for i in range(steps + 1):
        v = y_lo + i * 0.1
        y = sy(v)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#e3e6e8"/>')
        out.append(f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end" fill="#5a6166">{v:.1f}</text>')
    out.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#9aa2a7"/>')
    out.append(f'<text x="{left + plot_w / 2}" y="{height - 14}" font-size="12" text-anchor="middle" fill="#1b1f22">{escape(x_label)} (log scale; left is better)</text>')
    out.append(
        f'<text transform="translate(18 {top + plot_h / 2}) rotate(-90)" font-size="12" text-anchor="middle" fill="#1b1f22">{escape(y_label)} (up is better)</text>'
    )
    if len(front) > 1:
        path = []
        for i, p in enumerate(front):
            if i:
                path.append(f"L{sx(p.x):.1f},{sy(front[i - 1].y):.1f}")
            path.append(f"{'M' if i == 0 else 'L'}{sx(p.x):.1f},{sy(p.y):.1f}")
        out.append(f'<path d="{" ".join(path)}" fill="none" stroke="#d08a00" stroke-width="2" stroke-dasharray="5 4"/>')
    ordered = sorted(points, key=lambda p: -p.y)
    for n, p in enumerate(ordered, start=1):
        if p.x <= 0:
            continue
        on = p.system in front_names
        x, y = sx(p.x), sy(max(y_lo, p.y))
        fill = "#d08a00" if on else "#6b7c8f"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{6 if on else 4.5}" fill="{fill}" stroke="#ffffff" stroke-width="1.5"/>')
        out.append(f'<text x="{x + 8:.1f}" y="{y - 6:.1f}" font-size="10.5" font-weight="700" fill="{fill}">{n}</text>')
    # Legend: numbered systems, frontier members highlighted.
    lx = left + plot_w + 18
    out.append(f'<text x="{lx}" y="{top + 4}" font-size="11" font-weight="700" fill="#1b1f22">Systems (best first)</text>')
    for n, p in enumerate(ordered, start=1):
        on = p.system in front_names
        name = p.system if len(p.system) <= 44 else p.system[:43] + "…"
        out.append(
            f'<text x="{lx}" y="{top + 22 + (n - 1) * 15}" font-size="10.5" fill="{"#a86f00" if on else "#3d464c"}" font-weight="{700 if on else 400}">{n}. {escape(name)}</text>'
        )
    out.append(
        f'<text x="{lx}" y="{top + 22 + len(ordered) * 15 + 8}" font-size="10" fill="#5a6166">Gold = on the frontier</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def frontier_points(runs: list[dict[str, Any]], kind: str, axis: str) -> list[FrontierPoint]:
    """Collect (cost|latency, accuracy) per system for one task kind ('area' or 'stall')."""

    task = "click_connected_polygon" if kind == "area" else "stall_count"
    points: list[FrontierPoint] = []
    for run in runs:
        # A submitter can keep a system off a task's frontier with a stated reason
        # (frontierExclude + frontierNote), e.g. when count-only scoring cannot see a
        # known placement fault. The system still appears in the tables.
        if task in (run.get("frontierExclude") or []):
            continue
        report = run["_report"]
        summary = report.get("summary" if kind == "area" else "stallSummary") or {}
        acc = area_accuracy(summary) if kind == "area" else stall_accuracy(summary)
        if acc is None:
            continue
        if axis == "cost":
            x = summary.get("meanCostUsd")
        else:
            x = summary.get("p50LatencyMs")
            x = None if x is None else float(x) / 1000.0
        if x is None:
            continue
        points.append(FrontierPoint(str(run.get("system", "?")), float(x), acc))
    return points


def write_frontier_charts(runs: list[dict[str, Any]], out_dir: Path) -> dict[str, list[str]]:
    """Write frontier SVGs next to the leaderboard; return {chart file: frontier systems}."""

    written: dict[str, list[str]] = {}
    specs = [
        ("area", "cost", "Mean cost per lot", "Mean IoU", "$", "Paved-area takeoff: accuracy vs cost"),
        ("area", "latency", "Median latency per lot", "Mean IoU", "s", "Paved-area takeoff: accuracy vs speed"),
        ("stall", "cost", "Mean cost per lot", "Count accuracy", "$", "Stall counting: accuracy vs cost"),
        ("stall", "latency", "Median latency per lot", "Count accuracy", "s", "Stall counting: accuracy vs speed"),
    ]
    for kind, axis, x_label, y_label, unit, title in specs:
        points = frontier_points(runs, kind, axis)
        if len(points) < 2:
            continue
        name = f"frontier-{kind}-{axis}.svg"
        (out_dir / name).write_text(render_frontier_svg(points, x_label, y_label, unit, title), encoding="utf-8")
        written[name] = [p.system for p in pareto_front(points)]
    return written
