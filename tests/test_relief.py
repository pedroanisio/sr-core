"""Tests for the draft SREP "Add relief layers to the map" (M1 of SREP 12) and its reference module."""
import importlib.util
import math
import os
import re
import shutil
import subprocess
import tempfile

import pytest

np = pytest.importorskip("numpy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "relief_reference.py")
TERRAIN = os.path.join(ROOT, "conformance", "tools", "terrain_grid_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-relief.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rl = _load(MODULE, "relief_reference")
tg = _load(TERRAIN, "terrain_grid_reference")


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _plane(n, ge, gn, size, h0=0.0):
    """An n x n height grid (row 0 north) with the gradient (ge, gn) in metres per metre at pixel size `size`."""
    j, i = np.mgrid[0:n, 0:n]
    return h0 + ge * i * size - gn * j * size


def _padded(h):
    return rl.pad_grid(h)


def _hillshade(**kw):
    paint = dict(rl.HILLSHADE_DEFAULTS)
    paint.update(kw)
    return paint


# ------------------------------------------------------------------------------------------------ encodings and world


def test_decode_agrees_with_the_terrain_grid_reference():
    for px in ((0, 0, 0), (128, 0, 0), (128, 1, 128), (255, 255, 255), (1, 134, 160)):
        for enc in ("terrarium", "mapbox"):
            assert _close(rl.decode(enc, px), tg.decode(enc, px), 1e-9)


def test_encode_inverts_decode_within_the_encoding_step():
    for h in (-32768.0, -1234.5, -0.25, 0.0, 12.75, 1000.0, 8848.0, 32767.0):
        assert _close(rl.decode("terrarium", rl.encode("terrarium", h)), h, 1 / 256 + 1e-9)
    for h in (-10000.0, -3.1, 0.0, 12.75, 8848.0, 100000.0):
        assert _close(rl.decode("mapbox", rl.encode("mapbox", h)), h, 0.05 + 1e-9)
    assert rl.encode("terrarium", 0.0) == (128, 0, 0)
    assert rl.encode("mapbox", 0.0) == (1, 134, 160)


def test_encode_array_and_decode_array_round_trip_a_signed_field():
    h = np.linspace(-500.0, 500.0, 64).reshape(8, 8)
    for enc in ("terrarium", "mapbox"):
        px = rl.encode_array(enc, h)
        assert px.shape == (8, 8, 3) and px.dtype == np.uint8
        back = rl.decode_array(enc, px)
        assert np.max(np.abs(back - h)) <= (1 / 256 if enc == "terrarium" else 0.05) + 1e-9


def test_the_encodings_carry_depths_below_sea_level():
    assert rl.decode("terrarium", rl.encode("terrarium", -4000.0)) < -3999
    assert rl.decode("mapbox", rl.encode("mapbox", -4000.0)) < -3999


def test_bad_encoding_is_refused():
    with pytest.raises(rl.ReliefError, match="RL3"):
        rl.decode("gray", (0, 0, 0))


def test_pixel_size_is_the_mercator_ground_size():
    assert _close(rl.pixel_size(0, 0.0), 2 * math.pi * rl.R / 256, 1e-6)
    assert _close(rl.pixel_size(1, 0.0), rl.pixel_size(0, 0.0) / 2, 1e-6)
    assert _close(rl.pixel_size(3, 60.0), rl.pixel_size(3, 0.0) * 0.5, 1e-6)


def test_world_pixel_and_lon_lat_invert_each_other():
    for z in (0, 1, 5):
        w = 256 * 2 ** z
        assert _close(rl.world_pixel(z, 0.0, 0.0), (w / 2, w / 2), 1e-6)
        assert _close(rl.world_pixel(z, -180.0, 0.0), (0.0, w / 2), 1e-6)
        for lon, lat in ((12.5, 41.9), (-73.9, 40.7), (179.0, -85.0)):
            px, py = rl.world_pixel(z, lon, lat)
            assert _close(rl.lon_lat(z, px, py), (lon, lat), 1e-6)


def test_row_latitude_is_the_latitude_at_the_row_centre():
    assert _close(rl.row_latitude(0, 127.5), 0.0, 1e-9)
    assert 84.9 < rl.row_latitude(0, 0) < rl.MERCATOR_LIMIT
    assert -rl.MERCATOR_LIMIT < rl.row_latitude(0, 255) < -84.9
    assert _close(rl.row_latitude(1, 255.5), 0.0, 1e-9)


def test_mosaic_zoom_is_the_raster_tile_zoom_clamped_to_the_archive():
    k = 512 / (2 * math.pi)  # zoom 0: a 512-pixel world, 256-pixel tiles give z_tile 1
    assert rl.mosaic_zoom(k, 0.0, 0, 8) == 1
    assert rl.mosaic_zoom(k * 2 ** 3.4, 0.0, 0, 8) == 4
    assert rl.mosaic_zoom(k * 2 ** 3.5, 0.0, 0, 8) == 5
    assert rl.mosaic_zoom(k, 2.0, 0, 8) == 3
    assert rl.mosaic_zoom(k, -3.0, 0, 8) == 0
    assert rl.mosaic_zoom(k * 2 ** 10, 0.0, 0, 4) == 4
    assert rl.mosaic_zoom(k, 0.0, 3, 8) == 3


def test_the_globe_mosaic_zoom_follows_the_drape_texture():
    assert rl.globe_mosaic_zoom(2048, 0.0, 0, 8) == 4   # a 4096-wide drape is the world at zoom 4
    assert rl.globe_mosaic_zoom(512, 0.0, 0, 8) == 2
    assert rl.globe_mosaic_zoom(512, 1.0, 0, 8) == 3
    assert rl.globe_mosaic_zoom(4096, 0.0, 0, 2) == 2


# --------------------------------------------------------------------------------------------------- archives and tiles


def _field_plane(px, py):
    return 0.5 * px - 0.25 * py


def test_a_synthetic_archive_holds_the_tiles_it_is_asked_for():
    a = rl.synthetic_archive(2, _field_plane, "mapbox", tiles=[(1, 1), (2, 1)])
    assert a.min_zoom == 2 and a.max_zoom == 2
    assert a.tile(2, 1, 1).shape == (256, 256, 3)
    assert a.tile(2, 0, 0) is None
    assert rl.decode("mapbox", tuple(a.tile(2, 1, 1)[0, 0])) == pytest.approx(_field_plane(256.5, 256.5), abs=0.06)


def test_heights_of_a_present_tile_decode_it():
    a = rl.synthetic_archive(1, _field_plane, "mapbox")
    h = rl.heights(a, "mapbox", 1, 1, 0)
    assert h.shape == (256, 256)
    assert h[3, 7] == pytest.approx(_field_plane(256 + 7.5, 3.5), abs=0.06)


def test_heights_of_a_missing_tile_come_from_the_parent_square_bilinearly():
    a = rl.synthetic_archive(1, _field_plane, "mapbox")
    a.max_zoom = 2
    h = rl.heights(a, "mapbox", 2, 3, 1)      # child of 1/1/0, its south-east quarter
    assert h.shape == (256, 256)
    # the parent's pixels at 2x: a plane stays a plane, at half the gradient per pixel
    assert h[0, 0] == pytest.approx(_field_plane(1 * 256 + 128.25, 128.25), abs=0.5)
    assert h[0, 1] - h[0, 0] == pytest.approx(0.25, abs=0.01)


def test_heights_of_a_tile_with_no_ancestor_are_zero():
    a = rl.synthetic_archive(1, _field_plane, "mapbox", tiles=[(0, 0)])
    assert np.all(rl.heights(a, "mapbox", 1, 1, 1) == 0.0)


def test_the_mosaic_stitches_tiles_and_borders_them_with_their_neighbours():
    a = rl.synthetic_archive(2, _field_plane, "mapbox")
    m = rl.mosaic(a, "mapbox", 2, 1, 1, 2, 1)
    assert m.z == 2 and m.x0 == 1 and m.y0 == 1
    assert m.h.shape == (256 + 2, 512 + 2)
    inner = m.h[1:-1, 1:-1]
    assert inner[0, 0] == pytest.approx(_field_plane(256.5, 256.5), abs=0.06)
    assert inner[0, 256] == pytest.approx(_field_plane(512.5, 256.5), abs=0.06)   # no step at the tile seam
    assert inner[0, 256] - inner[0, 255] == pytest.approx(0.5, abs=0.12)
    # the border columns are the neighbour tiles' edge columns
    assert m.h[1, 0] == pytest.approx(_field_plane(255.5, 256.5), abs=0.06)
    assert m.h[1, -1] == pytest.approx(_field_plane(768.5, 256.5), abs=0.06)
    assert m.h[0, 1] == pytest.approx(_field_plane(256.5, 255.5), abs=0.06)
    assert m.h[-1, 1] == pytest.approx(_field_plane(256.5, 512.5), abs=0.06)


def test_the_mosaic_wraps_across_the_antimeridian_and_extrapolates_the_poles():
    a = rl.synthetic_archive(1, lambda px, py: 100.0 * np.sin(2 * np.pi * px / 512.0) + py, "terrarium")
    m = rl.mosaic(a, "terrarium", 1, 0, 0, 2, 2)
    assert m.h.shape == (514, 514)
    assert m.h[1, 0] == pytest.approx(m.h[1, 512], abs=1 / 128)      # west border is the east edge
    assert m.h[1, 513] == pytest.approx(m.h[1, 1], abs=1 / 128)      # east border is the west edge
    assert np.allclose(m.h[0, :], 2 * m.h[1, :] - m.h[2, :])          # north border extrapolates the top rows
    assert np.allclose(m.h[513, :], 2 * m.h[512, :] - m.h[511, :])


def test_the_mosaic_is_bounded():
    a = rl.synthetic_archive(1, _field_plane, "mapbox", tiles=[(0, 0)])
    with pytest.raises(rl.ReliefError, match="RL6"):
        rl.mosaic(a, "mapbox", 1, 0, 0, 2, 2, limit=256)


# ------------------------------------------------------------------------------------------------------- the gradient


def test_pad_grid_extrapolates_the_edges_like_gdaldem():
    h = np.arange(9.0).reshape(3, 3)
    p = rl.pad_grid(h)
    assert p.shape == (5, 5)
    assert p[2, 0] == 2 * 3 - 4 and p[2, 4] == 2 * 5 - 4 and p[0, 2] == 2 * 1 - 4 and p[4, 2] == 2 * 7 - 4
    assert p[0, 0] == -4.0 and p[0, 4] == 0.0 and p[4, 0] == 8.0 and p[4, 4] == 12.0 and p[2, 2] == 4.0


def test_horn_gradient_of_a_plane_is_the_plane_s_gradient():
    size = 30.0
    h = _plane(9, 0.02, -0.05, size)
    ge, gn = rl.gradient(_padded(h), size)
    assert ge.shape == (9, 9)
    assert np.allclose(ge, 0.02, atol=1e-9)
    assert np.allclose(gn, -0.05, atol=1e-9)


def test_horn_gradient_weights_the_middle_row_twice():
    h = np.zeros((3, 3))
    h[:, 2] = [1.0, 2.0, 1.0]          # east column
    ge, gn = rl.gradient(h, 1.0)        # already a padded 3 x 3 window: one centre pixel
    assert ge.shape == (1, 1)
    assert ge[0, 0] == pytest.approx((1 + 2 * 2 + 1) / 8.0)
    assert gn[0, 0] == pytest.approx(0.0)


def test_the_gradient_takes_a_pixel_size_per_row():
    h = _plane(5, 0.1, 0.0, 1.0)
    sizes = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
    ge, gn = rl.gradient(_padded(h), sizes)
    assert np.allclose(ge[:, 2], 0.1 / sizes)


# -------------------------------------------------------------------------------------------------------- hillshades


def _cos_lambert(ge, gn, e, direction, altitude):
    pe, pn = 2 * e * ge, 2 * e * gn
    th, al = math.radians(direction), math.radians(altitude)
    return (math.sin(al) - math.cos(al) * (pe * math.sin(th) + pn * math.cos(th))) / math.sqrt(1 + pe * pe + pn * pn)


def test_basic_is_gdal_s_default_level_from_the_lambert_cosine():
    for ge, gn in ((0.0, 0.0), (0.3, -0.3), (-0.5, 0.2), (1.0, 1.0)):
        want = _cos_lambert(ge, gn, 0.5, 315.0, 45.0)
        level = rl.shade_level("basic", np.array([[ge]]), np.array([[gn]]), _hillshade(direction=(315.0,)))[0, 0]
        assert level == (1 if want <= 0 else int(math.floor(1 + 254 * want + 0.5)))


def test_flat_ground_levels_per_method():
    z = np.zeros((1, 1))
    p = _hillshade(direction=(315.0,))
    assert rl.shade_level("basic", z, z, p)[0, 0] == 181            # 1 + 254 sin 45
    assert rl.shade_level("multidirectional", z, z, p)[0, 0] == 181
    assert rl.shade_level("igor", z, z, p)[0, 0] == 255             # no slope, no shadow
    assert rl.shade_level("combined", z, z, p)[0, 0] == 255         # the slope term is zero


def test_a_slope_facing_the_light_is_brighter_than_one_facing_away():
    p = _hillshade(direction=(315.0,))
    toward = rl.shade_level("basic", np.array([[0.3]]), np.array([[-0.3]]), p)[0, 0]    # descends to the north-west
    away = rl.shade_level("basic", np.array([[-0.3]]), np.array([[0.3]]), p)[0, 0]
    assert toward > 181 > away
    for method in ("combined", "igor", "multidirectional"):
        t = rl.shade_level(method, np.array([[0.3]]), np.array([[-0.3]]), p)[0, 0]
        a = rl.shade_level(method, np.array([[-0.3]]), np.array([[0.3]]), p)[0, 0]
        assert t > a, method


def test_combined_follows_gdal_s_formula():
    ge, gn = 0.4, 0.1
    c = _cos_lambert(ge, gn, 0.5, 315.0, 45.0)
    slope = math.hypot(ge, gn)      # p = 2e grad with e = 0.5
    cang = 1 - math.acos(c) * math.atan(slope) * 4 / (math.pi ** 2)
    want = 1 if cang <= 0 else int(math.floor(1 + 254 * cang + 0.5))
    assert rl.shade_level("combined", np.array([[ge]]), np.array([[gn]]), _hillshade(direction=(315.0,)))[0, 0] == want


def test_igor_follows_gdal_s_formula():
    ge, gn = 0.4, 0.1
    slope_deg = math.degrees(math.atan(math.hypot(ge, gn)))
    aspect = math.atan2(-gn, -ge)
    target = 1.5 * math.pi - math.radians(315.0)
    diff = abs((aspect % (2 * math.pi)) - (target % (2 * math.pi)))
    if diff > math.pi:
        diff = 2 * math.pi - diff
    want = int(math.floor(255 * (1 - (slope_deg / 90.0) * (1 - diff / math.pi)) + 0.5))
    assert rl.shade_level("igor", np.array([[ge]]), np.array([[gn]]), _hillshade(direction=(315.0,)))[0, 0] == want


def test_multidirectional_is_the_usgs_weighting_of_four_lights():
    ge, gn = 0.4, 0.1
    x, y = -ge, gn          # GDAL's x is west minus east, its y north minus south
    al = math.radians(45.0)
    s, c = math.sin(al), math.cos(al)
    c225 = math.cos(math.radians(225.0))
    v225 = max(0.0, s + (x - y) * c225 * c)
    v270 = max(0.0, s - x * c)
    v315 = max(0.0, s + (x + y) * c225 * c)
    v360 = max(0.0, s - y * c)
    xx, yy = x * x, y * y
    w225 = 0.5 * (xx + yy) - x * y
    w270, w360 = xx, yy
    w315 = (xx + yy) - w225
    cang = (w225 * v225 + w270 * v270 + w315 * v315 + w360 * v360) / (xx + yy) / math.sqrt(1 + xx + yy)
    want = int(math.floor(1 + 127 * cang + 0.5))
    got = rl.shade_level("multidirectional", np.array([[ge]]), np.array([[gn]]), _hillshade())[0, 0]
    assert got == want
    # the lights are fixed: the direction does not change it
    assert rl.shade_level("multidirectional", np.array([[ge]]), np.array([[gn]]), _hillshade(direction=(90.0,)))[0, 0] == want


def test_exaggeration_scales_the_slope():
    ge, gn = np.array([[0.2]]), np.array([[-0.2]])
    half = rl.shade_level("basic", ge, gn, _hillshade(direction=(315.0,), exaggeration=0.25))[0, 0]
    one = rl.shade_level("basic", ge, gn, _hillshade(direction=(315.0,), exaggeration=0.5))[0, 0]
    two = rl.shade_level("basic", ge, gn, _hillshade(direction=(315.0,), exaggeration=1.0))[0, 0]
    assert half < one < two
    assert one == rl.shade_level("basic", ge / 2, gn / 2, _hillshade(direction=(315.0,), exaggeration=1.0))[0, 0]


def test_viewport_anchor_turns_the_light_with_the_map():
    ge, gn = np.array([[0.3]]), np.array([[0.0]])
    p = _hillshade(direction=(270.0,), anchor="viewport")
    unrotated = rl.shade_level("basic", ge, gn, p, rotation=0.0)[0, 0]
    rotated = rl.shade_level("basic", ge, gn, p, rotation=90.0)[0, 0]
    assert rotated == rl.shade_level("basic", ge, gn, _hillshade(direction=(180.0,), anchor="map"), rotation=90.0)[0, 0]
    assert rotated != unrotated
    fixed = _hillshade(direction=(270.0,), anchor="map")
    assert rl.shade_level("basic", ge, gn, fixed, rotation=90.0)[0, 0] == unrotated


def test_shade_colour_mixes_shadow_and_highlight_about_one_half():
    p = _hillshade(shadow=("#000000FF",), highlight=("#FFFFFFFF",))
    dark = rl.shade_colour(np.array([[1]]), "basic", p)[0, 0]
    flat = rl.shade_colour(np.array([[128]]), "basic", p)[0, 0]
    light = rl.shade_colour(np.array([[255]]), "basic", p)[0, 0]
    assert _close(tuple(dark), (0.0, 0.0, 0.0, 1.0), 1e-9)
    assert _close(tuple(flat), (0.0, 0.0, 0.0, 0.0), 1e-9)
    assert _close(tuple(light), (1.0, 1.0, 1.0, 1.0), 1e-9)
    half = rl.shade_colour(np.array([[192]]), "basic", p)[0, 0]          # s = 191/254
    s = 191 / 254
    assert _close(tuple(half), (2 * s - 1,) * 4, 1e-9)                 # premultiplied white at alpha 2s - 1
    red = _hillshade(shadow=("#FF0000FF",))
    assert _close(tuple(rl.shade_colour(np.array([[64]]), "basic", red)[0, 0]), (1 - 2 * 63 / 254, 0, 0, 1 - 2 * 63 / 254), 1e-9)


def test_igor_colour_is_the_two_term_mix():
    p = _hillshade(shadow=("#000000FF",), highlight=("#FFFFFFFF",), direction=(315.0,))
    ge, gn = np.array([[0.4]]), np.array([[0.1]])
    rgba = rl.hillshade_pixels("igor", ge, gn, p)[0, 0]
    slope_s = math.degrees(math.atan(math.hypot(0.4, 0.1))) / 90.0
    aspect = math.atan2(-0.1, -0.4)
    target = 1.5 * math.pi - math.radians(315.0)
    diff = abs((aspect % (2 * math.pi)) - (target % (2 * math.pi)))
    if diff > math.pi:
        diff = 2 * math.pi - diff
    aspect_s = 1 - diff / math.pi
    shadow, highlight = slope_s * aspect_s, slope_s * (1 - aspect_s)
    assert _close(tuple(rgba), (highlight, highlight, highlight, shadow + highlight), 1e-6)


def test_standard_is_maplibre_s_legacy_formula():
    p = _hillshade(direction=(335.0,), exaggeration=0.5)
    flat = rl.hillshade_pixels("standard", np.zeros((1, 1)), np.zeros((1, 1)), p)[0, 0]
    assert _close(tuple(flat), (0.0, 0.0, 0.0, 0.0), 1e-9)                      # no slope: nothing drawn
    ge, gn = 0.3, -0.2
    pe, pn = 2 * 0.5 * ge, -2 * 0.5 * gn                                      # MapLibre's y points south
    slope = math.atan(0.625 * math.hypot(pe, pn))
    aspect = math.atan2(pn, -pe)
    az = math.radians(335.0) + math.pi
    shade = abs(((aspect + az) / math.pi + 0.5) % 2.0 - 1.0)                 # e = 0.5: scaledSlope = slope
    k = math.sin(slope)                                                      # clamp(2e) = 1
    accent = (1 - math.cos(slope))                                           # black accent: alpha only
    want = (shade * k, shade * k, shade * k, accent * (1 - k) + k)
    got = rl.hillshade_pixels("standard", np.array([[ge]]), np.array([[gn]]), p)[0, 0]
    assert _close(tuple(got), want, 1e-6)


def test_standard_with_another_exaggeration_rescales_the_slope():
    p = _hillshade(direction=(335.0,), exaggeration=0.8)
    ge, gn = 0.3, -0.2
    pe, pn = 2 * 0.8 * ge, -2 * 0.8 * gn
    slope = math.atan(0.625 * math.hypot(pe, pn))
    base = 1.875 - 0.8 * 1.75
    scaled = ((base ** slope - 1) / (base ** (math.pi / 2) - 1)) * (math.pi / 2)
    got = rl.hillshade_pixels("standard", np.array([[ge]]), np.array([[gn]]), p)[0, 0]
    aspect = math.atan2(pn, -pe)
    shade = abs(((aspect + math.radians(335.0) + math.pi) / math.pi + 0.5) % 2.0 - 1.0)
    assert _close(got[0], shade * math.sin(scaled), 1e-6)


def test_unknown_method_is_refused():
    with pytest.raises(rl.ReliefError, match="RL4"):
        rl.shade_level("fancy", np.zeros((1, 1)), np.zeros((1, 1)), _hillshade())


def test_hillshade_of_a_plane_grid_is_uniform_inside():
    size = 50.0
    h = _plane(12, 0.1, 0.05, size)
    levels = rl.hillshade_levels(h, size, "basic", _hillshade(direction=(315.0,)))
    assert levels.shape == (12, 12)
    assert np.all(levels == levels[0, 0])


def test_signed_elevations_shade_like_positive_ones():
    size = 50.0
    above = _plane(8, 0.1, 0.05, size, h0=2000.0)
    below = _plane(8, 0.1, 0.05, size, h0=-6000.0)
    p = _hillshade(direction=(315.0,))
    for method in rl.METHODS:
        if method == "standard":
            continue
        assert np.array_equal(rl.hillshade_levels(above, size, method, p), rl.hillshade_levels(below, size, method, p))


def test_the_mosaic_shades_without_a_seam_across_the_antimeridian():
    a = rl.synthetic_archive(1, lambda px, py: 300.0 * np.sin(2 * np.pi * px / 512.0) + 0.0 * py, "terrarium")
    m = rl.mosaic(a, "terrarium", 1, 0, 0, 2, 2)
    levels = rl.mosaic_levels(m, "basic", _hillshade(direction=(270.0,)))
    assert levels.shape == (512, 512)
    row = levels[256]
    # the field is periodic: the shade at the wrap continues smoothly, as it does one pixel in
    assert abs(int(row[0]) - int(row[511])) <= abs(int(row[1]) - int(row[0])) + 1
    # and the same value is reached from both sides of the seam between the two tiles
    assert abs(int(row[256]) - int(row[255])) <= abs(int(row[257]) - int(row[256])) + 1
    # a cut mosaic (one tile only) would differ at its edge: the border holds real neighbour data
    cut = rl.mosaic(a, "terrarium", 1, 0, 0, 1, 2)
    assert np.array_equal(rl.mosaic_levels(cut, "basic", _hillshade(direction=(270.0,)))[256, :256], row[:256])


def test_mosaic_levels_use_the_row_s_ground_size():
    # the same height difference per pixel is a steeper slope nearer the poles, where pixels are smaller
    a = rl.synthetic_archive(2, lambda px, py: 0.2 * py, "mapbox")
    m = rl.mosaic(a, "mapbox", 2, 0, 0, 1, 4)
    ge, gn = rl.mosaic_gradient(m)
    assert gn.shape == (1024, 256)
    assert abs(gn[100, 10]) > abs(gn[512, 10]) * 2


@pytest.mark.skipif(shutil.which("gdaldem") is None, reason="gdaldem (GDAL) is not installed")
@pytest.mark.parametrize("method,flag", [("basic", []), ("combined", ["-combined"]), ("igor", ["-igor"]),
                                         ("multidirectional", ["-multidirectional"])])
def test_within_one_level_of_gdaldem_hillshade(method, flag):
    PIL = pytest.importorskip("PIL.Image")
    j, i = np.mgrid[0:48, 0:48]
    h = 120.0 * np.sin(i / 5.0) * np.cos(j / 7.0) + 2.0 * i - 3.0 * j
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "dem.tif")
        out = os.path.join(d, "shade.tif")
        PIL.fromarray(h[::-1].astype(np.float32), mode="F").save(src)     # rows flipped: GDAL's ungeoreferenced y is up
        subprocess.run(["gdaldem", "hillshade", src, out, "-z", "1", "-s", "1", "-az", "315", "-alt", "45",
                        "-compute_edges", *flag, "-q"], check=True)
        got = np.array(PIL.open(out))[::-1].astype(int)
    ours = rl.hillshade_levels(h, 1.0, method, _hillshade(direction=(315.0,))).astype(int)
    assert np.max(np.abs(ours[1:-1, 1:-1] - got[1:-1, 1:-1])) <= 1


# ------------------------------------------------------------------------------------------------------ colour relief


RAMP = ["interpolate", ["linear"], ["elevation"], -4000, "#000080", 0, "#0000FF", 0.001, "#008000", 1000, "#FFFF00",
        3000, "#FFFFFF"]


def test_colour_relief_stops_are_read_from_the_expression():
    stops, mode = rl.relief_stops(RAMP)
    assert mode == "interpolate"
    assert [s[0] for s in stops] == [-4000, 0, 0.001, 1000, 3000]
    assert stops[1][1] == (0, 0, 255, 255)
    step, mode = rl.relief_stops(["step", ["elevation"], "#0000FF", 0, "#008000", 1000, "#FFFFFF"])
    assert mode == "step"
    assert [s[0] for s in step] == [-math.inf, 0, 1000]


def test_colour_relief_interpolates_like_gdaldem():
    stops, mode = rl.relief_stops(RAMP)
    ratio = (500.0 - 0.001) / (1000 - 0.001)
    assert rl.relief_colour(stops, mode, 500.0) == (int(0.5 + 0 + ratio * 255), int(0.5 + 128 + ratio * (255 - 128)), 0, 255)
    assert rl.relief_colour(stops, mode, -5000.0) == (0, 0, 128, 255)       # clamped below
    assert rl.relief_colour(stops, mode, 9000.0) == (255, 255, 255, 255)    # clamped above
    assert rl.relief_colour(stops, mode, 0.0) == (0, 0, 255, 255)           # exact stop
    assert rl.relief_colour(stops, mode, -2000.0) == (0, 0, int(0.5 + 128 + 0.5 * 127), 255)


def test_colour_relief_step_takes_the_band_below():
    stops, mode = rl.relief_stops(["step", ["elevation"], "#0000FF", 0, "#008000", 1000, "#FFFFFF"])
    assert rl.relief_colour(stops, mode, -1.0) == (0, 0, 255, 255)
    assert rl.relief_colour(stops, mode, 0.0) == (0, 128, 0, 255)
    assert rl.relief_colour(stops, mode, 999.9) == (0, 128, 0, 255)
    assert rl.relief_colour(stops, mode, 1000.0) == (255, 255, 255, 255)


def test_colour_relief_of_a_grid_is_vectorised_and_takes_the_opacity():
    stops, mode = rl.relief_stops(RAMP)
    h = np.array([[500.0, -5000.0], [0.0, 9000.0]])
    rgba = rl.relief_pixels(h, stops, mode, opacity=0.5)
    assert rgba.shape == (2, 2, 4)
    c = rl.relief_colour(stops, mode, 500.0)
    assert _close(tuple(rgba[0, 0]), (c[0] / 255 * 0.5, c[1] / 255 * 0.5, 0.0, 0.5), 1e-6)   # premultiplied
    assert _close(tuple(rgba[1, 1]), (0.5, 0.5, 0.5, 0.5), 1e-6)


def test_colour_relief_expressions_are_checked():
    with pytest.raises(rl.ReliefError, match="RL5"):
        rl.relief_stops(["interpolate", ["linear"], ["zoom"], 0, "#000000", 1, "#FFFFFF"])
    with pytest.raises(rl.ReliefError, match="RL5"):
        rl.relief_stops(["interpolate", ["linear"], ["elevation"], 10, "#000000", 5, "#FFFFFF"])
    with pytest.raises(rl.ReliefError, match="RL5"):
        rl.relief_stops(["interpolate", ["linear"], ["elevation"]])
    with pytest.raises(rl.ReliefError, match="RL5"):
        rl.relief_stops("#FF0000")


@pytest.mark.skipif(shutil.which("gdaldem") is None, reason="gdaldem (GDAL) is not installed")
def test_within_one_level_of_gdaldem_color_relief():
    PIL = pytest.importorskip("PIL.Image")
    j, i = np.mgrid[0:32, 0:32]
    h = -800.0 + 90.0 * i + 25.0 * j
    stops, mode = rl.relief_stops(RAMP)
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "dem.tif")
        out = os.path.join(d, "relief.tif")
        ramp = os.path.join(d, "ramp.txt")
        PIL.fromarray(h[::-1].astype(np.float32), mode="F").save(src)
        with open(ramp, "w", encoding="utf-8") as f:
            for e, (r, g, b, a) in stops:
                f.write(f"{e} {r} {g} {b} {a}\n")
        subprocess.run(["gdaldem", "color-relief", src, ramp, out, "-alpha", "-q"], check=True)
        got = np.array(PIL.open(out).convert("RGBA"))[::-1].astype(int)
    ours = np.rint(rl.relief_pixels(h, stops, mode) * 255).astype(int)
    assert np.max(np.abs(ours - got)) <= 1


