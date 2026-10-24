#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add space transforms" (srep/srep-0000-space-transforms.md; MF2 of
SREP 12): the matrix, expression and complex-function deform modifiers as point maps, the adaptive subdivision
of an outline under a map, the break at non-finite points, the conformality check, the stereographic projection
of the 3-sphere and the Penrose compactification. Standard library only.

    python3 space_transforms_reference.py        # prints the SREP's numeric-test table

Every function is a pure function of its arguments. Section numbers refer to the SREP's Semantics.
"""
import cmath
import math

DEFAULT_TOLERANCE = 0.25        # pixels: the mapped chord error a subdivided segment may keep (rule 4)
MAX_DEPTH = 10                  # a segment is split at most this many times along any branch (rule 4)
COMPLEX_KINDS = ("square", "cube", "inverse", "exp", "log", "sqrt", "sin", "cos", "mobius", "joukowski")


# ------------------------------------------------------------------------------------------- 1. matrix

def matrix_map(m, p, center=(0.0, 0.0)):
    """Rule 1: type="matrix": the SVG matrix (a, b, c, d, e, f) about `center`:
    x' = cx + a (x − cx) + c (y − cy) + e, y' = cy + b (x − cx) + d (y − cy) + f."""
    a, b, c, d, e, f = (float(v) for v in m)
    cx, cy = center
    x, y = p[0] - cx, p[1] - cy
    return (cx + a * x + c * y + e, cy + b * x + d * y + f)


def grid_nodes(cols, rows, box):
    """The cols × rows nodes of a regular grid over box = (x0, y0, x1, y1), row-major from the top-left."""
    if cols < 2 or rows < 2:
        raise ValueError("grid: at least 2 columns and 2 rows")
    x0, y0, x1, y1 = box
    return tuple((x0 + i * (x1 - x0) / (cols - 1), y0 + j * (y1 - y0) / (rows - 1))
                 for j in range(rows) for i in range(cols))


# --------------------------------------------------------------------------------------- 2. expressions

def expr_map(fu, fv, p, center=(0.0, 0.0), unit=1.0):
    """Rule 2: type="map": the pixel p is read as data (u, v) = ((x − cx)/unit, (cy − y)/unit), +v up as on an
    axes (the plots SREP, rule 1); the expressions give (u', v') and the pixel is (cx + unit·u', cy − unit·v')."""
    if not (unit > 0):
        raise ValueError("unit: positive")
    cx, cy = center
    u, v = (p[0] - cx) / unit, (cy - p[1]) / unit
    return (cx + unit * fu(u, v), cy - unit * fv(u, v))


# ---------------------------------------------------------------------------------- 3. complex functions

def _finite(w):
    return math.isfinite(w.real) and math.isfinite(w.imag)


def complex_function(kind, z, coefficients=()):
    """Rule 3: w = f(z) for the named function; mobius reads coefficients (a, b, c, d) as eight reals, real and
    imaginary parts in turn, and ad − bc = 0 is an error. A pole gives a non-finite w (never an exception)."""
    try:
        if kind == "square":
            return z * z
        if kind == "cube":
            return z * z * z
        if kind == "inverse":
            return 1 / z
        if kind == "exp":
            return cmath.exp(z)
        if kind == "log":
            return cmath.log(z)
        if kind == "sqrt":
            return cmath.sqrt(z)
        if kind == "sin":
            return cmath.sin(z)
        if kind == "cos":
            return cmath.cos(z)
        if kind == "joukowski":
            return z + 1 / z
        if kind == "mobius":
            if len(coefficients) != 8:
                raise ValueError("mobius: eight coefficients a, b, c, d as real, imaginary pairs")
            a, b, c, d = (complex(coefficients[i], coefficients[i + 1]) for i in range(0, 8, 2))
            if a * d - b * c == 0:
                raise ValueError("mobius: ad - bc must not be 0")
            return (a * z + b) / (c * z + d)
    except (ZeroDivisionError, OverflowError):
        return complex(math.inf, math.inf)
    raise ValueError(f"unknown complex function {kind!r}")


def complex_map(kind, p, center=(0.0, 0.0), unit=1.0, coefficients=()):
    """Rule 3: type="complex": the expression map with z = u + iv and (u', v') = (Re w, Im w)."""
    def fu(u, v):
        return complex_function(kind, complex(u, v), coefficients).real

    def fv(u, v):
        return complex_function(kind, complex(u, v), coefficients).imag
    return expr_map(fu, fv, p, center, unit)


# ----------------------------------------------------------------------------- 4. adaptive subdivision

def _ok(q):
    return all(math.isfinite(c) for c in q)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def subdivide_segment(f, p, q, tol=DEFAULT_TOLERANCE, max_depth=MAX_DEPTH):
    """Rule 4: the source points, p to q inclusive, at which the segment is sampled so that, at every kept
    sub-segment, the map of its midpoint is within `tol` pixels of the midpoint of its mapped ends. A segment
    is split at its parameter midpoint, recursively, at most max_depth times along any branch; a segment with
    a non-finite mapped end or midpoint is split too (down to the bound), so the break lands within 2^−max_depth
    of the pole."""
    if not (tol > 0):
        raise ValueError("tolerance: positive")
    out = [tuple(p)]

    def rec(a, b, fa, fb, depth):
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        fm = f(m)
        split = depth < max_depth and (not (_ok(fa) and _ok(fb) and _ok(fm))
                                       or _dist(fm, ((fa[0] + fb[0]) / 2, (fa[1] + fb[1]) / 2)) > tol)
        if split:
            rec(a, m, fa, fm, depth + 1)
            rec(m, b, fm, fb, depth + 1)
        else:
            out.append(tuple(b))
    rec(tuple(p), tuple(q), f(p), f(q), 0)
    return tuple(out)


def chord_error(f, points):
    """The largest distance between the map of a sub-segment's midpoint and the midpoint of its mapped ends."""
    worst = 0.0
    for a, b in zip(points, points[1:]):
        fa, fb, fm = f(a), f(b), f(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        worst = max(worst, _dist(fm, ((fa[0] + fb[0]) / 2, (fa[1] + fb[1]) / 2)))
    return worst


def deform_polyline(f, points, tol=DEFAULT_TOLERANCE, closed=False, max_depth=MAX_DEPTH):
    """Rule 5: the polyline under the map: each segment subdivided by rule 4 and mapped; a non-finite mapped
    point is dropped and breaks the path (SREP 70), so the result is a tuple of subpaths. A closed polyline
    maps its closing segment and, when unbroken, ends on its first mapped point."""
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        raise ValueError("polyline: at least two points")
    if closed:
        pts.append(pts[0])
    source = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        source.extend(subdivide_segment(f, a, b, tol, max_depth)[1:])
    parts, cur = [], []
    for s in source:
        w = f(s)
        if _ok(w):
            cur.append(w)
        elif cur:
            parts.append(tuple(cur))
            cur = []
    if cur:
        parts.append(tuple(cur))
    return tuple(parts)


# ----------------------------------------------------------------------------------- 6. conformality

def tangent_angle(f, p, d1, d2, h=1e-6):
    """Rule 6 (the test of a conformal map): the angle in degrees between the images of the directions d1 and
    d2 at p, from central differences of step h along each."""
    def image(d):
        n = math.hypot(*d)
        dx, dy = d[0] / n * h, d[1] / n * h
        a, b = f((p[0] - dx, p[1] - dy)), f((p[0] + dx, p[1] + dy))
        return (b[0] - a[0], b[1] - a[1])
    e1, e2 = image(d1), image(d2)
    dot = e1[0] * e2[0] + e1[1] * e2[1]
    n1, n2 = math.hypot(*e1), math.hypot(*e2)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / (n1 * n2)))))


