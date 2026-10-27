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


def test_a_lattice_origin_stays_within_half_a_cell_of_the_eye():
    # the eye rounded to the nearest multiple of the cell on each axis; a tie goes up; cell 0 is the eye itself
    assert sc.lattice_origin((2.0 ** 40 + 300.0, 700.0, -600.0), 1024.0) == (2.0 ** 40, 1024.0, -1024.0)
    assert sc.lattice_origin((512.0, -512.0, 0.0), 1024.0) == (1024.0, 0.0, 0.0)
    assert sc.lattice_origin((1.0e20, 1.0, -1.0), 1024.0) == (1.0e20, 0.0, 0.0)
    assert sc.lattice_origin((0.3, -0.7, 2.5), 0.0) == (0.3, -0.7, 2.5)
    eye = (2.0 ** 66 + 123456.0, -(2.0 ** 64) + 999.0, 777.0)
    for e, o in zip(eye, sc.lattice_origin(eye, 1024.0)):
        assert abs(e - o) <= 512.0 and o % 1024.0 == 0.0
    for bad in ((float("nan"), 0.0, 0.0), (0.0, float("inf"), 0.0)):
        with pytest.raises(sc.ScaleError):
            sc.lattice_origin(bad, 1024.0)
    with pytest.raises(sc.ScaleError):
        sc.lattice_origin((0.0, 0.0, 0.0), -1.0)
    with pytest.raises(sc.ScaleError):
        sc.lattice_origin((0.0, 0.0), 1024.0)


def test_the_rebased_error_bound_is_half_the_spacing_at_the_gap_plus_half_a_cell():
    assert sc.rebased_error_bound(0.0, 1024.0) == 2.0 ** -15
    assert sc.rebased_error_bound(1.0e9, 1024.0) == 32.0
    assert sc.rebased_error_bound(2.0 ** 17, 0.0) == sc.f32_ulp(2.0 ** 17) / 2.0
    assert sc.rebased_error_bound(3.1, 1024.0) < sc.RESOLUTION * 3.1
    assert sc.rebased_error_bound(3.0, 1024.0) > sc.RESOLUTION * 3.0
    for gap in (512.0, 1.0e3, 1.0e6, 1.0e9, 1.0e13, 1.0e20):
        assert sc.rebased_error_bound(gap, 1024.0) <= 2.0 ** -23 * gap
    with pytest.raises(sc.ScaleError):
        sc.rebased_error_bound(-1.0, 1024.0)
    # rebasing about the lattice origin keeps every error within the bound
    eye = (2.0 ** 40 + 300.0, -(2.0 ** 38) - 200.0, 2.0 ** 36 + 100.0)    # offsets below half a cell
    positions = (eye, (eye[0] + 2.0 ** 17 + 0.25, eye[1] - 2.0 ** 18, eye[2] + 1.0e9 + 0.001))
    rebased = sc.floating_origin(positions, eye, 1024.0)
    origin = sc.lattice_origin(eye, 1024.0)
    assert rebased[0] == (300.0, -200.0, 100.0)
    for p, r in zip(positions, rebased):
        for c, oc, rc, ec in zip(p, origin, r, eye):
            assert abs(rc - (c - oc)) <= sc.rebased_error_bound(abs(c - ec), 1024.0)
    assert sc.floating_origin(positions, eye) == sc.floating_origin(positions, eye, 0.0)


def test_the_draft_allows_a_lattice_origin_and_names_the_anchor_and_world_quantities(draft):
    assert "`lattice_origin(eye, cell)`" in draft and "`rebased_error_bound(g, cell)`" in draft
    assert "2⁻¹⁵ units at the eye for a 1024-unit cell" in draft
    assert "built about a binary64 anchor of its own" in draft
    assert "evaluated from the binary64 world position" in draft and "`altitude`" in draft


