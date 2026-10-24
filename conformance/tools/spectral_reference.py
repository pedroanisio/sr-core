#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add spectral rendering" (srep/srep-0000-spectral.md, OW2 of
SREP 12).

Pure functions, standard library only:

* dispersion models: Sellmeier and Cauchy forms, a table of named glasses with their published coefficients,
  the Abbe number and the bridge to KHR_materials_dispersion for the raster path;
* colour: the CIE 1931 2-degree colour matching functions as the Wyman, Sloan and Shirley (2013) multi-lobe
  fit, the CIE D65 illuminant at 10 nm, XYZ from a spectrum, chromaticity, the sRGB matrices, Planck's law;
* the Jakob and Hanika (2019) sigmoid-polynomial uplift of an RGB base colour to a bounded spectrum;
* hero-wavelength sampling (Wilkie et al. 2014): the hero from the path stream of SREP 92, its rotations, the
  spectral estimate with or without the companions after a dispersive event;
* the prism spectrum through the OW1 bench's deviation formula, and the seek check.

The D24 hash functions are copied from random_streams_reference.py so that this module stands alone.
Running the module prints the data rows of the draft's numeric table.
"""
import math

BAND = (380.0, 780.0)
DEFAULT_WAVELENGTHS = 4
MAX_WAVELENGTHS = 16
BAND_LIMITS = (360.0, 830.0)
DISPERSION_MODELS = ("none", "cauchy", "sellmeier", "glass")
LINES = {"F": 486.13, "d": 587.56, "C": 656.27, "e": 546.07, "g": 435.83}
RGB_WAVELENGTHS = (610.0, 550.0, 465.0)
TEMPERATURE_RANGE = (1000.0, 40000.0)
UPLIFT_BOUND = 0.005
UPLIFT_ITERATIONS = 100
SEEK_FRAMES = 48
CHANNEL_WAVELENGTH = 0x57415645  # "WAVE": the path stream channel of the hero draw, requested of SREP 92
CHANNEL_FRAME = 0x4652414D       # "FRAM": the per-frame seed derivation
SAMPLE_STRIDE = 65536            # pathSamples is at most 65536, so index = pixel * 65536 + sample is unique

# Planck
H_PLANCK = 6.62607015e-34
C_LIGHT = 299792458.0
K_BOLTZMANN = 1.380649e-23
WIEN_B = 2.897771955e6  # nm K


class SpectralError(ValueError):
    """A value outside the draft's domain."""


# ------------------------------------------------------------------------------------ D24 hashes (SREP 92)

MASK64 = (1 << 64) - 1
PHI = 0x9E3779B97F4A7C15
MUL1 = 0xBF58476D1CE4E5B9
MUL2 = 0x94D049BB133111EB
TWO53 = float(1 << 53)


def u64(x):
    if not isinstance(x, int) or x < -(1 << 63) or x >= (1 << 64):
        raise SpectralError(f"not a 64-bit integer: {x!r}")
    return x & MASK64


def mix64(z):
    z &= MASK64
    z = ((z ^ (z >> 30)) * MUL1) & MASK64
    z = ((z ^ (z >> 27)) * MUL2) & MASK64
    return z ^ (z >> 31)


def splitmix64(x):
    return mix64((u64(x) + PHI) & MASK64)


def H(seed, channel, index):
    return splitmix64(u64(seed) ^ splitmix64(u64(channel) ^ splitmix64(u64(index))))


def U(seed, channel, index):
    return (H(seed, channel, index) >> 11) / TWO53


# ------------------------------------------------------------------------------------ dispersion models

