"""Tests of the draft SREP "Add polarisation and wave optics" (srep/srep-0000-wave-optics.md) and of its
reference implementation conformance/tools/wave_optics_reference.py (OW3 of SREP 12, SRC-53).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import cmath
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "wave_optics_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-wave-optics.md")

_spec = importlib.util.spec_from_file_location("wave_optics_reference", MODULE)
wo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wo)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ------------------------------------------------------------------------------------ Jones calculus


def test_jones_vectors_are_unit_and_named():
    assert _close(wo.jones_linear(0.0), (1.0, 0.0))
    assert _close(wo.jones_linear(90.0), (0.0, 1.0))
    assert _close(wo.intensity(wo.jones_linear(37.0)), 1.0, 1e-12)
    left = wo.jones_circular("left")
    right = wo.jones_circular("right")
    assert _close(wo.intensity(left), 1.0, 1e-12)
    assert _close(abs(left[0]), abs(left[1]), 1e-12)
    # the two circular states are orthogonal
    assert abs(left[0] * right[0].conjugate() + left[1] * right[1].conjugate()) < 1e-12
    ell = wo.jones_elliptical(30.0, 20.0)
    assert _close(wo.intensity(ell), 1.0, 1e-12)
    assert _close(wo.jones_elliptical(0.0, 45.0), wo.jones_circular("left"), 1e-12)
    assert _close(wo.jones_elliptical(25.0, 0.0), wo.jones_linear(25.0), 1e-12)
    with pytest.raises(wo.WaveError):
        wo.jones_circular("up")


def test_malus_law_through_two_polarisers():
    for theta in (0.0, 30.0, 45.0, 60.0, 90.0):
        out = wo.apply(wo.polariser(theta), wo.jones_linear(0.0))
        assert _close(wo.intensity(out), wo.malus(theta), 1e-12), theta
        assert _close(wo.malus(theta), math.cos(math.radians(theta)) ** 2, 1e-15)
    # a polariser is idempotent and a projector
    p = wo.polariser(20.0)
    assert _close(wo.apply(p, wo.apply(p, wo.jones_linear(70.0))), wo.apply(p, wo.jones_linear(70.0)), 1e-12)
    # three polarisers at 0, 45, 90 pass 1/4 (cos^2 45 twice) while 0 and 90 alone pass nothing
    v = wo.jones_linear(0.0)
    assert _close(wo.intensity(wo.apply(wo.polariser(90.0), v)), 0.0, 1e-15)
    chain = wo.compose(wo.polariser(90.0), wo.polariser(45.0), wo.polariser(0.0))
    assert _close(wo.intensity(wo.apply(chain, v)), 0.25, 1e-12)
    # unpolarised light passes half through any polariser
    assert _close(wo.unpolarised_through(wo.polariser(33.0)), 0.5, 1e-12)


def test_waveplates_and_rotators():
    # a quarter-wave plate at 45 degrees turns linear light circular
    out = wo.apply(wo.quarter_wave(45.0), wo.jones_linear(0.0))
    assert _close(abs(out[0]), abs(out[1]), 1e-12)
    assert _close(abs(cmath.phase(out[1] / out[0])), math.pi / 2.0, 1e-12)
    assert _close(wo.degree_of_polarisation(wo.stokes(out)), 1.0, 1e-12)
    assert _close(abs(wo.stokes(out)[3]), 1.0, 1e-12)  # S3 is the circular component
    # a half-wave plate at theta rotates linear polarisation by 2 theta
    out = wo.apply(wo.half_wave(20.0), wo.jones_linear(0.0))
    assert _close(wo.intensity(wo.apply(wo.polariser(40.0), out)), 1.0, 1e-12)
    assert _close(wo.intensity(wo.apply(wo.polariser(130.0), out)), 0.0, 1e-12)
    # waveplate(180, theta) is the half-wave plate and waveplate(90, theta) the quarter-wave plate
    assert _close(wo.apply(wo.waveplate(180.0, 20.0), wo.jones_linear(10.0)),
                  wo.apply(wo.half_wave(20.0), wo.jones_linear(10.0)), 1e-12)
    # a rotator turns the plane by its angle
    out = wo.apply(wo.rotator(25.0), wo.jones_linear(10.0))
    assert _close(out, wo.jones_linear(35.0), 1e-12)
    # intensity is conserved by waveplates and rotators
    for m in (wo.quarter_wave(10.0), wo.half_wave(70.0), wo.rotator(-40.0), wo.waveplate(33.0, 12.0)):
        assert _close(wo.intensity(wo.apply(m, wo.jones_elliptical(15.0, 10.0))), 1.0, 1e-12)
    with pytest.raises(wo.WaveError):
        wo.waveplate(0.0, 10.0)


def test_stokes_parameters():
    s = wo.stokes(wo.jones_linear(0.0))
    assert _close(s, (1.0, 1.0, 0.0, 0.0), 1e-12)
    s = wo.stokes(wo.jones_linear(45.0))
    assert _close(s, (1.0, 0.0, 1.0, 0.0), 1e-12)
    s = wo.stokes(wo.jones_circular("left"))
    assert _close((s[0], s[1], s[2]), (1.0, 0.0, 0.0), 1e-12)
    assert _close(abs(s[3]), 1.0, 1e-12)
    assert _close(wo.degree_of_polarisation((1.0, 0.0, 0.0, 0.0)), 0.0, 1e-15)
    with pytest.raises(wo.WaveError):
        wo.degree_of_polarisation((0.0, 0.0, 0.0, 0.0))


def test_optical_rotation_follows_biot_and_colours_a_sugar_column():
    # sucrose: specific rotation +66.5 degrees per dm per (g / mL) at 589 nm
    assert _close(wo.biot_rotation(wo.SUCROSE_ROTATION, 1.0, 1.0, 589.0), 66.5, 1e-9)
    assert _close(wo.biot_rotation(wo.SUCROSE_ROTATION, 2.0, 0.5, 589.0), 66.5, 1e-9)
    # Biot's law: rotation grows as 1 / lambda^2, so blue turns more than red
    assert wo.biot_rotation(wo.SUCROSE_ROTATION, 1.0, 1.0, 450.0) > wo.biot_rotation(wo.SUCROSE_ROTATION, 1.0, 1.0, 650.0)
    assert _close(wo.biot_rotation(66.5, 1.0, 1.0, 589.0 * 2.0), 66.5 / 4.0, 1e-9)
    # between crossed polarisers the transmitted fraction is sin^2 of the rotation
    assert _close(wo.rotation_transmission(0.0, 90.0), 0.0, 1e-15)
    assert _close(wo.rotation_transmission(90.0, 90.0), 1.0, 1e-12)
    assert _close(wo.rotation_transmission(30.0, 0.0), 0.75, 1e-12)
    # the column's colour: white at zero length with a parallel analyser, black when crossed, coloured in between
    white = wo.rotation_colour(0.0, 1.0, 0.0)
    assert _close(white, (1.0, 1.0, 1.0), 1e-9)
    black = wo.rotation_colour(0.0, 1.0, 90.0)
    assert _close(black, (0.0, 0.0, 0.0), 1e-12)
    tinted = wo.rotation_colour(2.0, 1.0, 90.0)
    assert max(tinted) - min(tinted) > 0.1
    # the helix pitch of the E vector: 360 degrees of rotation per pitch
    assert _close(wo.helix_pitch(wo.SUCROSE_ROTATION, 1.0, 589.0), 360.0 / 66.5, 1e-9)
    with pytest.raises(wo.WaveError):
        wo.biot_rotation(66.5, -1.0, 1.0, 589.0)


# ------------------------------------------------------------------------------------ diffraction


def test_single_and_double_slit_closed_forms():
    assert wo.sinc(0.0) == 1.0
    assert _close(wo.sinc(math.pi), 0.0, 1e-15)
    lam, a, d = 500e-9, 20e-6, 100e-6
    assert _close(wo.single_slit(a, lam, 0.0), 1.0, 1e-15)
    for m in (1, 2, 3):
        theta = wo.slit_minimum(a, lam, m)
        assert _close(math.sin(theta), m * lam / a, 1e-15)
        assert _close(wo.single_slit(a, lam, theta), 0.0, 1e-12)
    assert _close(wo.double_slit(a, d, lam, 0.0), 1.0, 1e-15)
    # fringe spacing lambda L / d on a screen at L
    L = 1.0
    assert _close(wo.fringe_spacing(lam, L, d), lam * L / d, 1e-20)
    x1 = wo.fringe_spacing(lam, L, d)
    theta1 = math.atan(x1 / L)
    assert _close(wo.double_slit(a, d, lam, theta1) / wo.single_slit(a, lam, theta1), 1.0, 1e-6)
    theta_half = math.atan(0.5 * x1 / L)
    assert _close(wo.double_slit(a, d, lam, theta_half), 0.0, 1e-6)
    # the missing order: d / a = 5 kills the fifth bright fringe
    theta5 = math.asin(5.0 * lam / d)
    assert _close(wo.double_slit(a, d, lam, theta5), 0.0, 1e-12)
    with pytest.raises(wo.WaveError):
        wo.slit_minimum(a, lam, 100)  # sin would exceed 1


def test_bessel_and_the_airy_pattern():
    # J1 against its series at small x and a tabulated value
    assert _close(wo.bessel_j1(0.0), 0.0, 1e-15)
    assert _close(wo.bessel_j1(1.0), 0.4400505857, 1e-9)
    assert _close(wo.bessel_j1(5.0), -0.3275791376, 1e-9)
    assert _close(wo.bessel_j1(3.8317059702), 0.0, 1e-8)
    assert _close(wo.j1_first_zero(), 3.8317059702, 1e-7)
    assert _close(wo.AIRY_FACTOR, 3.8317059702 / math.pi, 1e-7)  # 1.2197 lambda / D
    lam, D = 550e-9, 2e-3
    assert _close(wo.airy(D, lam, 0.0), 1.0, 1e-12)
    theta0 = wo.airy_first_zero(D, lam)
    assert _close(math.sin(theta0), 1.2197 * lam / D, 1e-4 * lam / D)
    assert _close(wo.airy(D, lam, theta0), 0.0, 1e-10)
    # the first ring peaks near 1.75 % of the centre
    ring = max(wo.airy(D, lam, theta0 * (1.0 + i / 200.0)) for i in range(1, 200))
    assert _close(ring, 0.0175, 5e-4)
    # encircled energy in the central disc is 83.8 %
    assert _close(wo.airy_encircled(1.0), 0.838, 2e-3)


def test_gratings():
    lam, d, N = 500e-9, 2e-6, 100
    assert _close(wo.grating(N, d, lam, 0.0), 1.0, 1e-12)
    orders = wo.grating_orders(d, lam)
    assert len(orders) == 9  # m = -4 .. 4 fit under sin = 1 for d / lambda = 4
    assert _close(math.sin(orders[5]), lam / d, 1e-15)
    for m, theta in zip(range(-4, 5), orders):
        assert _close(wo.grating(N, d, lam, theta), 1.0, 1e-9), m
    # the first zero beside an order is 1 / N of the order spacing away
    theta = math.asin(lam / d + lam / (N * d))
    assert _close(wo.grating(N, d, lam, theta), 0.0, 1e-9)
    assert wo.resolving_power(N, 2) == 200
    assert _close(wo.grating_dispersion(d, lam, 1), 1.0 / (d * math.cos(math.asin(lam / d))), 1e-9)


def test_fft_matches_the_dft_and_parseval():
    import random
    rng = random.Random(3)
    xs = [complex(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(16)]
    got = wo.fft(xs)
    for k in range(16):
        want = sum(x * cmath.exp(-2j * math.pi * k * n / 16) for n, x in enumerate(xs))
        assert abs(got[k] - want) < 1e-12
    back = wo.ifft(got)
    assert all(abs(a - b) < 1e-12 for a, b in zip(back, xs))
    assert _close(sum(abs(v) ** 2 for v in got) / 16, sum(abs(v) ** 2 for v in xs), 1e-12)
    with pytest.raises(wo.WaveError):
        wo.fft(xs[:6])


def test_fraunhofer_by_fft_agrees_with_the_closed_forms():
    lam, L = 500e-9, 1.0
    slit = {"kind": "slit", "width": 20e-6}
    pattern = wo.fraunhofer_fft(slit, lam, L, samples=4096, extent=2e-3)
    assert len(pattern) == 4096
    xs = [x for x, _ in pattern]
    peak = max(i for _, i in pattern)
    assert _close(peak, 1.0, 1e-12)
    for x, inten in pattern:
        if abs(x) < 0.1:
            theta = math.atan(x / L)
            assert abs(inten - wo.single_slit(20e-6, lam, theta)) < 2e-2, x
    # the first minimum of the FFT pattern sits at L lambda / a within one sample
    dx = xs[1] - xs[0]
    first = min((i, x) for x, i in pattern if 0.015 < x < 0.035)[1]
    assert abs(first - L * lam / 20e-6) <= 2 * dx
    double = {"kind": "doubleSlit", "width": 20e-6, "separation": 100e-6}
    pattern = wo.fraunhofer_fft(double, lam, L, samples=4096, extent=2e-3)
    peaks = [x for (x0, i0), (x, i), (x2, i2) in zip(pattern, pattern[1:], pattern[2:])
             if i > i0 and i >= i2 and i > 0.2 and abs(x) < 0.012]
    spacings = [b - a for a, b in zip(peaks, peaks[1:])]
    assert spacings and all(abs(s - wo.fringe_spacing(lam, L, 100e-6)) <= 2 * dx for s in spacings)


def test_aperture_functions():
    f = wo.aperture_function({"kind": "slit", "width": 1.0}, 8, 4.0)
    assert len(f) == 8
    assert sum(abs(v) for v in f) == 2.0  # half-open [-a/2, a/2): samples at -0.5 and 0 (spacing 0.5)
    f = wo.aperture_function({"kind": "doubleSlit", "width": 0.5, "separation": 2.0}, 16, 4.0)
    assert sum(abs(v) for v in f) == 4.0
    g = wo.aperture_function({"kind": "grating", "lines": 4, "period": 1.0, "width": 0.25}, 32, 8.0)
    assert sum(abs(v) for v in g) == 4.0
    mask = wo.aperture_function({"kind": "mask", "values": [0, 1, 1, 0]}, 4, 4.0)
    assert [abs(v) for v in mask] == [0.0, 1.0, 1.0, 0.0]
    with pytest.raises(wo.WaveError):
        wo.aperture_function({"kind": "mask", "values": [0, 1, 1]}, 4, 4.0)
    with pytest.raises(wo.WaveError):
        wo.aperture_function({"kind": "circular", "diameter": 1.0}, 4, 4.0)  # the circular aperture is radial


def test_huygens_summation_reproduces_young_fringes_and_the_fresnel_number():
    lam, d, a, L = 500e-9, 100e-6, 5e-6, 1.0
    assert _close(wo.fresnel_number(a, lam, L), a * a / (lam * L), 1e-20)
    assert wo.fresnel_number(a, lam, L) < 0.1  # far field
    points = wo.aperture_points({"kind": "doubleSlit", "width": a, "separation": d}, 64)
    assert len(points) == 64
    spacing = wo.fringe_spacing(lam, L, d)
    center = abs(wo.huygens(points, lam, L, 0.0)) ** 2
    bright = abs(wo.huygens(points, lam, L, spacing)) ** 2
    dark = abs(wo.huygens(points, lam, L, spacing / 2.0)) ** 2
    assert _close(bright / center, 1.0, 1e-2)
    assert dark / center < 1e-2
    # a near-field screen: the pattern is not the Fraunhofer one
    near = wo.huygens_pattern(points, lam, 5e-3, (-2e-4, 2e-4), 201)
    assert len(near) == 201 and _close(max(i for _, i in near), 1.0, 1e-12)
    assert wo.fresnel_number(d, lam, 5e-3) > 1.0


def test_phase_as_hue():
    assert _close(wo.phase_hue(0.0), 0.0, 1e-15)
    assert _close(wo.phase_hue(math.pi), 0.5, 1e-15)
    assert _close(wo.phase_hue(-math.pi / 2.0), 0.75, 1e-15)
    assert _close(wo.complex_rgb(1.0 + 0j), (1.0, 0.0, 0.0), 1e-12)
    assert _close(wo.complex_rgb(cmath.exp(2j * math.pi / 3.0)), (0.0, 1.0, 0.0), 1e-12)
    assert _close(wo.complex_rgb(cmath.exp(4j * math.pi / 3.0)), (0.0, 0.0, 1.0), 1e-12)
    assert _close(wo.complex_rgb(0j), (0.0, 0.0, 0.0), 1e-15)
    assert _close(wo.complex_rgb(0.5 + 0j), (0.5, 0.0, 0.0), 1e-12)
    assert _close(wo.complex_rgb(2.0 + 0j, amplitude_max=4.0), (0.5, 0.0, 0.0), 1e-12)
    assert _close(wo.complex_rgb(3.0 + 0j, amplitude_max=1.0), (1.0, 0.0, 0.0), 1e-12)  # clipped
    assert _close(wo.hsv_to_rgb(1.0 / 6.0, 1.0, 1.0), (1.0, 1.0, 0.0), 1e-12)
    with pytest.raises(wo.WaveError):
        wo.complex_rgb(1.0 + 0j, amplitude_max=0.0)


def test_time_harmonic_fields_are_pure_functions_of_the_frame_and_the_seek_check_holds():
    lam, freq = 2.0, 0.5
    z0 = wo.time_harmonic(1.0, 0.0, lam, freq, 1.0)
    assert _close(abs(z0), 1.0, 1e-12)
    assert _close(cmath.phase(z0), math.pi, 1e-12)  # k x = pi at x = lambda / 2
    z1 = wo.time_harmonic(1.0, 1.0, lam, freq, 1.0)
    assert _close(cmath.phase(z1 / z0), -math.pi, 1e-12)  # omega t = pi after half a period
    assert wo.frame_field(12, 24.0, 1.0, lam, freq) == wo.time_harmonic(1.0, 0.5, lam, freq, 1.0)
    assert wo.seek_test() is True
    with pytest.raises(wo.WaveError):
        wo.frame_field(-1, 24.0, 1.0, lam, freq)


# ------------------------------------------------------------------------------------ validation


def test_validation_rules():
    wo.validate_polarisation({"polarisation": "linear", "angle": 30.0})
    wo.validate_polarisation({"polarisation": "circular", "handedness": "left"})
    wo.validate_polarisation({"polarisation": "elliptical", "angle": 10.0, "ellipticity": 20.0})
    wo.validate_polarisation({"polarisation": "none"})
    for bad in ({"polarisation": "radial"}, {"polarisation": "circular", "handedness": "up"},
                {"polarisation": "elliptical", "angle": 10.0, "ellipticity": 60.0}):
        with pytest.raises(wo.WaveError):
            wo.validate_polarisation(bad)
    wo.validate_jones_element({"kind": "polariser", "angle": 10.0})
    wo.validate_jones_element({"kind": "waveplate", "retardance": 90.0, "angle": 45.0})
    wo.validate_jones_element({"kind": "rotator", "angle": 20.0})
    wo.validate_jones_element({"kind": "rotator", "specificRotation": 66.5, "length": 1.0, "concentration": 0.5})
    for bad in ({"kind": "waveplate", "retardance": 0.0, "angle": 0.0}, {"kind": "mirror"},
                {"kind": "rotator", "specificRotation": 66.5, "length": -1.0, "concentration": 0.5},
                {"kind": "rotator"}):
        with pytest.raises(wo.WaveError):
            wo.validate_jones_element(bad)
    wo.validate_aperture({"kind": "slit", "width": 1e-5, "wavelength": 500.0, "distance": 1.0, "samples": 1024})
    wo.validate_aperture({"kind": "doubleSlit", "width": 1e-5, "separation": 1e-4, "wavelength": 500.0,
                          "distance": 1.0, "samples": 1024})
    wo.validate_aperture({"kind": "grating", "lines": 10, "period": 2e-6, "width": 1e-6, "wavelength": 500.0,
                          "distance": 1.0, "samples": 4096})
    wo.validate_aperture({"kind": "circular", "diameter": 1e-3, "wavelength": 500.0, "distance": 1.0, "samples": 256})
    for bad in ({"kind": "slit", "width": 0.0, "wavelength": 500.0, "distance": 1.0, "samples": 1024},
                {"kind": "doubleSlit", "width": 2e-4, "separation": 1e-4, "wavelength": 500.0, "distance": 1.0,
                 "samples": 1024},
                {"kind": "grating", "lines": 1, "period": 2e-6, "width": 1e-6, "wavelength": 500.0, "distance": 1.0,
                 "samples": 4096},
                {"kind": "slit", "width": 1e-5, "wavelength": 500.0, "distance": 1.0, "samples": 1000},
                {"kind": "slit", "width": 1e-5, "wavelength": 500.0, "distance": 1.0, "samples": 131072},
                {"kind": "slit", "width": 1e-5, "wavelength": 0.0, "distance": 1.0, "samples": 1024},
                {"kind": "slit", "width": 1e-5, "wavelength": 500.0, "distance": -1.0, "samples": 1024}):
        with pytest.raises(wo.WaveError):
            wo.validate_aperture(bad)
    wo.validate_display({"phase": "hue", "amplitude": "value"})
    wo.validate_display({"phase": "none", "amplitude": "value", "gamma": 2.2})
    for bad in ({"phase": "rainbow", "amplitude": "value"}, {"phase": "hue", "amplitude": "value", "gamma": 0.0},
                {"phase": "hue", "amplitude": "loud"}):
        with pytest.raises(wo.WaveError):
            wo.validate_display(bad)


def test_constants():
    assert wo.POLARISATIONS == ("none", "linear", "circular", "elliptical")
    assert wo.APERTURES == ("slit", "doubleSlit", "circular", "grating", "mask")
    assert wo.PHASE_MODES == ("hue", "none")
    assert wo.AMPLITUDE_MODES == ("value", "alpha", "none")
    assert wo.MAX_SAMPLES == 65536
    assert wo.SUCROSE_ROTATION == 66.5


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
    for word in ("SR-95", "polariser", "waveplate", "rotator", "detector", "polarisation", "diffraction", "aperture",
                 "slit", "doubleSlit", "circular", "grating", "mask", "Jones", "Stokes", "Malus", "Airy", "1.22",
                 "Huygens", "Fraunhofer", "Fresnel number", "FFT", "hue", "Biot", "sucrose", "retardance",
                 "handedness", "ellipticity", "WO1", "WO2", "WO3", "WO4", "V17", "seek check", "SREP 14",
                 "wave_optics_reference.py", "Hecht", "Born", "Wolf", "Goodman", "Collett"):
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
    s = wo.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or wo._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    wo.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
