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


def test_the_geodetic_latitude_of_a_surface_point():
    # the inverse of surface_point on the spheroid: atan2(z, (1 - f)^2 sqrt(x^2 + y^2)), the normal's elevation
    f = pl.flattening(399)
    for lat in (-90.0, -60.0, -0.5, 0.0, 30.0, 45.0, 89.0, 90.0):
        for lon in (0.0, 90.0, -135.0):
            p = pl.surface_point(EARTH, f, lon, lat)
            assert _close(pl.geodetic_latitude(p, f), lat, 1e-9), (lon, lat)
    p = pl.surface_point(EARTH, f, 0.0, 45.0)
    assert _close(math.degrees(math.asin(pl.surface_normal(EARTH, f, p)[2])), pl.geodetic_latitude(p, f), 1e-9)
    # read as a sphere's the same point is 0.19 degrees nearer the equator (Open issue 6)
    geocentric = pl.geodetic_latitude(p, 0.0)
    assert _close(geocentric, math.degrees(math.atan2(p[2], math.hypot(p[0], p[1]))), 1e-12)
    assert _close(geocentric, 44.8076, 5e-5) and 0.19 < 45.0 - geocentric < 0.2
    for bad in (1.0, -0.1):
        with pytest.raises(pl.PlanetError):
            pl.geodetic_latitude(p, bad)


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
    # no band: a step at the horizon, 1/2 on it (the engine's limit; the schema allows twilight="0")
    assert pl.night_weight((0.0, 0.0, -1.0), s, 0.0) == 1.0 and pl.night_weight((0.0, 0.0, 1.0), s, 0.0) == 0.0
    assert pl.night_weight((1.0, 0.0, 0.0), s, 0.0) == 0.5
    above = pl.unit((math.cos(math.radians(3.0)), 0.0, math.sin(math.radians(3.0))))
    assert pl.night_weight(half, s, 0.0) == 1.0 and pl.night_weight(above, s, 0.0) == 0.0
    with pytest.raises(pl.PlanetError):
        pl.night_weight(s, s, -1.0)


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


def test_the_cloud_shell_is_the_spheroid_scaled():
    # the shell is the body's spheroid scaled by 1 + height: over the pole it is height x the polar radius up,
    # not the equatorial sphere's a (1 + h) - c (47 km on the Earth)
    f = pl.flattening(399)
    s = (0.0, 0.0, 1.0)
    pole = pl.surface_point(EARTH, f, 0.0, 90.0)
    q = pl.cloud_shadow_point(pole, s, EARTH, 0.004, f)
    assert _close(q[2] - pole[2], 0.004 * pl.RADII[399][1], 1e-6)
    assert _close(q[2] - pole[2], 25.427, 1e-3) and EARTH * 1.004 - pl.RADII[399][1] > 46.0
    # a lit point's shadow texel lies on the scaled spheroid, along the sun's direction from the point
    p = pl.surface_point(EARTH, f, 30.0, 60.0)
    q = pl.cloud_shadow_point(p, s, EARTH, 0.004, f)
    shell = EARTH * 1.004
    assert _close(q[0] ** 2 + q[1] ** 2 + (q[2] / (1.0 - f)) ** 2, shell * shell, 1e-6 * shell * shell)
    assert _close(pl.unit(pl.sub(q, p)), s, 1e-12)
    # a sphere (flattening 0) is the old function
    assert pl.cloud_shadow_point(p, s, EARTH, 0.004, 0.0) == pl.cloud_shadow_point(p, s, EARTH, 0.004)
    # the day side is judged by the geodetic normal: a point at the equator with the sun just over its horizon
    sun = pl.unit((math.cos(math.radians(89.9)), 0.0, math.sin(math.radians(89.9))))
    assert pl.cloud_shadow_point(pl.surface_point(EARTH, f, 0.0, 0.0), sun, EARTH, 0.004, f) is not None
    assert pl.cloud_shadow_point(pl.surface_point(EARTH, f, 0.0, -0.2), sun, EARTH, 0.004, f) is None
    with pytest.raises(pl.PlanetError):
        pl.cloud_shadow_point(p, s, EARTH, 0.004, 1.0)


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


def test_the_ring_is_lit_on_both_faces_alike():
    # the lit cosine is |n . s| for the plane's normal: the same from either side, zero with the sun in the plane
    assert _close(pl.ring_cosine(pl.SATURN_SUN), math.sin(math.radians(26.7)))
    assert pl.ring_cosine((1.0, 0.0, -1.0)) == pl.ring_cosine((1.0, 0.0, 1.0))
    assert _close(pl.ring_cosine((1.0, 0.0, 1.0)), math.sqrt(0.5))
    assert pl.ring_cosine((3.0, 4.0, 0.0)) == 0.0
    with pytest.raises(pl.PlanetError):
        pl.ring_cosine((0.0, 0.0, 0.0))


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


def test_the_limb_half_extents_of_a_spheroid_seen_from_its_equator():
    eye = (0.0, -4.0 * EARTH, 0.0)
    cam = _camera(eye)
    a, c = pl.RADII[399]
    w, h = pl.limb_pixel_extents(cam, eye, a, c)
    assert _close(w, pl.limb_pixel_radius(cam, eye, a), 1e-9)
    assert _close(h, w * c / a, 1e-9)
    # the polar half-extent is where the tangent from the eye touches the meridian ellipse: no point of the
    # ellipse projects higher than it
    best = 0.0
    for k in range(1, 9000):
        t = math.radians(k / 50.0)
        p = (0.0, -a * math.cos(t), c * math.sin(t))
        if pl.dot(pl.sub(eye, p), (0.0, p[1] / (a * a), p[2] / (c * c))) > 0.0:
            best = max(best, -pl.project(cam, p)[1])
    assert abs(best - h) < 0.01
    with pytest.raises(pl.PlanetError):
        pl.limb_pixel_extents(cam, (0.0, -4.0 * EARTH, EARTH), a, c)


