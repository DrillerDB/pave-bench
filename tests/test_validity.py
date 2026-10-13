from pavebench.geometry import polygon_validity_error, ring_is_simple, segments_intersect

SQUARE = [(0, 0), (100, 0), (100, 100), (0, 100)]


def test_segments_intersect_cross_touch_and_miss():
    assert segments_intersect((0, 0), (10, 10), (0, 10), (10, 0))
    assert segments_intersect((0, 0), (10, 0), (10, 0), (10, 5))  # touching endpoint
    assert not segments_intersect((0, 0), (10, 0), (0, 1), (10, 1))


def test_simple_and_bowtie_rings():
    assert ring_is_simple(SQUARE)
    assert ring_is_simple(SQUARE + [SQUARE[0]])  # explicitly closed
    assert not ring_is_simple([(0, 0), (100, 100), (100, 0), (0, 100)])


def test_valid_polygon_with_holes():
    holes = [[(10, 10), (20, 10), (20, 20), (10, 20)], [(50, 50), (60, 50), (60, 60), (50, 60)]]
    assert polygon_validity_error(SQUARE, holes, 100, 100) is None


def test_invalid_polygons_are_named():
    assert polygon_validity_error([(0, 0), (100, 100), (100, 0), (0, 100)], [], 100, 100) == "self_intersecting_boundary"
    assert polygon_validity_error(SQUARE, [[(90, 90), (120, 90), (120, 95)]], 200, 200) == "cutout_outside_boundary"
    assert polygon_validity_error(SQUARE, [[(-5, 40), (50, 40), (50, 60)]], 100, 100) == "outside_image"
    crossing = [[(10, 10), (150, 10), (10, 20)]]
    assert polygon_validity_error(SQUARE, crossing, 200, 200) == "cutout_outside_boundary"
    edge_touch = [[(0, 10), (20, 10), (20, 20)]]
    assert polygon_validity_error(SQUARE, edge_touch, 100, 100) in {"cutout_outside_boundary", "cutout_crosses_boundary"}
    overlap = [[(10, 10), (40, 10), (40, 40), (10, 40)], [(30, 30), (60, 30), (60, 60), (30, 60)]]
    assert polygon_validity_error(SQUARE, overlap, 100, 100) == "overlapping_cutouts"
    nested = [[(10, 10), (60, 10), (60, 60), (10, 60)], [(20, 20), (30, 20), (30, 30), (20, 30)]]
    assert polygon_validity_error(SQUARE, nested, 100, 100) == "overlapping_cutouts"
