#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add relativity diagrams" (srep/srep-0000-relativity.md, SP6 of
SREP 12).

Four things, each a pure function:

* Minkowski diagrams in units of c: the Lorentz boost, the interval it preserves, rapidity (in which boosts
  compose by addition), light cones, inertial, accelerated (Rindler) and parametric worldlines, the grid of a
  boosted frame;
* conformal compactification: the Penrose diamond of Minkowski space and the Kruskal-Szekeres map of the
  Schwarzschild solution followed by the same compactification;
* embedding surfaces: Flamm's paraboloid z = 2 sqrt(r_s (r - r_s)) (its slope, proper radial distance, arc length
  and Gaussian curvature) and the Newtonian potential sheet, as rings and spokes;
* gravitational-wave strain: the plus and cross polarisations on a ring of test masses, the chirp mass, the
  quadrupole-formula frequency, amplitude and cycle count.

Running the module prints the data rows of the draft's numeric table.
"""
import math

G = 6.67430e-11
C = 299792458.0
M_SUN = 1.98841e30
AU_M = 149597870700.0
PC_M = 648000.0 / math.pi * AU_M
MPC_M = 1.0e6 * PC_M
COMPACT_MODES = ("none", "minkowski", "schwarzschild")
WORLDLINES = ("inertial", "accelerated", "parametric")
EMBEDDINGS = ("flamm", "potential")
PENROSE_EXTENT = math.pi / 2.0
MAX_STRAIN = 1.0
SEEK_FRAMES = 240
SIMPSON_PANELS = 4096
KRUSKAL_ITERATIONS = 200


class RelativityError(ValueError):
    """A value outside the draft's domain."""


# ------------------------------------------------------------------------------------ boosts and intervals


def _beta(beta):
    if not -1.0 < beta < 1.0:
        raise RelativityError("beta must lie strictly between -1 and 1")
    return float(beta)


def gamma(beta):
    """1 / sqrt(1 - beta^2)."""
    b = _beta(beta)
    return 1.0 / math.sqrt(1.0 - b * b)


def rapidity(beta):
    """atanh(beta)."""
    return math.atanh(_beta(beta))


def beta_from_rapidity(phi):
    """tanh(phi)."""
    return math.tanh(phi)


def boost(x, t, beta):
    """The Lorentz boost of the event (x, t) into the frame moving at beta (units of c)."""
    b = _beta(beta)
    g = gamma(b)
    return (g * (x - b * t), g * (t - b * x))


def inverse_boost(x, t, beta):
    """boost with -beta."""
    return boost(x, t, -_beta(beta))


def interval(x, t):
    """t^2 - x^2 (timelike positive)."""
    return t * t - x * x


def interval_between(a, b):
    """The interval of the separation b - a."""
    return interval(b[0] - a[0], b[1] - a[1])


def compose_beta(b1, b2):
    """(b1 + b2) / (1 + b1 b2)."""
    return (_beta(b1) + _beta(b2)) / (1.0 + b1 * b2)


def time_dilation(beta):
    """gamma: coordinate time per unit proper time."""
    return gamma(beta)


def length_contraction(beta):
    """1 / gamma."""
    return 1.0 / gamma(beta)


def doppler(beta):
    """The relativistic Doppler factor sqrt((1 + beta) / (1 - beta)) for approach."""
    b = _beta(beta)
    return math.sqrt((1.0 + b) / (1.0 - b))


def classify(a, b):
    """timelike, lightlike or spacelike separation of two events."""
    s = interval_between(a, b)
    dx, dt = b[0] - a[0], b[1] - a[1]
    scale = max(abs(dx), abs(dt), 1.0)
    if abs(s) <= 1e-12 * scale * scale:
        return "lightlike"
    return "timelike" if s > 0.0 else "spacelike"


def proper_time(a, b):
    """sqrt of a timelike interval."""
    s = interval_between(a, b)
    if s <= 0.0:
        raise RelativityError("proper time needs a timelike separation")
    return math.sqrt(s)


def proper_length(a, b):
    """sqrt of minus a spacelike interval."""
    s = interval_between(a, b)
    if s >= 0.0:
        raise RelativityError("proper length needs a spacelike separation")
    return math.sqrt(-s)


