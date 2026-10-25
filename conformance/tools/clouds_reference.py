"""Reference for the draft SREP "Add cloud layers and the night sky" (A3 of SREP 12).

A `cloudLayer` child of a dome light with `sky="physical"` is a spherical shell of cloud above the planet whose
shape is the random-streams draft's value noise dilated by Worley billows (Schneider and Vos 2015), shaped by a
height gradient blended from the stratus, stratocumulus and cumulus presets, thresholded so that the covered
fraction of the layer equals the weather map's coverage, eroded by a Worley detail noise and carried by an F4
wind. Light through the cloud follows Beer's law with the "powder" term and the multiple-scattering octaves of
Wrenninge, the phase function is the media draft's `fog` fit (Jendersie and d'Eon 2023). The night sky adds the
moon by the Lommel-Seeliger irradiance of Jensen et al. 2001 with earthshine, the Hapke-Lommel-Seeliger disc,
the airglow with the van Rhijn brightening and the uniform starlight and galactic background.

Every quantity is in the physical sky's frame: metres, the planet's centre at the origin, +z up at the observer,
x east and y north, radiance in units of the sun's irradiance. `python clouds_reference.py` prints the numeric
table of the draft's conformance section.
"""
from __future__ import annotations

import importlib.util
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PURPOSE = "clouds"
BASE_VALUE = 1
BASE_WORLEY = (2, 3, 4)
DETAIL_WORLEY = (5, 6, 7)
OCTAVE_STRIDE = 1024
MAX_OCTAVES = 3
WORLEY_WEIGHTS = (0.625, 0.25, 0.125)
PRESETS = {"stratus": (0.0, 0.1, 0.2, 0.3), "stratocumulus": (0.0, 0.15, 0.45, 0.6), "cumulus": (0.0, 0.1, 0.7, 1.0)}
CALIBRATION_POINTS = 32
CALIBRATION_CELLS = 8
RANGE = 35000.0
DEFAULT_FPS = 24
MS_ATTENUATION = 0.5
MS_CONTRIBUTION = 0.5
MS_ECCENTRICITY = 0.5
RAIN_COVERAGE = 0.7
RAIN_ALBEDO = 0.25
PHASE_STEPS = 20000

E_SUN = 1361.0
MOON_ALBEDO = 0.072
HAPKE_G = 0.6
HAPKE_T = 0.1
EARTHSHINE_FULL = 0.19
STARLIGHT = 3e-8
AIRGLOW = 5.1e-8
GALACTIC = 1e-8
AIRGLOW_HEIGHT = 80000.0
MOON_RAMP = ((340.0, 0.70), (740.0, 1.35))
MOON_WAVELENGTHS = (650.0, 550.0, 450.0)

DEFAULTS = {"base": 1500.0, "thickness": 2500.0, "coverage": 0.5, "type": 0.5, "precipitation": 0.0,
            "weather": None, "weatherScale": 20000.0, "density": 0.02, "scale": 4000.0, "detailScale": 500.0,
            "detail": 0.3, "octaves": 3, "wind": None, "dropletDiameter": 20.0, "albedo": 0.95, "ambient": 1.0,
            "seed": None}
LIGHT_DEFAULTS = {"airglow": 1.0, "starlight": 1.0, "earthshine": 1.0, "atmosphereHeight": 100000.0}


class CloudError(ValueError):
    """A cloud layer or a night-sky quantity outside the draft's rules."""


# ------------------------------------------------------------------------------------------------- the references

_MODULES = {}


def _module(name):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULES[name] = mod
    return _MODULES[name]


def wind():
    """The F4 wind reference (displacement of the layer, the value noise with its gradient)."""
    return _module("wind_reference")


def streams():
    """The random-streams reference (U, pack, E)."""
    return wind().streams()


def media():
    """The F3 media reference (the HG and Draine phase functions and the fog fit)."""
    return _module("media_reference")


def sky():
    """The A1 physical-sky reference (atmosphere, sun, moon, transmittance, sky radiance)."""
    return _module("physical_sky_reference")


PLANET_RADIUS = sky().atmosphere()["planet_radius"]
MOON_RADIUS_KM = sky().MOON_RADIUS_KM


# ------------------------------------------------------------------------------------------- seeds and helpers


def element_seed(project, layer_id, seed):
    """Rule 1: the layer's seed is E(project, id, @seed, "clouds")."""
    return streams().E(project, layer_id, seed, PURPOSE)


def _v(layer, key):
    return layer.get(key, DEFAULTS[key])


def _lv(light, key):
    return light.get(key, LIGHT_DEFAULTS[key])


def layer_seed(doc, layer):
    return element_seed(doc.get("project", {}).get("seed", 0), layer.get("id"), _v(layer, "seed"))


