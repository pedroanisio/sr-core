#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add fields and flow" (srep/srep-0000-fields.md), written from the
SREP text and from the published methods it names (Jobard and Lefer 1997; Cabral and Leedom 1993; Wegert 2012),
not from an engine. A field is a Python callable (x, y) -> (u, v) in the data frame (+v up); every other function
is a pure function of its arguments. tests/test_fields.py checks the rules and the SREP's numeric table against
this module.

Usage: python3 fields_reference.py  (prints the numeric-test table of the SREP). Standard library only.
"""
import cmath
import math

DEFAULT_MAX_STEPS = 10_000      # rule 4: the step bound of one streamline
DEFAULT_MAX_LINES = 10_000      # rule 6: the bound on the number of streamlines
DIFF_H = 1e-4                   # rule 3: the central-difference step, in data units
HEAD_LENGTH = 0.3               # rule 5: head length as a fraction of the shaft
HEAD_WIDTH = 0.5                # rule 5: head half-width as a fraction of the head length
WINDING_SAMPLES = 256           # rule 9: samples around the circle


# --- rule 2: sources -------------------------------------------------------------------------------------------

def grid_sampler(values, ranges):
    """A grid field: `values` is rows of (u, v) nodes, row j at y = y0 + j (y1 - y0) / (rows - 1) and column i at
    x = x0 + i (x1 - x0) / (cols - 1) over ranges = (x0, y0, x1, y1); bilinear between the nodes, (0, 0) outside
    the box."""
    rows = tuple(tuple((float(u), float(v)) for u, v in row) for row in values)
    if len(rows) < 2 or any(len(r) < 2 for r in rows) or len({len(r) for r in rows}) != 1:
        raise ValueError("a grid has at least two rows of at least two nodes, all rows of one length")
    x0, y0, x1, y1 = ranges
    nx, ny = len(rows[0]), len(rows)

    def sample(x, y):
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return (0.0, 0.0)
        fx = (x - x0) / (x1 - x0) * (nx - 1)
        fy = (y - y0) / (y1 - y0) * (ny - 1)
        i, j = min(int(fx), nx - 2), min(int(fy), ny - 2)
        s, t = fx - i, fy - j
        a, b = rows[j][i], rows[j][i + 1]
        c, d = rows[j + 1][i], rows[j + 1][i + 1]
        return tuple((a[k] * (1 - s) + b[k] * s) * (1 - t) + (c[k] * (1 - s) + d[k] * s) * t for k in (0, 1))
    return sample


def complex_sampler(f):
    """A complex function as a vector field: (x, y) -> (Re f(z), Im f(z)) with z = x + i y."""
    def sample(x, y):
        w = f(complex(x, y))
        return (w.real, w.imag)
    return sample


def charge_field(charges, p):
    """The Coulomb field of point charges ((x, y, q), ...) in the plane through them: sum of q r / |r|^3 with
    r = p - c (the constant is 1); (0, 0) at a charge."""
    ex = ey = 0.0
    for cx, cy, q in charges:
        rx, ry = p[0] - cx, p[1] - cy
        r = math.hypot(rx, ry)
        if r == 0.0:
            return (0.0, 0.0)
        ex += q * rx / r ** 3
        ey += q * ry / r ** 3
    return (ex, ey)


def dipole_field(p, m=(0.0, 1.0), center=(0.0, 0.0)):
    """The field of a point dipole m at `center` in the plane of its axis: (3 (m . r^) r^ - m) / r^3."""
    rx, ry = p[0] - center[0], p[1] - center[1]
    r = math.hypot(rx, ry)
    if r == 0.0:
        return (0.0, 0.0)
    ux, uy = rx / r, ry / r
    dot = m[0] * ux + m[1] * uy
    return ((3.0 * dot * ux - m[0]) / r ** 3, (3.0 * dot * uy - m[1]) / r ** 3)


def wire_field(p, current=1.0, center=(0.0, 0.0)):
    """The field of a straight current out of the plane at `center`: current / (2 pi r) counterclockwise."""
    rx, ry = p[0] - center[0], p[1] - center[1]
    r2 = rx * rx + ry * ry
    if r2 == 0.0:
        return (0.0, 0.0)
    k = current / (2.0 * math.pi * r2)
    return (-ry * k, rx * k)


def source_field(p, center=(0.0, 0.0)):
    """A 2D point source: r / |r|^2."""
    rx, ry = p[0] - center[0], p[1] - center[1]
    r2 = rx * rx + ry * ry
    return (0.0, 0.0) if r2 == 0.0 else (rx / r2, ry / r2)


def vortex_field(p, center=(0.0, 0.0)):
    """A 2D point vortex: (-y, x) / |r|^2, counterclockwise."""
    rx, ry = p[0] - center[0], p[1] - center[1]
    r2 = rx * rx + ry * ry
    return (0.0, 0.0) if r2 == 0.0 else (-ry / r2, rx / r2)


def poynting(e, b):
    """E x B for an in-plane E and an out-of-plane B (a number): (Ey B, -Ex B)."""
    return (e[1] * b, -e[0] * b)


def line_field(p, a, b, q=0.0, i=0.0):
    """A straight wire in the plane from a to b carrying the charge q per unit length and the current i (from a
    to b): the in-plane E of the finite line charge (Griffiths example 2.1, constant 1) and the out-of-plane B
    of the segment (Biot-Savart, Griffiths example 5.5, constant 1), as (Ex, Ey, Bz); (0, 0, 0) on the wire's
    line. With t the direction a -> b, n its left normal, s the position along the wire and d the signed
    distance from its line (positive on the left), the perpendicular factor is
    ((L - s) / sqrt((L - s)^2 + d^2) + s / sqrt(s^2 + d^2)) / d: E = q (factor n + (1 / sqrt(s^2 + d^2) -
    1 / sqrt((L - s)^2 + d^2)) t) and Bz = i factor / (4 pi), so a long wire gives i / (2 pi d), the point
    current's magnitude."""
    tx, ty = b[0] - a[0], b[1] - a[1]
    length = math.sqrt(tx * tx + ty * ty)
    tx, ty = tx / length, ty / length
    nx, ny = -ty, tx
    px, py = p[0] - a[0], p[1] - a[1]
    s, d = px * tx + py * ty, px * nx + py * ny
    if d == 0.0:
        return (0.0, 0.0, 0.0)
    r1, r2 = math.sqrt(s * s + d * d), math.sqrt((length - s) * (length - s) + d * d)
    perp = ((length - s) / r2 + s / r1) / d
    par = 1.0 / r1 - 1.0 / r2
    return (q * (perp * nx + par * tx), q * (perp * ny + par * ty), i * perp / (4.0 * math.pi))


