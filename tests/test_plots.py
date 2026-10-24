"""Draft SREP "Add coordinate systems and plots" (srep/srep-0000-plots.md, MF1 of SREP 12): the reference
implementation conformance/tools/plots_reference.py and the agreement between the SREP's numeric-test table and
that implementation.

The golden values come from two independent statements: the SREP's text (closed forms worked by hand in the table)
and this module, written from that text. The properties the SREP promises (sampled points on the analytic curve,
marching-squares vertices within 0.5 px of the curve at the default resolution, exact tick multiples, frames
orthonormal on tubes) are checked here against closed forms, not against the module's own output.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT = os.path.join(ROOT, "srep", "srep-0000-plots.md")
MODULE = os.path.join(ROOT, "conformance", "tools", "plots_reference.py")


def _load():
    spec = importlib.util.spec_from_file_location("plots_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pr = _load()

AX = pr.Axes(x_min=-1.0, x_max=1.0, y_min=-1.0, y_max=1.0, width=400.0, height=300.0)


# --- the mapping (rule 1) ---------------------------------------------------------------------------------------

def test_data_maps_to_the_box_with_y_up():
    assert pr.to_pixel(AX, -1.0, 1.0) == (0.0, 0.0)              # top-left of the box
    assert pr.to_pixel(AX, 1.0, -1.0) == (400.0, 300.0)          # bottom-right
    assert pr.to_pixel(AX, 0.0, 0.0) == (200.0, 150.0)
    assert pr.to_pixel(AX, 0.5, 0.5) == (300.0, 75.0)


@pytest.mark.parametrize("x, y", [(0.3, -0.7), (-1.0, 1.0), (0.123456, 0.654321)])
def test_from_pixel_inverts_to_pixel(x, y):
    px, py = pr.to_pixel(AX, x, y)
    bx, by = pr.from_pixel(AX, px, py)
    assert abs(bx - x) < 1e-12 and abs(by - y) < 1e-12


@pytest.mark.parametrize("kw", [dict(x_min=1.0, x_max=1.0), dict(x_min=2.0, x_max=1.0), dict(y_min=0.0, y_max=0.0),
                                dict(width=0.0), dict(height=-1.0)])
def test_an_empty_or_reversed_range_is_rejected(kw):
    base = dict(x_min=-1.0, x_max=1.0, y_min=-1.0, y_max=1.0, width=400.0, height=300.0)
    with pytest.raises(ValueError):
        pr.Axes(**{**base, **kw})


# --- ticks and labels (rules 4 and 5) ---------------------------------------------------------------------------

@pytest.mark.parametrize("lo, hi, step", [(0, 10, 1), (0, 1, 0.1), (-3, 3, 1), (0, 100, 10), (0, 7, 1), (0, 25, 5),
                                          (-0.05, 0.05, 0.01), (0, 1000, 100), (0.5, 0.9, 0.05), (-20, 20, 5)])
def test_the_nice_step_is_the_smallest_1_2_5_step_with_at_most_ten_intervals(lo, hi, step):
    got = pr.nice_step(lo, hi)
    assert abs(got - step) < 1e-12 * max(1.0, step), (lo, hi, got)
    k = math.floor(math.log10(got) + 1e-9)
    assert any(abs(got - m * 10.0 ** k) < 1e-9 * got for m in (1, 2, 5))
    assert (hi - lo) / got <= 10 + 1e-9
    # the next smaller nice step would give more than ten intervals
    smaller = {1: 0.5, 2: 1, 5: 2}[round(got / 10.0 ** k)] * 10.0 ** k
    assert (hi - lo) / smaller > 10


def test_ticks_are_exact_multiples_of_the_step_inside_the_range():
    t = pr.ticks(-1.0, 1.0, 0.5)
    assert t == (-1.0, -0.5, 0.0, 0.5, 1.0)
    assert pr.ticks(0.1, 0.9, 0.25) == (0.25, 0.5, 0.75)
    many = pr.ticks(0.0, 1.0, 0.1)
    assert len(many) == 11 and many[3] == 3 * 0.1 and many[-1] == 10 * 0.1     # k * step, never accumulated


def test_a_tick_at_the_edge_within_rounding_is_kept():
    assert pr.ticks(0.0, 0.3, 0.1)[-1] == 3 * 0.1       # 0.30000000000000004 counts as inside [0, 0.3]


@pytest.mark.parametrize("value, step, imaginary, label", [
    (1.0, 0.5, False, "1"), (-0.5, 0.5, False, "-0.5"), (0.75, 0.25, False, "0.75"), (2.0, 1.0, True, "2i"),
    (-1.0, 1.0, True, "-i"), (1.0, 1.0, True, "i"), (0.0, 1.0, True, "0"), (-0.0, 0.5, False, "0"),
    (1e-17, 0.5, False, "0"), (1000.0, 100.0, False, "1000"), (0.1, 0.05, False, "0.1"), (3 * 0.1, 0.1, False, "0.3"),
    (-2.5, 2.5, True, "-2.5i"), (1e-3, 1e-3, False, "0.001"),
])
def test_tick_labels_are_the_shortest_decimal_of_the_step(value, step, imaginary, label):
    assert pr.tick_label(value, step, imaginary) == label


def test_the_axis_line_sits_at_zero_or_at_the_lower_edge():
    assert pr.axis_position(-1.0, 1.0) == 0.0
    assert pr.axis_position(2.0, 5.0) == 2.0
    assert pr.axis_position(-5.0, -2.0) == -5.0
    assert pr.axis_position(0.0, 3.0) == 0.0


def test_the_label_decimals_follow_the_step():
    assert pr.label_decimals(1.0) == 0 and pr.label_decimals(0.5) == 1 and pr.label_decimals(0.25) == 2
    assert pr.label_decimals(0.001) == 3 and pr.label_decimals(100.0) == 0 and pr.label_decimals(2.5) == 1


# --- sampled curves (rule 7) ------------------------------------------------------------------------------------

def test_explicit_samples_are_evenly_spaced_and_on_the_curve():
    pts = pr.sample_explicit(lambda x: x * x, 0.0, 1.0, 5)
    assert pts == ((0.0, 0.0), (0.25, 0.0625), (0.5, 0.25), (0.75, 0.5625), (1.0, 1.0))


def test_the_default_sample_count_keeps_a_sine_within_half_a_pixel():
    ax = pr.Axes(x_min=-math.pi, x_max=math.pi, y_min=-1.5, y_max=1.5, width=500.0, height=300.0)
    pts = pr.sample_explicit(math.sin, ax.x_min, ax.x_max, pr.DEFAULT_SAMPLES)
    assert len(pts) == 256
    worst = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        xm = 0.5 * (x0 + x1)
        chord = 0.5 * (y0 + y1)
        _, py_chord = pr.to_pixel(ax, xm, chord)
        _, py_curve = pr.to_pixel(ax, xm, math.sin(xm))
        worst = max(worst, abs(py_chord - py_curve))
    assert worst <= 0.5
    assert pr.chord_error_px(ax, math.sin, pr.DEFAULT_SAMPLES) <= 0.5


def test_parametric_samples_follow_srep_70():
    pts = pr.sample_parametric(math.cos, math.sin, 0.0, 2 * math.pi, 4, closed=True)
    assert len(pts) == 4                                                  # Δ = (t1 − t0)/N when closed
    assert all(abs(math.hypot(x, y) - 1.0) < 1e-12 for x, y in pts)
    assert abs(pts[1][0]) < 1e-12 and abs(pts[1][1] - 1.0) < 1e-12        # t = π/2
    open_pts = pr.sample_parametric(lambda t: t, lambda t: 2 * t, 0.0, 1.0, 3)
    assert open_pts == ((0.0, 0.0), (0.5, 1.0), (1.0, 2.0))


def test_polar_samples_are_r_cos_r_sin_with_theta_in_radians():
    pts = pr.sample_polar(lambda th: 1.0, 0.0, math.pi, 3)
    assert [(round(x, 12), round(y, 12)) for x, y in pts] == [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0)]
    rose = pr.sample_polar(lambda th: math.cos(3 * th), 0.0, math.pi, 7)
    assert abs(rose[1][0] - math.cos(math.pi / 2) * math.cos(math.pi / 6)) < 1e-12


@pytest.mark.parametrize("n", [0, 1])
def test_fewer_than_two_samples_is_rejected(n):
    with pytest.raises(ValueError):
        pr.sample_explicit(math.sin, 0.0, 1.0, n)
    with pytest.raises(ValueError):
        pr.sample_polar(math.sin, 0.0, 1.0, n)


def test_a_non_finite_sample_breaks_the_curve_into_subpaths():
    pts = pr.sample_explicit(lambda x: 1.0 / x if x else math.inf, -1.0, 1.0, 5)
    parts = pr.split_finite(pts)
    assert parts == (((-1.0, -1.0), (-0.5, -2.0)), ((0.5, 2.0), (1.0, 1.0)))


# --- clipping to the box (rule 2) -------------------------------------------------------------------------------

def test_a_polyline_is_clipped_to_the_box_into_subpaths():
    assert pr.clip_polyline(((-1.0, 0.5), (3.0, 0.5)), 0.0, 0.0, 2.0, 1.0) == (((0.0, 0.5), (2.0, 0.5)),)
    inside = ((0.2, 0.2), (0.8, 0.9))
    assert pr.clip_polyline(inside, 0.0, 0.0, 1.0, 1.0) == (inside,)
    zig = ((0.5, -1.0), (0.5, 0.5), (0.5, 2.0), (1.5, 2.0), (1.5, 0.5))      # leaves at the top and comes back
    parts = pr.clip_polyline(zig, 0.0, 0.0, 2.0, 1.0)
    assert parts == (((0.5, 0.0), (0.5, 0.5), (0.5, 1.0)), ((1.5, 1.0), (1.5, 0.5)))
    assert pr.clip_polyline(((5.0, 5.0), (6.0, 6.0)), 0.0, 0.0, 1.0, 1.0) == ()


# --- implicit curves by marching squares (rule 8) ---------------------------------------------------------------

def test_marching_squares_on_a_line_is_exact():
    lines = pr.marching_squares(lambda x, y: x + y - 1.5, (0.0, 2.0, 0.0, 2.0), 2)
    assert len(lines) == 1
    pts = lines[0]
    assert pts[0] in ((0.0, 1.5), (1.5, 0.0)) and pts[-1] in ((0.0, 1.5), (1.5, 0.0)) and pts[0] != pts[-1]
    assert all(abs(x + y - 1.5) < 1e-12 for x, y in pts)


def test_marching_squares_on_a_circle_is_one_closed_loop_within_half_a_pixel():
    ax = pr.Axes(x_min=-1.2, x_max=1.2, y_min=-1.2, y_max=1.2, width=300.0, height=300.0)
    lines = pr.marching_squares(lambda x, y: x * x + y * y - 1.0, (ax.x_min, ax.x_max, ax.y_min, ax.y_max),
                                pr.DEFAULT_RESOLUTION)
    assert len(lines) == 1 and lines[0][0] == lines[0][-1]                    # closed: ends joined
    px_per_unit = ax.width / (ax.x_max - ax.x_min)
    worst = max(abs(math.hypot(x, y) - 1.0) for x, y in lines[0]) * px_per_unit
    assert worst <= 0.5
    assert len(lines[0]) > 100


def test_marching_squares_separates_the_branches_of_a_hyperbola():
    lines = pr.marching_squares(lambda x, y: x * y - 0.1, (-1.0, 1.0, -1.0, 1.0), 32)
    assert len(lines) == 2
    for pts in lines:
        assert pts[0] != pts[-1]                                                # open branches
        assert all(abs(x * y - 0.1) < 0.01 for x, y in pts)


def test_a_cell_with_a_non_finite_corner_draws_nothing():
    def f(x, y):
        return math.inf if (x == 0.0 and y == 0.0) else x + y - 0.75
    lines = pr.marching_squares(f, (0.0, 1.0, 0.0, 1.0), 4)
    assert all(math.isfinite(c) for pts in lines for p in pts for c in p)
    assert len(lines) >= 1


def test_the_saddle_is_resolved_by_the_cell_centre():
    # x·y − 0.1 on one cell [−1, 1]²: corners −0.1 (−−), ... a saddle; the centre value −0.1 < 0 joins the
    # positive corners apart, so two segments, each near its positive corner
    lines = pr.marching_squares(lambda x, y: x * y - 0.1, (-1.0, 1.0, -1.0, 1.0), 1)
    assert len(lines) == 2


@pytest.mark.parametrize("res", [0, 1])
def test_a_resolution_below_two_is_rejected_unless_it_is_one_cell(res):
    if res == 0:
        with pytest.raises(ValueError):
            pr.marching_squares(lambda x, y: x, (0.0, 1.0, 0.0, 1.0), res)
    else:
        pr.marching_squares(lambda x, y: x - 0.5, (0.0, 1.0, 0.0, 1.0), res)


# --- 3D axes and tubes (rule 10) --------------------------------------------------------------------------------

def test_data_maps_to_scene_units_with_y_up_as_minus_y():
    ax = pr.Axes3D(x_min=-1.0, x_max=1.0, y_min=-1.0, y_max=1.0, z_min=0.0, z_max=2.0,
                   width=200.0, height=200.0, depth=400.0)
    assert pr.to_scene(ax, 0.0, 0.0, 1.0) == (0.0, 0.0, 0.0)             # the data centre is the object's origin
    assert pr.to_scene(ax, 1.0, 1.0, 2.0) == (100.0, -100.0, 200.0)      # +y data is up, which is −y in scene space
    assert pr.to_scene(ax, -1.0, -1.0, 0.0) == (-100.0, 100.0, -200.0)


def test_a_tube_keeps_its_radius_and_an_orthonormal_frame():
    pts = [(math.cos(t), math.sin(t), t / 4) for t in [i * 0.1 for i in range(40)]]
    grid = pr.tube(pts, 0.05, 8)
    assert len(grid) == len(pts) and all(len(ring) == 8 for ring in grid)
    for c, ring in zip(pts, grid):
        for v in ring:
            assert abs(math.dist(c, v) - 0.05) < 1e-12
    frames = pr.tube_frames(pts)
    for t, n, b in frames:
        for u in (t, n, b):
            assert abs(math.hypot(*u) - 1.0) < 1e-12
        assert abs(sum(a * b_ for a, b_ in zip(t, n))) < 1e-12 and abs(sum(a * b_ for a, b_ in zip(n, b))) < 1e-12
    # consecutive normals turn as little as possible (parallel transport): no flip along a smooth helix
    for (_, n0, _), (_, n1, _) in zip(frames, frames[1:]):
        assert sum(a * b_ for a, b_ in zip(n0, n1)) > 0.99


def test_a_straight_tube_has_a_constant_frame():
    pts = [(0.0, 0.0, float(i)) for i in range(5)]
    frames = pr.tube_frames(pts)
    assert all(f == frames[0] for f in frames)
    assert frames[0][0] == (0.0, 0.0, 1.0)


@pytest.mark.parametrize("bad", [dict(radius=0.0), dict(segments=2)])
def test_a_degenerate_tube_is_rejected(bad):
    kw = dict(radius=1.0, segments=8)
    kw.update(bad)
    with pytest.raises(ValueError):
        pr.tube([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], kw["radius"], kw["segments"])


def test_a_tube_needs_two_distinct_points():
    with pytest.raises(ValueError):
        pr.tube([(0.0, 0.0, 0.0)], 1.0, 8)


# --- the SREP's numeric-test table agrees with the module --------------------------------------------------------

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
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


@pytest.mark.parametrize("name, expr, expected", _numeric_rows() if os.path.exists(DRAFT) else [])
def test_numeric_table_row(name, expr, expected):
    scope = {k: getattr(pr, k) for k in dir(pr) if not k.startswith("_")}
    scope["math"] = math
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "max": max}
    got = eval(expr, scope)   # one scope: a lambda in a row looks its names up in the globals
    want = eval(expected, {"__builtins__": {}, "inf": math.inf, "nan": math.nan}, {})
    assert _close(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(capsys):
    pr.main()
    out = capsys.readouterr().out
    printed = re.findall(r"^\| ([^|]+?) \| `([^`]+)` \| `([^`]+)` \|$", out, re.M)
    assert printed == _numeric_rows()
