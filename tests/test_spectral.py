"""Tests of the draft SREP "Add spectral rendering" (srep/srep-0000-spectral.md) and of its reference
implementation conformance/tools/spectral_reference.py (OW2 of SREP 12, SRC-52).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "spectral_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-spectral.md")

_spec = importlib.util.spec_from_file_location("spectral_reference", MODULE)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

_rs_spec = importlib.util.spec_from_file_location(
    "random_streams_reference", os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py"))
rs = importlib.util.module_from_spec(_rs_spec)
_rs_spec.loader.exec_module(rs)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ------------------------------------------------------------------------------------ dispersion models


def test_sellmeier_bk7_matches_the_schott_catalogue():
    # Schott N-BK7: n_d = 1.5168, n_F = 1.52238, n_C = 1.51432, V_d = 64.17
    assert _close(sp.glass_index("BK7", sp.LINES["d"]), 1.5168, 5e-5)
    assert _close(sp.glass_index("BK7", sp.LINES["F"]), 1.52238, 5e-5)
    assert _close(sp.glass_index("BK7", sp.LINES["C"]), 1.51432, 5e-5)
    assert _close(sp.abbe_number(lambda lam: sp.glass_index("BK7", lam)), 64.17, 0.05)
    # the model's coefficients are the public ones
    g = sp.GLASSES["BK7"]
    assert g["model"] == "sellmeier"
    assert _close(g["B"][0], 1.03961212, 1e-8)
    assert "source" in g and g["source"]


def test_the_glass_table_covers_the_named_glasses_with_known_indices():
    for name in ("BK7", "SF10", "SF11", "fusedSilica", "water", "diamond"):
        assert name in sp.GLASSES
        n = sp.glass_index(name, 587.56)
        assert 1.3 < n < 2.5
        # normal dispersion: the index falls with wavelength across the visible band
        assert sp.glass_index(name, 450.0) > n > sp.glass_index(name, 700.0)
    assert _close(sp.glass_index("fusedSilica", 587.56), 1.4585, 2e-4)
    assert _close(sp.glass_index("SF10", 587.56), 1.72825, 1e-4)
    assert _close(sp.glass_index("diamond", 587.56), 2.4175, 2e-3)
    assert _close(sp.glass_index("water", 587.56), 1.333, 2e-3)
    with pytest.raises(sp.SpectralError):
        sp.glass_index("unobtainium", 500.0)
    with pytest.raises(sp.SpectralError):
        sp.glass_index("BK7", 200.0)  # outside the fit's range


def test_sellmeier_and_cauchy_forms():
    B = (1.03961212, 0.231792344, 1.01046945)
    C = (0.00600069867, 0.0200179144, 103.560653)
    lam = 0.58756
    expected = math.sqrt(1.0 + sum(b * lam * lam / (lam * lam - c) for b, c in zip(B, C)))
    assert _close(sp.sellmeier(587.56, B, C), expected, 1e-12)
    # Cauchy n = A + B / lambda^2 with lambda in micrometres
    assert _close(sp.cauchy(500.0, 1.5, 0.004), 1.5 + 0.004 / 0.25, 1e-12)
    a, b = sp.cauchy_from_abbe(1.5168, 64.17)
    fn = lambda lam: sp.cauchy(lam, a, b)
    assert _close(fn(sp.LINES["d"]), 1.5168, 1e-9)
    assert _close(sp.abbe_number(fn), 64.17, 1e-6)
    with pytest.raises(sp.SpectralError):
        sp.sellmeier(587.56, (1.0, 1.0), C)  # mismatched lengths
    with pytest.raises(sp.SpectralError):
        sp.cauchy(500.0, 0.9, 0.0)  # index below 1


def test_refractive_index_dispatches_on_the_model():
    assert _close(sp.refractive_index({"model": "glass", "glass": "BK7"}, 587.56), 1.5168, 5e-5)
    assert _close(sp.refractive_index({"model": "cauchy", "A": 1.5, "B": 0.004}, 500.0), 1.516, 1e-12)
    assert _close(sp.refractive_index({"model": "sellmeier", "B": sp.GLASSES["BK7"]["B"], "C": sp.GLASSES["BK7"]["C"]},
                                      587.56), 1.5168, 5e-5)
    assert sp.refractive_index({"model": "none", "ior": 1.7}, 400.0) == 1.7
    assert sp.refractive_index({"model": "none", "ior": 1.7}, 700.0) == 1.7
    with pytest.raises(sp.SpectralError):
        sp.refractive_index({"model": "prism"}, 500.0)


def test_khr_dispersion_and_rgb_indices_bridge_to_the_raster_path():
    # KHR_materials_dispersion: dispersion = 20 / V_d
    assert _close(sp.khr_dispersion(64.17), 20.0 / 64.17, 1e-12)
    assert _close(sp.material_dispersion({"model": "glass", "glass": "BK7"}), 20.0 / 64.17, 2e-4)
    assert sp.material_dispersion({"model": "none", "ior": 1.5}) == 0.0
    r, g, b = sp.rgb_indices({"model": "glass", "glass": "BK7"})
    assert r < g < b
    assert _close(g, sp.glass_index("BK7", sp.RGB_WAVELENGTHS[1]), 1e-12)
    assert sp.RGB_WAVELENGTHS == (610.0, 550.0, 465.0)


# ------------------------------------------------------------------------------------ colour


def test_colour_matching_functions_peak_where_the_cie_tables_do():
    x, y, z = sp.cie_xyz(555.0)
    assert _close(y, 1.0, 0.02)
    assert y > x and y > z
    # the y-bar peak lies within 5 nm of 555 nm and the z-bar peak near 445 nm
    peak_y = max(range(380, 781), key=lambda lam: sp.cie_xyz(float(lam))[1])
    peak_z = max(range(380, 781), key=lambda lam: sp.cie_xyz(float(lam))[2])
    assert abs(peak_y - 555) <= 5
    assert abs(peak_z - 445) <= 5
    # x-bar has its secondary lobe in the violet
    assert sp.cie_xyz(445.0)[0] > 0.3
    # the three integrals are equal within 1 % (the equal-energy white)
    ints = [sum(sp.cie_xyz(float(l))[k] for l in range(360, 831)) for k in range(3)]
    assert max(ints) / min(ints) < 1.01


def test_equal_energy_and_d65_white_points():
    X, Y, Z = sp.xyz_from_spectrum(lambda lam: 1.0)
    assert _close(Y, 1.0, 1e-12)  # normalised to Y = 1
    x, y = sp.chromaticity(X, Y, Z)
    assert _close((x, y), (1.0 / 3.0, 1.0 / 3.0), 0.004)
    X, Y, Z = sp.white_point(sp.d65)
    assert Y == 1.0
    assert _close(sp.chromaticity(X, Y, Z), (0.3127, 0.3290), 0.003)
    assert _close((X, Z), (0.9505, 1.0890), 0.01)
    # the raw integral scales with the illuminant's power
    assert _close(sp.xyz_from_spectrum(sp.d65)[1], sp.xyz_from_spectrum(lambda lam: sp.d65(lam) / 2.0)[1] * 2.0, 1e-9)
    r, g, b = sp.xyz_to_linear_srgb(X, Y, Z)
    assert _close((r, g, b), (1.0, 1.0, 1.0), 0.02)
    # the matrices invert each other
    back = sp.linear_srgb_to_xyz(*sp.xyz_to_linear_srgb(0.3, 0.5, 0.2))
    assert _close(back, (0.3, 0.5, 0.2), 1e-9)
    assert _close(sp.linear_srgb_to_xyz(1.0, 1.0, 1.0), (0.9505, 1.0, 1.089), 2e-3)


def test_blackbody_follows_planck_and_wien():
    assert _close(sp.wien_peak(5778.0), 2.897771955e6 / 5778.0, 1e-6)
    peak = max(range(100, 3000), key=lambda lam: sp.blackbody(float(lam), 5778.0))
    assert abs(peak - sp.wien_peak(5778.0)) <= 1.0
    # Planck's law at one point: B(500 nm, 5778 K) in W sr^-1 m^-3
    h, c, k = 6.62607015e-34, 299792458.0, 1.380649e-23
    lam = 500e-9
    expected = 2 * h * c * c / lam ** 5 / (math.exp(h * c / (lam * k * 5778.0)) - 1.0)
    assert _close(sp.blackbody(500.0, 5778.0) / expected, 1.0, 1e-9)
    assert _close(sp.blackbody_normalised(sp.wien_peak(3000.0), 3000.0), 1.0, 1e-9)
    # chromaticity of a 6500 K blackbody lies within 0.01 of D65
    X, Y, Z = sp.xyz_from_spectrum(lambda lam: sp.blackbody(lam, 6500.0))
    assert _close(sp.chromaticity(X, Y, Z), (0.3127, 0.3290), 0.01)
    # a 3000 K body is orange: red above green above blue
    r, g, b = sp.xyz_to_linear_srgb(*sp.xyz_from_spectrum(lambda lam: sp.blackbody(lam, 3000.0)))
    assert r > g > b
    with pytest.raises(sp.SpectralError):
        sp.blackbody(500.0, 0.0)


def test_rgb_uplift_round_trips_in_gamut_colours():
    for rgb in ((0.2, 0.5, 0.7), (0.8, 0.3, 0.1), (0.5, 0.5, 0.5), (0.1, 0.6, 0.2), (0.9, 0.9, 0.2)):
        coeffs = sp.fit_uplift(rgb)
        back = sp.uplift_rgb(coeffs)
        assert _close(back, rgb, 2e-3), (rgb, back)
        # the spectrum is bounded in [0, 1]
        values = [sp.uplift_spectrum(coeffs, float(lam)) for lam in range(380, 781)]
        assert min(values) >= 0.0 and max(values) <= 1.0
    # grey is a flat spectrum
    c = sp.fit_uplift((0.5, 0.5, 0.5))
    assert _close((c[0], c[1]), (0.0, 0.0), 1e-6)
    flat = [sp.uplift_spectrum(c, float(lam)) for lam in range(380, 781, 50)]
    assert max(flat) - min(flat) < 1e-9
    assert sp.uplift_error((0.2, 0.5, 0.7)) < 2e-3
    with pytest.raises(sp.SpectralError):
        sp.fit_uplift((1.2, 0.0, 0.0))


def test_sigmoid_polynomial_form():
    assert _close(sp.sigmoid(0.0), 0.5, 1e-15)
    assert _close(sp.sigmoid(1e6), 1.0, 1e-9)
    assert _close(sp.sigmoid(-1e6), 0.0, 1e-9)
    # the polynomial is evaluated in the normalised wavelength (lambda - 380) / 400
    c = (1.0, -2.0, 0.5)
    t = (500.0 - 380.0) / 400.0
    assert _close(sp.uplift_spectrum(c, 500.0), sp.sigmoid(c[0] * t * t + c[1] * t + c[2]), 1e-15)


# ------------------------------------------------------------------------------------ hero wavelengths


def test_hero_wavelengths_are_rotations_of_the_hero():
    lams = sp.hero_wavelengths(0.1, 4)
    assert len(lams) == 4
    assert _close(lams[0], 380.0 + 0.1 * 400.0, 1e-12)
    assert _close(lams[1], lams[0] + 100.0, 1e-12)
    assert _close(lams[3], lams[0] + 300.0, 1e-12)
    wrapped = sp.hero_wavelengths(0.9, 4)
    assert _close(wrapped[1], 380.0 + 0.9 * 400.0 + 100.0 - 400.0, 1e-12)
    assert all(380.0 <= l < 780.0 for l in wrapped)
    assert sp.hero_wavelengths(0.25, 1) == (480.0,)
    custom = sp.hero_wavelengths(0.5, 2, 400.0, 700.0)
    assert _close(custom, (550.0, 400.0), 1e-12)
    with pytest.raises(sp.SpectralError):
        sp.hero_wavelengths(1.0, 4)
    with pytest.raises(sp.SpectralError):
        sp.hero_wavelengths(0.5, 0)
    with pytest.raises(sp.SpectralError):
        sp.hero_wavelengths(0.5, sp.MAX_WAVELENGTHS + 1)


def test_the_hero_draw_is_the_d24_unit_draw_of_the_path_stream():
    u = sp.hero_unit(7, 12345, 3)
    assert 0.0 <= u < 1.0
    assert u == rs.U(7, sp.CHANNEL_WAVELENGTH, sp.path_index(12345, 3))
    # pure function of frame-independent inputs; distinct across samples and pixels
    assert sp.hero_unit(7, 12345, 3) == sp.hero_unit(7, 12345, 3)
    assert sp.hero_unit(7, 12345, 4) != u
    assert sp.hero_unit(7, 12346, 3) != u
    lams = sp.frame_wavelengths(7, 12345, 3, 4)
    assert lams == sp.hero_wavelengths(sp.hero_unit(sp.frame_seed(0, 7), 12345, 3), 4)
    assert sp.frame_seed(0, 7) == rs.H(0, sp.CHANNEL_FRAME, 7)


def test_the_spectral_estimate_converges_to_the_integral():
    # a constant spectrum through many stratified heroes averages to the equal-energy XYZ
    target = sp.xyz_from_spectrum(lambda lam: 1.0)
    n = 256
    acc = [0.0, 0.0, 0.0]
    for i in range(n):
        est = sp.estimate_xyz(lambda lam: 1.0, sp.hero_wavelengths((i + 0.5) / n, 4))
        for k in range(3):
            acc[k] += est[k] / n
    assert _close(tuple(acc), target, 2e-3)
    # after a dispersive event only the hero survives and carries the full weight
    est = sp.estimate_xyz(lambda lam: 1.0, (550.0, 650.0, 750.0, 450.0), survivors=(True, False, False, False))
    hero_only = sp.estimate_xyz(lambda lam: 1.0, (550.0,))
    assert _close(est, hero_only, 1e-12)
    with pytest.raises(sp.SpectralError):
        sp.estimate_xyz(lambda lam: 1.0, (550.0, 650.0), survivors=(False, False))


def test_dispersive_refraction_keeps_the_hero_and_drops_the_companions():
    lams = (500.0, 600.0, 700.0, 400.0)
    out = sp.dispersive_event(lams, {"model": "glass", "glass": "BK7"})
    assert out["survivors"] == (True, False, False, False)
    assert _close(out["index"], sp.glass_index("BK7", 500.0), 1e-12)
    # a non-dispersive material keeps every wavelength
    out = sp.dispersive_event(lams, {"model": "none", "ior": 1.5})
    assert out["survivors"] == (True, True, True, True)
    assert out["index"] == 1.5


def test_a_spectral_path_through_a_prism_splits_colours():
    rows = sp.prism_spectrum("BK7", 60.0, 50.0, (sp.LINES["F"], sp.LINES["d"], sp.LINES["C"]))
    assert [lam for lam, _ in rows] == [sp.LINES["F"], sp.LINES["d"], sp.LINES["C"]]
    dev = [d for _, d in rows]
    assert dev[0] > dev[1] > dev[2]  # blue deviates most
    spread = sp.angular_dispersion("BK7", 60.0, 50.0)
    assert _close(spread, dev[0] - dev[2], 1e-12)
    assert 0.4 < spread < 1.0  # degrees between the F and C lines for a 60 degree BK7 prism near minimum deviation
    assert sp.angular_dispersion("SF10", 60.0, 60.0) > sp.angular_dispersion("BK7", 60.0, 60.0)
    # the deviation at d agrees with the ray-optics reference's formula
    import importlib.util as iu
    spec = iu.spec_from_file_location("ray_optics_reference", os.path.join(ROOT, "conformance", "tools",
                                                                           "ray_optics_reference.py"))
    ro = iu.module_from_spec(spec)
    spec.loader.exec_module(ro)
    assert _close(dev[1], ro.prism_deviation(sp.glass_index("BK7", sp.LINES["d"]), 60.0, 50.0), 1e-9)


def test_bench_elements_take_a_wavelength():
    el = {"kind": "prism", "n": 1.5, "material": {"model": "glass", "glass": "BK7"}}
    assert _close(sp.bench_index(el, 587.56), 1.5168, 5e-5)
    assert sp.bench_index({"kind": "prism", "n": 1.5}, 587.56) == 1.5
    assert sp.bench_index({"kind": "prism", "n": 1.5}, None) == 1.5
    with pytest.raises(sp.SpectralError):
        sp.bench_index(el, None)  # a dispersive element needs a wavelength
    rgb = sp.wavelength_rgb(550.0)
    assert len(rgb) == 3 and max(rgb) <= 1.0 and min(rgb) >= 0.0
    assert rgb[1] > rgb[0] and rgb[1] > rgb[2]
    red = sp.wavelength_rgb(650.0)
    assert red[0] > red[1] and red[0] > red[2]
    blue = sp.wavelength_rgb(450.0)
    assert blue[2] > blue[0] and blue[2] > blue[1]


# ------------------------------------------------------------------------------------ animation and the seek check


def test_frame_wavelengths_are_a_pure_function_of_the_frame_and_the_seek_check_holds():
    a = sp.frame_wavelengths(3, 10, 0, 4)
    b = sp.frame_wavelengths(3, 10, 0, 4)
    assert a == b
    assert sp.frame_wavelengths(4, 10, 0, 4) != a
    assert sp.seek_test() is True
    with pytest.raises(sp.SpectralError):
        sp.frame_wavelengths(-1, 10, 0, 4)


def test_spectral_and_rgb_renders_agree_for_uplifted_colours():
    # an RGB document rendered spectrally: the uplifted base colour under D65 comes back as the same colour
    for rgb in ((0.3, 0.6, 0.2), (0.7, 0.7, 0.7), (0.9, 0.1, 0.3)):
        assert sp.uplift_error(rgb) < sp.UPLIFT_BOUND
    assert sp.UPLIFT_BOUND <= 0.005


# ------------------------------------------------------------------------------------ validation


def test_validation_rules():
    sp.validate_material({"model": "glass", "glass": "BK7"})
    sp.validate_material({"model": "cauchy", "A": 1.5, "B": 0.004})
    sp.validate_material({"model": "sellmeier", "B": (1.0, 0.2, 1.0), "C": (0.006, 0.02, 103.0)})
    sp.validate_material({"model": "none", "ior": 1.5})
    for bad in ({"model": "glass", "glass": "nope"}, {"model": "cauchy", "A": 0.9, "B": 0.0},
                {"model": "sellmeier", "B": (1.0, 0.2), "C": (0.006, 0.02, 103.0)}, {"model": "sellmeier",
                "B": (1.0, 0.2, 1.0), "C": (-0.006, 0.02, 103.0)}, {"model": "none", "ior": 0.5}):
        with pytest.raises(sp.SpectralError):
            sp.validate_material(bad)
    sp.validate_spectral({"spectral": True, "bandMin": 380.0, "bandMax": 780.0, "wavelengths": 4})
    sp.validate_spectral({"spectral": False})
    for bad in ({"spectral": True, "bandMin": 500.0, "bandMax": 400.0, "wavelengths": 4},
                {"spectral": True, "bandMin": 300.0, "bandMax": 780.0, "wavelengths": 4},
                {"spectral": True, "bandMin": 380.0, "bandMax": 780.0, "wavelengths": 0},
                {"spectral": True, "bandMin": 380.0, "bandMax": 780.0, "wavelengths": 17}):
        with pytest.raises(sp.SpectralError):
            sp.validate_spectral(bad)
    sp.validate_emitter({"temperature": 6500.0})
    sp.validate_emitter({"spectrum": "#sun"})
    for bad in ({"temperature": 500.0}, {"temperature": 50000.0}, {"temperature": 6500.0, "spectrum": "#sun"}, {}):
        with pytest.raises(sp.SpectralError):
            sp.validate_emitter(bad)
    sp.validate_bench_wavelength(550.0)
    for bad in (370.0, 790.0):
        with pytest.raises(sp.SpectralError):
            sp.validate_bench_wavelength(bad)


def test_constants():
    assert sp.BAND == (380.0, 780.0)
    assert sp.DEFAULT_WAVELENGTHS == 4
    assert sp.MAX_WAVELENGTHS == 16
    assert sp.DISPERSION_MODELS == ("none", "cauchy", "sellmeier", "glass")
    assert _close(sp.LINES["d"], 587.56, 1e-9) and _close(sp.LINES["F"], 486.13, 1e-9)
    assert _close(sp.LINES["C"], 656.27, 1e-9)


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
    for word in ("SR-94", "dispersionModel", "glass", "cauchy", "sellmeier", "BK7", "SF10", "fusedSilica", "diamond",
                 "spectral", "bandMin", "bandMax", "wavelengths", "hero", "temperature", "spectrum", "uplift",
                 "Jakob", "Hanika", "Wilkie", "Wyman", "CIE 1931", "D65", "Abbe", "KHR_materials_dispersion",
                 "1.5168", "587.56", "SD1", "SD2", "SD3", "SD4", "V17", "seek check", "SREP 14", "SREP 92",
                 "spectral_reference.py", "Schott", "Malitson", "prism"):
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
    s = sp.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or sp._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    sp.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
