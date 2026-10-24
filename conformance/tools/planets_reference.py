"""Reference implementation of the draft SREP "Add planets and the Sun as bodies"
(srep/srep-0000-planets.md; SP3 of SREP 12, SRC-46).

Standard library only. The module gives:

- the bodies: the IAU 2009 equatorial and polar radii of the Sun, the eight planets and the Moon from NAIF's
  pck00010.tpc, the flattening, the scene radius under pixelsPerMeter and the spheroid's surface points and
  normals;
- the texture mapping: an equirectangular day texture with longitude -180 at the left edge and the prime meridian
  at the centre, and its relation to the engine's UV sphere (u = 0 at +x, the north pole at w = 0);
- the limb and the terminator as circles on the sphere, their cusps, the phase angle and illuminated fraction,
  the pinhole projection of the conformance camera and the lit fraction of the projected disc;
- day and night weights with a twilight band, the Hestroffer-Magnan (1998) limb darkening of the Sun per channel
  and its disc average 2 / (alpha + 2);
- the cloud shell: the texel a surface point's cloud shadow comes from, and the layer's drift;
- rings: the radial strip sample, the planet's shadow on the rings and the rings' shadow on the planet;
- the atmosphere shell's angular band from orbit (the physical-sky draft's atmosphere);
- the frame state (spin and cloud drift) as a pure function of frame, rate and body, and the seek check;
  `main()` prints the draft's numeric table.
"""
import math

RADII = {  # km, IAU 2009 (pck00010.tpc BODYnnn_RADII): (equatorial, polar)
    10: (696000.0, 696000.0),
    199: (2439.7, 2439.7),
    299: (6051.8, 6051.8),
    399: (6378.1366, 6356.7519),
    499: (3396.19, 3376.20),
    599: (71492.0, 66854.0),
    699: (60268.0, 54364.0),
    799: (25559.0, 24973.0),
    899: (24764.0, 24341.0),
    301: (1737.4, 1737.4),
}
SPIN = {  # degrees per day of the IAU 2009 prime meridian (the W rate of the time-frames draft's ROTATION)
    10: 14.18440,
    199: 6.1385025,
    299: -1.4813688,
    399: 360.9856235,
    499: 350.89198226,
    599: 870.5360000,
    699: 810.7939024,
    799: -501.1600928,
    899: 536.3128492,
    301: 13.17635815,
}
CHANNEL_WAVELENGTHS_NM = (610.0, 550.0, 465.0)  # the wavelengths the sRGB red, green and blue channels stand for
HM98_RANGE_NM = (303.0, 1100.0)  # the wavelengths Hestroffer and Magnan (1998) fitted
DAY_S = 86400.0


class PlanetError(ValueError):
    """A body, a value or a geometry the draft does not admit."""


# ------------------------------------------------------------------------------------ vectors


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n == 0.0:
        raise PlanetError("a zero vector has no direction")
    return (a[0] / n, a[1] / n, a[2] / n)


def angle(a, b):
    """Angle between two vectors, radians."""
    c = dot(a, b) / (norm(a) * norm(b))
    return math.acos(max(-1.0, min(1.0, c)))


def rounded(v, digits=9):
    """Round a number or a tuple and turn -0.0 into 0.0 (for printing)."""
    if isinstance(v, tuple):
        return tuple(rounded(x, digits) for x in v)
    r = round(v, digits)
    return 0.0 if r == 0.0 else r


def _basis(axis):
    """Two unit vectors perpendicular to `axis` and to each other."""
    a = unit(axis)
    helper = (0.0, 0.0, 1.0) if abs(a[2]) < 0.9 else (1.0, 0.0, 0.0)
    e1 = unit(cross(helper, a))
    e2 = cross(a, e1)
    return e1, e2


# ------------------------------------------------------------------------------------ rule 1: bodies, radii, textures


def _radii(body):
    if body not in RADII:
        raise PlanetError(f"no radii for body {body}; the draft covers {sorted(RADII)}")
    return RADII[body]