def remap(value, lo, hi, a, b):
    """Rule 2: the clamped linear remap of [lo, hi] onto [a, b]."""
    if not hi > lo:
        raise CloudError(f"remap needs lo < hi, got {lo!r} and {hi!r}")
    t = (value - lo) / (hi - lo)
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return a + (b - a) * t


def _clamp01(x):
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _octaves(n):
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_OCTAVES:
        raise CloudError(f"octaves is 1 to {MAX_OCTAVES}, got {n!r}")
    return n


# ------------------------------------------------------------------------------------------------------- noises


def value_fbm(e, q, octaves):
    """Rule 3: the wind draft's value noise on channel 1024 + k for octave k, mapped to [0, 1], summed with
    weights 1/2^k at frequencies 2^k."""
    n = _octaves(octaves)
    w = wind()
    total = 0.0
    norm = 0.0
    for k in range(n):
        f = 2.0 ** k
        a = 0.5 ** k
        v = w.value3(e, BASE_VALUE * OCTAVE_STRIDE + k, q[0] * f, q[1] * f, q[2] * f)[0]
        total += a * (v + 1.0) / 2.0
        norm += a
    return total / norm


def feature_point(e, channels, i, j, k, octave=0):
    """Rule 4: the Worley feature point of lattice cell (i, j, k): the cell's corner plus three uniform draws
    on the channels' octave lanes at pack(i, j, k)."""
    rs = streams()
    idx = rs.pack(i, j, k)
    return (i + rs.U(e, channels[0] * OCTAVE_STRIDE + octave, idx),
            j + rs.U(e, channels[1] * OCTAVE_STRIDE + octave, idx),
            k + rs.U(e, channels[2] * OCTAVE_STRIDE + octave, idx))


def worley_f1(e, channels, q, octave=0):
    """Rule 4: the distance to the nearest feature point of the 27 cells around q, at most 1."""
    i0, j0, k0 = (math.floor(c) for c in q)
    best = 1.0
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for dk in (-1, 0, 1):
                f = feature_point(e, channels, i0 + di, j0 + dj, k0 + dk, octave)
                d = math.sqrt((q[0] - f[0]) ** 2 + (q[1] - f[1]) ** 2 + (q[2] - f[2]) ** 2)
                if d < best:
                    best = d
    return best


def worley_fbm(e, channels, q, octaves):
    """Rule 4: the inverted F1 noise summed over octaves with the weights 0.625, 0.25, 0.125 at frequencies
    2^k."""
    n = _octaves(octaves)
    total = 0.0
    norm = 0.0
    for k in range(n):
        f = 2.0 ** k
        total += WORLEY_WEIGHTS[k] * (1.0 - worley_f1(e, channels, (q[0] * f, q[1] * f, q[2] * f), k))
        norm += WORLEY_WEIGHTS[k]
    return total / norm


def base_shape(e, q, octaves):
    """Rule 5: the value noise dilated by the Worley billows, remap(value, worley - 1, 1, 0, 1)."""
    return remap(value_fbm(e, q, octaves), worley_fbm(e, BASE_WORLEY, q, octaves) - 1.0, 1.0, 0.0, 1.0)


# ------------------------------------------------------------------------------------------------- the layer


def band(h, a, b, c, d):
    """Rule 6: a height band that rises from a to b and falls from c to d."""
    return remap(h, a, b, 0.0, 1.0) * (1.0 - remap(h, c, d, 0.0, 1.0))


def height_gradient(h, cloud_type):
    """Rule 6: the stratus, stratocumulus and cumulus bands blended by the cloud type (0, 0.5, 1)."""
    s = band(h, *PRESETS["stratus"])
    sc = band(h, *PRESETS["stratocumulus"])
    cu = band(h, *PRESETS["cumulus"])
    t = _clamp01(cloud_type)
    if t <= 0.5:
        u = 2.0 * t
        return s * (1.0 - u) + sc * u
    u = 2.0 * t - 1.0
    return sc * (1.0 - u) + cu * u


def _asset(doc, asset_id):
    for a in doc.get("assets", ()):
        if a.get("id") == asset_id:
            return a
    return None


def _wind_spec(layer, doc):
    wind_id = _v(layer, "wind")
    if wind_id is None:
        return None
    for w in doc.get("physics", {}).get("winds", ()):
        if w.get("id") == wind_id:
            return w
    return None


def drift(layer, doc, t, fps=DEFAULT_FPS):
    """Rule 8: the layer's displacement at time t: the wind draft's displacement of the layer's wind, its
    x along east and its y along north; zero without a wind."""
    w = _wind_spec(layer, doc)
    if w is None:
        return (0.0, 0.0)
    d = wind().displacement(w, t, fps)
    return (d[0], d[1])


