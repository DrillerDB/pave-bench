from __future__ import annotations

from collections import defaultdict
from typing import Any

# Latency classes for the leaderboard. The INSTANT class is the load-bearing
# claim for "instant AI takeoff": p95 wall-clock at or under 10 seconds.
LATENCY_INSTANT_MS = 10_000
LATENCY_FAST_MS = 60_000


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 10) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 10)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 10)


def _percentile_nearest_rank(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = max(1, round((percentile / 100) * len(sorted_values)))
    return sorted_values[min(len(sorted_values) - 1, rank - 1)]


def latency_class(p95_ms: float | None) -> str:
    if p95_ms is None:
        return "unknown"
    if p95_ms <= LATENCY_INSTANT_MS:
        return "INSTANT"
    if p95_ms <= LATENCY_FAST_MS:
        return "FAST"
    return "BATCH"


def _app_valid(results: list[dict[str, Any]]) -> dict[str, Any]:
    flags = [bool(r["app_valid"]) for r in results if r.get("app_valid") is not None]
    return {"appValidCases": len(flags), "appValidRate": round(sum(flags) / len(flags), 6) if flags else None}


def _latency_cost(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(r["latency_ms"]) for r in results if r.get("latency_ms") is not None]
    costs = [float(r["cost_usd"]) for r in results if r.get("cost_usd") is not None]
    p95 = _percentile_nearest_rank(latencies, 95) if latencies else None
    return {
        "latencyCases": len(latencies),
        "p50LatencyMs": _median(latencies) if latencies else None,
        "p95LatencyMs": p95,
        "latencyClass": latency_class(p95),
        "costCases": len(costs),
        "meanCostUsd": round(_mean(costs), 6) if costs else None,
        "totalCostUsd": round(sum(costs), 6) if costs else None,
    }


def _summarize_group(results: list[dict[str, Any]]) -> dict[str, Any]:
    area_deltas = [float(result["area_delta_pct"]) for result in results]
    sqft_deltas = [
        abs(float(result["pred_sqft"]) - float(result["gt_sqft"]))
        for result in results
        if result.get("gt_sqft") is not None and result.get("pred_sqft") is not None
    ]
    recoveries = [
        float(result["cutout_recovery"])
        for result in results
        if result.get("cutout_recovery") is not None and int(result.get("cutout_expected", 0)) > 0
    ]
    summary = {
        "cases": len(results),
        "passes": sum(1 for result in results if result["passed"]),
        "missingPredictions": sum(1 for result in results if result.get("error") == "missing_prediction"),
        "emptyPredictions": sum(1 for result in results if result.get("error") == "empty_prediction"),
        "invalidPolygons": sum(1 for result in results if str(result.get("error") or "").startswith("invalid_polygon")),
        "meanIou": _mean([float(result["iou"]) for result in results]),
        "meanAreaDeltaPct": _mean(area_deltas),
        "medianAreaDeltaPct": _median(area_deltas),
        "p90AreaDeltaPct": _percentile_nearest_rank(area_deltas, 90),
        "medianSqftDelta": _median(sqft_deltas) if sqft_deltas else None,
        "p90SqftDelta": _percentile_nearest_rank(sqft_deltas, 90) if sqft_deltas else None,
        "meanCutoutRecovery": _mean(recoveries) if recoveries else None,
        "cutoutCasesScored": len(recoveries),
    }
    summary.update(_latency_cost(results))
    summary.update(_app_valid(results))
    summary["distinctCases"] = len({str(r.get("case_id")) for r in results})
    return summary


def _group_by(results: list[dict[str, Any]], key: str, default: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        groups[str(result.get(key, default))].append(result)
    return groups


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summarize_group(results)
    summary["byTrack"] = {
        track: _summarize_group(rows)
        for track, rows in sorted(_group_by(results, "track", "unknown").items())
    }
    summary["byGsdTier"] = {
        tier: _summarize_group(rows)
        for tier, rows in sorted(_group_by(results, "gsd_tier", "unknown").items())
    }
    summary["bySplit"] = {
        split: _summarize_group(rows)
        for split, rows in sorted(_group_by(results, "split", "unspecified").items())
    }
    return summary


def _summarize_stall_group(results: list[dict[str, Any]]) -> dict[str, Any]:
    abs_errors = [
        float(result["abs_count_error_pct"])
        for result in results
        if result.get("abs_count_error_pct") is not None
    ]
    location_errors = [
        float(result["median_location_error_m"])
        for result in results
        if result.get("median_location_error_m") is not None
    ]
    precisions = [float(r["precision"]) for r in results if r.get("precision") is not None]
    recalls = [float(r["recall"]) for r in results if r.get("recall") is not None]
    f1s = [float(r["f1"]) for r in results if r.get("f1") is not None]
    summary = {
        "cases": len(results),
        "passes": sum(1 for result in results if result["passed"]),
        "missingPredictions": sum(1 for result in results if result.get("error") == "missing_prediction"),
        "scoredCount": len(abs_errors),
        "meanAbsCountErrorPct": _mean(abs_errors) if abs_errors else None,
        "medianAbsCountErrorPct": _median(abs_errors) if abs_errors else None,
        "p90AbsCountErrorPct": _percentile_nearest_rank(abs_errors, 90) if abs_errors else None,
        "casesWithMarkers": len(precisions),
        "meanPrecision": _mean(precisions) if precisions else None,
        "meanRecall": _mean(recalls) if recalls else None,
        "meanF1": _mean(f1s) if f1s else None,
        "medianLocationErrorM": _median(location_errors) if location_errors else None,
    }
    summary.update(_latency_cost(results))
    summary.update(_app_valid(results))
    summary["distinctCases"] = len({str(r.get("case_id")) for r in results})
    return summary


def summarize_stall_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summarize_stall_group(results)
    summary["byGsdTier"] = {
        tier: _summarize_stall_group(rows)
        for tier, rows in sorted(_group_by(results, "gsd_tier", "unknown").items())
    }
    summary["bySplit"] = {
        split: _summarize_stall_group(rows)
        for split, rows in sorted(_group_by(results, "split", "unspecified").items())
    }
    return summary