def light_cone(event, extent):
    """The ends of the future and past cones of an event, extent units of t away."""
    if not extent > 0.0:
        raise RelativityError("extent must be positive")
    x, t = event
    return {"future": ((x - extent, t + extent), (x + extent, t + extent)),
            "past": ((x - extent, t - extent), (x + extent, t - extent))}


def cone_slopes(event, cone):
    """|dt / dx| of the two future cone edges from the event: (1, 1) for light."""
    x, t = event
    (ax, at), (bx, bt) = cone["future"]
    return (abs((at - t) / (ax - x)), abs((bt - t) / (bx - x)))


def inside_future_cone(event, other):
    """True when other lies in the future light cone of event."""
    dx, dt = other[0] - event[0], other[1] - event[1]
    return dt > 0.0 and dt * dt - dx * dx > 0.0


def worldline_inertial(x0, t0, beta, t):
    """The event at time t on the worldline through (x0, t0) at speed beta."""
    b = _beta(beta)
    return (x0 + b * (t - t0), float(t))


def worldline_accelerated(a, tau):
    """Rindler motion from rest at the origin: x = (cosh(a tau) - 1) / a, t = sinh(a tau) / a."""
    if not a > 0.0:
        raise RelativityError("proper acceleration must be positive")
    return ((math.cosh(a * tau) - 1.0) / a, math.sinh(a * tau) / a)


def accelerated_beta(a, tau):
    """tanh(a tau), the speed on the Rindler worldline at proper time tau."""
    if not a > 0.0:
        raise RelativityError("proper acceleration must be positive")
    return math.tanh(a * tau)


def worldline_parametric(fx, ft, tau, h=1e-6):
    """(fx(tau), ft(tau)) with a timelike tangent."""
    dx = (fx(tau + h) - fx(tau - h)) / (2 * h)
    dt = (ft(tau + h) - ft(tau - h)) / (2 * h)
    if not dt > abs(dx):
        raise RelativityError("a worldline's tangent is timelike and future-directed")
    return (fx(tau), ft(tau))


def grid_x_line(beta, k, t):
    """The event at time t on the line x' = k of the frame moving at beta."""
    b = _beta(beta)
    return (k / gamma(b) + b * t, float(t))


def grid_t_line(beta, k, x):
    """The event at position x on the line t' = k of the frame moving at beta."""
    b = _beta(beta)
    return (float(x), k / gamma(b) + b * x)


def boosted_grid(beta, n, extent):
    """Segments of the lines x' = k and t' = k, k = -n .. n, across +-extent, in the coordinates of the frame
    the primed one moves through at beta."""
    xs = [(grid_x_line(beta, k, -extent), grid_x_line(beta, k, extent)) for k in range(-n, n + 1)]
    ts = [(grid_t_line(beta, k, -extent), grid_t_line(beta, k, extent)) for k in range(-n, n + 1)]
    return {"x": xs, "t": ts}


def diagram_grid(beta, n, extent):
    """The grid a diagram drawn in the frame at beta shows: the box frame's lines x = k and t = k where the boost
    carries them. From the drawn frame the box frame moves at -beta, so these are boosted_grid(-beta) in the
    drawn frame's own coordinates, which the axes map with no further boost."""
    return boosted_grid(-_beta(beta), n, extent)


# ------------------------------------------------------------------------------------ compactification


def penrose(x, t):
    """The Penrose diamond: U = atan(t - x), V = atan(t + x); X = (V - U) / 2, T = (U + V) / 2."""
    u = math.atan(t - x)
    v = math.atan(t + x)
    return ((v - u) / 2.0, (u + v) / 2.0)


def penrose_inverse(X, T):
    """The event of a diamond point."""
    u, v = T - X, T + X
    if not (abs(u) < PENROSE_EXTENT and abs(v) < PENROSE_EXTENT):
        raise RelativityError("the point lies outside the diamond")
    tu, tv = math.tan(u), math.tan(v)
    return ((tv - tu) / 2.0, (tu + tv) / 2.0)