def sample_map(asset, u, v):
    """Rule 7: bilinear, tiled sample of a weather map; pixel (i, j) sits at (i, j), values 0 to 255."""
    w, h = asset["width"], asset["height"]
    px = asset["pixels"]
    i0 = math.floor(u)
    j0 = math.floor(v)
    fu = u - i0
    fv = v - j0

    def at(i, j):
        return px[(j % h) * w + (i % w)]

    out = []
    for c in range(3):
        top = at(i0, j0)[c] * (1.0 - fu) + at(i0 + 1, j0)[c] * fu
        bottom = at(i0, j0 + 1)[c] * (1.0 - fu) + at(i0 + 1, j0 + 1)[c] * fu
        out.append((top * (1.0 - fv) + bottom * fv) / 255.0)
    return tuple(out)


def weather_at(layer, doc, m, t, fps=DEFAULT_FPS):
    """Rule 7: (coverage, precipitation, type) at the map point m = (east, north): the layer's attributes, or
    the weather map's red, green and blue sampled at (m - drift) / weatherScale, tiled."""
    if _v(layer, "weather") is None:
        return (float(_v(layer, "coverage")), float(_v(layer, "precipitation")), float(_v(layer, "type")))
    asset = _asset(doc, _v(layer, "weather"))
    if asset is None:
        raise CloudError(f"weather map {_v(layer, 'weather')!r} is not an image asset")
    dx, dy = drift(layer, doc, t, fps)
    s = _v(layer, "weatherScale")
    return sample_map(asset, (m[0] - dx) / s * asset["width"], (m[1] - dy) / s * asset["height"])


def effective_weather(w):
    """Rule 7: precipitation raises the coverage to at least 0.7 of itself and the type toward cumulonimbus."""
    coverage, precipitation, cloud_type = w
    return (max(coverage, RAIN_COVERAGE * precipitation), precipitation, max(cloud_type, precipitation))


def altitude(p):
    """The height of p above the planet's surface."""
    return math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2]) - PLANET_RADIUS


def map_point(p):
    """The (east, north) map coordinates of p: its horizontal position projected to the ground."""
    s = PLANET_RADIUS / math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
    return (p[0] * s, p[1] * s)


def point(x, y, h):
    """The point at map coordinates (x, y) and altitude h."""
    zz = PLANET_RADIUS * PLANET_RADIUS - x * x - y * y
    if zz <= 0.0:
        raise CloudError("the map point is beyond the planet's limb")
    s = (PLANET_RADIUS + h) / PLANET_RADIUS
    return (x * s, y * s, math.sqrt(zz) * s)


def up(p):
    """The unit vector away from the planet's centre at p."""
    r = math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
    return (p[0] / r, p[1] / r, p[2] / r)


def height_fraction(layer, p):
    """Rule 6: 0 at the layer's base and 1 at its top."""
    return (altitude(p) - _v(layer, "base")) / _v(layer, "thickness")


def lattice_point(layer, doc, p, t, fps=DEFAULT_FPS):
    """Rule 8: the noise lattice coordinates of p: the drifted map point and the altitude, over `scale`."""
    dx, dy = drift(layer, doc, t, fps)
    m = map_point(p)
    s = _v(layer, "scale")
    return ((m[0] - dx) / s, (m[1] - dy) / s, altitude(p) / s)


_CALIBRATION = {}


def calibration(layer, e):
    """Rule 9: the sorted base shape over a 32 x 32 grid of 8 x 8 lattice cells at the layer's middle height."""
    qz = (_v(layer, "base") + 0.5 * _v(layer, "thickness")) / _v(layer, "scale")
    n = _v(layer, "octaves")
    key = (e, n, qz)
    if key not in _CALIBRATION:
        pts = CALIBRATION_POINTS
        _CALIBRATION[key] = sorted(base_shape(e, ((i + 0.5) / pts * CALIBRATION_CELLS,
                                                  (j + 0.5) / pts * CALIBRATION_CELLS, qz), n)
                                   for i in range(pts) for j in range(pts))
    return list(_CALIBRATION[key])


def threshold(layer, e, coverage):
    """Rule 9: the base-shape value above which the layer is covered: 1 for no coverage, 0 for full, else the
    (1 - coverage) quantile of the calibration."""
    if coverage <= 0.0:
        return 1.0
    if coverage >= 1.0:
        return 0.0
    cal = calibration(layer, e)
    k = min(len(cal) - 1, max(0, int(math.floor((1.0 - coverage) * len(cal)))))
    return cal[k]


def covered(layer, doc, e, p, t, fps=DEFAULT_FPS):
    """Rule 9: p's column is covered when the base shape exceeds the threshold of the local coverage."""
    q = lattice_point(layer, doc, p, t, fps)
    w = effective_weather(weather_at(layer, doc, map_point(p), t, fps))
    return base_shape(e, q, _v(layer, "octaves")) > threshold(layer, e, w[0])