def flattening(body):
    """(a - c) / a of the IAU spheroid."""
    a, c = _radii(body)
    return (a - c) / a


def scene_radius(body, pixels_per_meter, radius_km=None):
    """The body's equatorial radius in scene units under `pixelsPerMeter` (SREP 4)."""
    if not (pixels_per_meter > 0.0):
        raise PlanetError("pixelsPerMeter is positive")
    km = _radii(body)[0] if radius_km is None else radius_km
    if not (km > 0.0):
        raise PlanetError("the radius is positive")
    return km * 1000.0 * pixels_per_meter


def _check_lon_lat(lon, lat):
    if not (math.isfinite(lon) and -90.0 <= lat <= 90.0):
        raise PlanetError("longitude is finite and latitude within [-90, 90]")


def texture_uv(lon, lat):
    """Texel of an equirectangular map: longitude -180 at the left edge, the prime meridian at the centre, the
    north pole at the top (u = lon / 360 + 1/2 wrapped into [0, 1), v = (90 - lat) / 180)."""
    _check_lon_lat(lon, lat)
    return ((lon / 360.0 + 0.5) % 1.0, (90.0 - lat) / 180.0)


def engine_uv(lon, lat):
    """The engine's UV-sphere coordinates of a longitude and latitude: u = 0 at +x (longitude 0), w = 0 at the
    north pole (prim.rs `sphere`), so the day texture is read at u + 1/2."""
    _check_lon_lat(lon, lat)
    return ((lon / 360.0) % 1.0, (90.0 - lat) / 180.0)


def engine_normal(u, w):
    """The engine's UV sphere normal (prim.rs): (sin(pi w) cos(2 pi u), -cos(pi w), sin(pi w) sin(2 pi u))."""
    th, ph = u * 2.0 * math.pi, w * math.pi
    return (math.sin(ph) * math.cos(th), -math.cos(ph), math.sin(ph) * math.sin(th))


def body_direction(lon, lat):
    """Unit vector in the body frame: x toward the prime meridian, z toward the north pole."""
    _check_lon_lat(lon, lat)
    lo, la = math.radians(lon), math.radians(lat)
    return (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))


def scene_from_body(v):
    """The scene's axes (SREP 4: y down): the body's pole is the scene's -y, the body's y is the scene's z."""
    return (v[0], -v[2], v[1])


def surface_point(a, f, lon, lat):
    """A point of the spheroid of equatorial radius `a` and flattening `f` at geodetic longitude and latitude."""
    if not (a > 0.0) or not (0.0 <= f < 1.0):
        raise PlanetError("the equatorial radius is positive and the flattening within [0, 1)")
    _check_lon_lat(lon, lat)
    lo, la = math.radians(lon), math.radians(lat)
    e2 = 2.0 * f - f * f
    n = a / math.sqrt(1.0 - e2 * math.sin(la) ** 2)
    return (n * math.cos(la) * math.cos(lo), n * math.cos(la) * math.sin(lo), n * (1.0 - e2) * math.sin(la))


def surface_normal(a, f, p):
    """The outward unit normal of the spheroid at a surface point (the gradient of its implicit equation)."""
    c = a * (1.0 - f)
    return unit((p[0] / (a * a), p[1] / (a * a), p[2] / (c * c)))


# ------------------------------------------------------------------------------------ rule 2: limb and terminator


def limb(eye, radius):
    """The limb of a sphere of `radius` at the origin seen from `eye`: its angular radius (degrees), and the
    circle's centre and radius (the plane eye . p = radius^2)."""
    d = norm(eye)
    if not (d > radius > 0.0):
        raise PlanetError("the eye is outside the sphere")
    e = unit(eye)
    return {"angular_radius": math.degrees(math.asin(radius / d)), "centre": mul(e, radius * radius / d),
            "radius": radius * math.sqrt(1.0 - (radius / d) ** 2)}


def limb_points(eye, radius, n):
    """`n` points around the limb circle."""
    lb = limb(eye, radius)
    e1, e2 = _basis(eye)
    out = []
    for k in range(n):
        t = 2.0 * math.pi * k / n
        out.append(add(lb["centre"], mul(add(mul(e1, math.cos(t)), mul(e2, math.sin(t))), lb["radius"])))
    return out


