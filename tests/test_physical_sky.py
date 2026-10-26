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
    with pytest.raises(ps.SkyError):
        ps.sky_radiance(a, (0.0, 0.0, a["planet_radius"] - 1.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0))
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
