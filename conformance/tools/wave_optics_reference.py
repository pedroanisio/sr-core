#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add polarisation and wave optics" (srep/srep-0000-wave-optics.md,
OW3 of SREP 12).

Pure functions, standard library only:

* Jones calculus: linear, circular and elliptical states, polarisers, waveplates and rotators, Stokes
  parameters, Malus's law, Biot's law of optical rotation and the colour of a sugar column between polarisers;
* scalar diffraction: the closed forms of the single slit, the double slit, the circular aperture (Airy, with
  J1 by quadrature) and the grating, the Fraunhofer pattern of a sampled aperture by a radix-2 FFT, and the
  Huygens–Fresnel summation of secondary sources for the near field;
* phase shown as hue for complex fields, and a time-harmonic field as a pure function of the frame (the seek
  check).

The CIE 1931 matching-function fit and the sRGB matrix of spectral_reference.py are copied so that this module
stands alone. Running the module prints the data rows of the draft's numeric table.
"""
import cmath
import math

POLARISATIONS = ("none", "linear", "circular", "elliptical")
HANDEDNESS = ("left", "right")
JONES_ELEMENTS = ("polariser", "waveplate", "rotator")
APERTURES = ("slit", "doubleSlit", "circular", "grating", "mask")
PHASE_MODES = ("hue", "none")
AMPLITUDE_MODES = ("value", "alpha", "none")
MAX_SAMPLES = 65536
SUCROSE_ROTATION = 66.5          # degrees per dm per (g / mL) at 589 nm
BIOT_WAVELENGTH = 589.0          # nm: the sodium D line the specific rotation is quoted at
SEEK_FRAMES = 48
BAND = (380.0, 780.0)


class WaveError(ValueError):
    """A value outside the draft's domain."""


# ------------------------------------------------------------------------------------ Jones calculus


def _rad(deg):
    return math.radians(deg)


def jones_linear(angle_deg):
    """Linear polarisation at an angle from x: (cos θ, sin θ)."""
    return (complex(math.cos(_rad(angle_deg))), complex(math.sin(_rad(angle_deg))))


def jones_circular(handedness):
    """(1, ±i) / √2: left is +i (counter-clockwise E vector looking into the beam, the optics convention)."""
    if handedness not in HANDEDNESS:
        raise WaveError("handedness is left or right")
    s = 1.0 / math.sqrt(2.0)
    return (complex(s), complex(0.0, s if handedness == "left" else -s))


def jones_elliptical(angle_deg, ellipticity_deg):
    """The state of azimuth θ and ellipticity angle χ: R(θ) (cos χ, i sin χ); χ = 45° is circular, 0 linear."""
    if not -45.0 <= ellipticity_deg <= 45.0:
        raise WaveError("ellipticity lies in -45 to 45 degrees")
    chi = _rad(ellipticity_deg)
    v = (complex(math.cos(chi)), complex(0.0, math.sin(chi)))
    return apply(rotator(angle_deg), v)


def intensity(v):
    """|Jx|² + |Jy|²."""
    return abs(v[0]) ** 2 + abs(v[1]) ** 2


def apply(m, v):
    """The matrix product M v."""
    return (m[0][0] * v[0] + m[0][1] * v[1], m[1][0] * v[0] + m[1][1] * v[1])


def _matmul(a, b):
    return ((a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1]),
            (a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1]))


def compose(*matrices):
    """The product of matrices applied right to left: compose(C, B, A) v = C (B (A v))."""
    out = ((1 + 0j, 0j), (0j, 1 + 0j))
    for m in matrices:
        out = _matmul(out, m)
    return out


def rotation(angle_deg):
    c, s = math.cos(_rad(angle_deg)), math.sin(_rad(angle_deg))
    return ((complex(c), complex(-s)), (complex(s), complex(c)))