def terminator_half_angle(radius, sun_distance):
    """The angular radius of the lit cap, degrees: 90 minus the Sun's angular radius as seen from the body's
    centre... for a point Sun at `sun_distance` the cap's edge is where the Sun grazes the horizon."""
    if not (sun_distance > radius > 0.0):
        raise PlanetError("the Sun is farther than the body's radius")
    return 90.0 - math.degrees(math.asin(radius / sun_distance))


def terminator_points(sun, radius, n, sun_distance=None):
    """`n` points of the terminator: the great circle normal to the sun direction, or the small circle of the
    lit cap for a point Sun at `sun_distance`."""
    s = unit(sun)
    half = 90.0 if sun_distance is None else terminator_half_angle(radius, sun_distance)
    e1, e2 = _basis(s)
    ch, sh = math.cos(math.radians(half)), math.sin(math.radians(half))
    out = []
    for k in range(n):
        t = 2.0 * math.pi * k / n
        ring = add(mul(e1, math.cos(t)), mul(e2, math.sin(t)))
        out.append(mul(add(mul(s, ch), mul(ring, sh)), radius))
    return out


def lit(p, sun):
    """Whether a surface point (or its normal) faces the Sun."""
    return dot(p, sun) > 0.0


def phase_angle(eye, sun):
    """Sun-body-observer angle, degrees."""
    return math.degrees(angle(eye, sun))


def illuminated_fraction(phase):
    """The lit fraction of the disc at a phase angle, degrees: (1 + cos i) / 2."""
    if not (0.0 <= phase <= 180.0):
        raise PlanetError("the phase angle is within [0, 180]")
    return (1.0 + math.cos(math.radians(phase))) / 2.0


def cusps(eye, sun, radius):
    """The two points where the terminator meets the limb, or None when the visible disc is wholly lit or
    wholly dark (the Sun within the limb's angular radius of the line of sight or its opposite)."""
    d = norm(eye)
    if not (d > radius > 0.0):
        raise PlanetError("the eye is outside the sphere")
    e, s = unit(eye), unit(sun)
    c = dot(e, s)
    if 1.0 - c * c < 1e-12:
        return None
    a = radius * radius / (d * (1.0 - c * c))
    p0 = add(mul(e, a), mul(s, -a * c))
    t2 = radius * radius - dot(p0, p0)
    if t2 <= 0.0:
        return None
    line = unit(cross(e, s))
    t = math.sqrt(t2)
    return (add(p0, mul(line, t)), add(p0, mul(line, -t)))


def camera(eye, target, up, focal_pixels):
    """A pinhole camera at `eye` looking at `target`; `focal_pixels` is the focal length in pixels."""
    if not (focal_pixels > 0.0):
        raise PlanetError("the focal length is positive")
    forward = unit(sub(target, eye))
    right = unit(cross(forward, up))
    return {"eye": tuple(eye), "forward": forward, "right": right, "up": cross(right, forward),
            "focal": float(focal_pixels)}


def project(cam, p):
    """Pixel offset (x right, y down) from the frame's centre of a point in front of the camera."""
    v = sub(p, cam["eye"])
    z = dot(v, cam["forward"])
    if not (z > 0.0):
        raise PlanetError("the point is behind the camera")
    return (cam["focal"] * dot(v, cam["right"]) / z, -cam["focal"] * dot(v, cam["up"]) / z)


def limb_pixel_radius(cam, eye, radius):
    """The radius in pixels of the disc of a body at the frame's centre."""
    return cam["focal"] * math.tan(math.radians(limb(eye, radius)["angular_radius"]))


def visible(eye, p, radius):
    """Whether a point of the sphere faces the eye (eye . p > radius^2)."""
    return dot(eye, p) > radius * radius


