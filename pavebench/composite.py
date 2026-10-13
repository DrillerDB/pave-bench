"""Composite score: one number for a full takeoff (lot outline + stall count + striping).

Defined only for a system that ran all three jobs with the same configuration:

- score = mean of the three job scores, each on 0-1 where 1 is perfect:
  lot outline mean IoU, stall count accuracy (1 - mean count error), and judged
  stripe usability / 10;
- cost = the three per-lot costs added (a full takeoff of one lot), or None when
  any job has no per-call price;
- time = the three median per-lot times added (the jobs run one after another);
- a system held off any job's frontier is held off the composite frontier too.

The stripe component is judged, not gold-scored, until stripe gold exists; the
composite inherits that caveat.
"""

from __future__ import annotations

from typing import Any

WEIGHTS = {"area": 1 / 3, "stall": 1 / 3, "stripe": 1 / 3}


def composite_rows(
    area: list[dict[str, Any]], stall: list[dict[str, Any]], judged: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join per-job rows by system name into composite rows (systems with all three jobs)."""

    by_area = {r["system"]: r for r in area}
    by_stall = {r["system"]: r for r in stall}
    stripe = {}
    for j in judged:
        if j.get("task") == "stripe_lines":
            stripe.update({s["system"]: s for s in j.get("systems", []) if s.get("meanUsability") is not None})
    rows: list[dict[str, Any]] = []
    for name, a in by_area.items():
        s, j = by_stall.get(name), stripe.get(name)
        if s is None or j is None:
            continue
        parts = {"area": float(a["accuracy"]), "stall": float(s["accuracy"]), "stripe": float(j["meanUsability"]) / 10}
        costs = [a.get("cost"), s.get("cost"), j.get("meanCostUsd")]
        times = [a.get("p50"), s.get("p50"), j.get("p50LatencyMs")]
        excluded = bool(a.get("excluded") or s.get("excluded"))
        rows.append(
            {
                "system": name,
                "provider": a.get("provider") or "Other",
                "accuracy": sum(WEIGHTS[k] * v for k, v in parts.items()),
                "components": parts,
                "cost": sum(costs) if all(c is not None for c in costs) else None,
                "p50": sum(times) if all(t is not None for t in times) else None,
                "excluded": excluded,
                "frontierNote": a.get("frontierNote") or s.get("frontierNote") or "",
                "notes": a.get("notes") or "",
            }
        )
    rows.sort(key=lambda r: -r["accuracy"])
    return rows


def render_composite_section(rows: list[dict[str, Any]], chart: str | None = None, frontier: list[str] | None = None) -> list[str]:
    if not rows:
        return []
    lines = [
        "## Composite: full takeoff (lot outline + stall count + striping)",
        "",
        "Mean of the three job scores on 0-1 (outline mean IoU, stall count accuracy, judged "
        "stripe usability / 10), for systems that ran all three jobs with the same configuration. "
        "Cost and time are for all three jobs on one lot. The stripe component is judged, not "
        "gold-scored.",
        "",
        "| # | System | Composite | Outline IoU | Stall accuracy | Stripe usability | Time / lot | Cost / lot |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, start=1):
        c = r["components"]
        lines.append(
            "| {i} | {sys}{held} | {comp:.3f} | {a:.3f} | {s:.1%} | {st:.1f} | {t} | {cost} |".format(
                i=i,
                sys=r["system"],
                held=" (held off frontier)" if r["excluded"] else "",
                comp=r["accuracy"],
                a=c["area"],
                s=c["stall"],
                st=c["stripe"] * 10,
                t="-" if r["p50"] is None else f"{r['p50'] / 1000:.0f} s",
                cost="-" if r["cost"] is None else f"${r['cost']:.3f}",
            )
        )
    lines.append("")
    if chart:
        lines += [f"![{chart}]({chart})", ""]
    if frontier:
        lines += ["Frontier: " + " → ".join(frontier), ""]
    return lines
