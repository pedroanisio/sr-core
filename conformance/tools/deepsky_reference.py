#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add deep sky: procedural galaxies, N-body mergers and
emission-line nebulae" (srep/srep-0000-deepsky.md), SP8 of SREP 12.

Standard library only. The rules of the SREP's Semantics section are the functions below, in its order: the
exponential and Sérsic profiles and their enclosed fractions (rules 1 and 2), the inverse-CDF samplers of radius,
height and azimuth (rules 3 to 5), the spiral arms and dust lanes (rules 5 and 6), star colours (rule 7), the
seeded catalogue (rule 8), the rotation curve and the galaxy's bodies (rule 9), the leapfrog N-body and mergers
(rule 10), the emission lines, palettes and the nebula sample (rules 11 and 12) and the bounds (rule 13).
`main()` prints the SREP's numeric table; `tests/test_deepsky.py` checks both.

Units: the galaxy's lengths are in scene units; the disk lies in the xz plane and its normal is +y; G = 1 in
the dynamics; temperatures are kelvin; wavelengths nanometres.
"""
import math
import zlib
from functools import lru_cache

MAX_STARS = 1 << 22       # galaxy/@stars
MAX_BODIES = 4096         # dynamics/@bodies
MAX_STEPS = 65536         # steps of one dynamics run
MAX_ARMS = 8              # arms/@count
MAX_LINES = 16            # line children of a nebula
RADIUS_CUT = 20.0         # disk radii beyond RADIUS_CUT scale lengths are not drawn
BULGE_CUT = 100.0         # bulge radii beyond BULGE_CUT effective radii are not drawn
SERSIC_MIN, SERSIC_MAX = 0.5, 10.0
P_COMPONENT, P_RADIUS, P_ANGLE, P_HEIGHT, P_COLOUR, P_BRIGHTNESS = 0, 1, 2, 3, 4, 5

# --- D24 (DEFINITIONS.md) and the random-streams draft, copied ---------------------------------------------

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1
TWO53 = float(1 << 53)
PHI = 0x9E3779B97F4A7C15


def u64(x):
    return int(x) & MASK64


def mix64(z):
    z = u64(z)
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9 & MASK64
    z = (z ^ (z >> 27)) * 0x94D049BB133111EB & MASK64
    return z ^ (z >> 31)


def splitmix64(x):
    return mix64((u64(x) + PHI) & MASK64)


def H(seed, channel, index):
    return splitmix64(u64(seed) ^ splitmix64(u64(channel) ^ splitmix64(u64(index))))


def U(seed, channel, index):
    return (H(seed, channel, index) >> 11) / TWO53


def E(project, element_id, seed, purpose):
    s = "" if seed is None else str(u64(seed))
    return zlib.crc32(f"{u64(project)}:{element_id}:{s}:{purpose}".encode("utf-8"))


def S(element_seed, purpose, step, index):
    for v in (purpose, step):
        if not isinstance(v, int) or v < 0 or v > MASK32:
            raise ValueError(f"purpose and step are integers in [0, 2^32): {v!r}")
    return U(element_seed, purpose + (step << 32), index)


# --- rules 1 and 2: the profiles -----------------------------------------------------------------------------


def exponential_profile(sigma0, h, r):
    """The exponential disk's surface density sigma0 exp(-r/h)."""
    if h <= 0.0:
        raise ValueError("the scale length must be positive")
    return sigma0 * math.exp(-r / h)


def exponential_enclosed(h, r):
    """The fraction of the exponential disk's mass within r: 1 - (1 + r/h) exp(-r/h)."""
    if h <= 0.0:
        raise ValueError("the scale length must be positive")
    x = r / h
    return 1.0 - (1.0 + x) * math.exp(-x)


def gamma_p(s, x):
    """The regularised lower incomplete gamma function P(s, x) (series below s + 1, continued fraction above)."""
    if x <= 0.0:
        return 0.0
    if x < s + 1.0:
        term = 1.0 / s
        total = term
        for k in range(1, 10000):
            term *= x / (s + k)
            total += term
            if abs(term) < abs(total) * 1e-16:
                break
        return total * math.exp(-x + s * math.log(x) - math.lgamma(s))
    tiny = 1e-300
    b = x + 1.0 - s
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for k in range(1, 10000):
        an = -k * (k - s)
        b += 2.0
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return 1.0 - math.exp(-x + s * math.log(x) - math.lgamma(s)) * h