def _ray_sphere(origin, direction, radius):
    """The nearest positive distance along a unit ray to a sphere at the origin, or None."""
    b = 2.0 * dot(origin, direction)
    c = dot(origin, origin) - radius * radius
    disc = b * b - 4.0 * c
    if disc < 0.0:
        if disc > -1e-9 * max(b * b, 1.0):
            disc = 0.0
        else:
            return None
    root = math.sqrt(disc)
    for t in ((-b - root) / 2.0, (-b + root) / 2.0):
        if t > 0.0:
            return t
    return None


def _pixel_ray(cam, x, y):
    f = cam["focal"]
    d = add(cam["forward"], add(mul(cam["right"], x / f), mul(cam["up"], -y / f)))
    return unit(d)


def disc_mu(cam, eye, radius, x, y):
    """cos of the angle between the surface normal and the line of sight at a pixel of the disc, or None off it."""
    d = _pixel_ray(cam, x, y)
    t = _ray_sphere(eye, d, radius)
    if t is None:
        return None
    p = add(eye, mul(d, t))
    return max(0.0, min(1.0, -dot(unit(p), d)))


def lit_fraction(eye, sun, radius, n):
    """The lit fraction of the projected disc, sampled on an n x n grid of a camera looking at the centre."""
    if n < 2:
        raise PlanetError("at least two samples per axis")
    cam = camera(eye, (0.0, 0.0, 0.0), _basis(eye)[0], 1000.0)
    r = limb_pixel_radius(cam, eye, radius)
    s = unit(sun)
    inside = lit_count = 0
    for i in range(n):
        y = -r + (i + 0.5) * 2.0 * r / n
        for j in range(n):
            x = -r + (j + 0.5) * 2.0 * r / n
            d = _pixel_ray(cam, x, y)
            t = _ray_sphere(eye, d, radius)
            if t is None:
                continue
            inside += 1
            if lit(add(eye, mul(d, t)), s):
                lit_count += 1
    return lit_count / inside


# ------------------------------------------------------------------------------------ rule 3: shading, night lights, limb darkening


def day_weight(normal, sun):
    """Lambert's cosine, clamped."""
    return max(0.0, dot(normal, sun))


def night_weight(normal, sun, twilight):
    """The weight of the night-lights map: 1 when the Sun is `twilight` degrees or more below the horizon, 0 when
    as far above it, 1/2 at the terminator, linear in the Sun's elevation between."""
    if not (twilight > 0.0):
        raise PlanetError("the twilight band is positive")
    e = math.degrees(math.asin(max(-1.0, min(1.0, dot(normal, sun)))))
    return max(0.0, min(1.0, 0.5 - e / (2.0 * twilight)))


def limb_alpha(nm):
    """Hestroffer and Magnan (1998) eq. 5: the exponent of I(mu) / I(1) = mu^alpha at a wavelength in nm, from
    their fit over 303 to 1099 nm; the band between 1 / 2.4 and 1 / 2.8 micrometres (357 to 417 nm) is not
    covered by either branch and is refused."""
    if not (HM98_RANGE_NM[0] <= nm <= HM98_RANGE_NM[1]):
        raise PlanetError("the Hestroffer-Magnan fit covers 303 to 1100 nm")
    inv = 1000.0 / nm  # 1 / lambda in inverse micrometres
    if inv <= 2.4:
        return -0.023 + 0.292 * inv
    if inv >= 2.8:
        return -0.507 + 0.441 * inv
    raise PlanetError("no fit between 357 and 417 nm")


def limb_darkening(mu, alpha):
    """I(mu) / I(1) = mu^alpha."""
    if not (0.0 <= mu <= 1.0):
        raise PlanetError("mu is within [0, 1]")
    return mu ** alpha


def disc_average(alpha):
    """The disc-averaged intensity over the central one: 2 / (alpha + 2)."""
    return 2.0 / (alpha + 2.0)


def disc_average_numeric(alpha, n):
    """The same by the midpoint rule over the disc's radius, mu = sqrt(1 - r^2)."""
    total = 0.0
    for k in range(n):
        r = (k + 0.5) / n
        total += 2.0 * r * math.sqrt(1.0 - r * r) ** alpha / n
    return total


