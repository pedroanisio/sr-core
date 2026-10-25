"""Reference for the draft SREP "Add spectral seas, caustics and flow maps to the ocean" (A4 of SREP 12).

A `sea` child of an `ocean` is a statistical wave field on top of SREP 40's shallow-water solver: a directional
spectrum (Phillips, Pierson-Moskowitz, JONSWAP or TMA with the cos^2s spreading of Longuet-Higgins) sampled on
a periodic grid, the initial amplitudes drawn once from the random-streams draft's normal draw G on channels 1
and 2 at pack(i, j, 0), and the field at any time written in closed form (Tessendorf 2001), so every frame
renders alone. The surface has a height, a choppy horizontal displacement, slopes, a normal, the Jacobian of the
displacement and the foam under its threshold. The ocean's optics add the exact Fresnel reflectance, Snell's
window, a homogeneous water medium (absorption after Pope and Fry 1997), caustics that conserve the transmitted
energy and flow maps (Vlachos 2010) that blend two phases of a sliding texture.

Lengths are metres, times seconds, angles in the ocean's plane in degrees from +x toward +z (the convention of
SREP 40's `wave@direction`), scene y pointing down. `python ocean_reference.py` prints the numeric table of the
draft's conformance section.
"""
from __future__ import annotations

import cmath
import functools
import importlib.util
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PURPOSE = "sea"
REAL_CHANNEL = 1
IMAG_CHANNEL = 2
MODELS = ("phillips", "piersonMoskowitz", "jonswap", "tma")
WATER_IOR = 1.333
WATER_G = 0.924
PM_ALPHA = 0.0081
PM_BETA = 0.74
PM_PEAK = 0.877
PM_U195 = 1.026
JONSWAP_PEAK = 22.0
JONSWAP_ALPHA = 0.076
JONSWAP_SIGMA = (0.07, 0.09)
FOAM_RAMP = 0.3
RESOLUTIONS = (16, 32, 64, 128, 256, 512, 1024, 2048)
OMEGA_STEPS = 4000
OMEGA_RANGE = (0.2, 8.0)
ANGLE_STEPS = 2048
MAX_FOAM_THRESHOLD = 2.0

DEFAULTS = {"model": "jonswap", "windSpeed": 10.0, "windDirection": 0.0, "fetch": 100000.0, "gamma": 3.3,
            "spread": 10.0, "cutoff": 0.0, "size": 1024.0, "resolution": 256, "choppiness": 1.0,
            "foamThreshold": 0.8, "foamDecay": 0.5, "seed": None,
            "absorption": (0.34, 0.0565, 0.0092), "scattering": (0.003, 0.003, 0.003), "ior": WATER_IOR,
            "caustics": False, "flowMap": None, "flowSpeed": 0.0, "flowCycle": 2.0}
SEA_KEYS = ("model", "windSpeed", "windDirection", "fetch", "gamma", "spread", "cutoff", "size", "resolution",
            "choppiness", "foamThreshold", "foamDecay", "seed")
OCEAN_KEYS = ("absorption", "scattering", "ior", "caustics", "flowMap", "flowSpeed", "flowCycle")


class OceanError(ValueError):
    """A sea, an ocean attribute or a quantity outside the draft's rules."""


# ------------------------------------------------------------------------------------------------- the references

_streams = None