# -------------------------------------------------------------------- 7. projections and diagrams

def stereographic(p):
    """Rule 7: the point (x, y, z, w) of the 3-sphere projected from the pole w = 1 onto w = 0:
    (x, y, z)/(1 − w); the pole itself is non-finite."""
    x, y, z, w = p
    d = 1.0 - w
    if d == 0.0:
        return (math.inf, math.inf, math.inf)
    return (x / d, y / d, z / d)


def inverse_stereographic(q):
    """Rule 7: the point of the 3-sphere that projects to (x, y, z): (2x, 2y, 2z, r² − 1)/(r² + 1)."""
    x, y, z = q
    r2 = x * x + y * y + z * z
    return (2 * x / (r2 + 1), 2 * y / (r2 + 1), 2 * z / (r2 + 1), (r2 - 1) / (r2 + 1))


def penrose(t, x):
    """Rule 8: the Penrose compactification of 1+1 Minkowski space: with u = t − x and v = t + x,
    T = (atan v + atan u)/2 and X = (atan v − atan u)/2, so light rays stay at 45° and infinity is the
    diamond's edge |T| + |X| = π/2."""
    au, av = math.atan(t - x), math.atan(t + x)
    return ((av + au) / 2, (av - au) / 2)


# -------------------------------------------------------------------------------------- the numeric table

