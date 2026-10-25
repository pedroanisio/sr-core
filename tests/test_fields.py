"""Tests of the draft SREP "Add fields and flow" (srep/srep-0000-fields.md) and of its reference module
conformance/tools/fields_reference.py: field sources (grid, complex, charges, dipole, wire), the operators,
RK4 streamlines, arrow glyphs, evenly spaced streamlines (Jobard and Lefer 1997), line integral convolution
(Cabral and Leedom 1993), phase portraits (Wegert 2012), the dipole line constant, charge and current lines,
and the SREP's numeric table against the module.
"""
import importlib.util
import math
import os
import re

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "fields_reference.py")
KIT = os.path.join(ROOT, "conformance", "tools", "fields_kit.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-fields.md")

spec = importlib.util.spec_from_file_location("fields_reference", MODULE)
fr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fr)
kspec = importlib.util.spec_from_file_location("fields_kit", KIT)
fk = importlib.util.module_from_spec(kspec)
kspec.loader.exec_module(fk)

UNIFORM = lambda x, y: (1.0, 0.0)          # noqa: E731
CIRCLE = lambda x, y: (-y, x)              # noqa: E731
BOX = (0.0, 0.0, 1.0, 1.0)


def _close(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b)) and len(a) == len(b)


# ------------------------------------------------------------------------------------------------ sources

def test_a_grid_field_is_exact_at_its_nodes_and_bilinear_between():
    f = fr.grid_sampler((((0.0, 0.0), (1.0, 0.0)), ((0.0, 1.0), (1.0, 1.0))), BOX)
    assert f(0.0, 0.0) == (0.0, 0.0)
    assert f(1.0, 0.0) == (1.0, 0.0)
    assert f(0.0, 1.0) == (0.0, 1.0)
    assert f(0.5, 0.5) == (0.5, 0.5)
    assert f(0.25, 1.0) == (0.25, 1.0)


def test_a_grid_field_is_zero_outside_its_box():
    f = fr.grid_sampler((((1.0, 1.0), (1.0, 1.0)), ((1.0, 1.0), (1.0, 1.0))), BOX)
    assert f(1.5, 0.5) == (0.0, 0.0)
    assert f(0.5, -0.1) == (0.0, 0.0)


def test_a_grid_needs_two_by_two_nodes_of_equal_rows():
    with pytest.raises(ValueError):
        fr.grid_sampler((((0.0, 0.0),),), BOX)
    with pytest.raises(ValueError):
        fr.grid_sampler((((0.0, 0.0), (1.0, 0.0)), ((0.0, 1.0),)), BOX)


def test_a_complex_function_is_a_vector_field():
    f = fr.complex_sampler(lambda z: z * z)
    assert f(1.0, 1.0) == (0.0, 2.0)
    assert f(0.0, 1.0) == (-1.0, 0.0)


def test_the_coulomb_field_of_one_charge_is_radial_and_falls_as_the_inverse_square():
    e = fr.charge_field(((0.0, 0.0, 1.0),), (2.0, 0.0))
    assert _close(e, (0.25, 0.0))
    e = fr.charge_field(((0.0, 0.0, -2.0),), (0.0, 1.0))
    assert _close(e, (0.0, -2.0))


def test_the_dipole_field_on_its_axis_and_equator():
    assert _close(fr.dipole_field((0.0, 2.0)), (0.0, 0.25))        # 2 m / r^3 on the axis
    assert _close(fr.dipole_field((2.0, 0.0)), (0.0, -0.125))      # -m / r^3 on the equator


def test_the_wire_field_circles_the_wire_and_falls_as_one_over_r():
    b = fr.wire_field((2.0, 0.0))
    assert _close(b, (0.0, 1.0 / (4.0 * math.pi)))
    b = fr.wire_field((0.0, 1.0), current=2.0)
    assert _close(b, (-1.0 / math.pi, 0.0))