@lru_cache(maxsize=None)
def sersic_b(n):
    """The b_n with P(2n, b_n) = 1/2, so that R_e holds half the light."""
    if not SERSIC_MIN <= n <= SERSIC_MAX:
        raise ValueError("the Sérsic index is in [0.5, 10]")
    lo, hi = 0.0, 4.0 * n + 10.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if gamma_p(2.0 * n, mid) < 0.5:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def sersic_profile(i_e, r_e, n, r):
    """The Sérsic surface brightness I_e exp(-b_n ((r/R_e)^(1/n) - 1))."""
    if r_e <= 0.0:
        raise ValueError("the effective radius must be positive")
    return i_e * math.exp(-sersic_b(n) * ((r / r_e) ** (1.0 / n) - 1.0))


def sersic_enclosed(n, r_e, r):
    """The fraction of the Sérsic light within r: P(2n, b_n (r/R_e)^(1/n))."""
    if r_e <= 0.0:
        raise ValueError("the effective radius must be positive")
    if r <= 0.0:
        return 0.0
    return gamma_p(2.0 * n, sersic_b(n) * (r / r_e) ** (1.0 / n))


# --- rules 3 to 5: the samplers ------------------------------------------------------------------------------


def _invert(cdf, u, lo, hi):
    """The r in [lo, hi] with cdf(r) = u by bisection (cdf rising); the bound when u lies beyond it."""
    if not 0.0 <= u < 1.0:
        raise ValueError("u is in [0, 1)")
    if cdf(hi) <= u:
        return hi
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if cdf(mid) < u:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-13 * max(1.0, hi):
            break
    return 0.5 * (lo + hi)


def sample_disk_radius(u, h):
    """The disk radius of the uniform draw u, by inverting the enclosed fraction."""
    if u == 0.0:
        return 0.0
    return _invert(lambda r: exponential_enclosed(h, r), u, 0.0, RADIUS_CUT * h)


def sample_bulge_radius(u, r_e, n):
    """The bulge radius of the uniform draw u, by inverting the Sérsic enclosed fraction."""
    if u == 0.0:
        return 0.0
    return _invert(lambda r: sersic_enclosed(n, r_e, r), u, 0.0, BULGE_CUT * r_e)


def sech2(z, z0):
    """The vertical profile sech^2(z / z0)."""
    return 1.0 / math.cosh(z / z0) ** 2


def sample_height(u, z0):
    """The height of the uniform draw u under sech^2: z0 atanh(2u - 1)."""
    if not 0.0 < u < 1.0:
        raise ValueError("u is in (0, 1)")
    return z0 * math.atanh(2.0 * u - 1.0)


def arm_phase(r, r0, pitch):
    """The azimuth of the logarithmic spiral's ridge at radius r: ln(r / r0) / tan(pitch)."""
    if r <= 0.0 or r0 <= 0.0:
        raise ValueError("radii are positive")
    return math.log(r / r0) / math.tan(pitch)


def _arms(arms):
    m, a = arms["count"], arms["amplitude"]
    if not (isinstance(m, int) and 1 <= m <= MAX_ARMS):
        raise ValueError("arms/@count is in 1..MAX_ARMS")
    if not 0.0 <= a <= 1.0:
        raise ValueError("arms/@amplitude is in [0, 1]")
    return m, a


def arm_density(r, theta, arms):
    """The azimuthal modulation 1 + A cos(m (theta - phase(r))) of the disk's density."""
    m, a = _arms(arms)
    return 1.0 + a * math.cos(m * (theta - arm_phase(r, arms["radius"], arms["pitch"])))


def azimuth_cdf(theta, r, arms):
    """The fraction of the ring at r with azimuth below theta under the arm modulation."""
    m, a = _arms(arms)
    phi = arm_phase(r, arms["radius"], arms["pitch"])
    return (theta + (a / m) * (math.sin(m * (theta - phi)) + math.sin(m * phi))) / (2.0 * math.pi)


def sample_azimuth(u, r, arms):
    """The azimuth of the uniform draw u at radius r, by inverting the ring's fraction."""
    if not 0.0 <= u <= 1.0:
        raise ValueError("u is in [0, 1]")
    lo, hi = 0.0, 2.0 * math.pi
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if azimuth_cdf(mid, r, arms) < u:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# --- rule 6: dust lanes --------------------------------------------------------------------------------------


