"""Tests of the draft SREP "Add tagged formula parts and shape morphing" (MF3 of SREP 12) and its reference module.

The reference module is conformance/tools/semantic_tex_reference.py; the draft is srep/srep-0000-semantic-tex.md.
The numeric table of the draft's Conformance section is parsed back here and every row is evaluated against the
module, and the module's main() must print exactly that table.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "semantic_tex_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-semantic-tex.md")

_spec = importlib.util.spec_from_file_location("semantic_tex_reference", MODULE)
sx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sx)

SQUARE = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
TRI = ((0.0, 0.0), (10.0, 0.0), (5.0, 8.0))


def _circle(n=32, r=5.0, c=(5.0, 5.0)):
    return tuple((c[0] + r * math.cos(2 * math.pi * k / n), c[1] + r * math.sin(2 * math.pi * k / n)) for k in range(n))


def _close(a, b, tol=1e-9):
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tol) for p, q in zip(a, b) for x, y in zip(p, q))


# ------------------------------------------------------------------------------------------------ tagged parts

def test_parts_are_found_with_their_tex_and_order():
    got = sx.parts(r"\part{lhs}{E} = \part{rhs}{m c^2}")
    assert [(p.name, p.tex) for p in got] == [("lhs", "E"), ("rhs", "m c^2")]
    assert [p.depth for p in got] == [0, 0]


def test_parts_nest_and_the_outer_part_contains_the_inner():
    got = sx.parts(r"\part{frac}{\frac{\part{num}{a}}{\part{den}{b}}}")
    assert [(p.name, p.depth) for p in got] == [("frac", 0), ("num", 1), ("den", 1)]
    assert got[0].tex == r"\frac{\part{num}{a}}{\part{den}{b}}"


def test_a_formula_without_parts_has_none():
    assert sx.parts(r"\sqrt{x^2 + y^2}") == ()


def test_braces_inside_a_part_are_balanced():
    got = sx.parts(r"\part{s}{\sum_{i=1}^{n} x_i}")
    assert got[0].tex == r"\sum_{i=1}^{n} x_i"


@pytest.mark.parametrize("tex", [r"\part{a}{x", r"\part{a}x", r"\part{}{x}", r"\part{a}{x} \part{a}{y}",
                                 r"\part{a}{\part{a}{x}}", r"\part{a b}{x}", r"\part{a}{x}}"])
def test_malformed_parts_are_errors(tex):
    with pytest.raises(ValueError):
        sx.parts(tex)


def test_strip_parts_leaves_a_plain_group_for_the_typesetter():
    assert sx.strip_parts(r"\part{lhs}{E} = \part{rhs}{m c^2}") == r"{E} = {m c^2}"
    assert sx.strip_parts(r"\part{f}{\frac{\part{n}{a}}{\part{d}{b}}}") == r"{\frac{{a}}{{b}}}"
    assert sx.strip_parts(r"x + y") == r"x + y"


def test_part_names_are_nmtokens():
    assert sx.parts(r"\part{x_1}{x}")[0].name == "x_1"
    assert sx.parts(r"\part{term-2}{x}")[0].name == "term-2"


# ------------------------------------------------------------------------------------------------- matching

def test_parts_match_by_name_and_the_rest_fade():
    a = sx.parts(r"\part{a}{x} + \part{b}{y} = \part{c}{z}")
    b = sx.parts(r"\part{c}{z} - \part{b}{y} = \part{d}{w}")
    m = sx.match_parts(a, b)
    assert m.matched == (("a", "x", "x"), ("b", "y", "y"), ("c", "z", "z")) or [t[0] for t in m.matched] == ["b", "c"]
    assert [t[0] for t in m.matched] == ["b", "c"]
    assert m.out == ("a",) and m.incoming == ("d",)


def test_matching_by_tex_pairs_equal_strings_in_order():
    a = sx.parts(r"\part{p}{x^2} + \part{q}{2x} + \part{r}{x^2}")
    b = sx.parts(r"\part{u}{x^2} + \part{v}{x^2}")
    m = sx.match_parts(a, b, by="tex")
    assert [(s, t) for s, t, _ in m.matched] == [("p", "u"), ("r", "v")]
    assert m.out == ("q",) and m.incoming == ()


def test_a_matched_pair_with_different_tex_morphs_and_equal_tex_moves():
    a = sx.parts(r"\part{k}{x^2}")
    b = sx.parts(r"\part{k}{y^2}")
    assert sx.match_parts(a, b).matched == (("k", "x^2", "y^2"),)
    assert sx.pair_kind("x^2", "x^2") == "move" and sx.pair_kind("x^2", "y^2") == "morph"
    assert sx.pair_kind("x ^ 2", "x^2") == "move"   # whitespace is not a difference


def test_the_matching_mode_is_checked():
    with pytest.raises(ValueError):
        sx.match_parts((), (), by="glyphs")


# --------------------------------------------------------------------------------- part boxes and opacity

def test_a_part_box_interpolates_its_centre_and_scale():
    a = sx.Box(10.0, 20.0, 40.0, 10.0)
    b = sx.Box(100.0, 50.0, 80.0, 20.0)
    mid = sx.box_at(a, b, 0.5)
    assert mid == sx.Box(55.0, 35.0, 60.0, 15.0)
    assert sx.box_at(a, b, 0.0) == a and sx.box_at(a, b, 1.0) == b


def test_the_part_transform_is_a_translation_and_a_uniform_scale_about_the_box_centre():
    a = sx.Box(0.0, 0.0, 20.0, 10.0)
    b = sx.Box(100.0, 100.0, 40.0, 20.0)
    tx, ty, s = sx.part_transform(a, b, 0.5)
    assert (tx, ty, s) == (55.0, 52.5, 1.5)    # centres (10, 5) and (120, 110): half the way; heights 10 and 20
    with pytest.raises(ValueError):
        sx.part_transform(a, sx.Box(0.0, 0.0, 0.0, 10.0), 0.5)


def test_unmatched_parts_fade_linearly():
    assert sx.opacity_out(0.25) == 0.75 and sx.opacity_in(0.25) == 0.25
    assert sx.opacity_out(1.0) == 0.0 and sx.opacity_in(0.0) == 0.0


def test_progress_is_clamped_to_the_unit_interval():
    assert sx.opacity_out(-1.0) == 1.0 and sx.opacity_in(2.0) == 1.0
    assert sx.box_at(sx.Box(0, 0, 1, 1), sx.Box(10, 10, 1, 1), 3.0) == sx.Box(10.0, 10.0, 1.0, 1.0)


# --------------------------------------------------------------------------------------- polygon helpers

def test_signed_area_and_centroid():
    assert sx.signed_area(SQUARE) == 100.0
    assert sx.signed_area(tuple(reversed(SQUARE))) == -100.0
    assert sx.centroid(SQUARE) == (5.0, 5.0)
    assert _close((sx.centroid(TRI),), ((5.0, 8.0 / 3.0),))


def test_perimeter_and_arc_length_resampling():
    assert sx.perimeter(SQUARE) == 40.0
    r = sx.resample(SQUARE, 8)
    assert r == ((0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 5.0), (10.0, 10.0), (5.0, 10.0), (0.0, 10.0), (0.0, 5.0))
    assert len(sx.resample(_circle(), 100)) == 100
    with pytest.raises(ValueError):
        sx.resample(SQUARE, 2)


def test_resampling_keeps_the_first_vertex_and_the_direction():
    r = sx.resample(TRI, 6)
    assert r[0] == (0.0, 0.0)
    assert sx.signed_area(r) > 0


def test_a_degenerate_polygon_cannot_be_resampled():
    with pytest.raises(ValueError):
        sx.resample(((1.0, 1.0), (1.0, 1.0), (1.0, 1.0)), 4)


def test_self_intersections_are_counted():
    assert sx.self_intersections(SQUARE) == 0
    bow = ((0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0))
    assert sx.self_intersections(bow) == 1
    assert sx.self_intersections(_circle()) == 0


# -------------------------------------------------------------------------------- alignment and the morph

def test_align_start_picks_the_rotation_with_the_least_travel():
    a = sx.resample(SQUARE, 8)
    b = tuple(a[2:] + a[:2])        # the same square, started two vertices later
    assert sx.align_start(a, b) == 6     # b[(i + 6) % 8] == a[i]
    assert sx.rotate(b, 6) == a


def test_align_start_reverses_an_opposite_winding():
    a = sx.resample(SQUARE, 8)
    b = tuple(reversed(a))
    aligned = sx.align(a, b)
    assert sx.signed_area(aligned) > 0 and aligned == a


def test_align_needs_equal_counts():
    with pytest.raises(ValueError):
        sx.align_start(SQUARE, TRI)


def test_the_morph_starts_at_a_and_ends_at_b():
    a, b = SQUARE, _circle()
    assert _close(sx.morph_polygon(a, b, 0.0, 64), sx.align(sx.resample(a, 64), sx.resample(b, 64))[0:0] + sx.resample(a, 64))
    assert _close(sx.morph_polygon(a, b, 1.0, 64), sx.align(sx.resample(a, 64), sx.resample(b, 64)))


def test_the_morph_is_linear_in_the_aligned_samples():
    a, b = SQUARE, _circle()
    ra, rb = sx.resample(a, 64), sx.align(sx.resample(a, 64), sx.resample(b, 64))
    mid = sx.morph_polygon(a, b, 0.5, 64)
    assert _close(mid, tuple(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(ra, rb)))


def test_a_square_to_a_circle_never_self_intersects():
    for p in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert sx.self_intersections(sx.morph_polygon(SQUARE, _circle(), p, 64)) == 0


def test_a_square_to_a_triangle_never_self_intersects():
    for p in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert sx.self_intersections(sx.morph_polygon(SQUARE, TRI, p, 64)) == 0


def test_morph_samples_default():
    assert sx.MORPH_SAMPLES == 64
    assert len(sx.morph_polygon(SQUARE, TRI, 0.5)) == 64


# ------------------------------------------------------------------------------------ sub-path matching

def test_subpaths_are_matched_by_nearest_centroid():
    A = (SQUARE, tuple((x + 100.0, y) for x, y in SQUARE))
    B = (tuple((x + 100.0, y + 1.0) for x, y in TRI), tuple((x, y + 1.0) for x, y in TRI))
    assert sx.match_subpaths(A, B) == ((0, 1), (1, 0))


def test_an_extra_subpath_collapses_to_its_partners_centroid():
    A = (SQUARE, tuple((x + 100.0, y) for x, y in SQUARE))
    B = (TRI,)
    pairs = sx.match_subpaths(A, B)
    assert pairs == ((0, 0), (1, None))
    shapes = sx.morph_path(A, B, 1.0, 8)
    assert len(shapes) == 2
    assert all(_close((q,), (sx.centroid(TRI),)) for q in shapes[1])    # collapsed onto the target's centroid
    shapes0 = sx.morph_path(A, B, 0.0, 8)
    assert _close(shapes0[1], sx.resample(A[1], 8))


def test_an_incoming_subpath_grows_from_its_partners_centroid():
    A = (SQUARE,)
    B = (TRI, tuple((x + 100.0, y) for x, y in TRI))
    pairs = sx.match_subpaths(A, B)
    assert pairs == ((0, 0), (None, 1))
    shapes = sx.morph_path(A, B, 0.0, 8)
    assert all(_close((q,), (sx.centroid(SQUARE),)) for q in shapes[1])


def test_empty_paths_are_errors():
    with pytest.raises(ValueError):
        sx.morph_path((), (TRI,), 0.5)


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


def _close_values(a, b):
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_close_values(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


@pytest.mark.parametrize("name, expr, expected", _numeric_rows() if os.path.exists(DRAFT) else [])
def test_numeric_table_row(name, expr, expected):
    scope = {k: getattr(sx, k) for k in dir(sx) if not k.startswith("_")}
    scope["math"] = math
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "max": max, "reversed": reversed, "all": all}
    got = eval(expr, scope)   # one scope: a lambda in a row looks its names up in the globals
    want = eval(expected, {"__builtins__": {}, "inf": math.inf, "nan": math.nan, "Box": sx.Box, "Part": sx.Part, "Matching": sx.Matching}, {})
    assert _close_values(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(capsys):
    sx.main()
    out = capsys.readouterr().out
    printed = re.findall(r"^\| ([^|]+?) \| `([^`]+)` \| `([^`]+)` \|$", out, re.M)
    assert printed == _numeric_rows()