def test_the_poynting_vector_of_an_in_plane_e_and_an_out_of_plane_b():
    assert fr.poynting((1.0, 0.0), 1.0) == (0.0, -1.0)
    assert fr.poynting((0.0, 2.0), 0.5) == (1.0, 0.0)


def test_the_point_source_and_vortex_fields():
    assert _close(fr.source_field((2.0, 0.0)), (0.5, 0.0))
    assert _close(fr.vortex_field((2.0, 0.0)), (0.0, 0.5))
    assert fr.source_field((0.0, 0.0)) == (0.0, 0.0)


# ------------------------------------------------------------------------------------------------ operators

def test_divergence_and_curl_by_central_differences():
    assert abs(fr.divergence(lambda x, y: (x, y), (0.3, 0.7)) - 2.0) < 1e-6
    assert abs(fr.curl(CIRCLE, (0.3, 0.7)) - 2.0) < 1e-6
    assert abs(fr.curl(lambda x, y: (x, y), (0.3, 0.7))) < 1e-6
    assert abs(fr.divergence(lambda x, y: fr.source_field((x, y)), (1.0, 0.0))) < 1e-6


# ------------------------------------------------------------------------------------------------ streamlines

def test_an_rk4_step_follows_the_unit_direction():
    assert _close(fr.rk4_step(UNIFORM, (0.0, 0.0), 0.5), (0.5, 0.0))
    assert _close(fr.rk4_step(lambda x, y: (3.0, 0.0), (0.0, 0.0), 0.5), (0.5, 0.0))
    assert fr.rk4_step(lambda x, y: (0.0, 0.0), (0.0, 0.0), 0.5) is None


def test_a_streamline_runs_both_ways_to_the_box():
    line = fr.streamline(UNIFORM, (0.5, 0.5), 0.25, 100, fr.inside_box(BOX))
    assert line == ((0.0, 0.5), (0.25, 0.5), (0.5, 0.5), (0.75, 0.5), (1.0, 0.5))


def test_a_streamline_stays_on_the_circle_of_a_rotation_field():
    line = fr.streamline(CIRCLE, (1.0, 0.0), 0.01, 100, lambda p: True, both=False)
    assert len(line) == 101
    assert abs(math.hypot(*line[-1]) - 1.0) < 1e-6


def test_a_streamline_stops_at_a_zero_and_at_the_step_bound():
    assert fr.streamline(lambda x, y: (0.0, 0.0), (0.0, 0.0), 0.1, 10, lambda p: True) == ((0.0, 0.0),)
    assert len(fr.streamline(UNIFORM, (0.0, 0.0), 0.1, 10, lambda p: True)) == 21


def test_a_streamline_stops_where_the_stop_test_says():
    line = fr.streamline(UNIFORM, (0.0, 0.0), 0.1, 100, lambda p: True, stop=lambda p: p[0] > 0.35, both=False)
    assert len(line) == 4   # 0, 0.1, 0.2, 0.3; the point at 0.4 is not added


def test_the_step_and_the_bound_are_positive():
    with pytest.raises(ValueError):
        fr.streamline(UNIFORM, (0.0, 0.0), 0.0, 10, lambda p: True)
    with pytest.raises(ValueError):
        fr.streamline(UNIFORM, (0.0, 0.0), 0.1, 0, lambda p: True)


# ------------------------------------------------------------------------------------------------ arrows

def test_an_arrow_has_a_shaft_along_the_vector_and_a_head_at_the_tip():
    shaft, head = fr.arrow((0.0, 0.0), (3.0, 4.0), 1.0, 10.0)
    assert shaft == ((0.0, 0.0), (3.0, 4.0))
    assert _close(head[0], (3.0, 4.0))
    assert _close(head[1], (1.5, 3.25))
    assert _close(head[2], (2.7, 2.35))


def test_an_arrow_is_scaled_and_clamped():
    shaft, _ = fr.arrow((1.0, 1.0), (3.0, 4.0), 2.0, 100.0)
    assert _close(shaft[1], (7.0, 9.0))
    shaft, _ = fr.arrow((0.0, 0.0), (30.0, 40.0), 1.0, 5.0)
    assert _close(shaft[1], (3.0, 4.0))