GLASSES = {
    "BK7": {"model": "sellmeier", "B": (1.03961212, 0.231792344, 1.01046945),
            "C": (0.00600069867, 0.0200179144, 103.560653), "range": (300.0, 2500.0),
            "source": "Schott N-BK7 data sheet (Sellmeier, micrometres)"},
    "SF10": {"model": "sellmeier", "B": (1.62153902, 0.256287842, 1.64447552),
             "C": (0.0122241457, 0.0595736775, 147.468793), "range": (380.0, 2500.0),
             "source": "Schott N-SF10 data sheet"},
    "SF11": {"model": "sellmeier", "B": (1.73759695, 0.313747346, 1.89878101),
             "C": (0.013188707, 0.0623068142, 155.23629), "range": (380.0, 2500.0),
             "source": "Schott N-SF11 data sheet"},
    "fusedSilica": {"model": "sellmeier", "B": (0.6961663, 0.4079426, 0.8974794),
                    "C": (0.0684043 ** 2, 0.1162414 ** 2, 9.896161 ** 2), "range": (210.0, 3710.0),
                    "source": "Malitson (1965), J. Opt. Soc. Am. 55, 1205"},
    "water": {"model": "sellmeier", "B": (5.684027565e-1, 1.726177391e-1, 2.086189578e-2, 1.130748688e-1),
              "C": (5.101829712e-3, 1.821153936e-2, 2.620722293e-2, 1.069792721e1), "range": (182.0, 1129.0),
              "source": "Daimon and Masumura (2007), Appl. Opt. 46, 3811, at 20 C"},
    "diamond": {"model": "sellmeier", "B": (0.3306, 4.3356), "C": (0.1750 ** 2, 0.1060 ** 2),
                "range": (225.0, 10000.0), "source": "Peter (1923), Z. Phys. 15, 358, as fitted on refractiveindex.info"},
}


def sellmeier(lam_nm, B, C):
    """n² = 1 + Σ Bᵢ λ² / (λ² − Cᵢ), λ in micrometres, Cᵢ in micrometres squared."""
    if len(B) != len(C) or not B:
        raise SpectralError("Sellmeier needs equal, non-empty B and C")
    if not lam_nm > 0.0:
        raise SpectralError("wavelength must be positive")
    l2 = (lam_nm / 1000.0) ** 2
    n2 = 1.0
    for b, c in zip(B, C):
        if l2 == c:
            raise SpectralError("wavelength at a Sellmeier pole")
        n2 += b * l2 / (l2 - c)
    if n2 < 1.0:
        raise SpectralError("the Sellmeier form gives an index below 1 here")
    return math.sqrt(n2)


def cauchy(lam_nm, A, B):
    """n = A + B / λ², λ in micrometres."""
    if not lam_nm > 0.0:
        raise SpectralError("wavelength must be positive")
    n = A + B / (lam_nm / 1000.0) ** 2
    if n < 1.0:
        raise SpectralError("the Cauchy form gives an index below 1 here")
    return n


def glass_index(name, lam_nm):
    """The index of a named glass at a wavelength inside its fit's range."""
    if name not in GLASSES:
        raise SpectralError(f"unknown glass {name!r}")
    g = GLASSES[name]
    lo, hi = g["range"]
    if not lo <= lam_nm <= hi:
        raise SpectralError(f"{name} is fitted for {lo:g} to {hi:g} nm")
    return sellmeier(lam_nm, g["B"], g["C"])


def refractive_index(material, lam_nm):
    """n(λ) of a material by its dispersion model."""
    model = material.get("model", "none")
    if model == "none":
        return float(material.get("ior", 1.5))
    if model == "glass":
        return glass_index(material["glass"], lam_nm)
    if model == "cauchy":
        return cauchy(lam_nm, material["A"], material["B"])
    if model == "sellmeier":
        return sellmeier(lam_nm, material["B"], material["C"])
    raise SpectralError(f"unknown dispersion model {model!r}")


def abbe_number(index_fn):
    """V_d = (n_d − 1) / (n_F − n_C)."""
    nd, nf, nc = index_fn(LINES["d"]), index_fn(LINES["F"]), index_fn(LINES["C"])
    if nf == nc:
        return math.inf
    return (nd - 1.0) / (nf - nc)


def cauchy_from_abbe(n_d, v_d):
    """The (A, B) Cauchy pair with the given n_d and Abbe number."""
    if not v_d > 0.0 or not n_d > 1.0:
        raise SpectralError("n_d above 1 and a positive Abbe number are needed")
    lf, lc, ld = (LINES["F"] / 1000.0, LINES["C"] / 1000.0, LINES["d"] / 1000.0)
    b = (n_d - 1.0) / (v_d * (1.0 / lf ** 2 - 1.0 / lc ** 2))
    return (n_d - b / ld ** 2, b)


