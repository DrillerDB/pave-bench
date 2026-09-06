from __future__ import annotations

import io
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from ..geometry import interior_point

# ProPaving gold traces were drawn on Google imagery; county/state orthos sit a
# couple of metres off. Ingested cases therefore land in review, never gold.
GEOREGISTRATION_CAVEAT = (
    "Gold geometry was hand-traced on Google imagery; it can sit ~2-3 m off this "
    "public-domain ortho. A reviewer must check the georegistration offset and "
    "adjust or re-trace before this case becomes reviewed_gold."
)


def _ring_lonlat(ring: list[list[float]]) -> list[tuple[float, float]]:
    points = [(float(pt[0]), float(pt[1])) for pt in ring]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _project(
    ring: list[tuple[float, float]],
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
) -> list[list[float]]:
    """Linear WGS84 -> pixel projection for an imageSR=4326 (plate-carree) export."""

    west, south, east, north = bbox
    span_lng = (east - west) or 1e-12
    span_lat = (north - south) or 1e-12
    projected: list[list[float]] = []
    for lng, lat in ring:
        x = (lng - west) / span_lng * width
        y = (north - lat) / span_lat * height
        projected.append([round(x, 3), round(y, 3)])
    return projected


def _export_image_url(base_url: str, bbox: tuple[float, float, float, float], width: int, height: int) -> str:
    west, south, east, north = bbox
    query = urllib.parse.urlencode(
        {
            "bbox": f"{west},{south},{east},{north}",
            "bboxSR": 4326,
            "imageSR": 4326,
            "size": f"{width},{height}",
            "format": "png",
            "f": "image",
        }
    )
    return f"{base_url.rstrip('/')}/exportImage?{query}"


