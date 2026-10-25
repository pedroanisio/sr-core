"""Tests of the draft SREP "Add space transforms" (MF2 of SREP 12) and its reference module.

The reference module is conformance/tools/space_transforms_reference.py; the draft is srep/srep-0000-space-transforms.md.
The numeric table of the draft's Conformance section is parsed back here and every row is evaluated against the
module, and the module's main() must print exactly that table.
"""
import cmath
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "space_transforms_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-space-transforms.md")

_spec = importlib.util.spec_from_file_location("space_transforms_reference", MODULE)
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)


def _close_pt(a, b, tol=1e-9):
    return len(a) == len(b) and all(math.isclose(x, y, rel_tol=tol, abs_tol=tol) for x, y in zip(a, b))


# ------------------------------------------------------------------------------------------------ matrix maps

def test_the_identity_matrix_moves_nothing():
    assert st.matrix_map((1, 0, 0, 1, 0, 0), (3.0, 4.0)) == (3.0, 4.0)


def test_the_matrix_follows_the_svg_convention():
    # x' = a x + c y + e, y' = b x + d y + f
    assert st.matrix_map((2, 0, 0, 3, 10, 20), (1.0, 1.0)) == (12.0, 23.0)
    assert st.matrix_map((0, 1, -1, 0, 0, 0), (1.0, 0.0)) == (0.0, 1.0)


def test_the_matrix_acts_about_the_centre():
    assert st.matrix_map((2, 0, 0, 2, 0, 0), (110.0, 60.0), center=(100.0, 50.0)) == (120.0, 70.0)
    assert st.matrix_map((2, 0, 0, 2, 0, 0), (100.0, 50.0), center=(100.0, 50.0)) == (100.0, 50.0)


def test_a_linear_map_moves_grid_nodes_exactly():
    nodes = st.grid_nodes(5, 3, (0.0, 0.0, 400.0, 200.0))
    assert len(nodes) == 15 and nodes[0] == (0.0, 0.0) and nodes[-1] == (400.0, 200.0)
    m = (1.0, 0.5, 0.25, 1.0, 0.0, 0.0)
    for x, y in nodes:
        assert st.matrix_map(m, (x, y)) == (x + 0.25 * y, 0.5 * x + y)


def test_grid_nodes_reject_fewer_than_two_per_side():
    with pytest.raises(ValueError):
        st.grid_nodes(1, 3, (0.0, 0.0, 1.0, 1.0))


# --------------------------------------------------------------------------------------------- expression maps

def test_the_expression_map_works_in_data_units_about_the_centre_with_y_up():
    # centre (100, 100), unit 50: the pixel (150, 50) is data (1, 1); z² takes it to (0, 2) = pixel (100, 0)
    got = st.expr_map(lambda u, v: u * u - v * v, lambda u, v: 2 * u * v, (150.0, 50.0), center=(100.0, 100.0), unit=50.0)
    assert _close_pt(got, (100.0, 0.0))


def test_the_expression_map_defaults_to_pixels_at_the_origin():
    assert st.expr_map(lambda u, v: u + 1, lambda u, v: v, (0.0, 0.0)) == (1.0, 0.0)
    assert st.expr_map(lambda u, v: u, lambda u, v: v + 1, (0.0, 0.0)) == (0.0, -1.0)   # +v is up: pixel y down


def test_the_unit_must_be_positive():
    with pytest.raises(ValueError):
        st.expr_map(lambda u, v: u, lambda u, v: v, (0.0, 0.0), unit=0.0)


# ----------------------------------------------------------------------------------------- complex functions

@pytest.mark.parametrize("kind, z, want", [
    ("square", 1 + 2j, (1 + 2j) ** 2),
    ("cube", 1 + 1j, (1 + 1j) ** 3),
    ("inverse", 2j, 1 / 2j),
    ("exp", 1j * math.pi, cmath.exp(1j * math.pi)),
    ("log", -1 + 0j, cmath.log(-1 + 0j)),
    ("sqrt", -4 + 0j, cmath.sqrt(-4 + 0j)),
    ("sin", 1 + 1j, cmath.sin(1 + 1j)),
    ("cos", 1 + 1j, cmath.cos(1 + 1j)),
    ("joukowski", 2 + 0j, 2.5 + 0j),
])
def test_the_complex_functions(kind, z, want):
    got = st.complex_function(kind, z)
    assert cmath.isclose(got, want, rel_tol=1e-12, abs_tol=1e-12), (kind, got, want)


def test_the_complex_kinds_are_listed():
    assert set(st.COMPLEX_KINDS) == {"square", "cube", "inverse", "exp", "log", "sqrt", "sin", "cos", "mobius", "joukowski"}


def test_mobius_takes_eight_coefficients():
    # (a z + b) / (c z + d) with a = 1, b = i, c = i, d = 1 is the Cayley-like map: z = 0 -> i
    coeffs = (1, 0, 0, 1, 0, 1, 1, 0)
    assert cmath.isclose(st.complex_function("mobius", 0j, coeffs), 1j)
    with pytest.raises(ValueError):
        st.complex_function("mobius", 0j, (1, 0, 0, 1))
    with pytest.raises(ValueError):
        st.complex_function("mobius", 0j, (1, 0, 0, 0, 0, 0, 0, 0))   # ad - bc = 0 is degenerate