def penrose_slope(event, direction):
    """dT / dX of a null ray from an event in the diamond: +1 rightwards, -1 leftwards."""
    if direction not in (1.0, -1.0, 1, -1):
        raise RelativityError("direction is +1 or -1")
    a = penrose(*event)
    b = penrose(event[0] + direction, event[1] + 1.0)
    return (b[1] - a[1]) / (b[0] - a[0])


def penrose_infinity(kind):
    """The diamond's corners: spacelike (i0), future and past timelike infinity."""
    if kind == "spacelike":
        return (PENROSE_EXTENT, 0.0)
    if kind == "future":
        return (0.0, PENROSE_EXTENT)
    if kind == "past":
        return (0.0, -PENROSE_EXTENT)
    raise RelativityError(f"unknown infinity {kind!r}")


def kruskal(r, t, rs):
    """Kruskal-Szekeres (T, X) of Schwarzschild (r, t) in the exterior and the interior, G = c = 1."""
    if not rs > 0.0:
        raise RelativityError("the Schwarzschild radius must be positive")
    if not r > 0.0:
        raise RelativityError("r must be positive")
    e = math.exp(r / (2.0 * rs))
    if r >= rs:
        p = math.sqrt(r / rs - 1.0) * e
        return (p * math.sinh(t / (2.0 * rs)), p * math.cosh(t / (2.0 * rs)))
    p = math.sqrt(1.0 - r / rs) * e
    return (p * math.cosh(t / (2.0 * rs)), p * math.sinh(t / (2.0 * rs)))


def kruskal_singularity(X):
    """T of the singularity r = 0 at X: T^2 - X^2 = 1."""
    return math.sqrt(1.0 + X * X)


def kruskal_radius(T, X, rs):
    """r from X^2 - T^2 = (r / rs - 1) e^(r / rs), by bisection."""
    if not rs > 0.0:
        raise RelativityError("the Schwarzschild radius must be positive")
    q = X * X - T * T
    if q < -1.0:
        raise RelativityError("the point lies beyond the singularity")
    if q == 0.0:
        return float(rs)
    lo, hi = 0.0, rs
    while (hi / rs - 1.0) * math.exp(hi / rs) < q:
        hi *= 2.0
    for _ in range(KRUSKAL_ITERATIONS):
        mid = 0.5 * (lo + hi)
        if (mid / rs - 1.0) * math.exp(mid / rs) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def penrose_schwarzschild(r, t, rs):
    """The Penrose diagram of the Schwarzschild solution: penrose applied to the Kruskal coordinates."""
    T, X = kruskal(r, t, rs)
    return penrose(X, T)


def compactify(x, t, mode, rs=None):
    """Dispatch of the compactification modes."""
    if mode not in COMPACT_MODES:
        raise RelativityError(f"unknown compactification {mode!r}")
    if mode == "none":
        return (float(x), float(t))
    if mode == "minkowski":
        return penrose(x, t)
    if rs is None or not rs > 0.0:
        raise RelativityError("the schwarzschild compactification needs a positive rs")
    return penrose_schwarzschild(x, t, rs)


# ------------------------------------------------------------------------------------ embeddings


def _flamm_domain(r, rs):
    if not rs > 0.0:
        raise RelativityError("the Schwarzschild radius must be positive")
    if r < rs:
        raise RelativityError("Flamm's paraboloid starts at the horizon")


def flamm(r, rs):
    """z = 2 sqrt(rs (r - rs))."""
    _flamm_domain(r, rs)
    return 2.0 * math.sqrt(rs * (r - rs))


def flamm_slope(r, rs):
    """dz / dr = sqrt(rs / (r - rs))."""
    _flamm_domain(r, rs)
    if r == rs:
        return math.inf
    return math.sqrt(rs / (r - rs))


def proper_radial_distance(r1, r2, rs):
    """The integral of dr / sqrt(1 - rs / r) from r1 to r2, in closed form."""
    _flamm_domain(r1, rs)
    _flamm_domain(r2, rs)
    if r2 < r1:
        raise RelativityError("r2 must not be below r1")

    def f(r):
        return math.sqrt(r * (r - rs)) + rs * math.log(math.sqrt(r) + math.sqrt(r - rs))

    return f(r2) - f(r1)