def dust_transmission(r, theta, arms):
    """The transmission exp(-tau exp(-d^2 / 2w^2)) of the dust lane that runs dust_offset inside the arm's
    ridge, d being the azimuthal distance to the nearest lane."""
    m, _ = _arms(arms)
    tau = arms["dust"]
    if tau < 0.0:
        raise ValueError("arms/@dust is not negative")
    if tau == 0.0:
        return 1.0
    period = 2.0 * math.pi / m
    d = theta - (arm_phase(r, arms["radius"], arms["pitch"]) - arms["dust_offset"])
    d = (d + period / 2.0) % period - period / 2.0
    return math.exp(-tau * math.exp(-d * d / (2.0 * arms["dust_width"] ** 2)))


# --- rule 7: colours -----------------------------------------------------------------------------------------


def _gauss(x, mu, s1, s2):
    t = (x - mu) / (s1 if x < mu else s2)
    return math.exp(-0.5 * t * t)


def cie_xyz(wavelength):
    """The CIE 1931 colour matching functions by the multi-lobe fit of Wyman, Sloan and Shirley (2013)."""
    x = (1.056 * _gauss(wavelength, 599.8, 37.9, 31.0) + 0.362 * _gauss(wavelength, 442.0, 16.0, 26.7)
         - 0.065 * _gauss(wavelength, 501.1, 20.4, 26.2))
    y = 0.821 * _gauss(wavelength, 568.8, 46.9, 40.5) + 0.286 * _gauss(wavelength, 530.9, 16.3, 31.1)
    z = 1.217 * _gauss(wavelength, 437.0, 11.8, 36.0) + 0.681 * _gauss(wavelength, 459.0, 26.0, 13.8)
    return (x, y, z)


def xyz_to_rgb(xyz):
    """Linear sRGB (D65) of an XYZ triple, negatives clamped to 0."""
    x, y, z = xyz
    r = 3.2406 * x - 1.5372 * y - 0.4986 * z
    g = -0.9689 * x + 1.8758 * y + 0.0415 * z
    b = 0.0557 * x - 0.2040 * y + 1.0570 * z
    return (max(0.0, r), max(0.0, g), max(0.0, b))


def _normalised(rgb):
    top = max(rgb)
    if top <= 0.0:
        raise ValueError("the colour is black")
    return tuple(c / top for c in rgb)


def wavelength_colour(wavelength):
    """The linear sRGB colour of a monochromatic line, scaled so its largest channel is 1."""
    if not 380.0 <= wavelength <= 780.0:
        raise ValueError("wavelengths are in 380..780 nm")
    return _normalised(xyz_to_rgb(cie_xyz(wavelength)))


def planck(wavelength, temperature):
    """Planck's spectral radiance at wavelength (nm) and temperature (K), up to a constant."""
    lam = wavelength * 1e-9
    return lam ** -5 / math.expm1(1.4387769e-2 / (lam * temperature))


@lru_cache(maxsize=None)
def blackbody_colour(temperature):
    """The linear sRGB colour of a blackbody, scaled so its largest channel is 1 (5 nm steps over 380..780)."""
    if temperature <= 0.0:
        raise ValueError("the temperature is positive")
    xyz = [0.0, 0.0, 0.0]
    for i in range(81):
        lam = 380.0 + 5.0 * i
        p = planck(lam, temperature)
        for k, v in enumerate(cie_xyz(lam)):
            xyz[k] += v * p
    return _normalised(xyz_to_rgb(tuple(xyz)))


# --- rule 8: the catalogue -----------------------------------------------------------------------------------


def _shares(disk, bulge):
    total = disk["share"] + bulge["share"]
    if disk["share"] < 0.0 or bulge["share"] < 0.0 or total > 1.0 + 1e-12 or total <= 0.0:
        raise ValueError("the shares are not negative and sum to at most 1")
    return total


