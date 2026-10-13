# Submission Format

Predictions are JSON Lines files. Each line is one case/task prediction.

```json
{
  "caseId": "demo_human_trace_guided",
  "task": "click_connected_polygon",
  "track": "vlm_polygon",
  "boundary": [[1, 1], [9, 1], [9, 9], [1, 9]],
  "cutouts": [],
  "latencyMs": 1200,
  "costUsd": 0.01,
  "metadata": {
    "model": "example-model",
    "modelCalls": 1,
    "promptHash": "sha256:..."
  }
}
```

Coordinates are pixel coordinates in `[x, y]` order with origin at the top-left corner of the benchmark image.

A polygon prediction must be valid to score: one simple outer ring (no self-crossing or
self-touching), every cutout strictly inside the boundary, cutouts not overlapping or
nested, and every vertex within 1 px of the image. An invalid polygon scores IoU 0 and
fails, with the reason in `error` (`invalid_polygon:self_intersecting_boundary`,
`invalid_polygon:cutout_crosses_boundary`, `invalid_polygon:overlapping_cutouts`,
`invalid_polygon:outside_image`, ...). Area from an invalid polygon depends on the fill
rule, so it is not comparable.

A file may hold several predictions for the same case and task (repeated tries); every
one is scored. `metadata.appValid` (optional, boolean) records whether the submitting
application's own validator accepted the draft; the leaderboard reports it beside
benchmark validity but never scores it.

Required fields:

- `caseId`
- `task`
- `track`
- either `boundary` plus `cutouts`, or `maskPath`

Polygon predictions:

```json
{
  "caseId": "pb_us_example_001",
  "task": "click_connected_polygon",
  "track": "vlm_polygon",
  "boundary": [[100, 200], [300, 200], [300, 400], [100, 400]],
  "cutouts": []
}
```

Mask predictions:

```json
{
  "caseId": "pb_us_example_001",
  "task": "semantic_mask",
  "track": "pure_segmentation",
  "maskPath": "masks/pb_us_example_001.png"
}
```

Mask files are loaded as grayscale images. Pixels with value `>= 128` are foreground pavement; lower values are background.

Stall-count predictions (`task: stall_count`):

```json
{
  "caseId": "pb_us_il_justice_testa_001",
  "task": "stall_count",
  "track": "hybrid_production",
  "count": 339,
  "stalls": [[512, 640], [[500, 600], [540, 600], [540, 690], [500, 690]]],
  "latencyMs": 8200,
  "costUsd": 0.11,
  "metadata": {"model": "example"}
}
```

- `count` (required) — total stall count.
- `stalls` (optional) — per-stall geometry, each item either a point `[x, y]` or an
  oriented-box ring `[[x, y], ...]`. Both reduce to a centroid for marker matching.
  Supplying geometry unlocks per-stall precision/recall and location error when the
  case ships gold markers.

Allowed `track` values:

- `pure_segmentation`
- `vlm_polygon`
- `image_generation_mask`
- `hybrid_production`

### Latency and cost are first-class

`latencyMs` (wall-clock) and `costUsd` are aggregated into p50/p95 latency, a
latency class (INSTANT/FAST/BATCH), and mean/total cost. The INSTANT badge depends
on them — see [proving-instant-takeoff.md](proving-instant-takeoff.md). Populate
them on every prediction.

Every leaderboard submission should also disclose model versions, training data, auxiliary data, number of model calls, average cost, average latency, the declared automation level (`full_auto` / `assisted` / `human_in_loop`), and the code commit used to generate predictions.

## Case metadata

A case `metadata.json` declares geometry, imagery, and (optionally) stall gold:

```json
{
  "caseId": "pb_us_il_justice_testa_001",
  "split": "dev",
  "imageSize": {"width": 1387, "height": 1608},
  "resolutionMetersPerPixel": 0.1524,
  "imagery": {
    "source": "Cook County 2025 Orthophotography",
    "nativeGsdMeters": 0.1524,
    "exportGsdMeters": 0.1524,
    "vintage": "2025",
    "license": "public domain",
    "redistributable": true,
    "imageryStatus": "included_redistributable"
  },
  "labelSource": {"role": "guide", "reviewStatus": "needs_gold_review"},
  "gold": {"boundary": [[x, y], ...], "cutouts": [[[x, y], ...]]},
  "clicks": [{"id": "main", "x": 640, "y": 800}],
  "stallGold": {"count": 339, "matchRadiusMeters": 2.7, "markers": [[x, y], ...]}
}
```

Reports segment results by `imagery.nativeGsdMeters` GSD tier (`<=8cm` / `8-15cm` /
`>15cm`) and by `split`. Guide cases (`role: guide` / `reviewStatus:
needs_gold_review`) require `--allow-guide` to score and never count toward the
INSTANT badge.

## Building cases from ProPaving fixtures

```bash
python3 -m pavebench.cli case-from-propaving \
  --fixture path/to/ground-truth.json --case-id pb_us_xx_001 \
  --out-dir dataset/v0/cases/pb_us_xx_001 \
  --imagery-config imagery.json --export-gsd 0.15
```

`imagery.json` must declare a redistributable public-domain source
(`redistributable: true`, non-Google, non-Esri) — e.g. a county/state ArcGIS
ImageServer. The generated case is `needs_gold_review` with a documented
georegistration caveat.

## Scoring many systems at once

```bash
python3 -m pavebench.cli score-runs --manifest <manifest.jsonl> --runs <runs.jsonl> \
  --out <dir>/leaderboard.md [--judged <judged.json>]
```

Each runs row may name `predictionsPath` (scored into `scorePath`), `tasks` (limit
scoring to the tasks the system attempted), `notes`, and `frontierExclude` +
`frontierNote` (keep a system off one task's frontier, with the reason printed).
Frontier SVGs are written next to the leaderboard.

## Rendering the leaderboard

```bash
python3 -m pavebench.cli leaderboard --runs results/runs.jsonl --out results/leaderboard.md
```

`runs.jsonl` rows declare `system`, `track`, `automation`, and a `scorePath` to a
`score-manifest` report. See `results/runs.example.jsonl`.

## CLI

Score one case:

```bash
python3 -m pavebench.cli score --case path/to/metadata.json --predictions predictions.jsonl --out score.json
```

Score a manifest:

```bash
python3 -m pavebench.cli score-manifest --manifest dataset/v0/manifest.example.jsonl --predictions predictions.jsonl --out score.json
```

Generate oracle predictions:

```bash
python3 -m pavebench.cli oracle --manifest dataset/v0/manifest.example.jsonl --out oracle.jsonl
```

Generate empty baseline predictions:

```bash
python3 -m pavebench.cli empty --manifest dataset/v0/manifest.example.jsonl --out empty.jsonl
```

For dry-running the toy guide fixture or any case marked `needs_gold_review`, add `--allow-guide`. Public leaderboard scoring should use reviewed-gold cases and omit that flag.