# shot 2 (Veritasium): a loop of two wires, the top one charged +1 carrying the current 1 to the right, the
# bottom one charged -1 carrying it back; each wire is (a, b, q, i)
SHOT2_WIRES = (((-1.0, 0.5), (1.0, 0.5), 1.0, 1.0), ((1.0, -0.5), (-1.0, -0.5), -1.0, 1.0))


def poynting_at(p, charges, dipoles, wires):
    """The Poynting vector at p: E the sum of the charges ((x, y, q)), dipoles ((x, y, mx, my)) and the wires'
    line charges, Bz the sum of the wires' currents (line_field), as poynting(E, Bz)."""
    ex, ey = charge_field(charges, p) if charges else (0.0, 0.0)
    for x, y, mx, my in dipoles:
        dx, dy = dipole_field(p, (mx, my), (x, y))
        ex, ey = ex + dx, ey + dy
    bz = 0.0
    for a, b, q, i in wires:
        wx, wy, wb = line_field(p, a, b, q, i)
        ex, ey, bz = ex + wx, ey + wy, bz + wb
    return poynting((ex, ey), bz)


def poynting_angle(p, charges, dipoles, wires):
    """The direction of the Poynting vector at p in degrees from +x."""
    sx, sy = poynting_at(p, charges, dipoles, wires)
    return math.degrees(math.atan2(sy, sx))


# --- rule 3: operators -------------------------------------------------------------------------------------------

def divergence(f, p, h=DIFF_H):
    """du/dx + dv/dy by central differences of step h."""
    x, y = p
    return (f(x + h, y)[0] - f(x - h, y)[0]) / (2 * h) + (f(x, y + h)[1] - f(x, y - h)[1]) / (2 * h)


