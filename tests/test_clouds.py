"""Tests for the draft SREP "Add cloud layers and the night sky" (A3 of SREP 12) and its reference module."""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "clouds_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-clouds.md")


def _load():
    spec = importlib.util.spec_from_file_location("clouds_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cl = _load()
rs = cl.streams()
wd = cl.wind()
md = cl.media()
ps = cl.sky()


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------------------- seeds and noises


def test_element_seed_uses_the_clouds_purpose():
    assert cl.element_seed(7, "c1", 5) == rs.E(7, "c1", 5, "clouds")
    assert cl.example_seed() == cl.element_seed(7, "c1", 5)


def test_remap_is_the_clamped_linear_remap():
    assert cl.remap(0.5, 0.0, 1.0, 0.0, 2.0) == 1.0
    assert cl.remap(0.25, 0.5, 1.0, 0.0, 1.0) == 0.0          # below the input range clamps
    assert cl.remap(2.0, 0.5, 1.0, 0.0, 1.0) == 1.0
    assert _close(cl.remap(0.75, 0.5, 1.0, 0.0, 1.0), 0.5)
    with pytest.raises(cl.CloudError):
        cl.remap(0.5, 1.0, 1.0, 0.0, 1.0)


def test_value_fbm_is_the_wind_drafts_value_noise_on_the_base_channel_mapped_to_unit():
    e = cl.example_seed()
    q = (0.37, 0.53, 0.11)
    one = cl.value_fbm(e, q, 1)
    assert _close(one, (wd.value3(e, cl.BASE_VALUE * cl.OCTAVE_STRIDE, *q)[0] + 1.0) / 2.0)
    for n in (1, 2, 3):
        assert 0.0 <= cl.value_fbm(e, q, n) <= 1.0
    with pytest.raises(cl.CloudError):
        cl.value_fbm(e, q, 0)


def test_worley_feature_points_sit_inside_their_cells_and_f1_is_the_nearest():
    e = cl.example_seed()
    f = cl.feature_point(e, cl.BASE_WORLEY, 2, -1, 3)
    assert 2.0 <= f[0] < 3.0 and -1.0 <= f[1] < 0.0 and 3.0 <= f[2] < 4.0
    # the F1 distance at the feature point itself is zero
    assert cl.worley_f1(e, cl.BASE_WORLEY, f) == 0.0
    # F1 is at most 1 (clamped) and the inverted noise is in [0, 1]
    for q in ((0.2, 0.3, 0.4), (5.5, -2.2, 1.1), (-7.9, 0.0, 3.3)):
        d = cl.worley_f1(e, cl.BASE_WORLEY, q)
        assert 0.0 <= d <= 1.0
        assert 0.0 <= cl.worley_fbm(e, cl.BASE_WORLEY, q, 3) <= 1.0
    # one octave is the inverted F1
    q = (0.2, 0.3, 0.4)
    assert _close(cl.worley_fbm(e, cl.BASE_WORLEY, q, 1), 1.0 - cl.worley_f1(e, cl.BASE_WORLEY, q))
    with pytest.raises(cl.CloudError):
        cl.worley_fbm(e, cl.BASE_WORLEY, q, 4)


def test_base_shape_dilates_the_value_noise_by_the_worley_billows():
    e = cl.example_seed()
    for q in ((0.2, 0.3, 0.4), (5.5, -2.2, 1.1), (-7.9, 0.0, 3.3), (12.25, 1.5, -4.75)):
        b = cl.base_shape(e, q, 3)
        assert 0.0 <= b <= 1.0
        v = cl.value_fbm(e, q, 3)
        w = cl.worley_fbm(e, cl.BASE_WORLEY, q, 3)
        assert _close(b, cl.remap(v, w - 1.0, 1.0, 0.0, 1.0))


# ------------------------------------------------------------------------------------- the layer's shape


def test_height_gradients_are_the_three_presets_blended_by_the_type():
    assert set(cl.PRESETS) == {"stratus", "stratocumulus", "cumulus"}
    for name, (a, b, c, d) in cl.PRESETS.items():
        assert 0.0 <= a < b <= c < d <= 1.0
        assert cl.band(0.0, a, b, c, d) == 0.0 and cl.band(1.0, a, b, c, d) == 0.0 or d == 1.0
        assert _close(cl.band((b + c) / 2.0, a, b, c, d), 1.0)
    h = 0.5
    assert _close(cl.height_gradient(h, 0.0), cl.band(h, *cl.PRESETS["stratus"]))
    assert _close(cl.height_gradient(h, 0.5), cl.band(h, *cl.PRESETS["stratocumulus"]))
    assert _close(cl.height_gradient(h, 1.0), cl.band(h, *cl.PRESETS["cumulus"]))
    mid = (cl.band(h, *cl.PRESETS["stratus"]) + cl.band(h, *cl.PRESETS["stratocumulus"])) / 2.0
    assert _close(cl.height_gradient(h, 0.25), mid)
    # stratus is thin and low, cumulus tall
    assert cl.height_gradient(0.8, 0.0) == 0.0 and cl.height_gradient(0.8, 1.0) > 0.5
    assert cl.height_gradient(-0.1, 0.5) == 0.0 and cl.height_gradient(1.1, 0.5) == 0.0


def test_weather_is_uniform_or_read_from_the_map_and_precipitation_makes_cumulonimbus():
    doc = cl.example_document()
    layer = cl.example_layer()
    assert cl.weather_at(layer, doc, (100.0, 200.0), 0.0) == (0.5, 0.0, 0.5)
    mapped = cl.mapped_document()
    ml = mapped["lights"][0]["cloudLayers"][0]
    # the map's pixel (0, 0) is (255, 0, 0): full coverage, stratus; pixel (1, 0) is (0, 0, 255): cumulus, no cover
    w00 = cl.weather_at(ml, mapped, (0.0, 0.0), 0.0)
    assert _close(w00, (1.0, 0.0, 0.0))
    w10 = cl.weather_at(ml, mapped, (ml["weatherScale"] / 2.0, 0.0), 0.0)
    assert _close(w10, (0.0, 0.0, 1.0))
    # bilinear between them
    w = cl.weather_at(ml, mapped, (ml["weatherScale"] / 4.0, 0.0), 0.0)
    assert _close(w, (0.5, 0.0, 0.5))
    # the map tiles
    assert _close(cl.weather_at(ml, mapped, (ml["weatherScale"], 0.0), 0.0), w00)
    # precipitation: coverage at least 0.7 p and the type toward cumulonimbus (1)
    assert _close(cl.effective_weather((0.2, 1.0, 0.3)), (0.7, 1.0, 1.0))
    assert _close(cl.effective_weather((0.9, 0.5, 0.0)), (0.9, 0.5, 0.5))
    assert cl.effective_weather((0.4, 0.0, 0.6)) == (0.4, 0.0, 0.6)


def test_the_wind_carries_the_weather_map_and_the_noise():
    mapped = cl.mapped_document()
    ml = mapped["lights"][0]["cloudLayers"][0]
    # the example wind blows 6 m/s toward 30 degrees: after 100 s the pattern has moved 600 m along it
    d = wd.displacement(mapped["physics"]["winds"][0], 100.0, 24)
    p = (1234.0, 567.0)
    assert _close(cl.weather_at(ml, mapped, (p[0] + d[0], p[1] + d[1]), 100.0), cl.weather_at(ml, mapped, p, 0.0), 1e-9)
    q0 = cl.lattice_point(ml, mapped, cl.point(1000.0, 3000.0, 2500.0), 0.0)
    q1 = cl.lattice_point(ml, mapped, cl.point(1000.0 + d[0], 3000.0 + d[1], 2500.0), 100.0)
    assert _close(q0, q1, 1e-9)
    assert _close(q0, (1000.0 / ml["scale"], 3000.0 / ml["scale"], 2500.0 / ml["scale"]), 1e-9)
    # without a wind nothing moves
    still = cl.example_document()
    sl = still["lights"][0]["cloudLayers"][0]
    p = cl.point(1000.0, 3000.0, 2500.0)
    assert cl.lattice_point(sl, still, p, 100.0) == cl.lattice_point(sl, still, p, 0.0)


def test_coverage_follows_the_weather_map_by_the_calibrated_threshold():
    doc = cl.example_document()
    layer = cl.example_layer()
    e = cl.example_seed()
    cal = cl.calibration(layer, e)
    assert len(cal) == cl.CALIBRATION_POINTS ** 2 and cal == sorted(cal)
    assert cl.threshold(layer, e, 1.0) <= cal[0] and cl.threshold(layer, e, 0.0) >= cal[-1]
    for c in (0.2, 0.5, 0.8):
        layer_c = dict(layer, coverage=c)
        doc_c = cl.example_document()
        doc_c["lights"][0]["cloudLayers"][0] = layer_c
        f = cl.covered_fraction(layer_c, doc_c, e, 0.0, 40)
        assert abs(f - c) < 0.04, (c, f)
    assert cl.covered_fraction(dict(layer, coverage=0.0), doc, e, 0.0, 16) == 0.0


def test_density_is_zero_outside_the_shell_and_scales_with_the_gradient_and_the_erosion():
    doc = cl.example_document()
    layer = cl.example_layer()
    e = cl.example_seed()
    mid = layer["base"] + 0.5 * layer["thickness"]
    below = cl.point(500.0, 500.0, layer["base"] - 1.0)
    above = cl.point(500.0, 500.0, layer["base"] + layer["thickness"] + 1.0)
    assert cl.density_at(layer, doc, e, below, 0.0) == 0.0 and cl.density_at(layer, doc, e, above, 0.0) == 0.0
    # somewhere in the core the density is positive and at most 1
    vals = [cl.density_at(layer, doc, e, cl.point(float(x), float(y), mid), 0.0)
            for x in range(0, 20000, 1000) for y in range(0, 20000, 1000)]
    assert 0.0 < max(vals) <= 1.0 and min(vals) == 0.0
    # erosion only lowers the density
    no_detail = dict(layer, detail=0.0)
    for x in range(0, 20000, 2500):
        p = cl.point(float(x), 3000.0, mid)
        assert cl.density_at(layer, doc, e, p, 0.0) <= cl.density_at(no_detail, doc, e, p, 0.0) + 1e-12
    # the extinction and the albedo under rain
    assert cl.extinction(layer, 0.5, 0.0) == 0.5 * layer["density"]
    assert cl.extinction(layer, 0.5, 1.0) == layer["density"]
    assert _close(cl.effective_albedo(layer, 0.0), layer["albedo"]) and cl.effective_albedo(layer, 1.0) < layer["albedo"]


def test_the_shell_is_a_spherical_layer_above_the_planet():
    layer = cl.example_layer()
    r = cl.PLANET_RADIUS
    assert _close(cl.altitude((0.0, 0.0, r)), 0.0)
    assert _close(cl.altitude((0.0, 0.0, r + 2000.0)), 2000.0)
    # a point of the tangent plane 20 km out is above the curved ground
    assert _close(cl.altitude((20000.0, 0.0, r)), math.sqrt(r * r + 20000.0 ** 2) - r, 1e-6)
    p = cl.point(1000.0, -2000.0, 2500.0)
    assert _close(cl.altitude(p), 2500.0, 1e-6)
    assert _close(cl.map_point(p), (1000.0, -2000.0), 1e-6)
    assert _close(cl.up(p), (p[0] / (r + 2500.0), p[1] / (r + 2500.0), p[2] / (r + 2500.0)), 1e-12)
    assert _close(cl.height_fraction(layer, cl.point(0.0, 0.0, layer["base"])), 0.0, 1e-9)
    assert _close(cl.height_fraction(layer, cl.point(0.0, 0.0, layer["base"] + layer["thickness"])), 1.0, 1e-9)
    with pytest.raises(cl.CloudError):
        cl.point(r, r, 0.0)


def test_optical_depth_and_transmittance_through_the_layer():
    doc = cl.example_document()
    layer = dict(cl.example_layer(), coverage=1.0, detail=0.0)
    e = cl.example_seed()
    origin = cl.point(3000.0, 3000.0, 0.0)
    zenith = cl.up(origin)
    tau = cl.optical_depth(layer, doc, e, origin, zenith, 0.0, 64)
    assert tau > 0.0
    assert _close(cl.transmittance_along(layer, doc, e, origin, zenith, 0.0, 64), math.exp(-tau))
    # the ray crosses the shell once, over the layer's thickness
    assert cl.shell_segments(layer, origin, zenith) == [(pytest.approx(layer["base"], abs=1e-3),
                                                          pytest.approx(layer["base"] + layer["thickness"], abs=1e-3))]
    # a horizontal ray below the layer sees nothing within the range
    low = cl.point(0.0, 0.0, 100.0)
    assert cl.shell_segments(layer, low, (1.0, 0.0, 0.0)) == []
    assert cl.optical_depth(layer, doc, e, low, (1.0, 0.0, 0.0), 0.0, 32) == 0.0
    with pytest.raises(cl.CloudError):
        cl.optical_depth(layer, doc, e, origin, zenith, 0.0, 0)


# ----------------------------------------------------------------------------------------------- lighting


def test_phase_functions_normalise():
    for d in (5.0, 10.0, 20.0, 50.0):
        assert abs(cl.phase_normalisation(d) - 1.0) < 1e-3, d
    assert abs(cl.phase_normalisation_hg(0.8) - 1.0) < 1e-6
    # the forward peak dominates; the Draine lobe gives the fog bow, a backscatter above the side scattering
    assert cl.phase(1.0, 20.0) > cl.phase(-1.0, 20.0) > cl.phase(0.0, 20.0)
    assert cl.phase(0.3, 20.0) == md.phase_fog(0.3, 20.0)
    with pytest.raises(ValueError):
        cl.phase(0.3, 2.0)


def test_beer_powder_and_the_multiple_scattering_octaves():
    assert cl.powder(0.0) == 0.0 and _close(cl.powder(10.0), 1.0, 1e-8)
    assert _close(cl.beer_powder(0.0), 0.0)
    # the Beer-powder product peaks inside the cloud, not at its surface
    taus = [i / 100.0 for i in range(1, 400)]
    peak = max(taus, key=cl.beer_powder)
    assert 0.3 < peak < 0.8
    assert _close(cl.beer_powder(peak), 2.0 * math.exp(-peak) * (1.0 - math.exp(-2.0 * peak)))
    # one octave is Beer times the phase; three octaves add two dimmer, wider, less attenuated lobes
    one = cl.multi_scatter(1.0, 0.5, 20.0, 1)
    assert _close(one, math.exp(-1.0) * cl.phase(0.5, 20.0))
    three = cl.multi_scatter(1.0, 0.5, 20.0, 3)
    assert three > one
    want = sum(0.5 ** k * math.exp(-(0.5 ** k) * 1.0) * cl.phase_scaled(0.5, 20.0, 0.5 ** k) for k in range(3))
    assert _close(three, want)
    assert cl.phase_scaled(0.5, 20.0, 1.0) == cl.phase(0.5, 20.0)
    assert cl.ambient_weight(0.0) < cl.ambient_weight(1.0) == 1.0


# -------------------------------------------------------------------------------------------- the night sky


def test_moon_irradiance_follows_lommel_seeliger_with_earthshine():
    d = 384400.0
    full = cl.moon_irradiance(0.0, d, earthshine=False)
    want = 2.0 * cl.MOON_ALBEDO * (cl.MOON_RADIUS_KM / d) ** 2 / 3.0 * cl.E_SUN
    assert _close(full, want, 1e-12)
    # the phase law falls with the phase angle and vanishes at new moon
    assert cl.phase_law(0.0) == 1.0
    assert cl.phase_law(90.0) < cl.phase_law(45.0) < 1.0
    assert abs(cl.phase_law(180.0)) < 1e-6
    assert cl.moon_irradiance(90.0, d, earthshine=False) < 0.5 * full
    # earthshine is largest at new moon and zero at full moon
    assert _close(cl.earthshine(180.0), 0.19 * 0.5, 1e-9)
    assert abs(cl.earthshine(0.0)) < 1e-6
    assert cl.moon_irradiance(170.0, d) > cl.moon_irradiance(170.0, d, earthshine=False)
    # in the sun's units
    assert _close(cl.moon_fraction(0.0, d, earthshine=False), full / cl.E_SUN)
    # a closer moon is brighter by the inverse square
    assert _close(cl.moon_irradiance(0.0, d / 2.0, earthshine=False), 4.0 * full)


def test_moon_disc_radiance_and_colour():
    d = 384400.0
    omega = math.pi * (cl.MOON_RADIUS_KM / d) ** 2
    assert _close(cl.moon_solid_angle(d), omega)
    assert _close(cl.moon_disc_radiance(0.0, d), cl.moon_irradiance(0.0, d) / omega)
    c = cl.moon_colour()
    assert c[0] > c[1] > c[2] > 0.0           # redder than the sun
    assert _close(cl.moon_ramp(340.0), 0.70) and _close(cl.moon_ramp(740.0), 1.35)
    assert _close(c, (cl.moon_ramp(650.0), cl.moon_ramp(550.0), cl.moon_ramp(450.0)))


def test_the_hapke_lommel_seeliger_brdf_has_no_limb_darkening_and_an_opposition_peak():
    # at normal incidence and emergence, the BRDF is 2/(3 pi) B S
    f0 = cl.moon_brdf(0.0, 0.0, 0.0)
    assert _close(f0, 2.0 / (3.0 * math.pi) * cl.retrodirective(0.0) * cl.scattering_law(0.0) / 2.0)
    assert cl.retrodirective(0.0) == 2.0 and _close(cl.retrodirective(120.0), 1.0)
    assert cl.retrodirective(10.0) < cl.retrodirective(1.0) < 2.0
    # full moon: f is the same at the centre and the limb (theta_i = theta_r), so the disc is uniform
    assert _close(cl.moon_brdf(80.0, 80.0, 0.0), cl.moon_brdf(0.0, 0.0, 0.0), 1e-12)
    # away from full moon the terminator side (grazing incidence) is darker than the limb toward the sun
    assert cl.moon_brdf(10.0, 70.0, 60.0) > cl.moon_brdf(70.0, 10.0, 60.0)
    assert cl.moon_brdf(95.0, 10.0, 60.0) == 0.0
    assert _close(cl.scattering_law(0.0), 1.0 + cl.HAPKE_T * 0.25)


def test_airglow_brightens_toward_the_horizon_by_van_rhijn_and_the_background_is_uniform():
    assert cl.van_rhijn(0.0) == 1.0
    assert cl.van_rhijn(60.0) > cl.van_rhijn(30.0) > 1.0
    r = cl.PLANET_RADIUS
    h = cl.AIRGLOW_HEIGHT
    z = math.radians(75.0)
    want = 1.0 / math.sqrt(1.0 - (r / (r + h)) ** 2 * math.sin(z) ** 2)
    assert _close(cl.van_rhijn(75.0), want)
    assert _close(cl.airglow_radiance(0.0), cl.AIRGLOW / (math.pi * cl.E_SUN))
    assert _close(cl.airglow_radiance(75.0, 2.0), 2.0 * cl.AIRGLOW / (math.pi * cl.E_SUN) * want)
    assert _close(cl.background_radiance(), (cl.STARLIGHT + cl.GALACTIC) / (math.pi * cl.E_SUN))
    assert _close(cl.background_radiance(0.0), cl.GALACTIC / (math.pi * cl.E_SUN))
    with pytest.raises(cl.CloudError):
        cl.van_rhijn(95.0)


def test_a_night_frame_sums_the_sun_the_moon_the_airglow_and_the_background():
    f = cl.night_frame("2003-10-17T04:00:00-07:00", 39.742476, -105.1786, (0.0, -1.0, 0.0))
    assert f["sun_zenith"] > 100.0                      # the sun is well below the horizon
    assert 0.0 <= f["moon_illuminated"] <= 1.0
    parts = ("sun_sky", "moon_sky", "airglow", "background")
    for k in parts:
        assert len(f[k]) == 3 and all(v >= 0.0 for v in f[k])
    total = tuple(sum(f[k][c] for k in parts) for c in range(3))
    assert _close(f["radiance"], total, 1e-15)
    assert all(v > 0.0 for v in f["radiance"])          # the sky is never black
    # the moon's sky is the sun's sky function scaled by the moon's irradiance fraction and colour
    assert f["moon_fraction"] > 0.0
    # switching the terms off
    off = cl.night_frame("2003-10-17T04:00:00-07:00", 39.742476, -105.1786, (0.0, -1.0, 0.0),
                         airglow=0.0, starlight=0.0, moon=False)
    assert off["moon_sky"] == (0.0, 0.0, 0.0) and off["airglow"] == (0.0, 0.0, 0.0)
    assert _close(off["background"], tuple(cl.GALACTIC / (math.pi * cl.E_SUN) * t for t in off["transmittance"]), 1e-15)
    # a direction into the ground sees no sky at all
    ground = cl.night_frame("2003-10-17T04:00:00-07:00", 39.742476, -105.1786, (0.0, 1.0, 0.0))
    assert ground["radiance"] == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------------------------- validation


def test_the_example_documents_are_valid_and_the_bad_one_lists_every_rule():
    assert cl.validate_document(cl.example_document()) == []
    assert cl.validate_document(cl.mapped_document()) == []
    assert cl.validate_document(cl.bad_document()) == ["CN1", "CN2", "CN3", "CN4", "CN5", "CN6"]


def test_validation_rules_one_at_a_time():
    def with_layer(**kw):
        doc = cl.example_document()
        doc["lights"][0]["cloudLayers"][0].update(kw)
        return doc

    for kw in (dict(coverage=1.5), dict(type=-0.1), dict(precipitation=2.0), dict(density=-1.0), dict(scale=0.0),
               dict(detailScale=0.0), dict(detail=1.5), dict(octaves=0), dict(octaves=4), dict(albedo=-0.1),
               dict(albedo=1.1), dict(ambient=-1.0), dict(weatherScale=0.0)):
        assert cl.validate_document(with_layer(**kw)) == ["CN1"], kw
    for kw in (dict(base=-1.0), dict(thickness=0.0), dict(base=99000.0, thickness=2000.0)):
        assert cl.validate_document(with_layer(**kw)) == ["CN2"], kw
    for kw in (dict(dropletDiameter=4.0), dict(dropletDiameter=51.0)):
        assert cl.validate_document(with_layer(**kw)) == ["CN3"], kw
    assert cl.validate_document(with_layer(weatherMap="ghost")) == ["CN4"]
    assert cl.validate_document(with_layer(wind="ghost")) == ["CN4"]
    doc = cl.example_document()
    doc["lights"][0]["sky"] = "gradient"
    assert cl.validate_document(doc) == ["CN5"]
    doc = cl.example_document()
    doc["lights"][0]["airglow"] = -1.0
    assert cl.validate_document(doc) == ["CN6"]
    doc = cl.example_document()
    doc["lights"][0]["earthshine"] = -0.5
    assert cl.validate_document(doc) == ["CN6"]
    low = cl.example_document()
    low["version"] = "1.7"
    assert cl.validate_document(low) == ["V17"]
    low["lights"][0]["cloudLayers"] = []
    low["lights"][0].pop("airglow", None)
    low["lights"][0].pop("starlight", None)
    low["lights"][0].pop("earthshine", None)
    low["lights"][0]["sky"] = "gradient"
    assert cl.validate_document(low) == []


def test_constants():
    assert cl.PURPOSE == "clouds"
    assert cl.BASE_VALUE == 1 and cl.BASE_WORLEY == (2, 3, 4) and cl.DETAIL_WORLEY == (5, 6, 7)
    assert cl.OCTAVE_STRIDE == 1024 and cl.MAX_OCTAVES == 3 and cl.WORLEY_WEIGHTS == (0.625, 0.25, 0.125)
    assert cl.DEFAULTS["base"] == 1500.0 and cl.DEFAULTS["thickness"] == 2500.0
    assert cl.DEFAULTS["dropletDiameter"] == 20.0 and cl.DEFAULTS["scale"] == 4000.0
    assert cl.E_SUN == 1361.0 and cl.MOON_ALBEDO == 0.072 and cl.MOON_RADIUS_KM == ps.MOON_RADIUS_KM
    assert cl.HAPKE_G == 0.6 and cl.HAPKE_T == 0.1 and cl.EARTHSHINE_FULL == 0.19
    assert cl.STARLIGHT == 3e-8 and cl.AIRGLOW == 5.1e-8 and cl.GALACTIC == 1e-8 and cl.AIRGLOW_HEIGHT == 80000.0
    assert cl.PLANET_RADIUS == ps.atmosphere()["planet_radius"]
    assert cl.CALIBRATION_POINTS == 32 and cl.CALIBRATION_CELLS == 8 and cl.RANGE == 35000.0
    assert cl.MS_ATTENUATION == 0.5 and cl.MS_CONTRIBUTION == 0.5 and cl.MS_ECCENTRICITY == 0.5


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
    for word in ("SR-102", "SREP 12", "SREP 14", "SREP 40", "SREP 79", "`cloudLayer`", "base", "thickness", "coverage",
                 "`type`", "precipitation", "weatherMap", "weatherScale", "density", "scale", "detailScale", "detail",
                 "octaves", "`wind`", "dropletDiameter", "albedo", "ambient", "earthshine", "airglow", "starlight",
                 "moonIntensity", "CN1", "CN2", "CN3", "CN4", "CN5", "CN6", "V17", "clouds_reference.py",
                 "random-streams", "D24", "pack(i, j, k)", "Worley", "Perlin", "Schneider", "Jendersie", "Jensen",
                 "Wrenninge", "van Rhijn", "Lommel", "Hapke", "Beer", "powder", "frozen", "Terragen", "HDRP",
                 "UE5", "stratus", "stratocumulus", "cumulus", "cumulonimbus", "1361", "0.072", "3 · 10⁻⁸",
                 "5.1 · 10⁻⁸", "fields.rs", "sky_radiance", "physical", "`fog`"):
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
    assert len(cl.TABLE) == len(_draft_rows())
    for (name, expr, _value), (dname, dexpr, _dvalue) in zip(cl.TABLE, _draft_rows()):
        assert name == dname and expr == dexpr


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = cl.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or cl._same(got, want), f"{name}: {got!r} != {want!r}"