def test_an_unknown_kind_is_an_error():
    with pytest.raises(ValueError):
        st.complex_function("tan", 1j)


def test_a_pole_gives_a_non_finite_point():
    w = st.complex_function("inverse", 0j)
    assert not (math.isfinite(w.real) and math.isfinite(w.imag))


def test_the_complex_map_uses_the_expression_map_convention():
    # square at pixel (150, 50) about (100, 100) with unit 50 is z = 1 + i -> 2i -> pixel (100, 0)
    assert _close_pt(st.complex_map("square", (150.0, 50.0), center=(100.0, 100.0), unit=50.0), (100.0, 0.0))


# ------------------------------------------------------------------------------------------ conformal angles

def _square(p):
    return st.expr_map(lambda u, v: u * u - v * v, lambda u, v: 2 * u * v, p)


def test_conformal_maps_keep_right_angles():
    for f in (_square, lambda p: st.complex_map("exp", p, unit=100.0), lambda p: st.complex_map("inverse", p, unit=100.0)):
        for p in ((1.0, 1.0), (30.0, -20.0), (-5.0, 7.0)):
            assert abs(st.tangent_angle(f, p, (1.0, 0.0), (0.0, 1.0)) - 90.0) < 1e-5


def test_a_non_conformal_map_does_not():
    f = lambda p: st.expr_map(lambda u, v: u, lambda u, v: 2 * v, p)    # noqa: E731
    assert abs(st.tangent_angle(f, (1.0, 1.0), (1.0, 1.0), (1.0, -1.0)) - 90.0) > 10.0


# ---------------------------------------------------------------------------------- adaptive subdivision

def test_a_straight_map_needs_no_subdivision():
    pts = st.subdivide_segment(lambda p: st.matrix_map((2, 0.5, 0, 1, 0, 0), p), (0.0, 0.0), (100.0, 100.0), 0.25)
    assert pts == ((0.0, 0.0), (100.0, 100.0))


def test_subdivision_stops_when_the_mapped_chord_is_within_tolerance():
    f = lambda p: st.complex_map("square", p, unit=100.0)    # noqa: E731
    pts = st.subdivide_segment(f, (0.0, 0.0), (100.0, 0.0), 0.25)
    assert pts[0] == (0.0, 0.0) and pts[-1] == (100.0, 0.0) and len(pts) > 2
    assert st.chord_error(f, pts) <= 0.25
    # a looser tolerance subdivides less, a tighter one more
    assert len(st.subdivide_segment(f, (0.0, 0.0), (100.0, 0.0), 2.0)) < len(pts) < len(st.subdivide_segment(f, (0.0, 0.0), (100.0, 0.0), 0.01))


def test_subdivision_splits_at_the_parameter_midpoint():
    f = lambda p: st.complex_map("square", p, unit=100.0)    # noqa: E731
    pts = st.subdivide_segment(f, (0.0, 0.0), (100.0, 0.0), 0.25)
    xs = [p[0] for p in pts]
    assert xs == sorted(xs)
    assert all(abs(x * 2 ** st.MAX_DEPTH / 100.0 - round(x * 2 ** st.MAX_DEPTH / 100.0)) < 1e-9 for x in xs)


def test_subdivision_is_bounded_by_the_depth():
    wild = lambda p: (p[0], 1000.0 * math.sin(p[0] * 1000.0))    # noqa: E731
    pts = st.subdivide_segment(wild, (0.0, 0.0), (1.0, 0.0), 1e-9)
    assert len(pts) == 2 ** st.MAX_DEPTH + 1
    assert st.MAX_DEPTH == 10 and st.DEFAULT_TOLERANCE == 0.25


def test_the_tolerance_must_be_positive():
    with pytest.raises(ValueError):
        st.subdivide_segment(_square, (0.0, 0.0), (1.0, 0.0), 0.0)


def test_a_polyline_is_mapped_segment_by_segment_without_repeated_joins():
    f = lambda p: st.matrix_map((1, 0, 0, 1, 5, 5), p)    # noqa: E731
    parts = st.deform_polyline(f, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)), 0.25)
    assert parts == (((5.0, 5.0), (15.0, 5.0), (15.0, 15.0)),)


def test_a_closed_polyline_maps_its_closing_segment_and_repeats_the_first_point():
    f = lambda p: st.matrix_map((1, 0, 0, 1, 0, 0), p)    # noqa: E731
    parts = st.deform_polyline(f, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)), 0.25, closed=True)
    assert parts == (((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 0.0)),)


def test_a_pole_breaks_the_mapped_path_into_subpaths():
    f = lambda p: st.complex_map("inverse", p, unit=10.0)    # noqa: E731
    parts = st.deform_polyline(f, ((-20.0, 0.0), (0.0, 0.0), (20.0, 0.0)), 0.25)
    assert len(parts) == 2
    assert all(all(math.isfinite(c) for q in part for c in q) for part in parts)
    assert len(parts[0]) >= 2 and len(parts[1]) >= 2