def flamm_arc_length(r1, r2, rs):
    """The arc length of a radial line on the paraboloid, by Simpson's rule on sqrt(1 + z'^2) in s = sqrt(r - rs)."""
    _flamm_domain(r1, rs)
    _flamm_domain(r2, rs)
    if r2 < r1:
        raise RelativityError("r2 must not be below r1")
    # substitute r = rs + s^2 so the integrand 2 s sqrt(1 + rs / s^2) = 2 sqrt(s^2 + rs) is smooth
    s1, s2 = math.sqrt(r1 - rs), math.sqrt(r2 - rs)
    n = SIMPSON_PANELS
    h = (s2 - s1) / n
    total = 0.0
    for i in range(n + 1):
        s = s1 + i * h
        w = 1.0 if i in (0, n) else (4.0 if i % 2 else 2.0)
        total += w * 2.0 * math.sqrt(s * s + rs)
    return total * h / 3.0


def flamm_curvature(r, rs):
    """The Gaussian curvature of Flamm's paraboloid, -rs / (2 r^3)."""
    _flamm_domain(r, rs)
    return -rs / (2.0 * r ** 3)


def potential(r, k):
    """The Newtonian sheet z = -k / r."""
    if not r > 0.0:
        raise RelativityError("r must be positive")
    return -k / r


def potential_slope(r, k):
    """k / r^2."""
    if not r > 0.0:
        raise RelativityError("r must be positive")
    return k / (r * r)


def embedding_point(kind, r, phi, scale):
    """The scene point of a sheet at (r, phi): (r cos phi, -z, r sin phi), z the sheet's height (the sheet sags)."""
    if kind not in EMBEDDINGS:
        raise RelativityError(f"unknown embedding {kind!r}")
    z = flamm(r, scale) if kind == "flamm" else potential(r, scale)
    return (r * math.cos(phi), -z, r * math.sin(phi))


def embedding_grid(kind, r_min, r_max, rings, spokes, samples, scale):
    """Rings at r_min .. r_max and spokes from r_min to r_max, as point lists; scale is the sheet's own
    rs (flamm, r_min at least rs) or k (potential)."""
    if kind not in EMBEDDINGS:
        raise RelativityError(f"unknown embedding {kind!r}")
    if not (r_min > 0.0 and r_max > r_min):
        raise RelativityError("r_max must exceed a positive r_min")
    if rings < 1 or spokes < 3 or samples < 2:
        raise RelativityError("rings >= 1, spokes >= 3, samples >= 2")
    if not scale > 0.0:
        raise RelativityError("rs or k must be positive")
    if kind == "flamm" and r_min < scale:
        raise RelativityError("rMin must not be below rs")
    ring_list = []
    for i in range(rings):
        r = r_min + (r_max - r_min) * i / (rings - 1) if rings > 1 else r_min
        ring_list.append([embedding_point(kind, r, 2.0 * math.pi * j / samples, scale) for j in range(samples)])
    spoke_list = []
    for j in range(spokes):
        phi = 2.0 * math.pi * j / spokes
        spoke_list.append([embedding_point(kind, r_min + (r_max - r_min) * i / (samples - 1), phi, scale)
                           for i in range(samples)])
    return {"rings": ring_list, "spokes": spoke_list}


# ------------------------------------------------------------------------------------ gravitational-wave strain


def strain_displacement(x, y, hplus, hcross):
    """((h+ x + hx y) / 2, (hx x - h+ y) / 2): the plane-wave displacement along the viewing axis."""
    return ((hplus * x + hcross * y) / 2.0, (hcross * x - hplus * y) / 2.0)


def strain_point(x, y, hplus, hcross, frequency, t, phase):
    """The displaced point at time t: the displacement times cos(2 pi f t + phase)."""
    dx, dy = strain_displacement(x, y, hplus, hcross)
    c = math.cos(2.0 * math.pi * frequency * t + phase)
    return (x + dx * c, y + dy * c)