# ------------------------------------------------------------------------------------------------------ raster paint


def test_raster_defaults_leave_a_pixel_unchanged():
    px = np.array([[[0.2, 0.4, 0.6, 1.0]]])
    out = rl.raster_pixels(px, dict(rl.RASTER_DEFAULTS))
    assert np.allclose(out, px)


def test_raster_opacity_premultiplies():
    px = np.array([[[0.2, 0.4, 0.6, 1.0]]])
    out = rl.raster_pixels(px, dict(rl.RASTER_DEFAULTS, opacity=0.5))
    assert np.allclose(out, [[[0.1, 0.2, 0.3, 0.5]]])


def test_hue_rotation_by_120_degrees_cycles_the_channels():
    px = np.array([[[1.0, 0.0, 0.0, 1.0]]])
    out = rl.raster_pixels(px, dict(rl.RASTER_DEFAULTS, hueRotate=120.0))
    assert np.allclose(out[0, 0, :3], [0.0, 1.0, 0.0], atol=1e-9) or np.allclose(out[0, 0, :3], [0.0, 0.0, 1.0], atol=1e-9)
    w = rl.spin_weights(120.0)
    assert _close(tuple(w), ((2 * -0.5 + 1) / 3, (-math.sqrt(3) * math.sqrt(3) / 2 + 0.5 + 1) / 3,
                             (math.sqrt(3) * math.sqrt(3) / 2 + 0.5 + 1) / 3), 1e-9)