def star(e, i, disk, bulge, arms):
    """Star i of the galaxy of element seed e: its position, component, colour and brightness."""
    total = _shares(disk, bulge)
    draw = lambda p: S(e, p, 0, i)
    u_colour = draw(P_COLOUR)
    u_bright = draw(P_BRIGHTNESS)
    if draw(P_COMPONENT) * total < bulge["share"]:
        r = sample_bulge_radius(draw(P_RADIUS), bulge["effective_radius"], bulge["sersic_index"])
        cos_t = 2.0 * draw(P_HEIGHT) - 1.0
        sin_t = math.sqrt(max(0.0, 1.0 - cos_t * cos_t))
        phi = 2.0 * math.pi * draw(P_ANGLE)
        x, y, z = r * sin_t * math.cos(phi), r * cos_t, r * sin_t * math.sin(phi)
        component, temperature, transmission = "bulge", bulge["temperature"], 1.0
    else:
        r = sample_disk_radius(draw(P_RADIUS), disk["scale_length"])
        theta = sample_azimuth(draw(P_ANGLE), r, arms) if r > 0.0 else 0.0
        x, z = r * math.cos(theta), r * math.sin(theta)
        y = sample_height(draw(P_HEIGHT), disk["scale_height"])
        component, temperature = "disk", disk["temperature"]
        transmission = dust_transmission(r, theta, arms) if r > 0.0 else 1.0
    colour = blackbody_colour(round(temperature * (0.8 + 0.4 * u_colour), 1))
    return {"x": x, "y": y, "z": z, "component": component, "colour": colour,
            "brightness": (0.25 + 1.5 * u_bright ** 3) * transmission}


def galaxy_stars(e, count, disk, bulge, arms):
    """The first count stars of the galaxy, in index order."""
    if not (isinstance(count, int) and 0 <= count <= MAX_STARS):
        raise ValueError("galaxy/@stars is in 0..MAX_STARS")
    _shares(disk, bulge)
    return [star(e, i, disk, bulge, arms) for i in range(count)]


def profile_error(radii, cdf):
    """The largest gap between the sorted radii's empirical fraction and cdf (the Kolmogorov statistic)."""
    n = len(radii)
    return max(max(abs((i + 1) / n - cdf(r)), abs(i / n - cdf(r))) for i, r in enumerate(radii))


# --- rule 9: the rotation curve and the galaxy's bodies ------------------------------------------------------


def rotation_speed(r, disk, bulge, halo, mass):
    """The circular speed at cylindrical radius r: the enclosed disk and bulge mass as if spherical, plus the
    cored isothermal halo v_h^2 r^2 / (r^2 + r_c^2)."""
    if r <= 0.0:
        return 0.0
    enclosed = mass * (disk["share"] * exponential_enclosed(disk["scale_length"], r)
                       + bulge["share"] * sersic_enclosed(bulge["sersic_index"], bulge["effective_radius"], r))
    v2 = enclosed / r + halo["speed"] ** 2 * r * r / (r * r + halo["core_radius"] ** 2)
    return math.sqrt(v2)


def galaxy_bodies(e, count, disk, bulge, arms, halo, mass):
    """The galaxy's stars as N-body particles of equal mass on circular orbits of the rotation curve."""
    if not (isinstance(count, int) and 1 <= count <= MAX_BODIES):
        raise ValueError("dynamics/@bodies is in 1..MAX_BODIES")
    positions, velocities = [], []
    for s in galaxy_stars(e, count, disk, bulge, arms):
        r = math.hypot(s["x"], s["z"])
        v = rotation_speed(r, disk, bulge, halo, mass)
        positions.append((s["x"], s["y"], s["z"]))
        velocities.append((-s["z"] / r * v, 0.0, s["x"] / r * v) if r > 0.0 else (0.0, 0.0, 0.0))
    return {"positions": positions, "velocities": velocities, "masses": [mass / count] * count}


# --- rule 10: the N-body and mergers -------------------------------------------------------------------------


def accelerations(positions, masses, softening, G):
    """Plummer-softened direct-sum accelerations."""
    n = len(positions)
    acc = [(0.0, 0.0, 0.0)] * n
    e2 = softening * softening
    for i in range(n):
        ax = ay = az = 0.0
        xi, yi, zi = positions[i]
        for j in range(n):
            if j == i:
                continue
            dx, dy, dz = positions[j][0] - xi, positions[j][1] - yi, positions[j][2] - zi
            inv = G * masses[j] / (dx * dx + dy * dy + dz * dz + e2) ** 1.5
            ax += dx * inv
            ay += dy * inv
            az += dz * inv
        acc[i] = (ax, ay, az)
    return acc


def energy(positions, velocities, masses, softening, G):
    """Kinetic plus softened potential energy."""
    e2 = softening * softening
    total = sum(0.5 * m * (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) for m, v in zip(masses, velocities))
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            dx, dy, dz = (positions[j][k] - positions[i][k] for k in range(3))
            total -= G * masses[i] * masses[j] / math.sqrt(dx * dx + dy * dy + dz * dz + e2)
    return total