def ring_axes(hplus, hcross):
    """The semi-axes of the ellipse a unit ring becomes at the wave's crest: 1 +- h / 2, h = sqrt(h+^2 + hx^2)."""
    h = math.hypot(hplus, hcross)
    return (1.0 + h / 2.0, 1.0 - h / 2.0)


def strained_ring(hplus, hcross, n, frequency, radius, t, phase):
    """n points of a ring of the given radius under the strain."""
    return [strain_point(radius * math.cos(2.0 * math.pi * i / n), radius * math.sin(2.0 * math.pi * i / n), hplus,
                         hcross, frequency, t, phase) for i in range(n)]


def chirp_mass(m1, m2):
    """(m1 m2)^(3/5) / (m1 + m2)^(1/5)."""
    if not (m1 > 0.0 and m2 > 0.0):
        raise RelativityError("masses must be positive")
    return (m1 * m2) ** 0.6 / (m1 + m2) ** 0.2


def _chirp_time(mc):
    if not mc > 0.0:
        raise RelativityError("the chirp mass must be positive")
    return G * mc / C ** 3


def gw_frequency(tau, mc):
    """The quadrupole-formula frequency tau seconds before coalescence: (1 / pi) (5 / (256 tau))^(3/8) (G Mc / c^3)^(-5/8)."""
    if not tau > 0.0:
        raise RelativityError("tau must be positive")
    return (5.0 / (256.0 * tau)) ** 0.375 * _chirp_time(mc) ** -0.625 / math.pi


def time_to_merger(f, mc):
    """The inverse of gw_frequency: (5 / 256) (G Mc / c^3)^(-5/3) (pi f)^(-8/3)."""
    if not f > 0.0:
        raise RelativityError("the frequency must be positive")
    return 5.0 / 256.0 * _chirp_time(mc) ** (-5.0 / 3.0) * (math.pi * f) ** (-8.0 / 3.0)


def gw_amplitude(d, mc, f):
    """(4 / d) (G Mc / c^2)^(5/3) (pi f / c)^(2/3)."""
    if not d > 0.0:
        raise RelativityError("the distance must be positive")
    if not f > 0.0:
        raise RelativityError("the frequency must be positive")
    return 4.0 / d * (G * mc / C ** 2) ** (5.0 / 3.0) * (math.pi * f / C) ** (2.0 / 3.0)


def chirp_cycles(tau1, tau2, mc):
    """Cycles of the wave from tau1 to tau2 before coalescence (tau2 <= tau1): the integral of f d tau in closed form."""
    if tau2 > tau1:
        raise RelativityError("tau2 must not exceed tau1")
    if not tau2 > 0.0:
        raise RelativityError("tau must be positive")
    k = (5.0 / 256.0) ** 0.375 * _chirp_time(mc) ** -0.625 / math.pi
    # integral of k tau^(-3/8) = k (8/5) tau^(5/8)
    return k * 1.6 * (tau1 ** 0.625 - tau2 ** 0.625)


# ------------------------------------------------------------------------------------ animation and mapping


def frame_beta(frame, fps, beta0, beta1, t0, t1):
    """The boost at a frame: linear in rapidity from beta0 at t0 to beta1 at t1, held outside."""
    if frame < 0 or int(frame) != frame:
        raise RelativityError("frame must be a non-negative integer")
    if not fps > 0.0:
        raise RelativityError("fps must be positive")
    if not t1 > t0:
        raise RelativityError("t1 must exceed t0")
    u = min(1.0, max(0.0, (frame / fps - t0) / (t1 - t0)))
    phi = rapidity(beta0) + (rapidity(beta1) - rapidity(beta0)) * u
    return beta_from_rapidity(phi)


def boost_keeps_interval(x, t, beta, want=None, tol=1e-9):
    """|interval(boost(x, t, beta)) - want| <= tol, want the interval of (x, t) unless given."""
    target = interval(x, t) if want is None else want
    return abs(interval(*boost(x, t, beta)) - target) <= tol


