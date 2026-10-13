from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .frontier import write_frontier_charts
from .judged import load_judged, render_judged_section

# INSTANT badge gates. A system earns the badge only when it is fully automated,
# lands in the INSTANT latency class, and clears the accuracy floor across enough
# reviewed-gold cases spanning multiple GSD tiers. See docs/proving-instant-takeoff.md.
INSTANT_MIN_CASES = 20
INSTANT_MIN_GSD_TIERS = 2
INSTANT_MIN_PASS_RATE = 0.90


def load_runs(path: str | Path) -> list[dict[str, Any]]:
    manifest_path = Path(path)
    base_dir = manifest_path.parent
    runs: list[dict[str, Any]] = []
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        score_value = row.get("scorePath")
        if not score_value:
            raise ValueError(f"Run row {line_number} is missing scorePath")
        score_path = Path(score_value)
        if not score_path.is_absolute():
            score_path = base_dir / score_path
        row["_report"] = json.loads(score_path.read_text(encoding="utf-8"))
        runs.append(row)
    return runs


def _gsd_tier_span(summary: dict[str, Any]) -> int:
    tiers = summary.get("byGsdTier", {})
    return sum(1 for tier in tiers if tier != "unknown")


def instant_badge(summary: dict[str, Any], automation: str) -> tuple[bool, list[str]]:
    """Return (earned, unmet_reasons) for the INSTANT badge."""

    reasons: list[str] = []
    if automation != "full_auto":
        reasons.append(f"automation={automation} (needs full_auto)")
    if summary.get("latencyClass") != "INSTANT":
        reasons.append(f"latencyClass={summary.get('latencyClass')} (needs INSTANT)")
    cases = int(summary.get("cases", 0))
    if cases < INSTANT_MIN_CASES:
        reasons.append(f"{cases} cases (needs >= {INSTANT_MIN_CASES})")
    passes = int(summary.get("passes", 0))
    pass_rate = passes / cases if cases else 0.0
    if pass_rate < INSTANT_MIN_PASS_RATE:
        reasons.append(f"pass rate {pass_rate:.0%} (needs >= {INSTANT_MIN_PASS_RATE:.0%})")
    tiers = _gsd_tier_span(summary)
    if tiers < INSTANT_MIN_GSD_TIERS:
        reasons.append(f"{tiers} GSD tiers (needs >= {INSTANT_MIN_GSD_TIERS})")
    return (not reasons, reasons)


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _num(value: float | None, suffix: str = "") -> str:
    return "-" if value is None else f"{value:g}{suffix}"


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value / 1000:.1f} s"


def _usd(value: float | None) -> str:
    return "-" if value is None else f"${value:.3f}"


def _tries(summary: dict[str, Any]) -> str:
    cases = int(summary.get("cases", 0))
    distinct = int(summary.get("distinctCases") or 0)
    if distinct and cases % distinct == 0 and cases != distinct:
        return f"{distinct} x {cases // distinct}"
    return str(cases)


def _valid_rate(summary: dict[str, Any]) -> float | None:
    cases = int(summary.get("cases", 0))
    if not cases:
        return None
    bad = sum(int(summary.get(k, 0)) for k in ("invalidPolygons", "emptyPredictions", "missingPredictions"))
    return (cases - bad) / cases


def _notes(runs: list[dict[str, Any]], task: str) -> list[str]:
    out: list[str] = []
    for run in runs:
        parts = [run.get("notes") or ""]
        if task in (run.get("frontierExclude") or []):
            parts.append("Not on the frontier: " + (run.get("frontierNote") or "excluded by the submitter."))
        text = " ".join(p for p in parts if p).strip()
        if text:
            out.append(f"- **{run.get('system', '?')}**: {text}")
    return ["Notes:", "", *out, ""] if out else []