def curl(f, p, h=DIFF_H):
    """dv/dx - du/dy by central differences of step h (positive counterclockwise)."""
    x, y = p
    return (f(x + h, y)[1] - f(x - h, y)[1]) / (2 * h) - (f(x, y + h)[0] - f(x, y - h)[0]) / (2 * h)


# --- rule 4: streamlines ---------------------------------------------------------------------------------------

def _unit(f, p):
    u, v = f(p[0], p[1])
    n = math.hypot(u, v)
    if n == 0.0 or not math.isfinite(n):
        return None
    return (u / n, v / n)


def rk4_step(f, p, h):
    """One Runge-Kutta 4 step of length h along the unit direction of f, so h is arc length; None where f is
    zero or not finite at any stage."""
    k1 = _unit(f, p)
    if k1 is None:
        return None
    k2 = _unit(f, (p[0] + 0.5 * h * k1[0], p[1] + 0.5 * h * k1[1]))
    if k2 is None:
        return None
    k3 = _unit(f, (p[0] + 0.5 * h * k2[0], p[1] + 0.5 * h * k2[1]))
    if k3 is None:
        return None
    k4 = _unit(f, (p[0] + h * k3[0], p[1] + h * k3[1]))
    if k4 is None:
        return None
    return (p[0] + h * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]) / 6.0,
            p[1] + h * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]) / 6.0)


def inside_box(ranges):
    """The predicate of a box (x0, y0, x1, y1), edges included."""
    x0, y0, x1, y1 = ranges
    return lambda p: x0 <= p[0] <= x1 and y0 <= p[1] <= y1


def _march(f, p0, h, max_steps, inside, stop, keep_stop=False):
    pts = []
    p = p0
    for _ in range(max_steps):
        q = rk4_step(f, p, h)
        if q is None or not inside(q):
            break
        if stop is not None and stop(q):
            if keep_stop:
                pts.append(q)
            break
        pts.append(q)
        p = q
    return pts


def streamline(f, p0, h, max_steps, inside, stop=None, both=True, keep_stop=False):
    """The polyline through p0: RK4 steps of length h forward (and backward when `both`) while the point is
    inside, the field is not zero and fewer than max_steps steps were taken each way. A point for which `stop`
    is true ends the line: it is left out, or kept as the last point when `keep_stop`."""
    if not h > 0.0:
        raise ValueError("the step is positive")
    if not (isinstance(max_steps, int) and max_steps >= 1):
        raise ValueError("the step bound is a positive integer")
    p0 = (float(p0[0]), float(p0[1]))
    fwd = _march(f, p0, h, max_steps, inside, stop, keep_stop)
    back = _march(f, p0, -h, max_steps, inside, stop, keep_stop) if both else []
    return tuple(reversed(back)) + (p0,) + tuple(fwd)


# --- rule 5: arrows ---------------------------------------------------------------------------------------------

def arrow(p, v, scale, max_length, head_length=HEAD_LENGTH, head_width=HEAD_WIDTH):
    """The glyph at p of vector v: a shaft from p of length min(|v| scale, max_length) along v, and a head
    (tip, left, right) whose length is head_length of the shaft and half-width head_width of that; None for a
    zero vector."""
    n = math.hypot(v[0], v[1])
    if n == 0.0 or not math.isfinite(n):
        return None
    length = min(n * scale, max_length)
    dx, dy = v[0] / n, v[1] / n
    tip = (p[0] + dx * length, p[1] + dy * length)
    hl = head_length * length
    hw = head_width * hl
    base = (tip[0] - dx * hl, tip[1] - dy * hl)
    left = (base[0] - dy * hw, base[1] + dx * hw)
    right = (base[0] + dy * hw, base[1] - dx * hw)
    return (((p[0], p[1]), tip), (tip, left, right))


def arrow_grid(f, ranges, cols, rows, scale, max_length):
    """The glyphs at the cols x rows nodes spanning ranges (edges included), row by row from y0."""
    if cols < 2 or rows < 2:
        raise ValueError("an arrow grid has at least two columns and two rows")
    x0, y0, x1, y1 = ranges
    out = []
    for j in range(rows):
        y = y0 + (y1 - y0) * j / (rows - 1)
        for i in range(cols):
            x = x0 + (x1 - x0) * i / (cols - 1)
            out.append(arrow((x, y), f(x, y), scale, max_length))
    return tuple(out)


