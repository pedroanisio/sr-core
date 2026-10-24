#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add homogeneous and height media, UsdVol volumes and
null-scattering transport" (srep/srep-0000-volumes.md), A2 of SREP 12.

Standard library only. The rules of the SREP's Semantics section are the functions below, in its order:
homogeneous and height media and their exact optical depths (rules 1 to 3), the UsdVol subset (rule 4), the
draws (rule 5), the majorant and delta and ratio tracking (rules 6 and 7), the phase function and its
sampling (rule 8), the random walk and the white furnace (rule 9), froxels (rule 10) and the bounds (rule
11). `main()` prints the SREP's numeric table; `tests/test_volumes.py` checks both.
"""
import math
import re
import zlib

MAX_DOMAINS = 64          # media in one pass (SREP 40)
MAX_BOUNCES = 32          # medium/@scatterBounces (SREP 79)
MAX_SLICES = 1024         # medium/@froxelSlices
MAX_COLLISIONS = 65536    # null collisions of one ray (medium/@maxSteps)
DRAWS_PER_RAY = 65536     # draws of one purpose for one ray
P_DISTANCE = 0            # purposes of the draws
P_PHASE = 1

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


# --- vectors ----------------------------------------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    if n == 0.0:
        raise ValueError("zero vector has no direction")
    return _mul(a, 1.0 / n)


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# --- rules 1 to 3: homogeneous and height media -----------------------------------------------------------

def homogeneous_density(shape, dims, p):
    """Density 1 inside a box (width, height, depth about the origin) or a sphere (radius), 0 outside."""
    if shape == "box":
        if len(dims) != 3 or not all(_finite(d) and d > 0.0 for d in dims):
            raise ValueError("a box has a positive width, height and depth")
        return 1.0 if all(abs(c) <= d / 2.0 for c, d in zip(p, dims)) else 0.0
    if shape == "sphere":
        if len(dims) != 1 or not (_finite(dims[0]) and dims[0] > 0.0):
            raise ValueError("a sphere has a positive radius")
        return 1.0 if _norm(p) <= dims[0] else 0.0
    raise ValueError("a homogeneous medium is a box or a sphere")


def height_density(p, base, falloff):
    """exp(−max(0, y − base)/falloff): 1 at and below the base, falling with height."""
    if not (_finite(falloff) and falloff > 0.0):
        raise ValueError("the falloff is a positive length")
    return math.exp(-max(0.0, p[1] - base) / falloff)


def height_field(base, falloff):
    """The height medium as a function of a point."""
    height_density((0.0, 0.0, 0.0), base, falloff)
    return lambda p: height_density(p, base, falloff)


def height_optical_depth(a, b, base, falloff, extinction=1.0):
    """The exact optical depth of a height medium along the segment a → b (times the extinction)."""
    height_density(a, base, falloff)
    length = _norm(_sub(b, a))
    if length == 0.0:
        return 0.0
    dy = (b[1] - a[1]) / length
    pieces = [(0.0, length)]
    if dy != 0.0:
        t = (base - a[1]) / dy
        if 0.0 < t < length:
            pieces = [(0.0, t), (t, length)]
    depth = 0.0
    for t0, t1 in pieces:
        ym = a[1] + dy * (t0 + t1) / 2.0
        if ym <= base:
            depth += t1 - t0
        elif dy == 0.0:
            depth += math.exp(-(a[1] - base) / falloff) * (t1 - t0)
        else:
            y0 = a[1] + dy * t0
            y1 = a[1] + dy * t1
            depth += falloff / dy * (math.exp(-(y0 - base) / falloff) - math.exp(-(y1 - base) / falloff))
    return depth * extinction


def march_optical_depth(f, a, b, steps, extinction=1.0):
    """The midpoint-rule optical depth of a density field along a → b in equal steps."""
    if not (isinstance(steps, int) and not isinstance(steps, bool) and 1 <= steps <= MAX_COLLISIONS):
        raise ValueError(f"steps is 1 to {MAX_COLLISIONS}")
    length = _norm(_sub(b, a))
    d = _mul(_sub(b, a), 1.0 / length) if length > 0.0 else (0.0, 0.0, 0.0)
    ds = length / steps
    return sum(f(_add(a, _mul(d, (k + 0.5) * ds))) for k in range(steps)) * ds * extinction


def transmittance(sigma, length):
    """Beer–Lambert: exp(−σ·L)."""
    return math.exp(-sigma * length)


# --- rule 4: the UsdVol subset ----------------------------------------------------------------------------

_DEF = re.compile(r'def\s+(\w+)\s+"([^"]+)"\s*(?:\([^)]*\))?\s*\{')
_REL = re.compile(r'rel\s+field:([A-Za-z0-9_.\-]{1,64})\s*=\s*<([^>]+)>')
_ASSET = re.compile(r'asset\s+filePath\s*=\s*@([^@]+)@')
_FIELD = re.compile(r'token\s+fieldName\s*=\s*"([^"]+)"')
_INDEX = re.compile(r'int\s+fieldIndex\s*=\s*(\d+)')
_DEFAULT = re.compile(r'defaultPrim\s*=\s*"([^"]+)"')


def _block_end(text, start):
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced braces in the usda text")


def _prims(text, parent, out):
    pos = 0
    while True:
        m = _DEF.search(text, pos)
        if not m:
            return
        start = m.end() - 1
        end = _block_end(text, start)
        body = text[start + 1:end]
        path = f"{parent}/{m.group(2)}"
        children = []
        own = body
        cpos = 0
        while True:
            c = _DEF.search(body, cpos)
            if not c:
                break
            cend = _block_end(body, c.end() - 1)
            children.append(body[c.start():cend + 1])
            cpos = cend + 1
        for child in children:
            own = own.replace(child, "")
        out[path] = (m.group(1), own)
        _prims(body, path, out)
        pos = end + 1


def usdvol_fields(text, prim=None):
    """The channels of a UsdVol Volume prim: {channel: (file path, grid name, field index)}.

    The subset read: `def Volume` prims with `rel field:<channel> = <path>` relationships to
    `def OpenVDBAsset` prims holding `asset filePath`, `token fieldName` and an optional `int fieldIndex`;
    `prim` picks the Volume by path, else the layer's defaultPrim when it is a Volume, else the first Volume.
    """
    if not text.startswith("#usda"):
        raise ValueError("not a usda text layer")
    prims = {}
    _prims(text, "", prims)
    volumes = [p for p, (t, _) in prims.items() if t == "Volume"]
    if prim is None:
        header_end = text.find("def ")
        d = _DEFAULT.search(text[:header_end] if header_end >= 0 else text)
        prim = f"/{d.group(1)}" if d and f"/{d.group(1)}" in volumes else (volumes[0] if volumes else None)
    if prim not in prims or prims[prim][0] != "Volume":
        raise ValueError(f"no Volume prim at {prim!r}")
    fields = {}
    for channel, target in _REL.findall(prims[prim][1]):
        if target not in prims:
            raise ValueError(f"field:{channel} names a missing prim {target}")
        kind, body = prims[target]
        if kind != "OpenVDBAsset":
            raise ValueError(f"field:{channel} names a {kind}; only OpenVDBAsset is read")
        a = _ASSET.search(body)
        n = _FIELD.search(body)
        if not a or not n:
            raise ValueError(f"{target} needs filePath and fieldName")
        i = _INDEX.search(body)
        fields[channel] = (a.group(1), n.group(1), int(i.group(1)) if i else 0)
    if not fields:
        raise ValueError(f"{prim} has no field relationships")
    return fields


# --- rule 5: the draws ------------------------------------------------------------------------------------

def draws(element_seed, purpose, pixel, sample):
    """The ray's draws of one purpose: S(e, purpose, sample, pixel·DRAWS_PER_RAY + i), i counting from 0."""
    if not (isinstance(pixel, int) and pixel >= 0 and isinstance(sample, int) and sample >= 0):
        raise ValueError("pixel and sample are nonnegative integers")
    state = {"i": 0}

    def u():
        i = state["i"]
        if i >= DRAWS_PER_RAY:
            raise ValueError(f"a ray draws at most {DRAWS_PER_RAY} times per purpose")
        state["i"] = i + 1
        return S(element_seed, purpose, sample, pixel * DRAWS_PER_RAY + i)

    return u