def seek_test():
    """Composing the per-frame boost increments reproduces the direct frame boost at every frame."""
    fps, b0, b1, t0, t1 = 24.0, 0.0, 0.8, 0.0, 10.0
    played = b0
    step = beta_from_rapidity((rapidity(b1) - rapidity(b0)) / ((t1 - t0) * fps))
    for frame in range(SEEK_FRAMES + 1):
        direct = frame_beta(frame, fps, b0, b1, t0, t1)
        if abs(direct - played) > 1e-12:
            return False
        if not boost_keeps_interval(3.0, 5.0, direct, want=16.0):
            return False
        played = compose_beta(played, step)
    return True


def diagram_pixel(x, t, box, beta=0.0, compact="none", rs=None):
    """The pixel of an event: boost, compactify, then the plots draft's axes mapping (y down)."""
    if not (box["xMax"] > box["xMin"] and box["yMax"] > box["yMin"]):
        raise RelativityError("the axes ranges must be increasing")
    xb, tb = boost(x, t, beta)
    xc, tc = compactify(xb, tb, compact, rs)
    px = box["x"] + (xc - box["xMin"]) / (box["xMax"] - box["xMin"]) * box["width"]
    py = box["y"] + (box["yMax"] - tc) / (box["yMax"] - box["yMin"]) * box["height"]
    return (px, py)


# ------------------------------------------------------------------------------------ validation


# the schema readings of the engine's SR-92 (9b5a2fb), settled by the draft: the stroke of a diagram's children, an
# event's dot and the embedding's default radii
SPACETIME_STROKE = "#FFCC00FF"
SPACETIME_STROKE_WIDTH = 3.0
EVENT_MARKER_SIZE = 8.0


def embedding_radii(kind, rs=None, hole_mass=None, r_min=None):
    """RD3's defaults: (rs, rMin) of a sheet, rs falling back to 2 mass of its blackHole and rMin to rs for flamm
    and rs / 4 for potential; None for a potential sheet's rs when it needs none."""
    if kind not in EMBEDDINGS:
        raise RelativityError("RD3: kind is flamm or potential")
    if rs is None and hole_mass is not None:
        rs = 2.0 * hole_mass
    if rs is not None and not rs > 0.0:
        raise RelativityError("RD3: rs (2 mass of the blackHole) must be positive")
    if kind == "flamm" and rs is None:
        raise RelativityError("RD3: a flamm sheet has rs or a blackHole")
    if r_min is None:
        if rs is None:
            raise RelativityError("RD3: a potential sheet without rMin needs rs or a blackHole")
        r_min = rs if kind == "flamm" else rs / 4.0
    if kind == "flamm" and r_min < rs:
        raise RelativityError("RD3: a flamm sheet's rMin is at least rs")
    return (rs, r_min)


def validate_spacetime(c, beta, compact, rs=None):
    """RD1: c positive, |beta| below 1, compact in the enumeration, rs positive for schwarzschild."""
    if not c > 0.0:
        raise RelativityError("RD1: c must be positive")
    _beta(beta)
    if compact not in COMPACT_MODES:
        raise RelativityError("RD1: compact is none, minkowski or schwarzschild")
    if compact == "schwarzschild" and (rs is None or not rs > 0.0):
        raise RelativityError("RD1: schwarzschild needs a positive rs")


def validate_worldline(kind, beta, a, x=None, t=None, tau0=None, tau1=None):
    """RD2: inertial has |velocity| below 1, accelerated a positive acceleration, parametric x and t; each
    attribute is written only on its kind (tau0 and tau1 on accelerated or parametric)."""
    if kind not in WORLDLINES:
        raise RelativityError("RD2: kind is inertial, accelerated or parametric")
    if kind == "inertial":
        if beta is None:
            raise RelativityError("RD2: an inertial worldline needs a velocity")
        _beta(beta)
    if kind == "accelerated" and (a is None or not a > 0.0):
        raise RelativityError("RD2: an accelerated worldline needs a positive acceleration")
    if kind == "parametric" and (x is None or t is None):
        raise RelativityError("RD2: a parametric worldline needs x and t")
    owners = ((beta, ("inertial",)), (a, ("accelerated",)), (x, ("parametric",)), (t, ("parametric",)),
              (tau0, ("accelerated", "parametric")), (tau1, ("accelerated", "parametric")))
    if any(value is not None and kind not in kinds for value, kinds in owners):
        raise RelativityError("RD2: velocity is inertial's, acceleration accelerated's, x and t parametric's, "
                              "tau0 and tau1 accelerated's and parametric's")


