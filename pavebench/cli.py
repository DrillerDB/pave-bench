from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from .baselines.empty import write_empty_predictions
from .baselines.oracle import write_oracle_predictions
from .eval import evaluate_mask_prediction, evaluate_polygon_prediction, missing_prediction_result
from .importers.human_trace import create_case_from_trace
from .importers.propaving_fixture import create_case_from_propaving
from .leaderboard import write_leaderboard
from .manifest import load_manifest
from .reporting import summarize_results, summarize_stall_results
from .schemas import (
    MaskPrediction,
    PolygonPrediction,
    StallCountPrediction,
    load_case_from_metadata,
    require_scoreable_case,
)
from .stalls import evaluate_stall_prediction, missing_stall_result

STALL_TASK = "stall_count"


def _points(raw_points: list[list[float]]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in raw_points]


def _read_mask(path: Path) -> list[list[int]]:
    image = Image.open(path).convert("L")
    width, height = image.size
    pixels = list(image.tobytes())
    return [
        [1 if pixels[y * width + x] >= 128 else 0 for x in range(width)]
        for y in range(height)
    ]


def _prediction_from_json(
    data: dict, base_dir: Path | None = None
) -> PolygonPrediction | MaskPrediction | StallCountPrediction:
    if data.get("task") == STALL_TASK or "count" in data:
        return StallCountPrediction(
            case_id=str(data["caseId"]),
            task=str(data.get("task", STALL_TASK)),
            track=data["track"],
            count=int(data["count"]),
            stalls=[list(stall) for stall in data.get("stalls", [])],
            latency_ms=data.get("latencyMs"),
            cost_usd=data.get("costUsd"),
            metadata=dict(data.get("metadata", {})),
        )
    if "maskPath" in data:
        mask_path = Path(data["maskPath"])
        if not mask_path.is_absolute() and base_dir is not None:
            mask_path = base_dir / mask_path
        return MaskPrediction(
            case_id=str(data["caseId"]),
            task=str(data["task"]),
            track=data["track"],
            mask=_read_mask(mask_path),
            latency_ms=data.get("latencyMs"),
            cost_usd=data.get("costUsd"),
            metadata={**dict(data.get("metadata", {})), "maskPath": str(mask_path)},
        )
    return PolygonPrediction(
        case_id=str(data["caseId"]),
        task=str(data["task"]),
        track=data["track"],
        boundary=_points(data["boundary"]),
        cutouts=[_points(cutout) for cutout in data.get("cutouts", [])],
        latency_ms=data.get("latencyMs"),
        cost_usd=data.get("costUsd"),
        metadata=dict(data.get("metadata", {})),
    )


def _score(args: argparse.Namespace) -> int:
    case = load_case_from_metadata(args.case)
    require_scoreable_case(case, allow_guide=args.allow_guide)
    predictions = _read_predictions(args.predictions)
    area_results: list[dict] = []
    stall_results: list[dict] = []
    for prediction in predictions:
        if prediction.case_id != case.case_id:
            continue
        _dispatch(case, prediction, area_results, stall_results)

    report = _report(area_results, stall_results)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


def _read_predictions(path: str | Path) -> list[PolygonPrediction | MaskPrediction | StallCountPrediction]:
    predictions: list[PolygonPrediction | MaskPrediction | StallCountPrediction] = []
    predictions_path = Path(path)
    for line in predictions_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            predictions.append(_prediction_from_json(json.loads(line), predictions_path.parent))
    return predictions


def _dispatch(case, prediction, area_results: list[dict], stall_results: list[dict]) -> None:
    """Evaluate one prediction into the area or stall result bucket."""

    if isinstance(prediction, StallCountPrediction):
        stall_results.append(asdict(evaluate_stall_prediction(case, prediction)))
    elif isinstance(prediction, MaskPrediction):
        area_results.append(asdict(evaluate_mask_prediction(case, prediction)))
    else:
        area_results.append(asdict(evaluate_polygon_prediction(case, prediction)))


def _report(area_results: list[dict], stall_results: list[dict] | None = None) -> dict:
    report: dict = {
        "summary": summarize_results(area_results),
        "results": area_results,
    }
    if stall_results:
        report["stallSummary"] = summarize_stall_results(stall_results)
        report["stallResults"] = stall_results
    return report


def score_manifest_report(
    manifest: str | Path, predictions_path: str | Path, allow_guide: bool = False, tasks: list[str] | None = None
) -> dict:
    """Score every prediction (all tries) in a JSONL file against a manifest.

    `tasks` limits scoring to the tasks a system was submitted for, so a system that
    only attempted stall counting is not reported as missing every area case.
    """

    rows = load_manifest(manifest)
    predictions = _read_predictions(predictions_path)
    area_results: list[dict] = []
    stall_results: list[dict] = []
    for row in rows:
        require_scoreable_case(row.case, allow_guide=allow_guide)
        for task in row.tasks or ["click_connected_polygon"]:
            if tasks is not None and task not in tasks:
                continue
            task_predictions = [
                prediction
                for prediction in predictions
                if prediction.case_id == row.case_id and prediction.task == task
            ]
            if not task_predictions:
                if task == STALL_TASK:
                    stall_results.append(asdict(missing_stall_result(row.case, task)))
                else:
                    area_results.append(asdict(missing_prediction_result(row.case, task)))
                continue
            for prediction in task_predictions:
                _dispatch(row.case, prediction, area_results, stall_results)
    return _report(area_results, stall_results)