# --- rules 6 and 7: the majorant, delta and ratio tracking --------------------------------------------------

def majorant(densities, density_scale, extinction):
    """The majorant extinction of a domain: its largest density times densityScale and extinction."""
    if any(not _finite(d) or d < 0.0 for d in densities):
        raise ValueError("densities are finite and nonnegative")
    return max(densities, default=0.0) * density_scale * extinction


def _sigma(f, p, extinction, density_scale, sigma_bar):
    sigma = f(p) * density_scale * extinction
    if not _finite(sigma) or sigma < 0.0:
        raise ValueError("the extinction is finite and nonnegative")
    if sigma > sigma_bar * (1.0 + 1e-12):
        raise ValueError("the extinction exceeds the majorant")
    return min(sigma, sigma_bar)


def delta_tracking(f, origin, direction, t0, t1, sigma_bar, u, extinction=1.0, density_scale=1.0,
                   max_collisions=MAX_COLLISIONS):
    """The first real collision along the ray in [t0, t1): (its distance or None, the null collisions).

    Tentative collisions are −ln(1 − u)/σ̄ apart; one is real with probability σ(x)/σ̄ (a second draw).
    """
    if not (_finite(sigma_bar) and sigma_bar > 0.0):
        raise ValueError("the majorant is positive")
    if not (1 <= max_collisions <= MAX_COLLISIONS):
        raise ValueError(f"max_collisions is 1 to {MAX_COLLISIONS}")
    t = t0
    nulls = 0
    while True:
        t += -math.log(1.0 - u()) / sigma_bar
        if t >= t1:
            return (None, nulls)
        p = _add(origin, _mul(direction, t))
        sigma = _sigma(f, p, extinction, density_scale, sigma_bar)
        if u() < sigma / sigma_bar:
            return (t, nulls)
        nulls += 1
        if nulls > max_collisions:
            raise ValueError(f"more than {max_collisions} null collisions on one ray")