def _meters_extent(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    west, south, east, north = bbox
    lat_mid = math.radians((south + north) / 2)
    width_m = (east - west) * 111_320 * math.cos(lat_mid)
    height_m = (north - south) * 111_320
    return width_m, height_m


def _returned_bbox(
    bbox: tuple[float, float, float, float], width: int, height: int,
) -> tuple[float, float, float, float]:
    """ArcGIS defaults to square imageSR units (degrees for our 4326 export).

    Match ProPaving's computeArcgisReturnedBounds: expand, never crop. Ground
    metres are not degrees, so the requested metre-sized raster changes extent.
    For fetched images the service response below is authoritative.
    """
    west, south, east, north = bbox
    cx, cy = (west + east) / 2, (south + north) / 2
    dx, dy = east - west, north - south
    ratio = width / height
    if dx / dy > ratio:
        dy = dx / ratio
    else:
        dx = dy * ratio
    return cx - dx / 2, cy - dy / 2, cx + dx / 2, cy + dy / 2


def _fetch_export(image_url: str) -> tuple[bytes, tuple, int, int, dict]:
    """Read image and georeferencing from ONE export, rather than guessing its extent."""
    metadata_url = image_url.replace("f=image", "f=json")
    request = urllib.request.Request(metadata_url, headers={"User-Agent": "PaveBench/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        export = json.load(response)
    if "error" in export:
        raise RuntimeError("ImageServer export failed")
    extent = export.get("extent", {})
    sr = extent.get("spatialReference", {})
    if sr.get("latestWkid", sr.get("wkid")) != 4326:
        raise RuntimeError("ImageServer returned an unexpected spatial reference")
    bbox = tuple(extent.get(k) for k in ("xmin", "ymin", "xmax", "ymax"))
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
        raise RuntimeError("ImageServer returned an invalid extent")
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise RuntimeError("ImageServer returned an empty extent")
    width, height = export.get("width"), export.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or min(width, height) <= 0:
        raise RuntimeError("ImageServer returned invalid image dimensions")
    image_request = urllib.request.Request(export["href"], headers={"User-Agent": "PaveBench/0.1"})
    with urllib.request.urlopen(image_request, timeout=120) as response:
        payload = response.read()
    with Image.open(io.BytesIO(payload)) as image:
        if image.size != (width, height):
            raise RuntimeError("ImageServer image dimensions disagree with export metadata")
    return payload, bbox, width, height, export


def create_case_from_propaving(
    fixture_path: str | Path,
    out_dir: str | Path,
    case_id: str,
    imagery_source: dict[str, Any],
    export_gsd_meters: float = 0.15,
    max_pixels: int = 4000,
    fetch: bool = True,
    split: str = "dev",
) -> dict[str, Any]:
    """Scaffold a benchmark case from a ProPaving gold fixture + imagery spec.

    ``imagery_source`` must declare a REDISTRIBUTABLE public-domain source, e.g.::

        {"name": "Cook County 2025 Orthophotography",
         "imageServer": "https://.../CookOrtho2025/ImageServer",
         "nativeGsdMeters": 0.1524, "vintage": "2025",
         "license": "public domain", "redistributable": true}

    Google imagery and Esri tiles are never redistributable and are rejected. The
    case is written with ``reviewStatus: needs_gold_review`` and the
    georegistration caveat; it is not benchmark truth until a reviewer promotes it.
    """

    if not imagery_source.get("redistributable"):
        raise ValueError(
            "imagery_source.redistributable must be true; only public-domain "
            "county/state orthos or USGS NAIP may back a public PaveBench case."
        )
    banned = ("google", "googleapis", "esri", "arcgisonline")
    haystack = " ".join(
        str(imagery_source.get(key, "")) for key in ("name", "imageServer", "sourceUrl", "license")
    ).lower()
    if any(term in haystack for term in banned):
        raise ValueError(
            f"imagery_source looks non-redistributable ({haystack!r}); Google and "
            "Esri World Imagery are prohibited for public cases."
        )

    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    geometry = fixture.get("geometry", {})
    if geometry.get("type") != "Polygon":
        raise ValueError("ProPaving fixture geometry must be a Polygon")
    rings = geometry.get("coordinates", [])
    if not rings:
        raise ValueError("ProPaving fixture polygon has no rings")

    boundary_lonlat = _ring_lonlat(rings[0])
    cutouts_lonlat = [_ring_lonlat(ring) for ring in rings[1:]]

    # The imagery extent is the user's analysis box when present ("imagery/crop
    # must fully contain this"), else the paved boundary.
    analysis_area = (fixture.get("analysisArea") or {}).get("geometry", {})
    if analysis_area.get("type") == "Polygon" and analysis_area.get("coordinates"):
        box_lonlat = _ring_lonlat(analysis_area["coordinates"][0])
        bbox = _bbox(box_lonlat)
    else:
        box_lonlat = None
        bbox = _bbox(boundary_lonlat)

    width_m, height_m = _meters_extent(bbox)
    width = max(1, round(width_m / export_gsd_meters))
    height = max(1, round(height_m / export_gsd_meters))
    scale = min(1.0, max_pixels / max(width, height))
    width = max(1, round(width * scale))
    height = max(1, round(height * scale))

    requested_bbox = bbox
    image_url = _export_image_url(imagery_source["imageServer"], bbox, width, height)
    bbox = _returned_bbox(requested_bbox, width, height)
    payload = None
    export = None
    if fetch:
        payload, bbox, width, height, export = _fetch_export(image_url)
    width_m, height_m = _meters_extent(bbox)
    pixel_size_x, pixel_size_y = width_m / width, height_m / height
    # Scalar compatibility with the evaluator: square of this value is pixel
    # AREA. Keep the actual axis resolutions in metadata; pixels need not be
    # square on the ground. Arithmetic-mean GSD silently biases square footage.
    effective_gsd = math.sqrt(pixel_size_x * pixel_size_y)

    boundary_px = _project(boundary_lonlat, bbox, width, height)
    cutouts_px = [_project(ring, bbox, width, height) for ring in cutouts_lonlat]
    input_box_px = _project(box_lonlat, bbox, width, height) if box_lonlat else None

    try:
        cx, cy = interior_point(
            [(p[0], p[1]) for p in boundary_px],
            [[(p[0], p[1]) for p in ring] for ring in cutouts_px],
        )
        clicks = [{"id": "main", "x": round(cx, 3), "y": round(cy, 3)}]
    except ValueError:
        clicks = []

    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)

    imagery_status = "declared_not_fetched"
    image_file: str | None = None
    if fetch:
        (destination / "image.png").write_bytes(payload)
        (destination / "export-response.json").write_text(json.dumps(export, indent=2) + "\n")
        image_file = "image.png"
        imagery_status = "included_redistributable"

    native_gsd = imagery_source.get("nativeGsdMeters")
    imagery = {
        "source": imagery_source.get("name"),
        "sourceUrl": imagery_source.get("imageServer"),
        "exportUrl": image_url,
        "imageFile": image_file,
        "nativeGsdMeters": native_gsd,
        "exportGsdMeters": effective_gsd,
        "pixelSizeMeters": {"x": pixel_size_x, "y": pixel_size_y},
        "vintage": imagery_source.get("vintage"),
        "license": imagery_source.get("license"),
        "redistributable": True,
        "imageryStatus": imagery_status,
        "bbox": {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]},
        "bboxSR": 4326,
        "requestedBbox": dict(zip(("west", "south", "east", "north"), requested_bbox)),
        "extentSource": "service_response" if fetch else "arcgis_default_aspect_ratio",
    }

    label_source = {
        "kind": "human_traced_paved_surface",
        "role": "guide",
        "reviewStatus": "needs_gold_review",
        "sourceMeasurementId": fixture.get("id"),
        "sourceName": fixture.get("name"),
        "tracedOn": "google_imagery",
        "georegistrationCaveat": GEOREGISTRATION_CAVEAT,
    }

    metadata: dict[str, Any] = {
        "caseId": case_id,
        "split": split,
        "imageSize": {"width": width, "height": height},
        "coordinateSpace": "image_pixels",
        "imagery": imagery,
        "resolutionMetersPerPixel": effective_gsd,
        "labelSource": label_source,
        "referenceSquareFeet": fixture.get("squareFeet"),
        "gold": {"boundary": boundary_px, "cutouts": cutouts_px},
        "clicks": clicks,
    }
    if input_box_px is not None:
        metadata["inputBox"] = input_box_px

    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    features = [
        {
            "type": "Feature",
            "properties": {"caseId": case_id, "role": "guide", "reviewStatus": "needs_gold_review"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    boundary_px + [boundary_px[0]],
                    *[ring + [ring[0]] for ring in cutouts_px],
                ],
            },
        }
    ]
    (destination / "gold.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2) + "\n",
        encoding="utf-8",
    )

    return metadata
