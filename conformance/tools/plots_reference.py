#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add coordinate systems and plots" (srep/srep-0000-plots.md; MF1 of
SREP 12): the data-to-pixel mapping of an axes box, nice tick steps and tick labels, the sampling of explicit,
parametric and polar curves, the clipping of a polyline to the box, implicit curves by marching squares, the
3D axes mapping and the tubes that draw 3D curves. Standard library only.

    python3 plots_reference.py        # prints the SREP's numeric-test table

Every function is a pure function of its arguments; nothing here reads a document or draws. Section numbers refer
to the SREP's Semantics.
"""
import math
from dataclasses import dataclass

DEFAULT_SAMPLES = 256           # samples of an explicit, parametric or polar plot (rule 7)
DEFAULT_RESOLUTION = 64         # cells per side of the marching-squares grid (rule 8)
DEFAULT_TUBE_SEGMENTS = 8       # vertices around a 3D tube (rule 10)
MAX_INTERVALS = 10              # the nice step cuts the range into at most this many intervals (rule 4)
LABEL_GAP = 4.0                 # pixels between a tick mark and its label (rule 5)


# ---------------------------------------------------------------------------------------------- 1. the mapping

@dataclass(frozen=True)
class Axes:
    """A 2D axes box: the data ranges and the box size in pixels (the box's top-left is the node's origin)."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    width: float
    height: float

    def __post_init__(self):
        if not (self.x_min < self.x_max) or not (self.y_min < self.y_max):
            raise ValueError("axes: xMin < xMax and yMin < yMax are required")
        if not (self.width > 0 and self.height > 0):
            raise ValueError("axes: width and height are positive")


def to_pixel(ax, x, y):
    """Rule 1: data (x, y) to the box's pixel (px, py); +y data is up, so py grows downward from yMax."""
    px = (x - ax.x_min) / (ax.x_max - ax.x_min) * ax.width
    py = (ax.y_max - y) / (ax.y_max - ax.y_min) * ax.height
    return px, py


def from_pixel(ax, px, py):
    """The inverse of to_pixel."""
    x = ax.x_min + px / ax.width * (ax.x_max - ax.x_min)
    y = ax.y_max - py / ax.height * (ax.y_max - ax.y_min)
    return x, y


# ------------------------------------------------------------------------------------- 4 and 5. ticks and labels

def ticks(lo, hi, step):
    """Rule 4: the multiples k·step inside [lo, hi], each computed as k × step (never accumulated), with a
    tolerance of 10⁻⁹·step at the edges so that 3 × 0.1 counts as inside [0, 0.3]."""
    if not (hi > lo) or not (step > 0):
        raise ValueError("ticks: lo < hi and step > 0 are required")
    eps = 1e-9 * step
    k0 = math.ceil((lo - eps) / step)
    k1 = math.floor((hi + eps) / step)
    return tuple(k * step for k in range(k0, k1 + 1))


def nice_step(lo, hi, max_intervals=MAX_INTERVALS):
    """Rule 4: the smallest step of the form 1, 2 or 5 × 10ᵏ (k an integer) with (hi − lo)/step ≤ max_intervals,
    so a range carries at most max_intervals + 1 ticks."""
    if not (hi > lo):
        raise ValueError("nice_step: lo < hi is required")
    span = hi - lo
    k = math.floor(math.log10(span)) - 2
    while True:
        for m in (1, 2, 5):
            step = m * 10.0 ** k
            if span / step <= max_intervals + 1e-9:
                return step
        k += 1


def label_decimals(step):
    """Rule 5: the fewest decimals (0 to 12) that write the step exactly: 1 → 0, 0.5 → 1, 0.25 → 2, 0.001 → 3."""
    if not (step > 0):
        raise ValueError("label_decimals: step > 0 is required")
    for d in range(13):
        if abs(round(step, d) - step) <= 1e-9 * step:
            return d
    return 12


def tick_label(value, step, imaginary=False):
    """Rule 5: the tick's label text (TeX): the value written with the step's decimals, trailing zeros and a
    trailing point removed, −0 written 0; on the imaginary axis the suffix i, with 1i and −1i written i and −i."""
    s = f"{value:.{label_decimals(step)}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", "0", ""):
        s = "0"
    if not imaginary or s == "0":
        return s
    if s == "1":
        return "i"
    if s == "-1":
        return "-i"
    return s + "i"


