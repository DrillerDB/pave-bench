"""Self-contained HTML leaderboard: frontier charts (cost or speed axis) and tables.

    python3 -m pavebench.cli report-html --runs runs.jsonl [--judged judged.json] \
        --title "PaveBench" --subtitle "..." --out leaderboard.html

Reads the same runs manifest and score reports as `leaderboard`. The page embeds its
data as JSON and draws the charts in the browser, so it has no external dependencies
beyond Google Fonts (with system fallbacks).
"""

from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

from .judged import load_judged
from .leaderboard import load_runs


def _area_row(run: dict[str, Any]) -> dict[str, Any] | None:
    s = run["_report"].get("summary") or {}
    if not s.get("cases"):
        return None
    cases = int(s["cases"])
    bad = sum(int(s.get(k, 0)) for k in ("invalidPolygons", "emptyPredictions", "missingPredictions"))
    return {
        "accuracy": float(s.get("meanIou", 0.0)),
        "passRate": int(s.get("passes", 0)) / cases,
        "attempts": cases,
        "lots": s.get("distinctCases") or cases,
        "valid": (cases - bad) / cases,
        "appValid": s.get("appValidRate"),
        "medianAreaDelta": s.get("medianAreaDeltaPct"),
        "p90AreaDelta": s.get("p90AreaDeltaPct"),
        "cutoutRecovery": s.get("meanCutoutRecovery"),
        "p50": s.get("p50LatencyMs"),
        "p95": s.get("p95LatencyMs"),
        "cost": s.get("meanCostUsd"),
    }


def _stall_row(run: dict[str, Any]) -> dict[str, Any] | None:
    s = run["_report"].get("stallSummary") or {}
    if not s.get("cases") or s.get("meanAbsCountErrorPct") is None:
        return None
    cases = int(s["cases"])
    return {
        "accuracy": max(0.0, 1 - float(s["meanAbsCountErrorPct"]) / 100),
        "passRate": int(s.get("passes", 0)) / cases,
        "attempts": cases,
        "lots": s.get("distinctCases") or cases,
        "meanErr": float(s["meanAbsCountErrorPct"]) / 100,
        "medianErr": (s.get("medianAbsCountErrorPct") or 0) / 100,
        "p90Err": (s.get("p90AbsCountErrorPct") or 0) / 100,
        "appValid": s.get("appValidRate"),
        "p50": s.get("p50LatencyMs"),
        "p95": s.get("p95LatencyMs"),
        "cost": s.get("meanCostUsd"),
    }


def report_data(runs_path: str | Path, judged_paths: list[str | Path] | None = None) -> dict[str, Any]:
    runs = load_runs(runs_path)
    tasks: dict[str, list[dict[str, Any]]] = {"area": [], "stall": []}
    for run in runs:
        base = {
            "system": run.get("system", "?"),
            "provider": run.get("provider") or "Other",
            "notes": run.get("notes") or "",
            "frontierExclude": run.get("frontierExclude") or [],
            "frontierNote": run.get("frontierNote") or "",
        }
        area = _area_row(run)
        if area:
            tasks["area"].append({**base, **area, "excluded": "click_connected_polygon" in base["frontierExclude"]})
        stall = _stall_row(run)
        if stall:
            tasks["stall"].append({**base, **stall, "excluded": "stall_count" in base["frontierExclude"]})
    judged = [load_judged(p) for p in judged_paths or []]
    providers = {r["system"]: r.get("provider") or "Other" for r in runs}
    for j in judged:
        for s in j.get("systems", []):
            s["provider"] = providers.get(s["system"], "Other")
    return {"tasks": tasks, "judged": judged}


def render_html(data: dict[str, Any], title: str, subtitle: str, updated: str | None = None) -> str:
    template = (Path(__file__).parent / "report_template.html").read_text(encoding="utf-8")
    return (
        template.replace("__TITLE__", escape(title))
        .replace("__SUBTITLE__", escape(subtitle))
        .replace("__UPDATED__", escape(updated or date.today().isoformat()))
        .replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    )


def write_html_report(
    runs_path: str | Path, out_path: str | Path, title: str, subtitle: str, judged: list[str | Path] | None = None
) -> None:
    Path(out_path).write_text(render_html(report_data(runs_path, judged), title, subtitle), encoding="utf-8")


def publish_results(
    manifest_path: str | Path,
    runs_path: str | Path,
    out_dir: str | Path,
    judged: list[str | Path] | None = None,
    set_name: str = "",
    set_description: str = "",
) -> dict[str, Any]:
    """Write the public results bundle: leaderboard.md, frontier SVGs and leaderboard.json.

    The JSON carries scores, cost and latency per system plus a description of the
    case set. It never carries imagery or gold geometry, so results from a private
    test split can be published without redistributing the cases.
    """

    from .leaderboard import write_leaderboard
    from .manifest import load_manifest

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_leaderboard(runs_path, out / "leaderboard.md", judged=judged)
    data = report_data(runs_path, judged)
    rows = load_manifest(manifest_path)
    gsd = [r.case.gsd_for_tier() for r in rows if r.case.gsd_for_tier()]
    tasks: dict[str, int] = {}
    for r in rows:
        for t in r.tasks:
            tasks[t] = tasks.get(t, 0) + 1
    judged_lots = max((s.get("lots") or 0 for j in data["judged"] for s in j.get("systems", [])), default=0)
    if judged_lots:
        tasks["stripe_lines"] = judged_lots
    systems = {r["system"] for rows_ in data["tasks"].values() for r in rows_} | {
        s["system"] for j in data["judged"] for s in j.get("systems", [])
    }
    data["meta"] = {
        "updated": date.today().isoformat(),
        "setName": set_name,
        "setDescription": set_description,
        "cases": len(rows),
        "casesByTask": tasks,
        "gsdRangeCm": [round(min(gsd) * 100, 1), round(max(gsd) * 100, 1)] if gsd else None,
        "systems": len(systems),
        "providers": sorted({r["provider"] for rows_ in data["tasks"].values() for r in rows_}),
    }
    (out / "leaderboard.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return data