def test_isophotes_are_small_circles_about_the_subsolar_point():
    s = pl.unit((1.0, -1.0, 0.0))
    for weight, half in ((0.0, 90.0), (0.5, 60.0), (0.1, math.degrees(math.acos(0.1)))):
        pts = pl.isophote_points(s, EARTH, 24, weight)
        assert len(pts) == 24
        for p in pts:
            assert _close(pl.norm(p), EARTH, 1e-6)
            assert _close(pl.day_weight(pl.unit(p), s), weight, 1e-9)
            assert _close(math.degrees(pl.angle(p, s)), half, 1e-6)
    assert pl.isophote_points(s, EARTH, 8, 0.0) == pl.terminator_points(s, EARTH, 8)
    with pytest.raises(pl.PlanetError):
        pl.isophote_points(s, EARTH, 8, 1.5)


def test_the_cusps_generalise_to_an_isophote_read_on_a_cone_about_the_line_of_sight():
    eye = (0.0, -5.0 * EARTH, 0.0)
    s = pl.unit((1.0, -1.0, 0.0))
    assert pl.cusps(eye, s, EARTH, 0.0, None) == pl.cusps(eye, s, EARTH)
    cone = 0.9 * pl.limb(eye, EARTH)["angular_radius"]
    for weight in (0.0, 0.1, 0.3):
        a, b = pl.cusps(eye, s, EARTH, weight, cone)
        for p in (a, b):
            assert _close(pl.norm(p), EARTH, 1e-6)
            assert _close(pl.day_weight(pl.unit(p), s), weight, 1e-9)
            assert _close(math.degrees(pl.angle(pl.sub(p, eye), pl.mul(eye, -1.0))), cone, 1e-6)
            assert pl.visible(eye, p, EARTH)
        assert _close(a[2], -b[2], 1e-6) and a[2] > 0.0
    assert pl.cusps(eye, (0.0, -1.0, 0.0), EARTH, 0.1, cone) is None
    with pytest.raises(pl.PlanetError):
        pl.cusps(eye, s, EARTH, 0.1, 2.0 * pl.limb(eye, EARTH)["angular_radius"])


def test_the_surface_point_seen_at_a_pixel():
    eye = (0.0, -4.0 * EARTH, 0.0)
    cam = _camera(eye)
    assert _close(pl.pixel_surface_point(cam, eye, EARTH, 0.0, 0.0), (0.0, -EARTH, 0.0), 1e-6)
    for p in pl.isophote_points(pl.unit((1.0, -1.0, 0.0)), EARTH, 12, 0.3):
        if pl.visible(eye, p, EARTH):
            x, y = pl.project(cam, p)
            assert _close(pl.pixel_surface_point(cam, eye, EARTH, x, y), p, 1e-6)
    r = pl.limb_pixel_radius(cam, eye, EARTH)
    assert pl.pixel_surface_point(cam, eye, EARTH, r + 1.0, 0.0) is None
    assert pl.disc_mu(cam, eye, EARTH, 0.0, 0.0) == 1.0


def test_the_planets_shadow_on_the_rings_follows_its_oblateness():
    sun = pl.SATURN_SUN
    sphere = pl.planet_shadow_on_rings(sun, pl.SATURN)
    assert sphere == pl.planet_shadow_on_rings(sun, pl.SATURN, 0.0)
    along, across = pl.planet_shadow_on_rings(sun, pl.SATURN, pl.flattening(699))
    assert _close(across, pl.SATURN, 1e-9) and along < sphere[0]
    # the tangent of the meridian ellipse parallel to the sun reaches the ring plane at the semi-axis
    f = pl.flattening(699)
    a, c = pl.SATURN, pl.SATURN * (1.0 - f)
    farthest = 0.0
    for k in range(36000):
        t = math.radians(k / 100.0)
        p = (a * math.cos(t), 0.0, c * math.sin(t))
        if sun[2] != 0.0:
            x = p[0] - sun[0] * p[2] / sun[2]
            farthest = max(farthest, -x)
    assert abs(farthest - along) < 0.01 * a
    assert pl.ring_shadowed_by_planet((-2.1 * a, 0.0, 0.0), sun, a)
    assert not pl.ring_shadowed_by_planet((-2.1 * a, 0.0, 0.0), sun, a, f)
    assert pl.ring_shadowed_by_planet((-2.0 * a, 0.0, 0.0), sun, a, f)
    assert pl.planet_shadow_on_rings((1.0, 0.0, 0.0), a, f) is None


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


