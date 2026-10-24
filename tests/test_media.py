"""Draft SREP "Define the participating-medium model and its phase functions" (srep/srep-0000-media.md, the F3
building block of SREP 12): the reference implementation conformance/tools/media_reference.py, its closed-form
checks, and the agreement between the SREP's numeric-test table and that implementation.

The checks come from independent statements: the coefficient and phase conventions of the reference engine
(crates/sr-volume/src/medium.rs, crates/sr-gpu/src/volume.wgsl, pathtrace.rs, three.wgsl at main 67a661a), the
closed forms of Draine (2003, appendix A: normalisation and moments) and the fits of Jendersie and d'Eon (2023),
typed here from the papers rather than imported from the module.
"""
import ast
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT = os.path.join(ROOT, "srep", "srep-0000-media.md")
MODULE = os.path.join(ROOT, "conformance", "tools", "media_reference.py")


def _load():
    spec = importlib.util.spec_from_file_location("media_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mr = _load()

PI = math.pi
PHASES = [(0.0, 0.0), (0.5, 0.0), (-0.3, 0.0), (0.0, 1.0), (0.7, 1.0), (0.9, 0.25), (-0.6, 3.0), (0.85, 32.0)]


# --- coefficients (SREP 40 medium, crates/sr-volume/src/medium.rs) ----------------------------------------------

def test_coefficients_split_extinction_into_scattering_and_absorption():
    c = mr.coefficients(density=0.5, density_scale=2.0, opacity=0.5, extinction=4.0, albedo=(1.0, 0.5, 0.0))
    assert c.sigma_t == pytest.approx(2.0)                 # 0.5 * 2 * 0.5 * 4
    assert c.sigma_s == pytest.approx((2.0, 1.0, 0.0))
    assert c.sigma_a == pytest.approx((0.0, 1.0, 2.0))


def test_zero_density_has_no_coefficients():
    c = mr.coefficients(density=0.0, density_scale=1.0, opacity=1.0, extinction=1.0, albedo=(1.0, 1.0, 1.0))
    assert (c.sigma_t, c.sigma_s, c.sigma_a) == (0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


@pytest.mark.parametrize("kwargs", [
    dict(density=-1.0), dict(density=float("nan")), dict(density_scale=-0.5), dict(opacity=1.5),
    dict(extinction=float("inf")), dict(albedo=(1.0, 1.2, 0.0)), dict(albedo=(-0.1, 0.0, 0.0)),
])
def test_coefficients_reject_values_outside_the_schema(kwargs):
    base = dict(density=1.0, density_scale=1.0, opacity=1.0, extinction=1.0, albedo=(1.0, 1.0, 1.0))
    base.update(kwargs)
    with pytest.raises(ValueError):
        mr.coefficients(**base)


def test_emission_is_density_times_scale_times_colour_plus_thermal():
    e = mr.emission(density=2.0, emission_scale=3.0, emission_color=(1.0, 0.5, 0.0), thermal=(0.0, 0.5, 1.0))
    assert e == pytest.approx((6.0, 6.0, 6.0))
    assert mr.emission(density=2.0, emission_scale=0.0, emission_color=(1.0, 1.0, 1.0), thermal=(1.0, 1.0, 1.0)) \
        == (0.0, 0.0, 0.0)


# --- transmittance and the march step (SREP 40; SREP 79 rule 4) ------------------------------------------------

def test_transmittance_is_beer_lambert():
    assert mr.transmittance(0.0, 10.0) == 1.0
    assert mr.transmittance(2.0, 0.5) == pytest.approx(math.exp(-1.0))
    assert mr.transmittance((1.0, 2.0, 3.0), 1.0) == pytest.approx((math.exp(-1), math.exp(-2), math.exp(-3)))


def test_step_weight_is_the_exact_integral_of_the_transmittance_over_the_step():
    assert mr.step_weight(0.0, 0.25) == 0.25
    assert mr.step_weight(2.0, 0.5) == pytest.approx((1.0 - math.exp(-1.0)) / 2.0)
    # the limit for a thin step is the step length
    assert mr.step_weight(1e-9, 0.5) == pytest.approx(0.5, rel=1e-6)


def test_overlapping_media_add_their_coefficients_in_any_order():
    a = mr.coefficients(density=1.0, density_scale=1.0, opacity=1.0, extinction=2.0, albedo=(1.0, 0.0, 0.5))
    b = mr.coefficients(density=0.5, density_scale=1.0, opacity=1.0, extinction=4.0, albedo=(0.0, 1.0, 0.5))
    ab, ba = mr.combine([a, b]), mr.combine([b, a])
    assert ab == ba
    assert ab.sigma_t == pytest.approx(4.0)
    assert ab.sigma_s == pytest.approx((2.0, 2.0, 2.0))


# --- the surface absorption as a medium (SREP 40; pathtrace.rs:80-86, three.wgsl:582-585) ---------------------

def test_surface_absorption_is_minus_log_colour_over_distance():
    s = mr.surface_absorption((0.5, 0.25, 1.0), 2.0)
    assert s == pytest.approx((math.log(2.0) / 2.0, math.log(4.0) / 2.0, 0.0))
    assert mr.transmittance(s, 2.0) == pytest.approx((0.5, 0.25, 1.0))


@pytest.mark.parametrize("color, distance", [
    ((1.0, 1.0, 1.0), 2.0), ((0.5, 0.5, 0.5), 0.0), ((0.5, 0.5, 0.5), float("inf")), ((0.5, 0.5, 0.5), -1.0),
])
def test_surface_absorption_is_zero_without_a_distance_or_for_white(color, distance):
    assert mr.surface_absorption(color, distance) == (0.0, 0.0, 0.0)


def test_surface_absorption_clamps_black_at_the_reference_floor():
    s = mr.surface_absorption((0.0, 1e-5, 1.0), 1.0)
    assert s[0] == pytest.approx(-math.log(1e-4))
    assert s[1] == pytest.approx(-math.log(1e-4))


# --- phase functions ---------------------------------------------------------------------------------------------

def _simpson(f, a, b, fa, fm, fb):
    return (b - a) / 6.0 * (fa + 4.0 * fm + fb)


def _adaptive(f, a, b, fa, fm, fb, whole, tol, depth):
    m = 0.5 * (a + b)
    lm, rm = 0.5 * (a + m), 0.5 * (m + b)
    flm, frm = f(lm), f(rm)
    left = _simpson(f, a, m, fa, flm, fm)
    right = _simpson(f, m, b, fm, frm, fb)
    if depth <= 0 or abs(left + right - whole) <= 15.0 * tol:
        return left + right + (left + right - whole) / 15.0
    return (_adaptive(f, a, m, fa, flm, fm, left, tol / 2.0, depth - 1)
            + _adaptive(f, m, b, fm, frm, fb, right, tol / 2.0, depth - 1))


def _quad(f, tol=1e-11):
    """Adaptive Simpson of f over cos theta in [-1, 1], times 2 pi: the integral over the sphere. Adaptive so
    that the forward peak of a strongly anisotropic phase function is resolved; the recursion depth is bounded."""
    fa, fm, fb = f(-1.0), f(0.0), f(1.0)
    whole = _simpson(f, -1.0, 1.0, fa, fm, fb)
    return 2.0 * PI * _adaptive(f, -1.0, 1.0, fa, fm, fb, whole, tol, 40)


@pytest.mark.parametrize("mu, g, expected", [
    (0.0, 0.0, 1 / (4 * PI)), (1.0, 0.5, 6.0 / (4 * PI)), (-1.0, 0.5, 0.75 / (4 * PI * 2.25 ** 1.5)),
    (0.3, -0.7, (1 - 0.49) / (4 * PI * (1 + 0.49 + 0.42) ** 1.5)),
])
def test_henyey_greenstein_closed_form(mu, g, expected):
    assert mr.phase_hg(mu, g) == pytest.approx(expected, rel=1e-12)


def test_henyey_greenstein_forward_peak_follows_propagation():
    # crates/sr-volume/src/medium.rs:433-434: g > 0 peaks at cos theta = 1
    assert mr.phase_hg(1.0, 0.5) > mr.phase_hg(-1.0, 0.5)
    assert mr.phase_hg(1.0, -0.5) < mr.phase_hg(-1.0, -0.5)


@pytest.mark.parametrize("mu, expected", [(1.0, 3 / (8 * PI)), (0.0, 3 / (16 * PI)), (-1.0, 3 / (8 * PI))])
def test_rayleigh_closed_form(mu, expected):
    assert mr.phase_rayleigh(mu) == pytest.approx(expected, rel=1e-12)


def test_draine_reduces_to_henyey_greenstein_rayleigh_and_cornette_shanks():
    for mu in (-1.0, -0.4, 0.0, 0.6, 1.0):
        assert mr.phase_draine(mu, 0.6, 0.0) == pytest.approx(mr.phase_hg(mu, 0.6), rel=1e-12)
        assert mr.phase_draine(mu, 0.0, 1.0) == pytest.approx(mr.phase_rayleigh(mu), rel=1e-12)
        g = 0.76
        cornette_shanks = 3 / (8 * PI) * (1 - g * g) / (2 + g * g) * (1 + mu * mu) / (1 + g * g - 2 * g * mu) ** 1.5
        assert mr.phase_draine(mu, g, 1.0) == pytest.approx(cornette_shanks, rel=1e-12)


def test_draine_closed_form_from_the_paper():
    # Draine 2003, equation 5
    mu, g, a = 0.25, 0.5, 2.0
    expected = (1 - g * g) / (4 * PI * (1 + a * (1 + 2 * g * g) / 3)) * (1 + a * mu * mu) / (1 + g * g - 2 * g * mu) ** 1.5
    assert mr.phase_draine(mu, g, a) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("g, alpha", PHASES)
def test_phase_functions_integrate_to_one_over_the_sphere(g, alpha):
    assert _quad(lambda mu: mr.phase_draine(mu, g, alpha)) == pytest.approx(1.0, abs=1e-9)
    assert _quad(lambda mu: mr.phase_hg(mu, g)) == pytest.approx(1.0, abs=1e-9)
    assert _quad(mr.phase_rayleigh) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("g, alpha", PHASES)
def test_draine_moments_match_the_paper(g, alpha):
    # Draine 2003, equations A2 and A3
    first = g * (1 + alpha * (3 + 2 * g * g) / 5) / (1 + alpha * (1 + 2 * g * g) / 3)
    second = (1 + 2 * g * g + (3 * alpha / 35) * (7 + 20 * g * g + 8 * g ** 4)) / (3 + alpha * (1 + 2 * g * g))
    assert mr.mean_cosine_draine(g, alpha) == pytest.approx(first, rel=1e-12)
    assert _quad(lambda mu: mu * mr.phase_draine(mu, g, alpha)) == pytest.approx(first, abs=1e-9)
    assert _quad(lambda mu: mu * mu * mr.phase_draine(mu, g, alpha)) == pytest.approx(second, abs=1e-9)


@pytest.mark.parametrize("bad", [dict(g=1.0), dict(g=-1.0), dict(g=float("nan")), dict(alpha=-0.1), dict(mu=1.5)])
def test_phase_functions_reject_values_outside_their_domain(bad):
    kwargs = dict(mu=0.0, g=0.0, alpha=0.0)
    kwargs.update(bad)
    with pytest.raises(ValueError):
        mr.phase_draine(**kwargs)
    if "alpha" not in bad:
        with pytest.raises(ValueError):
            mr.phase_hg(kwargs["mu"], kwargs["g"])


# --- the fog phase function (Jendersie and d'Eon 2023) ---------------------------------------------------------

@pytest.mark.parametrize("d", [5.0, 10.0, 20.0, 37.5, 50.0])
def test_fog_parameters_follow_the_published_fit(d):
    p = mr.fog_parameters(d)
    assert p.g_hg == pytest.approx(math.exp(-0.0990567 / (d - 1.67154)), rel=1e-12)
    assert p.g_d == pytest.approx(math.exp(-2.20679 / (d + 3.91029) - 0.428934), rel=1e-12)
    assert p.alpha == pytest.approx(math.exp(3.62489 - 8.29288 / (d + 5.52825)), rel=1e-12)
    assert p.w_d == pytest.approx(math.exp(-0.599085 / (d - 0.641583) - 0.665888), rel=1e-12)
    assert 0.0 < p.g_hg < 1.0 and 0.0 < p.g_d < 1.0 and p.alpha > 0.0 and 0.0 < p.w_d < 1.0


@pytest.mark.parametrize("d", [4.999, 50.001, 0.0, -1.0, float("nan"), float("inf")])
def test_fog_parameters_reject_diameters_outside_the_fit(d):
    with pytest.raises(ValueError):
        mr.fog_parameters(d)


@pytest.mark.parametrize("d", [5.0, 12.0, 50.0])
def test_fog_phase_is_the_weighted_sum_of_its_lobes_and_normalised(d):
    p = mr.fog_parameters(d)
    for mu in (-1.0, -0.2, 0.0, 0.5, 0.999, 1.0):
        expected = (1 - p.w_d) * mr.phase_hg(mu, p.g_hg) + p.w_d * mr.phase_draine(mu, p.g_d, p.alpha)
        assert mr.phase_fog(mu, d) == pytest.approx(expected, rel=1e-12)
    assert _quad(lambda mu: mr.phase_fog(mu, d)) == pytest.approx(1.0, abs=1e-9)


# --- sampling (SREP 79 rule 6; supplemental section 2) ---------------------------------------------------------

@pytest.mark.parametrize("xi", [0.0, 0.1, 0.5, 0.9, 0.999999])
def test_henyey_greenstein_sampling_is_the_srep_79_inversion(xi):
    for g in (0.0, 0.5, -0.8, 1e-4):
        if abs(g) < 1e-3:
            expected = 1.0 - 2.0 * xi
        else:
            s = (1 - g * g) / (1 - g + 2 * g * xi)
            expected = max(-1.0, min(1.0, (1 + g * g - s * s) / (2 * g)))
        assert mr.sample_hg(xi, g) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("g, alpha", PHASES)
@pytest.mark.parametrize("xi", [0.0, 0.05, 0.5, 0.95, 0.999])
def test_draine_sampling_inverts_its_cdf(g, alpha, xi):
    mu = mr.sample_draine(xi, g, alpha)
    assert -1.0 <= mu <= 1.0
    assert mr.cdf_draine(mu, g, alpha) == pytest.approx(xi, abs=1e-9)


def test_draine_cdf_is_monotone_from_zero_to_one():
    g, alpha = 0.7, 1.5
    assert mr.cdf_draine(-1.0, g, alpha) == 0.0
    assert mr.cdf_draine(1.0, g, alpha) == pytest.approx(1.0, abs=1e-12)
    values = [mr.cdf_draine(-1.0 + k / 50.0, g, alpha) for k in range(101)]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_draine_cdf_of_the_henyey_greenstein_case_is_the_closed_form():
    g = 0.6
    for mu in (-0.9, 0.0, 0.8):
        # the HG cumulative in cos theta: (1 - g^2) / (2 g) * (1 / sqrt(1 + g^2 - 2 g mu) - 1 / (1 + g))
        closed = (1 - g * g) / (2 * g) * (1 / math.sqrt(1 + g * g - 2 * g * mu) - 1 / (1 + g))
        assert mr.cdf_draine(mu, g, 0.0) == pytest.approx(closed, abs=1e-12)


def test_fog_sampling_picks_the_draine_lobe_below_the_weight():
    d = 10.0
    p = mr.fog_parameters(d)
    below = mr.sample_fog(0.5 * p.w_d, 0.3, d)
    above = mr.sample_fog(p.w_d + 0.5 * (1 - p.w_d), 0.3, d)
    assert below == pytest.approx(mr.sample_draine(0.3, p.g_d, p.alpha))
    assert above == pytest.approx(mr.sample_hg(0.3, p.g_hg))


@pytest.mark.parametrize("xi", [-0.1, 1.0, float("nan")])
def test_sampling_rejects_a_unit_draw_outside_the_half_open_interval(xi):
    with pytest.raises(ValueError):
        mr.sample_hg(xi, 0.5)
    with pytest.raises(ValueError):
        mr.sample_draine(xi, 0.5, 1.0)


# --- the SREP's numeric-test table ------------------------------------------------------------------------------

def _numeric_rows():
    if not os.path.exists(DRAFT):
        return []
    text = open(DRAFT, encoding="utf-8").read()
    start = text.index("### Numeric tests")
    end = text.index("\n### ", start + 1)
    rows = []
    for line in text[start:end].splitlines():
        m = re.match(r"^\| ([^|]+?) \| `([^`]+)` \| `([^`]+)` \|$", line)
        if m:
            rows.append((m.group(1).strip(), m.group(2), m.group(3)))
    return rows


def test_the_numeric_table_has_enough_rows():
    rows = _numeric_rows()
    assert len(rows) >= 20
    assert len({name for name, _, _ in rows}) == len(rows)


@pytest.mark.parametrize("name, expr, expected", _numeric_rows(), ids=lambda v: str(v)[:40])
def test_the_numeric_table_matches_the_reference(name, expr, expected):
    scope = {k: getattr(mr, k) for k in dir(mr) if not k.startswith("_")}
    scope["math"] = math
    scope["tuple"] = tuple
    got = eval(expr, {"__builtins__": {}}, scope)
    want = ast.literal_eval(expected)
    if isinstance(want, float) or (isinstance(want, tuple) and any(isinstance(v, float) for v in want)):
        assert got == pytest.approx(want, rel=1e-9, abs=1e-15)
    else:
        assert got == want


def test_the_module_prints_the_table(capsys):
    mr.main()
    out = capsys.readouterr().out
    rows = _numeric_rows()
    for name, _, _ in rows:
        assert f"| {name} |" in out