def test_the_draft_states_the_bars_drawing_order_frame_and_label(draft):
    assert "after all of the frame's content" in draft and "post effects never" in draft
    assert "the frame the camera draws into (the viewport for a" in draft and "`viewport3D`" in draft
    assert "a label no font can draw is an error" in draft
    assert "no bar on a 360 face" in draft
    # the engine's reported bars are the reference's
    bar = sc.scale_bar_at(5000.0, sc.focal_pixels(60, 320), 100, 200)
    assert bar["label"] == "20 m" and _close(bar["pixels"], 110.85125168440814, 1e-9)
    assert sc.scale_bar(sc.pixels_per_metre_ortho(2000, 1080, 100), 200) == sc.scale_bar(54, 200)
    assert sc.scale_bar(sc.pixels_per_metre_ortho(1080, 1080, 100), 200) == sc.scale_bar(100, 200)
    assert sc.lattice_origin((-512.0, -1536.0, 512.0), 1024.0) == (0.0, -1024.0, 1024.0)


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


def test_the_draft_states_the_fixed_buffer_bound_the_bar_labels_and_the_key_the_curve_leaves(draft):
    # the fixed-point buffer under `reversed`: 2^-24 f / n at the far plane, so one part in 1e5 holds to f / n = 168
    assert sc.resolves(1.0, 168.0, "reversed", "fixed") and not sc.resolves(1.0, 169.0, "reversed", "fixed")
    assert abs(sc.relative_resolution(168.0, 1.0, 168.0, "reversed", "fixed") / (168.0 / 2 ** 24) - 1.0) < 0.02
    assert "f / n = 168" in draft and "fails beyond n × 10⁵" not in draft
    # the scale-bar case's labels are the reference's
    labels = [sc.scale_bar_frame(f, 24, 2, 40, 10, 1e20, sc.focal_pixels(60, 1920), 100, 200)["label"]
              for f in (0, 96, 480, 960)]
    assert labels == ["10 mm", "100 mm", "10 Mm", "2 pc"]
    assert "(10 mm, 100 mm, 10 Mm, 2 pc" in draft and "(1 m, 10 m, 5 au, 2 pc)" not in draft
    # a key's interpolation is the curve of the segment it leaves (the schema's keyType), so SC2 pairs a geometric
    # key with the key after it
    assert "**SC2** a `geometric` key and the key after it have non-zero values of one sign" in draft
    assert "the key before it" not in draft and "the segment it leaves" in draft
    assert "the −1 key carries" in draft


def test_the_draft_states_sc2s_reach_and_the_scale_bar_checks(draft):
    # SC2 refuses `geometric` where a curve eases a progress from 0 to 1 (the implicit pair 0 -> 1 fails it)
    for consumer in ("`motionPath/@interpolation`", "`flyTo/@easing`", "`transition/@curve`", "`sizeCurve`", "`colorCurve`"):
        assert consumer in draft, consumer
    assert "a progress from 0 to 1" in draft and "never mapped to `linear`" in draft
    # a key that takes geometric from its animation's defaultInterpolation is checked too, timeRemap keys included
    assert '`defaultInterpolation="geometric"`' in draft and "`timeRemap`" in draft
    # the static check reads plain numbers; expressions and unit-suffixed values are the engine's build error
    assert "values are plain numbers" in draft and "build error of the engine" in draft
    assert "two lengths of one unit" in draft
    assert sc.validate_keys(2.0, 2000.0, "geometric") is None
    with pytest.raises(sc.ScaleError):
        sc.validate_keys(0.0, 1.0, "geometric")           # a progress curve's pair
    # SC3 and SC4 as checked, with the camera's defaults
    assert "at most one `scaleBar`" in draft and "`project/@width`" in draft
    assert "defaults 0.1 and 10 000 when absent" in draft
    with pytest.raises(sc.ScaleError):
        sc.validate_scale_bar(200, "auto", 20000.0, 0.1, 10000.0, 1920)
    sc.validate_scale_bar(200, "auto", 10000.0, 0.1, 10000.0, 1920)


def test_the_draft_records_the_engine_state(draft):
    row = next(line for line in draft.splitlines() if line.startswith("| Rust (`rs-scene-render`), reference |"))
    done, remaining = row.split(" | ")[1:3]
    assert done.startswith("feat/sr-67-fields bba6158") and "07a5ea3" in done and "f408760" in done and "SR-91" in row
    assert "E04" in done and "guarded" in done and "`powers_of_ten`" in done
    assert "685d380" in done and "`Depth32Float`" in done and "1 − d" in done
    assert "69867ab" in done and "`far` above `near`" in done and "848" in done
    assert "2a724ef" in done and "`lattice_origin(eye, 1024)`" in done and "12 mutants" in done
    assert "b620676" in done and "96b4a70" in done and "`scale_bar_frame`" in done and "`render --stats`" in done
    assert "b525913" in done and "joint look-at" in done
    assert remaining.startswith("none; the eight kit cases pass with the values below")
    assert "2.5D" not in remaining and "scale bar" not in remaining
    assert "no `near` clamp" not in remaining and "logarithmic mapping" not in remaining
    assert "lacks `far` above `near`" not in remaining and "SC1" not in remaining
    assert "at 67a661a `camera.rs` builds" not in done