def solar_disc(mu):
    """The limb-darkened Sun's linear colour relative to its centre, per channel."""
    return tuple(limb_darkening(mu, limb_alpha(nm)) for nm in CHANNEL_WAVELENGTHS_NM)


# ------------------------------------------------------------------------------------ rule 4: clouds


def cloud_shadow_point(p, sun, radius, height):
    """The point of the cloud shell (radius * (1 + height)) whose texel shadows the surface point `p`, or None
    when the Sun is below p's horizon."""
    if not (height > 0.0):
        raise PlanetError("the cloud height is a positive fraction of the radius")
    s = unit(sun)
    if not lit(p, s):
        return None
    shell = radius * (1.0 + height)
    b = dot(p, s)
    t = -b + math.sqrt(b * b - dot(p, p) + shell * shell)
    return add(p, mul(s, t))


def cloud_longitude(seconds, rate):
    """The layer's eastward drift, degrees, after `seconds` at `rate` degrees per second."""
    return (seconds * rate) % 360.0


def clouds_uv(lon, lat, seconds, rate):
    """The cloud texel over a longitude and latitude after the layer drifted eastward."""
    return texture_uv(lon - cloud_longitude(seconds, rate), lat)


# ------------------------------------------------------------------------------------ rule 5: rings


def ring_sample(strip, rho, inner, outer):
    """Linear interpolation of a radial strip of RGBA samples across [inner, outer]; None outside."""
    if not (outer > inner > 0.0) or len(strip) < 2:
        raise PlanetError("the ring spans a positive range and the strip has two samples or more")
    if rho < inner or rho > outer:
        return None
    x = (rho - inner) / (outer - inner) * (len(strip) - 1)
    i = min(int(x), len(strip) - 2)
    f = x - i
    return tuple(a * (1.0 - f) + b * f for a, b in zip(strip[i], strip[i + 1]))


def ring_shadowed_by_planet(q, sun, radius):
    """Whether a point of the ring plane lies in the planet's shadow: its ray toward the Sun hits the sphere."""
    return _ray_sphere(q, unit(sun), radius) is not None


def planet_shadow_on_rings(sun, radius):
    """Semi-axes of the ellipse the planet's shadow cuts in the ring plane (z = 0), along and across the Sun's
    projected direction, or None when the Sun is in the plane."""
    s = unit(sun)
    if s[2] == 0.0:
        return None
    return (radius / abs(s[2]), radius)


def ring_crossing(p, sun):
    """The radius at which the sun ray from a surface point crosses the ring plane ahead of it, or None."""
    s = unit(sun)
    if s[2] == 0.0:
        return None
    t = -p[2] / s[2]
    if t <= 0.0:
        return None
    q = add(p, mul(s, t))
    return math.hypot(q[0], q[1])


def ring_shadow(p, sun, strip, inner, outer):
    """The light reaching a surface point through the rings: 1 - alpha of the strip at the crossing radius."""
    rho = ring_crossing(p, sun)
    if rho is None:
        return 1.0
    sample = ring_sample(strip, rho, inner, outer)
    if sample is None:
        return 1.0
    return 1.0 - max(0.0, min(1.0, sample[3]))


# ------------------------------------------------------------------------------------ rule 6: atmosphere shell


def shell_band(distance, radius, height):
    """From a point at `distance` from the centre: the angles from the nadir of the planet's limb and of the
    atmosphere shell's edge, degrees; None for an edge the point is inside of."""
    if not (height > 0.0) or not (radius > 0.0):
        raise PlanetError("the radius and the shell height are positive")
    top = radius + height
    planet = math.degrees(math.asin(radius / distance)) if distance > radius else None
    shell = math.degrees(math.asin(top / distance)) if distance > top else None
    return {"planet": planet, "shell": shell}


# ------------------------------------------------------------------------------------ rule 7: frames and seek


def spin_degrees(body, seconds):
    """The body's rotation about its pole after `seconds`, degrees (signed, not wrapped)."""
    if body not in SPIN:
        raise PlanetError(f"no rotation rate for body {body}")
    return SPIN[body] * seconds / DAY_S


