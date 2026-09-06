# pb_us_il_justice_testa_001 — Justice IL (Testa Dr)

The first real-imagery PaveBench case: a large, empty, crisply striped office
parking lot with ~30 landscape-island cutouts, a building, and a retention pond.

| Field | Value |
|---|---|
| Location | Testa Dr, Justice IL (~41.757, -87.912) |
| Imagery | Cook County 2025 Orthophotography (ArcGIS ImageServer), public domain |
| Native GSD | 0.1524 m/px (0.5 US-ft, 6-inch nominal) -> `>15cm` tier |
| Image | `image.png`, 1387 x 1608, exported at imageSR=4326 |
| Ground pixel dimensions | approximately 0.152424 m east-west x 0.204328 m north-south; area-equivalent GSD 0.1765 m |
| Paved area (reference) | 227,861 sq ft (Craig's hand trace) |
| Cutouts | 30 interior landscape islands |
| Task inputs | user analysis box (`inputBox`), interior click |
| Status | `role: guide`, `reviewStatus: needs_gold_review` |

## Review status: needs_gold_review

This case is **not benchmark truth yet.** The gold geometry was hand-traced by
Craig on Google imagery and then projected onto the Cook County ortho by
`pavebench case-from-propaving` (linear WGS84 -> pixel mapping over the analysis
box). Two things a reviewer must confirm before promoting to `reviewed_gold`:

1. **Georegistration and scope review.** Check residual alignment and the
   intended treatment of pavement beside the building and the driveway aprons.
   The original large misalignment was an export-extent bug, corrected below;
   it must not be explained away as ordinary imagery registration noise.
2. **Cutout completeness.** All 30 islands were carried over; verify each lands
   on a real planter and none are missing at this resolution.

## Export-extent correction (2026-09-06)

ArcGIS defaults to `adjustAspectRatio=true`. With `imageSR=4326`, it expands the
requested bbox to match the pixel aspect ratio in **degrees**, not ground metres.
The old importer projected the trace against the requested bbox, while the PNG
actually covered a 34.05% larger latitude span. This misplaced the reference and
understated the square footage of predictions made against the image.

The importer now uses the service-reported extent and dimensions from the same
`f=json` export that supplies the image. `export-response.json` records that
response; `metadata.json` retains both requested and actual bounds and both
ground pixel dimensions. The scalar resolution is their geometric mean, so its
square preserves pixel area. Offline scaffolds mirror the ArcGIS expansion.

The PNG is byte-for-byte unchanged (SHA-256
`74f6bc05b2165c192d1f1ec75249937314fbbf9ed23c37412e37b455fea1d7d2`). Only its
reference projection and scale metadata were repaired. Scores made with the old
metadata must be recomputed; the repair is **not** a model improvement or a
promotion to reviewed gold. The source geographic trace remains unchanged.

See [ArcGIS exportImage documentation](https://developers.arcgis.com/rest/services-reference/enterprise/export-image/).

Regenerate the review overlay with:

```python
import json
from PIL import Image, ImageDraw
m = json.load(open("metadata.json"))
img = Image.open("image.png").convert("RGB")
d = ImageDraw.Draw(img, "RGBA")
b = [(p[0], p[1]) for p in m["gold"]["boundary"]]
d.line(b + [b[0]], fill=(0, 255, 255, 255), width=5)
for c in m["gold"]["cutouts"]:
    ring = [(p[0], p[1]) for p in c]
    d.line(ring + [ring[0]], fill=(255, 80, 0, 255), width=3)
img.save("review-overlay.png")
```

## Why this lot matters

It is the ProPaving founder's gold lot and the hardest imagery lesson in the
research: Esri World Imagery has no high-res tiles here (z19 native, 22 cm/px),
so it is unusable for stall stripes — but the **free** Cook County public-domain
ortho resolves it. This case exists to prove the benchmark can run on legal,
redistributable, reproducible imagery instead of Google.