def khr_dispersion(v_d):
    """KHR_materials_dispersion: dispersion = 20 / V_d."""
    if not v_d > 0.0:
        raise SpectralError("the Abbe number must be positive")
    return 20.0 / v_d


def material_dispersion(material):
    """The KHR dispersion of a material for the raster path: 0 without a model."""
    if material.get("model", "none") == "none":
        return 0.0
    return khr_dispersion(abbe_number(lambda lam: refractive_index(material, lam)))


def rgb_indices(material):
    """The indices at the red, green and blue wavelengths the raster path refracts with."""
    return tuple(refractive_index(material, lam) for lam in RGB_WAVELENGTHS)


# ------------------------------------------------------------------------------------ colour


def _lobe(lam, mu, s1, s2):
    s = s1 if lam < mu else s2
    t = (lam - mu) / s
    return math.exp(-0.5 * t * t)


def cie_xyz(lam):
    """The CIE 1931 2° colour matching functions, Wyman, Sloan and Shirley (2013) multi-lobe fit."""
    x = 1.056 * _lobe(lam, 599.8, 37.9, 31.0) + 0.362 * _lobe(lam, 442.0, 16.0, 26.7) \
        - 0.065 * _lobe(lam, 501.1, 20.4, 26.2)
    y = 0.821 * _lobe(lam, 568.8, 46.9, 40.5) + 0.286 * _lobe(lam, 530.9, 16.3, 31.1)
    z = 1.217 * _lobe(lam, 437.0, 11.8, 36.0) + 0.681 * _lobe(lam, 459.0, 26.0, 13.4)
    return (x, y, z)


D65_TABLE = (49.98, 54.65, 82.75, 91.49, 93.43, 86.68, 104.86, 117.01, 117.81, 114.86, 115.92, 108.81, 109.35,
             107.80, 104.79, 107.69, 104.41, 104.05, 100.00, 96.33, 95.79, 88.69, 90.01, 89.60, 87.70, 83.29,
             83.70, 80.03, 80.21, 82.28, 78.28, 69.72, 71.61, 74.35, 61.60, 69.89, 75.09, 63.59, 46.42, 66.81,
             63.38)  # CIE standard illuminant D65, relative power, 380 to 780 nm at 10 nm


def d65(lam):
    """The D65 relative power, linear between the table's 10 nm samples, 0 outside 380 to 780 nm."""
    if lam < 380.0 or lam > 780.0:
        return 0.0
    pos = (lam - 380.0) / 10.0
    i = min(int(pos), len(D65_TABLE) - 2)
    f = pos - i
    return D65_TABLE[i] * (1.0 - f) + D65_TABLE[i + 1] * f


def _band_samples(lo, hi, step):
    n = int(round((hi - lo) / step))
    return [lo + i * step for i in range(n + 1)]


_Y_NORM = {}


def _y_norm(lo, hi, step):
    key = (lo, hi, step)
    if key not in _Y_NORM:
        _Y_NORM[key] = sum(cie_xyz(l)[1] for l in _band_samples(lo, hi, step)) * step
    return _Y_NORM[key]


def xyz_from_spectrum(spectrum, lo=BAND[0], hi=BAND[1], step=1.0):
    """XYZ of a spectrum by the rectangle rule, normalised so that a constant 1 has Y = 1."""
    X = Y = Z = 0.0
    for lam in _band_samples(lo, hi, step):
        x, y, z = cie_xyz(lam)
        s = spectrum(lam)
        X += x * s
        Y += y * s
        Z += z * s
    k = step / _y_norm(lo, hi, step)
    return (X * k, Y * k, Z * k)


def white_point(spectrum, lo=BAND[0], hi=BAND[1], step=1.0):
    """XYZ of an illuminant scaled to Y = 1."""
    X, Y, Z = xyz_from_spectrum(spectrum, lo, hi, step)
    if Y <= 0.0:
        raise SpectralError("a white point needs a positive luminance")
    return (X / Y, 1.0, Z / Y)