# --- rule 6: evenly spaced streamlines (Jobard and Lefer 1997) ----------------------------------------------------

class _Buckets:
    """Points of accepted streamlines in cells of size d, with the line they belong to and their arc index, for
    nearest-point queries."""

    def __init__(self, d):
        self.d = d
        self.cells = {}

    def _key(self, p):
        return (math.floor(p[0] / self.d), math.floor(p[1] / self.d))

    def add(self, p, line, index=0):
        self.cells.setdefault(self._key(p), []).append((p, line, index))

    def nearest(self, p, line=None, index=0, lag=0):
        """The smallest distance from p to a stored point, where a point of `line` counts only when its arc
        index is at least `lag` away from `index` (inf when none within the neighbouring cells)."""
        kx, ky = self._key(p)
        best = math.inf
        for i in (kx - 1, kx, kx + 1):
            for j in (ky - 1, ky, ky + 1):
                for q, owner, k in self.cells.get((i, j), ()):
                    if owner is line and abs(k - index) < lag:
                        continue
                    best = min(best, math.hypot(p[0] - q[0], p[1] - q[1]))
        return best


def evenly_spaced_streamlines(f, ranges, d_sep, d_test=None, h=None, max_steps=DEFAULT_MAX_STEPS,
                              max_lines=DEFAULT_MAX_LINES, seed=None):
    """Jobard and Lefer 1997. The first streamline starts at `seed` (the box centre by default). A queue holds
    the accepted streamlines in order; for each, candidate seeds lie at d_sep on both sides of each of its
    points, and a candidate becomes a new streamline when it is inside the box, the field is not zero there,
    and it is at least d_sep from every point of every accepted streamline. When the queue is empty, the nodes
    of the grid of spacing d_sep from the box's corner (x0, y0), in row-major order, are tried as seeds under
    the same test, so that regions the first streamline does not reach are covered. A streamline is integrated
    by rule 4 both ways and stops when its next point is within d_test (d_sep / 2 by default) of a point of
    another streamline. h is d_sep / 4 by default. Bounded by max_lines streamlines and max_steps steps each
    way."""
    if not d_sep > 0.0:
        raise ValueError("the separation is positive")
    d_test = 0.5 * d_sep if d_test is None else d_test
    if not 0.0 < d_test <= d_sep:
        raise ValueError("the test distance is positive and at most the separation")
    h = d_sep / 4.0 if h is None else h
    if not (isinstance(max_lines, int) and max_lines >= 1):
        raise ValueError("the line bound is a positive integer")
    x0, y0, x1, y1 = ranges
    inside = inside_box(ranges)
    seed = ((x0 + x1) / 2.0, (y0 + y1) / 2.0) if seed is None else (float(seed[0]), float(seed[1]))
    buckets = _Buckets(d_sep)
    lines = []

    lag = int(math.ceil(d_sep / h)) + 1

    def trace(p0):
        """Rule 4's march from p0 each way; a step ends the line when its point is within d_test of a point of
        another streamline, or of this one at least `lag` steps away along the arc (a closed orbit)."""
        token = object()
        buckets.add(p0, token, 0)
        halves = []
        for sgn in (1.0, -1.0):
            pts = []
            p = p0
            for n in range(1, max_steps + 1):
                q = rk4_step(f, p, sgn * h)
                idx = int(sgn * n)
                if q is None or not inside(q) or buckets.nearest(q, token, idx, lag) < d_test:
                    break
                buckets.add(q, token, idx)
                pts.append(q)
                p = q
            halves.append(pts)
        return tuple(reversed(halves[1])) + (p0,) + tuple(halves[0])

    def grid_candidates():
        ny = int(math.floor((y1 - y0) / d_sep + 1e-9))
        nx = int(math.floor((x1 - x0) / d_sep + 1e-9))
        for j in range(ny + 1):
            for i in range(nx + 1):
                yield (x0 + i * d_sep, y0 + j * d_sep)

    if inside(seed) and _unit(f, seed) is not None:
        lines.append(trace(seed))
    k = 0
    scan = grid_candidates()
    while len(lines) < max_lines:
        if k >= len(lines):
            # the queue is empty: the next grid candidate far enough from every streamline seeds one (so a
            # region the seed's streamline does not reach, or a seed on a zero, is still covered)
            c = next(scan, None)
            if c is None:
                break
            if buckets.nearest(c) < d_sep - 1e-12 or _unit(f, c) is None:
                continue
            lines.append(trace(c))
            continue
        line = lines[k]
        k += 1
        for i, p in enumerate(line):
            if len(lines) >= max_lines:
                break
            q = line[i + 1] if i + 1 < len(line) else (line[i - 1] if i > 0 else None)
            if q is None:
                d = _unit(f, p)
                if d is None:
                    continue
            else:
                dx, dy = q[0] - p[0], q[1] - p[1]
                n = math.hypot(dx, dy)
                if n == 0.0:
                    continue
                d = (dx / n, dy / n)
            for sgn in (1.0, -1.0):
                c = (p[0] - d[1] * d_sep * sgn, p[1] + d[0] * d_sep * sgn)
                if not inside(c) or buckets.nearest(c) < d_sep - 1e-12 or _unit(f, c) is None:
                    continue
                lines.append(trace(c))
                if len(lines) >= max_lines:
                    break
    return tuple(lines)


