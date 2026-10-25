"""Reference for the draft SREP "Add pattern systems to the scene" (G2 of SREP 12).

Five 2D pattern nodes beside the engine's `flock` and `slime`, each a simulation box stepped at `rate` steps per
second from an initial state that the random streams fix: `reaction` (Gray-Scott reaction-diffusion, Pearson
1993), `lenia` (Chan 2019, with the Orbium glider), `automaton` (Life-like cellular automata on a torus, Golly
RLE patterns), `aggregation` (diffusion-limited aggregation, Witten and Sander 1981, lattice walkers whose steps
are stream draws) and `growth` (differential growth of a closed curve). The state at time t is the state after
min(maxSteps, prewarm + floor(t * rate)) steps, so every frame renders alone (SREP 14). Requires numpy.
`python patterns_reference.py` prints the numeric table of the draft's conformance section.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

INIT_PURPOSE = 1            # S(e, 1, 0, row * nx + col): the initial noise of a cell
WALK_PURPOSE = 2            # S(e, 2, k, 2 i): the launch angle (i = 0) and the steps of walker k; 2 i + 1 its stick test
JITTER_PURPOSE = 3          # S(e, 3, step, 2 node + c): the jitter of a curve node; 2 n + j: the j-th insertion's edge
MIN_RESOLUTION = 8
MAX_RESOLUTION = 2048
MAX_PARTICLES = 1000000
MAX_LAUNCHES = 100          # walkers launched per particle before the aggregate stops
LAPLACIAN_SIDE = 0.2        # the nine-point Laplacian's weights: sides, corners, centre -1
LAPLACIAN_CORNER = 0.05
FIELD_THRESHOLD = 0.1       # a cell counts as patterned when V exceeds it
COMPACTNESS = 0.35          # 4 pi A / P^2 above which the components are spots
DIGEST_DECIMALS = 3
KINDS = ("reaction", "lenia", "automaton", "aggregation", "growth")
CREATURES = ("orbium", "noise")
COMMON_DEFAULTS = {"resolution": 128, "rate": 30.0, "prewarm": 0, "maxSteps": 100000, "seed": None,
                   "saturation": 1.0, "color": "#FFD27AFF", "colorLow": "#00000000", "blend": "normal"}
REACTION_DEFAULTS = {"feed": 0.055, "kill": 0.062, "diffuseU": 1.0, "diffuseV": 0.5, "spot": 0.1, "noise": 0.01}
LENIA_DEFAULTS = {"R": 13, "T": 10, "mu": 0.15, "sigma": 0.015, "beta": (1.0,), "creature": "orbium"}
AUTOMATON_DEFAULTS = {"rule": "B3/S23", "pattern": None, "density": 0.0, "x": None, "y": None}
AGGREGATION_DEFAULTS = {"particles": 2000, "stick": 1.0, "launch": 5.0}
GROWTH_DEFAULTS = {"nodes": 24, "radius": 5.0, "maxEdge": 1.5, "repulsion": 3.0, "attraction": 0.5,
                   "alignment": 0.25, "repel": 0.75, "jitter": 0.05, "speed": 0.3, "insert": 1, "maxNodes": 5000}
ORBIUM_PARAMS = {"R": 13, "T": 10, "mu": 0.15, "sigma": 0.015, "beta": (1.0,)}
# Orbium unicaudatus, from Bert Chan's Lenia catalogue (animals.json, MIT licence, (c) 2018 Bert Chan), in the
# catalogue's run-length encoding decoded by decode_cells below: 20 x 20 cells, values 0..255 scaled to [0, 1].
ORBIUM_CELLS = ("7.MD6.qL$6.pKqEqFURpApBRAqQ$5.VqTrSsBrOpXpWpTpWpUpCrQ$4.CQrQsTsWsApITNPpGqGvL$3.IpIpWrOsGsBqXpJ4."
                "LsFrL$A.DpKpSpJpDqOqUqSqE5.ExD$qL.pBpTT2.qCrGrVrWqM5.sTpP$.pGpWpD3.qUsMtItQtJ6.tL$.uFqGH3."
                "pXtOuR2vFsK5.sM$.tUqL4.GuNwAwVxBwNpC4.qXpA$2.uH5.vBxGyEyMyHtW4.qIpL$2.wV5.tIyG3yOxQqW2.FqHpJ$2."
                "tUS4.rM2yOyJyOyHtVpPMpFqNV$2.HsR4.pUxAyOxLxDxEuVrMqBqGqKJ$3.sLpE3.pEuNxHwRwGvUuLsHrCqTpR$3."
                "TrMS2.pFsLvDvPvEuPtNsGrGqIP$4.pRqRpNpFpTrNtGtVtStGsMrNqNpF$5.pMqKqLqRrIsCsLsIrTrFqJpHE$6."
                "RpSqJqPqVqWqRqKpRXE$8.OpBpIpJpFTK!")
ORBIUM_MASS = 19600 / 255


class PatternError(ValueError):
    """A pattern element outside the draft's rules or bounds."""


# ------------------------------------------------------------------------------------------------- the references

_modules = {}


def _load(name):
    if name not in _modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _modules[name] = mod
    return _modules[name]


def streams():
    return _load("random_streams_reference")


def _project_seed(doc):
    project = doc.get("project", 0)
    if isinstance(project, dict):
        return project.get("seed", 0)
    return project


def _get(spec, key, defaults):
    v = spec.get(key)
    return defaults[key] if v is None else v