def test_the_draft_states_the_rings_lighting_and_the_geodetic_texel(draft):
    rule5 = " ".join(draft[draft.index("5. **Rings.**"):draft.index("6. **Atmosphere.**")].split())
    for phrase in ("alpha-blended diffuse surface", "no specular", "lit on both faces alike", "`ring_cosine(sun)`",
                   "rule 3's sun (under a physical sky, the sky's sun)", "no other light is shadowed by the planet",
                   "independent of the light's own shadow casting"):
        assert phrase in rule5, phrase
    rule2 = " ".join(draft[draft.index("2. **Textures and the mesh.**"):draft.index("3. **Shading")].split())
    assert "`geodetic_latitude(p, f)`" in rule2 and "(1 − f)² √(x² + y²)" in rule2 and "Open issue 6" in rule2
    assert "crosses one half" in draft and "`planet-rings-lit`" in draft


def test_the_draft_states_the_shells_irradiance(draft):
    rule6 = " ".join(draft[draft.index("6. **Atmosphere.**"):draft.index("7. **Limb, terminator and phase.**")].split())
    for phrase in ("rule 3's sun", "the light's colour times its intensity", "`effective_sun_irradiance`",
                   "transmittance alone", "one atmosphere", "not drawn"):
        assert phrase in rule6, phrase


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    assert "SR-89" in draft
    row = next(line for line in draft.splitlines() if line.startswith("| Rust (`rs-scene-render`), reference |"))
    done, remaining = row.split(" | ")[1:3]
    assert "a905705" in done and "path tracer" in done and "SR-89 reports" in done
    assert "9119130" in done and "orthographic camera" in done and "impact radius" in done
    assert "both tracers" not in remaining and "orthographic camera" not in remaining
    assert "a7dcc73" in done and "physical sky's sun" in done and "0b750e8" in done
    assert remaining.startswith("none; the ten kit cases pass")
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


# ------------------------------------------------------------------------------------ the kit (planets_kit.py)

KIT = os.path.join(ROOT, "conformance", "tools", "planets_kit.py")
pk_module = _load(os.path.join(ROOT, "conformance", "tools", "physical_sky_kit.py"), "physical_sky_kit")
sk = _load(os.path.join(ROOT, "conformance", "tools", "star_fields_kit.py"), "star_fields_kit")
kit = _load(KIT, "planets_kit")
np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _kit_rows(draft):
    return [m.group(1) for m in (re.match(r"^\| `srep-<n>-(planet-[a-z]+)\.xml` \|", line)
                                 for line in draft.splitlines()) if m]


def test_the_kit_camera_agrees_with_the_physical_sky_kits_projection():
    # the reference's pinhole in the body frame and the physical-sky kit's description of the engine's camera
    # (yaw, pitch, scene axes) put a point on the same pixel
    g = kit.geometry()
    for key, c in g.items():
        if c["cam"] is None:
            continue
        for p in (pl.mul(pl.body_direction(20.0, 10.0), c["a"]), pl.mul(pl.body_direction(-40.0, -30.0), c["a"] * 1.5),
                  (0.0, 0.0, 0.0)):
            d = pl.scene_from_body(pl.unit(pl.sub(p, c["eye"])))
            want = pk_module.project(c["fov"], c["yaw"], c["pitch"], d)
            if math.isnan(want[0]):
                continue
            got = kit.at(c["cam"], p)
            assert _close(got, want, 1e-6), (key, got, want)
    # the directional light travels away from the sun: its +z is the scene direction of -sun
    for sun in (kit.POLE_SUN, kit.SUN45, pl.SATURN_SUN):
        yaw, pitch = kit.light_aim(sun)
        assert _close(pk_module.unproject(60.0, yaw, pitch, (320.0, 180.0)), pl.scene_from_body(pl.mul(pl.unit(sun), -1.0)), 1e-9)
    assert kit.light_aim(kit.POLE_SUN)[1] == -90.0