def test_saturation_minus_one_is_the_grey_average_and_the_factors_are_maplibre_s():
    px = np.array([[[0.9, 0.3, 0.3, 1.0]]])
    out = rl.raster_pixels(px, dict(rl.RASTER_DEFAULTS, saturation=-1.0))
    assert np.allclose(out[0, 0, :3], 0.5)
    assert rl.saturation_factor(0.5) == pytest.approx(1 - 1 / (1.001 - 0.5))
    assert rl.saturation_factor(-0.25) == 0.25
    assert rl.contrast_factor(0.5) == pytest.approx(2.0)
    assert rl.contrast_factor(-0.5) == pytest.approx(0.5)


def test_contrast_and_brightness_follow_the_shader():
    px = np.array([[[0.25, 0.5, 0.75, 1.0]]])
    out = rl.raster_pixels(px, dict(rl.RASTER_DEFAULTS, contrast=0.5))
    assert np.allclose(out[0, 0, :3], [0.0, 0.5, 1.0])
    out = rl.raster_pixels(px, dict(rl.RASTER_DEFAULTS, brightnessMin=0.2, brightnessMax=0.6))
    assert np.allclose(out[0, 0, :3], 0.2 + np.array([0.25, 0.5, 0.75]) * 0.4)


def test_raster_output_is_clamped_and_premultiplied_input_is_undone():
    px = np.array([[[0.4, 0.2, 0.1, 0.5]]])      # premultiplied: straight colour (0.8, 0.4, 0.2)
    out = rl.raster_pixels(px, dict(rl.RASTER_DEFAULTS, contrast=0.9))
    assert np.all(out >= 0.0) and np.all(out <= 1.0)
    assert out[0, 0, 3] == pytest.approx(0.5)
    plain = rl.raster_pixels(px, dict(rl.RASTER_DEFAULTS))
    assert np.allclose(plain, px)