def covered_fraction(layer, doc, e, t, n):
    """The covered fraction of an n x n grid over the calibration region at the layer's middle height."""
    if n < 1:
        raise CloudError("n is at least 1")
    extent = CALIBRATION_CELLS * _v(layer, "scale")
    h = _v(layer, "base") + 0.5 * _v(layer, "thickness")
    count = 0
    for i in range(n):
        for j in range(n):
            if covered(layer, doc, e, point((i + 0.5) / n * extent, (j + 0.5) / n * extent, h), t):
                count += 1
    return count / (n * n)


def _sample(layer, doc, e, p, t, fps):
    h = height_fraction(layer, p)
    w = effective_weather(weather_at(layer, doc, map_point(p), t, fps))
    if h < 0.0 or h > 1.0:
        return 0.0, w
    n = _v(layer, "octaves")
    q = lattice_point(layer, doc, p, t, fps)
    thr = threshold(layer, e, w[0])
    if thr >= 1.0:
        return 0.0, w
    d = remap(base_shape(e, q, n), thr, 1.0, 0.0, 1.0) * height_gradient(h, w[2])
    detail = _v(layer, "detail")
    if d <= 0.0 or detail <= 0.0:
        return d, w
    r = _v(layer, "scale") / _v(layer, "detailScale")
    wd = worley_fbm(e, DETAIL_WORLEY, (q[0] * r, q[1] * r, q[2] * r), n)
    u = min(1.0, 10.0 * h)
    a = detail * (wd * (1.0 - u) + (1.0 - wd) * u)
    if a >= 1.0:
        return 0.0, w
    return remap(d, a, 1.0, 0.0, 1.0), w


def density_at(layer, doc, e, p, t, fps=DEFAULT_FPS):
    """Rule 10: the normalised density 0 to 1 at p: the thresholded base shape times the height gradient,
    eroded by the detail noise (wispy at the bottom, billowy above)."""
    return _sample(layer, doc, e, p, t, fps)[0]


def extinction(layer, density, precipitation):
    """Rule 11: the extinction coefficient per metre, `density` times the normalised density, doubled under
    full precipitation."""
    return density * _v(layer, "density") * (1.0 + precipitation)


def effective_albedo(layer, precipitation):
    """Rule 11: rain lowers the single-scattering albedo by a quarter at full precipitation."""
    return _v(layer, "albedo") * (1.0 - RAIN_ALBEDO * precipitation)


def _sphere_interval(p, d, radius):
    pd = p[0] * d[0] + p[1] * d[1] + p[2] * d[2]
    pp = p[0] * p[0] + p[1] * p[1] + p[2] * p[2]
    disc = pd * pd - (pp - radius * radius)
    if disc < 0.0:
        return None
    s = math.sqrt(disc)
    return (-pd - s, -pd + s)


def shell_segments(layer, p, d):
    """Rule 12: the ray parameter intervals of p + t d inside the layer's shell, within [0, RANGE]."""
    r_in = PLANET_RADIUS + _v(layer, "base")
    r_out = r_in + _v(layer, "thickness")
    outer = _sphere_interval(p, d, r_out)
    if outer is None:
        return []
    inner = _sphere_interval(p, d, r_in)
    segments = [outer] if inner is None else [(outer[0], inner[0]), (inner[1], outer[1])]
    out = []
    for s0, s1 in segments:
        s0 = max(s0, 0.0)
        s1 = min(s1, RANGE)
        if s1 > s0:
            out.append((s0, s1))
    return out


def optical_depth(layer, doc, e, origin, direction, t, samples, fps=DEFAULT_FPS):
    """Rule 12: the optical depth along the ray by midpoint sums of `samples` steps per shell segment."""
    if not isinstance(samples, int) or samples < 1:
        raise CloudError("samples is at least 1")
    tau = 0.0
    for s0, s1 in shell_segments(layer, origin, direction):
        ds = (s1 - s0) / samples
        for i in range(samples):
            s = s0 + (i + 0.5) * ds
            p = (origin[0] + s * direction[0], origin[1] + s * direction[1], origin[2] + s * direction[2])
            dens, w = _sample(layer, doc, e, p, t, fps)
            tau += extinction(layer, dens, w[1]) * ds
    return tau


def transmittance_along(layer, doc, e, origin, direction, t, samples, fps=DEFAULT_FPS):
    """Rule 12: exp of minus the optical depth."""
    return math.exp(-optical_depth(layer, doc, e, origin, direction, t, samples, fps))


# ------------------------------------------------------------------------------------------------------- lighting


def phase_scaled(mu, diameter, eccentricity):
    """Rule 13: the media draft's fog fit with both asymmetries scaled by `eccentricity` (1 is the fit itself)."""
    m = media()
    p = m.fog_parameters(diameter)
    return ((1.0 - p.w_d) * m.phase_hg(mu, eccentricity * p.g_hg)
            + p.w_d * m.phase_draine(mu, eccentricity * p.g_d, p.alpha))


def phase(mu, diameter):
    """Rule 13: the phase function of the layer's droplets, the media draft's `fog` fit."""
    return phase_scaled(mu, diameter, 1.0)