def _score_manifest(args: argparse.Namespace) -> int:
    report = score_manifest_report(args.manifest, args.predictions, allow_guide=args.allow_guide)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


def _score_runs(args: argparse.Namespace) -> int:
    """Score every run row that names a predictionsPath, then render the leaderboard."""

    runs_path = Path(args.runs)
    base = runs_path.parent
    for line in runs_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not row.get("predictionsPath"):
            continue
        predictions = Path(row["predictionsPath"])
        predictions = predictions if predictions.is_absolute() else base / predictions
        score_path = Path(row["scorePath"])
        score_path = score_path if score_path.is_absolute() else base / score_path
        report = score_manifest_report(args.manifest, predictions, allow_guide=args.allow_guide, tasks=row.get("tasks"))
        score_path.parent.mkdir(parents=True, exist_ok=True)
        score_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_leaderboard(runs_path, args.out, judged=args.judged)
    print(f"Wrote leaderboard to {args.out}")
    return 0


def _oracle(args: argparse.Namespace) -> int:
    write_oracle_predictions(args.manifest, args.out, allow_guide=args.allow_guide)
    return 0


def _empty(args: argparse.Namespace) -> int:
    write_empty_predictions(args.manifest, args.out, allow_guide=args.allow_guide)
    return 0


def _case_from_trace(args: argparse.Namespace) -> int:
    clicks = None
    if args.click:
        clicks = []
        for idx, raw in enumerate(args.click):
            x_str, _, y_str = raw.partition(",")
            clicks.append({"id": f"c{idx}" if idx else "main", "x": float(x_str), "y": float(y_str)})
    elif args.no_click:
        clicks = []
    create_case_from_trace(
        args.trace,
        args.out_dir,
        args.case_id,
        args.image_width,
        args.image_height,
        clicks=clicks,
        coordinate_space=args.coordinate_space,
    )
    return 0


def _case_from_propaving(args: argparse.Namespace) -> int:
    if args.imagery_config:
        imagery_source = json.loads(Path(args.imagery_config).read_text(encoding="utf-8"))
    else:
        imagery_source = {
            "name": args.imagery_name,
            "imageServer": args.image_server,
            "nativeGsdMeters": args.native_gsd,
            "vintage": args.vintage,
            "license": args.imagery_license,
            "redistributable": args.redistributable,
        }
    metadata = create_case_from_propaving(
        args.fixture,
        args.out_dir,
        args.case_id,
        imagery_source,
        export_gsd_meters=args.export_gsd,
        max_pixels=args.max_pixels,
        fetch=not args.no_fetch,
        split=args.split,
    )
    size = metadata["imageSize"]
    status = metadata["imagery"]["imageryStatus"]
    print(
        f"Wrote case {args.case_id} ({size['width']}x{size['height']} px, "
        f"{len(metadata['gold']['cutouts'])} cutouts, imagery={status}) to {args.out_dir}"
    )
    return 0


def _report_html(args: argparse.Namespace) -> int:
    from .html_report import write_html_report

    write_html_report(args.runs, args.out, args.title, args.subtitle, judged=args.judged)
    print(f"Wrote HTML report to {args.out}")
    return 0


def _publish(args: argparse.Namespace) -> int:
    from .html_report import publish_results

    publish_results(args.manifest, args.runs, args.out_dir, judged=args.judged, set_name=args.set_name, set_description=args.set_description)
    print(f"Wrote leaderboard.md, leaderboard.json and frontier charts to {args.out_dir}")
    return 0


