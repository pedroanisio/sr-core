"""Tests of the draft SREP "Add cutaways, exploded views and surface flow to 3D objects"
(srep/srep-0000-cutaways.md) and of its reference implementation conformance/tools/cutaways_reference.py
(S5 of SREP 12, SRC-41).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "cutaways_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-cutaways.md")

_spec = importlib.util.spec_from_file_location("cutaways_reference", MODULE)
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)

Z_UP = cr.plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _norm(p):
    return math.sqrt(sum(c * c for c in p))


# ------------------------------------------------------------------------------------ meshes and their measures


def test_the_unit_box_is_closed_and_outward():
    m = cr.box()
    assert len(m) == 12
    assert cr.closed(m)
    assert _close(cr.volume(m), 1.0)
    assert _close(cr.area(m), 6.0)
    assert cr.bounds(m) == ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
    assert cr.centre(m) == (0.0, 0.0, 0.0)


def test_the_icosphere_converges_to_the_sphere():
    m = cr.icosphere(1.0, 3)
    assert cr.closed(m)
    assert len(m) == 20 * 4 ** 3
    assert 0.98 * 4 / 3 * math.pi < cr.volume(m) < 4 / 3 * math.pi
    for tri in m:
        for p in tri:
            assert _close(_norm(p), 1.0, 1e-12)


def test_the_cylinder_and_torus_are_closed():
    c = cr.cylinder(1.0, 2.0, 48)
    assert cr.closed(c)
    assert _close(cr.volume(c), 48 * 0.5 * math.sin(2 * math.pi / 48) * 2.0)
    t = cr.torus(2.0, 0.5, 48, 24)
    assert cr.closed(t)
    assert 0.98 * 2 * math.pi ** 2 * 2.0 * 0.25 < cr.volume(t) < 2 * math.pi ** 2 * 2.0 * 0.25


def test_an_open_mesh_is_not_closed():
    m = cr.box()[:-1]
    assert not cr.closed(m)


# ------------------------------------------------------------------------------------ rule 1 and 2: section planes


def test_the_plane_normalises_and_keeps_the_back():
    p = cr.plane((0.0, 0.0, 0.3), (0.0, 0.0, 2.0))
    assert _close(p["normal"], (0.0, 0.0, 1.0))
    assert _close(cr.signed_distance(p, (0.0, 0.0, 1.0)), 0.7)
    assert _close(cr.signed_distance(p, (5.0, -5.0, 0.3)), 0.0)
    q = cr.plane((0.0, 0.0, 0.3), (0.0, 0.0, 2.0), keep="front")
    assert _close(cr.signed_distance(q, (0.0, 0.0, 1.0)), -0.7)
    with pytest.raises(cr.CutawayError):
        cr.plane((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    with pytest.raises(cr.CutawayError):
        cr.plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), keep="left")


def test_the_offset_moves_the_plane_along_its_normal():
    p = cr.plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), offset=0.3)
    assert _close(cr.signed_distance(p, (0.0, 0.0, 0.3)), 0.0)
    cut = cr.section(cr.box(), [p])
    assert _close(cr.volume(cut["walls"] + cut["cap"]), 0.8)


def test_the_box_cut_keeps_the_volume_below_the_plane():
    p = cr.plane((0.0, 0.0, 0.3), (0.0, 0.0, 1.0))
    cut = cr.section(cr.box(), [p])
    m = cut["walls"] + cut["cap"]
    assert cr.closed(m)
    assert _close(cr.volume(m), 0.8, 1e-12)
    assert _close(cr.volume(cr.clipped(cr.box(), [p])), 0.8, 1e-12)
    assert _close(cr.bounds(m), ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.3)), 1e-12)


def test_the_cut_faces_lie_on_the_plane():
    p = cr.plane((0.1, -0.2, 0.3), (0.3, -0.4, 1.0))
    cut = cr.section(cr.box(), [p])
    assert cut["cap"], "the cut is capped"
    assert cr.on_plane(cut["cap"], p, 1e-12)
    assert cr.plane_test() == (True, True, True)
    for tri in cut["cap"]:
        n = cr.triangle_normal(tri)
        assert _close(n, p["normal"], 1e-9), "every cap triangle faces the removed side"


def test_the_two_sides_of_a_cut_sum_to_the_whole():
    for normal in ((0.0, 0.0, 1.0), (1.0, 1.0, 0.0), (0.3, -0.4, 1.0)):
        p = cr.plane((0.1, 0.0, 0.05), normal)
        q = cr.plane((0.1, 0.0, 0.05), normal, keep="front")
        a = cr.clipped(cr.box(), [p])
        b = cr.clipped(cr.box(), [q])
        assert cr.closed(a) and cr.closed(b)
        assert _close(cr.volume(a) + cr.volume(b), 1.0, 1e-12)
    assert cr.volume_test() == (True, True, True)


def test_the_diagonal_cut_has_the_closed_form_cap():
    p = cr.plane((0.0, 0.0, 0.0), (1.0, 1.0, 0.0))
    cut = cr.section(cr.box(), [p])
    assert _close(cr.volume(cut["walls"] + cut["cap"]), 0.5, 1e-12)
    assert _close(cr.cap_area(cut["loops"], p), math.sqrt(2.0), 1e-12)
    assert _close(cr.area(cut["cap"]), math.sqrt(2.0), 1e-12)
    assert len(cut["loops"]) == 1


def test_a_plane_outside_the_bounds_is_the_identity_or_nothing():
    m = cr.box()
    assert cr.clipped(m, [cr.plane((0.0, 0.0, 0.5), (0.0, 0.0, 1.0))]) == m
    assert cr.clipped(m, [cr.plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), offset=2.0)]) == m
    assert cr.clipped(m, [cr.plane((0.0, 0.0, -0.5), (0.0, 0.0, 1.0))]) == ()
    assert cr.clipped(m, [cr.plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), offset=-2.0)]) == ()
    assert cr.identity_test() == (True, True)


def test_sections_apply_in_sequence_and_remove_the_union_of_their_fronts():
    planes = [cr.plane((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), cr.plane((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))]
    m = cr.clipped(cr.box(), planes)
    assert cr.closed(m)
    assert _close(cr.volume(m), 0.25, 1e-12)
    assert cr.bounds(m) == ((-0.5, -0.5, -0.5), (0.0, 0.0, 0.5))
    assert cr.clipped(cr.box(), planes) == cr.clipped(cr.clipped(cr.box(), planes[:1]), planes[1:])


def test_the_sphere_cut_through_vertices_on_the_plane_stays_closed():
    m = cr.icosphere(1.0, 2)
    assert any(abs(p[2]) == 0.0 for tri in m for p in tri), "the subdivided icosahedron has equator vertices"
    cut = cr.section(m, [Z_UP])
    k = cut["walls"] + cut["cap"]
    assert cr.closed(k)
    assert _close(cr.volume(k), cr.volume(m) / 2, 1e-12)
    assert len(cut["loops"]) == 1
    assert cr.on_plane(cut["cap"], Z_UP, 1e-12)
    assert cr.sphere_test() == (True, True, True)


def test_the_torus_cut_has_an_annulus_cap_with_a_hole():
    t = cr.torus(2.0, 0.5, 48, 24)
    cut = cr.section(t, [Z_UP])
    assert len(cut["loops"]) == 2
    k = cut["walls"] + cut["cap"]
    assert cr.closed(k)
    assert _close(cr.volume(k), cr.volume(t) / 2, 1e-9)
    outer, inner = sorted((cr.loop_area(loop, Z_UP) for loop in cut["loops"]), key=abs, reverse=True)
    assert outer > 0 > inner, "the outer loop winds with the normal and the hole against it"
    assert _close(cr.cap_area(cut["loops"], Z_UP), outer + inner, 1e-12)
    assert _close(cr.area(cut["cap"]), outer + inner, 1e-9)
    assert cr.torus_test() == (True, True, True)


def test_an_open_mesh_gets_no_cap():
    m = cr.box()[:-2]
    cut = cr.section(m, [cr.plane((0.0, 0.0, 0.3), (0.0, 0.0, 1.0))])
    assert cut["cap"] == ()
    assert cut["loops"] == ()
    assert cut["walls"]


def test_an_uncapped_section_leaves_the_opening():
    p = cr.plane((0.0, 0.0, 0.3), (0.0, 0.0, 1.0))
    cut = cr.section(cr.box(), [p], cap=False)
    assert cut["cap"] == ()
    assert len(cut["loops"]) == 1
    assert not cr.closed(cut["walls"])


def test_the_section_bounds_are_enforced():
    planes = [cr.plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), offset=0.01 * i) for i in range(cr.MAX_SECTIONS + 1)]
    with pytest.raises(cr.CutawayError):
        cr.section(cr.box(), planes)
    assert cr.section(cr.box(), planes[: cr.MAX_SECTIONS])["walls"]
    with pytest.raises(cr.CutawayError):
        cr.section(cr.box() * (cr.MAX_TRIANGLES // 12 + 1), [Z_UP])


# ------------------------------------------------------------------------------------ rule 3: hatching


def test_hatch_lines_are_centred_between_spacings_and_clipped_to_the_cap():
    p = cr.plane((0.0, 0.0, 0.3), (0.0, 0.0, 1.0))
    cut = cr.section(cr.box(), [p])
    segs = cr.hatch(cut["loops"], p, 0.25, 0.0)
    assert len(segs) == 4
    for a, b in segs:
        assert _close(_norm([x - y for x, y in zip(a, b)]), 1.0, 1e-12)
        assert _close(a[2], 0.3, 1e-12) and _close(b[2], 0.3, 1e-12)
    assert _close(cr.hatch_length(segs), 4.0, 1e-12)
    segs90 = cr.hatch(cut["loops"], p, 0.25, 90.0)
    assert len(segs90) == 4 and _close(cr.hatch_length(segs90), 4.0, 1e-12)
    diag = cr.hatch(cut["loops"], p, 0.25, 45.0)
    want = math.sqrt(2.0) * sum(1.0 - abs(c) * math.sqrt(2.0) for c in (-0.625, -0.375, -0.125, 0.125, 0.375, 0.625))
    assert len(diag) == 6
    assert _close(cr.hatch_length(diag), want, 1e-9)
    assert cr.hatch_test() == (True, True, True)


def test_hatching_an_annulus_skips_the_hole():
    t = cr.torus(2.0, 0.5, 48, 24)
    cut = cr.section(t, [Z_UP])
    segs = cr.hatch(cut["loops"], Z_UP, 0.5, 0.0)
    assert segs
    for a, b in segs:
        mid = tuple((x + y) / 2 for x, y in zip(a, b))
        r = math.hypot(mid[0], mid[1])
        assert 1.5 - 1e-9 <= r <= 2.5 + 1e-9, "every hatch segment lies in the ring"


def test_hatching_bounds():
    p = cr.plane((0.0, 0.0, 0.3), (0.0, 0.0, 1.0))
    cut = cr.section(cr.box(), [p])
    with pytest.raises(cr.CutawayError):
        cr.hatch(cut["loops"], p, 0.0, 0.0)
    with pytest.raises(cr.CutawayError):
        cr.hatch(cut["loops"], p, 1.0 / (cr.MAX_HATCH + 10), 0.0)


# ------------------------------------------------------------------------------------ rule 4 to 6: exploded views


def _assembly():
    return {
        "hub": cr.part(cr.box((0.4, 0.4, 0.4))),
        "left": cr.part(cr.box((0.4, 0.4, 0.4), (-1.0, 0.0, 0.0))),
        "right": cr.part(cr.box((0.4, 0.4, 0.4), (1.0, 0.0, 0.0))),
        "top": cr.part(cr.box((0.4, 0.4, 0.4), (0.0, 2.0, 0.0))),
    }


def test_the_assembly_centre_is_the_centre_of_the_parts_bounds():
    parts = _assembly()
    assert cr.assembly_centre(parts) == (0.0, 1.0, 0.0)
    assert cr.part_centre(parts["top"]) == (0.0, 2.0, 0.0)


def test_exploded_parts_return_exactly():
    parts = _assembly()
    for mode in ("radial", "axis", "rank"):
        out = cr.explode(parts, 0.0, mode=mode, axis=(0.0, 1.0, 0.0))
        for name in parts:
            assert out[name] == parts[name]["mesh"], (mode, name)
    assert cr.return_test() == (True, True, True)


def test_radial_explode_moves_parts_from_the_centre_in_proportion():
    parts = _assembly()
    d = cr.displacements(parts, 0.5)
    assert d["hub"] == (0.0, -0.5, 0.0)
    assert d["left"] == (-0.5, -0.5, 0.0)
    assert d["right"] == (0.5, -0.5, 0.0)
    assert d["top"] == (0.0, 0.5, 0.0)
    d2 = cr.displacements(parts, 1.0)
    for name in parts:
        assert _close(d2[name], tuple(2 * c for c in d[name]), 1e-12), "linear in amount"
    out = cr.explode(parts, 0.5)
    assert cr.part_centre({"mesh": out["top"]}) == (0.0, 2.5, 0.0)


def test_explode_about_a_given_centre_and_with_factors_and_directions():
    parts = _assembly()
    d = cr.displacements(parts, 1.0, centre=(0.0, 0.0, 0.0))
    assert d["hub"] == (0.0, 0.0, 0.0)
    assert d["top"] == (0.0, 2.0, 0.0)
    parts["top"]["factor"] = 0.25
    parts["left"]["direction"] = (0.0, 0.0, 1.0)
    d = cr.displacements(parts, 1.0, centre=(0.0, 0.0, 0.0))
    assert d["top"] == (0.0, 0.5, 0.0)
    assert d["left"] == (0.0, 0.0, 1.0), "a direction override is used as given, scaled by amount and factor"


def test_axis_explode_keeps_only_the_component_along_the_axis():
    parts = _assembly()
    d = cr.displacements(parts, 1.0, mode="axis", axis=(0.0, 2.0, 0.0), centre=(0.0, 0.0, 0.0))
    assert d["left"] == (0.0, 0.0, 0.0)
    assert d["top"] == (0.0, 2.0, 0.0)
    with pytest.raises(cr.CutawayError):
        cr.displacements(parts, 1.0, mode="axis", axis=(0.0, 0.0, 0.0))
    with pytest.raises(cr.CutawayError):
        cr.displacements(parts, 1.0, mode="axis")


def test_rank_explode_staggers_parts_by_their_distance_from_the_centre():
    parts = _assembly()
    ranks = cr.ranks(parts, centre=(0.0, 0.0, 0.0))
    assert ranks == {"hub": 0, "left": 1, "right": 1, "top": 2}, "ties share a rank, as a dense ranking"
    d = cr.displacements(parts, 1.0, mode="rank", spacing=0.5, centre=(0.0, 0.0, 0.0))
    assert d["hub"] == (0.0, 0.0, 0.0)
    assert _close(d["left"], (-0.5, 0.0, 0.0), 1e-12)
    assert _close(d["right"], (0.5, 0.0, 0.0), 1e-12)
    assert _close(d["top"], (0.0, 1.0, 0.0), 1e-12)
    assert cr.rank_test() == (True, True)


def test_exploded_parts_separate_and_the_separation_amount_is_closed_form():
    parts = _assembly()
    for name in parts:
        parts[name]["mesh"] = cr.box((0.9, 0.9, 0.9), cr.part_centre(parts[name]))
    assert cr.overlap(parts["left"]["mesh"], parts["hub"]["mesh"]) is False
    close = {k: cr.part(cr.box((1.5, 1.5, 1.5), cr.part_centre(v))) for k, v in parts.items()}
    assert cr.overlap(close["left"]["mesh"], close["hub"]["mesh"]) is True
    out = cr.explode(close, 0.5, centre=(0.0, 0.0, 0.0))
    assert cr.overlap(out["left"], out["hub"]) is True, "touching parts still overlap (closed boxes)"
    out = cr.explode(close, 0.5 + 1e-9, centre=(0.0, 0.0, 0.0))
    assert cr.overlap(out["left"], out["hub"]) is False
    assert cr.separation_test() == (True, True)


def test_explode_bounds_and_errors():
    parts = _assembly()
    with pytest.raises(cr.CutawayError):
        cr.explode(parts, -0.1)
    with pytest.raises(cr.CutawayError):
        cr.explode(parts, 1.0, mode="spiral")
    with pytest.raises(cr.CutawayError):
        cr.explode({}, 1.0)
    big = {f"p{i}": cr.part(cr.box()) for i in range(cr.MAX_PARTS + 1)}
    with pytest.raises(cr.CutawayError):
        cr.explode(big, 1.0)


def test_sections_apply_after_the_explosion():
    parts = _assembly()
    p = cr.plane((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    out = cr.explode(parts, 1.0, centre=(0.0, 0.0, 0.0))
    shown = cr.cutaway(out, [p])
    assert set(shown) == {"hub", "left", "right"}, "the top part moved wholly above the plane and is removed"
    assert _close(cr.volume(shown["hub"]), 0.4 ** 3 / 2, 1e-12)


# ------------------------------------------------------------------------------------ rule 7 to 9: surface flow


def test_the_tangent_field_is_the_field_minus_its_normal_part():
    s = cr.sphere_surface(1.0)
    p = (0.0, 0.0, 1.0)
    assert s["project"]((0.0, 0.0, 3.0)) == (0.0, 0.0, 1.0)
    assert s["normal"](p) == (0.0, 0.0, 1.0)
    down = cr.uniform((0.0, 0.0, -1.0))
    assert cr.tangent(s, down, p) == (0.0, 0.0, 0.0)
    q = s["project"]((1.0, 0.0, 1.0))
    t = cr.tangent(s, down, q)
    assert _close(sum(a * b for a, b in zip(t, s["normal"](q))), 0.0, 1e-12)
    assert _close(_norm(t), math.sqrt(0.5), 1e-12)


def test_a_uniform_field_on_the_sphere_runs_down_a_meridian_to_the_pole():
    s = cr.sphere_surface(1.0)
    down = cr.uniform((0.0, 0.0, -1.0))
    start = (math.sin(math.pi / 6), 0.0, math.cos(math.pi / 6))
    line = cr.flow_line(s, down, start, 0.01, 1000)
    assert line[0] == start
    for p in line:
        assert _close(_norm(p), 1.0, 1e-12)
        assert p[1] == 0.0
    assert _close(line[-1], (0.0, 0.0, -1.0), 0.01)
    assert len(line) < 1000, "the line ends at the stagnation point, not at the step bound"
    expected = math.pi - math.pi / 6
    assert _close(cr.arc_length(line), expected, 0.02)
    assert cr.meridian_test() == (True, True, True)


def test_a_rotational_field_on_the_sphere_closes_on_its_latitude():
    s = cr.sphere_surface(1.0)
    spin = cr.field(lambda x, y, z: (-y, x, 0.0))
    z0 = 0.5
    start = (math.sqrt(1 - z0 * z0), 0.0, z0)
    line = cr.flow_line(s, spin, start, 0.01, 10000)
    assert cr.closes(line, 0.01)
    assert len(line) < 10000
    for p in line:
        assert _close(_norm(p), 1.0, 1e-12)
        assert _close(p[2], z0, 1e-4)
    assert _close(cr.arc_length(line), 2 * math.pi * math.sqrt(1 - z0 * z0), 0.02)
    assert cr.latitude_test() == (True, True, True)


def test_a_uniform_field_on_the_plane_and_the_cylinder_runs_straight():
    plane = cr.plane_surface(0.0)
    line = cr.flow_line(plane, cr.uniform((2.0, 0.0, 0.5)), (-1.0, 0.25, 0.0), 0.1, 20)
    assert len(line) == 21
    for i, p in enumerate(line):
        assert _close(p, (-1.0 + 0.1 * i, 0.25, 0.0), 1e-12)
    cyl = cr.cylinder_surface(1.0)
    line = cr.flow_line(cyl, cr.uniform((0.0, 0.0, 1.0)), (0.6, 0.8, 0.0), 0.1, 20)
    assert len(line) == 21
    for i, p in enumerate(line):
        assert _close(p, (0.6, 0.8, 0.1 * i), 1e-12)
    assert cr.straight_test() == (True, True)


def test_the_line_stops_where_the_field_reverses_or_vanishes():
    plane = cr.plane_surface(0.0)
    sink = cr.field(lambda x, y, z: (-x, -y, 0.0))
    line = cr.flow_line(plane, sink, (1.0, 0.0, 0.0), 0.1, 100)
    assert len(line) <= 12
    assert _close(line[-1], (0.0, 0.0, 0.0), 0.1)
    still = cr.flow_line(plane, cr.uniform((0.0, 0.0, 1.0)), (1.0, 0.0, 0.0), 0.1, 100)
    assert still == ((1.0, 0.0, 0.0),)


def test_evenly_spaced_lines_on_the_plane_are_the_parallel_family():
    plane = cr.plane_surface(0.0)
    lines = cr.flow_lines(plane, cr.uniform((1.0, 0.0, 0.0)), (0.0, 0.0, 0.0), 0.2, 0.1, 0.05, 1000, 100,
                          bounds=((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)))
    assert len(lines) == 11
    ys = sorted(round(line[0][1], 9) for line in lines)
    assert ys == [round(-1.0 + 0.2 * i, 9) for i in range(11)]
    for line in lines:
        assert all(p[1] == line[0][1] for p in line)
        assert _close(line[0][0], -1.0, 0.05 + 1e-9) and _close(line[-1][0], 1.0, 0.05 + 1e-9)
    assert cr.spacing_test() == (True, True)


def test_evenly_spaced_lines_on_the_sphere_keep_their_distance():
    s = cr.sphere_surface(1.0)
    down = cr.uniform((0.0, 0.0, -1.0))
    lines = cr.flow_lines(s, down, (1.0, 0.0, 0.0), 0.3, 0.15, 0.03, 1000, 100)
    assert 10 <= len(lines) <= 100
    for line in lines:
        for p in line:
            assert _close(_norm(p), 1.0, 1e-12)
    assert cr.min_separation(lines) >= 0.15 - 0.03 - 1e-9
    assert cr.flow_lines(s, down, (1.0, 0.0, 0.0), 0.3, 0.15, 0.03, 1000, 100) == lines, "deterministic"


def test_flow_bounds_and_errors():
    plane = cr.plane_surface(0.0)
    with pytest.raises(cr.CutawayError):
        cr.flow_line(plane, cr.uniform((1.0, 0.0, 0.0)), (0.0, 0.0, 0.0), 0.0, 10)
    with pytest.raises(cr.CutawayError):
        cr.flow_line(plane, cr.uniform((1.0, 0.0, 0.0)), (0.0, 0.0, 0.0), 0.1, cr.MAX_STEPS + 1)
    with pytest.raises(cr.CutawayError):
        cr.flow_lines(plane, cr.uniform((1.0, 0.0, 0.0)), (0.0, 0.0, 0.0), 0.2, 0.3, 0.05, 10, 10)
    with pytest.raises(cr.CutawayError):
        cr.flow_lines(plane, cr.uniform((1.0, 0.0, 0.0)), (0.0, 0.0, 0.0), 0.2, 0.1, 0.05, 10, cr.MAX_LINES + 1)
    with pytest.raises(cr.CutawayError):
        cr.flow_line(plane, cr.field(lambda x, y, z: (float("nan"), 0.0, 0.0)), (0.0, 0.0, 0.0), 0.1, 10)


def test_a_line_from_a_point_off_the_surface_starts_on_it():
    s = cr.sphere_surface(2.0)
    line = cr.flow_line(s, cr.uniform((0.0, 0.0, -1.0)), (0.0, 3.0, 4.0), 0.1, 10)
    assert _close(line[0], (0.0, 1.2, 1.6), 1e-12)


# ------------------------------------------------------------------------------------ the seek check


def test_every_construction_is_a_function_of_its_inputs_alone():
    parts = _assembly()
    p = cr.plane((0.0, 0.0, 0.1), (0.3, 0.2, 1.0), offset=0.05)
    first = cr.cutaway(cr.explode(parts, 0.7), [p])
    cr.cutaway(cr.explode(parts, 0.2), [cr.plane((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))])
    again = cr.cutaway(cr.explode(parts, 0.7), [p])
    assert first == again
    assert cr.seek_test() == (True, True)


# ------------------------------------------------------------------------------------ the draft and its table


@pytest.fixture(scope="module")
def draft():
    assert os.path.exists(DRAFT), "the draft SREP is missing"
    with open(DRAFT, encoding="utf-8") as f:
        return f.read()


def test_the_draft_has_the_srep_sections(draft):
    for heading in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics", "## Rationale",
                    "## Rejected alternatives", "## Backwards compatibility", "## Engine impact", "## Conformance",
                    "### Numeric tests", "### Kit cases", "## Open issues", "## References", "## History"):
        assert heading in draft, heading
    assert "SREP:            0" in draft
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft
    assert "... no" not in draft


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    assert "SR-85" in draft
    for word in ("section", "explode", "flow", "cap", "hatch", "offset", "keep", "amount", "radial", "rank", "part",
                 "streamlines", "separation", "tangent", "Jobard", "ear clipping", "even-odd", "V17", "CUT1", "CUT7",
                 "seek check", "cutaways_reference.py", "exploded parts return exactly", "cut faces lie on the plane",
                 "nacelle", "Runge", "stagnation", "corner cutaway", "Sutherland", "fields draft"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 30


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = cr.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or cr._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    cr.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())