def min_separation(lines):
    """The smallest distance between a point of one streamline and a point of another; inf below two lines."""
    lines = tuple(lines)
    best = math.inf
    for a in range(len(lines)):
        for b in range(a + 1, len(lines)):
            for p in lines[a]:
                for q in lines[b]:
                    best = min(best, math.hypot(p[0] - q[0], p[1] - q[1]))
    return best


# --- rule 7: line integral convolution (Cabral and Leedom 1993) -----------------------------------------------------

def lic(f, noise, ranges, length, h):
    """The raster of the box kernel of half-length `length` along the streamline through each pixel centre of
    `noise` (rows from y0, columns from x0): the mean of the noise at the nearest pixel of each sample point
    at arc length 0, +-h, +-2h, ... up to `length` each way, samples outside the raster skipped."""
    rows = tuple(tuple(float(v) for v in r) for r in noise)
    if not rows or len({len(r) for r in rows}) != 1 or not rows[0]:
        raise ValueError("the noise is a rectangular raster")
    if not length > 0.0 or not h > 0.0:
        raise ValueError("the length and the step are positive")
    x0, y0, x1, y1 = ranges
    ny, nx = len(rows), len(rows[0])
    pw, ph = (x1 - x0) / nx, (y1 - y0) / ny

    def at(p):
        i = math.floor((p[0] - x0) / pw)
        j = math.floor((p[1] - y0) / ph)
        if 0 <= i < nx and 0 <= j < ny:
            return rows[j][i]
        return None

    n = int(math.floor(length / h + 1e-9))
    out = []
    for j in range(ny):
        row = []
        for i in range(nx):
            c = (x0 + (i + 0.5) * pw, y0 + (j + 0.5) * ph)
            acc, cnt = rows[j][i], 1
            for sgn in (1.0, -1.0):
                p = c
                for _ in range(n):
                    q = rk4_step(f, p, sgn * h)
                    if q is None:
                        break
                    v = at(q)
                    if v is not None:
                        acc += v
                        cnt += 1
                    p = q
            row.append(acc / cnt)
        out.append(tuple(row))
    return tuple(out)


# --- rules 8 and 9: phase portraits (Wegert 2012) -----------------------------------------------------------------

def phase_hue(w):
    """The hue of w in [0, 1): arg w / 2 pi, taken modulo 1; 0 for 0 and for a non-finite w."""
    w = complex(w)
    if w == 0 or not (math.isfinite(w.real) and math.isfinite(w.imag)):
        return 0.0
    return (cmath.phase(w) / math.tau) % 1.0


def modulus_shade(w, base=2.0):
    """The fractional part of log_base |w| in [0, 1): 0 at powers of the base, 0 for 0 and for a non-finite w."""
    w = complex(w)
    r = abs(w)
    if r == 0.0 or not math.isfinite(r):
        return 0.0
    return (math.log(r) / math.log(base)) % 1.0


