"""Tests of the draft SREP "Add a style layer" (srep/srep-0000-style-layer.md) and of its reference module
conformance/tools/style_layer_reference.py: look resolution, toon bands at their declared thresholds, the
specular and rim bands, flat shading, silhouette and crease edges of meshes, the outline edge mask and its
width, the sketch wobble with its taper and closed-path wavelength, overdraw passes and the boil step, marker
widths, hatching, and the SREP's numeric table against the module.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "style_layer_reference.py")
STREAMS = os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-style-layer.md")

spec = importlib.util.spec_from_file_location("style_layer_reference", MODULE)
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)

spec_rs = importlib.util.spec_from_file_location("random_streams_reference", STREAMS)
rs = importlib.util.module_from_spec(spec_rs)
spec_rs.loader.exec_module(rs)

THRESHOLDS = (0.2, 0.5, 0.8)
LEVELS = (0.1, 0.4, 0.7, 1.0)
Z = (0.0, 0.0, 1.0)
LINE = tuple((10.0 * i, 0.0) for i in range(11))   # 100 units long, 11 points

# a square of two triangles facing +z, and a second pair folded by 90 degrees
SQUARE_V = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0))
SQUARE_F = ((0, 1, 2), (1, 3, 2))
FOLD_V = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))
FOLD_F = ((0, 1, 2), (1, 0, 3))


def _close(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], tol) for k in a)
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


# ------------------------------------------------------------------------------------------------ looks

def test_the_four_looks_are_named():
    assert sl.KINDS == ("flat", "sketch", "toon", "photoreal")


def test_the_nearest_ancestor_look_wins():
    assert sl.resolve_look([("composition", None), ("group", "toon"), ("object3D", None)]) == "toon"
    assert sl.resolve_look([("composition", "sketch"), ("group", "flat"), ("shape", None)]) == "flat"
    assert sl.resolve_look([("composition", "sketch"), ("group", None), ("shape", "toon")]) == "toon"


def test_without_a_look_3d_nodes_are_photoreal_and_vector_nodes_flat():
    assert sl.resolve_look([("composition", None), ("object3D", None)]) == "photoreal"
    assert sl.resolve_look([("composition", None), ("group", None), ("shape", None)]) == "flat"
    assert sl.resolve_look([("composition", None), ("text", None)]) == "flat"


def test_an_unknown_look_or_an_empty_chain_is_an_error():
    assert sl.raises(lambda: sl.resolve_look([("composition", "cartoon")]))
    assert sl.raises(lambda: sl.resolve_look([]))


# ------------------------------------------------------------------------------------------------ toon bands

def test_lambert_is_the_clamped_cosine_of_unit_vectors():
    assert sl.lambert(Z, Z) == 1.0
    assert sl.lambert(Z, (1.0, 0.0, 0.0)) == 0.0
    assert sl.lambert(Z, (0.0, 0.0, -1.0)) == 0.0
    assert _close(sl.lambert((0.0, 0.0, 2.0), (0.0, 3.0, 3.0)), math.sqrt(0.5))


def test_bands_fall_at_their_declared_thresholds():
    assert sl.band_index(0.5, THRESHOLDS) == 2          # at a threshold, the upper band
    assert sl.band_index(0.5 - 1e-12, THRESHOLDS) == 1
    assert sl.band_index(0.0, THRESHOLDS) == 0
    assert sl.band_index(0.2, THRESHOLDS) == 1
    assert sl.band_index(0.8, THRESHOLDS) == 3
    assert sl.band_index(1.0, THRESHOLDS) == 3


def test_the_band_boundary_on_a_lit_sphere_is_at_the_arc_cosine_of_the_threshold():
    assert _close(sl.band_angle(0.5), 60.0)
    assert _close(sl.band_angle(1.0), 0.0)
    assert sl.band_index(math.cos(math.radians(60.0)), (0.5,)) == 1
    assert sl.band_index(math.cos(math.radians(60.001)), (0.5,)) == 0


def test_no_thresholds_is_one_band():
    assert sl.band_index(0.3, ()) == 0
    assert sl.toon_diffuse(0.3, (), (0.6,)) == 0.6


def test_toon_diffuse_takes_the_level_of_the_band():
    assert sl.toon_diffuse(0.0, THRESHOLDS, LEVELS) == 0.1
    assert sl.toon_diffuse(0.35, THRESHOLDS, LEVELS) == 0.4
    assert sl.toon_diffuse(0.6, THRESHOLDS, LEVELS) == 0.7
    assert sl.toon_diffuse(0.95, THRESHOLDS, LEVELS) == 1.0


def test_band_validation():
    assert sl.raises(lambda: sl.validate_bands((0.5, 0.2), (0.1, 0.4, 1.0)))       # not increasing
    assert sl.raises(lambda: sl.validate_bands((0.5, 0.5), (0.1, 0.4, 1.0)))       # not strictly
    assert sl.raises(lambda: sl.validate_bands((0.0, 0.5), (0.1, 0.4, 1.0)))       # 0 is not a threshold
    assert sl.raises(lambda: sl.validate_bands((0.5, 1.5), (0.1, 0.4, 1.0)))       # above 1
    assert sl.raises(lambda: sl.validate_bands((0.5,), (0.1, 0.4, 1.0)))           # levels count
    assert sl.raises(lambda: sl.validate_bands((0.5,), (0.4, 0.1)))                # levels not nondecreasing
    assert sl.raises(lambda: sl.validate_bands((0.5,), (0.4, 1.1)))                # level above 1
    assert sl.raises(lambda: sl.validate_bands(tuple(i / 20 for i in range(1, 18)), tuple(i / 20 for i in range(18))))
    assert sl.validate_bands(THRESHOLDS, LEVELS) is None
    assert sl.validate_bands((1.0,), (0.0, 1.0)) is None


def test_toon_shade_is_albedo_times_ambient_plus_band_times_light_clamped():
    assert _close(sl.toon_shade((1.0, 0.5, 0.25), (1.0, 1.0, 1.0), 0.6, THRESHOLDS, LEVELS, 0.1), (0.8, 0.4, 0.2))
    assert _close(sl.toon_shade((1.0, 1.0, 1.0), (2.0, 2.0, 2.0), 0.9, THRESHOLDS, LEVELS, 0.5), (1.0, 1.0, 1.0))
    assert _close(sl.toon_shade((0.5, 0.5, 0.5), (1.0, 0.0, 0.0), 0.0, THRESHOLDS, LEVELS, 0.0), (0.05, 0.0, 0.0))


def test_the_specular_band_is_a_step_on_the_blinn_phong_lobe():
    assert sl.toon_specular(Z, Z, Z, 32.0, 0.5) == 1.0
    tilted = (math.sqrt(0.5), 0.0, math.sqrt(0.5))
    assert sl.toon_specular(Z, tilted, Z, 32.0, 0.5) == 0.0
    assert sl.toon_specular(Z, tilted, Z, 4.0, 0.5) == 1.0
    assert sl.toon_specular(Z, (0.0, 0.0, -1.0), Z, 4.0, 0.5) == 0.0     # unlit side
    assert sl.raises(lambda: sl.toon_specular(Z, Z, Z, 0.0, 0.5))
    assert sl.raises(lambda: sl.toon_specular(Z, Z, Z, 4.0, 1.5))


def test_the_rim_band_lights_grazing_views():
    assert sl.rim(Z, Z, 0.7) == 0.0
    assert sl.rim(Z, (1.0, 0.0, 0.0), 0.7) == 1.0
    assert sl.rim(Z, (math.sqrt(0.5), 0.0, math.sqrt(0.5)), 0.3) == 0.0     # 1 - 0.7071 = 0.29 < 0.3
    assert sl.rim(Z, (math.sqrt(0.5), 0.0, math.sqrt(0.5)), 0.29) == 1.0


def test_flat_shade_is_the_albedo_untouched():
    assert sl.flat_shade((0.2, 0.4, 0.6)) == (0.2, 0.4, 0.6)


# ------------------------------------------------------------------------------------------------ edges

def test_boundary_edges_of_an_open_mesh_are_silhouettes():
    edges = sl.silhouette_edges(SQUARE_V, SQUARE_F, (0.0, 0.0, -1.0))
    assert edges == {(0, 1), (0, 2), (1, 3), (2, 3)}


def test_a_shared_edge_between_a_front_and_a_back_face_is_a_silhouette():
    assert sl.silhouette_edges(FOLD_V, FOLD_F, (0.0, 0.0, -1.0)) == {(0, 1), (0, 2), (1, 2), (0, 3), (1, 3)}
    # seen from above-front, both faces are front-facing: only the boundary remains
    assert (0, 1) not in sl.silhouette_edges(FOLD_V, FOLD_F, (0.0, 1.0, -1.0))


def test_face_normal_is_the_counter_clockwise_cross_product():
    assert sl.face_normal(FOLD_V, FOLD_F[0]) == (0.0, 0.0, 1.0)
    assert sl.face_normal(FOLD_V, FOLD_F[1]) == (0.0, -1.0, 0.0)


def test_crease_edges_are_shared_edges_folded_by_at_least_the_crease_angle():
    assert sl.crease_edges(FOLD_V, FOLD_F, 60.0) == {(0, 1)}
    assert sl.crease_edges(FOLD_V, FOLD_F, 90.0) == {(0, 1)}
    assert sl.crease_edges(FOLD_V, FOLD_F, 90.001) == set()
    assert sl.crease_edges(SQUARE_V, SQUARE_F, 1.0) == set()


def test_degenerate_faces_and_bad_indices_are_errors():
    assert sl.raises(lambda: sl.face_normal(SQUARE_V, (0, 0, 1)))
    assert sl.raises(lambda: sl.silhouette_edges(SQUARE_V, ((0, 1, 9),), (0.0, 0.0, -1.0)))
    assert sl.raises(lambda: sl.crease_edges(SQUARE_V, SQUARE_F, 0.0))


def test_the_depth_edge_is_on_the_near_side_only():
    depth = ((1.0, 1.0, 5.0), (1.0, 1.0, 5.0))
    assert sl.edge_mask(depth, None, 0.5, 0.2) == ((0, 1, 0), (0, 1, 0))


def test_the_normal_edge_is_on_both_sides():
    normals = (((0.0, 0.0, 1.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),)
    assert sl.edge_mask(None, normals, 0.5, 0.2) == ((0, 1, 1),)
    assert sl.edge_mask(None, normals, 0.5, 1.0) == ((0, 0, 0),)


def test_edge_mask_combines_depth_and_normals_and_checks_shapes():
    depth = ((1.0, 1.0, 5.0),)
    normals = (((0.0, 0.0, 1.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)),)
    assert sl.edge_mask(depth, normals, 0.5, 0.2) == ((0, 1, 0),)
    assert sl.raises(lambda: sl.edge_mask(depth, (((0.0, 0.0, 1.0),),), 0.5, 0.2))
    assert sl.raises(lambda: sl.edge_mask(None, None, 0.5, 0.2))
    assert sl.raises(lambda: sl.edge_mask(((1.0,), (1.0, 2.0)), None, 0.5, 0.2))


def test_the_outline_width_dilates_the_mask():
    mask = ((0, 0, 1, 0, 0),)
    assert sl.dilate(mask, 1.0) == ((0, 0, 1, 0, 0),)
    assert sl.dilate(mask, 2.0) == ((0, 1, 1, 1, 0),)
    assert sl.dilate(mask, 3.0) == ((0, 1, 1, 1, 0),)
    assert sl.dilate(mask, 5.0) == ((1, 1, 1, 1, 1),)
    assert sl.dilate(((0, 0, 0), (0, 1, 0), (0, 0, 0)), 3.0) == ((1, 1, 1), (1, 1, 1), (1, 1, 1))
    assert sl.dilate(mask, 0.0) == ((0, 0, 0, 0, 0),)
    assert sl.raises(lambda: sl.dilate(mask, -1.0))


def test_outline_radius():
    assert sl.outline_radius(1.0) == 0
    assert sl.outline_radius(2.0) == 1
    assert sl.outline_radius(3.0) == 1
    assert sl.outline_radius(4.0) == 2


# ------------------------------------------------------------------------------------------------ sketch

def test_a_line_sampled_on_whole_wavelengths_does_not_move():
    assert sl.wobble(LINE, 2.0, 10.0, 1) == LINE


def test_the_endpoints_of_an_open_path_are_fixed_and_the_taper_grows_over_a_wavelength():
    out = sl.wobble(LINE, 2.0, 20.0, 1)
    assert out[0] == LINE[0] and out[-1] == LINE[-1]
    assert all(p[0] == q[0] for p, q in zip(out, LINE))              # along the left normal (0, 1)
    assert _close(out[1][1], 2.0 * rs.N(1, 0, 0.5) * 0.5)
    assert _close(out[3][1], 2.0 * rs.N(1, 0, 1.5) * 1.0)
    assert _close(out[9][1], 2.0 * rs.N(1, 0, 4.5) * 0.5)
    assert out[2] == LINE[2]


def test_the_wobble_is_along_the_normal_of_the_path():
    vertical = tuple((0.0, 10.0 * i) for i in range(11))
    out = sl.wobble(vertical, 2.0, 20.0, 1)
    assert all(p[1] == q[1] for p, q in zip(out, vertical))
    assert _close(out[1][0], -2.0 * rs.N(1, 0, 0.5) * 0.5)          # left normal of (0, 1) is (-1, 0)


def test_wobble_is_deterministic_and_seed_and_channel_change_it():
    a = sl.wobble(LINE, 2.0, 20.0, 1)
    assert a == sl.wobble(LINE, 2.0, 20.0, 1)
    assert a != sl.wobble(LINE, 2.0, 20.0, 2)
    assert a != sl.wobble(LINE, 2.0, 20.0, 1, channel=1)
    assert sl.wobble(LINE, 0.0, 20.0, 1) == LINE


def test_a_closed_path_rounds_the_wavelength_to_whole_turns():
    square = ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0))      # perimeter 400
    assert sl.closed_wavelength(400.0, 30.0) == 400.0 / 13
    assert sl.closed_wavelength(400.0, 500.0) == 400.0
    out = sl.wobble(square, 2.0, 100.0, 7, closed=True)
    assert out[0] == square[0]                                          # s = 0 is a lattice point
    assert len(out) == 4
    # the corner at s = 100 is a lattice point too, so it stays
    assert out[1] == square[1]
    out = sl.wobble(square, 2.0, 150.0, 7, closed=True)                 # lambda' = 400 / 3
    s_over = 100.0 / (400.0 / 3)
    d = 2.0 * rs.N(7, 0, s_over)
    n = sl.vertex_normal(square, 1, True)
    assert _close(out[1], (square[1][0] + d * n[0], square[1][1] + d * n[1]))


def test_vertex_normals_are_left_normals_of_the_averaged_directions():
    square = ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0))
    assert _close(sl.vertex_normal(LINE, 0, False), (0.0, 1.0))
    assert _close(sl.vertex_normal(LINE, 5, False), (0.0, 1.0))
    assert _close(sl.vertex_normal(square, 1, True), (-math.sqrt(0.5), math.sqrt(0.5)))
    assert _close(sl.vertex_normal(square, 1, False), (-math.sqrt(0.5), math.sqrt(0.5)))
    assert _close(sl.vertex_normal(square, 0, False), (0.0, 1.0))
    assert _close(sl.vertex_normal(square, 0, True), (math.sqrt(0.5), math.sqrt(0.5)))


def test_wobble_validation():
    assert sl.raises(lambda: sl.wobble(((0.0, 0.0),), 2.0, 20.0, 1))
    assert sl.raises(lambda: sl.wobble(((0.0, 0.0), (0.0, 0.0)), 2.0, 20.0, 1))
    assert sl.raises(lambda: sl.wobble(LINE, -1.0, 20.0, 1))
    assert sl.raises(lambda: sl.wobble(LINE, 2.0, 0.0, 1))
    assert sl.raises(lambda: sl.wobble(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), 2.0, 20.0, 1, closed=True)) is False
    assert sl.raises(lambda: sl.wobble(((0.0, 0.0), (1.0, 0.0)), 2.0, 20.0, 1, closed=True))
    assert sl.raises(lambda: sl.wobble(tuple((float(i), 0.0) for i in range(sl.MAX_POINTS + 2)), 1.0, 20.0, 1))


def test_overdraw_is_one_wobble_per_pass_on_its_own_channel():
    passes = sl.overdraw(LINE, 3, 2.0, 20.0, 1)
    assert len(passes) == 3
    assert passes[0] == sl.wobble(LINE, 2.0, 20.0, 1, channel=0)
    assert passes[2] == sl.wobble(LINE, 2.0, 20.0, 1, channel=2)
    assert passes[0] != passes[1] != passes[2]
    assert sl.raises(lambda: sl.overdraw(LINE, 0, 2.0, 20.0, 1))
    assert sl.raises(lambda: sl.overdraw(LINE, sl.MAX_PASSES + 1, 2.0, 20.0, 1))


def test_the_boil_step_moves_every_pass_to_a_new_channel():
    assert sl.boil_channel(1, 2, 0.0, 0.0) == 1
    assert sl.boil_channel(1, 2, 10.0, 0.0) == 1
    assert sl.boil_channel(1, 2, 0.5, 4.0) == 5
    assert sl.boil_channel(0, 3, 0.4999999, 2.0) == 0
    assert sl.boil_channel(0, 3, 0.5, 2.0) == 3
    assert sl.boil_channel(0, 3, 0.1 * 3, 10.0) == 9              # 0.30000000000000004 * 10 under eps
    assert sl.raises(lambda: sl.boil_channel(2, 2, 0.0, 0.0))
    assert sl.raises(lambda: sl.boil_channel(0, 1, -1.0, 1.0))


def test_the_frame_alone_equals_the_frame_played():
    frames = [sl.overdraw(LINE, 2, 2.0, 20.0, 1, time=t, boil=4.0) for t in (0.0, 0.1, 0.25, 0.3, 0.5)]
    assert frames[0] == frames[1]
    assert frames[2] == frames[3] != frames[1]
    assert frames[4] == sl.overdraw(LINE, 2, 2.0, 20.0, 1, time=0.5, boil=4.0)
    assert frames[4][1] == sl.wobble(LINE, 2.0, 20.0, 1, channel=5)


def test_the_path_seed_is_the_element_seed_of_the_sketch_purpose():
    assert sl.path_seed(0, "p1", 5) == rs.E(0, "p1", 5, "sketch")
    assert sl.path_seed(0, "p1", None) == rs.E(0, "p1", None, "sketch")
    assert sl.path_seed(0, "p1", 5) != sl.path_seed(0, "p2", 5)


def test_marker_width_tapers_at_both_ends():
    assert sl.marker_width(0.0, 100.0, 4.0, 0.5) == 2.0
    assert sl.marker_width(100.0, 100.0, 4.0, 0.5) == 2.0
    assert _close(sl.marker_width(50.0, 100.0, 4.0, 0.5), 4.0)
    assert sl.marker_width(25.0, 100.0, 4.0, 0.0) == 4.0
    assert _close(sl.marker_width(25.0, 100.0, 4.0, 1.0), 4.0 * math.sqrt(0.5))
    assert sl.raises(lambda: sl.marker_width(0.0, 0.0, 4.0, 0.5))
    assert sl.raises(lambda: sl.marker_width(-1.0, 100.0, 4.0, 0.5))
    assert sl.raises(lambda: sl.marker_width(0.0, 100.0, 4.0, 1.5))


def test_hatch_segments_are_parallel_lines_clipped_to_the_box():
    segs = sl.hatch_segments((0.0, 0.0, 10.0, 10.0), 2.5, 0.0)
    assert len(segs) == 5
    assert all(_close(a[1], b[1]) for a, b in segs)                     # horizontal
    assert _close(segs[0], ((0.0, 0.0), (10.0, 0.0)))
    assert _close(segs[2], ((0.0, 5.0), (10.0, 5.0)))
    assert _close(segs[4], ((0.0, 10.0), (10.0, 10.0)))
    vertical = sl.hatch_segments((0.0, 0.0, 10.0, 10.0), 2.5, 90.0)
    assert len(vertical) == 5
    assert all(_close(a[0], b[0]) for a, b in vertical)
    diagonal = sl.hatch_segments((0.0, 0.0, 10.0, 10.0), 2.5, 45.0)
    assert len(diagonal) == 5
    assert _close(diagonal[2], ((0.0, 0.0), (10.0, 10.0)))
    assert all(_close(b[1] - a[1], b[0] - a[0]) for a, b in diagonal)


def test_hatch_validation():
    assert sl.raises(lambda: sl.hatch_segments((0.0, 0.0, 10.0, 10.0), 0.0, 0.0))
    assert sl.raises(lambda: sl.hatch_segments((0.0, 0.0, 0.0, 10.0), 2.5, 0.0))
    assert sl.raises(lambda: sl.hatch_segments((0.0, 0.0, 10.0, 10.0), 1e-6, 0.0))
    assert len(sl.hatch_segments((0.0, 0.0, 10.0, 10.0), 1.0, 180.0)) == 11


def test_hatch_layers_fall_with_the_band():
    assert sl.hatch_layers(0, 4) == 3
    assert sl.hatch_layers(3, 4) == 0
    assert sl.hatch_layers(0, 1) == 0
    assert sl.raises(lambda: sl.hatch_layers(4, 4))
    assert sl.hatch_angle(30.0, 2) == 150.0
    assert sl.hatch_angle(150.0, 1) == 30.0


def test_the_sketch_shading_of_a_surface_is_its_toon_band_and_hatching():
    sh = sl.sketch_surface(0.6, THRESHOLDS, LEVELS, (0.0, 0.0, 10.0, 10.0), 2.5, 0.0)
    assert sh["band"] == 2
    assert sh["layers"] == 1
    assert len(sh["segments"]) == 5
    assert sl.sketch_surface(0.95, THRESHOLDS, LEVELS, (0.0, 0.0, 10.0, 10.0), 2.5, 0.0)["segments"] == ()
    dark = sl.sketch_surface(0.0, THRESHOLDS, LEVELS, (0.0, 0.0, 10.0, 10.0), 2.5, 0.0)
    assert dark["layers"] == 3 and len(dark["segments"]) == 15


# ------------------------------------------------------------------------------------------------ the draft

@pytest.fixture(scope="module")
def draft():
    with open(DRAFT, encoding="utf-8") as fh:
        return fh.read()


def test_the_draft_has_the_srep_sections(draft):
    for section in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics", "## Rationale",
                    "## Rejected alternatives", "## Backwards compatibility", "## Engine impact", "## Conformance",
                    "### Numeric tests", "### Kit cases", "## Open issues", "## References", "## History"):
        assert section in draft, section
    assert "SREP:            0" in draft
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft


def test_the_draft_names_the_engine_card_and_the_looks(draft):
    assert "SR-74" in draft
    for word in ('"flat"', '"sketch"', '"toon"', '"photoreal"', "lookAssetType", "V17"):
        assert word in draft, word


def _rows(draft):
    start = draft.index("### Numeric tests")
    end = draft.index("### Kit cases")
    rows = re.findall(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", draft[start:end])
    return [(n, e, x) for n, e, x in rows if n != "Test" and not set(n) <= {"-"}]


def test_the_numeric_table_has_its_rows(draft):
    assert len(_rows(draft)) >= 30


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as fh:
        return _rows(fh.read())


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = sl.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert _close(got, want, 1e-9), name


def test_the_table_is_what_the_module_prints(draft, capsys):
    sl.main()
    printed = capsys.readouterr().out.strip().splitlines()
    rows = _rows(draft)
    assert len(printed) == len(rows)
    for line, (name, expr, expected) in zip(printed, rows):
        assert line == f"| {name} | `{expr}` | `{expected}` |", name