def momentum(velocities, masses):
    return tuple(sum(m * v[k] for m, v in zip(masses, velocities)) for k in range(3))


def nbody_run(positions, velocities, masses, steps, dt, softening, G):
    """steps kick-drift-kick leapfrog steps of dt; the state after step k is a function of k alone."""
    n = len(positions)
    if not (1 <= n <= MAX_BODIES) or len(velocities) != n or len(masses) != n:
        raise ValueError("bodies are in 1..MAX_BODIES with one velocity and mass each")
    if not (isinstance(steps, int) and 0 <= steps <= MAX_STEPS):
        raise ValueError("steps are in 0..MAX_STEPS")
    if not dt > 0.0:
        raise ValueError("dt is positive")
    pos = [tuple(p) for p in positions]
    vel = [tuple(v) for v in velocities]
    acc = accelerations(pos, masses, softening, G)
    for _ in range(steps):
        half = [tuple(v[k] + 0.5 * dt * a[k] for k in range(3)) for v, a in zip(vel, acc)]
        pos = [tuple(p[k] + dt * v[k] for k in range(3)) for p, v in zip(pos, half)]
        acc = accelerations(pos, masses, softening, G)
        vel = [tuple(v[k] + 0.5 * dt * a[k] for k in range(3)) for v, a in zip(half, acc)]
    return {"positions": pos, "velocities": vel, "steps": steps}


def _centred(g):
    """A galaxy's bodies with their centre of mass at the origin and their total momentum zero."""
    total = sum(g["masses"])
    com = tuple(sum(m * p[k] for m, p in zip(g["masses"], g["positions"])) / total for k in range(3))
    mean = tuple(sum(m * v[k] for m, v in zip(g["masses"], g["velocities"])) / total for k in range(3))
    return ([tuple(p[k] - com[k] for k in range(3)) for p in g["positions"]],
            [tuple(v[k] - mean[k] for k in range(3)) for v in g["velocities"]], total)


def merger_bodies(a, b, separation, impact, speed):
    """Two galaxies' bodies, each centred first, placed separation apart along x with the impact offset along
    z and approaching at the relative speed along x, with the centre of mass at rest at the origin."""
    pa, va, ma = _centred(a)
    pb, vb, mb = _centred(b)
    total = ma + mb
    offset_a = (-mb / total * separation, 0.0, -mb / total * impact)
    offset_b = (ma / total * separation, 0.0, ma / total * impact)
    boost_a, boost_b = mb / total * speed, -ma / total * speed
    positions = [tuple(p[k] + offset_a[k] for k in range(3)) for p in pa]
    positions += [tuple(p[k] + offset_b[k] for k in range(3)) for p in pb]
    velocities = [(v[0] + boost_a, v[1], v[2]) for v in va]
    velocities += [(v[0] + boost_b, v[1], v[2]) for v in vb]
    return {"positions": positions, "velocities": velocities, "masses": list(a["masses"]) + list(b["masses"])}


# --- rules 11 and 12: nebulae --------------------------------------------------------------------------------

LINES = {"h-alpha": 656.28, "h-beta": 486.13, "oiii": 500.7, "sii": 672.4, "nii": 658.3}

PALETTES = {
    "sho": {"sii": (1.0, 0.0, 0.0), "h-alpha": (0.0, 1.0, 0.0), "nii": (0.0, 1.0, 0.0),
            "oiii": (0.0, 0.0, 1.0), "h-beta": (0.0, 0.0, 1.0)},
    "hoo": {"sii": (1.0, 0.0, 0.0), "h-alpha": (1.0, 0.0, 0.0), "nii": (1.0, 0.0, 0.0),
            "oiii": (0.0, 1.0, 1.0), "h-beta": (0.0, 1.0, 1.0)},
}


def palette_colour(palette, line):
    """The colour a palette gives a line: its wavelength's colour for natural, the mapped channels otherwise."""
    if line not in LINES:
        raise ValueError(f"unknown emission line {line!r}")
    if palette == "natural":
        return wavelength_colour(LINES[line])
    if palette not in PALETTES:
        raise ValueError(f"unknown palette {palette!r}")
    return PALETTES[palette][line]


