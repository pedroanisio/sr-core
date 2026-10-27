"""Tests of the draft SREP "Add orbits and N-body motion" (srep/srep-0000-orbits.md) and of its reference
implementation conformance/tools/orbits_reference.py (SP4 of SREP 12, SRC-47).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "orbits_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-orbits.md")
TIME_FRAMES = os.path.join(ROOT, "conformance", "tools", "time_frames_reference.py")
RANDOM = os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py")

_spec = importlib.util.spec_from_file_location("orbits_reference", MODULE)
ob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ob)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _ang(a, b):
    """Difference of two angles in degrees, modulo 360."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _rel(a, b):
    """Relative distance of two vectors or numbers."""
    if isinstance(a, (tuple, list)):
        return ob.norm(ob.sub(a, b)) / max(ob.norm(a), ob.norm(b), 1e-300)
    return abs(a - b) / max(abs(a), abs(b), 1e-300)


MU = ob.GM_SUN
AU = ob.AU_M


def _earth():
    """A circular 1 au orbit in the plane: period one year to 0.1 %."""
    v = math.sqrt(MU / AU)
    return (AU, 0.0, 0.0), (0.0, v, 0.0)


def _sun_earth(sun_mass=1.98892e30):
    r, v = _earth()
    return ob.system([sun_mass, 5.9722e24], [(0.0, 0.0, 0.0), r], [(0.0, 0.0, 0.0), v])


# ------------------------------------------------------------------------------------ rule 1: Kepler


def test_the_constants():
    assert ob.G == 6.67430e-11 and ob.AU_M == 149597870700.0
    assert ob.GM[10] == ob.GM_SUN and ob.GM[399] == ob.GM_EARTH
    assert set(ob.GM) == {10, 199, 299, 399, 499, 599, 699, 799, 899, 301}
    assert _close(ob.period(MU, AU) / ob.DAY_S, 365.2569, 1e-3)  # the sidereal year
    assert ob.INTEGRATORS == ("leapfrog", "wisdomHolman", "ias15")
    with pytest.raises(ob.OrbitError):
        ob.period(MU, -AU)


def test_keplers_equation():
    for e in (0.0, 0.1, 0.5, 0.9, 0.99):
        for m in (-3.0, -1.0, 0.0, 0.3, 2.0, 3.1):
            big_e = ob.kepler_elliptic(m, e)
            assert _close(big_e - e * math.sin(big_e), m, 1e-13)
    for e in (1.1, 2.0, 5.0):
        for m in (-4.0, 0.0, 0.5, 6.0):
            h = ob.kepler_hyperbolic(m, e)
            assert _close(e * math.sinh(h) - h, m, 1e-12)
    with pytest.raises(ob.OrbitError):
        ob.kepler_elliptic(0.0, 1.0)
    with pytest.raises(ob.OrbitError):
        ob.kepler_hyperbolic(0.0, 0.9)


def test_elements_and_state_round_trip_to_1e_12():
    cases = [
        (AU, 0.0167, 0.0, 0.0, 102.9, 0.0),
        (1.5 * AU, 0.3, 25.0, 80.0, 200.0, 135.0),
        (0.4 * AU, 0.8, 90.0, 10.0, 350.0, -30.0),
        (3.0 * AU, 0.1, 150.0, 300.0, 45.0, 180.0),
        (-0.5 * AU, 1.5, 30.0, 60.0, 90.0, 20.0),  # hyperbolic
    ]
    for a, e, inc, raan, argp, nu in cases:
        r, v = ob.state_from_elements(MU, a, e, inc, raan, argp, nu)
        el = ob.elements_from_state(MU, r, v)
        assert _rel(el["a"], a) < 1e-12 and abs(el["e"] - e) < 1e-12
        assert abs(el["i"] - inc) < 1e-9 and _ang(el["raan"], raan) < 1e-9
        assert _ang(el["argp"], argp) < 1e-9 and _ang(el["nu"], nu) < 1e-9
        r2, v2 = ob.state_from_elements(MU, el["a"], el["e"], el["i"], el["raan"], el["argp"], el["nu"])
        assert _rel(r, r2) < 1e-12 and _rel(v, v2) < 1e-12
    el = ob.elements_from_state(MU, *_earth())
    assert el["e"] < 1e-15 and _rel(el["a"], AU) < 1e-14 and _rel(el["period"], ob.period(MU, AU)) < 1e-14
    assert el["energy"] < 0.0 and _rel(ob.norm(el["h"]), AU * math.sqrt(MU / AU)) < 1e-14
    hy = ob.elements_from_state(MU, *ob.state_from_elements(MU, -0.5 * AU, 1.5, 0.0, 0.0, 0.0, 0.0))
    assert hy["period"] is None and hy["energy"] > 0.0
    with pytest.raises(ob.OrbitError):
        ob.state_from_elements(MU, AU, 1.0, 0.0, 0.0, 0.0, 0.0)  # the parabola is excluded
    with pytest.raises(ob.OrbitError):
        ob.state_from_elements(MU, -AU, 0.5, 0.0, 0.0, 0.0, 0.0)  # a < 0 needs e > 1
    with pytest.raises(ob.OrbitError):
        ob.elements_from_state(MU, (AU, 0.0, 0.0), (0.0, 0.0, 0.0))  # a radial fall has no orbit plane


def test_stumpff_functions():
    assert _close(ob.stumpff_c2(0.0), 0.5) and _close(ob.stumpff_c3(0.0), 1.0 / 6.0)
    assert _close(ob.stumpff_c2(1e-9), 0.5 - 1e-9 / 24.0, 1e-15) and _close(ob.stumpff_c3(1e-9), 1.0 / 6.0 - 1e-9 / 120.0, 1e-15)
    for z in (1e-3, 0.5, 4.0, 30.0):
        assert _close(ob.stumpff_c2(z), (1.0 - math.cos(math.sqrt(z))) / z, 1e-9)
        assert _close(ob.stumpff_c3(z), (math.sqrt(z) - math.sin(math.sqrt(z))) / math.sqrt(z) ** 3, 1e-9)
        assert _close(ob.stumpff_c2(-z), (math.cosh(math.sqrt(z)) - 1.0) / z, 1e-9)
        assert _close(ob.stumpff_c3(-z), (math.sinh(math.sqrt(z)) - math.sqrt(z)) / math.sqrt(z) ** 3, 1e-9)