def test_the_draft_states_the_stored_depth_sc1s_order_and_the_prepass(draft):
    # the engine may store 1 - d (the reverse-Z convention); the worst relative resolution is the same either way
    assert "may store 1 − d" in draft and "mirrored" in draft
    n, f = 0.1, 1.0e19
    worst = sc.worst_resolution(n, f, "logarithmic", "float")
    assert _close(worst, 2.0 ** -24 * math.log(f / n), 1e-12) and worst < sc.RESOLUTION    # 2.74e-6 at the far decades
    assert sc.resolves(n, f, "reversed", "float") and sc.relative_resolution(1.0e8, n, f, "reversed", "float") < 2e-7
    # SC1 states far > near, as depth_ratio_valid does
    assert "**SC1** `near` is positive, `far` exceeds `near`" in draft
    assert not sc.depth_ratio_valid(1.0, 1.0) and sc.depth_ratio_valid(1.0, 1.0001)
    with pytest.raises(sc.ScaleError):
        sc.validate_camera(1.0, 0.5)
    # the AO/SSR prepass keeps its own reverse-Z buffer
    assert "AO/SSR prepass" in draft


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


# ------------------------------------------------------------------------------------ the kit

KIT = os.path.join(ROOT, "conformance", "tools", "scale_kit.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kit = _load(KIT, "scale_kit")
np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")
CASE = r"(scale-[a-z-]+)"


def test_the_kit_camera_puts_a_scene_point_on_its_pixel():
    # fov 60 over 640 columns: focal 554.26 px; y runs down the frame
    f = kit.focal()
    assert _close(f, sc.focal_pixels(60, 640), 1e-12)
    assert _close(kit.pixel((0.0, 0.0, 1000.0)), (320.0, 180.0), 1e-12)
    assert _close(kit.pixel((100.0, 50.0, 1000.0)), (320.0 + f * 0.1, 180.0 + f * 0.05), 1e-9)
    with pytest.raises(ValueError):
        kit.pixel((0.0, 0.0, -1.0))
    d = kit.direction(320.0 + f * 0.1, 180.0 + f * 0.05)
    assert _close(math.sqrt(sum(c * c for c in d)), 1.0, 1e-12)
    assert _close(kit.pixel(tuple(1000.0 * c for c in d)), (320.0 + f * 0.1, 180.0 + f * 0.05), 1e-9)
    assert _close(kit.sphere_pixels(2.0, 10.0, f), f * 0.2 / math.sqrt(0.96), 1e-12)
    with pytest.raises(ValueError):
        kit.sphere_pixels(10.0, 10.0, f)


def test_the_kit_geometry_follows_the_draft():
    g = kit.geometry()
    assert list(g) == kit.NAMES
    # 19 pairs one decade apart from 1 to 1e18 pixels, the farther sphere one part in 1e4 behind, all in frame
    pairs = g["scale-depth"]["pairs"]
    assert sorted(pairs) == list(range(19)) and g["scale-depth"]["far"] / g["scale-depth"]["near"] == 1e20
    for k, p in pairs.items():
        assert _close(p["distance"], 10.0 ** k, 1e-9 * 10.0 ** k) and p["radius"] == kit.DEPTH_SIZE * p["distance"]
        near_d = math.sqrt(sum(c * c for c in p["near"]))
        far_d = math.sqrt(sum(c * c for c in p["far"]))
        assert _close(near_d, p["distance"], 1e-6 * p["distance"])
        assert _close(far_d - near_d, (p["distance"] + p["radius"]) * 1e-4, 1e-6 * p["distance"])
        px, py = kit.pixel(p["near"])
        assert 40.0 < px < 600.0 and 40.0 < py < 320.0 and _close((px, py), kit.depth_slots()[k], 1e-6)
    # the powers of ten camera is 10^(k + 1) pixels away at frame 48 + 48 k and the sphere 2 x 10^k is a fifth of that
    assert g["scale-powers"]["frames"] == tuple(48 + 48 * k for k in range(19))
    for k, fr in enumerate(g["scale-powers"]["frames"]):
        d = g["scale-powers"]["distances"][fr]
        assert _close(d, 10.0 ** (k + 1), 1e-9 * d) and g["scale-powers"]["radii"][k] == 2.0 * 10.0 ** k
        assert _close(g["scale-powers"]["pixels"][fr], kit.focal() * 0.2 / math.sqrt(0.96), 1e-6)
    # the bar's frames and labels are the reference's; the orthographic bar is scale_bar(54, 200)
    bars = g["scale-bar"]["bars"]
    assert [bars[f]["label"] for f in (0, 96, 480, 960)] == ["10 mm", "100 mm", "10 Mm", "2 pc"]
    assert bars[0] == sc.scale_bar_frame(0, 24, 2, 40, 10, 1e20, sc.focal_pixels(60, 1920), 100, 200)
    assert g["scale-bar"]["rows"] == (1054, 1056) and g["scale-bar-ortho"]["bar"] == sc.scale_bar(54, 200)
    # two spheres 2^17 apart, 2^14 wide, seen from between them 200 000 pixels away
    c = g["scale-origin"]["centres"]
    assert _close(c[0][1], 180.0, 1e-9) and _close(c[1][0] - c[0][0], 2 * kit.focal() * 65536.0 / 200000.0, 1e-6)
    assert 30.0 < g["scale-origin"]["pixel_radius"] < 60.0
    assert g["scale-invalid"]["documents"] == [f"scale-invalid-{c}" for c in ("sc1", "sc2", "sc3", "sc4", "v17")]


def test_the_kit_documents_are_the_drafts(tmp_path):
    import xml.etree.ElementTree as ET
    docs = kit.documents()
    assert set(docs) == {k for keys in kit.DOCUMENTS.values() for k in keys} and len(docs) == 12
    trees = {k: ET.fromstring(t) for k, t in docs.items()}
    for k, root in trees.items():
        assert root.get("version") == ("1.7" if k == "scale-invalid-v17" else "1.8"), k
        assert root.find("physics").get("pixelsPerMeter") == "100.0"
    cam = trees["scale-depth"].find("composition/camera")
    assert (cam.get("near"), cam.get("far"), cam.get("depth")) == ("0.1", "1e+19", "reversed")
    assert trees["scale-depth-log"].find("composition/camera").get("depth") == "logarithmic"
    assert len(trees["scale-depth"].findall("composition/object3D")) == 38
    keys = trees["scale-powers"].findall("composition/camera/animate/key")
    assert [(k.get("time"), k.get("value"), k.get("interpolation")) for k in keys] == [
        ("2", "-10.0", "geometric"), ("40", "-1e+20", None)]
    assert len(trees["scale-powers"].findall("composition/object3D")) == 19
    bar = trees["scale-bar"].find("composition/camera")
    assert bar.get("target") == "ball" and bar.find("scaleBar") is not None and bar.find("animate") is not None
    assert trees["scale-bar"].find("project").get("width") == "1920"
    ortho = trees["scale-bar-ortho"].find("composition/camera")
    assert ortho.get("projection") == "orthographic" and ortho.get("orthoHeight") == "2000.0"
    assert trees["scale-bar-ortho"].find("project").get("height") == "1080"
    far = trees["scale-origin-far"]
    assert far.find("composition/camera").get("x") == "1e+20"
    assert [o.get("x") for o in far.findall("composition/object3D")] == [repr(1e20 - 65536.0), repr(1e20 + 65536.0)]
    assert trees["scale-invalid-sc1"].find("composition/camera").get("far") == "2e19"
    assert trees["scale-invalid-sc3"].find("composition/camera/scaleBar").get("maxWidth") == "700"
    assert trees["scale-invalid-sc4"].find("composition/camera/scaleBar").get("distance") == "2e6"
    paths = kit.write(str(tmp_path))
    assert all(os.path.exists(p) for p in paths.values()) and paths["scale-depth"].endswith("srep-0000-scale-depth.xml")


def _stats_line(frame, bars):
    import json
    return json.dumps({"frame": frame, "stats": {"scale_bars": bars}, "gpu": None, "paths": {}})


@pytest.fixture(scope="module")
def synthetic():
    exp, g = kit.expectations(), kit.geometry()
    frames, stats = {}, {}
    depth = kit.paint_discs(list(kit.depth_slots().values()), 20.0, "red")
    frames["scale-depth@0"], frames["scale-depth-log@0"] = depth, depth.copy()
    for k, fr in zip(kit.POWERS_DECADES, kit.POWERS_FRAMES):
        frames[f"scale-powers@{fr}"] = kit.paint_discs([(320.0, 180.0)], g["scale-powers"]["pixels"][fr],
                                                        kit.PARITY[k % 2])
    for fr, bar in g["scale-bar"]["bars"].items():
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frames[f"scale-bar@{fr}"] = kit.paint_bar(frame, g["scale-bar"]["rows"], 24, bar["pixels"])
        stats[f"scale-bar@{fr}"] = [{"camera": "eye", "measured": "target", "depth": kit.powers_distance(fr),
                                     "pixels": bar["pixels"], "label": bar["label"]}]
    frame = np.zeros((1080, 640, 3), dtype=np.uint8)
    bar = g["scale-bar-ortho"]["bar"]
    frames["scale-bar-ortho@0"] = kit.paint_bar(frame, g["scale-bar-ortho"]["rows"], 24, bar["pixels"])
    stats["scale-bar-ortho@0"] = [{"camera": "eye", "measured": "orthoHeight", "depth": 2000.0,
                                   "pixels": bar["pixels"], "label": bar["label"]}]
    origin = kit.paint_discs(g["scale-origin"]["centres"], g["scale-origin"]["pixel_radius"], "red")
    frames["scale-origin-here@0"] = origin
    frames["scale-origin-far@0"], frames["scale-origin-far@12"] = origin.copy(), origin.copy()
    frames["seek-alone"] = frames[f"scale-powers@{kit.POWERS_FRAMES[-1]}"]
    frames["seek-played"] = frames["seek-alone"].copy()
    refusals = {f"scale-invalid-{c}": f"error[{c.upper()}] (eye): refused" for c in kit.INVALID}
    return exp, g, frames, stats, refusals


def test_the_kit_measures_the_synthetic_frames(synthetic):
    exp, g, frames, stats, refusals = synthetic
    depth = kit.measure("scale-depth", frames, exp)
    assert depth["pass"] and depth["decades"] == 19 and depth["farther_pixels"] == 0 and depth["worst_window_fill"] == 1.0
    log = kit.measure("scale-depth-log", frames, exp)
    assert log["pass"] and log["worst_level"] == 0.0
    powers = kit.measure("scale-powers", frames, exp)
    assert powers["pass"] and powers["worst_off_px"] <= 0.3 and powers["spread_px"] == 0.0 and powers["centre_hits"] == 19
    bar = kit.measure("scale-bar", frames, exp, stats=stats)
    assert bar["pass"] and bar["bars"].startswith("0: 10 mm 166.28 px; 96: 100 mm") and bar["worst_run_end_px"] <= 0.5
    ortho = kit.measure("scale-bar-ortho", frames, exp, stats=stats)
    assert ortho["pass"] and ortho["bars"] == "0: 2 m 108.0 px"
    origin = kit.measure("scale-origin", frames, exp)
    assert origin["pass"] and origin["worst_off_px"] == 0.0 and origin["motion_px"] == 0.0
    assert kit.measure("scale-seek", frames, exp)["identical"]
    invalid = kit.measure("scale-invalid", frames, exp, refusals=refusals)
    assert invalid["pass"] and invalid["refused"] == 5 and invalid["sc1"] == "SC1" and invalid["v17"] == "V17"
    assert kit.diagnostic_code("error: something else entirely") == "error: something else entirely"
    with pytest.raises(ValueError):
        kit.measure("scale-moons", frames, exp)


def test_the_kit_fails_a_wrong_frame(synthetic):
    exp, g, frames, stats, refusals = synthetic

    def with_frame(key, frame):
        bad = dict(frames)
        bad[key] = frame
        return bad

    # a farther sphere showing through a nearer one
    leak = frames["scale-depth@0"].copy()
    cx, cy = kit.depth_slots()[18]
    leak[int(cy), int(cx)] = (0, 255, 0)
    assert not kit.measure("scale-depth", with_frame("scale-depth@0", leak), exp)["pass"]
    # a missing pair
    gone = kit.paint_discs(list(kit.depth_slots().values())[:-1], 20.0, "red")
    assert not kit.measure("scale-depth", with_frame("scale-depth@0", gone), exp)["pass"]
    # the logarithmic image two levels off
    off = frames["scale-depth-log@0"].copy()
    off[0, 0] = (2, 0, 0)
    assert not kit.measure("scale-depth-log", with_frame("scale-depth-log@0", off), exp)["pass"]
    # a disc 2 px too wide at one decade: the radii no longer agree
    fr = kit.POWERS_FRAMES[5]
    wide = kit.paint_discs([(320.0, 180.0)], g["scale-powers"]["pixels"][fr] + 2.0, kit.PARITY[5 % 2])
    assert not kit.measure("scale-powers", with_frame(f"scale-powers@{fr}", wide), exp)["pass"]
    # a reported bar a part in 1e6 off, a wrong label, a wrong source and a run 3 px short
    bad = {k: [dict(v[0])] for k, v in stats.items()}
    bad["scale-bar@96"][0]["pixels"] *= 1.0 + 1e-6
    assert not kit.measure("scale-bar", frames, exp, stats=bad)["pass"]
    bad = {k: [dict(v[0])] for k, v in stats.items()}
    bad["scale-bar@960"][0]["label"] = "1 pc"
    assert not kit.measure("scale-bar", frames, exp, stats=bad)["pass"]
    bad = {k: [dict(v[0])] for k, v in stats.items()}
    bad["scale-bar-ortho@0"][0]["measured"] = "far"
    assert not kit.measure("scale-bar-ortho", frames, exp, stats=bad)["pass"]
    short = frames["scale-bar@480"].copy()
    short[1054:1056, 24 + 163:24 + 170] = 0
    assert not kit.measure("scale-bar", with_frame("scale-bar@480", short), exp, stats=stats)["pass"]
    # the far spheres a pixel off, and moving between frames
    shifted = np.roll(frames["scale-origin-far@0"], 1, axis=1)
    assert not kit.measure("scale-origin", with_frame("scale-origin-far@0", shifted), exp)["pass"]
    moved = with_frame("scale-origin-far@12", shifted)
    assert not kit.measure("scale-origin", moved, exp)["pass"]
    # a seek frame that differs by one pixel, and an invalid document the engine rendered
    played = frames["seek-played"].copy()
    played[10, 10] = (1, 1, 1)
    assert not kit.measure("scale-seek", with_frame("seek-played", played), exp)["pass"]
    rendered = dict(refusals)
    rendered["scale-invalid-sc3"] = None
    assert kit.measure("scale-invalid", frames, exp, refusals=rendered) == {
        "pass": False, "refused": 4, "sc1": "SC1", "sc2": "SC2", "sc3": "rendered", "sc4": "SC4", "v17": "V17"}


def _fake_engine(frames, stats, refuse=()):
    class Result:
        def __init__(self, code, err=""):
            self.returncode, self.stderr, self.stdout = code, err, ""

    def exec(cmd, capture_output, text):
        assert cmd[1] == "render"
        key = os.path.basename(cmd[2])[len("srep-0000-"):-len(".xml")]
        if key.startswith("scale-invalid-"):
            return Result(1, f"warning: a software adapter\nerror[{key[-3:].upper()}] (eye): refused\n")
        if key in refuse:
            return Result(1, f"error: {key} refused\n")
        target = cmd[cmd.index("-o") + 1]
        err = ""
        if "-f" in cmd:
            frame = int(cmd[cmd.index("-f") + 1])
            name = "seek-alone" if frame == kit.SEEK_FRAMES and key == "scale-powers" else f"{key}@{frame}"
            Image.fromarray(frames[name], "RGB").save(target)
            if "--stats" in cmd:
                err = _stats_line(frame, stats.get(f"{key}@{frame}", [])) + "\n"
        else:
            first, last = (int(v) for v in cmd[cmd.index("--frames") + 1].split("..="))
            assert (first, last) == (0, kit.SEEK_FRAMES) and key == "scale-powers"
            Image.fromarray(frames["seek-played"], "RGB").save(target % last)
        return Result(0, err)

    return exec


def test_the_kit_parses_an_engines_stats_lines():
    text = "warning: slow\n" + _stats_line(7, [{"camera": "eye", "measured": "far", "depth": 1e6, "pixels": 1.0,
                                                  "label": "1 m"}]) + "\nwrote x.png\n{not json\n"
    assert kit.parse_stats(text) == {7: [{"camera": "eye", "measured": "far", "depth": 1e6, "pixels": 1.0, "label": "1 m"}]}
    assert kit.parse_stats("") == {}


def test_the_kit_plans_single_frames_a_seek_run_and_refusals():
    plan = kit.plan()
    assert list(plan) == kit.NAMES
    assert plan["scale-depth"] == [("scale-depth", (0,), "single")]
    assert plan["scale-depth-log"] == [("scale-depth", (0,), "single"), ("scale-depth-log", (0,), "single")]
    assert plan["scale-bar"] == [("scale-bar", (0, 96, 480, 960), "single")]
    assert plan["scale-origin"] == [("scale-origin-here", (0,), "single"), ("scale-origin-far", (0, 12), "single")]
    assert plan["scale-seek"] == [("scale-powers", (960,), "seek")]
    assert plan["scale-invalid"] == [(f"scale-invalid-{c}", (0,), "refuse") for c in kit.INVALID]


def test_the_kit_runs_an_engine_and_reports_every_case(synthetic, tmp_path):
    exp, g, frames, stats, refusals = synthetic
    report = kit.run("scene-render", str(tmp_path / "kit"), exec=_fake_engine(frames, stats))
    assert list(report) == kit.NAMES and all(r["pass"] for r in report.values()), report
    assert os.path.exists(tmp_path / "kit" / "srep-0000-scale-invalid-v17.xml")
    lines = kit.table(report).splitlines()
    assert lines[0] == "| Case | Measured | Pass |" and len(lines) == 2 + len(kit.NAMES)
    assert all(line.endswith("| yes |") for line in lines[2:])
    report = kit.run("scene-render", str(tmp_path / "kit2"),
                     exec=_fake_engine(frames, stats, refuse=("scale-origin-far", "scale-powers")),
                     only=["scale-depth", "scale-origin", "scale-seek"])
    assert list(report) == ["scale-depth", "scale-origin", "scale-seek"]
    assert report["scale-depth"]["pass"] and not report["scale-origin"]["pass"] and not report["scale-seek"]["pass"]
    assert report["scale-origin"]["error"] == "scale-origin-far: error: scale-origin-far refused"
    assert report["scale-seek"]["error"] == "scale-powers: error: scale-powers refused"
    assert "| scale-seek | error scale-powers: error: scale-powers refused | no |" in kit.table(report)


def test_the_draft_describes_the_kit(draft):
    for phrase in ("`conformance/tools/scale_kit.py`", "`srep-<n>-scale-depth.xml`", "`sphere_pixels(r, d, focal)`",
                   "single-sided", "`--stats`", "19 pairs", "one part in 10⁴ farther", "2 × 10ᵏ", "48 + 48 k",
                   "2¹⁷ pixels apart", "frame 960 rendered alone", "`scale_bar(54, 200)`", "SC1", "V17"):
        assert phrase in draft, phrase
    assert "twenty concentric spheres" not in draft and "to be measured" not in draft


KIT_ROW = re.compile(r"^\| `srep-<n>-" + CASE + r"\.xml` \| (?:[^|]|\\\|)* \| ([^|]*) \|$")
ENGINE_COMMIT = "96b4a70"


def test_the_draft_records_every_kit_case_measured(draft):
    rows = {m.group(1): m.group(2) for m in (KIT_ROW.match(line) for line in draft.splitlines()) if m}
    assert sorted(rows) == sorted(kit.NAMES)
    prefix = f"measured on scene-render feat/sr-67-fields {ENGINE_COMMIT} (0.8.0, llvmpipe): "
    for name, status in rows.items():
        assert status.startswith(prefix) and status.endswith("; pass"), (name, status)
