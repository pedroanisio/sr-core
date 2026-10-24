"""Tests of the draft SREP "Add scale: powers of ten, depth resolution and a floating origin"
(srep/srep-0000-scale.md) and of its reference implementation conformance/tools/scale_reference.py (SP5 of
SREP 12, SRC-48).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re
import struct

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "scale_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-scale.md")

_spec = importlib.util.spec_from_file_location("scale_reference", MODULE)
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _rel(a, b, tol=1e-12):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


def _binary32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


# ------------------------------------------------------------------------------------ binary32 helpers


def test_f32_rounds_to_binary32_and_keeps_representable_values():
    assert sc.f32(0.1) == _binary32(0.1)
    assert sc.f32(0.1) != 0.1
    assert sc.f32(1.0e6 + 0.25) == 1.0e6 + 0.25
    assert sc.f32(1.0e20) == _binary32(1.0e20)
    assert sc.f32(-2.5) == -2.5
    with pytest.raises(sc.ScaleError):
        sc.f32(1.0e39)


def test_f32_ulp_is_a_power_of_two_spacing():
    assert sc.f32_ulp(1.0) == 2.0 ** -23
    assert sc.f32_ulp(1.5) == 2.0 ** -23
    assert sc.f32_ulp(2.0) == 2.0 ** -22
    assert sc.f32_ulp(1.0e6) == 0.0625
    assert sc.f32_ulp(1.0e20) == 2.0 ** 43
    assert sc.f32_ulp(-1.0e20) == 2.0 ** 43
    assert sc.f32_ulp(1.0e-20) == 2.0 ** -90
    assert sc.f32_ulp(0.0) == 2.0 ** -149
    # the spacing is the exact distance to the next binary32 value
    for x in (1.0, 3.0, 1.0e6, 1.0e20, 7.0e-3):
        up = struct.unpack("<f", struct.pack("<I", struct.unpack("<I", struct.pack("<f", x))[0] + 1))[0]
        assert up - _binary32(x) == sc.f32_ulp(x), x


def test_f32_error_is_the_rounding_distance():
    assert sc.f32_error(1.0e6 + 0.25) == 0.0
    assert sc.f32_error(1.0e20) == abs(_binary32(1.0e20) - 1.0e20)
    assert 0.0 < sc.f32_error(1.0e20 + 1.0e12) <= sc.f32_ulp(1.0e20) / 2.0
    assert sc.f32_error(0.1) == abs(_binary32(0.1) - 0.1)


# ------------------------------------------------------------------------------------ depth mappings


def test_reversed_depth_is_one_at_near_and_zero_at_far():
    assert sc.depth(0.1, 0.1, 1.0e4, "reversed") == 1.0
    assert sc.depth(1.0e4, 0.1, 1.0e4, "reversed") == 0.0
    assert _close(sc.depth(0.2, 0.1, 1.0e19, "reversed"), 0.5, 1e-15)
    # the engine's clip mapping: z_clip = n f / (f - n) - n / (f - n) z with w = z
    n, f, z = 0.5, 2.0e3, 37.0
    clip = n * f / (f - n) - n / (f - n) * z
    assert _close(sc.depth(z, n, f, "reversed"), clip / z, 1e-15)
    assert sc.depth(z, n, f) == sc.depth(z, n, f, "reversed")


def test_logarithmic_depth_is_half_at_the_geometric_mean():
    assert sc.depth(0.1, 0.1, 1.0e19, "logarithmic") == 0.0
    assert _close(sc.depth(1.0e19, 0.1, 1.0e19, "logarithmic"), 1.0, 1e-15)
    assert _close(sc.depth(math.sqrt(0.1 * 1.0e19), 0.1, 1.0e19, "logarithmic"), 0.5, 1e-12)
    assert _close(sc.depth(10.0, 1.0, 1.0e3, "logarithmic"), 1.0 / 3.0, 1e-15)


def test_depth_refuses_bad_planes_modes_and_distances():
    for args in ((1.0, 0.0, 10.0), (1.0, -1.0, 10.0), (1.0, 1.0, 1.0), (1.0, 2.0, 1.0)):
        with pytest.raises(sc.ScaleError):
            sc.depth(*args)
    with pytest.raises(sc.ScaleError):
        sc.depth(0.05, 0.1, 100.0)
    with pytest.raises(sc.ScaleError):
        sc.depth(101.0, 0.1, 100.0)
    with pytest.raises(sc.ScaleError):
        sc.depth(1.0, 0.1, 100.0, "hyperbolic")
    assert sc.DEPTH_MODES == ("reversed", "logarithmic")


def test_distance_inverts_depth_in_both_modes():
    for mode in sc.DEPTH_MODES:
        for z in (0.1, 1.0, 123.456, 1.0e6, 1.0e12, 9.0e18):
            d = sc.depth(z, 0.1, 1.0e19, mode)
            assert 0.0 <= d <= 1.0
            assert _rel(sc.distance(d, 0.1, 1.0e19, mode), z, 1e-9), (mode, z)
    with pytest.raises(sc.ScaleError):
        sc.distance(1.5, 0.1, 100.0, "reversed")
    with pytest.raises(sc.ScaleError):
        sc.distance(-0.1, 0.1, 100.0, "logarithmic")


def test_depth_slope_is_the_derivative_of_the_mapping():
    for mode in sc.DEPTH_MODES:
        for z in (1.0, 1.0e3, 1.0e9):
            h = z * 1e-6
            numeric = abs(sc.depth(z + h, 0.1, 1.0e12, mode) - sc.depth(z - h, 0.1, 1.0e12, mode)) / (2 * h)
            assert _rel(sc.depth_slope(z, 0.1, 1.0e12, mode), numeric, 1e-6), (mode, z)
    assert _rel(sc.depth_slope(1.0e3, 0.1, 1.0e12, "logarithmic"), 1.0 / (1.0e3 * math.log(1.0e13)))


def test_depth_ulp_depends_on_the_buffer_kind():
    assert sc.depth_ulp(1.0, "float") == 2.0 ** -23
    assert sc.depth_ulp(0.5, "float") == 2.0 ** -24
    assert sc.depth_ulp(1.0e-20, "float") == 2.0 ** -90
    assert sc.depth_ulp(0.3, "fixed") == 2.0 ** -24
    assert sc.depth_ulp(1.0e-20, "fixed") == 2.0 ** -24
    assert sc.BUFFER_KINDS == ("float", "fixed")
    with pytest.raises(sc.ScaleError):
        sc.depth_ulp(0.5, "double")


def test_resolvable_gap_is_the_depth_step_over_the_slope():
    n, f = 0.1, 1.0e19
    for mode in sc.DEPTH_MODES:
        for kind in sc.BUFFER_KINDS:
            z = 1.0e6
            d = sc.depth(z, n, f, mode)
            want = sc.depth_ulp(d, kind) / sc.depth_slope(z, n, f, mode)
            assert _rel(sc.resolvable_gap(z, n, f, mode, kind), want)
            assert _rel(sc.relative_resolution(z, n, f, mode, kind), want / z)


def test_reversed_float_depth_resolves_one_part_in_ten_million_at_every_decade():
    n, f = 0.1, 1.0e19
    for k in range(0, 20):
        z = min(n * 10.0 ** k, f * 0.999)
        r = sc.relative_resolution(z, n, f, "reversed", "float")
        assert r <= 2.0 ** -23 * 1.0001, (k, r)


def test_reversed_fixed_depth_fails_far_from_the_camera_and_logarithmic_fixed_holds():
    n, f = 0.1, 1.0e19
    assert sc.relative_resolution(1.0e18, n, f, "reversed", "fixed") > 1.0e9
    assert sc.relative_resolution(0.1, n, f, "reversed", "fixed") < 1.0e-6
    for k in range(0, 20):
        z = min(n * 10.0 ** k, f)
        assert _rel(sc.relative_resolution(z, n, f, "logarithmic", "fixed"), 2.0 ** -24 * math.log(1.0e20), 1e-9)


def test_worst_resolution_and_resolves_decide_the_ratio():
    n, f = 0.1, 1.0e19
    assert sc.worst_resolution(n, f, "reversed", "float") <= 2.0 ** -23 * 1.0001
    assert _rel(sc.worst_resolution(n, f, "logarithmic", "fixed"), 2.0 ** -24 * math.log(1.0e20), 1e-9)
    assert sc.worst_resolution(n, f, "logarithmic", "float") < 1.0e-5
    assert sc.worst_resolution(n, f, "reversed", "fixed") > 1.0e9
    assert sc.resolves(n, f, "reversed", "float") is True
    assert sc.resolves(n, f, "logarithmic", "fixed") is True
    assert sc.resolves(n, f, "logarithmic", "float") is True
    assert sc.resolves(n, f, "reversed", "fixed") is False
    assert sc.resolves(0.1, 1.0e4, "reversed", "fixed") is False
    assert sc.resolves(0.1, 2.0, "reversed", "fixed") is True
    assert sc.RESOLUTION == 1.0e-5


def test_depth_ratio_is_bounded_by_sc1():
    assert sc.MAX_DEPTH_RATIO == 1.0e20
    assert sc.depth_ratio_valid(0.1, 1.0e19) is True
    assert sc.depth_ratio_valid(0.1, 1.0e4) is True
    assert sc.depth_ratio_valid(0.1, 2.0e19) is False
    assert sc.depth_ratio_valid(1.0, 1.0) is False
    assert sc.depth_ratio_valid(0.0, 1.0) is False
    sc.validate_camera(0.1, 1.0e19, "logarithmic")
    with pytest.raises(sc.ScaleError):
        sc.validate_camera(0.1, 2.0e19, "reversed")
    with pytest.raises(sc.ScaleError):
        sc.validate_camera(0.1, 1.0e4, "linear")


# ------------------------------------------------------------------------------------ geometric keys


def test_geometric_interpolation_moves_in_the_log_domain():
    assert sc.geometric(10.0, 1.0e20, 0.0) == 10.0
    assert sc.geometric(10.0, 1.0e20, 1.0) == 1.0e20
    assert _rel(sc.geometric(10.0, 1.0e20, 0.5), 10.0 * math.sqrt(1.0e19))
    for k in range(20):
        assert _rel(sc.geometric(10.0, 1.0e20, k / 19.0), 10.0 ** (k + 1)), k
    assert _rel(sc.geometric(1.0e20, 10.0, 0.25), 10.0 ** (20 - 19 * 0.25))
    assert _rel(sc.geometric(-2.0, -32.0, 0.5), -8.0)
    assert sc.geometric(3.0, 3.0, 0.7) == 3.0


def test_geometric_refuses_zero_mixed_signs_and_out_of_range_parameters():
    for v0, v1 in ((0.0, 1.0), (1.0, 0.0), (-1.0, 1.0), (2.0, -2.0)):
        with pytest.raises(sc.ScaleError):
            sc.geometric(v0, v1, 0.5)
    for u in (-0.01, 1.01):
        with pytest.raises(sc.ScaleError):
            sc.geometric(1.0, 10.0, u)
    sc.validate_keys(1.0, 10.0, "geometric")
    sc.validate_keys(-1.0, 10.0, "linear")
    with pytest.raises(sc.ScaleError):
        sc.validate_keys(-1.0, 10.0, "geometric")
    with pytest.raises(sc.ScaleError):
        sc.validate_keys(1.0, 10.0, "exponential")


def test_interpolate_dispatches_linear_and_geometric():
    assert sc.interpolate(10.0, 1000.0, 0.5, "linear") == 505.0
    assert _rel(sc.interpolate(10.0, 1000.0, 0.5, "geometric"), 100.0)
    assert sc.interpolate(10.0, 1000.0, 0.5) == 505.0
    with pytest.raises(sc.ScaleError):
        sc.interpolate(10.0, 1000.0, 0.5, "cubic")


def test_decades_count_the_powers_of_ten():
    assert sc.decade(1.0) == 0
    assert sc.decade(999.0) == 2
    assert sc.decade(1000.0) == 3
    assert sc.decade(0.05) == -2
    assert sc.decade(1.0e20) == 20
    assert _close(sc.decades(10.0, 1.0e20), 19.0, 1e-12)
    assert _close(sc.decades(1.0e20, 10.0), -19.0, 1e-12)
    with pytest.raises(sc.ScaleError):
        sc.decade(0.0)
    with pytest.raises(sc.ScaleError):
        sc.decades(-1.0, 10.0)


def test_powers_of_ten_camera_pulls_back_one_decade_per_equal_interval():
    t0, t1, d0, d1 = 2.0, 40.0, 10.0, 1.0e20
    assert sc.powers_of_ten(t0, t0, t1, d0, d1) == d0
    assert sc.powers_of_ten(t1, t0, t1, d0, d1) == d1
    assert sc.powers_of_ten(0.0, t0, t1, d0, d1) == d0
    assert sc.powers_of_ten(99.0, t0, t1, d0, d1) == d1
    for k in range(20):
        assert _rel(sc.powers_of_ten(t0 + 2.0 * k, t0, t1, d0, d1), 10.0 ** (k + 1)), k
    assert _rel(sc.time_at(1.0e5, t0, t1, d0, d1), t0 + 2.0 * 4)
    assert _rel(sc.time_at(d0, t0, t1, d0, d1), t0)
    with pytest.raises(sc.ScaleError):
        sc.powers_of_ten(3.0, 5.0, 5.0, d0, d1)
    with pytest.raises(sc.ScaleError):
        sc.time_at(1.0e21, t0, t1, d0, d1)


def test_frame_distance_is_a_pure_function_of_the_frame():
    fps = 24.0
    for frame in (0, 1, 47, 48, 480, 912):
        assert sc.frame_distance(frame, fps, 2.0, 40.0, 10.0, 1.0e20) == sc.powers_of_ten(
            frame / fps, 2.0, 40.0, 10.0, 1.0e20)
    assert _rel(sc.frame_distance(96, fps, 2.0, 40.0, 10.0, 1.0e20), 100.0)
    with pytest.raises(sc.ScaleError):
        sc.frame_distance(-1, fps, 2.0, 40.0, 10.0, 1.0e20)
    with pytest.raises(sc.ScaleError):
        sc.frame_distance(1, 0.0, 2.0, 40.0, 10.0, 1.0e20)


# ------------------------------------------------------------------------------------ the scale bar


def test_focal_pixels_follow_the_horizontal_field_of_view():
    # cameraType/@fov is horizontal: the focal distance in pixels is (frame width / 2) / tan(fov / 2)
    assert _rel(sc.focal_pixels(60.0, 1920.0), 960.0 / math.tan(math.radians(30.0)))
    assert _rel(sc.focal_pixels(90.0, 1000.0), 500.0)
    with pytest.raises(sc.ScaleError):
        sc.focal_pixels(0.0, 1920.0)
    with pytest.raises(sc.ScaleError):
        sc.focal_pixels(180.0, 1920.0)
    with pytest.raises(sc.ScaleError):
        sc.focal_pixels(60.0, 0.0)


def test_pixels_per_metre_scales_with_pixels_per_meter_focal_length_and_depth():
    focal = sc.focal_pixels(60.0, 1920.0)
    assert _rel(sc.pixels_per_metre(1000.0, focal, 100.0), 100.0 * focal / 1000.0)
    assert _rel(sc.pixels_per_metre(2000.0, focal, 100.0), 0.5 * sc.pixels_per_metre(1000.0, focal, 100.0))
    assert _rel(sc.pixels_per_metre_ortho(2000.0, 1080.0, 100.0), 54.0)
    for args in ((0.0, focal, 100.0), (1.0, focal, 0.0), (1.0, 0.0, 100.0)):
        with pytest.raises(sc.ScaleError):
            sc.pixels_per_metre(*args)
    with pytest.raises(sc.ScaleError):
        sc.pixels_per_metre_ortho(0.0, 1080.0, 100.0)


def test_nice_length_is_the_largest_one_two_five_power_of_ten_not_above_the_limit():
    assert sc.nice_length(2.1383) == 2.0
    assert sc.nice_length(0.9) == 0.5
    assert sc.nice_length(7.0) == 5.0
    assert sc.nice_length(10.0) == 10.0
    assert sc.nice_length(1.0) == 1.0
    assert sc.nice_length(4.999) == 2.0
    assert sc.nice_length(1.99e-6) == 1.0e-6
    assert sc.nice_length(3.0e20) == 2.0e20
    assert sc.STEPS == (1, 2, 5)
    with pytest.raises(sc.ScaleError):
        sc.nice_length(0.0)


def test_bar_unit_is_the_largest_unit_not_above_the_length():
    assert sc.bar_unit(1.0) == ("m", 1.0)
    assert sc.bar_unit(1.4e11) == ("m", 1.0)
    assert sc.bar_unit(sc.AU_M) == ("au", sc.AU_M)
    assert sc.bar_unit(1.0e15) == ("au", sc.AU_M)
    assert sc.bar_unit(sc.LY_M) == ("ly", sc.LY_M)
    assert sc.bar_unit(2.0e16) == ("ly", sc.LY_M)
    assert sc.bar_unit(sc.PC_M) == ("pc", sc.PC_M)
    assert sc.bar_unit(1.0e20) == ("pc", sc.PC_M)
    assert sc.bar_unit(1.0e20, "si") == ("m", 1.0)
    assert sc.bar_unit(1.0e-9) == ("m", 1.0)
    assert sc.UNITS == (("m", 1.0), ("au", sc.AU_M), ("ly", sc.LY_M), ("pc", sc.PC_M))
    assert sc.AU_M == 149597870700.0
    assert sc.LY_M == 9460730472580800.0
    assert _rel(sc.PC_M, 648000.0 / math.pi * sc.AU_M, 1e-15)
    with pytest.raises(sc.ScaleError):
        sc.bar_unit(1.0, "imperial")


def test_scale_labels_use_si_prefixes_on_metres_and_parsecs_only():
    assert sc.scale_label(2000.0, "m") == "2 km"
    assert sc.scale_label(5.0e-6, "m") == "5 µm"
    assert sc.scale_label(1.0, "m") == "1 m"
    assert sc.scale_label(0.5, "m") == "500 mm"
    assert sc.scale_label(2.0e-12, "m") == "2 pm"
    assert sc.scale_label(5.0e-13, "m") == "0.5 pm"
    assert sc.scale_label(1.0e11, "m") == "100 Gm"
    assert sc.scale_label(2.0e12, "m") == "2000 Gm"
    assert sc.scale_label(50000.0, "au") == "50000 au"
    assert sc.scale_label(2.0, "ly") == "2 ly"
    assert sc.scale_label(2000.0, "pc") == "2 kpc"
    assert sc.scale_label(5.0e6, "pc") == "5 Mpc"
    assert sc.scale_label(5.0e9, "pc") == "5 Gpc"
    assert sc.scale_label(2.0e10, "pc") == "20 Gpc"
    with pytest.raises(sc.ScaleError):
        sc.scale_label(1.0, "furlong")


def test_scale_bar_picks_the_largest_bar_that_fits():
    focal = sc.focal_pixels(60.0, 1920.0)
    ppm = sc.pixels_per_metre(2000.0, focal, 100.0)  # 83.1 screen pixels per metre
    bar = sc.scale_bar(ppm, 200)
    assert bar["metres"] == 2.0
    assert bar["unit"] == "m"
    assert bar["value"] == 2.0
    assert bar["label"] == "2 m"
    assert _rel(bar["pixels"], 2.0 * ppm)
    assert bar["pixels"] <= 200.0
    assert sc.scale_bar(ppm, 200)["pixels"] > 200.0 / 2.5 - 1e-9
    assert sc.scale_bar_at(2000.0, focal, 100.0, 200) == bar
    assert sc.scale_bar_at(2000.0, focal, 100.0, 200, "si") == bar
    # 2.5 pixels per metre: 50 m would be 125 px, 100 m 250 px
    assert sc.scale_bar(2.5, 200)["label"] == "50 m"
    assert sc.scale_bar(2.5, 250)["label"] == "100 m"
    assert sc.scale_bar(2.5, 249.999)["label"] == "50 m"
    # astronomical ladder
    far = sc.scale_bar(200.0 / (3.0 * sc.AU_M), 200)
    assert far["unit"] == "au" and far["value"] == 2.0 and far["label"] == "2 au"
    assert _rel(far["metres"], 2.0 * sc.AU_M)
    assert sc.scale_bar(200.0 / (3.0 * sc.AU_M), 200, "si")["label"] == "200 Gm"
    galactic = sc.scale_bar(200.0 / 1.0e20, 200)
    assert galactic["label"] == "2 kpc"
    assert _rel(galactic["metres"], 2000.0 * sc.PC_M)
    assert sc.scale_bar(200.0 / 1.0e20, 200, "si")["label"] == "100000000000 Gm"
    with pytest.raises(sc.ScaleError):
        sc.scale_bar(0.0, 200)
    with pytest.raises(sc.ScaleError):
        sc.scale_bar(ppm, 0)
    with pytest.raises(sc.ScaleError):
        sc.scale_bar(1.0e15, 1)  # below one picometre
    assert sc.MIN_BAR_M == 1.0e-12


def test_scale_bar_covers_the_widest_fraction_of_its_limit():
    # the bar is never shorter than 40 % of maxWidth: 5 -> 10 is the widest step of 1-2-5
    for ppm in (0.013, 0.7, 1.0, 2.5, 33.3, 1.0e-13, 1.0e-19):
        bar = sc.scale_bar(ppm, 300)
        assert 120.0 - 1e-9 <= bar["pixels"] <= 300.0, (ppm, bar)


def test_scale_bar_frames_follow_the_powers_of_ten_camera_and_seek():
    focal = sc.focal_pixels(60.0, 1920.0)
    first = sc.scale_bar_frame(0, 24.0, 2.0, 40.0, 10.0, 1.0e20, focal, 100.0, 200)
    assert first == sc.scale_bar_at(10.0, focal, 100.0, 200)
    at_48 = sc.scale_bar_frame(48, 24.0, 2.0, 40.0, 10.0, 1.0e20, focal, 100.0, 200)
    assert at_48 == sc.scale_bar_at(10.0, focal, 100.0, 200)
    at_96 = sc.scale_bar_frame(96, 24.0, 2.0, 40.0, 10.0, 1.0e20, focal, 100.0, 200)
    assert at_96["metres"] == 10.0 * first["metres"]
    last = sc.scale_bar_frame(960, 24.0, 2.0, 40.0, 10.0, 1.0e20, focal, 100.0, 200)
    assert last["unit"] == "pc"
    assert sc.seek_test() is True


# ------------------------------------------------------------------------------------ the floating origin


def test_world_coordinates_in_binary32_lose_the_gap_at_large_distances():
    # 1e20 is exact in binary64 and its spacing there is 2^14, so gaps are chosen as powers of two
    assert sc.world_error(1.0e20 + 2.0 ** 17, 1.0e20) == 2.0 ** 17
    assert sc.world_error(1.0e6 + 0.25, 1.0e6) == 0.0
    assert sc.world_error(1.0e8 + 1.0, 1.0e8) == 1.0
    assert _close(sc.world_error(1.0e8 + 0.1, 1.0e8), 0.1, 1e-7)
    assert sc.world_error(1000.0, 0.0) == 0.0
    assert sc.world_error(1.0e20 + 2.0 ** 43, 1.0e20) <= sc.f32_ulp(1.0e20)


def test_rebasing_about_the_eye_in_double_precision_keeps_the_gap():
    assert sc.rebased_error(1.0e20 + 2.0 ** 17, 1.0e20) == 0.0
    assert sc.rebased_error(1.0e20 + 2.0 ** 43, 1.0e20) == 0.0
    assert sc.rebased_error(1.0e8 + 0.1, 1.0e8) == sc.f32_error(1.0e8 + 0.1 - 1.0e8)
    assert sc.rebased_error(1.0e8 + 0.1, 1.0e8) < 1.0e-8
    assert sc.rebased_error(1.0e20 + 1.0e9 + 0.001, 1.0e20) <= sc.f32_ulp(1.0e9) / 2.0
    assert sc.rebased_error(5.0, 2.0) == 0.0


def test_floating_origin_rebases_every_position_about_the_eye():
    eye = (2.0 ** 66, -(2.0 ** 64), 2.0 ** 62)
    positions = (eye, (2.0 ** 66 + 2.0 ** 17, -(2.0 ** 64) - 2.0 ** 18, 2.0 ** 62 + 2.0 ** 16))
    assert sc.floating_origin(positions, eye) == ((0.0, 0.0, 0.0), (2.0 ** 17, -(2.0 ** 18), 2.0 ** 16))
    assert sc.floating_origin((), eye) == ()
    naive = sc.world_positions(positions, eye)
    assert naive[0] == (0.0, 0.0, 0.0)
    assert naive[1] == (0.0, 0.0, 0.0)
    with pytest.raises(sc.ScaleError):
        sc.floating_origin(((1.0, 2.0),), eye)


def test_rebase_needed_compares_the_world_error_with_the_resolution():
    assert sc.rebase_needed(1.0e20 + 2.0 ** 17, 1.0e20) is True
    assert sc.rebase_needed(1.0e8 + 0.1, 1.0e8) is True
    assert sc.rebase_needed(1.0e6 + 0.25, 1.0e6) is False
    assert sc.rebase_needed(1000.0, 0.0) is False
    assert sc.rebase_needed(1.0e20 + 1.0e18, 1.0e20) is False
    assert sc.rebase_needed(1.0e20, 1.0e20) is False


def test_world_extent_is_where_binary32_stops_resolving_the_gap():
    # the largest magnitude at which binary32 world coordinates still resolve `gap` units
    assert sc.world_extent(1.0) == 2.0 ** 24
    assert sc.world_extent(0.01) == 2.0 ** 17
    assert sc.world_extent(1.0e13) == 2.0 ** 67
    with pytest.raises(sc.ScaleError):
        sc.world_extent(0.0)


# ------------------------------------------------------------------------------------ validation


def test_scale_bar_validation_sc3_and_sc4():
    sc.validate_scale_bar(200, "auto", None, 0.1, 1.0e4, 1920)
    sc.validate_scale_bar(200, "si", 500.0, 0.1, 1.0e4, 1920)
    with pytest.raises(sc.ScaleError):
        sc.validate_scale_bar(0, "auto", None, 0.1, 1.0e4, 1920)
    with pytest.raises(sc.ScaleError):
        sc.validate_scale_bar(2000, "auto", None, 0.1, 1.0e4, 1920)
    with pytest.raises(sc.ScaleError):
        sc.validate_scale_bar(200, "metric", None, 0.1, 1.0e4, 1920)
    with pytest.raises(sc.ScaleError):
        sc.validate_scale_bar(200, "auto", 0.05, 0.1, 1.0e4, 1920)
    with pytest.raises(sc.ScaleError):
        sc.validate_scale_bar(200, "auto", 2.0e4, 0.1, 1.0e4, 1920)


def test_scope_and_same():
    s = sc.scope()
    assert s["math"] is math
    assert s["scale_bar"] is sc.scale_bar
    assert sc._same(1.0, 1.0 + 1e-7)
    assert not sc._same(1.0, 1.01)
    assert sc._same("2 km", "2 km")
    assert not sc._same("2 km", "5 km")
    assert sc._same((1.0, 2.0), (1.0, 2.0 + 1e-9))
    assert sc._same({"a": 1.0}, {"a": 1.0})
    assert sc._fmt(2.0) == "2"
    assert sc._fmt(2.74501e-06) == "2.74501e-06"
    assert sc._fmt("2 km") == "'2 km'"


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
    assert "SR-91" in draft
    for word in ("depth", "reversed", "logarithmic", "geometric", "scaleBar", "maxWidth", "units", "distance",
                 "floating origin", "binary32", "binary64", "powers of ten", "1-2-5", "au", "ly", "pc",
                 "SC1", "SC2", "SC3", "SC4", "V17", "seek check", "scale_reference.py", "SREP 14", "pixelsPerMeter",
                 "orthoHeight", "focalLength", "Depth32Float", "Eames", "Cozzi", "Thatcher", "Upchurch",
                 "one space", "SR-91"):
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
    s = sc.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or sc._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    sc.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())