def test_the_kit_writes_the_cases_the_draft_names(draft, tmp_path):
    assert _kit_rows(draft) == kit.NAMES
    assert [k for keys in kit.DOCUMENTS.values() for k in keys] == list(kit.documents())
    paths = kit.write(str(tmp_path))
    assert len(paths) == 17
    docs = {k: open(p, encoding="utf-8").read() for k, p in paths.items()}
    for key, text in docs.items():
        assert os.path.basename(paths[key]) == f"srep-0000-{key}.xml"
        assert '<scene version="1.8">' in text and 'primitive="planet"' in text and f'segments="{kit.SEGMENTS}"' in text
        assert 'width="640" height="360"' in text and f'path="out/{key}_%04d.exr"' in text
    assert 'body="399"' in docs["planet-limb"] and 'z="-25.5125464"' in docs["planet-limb"]
    assert 'body="699" radius="1"' in docs["planet-limb-saturn"] and 'pixelsPerMeter="1e-07"' in docs["planet-limb-saturn"]
    assert 'unlit="true"' in docs["planet-limb"] and "<lights>" not in docs["planet-limb"]
    assert 'radius="6.3781366"' in docs["planet-terminator"] and 'body=' not in docs["planet-terminator"]
    assert 'specular="0"' in docs["planet-terminator"] and 'type="directional"' in docs["planet-terminator"]
    for key in kit.DOCUMENTS["planet-phase"]:
        assert 'fov="1.2"' in docs[key] and 'radius="6.3781366"' in docs[key]
    assert 'baseColorMap="assets/planet-marks.png"' in docs["planet-texture"] and 'body="399"' in docs["planet-texture"]
    assert 'twilight="6"' in docs["planet-night"] and 'emissiveMap="assets/planet-white.png"' in docs["planet-night"]
    assert 'emissive="#FFFFFFFF"' in docs["planet-night"] and 'baseColor="#000000FF"' in docs["planet-night"]
    for key in kit.DOCUMENTS["planet-sun"]:
        assert 'body="10" limbDarkening="solar"' in docs[key] and 'projection="orthographic"' in docs[key]
        assert 'pixelsPerMeter="1e-08"' in docs[key] and 'emissive="#FFFFFFFF"' in docs[key]
    assert 'orthoHeight="1.6704" x="5.568" y="0.0" z="-20.88"' in docs["planet-sun"]
    assert 'orthoHeight="1.6704" x="0.0" y="0.0" z="-20.88"' in docs["planet-sun-centre"]
    assert 'y="-0.0"' not in "".join(docs.values())
    assert 'cloudMap="assets/planet-cloud.png" cloudHeight="0.004" cloudShadow="true"' in docs["planet-clouds"]
    assert 'fov="2"' in docs["planet-clouds"] and 'baseColor="#808080FF"' in docs["planet-clouds"]
    for key in kit.DOCUMENTS["planet-rings"]:
        assert 'body="699" ringMap="assets/planet-strip.png" ringInner="1.239" ringOuter="2.269"' in docs[key]
    # the lit companion: the same view, the light's azimuth turned by 180 degrees, the planet black
    assert 'baseColor="#000000FF"' in docs["planet-rings-lit"] and 'baseColor="#FFFFFFFF"' in docs["planet-rings"]
    camera = re.search(r"<camera [^>]*/>", docs["planet-rings"]).group(0)
    assert camera in docs["planet-rings-lit"]
    light = re.compile(r'<light id="sun" type="directional" intensity="1" yaw="([^"]*)" pitch="([^"]*)"/>')
    (yaw, pitch), (yaw_lit, pitch_lit) = (light.search(docs[k]).groups() for k in ("planet-rings", "planet-rings-lit"))
    assert pitch == pitch_lit and abs(abs(float(yaw) - float(yaw_lit)) - 180.0) < 1e-6
    assert 'atmosphere="earth" atmosphereHeight="100000"' in docs["planet-atmosphere"] and 'fov="10"' in docs["planet-atmosphere"]
    assert 'x="6.7781366"' in docs["planet-atmosphere"]
    seek = docs["planet-seek"]
    assert 'fps="24" duration="26"' in seek and '<space epoch="2451545.0" timeScale="tdb" origin="10" rate="60"/>' in seek
    assert 'orientation="bodyFixed" cloudMap="assets/planet-marks.png" cloudRotation="0.01"' in seek
    assert kit.SEEK_DURATION * kit.SEEK_FPS > kit.SEEK_FRAMES
    # the textures
    marks = np.asarray(Image.open(tmp_path / "assets" / "planet-marks.png"))
    assert marks.shape == (512, 1024, 4) and marks[..., 3].sum() == 3 * 16 * 255
    assert (marks[254:258, 510:514, 0] == 255).all() and (marks[254:258, 766:770, 1] == 255).all()
    assert (marks[126:130, 638:642, 2] == 255).all() and marks[..., :3].sum() == 3 * 16 * 255
    white = np.asarray(Image.open(tmp_path / "assets" / "planet-white.png"))
    assert white.shape == (4, 8, 4) and (white == 255).all()
    cloud = np.asarray(Image.open(tmp_path / "assets" / "planet-cloud.png"))
    col, row, lon, lat = kit.cloud_texel()
    assert cloud.shape == (2048, 4096, 4) and cloud.sum() == 4 * 255 and (cloud[row, col] == 255).all()
    assert (col, row) == (2048, 512) and _close((lon, lat), (0.0439453125, 44.9560546875), 1e-9)
    strip = np.asarray(Image.open(tmp_path / "assets" / "planet-strip.png"))
    assert strip.shape == (1, 4, 4) and strip[0, 1].tolist() == [204, 191, 153, 230]
    assert _close(kit.QSTRIP[1], (204 / 255, 191 / 255, 153 / 255, 230 / 255), 1e-12)