def _integrate(f, steps=PHASE_STEPS):
    """2 pi times the Simpson integral of f over the sphere, in the variable u with theta = pi u^2: the
    substitution clusters the samples at the forward peak of a strongly anisotropic lobe, which an even grid
    in the cosine would miss."""
    h = 1.0 / steps
    total = 0.0
    for i in range(1, steps):
        u = i * h
        theta = math.pi * u * u
        total += (4.0 if i % 2 else 2.0) * f(math.cos(theta)) * math.sin(theta) * 2.0 * math.pi * u
    return 2.0 * math.pi * total * h / 3.0


def phase_normalisation(diameter):
    """The integral of the phase function over the sphere, 1 for a normalised phase."""
    return _integrate(lambda mu: phase(mu, diameter))


def phase_normalisation_hg(g):
    return _integrate(lambda mu: media().phase_hg(mu, g))


def powder(tau):
    """Rule 14: the powder term 1 - exp(-2 tau)."""
    return 1.0 - math.exp(-2.0 * tau)


def beer_powder(tau):
    """Rule 14: 2 exp(-tau) (1 - exp(-2 tau)), Beer's law times the powder term."""
    return 2.0 * math.exp(-tau) * powder(tau)


def multi_scatter(tau, mu, diameter, octaves):
    """Rule 15: the multiple-scattering octaves: sum over k of b^k exp(-a^k tau) phase(mu, c^k g), with
    a = b = c = 1/2."""
    if not isinstance(octaves, int) or octaves < 1:
        raise CloudError("octaves is at least 1")
    total = 0.0
    for k in range(octaves):
        total += (MS_CONTRIBUTION ** k * math.exp(-(MS_ATTENUATION ** k) * tau)
                  * phase_scaled(mu, diameter, MS_ECCENTRICITY ** k))
    return total


def ambient_weight(h):
    """Rule 16: the weight of the sky's ambient light, 1/2 at the layer's base and 1 at its top."""
    return (1.0 + _clamp01(h)) / 2.0


# ------------------------------------------------------------------------------------------------ the night sky


def phase_law(phase_angle):
    """Rule 17: the Lommel-Seeliger phase law 1 - sin(phi/2) tan(phi/2) ln(cot(phi/4)) for the phase angle in
    degrees; 1 at full moon and 0 at new moon."""
    if phase_angle <= 0.0:
        return 1.0
    if phase_angle >= 180.0:
        return 0.0
    r = math.radians(phase_angle)
    return 1.0 - math.sin(r / 2.0) * math.tan(r / 2.0) * math.log(1.0 / math.tan(r / 4.0))


def earthshine(phase_angle):
    """Rule 17: the earthshine irradiance at the moon, 0.19 x 0.5 times the phase law of the earth's phase
    (pi minus the moon's phase angle), in W/m^2."""
    return EARTHSHINE_FULL * 0.5 * phase_law(180.0 - phase_angle)


def moon_irradiance(phase_angle, distance_km, earthshine_scale=1.0, earthshine=None):
    """Rule 17: Jensen's equation 5, the irradiance from the moon at the ground in W/m^2:
    (2 C r_m^2 / 3 d^2) (E_em + E_sun phase_law(phi))."""
    scale = earthshine_scale if earthshine is None else float(earthshine)
    prefactor = 2.0 * MOON_ALBEDO * (MOON_RADIUS_KM / distance_km) ** 2 / 3.0
    return prefactor * (scale * globals()["earthshine"](phase_angle) + E_SUN * phase_law(phase_angle))


def moon_fraction(phase_angle, distance_km, earthshine_scale=1.0, earthshine=None):
    """Rule 17: the moon's irradiance as a fraction of the sun's 1361 W/m^2."""
    return moon_irradiance(phase_angle, distance_km, earthshine_scale, earthshine) / E_SUN


def moon_solid_angle(distance_km):
    return math.pi * (MOON_RADIUS_KM / distance_km) ** 2


def moon_disc_radiance(phase_angle, distance_km, earthshine_scale=1.0):
    """Rule 18: the mean radiance of the lit disc, the irradiance over the disc's solid angle, in W/m^2/sr."""
    return moon_irradiance(phase_angle, distance_km, earthshine_scale) / moon_solid_angle(distance_km)


def moon_ramp(wavelength_nm):
    """Rule 18: the moon's spectrum relative to the sun's, a ramp from 70 % at 340 nm to 135 % at 740 nm."""
    (l0, r0), (l1, r1) = MOON_RAMP
    return r0 + (wavelength_nm - l0) / (l1 - l0) * (r1 - r0)


def moon_colour():
    """Rule 18: the ramp at 650, 550 and 450 nm."""
    return tuple(moon_ramp(l) for l in MOON_WAVELENGTHS)


def moon_tint():
    """Rule 18: the colour normalised to its green channel, the tint applied to the moon's light."""
    c = moon_colour()
    return tuple(x / c[1] for x in c)