def polariser(angle_deg):
    """The projector onto the linear state at θ: R(θ) diag(1, 0) R(−θ)."""
    c, s = math.cos(_rad(angle_deg)), math.sin(_rad(angle_deg))
    return ((complex(c * c), complex(c * s)), (complex(c * s), complex(s * s)))


def waveplate(retardance_deg, fast_axis_deg):
    """A retarder of phase δ between the fast and slow axes, fast axis at θ: R(θ) diag(1, e^{iδ}) R(−θ)."""
    if not retardance_deg > 0.0:
        raise WaveError("retardance must be positive")
    d = ((1 + 0j, 0j), (0j, cmath.exp(1j * _rad(retardance_deg))))
    return compose(rotation(fast_axis_deg), d, rotation(-fast_axis_deg))


def quarter_wave(fast_axis_deg):
    return waveplate(90.0, fast_axis_deg)


def half_wave(fast_axis_deg):
    return waveplate(180.0, fast_axis_deg)


def rotator(angle_deg):
    """An optical rotator turns the plane of polarisation by its angle."""
    return rotation(angle_deg)


def malus(theta_deg):
    """I / I₀ = cos² θ."""
    return math.cos(_rad(theta_deg)) ** 2


def unpolarised_through(m):
    """The transmitted fraction of unpolarised light: the mean over two orthogonal incoherent states."""
    return 0.5 * (intensity(apply(m, jones_linear(0.0))) + intensity(apply(m, jones_linear(90.0))))


def stokes(v):
    """(S0, S1, S2, S3) of a Jones vector."""
    ex, ey = v
    s0 = abs(ex) ** 2 + abs(ey) ** 2
    s1 = abs(ex) ** 2 - abs(ey) ** 2
    s2 = 2.0 * (ex * ey.conjugate()).real
    s3 = -2.0 * (ex * ey.conjugate()).imag
    return (s0, s1, s2, s3)


def degree_of_polarisation(s):
    """√(S1² + S2² + S3²) / S0."""
    if not s[0] > 0.0:
        raise WaveError("a dark beam has no degree of polarisation")
    return math.sqrt(s[1] ** 2 + s[2] ** 2 + s[3] ** 2) / s[0]


def source_jones(src):
    """The Jones states a source emits, each with its share of the power: a list of (vector, share)."""
    kind = src.get("polarisation", "none")
    if kind == "none":
        return [(jones_linear(0.0), 0.5), (jones_linear(90.0), 0.5)]
    if kind == "linear":
        return [(jones_linear(src.get("angle", 0.0)), 1.0)]
    if kind == "circular":
        return [(jones_circular(src.get("handedness", "left")), 1.0)]
    if kind == "elliptical":
        return [(jones_elliptical(src.get("angle", 0.0), src.get("ellipticity", 0.0)), 1.0)]
    raise WaveError(f"unknown polarisation {kind!r}")


def biot_rotation(specific_rotation, length_dm, concentration, lam_nm):
    """Biot's law: α = [α]_D l c (589 / λ)², degrees."""
    if length_dm < 0.0 or concentration < 0.0 or not lam_nm > 0.0:
        raise WaveError("length and concentration are non-negative and the wavelength positive")
    return specific_rotation * length_dm * concentration * (BIOT_WAVELENGTH / lam_nm) ** 2


def rotation_transmission(rotation_deg, analyser_deg):
    """The fraction through a polariser at 0, a rotation α and an analyser at β: cos²(α − β)."""
    return math.cos(_rad(rotation_deg - analyser_deg)) ** 2


def helix_pitch(specific_rotation, concentration, lam_nm):
    """The length in dm over which the E vector turns once: 360 / α per dm."""
    rate = biot_rotation(specific_rotation, 1.0, concentration, lam_nm)
    if rate == 0.0:
        return math.inf
    return 360.0 / rate


# ---- colour (copied from spectral_reference.py)

def _lobe(lam, mu, s1, s2):
    s = s1 if lam < mu else s2
    t = (lam - mu) / s
    return math.exp(-0.5 * t * t)