def nebula_emission(strengths, palette):
    """The emission colour of a nebula: the sum of each line's strength times its palette colour."""
    if len(strengths) > MAX_LINES:
        raise ValueError("a nebula has at most MAX_LINES lines")
    rgb = [0.0, 0.0, 0.0]
    for line, strength in strengths.items():
        if strength < 0.0:
            raise ValueError("line strengths are not negative")
        colour = palette_colour(palette, line)
        for k in range(3):
            rgb[k] += strength * colour[k]
    return tuple(rgb)


def nebula_sample(density, strengths, palette, extinction, emission_scale):
    """The A2 medium sample of a nebula: extinction sigma and emission at a point of the given density."""
    emission = nebula_emission(strengths, palette)
    return (density * extinction, tuple(density * emission_scale * c for c in emission))


# --- the numeric table ---------------------------------------------------------------------------------------

DISK = {"scale_length": 1.0, "scale_height": 0.1, "share": 0.7, "temperature": 6000.0}
BULGE = {"effective_radius": 0.5, "sersic_index": 4.0, "share": 0.3, "temperature": 4500.0}
ARMS = {"count": 2, "pitch": math.radians(15.0), "amplitude": 0.6, "radius": 0.5, "dust": 1.0, "dust_width": 0.15,
        "dust_offset": 0.25}
HALO = {"speed": 1.0, "core_radius": 0.5}
SEED = E(7, "m51", 3, "stars")


def disk_only():
    return dict(BULGE, share=0.0)


def bulge_only():
    return dict(DISK, share=0.0), dict(BULGE, share=1.0)


def no_arms():
    return dict(ARMS, amplitude=0.0)


def disk_radii(count):
    return sorted(math.hypot(s["x"], s["z"]) for s in galaxy_stars(SEED, count, DISK, disk_only(), no_arms()))


def bulge_radii(count):
    d, b = bulge_only()
    return sorted(math.sqrt(s["x"] ** 2 + s["y"] ** 2 + s["z"] ** 2) for s in galaxy_stars(SEED, count, d, b, ARMS))


def arm_counts(count):
    on = off = 0
    for s in galaxy_stars(SEED, count, DISK, disk_only(), ARMS):
        d = arm_density(math.hypot(s["x"], s["z"]), math.atan2(s["z"], s["x"]) % (2.0 * math.pi), ARMS)
        on += d > 1.3
        off += d < 0.7
    return (on, off)


def two_body(steps):
    v = 0.5 * math.sqrt(2.0)
    period = 2.0 * math.pi / math.sqrt(2.0)
    out = nbody_run([(-0.5, 0.0, 0.0), (0.5, 0.0, 0.0)], [(0.0, 0.0, -v), (0.0, 0.0, v)], [1.0, 1.0], steps,
                    period / steps, 0.0, 1.0)
    return max(abs(out["positions"][0][0] + 0.5), abs(out["positions"][0][2]))


def four_body_drift(steps):
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 2.0), (-1.5, 0.3, 0.0)]
    vel = [(0.0, 0.0, 0.0), (0.0, 0.1, 0.6), (-0.4, 0.0, 0.0), (0.0, -0.1, -0.3)]
    masses = [2.0, 0.5, 0.5, 0.3]
    e0 = energy(pos, vel, masses, 0.1, 1.0)
    out = nbody_run(pos, vel, masses, steps, 0.005, 0.1, 1.0)
    return abs(energy(out["positions"], out["velocities"], masses, 0.1, 1.0) - e0) / abs(e0)