def retrodirective(phase_angle):
    """Rule 18: Hapke's B(phi, g) with g = 0.6: 2 at opposition, 1 from 90 degrees on."""
    if phase_angle >= 90.0:
        return 1.0
    tphi = math.tan(math.radians(phase_angle))
    if tphi <= 0.0:
        return 2.0
    ex = math.exp(-HAPKE_G / tphi)
    return 2.0 - tphi / (2.0 * HAPKE_G) * (1.0 - ex) * (3.0 - ex)


def scattering_law(phase_angle):
    """Rule 18: S(phi) = (sin|phi| + (pi - |phi|) cos|phi|) / pi + t (1 - cos|phi| / 2)^2 with t = 0.1."""
    r = abs(math.radians(phase_angle))
    return (math.sin(r) + (math.pi - r) * math.cos(r)) / math.pi + HAPKE_T * (1.0 - 0.5 * math.cos(r)) ** 2


def moon_brdf(theta_i, theta_r, phase_angle):
    """Rule 18: the Hapke-Lommel-Seeliger BRDF (2 / 3 pi) B S / (1 + cos theta_r / cos theta_i), 0 when the
    sun is below the local horizon; a disc point's radiance is f times the normal irradiance."""
    ci = math.cos(math.radians(theta_i))
    cr = math.cos(math.radians(theta_r))
    if ci <= 0.0 or cr <= 0.0:
        return 0.0
    return 2.0 / (3.0 * math.pi) * retrodirective(phase_angle) * scattering_law(phase_angle) / (1.0 + cr / ci)


def van_rhijn(zenith_angle):
    """Rule 19: the van Rhijn brightening of a layer at 80 km seen at the zenith angle in degrees."""
    if not 0.0 <= zenith_angle <= 90.0:
        raise CloudError("the zenith angle is 0 to 90 degrees")
    ratio = PLANET_RADIUS / (PLANET_RADIUS + AIRGLOW_HEIGHT)
    return 1.0 / math.sqrt(1.0 - ratio * ratio * math.sin(math.radians(zenith_angle)) ** 2)


def airglow_radiance(zenith_angle, scale=1.0):
    """Rule 19: the airglow radiance in the sun's units, 5.1e-8 W/m^2 over pi at the zenith times the van
    Rhijn factor, times the light's `airglow`."""
    return scale * AIRGLOW / (math.pi * E_SUN) * van_rhijn(zenith_angle)


def background_radiance(starlight=1.0, galactic=1.0):
    """Rule 20: the uniform background, integrated starlight 3e-8 (times the light's `starlight`) plus the
    diffuse galactic and cosmic light 1e-8 W/m^2, over pi, in the sun's units."""
    return (starlight * STARLIGHT + galactic * GALACTIC) / (math.pi * E_SUN)


def _to_atmosphere(v):
    """Scene axes (+x east, -y up, +z north) to the physical sky's frame (x east, y north, z up)."""
    return (v[0], v[2], -v[1])


def night_frame(date, latitude, longitude, direction, altitude=0.0, airglow=1.0, starlight=1.0, earthshine=1.0,
                moon=True, samples=8):
    """Rule 21: one frame's sky radiance in a scene-axes direction: the sun's sky plus the moon's sky (the sky
    function lit from the moon's direction, scaled by the moon's irradiance fraction and tint) plus the
    airglow and the background, both through the atmosphere's transmittance."""
    p = sky()
    a = p.atmosphere()
    s = p.sun_from_document(date, latitude, longitude, altitude)
    m = p.moon_from_document(date, latitude, longitude, altitude)
    obs = (0.0, 0.0, a["planet_radius"] + max(0.0, altitude) + 1.0)
    d = p.unit(_to_atmosphere(direction))
    sun_sky = p.sky_radiance(a, obs, d, _to_atmosphere(s["direction"]), samples=samples)
    fraction = moon_fraction(m["phase_angle"], m["distance"], earthshine) if moon else 0.0
    zeros = (0.0, 0.0, 0.0)
    if fraction > 0.0:
        tint = moon_tint()
        lit = p.sky_radiance(a, obs, d, _to_atmosphere(m["direction"]), samples=samples)
        moon_sky = tuple(fraction * tint[c] * lit[c] for c in range(3))
    else:
        moon_sky = zeros
    trans = p.transmittance(a, obs, d)
    cos_z = d[2]
    if cos_z > 0.0:
        glow = airglow_radiance(math.degrees(math.acos(min(1.0, cos_z))), airglow)
        air = tuple(glow * trans[c] for c in range(3))
    else:
        air = zeros
    back = tuple(background_radiance(starlight) * trans[c] for c in range(3))
    radiance = tuple(sun_sky[c] + moon_sky[c] + air[c] + back[c] for c in range(3))
    return {"sun_zenith": s["zenith"], "sun_azimuth": s["azimuth"], "moon_zenith": m["zenith"],
            "moon_azimuth": m["azimuth"], "moon_illuminated": m["illuminated"], "moon_phase_angle": m["phase_angle"],
            "moon_distance": m["distance"], "moon_fraction": fraction, "sun_sky": tuple(sun_sky),
            "moon_sky": moon_sky, "airglow": air, "background": back, "transmittance": tuple(trans),
            "radiance": radiance}