def winding_number(f, center, radius, samples=WINDING_SAMPLES):
    """The number of turns of arg f(z) along the circle of `radius` about `center`, counterclockwise, from the
    wrapped differences of arg at `samples` equally spaced points: zeros minus poles inside, with multiplicity.
    A zero or non-finite value on a sample is an error."""
    if not radius > 0.0 or not (isinstance(samples, int) and samples >= 3):
        raise ValueError("the radius is positive and there are at least three samples")
    args = []
    for k in range(samples):
        a = math.tau * k / samples
        w = complex(f(complex(center[0] + radius * math.cos(a), center[1] + radius * math.sin(a))))
        if w == 0 or not (math.isfinite(w.real) and math.isfinite(w.imag)):
            raise ValueError("a zero or a pole lies on the circle")
        args.append(cmath.phase(w))
    total = 0.0
    for a, b in zip(args, args[1:] + args[:1]):
        d = b - a
        total += (d + math.pi) % math.tau - math.pi
    return int(round(total / math.tau))


# --- rule 10: dipole and charge lines ------------------------------------------------------------------------------

def dipole_line_constant(p, m=(0.0, 1.0), center=(0.0, 0.0)):
    """r / sin^2(theta) with theta the angle between p - center and the dipole axis; constant along a field line
    of the point dipole. Undefined (an error) on the axis."""
    rx, ry = p[0] - center[0], p[1] - center[1]
    r = math.hypot(rx, ry)
    mn = math.hypot(m[0], m[1])
    if r == 0.0 or mn == 0.0:
        raise ValueError("the point is not the centre and the moment is not zero")
    cos_t = (rx * m[0] + ry * m[1]) / (r * mn)
    sin2 = 1.0 - cos_t * cos_t
    if sin2 <= 1e-12:
        raise ValueError("the constant is undefined on the dipole axis")
    return r / sin2


def dipole_line_deviation(p0, h, steps, m=(0.0, 1.0)):
    """The largest relative change of the dipole line constant along `steps` RK4 steps of length h from p0,
    forward only."""
    f = lambda x, y: dipole_field((x, y), m)    # noqa: E731
    line = streamline(f, p0, h, steps, lambda p: True, both=False)
    c0 = dipole_line_constant(p0, m)
    return max(abs(dipole_line_constant(p, m) / c0 - 1.0) for p in line)


def charge_lines(charges, per_charge=8, r0=0.05, h=0.01, max_steps=5000, ranges=(-5.0, -5.0, 5.0, 5.0)):
    """Field lines of point charges: from each positive charge, per_charge lines start at radius r0 at angles
    2 pi k / per_charge and follow the field (rule 4, forward only) until they come within r0 of a negative
    charge (that point is the line's last), leave the box, or reach max_steps."""
    if not (isinstance(per_charge, int) and per_charge >= 1):
        raise ValueError("per_charge is a positive integer")
    f = lambda x, y: charge_field(charges, (x, y))    # noqa: E731
    inside = inside_box(ranges)
    negatives = [(cx, cy) for cx, cy, q in charges if q < 0]

    def stop(p):
        return any(math.hypot(p[0] - cx, p[1] - cy) < r0 for cx, cy in negatives)

    out = []
    for cx, cy, q in charges:
        if q <= 0:
            continue
        for k in range(per_charge):
            a = math.tau * k / per_charge
            p0 = (cx + r0 * math.cos(a), cy + r0 * math.sin(a))
            out.append(streamline(f, p0, h, max_steps, inside, stop=stop, both=False, keep_stop=True))
    return tuple(out)


def line_ends_on(line, charges, r0):
    """The index of the charge within r0 of the line's last point, or None."""
    x, y = line[-1]
    for i, (cx, cy, _) in enumerate(charges):
        if math.hypot(x - cx, y - cy) <= r0 + 1e-9:
            return i
    return None


# --- the numeric table -------------------------------------------------------------------------------------------

def raises(f):
    """True when f() raises ValueError (the rows that state an error)."""
    try:
        f()
    except ValueError:
        return True
    return False