def test_the_kit_expectations_come_from_the_reference():
    g = kit.geometry()
    e = kit.expectations()
    cam, eye = g["planet-limb"]["cam"], g["planet-limb"]["eye"]
    assert e["planet-limb"]["planet-limb"]["half_extents"] == pl.limb_pixel_extents(cam, eye, *pl.RADII[399])
    assert _close(e["planet-limb"]["planet-limb"]["half_extents"], (143.108, 142.629), 1e-3)
    assert _close(e["planet-limb"]["planet-limb-saturn"]["half_extents"][1] / e["planet-limb"]["planet-limb-saturn"]["half_extents"][0],
                  pl.RADII[699][1] / pl.RADII[699][0], 1e-9)
    sectors = e["planet-limb"]["planet-limb"]["sectors"]
    assert len(sectors) == kit.SECTORS and max(sectors) < 143.108 and min(sectors) > 142.629
    t = e["planet-terminator"]
    assert 10 <= len(t["points"]) <= 72 and len(t["cusps_at"]) == 2 and t["level"] == kit.ISOPHOTE
    assert _close(t["radius_px"], 143.108, 1e-3) and _close(t["cone_radius_px"], 143.108 - kit.CONE_INSET_PX, 1e-3)
    for pt in t["points"]:
        assert _close(pl.day_weight(pl.unit(pt["point"]), kit.SUN45), kit.ISOPHOTE, 1e-9)
    for key, phase in zip(kit.DOCUMENTS["planet-phase"], kit.PHASES):
        assert e["planet-phase"][key]["fraction"] == pl.illuminated_fraction(phase)
        assert abs(e["planet-phase"][key]["sampled"] - e["planet-phase"][key]["fraction"]) < 0.003
        assert _close(e["planet-phase"][key]["radius_px"], 152.78, 0.01)
    cam = g["planet-texture"]["cam"]
    assert e["planet-texture"]["red"] == kit.at(cam, pl.surface_point(pl.EARTH, pl.flattening(399), 0.0, 0.0))
    assert e["planet-texture"]["red"][0] < e["planet-texture"]["green"][0]      # east is to the right
    assert e["planet-texture"]["blue"][1] < e["planet-texture"]["red"][1]       # north is up
    rows = e["planet-night"]["rows"]
    assert [r["latitude"] for r in rows] == list(range(-12, 13))
    assert [r["weight"] for r in rows][:5] == [1.0] * 5 and rows[12]["weight"] == 0.5 and rows[-1]["weight"] == 0.0
    assert _close(rows[15]["weight"], pl.night_weight(pl.body_direction(0.0, 3.0), (0.0, 0.0, 1.0), 6.0), 1e-9)
    assert rows[0]["at"][1] > rows[-1]["at"][1]                                  # north is up
    s = e["planet-sun"]
    assert [m["mu"] for m in s["mus"]] == [0.5, 0.25, 0.1] and s["mus"][2]["factor"] == pl.solar_disc(0.1)
    assert _close(s["limb_column"], 620.0, 1e-9) and 612 < s["mus"][2]["column"] < 613
    c = e["planet-clouds"]
    assert _close(c["shift_deg"], math.degrees(kit.CLOUD_HEIGHT * math.tan(math.radians(45.0))), 2e-3)   # 0.229 degrees
    assert _dist(c["shadow_at"], c["cloud_at"]) > 20.0     # clear of the cloud's bilinear fringe (a texel is 10 px tall)
    assert _close(pl.cloud_shadow_point(c["shadow"], kit.POLE_SUN, pl.EARTH, kit.CLOUD_HEIGHT), c["shell"], 1e-3)
    assert c["shadow"][2] < c["ground"][2] and c["shadow_at"][1] > c["cloud_at"][1]   # toward the equator: down the frame
    r = e["planet-rings"]
    assert r["axes"] == pl.planet_shadow_on_rings(pl.SATURN_SUN, pl.SATURN, pl.flattening(699))
    assert len(r["edge"]) == len(kit.RING_EDGE_T) and all(0.2 < q["alpha"] < 0.9 for q in r["edge"])
    for q in r["edge"]:
        assert not pl.ring_shadowed_by_planet(pl.mul(q["point"], 1.001), pl.SATURN_SUN, pl.SATURN, pl.flattening(699))
        assert pl.ring_shadowed_by_planet(pl.mul(q["point"], 0.999), pl.SATURN_SUN, pl.SATURN, pl.flattening(699))
    assert r["ground"][-5.0]["light"] == 1.0 and 0.1 < r["ground"][-20.0]["light"] < 0.3
    assert _close(r["ratio"], r["ground"][-20.0]["light"] * r["ground"][-20.0]["weight"] / r["ground"][-5.0]["weight"], 1e-12)
    a = e["planet-atmosphere"]
    band = pl.shell_band(pl.EARTH + 400.0, pl.EARTH, 100.0)
    assert (a["ground"], a["top"]) == (band["planet"], band["shell"])
    assert a["ground"] < a["peak_angle"] < a["edge"] < a["top"] and a["peak"] > 0.0
    assert abs(a["limb_angle"] - a["ground"]) < 0.05
    assert e["planet-seek"] == {}


# ---------------------------------------------------------------- synthetic frames: the geometry of each case painted

def _rays(c):
    cam = c["cam"]
    f = cam["focal"]
    xs = np.arange(kit.W) + 0.5 - kit.W / 2.0
    ys = np.arange(kit.H) + 0.5 - kit.H / 2.0
    X, Y = np.meshgrid(xs, ys)
    fwd, right, up = (np.array(cam[k]) for k in ("forward", "right", "up"))
    d = fwd + right * (X / f)[..., None] - up * (Y / f)[..., None]
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def _hits(origin, d, radius, flattening=0.0):
    """Surface points (h, w, 3) and a mask where unit rays d from `origin` (h, w, 3 or 3) meet the spheroid."""
    k = 1.0 / (1.0 - flattening)
    o = np.asarray(origin, dtype=float) * np.array([1.0, 1.0, k])
    dd = d * np.array([1.0, 1.0, k])
    a = (dd * dd).sum(-1)
    b = 2.0 * (o * dd).sum(-1)
    cc = (o * o).sum(-1) - radius * radius
    disc = b * b - 4.0 * a * cc
    ok = disc >= 0.0
    t = np.where(ok, (-b - np.sqrt(np.where(ok, disc, 0.0))) / (2.0 * a), np.nan)
    ok = ok & (t > 0.0)
    return np.asarray(origin, dtype=float) + d * t[..., None], ok, t


def _normals(p, a, c):
    n = p / np.array([a * a, a * a, c * c])
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def _grey(lum):
    return np.repeat(lum[..., None], 3, axis=-1).astype(np.float64)


def _unlit(c):
    _, ok, _ = _hits(c["eye"], _rays(c), c["a"], c["f"])
    return _grey(ok.astype(float))