def test_universal_propagation_closes_the_orbit_to_1e_12():
    for a, e, inc, raan, argp, nu in ((AU, 0.0167, 7.0, 10.0, 20.0, 30.0), (0.3 * AU, 0.9, 60.0, 0.0, 0.0, 170.0),
                                     (2.0 * AU, 0.5, 0.0, 0.0, 90.0, 0.0)):
        r, v = ob.state_from_elements(MU, a, e, inc, raan, argp, nu)
        p = ob.period(MU, a)
        r1, v1 = ob.propagate(MU, r, v, p)
        assert _rel(r, r1) < 1e-12 and _rel(v, v1) < 1e-12, (a, e, _rel(r, r1), _rel(v, v1))
        assert ob.closure(MU, r, v) < 1e-12
        # a quarter period forward then back is the identity, and energy is kept
        r2, v2 = ob.propagate(MU, *ob.propagate(MU, r, v, p / 4.0), -p / 4.0)
        assert _rel(r, r2) < 1e-12 and _rel(v, v2) < 1e-12
        e0 = ob.specific_energy(MU, r, v)
        for t in (p / 7.0, p / 3.0, 2.5 * p):
            rt, vt = ob.propagate(MU, r, v, t)
            assert _rel(ob.specific_energy(MU, rt, vt), e0) < 1e-12
    # the propagated anomaly agrees with Kepler's equation
    r, v = ob.state_from_elements(MU, AU, 0.3, 0.0, 0.0, 0.0, 0.0)
    rt, vt = ob.propagate(MU, r, v, ob.period(MU, AU) / 4.0)
    big_e = ob.kepler_elliptic(math.pi / 2.0, 0.3)
    nu = 2.0 * math.atan2(math.sqrt(1.3) * math.sin(big_e / 2.0), math.sqrt(0.7) * math.cos(big_e / 2.0))
    assert _close(ob.elements_from_state(MU, rt, vt)["nu"], math.degrees(nu), 1e-7)
    # hyperbolic: 10 days forward and back
    r, v = ob.state_from_elements(MU, -0.5 * AU, 1.5, 30.0, 60.0, 90.0, 20.0)
    rb, vb = ob.propagate(MU, *ob.propagate(MU, r, v, 10.0 * ob.DAY_S), -10.0 * ob.DAY_S)
    assert _rel(r, rb) < 1e-12 and _rel(v, vb) < 1e-12
    with pytest.raises(ob.OrbitError):
        ob.propagate(MU, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0)


def test_propagation_agrees_with_the_standish_elements():
    tf = _load(TIME_FRAMES, "time_frames_reference")
    # the Earth-Moon barycentre's heliocentric position from the time-frames elements at J2000 and 30 days later;
    # the two-body propagation of the first state over 30 days lands within the elements' own accuracy
    p0 = tuple(x * 1000.0 for x in tf.approximate_position(3, 0.0))
    p1 = tuple(x * 1000.0 for x in tf.approximate_position(3, 30.0 * ob.DAY_S))
    pm = tuple(x * 1000.0 for x in tf.approximate_position(3, -1.0))
    pp = tuple(x * 1000.0 for x in tf.approximate_position(3, 1.0))
    v0 = ob.mul(ob.sub(pp, pm), 0.5)  # central difference over two seconds, m/s
    assert _close(ob.norm(v0), 30287.0, 100.0)
    r30, _ = ob.propagate(MU, p0, v0, 30.0 * ob.DAY_S)
    assert ob.norm(ob.sub(r30, p1)) < 2000e3  # 2000 km over 30 days: the elements are secular, the Moon is not in them
    el = ob.elements_from_state(MU, p0, v0)
    assert abs(el["e"] - 0.01671) < 2e-4 and _rel(el["a"], 1.00000261 * AU) < 1e-4


def test_the_orbit_element_places_the_object():
    orb = ob.orbit(MU, a=AU, e=0.0167, i=0.0, raan=0.0, argp=102.9, anomaly=0.0, epoch=0.0)
    r0, v0 = ob.orbit_state(orb, 0.0)
    assert _rel(ob.norm(r0), AU * (1.0 - 0.0167)) < 1e-12  # perihelion at the epoch
    rp, _ = ob.orbit_state(orb, ob.period(MU, AU) / 2.0)
    assert _rel(ob.norm(rp), AU * (1.0 + 0.0167)) < 1e-9
    r1, _ = ob.orbit_state(orb, ob.period(MU, AU))
    assert _rel(r0, r1) < 1e-12
    late = ob.orbit(MU, a=AU, e=0.0167, i=0.0, raan=0.0, argp=102.9, anomaly=0.0, epoch=100.0)
    assert _rel(ob.orbit_state(late, 100.0)[0], r0) < 1e-15
    assert ob.orbit_mu(mass=1.98892e30) == ob.G * 1.98892e30 and ob.orbit_mu(body=399) == ob.GM_EARTH
    with pytest.raises(ob.OrbitError):
        ob.orbit_mu()
    with pytest.raises(ob.OrbitError):
        ob.orbit(MU, a=AU, e=1.2, i=0.0, raan=0.0, argp=0.0, anomaly=0.0, epoch=0.0)


# ------------------------------------------------------------------------------------ rule 2: the system


def test_system_validation_and_invariants():
    s = _sun_earth()
    assert s["n"] == 2 and s["G"] == ob.G and s["softening"] == 0.0
    assert ob.energy(s) < 0.0
    p = ob.momentum(s)
    assert _rel(ob.norm(p), 5.9722e24 * math.sqrt(MU / AU)) < 1e-12
    com = ob.centre_of_mass(s)
    assert 0.0 < com[0] < 1000e3  # the barycentre sits inside the Sun
    L = ob.angular_momentum(s)
    assert L[2] > 0.0 and L[0] == 0.0 and L[1] == 0.0
    a = ob.accelerations(s, s["positions"])
    assert _close(ob.norm(a[1]), ob.G * 1.98892e30 / AU ** 2, 1e-12)
    assert a[0][0] > 0.0 and _rel(a[0][0] * 1.98892e30, -a[1][0] * 5.9722e24) < 1e-12  # Newton's third law
    rest = ob.at_rest(s)
    assert _close(ob.norm(ob.momentum(rest)), 0.0, 1e-6) and _close(ob.norm(ob.centre_of_mass(rest)), 0.0, 1e-6)
    with pytest.raises(ob.OrbitError):
        ob.system([1.0], [(0.0, 0.0, 0.0)], [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)])
    with pytest.raises(ob.OrbitError):
        ob.system([1.0, -1.0], [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)])
    with pytest.raises(ob.OrbitError):
        ob.system([1.0, 1.0], [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)], [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)])


