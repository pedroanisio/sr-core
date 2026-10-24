"""Tests of the draft SREP "Add Kerr geodesics, ray bundles, beaming and a relativistic camera"
(srep/srep-0000-relativistic.md) and of its reference module conformance/tools/relativistic_reference.py:
the Kerr metric's closed forms (horizons, ergosphere, photon orbits, ISCO, frame dragging), the static
observer's momentum, the conserved quantities along a traced geodesic, outcomes (captured, escaped, disk),
the Schwarzschild limits (shadow sqrt(27) M, deflection 4M/b, photon sphere 3M, ISCO 6M), the disk's redshift,
the relativistic camera (aberration, Doppler, searchlight), g^4 beaming, ray bundles, and the SREP's numeric
table against the module.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "relativistic_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-relativistic.md")

spec = importlib.util.spec_from_file_location("relativistic_reference", MODULE)
gr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gr)


def _close(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


# ------------------------------------------------------------------------------------ closed forms

def test_horizons_and_the_ergosphere():
    assert gr.horizons(1.0, 0.0) == (2.0, 0.0)
    assert _close(gr.horizons(1.0, 1.0), (1.0, 1.0))
    rp, rm = gr.horizons(1.0, 0.6)
    assert _close(rp, 1.8) and _close(rm, 0.2)
    assert _close(gr.ergosphere(1.0, 0.6, math.pi / 2.0), 2.0)
    assert _close(gr.ergosphere(1.0, 0.6, 0.0), 1.8)
    with pytest.raises(ValueError):
        gr.horizons(1.0, 1.1)
    with pytest.raises(ValueError):
        gr.horizons(0.0, 0.0)


def test_the_photon_orbits():
    assert _close(gr.photon_orbit(1.0, 0.0, True), 3.0)
    assert _close(gr.photon_orbit(1.0, 0.0, False), 3.0)
    assert _close(gr.photon_orbit(1.0, 1.0, True), 1.0)
    assert _close(gr.photon_orbit(1.0, 1.0, False), 4.0)
    assert gr.photon_orbit(1.0, 0.5, True) < 3.0 < gr.photon_orbit(1.0, 0.5, False)
    assert _close(gr.photon_orbit(2.0, 0.0, True), 6.0)


def test_the_isco():
    assert _close(gr.isco(1.0, 0.0, True), 6.0)
    assert _close(gr.isco(1.0, 0.0, False), 6.0)
    assert _close(gr.isco(1.0, 1.0, True), 1.0)
    assert _close(gr.isco(1.0, 1.0, False), 9.0)
    assert gr.isco(1.0, 0.9, True) < 6.0 < gr.isco(1.0, 0.9, False)


def test_frame_dragging_and_keplerian_rates():
    assert gr.omega_zamo(1.0, 0.0, 10.0, math.pi / 2.0) == 0.0
    assert gr.omega_zamo(1.0, 0.9, 10.0, math.pi / 2.0) > 0.0
    assert _close(gr.omega_kepler(1.0, 0.0, 4.0, True), 1.0 / 8.0)
    assert _close(gr.omega_kepler(1.0, 0.0, 4.0, False), -1.0 / 8.0)
    assert gr.omega_kepler(1.0, 0.9, 4.0, True) < 1.0 / 8.0
    assert abs(gr.omega_kepler(1.0, 0.9, 4.0, False)) > 1.0 / 8.0


def test_the_metric_reduces_to_schwarzschild():
    g = gr.metric(1.0, 0.0, 10.0, math.pi / 3.0)
    assert _close(g["tt"], -(1.0 - 0.2))
    assert g["tphi"] == 0.0
    assert _close(g["rr"], 1.0 / 0.8)
    assert _close(g["thth"], 100.0)
    assert _close(g["phiphi"], 100.0 * math.sin(math.pi / 3.0) ** 2)
    g = gr.metric(1.0, 0.9, 3.0, math.pi / 2.0)
    assert g["tphi"] < 0.0


# ------------------------------------------------------------------------------------ the observer

def test_the_static_observer_sends_a_null_momentum():
    for a in (0.0, 0.7):
        for d in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.6, 0.0, 0.8), (-0.5, 0.5, math.sqrt(0.5))):
            E, L, pr, pth = gr.static_momentum(1.0, a, 10.0, math.pi / 2.0, d)
            assert abs(gr.hamiltonian(1.0, a, 10.0, math.pi / 2.0, pr, pth, E, L)) < 1e-12
            assert E > 0.0
    with pytest.raises(ValueError):
        gr.static_momentum(1.0, 0.9, 1.5, math.pi / 2.0, (1.0, 0.0, 0.0))


def test_looking_at_the_hole_has_no_angular_momentum():
    E, L, pr, pth = gr.static_momentum(1.0, 0.0, 10.0, math.pi / 2.0, (-1.0, 0.0, 0.0))
    assert _close(L, 0.0) and _close(pth, 0.0) and pr < 0.0
    assert _close(E, math.sqrt(1.0 - 0.2))


def test_the_impact_parameter_of_a_schwarzschild_ray():
    r_o = 10.0
    alpha = 0.3
    d = (-math.cos(alpha), 0.0, math.sin(alpha))
    E, L, pr, pth = gr.static_momentum(1.0, 0.0, r_o, math.pi / 2.0, d)
    assert _close(abs(L / E), r_o * math.sin(alpha) / math.sqrt(1.0 - 2.0 / r_o))


# ------------------------------------------------------------------------------------ the trace

def test_the_conserved_quantities_hold_along_a_kerr_geodesic():
    E, L, pr, pth = gr.static_momentum(1.0, 0.8, 12.0, 1.2, (-0.9, 0.3, 0.3))
    Q0 = gr.carter(0.8, 1.2, pth, E, L)
    out = gr.trace(1.0, 0.8, 12.0, 1.2, (-0.9, 0.3, 0.3), r_far=60.0)
    assert out["outcome"] in ("captured", "escaped")
    assert abs(out["hamiltonian"]) < 1e-6
    assert abs(out["carter"] - Q0) < 1e-5
    assert out["steps"] <= gr.MAX_STEPS


def test_a_ray_aimed_at_the_hole_is_captured_and_one_aimed_away_escapes():
    captured = gr.trace(1.0, 0.0, 10.0, math.pi / 2.0, (-1.0, 0.0, 0.0), r_far=50.0)
    assert captured["outcome"] == "captured"
    escaped = gr.trace(1.0, 0.0, 10.0, math.pi / 2.0, (1.0, 0.0, 0.0), r_far=50.0)
    assert escaped["outcome"] == "escaped"
    assert _close(escaped["phi"], 0.0, 1e-6)


def test_the_schwarzschild_shadow_is_sqrt_27():
    b = gr.critical_impact(1.0, 0.0, True)
    assert abs(b - math.sqrt(27.0)) < 2e-3
    assert abs(gr.critical_impact(1.0, 0.0, False) - math.sqrt(27.0)) < 2e-3


def test_the_kerr_shadow_is_asymmetric():
    pro = gr.critical_impact(1.0, 0.95, True)
    retro = gr.critical_impact(1.0, 0.95, False)
    assert pro < math.sqrt(27.0) < retro
    assert abs(pro - gr.critical_impact_exact(1.0, 0.95, True)) < 5e-3
    assert abs(retro - gr.critical_impact_exact(1.0, 0.95, False)) < 5e-3


def test_the_exact_critical_impact_parameters():
    assert _close(gr.critical_impact_exact(1.0, 0.0, True), math.sqrt(27.0))
    assert _close(gr.critical_impact_exact(1.0, 1.0, True), 2.0)
    assert _close(gr.critical_impact_exact(1.0, 1.0, False), 7.0)


def test_the_weak_field_deflection_is_4m_over_b():
    for b in (400.0, 1600.0):
        alpha = gr.schwarzschild_deflection(1.0, b)
        assert abs(alpha / (4.0 / b) - 1.0) < 0.01, b
    assert abs(gr.schwarzschild_deflection(1.0, 10.0) - 0.590396) < 1e-5
    assert abs(gr.schwarzschild_deflection(1.0, 100.0) - 0.0412225) < 1e-6


def test_the_traced_deflection_matches_the_quadrature():
    for b in (10.0, 30.0):
        assert abs(gr.traced_deflection(1.0, 0.0, b) - gr.schwarzschild_deflection(1.0, b)) < 2e-3, b


def test_prograde_rays_bend_less():
    assert gr.traced_deflection(1.0, 0.9, 8.0) < gr.traced_deflection(1.0, 0.0, 8.0) < gr.traced_deflection(1.0, -0.9, 8.0)


def test_the_shadow_angle_of_an_observer():
    assert abs(gr.shadow_angle(1.0, 10.0) - 0.48336) < 1e-5
    assert abs(gr.shadow_angle(1.0, 50.0) - 0.10200) < 1e-5


def test_a_disk_crossing_reports_its_radius_and_redshift():
    out = gr.trace(1.0, 0.0, 30.0, 1.3, (-1.0, 0.25, 0.0), r_far=100.0, disk=(6.0, 20.0, True))
    assert out["outcome"] == "disk"
    assert 6.0 <= out["r"] <= 20.0
    assert 0.3 < out["g"] < 1.5
    assert gr.trace(1.0, 0.0, 30.0, 1.3, (-1.0, 0.0, 0.0), r_far=100.0, disk=(6.0, 20.0, True))["outcome"] == "captured"
    out = gr.trace(1.0, 0.0, 30.0, 1.3, (-1.0, 0.25, 0.0), r_far=100.0, disk=(6.0, 7.0, True))
    assert out["outcome"] != "disk" or 6.0 <= out["r"] <= 7.0


def test_the_disk_redshift_reduces_to_schwarzschild_at_infinity():
    for r in (6.0, 10.0):
        g = gr.disk_redshift(1.0, 0.0, r, 1.0, 0.0, True)
        assert _close(g, math.sqrt(1.0 - 3.0 / r))
    assert _close(gr.disk_redshift(1.0, 0.0, 6.0, 1.0, 0.0, True), 0.7071067811865476, 1e-12)
    g_plus = gr.disk_redshift(1.0, 0.0, 10.0, 1.0, 2.0, True)
    g_minus = gr.disk_redshift(1.0, 0.0, 10.0, 1.0, -2.0, True)
    assert g_plus > g_minus


def test_the_trace_is_bounded():
    with pytest.raises(ValueError):
        gr.trace(1.0, 0.0, 10.0, math.pi / 2.0, (-1.0, 0.0, 0.0), r_far=50.0, max_steps=gr.MAX_STEPS + 1)
    with pytest.raises(ValueError):
        gr.trace(1.0, 0.0, 1.5, math.pi / 2.0, (-1.0, 0.0, 0.0), r_far=50.0)
    with pytest.raises(ValueError):
        gr.trace(1.0, 0.0, 10.0, math.pi / 2.0, (0.0, 0.0, 0.0), r_far=50.0)


def test_the_trace_is_a_function_of_its_inputs():
    one = gr.trace(1.0, 0.5, 15.0, 1.0, (-0.8, 0.2, 0.5), r_far=60.0)
    two = gr.trace(1.0, 0.5, 15.0, 1.0, (-0.8, 0.2, 0.5), r_far=60.0)
    assert one == two


# ------------------------------------------------------------------------------------ the camera

def test_doppler_and_aberration():
    beta = (0.5, 0.0, 0.0)
    gamma = 1.0 / math.sqrt(0.75)
    assert _close(gr.doppler((1.0, 0.0, 0.0), beta), gamma * 1.5)
    assert _close(gr.doppler((-1.0, 0.0, 0.0), beta), gamma * 0.5)
    assert _close(gr.doppler((0.0, 1.0, 0.0), beta), gamma)
    assert gr.doppler((0.0, 1.0, 0.0), (0.0, 0.0, 0.0)) == 1.0
    d = gr.aberration((0.0, 1.0, 0.0), beta)
    assert _close(math.sqrt(sum(c * c for c in d)), 1.0)
    assert d[0] > 0.0
    assert _close(gr.aberration((1.0, 0.0, 0.0), beta), (1.0, 0.0, 0.0))
    assert _close(gr.aberration((0.0, 0.0, 1.0), (0.0, 0.0, 0.0)), (0.0, 0.0, 1.0))
    with pytest.raises(ValueError):
        gr.doppler((1.0, 0.0, 0.0), (1.0, 0.0, 0.0))


def test_aberration_inverts_with_the_opposite_velocity():
    beta = (0.3, 0.4, 0.0)
    d = (0.2, -0.5, math.sqrt(1.0 - 0.29))
    back = gr.aberration(gr.aberration(d, beta), (-0.3, -0.4, 0.0))
    assert _close(back, d, 1e-12)


def test_the_searchlight_and_beaming():
    assert gr.searchlight(2.0) == 16.0
    assert _close(gr.beamed_radiance(0.5, 0.7071067811865476), 0.5 * 0.25)
    with pytest.raises(ValueError):
        gr.searchlight(-1.0)


def test_orbit_and_infall_speeds_and_the_infall_redshift():
    assert _close(gr.orbit_speed(1.0, 6.0), 0.5)
    assert _close(gr.infall_speed(1.0, 8.0), 0.5)
    assert _close(gr.infall_redshift(1.0, 8.0), 2.0 / 3.0)
    assert _close(gr.infall_redshift(1.0, 2.0), 0.5)
    assert _close(gr.infall_redshift(1.0, 1e12), 1.0, 1e-5)
    with pytest.raises(ValueError):
        gr.orbit_speed(1.0, 3.0)
    with pytest.raises(ValueError):
        gr.infall_speed(1.0, 1.0)


def test_the_camera_velocity_of_the_modes():
    assert gr.camera_velocity("static", 1.0, 10.0) == (0.0, 0.0, 0.0)
    v = gr.camera_velocity("orbit", 1.0, 10.0)
    assert _close(v, (0.0, 0.0, gr.orbit_speed(1.0, 10.0)))
    v = gr.camera_velocity("infall", 1.0, 10.0)
    assert _close(v, (-gr.infall_speed(1.0, 10.0), 0.0, 0.0))
    with pytest.raises(ValueError):
        gr.camera_velocity("warp", 1.0, 10.0)


# ------------------------------------------------------------------------------------ ray bundles

def test_the_bundle_jacobian_of_a_linear_map():
    J = gr.bundle_jacobian(lambda x, y: (2.0 * x, 3.0 * y), 0.0, 0.0, 1e-3)
    assert _close(J, ((2.0, 0.0), (0.0, 3.0)), 1e-6)
    assert _close(gr.magnification(J), 6.0, 1e-6)
    assert _close(gr.ellipse_axes(J), (3.0, 2.0), 1e-6)


def test_the_bundle_axes_of_a_rotation_are_one():
    c, s = math.cos(0.4), math.sin(0.4)
    J = gr.bundle_jacobian(lambda x, y: (c * x - s * y, s * x + c * y), 0.1, 0.2, 1e-4)
    assert _close(gr.ellipse_axes(J), (1.0, 1.0), 1e-6)
    assert _close(gr.magnification(J), 1.0, 1e-6)


def test_the_sky_map_at_10m_magnifies_the_sky_a_little():
    J = gr.sky_jacobian(1.0, 0.0, 10.0, (0.3, 0.0), 1e-4)
    assert 1.0 < gr.magnification(J) < 1.5
    assert abs(gr.magnification(gr.sky_jacobian(1.0, 0.0, 400.0, (0.3, 0.0), 1e-4)) - 1.0) < 0.02
    assert gr.ellipse_axes(J)[0] >= gr.ellipse_axes(J)[1] > 0.0


def test_bundle_filtering_takes_the_mean_over_the_ellipse():
    assert _close(gr.bundle_filter(lambda x, y: 1.0, ((1.0, 0.0), (0.0, 1.0)), 0.0, 0.0, 0.1, 16), 1.0)
    assert _close(gr.bundle_filter(lambda x, y: x, ((1.0, 0.0), (0.0, 1.0)), 0.5, 0.0, 0.1, 16), 0.5, 1e-9)
    with pytest.raises(ValueError):
        gr.bundle_filter(lambda x, y: 1.0, ((1.0, 0.0), (0.0, 1.0)), 0.0, 0.0, 0.1, 0)
    with pytest.raises(ValueError):
        gr.bundle_filter(lambda x, y: 1.0, ((1.0, 0.0), (0.0, 1.0)), 0.0, 0.0, 0.1, gr.MAX_BUNDLE + 1)


# ------------------------------------------------------------------------------------ the draft

@pytest.fixture(scope="module")
def draft():
    assert os.path.exists(DRAFT), "the draft SREP is missing"
    with open(DRAFT, encoding="utf-8") as f:
        return f.read()


def test_the_draft_has_the_srep_sections(draft):
    assert draft.startswith("```\nSREP:            0\n")
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft
    for section in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics",
                    "## Rationale", "## Rejected alternatives", "## Backwards compatibility", "## Engine impact",
                    "## Conformance", "### Numeric tests", "### Kit cases", "## Open issues", "## References",
                    "## History"):
        assert section in draft, section
    assert "... no" not in draft


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    assert "SR-79" in draft
    for word in ("spin", "motion", "bundle", "Boyer", "Carter", "V17", "aberration", "Doppler", "searchlight",
                 "sqrt(27)", "ISCO", "seek check", "relativistic_reference.py", "James"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [m.groups() for m in ROW.finditer(f.read())]
    rows = [r for r in rows if r[0] not in ("Test",)]
    return rows or [("empty table", "0", "1")]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 30


@pytest.mark.parametrize("name,expr,expected", _draft_rows(), ids=[r[0] for r in _draft_rows()])
def test_the_table_rows_hold(name, expr, expected):
    scope = gr.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert gr._same(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(draft, capsys):
    gr.main()
    out = capsys.readouterr().out.strip().splitlines()
    table = [line for line in draft.splitlines() if ROW.match(line) and not line.startswith("| Test")]
    assert out == table