def axis_position(lo, hi):
    """Rule 3: the data coordinate the perpendicular axis line sits at: 0 when the range contains it, else the
    lower edge of the range."""
    return 0.0 if lo <= 0.0 <= hi else float(lo)


# ----------------------------------------------------------------------------------------- 7. sampled curves

def _grid(a, b, n, closed=False):
    if n < 2:
        raise ValueError("samples: at least 2")
    delta = (b - a) / (n if closed else n - 1)
    return [a + i * delta for i in range(n)]


def sample_explicit(f, x0, x1, n):
    """Rule 7a: (x_i, f(x_i)) at n evenly spaced x from x0 to x1 inclusive."""
    return tuple((x, f(x)) for x in _grid(x0, x1, n))


def sample_parametric(fx, fy, t0, t1, n, closed=False):
    """Rule 7b: the points of SREP 70 rule 2: t_i = t0 + i·Δ with Δ = (t1 − t0)/(n − 1), or /n when closed."""
    return tuple((fx(t), fy(t)) for t in _grid(t0, t1, n, closed))


def sample_polar(fr, theta0, theta1, n):
    """Rule 7c: (r cos θ, r sin θ) with r = fr(θ) at n evenly spaced θ (radians) from theta0 to theta1."""
    out = []
    for th in _grid(theta0, theta1, n):
        r = fr(th)
        out.append((r * math.cos(th), r * math.sin(th)))
    return tuple(out)


def split_finite(points):
    """SREP 70 rule 2 (non-finite points): drop every point with a non-finite coordinate; the points between two
    drops form one subpath each."""
    parts, cur = [], []
    for p in points:
        if all(math.isfinite(c) for c in p):
            cur.append(p)
        elif cur:
            parts.append(tuple(cur))
            cur = []
    if cur:
        parts.append(tuple(cur))
    return tuple(parts)


def chord_error_px(ax, f, n):
    """The largest vertical distance, in pixels, between the chord of two consecutive samples of y = f(x) over the
    axes' x range and the curve at the chord's middle (rule 12)."""
    pts = sample_explicit(f, ax.x_min, ax.x_max, n)
    worst = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        xm = 0.5 * (x0 + x1)
        _, chord = to_pixel(ax, xm, 0.5 * (y0 + y1))
        _, curve = to_pixel(ax, xm, f(xm))
        worst = max(worst, abs(chord - curve))
    return worst


# ---------------------------------------------------------------------------------------------- 2. clipping

def _clip_segment(p, q, x0, y0, x1, y1):
    """The part of segment p–q inside [x0, x1] × [y0, y1], or None. Each boundary cut sets the cut coordinate to the
    boundary value exactly, so the ends of the clipped parts of neighbouring segments coincide."""
    def cut(a, b, axis, bound, keep_below):
        # clip a–b against the half-plane coord[axis] <= bound (keep_below) or >= bound
        ca, cb = a[axis], b[axis]
        ina = ca <= bound if keep_below else ca >= bound
        inb = cb <= bound if keep_below else cb >= bound
        if ina and inb:
            return a, b
        if not ina and not inb:
            return None
        t = (bound - ca) / (cb - ca)
        other = 1 - axis
        oc = a[other] + t * (b[other] - a[other])
        cross = (bound, oc) if axis == 0 else (oc, bound)
        return (a, cross) if ina else (cross, b)
    seg = (p, q)
    for axis, bound, keep_below in ((0, x0, False), (0, x1, True), (1, y0, False), (1, y1, True)):
        seg = cut(seg[0], seg[1], axis, bound, keep_below)
        if seg is None:
            return None
    return seg


def clip_polyline(points, x0, y0, x1, y1):
    """Rule 2: the polyline clipped to the box [x0, x1] × [y0, y1]: a tuple of subpaths, one per run of the
    polyline inside the box."""
    parts, cur = [], []
    for p, q in zip(points, points[1:]):
        seg = _clip_segment(p, q, x0, y0, x1, y1)
        if seg is None:
            continue
        a, b = seg
        if cur and cur[-1] == a:
            cur.append(b)
        else:
            if cur:
                parts.append(tuple(cur))
            cur = [a, b]
    if cur:
        parts.append(tuple(cur))
    return tuple(parts)