def cie_xyz(lam):
    x = 1.056 * _lobe(lam, 599.8, 37.9, 31.0) + 0.362 * _lobe(lam, 442.0, 16.0, 26.7) \
        - 0.065 * _lobe(lam, 501.1, 20.4, 26.2)
    y = 0.821 * _lobe(lam, 568.8, 46.9, 40.5) + 0.286 * _lobe(lam, 530.9, 16.3, 31.1)
    z = 1.217 * _lobe(lam, 437.0, 11.8, 36.0) + 0.681 * _lobe(lam, 459.0, 26.0, 13.4)
    return (x, y, z)


RGB_TO_XYZ = ((0.4124564, 0.3575761, 0.1804375),
              (0.2126729, 0.7151522, 0.0721750),
              (0.0193339, 0.1191920, 0.9503041))


def _invert3(m):
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return (((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
            ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
            ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det))


XYZ_TO_RGB = _invert3(RGB_TO_XYZ)


def _xyz_to_rgb(X, Y, Z):
    return tuple(XYZ_TO_RGB[r][0] * X + XYZ_TO_RGB[r][1] * Y + XYZ_TO_RGB[r][2] * Z for r in range(3))


_WHITE = {}


def _equal_energy_white():
    """XYZ of the equal-energy spectrum over the band, used to scale colours so that it is (1, 1, 1)."""
    if not _WHITE:
        X = Y = Z = 0.0
        for i in range(401):
            x, y, z = cie_xyz(BAND[0] + i)
            X += x
            Y += y
            Z += z
        _WHITE["xyz"] = (X, Y, Z)
    return _WHITE["xyz"]


def rotation_colour(length_dm, concentration, analyser_deg, specific_rotation=SUCROSE_ROTATION):
    """Linear sRGB of white light through a polariser, a sugar column and an analyser, scaled so that the
    untouched white is (1, 1, 1)."""
    wx, wy, wz = _equal_energy_white()
    X = Y = Z = 0.0
    for i in range(401):
        lam = BAND[0] + i
        t = rotation_transmission(biot_rotation(specific_rotation, length_dm, concentration, lam), analyser_deg)
        x, y, z = cie_xyz(lam)
        X += x * t
        Y += y * t
        Z += z * t
    white = tuple(sum(row) for row in RGB_TO_XYZ)  # the sRGB white, which the inverse maps to (1, 1, 1)
    rgb = _xyz_to_rgb(X / wx * white[0], Y / wy * white[1], Z / wz * white[2])
    return tuple(min(1.0, max(0.0, v)) for v in rgb)


# ------------------------------------------------------------------------------------ diffraction


def sinc(x):
    """sin x / x, 1 at 0."""
    if x == 0.0:
        return 1.0
    return math.sin(x) / x


def single_slit(width, lam, theta):
    """I / I₀ = sinc²(π a sin θ / λ)."""
    return sinc(math.pi * width * math.sin(theta) / lam) ** 2


def slit_minimum(width, lam, m):
    """The angle of the m-th minimum: a sin θ = m λ."""
    s = m * lam / width
    if m == 0 or abs(s) > 1.0:
        raise WaveError("no such minimum")
    return math.asin(s)


def double_slit(width, separation, lam, theta):
    """cos²(π d sin θ / λ) sinc²(π a sin θ / λ)."""
    return math.cos(math.pi * separation * math.sin(theta) / lam) ** 2 * single_slit(width, lam, theta)


def fringe_spacing(lam, distance, separation):
    """Δx = λ L / d."""
    if not (lam > 0.0 and distance > 0.0 and separation > 0.0):
        raise WaveError("wavelength, distance and separation are positive")
    return lam * distance / separation


def bessel_j1(x):
    """J₁(x) = (1/π) ∫₀^π cos(τ − x sin τ) dτ by Simpson's rule."""
    n = 400
    h = math.pi / n
    total = 0.0
    for i in range(n + 1):
        tau = i * h
        w = 1.0 if i in (0, n) else (4.0 if i % 2 else 2.0)
        total += w * math.cos(tau - x * math.sin(tau))
    return total * h / 3.0 / math.pi


def j1_first_zero():
    """The first positive zero of J₁ by bisection (3.8317...)."""
    lo, hi = 3.0, 4.5
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if bessel_j1(lo) * bessel_j1(mid) <= 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


AIRY_FACTOR = j1_first_zero() / math.pi  # sin θ = 1.2197 λ / D


def airy(diameter, lam, theta):
    """(2 J₁(x) / x)², x = π D sin θ / λ."""
    x = math.pi * diameter * math.sin(theta) / lam
    if x == 0.0:
        return 1.0
    return (2.0 * bessel_j1(x) / x) ** 2


def airy_first_zero(diameter, lam):
    """The angle of the first dark ring: sin θ = 1.2197 λ / D."""
    s = AIRY_FACTOR * lam / diameter
    if s > 1.0:
        raise WaveError("the aperture is smaller than the first ring's angle allows")
    return math.asin(s)


def airy_encircled(rings):
    """The energy inside the n-th dark ring: 1 − J₀²(x) − J₁²(x) at x = the ring's zero (0.838 for the first)."""
    if rings != 1:
        raise WaveError("only the first ring is tabulated")
    x = j1_first_zero()
    n = 400
    h = math.pi / n
    j0 = 0.0
    for i in range(n + 1):
        tau = i * h
        w = 1.0 if i in (0, n) else (4.0 if i % 2 else 2.0)
        j0 += w * math.cos(x * math.sin(tau))
    j0 = j0 * h / 3.0 / math.pi
    return 1.0 - j0 * j0 - bessel_j1(x) ** 2


def grating(lines, period, lam, theta):
    """(sin(N φ) / (N sin φ))², φ = π d sin θ / λ."""
    phi = math.pi * period * math.sin(theta) / lam
    s = math.sin(phi)
    if abs(s) < 1e-12:
        return 1.0
    return (math.sin(lines * phi) / (lines * s)) ** 2


def grating_orders(period, lam):
    """The angles of every order m with |m λ / d| ≤ 1, from the most negative."""
    m_max = int(math.floor(period / lam))
    return [math.asin(m * lam / period) for m in range(-m_max, m_max + 1)]


def resolving_power(lines, order):
    """R = m N."""
    return lines * order


def grating_dispersion(period, lam, order):
    """dθ/dλ = m / (d cos θ)."""
    theta = math.asin(order * lam / period)
    return order / (period * math.cos(theta))


def fft(values):
    """The radix-2 Cooley–Tukey transform, X_k = Σ x_n e^{−2πi k n / N}."""
    n = len(values)
    if n == 0 or n & (n - 1):
        raise WaveError("the FFT needs a power-of-two length")
    a = [complex(v) for v in values]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        w = cmath.exp(-2j * math.pi / length)
        for start in range(0, n, length):
            wk = 1 + 0j
            for k in range(length // 2):
                u = a[start + k]
                v = a[start + k + length // 2] * wk
                a[start + k] = u + v
                a[start + k + length // 2] = u - v
                wk *= w
        length <<= 1
    return a


def ifft(values):
    n = len(values)
    out = fft([v.conjugate() for v in values])
    return [v.conjugate() / n for v in out]


def aperture_function(aperture, samples, extent):
    """The transmission of a one-dimensional aperture sampled at `samples` points across `extent`, centred."""
    kind = aperture.get("kind")
    if kind not in APERTURES:
        raise WaveError("unknown aperture")
    if kind == "circular":
        raise WaveError("the circular aperture is radial: use airy")
    if samples <= 0 or samples & (samples - 1) or samples > MAX_SAMPLES:
        raise WaveError("samples is a power of two up to 65536")
    dx = extent / samples
    xs = [(i - samples / 2) * dx for i in range(samples)]
    if kind == "mask":
        vals = aperture["values"]
        if len(vals) != samples:
            raise WaveError("a mask has one value per sample")
        return [complex(v) for v in vals]
    if kind == "slit":
        a = aperture["width"]
        return [complex(1.0) if -a / 2.0 <= x < a / 2.0 else 0j for x in xs]
    if kind == "doubleSlit":
        a, d = aperture["width"], aperture["separation"]
        return [complex(1.0) if (-a / 2.0 <= x - d / 2.0 < a / 2.0 or -a / 2.0 <= x + d / 2.0 < a / 2.0) else 0j
                for x in xs]
    n_lines, p, a = aperture["lines"], aperture["period"], aperture["width"]
    centres = [(k - (n_lines - 1) / 2.0) * p for k in range(n_lines)]
    return [complex(1.0) if any(-a / 2.0 <= x - c < a / 2.0 for c in centres) else 0j for x in xs]


def fraunhofer_fft(aperture, lam, distance, samples=4096, extent=2e-3):
    """The far-field intensity on a screen at `distance`: |FFT of the aperture|², at x = L λ f for the spatial
    frequencies f = k / extent, normalised to a unit peak; a list of (x, intensity) sorted by x."""
    if not (lam > 0.0 and distance > 0.0 and extent > 0.0):
        raise WaveError("wavelength, distance and extent are positive")
    field = aperture_function(aperture, samples, extent)
    spectrum = fft(field)
    out = []
    for k in range(samples):
        freq = (k if k < samples / 2 else k - samples) / extent
        out.append((distance * lam * freq, abs(spectrum[k]) ** 2))
    out.sort()
    peak = max(i for _, i in out)
    if peak <= 0.0:
        raise WaveError("an opaque aperture")
    return [(x, i / peak) for x, i in out]


def aperture_points(aperture, count):
    """`count` secondary sources spread evenly over the open parts of a one-dimensional aperture."""
    kind = aperture.get("kind")
    if kind == "slit":
        a = aperture["width"]
        return [-a / 2.0 + a * (i + 0.5) / count for i in range(count)]
    if kind == "doubleSlit":
        a, d = aperture["width"], aperture["separation"]
        half = count // 2
        return [-d / 2.0 - a / 2.0 + a * (i + 0.5) / half for i in range(half)] + \
               [d / 2.0 - a / 2.0 + a * (i + 0.5) / (count - half) for i in range(count - half)]
    if kind == "grating":
        n_lines, p, a = aperture["lines"], aperture["period"], aperture["width"]
        per = max(1, count // n_lines)
        pts = []
        for k in range(n_lines):
            c = (k - (n_lines - 1) / 2.0) * p
            pts += [c - a / 2.0 + a * (i + 0.5) / per for i in range(per)]
        return pts
    raise WaveError("Huygens points need a slit, doubleSlit or grating")


def huygens(points, lam, distance, x_screen):
    """The Huygens–Fresnel sum Σ e^{ikr} / √r of secondary sources on a line (cylindrical waves)."""
    k = 2.0 * math.pi / lam
    total = 0j
    for p in points:
        r = math.hypot(x_screen - p, distance)
        total += cmath.exp(1j * k * r) / math.sqrt(r)
    return total


def huygens_pattern(points, lam, distance, x_range, count):
    """(x, intensity) across the screen, normalised to a unit peak."""
    xs = [x_range[0] + (x_range[1] - x_range[0]) * i / (count - 1) for i in range(count)]
    raw = [(x, abs(huygens(points, lam, distance, x)) ** 2) for x in xs]
    peak = max(i for _, i in raw)
    return [(x, i / peak) for x, i in raw]


def fresnel_number(size, lam, distance):
    """N_F = a² / (λ L): far field below about 1."""
    if not (lam > 0.0 and distance > 0.0):
        raise WaveError("wavelength and distance are positive")
    return size * size / (lam * distance)


# ------------------------------------------------------------------------------------ phase as hue


def phase_hue(phase):
    """The hue in [0, 1) of a phase: φ / 2π mod 1."""
    return (phase / (2.0 * math.pi)) % 1.0


def hsv_to_rgb(h, s, v):
    i = int(math.floor(h * 6.0)) % 6
    f = h * 6.0 - math.floor(h * 6.0)
    p, q, t = v * (1.0 - s), v * (1.0 - s * f), v * (1.0 - s * (1.0 - f))
    return ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[i]


def complex_rgb(z, amplitude_max=1.0):
    """Hue from the phase, value from |z| / amplitude_max clipped to 1, saturation 1."""
    if not amplitude_max > 0.0:
        raise WaveError("amplitude_max must be positive")
    a = min(1.0, abs(z) / amplitude_max)
    if a == 0.0:
        return (0.0, 0.0, 0.0)
    return hsv_to_rgb(phase_hue(cmath.phase(z)), 1.0, a)


# ------------------------------------------------------------------------------------ time and the seek check


def time_harmonic(x, t, lam, frequency, amplitude):
    """A e^{i(kx − ωt)}."""
    if not lam > 0.0:
        raise WaveError("wavelength must be positive")
    return amplitude * cmath.exp(1j * (2.0 * math.pi * x / lam - 2.0 * math.pi * frequency * t))


def frame_field(frame, fps, x, lam, frequency, amplitude=1.0):
    """The field at a frame: a pure function of frame / fps."""
    if frame < 0 or int(frame) != frame or not fps > 0.0:
        raise WaveError("frame is a non-negative integer and fps positive")
    return time_harmonic(x, frame / fps, lam, frequency, amplitude)


def seek_test():
    """Frame k alone equals frame k of a run; the Jones chain and the Huygens sum carry no state."""
    pts = aperture_points({"kind": "doubleSlit", "width": 5e-6, "separation": 1e-4}, 16)
    run = [(frame_field(f, 24.0, 0.3, 2.0, 0.5), complex_rgb(frame_field(f, 24.0, 0.3, 2.0, 0.5)),
            abs(huygens(pts, 500e-9, 1.0, 1e-3 * math.sin(f))) ** 2,
            intensity(apply(compose(polariser(f * 3.0), quarter_wave(f)), jones_linear(0.0))))
           for f in range(SEEK_FRAMES + 1)]
    for k in (0, 7, 24, 48):
        alone = (frame_field(k, 24.0, 0.3, 2.0, 0.5), complex_rgb(frame_field(k, 24.0, 0.3, 2.0, 0.5)),
                 abs(huygens(pts, 500e-9, 1.0, 1e-3 * math.sin(k))) ** 2,
                 intensity(apply(compose(polariser(k * 3.0), quarter_wave(k)), jones_linear(0.0))))
        if alone != run[k]:
            return False
    return True


# ------------------------------------------------------------------------------------ validation


def validate_polarisation(src):
    """WO1 (sources): a known polarisation; circular has a handedness; elliptical has ellipticity in ±45°."""
    kind = src.get("polarisation", "none")
    if kind not in POLARISATIONS:
        raise WaveError("WO1: unknown polarisation")
    if kind == "circular" and src.get("handedness", "left") not in HANDEDNESS:
        raise WaveError("WO1: handedness is left or right")
    if kind == "elliptical" and not -45.0 <= src.get("ellipticity", 0.0) <= 45.0:
        raise WaveError("WO1: ellipticity lies in -45 to 45 degrees")


def validate_jones_element(el):
    """WO1 (elements): polariser, waveplate with positive retardance, rotator with an angle or Biot data."""
    kind = el.get("kind")
    if kind not in JONES_ELEMENTS:
        raise WaveError("WO1: unknown Jones element")
    if kind == "waveplate" and not el.get("retardance", 0.0) > 0.0:
        raise WaveError("WO1: retardance must be positive")
    if kind == "rotator":
        if "angle" in el:
            return
        if not all(k in el for k in ("specificRotation", "length", "concentration")):
            raise WaveError("WO3: a rotator has an angle or specificRotation, length and concentration")
        if el["length"] < 0.0 or el["concentration"] < 0.0:
            raise WaveError("WO3: length and concentration are non-negative")


def validate_aperture(ap):
    """WO2: positive sizes, separation above the slit width, at least two grating lines, a positive wavelength
    and distance, samples a power of two up to 65536."""
    kind = ap.get("kind")
    if kind not in APERTURES:
        raise WaveError("WO2: unknown aperture")
    if not ap.get("wavelength", 0.0) > 0.0 or not ap.get("distance", 0.0) > 0.0:
        raise WaveError("WO2: wavelength and distance are positive")
    n = ap.get("samples", 1024)
    if n <= 0 or n & (n - 1) or n > MAX_SAMPLES:
        raise WaveError("WO2: samples is a power of two up to 65536")
    if kind in ("slit", "doubleSlit", "grating") and not ap.get("width", 0.0) > 0.0:
        raise WaveError("WO2: width must be positive")
    if kind == "doubleSlit" and not ap.get("separation", 0.0) > ap["width"]:
        raise WaveError("WO2: separation exceeds the slit width")
    if kind == "grating" and (ap.get("lines", 0) < 2 or not ap.get("period", 0.0) > ap["width"]):
        raise WaveError("WO2: at least two lines and a period above the line width")
    if kind == "circular" and not ap.get("diameter", 0.0) > 0.0:
        raise WaveError("WO2: diameter must be positive")


def validate_display(d):
    """WO4: phase mode hue or none, amplitude mode value, alpha or none, positive gamma."""
    if d.get("phase", "hue") not in PHASE_MODES:
        raise WaveError("WO4: phase is hue or none")
    if d.get("amplitude", "value") not in AMPLITUDE_MODES:
        raise WaveError("WO4: amplitude is value, alpha or none")
    if not d.get("gamma", 1.0) > 0.0:
        raise WaveError("WO4: gamma must be positive")


# ------------------------------------------------------------------------------------ the table

TABLE = (
    ("Malus at 30 degrees", "malus(30)", "0.75"),
    ("Malus at 60 degrees", "malus(60)", "0.25"),
    ("linear at 0 through a polariser at 45", "intensity(apply(polariser(45), jones_linear(0)))", "0.5"),
    ("crossed polarisers", "intensity(apply(compose(polariser(90), polariser(0)), jones_linear(0)))", "0"),
    ("three polarisers at 0, 45, 90", "intensity(apply(compose(polariser(90), polariser(45), polariser(0)), jones_linear(0)))", "0.25"),
    ("unpolarised through a polariser", "unpolarised_through(polariser(33))", "0.5"),
    ("Stokes of linear at 45", "stokes(jones_linear(45))", "(1, 0, 1, 0)"),
    ("Stokes S3 of left circular", "stokes(jones_circular('left'))[3]", "1"),
    ("quarter-wave at 45 makes circular light", "abs(stokes(apply(quarter_wave(45), jones_linear(0)))[3])", "1"),
    ("half-wave at 20 rotates by 40", "intensity(apply(polariser(40), apply(half_wave(20), jones_linear(0))))", "1"),
    ("rotator of 25 on linear at 10", "intensity(apply(polariser(35), apply(rotator(25), jones_linear(10))))", "1"),
    ("sucrose rotation, 1 dm, 1 g/mL, 589 nm", "biot_rotation(SUCROSE_ROTATION, 1, 1, 589)", "66.5"),
    ("sucrose rotation at 450 nm", "biot_rotation(SUCROSE_ROTATION, 1, 1, 450)", "113.927"),
    ("crossed analyser after 30 degrees of rotation", "rotation_transmission(30, 90)", "0.25"),
    ("helix pitch of 1 g/mL sucrose at 589 nm, dm", "helix_pitch(SUCROSE_ROTATION, 1, 589)", "5.41353"),
    ("colour of a 2 dm column between crossed polarisers", "rotation_colour(2, 1, 90)", "(0.956719, 0.133937, 0.548296)"),
    ("single slit first minimum, a 20 um, 500 nm", "math.degrees(slit_minimum(20e-6, 500e-9, 1))", "1.43254"),
    ("single slit at half the first minimum", "single_slit(20e-6, 500e-9, slit_minimum(20e-6, 500e-9, 1) / 2)", "0.405221"),
    ("fringe spacing, 500 nm, 1 m, 100 um", "fringe_spacing(500e-9, 1, 100e-6)", "0.005"),
    ("double slit missing fifth order", "double_slit(20e-6, 100e-6, 500e-9, math.asin(5 * 500e-9 / 100e-6))", "0"),
    ("J1 at 1", "bessel_j1(1)", "0.440051"),
    ("first zero of J1", "j1_first_zero()", "3.83171"),
    ("Airy factor", "AIRY_FACTOR", "1.21967"),
    ("Airy first dark ring, D 2 mm, 550 nm, arcsec", "math.degrees(airy_first_zero(2e-3, 550e-9)) * 3600", "69.1831"),
    ("Airy first bright ring height", "max(airy(2e-3, 550e-9, airy_first_zero(2e-3, 550e-9) * (1 + i / 200)) for i in range(1, 200))", "0.0174978"),
    ("energy inside the first dark ring", "airy_encircled(1)", "0.837785"),
    ("grating orders for d 2 um, 500 nm", "len(grating_orders(2e-6, 500e-9))", "9"),
    ("grating first order angle, degrees", "math.degrees(grating_orders(2e-6, 500e-9)[5])", "14.4775"),
    ("grating zero beside the first order", "grating(100, 2e-6, 500e-9, math.asin(500e-9 / 2e-6 + 500e-9 / (100 * 2e-6)))", "0"),
    ("resolving power of 100 lines in order 2", "resolving_power(100, 2)", "200"),
    ("FFT of a delta", "[abs(v) for v in fft([1, 0, 0, 0])]", "(1, 1, 1, 1)"),
    ("Fraunhofer FFT first minimum, slit 20 um", "min((i, x) for x, i in fraunhofer_fft({'kind': 'slit', 'width': 20e-6}, 500e-9, 1, 4096, 2e-3) if 0.015 < x < 0.035)[1]", "0.025"),
    ("Fresnel number, a 5 um, 500 nm, 1 m", "fresnel_number(5e-6, 500e-9, 1)", "5e-05"),
    ("Huygens bright fringe over the centre", "abs(huygens(aperture_points({'kind': 'doubleSlit', 'width': 5e-6, 'separation': 1e-4}, 64), 500e-9, 1, 0.005)) ** 2 / abs(huygens(aperture_points({'kind': 'doubleSlit', 'width': 5e-6, 'separation': 1e-4}, 64), 500e-9, 1, 0)) ** 2", "0.991798"),
    ("hue of phase pi", "phase_hue(math.pi)", "0.5"),
    ("colour of e^(2 pi i / 3)", "complex_rgb(cmath.exp(2j * math.pi / 3))", "(0, 1, 0)"),
    ("colour of half amplitude at phase 0", "complex_rgb(0.5)", "(0.5, 0, 0)"),
    ("field phase at x = lambda / 2, t 0", "cmath.phase(time_harmonic(1, 0, 2, 0.5, 1))", "3.14159"),
    ("seek check", "seek_test()", "True"),
)


def scope():
    s = dict(globals())
    s["math"] = math
    s["cmath"] = cmath
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
        v = 0.0  # round-off residuals of exact zeros print as 0
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, (int, float)):
        return f"{v:.6g}"
    if isinstance(v, (tuple, list)):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    return repr(v)


def main():
    s = scope()
    for name, expr, _expected in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