def validate_embedding(kind, r_min, r_max, rings, spokes, rs=None):
    """RD3: kind in the enumeration, 0 < rMin < rMax (rMin at least rs for flamm when rs is given), rings >= 1,
    spokes >= 3; embedding_radii resolves the defaults first."""
    if kind not in EMBEDDINGS:
        raise RelativityError("RD3: kind is flamm or potential")
    if not (r_min > 0.0 and r_max > r_min):
        raise RelativityError("RD3: rMax must exceed a positive rMin (rs)")
    if kind == "flamm" and rs is not None and r_min < rs:
        raise RelativityError("RD3: a flamm sheet's rMin is at least rs")
    if rings < 1 or spokes < 3:
        raise RelativityError("RD3: rings >= 1 and spokes >= 3")


def validate_strain(hplus, hcross, frequency, chirp, merger=None):
    """RD4: |h+| and |hx| at most 1; exactly one of a positive frequency and a positive chirp mass, and
    chirpMass comes with merger."""
    if abs(hplus) > MAX_STRAIN or abs(hcross) > MAX_STRAIN:
        raise RelativityError("RD4: |hPlus| and |hCross| are at most 1")
    if (frequency is None) == (chirp is None):
        raise RelativityError("RD4: a strain has exactly one of frequency and chirpMass")
    if chirp is not None and merger is None:
        raise RelativityError("RD4: chirpMass comes with merger")
    if frequency is not None and not frequency > 0.0:
        raise RelativityError("RD4: frequency must be positive")
    if chirp is not None and not chirp > 0.0:
        raise RelativityError("RD4: chirpMass must be positive")


# ------------------------------------------------------------------------------------ the table