def ratio_tracking(f, origin, direction, t0, t1, sigma_bar, u, extinction=1.0, density_scale=1.0,
                   max_collisions=MAX_COLLISIONS):
    """An unbiased transmittance estimate: the product of 1 − σ(x)/σ̄ over the tentative collisions."""
    if not (_finite(sigma_bar) and sigma_bar > 0.0):
        raise ValueError("the majorant is positive")
    if not (1 <= max_collisions <= MAX_COLLISIONS):
        raise ValueError(f"max_collisions is 1 to {MAX_COLLISIONS}")
    t = t0
    weight = 1.0
    collisions = 0
    while True:
        t += -math.log(1.0 - u()) / sigma_bar
        if t >= t1:
            return weight
        p = _add(origin, _mul(direction, t))
        weight *= 1.0 - _sigma(f, p, extinction, density_scale, sigma_bar) / sigma_bar
        if weight == 0.0:
            return 0.0
        collisions += 1
        if collisions > max_collisions:
            raise ValueError(f"more than {max_collisions} collisions on one ray")


# --- rule 8: the phase function ---------------------------------------------------------------------------

def phase_hg(cos_theta, g):
    """Henyey–Greenstein, normalised over the sphere; g > 0 peaks forward."""
    if not (_finite(g) and -1.0 < g < 1.0):
        raise ValueError("the anisotropy is in (-1, 1)")
    d = 1.0 + g * g - 2.0 * g * max(-1.0, min(1.0, cos_theta))
    return (1.0 - g * g) / (4.0 * math.pi * d ** 1.5)


