"""Tests of the draft SREP "Add planets and the Sun as bodies" (srep/srep-0000-planets.md) and of its reference
implementation conformance/tools/planets_reference.py (SP3 of SREP 12, SRC-46).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "planets_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-planets.md")
SKY = os.path.join(ROOT, "conformance", "tools", "physical_sky_reference.py")
TIME_FRAMES = os.path.join(ROOT, "conformance", "tools", "time_frames_reference.py")

_spec = importlib.util.spec_from_file_location("planets_reference", MODULE)
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


EARTH = 6378.1366
# the conformance kit's implicit camera: 640 x 360, 60 degree horizontal field, focal length 554.256 pixels
F = (640 / 2) / math.tan(math.radians(60) / 2)


def _camera(eye, target=(0.0, 0.0, 0.0), up=(0.0, 0.0, 1.0)):
    return pl.camera(eye, target, up, F)


# ------------------------------------------------------------------------------------ rule 1: bodies, radii, textures


def test_the_iau_radii_and_flattening():
    assert pl.RADII[399] == (6378.1366, 6356.7519) and pl.RADII[10] == (696000.0, 696000.0)
    assert pl.RADII[699] == (60268.0, 54364.0) and pl.RADII[301] == (1737.4, 1737.4)
    assert set(pl.RADII) == {10, 199, 299, 399, 499, 599, 699, 799, 899, 301}
    assert _close(pl.flattening(399), (6378.1366 - 6356.7519) / 6378.1366)
    assert pl.flattening(299) == 0.0
    assert _close(pl.flattening(699), 0.09796, 1e-5)
    with pytest.raises(pl.PlanetError):
        pl.flattening(4)


def test_scene_radius_follows_pixels_per_meter():
    assert _close(pl.scene_radius(399, 1e-6), 6.3781366)
    assert _close(pl.scene_radius(10, 1e-9), 0.696)
    assert _close(pl.scene_radius(399, 1e-6, radius_km=6371.0), 6.371)
    with pytest.raises(pl.PlanetError):
        pl.scene_radius(399, 0.0)


def test_texture_uv_puts_the_prime_meridian_at_the_centre():
    assert _close(pl.texture_uv(0.0, 0.0), (0.5, 0.5))
    assert _close(pl.texture_uv(-180.0, 90.0), (0.0, 0.0))
    assert _close(pl.texture_uv(90.0, -90.0), (0.75, 1.0))
    assert _close(pl.texture_uv(180.0, 0.0), (0.0, 0.5))  # the seam wraps
    assert _close(pl.texture_uv(-90.0, 45.0), (0.25, 0.25))
    with pytest.raises(pl.PlanetError):
        pl.texture_uv(0.0, 91.0)


def test_engine_uv_is_the_texture_uv_shifted_by_a_half():
    for lon, lat in ((0.0, 0.0), (90.0, 30.0), (-120.0, -60.0), (179.0, 89.0)):
        u, w = pl.engine_uv(lon, lat)
        tu, tv = pl.texture_uv(lon, lat)
        assert _close(((u + 0.5) % 1.0, w), (tu, tv), 1e-9)
    # the engine's UV sphere (prim.rs): n = (sin(pi w) cos(2 pi u), -cos(pi w), sin(pi w) sin(2 pi u)), poles on y
    n = pl.engine_normal(*pl.engine_uv(90.0, 0.0))
    assert _close(n, (0.0, 0.0, 1.0), 1e-9)  # longitude 90 E is the scene's +z
    assert _close(pl.engine_normal(*pl.engine_uv(0.0, 90.0)), (0.0, -1.0, 0.0), 1e-9)  # the north pole is up (-y)
    assert _close(pl.engine_normal(*pl.engine_uv(0.0, 0.0)), (1.0, 0.0, 0.0), 1e-9)
    assert _close(pl.scene_from_body(pl.body_direction(90.0, 0.0)), (0.0, 0.0, 1.0), 1e-9)


def test_surface_points_of_the_spheroid():
    a, c = pl.RADII[399]
    assert _close(pl.surface_point(a, pl.flattening(399), 0.0, 0.0), (a, 0.0, 0.0))
    assert _close(pl.surface_point(a, pl.flattening(399), 0.0, 90.0), (0.0, 0.0, c), 1e-9)
    p = pl.surface_point(a, pl.flattening(399), 45.0, 45.0)
    assert _close((p[0] / a) ** 2 + (p[1] / a) ** 2 + (p[2] / c) ** 2, 1.0)
    n = pl.surface_normal(a, pl.flattening(399), p)
    assert _close(pl.norm(n), 1.0)
    assert math.degrees(pl.angle(n, pl.unit(p))) < 0.2  # geodetic and geocentric normals differ by under 0.2 degrees
    assert pl.surface_normal(a, 0.0, (a, 0.0, 0.0)) == (1.0, 0.0, 0.0)
    with pytest.raises(pl.PlanetError):
        pl.surface_point(a, 1.0, 0.0, 0.0)


# ------------------------------------------------------------------------------------ rule 2: limb and terminator


def test_the_limb_circle_from_a_camera():
    eye = (0.0, -4.0 * EARTH, 0.0)
    limb = pl.limb(eye, EARTH)
    assert _close(limb["angular_radius"], math.degrees(math.asin(0.25)))
    assert _close(limb["centre"], (0.0, -EARTH * 0.25, 0.0), 1e-6)
    assert _close(limb["radius"], EARTH * math.sqrt(1 - 1 / 16.0), 1e-6)
    pts = pl.limb_points(eye, EARTH, 36)
    assert len(pts) == 36
    for p in pts:
        assert _close(pl.norm(p), EARTH, 1e-6)  # on the sphere
        assert _close(pl.dot(pl.sub(p, eye), p), 0.0, 1e-3)  # tangent to the line of sight
    with pytest.raises(pl.PlanetError):
        pl.limb((0.0, EARTH * 0.5, 0.0), EARTH)


def test_the_terminator_is_the_great_circle_normal_to_the_sun():
    s = pl.unit((1.0, 2.0, 3.0))
    pts = pl.terminator_points(s, EARTH, 24)
    for p in pts:
        assert _close(pl.norm(p), EARTH, 1e-6) and _close(pl.dot(p, s), 0.0, 1e-6)
    assert _close(pl.terminator_half_angle(EARTH, 149597870.7), 90.0 - math.degrees(math.asin(EARTH / 149597870.7)))
    assert pl.terminator_half_angle(EARTH, 149597870.7) < 90.0
    near = pl.terminator_points(s, EARTH, 8, sun_distance=10.0 * EARTH)
    for p in near:
        assert pl.dot(p, s) > 0.0  # the lit cap is smaller than a hemisphere for a near sun
        assert _close(math.degrees(pl.angle(p, s)), pl.terminator_half_angle(EARTH, 10.0 * EARTH), 1e-9)
    with pytest.raises(pl.PlanetError):
        pl.terminator_half_angle(EARTH, EARTH)


def test_lit_and_phase():
    s = (1.0, 0.0, 0.0)
    assert pl.lit((EARTH, 0.0, 0.0), s) and not pl.lit((-EARTH, 0.0, 0.0), s)
    assert pl.lit(pl.unit((1.0, 1.0, 0.0)), s)
    assert _close(pl.phase_angle((0.0, 10.0, 0.0), s), 90.0)
    assert _close(pl.phase_angle((10.0, 0.0, 0.0), s), 0.0) and _close(pl.phase_angle((-10.0, 0.0, 0.0), s), 180.0)
    assert _close(pl.illuminated_fraction(0.0), 1.0) and _close(pl.illuminated_fraction(180.0), 0.0)
    assert _close(pl.illuminated_fraction(90.0), 0.5) and _close(pl.illuminated_fraction(60.0), 0.75)
    with pytest.raises(pl.PlanetError):
        pl.illuminated_fraction(181.0)


def test_the_cusps_lie_on_both_the_limb_and_the_terminator():
    eye = (0.0, -5.0 * EARTH, 0.0)
    s = pl.unit((1.0, -1.0, 0.0))
    a, b = pl.cusps(eye, s, EARTH)
    for p in (a, b):
        assert _close(pl.norm(p), EARTH, 1e-6)
        assert _close(pl.dot(p, s), 0.0, 1e-6)
        assert _close(pl.dot(pl.sub(p, eye), p), 0.0, 1e-3)
    assert _close(a[2], -b[2], 1e-6) and a[2] > 0.0  # symmetric about the plane of eye and sun
    assert pl.cusps(eye, (0.0, 1.0, 0.0), EARTH) is None  # sun behind the camera: the disc is fully lit, no cusp seen
    assert pl.cusps(eye, (0.0, -1.0, 0.0), EARTH) is None


def test_the_projection_of_the_limb_is_a_circle_of_the_expected_radius():
    eye = (0.0, -4.0 * EARTH, 0.0)
    cam = _camera(eye)
    r = F * math.tan(math.radians(pl.limb(eye, EARTH)["angular_radius"]))
    for p in pl.limb_points(eye, EARTH, 48):
        x, y = pl.project(cam, p)
        assert _close(math.hypot(x, y), r, 1e-6)
    assert _close(pl.project(cam, (0.0, 0.0, 0.0)), (0.0, 0.0), 1e-9)
    assert pl.project(cam, (0.0, 0.0, EARTH))[1] < 0.0  # up is toward the top of the frame (y down in pixels)
    assert pl.project(cam, (EARTH, 0.0, 0.0))[0] > 0.0  # +x of a camera looking along +y with z up is to the right
    assert _close(pl.limb_pixel_radius(cam, eye, EARTH), r)
    with pytest.raises(pl.PlanetError):
        pl.project(cam, eye)


def test_the_projected_terminator_and_cusps():
    eye = (0.0, -5.0 * EARTH, 0.0)
    cam = _camera(eye)
    s = pl.unit((1.0, -1.0, 0.0))
    r = pl.limb_pixel_radius(cam, eye, EARTH)
    for p in pl.cusps(eye, s, EARTH):
        x, y = pl.project(cam, p)
        assert _close(math.hypot(x, y), r, 1e-6)
    visible = [pl.project(cam, p) for p in pl.terminator_points(s, EARTH, 360) if pl.visible(eye, p, EARTH)]
    assert 100 < len(visible) < 260
    for x, y in visible:
        assert math.hypot(x, y) <= r + 1e-6
    # the lit side faces +x: the visible terminator bends into the left half with its cusps on the circle
    assert max(x for x, _ in visible) < r * 0.1
    assert pl.visible(eye, (0.0, -EARTH, 0.0), EARTH) and not pl.visible(eye, (0.0, EARTH, 0.0), EARTH)


def test_the_lit_pixel_fraction_of_a_disc_matches_the_phase():
    eye = (0.0, -200.0 * EARTH, 0.0)  # far enough that perspective moves the lit fraction by under 0.2 %
    for s, want in (((0.0, -1.0, 0.0), 1.0), ((1.0, 0.0, 0.0), 0.5), (pl.unit((1.0, -1.0, 0.0)), 0.5 + math.sqrt(0.5) / 2)):
        got = pl.lit_fraction(eye, s, EARTH, 400)
        assert _close(got, want, 0.01), (s, got, want)
        assert _close(got, pl.illuminated_fraction(pl.phase_angle(eye, s)), 0.01)


# ------------------------------------------------------------------------------------ rule 3: shading, night lights, limb darkening


def test_day_and_night_weights():
    s = (0.0, 0.0, 1.0)
    assert pl.day_weight((0.0, 0.0, 1.0), s) == 1.0 and pl.day_weight((0.0, 0.0, -1.0), s) == 0.0
    assert _close(pl.day_weight(pl.unit((1.0, 0.0, 1.0)), s), math.sqrt(0.5))
    assert pl.night_weight((0.0, 0.0, -1.0), s, 6.0) == 1.0 and pl.night_weight((0.0, 0.0, 1.0), s, 6.0) == 0.0
    assert _close(pl.night_weight((1.0, 0.0, 0.0), s, 6.0), 0.5)
    below = pl.unit((math.cos(math.radians(-6.0)), 0.0, math.sin(math.radians(-6.0))))
    assert _close(pl.night_weight(below, s, 6.0), 1.0, 1e-9)
    half = pl.unit((math.cos(math.radians(-3.0)), 0.0, math.sin(math.radians(-3.0))))
    assert _close(pl.night_weight(half, s, 6.0), 0.75, 1e-9)
    with pytest.raises(pl.PlanetError):
        pl.night_weight(s, s, 0.0)


def test_hestroffer_magnan_limb_darkening():
    assert _close(pl.limb_alpha(550.0), -0.023 + 0.292 / 0.55)
    assert _close(pl.limb_alpha(1000.0), 0.269)
    r, g, b = (pl.limb_alpha(nm) for nm in pl.CHANNEL_WAVELENGTHS_NM)
    assert b > g > r > 0.0  # bluer channels darken more toward the limb
    assert pl.CHANNEL_WAVELENGTHS_NM == (610.0, 550.0, 465.0)
    assert pl.limb_darkening(1.0, 0.5) == 1.0 and pl.limb_darkening(0.0, 0.5) == 0.0
    assert _close(pl.limb_darkening(0.25, 0.5), 0.5)
    assert _close(pl.disc_average(0.5), 0.8) and _close(pl.disc_average(0.0), 1.0)
    for alpha in (0.3, 0.5, 0.8):
        assert _close(pl.disc_average_numeric(alpha, 4000), pl.disc_average(alpha), 1e-4)
    assert _close(pl.solar_disc(1.0), (1.0, 1.0, 1.0)) and all(c == 0.0 for c in pl.solar_disc(0.0))
    edge = pl.solar_disc(0.1)
    assert edge[0] > edge[1] > edge[2] > 0.0  # the limb is redder
    for bad in (400.0, 2600.0):
        with pytest.raises(pl.PlanetError):
            pl.limb_alpha(bad)
    with pytest.raises(pl.PlanetError):
        pl.limb_darkening(1.1, 0.5)


def test_the_mu_of_a_disc_pixel():
    eye = (0.0, -10.0 * EARTH, 0.0)
    cam = _camera(eye)
    r = pl.limb_pixel_radius(cam, eye, EARTH)
    assert _close(pl.disc_mu(cam, eye, EARTH, 0.0, 0.0), 1.0, 1e-9)
    assert _close(pl.disc_mu(cam, eye, EARTH, r, 0.0), 0.0, 1e-6)
    assert 0.0 < pl.disc_mu(cam, eye, EARTH, r * 0.5, 0.0) < 1.0
    assert pl.disc_mu(cam, eye, EARTH, r * 1.01, 0.0) is None


# ------------------------------------------------------------------------------------ rule 4: clouds


def test_cloud_shell_and_shadow_parallax():
    s = (0.0, 0.0, 1.0)
    top = (0.0, 0.0, EARTH)
    q = pl.cloud_shadow_point(top, s, EARTH, 0.004)
    assert _close(q, (0.0, 0.0, EARTH * 1.004), 1e-6)  # at the subsolar point the shadow comes from straight above
    lat = 60.0  # the sun, along the pole, is 60 degrees above the horizon here: zenith angle 30
    p = pl.surface_point(EARTH, 0.0, 0.0, lat)
    q = pl.cloud_shadow_point(p, s, EARTH, 0.004)
    assert _close(pl.norm(q), EARTH * 1.004, 1e-6)
    shift = math.degrees(pl.angle(p, q))
    # small-angle estimate: the cloud texel is displaced toward the sun by h tan(zenith) radians at the surface
    assert _close(shift, math.degrees(0.004 * math.tan(math.radians(30.0))), 0.02)
    assert pl.cloud_shadow_point(pl.surface_point(EARTH, 0.0, 0.0, -30.0), s, EARTH, 0.004) is None  # night side: no shadow
    assert _close(pl.cloud_longitude(0.0, 1.5), 0.0) and _close(pl.cloud_longitude(100.0, 1.5), 150.0)
    assert _close(pl.cloud_longitude(400.0, 1.5), 240.0)  # wraps into [0, 360)
    u, v = pl.clouds_uv(10.0, 20.0, 100.0, 1.5)
    assert _close((u, v), pl.texture_uv(10.0 - 150.0, 20.0), 1e-9)  # the layer rotates eastward: the texel seen moves west
    with pytest.raises(pl.PlanetError):
        pl.cloud_shadow_point(top, s, EARTH, 0.0)


# ------------------------------------------------------------------------------------ rule 5: rings


def test_ring_geometry_and_shadows():
    R = pl.RADII[699][0]
    inner, outer = 1.239, 2.269
    strip = [(0.6, 0.6, 0.5, 0.2), (0.8, 0.75, 0.6, 0.9), (0.0, 0.0, 0.0, 0.0), (0.9, 0.85, 0.7, 0.6)]
    assert pl.ring_sample(strip, 1.239, inner, outer) == strip[0]
    assert pl.ring_sample(strip, 2.269, inner, outer) == strip[-1]
    mid = pl.ring_sample(strip, inner + (outer - inner) / 6.0, inner, outer)
    assert _close(mid, tuple((a + b) / 2 for a, b in zip(strip[0], strip[1])))
    assert pl.ring_sample(strip, 1.0, inner, outer) is None and pl.ring_sample(strip, 2.5, inner, outer) is None
    # sun 26.7 degrees above the ring plane (Saturn's solstice): the planet's shadow on the rings reaches R / sin(26.7)
    beta = 26.7
    s = (math.cos(math.radians(beta)), 0.0, math.sin(math.radians(beta)))
    far = R / math.sin(math.radians(beta))
    assert pl.ring_shadowed_by_planet((-far * 0.999, 0.0, 0.0), s, R)
    assert not pl.ring_shadowed_by_planet((-far * 1.001, 0.0, 0.0), s, R)
    assert not pl.ring_shadowed_by_planet((far * 0.5, 0.0, 0.0), s, R)  # the sunward side is lit
    assert pl.ring_shadowed_by_planet((-1.5 * R, 0.0, 0.0), s, R) and not pl.ring_shadowed_by_planet((0.0, 1.5 * R, 0.0), s, R)
    # the rings' shadow on the planet: the sun ray from a surface point crosses the ring plane at radius rho
    p = pl.surface_point(R, 0.0, 0.0, -20.0)  # noon meridian, southern hemisphere, the sun north of the ring plane
    rho = pl.ring_crossing(p, s)
    assert rho is not None and rho > R
    assert pl.ring_crossing(pl.surface_point(R, 0.0, 0.0, 20.0), s) is None  # the ray leaves the plane behind it
    assert pl.ring_crossing((R, 0.0, 0.0), (1.0, 0.0, 0.0)) is None  # the sun in the plane: no crossing
    shade = pl.ring_shadow(p, s, strip, inner * R, outer * R)
    assert 0.0 <= shade < 1.0  # the crossing at 1.62 radii falls inside the strip
    assert pl.ring_shadow(pl.surface_point(R, 0.0, 0.0, 20.0), s, strip, inner * R, outer * R) == 1.0
    with pytest.raises(pl.PlanetError):
        pl.ring_sample(strip, 1.5, 2.0, 1.0)


def test_the_saturn_shadow_ellipse():
    R = pl.RADII[699][0]
    beta = 26.7
    s = (math.cos(math.radians(beta)), 0.0, math.sin(math.radians(beta)))
    axes = pl.planet_shadow_on_rings(s, R)
    assert _close(axes, (R / math.sin(math.radians(beta)), R))
    assert pl.planet_shadow_on_rings((1.0, 0.0, 0.0), R) is None  # the sun in the plane: an edge-on shadow
    # the boundary of the ellipse agrees with the ray test
    a, b = axes
    for t in (0.3, 1.2, 2.5):
        q = (-a * math.cos(t) * 0.999, b * math.sin(t) * 0.999, 0.0)
        assert pl.ring_shadowed_by_planet(q, s, R) == (math.cos(t) > 0.0)  # the anti-sun half of the ellipse


# ------------------------------------------------------------------------------------ rule 6: atmosphere shell


def test_the_atmosphere_shell_from_orbit_and_from_the_ground():
    sky = _load(SKY, "physical_sky_reference")
    a = sky.atmosphere()
    R, top = a["planet_radius"] / 1000.0, a["top_radius"] / 1000.0
    d = R + 400.0
    band = pl.shell_band(d, R, top - R)
    assert _close(band["planet"], math.degrees(math.asin(R / d)))
    assert _close(band["shell"], math.degrees(math.asin(top / d)))
    assert 2.0 < band["shell"] - band["planet"] < 4.0
    obs = (0.0, 0.0, d * 1000.0)
    grazing = sky.limb_direction(a, obs)
    assert _close(math.degrees(pl.angle(grazing, (0.0, 0.0, -1.0))), band["planet"], 1e-6)
    low = pl.shell_band(R + 1.0, R, top - R)  # from inside the atmosphere the shell has no outer edge
    assert low["shell"] is None and _close(low["planet"], math.degrees(math.asin(R / (R + 1.0))))
    assert pl.shell_band(R - 1.0, R, 100.0) == {"planet": None, "shell": None}
    with pytest.raises(pl.PlanetError):
        pl.shell_band(d, R, 0.0)


# ------------------------------------------------------------------------------------ rule 7: frames and seek


def test_the_frame_state_is_a_pure_function():
    state = pl.frame_state(600, 24, rate=60.0, cloud_rotation=0.01, body=399)
    assert set(state) == {"seconds", "cloud_longitude", "spin"}
    assert _close(state["seconds"], 600 / 24 * 60.0)
    assert _close(state["cloud_longitude"], (600 / 24 * 60.0 * 0.01) % 360.0)
    assert _close(state["spin"], pl.spin_degrees(399, state["seconds"]))
    assert pl.seek_test() is True
    assert _close(pl.spin_degrees(399, 86164.0962), 360.0, 1e-3)  # one sidereal day is one turn
    assert _close(pl.spin_degrees(699, 3600.0), 360.0 * 3600.0 / (10.0 * 3600.0 + 33.0 * 60.0 + 38.0), 0.5)
    with pytest.raises(pl.PlanetError):
        pl.frame_state(-1, 24, 1.0, 0.0, 399)


def test_the_spin_rates_match_the_time_frames_rotation_elements():
    tf = _load(TIME_FRAMES, "time_frames_reference")
    for body in (399, 499, 599, 699, 301):
        rate = tf.ROTATION[body][2][1]  # degrees per day of the prime meridian's W
        assert _close(pl.spin_degrees(body, 86400.0), rate % 360.0 if rate > 0 else rate, 1e-9) or \
            _close(pl.spin_degrees(body, 86400.0) % 360.0, rate % 360.0, 1e-9)


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
    assert "SR-89" in draft
    for word in ("planet", "flattening", "cloudMap", "cloudHeight", "cloudRotation", "cloudShadow", "ringMap",
                 "ringInner", "ringOuter", "limbDarkening", "twilight", "nightLights", "atmosphere",
                 "atmosphereHeight", "equirectangular", "prime meridian", "terminator", "limb", "cusp",
                 "Hestroffer", "Magnan", "pck00010", "IAU", "PL1", "V17", "seek check", "planets_reference.py",
                 "SREP 14", "pixelsPerMeter", "baseColorMap", "emissiveMap", "Saturn", "night lights"):
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
    s = pl.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or pl._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    pl.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())
