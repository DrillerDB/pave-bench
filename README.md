# PaveBench

PaveBench is a public benchmark harness for aerial pavement segmentation and pavement-to-polygon extraction.

The benchmark is built around a practical contractor workflow: given a top-down aerial image, return a valid paved-surface mask or polygon with interior cutouts for buildings, islands, grass, trees, and other non-paved holes.

## Tracks

- `pure_segmentation`: image segmentation models that output masks or polygons.
- `vlm_polygon`: vision-language models that directly emit JSON polygon coordinates.
- `image_generation_mask`: image-generation/editing models that paint a mask image.
- `hybrid_production`: production-style pipelines using declared aids such as clicks, user boxes, parcel vectors, image cleaning, ensembles, or post-processing.

The tracks are intentionally separate. Direct VLM polygon generation, true mask segmentation, and hybrid post-processed systems test different capabilities.

## Tasks

The three contractor jobs, and how each is scored today:

| Job | Task | Scored against |
|---|---|---|
| Full lot measurement | `click_connected_polygon` (or `semantic_mask`) | Gold outline and islands |
| Stall count | `stall_count` | Gold count; per-stall markers when the case ships them |
| Striping takeoff | `stripe_lines` | A model judge, until stripe gold exists ([docs/model-frontier.md](docs/model-frontier.md#judged-tasks)) |

- `semantic_mask`: segment visible pavement in the image.
- `click_connected_polygon`: return the paved component containing the target click.
  The polygon must be valid: one simple outer ring, cutouts strictly inside it and
  apart from each other, every vertex on the image. Anything else scores as a failure.
- `stall_count`: count parking stalls in a lot polygon, optionally emitting per-stall
  geometry (points or oriented boxes) scored against gold markers.
- `stripe_lines`: painted stripe geometry (stall dividers, aisle lines, stop bars,
  hatch strokes) for linear-foot takeoff. Judged, not gold-scored, for now.
- `scope_polygon`: future task for matching a specific commercial project scope.

## Model frontier

`pavebench score-runs` scores every system in a runs manifest in one pass and renders
the leaderboard with price-performance and speed-performance frontier charts. Repeated
tries per case are all scored. See [docs/model-frontier.md](docs/model-frontier.md).

## What PaveBench measures

Per case and per system:

- **Accuracy** — IoU, sqft delta (median + p90), area-weighted cutout recovery; for
  stalls, count error % plus per-stall precision/recall at a 2.7 m radius and median
  location error.
- **Latency** (first-class) — p95 wall-clock, bucketed into a latency class:
  **INSTANT** (p95 <= 10 s), **FAST** (<= 60 s), **BATCH** (> 60 s).
- **Cost** — mean/total USD per case.

Results are segmented by **GSD tier** (`<=8cm` / `8-15cm` / `>15cm`) because method
rankings flip with imagery resolution. The **INSTANT badge** — the "first verified
instant AI pavement takeoff" claim — requires the INSTANT latency class, a
`full_auto` automation declaration, and an accuracy floor across reviewed-gold cases
spanning multiple GSD tiers. See [docs/proving-instant-takeoff.md](docs/proving-instant-takeoff.md).

## Google Maps Imagery

Do not use Google Maps Static API, Map Tiles API, or cached Google imagery in public PaveBench datasets.

Maps Static API is a Google Maps Platform Core Service, and Google Maps Platform terms restrict caching, extracting, and creating content from Google Maps Content. The terms also prohibit using Google Maps Content to train, test, validate, or fine-tune ML/AI models. See `docs/google-static-maps-use.md`.

## Human-Traced Surfaces

Saved ProPaving human-traced paved surfaces are useful as guide material. They can seed candidate cases, rough boundaries, or reviewer starting points.

They are not automatically benchmark truth. A public PaveBench gold label must be reviewed against redistributable imagery and marked as `reviewed_gold` in metadata.

## Quick Start

```bash
python3 -m pytest

python3 -m pavebench.cli oracle \
  --allow-guide \
  --manifest dataset/v0/manifest.example.jsonl \
  --out results/oracle.example.jsonl

python3 -m pavebench.cli empty \
  --allow-guide \
  --manifest dataset/v0/manifest.example.jsonl \
  --out results/empty.example.jsonl

python3 -m pavebench.cli score-manifest \
  --allow-guide \
  --manifest dataset/v0/manifest.example.jsonl \
  --predictions results/oracle.example.jsonl \
  --out results/oracle-score.json

python3 -m pavebench.cli score \
  --allow-guide \
  --case dataset/v0/cases/demo_human_trace_guided/metadata.json \
  --predictions dataset/v0/cases/demo_human_trace_guided/predictions.example.jsonl \
  --out results/demo-score.json
```

Create a review-guide case from a saved human trace:

```bash
python3 -m pavebench.cli case-from-trace \
  --trace path/to/human-trace.geojson \
  --case-id pb_us_example_001 \
  --image-width 1024 \
  --image-height 1024 \
  --out-dir dataset/v0/cases/pb_us_example_001
```

The generated case is marked `role: guide` and `reviewStatus: needs_gold_review`. It must be reviewed against redistributable public imagery before becoming benchmark truth. Scoring guide cases requires `--allow-guide`; reviewed benchmark cases should not use that flag.

Build a real-imagery case from a ProPaving gold fixture + a redistributable ortho, then render the leaderboard:

```bash
python3 -m pavebench.cli case-from-propaving \
  --fixture path/to/ground-truth.json --case-id pb_us_xx_001 \
  --out-dir dataset/v0/cases/pb_us_xx_001 \
  --imagery-config imagery.json --export-gsd 0.15

python3 -m pavebench.cli leaderboard --runs results/runs.jsonl --out results/leaderboard.md
```

## Submission Shape

Predictions are JSONL:

```json
{
  "caseId": "demo_human_trace_guided",
  "task": "click_connected_polygon",
  "track": "vlm_polygon",
  "boundary": [[1, 1], [9, 1], [9, 9], [1, 9]],
  "cutouts": [],
  "latencyMs": 1200,
  "costUsd": 0.01,
  "metadata": {"model": "example"}
}
```

Mask predictions are also supported:

```json
{
  "caseId": "demo_human_trace_guided",
  "task": "semantic_mask",
  "track": "pure_segmentation",
  "maskPath": "relative/or/absolute/mask.png",
  "metadata": {"model": "example"}
}
```

See `docs/submission-format.md` for the full contract.

## Current Status

This repository is a v0 harness with its **first real-imagery case**:
`pb_us_il_justice_testa_001` (Justice IL, Cook County 2025 public-domain ortho,
227,861 sq ft, 30 landscape-island cutouts). It ships evaluator code with latency /
cost / GSD-tier aggregation, the `stall_count` task and metrics, oracle and empty
baselines, ProPaving-fixture and human-trace case scaffolding, a leaderboard
generator with the INSTANT badge, and documentation.

The Justice case is `needs_gold_review` (Craig's trace was drawn on Google imagery
and carries a ~2-3 m offset vs the ortho — see its `README.md`). It is not benchmark
truth until reviewed. The path from one case to a publishable v1 is in
[docs/proving-instant-takeoff.md](docs/proving-instant-takeoff.md).