TABLE = [
    ("grid node", "grid_sampler((((0.0, 0.0), (1.0, 0.0)), ((0.0, 1.0), (1.0, 1.0))), (0.0, 0.0, 1.0, 1.0))(1.0, 0.0)"),
    ("grid bilinear", "grid_sampler((((0.0, 0.0), (1.0, 0.0)), ((0.0, 1.0), (1.0, 1.0))), (0.0, 0.0, 1.0, 1.0))(0.5, 0.5)"),
    ("grid outside", "grid_sampler((((1.0, 1.0), (1.0, 1.0)), ((1.0, 1.0), (1.0, 1.0))), (0.0, 0.0, 1.0, 1.0))(1.5, 0.5)"),
    ("complex field", "complex_sampler(lambda z: z * z)(1.0, 1.0)"),
    ("coulomb inverse square", "charge_field(((0.0, 0.0, 1.0),), (2.0, 0.0))"),
    ("dipole on the axis", "dipole_field((0.0, 2.0))"),
    ("dipole on the equator", "dipole_field((2.0, 0.0))"),
    ("wire field", "tuple(round(c, 12) + 0.0 for c in wire_field((2.0, 0.0)))"),
    ("poynting", "poynting((1.0, 0.0), 1.0)"),
    ("wire B at the midpoint", "round(line_field((0.0, 1.0), (-1.0, 0.0), (1.0, 0.0), i=1.0)[2], 12)"),
    ("wire E at the midpoint", "tuple(round(c, 12) + 0.0 for c in line_field((0.0, 1.0), (-1.0, 0.0), (1.0, 0.0), q=1.0)[:2])"),
    ("long wire is the point current", "round(line_field((0.0, 1.0), (-1e9, 0.0), (1e9, 0.0), i=1.0)[2], 12)"),
    ("below the wire the signs flip", "tuple(round(c, 12) + 0.0 for c in line_field((0.0, -1.0), (-1.0, 0.0), (1.0, 0.0), q=1.0, i=1.0))"),
    ("on the wire", "line_field((0.5, 0.0), (-1.0, 0.0), (1.0, 0.0), q=1.0, i=1.0)"),
    ("shot 2 poynting at the centre", "tuple(round(c, 6) + 0.0 for c in poynting_at((0.0, 0.0), (), (), SHOT2_WIRES))"),
    ("shot 2 arrows within 5 degrees", "round(max(abs(poynting_angle((x, y), (), (), SHOT2_WIRES)) for x in (-0.5, -0.25, 0.0, 0.25, 0.5) for y in (-0.25, 0.0, 0.25)), 6)"),
    ("divergence of a source", "round(divergence(lambda x, y: (x, y), (0.3, 0.7)), 6)"),
    ("curl of a rotation", "round(curl(lambda x, y: (-y, x), (0.3, 0.7)), 6)"),
    ("divergence of a point source", "round(divergence(lambda x, y: source_field((x, y)), (1.0, 0.0)), 6) + 0.0"),
    ("rk4 step on the unit direction", "rk4_step(lambda x, y: (3.0, 0.0), (0.0, 0.0), 0.5)"),
    ("rk4 at a zero", "rk4_step(lambda x, y: (0.0, 0.0), (0.0, 0.0), 0.5)"),
    ("streamline both ways to the box",
     "streamline(lambda x, y: (1.0, 0.0), (0.5, 0.5), 0.25, 100, inside_box((0.0, 0.0, 1.0, 1.0)))"),
    ("streamline on the circle",
     "abs(math.hypot(*streamline(lambda x, y: (-y, x), (1.0, 0.0), 0.01, 100, lambda p: True, both=False)[-1]) - 1.0) < 1e-6"),
    ("streamline step bound", "len(streamline(lambda x, y: (1.0, 0.0), (0.0, 0.0), 0.1, 10, lambda p: True))"),
    ("arrow", "tuple(tuple(tuple(round(c, 9) for c in q) for q in part) for part in arrow((0.0, 0.0), (3.0, 4.0), 1.0, 10.0))"),
    ("arrow clamped", "arrow((0.0, 0.0), (30.0, 40.0), 1.0, 5.0)[0][1]"),
    ("arrow of a zero vector", "arrow((0.0, 0.0), (0.0, 0.0), 1.0, 5.0)"),
    ("arrow grid count", "len(arrow_grid(lambda x, y: (1.0, 0.0), (0.0, 0.0, 1.0, 1.0), 3, 2, 1.0, 10.0))"),
    ("evenly spaced streamlines of a uniform field",
     "tuple(sorted(round(line[0][1], 9) for line in evenly_spaced_streamlines(lambda x, y: (1.0, 0.0), (0.0, 0.0, 1.0, 1.0), 0.25)))"),
    ("their separation",
     "min_separation(evenly_spaced_streamlines(lambda x, y: (1.0, 0.0), (0.0, 0.0, 1.0, 1.0), 0.25)) >= 0.25 - 1e-9"),
    ("vortex streamlines keep the test distance",
     "min_separation(evenly_spaced_streamlines(lambda x, y: (-y, x), (-1.0, -1.0, 1.0, 1.0), 0.2)) >= 0.1 - 0.05 - 1e-9"),
    ("streamline count bound",
     "len(evenly_spaced_streamlines(lambda x, y: (-y, x), (-1.0, -1.0, 1.0, 1.0), 0.05, max_lines=7))"),
    ("test distance above the separation is an error",
     "raises(lambda: evenly_spaced_streamlines(lambda x, y: (1.0, 0.0), (0.0, 0.0, 1.0, 1.0), 0.25, d_test=0.3))"),
    ("lic along the rows",
     "tuple(tuple(round(v, 12) for v in row) for row in lic(lambda x, y: (1.0, 0.0), ((0.2, 0.2, 0.2, 0.2), (0.8, 0.8, 0.8, 0.8)), (0.0, 0.0, 4.0, 2.0), 1.0, 0.5))"),
    ("lic across the rows",
     "lic(lambda x, y: (0.0, 1.0), ((0.2, 0.2, 0.2, 0.2), (0.8, 0.8, 0.8, 0.8)), (0.0, 0.0, 4.0, 2.0), 1.0, 1.0)"),
    ("phase hue of i", "phase_hue(1j)"),
    ("phase hue of -1", "phase_hue(-1.0)"),
    ("modulus shade of 3", "round(modulus_shade(3.0), 12)"),
    ("winding of z squared", "winding_number(lambda z: z * z, (0.0, 0.0), 1.0)"),
    ("winding of a pole", "winding_number(lambda z: 1.0 / z, (0.0, 0.0), 1.0)"),
    ("winding of two zeros and a pole", "winding_number(lambda z: (z - 1.0) * (z + 1.0) / z, (0.0, 0.0), 2.0)"),
    ("winding inside the zeros", "winding_number(lambda z: (z - 1.0) * (z + 1.0) / z, (0.0, 0.0), 0.5)"),
    ("zero on the circle is an error", "raises(lambda: winding_number(lambda z: z - 1.0, (0.0, 0.0), 1.0))"),
    ("dipole line constant", "round(dipole_line_constant((1.0, 1.0)), 12)"),
    ("dipole line constant holds", "dipole_line_deviation((1.0, 1.0), 0.01, 200) < 1e-4"),
    ("charge rays", "len(charge_lines(((0.0, 0.0, 1.0),), per_charge=8))"),
    ("charge ray direction",
     "round(math.degrees(math.atan2(charge_lines(((0.0, 0.0, 1.0),), per_charge=8)[2][-1][1], charge_lines(((0.0, 0.0, 1.0),), per_charge=8)[2][-1][0])), 6)"),
    ("lines ending on the negative charge",
     "sum(1 for line in charge_lines(((-1.0, 0.0, 1.0), (1.0, 0.0, -1.0)), per_charge=8) if line_ends_on(line, ((-1.0, 0.0, 1.0), (1.0, 0.0, -1.0)), 0.05) == 1)"),
    ("current lines are circles",
     "all(abs(math.hypot(*p) - 1.0) < 1e-6 for p in streamline(lambda x, y: wire_field((x, y)), (1.0, 0.0), 0.01, 700, lambda p: True, both=False))"),
]


def _fmt(v):
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    return repr(v)


def main():
    scope = {k: v for k, v in globals().items() if not k.startswith("_")}
    scope["math"] = math
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "sum": sum, "all": all,
                             "any": any, "max": max, "min": min, "sorted": sorted, "complex": complex}
    print("| Test | Expression | Expected |")
    print("|---|---|---|")
    for name, expr in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, scope))}` |")   # one scope: lambdas see the globals


if __name__ == "__main__":
    main()
