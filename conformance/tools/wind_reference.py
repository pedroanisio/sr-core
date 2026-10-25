#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add the wind field" (srep/srep-0000-wind.md, F4 of SREP 12),
written from the SREP text, the random-streams draft (F1) and the cited sources, not from an engine. The wind
is a velocity field w(p, t) in metres per second over the physics space (metres, +y up): a gusting mean, the
declared gusts and a curl-noise turbulence whose potential is D24 value noise on the lattice of the random-streams
draft. tests/test_wind.py checks the functions and the SREP's numeric table against this module.

Usage: python3 wind_reference.py  (prints the numeric-test table of the SREP). Standard library only; it loads
conformance/tools/random_streams_reference.py by path.
"""
import importlib.util
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PURPOSE = "wind"                      # E(project, id, seed, "wind")
GUST_CHANNEL = 1                      # gust octave k reads channel 1 * 1024 + k
POTENTIAL_CHANNELS = (2, 3, 4)        # potential component a, octave k: (2 + a) * 1024 + k
OCTAVE_STRIDE = 1024
MAX_OCTAVES = 8
GUST_SHAPES = ("cosine", "iec")
AFFECTS = ("all", "bodies", "particles")
DEFAULTS = {
    "speed": 0.0, "direction": 0.0, "speedZ": 0.0,
    "gustiness": 0.0, "gustPeriod": 4.0, "gustOctaves": 3,
    "turbulence": 0.0, "turbulenceScale": 5.0, "turbulenceOctaves": 3, "turbulenceTime": 4.0,
    "response": 0.5, "seed": None, "start": 0.0, "end": None, "affects": "all", "gusts": (),
}
GUST_DEFAULTS = {"at": 0.0, "duration": 1.0, "peak": 0.0, "shape": "cosine", "direction": None}
DIVERGENCE_STEP = 1e-4
DIVERGENCE_TOLERANCE = 1e-6
DEFAULT_FPS = 24


class WindError(ValueError):
    """A wind that breaks WD1 to WD5 or a reading outside the SREP's definitions."""


_streams = None