# ------------------------------------------------------------------------------------- 8. marching squares

def marching_squares(f, ranges, resolution, level=0.0):
    """Rule 8: the polylines of f(x, y) = level over ranges = (x0, x1, y0, y1) on a resolution × resolution grid of
    cells. A corner is *below* when f − level < 0. A crossing on an edge is placed by linear interpolation from
    the edge's lower (or left) corner; the two cells that share an edge share its crossing. The saddle cases
    (two opposite corners below) are resolved by the mean of the four corner values: when it is below, the two
    below corners are joined. A cell with a non-finite corner value draws nothing. Segments with a common
    endpoint are joined into polylines; a loop's last point repeats its first."""
    x0, x1, y0, y1 = ranges
    if resolution < 1:
        raise ValueError("resolution: at least 1")
    if not (x1 > x0 and y1 > y0):
        raise ValueError("ranges: x0 < x1 and y0 < y1")
    n = resolution
    xs = [x0 + i * (x1 - x0) / n for i in range(n + 1)]
    ys = [y0 + j * (y1 - y0) / n for j in range(n + 1)]
    v = [[f(xs[i], ys[j]) - level for j in range(n + 1)] for i in range(n + 1)]
    crossings = {}

    def crossing(i, j, horizontal):
        key = (i, j, horizontal)
        if key not in crossings:
            if horizontal:                       # edge from (i, j) to (i + 1, j)
                va, vb = v[i][j], v[i + 1][j]
                t = va / (va - vb)
                crossings[key] = (xs[i] + t * (xs[i + 1] - xs[i]), ys[j])
            else:                                # edge from (i, j) to (i, j + 1)
                va, vb = v[i][j], v[i][j + 1]
                t = va / (va - vb)
                crossings[key] = (xs[i], ys[j] + t * (ys[j + 1] - ys[j]))
        return crossings[key]

    segments = []
    for i in range(n):
        for j in range(n):
            va, vb, vc, vd = v[i][j], v[i + 1][j], v[i + 1][j + 1], v[i][j + 1]      # a bottom-left, counter-clockwise
            if not all(math.isfinite(c) for c in (va, vb, vc, vd)):
                continue
            below = tuple(c < 0 for c in (va, vb, vc, vd))
            ab = lambda: crossing(i, j, True)            # noqa: E731
            bc = lambda: crossing(i + 1, j, False)       # noqa: E731
            cd = lambda: crossing(i, j + 1, True)        # noqa: E731
            da = lambda: crossing(i, j, False)           # noqa: E731
            k = sum(below)
            if k == 0 or k == 4:
                continue
            if k == 1 or k == 3:
                corner = below.index(True) if k == 1 else below.index(False)
                pair = ((da, ab), (ab, bc), (bc, cd), (cd, da))[corner]
                segments.append((pair[0](), pair[1]()))
            elif below in ((True, True, False, False), (False, False, True, True)):
                segments.append((da(), bc()))
            elif below in ((False, True, True, False), (True, False, False, True)):
                segments.append((ab(), cd()))
            else:                                                   # saddle: a,c or b,d below
                centre_below = (va + vb + vc + vd) / 4 < 0
                join_ac = below[0] == centre_below                  # the below corners connect through the centre
                if join_ac:
                    segments.append((ab(), bc()))                   # isolate b
                    segments.append((cd(), da()))                   # isolate d
                else:
                    segments.append((da(), ab()))                   # isolate a
                    segments.append((bc(), cd()))                   # isolate c
    return _join(segments)


def _join(segments):
    by_point = {}
    for idx, (p, q) in enumerate(segments):
        by_point.setdefault(p, []).append(idx)
        by_point.setdefault(q, []).append(idx)
    used = [False] * len(segments)

    def take(point):
        for idx in by_point.get(point, ()):
            if not used[idx]:
                used[idx] = True
                p, q = segments[idx]
                return q if p == point else p
        return None

    lines = []
    for idx, (p, q) in enumerate(segments):
        if used[idx]:
            continue
        used[idx] = True
        chain = [p, q]
        while True:
            nxt = take(chain[-1])
            if nxt is None:
                break
            chain.append(nxt)
            if nxt == chain[0]:
                break
        if chain[-1] != chain[0]:
            while True:
                prv = take(chain[0])
                if prv is None:
                    break
                chain.insert(0, prv)
        lines.append(tuple(chain))
    return tuple(lines)


