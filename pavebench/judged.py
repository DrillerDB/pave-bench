"""Judged tasks: scored by a model judge instead of gold geometry.

Used where no gold exists yet (stripe lines today). A judged section is always
rendered apart from the gold-scored tables and names its judge, its reference
system and its calibration, because a judge is evidence, not ground truth.

Input file (JSON):

    {
      "task": "stripe_lines",
      "judge": "claude-opus-5-5",
      "reference": "<system every challenger is paired against>",
      "method": "<one paragraph>",
      "calibration": {"referenceSelfWinRate": 0.5, "orderAgreement": 0.8, "pairs": 12},
      "systems": [
        {"system": "...", "comparisons": 24, "lots": 6, "winRateVsReference": 0.4,
         "meanUsability": 6.8, "faults": {"rowsMissedMean": 0.2, "linesWithoutPaintMany": 1,
         "offsetLinesMany": 0, "hatchingOutlineOrMissing": 9},
         "meanCostUsd": 0.11, "p50LatencyMs": 80000}
      ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .frontier import FrontierPoint, pareto_front, render_frontier_svg


def load_judged(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v:.0%}"


def render_judged_section(data: dict[str, Any], out_dir: Path | None = None) -> list[str]:
    task = data.get("task", "judged")
    title = {"stripe_lines": "Stripe lines"}.get(task, task)
    lines = [f"## {title} (judged by {data.get('judge', '?')}, no gold)", ""]
    if data.get("method"):
        lines += [data["method"], ""]
    cal = data.get("calibration") or {}
    if cal:
        lines += [
            f"Calibration: the reference against its own second try won {_pct(cal.get('referenceSelfWinRate'))} "
            f"(a fair judge is near 50%); the judge gave the same verdict in both A/B orders on "
            f"{_pct(cal.get('orderAgreement'))} of {cal.get('pairs', '?')} pairs.",
            "",
        ]
    systems = sorted(data.get("systems", []), key=lambda s: -(s.get("meanUsability") or 0))
    lines.append(
        f"| System | Lots | Comparisons | Win rate vs {data.get('reference', 'reference')} | mean usability (0-10) | "
        "rows missed / draft | many lines without paint | hatching outline-only or missing | p50 latency | mean cost |"
    )
    lines.append("|" + "---|" * 10)
    for s in systems:
        f = s.get("faults", {})
        lat = s.get("p50LatencyMs")
        cost = s.get("meanCostUsd")
        lines.append(
            "| {sys} | {lots} | {n} | {win} | {u} | {rm} | {lwp} | {hatch} | {lat} | {cost} |".format(
                sys=s["system"],
                lots=s.get("lots", "-"),
                n=s.get("comparisons", "-"),
                win=_pct(s.get("winRateVsReference")),
                u="-" if s.get("meanUsability") is None else f"{s['meanUsability']:.1f}",
                rm="-" if f.get("rowsMissedMean") is None else f"{f['rowsMissedMean']:.1f}",
                lwp=_pct(f.get("linesWithoutPaintManyRate")),
                hatch=_pct(f.get("hatchingOutlineOrMissingRate")),
                lat="-" if lat is None else f"{lat / 1000:.1f} s",
                cost="-" if cost is None else f"${cost:.3f}",
            )
        )
    lines.append("")
    if out_dir is not None:
        points = [
            FrontierPoint(s["system"], float(s["meanCostUsd"]), float(s["meanUsability"]) / 10.0)
            for s in systems
            if s.get("meanCostUsd") and s.get("meanUsability") is not None
        ]
        if len(points) >= 2:
            name = f"frontier-{task}-cost.svg"
            (out_dir / name).write_text(
                render_frontier_svg(points, "Mean cost per lot", "Judged usability / 10", "$", f"{title} (judged): usability vs cost"),
                encoding="utf-8",
            )
            lines += [f"![{name}]({name})", "", "Frontier: " + " → ".join(p.system for p in pareto_front(points)), ""]
    return lines
