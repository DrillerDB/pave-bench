import json

import pytest

from pavebench.importers.propaving_fixture import create_case_from_propaving
from pavebench.schemas import load_case_from_metadata, needs_gold_review

# A tiny synthetic ProPaving fixture: a paved rectangle with one interior island,
# plus a slightly larger analysis box. Coordinates are WGS84 lng/lat.
FIXTURE = {
    "id": "test_measurement_1",
    "name": "Synthetic Lot",
    "type": "AREA",
    "squareFeet": 12345.6,
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [[-88.0020, 41.0000], [-88.0000, 41.0000], [-88.0000, 41.0020], [-88.0020, 41.0020], [-88.0020, 41.0000]],
            [[-88.0012, 41.0008], [-88.0008, 41.0008], [-88.0008, 41.0012], [-88.0012, 41.0012], [-88.0012, 41.0008]],
        ],
    },
    "analysisArea": {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[-88.0025, 40.9995], [-87.9995, 40.9995], [-87.9995, 41.0025], [-88.0025, 41.0025], [-88.0025, 40.9995]]
            ],
        },
        "squareFeet": 20000.0,
    },
}

COOK = {
    "name": "Cook County 2025 Orthophotography",
    "imageServer": "https://gis.cookcountyil.gov/imagery/rest/services/CookOrtho2025/ImageServer",
    "nativeGsdMeters": 0.1524,
    "vintage": "2025",
    "license": "public domain",
    "redistributable": True,
}


def _write_fixture(tmp_path):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(FIXTURE), encoding="utf-8")
    return path


def test_ingest_scaffolds_pixel_space_guide_case(tmp_path):
    fixture = _write_fixture(tmp_path)
    out_dir = tmp_path / "case"
    metadata = create_case_from_propaving(
        fixture, out_dir, "pb_synth_001", COOK, export_gsd_meters=0.5, fetch=False
    )

    assert metadata["coordinateSpace"] == "image_pixels"
    assert metadata["imagery"]["imageryStatus"] == "declared_not_fetched"
    assert metadata["imagery"]["nativeGsdMeters"] == 0.1524
    assert len(metadata["gold"]["cutouts"]) == 1
    assert "georegistrationCaveat" in metadata["labelSource"]
    assert metadata["labelSource"]["reviewStatus"] == "needs_gold_review"
    assert (out_dir / "metadata.json").exists()
    assert (out_dir / "gold.geojson").exists()

    case = load_case_from_metadata(out_dir / "metadata.json")
    assert needs_gold_review(case)
    # The paved boundary projects inside the analysis-box image, and the island
    # projects to an interior ring.
    xs = [p[0] for p in case.gt_boundary]
    ys = [p[1] for p in case.gt_boundary]
    assert min(xs) > 0 and max(xs) < case.image_width
    assert min(ys) > 0 and max(ys) < case.image_height
    assert len(case.gt_cutouts) == 1
    # A coarse native GSD (15 cm) buckets the case into the >15cm tier.
    assert case.gsd_for_tier() == 0.1524


def test_ingest_rejects_non_redistributable_imagery(tmp_path):
    fixture = _write_fixture(tmp_path)
    google = {**COOK, "name": "Google Static Maps", "imageServer": "https://maps.googleapis.com/..."}
    with pytest.raises(ValueError, match="non-redistributable|redistributable"):
        create_case_from_propaving(fixture, tmp_path / "c", "x", google, fetch=False)


def test_ingest_requires_redistributable_flag(tmp_path):
    fixture = _write_fixture(tmp_path)
    unflagged = {**COOK, "redistributable": False}
    with pytest.raises(ValueError, match="redistributable"):
        create_case_from_propaving(fixture, tmp_path / "c", "x", unflagged, fetch=False)


def test_export_projection_uses_returned_extent_not_requested_extent(tmp_path):
    """ArcGIS expands 4326 bounds to square degrees, not square ground metres.

    At 41 degrees a metre-sized image needs a taller latitude extent. Ignoring
    that expansion moved the Justice reference by tens of metres, and scored
    correctly located model islands as completely missed.
    """
    import math

    metadata = create_case_from_propaving(
        _write_fixture(tmp_path), tmp_path / "case", "pb_synth", COOK,
        export_gsd_meters=0.5, fetch=False,
    )
    b = metadata["imagery"]["bbox"]
    w, h = metadata["imageSize"].values()
    assert b["south"] < 40.9995
    assert b["north"] > 41.0025
    assert (b["east"] - b["west"]) / (b["north"] - b["south"]) == pytest.approx(w / h)
    # Project the fixture's known first geographic vertex against the extent
    # the image actually covers, not a reference derived from the output ring.
    assert metadata["gold"]["boundary"][0][1] == pytest.approx(
        (b["north"] - 41.0) / (b["north"] - b["south"]) * h, abs=0.001,
    )
    dx = (b["east"] - b["west"]) * 111320 * math.cos(math.radians(41.001)) / w
    dy = (b["north"] - b["south"]) * 111320 / h
    # Equivalent GSD must preserve pixel AREA; an arithmetic mean squared does not.
    assert metadata["resolutionMetersPerPixel"] ** 2 == pytest.approx(dx * dy, rel=1e-4)


@pytest.mark.parametrize("image_size", [(320, 640), (319, 640)])
def test_fetched_case_uses_service_extent_and_checks_image_dimensions(tmp_path, monkeypatch, image_size):
    import io
    import urllib.request
    from PIL import Image

    # Different from both requested dimensions and the deterministic estimate:
    # the response, not locally predicted framing, is authoritative.
    export = {
        "width": 320, "height": 640,
        "extent": {"xmin": -88.004, "ymin": 40.998, "xmax": -87.998,
                   "ymax": 41.004, "spatialReference": {"wkid": 4326}},
        "href": "https://gis.example.gov/rendered.png",
    }
    png = io.BytesIO()
    Image.new("RGB", image_size).save(png, format="PNG")
    urls = []
    def urlopen(request, timeout):
        urls.append(request.full_url)
        return io.BytesIO(json.dumps(export).encode() if "f=json" in request.full_url else png.getvalue())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    if image_size != (320, 640):
        with pytest.raises(RuntimeError, match="dimensions disagree"):
            create_case_from_propaving(_write_fixture(tmp_path), tmp_path / "case", "x", COOK)
        assert not (tmp_path / "case" / "metadata.json").exists()
        return
    m = create_case_from_propaving(_write_fixture(tmp_path), tmp_path / "case", "x", COOK)
    assert m["imageSize"] == {"width": 320, "height": 640}
    assert m["imagery"]["bbox"]["south"] == 40.998
    assert m["imagery"]["extentSource"] == "service_response"
    assert m["gold"]["boundary"][0] == pytest.approx([106.667, 426.667], abs=0.001)
    assert m["labelSource"]["reviewStatus"] == "needs_gold_review"
    assert "f=json" in urls[0]
    assert urls[1] == export["href"]
    assert (tmp_path / "case" / "export-response.json").exists()