# ----------------------------------------------------------------------------------- 10. 3D axes and tubes

@dataclass(frozen=True)
class Axes3D:
    """A 3D axes: data ranges and the box size in scene units, centred on the object's origin."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    width: float
    height: float
    depth: float

    def __post_init__(self):
        if not (self.x_min < self.x_max and self.y_min < self.y_max and self.z_min < self.z_max):
            raise ValueError("axes3D: each min is below its max")
        if not (self.width > 0 and self.height > 0 and self.depth > 0):
            raise ValueError("axes3D: width, height and depth are positive")


def to_scene(ax, x, y, z):
    """Rule 10: data to the object's local scene units, the data centre at the origin; +y data is up, which is −y
    in scene space (CONVENTIONS 2.1); +z data is away from the camera."""
    sx = (x - (ax.x_min + ax.x_max) / 2) / (ax.x_max - ax.x_min) * ax.width
    sy = -(y - (ax.y_min + ax.y_max) / 2) / (ax.y_max - ax.y_min) * ax.height
    sz = (z - (ax.z_min + ax.z_max) / 2) / (ax.z_max - ax.z_min) * ax.depth
    return sx, sy, sz


def _unit(v):
    n = math.hypot(*v)
    return tuple(c / n for c in v) if n else None


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def tube_frames(points):
    """Rule 10: the parallel-transport frame (T, N, B) at each point of a polyline. T_i is the unit central
    difference (one-sided at the ends; the previous tangent where it vanishes). N₀ is the unit part, normal to T₀,
    of the coordinate axis least aligned with T₀; N_i is N_{i−1} made normal to T_i and renormalised; B = T × N."""
    pts = [tuple(float(c) for c in p) for p in points]
    if len(pts) < 2 or all(p == pts[0] for p in pts):
        raise ValueError("tube: at least two distinct points")
    tangents = []
    prev = None
    for i in range(len(pts)):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, len(pts) - 1)]
        t = _unit(tuple(bb - aa for aa, bb in zip(a, b)))
        if t is None:
            t = prev
        if t is None:                                   # leading repeated points: look ahead
            for j in range(i + 1, len(pts)):
                t = _unit(tuple(bb - aa for aa, bb in zip(pts[i], pts[j])))
                if t is not None:
                    break
        tangents.append(t)
        prev = t
    t0 = tangents[0]
    axis = min(range(3), key=lambda k: abs(t0[k]))
    e = tuple(1.0 if k == axis else 0.0 for k in range(3))
    n = _unit(tuple(ec - _dot(e, t0) * tc for ec, tc in zip(e, t0)))
    frames = []
    for t in tangents:
        n = _unit(tuple(nc - _dot(n, t) * tc for nc, tc in zip(n, t))) or n
        frames.append((t, n, _cross(t, n)))
    return frames


def tube(points, radius, segments=DEFAULT_TUBE_SEGMENTS):
    """Rule 10: the vertex rings of a tube of `radius` around the polyline: ring i has `segments` vertices
    p_i + radius·(cos φ_j N_i + sin φ_j B_i), φ_j = 2πj/segments. The rings form a parametricSurface grid closed
    in the ring direction (SREP 70 rule 3)."""
    if not (radius > 0):
        raise ValueError("tube: radius > 0")
    if segments < 3:
        raise ValueError("tube: at least 3 segments")
    frames = tube_frames(points)
    rings = []
    for p, (_, n, b) in zip(points, frames):
        ring = []
        for j in range(segments):
            phi = 2 * math.pi * j / segments
            c, s = math.cos(phi), math.sin(phi)
            ring.append(tuple(pc + radius * (c * nc + s * bc) for pc, nc, bc in zip(p, n, b)))
        rings.append(tuple(ring))
    return tuple(rings)


# -------------------------------------------------------------------------------------- the numeric table

AX = "Axes(x_min=-1.0, x_max=1.0, y_min=-1.0, y_max=1.0, width=400.0, height=300.0)"
AX3 = "Axes3D(x_min=-1.0, x_max=1.0, y_min=-1.0, y_max=1.0, z_min=0.0, z_max=2.0, width=200.0, height=200.0, depth=400.0)"
CIRCLE = "marching_squares(lambda x, y: x * x + y * y - 1.0, (-1.2, 1.2, -1.2, 1.2), 64)"
TABLE = [
    ("nice step 0 to 10", "nice_step(0.0, 10.0)"),
    ("nice step 0 to 1", "nice_step(0.0, 1.0)"),
    ("nice step -3 to 3", "nice_step(-3.0, 3.0)"),
    ("nice step 0 to 25", "nice_step(0.0, 25.0)"),
    ("nice step 0 to 7", "nice_step(0.0, 7.0)"),
    ("nice step 0.5 to 0.9", "nice_step(0.5, 0.9)"),
    ("ticks", "ticks(-1.0, 1.0, 0.5)"),
    ("ticks inside", "ticks(0.1, 0.9, 0.25)"),
    ("ticks at the edge", "ticks(0.0, 0.3, 0.1)"),
    ("label decimals", "(label_decimals(1.0), label_decimals(0.5), label_decimals(0.25), label_decimals(0.001))"),
    ("label integer", "tick_label(1.0, 0.5)"),
    ("label negative", "tick_label(-0.5, 0.5)"),
    ("label two decimals", "tick_label(0.75, 0.25)"),
    ("label imaginary", "tick_label(2.0, 1.0, True)"),
    ("label minus i", "tick_label(-1.0, 1.0, True)"),
    ("label imaginary zero", "tick_label(0.0, 1.0, True)"),
    ("label negative zero", "tick_label(-0.0, 0.5)"),
    ("axis at zero", "axis_position(-1.0, 1.0)"),
    ("axis at the edge", "axis_position(2.0, 5.0)"),
    ("to pixel", f"to_pixel({AX}, 0.5, 0.5)"),
    ("from pixel", f"from_pixel({AX}, 300.0, 75.0)"),
    ("explicit samples", "sample_explicit(lambda x: x * x, 0.0, 1.0, 5)"),
    ("parametric closed", "tuple((round(x, 12), round(y, 12)) for x, y in sample_parametric(math.cos, math.sin, 0.0, 2 * math.pi, 4, closed=True))"),
    ("polar", "tuple((round(x, 12), round(y, 12)) for x, y in sample_polar(lambda th: 1.0, 0.0, math.pi, 3))"),
    ("split at a pole", "split_finite(sample_explicit(lambda x: 1.0 / x if x else math.inf, -1.0, 1.0, 5))"),
    ("clip a line", "clip_polyline(((-1.0, 0.5), (3.0, 0.5)), 0.0, 0.0, 2.0, 1.0)"),
    ("clip into subpaths", "clip_polyline(((0.5, -1.0), (0.5, 0.5), (0.5, 2.0), (1.5, 2.0), (1.5, 0.5)), 0.0, 0.0, 2.0, 1.0)"),
    ("marching squares line", "marching_squares(lambda x, y: x + y - 1.5, (0.0, 2.0, 0.0, 2.0), 2)"),
    ("marching squares circle", f"(len({CIRCLE}), len({CIRCLE}[0]), {CIRCLE}[0][0] == {CIRCLE}[0][-1])"),
    ("marching squares circle error px", f"round(max(abs(math.hypot(x, y) - 1.0) for x, y in {CIRCLE}[0]) * 300.0 / 2.4, 6)"),
    ("marching squares saddle", "len(marching_squares(lambda x, y: x * y - 0.1, (-1.0, 1.0, -1.0, 1.0), 1))"),
    ("chord error of a sine", "round(chord_error_px(Axes(x_min=-math.pi, x_max=math.pi, y_min=-1.5, y_max=1.5, width=500.0, height=300.0), math.sin, 256), 6)"),
    ("to scene", f"to_scene({AX3}, 1.0, 1.0, 2.0)"),
    ("tube frame straight", "tube_frames([(0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 2.0)])[1]"),
    ("tube ring", "tuple(round(c, 12) for c in tube([(0.0, 0.0, 0.0), (0.0, 0.0, 1.0)], 0.5, 4)[0][1])"),
]


def main():
    scope = {k: v for k, v in globals().items() if not k.startswith("_")}
    scope["math"] = math
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "max": max}
    print("| Test | Expression | Expected |")
    print("|---|---|---|")
    for name, expr in TABLE:
        got = eval(expr, scope)
        print(f"| {name} | `{expr}` | `{got!r}` |")


if __name__ == "__main__":
    main()
