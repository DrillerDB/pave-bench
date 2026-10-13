from __future__ import annotations

from .geometry import (
    covered_fraction,
    mask_image_iou,
    mask_to_image,
    point_in_polygon,
    polygon_area,
    polygon_validity_error,
    rasterize_polygon_image,
    ring_area,
)
from .schemas import Case, EvalResult, MaskPrediction, PolygonPrediction, gsd_tier

PASS_IOU = 0.86
PASS_AREA_DELTA = 0.08
PASS_CUTOUT_DELTA = 2
SQM_TO_SQFT = 10.76391041671
# A gold cutout counts as "found" when predicted holes cover at least this
# fraction of its area (robust to fragmentation and tracing noise).
CUTOUT_FOUND_FRACTION = 0.5


def _case_context(case: Case) -> dict:
    gsd = case.gsd_for_tier()
    return {"gsd_meters": gsd, "gsd_tier": gsd_tier(gsd), "split": case.split}


def _pred_context(prediction: PolygonPrediction | MaskPrediction) -> dict:
    return {
        "latency_ms": prediction.latency_ms,
        "cost_usd": prediction.cost_usd,
        "app_valid": prediction.metadata.get("appValid"),
    }


def cutout_recovery(gt_cutouts, pred_cutouts) -> tuple[int, int, float]:
    """Area-weighted recovery of gold cutouts by predicted holes.

    Returns (found, expected, area_weighted_recovery). With no gold cutouts the
    recovery is defined as 1.0 (nothing to miss).
    """

    expected = len(gt_cutouts)
    if expected == 0:
        return 0, 0, 1.0
    total_area = sum(ring_area(hole) for hole in gt_cutouts)
    found = 0
    recovered_area = 0.0
    for hole in gt_cutouts:
        if covered_fraction(hole, pred_cutouts) >= CUTOUT_FOUND_FRACTION:
            found += 1
            recovered_area += ring_area(hole)
    recovery = recovered_area / total_area if total_area > 0 else (found / expected)
    return found, expected, recovery


def mask_iou(truth: list[list[int]], pred: list[list[int]]) -> float:
    if len(truth) != len(pred) or any(len(t_row) != len(p_row) for t_row, p_row in zip(truth, pred)):
        raise ValueError("truth and pred masks must have matching dimensions")

    intersection = 0
    union = 0
    for truth_row, pred_row in zip(truth, pred):
        for truth_value, pred_value in zip(truth_row, pred_row):
            truth_on = bool(truth_value)
            pred_on = bool(pred_value)
            if truth_on and pred_on:
                intersection += 1
            if truth_on or pred_on:
                union += 1
    return 1.0 if union == 0 else intersection / union


def cutout_score(gt_count: int, pred_count: int) -> float:
    if gt_count == 0:
        return max(0.0, 1.0 - pred_count * 0.2)
    return max(0.0, 1.0 - min(1.0, abs(pred_count - gt_count) / gt_count))


def _valid_ring(points: list[tuple[float, float]]) -> bool:
    return len(points) >= 3


def _invalid_result(case: Case, prediction: PolygonPrediction, error: str) -> EvalResult:
    gt_area = polygon_area(case.gt_boundary, case.gt_cutouts)
    gt_sqft = pixel_area_to_sqft(gt_area, case)
    found, expected, recovery = cutout_recovery(case.gt_cutouts, [])
    return EvalResult(
        case_id=case.case_id,
        task=prediction.task,
        track=prediction.track,
        iou=0.0,
        gt_area_px=gt_area,
        pred_area_px=0.0,
        gt_sqft=gt_sqft,
        pred_sqft=0.0 if gt_sqft is not None else None,
        area_delta_pct=1.0,
        gt_cutout_count=len(case.gt_cutouts),
        pred_cutout_count=len(prediction.cutouts),
        cutout_score=0.0,
        cutout_recovery=recovery,
        cutout_found=found,
        cutout_expected=expected,
        target_click_contained=False,
        passed=False,
        error=error,
        **_case_context(case),
        **_pred_context(prediction),
    )


def pixel_area_to_sqft(area_px: float, case: Case) -> float | None:
    if case.meters_per_pixel is None:
        return None
    return area_px * (case.meters_per_pixel ** 2) * SQM_TO_SQFT