TABLE = (
    ("exponential enclosed", "tuple(round(exponential_enclosed(1.0, x), 6) for x in (1.0, 2.0, 3.0))", "(0.264241, 0.593994, 0.800852)"),
    ("regularised gamma", "(round(gamma_p(1.0, 1.0), 12), round(gamma_p(2.0, 1.0), 12), round(gamma_p(0.5, 2.0), 10))", "(round(1.0 - math.exp(-1.0), 12), round(1.0 - 2.0 * math.exp(-1.0), 12), round(math.erf(math.sqrt(2.0)), 10))"),
    ("sersic b", "tuple(round(sersic_b(n), 6) for n in (0.5, 1.0, 2.0, 4.0, 8.0))", "(0.693147, 1.678347, 3.672061, 7.669249, 15.66793)"),
    ("sersic half light", "tuple(round(sersic_enclosed(n, 2.0, 2.0), 12) for n in (1.0, 2.0, 4.0))", "(0.5, 0.5, 0.5)"),
    ("sersic n = 1 is exponential", "round(abs(sersic_enclosed(1.0, 1.0, 2.5) - exponential_enclosed(1.0 / sersic_b(1.0), 2.5)), 12)", "0.0"),
    ("sersic profile", "(round(sersic_profile(3.0, 2.0, 4.0, 2.0), 12), round(sersic_profile(3.0, 2.0, 4.0, 0.5), 6))", "(3.0, 28.35727)"),
    ("disk radius sampler", "(sample_disk_radius(0.0, 1.0), round(sample_disk_radius(0.5, 1.0), 6), round(exponential_enclosed(1.0, sample_disk_radius(0.5, 1.0)), 12))", "(0.0, 1.678347, 0.5)"),
    ("bulge radius sampler", "(round(sample_bulge_radius(0.5, 0.5, 4.0), 8), round(sersic_enclosed(2.0, 1.0, sample_bulge_radius(0.2, 1.0, 2.0)), 12))", "(0.5, 0.2)"),
    ("height sampler", "(sample_height(0.5, 0.1), round(sample_height(0.9, 0.1), 6), round(sech2(0.0, 0.1), 12))", "(0.0, 0.109861, 1.0)"),
    ("arm phase", "round(arm_phase(1.0, 0.5, math.radians(15.0)), 6)", "round(math.log(2.0) / math.tan(math.radians(15.0)), 6)"),
    ("arm density", "(round(arm_density(1.0, arm_phase(1.0, 0.5, ARMS['pitch']), ARMS), 12), round(arm_density(1.0, arm_phase(1.0, 0.5, ARMS['pitch']) + math.pi / 2.0, ARMS), 12))", "(1.6, 0.4)"),
    ("azimuth sampler", "(round(azimuth_cdf(sample_azimuth(0.25, 1.0, ARMS), 1.0, ARMS), 9), round(sample_azimuth(0.25, 1.0, no_arms()), 9))", "(0.25, round(math.pi / 2.0, 9))"),
    ("dust lane", "(round(dust_transmission(1.0, arm_phase(1.0, 0.5, ARMS['pitch']) - ARMS['dust_offset'], ARMS), 9), round(dust_transmission(1.0, arm_phase(1.0, 0.5, ARMS['pitch']) + math.pi / 2.0, ARMS), 6))", "(round(math.exp(-1.0), 9), 1.0)"),
    ("blackbody colours", "tuple(tuple(round(c, 3) for c in blackbody_colour(t)) for t in (3000.0, 5778.0, 30000.0))", "((1.0, 0.484, 0.154), (1.0, 0.88, 0.823), (0.363, 0.497, 1.0))"),
    ("a star is a function of its index", "(star(SEED, 17, DISK, BULGE, ARMS) == star(SEED, 17, DISK, BULGE, ARMS), star(SEED, 17, DISK, BULGE, ARMS) == star(SEED, 18, DISK, BULGE, ARMS))", "(True, False)"),
    ("the catalogue is stable under the count", "galaxy_stars(SEED, 100, DISK, BULGE, ARMS) == galaxy_stars(SEED, 200, DISK, BULGE, ARMS)[:100]", "True"),
    ("the disk follows the exponential law", "round(profile_error(disk_radii(20000), lambda r: exponential_enclosed(1.0, r)), 6)", "0.007123"),
    ("the bulge follows the sersic law", "round(profile_error(bulge_radii(20000), lambda r: sersic_enclosed(4.0, 0.5, r)), 6)", "0.007123"),
    ("the arms modulate the azimuths", "arm_counts(20000)", "(10003, 3365)"),
    ("rotation curve", "tuple(round(rotation_speed(r, DISK, BULGE, HALO, 1.0), 6) for r in (0.5, 1.0, 5.0, 20.0, 40.0))", "(0.962437, 1.091774, 1.087257, 1.024381, 1.012345)"),
    ("accelerations", "(accelerations([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [1.0, 1.0], 0.0, 1.0)[0], round(accelerations([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [1.0, 1.0], 1.0, 1.0)[0][0], 12))", "((1.0, 0.0, 0.0), round(2.0 ** -1.5, 12))"),
    ("a two body orbit closes", "tuple(round(two_body(n), 6) for n in (500, 2000))", "(0.000165, 1e-05)"),
    ("energy drift of four bodies", "round(four_body_drift(1000), 8)", "3.81e-06"),
    ("momentum is conserved", "tuple(round(c, 12) for c in momentum(nbody_run([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [(0.0, 0.0, 0.0), (0.0, 0.0, 0.7)], [1.0, 1.0], 100, 0.01, 0.1, 1.0)['velocities'], [1.0, 1.0]))", "(0.0, 0.0, 0.7)"),
    ("a run is a function of the step count", "(lambda a, b: nbody_run(a['positions'], a['velocities'], [1.0, 0.5, 0.5], 20, 0.01, 0.1, 1.0)['positions'] == b['positions'])(nbody_run([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 2.0)], [(0.0, 0.0, 0.0), (0.0, 0.1, 0.6), (-0.4, 0.0, 0.0)], [1.0, 0.5, 0.5], 20, 0.01, 0.1, 1.0), nbody_run([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 2.0)], [(0.0, 0.0, 0.0), (0.0, 0.1, 0.6), (-0.4, 0.0, 0.0)], [1.0, 0.5, 0.5], 40, 0.01, 0.1, 1.0))", "True"),
    ("galaxy bodies on the curve", "(lambda g: (len(g['positions']), round(sum(g['masses']), 12), all(abs(math.hypot(v[0], v[2]) - rotation_speed(math.hypot(p[0], p[2]), DISK, disk_only(), HALO, 1.0)) < 1e-9 for p, v in zip(g['positions'], g['velocities']))))(galaxy_bodies(SEED, 50, DISK, disk_only(), no_arms(), HALO, 1.0))", "(50, 1.0, True)"),
    ("a merger is at rest at the origin", "(lambda m: (len(m['positions']), round(sum(mi * p[0] for mi, p in zip(m['masses'], m['positions'])), 9), round(sum(mi * v[0] for mi, v in zip(m['masses'], m['velocities'])), 9)))(merger_bodies(galaxy_bodies(SEED, 30, DISK, disk_only(), no_arms(), HALO, 1.0), galaxy_bodies(SEED + 1, 20, DISK, disk_only(), no_arms(), HALO, 0.5), 10.0, 2.0, 0.3))", "(50, 0.0, 0.0)"),
    ("emission lines", "tuple(LINES[k] for k in ('h-alpha', 'h-beta', 'oiii', 'sii', 'nii'))", "(656.28, 486.13, 500.7, 672.4, 658.3)"),
    ("line colours", "tuple(tuple(round(c, 3) for c in wavelength_colour(LINES[k])) for k in ('h-alpha', 'oiii', 'h-beta'))", "((1.0, 0.0, 0.0), (0.0, 1.0, 0.323), (0.0, 0.536, 1.0))"),
    ("palettes", "(palette_colour('sho', 'sii'), palette_colour('sho', 'h-alpha'), palette_colour('sho', 'oiii'), palette_colour('hoo', 'h-alpha'), palette_colour('hoo', 'oiii'))", "((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0))"),
    ("nebula emission", "(nebula_emission({'h-alpha': 1.0, 'oiii': 0.5}, 'sho'), nebula_emission({}, 'sho'))", "((0.0, 1.0, 0.5), (0.0, 0.0, 0.0))"),
    ("nebula sample", "nebula_sample(0.5, {'h-alpha': 1.0, 'oiii': 0.5}, 'sho', 2.0, 3.0)", "(1.0, (0.0, 1.5, 0.75))"),
    ("bounds", "(MAX_STARS, MAX_BODIES, MAX_STEPS, MAX_ARMS, MAX_LINES, RADIUS_CUT, BULGE_CUT, SERSIC_MIN, SERSIC_MAX)", "(4194304, 4096, 65536, 8, 16, 20.0, 100.0, 0.5, 10.0)"),
)


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["__builtins__"] = {"round": round, "tuple": tuple, "len": len, "sorted": sorted, "min": min, "max": max,
                         "abs": abs, "range": range, "list": list, "set": set, "dict": dict, "True": True,
                         "False": False, "None": None, "any": any, "all": all, "int": int, "float": float,
                         "zip": zip, "sum": sum, "iter": iter, "next": next, "ValueError": ValueError}
    return s


def _same(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    return a == b


def main():
    s = scope()
    for name, expr, expected in TABLE:
        got = eval(expr, s)
        want = eval(expected, s)
        if got != want and not _same(got, want):
            raise SystemExit(f"{name}: {got!r} != {want!r}")
        print(f"| {name} | `{expr}` | `{expected}` |")


if __name__ == "__main__":
    main()