def render_leaderboard(runs: list[dict[str, Any]], frontier: dict[str, list[str]] | None = None) -> str:
    lines: list[str] = ["# PaveBench Leaderboard", ""]
    lines.append(
        "Latency class: **INSTANT** = p95 wall-clock <= 10 s, **FAST** <= 60 s, "
        "**BATCH** > 60 s. The INSTANT badge additionally requires full automation "
        f"(no human in the loop), pass rate >= {INSTANT_MIN_PASS_RATE:.0%} over "
        f">= {INSTANT_MIN_CASES} reviewed-gold cases spanning >= {INSTANT_MIN_GSD_TIERS} "
        "GSD tiers. See docs/proving-instant-takeoff.md."
    )
    lines.append("")
    lines.append(
        "*Cases* reads `lots x tries` when each lot was attempted more than once; every "
        "attempt is scored. *Valid* is the share of attempts that returned a usable polygon "
        "(simple outer ring, holes inside it and apart, every vertex on the image). "
        "*App-valid* is the share the submitting application's own validator accepted, when "
        "the submission reports it."
    )
    lines.append("")

    area_runs = [run for run in runs if run["_report"].get("summary", {}).get("cases")]
    area_runs.sort(key=lambda r: -float(r["_report"]["summary"].get("meanIou", 0.0)))
    if not area_runs:
        lines.append("_No area-task submissions yet._")
    else:
        lines.append("## Paved-area takeoff")
        lines.append("")
        header = (
            "| System | Track | Automation | Cases | Pass | Valid | App-valid | mean IoU | median areaΔ | "
            "p90 areaΔ | cutout recov. | p50 latency | p95 latency | Latency class | mean cost | INSTANT |"
        )
        lines.append(header)
        lines.append("|" + "---|" * 16)
        for run in area_runs:
            summary = run["_report"]["summary"]
            earned, _ = instant_badge(summary, run.get("automation", "unknown"))
            cases = int(summary.get("cases", 0))
            passes = int(summary.get("passes", 0))
            lines.append(
                "| {system} | {track} | {automation} | {cases} | {passrate} | {valid} | {app} | {iou:.3f} | "
                "{med} | {p90} | {recov} | {p50} | {lat} | {lclass} | {cost} | {badge} |".format(
                    system=run.get("system", "?"),
                    track=run.get("track", "-"),
                    automation=run.get("automation", "-"),
                    cases=_tries(summary),
                    passrate=f"{passes}/{cases}",
                    valid=_pct(_valid_rate(summary)),
                    app=_pct(summary.get("appValidRate")),
                    iou=float(summary.get("meanIou", 0.0)),
                    med=_pct(summary.get("medianAreaDeltaPct")),
                    p90=_pct(summary.get("p90AreaDeltaPct")),
                    recov=_pct(summary.get("meanCutoutRecovery")),
                    p50=_ms(summary.get("p50LatencyMs")),
                    lat=_ms(summary.get("p95LatencyMs")),
                    lclass=summary.get("latencyClass", "unknown"),
                    cost=_usd(summary.get("meanCostUsd")),
                    badge="YES" if earned else "-",
                )
            )
        lines.append("")
        lines.extend(_notes(area_runs, "click_connected_polygon"))

    stall_runs = [run for run in runs if run["_report"].get("stallSummary", {}).get("cases")]
    stall_runs.sort(key=lambda r: float(r["_report"]["stallSummary"].get("meanAbsCountErrorPct") or 1e9))
    if stall_runs:
        lines.append("## Stall counting")
        lines.append("")
        lines.append(
            "| System | Automation | Cases | Pass (±10%) | mean |countΔ| | median |countΔ| | p90 |countΔ| | "
            "App-valid | precision | recall | median loc. err | p50 latency | p95 latency | Latency class | mean cost |"
        )
        lines.append("|" + "---|" * 15)
        for run in stall_runs:
            summary = run["_report"]["stallSummary"]
            cases = int(summary.get("cases", 0))
            passes = int(summary.get("passes", 0))
            lines.append(
                "| {system} | {automation} | {cases} | {passrate} | {mean} | {med} | {p90} | {app} | "
                "{prec} | {rec} | {loc} | {p50} | {lat} | {lclass} | {cost} |".format(
                    system=run.get("system", "?"),
                    automation=run.get("automation", "-"),
                    cases=_tries(summary),
                    passrate=f"{passes}/{cases}",
                    mean=_pct(_frac(summary.get("meanAbsCountErrorPct"))),
                    med=_pct(_frac(summary.get("medianAbsCountErrorPct"))),
                    p90=_pct(_frac(summary.get("p90AbsCountErrorPct"))),
                    app=_pct(summary.get("appValidRate")),
                    prec=_pct(summary.get("meanPrecision")),
                    rec=_pct(summary.get("meanRecall")),
                    loc=_num(summary.get("medianLocationErrorM"), suffix=" m") if summary.get("medianLocationErrorM") is not None else "-",
                    p50=_ms(summary.get("p50LatencyMs")),
                    lat=_ms(summary.get("p95LatencyMs")),
                    lclass=summary.get("latencyClass", "unknown"),
                    cost=_usd(summary.get("meanCostUsd")),
                )
            )
        lines.append("")
        lines.extend(_notes(stall_runs, "stall_count"))

    if frontier:
        lines.append("## Frontiers")
        lines.append("")
        lines.append(
            "A system is on a frontier when no other system is at least as accurate and cheaper "
            "(or faster). Accuracy is mean IoU for paved-area takeoff (invalid polygons score 0) "
            "and 1 - mean absolute count error for stall counting."
        )
        lines.append("")
        for chart, systems in frontier.items():
            lines.append(f"![{chart}]({chart})")
            lines.append("")
            lines.append("Frontier: " + " → ".join(systems))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _frac(pct: float | None) -> float | None:
    return None if pct is None else pct / 100.0


def write_leaderboard(
    runs_path: str | Path, out_path: str | Path, charts: bool = True, judged: list[str | Path] | None = None
) -> None:
    runs = load_runs(runs_path)
    out = Path(out_path)
    frontier = write_frontier_charts(runs, out.parent) if charts else None
    text = render_leaderboard(runs, frontier)
    if judged:
        # Composite needs every job, so it exists only when a judged stripe file is given.
        from .composite import render_composite_section
        from .frontier import FrontierPoint, pareto_front, render_frontier_svg
        from .html_report import report_data

        rows = report_data(runs_path, judged)["tasks"]["composite"]
        chart, front = None, None
        points = [FrontierPoint(r["system"], r["cost"], r["accuracy"]) for r in rows if r["cost"] and not r["excluded"]]
        if charts and len(points) >= 2:
            chart = "frontier-composite-cost.svg"
            (out.parent / chart).write_text(
                render_frontier_svg(points, "Cost per lot, all three jobs", "Composite score", "$", "Full takeoff: composite vs cost"), encoding="utf-8"
            )
            front = [p.system for p in pareto_front(points)]
        # Composite goes first: it is the headline table.
        head, _, rest = text.partition("## ")
        text = head + "\n".join(render_composite_section(rows, chart, front)) + "\n## " + rest
    for path in judged or []:
        text = text.rstrip() + "\n\n" + "\n".join(render_judged_section(load_judged(path), out.parent if charts else None)).rstrip() + "\n"
    out.write_text(text, encoding="utf-8")
