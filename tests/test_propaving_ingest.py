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


def test_mercator_frame_is_pixel_aligned_and_round_trips():
    from pavebench.importers.propaving_fixture import _mercator_frame, _project

    bbox = (-87.9127, 41.7559, -87.9102, 41.7581)
    frame, w, h, gsd = _mercator_frame(bbox, 0.1524, 4000)
    cell_x = (frame[2] - frame[0]) / w
    cell_y = (frame[3] - frame[1]) / h
    assert abs(cell_x - cell_y) < 1e-9  # square pixels: the server returns this extent as asked
    assert abs(gsd - 0.1524) < 1e-4
    (x0, y0), = _project([(bbox[0], bbox[3])], frame, w, h)
    (x1, y1), = _project([(bbox[2], bbox[1])], frame, w, h)
    assert 0 <= x0 < 1.5 and 0 <= y0 < 1.5 and w - 1.5 < x1 <= w and h - 1.5 < y1 <= h