def chromaticity(X, Y, Z):
    """(x, y) = (X, Y) / (X + Y + Z)."""
    s = X + Y + Z
    if s <= 0.0:
        raise SpectralError("chromaticity of a black stimulus")
    return (X / s, Y / s)


RGB_TO_XYZ = ((0.4124564, 0.3575761, 0.1804375),
              (0.2126729, 0.7151522, 0.0721750),
              (0.0193339, 0.1191920, 0.9503041))  # IEC 61966-2-1, D65


def _invert3(m):
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return (((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
            ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
            ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det))


XYZ_TO_RGB = _invert3(RGB_TO_XYZ)


def _mat(m, v):
    return tuple(sum(m[r][k] * v[k] for k in range(3)) for r in range(3))


def linear_srgb_to_xyz(r, g, b):
    return _mat(RGB_TO_XYZ, (r, g, b))


def xyz_to_linear_srgb(X, Y, Z):
    return _mat(XYZ_TO_RGB, (X, Y, Z))


def wien_peak(T):
    """λ_max = b / T in nm."""
    if not T > 0.0:
        raise SpectralError("temperature must be positive")
    return WIEN_B / T


def blackbody(lam_nm, T):
    """Planck's spectral radiance B(λ, T) in W sr⁻¹ m⁻³."""
    if not T > 0.0 or not lam_nm > 0.0:
        raise SpectralError("temperature and wavelength must be positive")
    lam = lam_nm * 1e-9
    x = H_PLANCK * C_LIGHT / (lam * K_BOLTZMANN * T)
    if x > 700.0:
        return 0.0
    return 2.0 * H_PLANCK * C_LIGHT * C_LIGHT / lam ** 5 / math.expm1(x)


def blackbody_normalised(lam_nm, T):
    """B(λ, T) / B(λ_max, T), 1 at the Wien peak."""
    return blackbody(lam_nm, T) / blackbody(wien_peak(T), T)


# ------------------------------------------------------------------------------------ uplift (Jakob and Hanika 2019)


def sigmoid(x):
    """1/2 + x / (2 √(1 + x²))."""
    return 0.5 + x / (2.0 * math.sqrt(1.0 + x * x))


def _sigmoid_inverse(y):
    a = 2.0 * (y - 0.5)
    a = max(-0.999999999, min(0.999999999, a))
    return a / math.sqrt(1.0 - a * a)


def uplift_spectrum(coeffs, lam):
    """s(λ) = sigmoid(c₀ t² + c₁ t + c₂), t = (λ − 380) / 400."""
    t = (lam - BAND[0]) / (BAND[1] - BAND[0])
    c0, c1, c2 = coeffs
    return sigmoid(c0 * t * t + c1 * t + c2)


_UPLIFT_CACHE = {}


def _uplift_tables():
    """The products cmf × D65 at 1 nm and the white point, computed once."""
    if not _UPLIFT_CACHE:
        lams = _band_samples(BAND[0], BAND[1], 1.0)
        rows = []
        wx = wy = wz = 0.0
        for lam in lams:
            x, y, z = cie_xyz(lam)
            e = d65(lam)
            rows.append((lam, x * e, y * e, z * e))
            wx += x * e
            wy += y * e
            wz += z * e
        target = linear_srgb_to_xyz(1.0, 1.0, 1.0)
        # scale XYZ so that the D65 white of the fit lands exactly on the sRGB white
        _UPLIFT_CACHE["rows"] = rows
        _UPLIFT_CACHE["scale"] = (target[0] / wx, target[1] / wy, target[2] / wz)
    return _UPLIFT_CACHE["rows"], _UPLIFT_CACHE["scale"]


def uplift_xyz(coeffs):
    """XYZ of the uplifted reflectance under D65, with the white at the sRGB white."""
    rows, scale = _uplift_tables()
    X = Y = Z = 0.0
    for lam, xe, ye, ze in rows:
        s = uplift_spectrum(coeffs, lam)
        X += xe * s
        Y += ye * s
        Z += ze * s
    return (X * scale[0], Y * scale[1], Z * scale[2])


def uplift_rgb(coeffs):
    """Linear sRGB of the uplifted spectrum."""
    return xyz_to_linear_srgb(*uplift_xyz(coeffs))


def fit_uplift(rgb):
    """The sigmoid-polynomial coefficients whose spectrum renders to the given linear sRGB (Gauss–Newton)."""
    if len(rgb) != 3 or any(not 0.0 <= c <= 1.0 for c in rgb):
        raise SpectralError("an uplifted colour lies in the unit cube")
    target = tuple(float(c) for c in rgb)
    mean = sum(target) / 3.0
    c = [0.0, 0.0, _sigmoid_inverse(mean)]

    def residual(cc):
        got = uplift_rgb(cc)
        return [got[k] - target[k] for k in range(3)]

    r = residual(c)
    err = sum(v * v for v in r)
    damping = 1e-3
    for _ in range(UPLIFT_ITERATIONS):
        if err < 1e-20:
            break
        h = 1e-4
        J = [[0.0] * 3 for _ in range(3)]
        for j in range(3):
            cp = list(c)
            cm = list(c)
            cp[j] += h
            cm[j] -= h
            rp = residual(cp)
            rm = residual(cm)
            for k in range(3):
                J[k][j] = (rp[k] - rm[k]) / (2.0 * h)
        # normal equations with Levenberg damping
        JtJ = [[sum(J[k][i] * J[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        Jtr = [sum(J[k][i] * r[k] for k in range(3)) for i in range(3)]
        stepped = False
        for _attempt in range(12):
            A = [[JtJ[i][j] + (damping if i == j else 0.0) * (1.0 + JtJ[i][i]) for j in range(3)] for i in range(3)]
            try:
                inv = _invert3(A)
            except ZeroDivisionError:
                damping *= 10.0
                continue
            delta = _mat(inv, Jtr)
            trial = [c[i] - delta[i] for i in range(3)]
            rt = residual(trial)
            et = sum(v * v for v in rt)
            if et < err:
                c, r, err = trial, rt, et
                damping = max(damping / 3.0, 1e-9)
                stepped = True
                break
            damping *= 10.0
        if not stepped:
            break
    return tuple(c)


def uplift_error(rgb):
    """The largest component error of the uplift round trip."""
    back = uplift_rgb(fit_uplift(rgb))
    return max(abs(back[k] - rgb[k]) for k in range(3))


# ------------------------------------------------------------------------------------ hero wavelengths


def hero_wavelengths(u, count, lo=BAND[0], hi=BAND[1]):
    """The hero λ₀ = lo + u (hi − lo) and its rotations λⱼ = lo + ((u + j / count) mod 1)(hi − lo)."""
    if not 0.0 <= u < 1.0:
        raise SpectralError("the unit draw lies in [0, 1)")
    if not (isinstance(count, int) and 1 <= count <= MAX_WAVELENGTHS):
        raise SpectralError(f"wavelengths per path lie in 1 .. {MAX_WAVELENGTHS}")
    if not lo < hi:
        raise SpectralError("the band needs bandMin below bandMax")
    return tuple(lo + ((u + j / count) % 1.0) * (hi - lo) for j in range(count))


def path_index(pixel, sample):
    """The path stream index: pixel × 65536 + sample."""
    if pixel < 0 or sample < 0 or sample >= SAMPLE_STRIDE:
        raise SpectralError("pixel and sample are non-negative and sample is below 65536")
    return pixel * SAMPLE_STRIDE + sample


def hero_unit(seed, pixel, sample):
    """The hero's unit draw U(seed, WAVE, path_index) of SREP 92."""
    return U(seed, CHANNEL_WAVELENGTH, path_index(pixel, sample))


def frame_seed(seed, frame):
    """The stream seed of a frame: H(seed, FRAM, frame)."""
    if frame < 0 or int(frame) != frame:
        raise SpectralError("frame must be a non-negative integer")
    return H(seed, CHANNEL_FRAME, int(frame))


def frame_wavelengths(frame, pixel, sample, count, seed=0, lo=BAND[0], hi=BAND[1]):
    """The wavelengths of one path at a frame: a pure function of (seed, frame, pixel, sample)."""
    return hero_wavelengths(hero_unit(frame_seed(seed, frame), pixel, sample), count, lo, hi)


def estimate_xyz(radiance, wavelengths, survivors=None, lo=BAND[0], hi=BAND[1]):
    """The hero estimate of XYZ: (hi − lo) / n Σ cmf(λⱼ) L(λⱼ) over the surviving wavelengths, normalised like
    xyz_from_spectrum."""
    if survivors is None:
        survivors = (True,) * len(wavelengths)
    if len(survivors) != len(wavelengths) or not survivors[0]:
        raise SpectralError("the hero always survives")
    alive = [lam for lam, s in zip(wavelengths, survivors) if s]
    k = (hi - lo) / len(alive) / _y_norm(lo, hi, 1.0)
    X = Y = Z = 0.0
    for lam in alive:
        x, y, z = cie_xyz(lam)
        L = radiance(lam)
        X += x * L
        Y += y * L
        Z += z * L
    return (X * k, Y * k, Z * k)


def dispersive_event(wavelengths, material):
    """A refraction: a dispersive material keeps the hero only; the index is the hero's."""
    model = material.get("model", "none")
    n = refractive_index(material, wavelengths[0])
    if model == "none":
        return {"survivors": (True,) * len(wavelengths), "index": n}
    return {"survivors": (True,) + (False,) * (len(wavelengths) - 1), "index": n}


# ------------------------------------------------------------------------------------ the bench and prisms


def prism_deviation(n, apex_deg, incidence_deg):
    """The OW1 bench's deviation: i + asin(n sin(A − asin(sin i / n))) − A, degrees."""
    a = math.radians(apex_deg)
    i = math.radians(incidence_deg)
    s = math.sin(i) / n
    if abs(s) > 1.0:
        raise SpectralError("no refraction at the first face")
    t1 = math.asin(s)
    s2 = n * math.sin(a - t1)
    if abs(s2) > 1.0:
        raise SpectralError("total internal reflection at the second face")
    return math.degrees(i + math.asin(s2)) - apex_deg


def prism_spectrum(glass, apex_deg, incidence_deg, wavelengths):
    """(λ, deviation) for each wavelength through a prism of the named glass."""
    return [(lam, prism_deviation(glass_index(glass, lam), apex_deg, incidence_deg)) for lam in wavelengths]


def angular_dispersion(glass, apex_deg, incidence_deg):
    """The deviation of the F line minus that of the C line, degrees."""
    rows = prism_spectrum(glass, apex_deg, incidence_deg, (LINES["F"], LINES["C"]))
    return rows[0][1] - rows[1][1]


def bench_index(element, lam_nm):
    """The index a bench element refracts with: its material at the ray's wavelength, or its n."""
    if "material" in element:
        if lam_nm is None:
            raise SpectralError("a dispersive element needs a wavelength on the source")
        return refractive_index(element["material"], lam_nm)
    return float(element["n"])


def wavelength_rgb(lam):
    """A drawing colour for a monochromatic ray: linear sRGB of the matching functions, clipped and scaled to
    a unit maximum."""
    rgb = [max(0.0, v) for v in xyz_to_linear_srgb(*cie_xyz(lam))]
    m = max(rgb)
    if m <= 0.0:
        return (0.0, 0.0, 0.0)
    return tuple(min(1.0, v / m) for v in rgb)


# ------------------------------------------------------------------------------------ seek


def seek_test():
    """Frame k's wavelengths and estimate alone equal frame k of a run over all frames (no state)."""
    run = [[frame_wavelengths(f, p, s, 4) for p in (0, 7, 99) for s in (0, 1)] for f in range(SEEK_FRAMES + 1)]
    for k in (0, 11, 24, 48):
        alone = [frame_wavelengths(k, p, s, 4) for p in (0, 7, 99) for s in (0, 1)]
        if alone != run[k]:
            return False
        for lams in alone:
            a = estimate_xyz(lambda lam: blackbody_normalised(lam, 5000.0), lams)
            b = estimate_xyz(lambda lam: blackbody_normalised(lam, 5000.0), lams)
            if a != b:
                return False
    return True


# ------------------------------------------------------------------------------------ validation


def validate_material(material):
    """SD1: a known model; a known glass; Cauchy A at least 1 and B non-negative; Sellmeier B and C of equal
    length with positive C; ior at least 1."""
    model = material.get("model", "none")
    if model not in DISPERSION_MODELS:
        raise SpectralError("SD1: unknown dispersion model")
    if model == "glass" and material.get("glass") not in GLASSES:
        raise SpectralError("SD1: unknown glass")
    if model == "cauchy" and (not material.get("A", 0.0) >= 1.0 or material.get("B", 0.0) < 0.0):
        raise SpectralError("SD1: Cauchy A at least 1 and B non-negative")
    if model == "sellmeier":
        B, C = material.get("B", ()), material.get("C", ())
        if len(B) != len(C) or not B:
            raise SpectralError("SD1: Sellmeier B and C of equal, positive length")
        if any(not c > 0.0 for c in C) or any(b < 0.0 for b in B):
            raise SpectralError("SD1: Sellmeier C positive and B non-negative")
    if model == "none" and not material.get("ior", 1.5) >= 1.0:
        raise SpectralError("SD1: ior at least 1")


def validate_spectral(camera):
    """SD2: with spectral, bandMin below bandMax inside 360 to 830 nm and wavelengths in 1 .. 16."""
    if not camera.get("spectral", False):
        return
    lo, hi = camera.get("bandMin", BAND[0]), camera.get("bandMax", BAND[1])
    if not (BAND_LIMITS[0] <= lo < hi <= BAND_LIMITS[1]):
        raise SpectralError("SD2: the band lies inside 360 to 830 nm with bandMin below bandMax")
    n = camera.get("wavelengths", DEFAULT_WAVELENGTHS)
    if not (isinstance(n, int) and 1 <= n <= MAX_WAVELENGTHS):
        raise SpectralError("SD2: wavelengths lie in 1 .. 16")


def validate_emitter(emitter):
    """SD3: exactly one of temperature (1000 to 40000 K) and spectrum."""
    has_t = "temperature" in emitter
    has_s = "spectrum" in emitter
    if has_t == has_s:
        raise SpectralError("SD3: exactly one of temperature and spectrum")
    if has_t and not TEMPERATURE_RANGE[0] <= emitter["temperature"] <= TEMPERATURE_RANGE[1]:
        raise SpectralError("SD3: temperature lies in 1000 to 40000 K")


def validate_bench_wavelength(lam):
    """SD4: a bench source's wavelength lies in the band."""
    if not BAND[0] <= lam <= BAND[1]:
        raise SpectralError("SD4: wavelength lies in 380 to 780 nm")


# ------------------------------------------------------------------------------------ the table

TABLE = (
    ("BK7 at the d line", "glass_index('BK7', LINES['d'])", "1.5168"),
    ("BK7 at the F line", "glass_index('BK7', LINES['F'])", "1.52238"),
    ("BK7 at the C line", "glass_index('BK7', LINES['C'])", "1.51432"),
    ("Abbe number of BK7", "abbe_number(lambda lam: glass_index('BK7', lam))", "64.1664"),
    ("KHR dispersion of BK7", "material_dispersion({'model': 'glass', 'glass': 'BK7'})", "0.31169"),
    ("SF10 at the d line", "glass_index('SF10', LINES['d'])", "1.72828"),
    ("SF11 at the d line", "glass_index('SF11', LINES['d'])", "1.78472"),
    ("fused silica at the d line", "glass_index('fusedSilica', LINES['d'])", "1.45846"),
    ("water at the d line", "glass_index('water', LINES['d'])", "1.3334"),
    ("diamond at the d line", "glass_index('diamond', LINES['d'])", "2.41749"),
    ("Cauchy pair for n_d 1.5168, V 64.17", "cauchy_from_abbe(1.5168, 64.17)", "(1.50458, 0.00421731)"),
    ("Cauchy at 500 nm", "cauchy(500, 1.5, 0.004)", "1.516"),
    ("RGB indices of BK7", "rgb_indices({'model': 'glass', 'glass': 'BK7'})", "(1.51591, 1.51852, 1.52401)"),
    ("y-bar at 555 nm", "cie_xyz(555)[1]", "0.998039"),
    ("x-bar at 445 nm", "cie_xyz(445)[0]", "0.358492"),
    ("equal-energy chromaticity", "chromaticity(*xyz_from_spectrum(lambda lam: 1.0))", "(0.333462, 0.333945)"),
    ("D65 chromaticity", "chromaticity(*xyz_from_spectrum(d65))", "(0.313111, 0.329492)"),
    ("D65 white point", "white_point(d65)", "(0.950284, 1, 1.08469)"),
    ("D65 white in linear sRGB", "xyz_to_linear_srgb(*white_point(d65))", "(1.00146, 1.00001, 0.995617)"),
    ("sRGB white XYZ", "linear_srgb_to_xyz(1, 1, 1)", "(0.95047, 1, 1.08883)"),
    ("Wien peak of 5778 K", "wien_peak(5778)", "501.518"),
    ("Planck at 500 nm, 5778 K", "blackbody(500, 5778)", "2.63757e+13"),
    ("6500 K chromaticity", "chromaticity(*xyz_from_spectrum(lambda lam: blackbody(lam, 6500)))", "(0.313878, 0.324148)"),
    ("3000 K in linear sRGB, scaled to Y 1", "xyz_to_linear_srgb(*xyz_from_spectrum(lambda lam: blackbody_normalised(lam, 3000)))", "(0.731071, 0.353596, 0.112152)"),
    ("uplift of grey 0.5", "fit_uplift((0.5, 0.5, 0.5))", "(0, 0, 0)"),
    ("uplift round trip of (0.2, 0.5, 0.7)", "uplift_rgb(fit_uplift((0.2, 0.5, 0.7)))", "(0.2, 0.5, 0.7)"),
    ("uplift error of (0.9, 0.1, 0.3)", "uplift_error((0.9, 0.1, 0.3)) < UPLIFT_BOUND", "True"),
    ("uplifted spectrum of (0.2, 0.5, 0.7) at 450 nm", "uplift_spectrum(fit_uplift((0.2, 0.5, 0.7)), 450)", "0.679988"),
    ("hero wavelengths at u 0.1", "hero_wavelengths(0.1, 4)", "(420, 520, 620, 720)"),
    ("hero wavelengths wrap at u 0.9", "hero_wavelengths(0.9, 4)", "(740, 440, 540, 640)"),
    ("path index of pixel 12345, sample 3", "path_index(12345, 3)", "8.09042e+08"),
    ("hero draw of seed 7, pixel 12345, sample 3", "hero_unit(7, 12345, 3)", "0.696965"),
    ("wavelengths at frame 3, pixel 10, sample 0", "frame_wavelengths(3, 10, 0, 4)", "(511.203, 611.203, 711.203, 411.203)"),
    ("estimate of a constant with the hero only", "estimate_xyz(lambda lam: 1.0, (550, 650, 750, 450), survivors=(True, False, False, False))[1]", "3.72041"),
    ("dispersive event keeps the hero", "dispersive_event((500, 600, 700, 400), {'model': 'glass', 'glass': 'BK7'})['survivors']", "(True, False, False, False)"),
    ("BK7 prism deviation at d, 60 degrees, incidence 50", "prism_deviation(glass_index('BK7', LINES['d']), 60, 50)", "38.6536"),
    ("BK7 prism F minus C spread", "angular_dispersion('BK7', 60, 50)", "0.702572"),
    ("SF10 prism F minus C spread", "angular_dispersion('SF10', 60, 60)", "2.94372"),
    ("drawing colour of 650 nm", "wavelength_rgb(650)", "(1, 0, 0)"),
    ("seek check", "seek_test()", "True"),
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
