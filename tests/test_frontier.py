import json

from pavebench.cli import main
from pavebench.frontier import FrontierPoint, pareto_front, render_frontier_svg


def test_pareto_front_keeps_only_undominated_points():
    pts = [
        FrontierPoint("cheap-bad", 0.01, 0.4),
        FrontierPoint("mid-good", 0.05, 0.85),
        FrontierPoint("mid-worse", 0.06, 0.80),
        FrontierPoint("dear-best", 0.5, 0.9),
        FrontierPoint("dear-worse", 0.4, 0.7),
    ]
    assert [p.system for p in pareto_front(pts)] == ["cheap-bad", "mid-good", "dear-best"]


def test_frontier_svg_lists_every_system():
    svg = render_frontier_svg(
        [FrontierPoint("A", 0.01, 0.5), FrontierPoint("B", 0.2, 0.9)], "Cost", "IoU", "$", "Test chart"
    )
    assert svg.startswith("<svg") and "Test chart" in svg and "1. B" in svg and "2. A" in svg


def _case(tmp_path, case_id, task):
    d = tmp_path / "cases" / case_id
    d.mkdir(parents=True)
    meta = {
        "caseId": case_id,
        "split": "test",
        "imageSize": {"width": 100, "height": 100},
        "resolutionMetersPerPixel": 0.1,
        "labelSource": {"role": "gold", "reviewStatus": "reviewed_gold"},
        "gold": {"boundary": [[10, 10], [90, 10], [90, 90], [10, 90]], "cutouts": []},
        "clicks": [{"id": "main", "x": 50, "y": 50}],
    }
    if task == "stall_count":
        meta["stallGold"] = {"count": 40, "markers": []}
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return json.dumps({"caseId": case_id, "split": "test", "tasks": [task], "metadataPath": f"cases/{case_id}/metadata.json"})


def test_score_runs_scopes_tasks_and_renders_frontier(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(_case(tmp_path, "area1", "click_connected_polygon") + "\n" + _case(tmp_path, "lot1", "stall_count") + "\n")
    preds = tmp_path / "predictions"
    preds.mkdir()
    good = {"caseId": "area1", "task": "click_connected_polygon", "track": "vlm_polygon", "boundary": [[10, 10], [90, 10], [90, 90], [10, 90]], "cutouts": [], "latencyMs": 2000, "costUsd": 0.5, "metadata": {"appValid": True}}
    bowtie = {**good, "boundary": [[10, 10], [90, 90], [90, 10], [10, 90]], "costUsd": 0.01, "metadata": {"appValid": False}}
    stall = {"caseId": "lot1", "task": "stall_count", "track": "vlm_polygon", "count": 42, "latencyMs": 1000, "costUsd": 0.02}
    (preds / "a.jsonl").write_text(json.dumps(good) + "\n" + json.dumps(stall) + "\n")
    (preds / "b.jsonl").write_text(json.dumps(bowtie) + "\n")
    runs = tmp_path / "runs.jsonl"
    runs.write_text(
        json.dumps({"system": "A", "track": "vlm_polygon", "automation": "full_auto", "predictionsPath": "predictions/a.jsonl", "scorePath": "scores/a.json"}) + "\n"
        + json.dumps({"system": "B", "track": "vlm_polygon", "automation": "full_auto", "tasks": ["click_connected_polygon"], "predictionsPath": "predictions/b.jsonl", "scorePath": "scores/b.json", "notes": "area only"}) + "\n"
    )
    out = tmp_path / "leaderboard.md"
    assert main(["score-runs", "--manifest", str(manifest), "--runs", str(runs), "--out", str(out)]) == 0
    b = json.loads((tmp_path / "scores" / "b.json").read_text())
    assert b["summary"]["invalidPolygons"] == 1 and "stallSummary" not in b
    a = json.loads((tmp_path / "scores" / "a.json").read_text())
    assert a["summary"]["appValidRate"] == 1.0 and a["stallSummary"]["passes"] == 1
    text = out.read_text()
    assert "## Frontiers" in text and "frontier-area-cost.svg" in text and "**B**: area only" in text
    assert (tmp_path / "frontier-area-cost.svg").exists()


def test_judged_section_renders_with_calibration(tmp_path):
    from pavebench.judged import render_judged_section

    data = {
        "task": "stripe_lines",
        "judge": "claude-opus-5-5",
        "reference": "Ref",
        "calibration": {"referenceSelfWinRate": 0.5, "orderAgreement": 0.75, "pairs": 8},
        "systems": [
            {"system": "Ref", "lots": 2, "comparisons": 8, "winRateVsReference": 0.5, "meanUsability": 8.0, "faults": {}, "meanCostUsd": 0.5, "p50LatencyMs": 90000},
            {"system": "Cheap", "lots": 2, "comparisons": 8, "winRateVsReference": 0.25, "meanUsability": 6.5, "faults": {"hatchingOutlineOrMissingRate": 0.5}, "meanCostUsd": 0.05, "p50LatencyMs": 30000},
        ],
    }
    text = "\n".join(render_judged_section(data, tmp_path))
    assert "judged by claude-opus-5-5, no gold" in text and "Calibration" in text and "| Ref |" in text
    assert (tmp_path / "frontier-stripe_lines-cost.svg").exists()


def test_report_html_embeds_data(tmp_path):
    test_score_runs_scopes_tasks_and_renders_frontier(tmp_path)
    out = tmp_path / "report.html"
    assert main(["report-html", "--runs", str(tmp_path / "runs.jsonl"), "--out", str(out), "--title", "T", "--subtitle", "S"]) == 0
    html = out.read_text()
    assert "<title>T</title>" in html and '"system": "A"' in html and "__DATA__" not in html
