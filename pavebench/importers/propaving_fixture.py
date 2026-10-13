from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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


# Exports use Web Mercator (EPSG:3857). An ArcGIS ImageServer always returns square
# pixels in the output spatial reference and silently widens the extent when the
# requested size does not match the bbox aspect. A plate-carree (4326) export with
# pixels square on the ground therefore came back covering more latitude than
# requested, and every projected vertex landed in the wrong place (Justice IL, fixed
# 2026-10-13). In 3857 we choose an extent that is an exact multiple of the pixel
# size, so the server returns precisely what was asked, and pixels are square on the
# ground (scale 1/cos(lat) in both axes).
_R = 6378137.0


def _merc(lng: float, lat: float) -> tuple[float, float]:
    x = math.radians(lng) * _R
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _R
    return x, y


def _unmerc(x: float, y: float) -> tuple[float, float]:
    return math.degrees(x / _R), math.degrees(2 * math.atan(math.exp(y / _R)) - math.pi / 2)


def _mercator_frame(
    bbox: tuple[float, float, float, float], export_gsd_meters: float, max_pixels: int
) -> tuple[tuple[float, float, float, float], int, int, float]:
    """Pixel-aligned Web Mercator extent (xmin, ymin, xmax, ymax), size and ground GSD."""

    west, south, east, north = bbox
    lat_mid = math.radians((south + north) / 2)
    xmin, ymin = _merc(west, south)
    xmax, ymax = _merc(east, north)
    cell = export_gsd_meters / math.cos(lat_mid)  # Mercator metres per pixel
    width = max(1, math.ceil((xmax - xmin) / cell))
    height = max(1, math.ceil((ymax - ymin) / cell))
    longest = max(width, height)
    if longest > max_pixels:
        cell *= longest / max_pixels
        width = max(1, math.ceil((xmax - xmin) / cell))
        height = max(1, math.ceil((ymax - ymin) / cell))
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    frame = (cx - width * cell / 2, cy - height * cell / 2, cx + width * cell / 2, cy + height * cell / 2)
    return frame, width, height, round(cell * math.cos(lat_mid), 5)


def _project(
    ring: list[tuple[float, float]],
    frame: tuple[float, float, float, float],
    width: int,
    height: int,
) -> list[list[float]]:
    """WGS84 -> pixel for an imageSR=3857 export of exactly ``frame``."""

    xmin, ymin, xmax, ymax = frame
    sx = width / (xmax - xmin)
    sy = height / (ymax - ymin)
    projected: list[list[float]] = []
    for lng, lat in ring:
        x, y = _merc(lng, lat)
        projected.append([round((x - xmin) * sx, 3), round((ymax - y) * sy, 3)])
    return projected


def _export_image_url(base_url: str, frame: tuple[float, float, float, float], width: int, height: int) -> str:
    xmin, ymin, xmax, ymax = frame
    query = urllib.parse.urlencode(
        {
            "bbox": f"{xmin:.3f},{ymin:.3f},{xmax:.3f},{ymax:.3f}",
            "bboxSR": 3857,
            "imageSR": 3857,
            "size": f"{width},{height}",
            "format": "png",
            "f": "image",
        }
    )
    return f"{base_url.rstrip('/')}/exportImage?{query}"


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

    frame, width, height, effective_gsd = _mercator_frame(bbox, export_gsd_meters, max_pixels)
    west, south = _unmerc(frame[0], frame[1])
    east, north = _unmerc(frame[2], frame[3])

    boundary_px = _project(boundary_lonlat, frame, width, height)
    cutouts_px = [_project(ring, frame, width, height) for ring in cutouts_lonlat]
    input_box_px = _project(box_lonlat, frame, width, height) if box_lonlat else None

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

    image_url = _export_image_url(imagery_source["imageServer"], frame, width, height)
    imagery_status = "declared_not_fetched"
    image_file: str | None = None
    if fetch:
        request = urllib.request.Request(image_url, headers={"User-Agent": "PaveBench/0.1"})
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (public gov ImageServer)
            payload = response.read()
        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type:
            raise RuntimeError(f"ImageServer did not return an image (Content-Type={content_type})")
        (destination / "image.png").write_bytes(payload)
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
        "vintage": imagery_source.get("vintage"),
        "license": imagery_source.get("license"),
        "redistributable": True,
        "imageryStatus": imagery_status,
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "bboxSR": 4326,
        "imageSR": 3857,
        "mercatorExtent": {"xmin": frame[0], "ymin": frame[1], "xmax": frame[2], "ymax": frame[3]},
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