def sample_hg(g, u1, u2):
    """(cos θ, φ) of a direction drawn from the phase function with two unit draws."""
    phase_hg(1.0, g)
    if abs(g) < 1e-3:
        cos = 1.0 - 2.0 * u1
    else:
        s = (1.0 - g * g) / (1.0 - g + 2.0 * g * u1)
        cos = (1.0 + g * g - s * s) / (2.0 * g)
    return (max(-1.0, min(1.0, cos)), 2.0 * math.pi * u2)


def scatter_direction(d, g, u1, u2):
    """The unit direction at the sampled angle about d."""
    d = _unit(d)
    cos, phi = sample_hg(g, u1, u2)
    sin = math.sqrt(max(0.0, 1.0 - cos * cos))
    helper = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    t1 = _unit((d[1] * helper[2] - d[2] * helper[1], d[2] * helper[0] - d[0] * helper[2],
                d[0] * helper[1] - d[1] * helper[0]))
    t2 = (d[1] * t1[2] - d[2] * t1[1], d[2] * t1[0] - d[0] * t1[2], d[0] * t1[1] - d[1] * t1[0])
    out = _add(_add(_mul(t1, sin * math.cos(phi)), _mul(t2, sin * math.sin(phi))), _mul(d, cos))
    return _unit(out)


# --- rule 9: the walk and the white furnace ----------------------------------------------------------------

def _sphere_exit(p, d, radius):
    b = _dot(p, d)
    c = _dot(p, p) - radius * radius
    disc = b * b - c
    if disc < 0.0:
        return 0.0
    return max(0.0, -b + math.sqrt(disc))


def furnace_walk(f, radius, sigma_bar, albedo, g, seed, pixel, max_bounces, extinction=1.0, density_scale=1.0,
                 sample=0):
    """One path through a spherical medium inside a white furnace of radiance 1.

    The path starts at the centre heading +z, collides by delta tracking, scatters by the phase function and
    multiplies its throughput by the albedo at each collision; it escapes with radiance = throughput, or is
    cut at max_bounces with radiance 0. Returns {"throughput", "bounces", "escaped", "radiance"}.
    """
    if not (isinstance(max_bounces, int) and 0 <= max_bounces <= MAX_BOUNCES):
        raise ValueError(f"max_bounces is 0 to {MAX_BOUNCES}")
    if not (_finite(albedo) and 0.0 <= albedo <= 1.0):
        raise ValueError("the albedo is in [0, 1]")
    u_dist = draws(seed, P_DISTANCE, pixel, sample)
    u_phase = draws(seed, P_PHASE, pixel, sample)
    p = (0.0, 0.0, 0.0)
    d = (0.0, 0.0, 1.0)
    throughput = 1.0
    bounces = 0
    while True:
        exit_t = _sphere_exit(p, d, radius)
        t, _ = delta_tracking(f, p, d, 0.0, exit_t, sigma_bar, u_dist, extinction, density_scale)
        if t is None:
            return {"throughput": throughput, "bounces": bounces, "escaped": True, "radiance": throughput}
        bounces += 1
        if bounces > max_bounces:
            return {"throughput": throughput, "bounces": bounces - 1, "escaped": False, "radiance": 0.0}
        throughput *= albedo
        p = _add(p, _mul(d, t))
        d = scatter_direction(d, g, u_phase(), u_phase())


def furnace_mean(f, radius, sigma_bar, albedo, g, seed, pixels, max_bounces):
    """The mean radiance of `pixels` furnace walks."""
    return sum(furnace_walk(f, radius, sigma_bar, albedo, g, seed, p, max_bounces)["radiance"]
               for p in range(pixels)) / pixels


# --- rule 10: froxels ------------------------------------------------------------------------------------

def froxel_depths(n, near, far):
    """The n + 1 slice depths near·(far/near)^(k/n), exponential in depth."""
    if not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= MAX_SLICES):
        raise ValueError(f"the slice count is 1 to {MAX_SLICES}")
    if not (_finite(near) and _finite(far) and 0.0 < near < far):
        raise ValueError("0 < near < far")
    return tuple(near * (far / near) ** (k / n) for k in range(n + 1))