SQ = "lambda p: complex_map('square', p, unit=100.0)"
INV = "lambda p: complex_map('inverse', p, unit=10.0)"
TABLE = [
    ("matrix identity", "matrix_map((1, 0, 0, 1, 0, 0), (3.0, 4.0))"),
    ("matrix svg order", "matrix_map((2, 0, 0, 3, 10, 20), (1.0, 1.0))"),
    ("matrix rotation", "matrix_map((0, 1, -1, 0, 0, 0), (1.0, 0.0))"),
    ("matrix about the centre", "matrix_map((2, 0, 0, 2, 0, 0), (110.0, 60.0), center=(100.0, 50.0))"),
    ("matrix shear of a grid node", "matrix_map((1.0, 0.5, 0.25, 1.0, 0.0, 0.0), grid_nodes(5, 3, (0.0, 0.0, 400.0, 200.0))[7])"),
    ("grid nodes", "grid_nodes(3, 2, (0.0, 0.0, 100.0, 50.0))"),
    ("expression map z squared", "expr_map(lambda u, v: u * u - v * v, lambda u, v: 2 * u * v, (150.0, 50.0), center=(100.0, 100.0), unit=50.0)"),
    ("expression map y up", "expr_map(lambda u, v: u, lambda u, v: v + 1, (0.0, 0.0))"),
    ("complex square", "complex_function('square', complex(1, 2))"),
    ("complex inverse", "complex_function('inverse', complex(0, 2))"),
    ("complex exp", "tuple(round(c, 12) for c in (complex_function('exp', complex(0, math.pi)).real, complex_function('exp', complex(0, math.pi)).imag))"),
    ("complex log", "complex_function('log', complex(-1, 0))"),
    ("complex sqrt", "complex_function('sqrt', complex(-4, 0))"),
    ("complex joukowski", "complex_function('joukowski', complex(2, 0))"),
    ("complex mobius", "complex_function('mobius', complex(0, 0), (1, 0, 0, 1, 0, 1, 1, 0))"),
    ("complex pole", "tuple(math.isfinite(c) for c in (complex_function('inverse', complex(0, 0)).real, complex_function('inverse', complex(0, 0)).imag))"),
    ("complex map", "complex_map('square', (150.0, 50.0), center=(100.0, 100.0), unit=50.0)"),
    ("conformal square", f"round(tangent_angle({SQ}, (30.0, -20.0), (1.0, 0.0), (0.0, 1.0)), 5)"),
    ("conformal exp", "round(tangent_angle(lambda p: complex_map('exp', p, unit=100.0), (30.0, -20.0), (1.0, 0.0), (0.0, 1.0)), 5)"),
    ("not conformal", "round(tangent_angle(lambda p: expr_map(lambda u, v: u, lambda u, v: 2 * v, p), (1.0, 1.0), (1.0, 1.0), (1.0, -1.0)), 5)"),
    ("no subdivision under a matrix", "subdivide_segment(lambda p: matrix_map((2, 0.5, 0, 1, 0, 0), p), (0.0, 0.0), (100.0, 100.0), 0.25)"),
    ("subdivision count", f"len(subdivide_segment({SQ}, (0.0, 0.0), (100.0, 0.0), 0.25))"),
    ("subdivision within tolerance", f"chord_error({SQ}, subdivide_segment({SQ}, (0.0, 0.0), (100.0, 0.0), 0.25)) <= 0.25"),
    ("subdivision bound", "len(subdivide_segment(lambda p: (p[0], 1000.0 * math.sin(p[0] * 1000.0)), (0.0, 0.0), (1.0, 0.0), 1e-9))"),
    ("polyline translated", "deform_polyline(lambda p: matrix_map((1, 0, 0, 1, 5, 5), p), ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)), 0.25)"),
    ("polyline closed", "deform_polyline(lambda p: matrix_map((1, 0, 0, 1, 0, 0), p), ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)), 0.25, closed=True)"),
    ("polyline broken at a pole", f"len(deform_polyline({INV}, ((-20.0, 0.0), (0.0, 0.0), (20.0, 0.0)), 0.25))"),
    ("stereographic equator", "stereographic((1.0, 0.0, 0.0, 0.0))"),
    ("stereographic south pole", "stereographic((0.0, 0.0, 0.0, -1.0))"),
    ("stereographic circle through the pole", "round(stereographic((0.0, 0.0, math.sin(1.0), math.cos(1.0)))[2], 12)"),
    ("inverse stereographic", "inverse_stereographic((0.5, -0.25, 0.75))"),
    ("penrose origin of time", "penrose(1.0, 0.0)"),
    ("penrose light ray", "round(penrose(3.0, 2.0)[0] - penrose(3.0, 2.0)[1], 12) == round(penrose(-1.0, -2.0)[0] - penrose(-1.0, -2.0)[1], 12)"),
    ("penrose infinity", "tuple(round(c, 9) for c in penrose(1e12, 0.0))"),
]


def main():
    scope = {k: v for k, v in globals().items() if not k.startswith("_")}
    scope["math"] = math
    scope["cmath"] = cmath
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "max": max, "complex": complex}
    print("| Test | Expression | Expected |")
    print("|---|---|---|")
    for name, expr in TABLE:
        got = eval(expr, scope)
        print(f"| {name} | `{expr}` | `{got!r}` |")


if __name__ == "__main__":
    main()
