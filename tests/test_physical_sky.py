"""Tests of the draft SREP "Add the physical sun, moon and sky to dome lights" (srep/srep-0000-physical-sky.md)
and of its reference implementation conformance/tools/physical_sky_reference.py (A1 of SREP 12, SRC-43).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "physical_sky_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-physical-sky.md")

_spec = importlib.util.spec_from_file_location("physical_sky_reference", MODULE)
ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ps)

# The published example of Reda and Andreas (2004, 2008 revision), section 6 / appendix A.
EXAMPLE = dict(year=2003, month=10, day=17, hour=12, minute=30, second=30.0, timezone=-7.0,
               longitude=-105.1786, latitude=39.742476, elevation=1830.14, pressure=820.0, temperature=11.0,
               delta_t=67.0, slope=30.0, azimuth_rotation=-10.0, refraction=0.5667)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ------------------------------------------------------------------------------------ rule 1 and 2: time scales


def test_julian_day_of_the_example_and_of_the_epoch():
    assert _close(ps.julian_day(2003, 10, 17, 12, 30, 30.0, -7.0), 2452930.312847, 5e-7)
    assert ps.julian_day(2000, 1, 1, 12, 0, 0.0, 0.0) == 2451545.0
    assert ps.julian_day(1999, 1, 1, 0, 0, 0.0, 0.0) == 2451179.5
    assert ps.julian_day(1987, 1, 27, 0, 0, 0.0, 0.0) == 2446822.5
    assert ps.julian_day(1600, 12, 31, 0, 0, 0.0, 0.0) == 2305812.5


def test_the_date_time_string_parses_with_its_offset():
    assert ps.parse_datetime("2003-10-17T12:30:30-07:00") == (2003, 10, 17, 12, 30, 30.0, -7.0)
    assert ps.parse_datetime("2026-06-21T12:00:00Z") == (2026, 6, 21, 12, 0, 0.0, 0.0)
    assert ps.parse_datetime("2026-06-21T12:00:00.5+05:30") == (2026, 6, 21, 12, 0, 0.5, 5.5)
    for bad in ("2026-06-21", "2026-13-01T00:00:00Z", "2026-06-21T25:00:00Z", "2026-06-21T12:00:00", "yesterday"):
        with pytest.raises(ps.SkyError):
            ps.parse_datetime(bad)


def test_the_time_scales_of_the_example():
    jd = ps.julian_day(2003, 10, 17, 12, 30, 30.0, -7.0)
    t = ps.time_scales(jd, 67.0)
    assert _close(t["jde"], jd + 67.0 / 86400.0)
    assert _close(t["jc"], (jd - 2451545.0) / 36525.0)
    assert _close(t["jme"], t["jce"] / 10.0)


# ------------------------------------------------------------------------------------ rule 3 to 6: the sun


def test_the_heliocentric_position_of_the_example():
    jd = ps.julian_day(2003, 10, 17, 12, 30, 30.0, -7.0)
    t = ps.time_scales(jd, 67.0)
    assert _close(ps.heliocentric_longitude(t["jme"]), 24.0182616917, 1e-6)
    assert _close(ps.heliocentric_latitude(t["jme"]), -0.0001011219, 1e-7)
    assert _close(ps.earth_radius_vector(t["jme"]), 0.9965422974, 1e-7)


def test_the_nutation_and_obliquity_of_the_example():
    jd = ps.julian_day(2003, 10, 17, 12, 30, 30.0, -7.0)
    t = ps.time_scales(jd, 67.0)
    dpsi, deps = ps.nutation(t["jce"])
    assert _close(dpsi, -0.00399840, 2e-7)
    assert _close(deps, 0.00166657, 2e-7)
    assert _close(ps.true_obliquity(t["jme"], deps), 23.440465, 1e-5)


def test_the_apparent_sun_of_the_example():
    s = ps.sun_position(**EXAMPLE)
    assert _close(s["apparent_longitude"], 204.0085519281, 1e-6)
    assert _close(s["right_ascension"], 202.22741, 1e-5)
    assert _close(s["declination"], -9.31434, 1e-5)
    assert _close(s["hour_angle"], 11.105900, 1e-5)
    assert _close(s["topocentric_right_ascension"], 202.22704, 1e-5)
    assert _close(s["topocentric_declination"], -9.316179, 1e-5)
    # The report prints H' = 11.10629, but H - delta alpha from its own printed H and alpha' is
    # 11.10627; the report's value is rounded from unprinted digits, so this one check is looser.
    assert _close(s["topocentric_hour_angle"], 11.10629, 3e-5)


def test_the_published_example_within_a_thousandth_of_a_degree():
    s = ps.sun_position(**EXAMPLE)
    assert _close(s["zenith"], 50.11162, 1e-3)
    assert _close(s["azimuth"], 194.34024, 1e-3)
    assert _close(s["incidence"], 25.18700, 1e-3)
    assert ps.spa_test() == (True, True, True)


def test_refraction_vanishes_below_the_horizon_and_at_zero_pressure():
    # The report applies refraction down to -(0.26667 + 0.5667) degrees of elevation, below it none.
    assert ps.refraction_correction(91.0, 820.0, 11.0, 0.5667) == 0.0
    assert ps.refraction_correction(90.0, 820.0, 11.0, 0.5667) > 0.0
    assert ps.refraction_correction(45.0, 0.0, 11.0, 0.5667) == 0.0
    r = ps.refraction_correction(89.0, 1013.25, 10.0, 0.5667)
    assert 0.3 < r < 0.6
    assert ps.refraction_correction(95.0, 1013.25, 10.0, 0.5667) == 0.0


def test_the_sun_direction_in_scene_axes():
    # Zenith 0 is straight up (-y); azimuth 0 is north, which the draft maps to +z, east to +x.
    assert _close(ps.sun_direction(0.0, 0.0), (0.0, -1.0, 0.0))
    assert _close(ps.sun_direction(90.0, 0.0), (0.0, 0.0, 1.0))
    assert _close(ps.sun_direction(90.0, 90.0), (1.0, 0.0, 0.0))
    assert _close(ps.sun_direction(90.0, 180.0), (0.0, 0.0, -1.0))
    assert _close(ps.sun_direction(120.0, 0.0), (0.0, 0.5, math.cos(math.radians(30.0))))


def test_a_date_places_the_sun_with_the_document_defaults():
    s = ps.sun_from_document("2003-10-17T12:30:30-07:00", 39.742476, -105.1786, altitude=1830.14, pressure=820.0,
                             temperature=11.0, delta_t=67.0)
    assert _close(s["zenith"], 50.11162, 1e-3)
    assert _close(s["azimuth"], 194.34024, 1e-3)
    d = ps.sun_from_document("2026-06-21T12:00:00Z", 0.0, 0.0)
    assert d["zenith"] < 24.0, "near the June solstice the sun at noon on the equator is at about 23.4 degrees"
    assert d["azimuth"] < 10.0 or d["azimuth"] > 350.0


def test_sun_errors():
    with pytest.raises(ps.SkyError):
        ps.sun_from_document("2026-06-21T12:00:00Z", 91.0, 0.0)
    with pytest.raises(ps.SkyError):
        ps.sun_from_document("2026-06-21T12:00:00Z", 0.0, 181.0)
    with pytest.raises(ps.SkyError):
        ps.sun_from_document("2026-06-21T12:00:00Z", 0.0, 0.0, pressure=-1.0)
    with pytest.raises(ps.SkyError):
        ps.sun_from_document("2026-06-21T12:00:00Z", 0.0, 0.0, delta_t=10000.0)
    with pytest.raises(ps.SkyError):
        ps.sun_from_document("1800-06-21T12:00:00Z", 0.0, 0.0)
    with pytest.raises(ps.SkyError):
        ps.sun_from_document("2300-06-21T12:00:00Z", 0.0, 0.0)


# ------------------------------------------------------------------------------------ rule 7: the moon


def test_the_moon_of_meeus_example_47a():
    # 1992 April 12, 0h TD: lambda 133.162655, beta -3.229126, distance 368409.7 km (Meeus 1998, example 47.a).
    jde = 2448724.5
    m = ps.moon_position(jde)
    assert _close(m["longitude"], 133.162655, 0.05)
    assert _close(m["latitude"], -3.229126, 0.02)
    assert _close(m["distance"], 368409.7, 3700.0)
    assert ps.moon_test() == (True, True, True)


def test_the_moon_is_placed_topocentrically_by_the_same_observer():
    m = ps.moon_from_document("2003-10-17T12:30:30-07:00", 39.742476, -105.1786, altitude=1830.14, delta_t=67.0)
    assert 0.0 <= m["azimuth"] < 360.0
    assert 0.0 <= m["zenith"] <= 180.0
    assert 0.49 < m["angular_diameter"] < 0.57
    g = ps.moon_from_document("2003-10-17T12:30:30-07:00", 39.742476, -105.1786, altitude=1830.14, delta_t=67.0,
                              topocentric=False)
    assert abs(g["zenith"] - m["zenith"]) < 1.0 and abs(g["zenith"] - m["zenith"]) > 0.0


def test_the_phase_angle_and_illuminated_fraction():
    # Full moon 2003-11-09 01:13 UTC, new moon 2003-10-25 12:50 UTC (USNO).
    full = ps.moon_from_document("2003-11-09T01:13:00Z", 0.0, 0.0)
    new = ps.moon_from_document("2003-10-25T12:50:00Z", 0.0, 0.0)
    assert full["illuminated"] > 0.99
    assert new["illuminated"] < 0.01


# ------------------------------------------------------------------------------------ rule 8 to 10: the atmosphere


def test_the_default_atmosphere_is_hillaire_s_earth():
    a = ps.atmosphere()
    assert a["planet_radius"] == 6360000.0
    assert a["top_radius"] == 6460000.0
    assert _close(a["rayleigh_scattering"], (5.802e-6, 13.558e-6, 33.1e-6))
    assert a["rayleigh_scale"] == 8000.0
    assert _close(a["mie_scattering"], 3.996e-6) and _close(a["mie_absorption"], 4.4e-6)
    assert a["mie_scale"] == 1200.0 and a["mie_anisotropy"] == 0.8
    assert _close(a["ozone_absorption"], (0.650e-6, 1.881e-6, 0.085e-6))
    assert a["ozone_centre"] == 25000.0 and a["ozone_width"] == 15000.0


def test_density_profiles():
    a = ps.atmosphere()
    assert ps.rayleigh_density(a, 0.0) == 1.0
    assert _close(ps.rayleigh_density(a, 8000.0), math.exp(-1.0))
    assert _close(ps.mie_density(a, 1200.0), math.exp(-1.0))
    assert ps.ozone_density(a, 25000.0) == 1.0
    assert ps.ozone_density(a, 10000.0) == 0.0
    assert ps.ozone_density(a, 40000.0) == 0.0
    assert _close(ps.ozone_density(a, 17500.0), 0.5)
    assert ps.rayleigh_density(a, 100000.0 + 1.0) == 0.0, "nothing above the top of the atmosphere"


def test_vertical_transmittance_against_the_closed_form():
    a = ps.atmosphere(ozone=0.0)
    t = ps.transmittance(a, (0.0, 0.0, a["planet_radius"]), (0.0, 0.0, 1.0))
    for c in range(3):
        depth = (a["rayleigh_scattering"][c] * a["rayleigh_scale"] * (1 - math.exp(-100000.0 / a["rayleigh_scale"]))
                 + (a["mie_scattering"] + a["mie_absorption"]) * a["mie_scale"]
                 * (1 - math.exp(-100000.0 / a["mie_scale"])))
        assert _close(t[c], math.exp(-depth), 1e-6)
    assert ps.transmittance_test() == (True, True, True)


def test_transmittance_is_multiplicative_along_a_ray_and_refined_by_quadrature():
    a = ps.atmosphere()
    p = (0.0, 0.0, a["planet_radius"] + 10.0)
    d = ps.unit((1.0, 0.0, 0.3))
    full = ps.transmittance(a, p, d, samples=256)
    q = ps.march(p, d, 50000.0)
    part = ps.transmittance(a, p, d, samples=128, length=50000.0)
    rest = ps.transmittance(a, q, d, samples=128)
    for c in range(3):
        assert _close(full[c], part[c] * rest[c], 2e-5)
    fine = ps.transmittance(a, p, d, samples=2048)
    for c in range(3):
        assert _close(full[c], fine[c], 1e-5)


def test_the_ground_blocks_the_sun_below_the_horizon():
    a = ps.atmosphere()
    p = (0.0, 0.0, a["planet_radius"] + 10.0)
    assert ps.transmittance(a, p, ps.unit((1.0, 0.0, -0.1))) == (0.0, 0.0, 0.0)
    assert ps.hits_ground(a, p, ps.unit((1.0, 0.0, -0.1))) is True
    assert ps.hits_ground(a, p, (0.0, 0.0, 1.0)) is False


def test_the_phase_functions_are_normalised():
    assert _close(ps.integrate_phase(lambda mu: ps.rayleigh_phase(mu)), 1.0, 1e-6)
    assert _close(ps.integrate_phase(lambda mu: ps.hg_phase(mu, 0.8)), 1.0, 1e-6)
    assert _close(ps.rayleigh_phase(1.0), 3.0 / (16.0 * math.pi) * 2.0)
    assert _close(ps.rayleigh_phase(0.0), 3.0 / (16.0 * math.pi))


def test_single_scattering_sky_is_blue_at_the_zenith_and_warm_at_the_sun():
    a = ps.atmosphere()
    sun = ps.unit((1.0, 0.0, 1.0))
    obs = (0.0, 0.0, a["planet_radius"] + 1.0)
    zenith = ps.sky_radiance(a, obs, (0.0, 0.0, 1.0), sun, multiple=False)
    assert zenith[2] > zenith[1] > zenith[0] > 0.0
    near = ps.sky_radiance(a, obs, ps.unit((1.0, 0.0, 0.1)), sun, multiple=False)
    far = ps.sky_radiance(a, obs, ps.unit((-1.0, 0.0, 0.1)), sun, multiple=False)
    assert sum(near) > sum(far), "the Mie forward lobe brightens the sky near the sun"
    assert ps.sky_radiance(a, obs, ps.unit((1.0, 0.0, -0.2)), sun, multiple=False) == (0.0, 0.0, 0.0)


def test_single_scattering_against_a_fine_quadrature():
    a = ps.atmosphere()
    sun = ps.unit((1.0, 0.0, 0.5))
    obs = (0.0, 0.0, a["planet_radius"] + 1.0)
    d = ps.unit((0.3, 0.4, 0.6))
    coarse = ps.sky_radiance(a, obs, d, sun, multiple=False, samples=32)
    fine = ps.sky_radiance(a, obs, d, sun, multiple=False, samples=512)
    for c in range(3):
        assert _close(coarse[c], fine[c], 1e-3 * fine[c])
    assert ps.quadrature_test() == (True, True)


def test_the_sky_is_symmetric_about_the_sun_s_vertical_plane():
    a = ps.atmosphere()
    sun = ps.unit((1.0, 0.0, 0.5))
    obs = (0.0, 0.0, a["planet_radius"] + 1.0)
    left = ps.sky_radiance(a, obs, ps.unit((0.2, 0.7, 0.5)), sun)
    right = ps.sky_radiance(a, obs, ps.unit((0.2, -0.7, 0.5)), sun)
    assert _close(left, right, 1e-12)


def test_multiple_scattering_adds_light_and_conserves_energy():
    a = ps.atmosphere()
    sun = ps.unit((1.0, 0.0, 0.5))
    obs = (0.0, 0.0, a["planet_radius"] + 1.0)
    d = ps.unit((-0.5, 0.0, 0.3))
    single = ps.sky_radiance(a, obs, d, sun, multiple=False)
    both = ps.sky_radiance(a, obs, d, sun, multiple=True)
    assert all(b > s for b, s in zip(both, single))
    f = ps.multiple_scattering_factor(a, 1.0, 0.5)
    assert all(0.0 < x < 1.0 for x in f), "the fraction scattered again is a proper fraction"
    irr = ps.sky_irradiance(a, obs, sun)
    assert all(0.0 < e < 1.0 for e in irr), "the sky delivers less than the sun's own irradiance"
    assert ps.energy_test() == (True, True)


def test_sun_disc_and_limb_transmittance():
    a = ps.atmosphere()
    obs = (0.0, 0.0, a["planet_radius"] + 1.0)
    high = ps.sun_radiance(a, obs, ps.unit((0.0, 0.0, 1.0)))
    low = ps.sun_radiance(a, obs, ps.unit((1.0, 0.0, 0.02)))
    assert all(h > l for h, l in zip(high, low))
    assert low[0] / low[2] > high[0] / high[2], "the low sun is redder"
    assert ps.sun_radiance(a, obs, ps.unit((1.0, 0.0, -0.02))) == (0.0, 0.0, 0.0)


def test_aerial_perspective_is_the_identity_at_zero_distance_and_fades_with_it():
    a = ps.atmosphere()
    sun = ps.unit((1.0, 0.0, 0.5))
    obs = (0.0, 0.0, a["planet_radius"] + 1.0)
    d = ps.unit((1.0, 0.0, 0.0))
    colour = (0.2, 0.4, 0.1)
    assert ps.aerial_perspective(a, obs, d, 0.0, colour, sun) == colour
    near = ps.aerial_perspective(a, obs, d, 1000.0, colour, sun)
    far = ps.aerial_perspective(a, obs, d, 50000.0, colour, sun)
    sky = ps.sky_radiance(a, obs, d, sun)
    for c in range(3):
        assert abs(far[c] - sky[c]) < abs(near[c] - sky[c]), "with distance the colour goes to the sky's"
    assert ps.aerial_test() == (True, True)


def test_height_fog_has_the_closed_form_transmittance():
    fog = ps.fog(density=0.001, height=100.0)
    assert ps.fog_transmittance(fog, 0.0, 0.0, 1000.0) == math.exp(-1.0)
    t = ps.fog_transmittance(fog, 0.0, 50.0, 1000.0)
    assert _close(t, math.exp(-0.001 * 1000.0 * 100.0 / 50.0 * (1 - math.exp(-0.5))))
    assert _close(ps.fog_transmittance(fog, 200.0, 200.0, 1000.0), math.exp(-0.001 * 1000.0 * math.exp(-2.0)))
    assert ps.fog_transmittance(fog, 0.0, 0.0, 0.0) == 1.0
    assert ps.fog_test() == (True, True)


def test_the_observer_altitude_and_the_planet_limb_from_orbit():
    a = ps.atmosphere()
    sun = ps.unit((0.0, 0.0, 1.0))
    orbit = (0.0, 0.0, a["planet_radius"] + 400000.0)
    space = ps.sky_radiance(a, orbit, (0.0, 0.0, 1.0), sun)
    assert space == (0.0, 0.0, 0.0), "looking away from the planet from orbit there is no atmosphere"
    limb = ps.limb_direction(a, orbit)
    just_in = ps.sky_radiance(a, orbit, ps.unit((1.0, 0.0, limb[2] + 0.002)), sun)
    just_out = ps.sky_radiance(a, orbit, ps.unit((1.0, 0.0, limb[2] + 0.02)), sun)
    assert sum(just_in) > sum(just_out) > 0.0


def test_atmosphere_errors_and_bounds():
    with pytest.raises(ps.SkyError):
        ps.atmosphere(planet_radius=0.0)
    with pytest.raises(ps.SkyError):
        ps.atmosphere(top_radius=6000000.0)
    with pytest.raises(ps.SkyError):
        ps.atmosphere(aerosol=-1.0)
    with pytest.raises(ps.SkyError):
        ps.atmosphere(mie_anisotropy=1.0)
    a = ps.atmosphere()
    with pytest.raises(ps.SkyError):
        ps.transmittance(a, (0.0, 0.0, a["planet_radius"]), (0.0, 0.0, 1.0), samples=0)
    with pytest.raises(ps.SkyError):
        ps.transmittance(a, (0.0, 0.0, a["planet_radius"]), (0.0, 0.0, 1.0), samples=ps.MAX_SAMPLES + 1)
    # An observer below the sphere is lifted onto it (rule 10), not refused.
    assert ps.sky_radiance(a, (0.0, 0.0, a["planet_radius"] - 1.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)) == \
        ps.sky_radiance(a, (0.0, 0.0, a["planet_radius"]), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0))
    with pytest.raises(ps.SkyError):
        ps.fog(density=-1.0, height=100.0)


# ------------------------------------------------------------------------------------ the seek check


def test_the_sky_is_a_function_of_the_date_alone():
    first = ps.sky_frame("2003-10-17T12:30:30-07:00", 39.742476, -105.1786, (0.0, 0.0, 1.0))
    ps.sky_frame("2003-10-17T18:30:30-07:00", 39.742476, -105.1786, (0.0, 0.0, 1.0))
    again = ps.sky_frame("2003-10-17T12:30:30-07:00", 39.742476, -105.1786, (0.0, 0.0, 1.0))
    assert first == again
    assert ps.seek_test() == (True, True)


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
    assert "SR-86" in draft
    for word in ("physical", "date", "latitude", "longitude", "altitude", "pressure", "temperature", "deltaT",
                 "Reda and Andreas", "50.11162", "194.34024", "nutation", "topocentric", "refraction", "moon",
                 "Montenbruck", "Hillaire", "Bruneton", "Rayleigh", "Mie", "ozone", "transmittance", "quadrature",
                 "multiple scattering", "aerial perspective", "height fog", "fogDensity", "fogHeight", "PSKY3", "V17",
                 "seek check", "physical_sky_reference.py", "Hosek", "Prague", "BSD-3-Clause", "pvlib",
                 "media draft", "limb", "SREP 71"):
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
    s = ps.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or ps._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    ps.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())


# ------------------------------------------------------------------------- the sun's scale under physical (SR-86)


def test_an_absent_sun_intensity_reads_as_one_under_physical():
    assert ps.effective_sun_irradiance() == (1.0, 1.0, 1.0)
    assert ps.effective_sun_irradiance((1.0, 0.5, 0.25)) == (1.0, 0.5, 0.25)
    assert ps.effective_sun_irradiance((1.0, 0.5, 0.25), 2.0) == (2.0, 1.0, 0.5)
    assert ps.effective_sun_irradiance((1.0, 1.0, 1.0), 0.0) == (0.0, 0.0, 0.0)      # an explicit 0: no sun
    a = ps.atmosphere(sun_irradiance=ps.effective_sun_irradiance((1.0, 1.0, 1.0), 2.0))
    obs = ps._ground_observer(a)
    up = (0.0, 0.0, 1.0)
    assert all(abs(x - 2.0 * y) < 1e-12 for x, y in zip(ps.sun_radiance(a, obs, up), ps.sun_radiance(ps.atmosphere(), obs, up)))
    for bad_colour in ((1.0, 1.0), (1.5, 1.0, 1.0), (-0.1, 0.0, 0.0)):
        with pytest.raises(ps.SkyError):
            ps.effective_sun_irradiance(bad_colour)
    for bad_k in (-1.0, math.nan, math.inf):
        with pytest.raises(ps.SkyError):
            ps.effective_sun_irradiance((1.0, 1.0, 1.0), bad_k)


def test_the_draft_settles_the_sun_intensity_default(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("under `physical` reads as 1 when absent", "`effective_sun_irradiance`",
                   "`colorType` channels are in [0, 1]", "scaled once", "the sun's effective irradiance",
                   "An explicit `sunIntensity=\"0\"` under `physical` removes the sun's light and disc"):
        assert phrase in text, phrase
    assert "`sun_radiance` times `sunIntensity`" not in text


def test_the_draft_prefixes_its_rule_ids_and_warns_for_psky1(draft):
    text = re.sub(r"\n +", " ", draft)
    assert re.search(r"(?<![A-Z`])SKY[1-4]", draft) is None, "SREP 71 owns SKY1 and SKY2 in schema/scene-render.sch"
    for phrase in ("**PSKY1**", "**PSKY2**", "**PSKY3**", "**PSKY4**", "`p-srep-physical-sky`",
                   "already owns `SKY1` and `SKY2`", "each is ignored with a warning",
                   "a native check, not a Schematron assert"):
        assert phrase in text, phrase
    with open(os.path.join(ROOT, "schema", "scene-render.sch"), encoding="utf-8") as f:
        sch = f.read()
    assert 'id="SKY1"' in sch and 'id="SKY2"' in sch and "PSKY" not in sch


# -------------------------------------------------------------------- the moon's and the sun disc's radiance (SR-86)


def test_the_moon_disc_follows_the_lambert_phase_law():
    assert ps.lambert_phase(0.0) == 1.0 and _close(ps.lambert_phase(90.0), 1.0 / math.pi, 1e-12)
    assert abs(ps.lambert_phase(180.0)) < 1e-15
    assert ps.lambert_phase(30.0) > ps.lambert_phase(60.0) > ps.lambert_phase(120.0) > 0.0
    for bad in (-1.0, 181.0, math.nan):
        with pytest.raises(ps.SkyError):
            ps.lambert_phase(bad)
    a = ps.atmosphere()
    obs = ps._ground_observer(a)
    full = ps.moon_from_document("2003-11-09T01:13:00Z", 0.0, 0.0)
    new = ps.moon_from_document("2003-10-25T12:50:00Z", 0.0, 0.0)
    z = math.radians(full["zenith"])
    t = ps.transmittance(a, obs, (math.sin(z), 0.0, math.cos(z)))
    radiance = ps.moon_radiance(a, obs, full)
    assert all(_close(radiance[c], ps.MOON_ALBEDO * ps.lambert_phase(full["phase_angle"]) * t[c] / math.pi, 1e-12)
               for c in range(3))
    assert all(0.0 < x < ps.MOON_ALBEDO / math.pi for x in radiance) and radiance[0] > radiance[2]  # reddened
    assert all(x < 1e-6 for x in ps.moon_radiance(a, obs, new))
    assert ps.moon_radiance(a, obs, dict(full, zenith=100.0)) == (0.0, 0.0, 0.0)              # below the horizon
    assert ps.moon_radiance(a, obs, full, 2.0) == tuple(2.0 * x for x in radiance)
    assert ps.moon_radiance(a, obs, full, 0.0) == (0.0, 0.0, 0.0)
    scaled = ps.atmosphere(sun_irradiance=ps.effective_sun_irradiance((1.0, 1.0, 1.0), 3.0))
    assert all(_close(x, 3.0 * y, 1e-12) for x, y in zip(ps.moon_radiance(scaled, obs, full), radiance))
    for bad in (-1.0, math.inf):
        with pytest.raises(ps.SkyError):
            ps.moon_radiance(a, obs, full, bad)


def test_the_sun_disc_carries_the_transmitted_irradiance_whatever_its_size():
    a = ps.atmosphere()
    obs = ps._ground_observer(a)
    up = (0.0, 0.0, 1.0)
    e = ps.sun_radiance(a, obs, up)
    assert _close(ps.disc_solid_angle(0.53), 2.0 * math.pi * (1.0 - math.cos(math.radians(0.265))), 1e-15)
    for size in (0.53, 2.0, 10.0):
        disc = ps.sun_disc_radiance(a, obs, up, size)
        assert all(_close(disc[c] * ps.disc_solid_angle(size), e[c], 1e-12) for c in range(3)), size
    assert ps.sun_disc_radiance(a, obs, up, 0.0) == (0.0, 0.0, 0.0)
    tinted = ps.sun_disc_radiance(a, obs, up, 0.53, (1.0, 0.5, 0.0))
    plain = ps.sun_disc_radiance(a, obs, up)
    assert tinted == (plain[0], 0.5 * plain[1], 0.0)
    assert ps.sun_disc_radiance(a, obs, ps.unit((1.0, 0.0, -0.1))) == (0.0, 0.0, 0.0)          # through the ground
    for bad_size in (-0.1, 181.0, math.nan):
        with pytest.raises(ps.SkyError):
            ps.sun_disc_radiance(a, obs, up, bad_size)
    for bad_colour in ((1.0, 1.0), (2.0, 1.0, 1.0)):
        with pytest.raises(ps.SkyError):
            ps.sun_disc_radiance(a, obs, up, 0.53, bad_colour)


def test_the_draft_defines_the_moon_and_sun_disc_radiance_and_the_sky_day_expectation(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("`moon_radiance`", "`MOON_ALBEDO` 0.12", "`lambert_phase`", "(sin α + (π − α) cos α)/π",
                   "The disc's shape is not phased (open issue 6)", "`sun_disc_radiance`",
                   "`disc_solid_angle(sunSize)`", "`sunColor` tints the disc alone",
                   "the disc's power over its solid angle is the transmitted irradiance whatever `sunSize` says",
                   "`sky_radiance` toward the zenith at the case's own observer and sun direction",
                   "6. **The moon's disc.**"):
        assert phrase in text, phrase
    assert "Earth-moon geometric factor" not in text
    assert "`zenith_radiance()` scaled by `sunIrradiance`" not in text


def test_the_draft_drops_the_sun_intensity_schema_default(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("`sunIntensity` on `lightType` (5990) loses its XSD `default=\"0\"`",
                   "an absent value reads as 0 under `none` and `gradient`", "and as 1 under `physical`",
                   "A schema default is filled before any consumer of the validated infoset sees the document",
                   "**Keeping `sunIntensity`'s schema default.**", "the schema carries no default for it, see Syntax",
                   "`sunIntensity` losing its schema default"):
        assert phrase in text, phrase
    with open(os.path.join(ROOT, "schema", "scene-render.xsd"), encoding="utf-8") as f:
        xsd = f.read()
    assert '<xs:attribute name="sunIntensity" type="nonNegativeDecimal" default="0">' in xsd  # the draft's diff base


# -------------------------------------------------------------------- rules 10 and 11: scale and origin (SR-86)


def test_scene_points_map_to_the_atmosphere_through_pixels_per_meter():
    a = ps.atmosphere()
    r = a["planet_radius"]
    assert ps.atmosphere_position(a, (0.0, 0.0, 0.0)) == (0.0, 0.0, r)
    assert ps.atmosphere_position(a, (0.0, 0.0, 0.0), 400000.0, 1.0) == (0.0, 0.0, r + 400000.0)
    assert ps.atmosphere_position(a, (100.0, -5000.0, 250.0), 10.0, 1.0) == (100.0, 250.0, r + 5010.0)
    assert ps.atmosphere_position(a, (100.0, -5000.0, 250.0)) == (1.0, 2.5, r + 50.0)        # default 100 px/m
    assert ps.scene_altitude(-500.0, 0.0, 1.0) == 500.0 and ps.scene_altitude(0.0, 1830.14, 1.0) == 1830.14
    assert ps.scene_altitude(-50000.0) == 500.0
    obs = ps.atmosphere_position(a, (0.0, 0.0, 0.0), 0.0, 1.0)
    wall = ps.atmosphere_position(a, (0.0, 0.0, 1000.0), 0.0, 1.0)
    assert _close(math.dist(obs, wall), 1000.0, 1e-9)
    f = ps.fog(0.001, 100.0)
    assert _close(ps.fog_transmittance(f, ps.scene_altitude(0.0, 0.0, 1.0), ps.scene_altitude(0.0, 0.0, 1.0), 1000.0),
                  math.exp(-1.0), 1e-12)
    assert _close(ps.fog_transmittance(f, ps.scene_altitude(-500.0, 0.0, 1.0), ps.scene_altitude(-500.0, 0.0, 1.0), 1000.0),
                  math.exp(-math.exp(-5.0)), 1e-12)                                          # e^(-0.0067)
    for bad_k in (0.0, -1.0, math.nan):
        with pytest.raises(ps.SkyError):
            ps.atmosphere_position(a, (0.0, 0.0, 0.0), 0.0, bad_k)
        with pytest.raises(ps.SkyError):
            ps.scene_altitude(0.0, 0.0, bad_k)
    with pytest.raises(ps.SkyError):
        ps.atmosphere_position(a, (0.0, math.inf, 0.0))
    with pytest.raises(ps.SkyError):
        ps.atmosphere_position(a, (0.0, 0.0))


def test_the_draft_states_the_scale_and_origin_of_rules_10_and_11(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("a metre is `physics/@pixelsPerMeter` pixels (SREP 14 rule 4", "the scene's origin is rule 9's observer at `altitude`",
                   "`atmosphere_position(a, p, altitude, pixelsPerMeter)`", "`scene_altitude(y, altitude, pixelsPerMeter)`",
                   "**A scale of the draft's own for rules 10 and 11.**", "`physics pixelsPerMeter=\"1\"`",
                   "a grey wall 1,000 px away at y = 0", "a wall at y = −500 (500 m altitude)"):
        assert phrase in text, phrase
    assert "a grey wall 1 km away at ground level" not in text


# ------------------------------------------------------------------- rule 11 joins rule 10's march (SR-86)


def test_fog_joins_the_aerial_march_and_has_a_closed_form_without_it():
    a = ps.atmosphere()
    obs = ps._ground_observer(a)
    d, sun, colour = (1.0, 0.0, 0.0), ps.unit((1.0, 0.0, 0.5)), (0.5, 0.5, 0.5)
    horizon = ps.horizon_radiance(a, obs, d, sun)
    assert horizon == ps.sky_radiance(a, obs, (1.0, 0.0, 0.0), sun)
    assert ps.horizon_radiance(a, obs, ps.unit((1.0, 0.0, 0.3)), sun) == horizon              # elevation dropped
    assert ps.horizon_radiance(a, obs, (0.0, 0.0, 1.0), sun) == horizon                       # vertical: +x
    assert ps.horizon_radiance(a, obs, (0.0, 1.0, 0.0), sun) != horizon                       # another azimuth
    assert all(x > 0.0 for x in horizon)
    with pytest.raises(ps.SkyError):
        ps.horizon_radiance(a, (1.0, 0.0, a["planet_radius"]), d, sun)
    f = ps.fog(0.001, 100.0)
    plain = ps.aerial_perspective(a, obs, d, 1000.0, colour, sun)
    assert ps.aerial_perspective(a, obs, d, 1000.0, colour, sun, fog=ps.fog(0.0, 100.0), horizon=horizon) == plain
    with pytest.raises(ps.SkyError):
        ps.aerial_perspective(a, obs, d, 1000.0, colour, sun, fog=f)
    assert ps.aerial_perspective(a, obs, d, 0.0, colour, sun, fog=f, horizon=horizon) == colour
    still = ps.atmosphere(rayleigh_scattering=(0.0, 0.0, 0.0), mie_scattering=0.0, mie_absorption=0.0,
                          ozone_absorption=(0.0, 0.0, 0.0))
    end = ps._height(still, ps.march(obs, d, 1000.0))
    marched = ps.aerial_perspective(still, obs, d, 1000.0, colour, sun, fog=f, horizon=(0.1, 0.2, 0.3))
    closed = ps.fogged(colour, f, ps._height(still, obs), end, 1000.0, (0.1, 0.2, 0.3))
    assert all(_close(m, c, 2e-4 * c) for m, c in zip(marched, closed))      # the sphere's curvature
    assert not all(_close(m, c, 1e-5 * c) for m, c in zip(marched, closed))
    assert _close(ps.fogged(colour, f, 0.0, 0.0, 1000.0, (0.0, 0.0, 0.0))[0], 0.5 * math.exp(-1.0), 1e-12)
    assert _close(ps.fogged((0.0, 0.0, 0.0), f, 0.0, 0.0, 1000.0, (1.0, 1.0, 1.0))[0], 1.0 - math.exp(-1.0), 1e-12)
    assert ps.fogged(colour, f, 0.0, 0.0, 0.0, (1.0, 1.0, 1.0)) == colour
    thin = ps.aerial_perspective(a, obs, d, 1000.0, colour, sun, fog=f, horizon=horizon)
    thick = ps.aerial_perspective(a, obs, d, 1000.0, colour, sun, fog=ps.fog(0.003, 100.0), horizon=horizon)
    assert all(abs(t2 - h) < abs(t1 - h) < abs(p - h) or abs(t2 - h) < abs(t1 - h) for t2, t1, p, h in zip(thick, thin, plain, horizon))
    assert ps.fog_march_test() == (True, True, True)
    assert ps.fog_transmittance(f, 100.0, 100.0 + 1e-12, 1000.0) == ps.fog_transmittance(f, 100.0, 100.0, 1000.0)


def test_the_draft_states_how_the_fog_joins_the_aerial_march(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("joins rule 10's march over every surface segment", "σ_f(h) × L_h", "one march, so no order of the two media arises",
                   "`horizon_radiance`; a vertical ray takes azimuth +x", "The media draft's `fog` phase is for declared media, not this fog",
                   "c × T_f + (1 − T_f) × L_h (`fogged`)", "The fog is not applied to the sky itself", "reproduces the closed form within 2 × 10⁻⁴ at 1 km",
                   "`aerialPerspective=\"false\"`: a grey wall", "within 2 % per channel of `aerial_perspective` with the fog",
                   "**Applying the fog at one end of a surface segment.**"):
        assert phrase in text, phrase
    assert "consistent with the media draft's fog phase" not in text


# ------------------------------------------------------------------- rule 10 below the sphere (SR-86)


def test_surface_segments_march_below_the_sphere_and_observers_are_lifted_onto_it():
    a = ps.atmosphere()
    r = a["planet_radius"]
    sun, d, colour = ps.unit((1.0, 0.0, 0.5)), (1.0, 0.0, 0.0), (0.2, 0.4, 0.1)
    camera = (0.0, 0.0, r - 1.8)
    assert ps._lift(a, camera) == (0.0, 0.0, r)
    assert ps._lift(a, (0.0, 0.0, r + 5.0)) == (0.0, 0.0, r + 5.0)
    assert _close(ps._norm(ps._lift(a, (3.0, 4.0, r - 100.0))), r, 1e-6)
    below = ps.aerial_perspective(a, camera, d, 10000.0, colour, sun)
    over = ps.aerial_perspective(a, ps._ground_observer(a), d, 10000.0, colour, sun)
    assert all(_close(b, o, 2e-3 * o) for b, o in zip(below, over)) and below != colour
    # Fully below the sphere over the whole segment the air is sea-level air: two depths agree to rounding.
    deep = ps.aerial_perspective(a, (0.0, 0.0, r - 1000.0), d, 1000.0, colour, sun)
    shallow = ps.aerial_perspective(a, camera, d, 1000.0, colour, sun)
    assert all(_close(x, y, 1e-9 * y) for x, y in zip(deep, shallow)) and deep != colour
    # The planet does not occlude a surface segment: a ray dipping through the sphere keeps marching.
    through = ps.aerial_perspective(a, ps._ground_observer(a), ps.unit((1.0, 0.0, -0.01)), 5000.0, colour, sun)
    level = ps.aerial_perspective(a, ps._ground_observer(a), d, 5000.0, colour, sun)
    assert all(_close(t, l, 2e-3 * l) for t, l in zip(through, level)) and through != colour
    # The fog's altitude is clamped too: wholly below the sphere, two depths see the same sea-level fog.
    f = ps.fog(0.001, 100.0)
    fog_deep = ps.aerial_perspective(a, (0.0, 0.0, r - 1000.0), d, 1000.0, colour, sun, fog=f, horizon=(0.1, 0.2, 0.3))
    fog_shallow = ps.aerial_perspective(a, camera, d, 1000.0, colour, sun, fog=f, horizon=(0.1, 0.2, 0.3))
    assert all(_close(x, y, 1e-9 * y) for x, y in zip(fog_deep, fog_shallow)) and fog_deep != shallow
    # Rule 9's observer and L_h are lifted, never refused.
    assert ps.sky_radiance(a, camera, (0.0, 0.0, 1.0), sun) == ps.sky_radiance(a, (0.0, 0.0, r), (0.0, 0.0, 1.0), sun)
    assert ps.horizon_radiance(a, camera, d, sun) == ps.horizon_radiance(a, (0.0, 0.0, r), d, sun)
    assert ps.sun_radiance(a, camera, sun) == ps.sun_radiance(a, (0.0, 0.0, r), sun)
    assert ps.sky_irradiance(a, camera, sun, 2, 4) == ps.sky_irradiance(a, (0.0, 0.0, r), sun, 2, 4)
    assert ps.hits_ground(a, camera, (0.0, 0.0, -1.0)) and not ps.hits_ground(a, camera, (0.0, 0.0, 1.0))
    with pytest.raises(ps.SkyError):
        ps._inscatter(a, camera, d, sun, 4, True, surface=True)
    with pytest.raises(ps.SkyError):
        ps._path_end(a, camera, d)
    assert ps.below_ground_test() == (True, True, True)


def test_the_draft_walks_surface_segments_below_the_sphere(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("A surface segment is walked between its two mapped ends wherever they lie",
                   "the planet's sphere does not occlude it (the scene's own geometry does)",
                   "an altitude below 0 along it reads as 0", "the sample is lifted to the sphere",
                   "never refused (`below_ground_test`)", "The same lift applies to rule 9's observer and to rule 11's L_h",
                   "**Refusing segments below the sphere.**", "7. **Observers below sea level.**",
                   "a companion with no `physics` element and the default camera's position and lens"):
        assert phrase in text, phrase


def test_surface_segments_from_orbit_converge_with_the_default_samples():
    a = ps.atmosphere()
    obs = (0.0, 0.0, a["planet_radius"] + 400000.0)
    sun, colour, down = ps.unit((0.3, 0.2, 0.9)), (0.2, 0.3, 0.4), (0.0, 0.0, -1.0)
    coarse = ps.aerial_perspective(a, obs, down, 400000.0, colour, sun)
    fine = ps.aerial_perspective(a, obs, down, 400000.0, colour, sun, samples=1024)
    assert all(_close(c, f, 1e-4 * f) for c, f in zip(coarse, fine)) and coarse != colour
    assert ps.aerial_perspective(a, obs, down, 50000.0, colour, sun) == colour                # wholly in vacuum
    assert ps.aerial_perspective(a, obs, (0.0, 0.0, 1.0), 400000.0, colour, sun) == colour     # away from the planet
    # A rising segment from the ground clusters toward the ground end, a falling one toward the far end.
    g = ps._ground_observer(a)
    up = ps.aerial_perspective(a, g, ps.unit((1.0, 0.0, 1.0)), 50000.0, colour, sun)
    up_fine = ps.aerial_perspective(a, g, ps.unit((1.0, 0.0, 1.0)), 50000.0, colour, sun, samples=1024)
    assert all(_close(c, f, 1e-4 * f) for c, f in zip(up, up_fine))
    assert ps.orbit_segment_test() == (True, True)


def test_the_draft_states_where_a_surface_segment_samples_start(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("The segment's samples start where it enters the atmosphere", "cluster toward its lower end",
                   "`orbit_segment_test`: 16 samples within 10⁻⁴ of 1,024",
                   "the default camera's position and lens, its `far` raised past a grey wall at y = 330, 500,000 px (5 km) away"):
        assert phrase in text, phrase


# ------------------------------------------------------------------------------------ the kit (SR-86)

KIT = os.path.join(ROOT, "conformance", "tools", "physical_sky_kit.py")
_kspec = importlib.util.spec_from_file_location("physical_sky_kit", KIT)
pk = importlib.util.module_from_spec(_kspec)
_kspec.loader.exec_module(pk)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ALL_KEYS = sorted(k for keys in pk.DOCUMENTS.values() for k in keys)
GREY = (0.5, 0.5, 0.5)                # the synthetic engine's grey: what its near box radiates


def test_the_kit_camera_aims_projects_and_unprojects():
    for d in ((0.0, 0.0, 1.0), (0.3, -0.5, 0.8), (-0.9, 0.1, 0.2), (0.0, -1.0, 0.001), (0.2, 0.7, -0.6)):
        d = ps.unit(d)
        yaw, pitch = pk.aim(d)
        assert _close(pk.project(10.0, yaw, pitch, d), (pk.W / 2.0, pk.H / 2.0), 1e-6)
        for fov in (10.0, 20.0, 60.0):
            for at in ((320.5, 180.5), (10.0, 350.0), (600.25, 2.75), (0.0, 0.0)):
                back = pk.unproject(fov, yaw, pitch, at)
                assert _close(pk.project(fov, yaw, pitch, back), at, 1e-6), (d, fov, at)
    # the frame's axes: +x right, +y down; a degree is pixels_per_degree at the centre
    right = pk.project(10.0, 0.0, 0.0, ps.unit((math.tan(math.radians(1.0)), 0.0, 1.0)))
    assert _close(right, (pk.W / 2.0 + pk.pixels_per_degree(10.0), pk.H / 2.0), 1e-9)
    up = pk.project(10.0, 0.0, 0.0, ps.unit((0.0, -math.tan(math.radians(1.0)), 1.0)))
    assert up[1] < pk.H / 2.0 and _close(up[0], pk.W / 2.0, 1e-9)
    assert math.isnan(pk.project(10.0, 0.0, 0.0, (0.0, 0.0, -1.0))[0])
    # scene axes to the atmosphere's: up is +z there, east +x, north +y; the sun's direction maps to the sun's
    assert _close(pk.to_atmosphere((0.0, -1.0, 0.0)), (0.0, 0.0, 1.0))
    assert _close(pk.to_atmosphere((1.0, 0.0, 0.0)), (1.0, 0.0, 0.0)) and _close(pk.to_atmosphere((0.0, 0.0, 1.0)), (0.0, 1.0, 0.0))
    z, a = math.radians(50.0), math.radians(194.0)
    assert _close(pk.to_atmosphere(ps.sun_direction(50.0, 194.0)), (math.sin(z) * math.sin(a), math.sin(z) * math.cos(a), math.cos(z)))
    assert _close(pk.to_scene(pk.to_atmosphere((0.3, -0.4, 0.5))), (0.3, -0.4, 0.5))
    assert _close(pk.DEFAULT_EYE, (320.0, 180.0, -554.2562584), 1e-6)


def test_the_kit_writes_the_cases_the_draft_names(tmp_path):
    import xml.etree.ElementTree as ET
    paths = pk.write(str(tmp_path))
    assert sorted(paths) == ALL_KEYS and len(ALL_KEYS) == 15
    assert all(name in pk.DOCUMENTS and pk.DOCUMENTS[name][0] == name for name in pk.NAMES) and len(pk.NAMES) == 8
    docs = {}
    for key, path in paths.items():
        assert os.path.basename(path) == f"srep-0000-{key}.xml"
        root = ET.parse(path).getroot()
        docs[key] = root
        assert root.tag == "scene" and root.get("version") == "1.8"
        assert root.find("output").get("codec") == "exr-sequence" and root.find("output").get("path") == f"out/{key}_%04d.exr"
        light = root.find("lights/light")
        assert light.get("type") == "dome" and light.get("sky") == "physical" and light.get("environmentVisible") == "true"
        assert light.get("moon") == ("true" if key.startswith("sky-moon") else "false")
        cam = root.find("composition/camera")
        assert cam.get("x") is not None and cam.get("y") is not None and cam.get("z") is not None   # never the implicit eye
        assert cam.get("projection") is None
        for box in root.findall("composition/object3D"):
            assert box.get("primitive") == "box" and box.get("material") == "grey"
        if root.findall("composition/object3D"):
            material = root.find("materials/material")
            assert material.get("id") == "grey" and material.get("unlit") == "true" and material.get("baseColor") == pk.GREY
    spa = docs["sky-spa"].find("lights/light")
    assert spa.get("date") == "2003-10-17T12:30:30-07:00" and spa.get("latitude") == "39.742476"
    assert spa.get("longitude") == "-105.1786" and spa.get("altitude") == "1830.14" and spa.get("pressure") == "820.0"
    assert spa.get("temperature") == "11.0" and spa.get("deltaT") == "67.0"
    assert docs["sky-day"].find("lights/light").get("date") == pk.DAY_DATE
    assert float(docs["sky-day"].find("composition/camera").get("pitch")) == pk.DAY_PITCH
    assert float(docs["sky-day-horizon"].find("composition/camera").get("yaw")) == 180.0
    for key, elevation in (("sky-sunset", 1.0), ("sky-sunset-below", -1.0)):
        light = docs[key].find("lights/light")
        sun = ps.sun_from_document(light.get("date"), float(light.get("latitude")), float(light.get("longitude")))
        assert abs(90.0 - sun["zenith"] - elevation) < 0.002, (key, sun["zenith"])
        assert light.get("date").startswith(pk.SUNSET_DAY + "T18:")
    assert docs["sky-sunset-noon"].find("lights/light").get("date") == pk.NOON_DATE
    orbit = docs["sky-orbit"]
    assert orbit.find("lights/light").get("altitude") == "400000.0" and orbit.find("physics").get("pixelsPerMeter") == "1"
    assert [float(orbit.find("composition/camera").get(c)) for c in "xyz"] == [0.0, 0.0, 0.0]
    aerial = docs["sky-aerial"]
    assert aerial.find("physics").get("pixelsPerMeter") == "1" and len(aerial.findall("composition/object3D")) == 6
    assert float(aerial.find("composition/camera").get("far")) > max(pk.AERIAL_DISTANCES)
    zs = sorted(float(b.get("z")) - pk.BOX_DEPTH / 2.0 for b in aerial.findall("composition/object3D"))
    assert zs == sorted([pk.NEAR] + list(pk.AERIAL_DISTANCES))
    default = docs["sky-aerial-default"]
    cam = default.find("composition/camera")
    assert default.find("physics") is None and cam.get("fov") is None and cam.get("far") == "600000"
    assert (float(cam.get("x")), float(cam.get("y"))) == (320.0, 180.0) and _close(float(cam.get("z")), pk.DEFAULT_EYE[2])
    wall = [b for b in default.findall("composition/object3D") if b.get("id") == "wall"][0]
    assert float(wall.get("y")) == 330.0 and abs(float(wall.get("z")) - pk.BOX_DEPTH / 2.0 - float(cam.get("z")) - 500000.0) < 1e-6
    for key in ("sky-fog", "sky-fog-high", "sky-fog-aerial"):
        light = docs[key].find("lights/light")
        assert light.get("fogDensity") == "0.001" and light.get("fogHeight") == "100.0" and light.get("altitude") == "0.0"
        assert light.get("aerialPerspective") == ("true" if key == "sky-fog-aerial" else "false")
        assert docs[key].find("physics").get("pixelsPerMeter") == "1"
        wall = [b for b in docs[key].findall("composition/object3D") if b.get("id") == "wall"][0]
        assert float(wall.get("z")) - pk.BOX_DEPTH / 2.0 == 1000.0
        assert float(wall.get("y")) == float(docs[key].find("composition/camera").get("y")) == (-500.0 if key == "sky-fog-high" else 0.0)
    assert docs["sky-moon"].find("lights/light").get("date") == pk.FULL_MOON
    assert docs["sky-moon-new"].find("lights/light").get("date") == pk.NEW_MOON
    seek = docs["sky-seek"]
    assert seek.find("project").get("fps") == "24" and seek.find("project").get("duration") == "2"
    keys = seek.findall("lights/light/animate/key")
    assert seek.find("lights/light/animate").get("property") == "date" and len(keys) == 49
    assert keys[0].get("value") == "2026-06-20T18:00:00Z" and keys[-1].get("value") == "2026-06-21T18:00:00Z"
    assert keys[40].get("value") == "2026-06-21T14:00:00Z" and abs(float(keys[40].get("time")) - 39.5 / 24.0) < 1e-6
    assert float(keys[0].get("time")) == 0.0 and abs(float(keys[1].get("time")) - 0.5 / 24.0) < 1e-6
    assert float(keys[-1].get("time")) < 2.0 and all(float(k.get("time")) < float(n.get("time")) for k, n in zip(keys, keys[1:]))
    assert seek.find("lights/light").get("date") == keys[0].get("value")
    assert pk.documents() == pk.documents()


def test_the_kit_expectations_come_from_the_reference():
    a = ps.atmosphere()
    exp = pk.expectations()
    spa = exp["sky-spa"]
    assert round(spa["zenith"], 5) == 50.11162 and round(spa["azimuth"], 5) == 194.34024
    assert _close(spa["at"], (pk.W / 2.0, pk.H / 2.0), 1e-6)
    day = exp["sky-day"]
    light = pk.lights()["sky-day"]
    sun = pk.to_atmosphere(ps.sun_from_document(pk.DAY_DATE, 0.0, 0.0)["direction"])
    assert _close(day["zenith"], ps.sky_radiance(a, (0.0, 0.0, a["planet_radius"]), pk.to_atmosphere(day["zenith_direction"]), sun))
    assert math.degrees(math.acos(-day["zenith_direction"][1])) < 1.1 and abs(-day["horizon_direction"][1]) < 0.02
    assert day["zenith"][2] / day["zenith"][0] > day["horizon"][2] / day["horizon"][0]
    assert sum(day["horizon"]) > sum(day["zenith"])
    assert light["latitude"] == 0.0 and light["longitude"] == 0.0
    sunset = exp["sky-sunset"]
    assert abs(sunset["sky-sunset"]["elevation"] - 1.0) < 0.002 and abs(sunset["sky-sunset-below"]["elevation"] + 1.0) < 0.002
    assert sunset["sky-sunset-noon"]["elevation"] > 88.0
    disc, noon = sunset["sky-sunset"]["disc"], sunset["sky-sunset-noon"]["disc"]
    assert disc[0] / disc[2] > 10.0 * noon[0] / noon[2] and noon[0] > 1000.0
    assert sunset["sky-sunset-below"]["disc"] == (0.0, 0.0, 0.0)
    orbit = exp["sky-orbit"]
    obs = (0.0, 0.0, a["planet_radius"] + pk.ORBIT_ALTITUDE)
    limb = ps.limb_direction(a, obs)
    assert _close(orbit["ground"], math.degrees(math.acos(-limb[2])), 1e-9)
    assert _close(orbit["top"], math.degrees(math.asin(a["top_radius"] / ps._norm(obs))), 1e-9)
    assert orbit["ground"] < orbit["edge"] < orbit["top"] and orbit["peak"] > 0.1
    assert min(orbit["angles"]) < orbit["ground"] - 1.0 and max(orbit["angles"]) > orbit["top"] + 1.0
    aerial = exp["sky-aerial"]
    row = aerial["sky-aerial"]
    assert row["fog"] is None and row["aerial"] and _close(row["observer"], (0.0, 0.0, a["planet_radius"]))
    assert [round(b["length"]) for b in row["boxes"].values()] == [10, 100, 5003, 10000, 20012, 50122]
    colours = [pk.seen(a, row, b, GREY) for n, b in row["boxes"].items() if n != "near"]
    horizon = [ps.sky_radiance(a, row["observer"], (b["direction"][0], b["direction"][1], 0.0), row["sun"])
               for n, b in row["boxes"].items() if n != "near"]
    gaps = [math.dist(c, h) for c, h in zip(colours, horizon)]
    assert all(x > y for x, y in zip(gaps, gaps[1:]))
    default = aerial["sky-aerial-default"]
    assert _close(default["observer"], (3.2, -5.542562584, a["planet_radius"] - 1.8), 1e-6)
    wall = default["boxes"]["wall"]
    assert _close(wall["length"], 5000.0, 1e-6) and _close(wall["direction"], (0.0, 1.0, 0.0))
    shift = [1.0 - c / 0.5 for c in pk.seen(a, default, wall, GREY)]
    assert all(0.05 < s < 0.09 for s in shift), shift
    assert _close(pk.material_grey(a, default, pk.seen(a, default, default["boxes"]["near"], GREY)), GREY, 1e-9)
    fog = exp["sky-fog"]
    f = ps.fog(0.001, 100.0)
    for key, h in (("sky-fog", 0.0), ("sky-fog-high", 500.0)):
        wall = fog[key]["boxes"]["wall"]
        assert wall["h0"] == wall["h1"] == h and wall["length"] == 1000.0 and not fog[key]["aerial"]
        expected = ps.fogged(GREY, f, h, h, 1000.0, wall["horizon"])
        assert _close(pk.seen(a, fog[key], wall, GREY), expected)
        t = math.exp(-1.0) if h == 0.0 else math.exp(-0.001 * 1000.0 * math.exp(-5.0))
        assert _close(expected, tuple(0.5 * t + (1.0 - t) * wall["horizon"][c] for c in range(3)))
    wall = fog["sky-fog-aerial"]["boxes"]["wall"]
    assert fog["sky-fog-aerial"]["aerial"]
    assert _close(pk.seen(a, fog["sky-fog-aerial"], wall, GREY),
                  ps.aerial_perspective(a, fog["sky-fog-aerial"]["observer"], wall["direction"], 1000.0, GREY,
                                        fog["sky-fog-aerial"]["sun"], fog=f, horizon=wall["horizon"]))
    moon = exp["sky-moon"]
    assert abs(moon["sky-moon"]["angular_diameter"] - 0.50) < 0.02 and moon["sky-moon"]["illuminated"] > 0.999
    assert round(moon["sky-moon"]["zenith"], 3) == 27.717 and round(moon["sky-moon"]["azimuth"], 3) == 307.748
    assert moon["sky-moon-new"]["illuminated"] < 1e-3 and max(moon["sky-moon-new"]["radiance"]) < 1e-6
    assert all(_close(m["at"], (pk.W / 2.0, pk.H / 2.0), 1e-6) for m in moon.values())
    assert exp["sky-seek"] == {}


def _fill_disc(frame, at, radius_px, rgb):
    h, w, _ = frame.shape
    ys, xs = np.mgrid[0:h, 0:w]
    frame[(xs + 0.5 - at[0]) ** 2 + (ys + 0.5 - at[1]) ** 2 <= radius_px ** 2] = rgb


def _square(frame, at, half, rgb):
    x, y = int(math.floor(at[0])), int(math.floor(at[1]))
    frame[max(0, y - half):y + half + 1, max(0, x - half):x + half + 1] = rgb


def _frames(exp):
    """Synthetic frames of every document from the expectations (what a correct engine renders)."""
    a = ps.atmosphere()
    f = {}

    def blank(value=0.0):
        return np.full((pk.H, pk.W, 3), value, dtype=np.float64)
    f["sky-spa"] = blank(0.05)
    _fill_disc(f["sky-spa"], exp["sky-spa"]["at"], ps.SUN_RADIUS_DEG * pk.pixels_per_degree(pk.FOV["sky-spa"]), (50.0,) * 3)
    f["sky-day"], f["sky-day-horizon"] = blank(), blank()
    f["sky-day"][:] = exp["sky-day"]["zenith"]
    f["sky-day-horizon"][:] = exp["sky-day"]["horizon"]
    ppd = pk.pixels_per_degree(pk.FOV["sky-sunset"])
    for key in pk.DOCUMENTS["sky-sunset"]:
        e = exp["sky-sunset"][key]
        f[key] = blank()
        horizon_row = pk.H / 2.0 + e["elevation"] * ppd            # the horizon lies below a sun above it
        rows = np.arange(pk.H)[:, None, None] + 0.5
        f[key][:] = np.where(rows < horizon_row, np.array([0.1, 0.15, 0.3]), 0.0)
        if e["elevation"] > 0.0:
            _fill_disc(f[key], e["at"], ps.SUN_RADIUS_DEG * ppd, e["disc"])
    o = exp["sky-orbit"]
    fov, yaw, pitch, _ = pk.cameras(pk.lights())["sky-orbit"]
    angles = [math.degrees(math.acos(pk.unproject(fov, yaw, pitch, (pk.W / 2.0 + 0.5, row + 0.5))[1])) for row in range(pk.H)]
    order = np.argsort(o["angles"])
    lum = np.interp(angles, np.asarray(o["angles"])[order], np.asarray(o["luminance"])[order])
    f["sky-orbit"] = np.repeat(np.repeat(lum[:, None, None], pk.W, axis=1), 3, axis=2)
    for name in ("sky-aerial", "sky-fog"):
        for key in pk.DOCUMENTS[name]:
            seg = exp[name][key]
            f[key] = blank()
            for box_name, box in seg["boxes"].items():
                _square(f[key], box["at"], 3, pk.seen(a, seg, box, GREY))
    m = exp["sky-moon"]["sky-moon"]
    f["sky-moon"] = blank()
    _fill_disc(f["sky-moon"], m["at"], m["angular_diameter"] / 2.0 * pk.pixels_per_degree(pk.FOV["sky-moon"]), m["radiance"])
    f["sky-moon-new"] = blank(0.3)
    f["sky-moon-new"][:, :, 2] = 0.4
    gradient = np.linspace(0, 255, pk.W)[None, :, None].repeat(pk.H, axis=0).repeat(3, axis=2)
    f["seek-alone"] = np.concatenate([gradient, np.full((pk.H, pk.W, 1), 255.0)], axis=2)
    f["seek-played"] = f["seek-alone"].copy()
    return f


def test_the_kit_measures_each_case():
    exp = pk.expectations()
    frames = _frames(exp)
    for name in pk.NAMES:
        r = pk.measure(name, frames, exp)
        assert r["pass"], (name, r)
    good = pk.measure("sky-moon", frames, exp)
    assert abs(good["diameter_deg"] - 0.4912) < 0.01 and good["off_deg"] < 0.01, good
    assert pk.measure("sky-orbit", frames, exp)["edge_off_deg"] < 0.01
    assert pk.measure("sky-aerial", frames, exp)["sky-aerial"]["worst_rel"] < 1e-9
    bad = dict(frames)
    bad["sky-spa"] = np.roll(frames["sky-spa"], 5, axis=1)                   # the disc 0.16 degrees off
    assert not pk.measure("sky-spa", bad, exp)["pass"]
    bad["sky-day"] = frames["sky-day"] * 1.05
    assert not pk.measure("sky-day", bad, exp)["pass"]
    swapped = dict(frames, **{"sky-day": frames["sky-day-horizon"], "sky-day-horizon": frames["sky-day"]})
    assert not pk.measure("sky-day", swapped, exp)["pass"]
    with_disc = dict(frames)
    with_disc["sky-sunset-below"] = frames["sky-sunset-below"].copy()
    _fill_disc(with_disc["sky-sunset-below"], exp["sky-sunset"]["sky-sunset-below"]["at"], 10.0, exp["sky-sunset"]["sky-sunset"]["disc"])
    assert not pk.measure("sky-sunset", with_disc, exp)["pass"]
    white = dict(frames, **{"sky-sunset": frames["sky-sunset-noon"]})          # a sunset disc as white as noon's
    assert not pk.measure("sky-sunset", white, exp)["pass"]
    bad["sky-orbit"] = np.roll(frames["sky-orbit"], 20, axis=0)                # the shell 0.3 degrees off
    assert not pk.measure("sky-orbit", bad, exp)["pass"]
    glow = dict(frames)
    glow["sky-orbit"] = frames["sky-orbit"] + 1e-3                              # light above the atmosphere
    assert not pk.measure("sky-orbit", glow, exp)["pass"]
    bad["sky-aerial"] = frames["sky-aerial"] * 1.03
    assert not pk.measure("sky-aerial", bad, exp)["pass"]
    bare = dict(frames)
    bare["sky-aerial-default"] = frames["sky-aerial-default"].copy()           # the wall as grey as the near box
    _square(bare["sky-aerial-default"], exp["sky-aerial"]["sky-aerial-default"]["boxes"]["wall"]["at"], 3, GREY)
    assert not pk.measure("sky-aerial", bare, exp)["pass"]
    clear = dict(frames)
    clear["sky-fog"] = frames["sky-fog"].copy()
    _square(clear["sky-fog"], exp["sky-fog"]["sky-fog"]["boxes"]["wall"]["at"], 3, GREY)
    assert not pk.measure("sky-fog", clear, exp)["pass"]
    big = dict(frames)
    big["sky-moon"] = np.zeros_like(frames["sky-moon"])
    m = exp["sky-moon"]["sky-moon"]
    _fill_disc(big["sky-moon"], m["at"], (m["angular_diameter"] / 2.0 + 0.02) * pk.pixels_per_degree(10.0), m["radiance"])
    assert not pk.measure("sky-moon", big, exp)["pass"]
    bad["sky-moon"] = np.roll(frames["sky-moon"], 20, axis=1)                  # 0.3 degrees off
    assert not pk.measure("sky-moon", bad, exp)["pass"]
    lit = dict(frames)
    lit["sky-moon-new"] = frames["sky-moon-new"].copy()
    _fill_disc(lit["sky-moon-new"], exp["sky-moon"]["sky-moon-new"]["at"], 15.0, (2.0, 2.0, 2.0))
    assert not pk.measure("sky-moon", lit, exp)["pass"]
    bad["seek-played"] = np.roll(frames["seek-played"], 1, axis=1)
    assert not pk.measure("sky-seek", bad, exp)["pass"]
    with pytest.raises(ValueError):
        pk.measure("sky-nothing", frames, exp)


def _fake_engine(frames, refuse=()):
    """An exec that writes the synthetic frame of each document the kit encodes or renders, and refuses the named
    documents with the given code."""
    def exec(cmd, capture_output, text):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        doc = cmd[2]
        key = os.path.basename(doc)[len("srep-0000-"):-len(".xml")]
        if key in refuse:
            R.returncode, R.stderr = 1, "error[%s] (dome): refused\n" % refuse[key]
            return R
        if cmd[1] == "encode":
            out_dir = cmd[cmd.index("--out-dir") + 1]
            os.makedirs(os.path.join(out_dir, "out"), exist_ok=True)
            pk.sk.write_exr(os.path.join(out_dir, "out", f"{key}_0000.exr"), frames[key])
            return R
        assert cmd[1] == "render" and key == "sky-seek"
        out = cmd[cmd.index("-o") + 1]
        if "-f" in cmd:
            targets = [out]
        else:
            last = int(cmd[cmd.index("--frames") + 1].split("..=")[1])
            targets = [out % f for f in range(last + 1)]
        img = Image.fromarray(frames["seek-alone"].astype(np.uint8), "RGBA")
        for path in targets:
            img.save(path)
        return R
    return exec


def test_the_kit_runs_an_engine_and_reports_every_case(tmp_path):
    exp = pk.expectations()
    frames = _frames(exp)
    report = pk.run("engine", str(tmp_path / "ok"), exec=_fake_engine(frames))
    assert list(report) == pk.NAMES and all(r["pass"] for r in report.values()), report
    assert os.path.exists(tmp_path / "ok" / "sky-seek-seq-0040.png") and os.path.exists(tmp_path / "ok" / "srep-0000-sky-fog-high.xml")
    refused = pk.run("engine", str(tmp_path / "refused"), exec=_fake_engine(frames, refuse={"sky-moon-new": "S06", "sky-seek": "S01"}))
    assert not refused["sky-moon"]["pass"] and "S06" in refused["sky-moon"]["error"] and "sky-moon-new" in refused["sky-moon"]["error"]
    assert not refused["sky-seek"]["pass"] and "S01" in refused["sky-seek"]["error"]
    assert sum(r["pass"] for r in refused.values()) == 6
    text = pk.table(report)
    assert text.splitlines()[0] == "| Case | Measured | Pass |" and "| sky-spa |" in text and text.count("| yes |") == 8
    assert pk.main(["--write", str(tmp_path / "written")]) == 0 and os.path.exists(tmp_path / "written" / "srep-0000-sky-seek.xml")


def test_the_draft_describes_the_kit(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("`conformance/tools/physical_sky_kit.py`", "`scene-render encode`", "exr-sequence", "`sky-day-horizon`",
                   "`sky-sunset-noon`", "`sky-sunset-below`", "`sky-aerial-default`", "`sky-fog-high`", "`sky-fog-aerial`",
                   "`sky-moon-new`", '`environmentVisible="true"`', "near box", "`unproject`", "(320, 180, −554.26",
                   "one key per frame", "14:00 UTC", "strings are discrete", "1 % of its peak"):
        assert phrase in text, phrase
    assert "SREP 4's" not in text            # SREP 4 is semantic versioning, not animation