# ---------------------------------------------------------------------------------------------- the documents


def example_layer():
    return {"id": "c1", "seed": 5, "base": 1500.0, "thickness": 2500.0, "coverage": 0.5, "type": 0.5,
            "precipitation": 0.0, "weather": None, "weatherScale": 20000.0, "density": 0.02, "scale": 4000.0,
            "detailScale": 500.0, "detail": 0.3, "octaves": 3, "wind": None, "dropletDiameter": 20.0,
            "albedo": 0.95, "ambient": 1.0}


def example_document():
    return {"version": "1.8", "project": {"seed": 7}, "physics": {"winds": []}, "assets": [],
            "lights": [{"id": "sky", "type": "dome", "sky": "physical", "date": "2003-10-17T04:00:00-07:00",
                        "latitude": 39.742476, "longitude": -105.1786, "airglow": 1.0, "starlight": 1.0,
                        "earthshine": 1.0, "cloudLayers": [example_layer()]}]}


def mapped_document():
    doc = example_document()
    doc["physics"]["winds"] = [wind().example_wind()]
    doc["assets"] = [{"id": "wm", "type": "image", "width": 2, "height": 1, "pixels": [(255, 0, 0), (0, 0, 255)]}]
    layer = doc["lights"][0]["cloudLayers"][0]
    layer["weather"] = "wm"
    layer["wind"] = "w1"
    return doc


def example_seed():
    return element_seed(7, "c1", 5)


def bad_document():
    doc = example_document()
    layer = doc["lights"][0]["cloudLayers"][0]
    layer.update(coverage=2.0, thickness=0.0, dropletDiameter=1.0, wind="ghost")
    doc["lights"][0].update(sky="gradient", airglow=-1.0)
    return doc


# -------------------------------------------------------------------------------------------------- validation


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_layer(layer, doc, light):
    codes = set()
    unit = all(_number(_v(layer, k)) and 0.0 <= _v(layer, k) <= 1.0
               for k in ("coverage", "type", "precipitation", "detail", "albedo"))
    positive = all(_number(_v(layer, k)) and _v(layer, k) > 0.0 for k in ("scale", "detailScale", "weatherScale"))
    nonneg = all(_number(_v(layer, k)) and _v(layer, k) >= 0.0 for k in ("density", "ambient"))
    octaves = _v(layer, "octaves")
    if not (unit and positive and nonneg and isinstance(octaves, int) and not isinstance(octaves, bool)
            and 1 <= octaves <= MAX_OCTAVES):
        codes.add("CN1")
    base, thickness = _v(layer, "base"), _v(layer, "thickness")
    if not (_number(base) and _number(thickness) and base >= 0.0 and thickness > 0.0
            and base + thickness <= _lv(light, "atmosphereHeight")):
        codes.add("CN2")
    d = _v(layer, "dropletDiameter")
    if not (_number(d) and 5.0 <= d <= 50.0):
        codes.add("CN3")
    if _v(layer, "weather") is not None and _asset(doc, _v(layer, "weather")) is None:
        codes.add("CN4")
    if _v(layer, "wind") is not None and _wind_spec(layer, doc) is None:
        codes.add("CN4")
    return codes


def validate_document(doc):
    """The draft's rules CN1 to CN6 and V17 over a document, as sorted codes."""
    codes = set()
    major, minor = (int(x) for x in str(doc.get("version", "1.0")).split(".")[:2])
    new = (major, minor) >= (1, 8)
    for light in doc.get("lights", ()):
        layers = light.get("cloudLayers", [])
        if (layers or any(k in light for k in ("airglow", "starlight", "earthshine"))) and not new:
            codes.add("V17")
            continue
        if layers and light.get("sky") != "physical":
            codes.add("CN5")
        for k in ("airglow", "starlight", "earthshine"):
            if k in light and not (_number(light[k]) and light[k] >= 0.0):
                codes.add("CN6")
        for layer in layers:
            codes |= validate_layer(layer, doc, light)
    return sorted(codes)


# ----------------------------------------------------------------------------------------------- numeric table

DATE = "2003-10-17T04:00:00-07:00"
LAT = 39.742476
LON = -105.1786

