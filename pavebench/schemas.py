from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .geometry import Point

Track = Literal[
    "pure_segmentation",
    "vlm_polygon",
    "image_generation_mask",
    "hybrid_production",
]

# GSD (ground sample distance) tiers. Method rankings flip across these tiers
# (research exp-C/E), so every scoring report segments results by tier.
GSD_TIER_FINE = "<=8cm"
GSD_TIER_MID = "8-15cm"
GSD_TIER_COARSE = ">15cm"
GSD_TIER_UNKNOWN = "unknown"


def gsd_tier(meters_per_pixel: float | None) -> str:
    """Bucket a native ground-sample-distance into the benchmark's tiers."""

    if meters_per_pixel is None:
        return GSD_TIER_UNKNOWN
    if meters_per_pixel <= 0.08:
        return GSD_TIER_FINE
    if meters_per_pixel <= 0.15:
        return GSD_TIER_MID
    return GSD_TIER_COARSE


@dataclass(frozen=True)
class Click:
    click_id: str
    x: float
    y: float


@dataclass(frozen=True)
class Case:
    case_id: str
    image_width: int
    image_height: int
    gt_boundary: list[Point]
    gt_cutouts: list[list[Point]] = field(default_factory=list)
    clicks: list[Click] = field(default_factory=list)
    label_source: dict[str, Any] = field(default_factory=dict)
    meters_per_pixel: float | None = None
    # Native resolution of the case imagery, used for GSD-tier segmentation.
    # Falls back to meters_per_pixel when imagery does not declare its own.
    native_meters_per_pixel: float | None = None
    imagery: dict[str, Any] = field(default_factory=dict)
    split: str = "unspecified"
    # Optional stall-count gold. gt_stall_markers are pixel-space stall centers.
    gt_stall_count: int | None = None
    gt_stall_markers: list[Point] = field(default_factory=list)
    stall_match_radius_m: float = 2.7

    def gsd_for_tier(self) -> float | None:
        """The resolution used to bucket this case into a GSD tier.

        Prefers the imagery's honest native GSD over an upsampled export GSD, so
        a lot exported at 6 cm/px from 15 cm/px imagery is tiered as coarse.
        """

        return self.native_meters_per_pixel or self.meters_per_pixel


@dataclass(frozen=True)
class PolygonPrediction:
    case_id: str
    task: str
    track: Track
    boundary: list[Point]
    cutouts: list[list[Point]] = field(default_factory=list)
    latency_ms: int | None = None
    cost_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MaskPrediction:
    case_id: str
    task: str
    track: Track
    mask: list[list[int]]
    latency_ms: int | None = None
    cost_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# A predicted stall is either a point [x, y] or an oriented box ring
# [[x, y], [x, y], ...]. Both reduce to a centroid for marker matching.
StallGeometry = list  # list[float] point, or list[list[float]] ring


@dataclass(frozen=True)
class StallCountPrediction:
    case_id: str
    task: str
    track: Track
    count: int
    stalls: list[StallGeometry] = field(default_factory=list)
    latency_ms: int | None = None
    cost_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    task: str
    track: str
    iou: float
    gt_area_px: float
    pred_area_px: float
    gt_sqft: float | None
    pred_sqft: float | None
    area_delta_pct: float
    gt_cutout_count: int
    pred_cutout_count: int
    cutout_score: float
    target_click_contained: bool
    passed: bool
    error: str | None = None
    # Cutout recovery: area-weighted fraction of gold cutouts recovered, plus the
    # raw found/expected counts (research: island detection is the weakest link).
    cutout_recovery: float | None = None
    cutout_found: int = 0
    cutout_expected: int = 0
    # First-class latency/cost/GSD/split context carried into aggregation.
    latency_ms: int | None = None
    cost_usd: float | None = None
    gsd_meters: float | None = None
    gsd_tier: str = GSD_TIER_UNKNOWN
    split: str = "unspecified"
    # Optional: whether the submitting application's own validator accepted this
    # draft (metadata.appValid). Reported beside benchmark validity, never scored.
    app_valid: bool | None = None


@dataclass(frozen=True)
class StallEvalResult:
    case_id: str
    task: str
    track: str
    gt_count: int | None
    pred_count: int
    count_error_pct: float | None
    abs_count_error_pct: float | None
    has_markers: bool
    matched: int
    precision: float | None
    recall: float | None
    f1: float | None
    median_location_error_m: float | None
    passed: bool
    error: str | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None
    gsd_meters: float | None = None
    gsd_tier: str = GSD_TIER_UNKNOWN
    split: str = "unspecified"
    # Optional: whether the submitting application's own validator accepted this
    # draft (metadata.appValid). Reported beside benchmark validity, never scored.
    app_valid: bool | None = None


def _points(raw_points: list[list[float]]) -> list[Point]:
    return [(float(point[0]), float(point[1])) for point in raw_points]


def load_case_from_metadata(path: str | Path) -> Case:
    metadata_path = Path(path)
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    image_size = data["imageSize"]
    gold = data.get("gold") or data.get("guide")
    if not gold:
        raise ValueError(f"Case {data.get('caseId', metadata_path)} has no gold or guide geometry")
    source = data.get("source", {})
    imagery = dict(data.get("imagery", {}))
    # Effective (export) resolution used to convert pixel area -> square feet.
    meters_per_pixel = (
        data.get("resolutionMetersPerPixel")
        or imagery.get("exportGsdMeters")
        or imagery.get("gsdMeters")
        or source.get("resolutionMetersPerPixel")
    )
    # Honest native resolution used for GSD-tier bucketing.
    native_mpp = imagery.get("nativeGsdMeters") or meters_per_pixel
    clicks = [
        Click(click_id=str(click["id"]), x=float(click["x"]), y=float(click["y"]))
        for click in data.get("clicks", [])
    ]

    stall_gold = data.get("stallGold") or {}
    gt_stall_count = stall_gold.get("count")
    gt_stall_markers = [
        (float(marker[0]), float(marker[1])) for marker in stall_gold.get("markers", [])
    ]

    return Case(
        case_id=str(data["caseId"]),
        image_width=int(image_size["width"]),
        image_height=int(image_size["height"]),
        gt_boundary=_points(gold["boundary"]),
        gt_cutouts=[_points(cutout) for cutout in gold.get("cutouts", [])],
        clicks=clicks,
        label_source=dict(data.get("labelSource", {})),
        meters_per_pixel=float(meters_per_pixel) if meters_per_pixel is not None else None,
        native_meters_per_pixel=float(native_mpp) if native_mpp is not None else None,
        imagery=imagery,
        split=str(data.get("split", "unspecified")),
        gt_stall_count=int(gt_stall_count) if gt_stall_count is not None else None,
        gt_stall_markers=gt_stall_markers,
        stall_match_radius_m=float(stall_gold.get("matchRadiusMeters", 2.7)),
    )


def needs_gold_review(case: Case) -> bool:
    role = str(case.label_source.get("role", "")).lower()
    review_status = str(case.label_source.get("reviewStatus", "")).lower()
    return role == "guide" or review_status in {"needs_gold_review", "rejected"}


def require_scoreable_case(case: Case, allow_guide: bool = False) -> None:
    if needs_gold_review(case) and not allow_guide:
        raise ValueError(
            f"Case {case.case_id} needs gold review; pass --allow-guide only for dry-run guide scoring."
        )