def test_a_zero_vector_draws_no_arrow():
    assert fr.arrow((0.0, 0.0), (0.0, 0.0), 1.0, 5.0) is None


def test_an_arrow_grid_samples_the_field_at_its_nodes():
    arrows = fr.arrow_grid(lambda x, y: (x, 0.0), BOX, 3, 2, 1.0, 10.0)
    assert len(arrows) == 6
    assert arrows[0] is None                             # the node at x = 0 has a zero vector
    assert arrows[2][0] == ((1.0, 0.0), (2.0, 0.0))


# ------------------------------------------------------------------------------------------------ Jobard–Lefer

def test_evenly_spaced_streamlines_of_a_uniform_field_are_d_sep_apart():
    lines = fr.evenly_spaced_streamlines(UNIFORM, BOX, 0.25)
    ys = sorted(round(line[0][1], 9) for line in lines)
    assert ys == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert fr.min_separation(lines) >= 0.25 - 1e-9


def test_the_first_streamline_starts_at_the_seed():
    lines = fr.evenly_spaced_streamlines(UNIFORM, BOX, 0.25, seed=(0.5, 0.4))
    assert any(abs(line[0][1] - 0.4) < 1e-9 for line in lines)


def test_evenly_spaced_streamlines_of_a_vortex_keep_the_test_distance():
    lines = fr.evenly_spaced_streamlines(CIRCLE, (-1.0, -1.0, 1.0, 1.0), 0.2)
    assert 3 <= len(lines) <= 200
    assert fr.min_separation(lines) >= 0.1 - 0.05 - 1e-9


def test_a_seed_on_a_zero_falls_back_to_the_grid_scan_and_the_scan_covers_the_box():
    lines = fr.evenly_spaced_streamlines(CIRCLE, (-1.0, -1.0, 1.0, 1.0), 0.5)   # the centre is a zero
    assert len(lines) >= 2
    # two separate regions: a field that vanishes on the line x = 0 keeps the first streamline on one side
    halves = lambda x, y: (0.0, 1.0) if abs(x) > 0.1 else (0.0, 0.0)   # noqa: E731
    lines = fr.evenly_spaced_streamlines(halves, (-1.0, -1.0, 1.0, 1.0), 0.5, seed=(-0.5, 0.0))
    assert any(line[0][0] > 0.1 for line in lines) and any(line[0][0] < -0.1 for line in lines)


def test_evenly_spaced_streamlines_are_bounded():
    lines = fr.evenly_spaced_streamlines(CIRCLE, (-1.0, -1.0, 1.0, 1.0), 0.05, max_lines=7)
    assert len(lines) == 7


def test_the_separation_must_be_positive_and_the_test_distance_smaller():
    with pytest.raises(ValueError):
        fr.evenly_spaced_streamlines(UNIFORM, BOX, 0.0)
    with pytest.raises(ValueError):
        fr.evenly_spaced_streamlines(UNIFORM, BOX, 0.25, d_test=0.3)


def test_min_separation_of_fewer_than_two_lines_is_infinite():
    assert fr.min_separation(()) == math.inf
    assert fr.min_separation((((0.0, 0.0), (1.0, 0.0)),)) == math.inf


# ------------------------------------------------------------------------------------------------ LIC

NOISE = ((0.2, 0.2, 0.2, 0.2), (0.8, 0.8, 0.8, 0.8))


def test_lic_along_a_horizontal_field_keeps_a_row_constant_noise():
    out = fr.lic(UNIFORM, NOISE, (0.0, 0.0, 4.0, 2.0), 1.0, 0.5)
    assert all(abs(a - b) < 1e-12 for ra, rb in zip(out, NOISE) for a, b in zip(ra, rb))


def test_lic_along_a_vertical_field_averages_the_rows():
    out = fr.lic(lambda x, y: (0.0, 1.0), NOISE, (0.0, 0.0, 4.0, 2.0), 1.0, 1.0)
    assert out == ((0.5, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5))


