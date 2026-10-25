"""Tests for the draft SREP "Add spectral seas, caustics and flow maps to the ocean" (A4 of SREP 12) and its
reference module."""
import cmath
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "ocean_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-ocean.md")


def _load():
    spec = importlib.util.spec_from_file_location("ocean_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


oc = _load()
rs = oc.streams()


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ----------------------------------------------------------------------------------------------- dispersion


def test_dispersion_is_deep_in_deep_water_and_shallow_in_shallow_water():
    g = 9.81
    assert _close(oc.omega(0.1, g, None), math.sqrt(g * 0.1))
    assert _close(oc.omega(0.1, g, 1000.0), math.sqrt(g * 0.1), 1e-9)
    # shallow: omega = k sqrt(g d)
    assert _close(oc.omega(0.001, g, 2.0), 0.001 * math.sqrt(g * 2.0), 1e-6)
    # the group derivative d omega / d k by differences
    k = 0.2
    h = 1e-6
    for d in (None, 5.0):
        num = (oc.omega(k + h, g, d) - oc.omega(k - h, g, d)) / (2.0 * h)
        assert _close(oc.domega_dk(k, g, d), num, 1e-6)
    with pytest.raises(oc.OceanError):
        oc.omega(0.0, g, None)


# -------------------------------------------------------------------------------------------------- spectra


def test_the_frequency_spectra_peak_where_their_papers_say():
    g = 9.81
    pm = oc.pierson_moskowitz_peak(10.0, g)
    # Pierson and Moskowitz 1964 by way of Horvath 2015: omega_p = 0.877 g / (1.026 U10)
    assert _close(pm, 0.877 * g / (1.026 * 10.0))
    jp = oc.jonswap_peak(10.0, 100000.0, g)
    assert _close(jp, 22.0 * (g * g / (10.0 * 100000.0)) ** (1.0 / 3.0))
    # the spectra are maximal at their peaks (sampled around them)
    for f, peak in ((lambda w: oc.pierson_moskowitz(w, 10.0, g), pm),
                    (lambda w: oc.jonswap(w, 10.0, 100000.0, g, 3.3), jp)):
        values = [f(peak * (1.0 + 0.01 * i)) for i in range(-10, 11)]
        assert max(values) == values[10] or max(values) in values[9:12]
    # JONSWAP with gamma 1 is a fetch-limited Pierson-Moskowitz shape
    w = jp * 1.3
    base = oc.jonswap(w, 10.0, 100000.0, g, 1.0)
    assert _close(oc.jonswap(w, 10.0, 100000.0, g, 3.3) / base, 3.3 ** math.exp(-(w - jp) ** 2 / (2.0 * 0.09 ** 2 * jp * jp)))
    # the spectra vanish at omega -> 0 and decay as omega^-5
    assert oc.pierson_moskowitz(1e-3, 10.0, g) == 0.0 or oc.pierson_moskowitz(1e-3, 10.0, g) < 1e-300
    assert _close(oc.jonswap(40.0, 10.0, 100000.0, g, 3.3) / oc.jonswap(20.0, 10.0, 100000.0, g, 3.3), 2.0 ** -5, 1e-3)


def test_tma_is_jonswap_times_the_kitaigorodskii_depth_factor():
    g = 9.81
    assert oc.kitaigorodskii(0.5) == 0.5 * 0.25
    assert _close(oc.kitaigorodskii(1.5), 1.0 - 0.5 * (2.0 - 1.5) ** 2)
    assert oc.kitaigorodskii(2.0) == 1.0 and oc.kitaigorodskii(3.0) == 1.0
    w = 1.0
    d = 5.0
    assert _close(oc.tma(w, 10.0, 100000.0, d, g, 3.3), oc.jonswap(w, 10.0, 100000.0, g, 3.3) * oc.kitaigorodskii(w * math.sqrt(d / g)))
    # deep water leaves JONSWAP unchanged
    assert _close(oc.tma(w, 10.0, 100000.0, 1000.0, g, 3.3), oc.jonswap(w, 10.0, 100000.0, g, 3.3))


def test_the_directional_spreading_integrates_to_one_and_the_phillips_spectrum_follows_the_wind():
    for s in (1.0, 4.0, 10.0):
        total = oc.integrate_angle(lambda th: oc.spreading(th, 0.3, s))
        assert abs(total - 1.0) < 1e-6, s
    assert oc.spreading(0.3, 0.3, 10.0) > oc.spreading(0.3 + 1.0, 0.3, 10.0)
    assert oc.spreading(0.3 + math.pi, 0.3, 10.0) == 0.0
    # Phillips: zero against the wind's normal, maximal along it, zero at k = 0
    g = 9.81
    assert oc.phillips((0.0, 0.1), 10.0, 0.0, g) == 0.0
    assert oc.phillips((0.1, 0.0), 10.0, 0.0, g) > oc.phillips((0.1 * math.cos(1.0), 0.1 * math.sin(1.0)), 10.0, 0.0, g) > 0.0
    assert oc.phillips((0.0, 0.0), 10.0, 0.0, g) == 0.0
    assert _close(oc.phillips((0.1, 0.0), 10.0, 0.0, g), math.exp(-1.0 / (0.1 * 10.0 ** 2 / g) ** 2) / 0.1 ** 4)


def test_the_wavenumber_spectrum_carries_the_jacobian_of_the_polar_change():
    sea = oc.example_sea()
    g = 9.81
    k = (0.15, 0.05)
    kk = math.hypot(*k)
    w = oc.omega(kk, g, None)
    want = (oc.jonswap(w, sea["windSpeed"], sea["fetch"], g, sea["gamma"])
            * oc.spreading(math.atan2(k[1], k[0]), math.radians(sea["windDirection"]), sea["spread"])
            * oc.domega_dk(kk, g, None) / kk)
    assert _close(oc.spectrum_k(sea, k, g, None), want, 1e-12)
    assert oc.spectrum_k(sea, (0.0, 0.0), g, None) == 0.0
    # a small-wave cutoff removes short waves
    cut = dict(sea, cutoff=50.0)
    assert oc.spectrum_k(cut, (0.5, 0.0), g, None) == 0.0 and oc.spectrum_k(cut, (0.05, 0.0), g, None) > 0.0
    with pytest.raises(oc.OceanError):
        oc.spectrum_k(dict(sea, model="airy"), k, g, None)


def test_the_wave_height_variance_equals_the_spectrum_integral():
    g = 9.81
    sea = oc.example_sea()
    for model in ("piersonMoskowitz", "jonswap", "tma"):
        spec = dict(sea, model=model)
        m0 = oc.m0(spec, g, 20.0)
        assert m0 > 0.0
        # the discrete sum over the resolved band
        band = oc.variance_sum(spec, g, 20.0)
        assert abs(band / m0 - 1.0) < 0.06, (model, band, m0)
        # the generated amplitudes: Parseval over the grid, at two times
        e = oc.example_seed()
        for t in (0.0, 7.3):
            var = oc.variance_parseval(spec, e, t, g, 20.0)
            assert abs(var / m0 - 1.0) < 0.08, (model, t, var, m0)
    # the significant wave height is four times the root of the variance
    assert _close(oc.significant_height(0.25), 2.0)


# ---------------------------------------------------------------------------------------------- the field


def test_the_amplitudes_are_hermitian_and_analytic_in_time():
    sea = dict(oc.example_sea(), resolution=16, size=256.0)
    e = oc.example_seed()
    g = 9.81
    n = sea["resolution"]
    for (i, j) in ((3, 5), (9, 2), (1, 15)):
        a = oc.amplitude(sea, e, i, j, 2.5, g, 20.0)
        b = oc.amplitude(sea, e, (-i) % n, (-j) % n, 2.5, g, 20.0)
        assert abs(a - b.conjugate()) < 1e-12
    # the same draws give the same amplitudes; t enters analytically
    h0 = oc.amplitude0(sea, e, 3, 5, g, 20.0)
    assert h0 == oc.amplitude0(sea, e, 3, 5, g, 20.0)
    k = oc.wavevector(sea, 3, 5)
    w = oc.omega(math.hypot(*k), g, 20.0)
    h0m = oc.amplitude0(sea, e, (-3) % n, (-5) % n, g, 20.0)
    want = h0 * cmath.exp(1j * w * 2.5) + h0m.conjugate() * cmath.exp(-1j * w * 2.5)
    assert abs(oc.amplitude(sea, e, 3, 5, 2.5, g, 20.0) - want) < 1e-12
    # the draws come from the streams on channels 1 and 2 at pack(i, j, 0)
    kk = math.hypot(*k)
    p = oc.spectrum_k(sea, k, g, 20.0) * oc.dk(sea) ** 2
    xi = complex(rs.G(e, oc.REAL_CHANNEL, rs.pack(3, 5, 0)), rs.G(e, oc.IMAG_CHANNEL, rs.pack(3, 5, 0)))
    assert abs(h0 - xi * math.sqrt(p) / 2.0) < 1e-12
    # the Nyquist row and column and k = 0 are empty
    assert oc.amplitude0(sea, e, 0, 0, g, 20.0) == 0 and oc.amplitude0(sea, e, n // 2, 3, g, 20.0) == 0


def test_the_height_is_real_and_periodic_and_the_sea_seed_uses_its_purpose():
    sea = dict(oc.example_sea(), resolution=8, size=128.0)
    e = oc.example_seed()
    g = 9.81
    h = oc.height(sea, e, 10.0, 20.0, 1.0, g, 20.0)
    assert isinstance(h, float)
    assert _close(oc.height(sea, e, 10.0 + sea["size"], 20.0, 1.0, g, 20.0), h, 1e-9)
    assert _close(oc.height(sea, e, 10.0, 20.0 - sea["size"], 1.0, g, 20.0), h, 1e-9)
    assert oc.element_seed(7, "sea1", 3) == rs.E(7, "sea1", 3, "sea")
    assert oc.example_seed() == oc.element_seed(7, "sea1", 3)


def test_the_displacement_and_the_jacobian_match_differences_and_choppiness_folds_the_surface():
    sea = dict(oc.example_sea(), resolution=8, size=128.0, choppiness=1.0)
    e = oc.example_seed()
    g = 9.81
    x, z, t = 33.0, 71.0, 2.0
    d = oc.displacement(sea, e, x, z, t, g, 20.0)
    assert len(d) == 3
    assert _close(d[1], oc.height(sea, e, x, z, t, g, 20.0), 1e-12)
    eps = 1e-4
    dxdx = (oc.displacement(sea, e, x + eps, z, t, g, 20.0)[0] - oc.displacement(sea, e, x - eps, z, t, g, 20.0)[0]) / (2 * eps)
    dzdz = (oc.displacement(sea, e, x, z + eps, t, g, 20.0)[2] - oc.displacement(sea, e, x, z - eps, t, g, 20.0)[2]) / (2 * eps)
    dxdz = (oc.displacement(sea, e, x, z + eps, t, g, 20.0)[0] - oc.displacement(sea, e, x, z - eps, t, g, 20.0)[0]) / (2 * eps)
    want = (1.0 + dxdx) * (1.0 + dzdz) - dxdz * dxdz
    assert _close(oc.jacobian(sea, e, x, z, t, g, 20.0), want, 1e-5)
    # no choppiness: no horizontal displacement, Jacobian 1
    flat = dict(sea, choppiness=0.0)
    assert oc.displacement(flat, e, x, z, t, g, 20.0)[0] == 0.0 and oc.jacobian(flat, e, x, z, t, g, 20.0) == 1.0
    # more choppiness lowers the minimum Jacobian over a line of points
    def min_j(c):
        s = dict(sea, choppiness=c)
        return min(oc.jacobian(s, e, i * sea["size"] / 32.0, z, t, g, 20.0) for i in range(32))
    assert min_j(2.0) < min_j(1.0) < min_j(0.5)
    # foam where the Jacobian falls under the threshold
    assert oc.foam(0.5, 0.8) == 1.0 and oc.foam(1.2, 0.8) == 0.0 and _close(oc.foam(0.65, 0.8), 0.5)


def test_the_normal_follows_the_slopes():
    sea = dict(oc.example_sea(), resolution=8, size=128.0)
    e = oc.example_seed()
    g = 9.81
    x, z, t = 12.0, 5.0, 0.5
    sx, sz = oc.slopes(sea, e, x, z, t, g, 20.0)
    eps = 1e-4
    nx = (oc.height(sea, e, x + eps, z, t, g, 20.0) - oc.height(sea, e, x - eps, z, t, g, 20.0)) / (2 * eps)
    assert _close(sx, nx, 1e-5)
    n = oc.normal(sx, sz)
    assert _close(math.hypot(*n), 1.0) and n[1] < 0.0            # scene y points down, so the up normal has -y
    assert _close(n, (sx / math.sqrt(1 + sx * sx + sz * sz), -1.0 / math.sqrt(1 + sx * sx + sz * sz), sz / math.sqrt(1 + sx * sx + sz * sz)))


# ----------------------------------------------------------------------------------------------------- optics


def test_fresnel_is_two_percent_at_normal_incidence_and_total_beyond_the_critical_angle():
    f0 = oc.fresnel(1.0, oc.WATER_IOR)
    assert abs(f0 - 0.020) < 5e-4 and _close(f0, ((oc.WATER_IOR - 1.0) / (oc.WATER_IOR + 1.0)) ** 2)
    assert oc.fresnel(0.0, oc.WATER_IOR) == 1.0
    assert oc.fresnel(0.5, oc.WATER_IOR) > f0
    # from below: total internal reflection beyond the critical angle
    assert oc.fresnel(math.cos(math.radians(60.0)), 1.0 / oc.WATER_IOR) == 1.0
    assert oc.fresnel(math.cos(math.radians(30.0)), 1.0 / oc.WATER_IOR) < 1.0
    # Snell's window
    assert abs(oc.snell_window(oc.WATER_IOR) - 48.6) < 0.05
    d = oc.refract((0.6, 0.8, 0.0), (0.0, 1.0, 0.0), 1.0 / oc.WATER_IOR)
    assert _close(math.hypot(*d), 1.0) and _close(d[0], 0.6 / oc.WATER_IOR)
    assert oc.refract((0.9, math.sqrt(1 - 0.81), 0.0), (0.0, 1.0, 0.0), oc.WATER_IOR) is None


def test_caustics_conserve_the_transmitted_energy_and_focus_under_crests():
    c = oc.caustics(amplitude=0.2, wavelength=4.0, depth=4.0, rays=4000, bins=40)
    assert len(c) == 40
    assert all(v >= 0.0 for v in c)
    # the mean floor irradiance over a period is the transmitted fraction, the rays' mean (1 - F)
    assert abs(sum(c) / 40 - oc.transmitted_fraction(0.2, 4.0, 4000)) < 1e-9
    assert max(c) > 1.5 * (sum(c) / 40)              # bright lines
    flat = oc.caustics(amplitude=0.0, wavelength=4.0, depth=4.0, rays=400, bins=8)
    assert all(_close(v, 1.0 - oc.fresnel(1.0, oc.WATER_IOR), 1e-12) for v in flat)
    with pytest.raises(oc.OceanError):
        oc.caustics(amplitude=0.2, wavelength=4.0, depth=2.0, rays=0, bins=8)


def test_the_water_medium_absorbs_red_first():
    a = oc.water_absorption()
    assert a == oc.DEFAULTS["absorption"] == (0.34, 0.0565, 0.0092)
    t = oc.depth_transmittance(a, 10.0)
    assert t[0] < t[1] < t[2] and _close(t[2], math.exp(-0.092))
    ocean = oc.example_document()["oceans"][0]
    seen = oc.underwater_colour(ocean, 10.0, (1.0, 1.0, 1.0))
    assert _close(seen, oc.depth_transmittance(oc.extinction(ocean), 10.0))
    assert all(u < v for u, v in zip(seen, t))                      # the scattering attenuates the direct light too


# -------------------------------------------------------------------------------------------------- flow maps


def test_flow_map_phases_blend_two_layers_continuously():
    for t in (0.0, 0.25, 0.5, 0.75, 0.99):
        p0, p1, w0 = oc.flow_phases(t, 1.0)
        assert _close(p0, t % 1.0) and _close(p1, (t + 0.5) % 1.0)
        assert 0.0 <= w0 <= 1.0 and _close(w0, 1.0 - abs(2.0 * p0 - 1.0))
    # at the reset of a layer its weight is zero, so the jump is invisible
    assert oc.flow_phases(0.0, 2.0)[2] == 0.0 and oc.flow_phases(1.0, 2.0)[2] == 1.0
    # a constant texture flows to itself; a ramp moves against the flow
    assert _close(oc.flow_sample(lambda uv: 1.0, (0.2, 0.3), (1.0, 0.0), 0.3, 1.0, 1.0), 1.0)
    ramp = oc.flow_sample(lambda uv: uv[0], (0.2, 0.3), (0.1, 0.0), 0.5, 1.0, 1.0)
    p0, p1, w0 = oc.flow_phases(0.5, 1.0)
    assert _close(ramp, w0 * (0.2 - 0.1 * p0) + (1.0 - w0) * (0.2 - 0.1 * p1))
    with pytest.raises(oc.OceanError):
        oc.flow_phases(0.0, 0.0)


# ---------------------------------------------------------------------------------------------- the ocean


def test_the_sea_adds_to_the_ocean_surface_with_the_depth_taper():
    assert oc.taper(1.0, 10.0) == 1.0
    assert oc.taper(8.0, 10.0) == 5.0 and oc.taper(-8.0, 10.0) == -5.0
    assert oc.taper(0.0, 0.0) == 0.0
    doc = oc.example_document()
    e = oc.example_seed()
    s = oc.surface_height(doc, e, 3.0, 4.0, 1.0)
    sea = doc["oceans"][0]["sea"]
    assert _close(s, doc["oceans"][0]["waterLevel"] - oc.taper(oc.height(sea, e, 3.0, 4.0, 1.0, 9.81, 10.0), 10.0))


def test_the_example_documents_validate_and_the_bad_one_lists_every_rule():
    assert oc.validate_document(oc.example_document()) == []
    assert oc.validate_document(oc.bad_document()) == ["OC1", "OC2", "OC3", "OC4", "OC5", "OC6"]


def test_validation_rules_one_at_a_time():
    def with_sea(**kw):
        doc = oc.example_document()
        doc["oceans"][0]["sea"].update(kw)
        return doc

    def with_ocean(**kw):
        doc = oc.example_document()
        doc["oceans"][0].update(kw)
        return doc

    assert oc.validate_document(with_sea(model="airy")) == ["OC1"]
    for kw in (dict(windSpeed=0.0), dict(fetch=0.0), dict(gamma=0.5), dict(spread=0.0), dict(cutoff=-1.0)):
        assert oc.validate_document(with_sea(**kw)) == ["OC2"], kw
    for kw in (dict(size=0.0), dict(resolution=12), dict(resolution=8, size=128.0), dict(resolution=4096), dict(choppiness=-0.1)):
        assert oc.validate_document(with_sea(**kw)) == ["OC3"], kw
    for kw in (dict(foamThreshold=-0.1), dict(foamThreshold=2.5), dict(foamDecay=-1.0)):
        assert oc.validate_document(with_sea(**kw)) == ["OC4"], kw
    for kw in (dict(absorption=(-1.0, 0.1, 0.1)), dict(scattering=(0.1, -0.1, 0.1)), dict(ior=0.9)):
        assert oc.validate_document(with_ocean(**kw)) == ["OC5"], kw
    for kw in (dict(flowMap="ghost"), dict(flowSpeed=-1.0), dict(flowCycle=0.0)):
        assert oc.validate_document(with_ocean(**kw)) == ["OC6"], kw
    # the sea's size must cover at least one cell of the solver and the wavelength floor holds
    low = oc.example_document()
    low["version"] = "1.7"
    assert oc.validate_document(low) == ["V17"]
    del low["oceans"][0]["sea"]
    for k in ("absorption", "scattering", "ior", "flowMap", "flowSpeed", "flowCycle", "caustics"):
        low["oceans"][0].pop(k, None)
    assert oc.validate_document(low) == []


def test_constants():
    assert oc.PURPOSE == "sea" and oc.REAL_CHANNEL == 1 and oc.IMAG_CHANNEL == 2
    assert oc.MODELS == ("phillips", "piersonMoskowitz", "jonswap", "tma")
    assert oc.WATER_IOR == 1.333 and oc.PM_ALPHA == 0.0081 and oc.PM_BETA == 0.74
    assert oc.DEFAULTS["model"] == "jonswap" and oc.DEFAULTS["windSpeed"] == 10.0 and oc.DEFAULTS["fetch"] == 100000.0
    assert oc.DEFAULTS["gamma"] == 3.3 and oc.DEFAULTS["spread"] == 10.0 and oc.DEFAULTS["size"] == 1024.0
    assert oc.DEFAULTS["resolution"] == 256 and oc.DEFAULTS["choppiness"] == 1.0 and oc.DEFAULTS["foamThreshold"] == 0.8
    assert oc.DEFAULTS["scattering"] == (0.003, 0.003, 0.003) and oc.DEFAULTS["flowCycle"] == 2.0
    assert oc.RESOLUTIONS == (16, 32, 64, 128, 256, 512, 1024, 2048)
    assert oc.OMEGA_STEPS == 4000 and oc.OMEGA_RANGE == (0.2, 8.0)


# ------------------------------------------------------------------------------------------------ the draft


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
    for word in ("SR-103", "SREP 12", "SREP 14", "SREP 40", "SREP 77", "SREP 79", "`sea`", "`model`", "phillips",
                 "piersonMoskowitz", "jonswap", "tma", "windSpeed", "windDirection", "fetch", "gamma", "spread",
                 "cutoff", "size", "resolution", "choppiness", "foamThreshold", "foamDecay", "absorption",
                 "scattering", "ior", "caustics", "flowMap", "flowSpeed", "flowCycle", "OC1", "OC2", "OC3", "OC4",
                 "OC5", "OC6", "V17", "ocean_reference.py", "random-streams", "D24", "pack(i, j, 0)", "Tessendorf",
                 "Horvath", "Hasselmann", "Pierson", "Moskowitz", "Kitaigorodskii", "Longuet-Higgins", "Pope",
                 "Fry", "Vlachos", "Jacobian", "Hermitian", "Parseval", "Fresnel", "Snell", "48.6", "0.020",
                 "whitewater", "`wave`", "waves.rs", "Houdini", "Blender", "HDRP", "significant wave height",
                 "1.333"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 24


def test_the_table_is_what_the_module_prints(draft):
    assert len(oc.TABLE) == len(_draft_rows())
    for (name, expr, _value), (dname, dexpr, _dvalue) in zip(oc.TABLE, _draft_rows()):
        assert name == dname and expr == dexpr


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = oc.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or oc._same(got, want), f"{name}: {got!r} != {want!r}"