def _leaderboard(args: argparse.Namespace) -> int:
    write_leaderboard(args.runs, args.out, judged=args.judged)
    print(f"Wrote leaderboard to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pavebench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    score = subparsers.add_parser("score", help="Score prediction JSONL against one case metadata file")
    score.add_argument("--allow-guide", action="store_true", help="Allow scoring cases that still need gold review")
    score.add_argument("--case", required=True, help="Path to case metadata.json")
    score.add_argument("--predictions", required=True, help="Path to prediction JSONL")
    score.add_argument("--out", required=True, help="Path to write JSON report")
    score.set_defaults(func=_score)

    score_manifest = subparsers.add_parser("score-manifest", help="Score prediction JSONL against a manifest")
    score_manifest.add_argument("--allow-guide", action="store_true", help="Allow scoring cases that still need gold review")
    score_manifest.add_argument("--manifest", required=True, help="Path to manifest JSONL")
    score_manifest.add_argument("--predictions", required=True, help="Path to prediction JSONL")
    score_manifest.add_argument("--out", required=True, help="Path to write JSON report")
    score_manifest.set_defaults(func=_score_manifest)

    oracle = subparsers.add_parser("oracle", help="Write oracle predictions from manifest gold geometry")
    oracle.add_argument("--allow-guide", action="store_true", help="Allow oracle output for cases that still need gold review")
    oracle.add_argument("--manifest", required=True, help="Path to manifest JSONL")
    oracle.add_argument("--out", required=True, help="Path to write prediction JSONL")
    oracle.set_defaults(func=_oracle)

    empty = subparsers.add_parser("empty", help="Write empty baseline predictions from a manifest")
    empty.add_argument("--allow-guide", action="store_true", help="Allow empty baseline output for cases that still need gold review")
    empty.add_argument("--manifest", required=True, help="Path to manifest JSONL")
    empty.add_argument("--out", required=True, help="Path to write prediction JSONL")
    empty.set_defaults(func=_empty)

    trace = subparsers.add_parser("case-from-trace", help="Create review-guide case files from a human trace GeoJSON")
    trace.add_argument("--trace", required=True, help="Path to human trace GeoJSON")
    trace.add_argument("--case-id", required=True, help="Case id for the generated benchmark case")
    trace.add_argument("--image-width", required=True, type=int, help="Benchmark image width in pixels")
    trace.add_argument("--image-height", required=True, type=int, help="Benchmark image height in pixels")
    trace.add_argument("--out-dir", required=True, help="Directory to write metadata.json and gold.geojson")
    trace.add_argument(
        "--click",
        action="append",
        metavar="X,Y",
        help="Click target as 'x,y' (repeatable). Omit to auto-derive one interior click; use --no-click to leave click-less.",
    )
    trace.add_argument("--no-click", action="store_true", help="Do not write any click target")
    trace.add_argument(
        "--coordinate-space",
        choices=["image_pixels", "geographic_wgs84"],
        help="Coordinate system of the trace geometry (recorded in metadata for the imagery step)",
    )
    trace.set_defaults(func=_case_from_trace)

    propaving = subparsers.add_parser(
        "case-from-propaving",
        help="Scaffold a case from a ProPaving gold fixture + redistributable imagery source",
    )
    propaving.add_argument("--fixture", required=True, help="Path to ProPaving gold fixture JSON")
    propaving.add_argument("--case-id", required=True, help="Case id for the generated case")
    propaving.add_argument("--out-dir", required=True, help="Directory to write the case files")
    propaving.add_argument("--imagery-config", help="JSON file describing the imagery source (overrides the flags below)")
    propaving.add_argument("--image-server", help="ArcGIS ImageServer base URL for a public-domain ortho")
    propaving.add_argument("--imagery-name", help="Human-readable imagery source name")
    propaving.add_argument("--native-gsd", type=float, help="Native imagery resolution in meters/pixel")
    propaving.add_argument("--vintage", help="Imagery capture year")
    propaving.add_argument("--imagery-license", default="public domain", help="Imagery license")
    propaving.add_argument("--redistributable", action="store_true", help="Assert the imagery is redistributable (required)")
    propaving.add_argument("--export-gsd", type=float, default=0.15, help="Target export resolution in meters/pixel")
    propaving.add_argument("--max-pixels", type=int, default=4000, help="Cap on the longest image edge")
    propaving.add_argument("--split", default="dev", help="Dataset split for the case (dev/test)")
    propaving.add_argument("--no-fetch", action="store_true", help="Skip fetching imagery; only scaffold geometry + metadata")
    propaving.set_defaults(func=_case_from_propaving)

    score_runs = subparsers.add_parser(
        "score-runs", help="Score every run in a runs manifest (rows with predictionsPath) and render the leaderboard"
    )
    score_runs.add_argument("--manifest", required=True)
    score_runs.add_argument("--runs", required=True)
    score_runs.add_argument("--out", required=True)
    score_runs.add_argument("--allow-guide", action="store_true")
    score_runs.add_argument("--judged", action="append", help="Judged-task results JSON (pavebench/judged.py); repeatable")
    score_runs.set_defaults(func=_score_runs)

    publish = subparsers.add_parser("publish", help="Write the public results bundle (markdown, JSON, frontier SVGs) from scored runs")
    publish.add_argument("--manifest", required=True)
    publish.add_argument("--runs", required=True)
    publish.add_argument("--out-dir", required=True)
    publish.add_argument("--judged", action="append")
    publish.add_argument("--set-name", default="")
    publish.add_argument("--set-description", default="")
    publish.set_defaults(func=_publish)

    report = subparsers.add_parser("report-html", help="Render a self-contained HTML leaderboard with frontier charts")
    report.add_argument("--runs", required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--title", default="PaveBench Leaderboard")
    report.add_argument("--subtitle", default="")
    report.add_argument("--judged", action="append")
    report.set_defaults(func=_report_html)

    leaderboard = subparsers.add_parser("leaderboard", help="Render the leaderboard markdown from a runs manifest")
    leaderboard.add_argument("--runs", required=True, help="Path to runs manifest JSONL (system/track/automation/scorePath)")
    leaderboard.add_argument("--out", required=True, help="Path to write the leaderboard markdown")
    leaderboard.add_argument("--judged", action="append", help="Judged-task results JSON; repeatable")
    leaderboard.set_defaults(func=_leaderboard)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