def test_raster_resampling_is_nearest_or_linear():
    tile = np.zeros((2, 2, 4))
    tile[0, 0] = (1.0, 1.0, 1.0, 1.0)
    assert _close(tuple(rl.sample(tile, 0.75, 0.25, "nearest")), (1.0, 1.0, 1.0, 1.0), 1e-9)
    assert _close(tuple(rl.sample(tile, 1.0, 1.0, "linear")), (0.25, 0.25, 0.25, 0.25), 1e-9)
    with pytest.raises(rl.ReliefError, match="RL4"):
        rl.sample(tile, 0.5, 0.5, "cubic")


# ---------------------------------------------------------------------------------------------------------- contours


def test_contour_levels_are_base_plus_multiples_of_the_interval():
    assert rl.levels(-250.0, 420.0, 100.0, 0.0) == [-200.0, -100.0, 0.0, 100.0, 200.0, 300.0, 400.0]
    assert rl.levels(-250.0, 420.0, 100.0, 50.0) == [-250.0, -150.0, -50.0, 50.0, 150.0, 250.0, 350.0]
    assert rl.levels(5.0, 5.0, 100.0, 0.0) == []
    assert rl.levels(0.0, 1000.0, 100.0, 0.0, lo=250.0, hi=600.0) == [300.0, 400.0, 500.0, 600.0]