def froxel_index(depth, n, near, far):
    """The slice holding a depth, clamped to the first and last."""
    froxel_depths(n, near, far)
    k = math.floor(n * math.log(depth / near) / math.log(far / near)) if depth > near else 0
    return max(0, min(n - 1, k))


def froxel_integrate(slices):
    """Front-to-back integration of (σ, source rgb, length) slices: (radiance rgb, transmittance).

    Each slice adds T·(1 − e^(−σΔ))/σ times its source (Δ when σ is 0) and multiplies T by e^(−σΔ).
    """
    radiance = [0.0, 0.0, 0.0]
    t = 1.0
    for sigma, source, length in slices:
        if not (_finite(sigma) and sigma >= 0.0 and _finite(length) and length >= 0.0):
            raise ValueError("a slice has a nonnegative extinction and length")
        weight = t * (length if sigma == 0.0 else -math.expm1(-sigma * length) / sigma)
        for c in range(3):
            radiance[c] += weight * source[c]
        t *= math.exp(-sigma * length)
    return (tuple(radiance), t)


def froxel_transmittance(f, origin, direction, n, near, far, extinction=1.0, density_scale=1.0):
    """The transmittance from near to far along a ray through n froxel slices sampled at their midpoints."""
    depths = froxel_depths(n, near, far)
    d = _unit(direction)
    slices = []
    for z0, z1 in zip(depths, depths[1:]):
        p = _add(origin, _mul(d, (z0 + z1) / 2.0))
        slices.append((f(p) * density_scale * extinction, (0.0, 0.0, 0.0), z1 - z0))
    return froxel_integrate(slices)[1]


# --- the table ---------------------------------------------------------------------------------------------

def const(value):
    return lambda p: value


SEED = E(7, "fog", 3, "transport")


def ratio_mean(sigma, length, sigma_bar, pixels, sample=0):
    """The mean of `pixels` ratio-tracking estimates on a homogeneous medium."""
    return sum(ratio_tracking(const(sigma), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, length, sigma_bar,
                              draws(SEED, P_DISTANCE, p, sample)) for p in range(pixels)) / pixels


def height_ratio_mean(pixels, sample=1):
    """The mean ratio-tracking transmittance of the unit height medium along (0.8, 0.6, 0) for 5 units."""
    f = height_field(0.0, 1.0)
    return sum(ratio_tracking(f, (0.0, 0.0, 0.0), (0.8, 0.6, 0.0), 0.0, 5.0, 1.0, draws(SEED, P_DISTANCE, p, sample))
               for p in range(pixels)) / pixels