TABLE = (
    ("element seed", 'element_seed(7, "c1", 5)', "2483463061"),
    ("remap", "remap(0.75, 0.5, 1.0, 0.0, 1.0)", "0.5"),
    ("value fbm, one octave", "value_fbm(E, (0.37, 0.53, 0.11), 1)", "0.6246452408488397"),
    ("value fbm, three octaves", "value_fbm(E, (0.37, 0.53, 0.11), 3)", "0.5658644685814017"),
    ("feature point", "feature_point(E, BASE_WORLEY, 2, -1, 3)", "(2.6824283768829638, -0.5042499838309308, 3.0599349193743226)"),
    ("Worley F1", "worley_f1(E, BASE_WORLEY, (0.2, 0.3, 0.4))", "0.37212043590414656"),
    ("Worley fbm", "worley_fbm(E, BASE_WORLEY, (0.2, 0.3, 0.4), 3)", "0.5343879844859671"),
    ("base shape", "base_shape(E, (0.2, 0.3, 0.4), 3)", "0.5570028229561091"),
    ("height gradient, stratus", "height_gradient(0.25, 0.0)", "0.5"),
    ("height gradient, cumulus", "height_gradient(0.8, 1.0)", "0.6666666666666664"),
    ("height gradient, blend", "height_gradient(0.5, 0.25)", "0.33333333333333337"),
    ("effective weather", "effective_weather((0.2, 1.0, 0.3))", "(0.7, 1.0, 1.0)"),
    ("weather map", "weather_at(ML, MAPPED, (5000.0, 0.0), 0.0)", "(0.5, 0.0, 0.5)"),
    ("drift", "drift(ML, MAPPED, 100.0)", "(519.6152422706881, 299.99999999999994)"),
    ("lattice point", "lattice_point(ML, MAPPED, point(1000.0, 3000.0, 2500.0), 100.0)", "(0.12009618943232797, 0.6749999999999999, 0.625)"),
    ("threshold", "threshold(LAYER, E, 0.5)", "0.6820434552191994"),
    ("covered fraction", "covered_fraction(LAYER, DOC, E, 0.0, 24)", "0.4930555555555556"),
    ("density", "density_at(FULL, DOC, E, point(5000.0, 5000.0, 2750.0), 0.0)", "0.42224652731675694"),
    ("shell segments", "shell_segments(LAYER, point(3000.0, 3000.0, 0.0), up(point(3000.0, 3000.0, 0.0)))", "[(1499.9999999990687, 3999.9999999990687)]"),
    ("optical depth", "optical_depth(FULL, DOC, E, point(3000.0, 3000.0, 0.0), up(point(3000.0, 3000.0, 0.0)), 0.0, 32)", "15.778026580402186"),
    ("phase normalisation", "phase_normalisation(20.0)", "1.0000000000002982"),
    ("phase", "phase(0.5, 20.0)", "0.01883642543832383"),
    ("Beer-powder", "beer_powder(0.5493)", "0.7698003588759074"),
    ("multiple scattering", "multi_scatter(1.0, 0.5, 20.0, 3)", "0.04821804243628386"),
    ("moon irradiance, full", "moon_irradiance(0.0, 384400.0)", "0.0013345419776139365"),
    ("moon irradiance, quarter", "moon_irradiance(90.0, 384400.0)", "0.0005028568309080366"),
    ("moon fraction", "moon_fraction(90.0, 384400.0)", "3.6947599625866023e-07"),
    ("earthshine", "earthshine(150.0)", "0.08164166578068305"),
    ("retrodirective", "retrodirective(10.0)", "1.5785809130778778"),
    ("scattering law", "scattering_law(10.0)", "1.0111355253059828"),
    ("moon BRDF", "moon_brdf(30.0, 45.0, 10.0)", "0.1864663629976326"),
    ("moon colour", "moon_colour()", "(1.20375, 1.04125, 0.87875)"),
    ("van Rhijn", "van_rhijn(75.0)", "3.332893420075101"),
    ("airglow radiance", "airglow_radiance(75.0)", "3.975425362641243e-11"),
    ("background radiance", "background_radiance()", "9.355176669619123e-12"),
    ("night radiance", "night_frame(DATE, LAT, LON, (0.0, -1.0, 0.0))[\"radiance\"]", "(6.02530675251142e-09, 1.2966163647266666e-08, 3.486398152122379e-08)"),
    ("validation", "validate_document(bad_document())", "['CN1', 'CN2', 'CN3', 'CN4', 'CN5', 'CN6']"),
)


def scope():
    """The names the table's expressions use."""
    s = dict(globals())
    s["E"] = example_seed()
    s["LAYER"] = example_layer()
    s["DOC"] = example_document()
    s["MAPPED"] = mapped_document()
    s["ML"] = s["MAPPED"]["lights"][0]["cloudLayers"][0]
    s["FULL"] = dict(example_layer(), coverage=1.0, detail=0.0)
    return s


def _same(a, b, rel=5e-4, abs_tol=1e-12):
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return repr(v)


def main():
    s = scope()
    print("| Test | Expression | Value |")
    print("|---|---|---|")
    for name, expr, _ in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