TABLE = (
    ("gamma at 0.6", "gamma(0.6)", "1.25"),
    ("rapidity at 0.6", "rapidity(0.6)", "0.693147"),
    ("boost of (1, 0) at 0.6", "boost(1, 0, 0.6)", "(1.25, -0.75)"),
    ("boost of (0, 1) at 0.6", "boost(0, 1, 0.6)", "(-0.75, 1.25)"),
    ("interval of (3, 5)", "interval(3, 5)", "16"),
    ("interval of (3, 5) boosted at 0.6", "interval(*boost(3, 5, 0.6))", "16"),
    ("interval of (3, 5) boosted at 0.999", "interval(*boost(3, 5, 0.999))", "16"),
    ("composition of 0.5 and 0.5", "compose_beta(0.5, 0.5)", "0.8"),
    ("rapidity adds", "beta_from_rapidity(rapidity(0.5) + rapidity(0.5))", "0.8"),
    ("time dilation at 0.6", "time_dilation(0.6)", "1.25"),
    ("length contraction at 0.6", "length_contraction(0.6)", "0.8"),
    ("Doppler factor at 0.6", "doppler(0.6)", "2"),
    ("separation (1, 2) from the origin", "classify((0, 0), (1, 2))", "'timelike'"),
    ("separation (2, 1) from the origin", "classify((0, 0), (2, 1))", "'spacelike'"),
    ("separation (3, 3) boosted at 0.9", "classify(boost(0, 0, 0.9), boost(3, 3, 0.9))", "'lightlike'"),
    ("proper time to (3, 5)", "proper_time((0, 0), (3, 5))", "4"),
    ("cone slopes after a boost at 0.9", "cone_slopes(boost(1, 2, 0.9), {'future': tuple(boost(*p, 0.9) for p in light_cone((1, 2), 3)['future'])})", "(1, 1)"),
    ("Rindler event at a 2, tau 1", "worldline_accelerated(2, 1)", "(1.3811, 1.81343)"),
    ("Rindler speed at a 2, tau 1", "accelerated_beta(2, 1)", "0.964028"),
    ("x' = 2 line at t = 1, beta 0.6", "grid_x_line(0.6, 2, 1)", "(2.2, 1)"),
    ("the box's line x = 2 drawn at beta 0.6, at t' = 1", "grid_x_line(-0.6, 2, 1)", "(1, 1)"),
    ("Penrose of (1, 0)", "penrose(1, 0)", "(0.785398, 0)"),
    ("Penrose of (1e6, 0)", "penrose(1e6, 0)", "(1.5708, 0)"),
    ("Penrose null slope from (2, -1)", "penrose_slope((2, -1), 1)", "1"),
    ("Kruskal of r 6, t 0, rs 2", "kruskal(6, 0, 2)", "(0, 6.33807)"),
    ("Kruskal of r 6, t 3, rs 2", "kruskal(6, 3, 2)", "(5.2119, 8.20579)"),
    ("Kruskal invariant at r 6", "kruskal(6, 3, 2)[1] ** 2 - kruskal(6, 3, 2)[0] ** 2", "40.1711"),
    ("Kruskal of r 1, t 0, rs 2", "kruskal(1, 0, 2)", "(0.907943, 0)"),
    ("singularity at X 3", "kruskal_singularity(3)", "3.16228"),
    ("Penrose T of the singularity at X 3", "penrose(3, kruskal_singularity(3))[1]", "0.785398"),
    ("radius back from Kruskal (3, 6, 2)", "kruskal_radius(*kruskal(6, 3, 2), 2)", "6"),
    ("Flamm at r 4, rs 2", "flamm(4, 2)", "4"),
    ("Flamm slope at r 4, rs 2", "flamm_slope(4, 2)", "1"),
    ("proper distance 2 to 4, rs 2", "proper_radial_distance(2, 4, 2)", "4.59117"),
    ("arc length 2 to 4 on the sheet", "flamm_arc_length(2, 4, 2)", "4.59117"),
    ("proper distance 3 to 10, rs 2", "proper_radial_distance(3, 10, 2)", "8.78253"),
    ("Flamm curvature at r 4, rs 2", "flamm_curvature(4, 2)", "-0.015625"),
    ("potential sheet at r 2, k 4", "potential(2, 4)", "-2"),
    ("embedding point r 4, phi 0", "embedding_point('flamm', 4, 0, 2)", "(4, -4, 0)"),
    ("embedding point of the potential sheet r 2, k 4", "embedding_point('potential', 2, 0, 4)", "(2, 2, 0)"),
    ("embedding radii of a potential sheet from a hole of mass 3", "embedding_radii('potential', None, 3)", "(6, 1.5)"),
    ("strain of (1, 0) under h+ 0.2", "strain_displacement(1, 0, 0.2, 0)", "(0.1, 0)"),
    ("ring axes under h+ 0.2", "ring_axes(0.2, 0)", "(1.1, 0.9)"),
    ("cross polarisation on the diagonal", "math.hypot(*strain_point(2 ** -0.5, 2 ** -0.5, 0, 0.2, 1, 0, 0))", "1.1"),
    ("chirp mass of 36 and 29 solar masses", "chirp_mass(36, 29)", "28.0956"),
    ("frequency 0.2 s before merger, 28 solar masses", "gw_frequency(0.2, 28 * M_SUN)", "34.4138"),
    ("time to merger from 150 Hz", "time_to_merger(150, 28 * M_SUN)", "0.00394525"),
    ("strain at 410 Mpc, 150 Hz", "gw_amplitude(410 * MPC_M, 28 * M_SUN, 150)", "2.1131e-21"),
    ("cycles from 0.2 s to 0.05 s", "chirp_cycles(0.2, 0.05, 28 * M_SUN)", "6.38227"),
    ("boost at frame 120 of 0 to 0.8 over 10 s", "frame_beta(120, 24, 0, 0.8, 0, 10)", "0.5"),
    ("seek check", "seek_test()", "True"),
    ("pixel of (1, 0) boosted at 0.6", "diagram_pixel(1, 0, {'x': 100, 'y': 50, 'width': 400, 'height': 300, 'xMin': -2, 'xMax': 2, 'yMin': -1.5, 'yMax': 1.5}, 0.6)", "(425, 275)"),
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
