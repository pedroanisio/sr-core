"""Tests of the draft SREP "Add stylised characters" (srep/srep-0000-characters.md) and of its reference
module conformance/tools/characters_reference.py: area-preserving squash and stretch in 2D, volume-preserving
squash and stretch in 3D, the floor contact under squash, velocity-driven stretch, eyes (pupil travel, lids,
blinks) in 2D and 3D, the bounce rig, and the SREP's numeric table against the module.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "characters_reference.py")
STREAMS = os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-characters.md")

spec = importlib.util.spec_from_file_location("characters_reference", MODULE)
ch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ch)

spec_rs = importlib.util.spec_from_file_location("random_streams_reference", STREAMS)
rs = importlib.util.module_from_spec(spec_rs)
spec_rs.loader.exec_module(rs)

SQUARE = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
CUBE_V = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
          (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0))
CUBE_F = ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
          (2, 3, 7), (2, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5))


def _close(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], tol) for k in a)
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


# ------------------------------------------------------------------------------------------------ 2D

def test_squash_scales_in_2d_preserve_area():
    assert ch.scales_2d("squash", 0.5, "y") == (2.0, 0.5)
    assert ch.scales_2d("squash", 0.5, "x") == (0.5, 2.0)
    assert ch.scales_2d("stretch", 1.0, "y") == (0.5, 2.0)
    assert ch.scales_2d("stretch", 0.0, "y") == (1.0, 1.0)
    for kind, amount in (("squash", 0.3), ("stretch", 0.7)):
        sx, sy = ch.scales_2d(kind, amount, "y")
        assert _close(sx * sy, 1.0)


def test_deform_points_squashes_about_the_center():
    out = ch.deform_points(SQUARE, "squash", 0.5, "y", (1.0, 1.0))
    assert _close(out, ((-1.0, 0.5), (3.0, 0.5), (3.0, 1.5), (-1.0, 1.5)))
    assert _close(ch.polygon_area(out), ch.polygon_area(SQUARE))
    assert ch.deform_points(SQUARE, "squash", 0.0, "y", (1.0, 1.0)) == SQUARE


def test_polygon_area_is_the_shoelace_absolute():
    assert ch.polygon_area(SQUARE) == 4.0
    assert ch.polygon_area(tuple(reversed(SQUARE))) == 4.0
    assert _close(ch.polygon_area(((0.0, 0.0), (3.0, 0.0), (0.0, 4.0))), 6.0)
    assert ch.raises(lambda: ch.polygon_area(((0.0, 0.0), (1.0, 1.0))))


def test_the_floor_contact_stays_under_squash():
    out = ch.squash_on_floor(SQUARE, 0.4, 2.0)
    assert all(_close(p[1], 2.0) for p in out if p[1] > 1.9)
    assert _close(out[0], (1.0 - 1.0 / 0.6, 0.8))
    assert _close(ch.polygon_area(out), 4.0)
    assert ch.raises(lambda: ch.squash_on_floor(SQUARE, 1.0, 2.0))


def test_deform_validation():
    assert ch.raises(lambda: ch.scales_2d("squash", 1.0, "y"))
    assert ch.raises(lambda: ch.scales_2d("squash", -0.1, "y"))
    assert ch.raises(lambda: ch.scales_2d("stretch", -0.1, "y"))
    assert ch.raises(lambda: ch.scales_2d("bend", 0.1, "y"))
    assert ch.raises(lambda: ch.scales_2d("squash", 0.1, "z"))
    assert ch.raises(lambda: ch.scales_2d("stretch", ch.MAX_STRETCH + 1.0, "y"))


# ------------------------------------------------------------------------------------------------ 3D

def test_squash_scales_in_3d_preserve_volume():
    sx, sy, sz = ch.scales_3d("squash", 0.5, "y")
    assert _close((sx, sy, sz), (math.sqrt(2.0), 0.5, math.sqrt(2.0)))
    assert _close(sx * sy * sz, 1.0)
    sx, sy, sz = ch.scales_3d("stretch", 1.0, "z")
    assert _close((sx, sy, sz), (math.sqrt(0.5), math.sqrt(0.5), 2.0))
    assert ch.scales_3d("squash", 0.0, "x") == (1.0, 1.0, 1.0)
    assert ch.raises(lambda: ch.scales_3d("squash", 0.5, "velocity"))


def test_mesh_volume_by_the_divergence_theorem():
    assert _close(ch.mesh_volume(CUBE_V, CUBE_F), 1.0)
    inside_out = tuple((a, c, b) for a, b, c in CUBE_F)
    assert _close(ch.mesh_volume(CUBE_V, inside_out), -1.0)
    assert ch.raises(lambda: ch.mesh_volume(CUBE_V, ((0, 1, 9),)))


def test_deform_vertices_keeps_the_volume():
    for kind, amount, axis in (("squash", 0.5, "y"), ("stretch", 2.0, "x"), ("squash", 0.9, "z")):
        out = ch.deform_vertices(CUBE_V, kind, amount, axis, (0.5, 0.5, 0.5))
        assert _close(ch.mesh_volume(out, CUBE_F), 1.0)
    out = ch.deform_vertices(CUBE_V, "squash", 0.5, "y", (0.5, 0.5, 0.5))
    assert _close(out[6], (0.5 + 0.5 * math.sqrt(2.0), 0.75, 0.5 + 0.5 * math.sqrt(2.0)))


def test_a_squashed_sphere_sdf_keeps_its_volume_by_the_inverse_map():
    f = ch.squashed_sdf(lambda p: math.sqrt(sum(c * c for c in p)) - 1.0, "squash", 0.5, "y", (0.0, 0.0, 0.0))
    assert _close(f((0.0, 0.5, 0.0)), 0.0)                  # the pole moves in
    assert _close(f((math.sqrt(2.0), 0.0, 0.0)), 0.0)       # the equator moves out
    assert f((0.0, 0.0, 0.0)) < 0.0


# ------------------------------------------------------------------------------------------------ velocity

def test_velocity_is_the_backward_difference_from_the_declared_start():
    pos = lambda t: (10.0 * t, 5.0 * t * t)   # noqa: E731
    assert _close(ch.velocity(pos, 1.0, 0.1), (10.0, 9.5))
    assert ch.velocity(pos, 0.0, 0.1) == (0.0, 0.0)
    assert ch.velocity(pos, 0.05, 0.1) == (0.0, 0.0)
    assert ch.velocity(pos, 1.0, 0.1, start=0.95) == (0.0, 0.0)
    assert ch.raises(lambda: ch.velocity(pos, 1.0, 0.0))


def test_velocity_stretch_is_gain_times_speed_up_to_the_amount():
    assert _close(ch.velocity_stretch((30.0, 40.0), 0.01, 0.4), (0.4, 53.13010235415598))
    assert _close(ch.velocity_stretch((30.0, 40.0), 0.001, 0.4), (0.05, 53.13010235415598))
    assert ch.velocity_stretch((0.0, 0.0), 0.01, 0.4) == (0.0, 0.0)
    assert _close(ch.velocity_stretch((0.0, -1.0), 1.0, 0.4), (0.4, -90.0))
    assert ch.raises(lambda: ch.velocity_stretch((1.0, 0.0), -1.0, 0.4))


def test_stretch_along_an_angle_rotates_scales_and_rotates_back():
    assert _close(ch.stretch_along(((1.0, 0.0), (0.0, 1.0)), 1.0, 0.0, (0.0, 0.0)), ((2.0, 0.0), (0.0, 0.5)))
    assert _close(ch.stretch_along(((1.0, 0.0), (0.0, 1.0)), 1.0, 90.0, (0.0, 0.0)), ((0.5, 0.0), (0.0, 2.0)))
    out = ch.stretch_along(SQUARE, 0.5, 30.0, (1.0, 1.0))
    assert _close(ch.polygon_area(out), 4.0)
    assert ch.stretch_along(SQUARE, 0.0, 30.0, (1.0, 1.0)) == SQUARE


# ------------------------------------------------------------------------------------------------ eyes

def test_the_pupil_moves_toward_the_target_within_its_travel():
    assert _close(ch.pupil_offset((0.0, 0.0), (100.0, 0.0), 10.0, 4.0), (6.0, 0.0))
    assert _close(ch.pupil_offset((0.0, 0.0), (3.0, 4.0), 10.0, 4.0), (3.0, 4.0))
    assert _close(ch.pupil_offset((0.0, 0.0), (100.0, 0.0), 10.0, 4.0, travel=0.5), (3.0, 0.0))
    assert _close(ch.pupil_offset((0.0, 0.0), (30.0, 40.0), 10.0, 4.0, travel=0.5), (1.8, 2.4))
    assert ch.pupil_offset((5.0, 5.0), (5.0, 5.0), 10.0, 4.0) == (0.0, 0.0)
    assert ch.pupil_offset((5.0, 5.0), None, 10.0, 4.0) == (0.0, 0.0)


def test_eye_validation():
    assert ch.raises(lambda: ch.pupil_offset((0.0, 0.0), (1.0, 0.0), 4.0, 4.0))
    assert ch.raises(lambda: ch.pupil_offset((0.0, 0.0), (1.0, 0.0), 10.0, 0.0))
    assert ch.raises(lambda: ch.pupil_offset((0.0, 0.0), (1.0, 0.0), 10.0, 4.0, travel=1.5))
    assert ch.raises(lambda: ch.visible_area(10.0, 1.5))
    assert ch.raises(lambda: ch.lid_line(0.0, 10.0, -0.1))


def test_the_lid_comes_down_from_the_top():
    assert ch.lid_line(50.0, 10.0, 1.0) == 40.0
    assert ch.lid_line(50.0, 10.0, 0.5) == 50.0
    assert ch.lid_line(50.0, 10.0, 0.0) == 60.0


def test_the_visible_area_is_the_circular_segment_below_the_lid():
    assert _close(ch.visible_area(10.0, 1.0), 100.0 * math.pi)
    assert _close(ch.visible_area(10.0, 0.5), 50.0 * math.pi)
    assert ch.visible_area(10.0, 0.0) == 0.0
    assert _close(ch.visible_area(10.0, 0.25), 100.0 * math.acos(0.5) - 5.0 * math.sqrt(75.0))


def test_the_3d_pupil_sits_on_the_sphere_toward_the_target_within_the_travel_angle():
    assert _close(ch.pupil_center_3d((0.0, 0.0, 0.0), 10.0, 4.0, (0.0, 0.0, 50.0)), (0.0, 0.0, 8.0))
    assert _close(ch.pupil_center_3d((0.0, 0.0, 0.0), 10.0, 4.0, (100.0, 0.0, 0.0)), (8.0, 0.0, 0.0))
    assert _close(ch.pupil_center_3d((0.0, 0.0, 0.0), 10.0, 4.0, (100.0, 0.0, 0.0), travel=0.5),
                  (8.0 * math.sqrt(0.5), 0.0, 8.0 * math.sqrt(0.5)))
    assert _close(ch.pupil_center_3d((1.0, 2.0, 3.0), 10.0, 4.0, None), (1.0, 2.0, 11.0))
    assert _close(ch.pupil_center_3d((0.0, 0.0, 0.0), 10.0, 4.0, (0.0, 0.0, -50.0)), (0.0, 0.0, 8.0))
    assert _close(ch.pupil_center_3d((0.0, 0.0, 0.0), 10.0, 4.0, (0.0, 0.0, 50.0), forward=(1.0, 0.0, 0.0),
                                     travel=0.5), (8.0 * math.sqrt(0.5), 0.0, 8.0 * math.sqrt(0.5)))


def test_blinks_are_seeded_and_triangular():
    period, duration, seed = 4.0, 0.2, 3
    s0 = rs.U(seed, 0, 0) * (period - duration)
    assert ch.blink_start(0, period, duration, seed) == s0
    assert ch.blink_start(1, period, duration, seed) == period + rs.U(seed, 0, 1) * (period - duration)
    assert ch.blink_open(s0, period, duration, seed) == 1.0
    assert _close(ch.blink_open(s0 + 0.05, period, duration, seed), 0.5)
    assert _close(ch.blink_open(s0 + 0.1, period, duration, seed), 0.0)
    assert _close(ch.blink_open(s0 + 0.15, period, duration, seed), 0.5)
    assert ch.blink_open(s0 + 0.2, period, duration, seed) == 1.0
    assert ch.blink_open(s0 - 0.01, period, duration, seed) == 1.0
    assert ch.blink_open(-1.0, period, duration, seed) == 1.0
    assert ch.blink_open(s0 + 0.1, period, duration, seed, start=10.0) == 1.0
    assert _close(ch.blink_open(10.0 + s0 + 0.1, period, duration, seed, start=10.0), 0.0)


def test_blink_validation_and_determinism():
    assert ch.raises(lambda: ch.blink_open(1.0, 1.0, 1.0, 3))
    assert ch.raises(lambda: ch.blink_open(1.0, 1.0, 0.0, 3))
    assert ch.raises(lambda: ch.blink_open(1.0, 0.0, 0.1, 3))
    assert ch.raises(lambda: ch.blink_start(-1, 4.0, 0.2, 3))
    a = [ch.blink_open(t / 10.0, 4.0, 0.2, 3) for t in range(100)]
    assert a == [ch.blink_open(t / 10.0, 4.0, 0.2, 3) for t in range(100)]
    assert a != [ch.blink_open(t / 10.0, 4.0, 0.2, 4) for t in range(100)]
    assert ch.blink_open(2.0, 4.0, 0.2, None) == 1.0            # no period: never blinks
    assert ch.blink_open(2.0, None, 0.2, 3) == 1.0


def test_the_open_eye_at_a_frame_is_the_blink_times_the_authored_open():
    period, duration, seed = 4.0, 0.2, 3
    s0 = rs.U(seed, 0, 0) * (period - duration)
    assert _close(ch.eye_open(0.6, s0 + 0.05, period, duration, seed), 0.3)
    assert ch.eye_open(0.6, 1000.0 + s0 + 0.1, None, duration, seed) == 0.6


# ------------------------------------------------------------------------------------------------ bounce

def test_the_hop_is_a_parabola_of_the_period():
    assert ch.hop(0.0, 100.0, 2.0) == (0.0, 200.0)
    assert ch.hop(1.0, 100.0, 2.0) == (100.0, 0.0)
    assert ch.hop(0.5, 100.0, 2.0) == (75.0, 100.0)
    assert ch.hop(2.5, 100.0, 2.0) == (75.0, 100.0)
    assert ch.raises(lambda: ch.hop(0.5, 100.0, 0.0))
    assert ch.raises(lambda: ch.hop(-0.5, 100.0, 2.0))


def test_the_bounce_rig_squashes_in_contact_and_stretches_in_flight():
    rig = ch.bounce_rig(0.0, 100.0, 2.0, contact=0.2, squash_max=0.3, gain=0.002, stretch_max=0.5)
    assert rig == {"y": 0.0, "kind": "squash", "amount": 0.3}
    rig = ch.bounce_rig(0.1, 100.0, 2.0, contact=0.2, squash_max=0.3, gain=0.002, stretch_max=0.5)
    assert _close(rig, {"y": 19.0, "kind": "squash", "amount": 0.015})
    rig = ch.bounce_rig(0.5, 100.0, 2.0, contact=0.2, squash_max=0.3, gain=0.002, stretch_max=0.5)
    assert _close(rig, {"y": 75.0, "kind": "stretch", "amount": 0.2})
    rig = ch.bounce_rig(1.0, 100.0, 2.0, contact=0.2, squash_max=0.3, gain=0.002, stretch_max=0.5)
    assert _close(rig, {"y": 100.0, "kind": "stretch", "amount": 0.0})
    rig = ch.bounce_rig(0.5, 100.0, 2.0, contact=0.2, squash_max=0.3, gain=0.01, stretch_max=0.5)
    assert _close(rig["amount"], 0.5)
    assert ch.raises(lambda: ch.bounce_rig(0.5, 100.0, 2.0, contact=1.0, squash_max=0.3, gain=0.01, stretch_max=0.5))
    assert ch.raises(lambda: ch.bounce_rig(0.5, 100.0, 2.0, contact=0.2, squash_max=1.0, gain=0.01, stretch_max=0.5))


def test_the_bounce_rig_frame_alone_equals_the_frame_played():
    played = [ch.bounce_rig(k * 0.05, 100.0, 2.0, contact=0.2, squash_max=0.3, gain=0.002, stretch_max=0.5)
              for k in range(80)]
    assert played[37] == ch.bounce_rig(37 * 0.05, 100.0, 2.0, contact=0.2, squash_max=0.3, gain=0.002, stretch_max=0.5)
    out = ch.deform_points(SQUARE, played[37]["kind"], played[37]["amount"], "y", (1.0, 1.0))
    assert _close(ch.polygon_area(out), 4.0)


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


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    assert "SR-75" in draft
    for word in ("eyeType", 'shape="eye"', 'axis="velocity"', "V17", "1 / sqrt(s)", "seek check"):
        assert word in draft, word


def _rows(draft):
    start = draft.index("### Numeric tests")
    end = draft.index("### Kit cases")
    rows = re.findall(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", draft[start:end])
    return [(n, e, x) for n, e, x in rows if n != "Test" and not set(n) <= {"-"}]


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as fh:
        return _rows(fh.read())


def test_the_numeric_table_has_its_rows(draft):
    assert len(_rows(draft)) >= 30


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = ch.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert _close(got, want, 1e-9), name


def test_the_table_is_what_the_module_prints(draft, capsys):
    ch.main()
    printed = capsys.readouterr().out.strip().splitlines()
    rows = _rows(draft)
    assert len(printed) == len(rows)
    for line, (name, expr, expected) in zip(printed, rows):
        assert line == f"| {name} | `{expr}` | `{expected}` |", name