def test_softening_bounds_the_force():
    s = ob.system([1.0, 1.0], [(0.0, 0.0, 0.0), (1e-3, 0.0, 0.0)], [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)], G=1.0,
                  softening=1.0)
    a = ob.accelerations(s, s["positions"])
    assert ob.norm(a[0]) < 1e-3  # 1 / (r^2 + eps^2)^(3/2) * r
    assert _close(ob.norm(a[0]), 1e-3 / (1e-6 + 1.0) ** 1.5, 1e-12)


# ------------------------------------------------------------------------------------ rule 3: integrators


def _kepler_pair():
    """Two bodies in a circular orbit in G = 1 units: masses 1 and 1e-3, separation 1."""
    m, mu = 1e-3, 1.0 + 1e-3
    v = math.sqrt(mu / 1.0)
    return ob.system([1.0, m], [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [(0.0, -v * m / mu, 0.0), (0.0, v / mu, 0.0)],
                     G=1.0)


def test_leapfrog_is_symplectic_and_reversible():
    s = _kepler_pair()
    p = 2.0 * math.pi
    dt = p / 200.0
    drift = ob.energy_drift(s, "leapfrog", dt, 50.0 * p)
    assert drift < 1e-3  # bounded, not growing: the same bound over 10 periods
    assert _close(drift, ob.energy_drift(s, "leapfrog", dt, 10.0 * p), 2e-4)
    assert ob.reversibility(s, "leapfrog", dt, 10.0 * p) < 1e-10
    s1 = ob.integrate(s, "leapfrog", dt, p)
    assert ob.norm(ob.sub(s1["positions"][1], s["positions"][1])) < 5e-3  # a period later, back within the error
    assert _close(ob.norm(ob.momentum(s1)), 0.0, 1e-15)
    with pytest.raises(ob.OrbitError):
        ob.integrate(s, "euler", dt, p)
    with pytest.raises(ob.OrbitError):
        ob.integrate(s, "leapfrog", 0.0, p)
    with pytest.raises(ob.OrbitError):
        ob.integrate(s, "leapfrog", dt, p / 3.0)  # the time is a whole number of steps


def test_leapfrog_error_scales_with_the_square_of_the_step():
    s = _kepler_pair()
    p = 2.0 * math.pi
    e1 = ob.position_error(s, "leapfrog", p / 100.0, p)
    e2 = ob.position_error(s, "leapfrog", p / 200.0, p)
    assert 3.0 < e1 / e2 < 5.0


def test_wisdom_holman_keeps_energy_a_hundred_times_better_than_leapfrog_on_the_same_step():
    s = _kepler_pair()
    p = 2.0 * math.pi
    dt = p / 20.0
    assert ob.energy_drift(s, "wisdomHolman", dt, 20.0 * p) < 1e-9  # a two-body problem is exact in the Kepler drift
    assert ob.energy_drift(s, "leapfrog", dt, 20.0 * p) > 1e-3
    assert ob.reversibility(s, "wisdomHolman", dt, 10.0 * p) < 1e-10
    three = ob.system([1.0, 1e-3, 1e-4], [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
                      [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-math.sqrt(0.5), 0.0, 0.0)], G=1.0)
    three = ob.at_rest(three)
    drift = ob.energy_drift(three, "wisdomHolman", dt, 50.0 * p)
    assert drift < 1e-5
    assert _close(drift, ob.energy_drift(three, "wisdomHolman", dt, 10.0 * p), 1e-5)  # bounded
    assert ob.reversibility(three, "wisdomHolman", dt, 10.0 * p) < 1e-9


def test_the_gauss_radau_nodes():
    h = ob.RADAU_H
    assert len(h) == 8 and h[0] == 0.0 and all(h[i] < h[i + 1] for i in range(7)) and h[-1] < 1.0
    # the nodes integrate polynomials up to degree 2 * 8 - 2 = 14 exactly on [0, 1]
    w = ob.RADAU_W
    assert _close(sum(w), 1.0, 1e-14)
    for k in range(15):
        assert _close(sum(wi * hi ** k for wi, hi in zip(w, h)), 1.0 / (k + 1), 1e-13), k
    assert _close(h[1], 0.0562625605369221, 1e-15) and _close(h[7], 0.9775206135612875, 1e-15)
    assert _close(h[4], 0.5471536263305554, 1e-15)
    # the polynomial coefficients convert the Newton form to the monomial form: both give the same polynomial
    g = (1.0, -0.5, 0.25, -0.125, 0.0625, -0.03125, 0.015625)
    b = ob.b_from_g(g)
    for tau in (0.1, 0.5, 0.9):
        newton = sum(gj * math.prod(tau - h[i] for i in range(1, j + 1)) * tau for j, gj in enumerate(g))
        mono = sum(bk * tau ** (k + 1) for k, bk in enumerate(b))
        assert _close(newton, mono, 1e-14)


def test_ias15_is_fifteenth_order_reversible_and_adaptive():
    s = _kepler_pair()
    p = 2.0 * math.pi
    e1 = ob.position_error(s, "ias15", p / 20.0, p)
    e2 = ob.position_error(s, "ias15", p / 40.0, p)
    assert e1 < 1e-8 and e2 < 1e-12
    assert ob.energy_drift(s, "ias15", p / 20.0, 20.0 * p) < 1e-10
    assert ob.reversibility(s, "ias15", p / 20.0, 10.0 * p) < 1e-10
    # adaptive: an eccentric orbit shrinks its step at pericentre and lands on the end time exactly
    ecc = ob.system([1.0, 1e-3], [(0.0, 0.0, 0.0), (1.9, 0.0, 0.0)], [(0.0, 0.0, 0.0), (0.0, math.sqrt(1.001 * 0.1 / 1.9), 0.0)],
                    G=1.0)
    ecc = ob.at_rest(ecc)
    out, steps = ob.integrate_adaptive(ecc, 2.0 * math.pi, 0.1, 1e-9)
    assert steps["count"] > 10 and steps["min"] < 0.05 < steps["max"]
    assert _close(out["t"], 2.0 * math.pi, 1e-12)
    assert abs(ob.energy(out) - ob.energy(ecc)) / abs(ob.energy(ecc)) < 1e-9
    with pytest.raises(ob.OrbitError):
        ob.integrate_adaptive(ecc, 1.0, 0.1, 0.0)
    with pytest.raises(ob.OrbitError):
        ob.integrate_adaptive(ecc, 1.0, 0.1, 1e-9, max_steps=3)


def test_the_three_body_figure_eight_closes():
    # Chenciner and Montgomery (2000), initial conditions of Simo: period 6.3259
    x1 = (0.97000436, -0.24308753, 0.0)
    v3 = (-0.93240737, -0.86473146, 0.0)
    s = ob.system([1.0, 1.0, 1.0], [x1, ob.mul(x1, -1.0), (0.0, 0.0, 0.0)],
                  [ob.mul(v3, -0.5), ob.mul(v3, -0.5), v3], G=1.0)
    period = 6.32591398
    out = ob.integrate(s, "ias15", period / 400.0, period)
    for a, b in zip(out["positions"], s["positions"]):
        assert ob.norm(ob.sub(a, b)) < 1e-6
    out = ob.integrate(s, "leapfrog", period / 40000.0, period)
    for a, b in zip(out["positions"], s["positions"]):
        assert ob.norm(ob.sub(a, b)) < 1e-4


# ------------------------------------------------------------------------------------ rule 4: the cluster


def test_the_plummer_cluster_is_drawn_from_the_random_streams():
    rs = _load(RANDOM, "random_streams_reference")
    assert ob.U(7, 3, 11) == rs.U(7, 3, 11) and ob.U(-1, 0, 2 ** 40) == rs.U(-1, 0, 2 ** 40)
    c = ob.plummer(seed=42, n=400, total_mass=1.0, scale=1.0, G=1.0)
    assert c["n"] == 400 and _close(sum(c["masses"]), 1.0, 1e-12)
    assert _close(ob.norm(ob.centre_of_mass(c)), 0.0, 1e-12) and _close(ob.norm(ob.momentum(c)), 0.0, 1e-12)
    radii = sorted(ob.norm(p) for p in c["positions"])
    assert 1.0 < radii[200] < 1.6  # the half-mass radius of a Plummer sphere is 1.305 a
    k = ob.kinetic(c)
    w = ob.potential(c)
    assert 0.7 < 2.0 * k / abs(w) < 1.3  # virial equilibrium, within the noise of 400 bodies
    assert c == ob.plummer(seed=42, n=400, total_mass=1.0, scale=1.0, G=1.0)  # deterministic
    assert c["positions"][0] != ob.plummer(seed=43, n=400, total_mass=1.0, scale=1.0, G=1.0)["positions"][0]
    # the samples are per index, so a bigger cluster keeps the smaller one's bodies up to the recentring shift
    shift = ob.sub(c["positions"][3], ob.plummer_sample(42, 3, 1.0, 1.0, 1.0)[0])
    assert _close(shift, ob.sub(c["positions"][7], ob.plummer_sample(42, 7, 1.0, 1.0, 1.0)[0]), 1e-12)
    with pytest.raises(ob.OrbitError):
        ob.plummer(seed=1, n=1, total_mass=1.0, scale=1.0, G=1.0)
    with pytest.raises(ob.OrbitError):
        ob.plummer(seed=1, n=ob.MAX_BODIES + 1, total_mass=1.0, scale=1.0, G=1.0)


def test_plummer_radius_and_speed_laws():
    # the inverse of the Plummer cumulative mass and the speed sampling of Aarseth, Henon and Wielen
    assert _close(ob.plummer_radius(0.5, 1.0), 1.0 / math.sqrt(0.5 ** (-2.0 / 3.0) - 1.0))
    assert _close(ob.plummer_radius(0.5, 1.0), 1.3048, 1e-3)
    assert ob.plummer_escape_speed(0.0, 1.0, 1.0, 1.0) == math.sqrt(2.0)
    assert _close(ob.plummer_escape_speed(1.0, 1.0, 1.0, 1.0), math.sqrt(2.0) * 2.0 ** -0.25)
    q, tries = ob.plummer_q(seed=1, channel=5, index=0)
    assert 0.0 <= q < 1.0 and tries >= 1


# ------------------------------------------------------------------------------------ rules 5 and 6: trails, frames and seek


def test_trail_samples_and_fade():
    times = ob.trail_times(100.0, 30.0, 4)
    assert times == (70.0, 80.0, 90.0, 100.0)
    assert ob.trail_times(10.0, 30.0, 4) == (0.0, 0.0, 0.0, 10.0)  # clamped at the epoch
    assert _close(ob.trail_alpha(0.0, 30.0), 1.0) and _close(ob.trail_alpha(30.0, 30.0), 0.0)
    assert _close(ob.trail_alpha(15.0, 30.0), 0.5)
    assert ob.trail_alpha(15.0, 30.0, fade=False) == 1.0
    with pytest.raises(ob.OrbitError):
        ob.trail_times(100.0, 30.0, 1)
    with pytest.raises(ob.OrbitError):
        ob.trail_times(100.0, 0.0, 4)
    orb = ob.orbit(MU, a=AU, e=0.0, i=0.0, raan=0.0, argp=0.0, anomaly=0.0, epoch=0.0)
    pts = ob.orbit_trail(orb, ob.period(MU, AU) / 4.0, ob.period(MU, AU) / 4.0, 3)
    assert len(pts) == 3 and _rel(pts[0], (AU, 0.0, 0.0)) < 1e-12 and _rel(pts[-1], (0.0, AU, 0.0)) < 1e-9


def test_the_frame_state_is_a_pure_function_and_seeks():
    s = _kepler_pair()
    p = 2.0 * math.pi
    step = p / 240.0
    rate = p / 10.0  # ten seconds of scene time per orbit
    fps = 24
    assert ob.steps_to(600 / fps * rate, step) == 600
    with pytest.raises(ob.OrbitError):
        ob.steps_to(1.5 * step, step)
    direct = ob.frame_state(s, "leapfrog", step, 600, fps, rate)
    played = s
    for k in range(1, 601):
        played = ob.integrate(played, "leapfrog", step, k / fps * rate - (k - 1) / fps * rate)
    for a, b in zip(direct["positions"], played["positions"]):
        assert ob.norm(ob.sub(a, b)) < 1e-9
    assert ob.seek_test() is True
    assert _close(direct["t"], 600 / fps * rate, 1e-9)
    with pytest.raises(ob.OrbitError):
        ob.frame_state(s, "leapfrog", step, -1, fps, rate)


def test_scene_mapping_follows_the_time_frames_axes():
    tf = _load(TIME_FRAMES, "time_frames_reference")
    sp = tf.space("2000-01-01T12:00:00Z")
    p_m = (1.0e9, 2.0e9, 3.0e9)
    want = tf.scene_from_icrf(sp, tuple(x / 1000.0 for x in p_m), (0.0, 0.0, 0.0), 1e-6)
    assert _close(ob.scene_position(p_m, (0.0, 0.0, 0.0), 1e-6), want, 1e-6)
    assert _close(ob.scene_position((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 2.0), (2.0, 0.0, 0.0))
    assert _close(ob.scene_position((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 1.0), (0.0, -1.0, 0.0))
    with pytest.raises(ob.OrbitError):
        ob.scene_position(p_m, (0.0, 0.0, 0.0), 0.0)


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
    assert "SR-90" in draft
    for word in ("orbit", "nbody", "member", "cluster", "trail", "integrator", "leapfrog", "wisdomHolman", "ias15",
                 "step", "tolerance", "softening", "anomaly", "raan", "argp", "universal", "Stumpff", "Rein",
                 "Spiegel", "Everhart", "Gauss", "Radau", "Wisdom", "Holman", "Plummer", "Aarseth", "Chenciner",
                 "OR1", "V17", "seek check", "orbits_reference.py", "SREP 14", "pixelsPerMeter", "1e-12",
                 "reversib", "energy", "GM", "DE440", "random streams", "SR-90"):
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
    s = ob.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or ob._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    ob.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())


def test_a_members_trail_walks_the_step_grid_then_one_step_of_the_remainder():
    # rule 5 for a member: whole steps along the step grid from the epoch, then one step of the remainder
    s = ob._pair()
    out = ob.member_trail(s, "leapfrog", 0.1, (0.0, 0.25, 0.3, 0.3))
    assert out[0]["positions"] == s["positions"] and out[0]["t"] == 0.0
    two = ob.integrate(s, "leapfrog", 0.1, 0.2)
    assert _close(out[1]["positions"][1], ob.integrate(two, "leapfrog", 0.05, 0.05)["positions"][1], 1e-12)
    assert _close(out[2]["positions"][1], ob.integrate(s, "leapfrog", 0.1, 0.3)["positions"][1], 1e-12)
    assert out[3]["positions"] == out[2]["positions"]
    # the remainder step is one step, not a finer grid
    assert not _close(out[1]["positions"][1], ob.integrate(s, "leapfrog", 0.05, 0.25)["positions"][1], 1e-9)
    # grid times are reached exactly, with no remainder step
    assert _close(ob.member_trail(s, "ias15", 0.1, (0.2,))[0]["positions"][1],
                  ob.integrate(s, "ias15", 0.1, 0.2)["positions"][1], 1e-12)
    for integrator, step, times in (("leapfrog", 0.1, (0.3, 0.25)), ("leapfrog", 0.0, (0.0,)), ("leapfrog", 0.1, (-0.1,)),
                                    ("euler", 0.1, (0.1,))):
        with pytest.raises(ob.OrbitError):
            ob.member_trail(s, integrator, step, times)


# ------------------------------------------------------------------------------------ the kit

KIT = os.path.join(ROOT, "conformance", "tools", "orbits_kit.py")
kit = _load(KIT, "orbits_kit")
np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")
CASE = r"((?:orbit|nbody)-[a-z]+|trail)"


def _kit_rows(draft):
    return [m.group(1) for m in (re.match(r"^\| `srep-<n>-" + CASE + r"\.xml` \|", line)
                                 for line in draft.splitlines()) if m]


def test_the_kit_camera_puts_a_scene_point_on_its_pixel():
    # orthoHeight equal to the frame's height: one scene unit per pixel, the origin at the frame's centre; the
    # time-frames axes put space x to the right, space z up the frame and space y along the view
    assert kit.pixel(ob.ZERO, 1.0) == (320.0, 180.0)
    assert kit.pixel((100.0, 0.0, 0.0), 1.0) == (420.0, 180.0)
    assert kit.pixel((0.0, 0.0, 50.0), 1.0) == (320.0, 130.0)
    assert kit.pixel((0.0, 7.0, 0.0), 1.0) == (320.0, 180.0)
    assert kit.pixel((1e9, 0.0, 0.0), 1e-7) == (420.0, 180.0)
    assert _close(kit.frame_time(24, 2.0), 2.0, 1e-12) and kit.frame_time(0, 2.0) == 0.0
    # a reference system in the x-y plane turned into the space x-z plane, the kit's orbit plane
    s = kit.swapped(ob._pair())
    assert s["positions"][1] == (1.0, 0.0, 0.0) and s["velocities"][1][1] == 0.0 and s["velocities"][1][2] != 0.0
    assert kit.swap((1.0, 2.0, 3.0)) == (1.0, 3.0, 2.0)
    # linear light of the engine's sRGB PNG and the tube seen through both walls
    assert _close(float(kit.linear(255)), 1.0, 1e-12) and _close(float(kit.linear(0)), 0.0, 1e-12)
    assert _close(float(kit.linear(188)), 0.5029, 1e-3)
    assert kit.tube_opacity(0.0) == 0.0 and kit.tube_opacity(1.0) == 1.0 and _close(kit.tube_opacity(0.5), 0.75, 1e-12)


def test_the_kit_geometry_follows_the_draft():
    g = kit.geometry()
    assert list(g) == kit.NAMES
    c = g["orbit-ellipse"]
    assert c["e"] == 0.3 and _close(c["rate"], ob.period(kit.MU, kit.A_M), 1e-9) and kit.A_M * kit.ORBIT_PPM == 100.0
    h = g["orbit-hyperbola"]
    assert h["e"] == 1.5 and h["a"] < 0.0 and 0.0 < h["pericentre_frame"] < kit.ORBIT_FRAMES
    assert _close(math.hypot(*h["asymptote"]), 1.0, 1e-9) and h["rate"] > 0.0
    assert _close(kit.hyperbola_time(kit.MU, -kit.HYPERBOLA_A_M, kit.HYPERBOLA_E, 0.0), 0.0, 1e-9)
    assert kit.hyperbola_time(kit.MU, -kit.HYPERBOLA_A_M, kit.HYPERBOLA_E, -110.0) < 0.0
    # OR3: the pair's frame interval is one step, the eight's 20 steps; the seek case's one step too
    p = g["nbody-pair"]
    assert ob.steps_to(p["rate"] / kit.FPS, p["step"]) == 1 and p["duration"] * kit.FPS > max(p["frames"])
    assert p["frames"] == (0, 240, 480) and _close(p["rate"], ob.TWO_PI, 1e-12)
    e = g["nbody-eight"]
    assert ob.steps_to(e["rate"] / kit.FPS, e["step"]) == kit.EIGHT_STEPS_PER_FRAME and e["rate"] == ob.EIGHT_PERIOD
    a = g["nbody-adaptive"]
    assert a["tolerance"] == 1e-9 and _close(a["rate"], ob.period(1.0 + 1e-3, 1.0), 1e-12) and a["frames"] == (0, 12, 24)
    pos, vel, masses = a["system"]["positions"], a["system"]["velocities"], a["system"]["masses"]
    assert _close(math.dist(pos[0], pos[1]), 1.0 + kit.ADAPTIVE_E, 1e-12)              # apocentre at frame 0
    assert _close(ob.add(ob.mul(pos[0], masses[0]), ob.mul(pos[1], masses[1])), ob.ZERO, 1e-12)   # barycentric
    assert _close(ob.add(ob.mul(vel[0], masses[0]), ob.mul(vel[1], masses[1])), ob.ZERO, 1e-12)
    t = g["trail"]
    assert _close(t["length"] * 4.0, t["rate"], 1e-9) and t["samples"] == 16 and t["frames"] == (12,)
    s = g["nbody-seek"]
    assert ob.steps_to(s["rate"] / kit.FPS, s["step"]) == 1 and s["duration"] * kit.FPS > kit.SEEK_FRAMES
    assert g["nbody-cluster"]["scale"] * kit.CLUSTER_PPM == 40.0 and g["nbody-cluster"]["seed"] == 42


def test_the_kit_writes_the_cases_the_draft_names(draft, tmp_path):
    assert _kit_rows(draft) == kit.NAMES
    assert [k for keys in kit.DOCUMENTS.values() for k in keys] == list(kit.documents())
    paths = kit.write(str(tmp_path))
    assert len(paths) == 10
    docs = {k: open(p, encoding="utf-8").read() for k, p in paths.items()}
    for key, text in docs.items():
        assert os.path.basename(paths[key]) == f"srep-0000-{key}.xml"
        assert '<scene version="1.8">' in text and 'width="640" height="360" fps="24"' in text
        assert '<camera id="cam" projection="orthographic" orthoHeight="360" x="0" y="0" z="-1000"/>' in text
        assert '<space epoch="2451545.0" timeScale="tdb" rate=' in text and 'unlit="true"' in text
        assert "<lights>" not in text and "<physics pixelsPerMeter=" in text
    assert '<orbit around="centre" mu="1e+20" a="1000000000.0" e="0.3" i="90" anomaly="0"/>' in docs["orbit-ellipse"]
    assert 'pixelsPerMeter="1e-07"' in docs["orbit-ellipse"] and '<object3D id="centre" primitive="sphere" radius="6"' in docs["orbit-ellipse"]
    assert 'a="-500000000.0" e="1.5" i="90" anomaly="-110"' in docs["orbit-hyperbola"]
    for i in ob.INTEGRATORS:
        text = docs[f"nbody-pair-{i}"]
        assert f'<nbody G="1" integrator="{i}" step=' in text and text.count("<member ") == 2
        assert '<member ref="a" mass="1.0" x="0.0" y="0.0" z="0.0" vx="0.0" vy="0.0" vz="' in text
        assert 'duration="21"' in text and 'pixelsPerMeter="100.0"' in text
    assert 'integrator="ias15"' in docs["nbody-eight"] and docs["nbody-eight"].count("<member ") == 3
    assert ('<nbody><cluster count="400" mass="2e+32" scale="1000000000000.0" seed="42" prefix="c" radius="1"/></nbody>'
            in docs["nbody-cluster"]) and 'pixelsPerMeter="4e-11"' in docs["nbody-cluster"]
    assert 'integrator="ias15" step=' in docs["nbody-adaptive"] and 'tolerance="1e-09"' in docs["nbody-adaptive"]
    assert '<trail length=' in docs["trail"] and 'samples="16" width="3" color="#0000FFFF"/>' in docs["trail"]
    assert 'integrator="leapfrog"' in docs["nbody-seek"] and 'duration="26"' in docs["nbody-seek"]
    assert "<orbit" not in docs["nbody-seek"] and "<trail" not in docs["orbit-ellipse"] and "<nbody" not in docs["trail"]


def test_the_kit_expectations_come_from_the_reference():
    g, e = kit.geometry(), kit.expectations()
    c = g["orbit-ellipse"]
    orb = ob.orbit(c["mu"], c["a"], c["e"], kit.INCLINATION, 0.0, 0.0, 0.0, 0.0)
    assert e["orbit-ellipse"]["body"][5] == kit.pixel(ob.orbit_state(orb, kit.frame_time(5, c["rate"]))[0], c["ppm"])
    assert _close(e["orbit-ellipse"]["body"][0], (390.0, 180.0), 1e-6)         # pericentre: a (1 - e) = 70 px right
    assert _close(e["orbit-ellipse"]["body"][12], (190.0, 180.0), 1e-6)        # apocentre half a period later
    assert _close(e["orbit-ellipse"]["body"][24], e["orbit-ellipse"]["body"][0], 1e-6)
    assert e["orbit-ellipse"]["body"][1][1] < 180.0                             # up the frame from pericentre
    h = e["orbit-hyperbola"]
    nearest = min(math.dist(p, (320.0, 180.0)) for p in h["body"].values())
    assert len(h["body"]) == 25 and 25.0 <= nearest < 30.0                      # |a| (e - 1) = 25 px at pericentre
    assert _close(math.hypot(*h["asymptote"]), 1.0, 1e-9) and h["asymptote"][0] < 0.0
    assert h["body"][24][0] < 320.0 and h["body"][0][0] < 320.0                 # both legs leave to the left
    assert h["body"][0][1] > 180.0 > h["body"][24][1]                         # in from below, out above the x axis
    p = e["nbody-pair"]
    for i in ob.INTEGRATORS:
        assert _close(p[i][0], [(320.0, 180.0), (420.0, 180.0)], 1e-9)
        assert [f for f in p[i]] == list(kit.PAIR_FRAMES)
        assert p[i][480] == [kit.pixel(q, g["nbody-pair"]["ppm"]) for q in
                             ob.integrate(g["nbody-pair"]["system"], i, g["nbody-pair"]["step"],
                                          kit.frame_time(480, g["nbody-pair"]["rate"]))["positions"]]
    assert max(math.dist(a, b) for a, b in zip(p["ias15"][480], p["wisdomHolman"][480])) < 0.05
    eight = e["nbody-eight"]
    assert len(eight[0]) == 3 and max(math.dist(a, b) for a, b in zip(eight[0], eight[24])) < 0.05
    k = e["nbody-cluster"]["bodies"]
    assert len(k) == 400 and k[3] == kit.pixel(ob.plummer(42, 400, 2e32, 1e12)["positions"][3], kit.CLUSTER_PPM)
    mean = (sum(q[0] for q in k) / 400.0, sum(q[1] for q in k) / 400.0)
    assert _close(mean, (320.0, 180.0), 1e-6)                                   # recentred
    a = e["nbody-adaptive"]
    assert _close(math.dist(*a[0]), 190.0, 1e-6) and _close(math.dist(*a[12]), 10.0, 1e-3)
    assert max(math.dist(x, y) for x, y in zip(a[0], a[24])) < 1e-3
    t = e["trail"]
    assert len(t["samples"]) == 16 and t["samples"][-1] == e["orbit-ellipse"]["body"][12]
    assert _close(t["alphas"], [kk / 15.0 for kk in range(16)], 1e-12)
    assert e["nbody-seek"] == {}


# ---------------------------------------------------------------- synthetic frames: the bodies painted where expected

def _srgb8(value):
    c = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055
    return int(round(c * 255.0))


def _paint(frame, discs):
    """Discs of pure colours (colour -> [(point, radius)]) onto an RGB frame."""
    for colour, items in discs.items():
        for at, radius in items:
            mask = kit.paint_discs([at], radius) > 0.0
            frame[mask] = 0
            if colour == "white":
                frame[mask] = 255
            else:
                frame[mask, kit.CHANNEL[colour]] = 255
    return frame


@pytest.fixture(scope="module")
def synthetic():
    exp, g = kit.expectations(), kit.geometry()
    rc, rb, rs = kit.RADIUS["centre"], kit.RADIUS["body"], kit.RADIUS["small"]
    centre = kit.pixel(ob.ZERO, 1.0)

    def blank():
        return np.zeros((kit.H, kit.W, 3), dtype=np.uint8)

    frames = {}
    for name in ("orbit-ellipse", "orbit-hyperbola"):
        for f, at in exp[name]["body"].items():
            frames[f"{name}@{f}"] = _paint(blank(), {"red": [(centre, rc)], "green": [(at, rb)]})
    for i in ob.INTEGRATORS:
        for f, (a, b) in exp["nbody-pair"][i].items():
            frames[f"nbody-pair-{i}@{f}"] = _paint(blank(), {"red": [(a, rc)], "green": [(b, rb)]})
    for f, pts in exp["nbody-eight"].items():
        frames[f"nbody-eight@{f}"] = _paint(blank(), {c: [(p, rb)] for c, p in zip(("red", "green", "blue"), pts)})
    frames["nbody-cluster@0"] = _paint(blank(), {"white": [(p, kit.CLUSTER["radius"]) for p in exp["nbody-cluster"]["bodies"]]})
    for f, (a, b) in exp["nbody-adaptive"].items():
        frames[f"nbody-adaptive@{f}"] = _paint(blank(), {"red": [(a, rb)], "green": [(b, rs)]})
    trail = blank()
    for at, alpha in zip(exp["trail"]["samples"][:-1], exp["trail"]["alphas"][:-1]):
        mask = kit.paint_discs([at], kit.TRAIL_WIDTH / 2.0) > 0.0
        trail[mask, 2] = _srgb8(kit.tube_opacity(alpha))
    frames[f"trail@{kit.TRAIL_FRAME}"] = _paint(trail, {"red": [(centre, rc)], "green": [(exp["trail"]["samples"][-1], rb)]})
    seek = blank()
    seek[100:200, 300:400] = 200
    frames["seek-alone"], frames["seek-played"] = seek, seek.copy()
    return exp, g, frames


def test_the_kit_measures_each_case(synthetic):
    exp, g, frames = synthetic
    for name in kit.NAMES:
        r = kit.measure(name, frames, exp)
        assert r["pass"], (name, r)
    ellipse = kit.measure("orbit-ellipse", frames, exp)
    assert ellipse["frames"] == 25 and ellipse["worst_off_px"] <= 0.2 and ellipse["closure_px"] <= 0.2
    hyper = kit.measure("orbit-hyperbola", frames, exp)
    assert hyper["frames"] >= 20 and hyper["chord_off_deg"] <= 0.2 and hyper["chord_to_asymptote_deg"] < 3.0
    assert hyper["chord_frames"][0] > exp["orbit-hyperbola"]["pericentre_frame"]
    pair = kit.measure("nbody-pair", frames, exp)
    assert all(f in pair[i] for i in ob.INTEGRATORS for f in kit.PAIR_FRAMES) and pair["worst_off_px"] <= 0.2
    eight = kit.measure("nbody-eight", frames, exp)
    assert max(eight["return_px"]) <= 0.2 and eight["worst_off_px"] <= 0.2
    cluster = kit.measure("nbody-cluster", frames, exp)
    assert cluster["in_frame"] >= 380 and cluster["isolated"] >= 50 and cluster["body_3"].startswith("isolated")
    assert cluster["centroid_off_px"] <= 0.5 and cluster["worst_off_px"] <= 0.6
    adaptive = kit.measure("nbody-adaptive", frames, exp)
    assert _close(adaptive["pericentre"], adaptive["expected_pericentre"], 0.2)
    trail = kit.measure("trail", frames, exp)
    assert trail["oldest"] == 0.0 and trail["newest"] >= 0.99 and trail["monotone"] and trail["read_samples"] == sum(1 for a in exp["trail"]["alphas"][:-1] if a >= 0.2)
    assert trail["worst_level_off"] <= 0.01 and trail["worst_off_px"] <= 0.5     # the 1.5 px window's read bias on a 1.5 px tube
    with pytest.raises(ValueError):
        kit.measure("nbody-moons", frames, exp)


def test_the_kit_fails_a_wrong_frame(synthetic):
    exp, g, frames = synthetic

    def shifted(key, dx):
        bad = dict(frames)
        bad[key] = np.roll(frames[key], dx, axis=1)
        return bad

    assert not kit.measure("orbit-ellipse", shifted("orbit-ellipse@6", 2), exp)["pass"]
    assert not kit.measure("orbit-hyperbola", shifted("orbit-hyperbola@22", 3), exp)["pass"]
    assert not kit.measure("nbody-pair", shifted("nbody-pair-ias15@480", 2), exp)["pass"]
    assert not kit.measure("nbody-eight", shifted("nbody-eight@24", 2), exp)["pass"]
    assert not kit.measure("nbody-cluster", shifted("nbody-cluster@0", 2), exp)["pass"]
    assert not kit.measure("nbody-adaptive", shifted("nbody-adaptive@12", 2), exp)["pass"]
    assert not kit.measure("trail", shifted(f"trail@{kit.TRAIL_FRAME}", 2), exp)["pass"]
    # a trail that does not fade
    flat = frames[f"trail@{kit.TRAIL_FRAME}"].copy()
    blue = flat[..., 2]
    blue[blue > 0] = 255
    bad = dict(frames)
    bad[f"trail@{kit.TRAIL_FRAME}"] = flat
    assert not kit.measure("trail", bad, exp)["pass"]
    # a hyperbola whose outgoing leg is straight but turned: the chord misses the expected direction
    turned = dict(frames)
    for f in range(18, 25):
        turned[f"orbit-hyperbola@{f}"] = np.roll(frames[f"orbit-hyperbola@{f}"], (f - 17) * 1, axis=0)
    assert not kit.measure("orbit-hyperbola", turned, exp)["pass"]
    bad = dict(frames)
    bad["seek-played"] = frames["seek-alone"].copy()
    bad["seek-played"][150, 350] = 0
    assert not kit.measure("nbody-seek", bad, exp)["pass"]


def _fake_engine(frames, refuse=()):
    class Result:
        def __init__(self, code, err=""):
            self.returncode, self.stderr, self.stdout = code, err, ""

    def exec(cmd, capture_output, text):
        assert cmd[1] == "render"
        key = os.path.basename(cmd[2])[len("srep-0000-"):-len(".xml")]
        if key in refuse:
            return Result(1, f"error: OR3 {key} refused\n")
        target = cmd[cmd.index("-o") + 1]
        if "-f" in cmd:
            frame = int(cmd[cmd.index("-f") + 1])
            Image.fromarray(frames["seek-alone" if key == "nbody-seek" else f"{key}@{frame}"], "RGB").save(target)
        else:
            first, last = (int(v) for v in cmd[cmd.index("--frames") + 1].split("..="))
            if key == "nbody-seek":
                assert (first, last) == (0, kit.SEEK_FRAMES)
                Image.fromarray(frames["seek-played"], "RGB").save(target % last)
            else:
                for f in range(first, last + 1):
                    Image.fromarray(frames[f"{key}@{f}"], "RGB").save(target % f)
        return Result(0)

    return exec


def test_the_kit_plans_sequences_for_the_orbits_and_single_frames_otherwise():
    plan = kit.plan()
    assert list(plan) == kit.NAMES
    assert plan["orbit-ellipse"] == [("orbit-ellipse", tuple(range(25)), True)]
    assert plan["nbody-pair"] == [(f"nbody-pair-{i}", (0, 240, 480), False) for i in ob.INTEGRATORS]
    assert plan["nbody-seek"] == [("nbody-seek", (600,), False)] and plan["trail"] == [("trail", (12,), False)]


def test_the_kit_runs_an_engine_and_reports_every_case(synthetic, tmp_path):
    exp, g, frames = synthetic
    report = kit.run("scene-render", str(tmp_path / "kit"), exec=_fake_engine(frames))
    assert list(report) == kit.NAMES and all(r["pass"] for r in report.values()), report
    assert os.path.exists(tmp_path / "kit" / "srep-0000-nbody-pair-ias15.xml")
    lines = kit.table(report).splitlines()
    assert lines[0] == "| Case | Measured | Pass |" and len(lines) == 2 + len(kit.NAMES)
    assert all(line.endswith("| yes |") for line in lines[2:])
    report = kit.run("scene-render", str(tmp_path / "kit2"),
                     exec=_fake_engine(frames, refuse=("nbody-pair-wisdomHolman", "nbody-seek")),
                     only=["orbit-ellipse", "nbody-pair", "nbody-seek"])
    assert list(report) == ["orbit-ellipse", "nbody-pair", "nbody-seek"]
    assert report["orbit-ellipse"]["pass"] and not report["nbody-pair"]["pass"] and not report["nbody-seek"]["pass"]
    assert report["nbody-pair"]["error"] == "nbody-pair-wisdomHolman: error: OR3 nbody-pair-wisdomHolman refused"
    assert report["nbody-seek"]["error"] == "nbody-seek: error: OR3 nbody-seek refused"
    assert "| nbody-seek | error nbody-seek: error: OR3 nbody-seek refused | no |" in kit.table(report)


def test_the_draft_describes_the_kit(draft):
    for phrase in ("`conformance/tools/orbits_kit.py`", "`srep-<n>-orbit-ellipse.xml`", "seen by an orthographic camera",
                   "(W / 2 + x, H / 2 + y)", "one scene unit is one pixel", "one pure colour", "centroid", "sRGB",
                   "1 − (1 − α)²", "24 steps per orbit", "480 steps per period", "chord", "isolated",
                   "frame 600 rendered alone", "`member_trail`", "eight segments", "scene units, default 2",
                   "`radius` (`positiveDecimal`, scene units, default 2", "`approximate_relative`", "±60 s",
                   "its centre's place at that time plus", "the engine integrates from the epoch"):
        assert phrase in draft, phrase
    assert "pixels, default 2" not in draft and "facing the camera" not in draft and "at 20 steps per orbit for 20 orbits" not in draft


KIT_ROW = re.compile(r"^\| `srep-<n>-" + CASE + r"\.xml` \| (?:[^|]|\\\|)* \| ([^|]*) \|$")
ENGINE_COMMIT = "105c036"


def test_the_draft_records_every_kit_case_measured(draft):
    rows = {m.group(1): m.group(2) for m in (KIT_ROW.match(line) for line in draft.splitlines()) if m}
    assert sorted(rows) == sorted(kit.NAMES)
    prefix = f"measured on scene-render feat/sr-67-fields {ENGINE_COMMIT} (0.8.0, llvmpipe): "
    for name, status in rows.items():
        assert status.startswith(prefix) and status.endswith("; pass"), (name, status)
    assert "to be measured" not in draft


def test_the_draft_records_the_engine_state(draft):
    row = next(line for line in draft.splitlines() if line.startswith("| Rust (`rs-scene-render`), reference |"))
    done, remaining = row.split(" | ")[1:3]
    assert done.startswith(f"feat/sr-67-fields {ENGINE_COMMIT}") and "SR-90" in row
    assert remaining.startswith("none; the eight kit cases pass with the values below")


def test_the_draft_records_the_engine_release(draft):
    row = next(line for line in draft.splitlines() if line.startswith("| Rust (`rs-scene-render`), reference |"))
    done, remaining = row.split(" | ")[1:3]
    assert "; released in scene-render v0.9.0 (" in done and done.rstrip().endswith(")")