def digest(obj):
    """sha256 of the object as JSON with sorted keys and floats rounded to three decimals."""
    def rnd(v):
        if isinstance(v, float):
            return round(v, DIGEST_DECIMALS)
        if isinstance(v, dict):
            return {k: rnd(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [rnd(x) for x in v]
        return v
    text = json.dumps(rnd(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------- the common frame


def grid(spec):
    """(nx, ny): `resolution` cells along the longer side of the box, the other side in proportion (as `slime`)."""
    w, h = float(spec["width"]), float(spec["height"])
    res = int(_get(spec, "resolution", COMMON_DEFAULTS))
    if w >= h:
        return res, max(1, int(round(res * h / w)))
    return max(1, int(round(res * w / h))), res


def steps_at(spec, t):
    """The step count of a frame at time t: min(maxSteps, prewarm + floor(t * rate)); the frame owns the bound."""
    rate = float(_get(spec, "rate", COMMON_DEFAULTS))
    prewarm = int(_get(spec, "prewarm", COMMON_DEFAULTS))
    bound = int(_get(spec, "maxSteps", COMMON_DEFAULTS))
    return min(bound, prewarm + max(0, math.floor(t * rate + 1e-9)))


def element_seed(doc, spec):
    """E(project, id, seed, "stream"), the element seed every simulation of the streams draft uses."""
    return streams().E(_project_seed(doc), spec["id"], spec.get("seed"), "stream")


def noise_field(e, nx, ny):
    """The initial noise: cell (row, col) is S(e, 1, 0, row * nx + col) in [0, 1); shape (ny, nx)."""
    S = streams().S
    out = np.empty((ny, nx))
    for row in range(ny):
        base = row * nx
        for col in range(nx):
            out[row, col] = S(e, INIT_PURPOSE, 0, base + col)
    return out


def _hex(color):
    m = re.fullmatch(r"#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?", str(color))
    if not m:
        raise PatternError(f"a literal colour #RRGGBB or #RRGGBBAA is required: {color!r}")
    rgb = m.group(1)
    a = m.group(2) or "FF"
    return tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4)) + (int(a, 16),)


def ramp(spec, x):
    """The two-colour ramp: colorLow at 0, color at 1 (the field divided by `saturation`), clamped; (r, g, b, a)."""
    lo = _hex(_get(spec, "colorLow", COMMON_DEFAULTS))
    hi = _hex(_get(spec, "color", COMMON_DEFAULTS))
    f = min(1.0, max(0.0, float(x)))
    return tuple(int(round(lo[i] + (hi[i] - lo[i]) * f)) for i in range(4))


# ------------------------------------------------------------------------------------------------- Gray-Scott


def laplacian(a):
    """The nine-point Laplacian on the torus: sides 0.2, corners 0.05, centre -1."""
    up, down = np.roll(a, 1, 0), np.roll(a, -1, 0)
    sides = up + down + np.roll(a, 1, 1) + np.roll(a, -1, 1)
    corners = np.roll(up, 1, 1) + np.roll(up, -1, 1) + np.roll(down, 1, 1) + np.roll(down, -1, 1)
    return LAPLACIAN_SIDE * sides + LAPLACIAN_CORNER * corners - a


def reaction_initial(doc, spec):
    """U = 1, V = 0 everywhere but a centred square of side round(spot * min(nx, ny)) cells where U = 1/2 and
    V = 1/4, each scaled by 1 + noise * (2 r - 1) with r the cell's stream draw (Pearson 1993's start)."""
    nx, ny = grid(spec)
    u = np.ones((ny, nx))
    v = np.zeros((ny, nx))
    side = int(round(float(_get(spec, "spot", REACTION_DEFAULTS)) * min(nx, ny)))
    if side <= 0:
        return u, v
    amp = float(_get(spec, "noise", REACTION_DEFAULTS))
    r = noise_field(element_seed(doc, spec), nx, ny)
    y0, x0 = (ny - side) // 2, (nx - side) // 2
    box = (slice(y0, y0 + side), slice(x0, x0 + side))
    wobble = amp * (2.0 * r[box] - 1.0)
    u[box] = 0.5 * (1.0 + wobble)
    v[box] = 0.25 * (1.0 - wobble)
    return u, v


def gray_scott(doc, spec, steps):
    """Pearson's system stepped `steps` times with dt = 1: U += Du L U - U V^2 + f (1 - U); V += Dv L V + U V^2 -
    (f + k) V; both clipped to [0, 1]. Returns (U, V)."""
    f = float(_get(spec, "feed", REACTION_DEFAULTS))
    k = float(_get(spec, "kill", REACTION_DEFAULTS))
    du = float(_get(spec, "diffuseU", REACTION_DEFAULTS))
    dv = float(_get(spec, "diffuseV", REACTION_DEFAULTS))
    u, v = reaction_initial(doc, spec)
    for _ in range(int(steps)):
        uvv = u * v * v
        u = np.clip(u + du * laplacian(u) - uvv + f * (1.0 - u), 0.0, 1.0)
        v = np.clip(v + dv * laplacian(v) + uvv - (f + k) * v, 0.0, 1.0)
    return u, v


def label(mask):
    """Four-connected components of a boolean field on the torus: labels (0 outside) and their count."""
    mask = np.asarray(mask, dtype=bool)
    ny, nx = mask.shape
    labels = np.where(mask, np.arange(1, ny * nx + 1).reshape(ny, nx), 0)
    big = ny * nx + 1
    while True:
        cur = np.where(mask, labels, big)
        best = cur.copy()
        for axis in (0, 1):
            for shift in (1, -1):
                best = np.minimum(best, np.roll(cur, shift, axis))
        best = np.where(mask, best, 0)
        if np.array_equal(best, labels):
            break
        labels = best
    ids = np.unique(labels[mask])
    return labels, len(ids)


def components(mask):
    return label(mask)[1]


def classify(v):
    """The pattern class of a V field: extinct (no cell above the threshold), uniform (every cell above it), spots
    (at least four components with area-weighted compactness 4 pi A / P^2 of at least 0.35), labyrinth (lower
    compactness), mixed otherwise."""
    mask = np.asarray(v) > FIELD_THRESHOLD
    share = float(mask.mean())
    if share < 1e-3:
        return "extinct"
    if share > 0.99:
        return "uniform"
    labels, count = label(mask)
    area = np.bincount(labels.ravel())
    perimeter = np.zeros_like(area)
    for axis in (0, 1):
        for shift in (1, -1):
            outside = ~np.roll(mask, shift, axis)
            perimeter += np.bincount(labels[mask & outside], minlength=len(area))
    ids = np.nonzero(area)[0]
    ids = ids[ids > 0]
    compact = 4.0 * math.pi * area[ids] / np.maximum(perimeter[ids], 1) ** 2
    weighted = float((compact * area[ids]).sum() / area[ids].sum())
    if weighted >= COMPACTNESS:
        return "spots" if count >= 4 else "mixed"
    return "labyrinth"


# ------------------------------------------------------------------------------------------------- Lenia


def kernel_core(r):
    """The exponential core exp(4 - 1 / (r (1 - r))) on (0, 1), zero outside; peak 1 at r = 1/2."""
    if r <= 0.0 or r >= 1.0:
        return 0.0
    return math.exp(4.0 - 1.0 / (r * (1.0 - r)))


def growth_map(u, mu, sigma):
    """The Gaussian growth 2 exp(-(u - mu)^2 / (2 sigma^2)) - 1 in [-1, 1]."""
    return 2.0 * np.exp(-((np.asarray(u, dtype=float) - mu) ** 2) / (2.0 * sigma * sigma)) - 1.0


def lenia_kernel(R, beta, nx, ny):
    """The ring kernel of radius R cells on the (ny, nx) torus, centred at [0, 0]: with B = len(beta) and r = d / R,
    K = beta[min(floor(B r), B - 1)] * core(B r mod 1) for r < 1, normalised to sum 1."""
    beta = tuple(float(b) for b in beta)
    B = len(beta)
    iy = np.arange(ny)
    ix = np.arange(nx)
    dy = np.minimum(iy, ny - iy)[:, None]
    dx = np.minimum(ix, nx - ix)[None, :]
    d = np.sqrt(dx * dx + dy * dy) / float(R)
    k = np.zeros((ny, nx))
    for row in range(ny):
        for col in range(nx):
            r = d[row, col]
            if r < 1.0:
                br = B * r
                k[row, col] = beta[min(int(math.floor(br)), B - 1)] * kernel_core(br - math.floor(br))
    total = k.sum()
    if total <= 0.0:
        raise PatternError("the kernel is empty")
    return k / total


def decode_cells(text):
    """Bert Chan's cell encoding: '.' is 0, 'A'..'X' are 1..24, a prefix 'p'..'y' adds 24 per letter from 25, a
    digit prefix repeats, '$' ends a row (a count repeats it), '!' ends the pattern; values are scaled by 255."""
    rows = [[]]
    count = ""
    prefix = ""
    for ch in str(text).rstrip("!") + "$":
        if ch.isdigit():
            count += ch
            continue
        if ch in "pqrstuvwxy":
            prefix = ch
            continue
        n = int(count) if count else 1
        if ch == "$":
            rows.extend([] for _ in range(n))
        elif ch == ".":
            rows[-1].extend([0] * n)
        elif "A" <= ch <= "X":
            v = ord(ch) - ord("A") + 1
            if prefix:
                v += (ord(prefix) - ord("p")) * 24 + 24
            rows[-1].extend([v] * n)
        else:
            raise PatternError(f"unknown cell character {ch!r}")
        count = ""
        prefix = ""
    rows = rows[:-1] if not rows[-1] else rows
    while rows and not rows[-1]:
        rows.pop()
    width = max(len(r) for r in rows)
    return np.array([r + [0] * (width - len(r)) for r in rows], dtype=float) / 255.0


def orbium():
    return decode_cells(ORBIUM_CELLS)


def _lenia_setup(doc, spec):
    nx, ny = grid(spec)
    R = int(_get(spec, "R", LENIA_DEFAULTS))
    if 2 * R + 1 > min(nx, ny):
        raise PatternError(f"a kernel of radius {R} needs at least {2 * R + 1} cells on each side, got {nx} x {ny}")
    creature = _get(spec, "creature", LENIA_DEFAULTS)
    if creature not in CREATURES:
        raise PatternError(f"unknown creature {creature!r}")
    a = np.zeros((ny, nx))
    if creature == "orbium":
        cells = orbium()
        h, w = cells.shape
        if h > ny or w > nx:
            raise PatternError("the creature does not fit the grid")
        y0, x0 = (ny - h) // 2, (nx - w) // 2
        a[y0:y0 + h, x0:x0 + w] = cells
    else:
        a = noise_field(element_seed(doc, spec), nx, ny)
    kernel = lenia_kernel(R, _get(spec, "beta", LENIA_DEFAULTS), nx, ny)
    return a, np.fft.rfft2(kernel), float(_get(spec, "mu", LENIA_DEFAULTS)), \
        float(_get(spec, "sigma", LENIA_DEFAULTS)), 1.0 / float(_get(spec, "T", LENIA_DEFAULTS))


def _lenia_step(a, kernel_fft, mu, sigma, dt):
    potential = np.fft.irfft2(np.fft.rfft2(a) * kernel_fft, s=a.shape)
    return np.clip(a + dt * growth_map(potential, mu, sigma), 0.0, 1.0)


def lenia(doc, spec, steps):
    """A <- clip(A + (1/T) G(K * A), 0, 1) stepped `steps` times; K * A is the circular convolution (by FFT)."""
    a, kf, mu, sigma, dt = _lenia_setup(doc, spec)
    for _ in range(int(steps)):
        a = _lenia_step(a, kf, mu, sigma, dt)
    return a


def mass(a):
    return float(np.asarray(a).sum())


def centroid(a, nx, ny):
    """The circular mean of the field's mass on the torus, (x, y) in cells."""
    a = np.asarray(a)
    total = a.sum()
    if total <= 0.0:
        return (0.0, 0.0)
    out = []
    for n, axis in ((nx, 1), (ny, 0)):
        prof = a.sum(axis=0) if axis == 1 else a.sum(axis=1)
        th = 2.0 * math.pi * np.arange(n) / n
        ang = math.atan2(float((prof * np.sin(th)).sum()), float((prof * np.cos(th)).sum())) % (2.0 * math.pi)
        out.append(ang * n / (2.0 * math.pi))
    return (out[0], out[1])


def displacement(c0, c1, nx, ny):
    """The shortest distance between two centroids on the torus."""
    dx = (c1[0] - c0[0] + nx / 2.0) % nx - nx / 2.0
    dy = (c1[1] - c0[1] + ny / 2.0) % ny - ny / 2.0
    return math.hypot(dx, dy)


def lenia_track(doc, spec, steps, every):
    """[(step, mass, centroid)] at step 0, every `every` steps, and at `steps`."""
    nx, ny = grid(spec)
    a, kf, mu, sigma, dt = _lenia_setup(doc, spec)
    track = [(0, mass(a), centroid(a, nx, ny))]
    for s in range(1, int(steps) + 1):
        a = _lenia_step(a, kf, mu, sigma, dt)
        if s % every == 0 or s == steps:
            track.append((s, mass(a), centroid(a, nx, ny)))
    return track


def lenia_speed(track, nx, ny):
    """The mean speed, cells per step, between consecutive samples of a track."""
    speeds = [displacement(track[i][2], track[i + 1][2], nx, ny) / (track[i + 1][0] - track[i][0])
              for i in range(len(track) - 1)]
    return sum(speeds) / len(speeds)


# ------------------------------------------------------------------------------------------------- cellular automata


def parse_rule(rule):
    """B<digits>/S<digits>: the neighbour counts (0..8, each once) that give birth and that let a cell survive."""
    m = re.fullmatch(r"B([0-8]*)/S([0-8]*)", str(rule))
    if not m:
        raise PatternError(f"a rule is B<digits>/S<digits>: {rule!r}")
    out = []
    for digits in m.groups():
        if len(set(digits)) != len(digits):
            raise PatternError(f"a neighbour count appears twice in {rule!r}")
        out.append({int(c) for c in digits})
    return out[0], out[1]


def parse_rle(text):
    """Golly's run-length encoding: b dead, o alive, $ end of row, ! end; a count repeats; rows pad with dead cells."""
    text = str(text)
    if not text.endswith("!"):
        raise PatternError("a pattern ends with '!'")
    body = text[:-1]
    rows = [[]]
    pos = 0
    for m in re.finditer(r"(\d*)([bo$])", body):
        if m.start() != pos:
            raise PatternError(f"unknown pattern text at {pos}: {body[pos:m.start()]!r}")
        pos = m.end()
        n = int(m.group(1)) if m.group(1) else 1
        tag = m.group(2)
        if tag == "$":
            rows.extend([] for _ in range(n))
        else:
            rows[-1].extend([1 if tag == "o" else 0] * n)
    if pos != len(body):
        raise PatternError(f"unknown pattern text at {pos}: {body[pos:]!r}")
    while rows and not rows[-1]:
        rows.pop()
    if not rows or not any(any(r) for r in rows):
        raise PatternError("an empty pattern")
    width = max(len(r) for r in rows)
    return np.array([r + [0] * (width - len(r)) for r in rows], dtype=np.uint8)


def automaton_initial(doc, spec):
    nx, ny = grid(spec)
    pattern = spec.get("pattern")
    if pattern is not None:
        cells = parse_rle(pattern)
        h, w = cells.shape
        if h > ny or w > nx:
            raise PatternError(f"a {w} x {h} pattern does not fit a {nx} x {ny} grid")
        x = spec.get("x")
        y = spec.get("y")
        x = (nx - w + 1) // 2 if x is None else int(x)
        y = (ny - h + 1) // 2 if y is None else int(y)
        if not (0 <= x < nx and 0 <= y < ny):
            raise PatternError("the pattern's corner is outside the grid")
        out = np.zeros((ny, nx), dtype=np.uint8)
        for r in range(h):
            for c in range(w):
                out[(y + r) % ny, (x + c) % nx] = cells[r, c]
        return out
    density = float(_get(spec, "density", AUTOMATON_DEFAULTS))
    return (noise_field(element_seed(doc, spec), nx, ny) < density).astype(np.uint8)


def automaton_step(cells, births, survivals):
    n = np.zeros(cells.shape, dtype=np.int16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                n += np.roll(np.roll(cells, dy, 0), dx, 1)
    born = np.isin(n, list(births)) & (cells == 0)
    stay = np.isin(n, list(survivals)) & (cells == 1)
    return (born | stay).astype(np.uint8)


def automaton(doc, spec, steps):
    births, survivals = parse_rule(_get(spec, "rule", AUTOMATON_DEFAULTS))
    cells = automaton_initial(doc, spec)
    for _ in range(int(steps)):
        cells = automaton_step(cells, births, survivals)
    return cells


def period(doc, spec, max_period):
    """The smallest p in 1..max_period after which the automaton repeats its start up to a translation, with that
    translation (dy, dx) in the shortest wrapped form; None when it does not."""
    births, survivals = parse_rule(_get(spec, "rule", AUTOMATON_DEFAULTS))
    start = automaton_initial(doc, spec)
    ny, nx = start.shape
    shifts = sorted(((dy, dx) for dy in range(-(ny // 2), (ny + 1) // 2) for dx in range(-(nx // 2), (nx + 1) // 2)),
                    key=lambda s: (abs(s[0]) + abs(s[1]), s))
    cells = start
    total = int(start.sum())
    for p in range(1, int(max_period) + 1):
        cells = automaton_step(cells, births, survivals)
        if int(cells.sum()) != total:
            continue
        for dy, dx in shifts:
            if np.array_equal(cells, np.roll(start, (dy, dx), (0, 1))):
                return p, (dy, dx)
    return None


# ------------------------------------------------------------------------------------------------- aggregation


def walker_angle(e, k, i):
    """2 pi S(e, 2, k, 2 i): the launch angle of walker k at i = 0, the direction of its i-th step after."""
    return 2.0 * math.pi * streams().S(e, WALK_PURPOSE, k, 2 * i)


_DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))
_AGGREGATES = {}


def aggregate(doc, spec, n):
    """The first n particles of the aggregate (see _aggregate); results are cached, the walk is deterministic."""
    nx, ny = grid(spec)
    key = (element_seed(doc, spec), nx, ny, float(_get(spec, "stick", AGGREGATION_DEFAULTS)),
           float(_get(spec, "launch", AGGREGATION_DEFAULTS)), min(int(n), int(_get(spec, "particles", AGGREGATION_DEFAULTS))))
    if key not in _AGGREGATES:
        _AGGREGATES[key] = _aggregate(doc, spec, n)
    out = _AGGREGATES[key]
    return {"positions": list(out["positions"]), "radius": out["radius"], "launched": out["launched"],
            "centre": out["centre"]}


def _aggregate(doc, spec, n):
    """The first n particles of the aggregate: the seed at the grid's centre, then one stuck walker after another.
    Walker k launches at rmax + launch from the centre at its stream angle; each step moves one cell in the
    direction floor(4 u) of its draw, or jumps floor(d - rmax - 1) cells when it is farther than rmax + 2 from the
    centre (no particle lies on such a jump); it sticks with probability `stick` when a four-neighbour is occupied,
    and is lost beyond 2 (rmax + launch) + 10 cells, outside the grid, or when MAX_LAUNCHES walkers per particle
    have been launched. The aggregate stops when the launch circle no longer fits the grid."""
    S = streams().S
    e = element_seed(doc, spec)
    nx, ny = grid(spec)
    cx, cy = nx // 2, ny // 2
    stick = float(_get(spec, "stick", AGGREGATION_DEFAULTS))
    launch = float(_get(spec, "launch", AGGREGATION_DEFAULTS))
    limit = min(int(n), int(_get(spec, "particles", AGGREGATION_DEFAULTS)))
    positions = [(cx, cy)]
    occupied = {(cx, cy)}
    rmax = 0.0
    k = 0
    margin = min(cx, cy, nx - 1 - cx, ny - 1 - cy)
    while len(positions) < limit and k < MAX_LAUNCHES * limit:
        if rmax + launch > margin:
            break
        k += 1
        radius = rmax + launch
        angle = walker_angle(e, k, 0)
        x = int(round(cx + radius * math.cos(angle)))
        y = int(round(cy + radius * math.sin(angle)))
        kill = 2.0 * radius + 10.0
        i = 0
        while True:
            i += 1
            d = math.hypot(x - cx, y - cy)
            if d > kill:
                break
            u = S(e, WALK_PURPOSE, k, 2 * i)
            dx, dy = _DIRECTIONS[min(3, int(4.0 * u))]
            jump = max(1, int(math.floor(d - rmax - 1.0))) if d > rmax + 2.0 else 1
            tx, ty = x + dx * jump, y + dy * jump
            if not (0 <= tx < nx and 0 <= ty < ny):
                break
            if (tx, ty) not in occupied:
                x, y = tx, ty
            if any((x + ddx, y + ddy) in occupied for ddx, ddy in _DIRECTIONS):
                if stick >= 1.0 or S(e, WALK_PURPOSE, k, 2 * i + 1) < stick:
                    positions.append((x, y))
                    occupied.add((x, y))
                    rmax = max(rmax, d)
                    break
    return {"positions": positions, "radius": rmax, "launched": k, "centre": (cx, cy)}


def fractal_dimension(points):
    """The radius-of-gyration dimension of a growth sequence (Witten and Sander 1981): with Rg(m) the radius of
    gyration of the first m points, D = 1 / slope of log Rg(m) against log m, least squares over twelve counts
    spaced geometrically from n / 8 to n."""
    pts = np.asarray(points, dtype=float)
    n = len(pts)
    counts = np.unique(np.geomspace(max(2, n // 8), n, 12).astype(int))
    rg = []
    for m in counts:
        p = pts[:m]
        c = p.mean(axis=0)
        rg.append(math.sqrt(float(((p - c) ** 2).sum(axis=1).mean())))
    x, y = np.log(counts), np.log(rg)
    slope = float(((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum())
    return 1.0 / slope


# ------------------------------------------------------------------------------------------------- differential growth


def growth_initial(doc, spec):
    """`nodes` nodes on a circle of `radius` cells about the box's centre, counter-clockwise from +x."""
    nx, ny = grid(spec)
    n = int(_get(spec, "nodes", GROWTH_DEFAULTS))
    r = float(_get(spec, "radius", GROWTH_DEFAULTS))
    th = 2.0 * math.pi * np.arange(n) / n
    return np.stack([nx / 2.0 + r * np.cos(th), ny / 2.0 + r * np.sin(th)], axis=1)


def curve_length(nodes):
    nodes = np.asarray(nodes, dtype=float)
    return float(np.hypot(*(np.roll(nodes, -1, 0) - nodes).T).sum())


def split_edges(nodes, max_edge):
    """Insert the midpoint of every edge longer than max_edge, keeping the order."""
    nodes = np.asarray(nodes, dtype=float)
    out = []
    n = len(nodes)
    for i in range(n):
        a, b = nodes[i], nodes[(i + 1) % n]
        out.append(a)
        if math.hypot(*(b - a)) > max_edge:
            out.append((a + b) / 2.0)
    return np.array(out)


def jitter(e, step, node):
    """(S(e, 3, step, 2 node) - 1/2, S(e, 3, step, 2 node + 1) - 1/2)."""
    S = streams().S
    return (S(e, JITTER_PURPOSE, step, 2 * node) - 0.5, S(e, JITTER_PURPOSE, step, 2 * node + 1) - 0.5)


def insertion_edge(e, step, n, j=0):
    """floor(n S(e, 3, step, 2 n + j)): the edge that receives the j-th inserted node of a step among n nodes."""
    return int(n * streams().S(e, JITTER_PURPOSE, step, 2 * n + j))


def grow(doc, spec, steps):
    """The closed curve after `steps` steps. Each step every node moves by `speed` times the clipped sum of:
    attraction, the unit vectors toward both neighbours; alignment toward the neighbours' midpoint; repulsion
    from every other node within `repulsion` cells, by (1 - d / repulsion) away from it; and `jitter` times the
    node's stream draw. Nodes stay inside the box; then `insert` nodes are added at the midpoints of stream-chosen
    edges, and every edge longer than `maxEdge` is split at its midpoint, both while the count is below
    `maxNodes`; a split that would pass `maxNodes` is skipped whole, and a curve with `maxNodes` nodes is frozen."""
    e = element_seed(doc, spec)
    nx, ny = grid(spec)
    nodes = growth_initial(doc, spec)
    max_edge = float(_get(spec, "maxEdge", GROWTH_DEFAULTS))
    rep = float(_get(spec, "repulsion", GROWTH_DEFAULTS))
    w_att = float(_get(spec, "attraction", GROWTH_DEFAULTS))
    w_ali = float(_get(spec, "alignment", GROWTH_DEFAULTS))
    w_rep = float(_get(spec, "repel", GROWTH_DEFAULTS))
    w_jit = float(_get(spec, "jitter", GROWTH_DEFAULTS))
    speed = float(_get(spec, "speed", GROWTH_DEFAULTS))
    cap = int(_get(spec, "maxNodes", GROWTH_DEFAULTS))
    insert = int(_get(spec, "insert", GROWTH_DEFAULTS))
    for step in range(1, int(steps) + 1):
        n = len(nodes)
        if n >= cap:
            break                                    # the curve is frozen at maxNodes
        prev, nxt = np.roll(nodes, 1, 0), np.roll(nodes, -1, 0)
        force = np.zeros_like(nodes)
        for nb in (prev, nxt):
            dvec = nb - nodes
            dist = np.maximum(np.hypot(dvec[:, 0], dvec[:, 1]), 1e-12)[:, None]
            force += w_att * dvec / dist
        force += w_ali * ((prev + nxt) / 2.0 - nodes)
        if rep > 0.0 and w_rep > 0.0:
            diff = nodes[:, None, :] - nodes[None, :, :]
            dist = np.hypot(diff[:, :, 0], diff[:, :, 1])
            near = (dist < rep) & (dist > 0.0)
            weight = np.where(near, (1.0 - dist / rep) / np.maximum(dist, 1e-12), 0.0)
            force += w_rep * (diff * weight[:, :, None]).sum(axis=1)
        if w_jit > 0.0:
            force += w_jit * np.array([jitter(e, step, i) for i in range(n)])
        mag = np.maximum(np.hypot(force[:, 0], force[:, 1]), 1e-12)[:, None]
        move = force * np.minimum(1.0, 1.0 / mag) * speed
        nodes = nodes + move
        nodes[:, 0] = np.clip(nodes[:, 0], 0.0, float(nx))
        nodes[:, 1] = np.clip(nodes[:, 1], 0.0, float(ny))
        for j in range(insert):
            if len(nodes) >= cap:
                break
            i = insertion_edge(e, step, n, j)
            mid = (nodes[i] + nodes[(i + 1) % len(nodes)]) / 2.0
            nodes = np.insert(nodes, i + 1, mid, axis=0)
        split = split_edges(nodes, max_edge)
        if len(split) <= cap:
            nodes = split                            # a split that would pass maxNodes is skipped whole
    return nodes


def self_intersections(nodes):
    """The number of pairs of non-adjacent edges of the closed curve that cross."""
    p = np.asarray(nodes, dtype=float)
    n = len(p)
    q = np.roll(p, -1, 0)
    count = 0

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            a, b, c, d = p[i], q[i], p[j], q[j]
            if orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0:
                count += 1
    return count


# ------------------------------------------------------------------------------------------------- the run


def _summary(doc, spec, steps):
    kind = spec["kind"]
    nx, ny = grid(spec)
    out = {"kind": kind, "steps": steps, "grid": (nx, ny)}
    if kind == "reaction":
        u, v = gray_scott(doc, spec, steps)
        out.update({"class": classify(v), "meanU": float(u.mean()), "meanV": float(v.mean()),
                    "cover": float((v > FIELD_THRESHOLD).mean())})
    elif kind == "lenia":
        a = lenia(doc, spec, steps)
        out.update({"mass": mass(a), "centroid": centroid(a, nx, ny), "peak": float(a.max())})
    elif kind == "automaton":
        cells = automaton(doc, spec, steps)
        out.update({"alive": int(cells.sum())})
    elif kind == "aggregation":
        agg = aggregate(doc, spec, steps)
        out.update({"particles": len(agg["positions"]), "radius": agg["radius"], "launched": agg["launched"]})
    elif kind == "growth":
        nodes = grow(doc, spec, steps)
        out.update({"nodes": int(len(nodes)), "length": curve_length(nodes),
                    "crossings": self_intersections(nodes) if len(nodes) <= 1000 else None})
    else:
        raise PatternError(f"unknown kind {kind!r}")
    return out


def run(doc, t):
    """Every pattern element of the document at time t: its state summary, and a digest of them all."""
    elements = {}
    for spec in doc.get("patterns") or []:
        elements[spec["id"]] = _summary(doc, spec, steps_at(spec, t))
    return {"time": t, "elements": elements, "digest": digest(elements)}


# ------------------------------------------------------------------------------------------------- documents


def example_document():
    return {
        "version": "1.8", "project": 7,
        "patterns": [
            {"kind": "reaction", "id": "coral", "width": 128.0, "height": 128.0, "resolution": 128, "seed": 3,
             "feed": 0.055, "kill": 0.062, "rate": 100.0, "saturation": 0.5, "color": "#2A9D8FFF"},
            {"kind": "lenia", "id": "orbium", "width": 64.0, "height": 64.0, "resolution": 64, "seed": 1,
             "rate": 10.0, "color": "#E9C46AFF"},
            {"kind": "automaton", "id": "life", "width": 32.0, "height": 32.0, "resolution": 32, "seed": 2,
             "pattern": "b2o$2o$bo!", "rate": 8.0, "color": "#F4F1DEFF"},
            {"kind": "aggregation", "id": "frost", "width": 128.0, "height": 128.0, "resolution": 128, "seed": 5,
             "particles": 600, "rate": 30.0, "color": "#A8DADCFF"},
            {"kind": "growth", "id": "vine", "width": 100.0, "height": 100.0, "resolution": 100, "seed": 2,
             "nodes": 24, "radius": 5.0, "maxNodes": 800, "rate": 30.0, "color": "#81B29AFF"},
        ],
    }


def bad_document():
    doc = example_document()
    doc["patterns"][0]["resolution"] = 4                 # PT1
    doc["patterns"][1]["R"] = 0                          # PT2
    doc["patterns"][2]["rule"] = "B3S23"                 # PT3
    doc["patterns"][3]["stick"] = 0.0                    # PT4
    doc["patterns"][4]["nodes"] = 2                      # PT5
    return doc


def _positive(spec, key, defaults):
    return float(_get(spec, key, defaults)) > 0.0


def _unit(spec, key, defaults):
    return 0.0 <= float(_get(spec, key, defaults)) <= 1.0


def _check_frame(spec):
    if spec.get("kind") not in KINDS:
        return False
    res = int(_get(spec, "resolution", COMMON_DEFAULTS))
    prewarm = int(_get(spec, "prewarm", COMMON_DEFAULTS))
    bound = int(_get(spec, "maxSteps", COMMON_DEFAULTS))
    return (MIN_RESOLUTION <= res <= MAX_RESOLUTION and _positive(spec, "rate", COMMON_DEFAULTS)
            and 0 <= prewarm <= bound and bound >= 1 and float(spec["width"]) > 0.0 and float(spec["height"]) > 0.0
            and _positive(spec, "saturation", COMMON_DEFAULTS))


def _check_reaction(spec):
    du = float(_get(spec, "diffuseU", REACTION_DEFAULTS))
    dv = float(_get(spec, "diffuseV", REACTION_DEFAULTS))
    return (_unit(spec, "feed", REACTION_DEFAULTS) and _unit(spec, "kill", REACTION_DEFAULTS)
            and 0.0 < dv <= du <= 1.0 and _unit(spec, "spot", REACTION_DEFAULTS) and _unit(spec, "noise", REACTION_DEFAULTS))


def _check_lenia(spec):
    nx, ny = grid(spec)
    R = int(_get(spec, "R", LENIA_DEFAULTS))
    beta = list(_get(spec, "beta", LENIA_DEFAULTS))
    return (R >= 1 and 2 * R + 1 <= min(nx, ny) and int(_get(spec, "T", LENIA_DEFAULTS)) >= 1
            and _positive(spec, "mu", LENIA_DEFAULTS) and _positive(spec, "sigma", LENIA_DEFAULTS)
            and len(beta) >= 1 and all(0.0 < float(b) <= 1.0 for b in beta)
            and _get(spec, "creature", LENIA_DEFAULTS) in CREATURES)


def _check_automaton(spec):
    nx, ny = grid(spec)
    try:
        parse_rule(_get(spec, "rule", AUTOMATON_DEFAULTS))
        if spec.get("pattern") is not None:
            cells = parse_rle(spec["pattern"])
            if cells.shape[0] > ny or cells.shape[1] > nx:
                return False
    except PatternError:
        return False
    x, y = spec.get("x"), spec.get("y")
    return (_unit(spec, "density", AUTOMATON_DEFAULTS) and (x is None or 0 <= int(x) < nx)
            and (y is None or 0 <= int(y) < ny))


def _check_aggregation(spec):
    stick = float(_get(spec, "stick", AGGREGATION_DEFAULTS))
    return (1 <= int(_get(spec, "particles", AGGREGATION_DEFAULTS)) <= MAX_PARTICLES and 0.0 < stick <= 1.0
            and _positive(spec, "launch", AGGREGATION_DEFAULTS))


def _check_growth(spec):
    n = int(_get(spec, "nodes", GROWTH_DEFAULTS))
    return (n >= 3 and int(_get(spec, "maxNodes", GROWTH_DEFAULTS)) >= n and _positive(spec, "radius", GROWTH_DEFAULTS)
            and _positive(spec, "maxEdge", GROWTH_DEFAULTS) and _positive(spec, "speed", GROWTH_DEFAULTS)
            and int(_get(spec, "insert", GROWTH_DEFAULTS)) >= 0
            and all(float(_get(spec, k, GROWTH_DEFAULTS)) >= 0.0
                    for k in ("repulsion", "attraction", "alignment", "repel", "jitter")))


_CHECKS = {"reaction": ("PT2", _check_reaction), "lenia": ("PT2", _check_lenia), "automaton": ("PT3", _check_automaton),
           "aggregation": ("PT4", _check_aggregation), "growth": ("PT5", _check_growth)}


def validate_document(doc):
    """The codes of the draft's rules the document breaks, sorted: PT1 the frame, PT2 reaction and lenia parameters,
    PT3 the automaton's rule and pattern, PT4 the aggregation, PT5 the growth, V17 the version."""
    codes = set()
    patterns = doc.get("patterns") or []
    if not patterns:
        return []
    major, minor = (int(x) for x in str(doc.get("version", "1.8")).split(".")[:2])
    if (major, minor) < (1, 8):
        codes.add("V17")
    for spec in patterns:
        if not _check_frame(spec):
            codes.add("PT1")
            continue
        code, check = _CHECKS[spec["kind"]]
        if not check(spec):
            codes.add(code)
    return sorted(codes)


# ------------------------------------------------------------------------------------------------- the table

TABLE = (
    ("resolution bounds", "(MIN_RESOLUTION, MAX_RESOLUTION)", "(8, 2048)"),
    ("grid of a 200 x 100 box at 64", "grid({'width': 200.0, 'height': 100.0, 'resolution': 64})", "(64, 32)"),
    ("steps at 1 s, rate 30, prewarm 10", "steps_at({'rate': 30.0, 'prewarm': 10, 'maxSteps': 100}, 1.0)", "40"),
    ("element seed of the coral", "element_seed(EXAMPLE, EXAMPLE['patterns'][0])", "4250453633"),
    ("first noise draw of the coral", "noise_field(element_seed(EXAMPLE, EXAMPLE['patterns'][0]), 4, 1)[0, 0]", "0.07822702388394731"),
    ("Laplacian of a point: centre, side, corner", "(laplacian(POINT)[0, 0], laplacian(POINT)[0, 1], laplacian(POINT)[7, 7])", "(-1.0, 0.2, 0.05)"),
    ("mitosis class (f 0.0367, k 0.0649)", "classify(MITOSIS[1])", "'spots'"),
    ("mitosis: components", "components(MITOSIS[1] > FIELD_THRESHOLD)", "8"),
    ("coral class (f 0.055, k 0.062)", "classify(CORAL[1])", "'labyrinth'"),
    ("coral: cover", "float((CORAL[1] > FIELD_THRESHOLD).mean())", "0.365478515625"),
    ("extinct class (f 0.03, k 0.07)", "classify(EXTINCT[1])", "'extinct'"),
    ("kernel core at 1/2 and 1/4", "(kernel_core(0.5), kernel_core(0.25))", "(1.0, 0.2635971381157268)"),
    ("growth map at mu + sigma", "float(growth_map(0.165, 0.15, 0.015))", "0.21306131942526574"),
    ("Orbium kernel: peak cell", "float(KERNEL[0, 7])", "0.0047918072957934005"),
    ("Orbium mass", "ORBIUM_MASS", "76.86274509803921"),
    ("Orbium at 120 steps: mass", "TRACK[-1][1]", "71.41823459916863"),
    ("Orbium: speed, cells per step", "lenia_speed(TRACK, 64, 64)", "0.6102042564583444"),
    ("Orbium: centroid at 120 steps", "TRACK[-1][2]", "(59.48012739624021, 36.72984639778816)"),
    ("Life rule", "parse_rule('B3/S23')", "({3}, {2, 3})"),
    ("glider cells", "parse_rle('bo$2bo$3o!').tolist()", "[[0, 1, 0], [0, 0, 1], [1, 1, 1]]"),
    ("blinker period", "period(LIFE, LIFE['patterns'][0], 8)", "(2, (0, 0))"),
    ("glider period and shift", "period(GLIDER, GLIDER['patterns'][0], 8)", "(4, (1, 1))"),
    ("R-pentomino alive at 100 steps", "int(automaton(EXAMPLE, EXAMPLE['patterns'][2], 100).sum())", "43"),
    ("cluster of 2000: radius", "CLUSTER['radius']", "82.87339742040264"),
    ("cluster of 2000: launched walkers", "CLUSTER['launched']", "3044"),
    ("cluster of 2000: dimension", "fractal_dimension(CLUSTER['positions'])", "1.70549615492584"),
    ("cluster: second particle", "CLUSTER['positions'][1]", "(127, 128)"),
    ("dimension of a disc grown outward", "fractal_dimension(DISC)", "2.0001587502777305"),
    ("curve at 0, 30 and 300 steps: nodes", "[len(grow(VINE, VINE['patterns'][0], s)) for s in (0, 30, 300)]", "[24, 80, 473]"),
    ("curve at 300 steps: length", "curve_length(grow(VINE, VINE['patterns'][0], 300))", "497.5086731587346"),
    ("curve at 300 steps: crossings", "self_intersections(grow(VINE, VINE['patterns'][0], 300))", "0"),
    ("ramp at 1/2", "ramp({'color': '#FFD27AFF', 'colorLow': '#00000000'}, 0.5)", "(128, 105, 61, 128)"),
    ("run at 1 s: digest", "RUN['digest']", "'c886c535e80c9d8d33804b62b4c4c54ffeea0f039692b56a6734a936b9d3743f'"),
    ("run at 1 s: particles of the frost", "RUN['elements']['frost']['particles']", "30"),
    ("bad document", "validate_document(bad_document())", "['PT1', 'PT2', 'PT3', 'PT4', 'PT5']"),
)

_SCOPE = None


def scope():
    global _SCOPE
    if _SCOPE is None:
        s = {k: v for k, v in globals().items() if not k.startswith("__")}
        s["EXAMPLE"] = example_document()
        point = np.zeros((8, 8))
        point[0, 0] = 1.0
        s["POINT"] = point
        base = {"kind": "reaction", "id": "r1", "width": 128.0, "height": 128.0, "resolution": 128, "seed": 3}
        doc = {"version": "1.8", "project": 7, "patterns": [base]}
        s["MITOSIS"] = gray_scott(doc, dict(base, feed=0.0367, kill=0.0649), 4000)
        s["CORAL"] = gray_scott(doc, dict(base, feed=0.055, kill=0.062), 4000)
        s["EXTINCT"] = gray_scott(doc, dict(base, feed=0.03, kill=0.07), 4000)
        s["KERNEL"] = lenia_kernel(13, (1.0,), 64, 64)
        orb = {"kind": "lenia", "id": "l1", "width": 64.0, "height": 64.0, "resolution": 64, "seed": 1}
        s["TRACK"] = lenia_track({"version": "1.8", "project": 7, "patterns": [orb]}, orb, 120, 20)
        life = {"kind": "automaton", "id": "a1", "width": 16.0, "height": 16.0, "resolution": 16, "seed": 1,
                "pattern": "3o!"}
        s["LIFE"] = {"version": "1.8", "project": 7, "patterns": [life]}
        s["GLIDER"] = {"version": "1.8", "project": 7, "patterns": [dict(life, pattern="bo$2bo$3o!")]}
        dla = {"kind": "aggregation", "id": "d1", "width": 256.0, "height": 256.0, "resolution": 256, "seed": 5}
        s["CLUSTER"] = aggregate({"version": "1.8", "project": 7, "patterns": [dla]}, dla, 2000)
        s["DISC"] = sorted(((x, y) for x in range(-40, 41) for y in range(-40, 41) if x * x + y * y <= 1600),
                           key=lambda q: (q[0] * q[0] + q[1] * q[1], q))
        vine = {"kind": "growth", "id": "g1", "width": 100.0, "height": 100.0, "resolution": 100, "seed": 2,
                "nodes": 24, "radius": 8.0, "maxNodes": 800}
        s["VINE"] = {"version": "1.8", "project": 7, "patterns": [vine]}
        s["RUN"] = run(s["EXAMPLE"], 1.0)
        _SCOPE = s
    return _SCOPE


def _same(a, b, rel=5e-4, abs_tol=1e-9):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (set, frozenset)) and isinstance(b, (set, frozenset)):
        return a == b
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)):
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return repr(float(v))
    if isinstance(v, set):
        return "{" + ", ".join(_fmt(x) for x in sorted(v)) + "}"
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k!r}: {_fmt(x)}" for k, x in v.items()) + "}"
    return repr(v)


def main():
    s = scope()
    print("| Test | Expression | Value |")
    print("|---|---|---|")
    for name, expr, _ in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