def _lambert(c, sun, albedo=1.0):
    p, ok, _ = _hits(c["eye"], _rays(c), c["a"], c["f"])
    n = _normals(np.where(ok[..., None], p, 1.0), c["a"], c["a"] * (1.0 - c["f"]))
    w = np.clip(n @ np.array(pl.unit(sun)), 0.0, None) * ok
    return _grey(w * albedo / math.pi)


def _night(c, twilight):
    p, ok, _ = _hits(c["eye"], _rays(c), c["a"], c["f"])
    n = _normals(np.where(ok[..., None], p, 1.0), c["a"], c["a"] * (1.0 - c["f"]))
    e = np.degrees(np.arcsin(np.clip(n @ np.array(c["sun"]), -1.0, 1.0)))
    return _grey(np.clip(0.5 - e / (2.0 * twilight), 0.0, 1.0) * ok * 0.7)


def _sun_frame(rho_centre, alphas):
    xs = (np.arange(kit.W) + 0.5 - kit.W / 2.0) / kit.SUN_RADIUS_PX + rho_centre
    ys = (np.arange(kit.H) + 0.5 - kit.H / 2.0) / kit.SUN_RADIUS_PX
    X, Y = np.meshgrid(xs, ys)
    rho2 = X * X + Y * Y
    mu = np.sqrt(np.clip(1.0 - rho2, 0.0, 1.0))
    out = np.stack([np.where(rho2 < 1.0, mu ** al, 0.0) for al in alphas], axis=-1)
    return out * 3.0


def _clouds(c, shadow_lat):
    col, row, lon, lat = c["texel"]
    rays = _rays(c)
    ground = _lambert(c, c["sun"], 0.5)
    p, ok, _ = _hits(c["eye"], rays, c["a"])
    lons = np.degrees(np.arctan2(p[..., 1], p[..., 0]))
    lats = np.degrees(np.arcsin(np.clip(p[..., 2] / c["a"], -1.0, 1.0)))
    half_lon, half_lat = 180.0 / kit.CLOUD_TEXTURE[0], 90.0 / kit.CLOUD_TEXTURE[1]
    shadow = ok & (np.abs(lons - lon) < half_lon) & (np.abs(lats - shadow_lat) < half_lat)
    ground[shadow] = 0.0
    q, okq, _ = _hits(c["eye"], rays, c["a"] * (1.0 + kit.CLOUD_HEIGHT))
    qlons = np.degrees(np.arctan2(q[..., 1], q[..., 0]))
    qlats = np.degrees(np.arcsin(np.clip(q[..., 2] / (c["a"] * (1.0 + kit.CLOUD_HEIGHT)), -1.0, 1.0)))
    cloud = okq & (np.abs(qlons - lon) < half_lon) & (np.abs(qlats - lat) < half_lat)
    ground[cloud] = 0.9
    return ground