def streams():
    """The random-streams reference module (E, G, pack), loaded by path."""
    global _streams
    if _streams is None:
        path = os.path.join(HERE, "random_streams_reference.py")
        spec = importlib.util.spec_from_file_location("random_streams_reference", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _streams = mod
    return _streams


def _get(element, key):
    return element[key] if key in element and element[key] is not None else DEFAULTS[key]


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# -------------------------------------------------------------------------------------------------- dispersion


def omega(k, g, depth):
    """The angular frequency of the wavenumber k: sqrt(g k tanh(k depth)), deep water when depth is None."""
    if not k > 0.0:
        raise OceanError(f"the wavenumber is positive: {k!r}")
    if depth is None:
        return math.sqrt(g * k)
    return math.sqrt(g * k * math.tanh(k * depth))


def domega_dk(k, g, depth):
    """The group velocity d omega / d k."""
    w = omega(k, g, depth)
    if depth is None:
        return g / (2.0 * w)
    kd = k * depth
    return g * (math.tanh(kd) + kd / math.cosh(kd) ** 2) / (2.0 * w)


# -------------------------------------------------------------------------------------------------- spectra


def pierson_moskowitz_peak(wind_speed, g):
    """The peak frequency of the fully developed sea: 0.877 g / U_19.5 with U_19.5 = 1.026 U_10 (Horvath 2015)."""
    return PM_PEAK * g / (PM_U195 * wind_speed)


def pierson_moskowitz(w, wind_speed, g):
    """S(omega) = alpha g^2 omega^-5 exp(-beta (omega_0 / omega)^4), omega_0 = g / U_19.5 (Pierson and Moskowitz 1964)."""
    if not w > 0.0:
        return 0.0
    w0 = g / (PM_U195 * wind_speed)
    return PM_ALPHA * g * g / w ** 5 * math.exp(-PM_BETA * (w0 / w) ** 4)


def pierson_moskowitz_m0(wind_speed, g):
    """The integral of the Pierson-Moskowitz spectrum over all frequencies: alpha U_19.5^4 / (4 beta g^2)."""
    u = PM_U195 * wind_speed
    return PM_ALPHA * u ** 4 / (4.0 * PM_BETA * g * g)


def jonswap_peak(wind_speed, fetch, g):
    """The peak frequency 22 (g^2 / (U_10 F))^(1/3) of the fetch-limited sea (Hasselmann et al. 1973)."""
    return JONSWAP_PEAK * (g * g / (wind_speed * fetch)) ** (1.0 / 3.0)


def jonswap_alpha(wind_speed, fetch, g):
    """The JONSWAP energy scale 0.076 (U_10^2 / (F g))^0.22."""
    return JONSWAP_ALPHA * (wind_speed * wind_speed / (fetch * g)) ** 0.22


def jonswap(w, wind_speed, fetch, g, gamma):
    """S(omega) = alpha g^2 omega^-5 exp(-5/4 (omega_p / omega)^4) gamma^r, r = exp(-(omega - omega_p)^2 /
    (2 sigma^2 omega_p^2)), sigma 0.07 below the peak and 0.09 above it."""
    if not w > 0.0:
        return 0.0
    wp = jonswap_peak(wind_speed, fetch, g)
    sigma = JONSWAP_SIGMA[0] if w <= wp else JONSWAP_SIGMA[1]
    r = math.exp(-((w - wp) ** 2) / (2.0 * sigma * sigma * wp * wp))
    return jonswap_alpha(wind_speed, fetch, g) * g * g / w ** 5 * math.exp(-1.25 * (wp / w) ** 4) * gamma ** r


def kitaigorodskii(wh):
    """The depth factor Phi of Kitaigorodskii et al. 1975 in omega_h = omega sqrt(depth / g): omega_h^2 / 2 below
    1, 1 - (2 - omega_h)^2 / 2 between 1 and 2, 1 above."""
    if wh <= 1.0:
        return 0.5 * wh * wh
    if wh < 2.0:
        return 1.0 - 0.5 * (2.0 - wh) ** 2
    return 1.0


def tma(w, wind_speed, fetch, depth, g, gamma):
    """The TMA spectrum: JONSWAP times the Kitaigorodskii depth factor (Bouws et al. 1985); deep when depth is None."""
    s = jonswap(w, wind_speed, fetch, g, gamma)
    if depth is None:
        return s
    return s * kitaigorodskii(w * math.sqrt(depth / g))


def _wrap(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def spreading_norm(s):
    """1 / integral of cos^2s(theta / 2) over the circle: Gamma(s + 1) / (2 sqrt(pi) Gamma(s + 1/2))."""
    return math.gamma(s + 1.0) / (2.0 * math.sqrt(math.pi) * math.gamma(s + 0.5))


def spreading(theta, wind_direction, s):
    """The directional spreading D(theta) = C(s) cos^2s((theta - theta_w) / 2) of Longuet-Higgins et al. 1963,
    normalised to one over the circle and zero against the wind; angles in radians."""
    d = _wrap(theta - wind_direction)
    c = math.cos(0.5 * d)
    if c <= 0.0:
        return 0.0
    return spreading_norm(s) * c ** (2.0 * s)


def integrate_angle(f):
    """Simpson's rule of f over the circle [-pi, pi]."""
    n = ANGLE_STEPS
    h = 2.0 * math.pi / n
    total = f(-math.pi) + f(math.pi)
    for i in range(1, n):
        total += (4.0 if i % 2 else 2.0) * f(-math.pi + i * h)
    return total * h / 3.0


def phillips(k_vec, wind_speed, wind_direction, g):
    """The Phillips spectrum of Tessendorf 2001 with unit scale: exp(-1 / (k L)^2) / k^4 (k_hat . w_hat)^2,
    L = U^2 / g; angles in radians."""
    k = math.hypot(*k_vec)
    if k == 0.0:
        return 0.0
    L = wind_speed * wind_speed / g
    dot = (k_vec[0] * math.cos(wind_direction) + k_vec[1] * math.sin(wind_direction)) / k
    if dot == 0.0:
        return 0.0
    return math.exp(-1.0 / (k * L) ** 2) / k ** 4 * dot * dot


def phillips_scale(wind_speed, g):
    """The scale A of the Phillips spectrum that gives it the Pierson-Moskowitz variance of the same wind:
    2 m0_PM / (pi L^2), since the integral of the unit Phillips spectrum over the plane is pi L^2 / 2."""
    L = wind_speed * wind_speed / g
    return 2.0 * pierson_moskowitz_m0(wind_speed, g) / (math.pi * L * L)


def frequency_spectrum(sea, w, g, depth):
    """S(omega) of the sea's frequency model."""
    model = _get(sea, "model")
    u = _get(sea, "windSpeed")
    if model == "piersonMoskowitz":
        return pierson_moskowitz(w, u, g)
    if model == "jonswap":
        return jonswap(w, u, _get(sea, "fetch"), g, _get(sea, "gamma"))
    if model == "tma":
        return tma(w, u, _get(sea, "fetch"), depth, g, _get(sea, "gamma"))
    raise OceanError(f"unknown spectrum model {model!r}")


def cutoff_wavenumber(sea):
    """The largest wavenumber the sea carries, 2 pi / cutoff, or None without a cutoff."""
    c = _get(sea, "cutoff")
    return 2.0 * math.pi / c if c > 0.0 else None


def spectrum_k(sea, k_vec, g, depth):
    """The wavenumber spectrum P(k): S(omega(k)) D(theta) (d omega / d k) / k for the frequency models, A times
    the Phillips spectrum otherwise; zero at k = 0 and beyond the cutoff."""
    k = math.hypot(*k_vec)
    if k == 0.0:
        return 0.0
    kc = cutoff_wavenumber(sea)
    if kc is not None and k > kc:
        return 0.0
    model = _get(sea, "model")
    if model not in MODELS:
        raise OceanError(f"unknown spectrum model {model!r}")
    u = _get(sea, "windSpeed")
    wd = math.radians(_get(sea, "windDirection"))
    if model == "phillips":
        return phillips_scale(u, g) * phillips(k_vec, u, wd, g)
    w = omega(k, g, depth)
    return (frequency_spectrum(sea, w, g, depth) * spreading(math.atan2(k_vec[1], k_vec[0]), wd, _get(sea, "spread"))
            * domega_dk(k, g, depth) / k)


def m0(sea, g, depth):
    """The variance of the sea's height: the spectrum's integral, over the frequencies OMEGA_RANGE (Simpson in
    OMEGA_STEPS steps, the spreading integrating to one) up to the cutoff, or the closed form for Phillips."""
    model = _get(sea, "model")
    if model not in MODELS:
        raise OceanError(f"unknown spectrum model {model!r}")
    kc = cutoff_wavenumber(sea)
    u = _get(sea, "windSpeed")
    if model == "phillips":
        L = u * u / g
        tail = 1.0 if kc is None else math.exp(-1.0 / (kc * L) ** 2)
        return phillips_scale(u, g) * math.pi * L * L / 2.0 * tail
    lo, hi = OMEGA_RANGE
    if kc is not None:
        hi = min(hi, omega(kc, g, depth))
    if hi <= lo:
        return 0.0
    n = OMEGA_STEPS
    h = (hi - lo) / n
    total = frequency_spectrum(sea, lo, g, depth) + frequency_spectrum(sea, hi, g, depth)
    for i in range(1, n):
        total += (4.0 if i % 2 else 2.0) * frequency_spectrum(sea, lo + i * h, g, depth)
    return total * h / 3.0


def significant_height(variance):
    """The significant wave height H_s = 4 sqrt(m0)."""
    return 4.0 * math.sqrt(variance)


# ------------------------------------------------------------------------------------------------- the grid


def dk(sea):
    """The grid's wavenumber step 2 pi / size."""
    return 2.0 * math.pi / _get(sea, "size")


def _signed(i, n):
    return i - n if i >= n // 2 else i


def wavevector(sea, i, j):
    """The wavevector of grid cell (i, j): 2 pi (i', j') / size with i' = i for i < n / 2 and i - n otherwise."""
    n = _get(sea, "resolution")
    return (dk(sea) * _signed(i % n, n), dk(sea) * _signed(j % n, n))


def variance_sum(sea, g, depth):
    """The sum of P(k) dk^2 over the grid: the variance the resolved band carries."""
    n = _get(sea, "resolution")
    d = dk(sea) ** 2
    total = 0.0
    for i in range(n):
        for j in range(n):
            if i == n // 2 or j == n // 2:
                continue
            total += spectrum_k(sea, wavevector(sea, i, j), g, depth) * d
    return total


def element_seed(project, element_id, seed):
    """E(project, id, seed, "sea") of the random-streams draft."""
    return streams().E(project, element_id, seed, PURPOSE)


def amplitude0(sea, e, i, j, g, depth):
    """h0(k) = (G(e, 1, pack(i, j, 0)) + i G(e, 2, pack(i, j, 0))) sqrt(P(k) dk^2) / 2; zero at k = 0 and on the
    Nyquist row and column."""
    n = _get(sea, "resolution")
    i %= n
    j %= n
    if (i == 0 and j == 0) or i == n // 2 or j == n // 2:
        return 0j
    rs = streams()
    p = spectrum_k(sea, wavevector(sea, i, j), g, depth) * dk(sea) ** 2
    if p == 0.0:
        return 0j
    xi = complex(rs.G(e, REAL_CHANNEL, rs.pack(i, j, 0)), rs.G(e, IMAG_CHANNEL, rs.pack(i, j, 0)))
    return xi * math.sqrt(p) / 2.0


def amplitude(sea, e, i, j, t, g, depth):
    """h(k, t) = h0(k) e^(i omega t) + conj(h0(-k)) e^(-i omega t)."""
    n = _get(sea, "resolution")
    k = wavevector(sea, i, j)
    kk = math.hypot(*k)
    if kk == 0.0 or i % n == n // 2 or j % n == n // 2:
        return 0j
    w = omega(kk, g, depth)
    return (amplitude0(sea, e, i, j, g, depth) * cmath.exp(1j * w * t)
            + amplitude0(sea, e, (-i) % n, (-j) % n, g, depth).conjugate() * cmath.exp(-1j * w * t))


def _sea_key(sea):
    return tuple(_get(sea, k) for k in SEA_KEYS)


@functools.lru_cache(maxsize=64)
def _modes_cached(key, e, t, g, depth):
    sea = dict(zip(SEA_KEYS, key))
    n = sea["resolution"]
    out = []
    for i in range(n):
        for j in range(n):
            h = amplitude(sea, e, i, j, t, g, depth)
            if h != 0j:
                k = wavevector(sea, i, j)
                out.append((k[0], k[1], math.hypot(*k), h))
    return tuple(out)


def modes(sea, e, t, g, depth):
    """Every grid mode with a non-zero amplitude at time t, as (kx, kz, |k|, h(k, t))."""
    return _modes_cached(_sea_key(sea), e, t, g, depth)


def variance_parseval(sea, e, t, g, depth):
    """The spatial variance of the generated height: the sum of |h(k, t)|^2 over the grid (Parseval)."""
    return sum(abs(h) ** 2 for _, _, _, h in modes(sea, e, t, g, depth))


def _sum(sea, e, x, z, t, g, depth, weight):
    total = 0j
    for kx, kz, kk, h in modes(sea, e, t, g, depth):
        total += weight(kx, kz, kk) * h * cmath.exp(1j * (kx * x + kz * z))
    return total.real


def height(sea, e, x, z, t, g, depth):
    """The height h(x, z, t) = Re sum_k h(k, t) e^(i k . x), positive up, periodic in size."""
    return float(_sum(sea, e, x, z, t, g, depth, lambda kx, kz, kk: 1.0))


def displacement(sea, e, x, z, t, g, depth):
    """(D_x, h, D_z): the choppy displacement D = -i choppiness sum_k (k / |k|) h(k, t) e^(i k . x) and the height."""
    c = _get(sea, "choppiness")
    if c == 0.0:
        return (0.0, height(sea, e, x, z, t, g, depth), 0.0)
    dx = _sum(sea, e, x, z, t, g, depth, lambda kx, kz, kk: -1j * c * kx / kk)
    dz = _sum(sea, e, x, z, t, g, depth, lambda kx, kz, kk: -1j * c * kz / kk)
    return (dx, height(sea, e, x, z, t, g, depth), dz)


def jacobian(sea, e, x, z, t, g, depth):
    """J = (1 + dD_x/dx) (1 + dD_z/dz) - (dD_x/dz)^2 of the horizontal displacement, from the analytic derivatives."""
    c = _get(sea, "choppiness")
    if c == 0.0:
        return 1.0
    jxx = _sum(sea, e, x, z, t, g, depth, lambda kx, kz, kk: c * kx * kx / kk)
    jzz = _sum(sea, e, x, z, t, g, depth, lambda kx, kz, kk: c * kz * kz / kk)
    jxz = _sum(sea, e, x, z, t, g, depth, lambda kx, kz, kk: c * kx * kz / kk)
    return (1.0 + jxx) * (1.0 + jzz) - jxz * jxz


def foam(j, threshold):
    """The foam coverage from the Jacobian: 1 at threshold - FOAM_RAMP and below, 0 at the threshold and above,
    linear between."""
    return min(1.0, max(0.0, (threshold - j) / FOAM_RAMP))


def slopes(sea, e, x, z, t, g, depth):
    """(dh/dx, dh/dz) of the height, analytic."""
    sx = _sum(sea, e, x, z, t, g, depth, lambda kx, kz, kk: 1j * kx)
    sz = _sum(sea, e, x, z, t, g, depth, lambda kx, kz, kk: 1j * kz)
    return (sx, sz)


def normal(sx, sz):
    """The unit normal (sx, -1, sz) / |.| of the surface with scene y pointing down."""
    m = math.sqrt(1.0 + sx * sx + sz * sz)
    return (sx / m, -1.0 / m, sz / m)


# ----------------------------------------------------------------------------------------------------- optics


def fresnel(cos_i, n):
    """The unpolarised Fresnel reflectance for the index ratio n = n_t / n_i: one beyond the critical angle."""
    cos_i = min(1.0, max(0.0, cos_i))
    sin_t2 = (1.0 - cos_i * cos_i) / (n * n)
    if sin_t2 >= 1.0:
        return 1.0
    cos_t = math.sqrt(1.0 - sin_t2)
    rs = ((cos_i - n * cos_t) / (cos_i + n * cos_t)) ** 2
    rp = ((n * cos_i - cos_t) / (n * cos_i + cos_t)) ** 2
    return 0.5 * (rs + rp)


def snell_window(n):
    """The half-angle of Snell's window in degrees: asin(1 / n)."""
    return math.degrees(math.asin(1.0 / n))


def refract(direction, surface_normal, eta):
    """The refracted unit direction for eta = n_i / n_t: the tangential part scales by eta, the normal part keeps
    its sign; None under total internal reflection."""
    d = direction
    nn = surface_normal
    c = d[0] * nn[0] + d[1] * nn[1] + d[2] * nn[2]
    t = tuple(eta * (d[a] - c * nn[a]) for a in range(3))
    tt = t[0] * t[0] + t[1] * t[1] + t[2] * t[2]
    if tt > 1.0:
        return None
    m = math.copysign(math.sqrt(1.0 - tt), c)
    return tuple(t[a] + m * nn[a] for a in range(3))


def _rays(amplitude, wavelength, rays):
    """The ray stations over one wavelength: x, the surface height and the slope of a sin(2 pi x / lambda)."""
    if not isinstance(rays, int) or rays <= 0:
        raise OceanError(f"rays is a positive integer: {rays!r}")
    for i in range(rays):
        x = (i + 0.5) / rays * wavelength
        phase = 2.0 * math.pi * x / wavelength
        yield x, amplitude * math.sin(phase), amplitude * 2.0 * math.pi / wavelength * math.cos(phase)


def transmitted_fraction(amplitude, wavelength, rays):
    """The mean of 1 - F over the vertical rays through a sinusoidal surface."""
    total = 0.0
    for _, _, s in _rays(amplitude, wavelength, rays):
        total += 1.0 - fresnel(1.0 / math.sqrt(1.0 + s * s), WATER_IOR)
    return total / rays


def caustics(amplitude, wavelength, depth, rays, bins):
    """The floor irradiance under one period of a sinusoidal surface, in units of the incident irradiance: vertical
    rays refracted into the water and binned where they reach the floor at `depth` below the mean level."""
    if not isinstance(bins, int) or bins <= 0:
        raise OceanError(f"bins is a positive integer: {bins!r}")
    out = [0.0] * bins
    for x, h, s in _rays(amplitude, wavelength, rays):
        m = math.sqrt(1.0 + s * s)
        n = (-s / m, 1.0 / m, 0.0)                        # up, in the (x, up) plane of this section
        d = refract((0.0, -1.0, 0.0), n, 1.0 / WATER_IOR)
        f = fresnel(1.0 / m, WATER_IOR)
        hit = x + (depth + h) * d[0] / -d[1]
        b = int(math.floor(hit / wavelength * bins)) % bins
        out[b] += (1.0 - f) * bins / rays
    return out


def water_absorption():
    """The absorption of pure water at 650, 550 and 450 nm in 1/m (Pope and Fry 1997)."""
    return DEFAULTS["absorption"]


def extinction(ocean):
    """Absorption plus scattering of the ocean's water, per channel."""
    a = _get(ocean, "absorption")
    s = _get(ocean, "scattering")
    return tuple(a[c] + s[c] for c in range(3))


def depth_transmittance(coefficients, length):
    """exp(-c L) per channel."""
    return tuple(math.exp(-c * length) for c in coefficients)


def underwater_colour(ocean, length, colour):
    """A colour seen through `length` metres of the ocean's water: the direct transmission by its extinction."""
    t = depth_transmittance(extinction(ocean), length)
    return tuple(colour[c] * t[c] for c in range(3))


# -------------------------------------------------------------------------------------------------- flow maps


def flow_phases(t, cycle):
    """The two phases p0 = t / cycle mod 1 and p1 = p0 + 1/2 mod 1 and the weight w0 = 1 - |2 p0 - 1| of the first."""
    if not cycle > 0.0:
        raise OceanError(f"flowCycle is positive: {cycle!r}")
    p0 = (t / cycle) % 1.0
    p1 = (t / cycle + 0.5) % 1.0
    return (p0, p1, 1.0 - abs(2.0 * p0 - 1.0))


def flow_sample(texture, uv, velocity, t, speed, cycle):
    """The flow-mapped texture (Vlachos 2010): each phase slides uv by velocity speed cycle p, blended by w0."""
    p0, p1, w0 = flow_phases(t, cycle)

    def at(p):
        return texture((uv[0] - velocity[0] * speed * cycle * p, uv[1] - velocity[1] * speed * cycle * p))
    return w0 * at(p0) + (1.0 - w0) * at(p1)


# -------------------------------------------------------------------------------------------------- the ocean


def taper(h, depth):
    """SREP 40's depth taper: the rise clamped to half the local depth."""
    half = 0.5 * depth
    return min(half, max(-half, h))


def surface_height(doc, e, x, z, t):
    """The ocean surface in scene y: waterLevel minus the tapered sea height (y points down)."""
    ocean = doc["oceans"][0]
    depth = ocean.get("bottomDepth", 10.0)
    g = ocean.get("gravity", 9.81)
    return ocean["waterLevel"] - taper(height(ocean["sea"], e, x, z, t, g, depth), depth)


def example_sea():
    return {"id": "sea1", "model": "jonswap", "windSpeed": 10.0, "windDirection": 30.0, "fetch": 100000.0,
            "gamma": 3.3, "spread": 10.0, "cutoff": 0.0, "size": 1024.0, "resolution": 256, "choppiness": 1.0,
            "foamThreshold": 0.8, "foamDecay": 0.5, "seed": 3}


def example_document():
    return {"version": "1.8", "project": {"seed": 7},
            "assets": [{"id": "fm", "type": "image", "width": 2, "height": 2}],
            "oceans": [{"id": "o1", "width": 2048.0, "depth": 2048.0, "cellSize": 8.0, "waterLevel": 20.0,
                        "bottomDepth": 10.0, "gravity": 9.81, "absorption": (0.34, 0.0565, 0.0092),
                        "scattering": (0.003, 0.003, 0.003), "ior": 1.333, "caustics": True, "flowMap": "fm",
                        "flowSpeed": 0.1, "flowCycle": 2.0, "sea": example_sea()}]}


def example_seed():
    return element_seed(7, "sea1", 3)


def bad_document():
    doc = example_document()
    doc["oceans"][0]["sea"].update(model="airy", windSpeed=0.0, resolution=12, foamThreshold=3.0)
    doc["oceans"][0].update(ior=0.5, flowCycle=0.0)
    return doc


def _positive(v):
    return _number(v) and v > 0.0


def _non_negative(v):
    return _number(v) and v >= 0.0


def _triple(v):
    return isinstance(v, (tuple, list)) and len(v) == 3 and all(_non_negative(c) for c in v)


def validate_sea(sea):
    """The draft's rules OC1 to OC4 over one sea."""
    codes = set()
    if _get(sea, "model") not in MODELS:
        codes.add("OC1")
    if not (_positive(_get(sea, "windSpeed")) and _positive(_get(sea, "fetch")) and _number(_get(sea, "gamma"))
            and _get(sea, "gamma") >= 1.0 and _positive(_get(sea, "spread")) and _non_negative(_get(sea, "cutoff"))
            and _number(_get(sea, "windDirection"))):
        codes.add("OC2")
    seed = sea.get("seed")
    if not (_positive(_get(sea, "size")) and _get(sea, "resolution") in RESOLUTIONS
            and _non_negative(_get(sea, "choppiness"))
            and (seed is None or (isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed < 2 ** 64))):
        codes.add("OC3")
    ft = _get(sea, "foamThreshold")
    if not (_number(ft) and 0.0 <= ft <= MAX_FOAM_THRESHOLD and _non_negative(_get(sea, "foamDecay"))):
        codes.add("OC4")
    return codes


def validate_ocean(ocean, doc):
    """The draft's rules OC5 and OC6 over one ocean's new attributes."""
    codes = set()
    ior = _get(ocean, "ior")
    if not (_triple(_get(ocean, "absorption")) and _triple(_get(ocean, "scattering")) and _number(ior) and ior >= 1.0):
        codes.add("OC5")
    fm = ocean.get("flowMap")
    images = {a.get("id") for a in doc.get("assets", ()) if a.get("type") == "image"}
    if not ((fm is None or fm in images) and _non_negative(_get(ocean, "flowSpeed")) and _positive(_get(ocean, "flowCycle"))):
        codes.add("OC6")
    return codes


def validate_document(doc):
    """The draft's rules OC1 to OC6 and V17 over a document, as sorted codes."""
    codes = set()
    major, minor = (int(x) for x in str(doc.get("version", "1.0")).split(".")[:2])
    new = (major, minor) >= (1, 8)
    for ocean in doc.get("oceans", ()):
        sea = ocean.get("sea")
        if (sea is not None or any(k in ocean for k in OCEAN_KEYS)) and not new:
            codes.add("V17")
            continue
        if sea is not None:
            codes |= validate_sea(sea)
        codes |= validate_ocean(ocean, doc)
    return sorted(codes)


# ----------------------------------------------------------------------------------------------- numeric table

TABLE = (
    ("element seed", 'element_seed(7, "sea1", 3)', "1610619058"),
    ("deep dispersion", "omega(0.1, 9.81, None)", "0.9904544411531507"),
    ("finite-depth dispersion", "omega(0.1, 9.81, 5.0)", "0.6733030010864868"),
    ("group velocity", "domega_dk(0.1, 9.81, 5.0)", "6.231143652544589"),
    ("Pierson-Moskowitz peak", "pierson_moskowitz_peak(10.0, 9.81)", "0.8385350877192983"),
    ("Pierson-Moskowitz at its peak", "pierson_moskowitz(pierson_moskowitz_peak(10.0, 9.81), 10.0, 9.81)", "0.5382008933999488"),
    ("Pierson-Moskowitz variance", "pierson_moskowitz_m0(10.0, 9.81)", "0.31509733943134277"),
    ("JONSWAP peak", "jonswap_peak(10.0, 100000.0, 9.81)", "1.0081736733065412"),
    ("JONSWAP at its peak", "jonswap(jonswap_peak(10.0, 100000.0, 9.81), 10.0, 100000.0, 9.81, 3.3)", "0.8789284065108056"),
    ("Kitaigorodskii factor", "kitaigorodskii(1.5)", "0.875"),
    ("TMA", "tma(1.0, 10.0, 100000.0, 5.0, 9.81, 3.3)", "0.2220585232770745"),
    ("spreading along the wind", "spreading(0.5, 0.5, 10.0)", "0.9032781268674754"),
    ("spreading integral", "integrate_angle(lambda th: spreading(th, 0.5, 4.0))", "1.0000000000000013"),
    ("Phillips", "phillips((0.1, 0.0), 10.0, 0.0, 9.81)", "3819.899422158739"),
    ("Phillips scale", "phillips_scale(10.0, 9.81)", "0.0019304691862325773"),
    ("wavenumber spectrum", "spectrum_k(SEA, (0.15, 0.05), 9.81, None)", "3.9913850190687006"),
    ("variance, JONSWAP", "m0(SEA, 9.81, 20.0)", "0.28578433445848483"),
    ("variance, TMA", "m0(dict(SEA, model='tma'), 9.81, 20.0)", "0.25137023498089933"),
    ("significant wave height", "significant_height(m0(SEA, 9.81, 20.0))", "2.1383520176378252"),
    ("wavevector", "wavevector(SEA, 3, 250)", "(0.018407769454627694, -0.03681553890925539)"),
    ("wavenumber step", "dk(SEA)", "0.006135923151542565"),
    ("initial amplitude", "amplitude0(SEA, E, 3, 5, 9.81, 20.0)", "(8.511055819601815e-08-1.5419043209523627e-07j)"),
    ("amplitude at t = 2.5", "amplitude(SEA, E, 3, 5, 2.5, 9.81, 20.0)", "(1.7533876330052506e-07+1.6579562149170433e-08j)"),
    ("height", "height(SMALL, E, 10.0, 20.0, 1.0, 9.81, 20.0)", "0.3953231398611454"),
    ("displacement", "displacement(SMALL, E, 33.0, 71.0, 2.0, 9.81, 20.0)", "(-0.6155832127499618, 0.7360888173734451, -0.32709881458703643)"),
    ("Jacobian", "jacobian(SMALL, E, 33.0, 71.0, 2.0, 9.81, 20.0)", "1.0846704117260353"),
    ("foam", "foam(0.65, 0.8)", "0.5000000000000001"),
    ("slopes", "slopes(SMALL, E, 12.0, 5.0, 0.5, 9.81, 20.0)", "(-0.028491169810334057, 0.01890440707832599)"),
    ("normal", "normal(0.3, -0.4)", "(0.2683281572999747, -0.8944271909999159, -0.35777087639996635)"),
    ("Fresnel at normal incidence", "fresnel(1.0, WATER_IOR)", "0.020373187841971414"),
    ("Fresnel at 60 degrees", "fresnel(0.5, WATER_IOR)", "0.05969091917515265"),
    ("Fresnel from below at 30 degrees", "fresnel(math.cos(math.radians(30.0)), 1.0 / WATER_IOR)", "0.025519162292123147"),
    ("Snell's window", "snell_window(WATER_IOR)", "48.60662639169028"),
    ("refraction", "refract((0.6, 0.8, 0.0), (0.0, 1.0, 0.0), 1.0 / WATER_IOR)", "(0.450112528132033, 0.8929718427915797, 0.0)"),
    ("transmitted fraction", "transmitted_fraction(0.2, 4.0, 4000)", "0.9795880690806308"),
    ("caustic peak", "max(caustics(0.2, 4.0, 4.0, 4000, 40))", "1.9886420019310953"),
    ("depth transmittance", "depth_transmittance(water_absorption(), 10.0)", "(0.033373269960326066, 0.5683601467575404, 0.9121051495450904)"),
    ("underwater colour", "underwater_colour(OCEAN, 10.0, (1.0, 1.0, 1.0))", "(0.03238694077290704, 0.5515625658678297, 0.8851483685026271)"),
    ("flow phases", "flow_phases(0.75, 2.0)", "(0.375, 0.875, 0.75)"),
    ("flow sample", "flow_sample(lambda uv: uv[0], (0.2, 0.3), (0.1, 0.0), 0.5, 1.0, 1.0)", "0.15000000000000002"),
    ("depth taper", "taper(8.0, 10.0)", "5.0"),
    ("surface height", "surface_height(SMALLDOC, E, 3.0, 4.0, 1.0)", "20.15218820270499"),
    ("bad document", "validate_document(bad_document())", "['OC1', 'OC2', 'OC3', 'OC4', 'OC5', 'OC6']"),
)


def scope():
    """The names the table's expressions use."""
    s = dict(globals())
    s["E"] = example_seed()
    s["SEA"] = example_sea()
    s["SMALL"] = dict(example_sea(), resolution=8, size=128.0)
    s["DOC"] = example_document()
    s["OCEAN"] = s["DOC"]["oceans"][0]
    small_doc = example_document()
    small_doc["oceans"][0]["sea"].update(resolution=8, size=128.0)
    s["SMALLDOC"] = small_doc
    return s


def _same(a, b, rel=5e-4, abs_tol=1e-12):
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, complex) or isinstance(b, complex):
        return cmath.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)
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
    if isinstance(v, complex):
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