def test_a_segment_whose_end_is_non_finite_is_cut_at_the_last_finite_sample():
    f = lambda p: (p[0], 1.0 / p[0] if p[0] else math.inf)    # noqa: E731
    parts = st.deform_polyline(f, ((1.0, 0.0), (0.0, 0.0)), 0.25)
    assert len(parts) == 1 and parts[0][0] == (1.0, 1.0) and len(parts[0]) > 1


def test_too_short_a_polyline_is_an_error():
    with pytest.raises(ValueError):
        st.deform_polyline(_square, ((0.0, 0.0),), 0.25)


# ------------------------------------------------------------------------------------- projections and diagrams

def test_stereographic_projection_from_the_north_pole():
    assert _close_pt(st.stereographic((1.0, 0.0, 0.0, 0.0)), (1.0, 0.0, 0.0))
    assert _close_pt(st.stereographic((0.0, 0.0, 0.0, -1.0)), (0.0, 0.0, 0.0))
    x, y, z = st.stereographic((0.0, 0.0, 0.0, 1.0))
    assert not all(math.isfinite(c) for c in (x, y, z))


def test_stereographic_projection_inverts():
    q = (0.5, -0.25, 0.75)
    p = st.inverse_stereographic(q)
    assert abs(sum(c * c for c in p) - 1.0) < 1e-12
    assert _close_pt(st.stereographic(p), q)


def test_a_circle_through_the_pole_blows_up_to_a_line():
    # the great circle in the (z, w) plane: (0, 0, sin s, cos s) projects to (0, 0, sin s / (1 - cos s)): a line on z
    for s in (0.5, 1.0, 2.0, 3.0):
        x, y, z = st.stereographic((0.0, 0.0, math.sin(s), math.cos(s)))
        assert x == 0.0 and y == 0.0 and math.isclose(z, math.sin(s) / (1 - math.cos(s)))


def test_the_penrose_compactification():
    T, X = st.penrose(1.0, 0.0)
    assert math.isclose(T, math.pi / 4) and X == 0.0
    T, X = st.penrose(0.0, 1.0)
    assert T == 0.0 and math.isclose(X, math.pi / 4)
    # light rays keep 45 degrees: t = x + c maps to T - X = const
    for c in (0.0, 1.0, -2.0):
        vals = {round(st.penrose(x + c, x)[0] - st.penrose(x + c, x)[1], 12) for x in (-3.0, 0.0, 2.0, 10.0)}
        assert len(vals) == 1
    # infinity reaches the diamond's edge
    T, X = st.penrose(1e12, 0.0)
    assert abs(T - math.pi / 2) < 1e-9 and abs(X) < 1e-9


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
    assert len(_numeric_rows()) >= 24
    assert "Status:          Draft" in text and "SREP:            0" in text


def _close(a, b):
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, complex) or isinstance(b, complex):
        return cmath.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


@pytest.mark.parametrize("name, expr, expected", _numeric_rows() if os.path.exists(DRAFT) else [])
def test_numeric_table_row(name, expr, expected):
    scope = {k: getattr(st, k) for k in dir(st) if not k.startswith("_")}
    scope["math"] = math
    scope["cmath"] = cmath
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "max": max, "complex": complex}
    got = eval(expr, scope)   # one scope: a lambda in a row looks its names up in the globals
    want = eval(expected, {"__builtins__": {}, "inf": math.inf, "nan": math.nan}, {})
    assert _close(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(capsys):
    st.main()
    out = capsys.readouterr().out
    printed = re.findall(r"^\| ([^|]+?) \| `([^`]+)` \| `([^`]+)` \|$", out, re.M)
    assert printed == _numeric_rows()


def test_the_draft_answers_the_engine_review():
    """SR-64's review: a group gains deform alone (the bodyBehaviour group would admit rigidBody and softBody on a
    group with no semantics), SPT2's XPath is written out, and the gate is SREP 12's shared V17."""
    text = open(DRAFT, encoding="utf-8").read()
    assert "gains `deform` (`deformType`, xsd:2826)" in text
    assert "gains `bodyBehaviour`" not in text
    assert 'id="SPT2"' in text and "str:tokenize(normalize-space(@coefficients), ' ')" in text
    assert "shared 1.8 gate" in text and "V17" in text


def test_the_draft_writes_out_spt1():
    """SPT1's XPath is in the draft (the engine's assert, adopted verbatim), not prose alone."""
    text = open(DRAFT, encoding="utf-8").read()
    assert 'id="SPT1"' in text
    for clause in ("(not(@type='map') or (@x and @y))", "(not(@type='complex') or @function)",
                   "(not(@function='mobius') or (@coefficients and count(str:tokenize(normalize-space(@coefficients), ' '))=8))",
                   "(not(@coefficients) or @function='mobius')", "(@type='map' or not(@x or @y))",
                   "(@type='complex' or not(@function or @coefficients))"):
        assert clause in text, clause