TABLE = (
    ("box density", "(homogeneous_density('box', (2.0, 4.0, 6.0), (0.9, -1.9, 2.9)), homogeneous_density('box', (2.0, 4.0, 6.0), (1.1, 0.0, 0.0)))", "(1.0, 0.0)"),
    ("sphere density", "(homogeneous_density('sphere', (1.5,), (0.0, 1.4, 0.0)), homogeneous_density('sphere', (1.5,), (0.0, 1.6, 0.0)))", "(1.0, 0.0)"),
    ("height density", "(height_density((0.0, 0.0, 0.0), 0.0, 1.0), round(height_density((0.0, 1.0, 0.0), 0.0, 1.0), 12), height_density((0.0, -5.0, 0.0), 0.0, 1.0))", "(1.0, round(math.exp(-1.0), 12), 1.0)"),
    ("height depth, vertical", "round(height_optical_depth((0.0, 0.0, 0.0), (0.0, 2.0, 0.0), 0.0, 1.0), 12)", "round(1.0 - math.exp(-2.0), 12)"),
    ("height depth, horizontal", "round(height_optical_depth((0.0, 1.0, 0.0), (3.0, 1.0, 0.0), 0.0, 1.0), 12)", "round(3.0 * math.exp(-1.0), 12)"),
    ("height depth, below the base", "height_optical_depth((0.0, -2.0, 0.0), (0.0, -1.0, 0.0), 0.0, 1.0)", "1.0"),
    ("height depth, across the base", "round(height_optical_depth((0.0, -1.0, 0.0), (0.0, 1.0, 0.0), 0.0, 1.0), 12)", "round(2.0 - math.exp(-1.0), 12)"),
    ("height depth, downward", "round(height_optical_depth((0.0, 2.0, 0.0), (0.0, 0.0, 0.0), 0.0, 1.0), 12)", "round(1.0 - math.exp(-2.0), 12)"),
    ("height depth, extinction", "round(height_optical_depth((0.0, 0.0, 0.0), (0.0, 2.0, 0.0), 0.0, 1.0, extinction=3.0), 12)", "round(3.0 * (1.0 - math.exp(-2.0)), 12)"),
    ("the march converges", "tuple(round(abs(march_optical_depth(height_field(0.0, 1.0), (0.0, 0.0, 0.0), (4.0, 3.0, 0.0), n) - height_optical_depth((0.0, 0.0, 0.0), (4.0, 3.0, 0.0), 0.0, 1.0)), 6) for n in (4, 8, 16))", "(0.036518, 0.009242, 0.002317)"),
    ("beer lambert", "round(transmittance(0.5, 2.0), 12)", "round(math.exp(-1.0), 12)"),
    ("usdvol default prim", "usdvol_fields('#usda 1.0\\n(\\n defaultPrim = \"smoke\"\\n)\\ndef Volume \"smoke\" {\\n rel field:density = </smoke/density>\\n def OpenVDBAsset \"density\" {\\n asset filePath = @./smoke.vdb@\\n token fieldName = \"density\"\\n int fieldIndex = 0\\n }\\n}\\n')", "{'density': ('./smoke.vdb', 'density', 0)}"),
    ("usdvol index defaults to 0", "usdvol_fields('#usda 1.0\\ndef Volume \"fog\" {\\n rel field:density = </fog/d>\\n def OpenVDBAsset \"d\" {\\n asset filePath = @fog.vdb@\\n token fieldName = \"density\"\\n }\\n}\\n', prim='/fog')", "{'density': ('fog.vdb', 'density', 0)}"),
    ("draws are a stream", "(draws(SEED, P_DISTANCE, 5, 2)() == S(SEED, P_DISTANCE, 2, 5 * DRAWS_PER_RAY), draws(SEED, P_DISTANCE, 5, 2)() == draws(SEED, P_DISTANCE, 5, 2)())", "(True, True)"),
    ("majorant", "majorant((0.0, 0.5, 2.0), density_scale=3.0, extinction=0.5)", "3.0"),
    ("delta tracking, free path", "(lambda it: tuple(round(v, 12) if v is not None else None for v in (delta_tracking(const(1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 10.0, 2.0, lambda: next(it), extinction=2.0)[0],)))(iter((0.5, 0.0)))", "(round(math.log(2.0) / 2.0, 12),)"),
    ("delta tracking, escape", "(lambda it: delta_tracking(const(1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 0.1, 2.0, lambda: next(it), extinction=2.0))(iter((0.5,)))", "(None, 0)"),
    ("delta tracking, null collision", "(lambda it: (lambda r: (round(r[0], 12), r[1]))(delta_tracking(const(0.5), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 10.0, 1.0, lambda: next(it))))(iter((0.5, 0.9, 0.5, 0.1)))", "(round(2.0 * math.log(2.0), 12), 1)"),
    ("ratio tracking, one collision", "(ratio_tracking(const(0.7), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 2.0, 0.7, lambda: 0.5), ratio_tracking(const(0.7), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 0.01, 0.7, lambda: 0.5))", "(0.0, 1.0)"),
    ("ratio tracking is unbiased", "tuple(round(ratio_mean(0.7, 2.0, sb, 400), 6) for sb in (0.7, 1.4))", "(0.2525, 0.231133)"),
    ("ratio tracking, exact value", "round(math.exp(-1.4), 6)", "0.246597"),
    ("ratio tracking, height medium", "(round(height_ratio_mean(400), 6), round(math.exp(-height_optical_depth((0.0, 0.0, 0.0), (4.0, 3.0, 0.0), 0.0, 1.0)), 6))", "(0.219881, 0.205217)"),
    ("phase normalises", "round(2.0 * math.pi * sum(phase_hg(-1.0 + (i + 0.5) * 2.0 / 2000, 0.5) * 2.0 / 2000 for i in range(2000)), 4)", "1.0"),
    ("phase isotropic", "round(phase_hg(0.3, 0.0), 12)", "round(1.0 / (4.0 * math.pi), 12)"),
    ("phase sampling, isotropic", "(round(sample_hg(0.0, 0.25, 0.0)[0], 12), round(sample_hg(0.0, 0.75, 0.5)[1], 12))", "(0.5, round(math.pi, 12))"),
    ("phase sampling, forward", "sample_hg(0.9, 0.5, 0.0)[0] > 0.9", "True"),
    ("scattered direction", "round(sum(a * b for a, b in zip((0.0, 0.0, 1.0), scatter_direction((0.0, 0.0, 1.0), 0.6, 0.1, 0.2))), 12)", "round(sample_hg(0.6, 0.1, 0.2)[0], 12)"),
    ("furnace keeps energy", "all(furnace_walk(const(1.0), 1.0, 1.0, albedo=1.0, g=0.0, seed=SEED, pixel=p, max_bounces=32)['throughput'] == 1.0 for p in range(50))", "True"),
    ("furnace loses energy by albedo", "(lambda r: r['throughput'] == 0.5 ** r['bounces'])(furnace_walk(const(1.0), 1.0, 1.0, albedo=0.5, g=0.0, seed=SEED, pixel=1, max_bounces=32))", "True"),
    ("furnace mean", "round(furnace_mean(const(1.0), 1.0, 1.0, 1.0, 0.0, SEED, 300, 32), 6)", "1.0"),
    ("froxel depths", "tuple(round(z, 12) for z in froxel_depths(3, 1.0, 8.0))", "(1.0, 2.0, 4.0, 8.0)"),
    ("froxel index", "(froxel_index(2.9, 3, 1.0, 8.0), froxel_index(1.0, 3, 1.0, 8.0), froxel_index(8.0, 3, 1.0, 8.0))", "(1, 0, 2)"),
    ("froxel slice is exact", "(lambda r: (round(r[0][0], 12), round(r[1], 12)))(froxel_integrate(((1.0, (1.0, 1.0, 1.0), 1.0),)))", "(round(1.0 - math.exp(-1.0), 12), round(math.exp(-1.0), 12))"),
    ("froxel emission without extinction", "froxel_integrate(((0.0, (2.0, 0.0, 0.0), 3.0),))", "((6.0, 0.0, 0.0), 1.0)"),
    ("froxels compose", "round(froxel_integrate(((1.0, (1.0, 1.0, 1.0), 1.0), (1.0, (1.0, 1.0, 1.0), 1.0)))[0][0] - froxel_integrate(((1.0, (1.0, 1.0, 1.0), 2.0),))[0][0], 12)", "0.0"),
    ("froxels converge", "tuple(round(abs(froxel_transmittance(height_field(0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), n, 0.5, 4.0) - math.exp(-height_optical_depth((0.0, 0.5, 0.0), (0.0, 4.0, 0.0), 0.0, 1.0))), 6) for n in (8, 32, 128))", "(0.002335, 0.000146, 9e-06)"),
    ("raster against the path tracer", "abs(froxel_transmittance(height_field(0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 256, 0.5, 4.0) - sum(ratio_tracking(height_field(0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 0.5, 4.0, 1.0, draws(SEED, P_DISTANCE, p, 2)) for p in range(400)) / 400) < 0.03", "True"),
    ("bounds", "(MAX_DOMAINS, MAX_BOUNCES, MAX_SLICES, MAX_COLLISIONS)", "(64, 32, 1024, 65536)"),
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
