from __future__ import annotations

from .geometry import Point
from .schemas import Case, StallCountPrediction, StallEvalResult, gsd_tier

# A stall count passes when it lands within this fraction of the gold count.
STALL_PASS_COUNT_PCT = 0.10


def stall_centroid(stall) -> Point:
    """Centroid of a predicted stall (a point [x, y] or an oriented-box ring)."""

    if not stall:
        raise ValueError("empty stall geometry")
    first = stall[0]
    if isinstance(first, (int, float)):
        return (float(stall[0]), float(stall[1]))
    xs = [float(vertex[0]) for vertex in stall]
    ys = [float(vertex[1]) for vertex in stall]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _distance(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def match_stalls(
    predicted: list[Point],
    markers: list[Point],
    radius_px: float,
) -> list[tuple[int, int, float]]:
    """Greedy one-to-one nearest matching within ``radius_px``.

    Returns matched (pred_index, marker_index, distance_px) triples. Each
    predicted stall and each gold marker is used at most once, closest first.
    """

    candidates: list[tuple[float, int, int]] = []
    for pred_index, pred_point in enumerate(predicted):
        for marker_index, marker_point in enumerate(markers):
            distance = _distance(pred_point, marker_point)
            if distance <= radius_px:
                candidates.append((distance, pred_index, marker_index))
    candidates.sort()
    used_pred: set[int] = set()
    used_marker: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for distance, pred_index, marker_index in candidates:
        if pred_index in used_pred or marker_index in used_marker:
            continue
        used_pred.add(pred_index)
        used_marker.add(marker_index)
        matches.append((pred_index, marker_index, distance))
    return matches


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def evaluate_stall_prediction(case: Case, prediction: StallCountPrediction) -> StallEvalResult:
    gt_count = case.gt_stall_count
    pred_count = int(prediction.count)

    count_error_pct: float | None = None
    abs_count_error_pct: float | None = None
    passed = False
    if gt_count is not None and gt_count > 0:
        count_error_pct = (pred_count - gt_count) / gt_count * 100.0
        abs_count_error_pct = abs(count_error_pct)
        passed = abs_count_error_pct <= STALL_PASS_COUNT_PCT * 100.0

    context = {
        "gsd_meters": case.gsd_for_tier(),
        "gsd_tier": gsd_tier(case.gsd_for_tier()),
        "split": case.split,
        "latency_ms": prediction.latency_ms,
        "cost_usd": prediction.cost_usd,
        "app_valid": prediction.metadata.get("appValid"),
    }

    markers = case.gt_stall_markers
    has_markers = bool(markers) and bool(prediction.stalls)
    precision = recall = f1 = median_location_error_m = None

    if has_markers:
        meters_per_pixel = case.meters_per_pixel
        if not meters_per_pixel:
            # No resolution -> cannot convert the 2.7 m radius to pixels.
            return StallEvalResult(
                case_id=case.case_id,
                task=prediction.task,
                track=prediction.track,
                gt_count=gt_count,
                pred_count=pred_count,
                count_error_pct=count_error_pct,
                abs_count_error_pct=abs_count_error_pct,
                has_markers=False,
                matched=0,
                precision=None,
                recall=None,
                f1=None,
                median_location_error_m=None,
                passed=passed,
                error="no_resolution_for_location_metrics",
                **context,
            )
        radius_px = case.stall_match_radius_m / meters_per_pixel
        predicted_points = [stall_centroid(stall) for stall in prediction.stalls]
        matches = match_stalls(predicted_points, markers, radius_px)
        matched = len(matches)
        precision = matched / len(predicted_points) if predicted_points else 0.0
        recall = matched / len(markers) if markers else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        location_errors_m = [distance * meters_per_pixel for _, _, distance in matches]
        median_location_error_m = _median(location_errors_m) if location_errors_m else None
    else:
        matched = 0

    return StallEvalResult(
        case_id=case.case_id,
        task=prediction.task,
        track=prediction.track,
        gt_count=gt_count,
        pred_count=pred_count,
        count_error_pct=count_error_pct,
        abs_count_error_pct=abs_count_error_pct,
        has_markers=has_markers,
        matched=matched,
        precision=precision,
        recall=recall,
        f1=f1,
        median_location_error_m=median_location_error_m,
        passed=passed,
        error=None if gt_count is not None else "no_gold_count",
        **context,
    )


def missing_stall_result(case: Case, task: str) -> StallEvalResult:
    return StallEvalResult(
        case_id=case.case_id,
        task=task,
        track="missing",
        gt_count=case.gt_stall_count,
        pred_count=0,
        count_error_pct=-100.0 if case.gt_stall_count else None,
        abs_count_error_pct=100.0 if case.gt_stall_count else None,
        has_markers=False,
        matched=0,
        precision=None,
        recall=None,
        f1=None,
        median_location_error_m=None,
        passed=False,
        error="missing_prediction",
        gsd_meters=case.gsd_for_tier(),
        gsd_tier=gsd_tier(case.gsd_for_tier()),
        split=case.split,
    )