def streams():
    """The random-streams reference module (E, U, V, pack), loaded by path."""
    global _streams
    if _streams is None:
        path = os.path.join(HERE, "random_streams_reference.py")
        spec = importlib.util.spec_from_file_location("random_streams_reference", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _streams = mod
    return _streams


# --- rule 1: the mean wind ------------------------------------------------------------------------------------

def value(spec, key, t):
    """An attribute at time t: a number, or an animated value given as a function of time."""
    v = spec.get(key, DEFAULTS[key])
    return v(t) if callable(v) else v


def unit_direction(degrees):
    """The unit vector of a heading in the physics xy plane: degrees from +x toward +y."""
    r = math.radians(degrees)
    return (math.cos(r), math.sin(r), 0.0)


def mean_velocity(spec, t):
    """speed along direction, plus speedZ along the scene's z (the forceZ axis), in m/s."""
    s = value(spec, "speed", t)
    d = unit_direction(value(spec, "direction", t))
    return (s * d[0], s * d[1], value(spec, "speedZ", t))


# --- rule 2: the element seed ---------------------------------------------------------------------------------

def element_seed(project, wind_id, seed):
    """e = E(project, id, @seed, "wind") of the random-streams draft."""
    return streams().E(project, wind_id, seed, PURPOSE)


# --- rule 3: the gust factor ----------------------------------------------------------------------------------

def _octaves(n):
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > MAX_OCTAVES:
        raise WindError(f"octaves are an integer from 1 to {MAX_OCTAVES}: {n!r}")
    return n


def gust_noise(e, x, octaves):
    """The octave sum of the random-streams draft's value noise V on the gust channels: octave k weighs 1/2^k
    and samples V(e, 1024 + k, x 2^k); the sum is divided by the sum of the weights. In [-1, 1]."""
    rs = streams()
    total = norm = 0.0
    w = f = 1.0
    for k in range(_octaves(octaves)):
        total += w * rs.V(e, GUST_CHANNEL * OCTAVE_STRIDE + k, x * f)
        norm += w
        w *= 0.5
        f *= 2.0
    return total / norm


def gust_factor(spec, e, t):
    """g(t) = 1 + gustiness * gust_noise(e, t / gustPeriod, gustOctaves), in [1 - gustiness, 1 + gustiness]."""
    g = value(spec, "gustiness", t)
    if g == 0.0:
        return 1.0
    return 1.0 + g * gust_noise(e, t / value(spec, "gustPeriod", t), spec.get("gustOctaves", DEFAULTS["gustOctaves"]))


def gust_range(spec, e, t0, t1, samples):
    """The least and greatest gust factor over samples times from t0 to t1."""
    vals = [gust_factor(spec, e, t0 + (t1 - t0) * i / (samples - 1)) for i in range(samples)]
    return (min(vals), max(vals))


# --- rule 4: the declared gusts -------------------------------------------------------------------------------

def _iec_raw(tau):
    """The IEC 61400-1 extreme operating gust shape -0.37 sin(3 pi tau) (1 - cos(2 pi tau)) on [0, 1]."""
    return -0.37 * math.sin(3.0 * math.pi * tau) * (1.0 - math.cos(2.0 * math.pi * tau))


def _iec_peak():
    """The maximum of the raw IEC shape on [0, 1]: a scan, then a golden-section refinement."""
    n = 4000
    best = max(range(n + 1), key=lambda i: _iec_raw(i / n))
    a, b = max(0.0, (best - 1) / n), min(1.0, (best + 1) / n)
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    c, d = b - phi * (b - a), a + phi * (b - a)
    for _ in range(200):
        if _iec_raw(c) < _iec_raw(d):
            a = c
        else:
            b = d
        c, d = b - phi * (b - a), a + phi * (b - a)
    return _iec_raw((a + b) / 2.0)


IEC_PEAK = _iec_peak()


def bump(shape, tau):
    """The gust shape at the normalised time tau = (t - at) / duration: 0 outside [0, 1]; cosine is
    (1 - cos(2 pi tau)) / 2; iec is the IEC 61400-1 extreme operating gust divided by its peak (IEC_PEAK),
    so that both shapes peak at 1."""
    if shape not in GUST_SHAPES:
        raise WindError(f"gust shape is one of {GUST_SHAPES}: {shape!r}")
    if tau < 0.0 or tau > 1.0:
        return 0.0
    if shape == "cosine":
        return (1.0 - math.cos(2.0 * math.pi * tau)) / 2.0
    return _iec_raw(tau) / IEC_PEAK


def declared_gusts(spec, t):
    """The sum over the gust children of peak * bump(shape, tau) along the gust's direction (the wind's
    direction at t when it has none), in m/s."""
    total = [0.0, 0.0, 0.0]
    for g in spec.get("gusts", DEFAULTS["gusts"]):
        at = g.get("at", GUST_DEFAULTS["at"])
        duration = g.get("duration", GUST_DEFAULTS["duration"])
        if duration <= 0.0:
            raise WindError("a gust's duration is positive")
        tau = (t - at) / duration
        b = bump(g.get("shape", GUST_DEFAULTS["shape"]), tau)
        if b == 0.0:
            continue
        heading = g.get("direction")
        if heading is None:
            heading = value(spec, "direction", t)
        d = unit_direction(heading)
        peak = g.get("peak", GUST_DEFAULTS["peak"])
        for i in range(3):
            total[i] += peak * b * d[i]
    return tuple(total)


# --- rule 5: the lattice, the potential and its gradient ------------------------------------------------------

def fade(f):
    """The quintic fade 6 f^5 - 15 f^4 + 10 f^3 (Perlin 2002)."""
    return f * f * f * (f * (f * 6.0 - 15.0) + 10.0)


def dfade(f):
    """Its derivative 30 f^2 (1 - f)^2."""
    return 30.0 * f * f * (1.0 - f) * (1.0 - f)


def lattice_value(e, c, i, j, k):
    """2 U(e, c, pack(i, j, k)) - 1 at the lattice point (i, j, k) on channel c."""
    rs = streams()
    return 2.0 * rs.U(e, c, rs.pack(i, j, k)) - 1.0


def value3(e, c, x, y, z):
    """3D value noise: the eight surrounding lattice values blended with the quintic fade on each axis, and its
    exact gradient with respect to (x, y, z). The value is in [-1, 1]; the gradient is 0 at lattice points."""
    i, j, k = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = x - i, y - j, z - k
    wx, wy, wz = fade(fx), fade(fy), fade(fz)
    dwx, dwy, dwz = dfade(fx), dfade(fy), dfade(fz)
    v = 0.0
    gx = gy = gz = 0.0
    for dx in (0, 1):
        ax, dax = (wx, dwx) if dx else (1.0 - wx, -dwx)
        for dy in (0, 1):
            ay, day = (wy, dwy) if dy else (1.0 - wy, -dwy)
            for dz in (0, 1):
                az, daz = (wz, dwz) if dz else (1.0 - wz, -dwz)
                c8 = lattice_value(e, c, i + dx, j + dy, k + dz)
                v += c8 * ax * ay * az
                gx += c8 * dax * ay * az
                gy += c8 * ax * day * az
                gz += c8 * ax * ay * daz
    return v, (gx, gy, gz)


def _potential_terms(e, q, octaves):
    """For each component a: (value, gradient) of the octave sum over the potential channels, derivatives
    with respect to q (octave k contributes 2^k times its own gradient)."""
    n = _octaves(octaves)
    out = []
    for a in range(3):
        total = 0.0
        grad = [0.0, 0.0, 0.0]
        norm = 0.0
        w = f = 1.0
        for k in range(n):
            v, g = value3(e, POTENTIAL_CHANNELS[a] * OCTAVE_STRIDE + k, q[0] * f, q[1] * f, q[2] * f)
            total += w * v
            for i in range(3):
                grad[i] += w * f * g[i]
            norm += w
            w *= 0.5
            f *= 2.0
        out.append((total / norm, tuple(x / norm for x in grad)))
    return out


def potential(e, q, octaves):
    """The vector potential Psi(q): three octave sums of value3 on channels (2 + a) 1024 + k, weights 1/2^k."""
    return tuple(v for v, _g in _potential_terms(e, q, octaves))


def potential_gradient(e, q, octaves):
    """The three gradients of Psi with respect to the lattice coordinate q."""
    return tuple(g for _v, g in _potential_terms(e, q, octaves))


def curl(grads):
    """The curl of a vector field from its three gradients: (d2/dy - d1/dz, d0/dz - d2/dx, d1/dx - d0/dy)."""
    g0, g1, g2 = grads
    return (g2[1] - g1[2], g0[2] - g2[0], g1[0] - g0[1])


# --- rule 6: time and the frozen turbulence -------------------------------------------------------------------

def displacement(spec, t, fps=DEFAULT_FPS):
    """D(t): the integral of the mean velocity from 0 to t by the trapezoid rule over the document's frames
    (frame times k / fps up to t, then the partial step to t). Exact for constant and linearly animated means."""
    if t <= 0.0:
        return (0.0, 0.0, 0.0)
    n = int(math.floor(t * fps + 1e-9))
    acc = [0.0, 0.0, 0.0]
    prev = mean_velocity(spec, 0.0)
    for k in range(1, n + 1):
        cur = mean_velocity(spec, k / fps)
        for i in range(3):
            acc[i] += 0.5 * (prev[i] + cur[i]) / fps
        prev = cur
    rest = t - n / fps
    if rest > 1e-12:
        cur = mean_velocity(spec, t)
        for i in range(3):
            acc[i] += 0.5 * (prev[i] + cur[i]) * rest
    return tuple(acc)


def _point3(p):
    p = tuple(float(x) for x in p)
    if len(p) == 2:
        return (p[0], p[1], 0.0)
    if len(p) != 3:
        raise WindError("a point has two or three coordinates")
    return p


def lattice_point(spec, p, t, fps=DEFAULT_FPS):
    """q = (p - D(t)) / turbulenceScale + (0, 0, t / turbulenceTime): the pattern rides the mean wind
    (Taylor's frozen turbulence) and slides one lattice cell per turbulenceTime along the third coordinate."""
    p = _point3(p)
    d = displacement(spec, t, fps)
    scale = value(spec, "turbulenceScale", t)
    period = value(spec, "turbulenceTime", t)
    return ((p[0] - d[0]) / scale, (p[1] - d[1]) / scale, (p[2] - d[2]) / scale + t / period)


# --- rule 7: the turbulence -----------------------------------------------------------------------------------

def turbulence_at(spec, e, p, t, fps=DEFAULT_FPS):
    """turbulence * curl_q Psi(q(p, t)): divergence-free by construction, in m/s."""
    amp = value(spec, "turbulence", t)
    if amp == 0.0:
        return (0.0, 0.0, 0.0)
    q = lattice_point(spec, p, t, fps)
    c = curl(potential_gradient(e, q, spec.get("turbulenceOctaves", DEFAULTS["turbulenceOctaves"])))
    return tuple(amp * x for x in c)


def turbulence2_at(spec, e, p, t, fps=DEFAULT_FPS):
    """The 2D form for readers in the plane: turbulence * (dPsi2/dq_y, -dPsi2/dq_x) at q(p, t) with p_z = 0."""
    amp = value(spec, "turbulence", t)
    if amp == 0.0:
        return (0.0, 0.0)
    q = lattice_point(spec, _point3(p)[:2], t, fps)
    g2 = potential_gradient(e, q, spec.get("turbulenceOctaves", DEFAULTS["turbulenceOctaves"]))[2]
    return (amp * g2[1], -amp * g2[0])


def divergence(spec, e, p, t, fps=DEFAULT_FPS, h=DIVERGENCE_STEP):
    """The divergence of turbulence_at by central differences with step h metres."""
    p = _point3(p)
    total = 0.0
    for i in range(3):
        hi = list(p)
        lo = list(p)
        hi[i] += h
        lo[i] -= h
        total += (turbulence_at(spec, e, hi, t, fps)[i] - turbulence_at(spec, e, lo, t, fps)[i]) / (2.0 * h)
    return total


def divergence2(spec, e, p, t, fps=DEFAULT_FPS, h=DIVERGENCE_STEP):
    """The planar divergence of turbulence2_at."""
    p = _point3(p)[:2]
    total = 0.0
    for i in range(2):
        hi = list(p)
        lo = list(p)
        hi[i] += h
        lo[i] -= h
        total += (turbulence2_at(spec, e, hi, t, fps)[i] - turbulence2_at(spec, e, lo, t, fps)[i]) / (2.0 * h)
    return total


def turbulence_rms(e, octaves, n):
    """The root mean square speed of the unit turbulence (amplitude 1) over n^3 points spread through four
    lattice cells per axis: the factor between the turbulence attribute and the speed it produces."""
    total = 0.0
    for i in range(n):
        for j in range(n):
            for k in range(n):
                q = (4.0 * (i + 0.5) / n, 4.0 * (j + 0.5) / n, 4.0 * (k + 0.5) / n)
                c = curl(potential_gradient(e, q, octaves))
                total += c[0] * c[0] + c[1] * c[1] + c[2] * c[2]
    return math.sqrt(total / n ** 3)


# --- rule 8: the wind -----------------------------------------------------------------------------------------

def _find_wind(doc, wind_id):
    for spec in doc.get("physics", {}).get("winds", ()):
        if spec.get("id") == wind_id:
            return spec
    raise WindError(f"no wind {wind_id!r}")


def wind_at(doc, wind_id, p, t, fps=DEFAULT_FPS):
    """w(p, t) = g(t) mean(t) + declared gusts(t) + turbulence(p, t) inside [start, end], else 0. A 2D point
    (two coordinates) reads the 2D turbulence form and gets a 2D vector."""
    spec = _find_wind(doc, wind_id)
    planar = len(tuple(p)) == 2
    start = value(spec, "start", t)
    end = spec.get("end", DEFAULTS["end"])
    if t < start or (end is not None and t > end):
        return (0.0, 0.0) if planar else (0.0, 0.0, 0.0)
    e = element_seed(doc.get("project", {}).get("seed", 0), wind_id, spec.get("seed", DEFAULTS["seed"]))
    g = gust_factor(spec, e, t)
    m = mean_velocity(spec, t)
    d = declared_gusts(spec, t)
    if planar:
        tb = turbulence2_at(spec, e, p, t, fps)
        return tuple(g * m[i] + d[i] + tb[i] for i in range(2))
    tb = turbulence_at(spec, e, p, t, fps)
    return tuple(g * m[i] + d[i] + tb[i] for i in range(3))


def to_pixels(w, pixels_per_meter):
    """The planar part of a velocity in the 2D scene's pixels per second: x scaled, y flipped (the physics
    world is +y up, the scene +y down)."""
    return (w[0] * pixels_per_meter, -w[1] * pixels_per_meter)


# --- rule 9: readers ------------------------------------------------------------------------------------------

def relaxation(w, v, response):
    """The acceleration of a particle or body moving at v in wind w: (w - v) / response."""
    if response <= 0.0:
        raise WindError("response is positive")
    return tuple((w[i] - v[i]) / response for i in range(len(w)))


def settle_fraction(t_over_response):
    """The share of the wind speed a body at rest has after t: 1 - exp(-t / response)."""
    return 1.0 - math.exp(-t_over_response)


def settled_speed(wind_speed, response, t, rate):
    """A body from rest in a steady wind, integrated by classical RK4 at rate steps per second."""
    n = int(round(t * rate))
    h = t / n if n else 0.0
    v = 0.0

    def f(v):
        return (wind_speed - v) / response
    for _ in range(n):
        k1 = f(v)
        k2 = f(v + 0.5 * h * k1)
        k3 = f(v + 0.5 * h * k2)
        k4 = f(v + h * k3)
        v += h * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
    return v


# --- the example and the validation ---------------------------------------------------------------------------

def example_wind():
    """The wind of the draft's example: 6 m/s toward 30 degrees, gusting by 30 % over 4 s cells, 1.5 m/s of
    turbulence on 5 m cells sliding every 4 s, a cosine gust and an IEC gust, seed 11."""
    return {
        "id": "w1", "speed": 6.0, "direction": 30.0, "gustiness": 0.3, "gustPeriod": 4.0, "gustOctaves": 3,
        "turbulence": 1.5, "turbulenceScale": 5.0, "turbulenceOctaves": 3, "turbulenceTime": 4.0,
        "response": 0.5, "seed": 11,
        "gusts": [{"at": 2.0, "duration": 3.0, "peak": 4.0, "shape": "cosine"},
                  {"at": 10.0, "duration": 6.0, "peak": 5.0, "shape": "iec"}],
    }


def example_document():
    return {
        "version": "1.8",
        "project": {"seed": 7},
        "physics": {"winds": [example_wind()], "forceFields": [{"id": "f1", "type": "wind"}]},
        "readers": [{"id": "em1", "forceFields": ["w1"]}],
    }


def example_seed():
    return element_seed(7, "w1", 11)


def bad_document():
    """One document that breaks every rule once."""
    doc = example_document()
    w = doc["physics"]["winds"][0]
    w["gustiness"] = 1.5                                   # WD1
    w["gusts"].append({"at": 1.0, "duration": 0.0})        # WD2
    doc["readers"][0]["forceFields"] = ["w1", "ghost"]     # WD3
    w["start"], w["end"] = 5.0, 4.0                        # WD4
    w["affects"] = "clouds"                                # WD5
    return doc


def _num(spec, key, t):
    v = value(spec, key, t)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def validate_wind(spec, ids):
    """The codes a wind breaks, checked at its start time: WD1 ranges, WD2 gusts, WD4 window, WD5 affects."""
    codes = set()
    t0 = spec.get("start", DEFAULTS["start"])
    t0 = t0 if isinstance(t0, (int, float)) else 0.0

    def check(key, ok):
        v = _num(spec, key, t0)
        if v is None or not ok(v):
            codes.add("WD1")
    check("speed", lambda v: v >= 0.0)
    check("gustiness", lambda v: 0.0 <= v <= 1.0)
    check("gustPeriod", lambda v: v > 0.0)
    check("turbulence", lambda v: v >= 0.0)
    check("turbulenceScale", lambda v: v > 0.0)
    check("turbulenceTime", lambda v: v > 0.0)
    check("response", lambda v: v > 0.0)
    for key in ("gustOctaves", "turbulenceOctaves"):
        v = spec.get(key, DEFAULTS[key])
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > MAX_OCTAVES:
            codes.add("WD1")
    for g in spec.get("gusts", DEFAULTS["gusts"]):
        if g.get("at", GUST_DEFAULTS["at"]) < 0.0 or g.get("duration", GUST_DEFAULTS["duration"]) <= 0.0 \
                or g.get("shape", GUST_DEFAULTS["shape"]) not in GUST_SHAPES:
            codes.add("WD2")
    end = spec.get("end", DEFAULTS["end"])
    if end is not None and end <= t0:
        codes.add("WD4")
    if spec.get("affects", DEFAULTS["affects"]) not in AFFECTS:
        codes.add("WD5")
    return codes


def validate_document(doc):
    """The sorted codes of WD1 to WD5 and V17 a document breaks; [] when valid. WD3: a reader's forceFields
    entry names a wind or a forceField of the document. V17: a wind in a document below 1.8."""
    codes = set()
    winds = doc.get("physics", {}).get("winds", ())
    ids = {w.get("id") for w in winds} | {f.get("id") for f in doc.get("physics", {}).get("forceFields", ())}
    if winds and tuple(int(x) for x in str(doc.get("version", "1.8")).split(".")[:2]) < (1, 8):
        codes.add("V17")
    for w in winds:
        codes |= validate_wind(w, ids)
    for reader in doc.get("readers", ()):
        for ref in reader.get("forceFields", ()):
            if ref not in ids:
                codes.add("WD3")
    return sorted(codes)


# --- the numeric table of the SREP ----------------------------------------------------------------------------

TABLE = (
    ("the element seed of the example", "example_seed()", "3265224338"),
    ("the mean velocity (m/s)", "mean_velocity(example_wind(), 0.0)", "(5.19615, 3, 0)"),
    ("the gust factor at 1.3 s", "gust_factor(example_wind(), example_seed(), 1.3)", "1.02528"),
    ("the gust factor at 8 s", "gust_factor(example_wind(), example_seed(), 8.0)", "0.956658"),
    ("the gust factor's range over a minute", "gust_range(example_wind(), example_seed(), 0.0, 60.0, 601)", "(0.814826, 1.20607)"),
    ("the same seed gives the same gust", "gust_factor(example_wind(), element_seed(7, 'w1', 11), 1.3) == gust_factor(example_wind(), example_seed(), 1.3)", "True"),
    ("another project seed gives another gust", "gust_factor(example_wind(), element_seed(8, 'w1', 11), 1.3)", "0.884407"),
    ("the cosine bump at its centre", "bump('cosine', 0.5)", "1"),
    ("the cosine bump at a quarter", "bump('cosine', 0.25)", "0.5"),
    ("the peak of the raw IEC gust shape", "IEC_PEAK", "0.74"),
    ("the IEC bump in its first dip", "bump('iec', 0.15)", "-0.20357"),
    ("the declared gust at 3.5 s (m/s)", "declared_gusts(example_wind(), 3.5)", "(3.4641, 2, 0)"),
    ("no declared gust at 6 s", "declared_gusts(example_wind(), 6.0)", "(0, 0, 0)"),
    ("the lattice value at (3, -2, 5)", "lattice_value(example_seed(), 2048, 3, -2, 5)", "0.907601"),
    ("the potential at a point", "potential(example_seed(), (0.37, 0.53, 0.11), 3)", "(-0.415486, -0.150265, 0.0692588)"),
    ("the gradient of the third potential component", "potential_gradient(example_seed(), (0.37, 0.53, 0.11), 3)[2]", "(-0.373448, 0.727646, 0.17609)"),
    ("the turbulence at (3, 2, 0.5) m at 1 s (m/s)", "turbulence_at(example_wind(), example_seed(), (3.0, 2.0, 0.5), 1.0)", "(1.09009, 0.550721, 2.87105)"),
    ("its divergence is below the tolerance", "abs(divergence(example_wind(), example_seed(), (3.0, 2.0, 0.5), 1.0)) < DIVERGENCE_TOLERANCE", "True"),
    ("the 2D form at (3, 2) m at 1 s (m/s)", "turbulence2_at(example_wind(), example_seed(), (3.0, 2.0), 1.0)", "(-0.552167, 1.02014)"),
    ("the 2D form is divergence-free too", "abs(divergence2(example_wind(), example_seed(), (3.0, 2.0), 1.0)) < DIVERGENCE_TOLERANCE", "True"),
    ("the RMS speed of the unit turbulence", "turbulence_rms(example_seed(), 3, 8)", "1.47887"),
    ("the displacement after 2.5 s (m)", "displacement(example_wind(), 2.5, 24)", "(12.9904, 7.5, 0)"),
    ("the displacement under a speed ramp", "displacement(dict(example_wind(), speed=lambda t: 4.0 * t, direction=0.0), 2.0, 24)", "(8, 0, 0)"),
    ("the lattice point of (3, 1, 0) m at 4 s with no mean wind", "lattice_point(dict(example_wind(), speed=0.0), (3.0, 1.0, 0.0), 4.0)", "(0.6, 0.2, 1)"),
    ("frozen turbulence rides the mean wind", "_same(turbulence_at(dict(example_wind(), turbulenceTime=1e12, speed=2.0, direction=0.0), example_seed(), (6.0, 1.0, 0.0), 1.5), turbulence_at(dict(example_wind(), turbulenceTime=1e12, speed=2.0, direction=0.0), example_seed(), (3.0, 1.0, 0.0), 0.0))", "True"),
    ("the wind at (3, 2, 0) m at 3.5 s (m/s)", "wind_at(example_document(), 'w1', (3.0, 2.0, 0.0), 3.5)", "(7.54575, 5.69762, 1.55088)"),
    ("the wind at a 2D point", "wind_at(example_document(), 'w1', (3.0, 2.0), 3.5)", "(7.21224, 5.1875)"),
    ("the wind in scene pixels per second", "to_pixels((1.0, 2.0), 100.0)", "(100, -200)"),
    ("the relaxation of a body at 1 m/s in a 6 m/s wind", "relaxation((6.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.5)", "(10, 0, 0)"),
    ("a body from rest after one response time", "settled_speed(6.0, 0.5, 0.5, 240)", "3.79272"),
    ("the example document is valid", "validate_document(example_document())", "[]"),
    ("the bad document breaks every rule", "validate_document(bad_document())", "['WD1', 'WD2', 'WD3', 'WD4', 'WD5']"),
    ("a 1.7 document with a wind", "validate_document(dict(example_document(), version='1.7'))", "['V17']"),
)


def scope():
    s = dict(globals())
    s["math"] = math
    return s


def _same(a, b, rel=5e-4, abs_tol=5e-4):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _fmt(v):
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and abs(v) < 1e-12:
        v = 0.0
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, (tuple, list)):
        inner = ", ".join(_fmt(x) for x in v)
        return "(" + inner + ")" if isinstance(v, tuple) else "[" + inner + "]"
    return repr(v)


def main():
    s = scope()
    for name, expr, _expected in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