def evaluate_polygon_prediction(case: Case, prediction: PolygonPrediction) -> EvalResult:
    if len(prediction.boundary) == 0:
        return _invalid_result(case, prediction, "empty_prediction")
    if not _valid_ring(prediction.boundary) or any(not _valid_ring(cutout) for cutout in prediction.cutouts):
        return _invalid_result(case, prediction, "invalid_polygon")
    reason = polygon_validity_error(prediction.boundary, prediction.cutouts, case.image_width, case.image_height)
    if reason:
        return _invalid_result(case, prediction, f"invalid_polygon:{reason}")

    truth_mask = rasterize_polygon_image(case.gt_boundary, case.gt_cutouts, case.image_width, case.image_height)
    pred_mask = rasterize_polygon_image(prediction.boundary, prediction.cutouts, case.image_width, case.image_height)
    iou = mask_image_iou(truth_mask, pred_mask)

    gt_area = polygon_area(case.gt_boundary, case.gt_cutouts)
    pred_area = polygon_area(prediction.boundary, prediction.cutouts)
    gt_sqft = pixel_area_to_sqft(gt_area, case)
    pred_sqft = pixel_area_to_sqft(pred_area, case)
    area_delta = 0.0 if gt_area == 0 and pred_area == 0 else abs(pred_area - gt_area) / max(gt_area, 1e-12)

    target_click_contained = True
    if case.clicks:
        click = case.clicks[0]
        target_click_contained = point_in_polygon((click.x, click.y), prediction.boundary, prediction.cutouts)

    gt_cutouts = len(case.gt_cutouts)
    pred_cutouts = len(prediction.cutouts)
    cutouts_ok = abs(gt_cutouts - pred_cutouts) <= PASS_CUTOUT_DELTA
    passed = iou >= PASS_IOU and area_delta <= PASS_AREA_DELTA and cutouts_ok and target_click_contained
    found, expected, recovery = cutout_recovery(case.gt_cutouts, prediction.cutouts)

    return EvalResult(
        case_id=case.case_id,
        task=prediction.task,
        track=prediction.track,
        iou=iou,
        gt_area_px=gt_area,
        pred_area_px=pred_area,
        gt_sqft=gt_sqft,
        pred_sqft=pred_sqft,
        area_delta_pct=area_delta,
        gt_cutout_count=gt_cutouts,
        pred_cutout_count=pred_cutouts,
        cutout_score=cutout_score(gt_cutouts, pred_cutouts),
        cutout_recovery=recovery,
        cutout_found=found,
        cutout_expected=expected,
        target_click_contained=target_click_contained,
        passed=passed,
        **_case_context(case),
        **_pred_context(prediction),
    )


def _mask_target_contains_click(mask: list[list[int]], case: Case) -> bool:
    if not case.clicks:
        return True
    click = case.clicks[0]
    x = int(click.x)
    y = int(click.y)
    if y < 0 or y >= len(mask) or x < 0 or (mask and x >= len(mask[0])):
        return False
    return bool(mask[y][x])


def evaluate_mask_prediction(case: Case, prediction: MaskPrediction) -> EvalResult:
    if len(prediction.mask) != case.image_height or any(len(row) != case.image_width for row in prediction.mask):
        return EvalResult(
            case_id=case.case_id,
            task=prediction.task,
            track=prediction.track,
            iou=0.0,
            gt_area_px=polygon_area(case.gt_boundary, case.gt_cutouts),
            pred_area_px=0.0,
            gt_sqft=pixel_area_to_sqft(polygon_area(case.gt_boundary, case.gt_cutouts), case),
            pred_sqft=None,
            area_delta_pct=1.0,
            gt_cutout_count=len(case.gt_cutouts),
            pred_cutout_count=0,
            cutout_score=0.0,
            cutout_recovery=cutout_recovery(case.gt_cutouts, [])[2],
            cutout_found=0,
            cutout_expected=len(case.gt_cutouts),
            target_click_contained=False,
            passed=False,
            error="mask_size_mismatch",
            **_case_context(case),
            **_pred_context(prediction),
        )

    truth_image = rasterize_polygon_image(case.gt_boundary, case.gt_cutouts, case.image_width, case.image_height)
    pred_image = mask_to_image(prediction.mask, case.image_width, case.image_height)
    iou = mask_image_iou(truth_image, pred_image)
    gt_area = polygon_area(case.gt_boundary, case.gt_cutouts)
    pred_area = float(sum(1 for row in prediction.mask for value in row if value))
    area_delta = 0.0 if gt_area == 0 and pred_area == 0 else abs(pred_area - gt_area) / max(gt_area, 1e-12)
    target_click_contained = _mask_target_contains_click(prediction.mask, case)
    passed = iou >= PASS_IOU and area_delta <= PASS_AREA_DELTA and target_click_contained

    return EvalResult(
        case_id=case.case_id,
        task=prediction.task,
        track=prediction.track,
        iou=iou,
        gt_area_px=gt_area,
        pred_area_px=pred_area,
        gt_sqft=pixel_area_to_sqft(gt_area, case),
        pred_sqft=pixel_area_to_sqft(pred_area, case),
        area_delta_pct=area_delta,
        gt_cutout_count=len(case.gt_cutouts),
        pred_cutout_count=0,
        cutout_score=1.0 if len(case.gt_cutouts) == 0 else 0.0,
        cutout_recovery=1.0 if len(case.gt_cutouts) == 0 else 0.0,
        cutout_found=0,
        cutout_expected=len(case.gt_cutouts),
        target_click_contained=target_click_contained,
        passed=passed,
        **_case_context(case),
        **_pred_context(prediction),
    )


def missing_prediction_result(case: Case, task: str) -> EvalResult:
    gt_area = polygon_area(case.gt_boundary, case.gt_cutouts)
    gt_sqft = pixel_area_to_sqft(gt_area, case)
    found, expected, recovery = cutout_recovery(case.gt_cutouts, [])
    return EvalResult(
        case_id=case.case_id,
        task=task,
        track="missing",
        iou=0.0,
        gt_area_px=gt_area,
        pred_area_px=0.0,
        gt_sqft=gt_sqft,
        pred_sqft=0.0 if gt_sqft is not None else None,
        area_delta_pct=1.0,
        gt_cutout_count=len(case.gt_cutouts),
        pred_cutout_count=0,
        cutout_score=0.0,
        cutout_recovery=recovery,
        cutout_found=found,
        cutout_expected=expected,
        target_click_contained=False,
        passed=False,
        error="missing_prediction",
        **_case_context(case),
    )