def test_lic_of_a_zero_field_is_the_noise():
    out = fr.lic(lambda x, y: (0.0, 0.0), NOISE, (0.0, 0.0, 4.0, 2.0), 1.0, 0.5)
    assert out == NOISE
    assert fr.lic(UNIFORM, NOISE, (0.0, 0.0, 4.0, 2.0), 0.4, 0.5) == NOISE   # a length below the step: no samples


def test_lic_needs_a_rectangular_noise_and_a_positive_length():
    with pytest.raises(ValueError):
        fr.lic(UNIFORM, ((0.2, 0.2), (0.8,)), (0.0, 0.0, 2.0, 2.0), 1.0, 0.5)
    with pytest.raises(ValueError):
        fr.lic(UNIFORM, NOISE, (0.0, 0.0, 4.0, 2.0), 0.0, 0.5)


# ------------------------------------------------------------------------------------------------ phase portraits

def test_the_phase_hue_turns_once_around_the_origin():
    assert fr.phase_hue(1.0) == 0.0
    assert fr.phase_hue(1j) == 0.25
    assert fr.phase_hue(-1.0) == 0.5
    assert fr.phase_hue(-1j) == 0.75
    assert fr.phase_hue(0.0) == 0.0


def test_the_modulus_shade_repeats_at_powers_of_two():
    assert fr.modulus_shade(1.0) == 0.0
    assert fr.modulus_shade(4.0) == 0.0
    assert abs(fr.modulus_shade(3.0) - (math.log2(3.0) - 1.0)) < 1e-12
    assert fr.modulus_shade(0.0) == 0.0


def test_the_winding_number_counts_zeros_minus_poles():
    assert fr.winding_number(lambda z: z * z, (0.0, 0.0), 1.0) == 2
    assert fr.winding_number(lambda z: 1.0 / z, (0.0, 0.0), 1.0) == -1
    assert fr.winding_number(lambda z: (z - 1.0) * (z + 1.0) / z, (0.0, 0.0), 2.0) == 1
    assert fr.winding_number(lambda z: (z - 1.0) * (z + 1.0) / z, (0.0, 0.0), 0.5) == -1
    assert fr.winding_number(lambda z: z - 3.0, (0.0, 0.0), 1.0) == 0


def test_a_zero_or_pole_on_the_circle_is_an_error():
    with pytest.raises(ValueError):
        fr.winding_number(lambda z: z - 1.0, (0.0, 0.0), 1.0)


# ------------------------------------------------------------------------------------------------ the shots

def test_the_dipole_line_constant_holds_along_a_field_line():
    assert abs(fr.dipole_line_constant((1.0, 1.0)) - 2.0 * math.sqrt(2.0)) < 1e-12
    assert fr.dipole_line_deviation((1.0, 1.0), 0.01, 200) < 1e-4


def test_the_dipole_constant_is_undefined_on_the_axis():
    with pytest.raises(ValueError):
        fr.dipole_line_constant((0.0, 2.0))


def test_field_lines_of_one_charge_are_rays_at_equal_angles():
    lines = fr.charge_lines(((0.0, 0.0, 1.0),), per_charge=8)
    assert len(lines) == 8
    for k, line in enumerate(lines):
        x, y = line[-1]
        want = 360.0 * k / 8
        got = math.degrees(math.atan2(y, x)) % 360.0
        assert abs((got - want + 180.0) % 360.0 - 180.0) < 1e-6
        assert math.hypot(x, y) > 4.9    # ends at the box


def test_field_lines_from_a_positive_charge_end_on_a_negative_one():
    charges = ((-1.0, 0.0, 1.0), (1.0, 0.0, -1.0))
    lines = fr.charge_lines(charges, per_charge=8)
    assert len(lines) == 8
    ends = [fr.line_ends_on(line, charges, 0.05) for line in lines]
    assert ends.count(1) >= 4 and all(e in (None, 1) for e in ends)
    assert all(math.hypot(line[-1][0] - 1.0, line[-1][1]) < 0.05 for line, e in zip(lines, ends) if e == 1)