def _rings(c, flattening):
    rays = _rays(c)
    eye = np.array(c["eye"])
    t = -eye[2] / rays[..., 2]
    q = eye + rays * t[..., None]
    rho = np.hypot(q[..., 0], q[..., 1])
    inner, outer = kit.RING_INNER * c["a"], kit.RING_OUTER * c["a"]
    xp = inner + np.arange(4) * (outer - inner) / 3.0
    alpha = np.interp(rho, xp, [tx[3] for tx in kit.QSTRIP]) * (t > 0.0) * (rho >= inner) * (rho <= outer)
    s = np.array(pl.unit(c["sun"]))
    _, shadowed, _ = _hits(q.reshape(-1, 3), np.broadcast_to(s, (q.size // 3, 3)), c["a"], flattening)
    lit = alpha * (~shadowed.reshape(rho.shape)) * 0.4
    p, ok, tp = _hits(c["eye"], rays, c["a"], c["f"])
    planet = np.where(ok & ((t <= 0.0) | (tp < t)), 0.6, 0.0)
    return _grey(np.where(planet > 0.0, planet, lit))


def _ground_frame(c, exp, scale=0.3):
    rgb = np.zeros((kit.H, kit.W, 3))
    for lat, row in exp["ground"].items():
        x, y = (int(v) for v in row["at"])
        rgb[y - 3:y + 4, x - 3:x + 4, :] = scale * row["light"] * row["weight"]   # covers the bilinear window
    return rgb


def _atmosphere_frame(c, exp, shift=0.0):
    angles = [math.degrees(math.acos(-pk_module.unproject(c["fov"], c["yaw"], c["pitch"], (col + 0.5, kit.H / 2.0 + 0.5))[0]))
              for col in range(kit.W)]
    lum = np.interp(np.array(angles) - shift, exp["angles"], exp["luminance"])
    return _grey(np.tile(lum, (kit.H, 1)))


def _marks_frame(exp, shift=0.0):
    rgb = np.zeros((kit.H, kit.W, 3))
    for channel, (x, y) in exp.items():
        xi, yi = int(x + shift), int(y)
        rgb[yi - 1:yi + 2, xi - 1:xi + 2, "rgb".index(channel[0])] = 1.0
    return rgb


def _frames(exp, g):
    f = {key: _unlit(g[key]) for key in kit.DOCUMENTS["planet-limb"]}
    f["planet-terminator"] = _lambert(g["planet-terminator"], kit.SUN45)
    for key in kit.DOCUMENTS["planet-phase"]:
        f[key] = _lambert(g[key], g[key]["sun"])
    f["planet-texture"] = _marks_frame(exp["planet-texture"])
    f["planet-night"] = _night(g["planet-night"], kit.TWILIGHT)
    alphas = [pl.limb_alpha(nm) for nm in pl.CHANNEL_WAVELENGTHS_NM]
    f["planet-sun"] = _sun_frame(kit.SUN_CENTRE_RHO, alphas)
    f["planet-sun-centre"] = _sun_frame(0.0, alphas)
    shadow_lat = math.degrees(math.asin(exp["planet-clouds"]["shadow"][2] / pl.EARTH))
    f["planet-clouds"] = _clouds(g["planet-clouds"], shadow_lat)
    f["planet-rings"] = _rings(g["planet-rings"], pl.flattening(699))
    f["planet-rings-lit"] = _rings(g["planet-rings-lit"], pl.flattening(699))
    f["planet-rings-ground"] = _ground_frame(g["planet-rings-ground"], exp["planet-rings"])
    f["planet-atmosphere"] = _atmosphere_frame(g["planet-atmosphere"], exp["planet-atmosphere"])
    seek = np.zeros((kit.H, kit.W, 3), dtype=np.uint8)
    seek[100:200, 300:400] = 200
    f["seek-alone"] = seek
    f["seek-played"] = seek.copy()
    return f


@pytest.fixture(scope="module")
def synthetic():
    exp = kit.expectations()
    g = kit.geometry()
    return exp, g, _frames(exp, g)


def test_the_kit_measures_each_case(synthetic):
    exp, g, frames = synthetic
    for name in kit.NAMES:
        r = kit.measure(name, frames, exp)
        assert r["pass"], (name, r)
    limb = kit.measure("planet-limb", frames, exp)
    assert limb["planet-limb"]["worst_off_px"] <= 0.15 and limb["planet-limb-saturn"]["worst_off_px"] <= 0.15
    assert _close(limb["planet-limb-saturn"]["half_extents_px"], (143.11, 129.09), 0.05)
    term = kit.measure("planet-terminator", frames, exp)
    assert term["worst_off_px"] <= 0.2 and max(term["cusps_off_px"]) <= 0.3 and term["crossings_on_cone"] == 2
    phase = kit.measure("planet-phase", frames, exp)
    assert phase["disc_rel_off"] <= 0.005 and phase["planet-phase-120"]["rel_off"] <= 0.005
    night = kit.measure("planet-night", frames, exp)
    assert night["worst_off"] <= 0.012                    # the 3 x 3 window straddles the ramp's kinks at +-6 degrees
    assert all(abs(w - row["weight"]) <= 1e-3 for w, row in zip(night["weights"], exp["planet-night"]["rows"])
               if abs(row["latitude"]) < kit.TWILIGHT)
    sun = kit.measure("planet-sun", frames, exp)
    assert sun["worst_rel"] <= 0.01
    clouds = kit.measure("planet-clouds", frames, exp)
    assert abs(clouds["shift_deg"] - exp["planet-clouds"]["shift_deg"]) <= 0.01 and clouds["toward_equator"]
    assert clouds["shadow_off_px"] <= 0.5 and clouds["cloud_off_px"] <= 0.5
    rings = kit.measure("planet-rings", frames, exp)
    assert rings["worst_edge_off_px"] <= kit.RING_EDGE_TOL_PX and abs(rings["mean_edge_off_px"]) <= 0.3
    assert rings["light_rel_off"] <= 1e-6
    atmosphere = kit.measure("planet-atmosphere", frames, exp)
    assert atmosphere["peak_off_deg"] <= 0.02 and atmosphere["edge_off_deg"] <= 0.02 and atmosphere["limb_off_deg"] <= 0.02
    with pytest.raises(ValueError):
        kit.measure("planet-moons", frames, exp)


def test_the_kit_fails_a_wrong_frame(synthetic):
    exp, g, frames = synthetic
    bad = dict(frames)
    big = dict(g["planet-limb"], a=pl.EARTH * 1.01)
    bad["planet-limb"] = _unlit(big)
    assert not kit.measure("planet-limb", bad, exp)["pass"]
    bad = dict(frames)
    turned = (math.cos(math.radians(48.0)), -math.sin(math.radians(48.0)), 0.0)
    bad["planet-terminator"] = _lambert(g["planet-terminator"], turned)
    assert not kit.measure("planet-terminator", bad, exp)["pass"]
    bad = dict(frames)
    bad["planet-phase-60"], bad["planet-phase-90"] = frames["planet-phase-90"], frames["planet-phase-60"]
    assert not kit.measure("planet-phase", bad, exp)["pass"]
    bad = dict(frames)
    bad["planet-texture"] = _marks_frame(exp["planet-texture"], shift=2.0)
    assert not kit.measure("planet-texture", bad, exp)["pass"]
    bad = dict(frames)
    bad["planet-night"] = _night(g["planet-night"], 2.0 * kit.TWILIGHT)
    assert not kit.measure("planet-night", bad, exp)["pass"]
    bad = dict(frames)
    bad["planet-sun"] = _sun_frame(kit.SUN_CENTRE_RHO, [2.0 * pl.limb_alpha(nm) for nm in pl.CHANNEL_WAVELENGTHS_NM])
    assert not kit.measure("planet-sun", bad, exp)["pass"]
    bad = dict(frames)
    bad["planet-clouds"] = _clouds(g["planet-clouds"], g["planet-clouds"]["texel"][3])   # the shadow under the cloud
    assert not kit.measure("planet-clouds", bad, exp)["pass"]
    bad = dict(frames)
    bad["planet-rings"] = _rings(g["planet-rings"], 0.0)                              # a spherical Saturn's shadow
    assert not kit.measure("planet-rings", bad, exp)["pass"]
    bad = dict(frames)
    bad["planet-rings-ground"] = _ground_frame(g["planet-rings-ground"], exp["planet-rings"])
    x, y = (int(v) for v in exp["planet-rings"]["ground"][-20.0]["at"])
    bad["planet-rings-ground"][y - 3:y + 4, x - 3:x + 4, :] *= 1.1                 # the shadowed ground 10 % too bright
    assert not kit.measure("planet-rings", bad, exp)["pass"]
    bad = dict(frames)
    bad["planet-atmosphere"] = _atmosphere_frame(g["planet-atmosphere"], exp["planet-atmosphere"], shift=0.3)
    assert not kit.measure("planet-atmosphere", bad, exp)["pass"]
    bad = dict(frames)
    bad["seek-played"] = frames["seek-alone"].copy()
    bad["seek-played"][150, 350] = 0
    assert not kit.measure("planet-seek", bad, exp)["pass"]


def _fake_engine(frames, refuse=()):
    class Result:
        def __init__(self, code, err=""):
            self.returncode, self.stderr, self.stdout = code, err, ""

    def exec(cmd, capture_output, text):
        doc = cmd[2]
        key = os.path.basename(doc)[len("srep-0000-"):-len(".xml")]
        if key in refuse:
            return Result(1, f"error: PL5 {key} refused\n")
        if cmd[1] == "encode":
            out = os.path.join(cmd[cmd.index("--out-dir") + 1], "out")
            os.makedirs(out, exist_ok=True)
            sk.write_exr(os.path.join(out, f"{key}_0000.exr"), frames[key].astype(np.float32))
            return Result(0)
        assert cmd[1] == "render"
        target = cmd[cmd.index("-o") + 1]
        if "-f" in cmd:
            Image.fromarray(frames["seek-alone"], "RGB").save(target)
        else:
            assert cmd[cmd.index("--frames") + 1] == f"0..={kit.SEEK_FRAMES}"
            Image.fromarray(frames["seek-played"], "RGB").save(target % kit.SEEK_FRAMES)
        return Result(0)

    return exec


def test_the_kit_runs_an_engine_and_reports_every_case(synthetic, tmp_path):
    exp, g, frames = synthetic
    report = kit.run("scene-render", str(tmp_path / "kit"), exec=_fake_engine(frames))
    assert list(report) == kit.NAMES and all(r["pass"] for r in report.values()), report
    assert os.path.exists(tmp_path / "kit" / "assets" / "planet-strip.png")
    lines = kit.table(report).splitlines()
    assert lines[0] == "| Case | Measured | Pass |" and len(lines) == 2 + len(kit.NAMES) and all(l.endswith("| yes |") for l in lines[2:])
    report = kit.run("scene-render", str(tmp_path / "kit2"), exec=_fake_engine(frames, refuse=("planet-sun", "planet-seek")),
                     only=["planet-limb", "planet-sun", "planet-seek"])
    assert list(report) == ["planet-limb", "planet-sun", "planet-seek"]
    assert report["planet-limb"]["pass"] and not report["planet-sun"]["pass"] and not report["planet-seek"]["pass"]
    assert report["planet-sun"]["error"] == "planet-sun: error: PL5 planet-sun refused"
    assert report["planet-seek"]["error"] == "error: PL5 planet-seek refused"
    assert "| planet-sun | error planet-sun: error: PL5 planet-sun refused | no |" in kit.table(report)


def test_the_draft_describes_the_kit(draft):  # noqa: E501
    for phrase in ("`conformance/tools/planets_kit.py`", "`srep-<n>-planet-limb.xml`", "synthetic textures",
                   "`limb_pixel_extents`", "`isophote_points`", "`pixel_surface_point`", "36 sectors",
                   "orthographic", "`QSTRIP`", "spheroid", "`segments=\"256\"`", "`specular=\"0\"`",
                   "frame 600 rendered alone", "with flattening f the\n   meridian ellipse", "no night side",
                   "whole surface is night", '`twilight="0"`', "projection's axis",
                   "spheroid scaled by 1 + `cloudHeight`", "white diffuse surface", "uniform scale"):
        assert phrase in draft, phrase


KIT_ROW = re.compile(r"^\| `srep-<n>-planet-([a-z]+)\.xml` \| (?:[^|]|\\\|)* \| ([^|]*) \|$")
ENGINE_COMMIT = "e107893"


def test_the_draft_records_the_kit_cases_measured_so_far(draft):
    rows = {m.group(1): m.group(2) for m in (KIT_ROW.match(line) for line in draft.splitlines()) if m}
    assert sorted(rows) == sorted(name[len("planet-"):] for name in kit.NAMES)
    prefix = f"measured on scene-render feat/sr-67-fields {ENGINE_COMMIT} (0.8.0, llvmpipe): "
    measured = {name for name, status in rows.items() if status.startswith(prefix)}
    for name, status in rows.items():
        if name in measured:
            assert status.endswith("; pass") or status.endswith("; fail"), (name, status)
        else:
            assert status == "to be measured", (name, status)
    assert measured == set(name[len("planet-"):] for name in kit.NAMES)   # every row measured
    assert all(rows[name].endswith("; pass") for name in measured)