def test_too_many_levels_are_refused():
    with pytest.raises(rl.ReliefError, match="RL2"):
        rl.levels(0.0, 1e9, 1.0, 0.0)


def test_marching_squares_on_a_plane_puts_the_contour_where_it_belongs():
    h = _plane(8, 1.0, 0.0, 1.0)             # h = i (pixel column); the contour at 2.5 lies at x = 3.0 (centre + 0.5)
    lines = rl.marching_squares(h, 2.5)
    assert len(lines) == 1
    xs = [x for x, y in lines[0]]
    assert all(_close(x, 3.0, 1e-9) for x in xs)
    assert min(y for x, y in lines[0]) == pytest.approx(0.5) and max(y for x, y in lines[0]) == pytest.approx(7.5)


def test_a_vertex_on_the_level_counts_as_inside():
    h = _plane(4, 1.0, 0.0, 1.0)
    lines = rl.marching_squares(h, 2.0)      # the level equals the column 2 heights
    assert len(lines) == 1
    assert all(_close(x, 2.5, 1e-9) for x, y in lines[0])
    assert all(len(line) >= 2 for line in lines)


def test_a_cone_gives_rings_within_half_a_pixel():
    n = 64
    j, i = np.mgrid[0:n, 0:n]
    h = 1000.0 - 10.0 * np.hypot(i + 0.5 - n / 2, j + 0.5 - n / 2)
    for level in (900.0, 800.0, 700.0):
        lines = rl.marching_squares(h, level)
        assert len(lines) == 1
        line = lines[0]
        assert line[0] == line[-1]                                            # closed
        r = (1000.0 - level) / 10.0
        for x, y in line:
            assert abs(math.hypot(x - n / 2, y - n / 2) - r) <= 0.5