def test_no_lines_leave_a_negative_charge():
    assert fr.charge_lines(((0.0, 0.0, -1.0),), per_charge=8) == ()


def test_current_lines_are_circles_about_the_wire():
    line = fr.streamline(lambda x, y: fr.wire_field((x, y)), (1.0, 0.0), 0.01, 700, lambda p: True, both=False)
    assert all(abs(math.hypot(*p) - 1.0) < 1e-6 for p in line)
    assert math.hypot(line[628][0] - 1.0, line[628][1]) < 0.01     # back at the start after 2 pi


# ------------------------------------------------------------------------------------------------ the draft

def _numeric_rows():
    text = open(DRAFT, encoding="utf-8").read()
    body = text.split("### Numeric tests", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in body.splitlines():
        m = re.match(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", line)
        if m and m.group(1) not in ("Test", "---"):
            rows.append((m.group(1), m.group(2), m.group(3)))
    return rows


def test_the_draft_exists_with_its_sections_and_a_table():
    text = open(DRAFT, encoding="utf-8").read()
    for section in ("## Abstract", "## Motivation", "### Syntax", "### Semantics", "## Rationale",
                    "## Rejected alternatives", "## Backwards compatibility", "## Engine impact", "### Numeric tests",
                    "### Kit cases", "## Open issues", "## References", "## History"):
        assert section in text, section
    assert len(_numeric_rows()) >= 30
    assert "Status:          Draft" in text and "SREP:            0" in text
    assert "SR-67" in text


def test_the_draft_closes_the_schema_gaps_of_the_engine_vendoring():
    # SRC-26, the eight gaps the engine found vendoring the draft (SR-67)
    text = open(DRAFT, encoding="utf-8").read()
    flat = re.sub(r"\n +", " ", text)   # the draft wraps at 110 columns
    syntax = flat.split("### Syntax", 1)[1].split("### Semantics", 1)[0]
    assert "`FLD3` and `FLD4` in one rule of context `field/portrait | field/contours | field/lines | field/streamlines`" in syntax
    assert "first matching rule only" in syntax
    assert "`V17`, the shared 1.8 gate of SREP 12" in syntax and "gains the clause `not(.//field)`" in syntax
    assert "| `stroke`, `strokeWidth` | `paintType`, `positiveDecimal` | `#FFFFFFFF`, 2 |" in syntax
    for child in ("arrows", "streamlines", "lines", "contours"):
        row = [line for line in text.splitlines() if line.startswith(f"| `{child}` |")]
        assert len(row) == 1 and "`stroke`, `strokeWidth` (the field's when absent)" in row[0], child
    assert "`cols`, `rows` (`xs:positiveInteger`, at most 1000, default 10)" in syntax
    assert "`perCharge` (`xs:positiveInteger`, at most 1000, default 8)" in syntax
    assert syntax.count("at most 4096") == 2   # lic and contours resolution
    assert "`scalar` takes `@u` without `@v`, or `@grid`; `complex` takes `@function` or `@w`" in syntax
    assert "`@coefficients` appears with `@function='mobius'` only and then holds eight numbers" in syntax
    assert "| `coefficients` | `numberListType` (xsd:94) |" in syntax
    assert "`base` (`xs:double` with `minExclusive` 1, default 2)" in syntax
    assert "`FLD5` on `field`: `ancestor::axes or (@width and @height)`" in syntax
    semantics = flat.split("### Semantics", 1)[1].split("## Rationale", 1)[0]
    assert "in the presentation's stroke" in semantics and "in the stroke's paint" not in semantics
    assert "`cols`, `rows` and `perCharge` at most 1000, `resolution` at most 4096" in semantics
    assert "2026-10-25: eight schema gaps the engine found vendoring the draft (SR-67)" in flat


def _rows_close(a, b):
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_rows_close(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


@pytest.mark.parametrize("name, expr, expected", _numeric_rows() if os.path.exists(DRAFT) else [])
def test_numeric_table_row(name, expr, expected):
    scope = {k: getattr(fr, k) for k in dir(fr) if not k.startswith("_")}
    scope["math"] = math
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "sum": sum, "all": all,
                             "any": any, "max": max, "min": min, "sorted": sorted, "complex": complex}
    got = eval(expr, scope)   # one scope: a lambda in a row looks its names up in the globals
    want = eval(expected, {"__builtins__": {}, "inf": math.inf, "nan": math.nan}, {})
    assert _rows_close(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(capsys):
    fr.main()
    out = capsys.readouterr().out
    printed = re.findall(r"^\| ([^|]+?) \| `([^`]+)` \| `([^`]+)` \|$", out, re.M)
    assert printed == _numeric_rows()


# ------------------------------------------------------------------------------------------------ wires (shot 2)

SEG = ((-1.0, 0.0), (1.0, 0.0))


def test_a_long_wire_has_the_point_current_field_out_of_the_plane():
    far = ((-1e9, 0.0), (1e9, 0.0))
    assert math.isclose(fr.line_field((0.0, 1.0), *far, i=1.0)[2], 1.0 / (2.0 * math.pi), rel_tol=1e-9)
    assert math.isclose(fr.line_field((0.0, -1.0), *far, i=1.0)[2], -1.0 / (2.0 * math.pi), rel_tol=1e-9)
    assert fr.line_field((0.0, 1.0), *far, i=1.0)[:2] == (0.0, 0.0)


def test_a_finite_wire_follows_biot_savart_and_the_line_charge_law():
    ex, ey, bz = fr.line_field((0.0, 1.0), *SEG, q=1.0, i=1.0)
    assert math.isclose(bz, math.sqrt(2.0) / (4.0 * math.pi), rel_tol=1e-12)        # Griffiths example 5.5
    assert math.isclose(ey, 2.0 * 1.0 / (1.0 * math.sqrt(2.0)), rel_tol=1e-12)      # Griffiths example 2.1
    assert abs(ex) < 1e-15
    ex2, ey2, bz2 = fr.line_field((0.0, -1.0), *SEG, q=1.0, i=1.0)
    assert math.isclose(ey2, -ey, rel_tol=1e-12) and math.isclose(bz2, -bz, rel_tol=1e-12)
    assert fr.line_field((0.5, 0.0), *SEG, q=1.0, i=1.0) == (0.0, 0.0, 0.0)          # on the wire


def test_the_shot_2_poynting_vector_points_from_the_source_to_the_load():
    sx, sy = fr.poynting_at((0.0, 0.0), (), (), fr.SHOT2_WIRES)
    assert sx > 0 and abs(sy) < 1e-12
    angles = [abs(fr.poynting_angle((x, y), (), (), fr.SHOT2_WIRES)) for x in (-0.5, -0.25, 0.0, 0.25, 0.5)
              for y in (-0.25, 0.0, 0.25)]
    assert max(angles) < 5.0 and max(angles) > 3.0
    assert abs(fr.poynting_angle((1.0, 0.25), (), (), fr.SHOT2_WIRES)) > 20.0      # the fringe past the window


def test_the_draft_declares_the_wire_source_and_the_poynting_presentation():
    text = open(DRAFT, encoding="utf-8").read()
    flat = re.sub(r"\n +", " ", text)
    assert "| `wire` | `x1`, `y1`, `x2`, `y2`, `q` (`xs:double`, default 0), `i` (`xs:double`, default 0) |" in flat
    assert "`show` (`field` | `poynting`, default `field`)" in flat
    assert "`FLD6` on `field/arrows[@show='poynting']`" in flat
    assert "(charge | current | dipole | wire)*" in flat
    assert "15 arrows" in flat and "within 5°" in flat
    assert "2026-10-25: the `wire` source and `arrows/@show=\"poynting\"`" in flat


# ------------------------------------------------------------------------------------------------ the kit cases

def _kit_rows():
    text = open(DRAFT, encoding="utf-8").read()
    body = text.split("### Kit cases", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `srep-<n>-(field-[a-z]+)\.xml` \|", body, re.M)


def test_the_kit_writes_the_six_cases_the_draft_names():
    import xml.etree.ElementTree as ET
    docs = fk.documents()
    assert list(docs) == _kit_rows() == fk.NAMES
    for name, xml in docs.items():
        root = ET.fromstring(xml)
        assert root.get("version") == "1.8"
        fields = root.findall(".//field")
        assert len(fields) == 1, name
        f = fields[0]
        assert f.get("width") and f.get("height") and f.get("xMin") and f.get("yMax"), name
    u = ET.fromstring(docs["field-uniform"]).find(".//field")
    assert (u.get("u"), u.get("v"), u.get("width"), u.get("height")) == ("1", "0", "400", "400")
    assert u.find("streamlines").get("separation") == "80"
    v = ET.fromstring(docs["field-vortex"]).find(".//field")
    assert (v.get("u"), v.get("v")) == ("-y", "x") and v.find("arrows").get("cols") == "5" == v.find("arrows").get("rows")
    d = ET.fromstring(docs["field-dipole"]).find(".//field")
    assert d.find("dipole") is not None and d.find("streamlines").get("maxLines") == "1"
    p = ET.fromstring(docs["field-portrait"]).find(".//field")
    assert p.get("kind") == "complex" and p.get("w") and p.find("portrait") is not None
    lic = ET.fromstring(docs["field-lic"]).find(".//field")
    assert (lic.get("u"), lic.get("v")) == ("1", "0") and lic.find("lic").get("resolution") == "4"
    assert lic.find("lic").get("seed") and (int(lic.get("width")), int(lic.get("height"))) == (400, 200)
    poy = ET.fromstring(docs["field-poynting"]).find(".//field")
    assert len(poy.findall("wire")) == 2 and poy.find("arrows").get("show") == "poynting"


def _blank(w=480, h=480):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_row_lines_finds_the_centroid_of_each_horizontal_line():
    a = _blank()
    for r in (119, 199, 279, 359, 439):
        a[r:r + 2, 40:440] = 255
    assert fk.row_lines(fk.lit(a)) == [120.0, 200.0, 280.0, 360.0, 440.0]
    assert fk.row_lines(fk.lit(_blank())) == []


def test_arrow_directions_run_from_the_node_to_the_glyph_centroid():
    from PIL import Image, ImageDraw
    S = 8                                                         # supersampled, then box-filtered: antialiased
    im = Image.new("RGB", (480 * S, 480 * S))
    dr = ImageDraw.Draw(im)
    nodes = [(100.0, 100.0), (300.0, 100.0), (100.0, 300.0), (300.0, 300.0)]
    angles = [0.0, 90.0, 225.0, -30.0]
    for (px, py), ang in zip(nodes, angles):
        dx, dy = math.cos(math.radians(ang)), -math.sin(math.radians(ang))
        tip = (px + 30 * dx, py + 30 * dy)
        dr.line([(px * S, py * S), (tip[0] * S, tip[1] * S)], fill=(255, 255, 255), width=2 * S)
        base = (tip[0] - 9 * dx, tip[1] - 9 * dy)
        left = (base[0] - 4.5 * dy, base[1] + 4.5 * dx)
        right = (base[0] + 4.5 * dy, base[1] - 4.5 * dx)
        dr.polygon([(x * S, y * S) for x, y in (tip, left, right)], fill=(255, 255, 255))
    im = im.resize((480, 480), Image.BOX)
    got = fk.arrow_directions(fk.lit(np.asarray(im)), nodes + [(200.0, 200.0)])
    assert got[-1] is None                                        # no glyph at the last node
    for g, want in zip(got, angles):
        assert abs((g - want + 180.0) % 360.0 - 180.0) < 1.0, (g, want)


def test_hue_winding_counts_the_turns_of_the_rendered_hue():
    import colorsys
    a = _blank(240, 240)
    c = (120.0, 120.0)
    for sign in (1, -1):
        for yy in range(240):
            for xx in range(240):
                ang = math.atan2(-(yy + 0.5 - c[1]), xx + 0.5 - c[0]) * sign
                r, g, b = colorsys.hls_to_rgb((ang / (2 * math.pi)) % 1.0, 0.5, 1.0)
                a[yy, xx] = (int(r * 255), int(g * 255), int(b * 255))
        assert fk.hue_winding(a, c, 80.0) == sign
    a[:] = 200
    assert fk.hue_winding(a, c, 80.0) == 0


def test_row_spread_reports_the_largest_spread_of_a_row_and_the_distinct_rows():
    a = _blank(480, 280)
    a[40:140, 40:440] = 60
    a[140:240, 40:440] = 180
    assert fk.row_spread(a, (40, 40, 400, 200)) == (0, 2)
    a[100, 300] = 63
    assert fk.row_spread(a, (40, 40, 400, 200)) == (3, 3)


def test_curve_distance_measures_the_lit_pixels_against_r_equals_c_sine_squared():
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (480, 480))
    dr = ImageDraw.Draw(im)
    c, ppu = (240.0, 240.0), 200.0
    pts = []
    for k in range(1, 180):
        th = math.radians(k)
        r = 0.5 * math.sin(th) ** 2
        pts.append((c[0] + r * math.sin(th) * ppu, c[1] - r * math.cos(th) * ppu))   # theta from the +y axis
    dr.line(pts, fill=(255, 255, 255), width=2)
    angles = [30 + 120 * k / 19 for k in range(20)]
    assert fk.curve_distance(fk.lit(np.asarray(im)), c, ppu, 0.5, angles) < 1.5
    im2 = Image.new("RGB", (480, 480))
    ImageDraw.Draw(im2).ellipse([140, 140, 340, 340], outline=(255, 255, 255), width=2)
    assert fk.curve_distance(fk.lit(np.asarray(im2)), c, ppu, 0.5, angles) > 5.0


def test_the_kit_runs_an_engine_and_reports_every_case(tmp_path):
    from PIL import Image
    calls = []

    def fake_exec(cmd, **kw):
        calls.append(cmd)
        out = cmd[cmd.index("-o") + 1]
        if "poynting" in cmd[2]:
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "error[E0001]: unknown attribute show"})()
        for path in ([out] if "%04d" not in out else [out % k for k in range(3)]):
            Image.new("RGB", (480, 480)).save(path)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    report = fk.run("fake-engine", str(tmp_path), exec=fake_exec)
    assert list(report) == fk.NAMES
    assert all(c[0] == "fake-engine" and c[1] == "render" for c in calls)
    assert report["field-poynting"]["error"].startswith("error[E0001]")
    assert report["field-uniform"]["pass"] is False and report["field-uniform"]["lines"] == []
    assert report["field-vortex"]["seek"] is True            # frame 2 alone equals frame 2 of 0..2
    assert os.path.exists(os.path.join(str(tmp_path), "srep-0000-field-uniform.xml"))
    table = fk.table(report)
    assert table.count("\n") == len(fk.NAMES) + 1 and "| field-poynting |" in table


def test_the_draft_records_every_kit_case_measured_on_one_engine_commit():
    text = open(DRAFT, encoding="utf-8").read()
    body = text.split("### Kit cases", 1)[1].split("\n## ", 1)[0]
    cells = re.findall(r"^\| `srep-<n>-field-[a-z]+\.xml` \| (?:[^|]|\\\|)* \| ([^|]*) \|$", body, re.M)
    assert len(cells) == len(fk.NAMES)
    for cell in cells:
        assert cell.startswith("measured on scene-render feat/sr-67-fields 4f086d9 (0.8.0, llvmpipe): ")
        assert cell.endswith("; pass")
    assert "refuses" not in body
    assert "feat/sr-67-fields at 4f086d9 (which vendors the draft as of f6cf12f, with the" in body
    assert "the worst 3.51°" in cells[-1]