def frame_state(frame, fps, rate, cloud_rotation, body):
    """The state of a frame: scene seconds, the cloud layer's drift and the body's spin, each a pure function of
    the frame index, the frame rate, the clock's rate and the document's constants."""
    if not (frame >= 0) or not (fps > 0) or not (rate >= 0.0):
        raise PlanetError("frame is non-negative, fps positive and the rate non-negative")
    seconds = frame / fps * rate
    return {"seconds": seconds, "cloud_longitude": cloud_longitude(seconds, cloud_rotation),
            "spin": spin_degrees(body, seconds)}


def seek_test(frames=600, fps=24, rate=60.0, cloud_rotation=0.01, body=399):
    """Frame `frames` computed alone equals the state reached by stepping every frame from 0 (SREP 14)."""
    direct = frame_state(frames, fps, rate, cloud_rotation, body)
    lon = spin = 0.0
    for k in range(frames):
        step = rate / fps
        lon = (lon + step * cloud_rotation) % 360.0
        spin += spin_degrees(body, step)
    return (math.isclose(lon, direct["cloud_longitude"], abs_tol=1e-6)
            and math.isclose(spin, direct["spin"], rel_tol=1e-9, abs_tol=1e-6))


# ------------------------------------------------------------------------------------ the draft's numeric table

F = (640 / 2) / math.tan(math.radians(60) / 2)  # the kit camera's focal length in pixels (640 wide, 60 degrees)
EARTH = RADII[399][0]
SATURN = RADII[699][0]
EYE4 = (0.0, -4.0 * EARTH, 0.0)
EYE5 = (0.0, -5.0 * EARTH, 0.0)
SUN45 = (math.sqrt(0.5), -math.sqrt(0.5), 0.0)
SATURN_SUN = (math.cos(math.radians(26.7)), 0.0, math.sin(math.radians(26.7)))
STRIP = ((0.6, 0.6, 0.5, 0.2), (0.8, 0.75, 0.6, 0.9), (0.0, 0.0, 0.0, 0.0), (0.9, 0.85, 0.7, 0.6))

