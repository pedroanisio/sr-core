"""Tests of the draft SREP "Add relativity diagrams" (srep/srep-0000-relativity.md) and of its reference
implementation conformance/tools/relativity_reference.py (SP6 of SREP 12, SRC-49).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "relativity_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-relativity.md")

_spec = importlib.util.spec_from_file_location("relativity_reference", MODULE)
rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _rel(a, b, tol=1e-12):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


# ------------------------------------------------------------------------------------ boosts and intervals


def test_gamma_and_rapidity_are_the_standard_functions():
    assert rl.gamma(0.0) == 1.0
    assert _close(rl.gamma(0.6), 1.25, 1e-12)
    assert _close(rl.gamma(0.8), 5.0 / 3.0, 1e-12)
    assert _close(rl.rapidity(0.6), math.atanh(0.6), 1e-15)
    assert _close(rl.beta_from_rapidity(rl.rapidity(0.6)), 0.6, 1e-15)
    assert rl.beta_from_rapidity(0.0) == 0.0
    for beta in (1.0, -1.0, 1.5):
        with pytest.raises(rl.RelativityError):
            rl.gamma(beta)
        with pytest.raises(rl.RelativityError):
            rl.rapidity(beta)


def test_boost_is_the_lorentz_transformation_in_units_of_c():
    x, t = rl.boost(1.0, 0.0, 0.6)
    assert _close((x, t), (1.25, -0.75), 1e-12)
    x, t = rl.boost(0.0, 1.0, 0.6)
    assert _close((x, t), (-0.75, 1.25), 1e-12)
    assert rl.boost(3.0, 4.0, 0.0) == (3.0, 4.0)
    assert _close(rl.inverse_boost(*rl.boost(3.0, 4.0, 0.6), 0.6), (3.0, 4.0), 1e-12)
    assert _close(rl.boost(*rl.boost(3.0, 4.0, 0.6), -0.6), (3.0, 4.0), 1e-12)
    with pytest.raises(rl.RelativityError):
        rl.boost(1.0, 0.0, 1.0)


def test_a_boost_preserves_the_interval():
    for x, t in ((3.0, 4.0), (-2.0, 0.5), (7.0, 7.0), (1.0e3, -2.0e3), (0.0, 0.0)):
        for beta in (0.0, 0.3, -0.6, 0.99, 0.999999):
            assert _rel(rl.interval(*rl.boost(x, t, beta)), rl.interval(x, t), 1e-8), (x, t, beta)
    assert rl.interval(3.0, 5.0) == 16.0
    assert rl.interval(5.0, 3.0) == -16.0
    a, b = (1.0, 2.0), (4.0, 7.0)
    assert rl.interval_between(a, b) == rl.interval(3.0, 5.0)
    assert _rel(rl.interval_between(rl.boost(*a, 0.6), rl.boost(*b, 0.6)), 16.0, 1e-12)


def test_velocity_composition_is_additive_in_rapidity():
    assert _close(rl.compose_beta(0.5, 0.5), 0.8, 1e-12)
    assert _close(rl.compose_beta(0.6, -0.6), 0.0, 1e-12)
    assert rl.compose_beta(0.999, 0.999) < 1.0
    for b1, b2 in ((0.3, 0.4), (-0.9, 0.95), (0.1, 0.1)):
        assert _close(rl.compose_beta(b1, b2), rl.beta_from_rapidity(rl.rapidity(b1) + rl.rapidity(b2)), 1e-12)
    assert _close(rl.time_dilation(0.6), 1.25, 1e-12)
    assert _close(rl.length_contraction(0.6), 0.8, 1e-12)
    assert _close(rl.doppler(0.6), 2.0, 1e-12)
    assert _close(rl.doppler(-0.6), 0.5, 1e-12)


def test_causal_classification_and_proper_time():
    assert rl.classify((0.0, 0.0), (1.0, 2.0)) == "timelike"
    assert rl.classify((0.0, 0.0), (2.0, 1.0)) == "spacelike"
    assert rl.classify((0.0, 0.0), (3.0, 3.0)) == "lightlike"
    assert rl.classify((0.0, 0.0), (-3.0, 3.0)) == "lightlike"
    assert rl.classify((1.0, 1.0), (1.0, 1.0)) == "lightlike"
    for beta in (0.3, -0.7, 0.95):
        assert rl.classify(rl.boost(0.0, 0.0, beta), rl.boost(1.0, 2.0, beta)) == "timelike"
        assert rl.classify(rl.boost(0.0, 0.0, beta), rl.boost(2.0, 1.0, beta)) == "spacelike"
    assert _close(rl.proper_time((0.0, 0.0), (3.0, 5.0)), 4.0, 1e-12)
    assert _close(rl.proper_time((0.0, 0.0), (3.0, 5.0)), rl.proper_time(rl.boost(0.0, 0.0, 0.6), rl.boost(3.0, 5.0, 0.6)), 1e-12)
    with pytest.raises(rl.RelativityError):
        rl.proper_time((0.0, 0.0), (5.0, 3.0))
    assert _close(rl.proper_length((0.0, 0.0), (5.0, 3.0)), 4.0, 1e-12)
    with pytest.raises(rl.RelativityError):
        rl.proper_length((0.0, 0.0), (3.0, 5.0))


def test_light_cones_stay_at_45_degrees_under_any_boost():
    cone = rl.light_cone((1.0, 2.0), 3.0)
    assert cone["future"] == ((-2.0, 5.0), (4.0, 5.0))
    assert cone["past"] == ((-2.0, -1.0), (4.0, -1.0))
    assert rl.cone_slopes((1.0, 2.0), cone) == (1.0, 1.0)
    for beta in (0.0, 0.5, -0.9, 0.99):
        event = rl.boost(1.0, 2.0, beta)
        boosted = {k: tuple(rl.boost(*p, beta) for p in v) for k, v in cone.items()}
        assert _close(rl.cone_slopes(event, boosted), (1.0, 1.0), 1e-9), beta
    assert rl.inside_future_cone((0.0, 0.0), (0.5, 1.0)) is True
    assert rl.inside_future_cone((0.0, 0.0), (1.5, 1.0)) is False
    assert rl.inside_future_cone((0.0, 0.0), (0.5, -1.0)) is False
    with pytest.raises(rl.RelativityError):
        rl.light_cone((1.0, 2.0), 0.0)


def test_worldlines_inertial_accelerated_and_parametric():
    assert rl.worldline_inertial(1.0, 0.0, 0.5, 4.0) == (3.0, 4.0)
    assert rl.worldline_inertial(1.0, 2.0, -0.25, 6.0) == (0.0, 6.0)
    with pytest.raises(rl.RelativityError):
        rl.worldline_inertial(0.0, 0.0, 1.0, 1.0)
    # Rindler: x = (cosh(a tau) - 1) / a, t = sinh(a tau) / a, in units of c
    x, t = rl.worldline_accelerated(2.0, 1.0)
    assert _close((x, t), ((math.cosh(2.0) - 1.0) / 2.0, math.sinh(2.0) / 2.0), 1e-12)
    assert rl.worldline_accelerated(2.0, 0.0) == (0.0, 0.0)
    assert _close(rl.accelerated_beta(2.0, 1.0), math.tanh(2.0), 1e-12)
    # proper time along the hyperbola is tau: the interval between tau and tau + h is h^2 to second order
    for tau in (0.0, 0.5, 2.0):
        h = 1e-4
        ds2 = rl.interval_between(rl.worldline_accelerated(1.5, tau), rl.worldline_accelerated(1.5, tau + h))
        assert abs(ds2 - h * h) < 1e-12, tau
    # the hyperbola (x + 1/a)^2 - t^2 = 1/a^2
    x, t = rl.worldline_accelerated(0.5, 3.0)
    assert _close((x + 2.0) ** 2 - t * t, 4.0, 1e-9)
    with pytest.raises(rl.RelativityError):
        rl.worldline_accelerated(0.0, 1.0)
    assert rl.worldline_parametric(lambda s: 2.0 * s, lambda s: 3.0 * s, 0.5) == (1.0, 1.5)
    with pytest.raises(rl.RelativityError):
        rl.worldline_parametric(lambda s: 2.0 * s, lambda s: s, 0.5)  # spacelike tangent


def test_grid_lines_of_the_boosted_frame():
    # x' = k: x = k / gamma + beta t; t' = k: t = k / gamma + beta x
    assert _close(rl.grid_x_line(0.6, 2.0, 0.0), (1.6, 0.0), 1e-12)
    assert _close(rl.grid_x_line(0.6, 2.0, 1.0), (2.2, 1.0), 1e-12)
    assert _close(rl.grid_t_line(0.6, 2.0, 0.0), (0.0, 1.6), 1e-12)
    assert _close(rl.grid_t_line(0.6, 2.0, 1.0), (1.0, 2.2), 1e-12)
    for point in (rl.grid_x_line(0.6, 2.0, 0.7), rl.grid_x_line(0.6, 2.0, -3.0)):
        assert _close(rl.boost(*point, 0.6)[0], 2.0, 1e-12)
    for point in (rl.grid_t_line(0.6, 2.0, 0.7), rl.grid_t_line(0.6, 2.0, -3.0)):
        assert _close(rl.boost(*point, 0.6)[1], 2.0, 1e-12)
    assert rl.grid_x_line(0.0, 2.0, 5.0) == (2.0, 5.0)
    lines = rl.boosted_grid(0.6, 3, 2.0)
    assert len(lines["x"]) == 7 and len(lines["t"]) == 7
    assert all(len(seg) == 2 for seg in lines["x"] + lines["t"])


# ------------------------------------------------------------------------------------ compactification


def test_penrose_compactification_of_minkowski_space():
    assert rl.penrose(0.0, 0.0) == (0.0, 0.0)
    X, T = rl.penrose(1.0, 0.0)
    assert _close((X, T), (math.atan(1.0), 0.0), 1e-15)
    X, T = rl.penrose(0.0, 1.0)
    assert _close((X, T), (0.0, math.atan(1.0)), 1e-15)
    # the whole plane lands inside the diamond |X| + |T| < pi / 2
    for x, t in ((1.0e6, 0.0), (0.0, -1.0e9), (3.0e4, 3.0e4 + 1.0), (-5.0e5, 2.0e5)):
        X, T = rl.penrose(x, t)
        assert abs(X) + abs(T) < math.pi / 2.0
    assert _close(rl.penrose_inverse(*rl.penrose(2.0, -3.0)), (2.0, -3.0), 1e-12)
    assert rl.PENROSE_EXTENT == math.pi / 2.0
    with pytest.raises(rl.RelativityError):
        rl.penrose_inverse(1.0, 1.0)


def test_null_rays_stay_at_45_degrees_in_the_penrose_diamond():
    for x, t in ((0.0, 0.0), (2.0, -1.0), (-30.0, 7.0)):
        for s in (0.5, 10.0, 1.0e4):
            a = rl.penrose(x, t)
            b = rl.penrose(x + s, t + s)
            assert _close(b[0] - a[0], b[1] - a[1], 1e-12), (x, t, s)
            c = rl.penrose(x - s, t + s)
            assert _close(c[0] - a[0], -(c[1] - a[1]), 1e-12), (x, t, s)
    assert rl.penrose_slope((2.0, -1.0), 1.0) == 1.0
    assert rl.penrose_slope((2.0, -1.0), -1.0) == -1.0
    # spacelike infinity and timelike infinity
    assert _close(rl.penrose_infinity("spacelike"), (math.pi / 2.0, 0.0), 1e-15)
    assert _close(rl.penrose_infinity("future"), (0.0, math.pi / 2.0), 1e-15)
    assert _close(rl.penrose_infinity("past"), (0.0, -math.pi / 2.0), 1e-15)
    with pytest.raises(rl.RelativityError):
        rl.penrose_infinity("sideways")


def test_kruskal_coordinates_of_the_schwarzschild_solution():
    rs = 2.0
    T, X = rl.kruskal(6.0, 0.0, rs)
    assert T == 0.0 and _close(X, math.sqrt(2.0) * math.exp(1.5), 1e-12)
    # exterior: X^2 - T^2 = (r / rs - 1) e^(r / rs) for every t
    for r in (2.5, 6.0, 40.0):
        for t in (0.0, 3.0, -11.0):
            T, X = rl.kruskal(r, t, rs)
            assert _rel(X * X - T * T, (r / rs - 1.0) * math.exp(r / rs), 1e-9), (r, t)
            assert X > abs(T)
    # interior: T^2 - X^2 = (1 - r / rs) e^(r / rs)
    for r in (0.5, 1.0, 1.9):
        for t in (0.0, 2.0, -5.0):
            T, X = rl.kruskal(r, t, rs)
            assert _rel(T * T - X * X, (1.0 - r / rs) * math.exp(r / rs), 1e-9), (r, t)
            assert T > abs(X)
    # the horizon is the pair of diagonals, the singularity the hyperbola T^2 - X^2 = 1
    assert rl.kruskal(rs, 5.0, rs) == (0.0, 0.0)
    assert _close(rl.kruskal_singularity(0.0), 1.0, 1e-15)
    assert _close(rl.kruskal_singularity(3.0), math.sqrt(10.0), 1e-15)
    for r in (0.5, 1.0, 1.9, 2.5, 6.0, 40.0):
        for t in (0.0, 3.0):
            T, X = rl.kruskal(r, t, rs)
            assert _rel(rl.kruskal_radius(T, X, rs), r, 1e-9), (r, t)
    assert rl.kruskal_radius(0.0, 0.0, rs) == rs
    with pytest.raises(rl.RelativityError):
        rl.kruskal(0.0, 0.0, rs)
    with pytest.raises(rl.RelativityError):
        rl.kruskal(1.0, 0.0, 0.0)
    with pytest.raises(rl.RelativityError):
        rl.kruskal_radius(2.0, 0.0, rs)  # beyond the singularity


def test_the_schwarzschild_penrose_diagram_has_the_singularity_on_a_horizontal_line():
    rs = 2.0
    for X in (-4.0, -0.5, 0.0, 1.0, 7.0):
        T = rl.kruskal_singularity(X)
        assert _close(rl.penrose(X, T)[1], math.pi / 4.0, 1e-12), X
    # the horizon T = +-X lands on the diagonals through the origin
    for X in (0.2, 1.0, 5.0):
        Xp, Tp = rl.penrose(X, X)
        assert _close(Xp, Tp, 1e-15)
        Xp, Tp = rl.penrose(X, -X)
        assert _close(Xp, -Tp, 1e-15)
    # a static exterior point moves along a curve of constant r as t grows
    a = rl.penrose_schwarzschild(6.0, 0.0, rs)
    b = rl.penrose_schwarzschild(6.0, 4.0, rs)
    assert a != b and abs(a[0]) + abs(a[1]) < math.pi / 2.0 and abs(b[0]) + abs(b[1]) < math.pi / 2.0
    assert _close(rl.penrose_schwarzschild(6.0, 0.0, rs)[1], 0.0, 1e-15)
    assert rl.COMPACT_MODES == ("none", "minkowski", "schwarzschild")
    assert rl.compactify(2.0, -3.0, "none") == (2.0, -3.0)
    assert rl.compactify(2.0, -3.0, "minkowski") == rl.penrose(2.0, -3.0)
    assert rl.compactify(6.0, 4.0, "schwarzschild", rs) == rl.penrose_schwarzschild(6.0, 4.0, rs)
    with pytest.raises(rl.RelativityError):
        rl.compactify(2.0, -3.0, "kruskal")


# ------------------------------------------------------------------------------------ embeddings


def test_flamms_paraboloid_and_its_slope():
    assert rl.flamm(2.0, 2.0) == 0.0
    assert _close(rl.flamm(4.0, 2.0), 2.0 * math.sqrt(4.0), 1e-12)
    assert _close(rl.flamm(3.0, 1.0), 2.0 * math.sqrt(2.0), 1e-12)
    for r in (2.5, 4.0, 50.0):
        h = 1e-6
        numeric = (rl.flamm(r + h, 2.0) - rl.flamm(r - h, 2.0)) / (2 * h)
        assert _rel(rl.flamm_slope(r, 2.0), numeric, 1e-6)
    assert _close(rl.flamm_slope(4.0, 2.0), 1.0, 1e-12)
    with pytest.raises(rl.RelativityError):
        rl.flamm(1.0, 2.0)
    with pytest.raises(rl.RelativityError):
        rl.flamm(3.0, 0.0)
    # the paraboloid z^2 = 4 rs (r - rs)
    for r in (2.0, 3.0, 10.0):
        assert _close(rl.flamm(r, 2.0) ** 2, 8.0 * (r - 2.0), 1e-9)


def test_radial_arc_length_on_the_sheet_is_the_proper_radial_distance():
    rs = 2.0
    for r1, r2 in ((2.0, 4.0), (3.0, 10.0), (2.5, 100.0)):
        proper = rl.proper_radial_distance(r1, r2, rs)
        assert proper > r2 - r1
        assert _rel(rl.flamm_arc_length(r1, r2, rs), proper, 1e-6), (r1, r2)
    assert rl.proper_radial_distance(5.0, 5.0, rs) == 0.0
    assert _rel(rl.proper_radial_distance(1.0e6, 1.0e6 + 1.0, rs), 1.0, 1e-5)
    with pytest.raises(rl.RelativityError):
        rl.proper_radial_distance(1.0, 4.0, rs)
    with pytest.raises(rl.RelativityError):
        rl.proper_radial_distance(4.0, 3.0, rs)


def test_gaussian_curvature_of_flamms_paraboloid():
    rs = 2.0
    for r in (2.5, 4.0, 10.0):
        assert _rel(rl.flamm_curvature(r, rs), -rs / (2.0 * r ** 3), 1e-12)
        # a surface of revolution z(r): K = z' z'' / (r (1 + z'^2)^2)
        h = 1e-4
        z1 = rl.flamm_slope(r, rs)
        z2 = (rl.flamm_slope(r + h, rs) - rl.flamm_slope(r - h, rs)) / (2 * h)
        assert _rel(rl.flamm_curvature(r, rs), z1 * z2 / (r * (1.0 + z1 * z1) ** 2), 1e-6)
    assert rl.flamm_curvature(10.0, rs) < 0.0


def test_the_potential_sheet_and_embedding_points():
    assert rl.potential(2.0, 4.0) == -2.0
    assert _close(rl.potential_slope(2.0, 4.0), 1.0, 1e-12)
    with pytest.raises(rl.RelativityError):
        rl.potential(0.0, 4.0)
    assert rl.EMBEDDINGS == ("flamm", "potential")
    p = rl.embedding_point("flamm", 4.0, 0.0, 2.0)
    assert _close(p, (4.0, -4.0, 0.0), 1e-12)
    p = rl.embedding_point("flamm", 4.0, math.pi / 2.0, 2.0)
    assert _close(p, (0.0, -4.0, 4.0), 1e-12)
    # the potential sheet sags downward: z = -k / r is the height and scene y = -z = k / r points down
    p = rl.embedding_point("potential", 2.0, math.pi, 4.0)
    assert _close(p, (-2.0, 2.0, 0.0), 1e-12)
    assert rl.embedding_point("potential", 1.0, 0.0, 4.0)[1] > rl.embedding_point("potential", 4.0, 0.0, 4.0)[1] > 0.0
    assert rl.embedding_point("flamm", 2.0, 0.0, 2.0)[1] == 0.0 > rl.embedding_point("flamm", 4.0, 0.0, 2.0)[1]
    with pytest.raises(rl.RelativityError):
        rl.embedding_point("rubber", 4.0, 0.0, 2.0)
    grid = rl.embedding_grid("flamm", 2.0, 10.0, 4, 8, 16, 2.0)
    assert len(grid["rings"]) == 4 and len(grid["spokes"]) == 8
    assert all(len(ring) == 16 for ring in grid["rings"])
    assert all(len(spoke) == 16 for spoke in grid["spokes"])
    assert _close(grid["rings"][0][0], rl.embedding_point("flamm", 2.0, 0.0, 2.0), 1e-12)
    assert _close(grid["rings"][-1][0], rl.embedding_point("flamm", 10.0, 0.0, 2.0), 1e-12)
    assert _close(grid["spokes"][0][-1], rl.embedding_point("flamm", 10.0, 0.0, 2.0), 1e-12)
    assert _close(grid["spokes"][1][0], rl.embedding_point("flamm", 2.0, 2.0 * math.pi / 8.0, 2.0), 1e-12)
    # the sheet keeps its own rs or k, whatever rMin is
    wide = rl.embedding_grid("flamm", 4.0, 10.0, 2, 3, 2, 2.0)
    assert _close(wide["rings"][0][0], rl.embedding_point("flamm", 4.0, 0.0, 2.0), 1e-12)
    assert wide["rings"][0][0][1] == -4.0
    well = rl.embedding_grid("potential", 1.0, 10.0, 2, 3, 2, 4.0)
    assert _close(well["rings"][0][0], (1.0, 4.0, 0.0), 1e-12) and _close(well["spokes"][0][-1], (10.0, 0.4, 0.0), 1e-12)
    for args in (("flamm", 2.0, 1.0, 4, 8, 16, 2.0), ("flamm", 1.0, 10.0, 4, 8, 16, 2.0),
                 ("potential", 1.0, 10.0, 4, 8, 16, 0.0)):
        with pytest.raises(rl.RelativityError):
            rl.embedding_grid(*args)


# ------------------------------------------------------------------------------------ gravitational-wave strain


def test_strain_displaces_a_ring_into_the_plus_and_cross_ellipses():
    assert rl.strain_displacement(1.0, 0.0, 0.2, 0.0) == (0.1, 0.0)
    assert rl.strain_displacement(0.0, 1.0, 0.2, 0.0) == (0.0, -0.1)
    d = rl.strain_displacement(1.0, 0.0, 0.0, 0.2)
    assert _close(d, (0.0, 0.1), 1e-15)
    axes = rl.ring_axes(0.2, 0.0)
    assert _close(axes, (1.1, 0.9), 1e-12)
    assert _close(rl.ring_axes(0.0, 0.2), (1.1, 0.9), 1e-12)
    assert _close(rl.ring_axes(0.0, 0.0), (1.0, 1.0), 1e-12)
    # the cross polarisation stretches along the diagonal
    s = 1.0 / math.sqrt(2.0)
    x, y = rl.strain_point(s, s, 0.0, 0.2, 1.0, 0.0, 0.0)
    assert _close(math.hypot(x, y), 1.1, 1e-12)
    x, y = rl.strain_point(s, -s, 0.0, 0.2, 1.0, 0.0, 0.0)
    assert _close(math.hypot(x, y), 0.9, 1e-12)
    # the displacement oscillates at the wave frequency and vanishes a quarter period later
    x, y = rl.strain_point(1.0, 0.0, 0.2, 0.0, 2.0, 0.125, 0.0)
    assert _close((x, y), (1.0, 0.0), 1e-12)
    x, y = rl.strain_point(1.0, 0.0, 0.2, 0.0, 2.0, 0.25, 0.0)
    assert _close((x, y), (0.9, 0.0), 1e-12)
    x, y = rl.strain_point(1.0, 0.0, 0.2, 0.0, 2.0, 0.0, math.pi)
    assert _close((x, y), (0.9, 0.0), 1e-12)
    ring = rl.strained_ring(0.2, 0.0, 8, 1.0, 1.0, 0.0, 0.0)
    assert len(ring) == 8
    assert _close(ring[0], (1.1, 0.0), 1e-12)
    assert _close(ring[2], (0.0, 0.9), 1e-12)


def test_chirp_mass_frequency_and_amplitude_follow_the_quadrupole_formula():
    m = rl.chirp_mass(30.0, 30.0)
    assert _rel(m, 30.0 * 2.0 ** -0.2, 1e-12)
    assert _rel(rl.chirp_mass(36.0, 29.0), (36.0 * 29.0) ** 0.6 / 65.0 ** 0.2, 1e-12)
    mc = 28.0 * rl.M_SUN
    f = rl.gw_frequency(0.2, mc)
    assert 30.0 < f < 40.0
    assert rl.gw_frequency(0.05, mc) > f
    assert _rel(rl.gw_frequency(rl.time_to_merger(150.0, mc), mc), 150.0, 1e-9)
    assert _rel(rl.time_to_merger(f, mc), 0.2, 1e-9)
    h = rl.gw_amplitude(410.0 * rl.MPC_M, mc, 150.0)
    assert 1.0e-21 < h < 3.0e-21
    assert _rel(rl.gw_amplitude(820.0 * rl.MPC_M, mc, 150.0), h / 2.0, 1e-12)
    assert rl.G == 6.67430e-11 and rl.C == 299792458.0 and rl.M_SUN == 1.98841e30
    assert _rel(rl.MPC_M, 1.0e6 * 648000.0 / math.pi * 149597870700.0, 1e-15)
    for args in ((0.0, mc), (1.0, 0.0)):
        with pytest.raises(rl.RelativityError):
            rl.gw_frequency(*args)
    with pytest.raises(rl.RelativityError):
        rl.gw_amplitude(0.0, mc, 150.0)
    with pytest.raises(rl.RelativityError):
        rl.chirp_mass(0.0, 1.0)


def test_chirp_phase_accumulates_cycles():
    mc = 28.0 * rl.M_SUN
    # the phase from tau1 to tau2 before merger is the integral of 2 pi f
    tau1, tau2 = 0.2, 0.05
    cycles = rl.chirp_cycles(tau1, tau2, mc)
    assert cycles > 0.0
    n = 2000
    numeric = 0.0
    for i in range(n):
        tau = tau1 + (tau2 - tau1) * (i + 0.5) / n
        numeric += rl.gw_frequency(tau, mc) * (tau1 - tau2) / n
    assert _rel(cycles, numeric, 1e-4)
    assert rl.chirp_cycles(0.2, 0.2, mc) == 0.0
    with pytest.raises(rl.RelativityError):
        rl.chirp_cycles(0.05, 0.2, mc)


# ------------------------------------------------------------------------------------ animation and mapping


def test_a_keyed_boost_moves_in_rapidity_and_seeks():
    assert rl.frame_beta(0, 24.0, 0.0, 0.8, 0.0, 10.0) == 0.0
    assert _close(rl.frame_beta(240, 24.0, 0.0, 0.8, 0.0, 10.0), 0.8, 1e-15)
    mid = rl.frame_beta(120, 24.0, 0.0, 0.8, 0.0, 10.0)
    assert _close(mid, rl.beta_from_rapidity(rl.rapidity(0.8) / 2.0), 1e-15)
    assert _close(rl.compose_beta(mid, mid), 0.8, 1e-12)
    assert rl.frame_beta(480, 24.0, 0.0, 0.8, 0.0, 10.0) == rl.frame_beta(240, 24.0, 0.0, 0.8, 0.0, 10.0)
    assert rl.seek_test() is True
    # the seek check holds the interval on both sides
    assert rl.boost_keeps_interval(3.0, 5.0, 0.6) and rl.boost_keeps_interval(3.0, 5.0, 0.0)
    assert not rl.boost_keeps_interval(3.0, 5.0, 0.6, want=16.0 + 1e-6)
    assert not rl.boost_keeps_interval(3.0, 5.0, 0.6, want=16.0 - 1e-6)
    with pytest.raises(rl.RelativityError):
        rl.frame_beta(-1, 24.0, 0.0, 0.8, 0.0, 10.0)
    with pytest.raises(rl.RelativityError):
        rl.frame_beta(1, 24.0, 0.0, 1.0, 0.0, 10.0)
    with pytest.raises(rl.RelativityError):
        rl.frame_beta(1, 24.0, 0.0, 0.8, 5.0, 5.0)


def test_diagram_points_map_to_pixels_through_the_axes_box():
    box = {"x": 100.0, "y": 50.0, "width": 400.0, "height": 300.0, "xMin": -2.0, "xMax": 2.0, "yMin": -1.5,
           "yMax": 1.5}
    assert rl.diagram_pixel(0.0, 0.0, box) == (300.0, 200.0)
    assert rl.diagram_pixel(-2.0, 1.5, box) == (100.0, 50.0)
    assert rl.diagram_pixel(2.0, -1.5, box) == (500.0, 350.0)
    assert rl.diagram_pixel(1.0, 0.0, box, 0.6) == rl.diagram_pixel(*rl.boost(1.0, 0.0, 0.6), box)
    assert rl.diagram_pixel(1.0, 0.0, box, 0.0, "minkowski") == rl.diagram_pixel(*rl.penrose(1.0, 0.0), box)
    with pytest.raises(rl.RelativityError):
        rl.diagram_pixel(0.0, 0.0, {**box, "xMin": 2.0})


# ------------------------------------------------------------------------------------ validation


def test_validation_rd1_to_rd4():
    rl.validate_spacetime(1.0, 0.6, "none")
    rl.validate_spacetime(2.5, -0.999, "schwarzschild", 2.0)
    for args in ((0.0, 0.6, "none"), (1.0, 1.0, "none"), (1.0, 0.0, "kruskal"), (1.0, 0.0, "schwarzschild", 0.0)):
        with pytest.raises(rl.RelativityError):
            rl.validate_spacetime(*args)
    rl.validate_worldline("inertial", 0.5, None)
    rl.validate_worldline("accelerated", None, 2.0)
    rl.validate_worldline("parametric", None, None)
    for args in (("inertial", 1.0, None), ("accelerated", None, 0.0), ("geodesic", None, None),
                 ("inertial", None, None)):
        with pytest.raises(rl.RelativityError):
            rl.validate_worldline(*args)
    rl.validate_embedding("flamm", 2.0, 10.0, 4, 8)
    rl.validate_embedding("potential", 1.0, 10.0, 1, 3)
    for args in (("flamm", 0.0, 10.0, 4, 8), ("flamm", 2.0, 2.0, 4, 8), ("flamm", 2.0, 10.0, 0, 8),
                 ("flamm", 2.0, 10.0, 4, 2), ("sheet", 2.0, 10.0, 4, 8)):
        with pytest.raises(rl.RelativityError):
            rl.validate_embedding(*args)
    rl.validate_strain(0.2, 0.0, 2.0, None)
    rl.validate_strain(0.2, 0.1, None, 28.0, 1.0)
    rl.validate_strain(0.2, 0.0, 2.0, None, 1.0)
    # RD4: exactly one of frequency and chirpMass, and chirpMass comes with merger
    for args in ((1.5, 0.0, 2.0, None), (0.0, -1.5, 2.0, None), (0.2, 0.0, 0.0, None), (0.2, 0.0, None, None),
                 (0.2, 0.0, None, 0.0, 1.0), (0.2, 0.0, 2.0, 28.0, 1.0), (0.2, 0.0, None, 28.0)):
        with pytest.raises(rl.RelativityError):
            rl.validate_strain(*args)


def test_scope_and_same():
    s = rl.scope()
    assert s["math"] is math
    assert s["boost"] is rl.boost
    assert rl._same(1.0, 1.0 + 1e-7)
    assert not rl._same(1.0, 1.01)
    assert rl._same("timelike", "timelike")
    assert rl._same((1.0, 2.0), (1.0, 2.0 + 1e-9))
    assert rl._fmt(2.0) == "2"
    assert rl._fmt("timelike") == "'timelike'"


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
    assert "SR-92" in draft
    for word in ("spacetime", "boost", "rapidity", "event", "worldline", "lightRay", "lightCone", "compact",
                 "minkowski", "schwarzschild", "penrose", "Kruskal", "embedding", "flamm", "potential", "strain",
                 "hPlus", "hCross", "chirpMass", "frequency", "interval", "Flamm", "Penrose", "Rindler",
                 "RD1", "RD2", "RD3", "RD4", "V17", "seek check", "relativity_reference.py", "SREP 14",
                 "SREP 76", "axes", "primitive", "modifier", "Misner", "Thorne", "Wheeler", "Carroll",
                 "Maggiore", "Abbott", "SR-92"):
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
    s = rl.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or rl._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    rl.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())


def test_the_draft_records_the_engine_state(draft):
    row = next(line for line in draft.splitlines() if line.startswith("| Rust (`rs-scene-render`), reference |"))
    done, remaining = row.split(" | ")[1:3]
    assert done.startswith("feat/sr-67-fields 011b842") and "`sr_3d::relativity`" in done and "SR-92" in row
    assert "nothing of this SREP at 67a661a" not in done
    assert remaining.startswith("parse the elements") and "the seek check (rule 5)" in remaining
    assert "| embedding point of the potential sheet r 2, k 4 | `embedding_point('potential', 2, 0, 4)` | `(2, 2, 0)` |" in draft
    assert "the sheet's y at `rMin` is k/`rMin`" in draft