def test_saddles_are_resolved_by_the_cell_mean():
    h = np.array([[0.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 0.0]])
    high = rl.marching_squares(h, 0.4)        # the saddle cell's mean 0.5 is above the level: the highs join
    low = rl.marching_squares(h, 0.6)         # mean below: the highs are separate
    assert len(high) == 1 and len(low) == 2
    assert all(line[0] == line[-1] for line in high + low)


def test_contours_of_a_mosaic_are_in_lon_lat_and_cross_tile_seams():
    a = rl.synthetic_archive(2, lambda px, py: 0.5 * px, "mapbox")
    m = rl.mosaic(a, "mapbox", 2, 1, 1, 2, 1)
    out = rl.contours(m, 50.0, 0.0)
    assert set(out) == set(rl.levels(float(m.h.min()), float(m.h.max()), 50.0, 0.0))
    for level, lines in out.items():
        assert lines, level
        for line in lines:
            lons = [p[0] for p in line]
            assert max(lons) - min(lons) < 1e-6                                 # a vertical line
        lon0 = out[level][0][0][0]
        px, _ = rl.world_pixel(2, lon0, 0.0)
        assert px == pytest.approx(level / 0.5, abs=0.15)                     # where the field reaches the level
    # a level through the seam between the two tiles is one unbroken line
    seam_level = rl.levels(float(m.h.min()), float(m.h.max()), 50.0, 0.0)[len(out) // 2]
    assert len(out[seam_level]) == 1


def test_contours_wrap_across_the_antimeridian_and_are_split_there():
    a = rl.synthetic_archive(1, lambda px, py: 100.0 * np.cos(2 * np.pi * px / 512.0) + 0.3 * py, "terrarium")
    m = rl.mosaic(a, "terrarium", 1, 0, 0, 2, 2)
    out = rl.contours(m, 50.0, 0.0)
    lines = out[150.0]
    assert len(lines) >= 2                                                    # cut at the antimeridian
    for line in lines:
        for lon, lat in line:
            assert -180.0 <= lon <= 180.0
    # the ridge at px = 0 (lon -180) and px = 512 (lon 180): the contour pieces at both edges exist
    edges = [p for line in lines for p in line if abs(abs(p[0]) - 180.0) < 1e-6]
    assert edges


def test_index_contours_are_every_nth_level():
    assert rl.is_index(500.0, 100.0, 0.0, 5) is True
    assert rl.is_index(400.0, 100.0, 0.0, 5) is False
    assert rl.is_index(0.0, 100.0, 0.0, 5) is True
    assert rl.is_index(-500.0, 100.0, 0.0, 5) is True
    assert rl.is_index(550.0, 100.0, 50.0, 5) is True


@pytest.mark.skipif(shutil.which("gdal_contour") is None, reason="gdal_contour (GDAL) is not installed")
def test_within_half_a_pixel_of_gdal_contour():
    import json
    PIL = pytest.importorskip("PIL.Image")
    n = 40
    j, i = np.mgrid[0:n, 0:n]
    h = 500.0 + 80.0 * np.sin(i / 4.0) * np.cos(j / 6.0) + 3.0 * i
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "dem.tif")
        out = os.path.join(d, "contours.json")
        PIL.fromarray(h.astype(np.float32), mode="F").save(src)
        subprocess.run(["gdal_contour", "-i", "50", "-off", "0", "-a", "level", "-f", "GeoJSON", src, out, "-q"],
                       check=True)
        with open(out, encoding="utf-8") as f:
            features = json.load(f)["features"]
    theirs = {}
    for ft in features:
        geom = ft["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        theirs.setdefault(float(ft["properties"]["level"]), []).extend(parts)
    for level in rl.levels(float(h.min()), float(h.max()), 50.0, 0.0):
        ours = rl.marching_squares(h, level)
        segs = [(a, b) for part in theirs.get(level, []) for a, b in zip(part, part[1:])]
        assert segs, level
        for line in ours:
            for x, y in line:
                assert min(rl.point_segment_distance((x, y), a, b) for a, b in segs) <= 0.5, (level, x, y)


def test_point_segment_distance():
    assert rl.point_segment_distance((0.0, 1.0), (0.0, 0.0), (2.0, 0.0)) == pytest.approx(1.0)
    assert rl.point_segment_distance((3.0, 0.0), (0.0, 0.0), (2.0, 0.0)) == pytest.approx(1.0)
    assert rl.point_segment_distance((1.0, 0.0), (1.0, 0.0), (1.0, 0.0)) == pytest.approx(0.0)


# ----------------------------------------------------------------------------------------------------------- the globe


def test_globe_rows_clamp_beyond_the_mercator_limit():
    z = 2
    n = 256 * 2 ** z
    assert rl.globe_row(z, 0.0) == pytest.approx(n / 2 - 0.5)
    assert rl.globe_row(z, 89.0) == 0.0
    assert rl.globe_row(z, -90.0) == n - 1.0
    assert 0.0 < rl.globe_row(z, 80.0) < n / 2


def test_the_globe_drape_samples_the_world_mosaic_by_latitude():
    a = rl.synthetic_archive(1, lambda px, py: 0.0 * px + py, "terrarium")
    m = rl.mosaic(a, "terrarium", 1, 0, 0, 2, 2)
    T = 64
    d = rl.globe_drape_heights(m, T)
    assert d.shape == (T, 2 * T)
    assert np.all(d[0] == d[0, 0])                 # one row has one latitude: one height for a py-only field
    assert d[0, 0] <= d[1, 0] <= d[T - 1, 0]       # north pole row to south pole row, heights increase with py
    assert d[0, 0] == pytest.approx(0.5, abs=0.01) # the top row is clamped to the first mosaic row (py 0.5)
    _, py = rl.world_pixel(1, 0.0, 90.0 - (T // 2 + 0.5) * 180.0 / T)
    assert d[T // 2, 0] == pytest.approx(py, abs=0.02)      # a py-only field read bilinearly is exact


def test_the_globe_drape_wraps_in_longitude():
    a = rl.synthetic_archive(1, lambda px, py: 100.0 * np.sin(2 * np.pi * px / 512.0) + 0.0 * py, "terrarium")
    m = rl.mosaic(a, "terrarium", 1, 0, 0, 2, 2)
    d = rl.globe_drape_heights(m, 64)
    for u in (0, 1, 126, 127):
        px = ((u + 0.5) / 128 * 360.0) / 360.0 * 512.0
        assert d[32, u] == pytest.approx(100.0 * math.sin(2 * math.pi * px / 512.0), abs=0.2), u


# ------------------------------------------------------------------------------------------------- the whole document


def test_the_example_document_runs_and_its_summary_is_stable():
    doc = rl.example_document()
    out = rl.run(doc)
    assert [o["kind"] for o in out] == ["basemap", "contours"]
    base = out[0]
    assert base["zoom"] == 6 and base["tiles"] == (2, 2)
    assert set(base["layers"]) == {"raster", "hillshade", "color-relief"}
    assert 1 <= base["layers"]["hillshade"]["mean"] <= 255
    assert base["layers"]["hillshade"]["levels"][0] < 150 < 210 < base["layers"]["hillshade"]["levels"][1]
    assert base["layers"]["color-relief"]["digest"] == rl.digest(base["layers"]["color-relief"]["pixels"])
    cont = out[1]
    assert cont["levels"] >= 3 and cont["vertices"] > 0
    assert rl.run(doc) == out


def test_the_example_document_is_valid_and_the_bad_one_lists_every_code():
    assert rl.validate_document(rl.example_document()) == []
    assert rl.validate_document(rl.bad_document()) == ["RL1", "RL2", "RL3", "RL4", "RL5", "V17"]


def test_validation_one_at_a_time():
    def doc_with(child_edit=None, layer_edit=None):
        doc = rl.example_document()
        if child_edit:
            child_edit(doc)
        if layer_edit:
            layer_edit(doc["map"]["children"][0]["style"])
        return doc

    def set_contours(key, value):
        def edit(doc):
            doc["map"]["children"][1][key] = value
        return edit

    def set_basemap(key, value):
        def edit(doc):
            doc["map"]["children"][0][key] = value
        return edit

    assert rl.validate_document(doc_with(set_contours("elevation", "nowhere"))) == ["RL1"]
    assert rl.validate_document(doc_with(set_contours("interval", 0.0))) == ["RL2"]
    assert rl.validate_document(doc_with(set_contours("index", 0))) == ["RL2"]
    assert rl.validate_document(doc_with(set_contours("encoding", "gray16"))) == ["RL3"]
    assert rl.validate_document(doc_with(set_basemap("encoding", "png"))) == ["RL3"]

    def bad_method(style):
        style[1]["paint"]["hillshade-method"] = "shiny"

    def bad_arrays(style):
        style[1]["paint"]["hillshade-illumination-direction"] = [315, 45]
        style[1]["paint"]["hillshade-illumination-altitude"] = [45]

    def bad_altitude(style):
        style[1]["paint"]["hillshade-illumination-altitude"] = [95]

    def bad_ramp(style):
        style[2]["paint"]["color-relief-color"] = ["interpolate", ["linear"], ["zoom"], 0, "#000000", 1, "#FFFFFF"]

    def bad_resampling(style):
        style[0]["paint"]["raster-resampling"] = "cubic"

    assert rl.validate_document(doc_with(layer_edit=bad_method)) == ["RL4"]
    assert rl.validate_document(doc_with(layer_edit=bad_arrays)) == ["RL4"]
    assert rl.validate_document(doc_with(layer_edit=bad_altitude)) == ["RL4"]
    assert rl.validate_document(doc_with(layer_edit=bad_resampling)) == ["RL4"]
    assert rl.validate_document(doc_with(layer_edit=bad_ramp)) == ["RL5"]
    assert rl.validate_document(doc_with(set_contours("smooth", True))) == ["V17"]


def test_relief_layers_on_a_basemap_without_elevation_warn_and_are_skipped():
    doc = rl.example_document()
    del doc["map"]["children"][0]["elevation"]
    assert rl.validate_document(doc) == []
    assert rl.warnings(doc) == ["W-RL1"]
    out = rl.run(doc)
    assert set(out[0]["layers"]) == {"raster"}


def test_the_paint_is_read_with_maplibre_defaults():
    p = rl.hillshade_paint({})
    assert p == rl.HILLSHADE_DEFAULTS
    p = rl.hillshade_paint({"hillshade-illumination-direction": 300, "hillshade-shadow-color": "#102030"})
    assert p["direction"] == (300.0,) and p["shadow"] == ("#102030FF",)
    p = rl.hillshade_paint({"hillshade-illumination-direction": [300, 60], "hillshade-illumination-altitude": [30, 50],
                            "hillshade-shadow-color": ["#000000", "#111111"], "hillshade-highlight-color": ["#fff", "#eee"]})
    assert p["direction"] == (300.0, 60.0) and len(p["shadow"]) == 2
    r = rl.raster_paint({"raster-opacity": 0.5, "raster-hue-rotate": 400})
    assert r["opacity"] == 0.5 and r["hueRotate"] == 40.0
    assert rl.relief_paint({"color-relief-opacity": 0.25, "color-relief-color": RAMP})["opacity"] == 0.25


def test_constants_and_defaults():
    assert rl.METHODS == ("standard", "basic", "combined", "igor", "multidirectional")
    assert rl.ENCODINGS == ("terrarium", "mapbox")
    assert rl.RESAMPLINGS == ("linear", "nearest")
    assert rl.HILLSHADE_DEFAULTS["direction"] == (335.0,) and rl.HILLSHADE_DEFAULTS["altitude"] == (45.0,)
    assert rl.HILLSHADE_DEFAULTS["exaggeration"] == 0.5 and rl.HILLSHADE_DEFAULTS["method"] == "standard"
    assert rl.HILLSHADE_DEFAULTS["anchor"] == "viewport"
    assert rl.RASTER_DEFAULTS == {"opacity": 1.0, "hueRotate": 0.0, "brightnessMin": 0.0, "brightnessMax": 1.0,
                                  "saturation": 0.0, "contrast": 0.0, "resampling": "linear"}
    assert rl.CONTOURS_DEFAULTS["interval"] == 100.0 and rl.CONTOURS_DEFAULTS["index"] == 5
    assert rl.CONTOURS_DEFAULTS["encoding"] == "terrarium" and rl.CONTOURS_DEFAULTS["strokeWidth"] == 0.5
    assert rl.CONTOURS_DEFAULTS["indexStrokeWidth"] == 1.0 and rl.CONTOURS_DEFAULTS["detail"] == 0.0
    assert rl.BASEMAP_RELIEF_DEFAULTS == {"elevation": None, "encoding": "terrarium"}
    assert rl.MAX_LEVELS == 4096 and rl.MAX_MOSAIC == 8192
    assert rl.R == 6378137.0 and rl.TILE == 256
    assert rl.MERCATOR_LIMIT == pytest.approx(85.0511287798, abs=1e-9)


# ---------------------------------------------------------------------------------------------------------- the draft


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
    for word in ("SR-112", "SREP 9", "SREP 10", "SREP 12", "SREP 14", "`raster`", "`hillshade`", "`color-relief`",
                 "`contours`", "`basemap`", "`elevation`", "`encoding`", "terrarium", "mapbox", "`interval`", "`base`",
                 "`index`", "`stroke`", "`strokeWidth`", "`indexStroke`", "`indexStrokeWidth`", "`opacity`", "`detail`",
                 "`minLevel`", "`maxLevel`", "hillshade-method", "standard", "basic", "combined", "igor",
                 "multidirectional", "hillshade-illumination-direction", "hillshade-illumination-altitude",
                 "hillshade-illumination-anchor", "hillshade-exaggeration", "hillshade-shadow-color",
                 "hillshade-highlight-color", "hillshade-accent-color", "color-relief-color", "color-relief-opacity",
                 "raster-opacity", "raster-hue-rotate", "raster-brightness-min", "raster-brightness-max",
                 "raster-saturation", "raster-contrast", "raster-resampling", "Horn", "gdaldem", "gdal_contour",
                 "GDAL", "MapLibre", "MIT", "BSD-3", "marching squares", "saddle", "antimeridian", "pole",
                 "bathymetry", "signed", "globe", "drape", "mosaic", "RL1", "RL2", "RL3", "RL4", "RL5", "RL6",
                 "W-RL1", "V17", "relief_reference.py", "numpy", "USGS", "Lambert", "within 1 level", "0.5 px",
                 "seam", "6378137", "85.0511"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 20
    assert len(rl.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in rl.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = rl.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert rl._same(value, want), (name, value, want)