TABLE = [
    ("Earth radii (km)", "RADII[399]", "(6378.14, 6356.75)"),
    ("Saturn radii (km)", "RADII[699]", "(60268, 54364)"),
    ("Sun radius (km)", "RADII[10][0]", "696000"),
    ("Earth flattening", "flattening(399)", "0.00335281"),
    ("Saturn flattening", "flattening(699)", "0.0979624"),
    ("Earth scene radius at 1e-6 px/m", "scene_radius(399, 1e-6)", "6.37814"),
    ("Sun scene radius at 1e-9 px/m", "scene_radius(10, 1e-9)", "0.696"),
    ("texture uv of the prime meridian", "texture_uv(0.0, 0.0)", "(0.5, 0.5)"),
    ("texture uv of the north-west corner", "texture_uv(-180.0, 90.0)", "(0, 0)"),
    ("texture uv of 90 E, 90 S", "texture_uv(90.0, -90.0)", "(0.75, 1)"),
    ("engine uv of 90 E", "engine_uv(90.0, 0.0)", "(0.25, 0.5)"),
    ("engine normal at u 0.25", "rounded(engine_normal(0.25, 0.5))", "(0, 0, 1)"),
    ("scene direction of 90 E", "rounded(scene_from_body(body_direction(90.0, 0.0)))", "(0, 0, 1)"),
    ("Earth's pole (km)", "rounded(surface_point(EARTH, flattening(399), 0.0, 90.0), 4)", "(0, 0, 6356.75)"),
    ("limb angular radius from 4 Earth radii (deg)", "limb(EYE4, EARTH)['angular_radius']", "14.4775"),
    ("limb circle radius from 4 Earth radii (km)", "limb(EYE4, EARTH)['radius']", "6175.6"),
    ("limb pixel radius from 4 Earth radii", "limb_pixel_radius(camera(EYE4, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), F), EYE4, EARTH)", "143.108"),
    ("terminator half-angle, Earth from the Sun (deg)", "terminator_half_angle(EARTH, 149597870.7)", "89.9976"),
    ("phase angle at 45 degrees", "phase_angle(EYE5, SUN45)", "45"),
    ("illuminated fraction at 60 degrees", "illuminated_fraction(60.0)", "0.75"),
    ("cusp height over the radius", "cusps(EYE5, SUN45, EARTH)[0][2] / EARTH", "0.959166"),
    ("lit fraction of the disc at 45 degrees", "lit_fraction((0.0, -200.0 * EARTH, 0.0), SUN45, EARTH, 200)", "0.85497"),
    ("day weight at 45 degrees", "day_weight(unit((1.0, 0.0, 1.0)), (0.0, 0.0, 1.0))", "0.707107"),
    ("night weight 3 degrees below the horizon", "night_weight(body_direction(93.0, 0.0), (1.0, 0.0, 0.0), 6.0)", "0.75"),
    ("limb-darkening exponent at 610 nm", "limb_alpha(610.0)", "0.455689"),
    ("limb-darkening exponent at 550 nm", "limb_alpha(550.0)", "0.507909"),
    ("limb-darkening exponent at 465 nm", "limb_alpha(465.0)", "0.604957"),
    ("limb-darkening exponent at 1000 nm", "limb_alpha(1000.0)", "0.269"),
    ("intensity at mu 0.25, 550 nm", "limb_darkening(0.25, limb_alpha(550.0))", "0.494548"),
    ("disc average at 550 nm", "disc_average(limb_alpha(550.0))", "0.797477"),
    ("disc average by quadrature", "disc_average_numeric(limb_alpha(550.0), 4000)", "0.797481"),
    ("solar disc colour at mu 0.1", "solar_disc(0.1)", "(0.350196, 0.310521, 0.248338)"),
    ("cloud shadow shift at 60 N, sun over the pole (deg)",
     "math.degrees(angle(surface_point(EARTH, 0.0, 0.0, 60.0), cloud_shadow_point(surface_point(EARTH, 0.0, 0.0, 60.0), (0.0, 0.0, 1.0), EARTH, 0.004)))",
     "0.131704"),
    ("cloud drift after 100 s at 1.5 deg/s", "cloud_longitude(100.0, 1.5)", "150"),
    ("ring sample between the first two texels", "ring_sample(STRIP, 1.239 + (2.269 - 1.239) / 6.0, 1.239, 2.269)", "(0.7, 0.675, 0.55, 0.55)"),
    ("Saturn's shadow on the rings, semi-axes over the radius", "tuple(x / SATURN for x in planet_shadow_on_rings(SATURN_SUN, SATURN))", "(2.22559, 1)"),
    ("ring crossing from 20 S on the noon meridian, over the radius", "ring_crossing(surface_point(SATURN, 0.0, 0.0, -20.0), SATURN_SUN) / SATURN", "1.61972"),
    ("light through the rings at 20 S", "ring_shadow(surface_point(SATURN, 0.0, 0.0, -20.0), SATURN_SUN, STRIP, 1.239 * SATURN, 2.269 * SATURN)", "0.198014"),
    ("atmosphere band from 400 km (deg)", "shell_band(6360.0 + 400.0, 6360.0, 100.0)", "{'planet': 70.1911, 'shell': 72.8666}"),
    ("one sidereal day of spin (deg)", "spin_degrees(399, 86164.0962)", "360"),
    ("Saturn's spin in an hour (deg)", "spin_degrees(699, 3600.0)", "33.7831"),
    ("cloud drift at frame 600", "frame_state(600, 24, 60.0, 0.01, 399)['cloud_longitude']", "15"),
    ("seek check", "seek_test()", "True"),
]


def scope():
    s = dict(globals())
    s["math"] = math
    return s


def _same(a, b, rel=5e-4, abs_tol=5e-4):
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k!r}: {_fmt(x)}" for k, x in v.items()) + "}"
    return repr(v)


def main():
    s = scope()
    for name, expr, _ in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
