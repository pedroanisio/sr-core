"""Reference implementation of the draft SREP "Add orbits and N-body motion"
(srep/srep-0000-orbits.md; SP4 of SREP 12, SRC-47).

Standard library only. The module gives:

- Kepler's problem: elements to state and back, Kepler's equation (elliptic and hyperbolic), propagation by
  universal variables with the Stumpff functions, so a two-body orbit closes on itself to 1e-12;
- the `orbit` element: an object's state at any time of the space clock from its elements at an epoch;
- the N-body system: masses, positions and velocities in SI units with an optional Plummer softening, its energy,
  momentum and angular momentum;
- three integrators: leapfrog (kick-drift-kick), Wisdom-Holman in Jacobi coordinates with the Kepler drift, and
  IAS15 (Everhart's Gauss-Radau scheme of 15th order as described by Rein and Spiegel 2015) with a fixed step or
  an adaptive one bounded by a tolerance; the error, energy-drift and reversibility measures;
- the Plummer cluster drawn from the random streams of the F1 draft (Aarseth, Henon and Wielen's sampling);
- trails (the times and fading of a ribbon of past positions), the frame state as a pure function of the frame
  index and the seek check; `main()` prints the draft's numeric table.
"""
import math

G = 6.67430e-11  # m^3 kg^-1 s^-2 (CODATA 2018)
AU_M = 149597870700.0  # the astronomical unit (IAU 2012)
DAY_S = 86400.0
GM_SUN = 1.32712440041279419e20  # m^3 s^-2, DE440
GM_EARTH = 3.98600435507e14
GM = {  # m^3 s^-2, the DE440 header values (Park et al. 2021) for the bodies with IAU radii in the planets draft
    10: GM_SUN,
    199: 2.2031868551e13,
    299: 3.24858592e14,
    399: GM_EARTH,
    499: 4.2828375816e13,
    599: 1.26712764100000e17,
    699: 3.7940584841800e16,
    799: 5.7945564e15,
    899: 6.83652710058e15,
    301: 4.902800118e12,
}
INTEGRATORS = ("leapfrog", "wisdomHolman", "ias15")
MAX_KEPLER_ITERATIONS = 60
MAX_UNIVERSAL_ITERATIONS = 60
MAX_RADAU_ITERATIONS = 12
MAX_STEPS = 1_000_000  # the deterministic bound of an adaptive integration
MAX_BODIES = 4096
MAX_TRIES = 64  # rejection draws per Plummer speed
STEP_TOLERANCE = 1e-9  # a frame time is a whole number of steps within this fraction of a step
MASK64 = (1 << 64) - 1
PHI = 0x9E3779B97F4A7C15
MUL1 = 0xBF58476D1CE4E5B9
MUL2 = 0x94D049BB133111EB
TWO53 = float(1 << 53)


class OrbitError(ValueError):
    """An orbit, a system, a step or a draw the draft does not admit."""


# ------------------------------------------------------------------------------------ vectors


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n == 0.0:
        raise OrbitError("a zero vector has no direction")
    return (a[0] / n, a[1] / n, a[2] / n)


ZERO = (0.0, 0.0, 0.0)


# ------------------------------------------------------------------------------------ rule 1: Kepler's problem


def period(mu, a):
    """2 pi sqrt(a^3 / mu) of an ellipse."""
    if not (mu > 0.0) or not (a > 0.0):
        raise OrbitError("the period needs a positive mu and a positive semi-major axis")
    return 2.0 * math.pi * math.sqrt(a ** 3 / mu)


def specific_energy(mu, r, v):
    """v^2 / 2 - mu / r."""
    return dot(v, v) / 2.0 - mu / norm(r)


def kepler_elliptic(mean_anomaly, e):
    """E - e sin E = M, radians; Newton's iterations from Danby's start, bounded."""
    if not (0.0 <= e < 1.0):
        raise OrbitError("the elliptic eccentricity is in [0, 1)")
    m = math.remainder(mean_anomaly, 2.0 * math.pi)
    big_e = m + 0.85 * e * (1.0 if math.sin(m) >= 0.0 else -1.0)
    for _ in range(MAX_KEPLER_ITERATIONS):
        f = big_e - e * math.sin(big_e) - m
        de = f / (1.0 - e * math.cos(big_e))
        big_e -= de
        if abs(de) <= 1e-15 * max(1.0, abs(big_e)):
            return big_e
    raise OrbitError("Kepler's equation did not converge")


def kepler_hyperbolic(mean_anomaly, e):
    """e sinh H - H = M, radians."""
    if not (e > 1.0):
        raise OrbitError("the hyperbolic eccentricity is above 1")
    h = math.asinh(mean_anomaly / e)
    for _ in range(MAX_KEPLER_ITERATIONS):
        f = e * math.sinh(h) - h - mean_anomaly
        dh = f / (e * math.cosh(h) - 1.0)
        h -= dh
        if abs(dh) <= 1e-15 * max(1.0, abs(h)):
            return h
    raise OrbitError("the hyperbolic Kepler equation did not converge")


def _check_conic(a, e):
    if not (e >= 0.0) or abs(e - 1.0) < 1e-12:
        raise OrbitError("the eccentricity is non-negative and not 1 (the parabola is excluded)")
    if (e < 1.0 and not a > 0.0) or (e > 1.0 and not a < 0.0):
        raise OrbitError("a is positive for an ellipse and negative for a hyperbola")


def state_from_elements(mu, a, e, i, raan, argp, nu):
    """Position (m) and velocity (m/s) from the classical elements (a in m, angles in degrees, nu the true
    anomaly)."""
    if not (mu > 0.0):
        raise OrbitError("mu is positive")
    _check_conic(a, e)
    p = a * (1.0 - e * e)
    nu_r = math.radians(nu)
    denom = 1.0 + e * math.cos(nu_r)
    if not (denom > 0.0):
        raise OrbitError("the true anomaly is outside the hyperbola's asymptotes")
    r = p / denom
    rp = (r * math.cos(nu_r), r * math.sin(nu_r), 0.0)
    k = math.sqrt(mu / p)
    vp = (-k * math.sin(nu_r), k * (e + math.cos(nu_r)), 0.0)
    m = _perifocal_to_inertial(i, raan, argp)
    return _apply(m, rp), _apply(m, vp)


def _perifocal_to_inertial(i, raan, argp):
    ci, si = math.cos(math.radians(i)), math.sin(math.radians(i))
    co, so = math.cos(math.radians(raan)), math.sin(math.radians(raan))
    cw, sw = math.cos(math.radians(argp)), math.sin(math.radians(argp))
    return ((co * cw - so * sw * ci, -co * sw - so * cw * ci, so * si),
            (so * cw + co * sw * ci, -so * sw + co * cw * ci, -co * si),
            (sw * si, cw * si, ci))


def _apply(m, v):
    return tuple(dot(row, v) for row in m)


def _deg360(x):
    return math.degrees(x) % 360.0


def elements_from_state(mu, r, v):
    """The classical elements of a state: a, e, i, raan, argp, nu, M (degrees), period (None for a hyperbola),
    the specific energy and the specific angular momentum vector h."""
    if not (mu > 0.0):
        raise OrbitError("mu is positive")
    rn = norm(r)
    h = cross(r, v)
    hn = norm(h)
    if rn == 0.0 or hn <= 1e-12 * rn * norm(v) or hn == 0.0:
        raise OrbitError("a radial or degenerate state has no orbit plane")
    energy = dot(v, v) / 2.0 - mu / rn
    if abs(energy) < 1e-14 * mu / rn:
        raise OrbitError("a parabolic state has no semi-major axis")
    a = -mu / (2.0 * energy)
    e_vec = mul(sub(mul(r, dot(v, v) - mu / rn), mul(v, dot(r, v))), 1.0 / mu)
    e = norm(e_vec)
    h_hat = mul(h, 1.0 / hn)
    inc = math.acos(max(-1.0, min(1.0, h_hat[2])))
    node = cross((0.0, 0.0, 1.0), h)
    if norm(node) <= 1e-12 * hn:
        n_hat, raan = (1.0, 0.0, 0.0), 0.0
    else:
        n_hat = unit(node)
        raan = math.atan2(node[1], node[0])
    if e <= 1e-12:
        e_hat, argp = n_hat, 0.0
    else:
        e_hat = mul(e_vec, 1.0 / e)
        argp = math.atan2(dot(cross(n_hat, e_hat), h_hat), dot(n_hat, e_hat))
    r_hat = mul(r, 1.0 / rn)
    nu = math.atan2(dot(cross(e_hat, r_hat), h_hat), dot(e_hat, r_hat))
    if e < 1.0:
        big_e = 2.0 * math.atan2(math.sqrt(1.0 - e) * math.sin(nu / 2.0), math.sqrt(1.0 + e) * math.cos(nu / 2.0))
        mean = big_e - e * math.sin(big_e)
        per = period(mu, a)
    else:
        big_h = 2.0 * math.atanh(math.sqrt((e - 1.0) / (e + 1.0)) * math.tan(nu / 2.0))
        mean = e * math.sinh(big_h) - big_h
        per = None
    return {"a": a, "e": e, "i": math.degrees(inc), "raan": _deg360(raan), "argp": _deg360(argp),
            "nu": _deg360(nu), "M": _deg360(mean), "period": per, "energy": energy, "h": h}


def stumpff_c2(z):
    """(1 - cos sqrt z) / z, continued through z = 0 and to z < 0."""
    if abs(z) < 1e-3:
        return 0.5 - z / 24.0 + z * z / 720.0 - z ** 3 / 40320.0 + z ** 4 / 3628800.0
    if z > 0.0:
        return (1.0 - math.cos(math.sqrt(z))) / z
    return (math.cosh(math.sqrt(-z)) - 1.0) / -z


def stumpff_c3(z):
    """(sqrt z - sin sqrt z) / sqrt z^3, continued through z = 0 and to z < 0."""
    if abs(z) < 1e-3:
        return 1.0 / 6.0 - z / 120.0 + z * z / 5040.0 - z ** 3 / 362880.0 + z ** 4 / 39916800.0
    if z > 0.0:
        s = math.sqrt(z)
        return (s - math.sin(s)) / s ** 3
    s = math.sqrt(-z)
    return (math.sinh(s) - s) / s ** 3


def propagate(mu, r0, v0, dt):
    """The state `dt` seconds later (or earlier) by the universal variable chi with Newton's iterations and the
    Lagrange f and g functions (Vallado, algorithm 8)."""
    if not (mu > 0.0):
        raise OrbitError("mu is positive")
    r0n = norm(r0)
    if r0n == 0.0:
        raise OrbitError("the state is at the centre")
    if dt == 0.0:
        return tuple(r0), tuple(v0)
    sqmu = math.sqrt(mu)
    rv = dot(r0, v0)
    alpha = 2.0 / r0n - dot(v0, v0) / mu  # 1 / a
    if alpha > 1e-12 / r0n:
        chi = sqmu * alpha * dt
    elif alpha < -1e-12 / r0n:
        a = 1.0 / alpha
        sign = 1.0 if dt > 0.0 else -1.0
        num = -2.0 * mu * alpha * dt
        den = rv + sign * math.sqrt(-mu * a) * (1.0 - r0n * alpha)
        chi = sign * math.sqrt(-a) * math.log(num / den)
    else:
        h = norm(cross(r0, v0))
        p = h * h / mu
        s = 0.5 * math.atan(1.0 / (3.0 * math.sqrt(mu / p ** 3) * dt))
        w = math.atan(math.tan(s) ** (1.0 / 3.0))
        chi = math.sqrt(p) * 2.0 / math.tan(2.0 * w)
    last = math.inf
    for _ in range(MAX_UNIVERSAL_ITERATIONS):
        z = alpha * chi * chi
        c2, c3 = stumpff_c2(z), stumpff_c3(z)
        r = chi * chi * c2 + rv / sqmu * chi * (1.0 - z * c3) + r0n * (1.0 - z * c2)
        f = rv / sqmu * chi * chi * c2 + (1.0 - alpha * r0n) * chi ** 3 * c3 + r0n * chi - sqmu * dt
        d = f / r
        chi -= d
        step = abs(d) / max(1.0, abs(chi))
        if step <= 4e-16 or (step <= 1e-12 and step >= last):  # at rounding, or no longer shrinking
            break
        last = step
    else:
        raise OrbitError("the universal Kepler equation did not converge")
    z = alpha * chi * chi
    c2, c3 = stumpff_c2(z), stumpff_c3(z)
    f = 1.0 - chi * chi * c2 / r0n
    g = dt - chi ** 3 * c3 / sqmu
    r = add(mul(r0, f), mul(v0, g))
    rn = norm(r)
    gdot = 1.0 - chi * chi * c2 / rn
    fdot = sqmu / (r0n * rn) * chi * (z * c3 - 1.0)
    v = add(mul(r0, fdot), mul(v0, gdot))
    return r, v


def closure(mu, r, v):
    """The largest relative deviation of position and velocity after one period."""
    el = elements_from_state(mu, r, v)
    if el["period"] is None:
        raise OrbitError("only an ellipse closes")
    r1, v1 = propagate(mu, r, v, el["period"])
    return max(norm(sub(r, r1)) / norm(r), norm(sub(v, v1)) / norm(v))


def orbit_mu(mass=None, body=None):
    """The gravitational parameter of the central object: G times its mass, or the GM of its NAIF body."""
    if mass is not None:
        if not (mass > 0.0):
            raise OrbitError("the central mass is positive")
        return G * mass
    if body is not None:
        if body not in GM:
            raise OrbitError(f"no GM for body {body}; the draft covers {sorted(GM)}")
        return GM[body]
    raise OrbitError("the orbit's central object needs a mass or a body")


def orbit(mu, a, e, i, raan, argp, anomaly, epoch):
    """The `orbit` element: the state at `epoch` (seconds of the space clock past its epoch) from the elements."""
    if not math.isfinite(epoch):
        raise OrbitError("the orbit's epoch is finite")
    r, v = state_from_elements(mu, a, e, i, raan, argp, anomaly)
    return {"mu": float(mu), "r0": r, "v0": v, "epoch": float(epoch)}


def orbit_state(orb, t):
    """Position and velocity at time t of the space clock."""
    return propagate(orb["mu"], orb["r0"], orb["v0"], t - orb["epoch"])


# ------------------------------------------------------------------------------------ rule 2: the system


def system(masses, positions, velocities, G=G, softening=0.0, t=0.0):
    """An N-body state: masses (kg), positions (m) and velocities (m/s), the constant and the Plummer softening."""
    n = len(masses)
    if n < 1 or n > MAX_BODIES or len(positions) != n or len(velocities) != n:
        raise OrbitError(f"1 to {MAX_BODIES} bodies, each with a mass, a position and a velocity")
    if not all(m > 0.0 and math.isfinite(m) for m in masses):
        raise OrbitError("masses are positive and finite")
    if not (G > 0.0) or not (softening >= 0.0):
        raise OrbitError("G is positive and the softening non-negative")
    pos = [tuple(float(x) for x in p) for p in positions]
    vel = [tuple(float(x) for x in v) for v in velocities]
    if softening == 0.0:
        for i in range(n):
            for j in range(i + 1, n):
                if pos[i] == pos[j]:
                    raise OrbitError(f"bodies {i} and {j} coincide and the softening is zero")
    return {"n": n, "masses": [float(m) for m in masses], "positions": pos, "velocities": vel, "G": float(G),
            "softening": float(softening), "t": float(t)}


def _with(s, positions, velocities, t):
    return {"n": s["n"], "masses": s["masses"], "positions": positions, "velocities": velocities, "G": s["G"],
            "softening": s["softening"], "t": t}


def accelerations(s, positions):
    """Newtonian accelerations with Plummer softening: a_i = sum_j G m_j (r_j - r_i) / (|r_j - r_i|^2 + eps^2)^(3/2)."""
    n, m, g, eps2 = s["n"], s["masses"], s["G"], s["softening"] ** 2
    acc = [ZERO] * n
    for i in range(n):
        for j in range(i + 1, n):
            d = sub(positions[j], positions[i])
            inv = (dot(d, d) + eps2) ** -1.5
            acc[i] = add(acc[i], mul(d, g * m[j] * inv))
            acc[j] = sub(acc[j], mul(d, g * m[i] * inv))
    return acc


def kinetic(s):
    return sum(0.5 * m * dot(v, v) for m, v in zip(s["masses"], s["velocities"]))


def potential(s):
    n, m, p, g, eps2 = s["n"], s["masses"], s["positions"], s["G"], s["softening"] ** 2
    total = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            d = sub(p[j], p[i])
            total -= g * m[i] * m[j] / math.sqrt(dot(d, d) + eps2)
    return total


def energy(s):
    return kinetic(s) + potential(s)


def momentum(s):
    total = ZERO
    for m, v in zip(s["masses"], s["velocities"]):
        total = add(total, mul(v, m))
    return total


def centre_of_mass(s):
    total = ZERO
    for m, p in zip(s["masses"], s["positions"]):
        total = add(total, mul(p, m))
    return mul(total, 1.0 / sum(s["masses"]))


def angular_momentum(s):
    total = ZERO
    for m, p, v in zip(s["masses"], s["positions"], s["velocities"]):
        total = add(total, mul(cross(p, v), m))
    return total


def at_rest(s):
    """The same system in its barycentric frame: the centre of mass at the origin and at rest."""
    com = centre_of_mass(s)
    vcom = mul(momentum(s), 1.0 / sum(s["masses"]))
    return _with(s, [sub(p, com) for p in s["positions"]], [sub(v, vcom) for v in s["velocities"]], s["t"])


# ------------------------------------------------------------------------------------ rule 3: integrators


def step_leapfrog(s, dt):
    """Kick-drift-kick."""
    a = accelerations(s, s["positions"])
    v_half = [add(v, mul(ai, dt / 2.0)) for v, ai in zip(s["velocities"], a)]
    x = [add(p, mul(v, dt)) for p, v in zip(s["positions"], v_half)]
    a = accelerations(s, x)
    v = [add(vh, mul(ai, dt / 2.0)) for vh, ai in zip(v_half, a)]
    return _with(s, x, v, s["t"] + dt)


def _jacobi(masses, vectors):
    """Jacobi coordinates: r_i = x_i - X_{i-1}, X_i the centre of mass of bodies 0..i; returns (r, X_last, M)."""
    big_x, big_m = vectors[0], masses[0]
    r = [None] * len(masses)
    cum = [big_m]
    for i in range(1, len(masses)):
        r[i] = sub(vectors[i], big_x)
        big_x = mul(add(mul(big_x, big_m), mul(vectors[i], masses[i])), 1.0 / (big_m + masses[i]))
        big_m += masses[i]
        cum.append(big_m)
    return r, big_x, cum


def _from_jacobi(masses, r, big_x, cum):
    n = len(masses)
    out = [None] * n
    x = big_x
    for i in range(n - 1, 0, -1):
        x = sub(x, mul(r[i], masses[i] / cum[i]))
        out[i] = add(x, r[i])
    out[0] = x
    return out


def _interaction_accelerations(s, positions, r, cum):
    """Cartesian accelerations of H_int = sum_i G m_i M_{i-1} / |r_i| - sum_pairs G m_i m_j / |x_i - x_j|."""
    n, m, g = s["n"], s["masses"], s["G"]
    a = accelerations(s, positions)
    kep = [None] + [mul(r[i], g / norm(r[i]) ** 3) for i in range(1, n)]  # G r_i / |r_i|^3
    out = []
    for j in range(n):
        aj = a[j]
        if j >= 1:
            aj = add(aj, mul(kep[j], cum[j - 1]))
        for i in range(j + 1, n):
            aj = sub(aj, mul(kep[i], m[i]))
        out.append(aj)
    return out


def step_wisdom_holman(s, dt):
    """Wisdom and Holman (1991) in Jacobi coordinates, kick-drift-kick: the interaction kick for dt / 2, the
    Kepler drift of every Jacobi coordinate about the mass inside it for dt, the kick for dt / 2."""
    if s["softening"] != 0.0:
        raise OrbitError("the Wisdom-Holman splitting has no softening")
    n, m, g = s["n"], s["masses"], s["G"]
    if n == 1:
        return _with(s, [add(s["positions"][0], mul(s["velocities"][0], dt))], s["velocities"], s["t"] + dt)
    r, big_x, cum = _jacobi(m, s["positions"])
    rdot, big_v, _ = _jacobi(m, s["velocities"])
    rdot = _kick(s, m, r, rdot, big_x, big_v, cum, dt / 2.0)
    for i in range(1, n):
        r[i], rdot[i] = propagate(g * cum[i], r[i], rdot[i], dt)
    big_x = add(big_x, mul(big_v, dt))
    rdot = _kick(s, m, r, rdot, big_x, big_v, cum, dt / 2.0)
    return _with(s, _from_jacobi(m, r, big_x, cum), _from_jacobi(m, rdot, big_v, cum), s["t"] + dt)


def _kick(s, m, r, rdot, big_x, big_v, cum, dt):
    positions = _from_jacobi(m, r, big_x, cum)
    a = _interaction_accelerations(s, positions, r, cum)
    a_j, _, _ = _jacobi(m, a)
    return [rdot[0]] + [add(rdot[i], mul(a_j[i], dt)) for i in range(1, s["n"])]


def _legendre(n, x):
    p0, p1 = 1.0, x
    if n == 0:
        return p0
    for k in range(2, n + 1):
        p0, p1 = p1, ((2 * k - 1) * x * p1 - (k - 1) * p0) / k
    return p1


def radau_nodes(n=8):
    """The left Gauss-Radau nodes on [0, 1]: 0 and the roots of P_{n-1} + P_n in (-1, 1) mapped by (x + 1) / 2."""
    f = lambda x: _legendre(n - 1, x) + _legendre(n, x)
    roots = []
    grid = 4000
    xs = [-1.0 + 1e-9 + (2.0 - 2e-9) * k / grid for k in range(grid + 1)]
    for a, b in zip(xs, xs[1:]):
        fa, fb = f(a), f(b)
        if fa == 0.0:
            roots.append(a)
            continue
        if fa * fb < 0.0:
            for _ in range(200):
                c = (a + b) / 2.0
                fc = f(c)
                if fc == 0.0 or (b - a) < 1e-17:
                    break
                if fa * fc < 0.0:
                    b, fb = c, fc
                else:
                    a, fa = c, fc
            roots.append((a + b) / 2.0)
    if len(roots) != n - 1:
        raise OrbitError("the Radau polynomial did not yield its roots")
    return (0.0,) + tuple((x + 1.0) / 2.0 for x in sorted(roots))


def _solve(matrix, rhs):
    """Gaussian elimination with partial pivoting."""
    n = len(rhs)
    m = [list(row) + [b] for row, b in zip(matrix, rhs)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [a - f * b for a, b in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def radau_weights(h):
    """Quadrature weights on [0, 1] for the nodes: exact for polynomials up to degree 2n - 2."""
    n = len(h)
    return tuple(_solve([[hi ** k for hi in h] for k in range(n)], [1.0 / (k + 1) for k in range(n)]))


RADAU_H = radau_nodes()
RADAU_W = radau_weights(RADAU_H)


def _newton_to_monomial(h):
    """c[j][k]: the coefficient of tau^k in prod_{i=1..j} (tau - h_i), j = 0..6."""
    rows = []
    poly = [1.0]
    for j in range(7):
        if j > 0:
            poly = [0.0] + poly
            poly = [poly[k] - (h[j] * poly[k + 1] if k + 1 < len(poly) else 0.0) for k in range(len(poly))]
        rows.append(tuple(poly) + (0.0,) * (7 - len(poly)))
    return tuple(rows)


RADAU_C = _newton_to_monomial(RADAU_H)
RADAU_R = tuple(tuple(1.0 / (RADAU_H[i] - RADAU_H[j]) if j < i else 0.0 for j in range(8)) for i in range(8))


def b_from_g(g):
    """b_k = sum_{j >= k} c_{jk} g_j: the monomial coefficients of the Newton form."""
    return tuple(sum(RADAU_C[j][k] * g[j] for j in range(k, 7)) for k in range(7))


def _flat(vectors):
    return [c for v in vectors for c in v]


def _unflat(flat):
    return [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]


def _radau_step(s, dt, b_start):
    """One Gauss-Radau step of size dt from a guess of the b coefficients; returns (positions, velocities, b,
    the error estimate max|b6| / max|a0|)."""
    h, n3 = RADAU_H, 3 * s["n"]
    x0, v0 = _flat(s["positions"]), _flat(s["velocities"])
    a0 = _flat(accelerations(s, s["positions"]))
    b = [list(bk) for bk in b_start]
    g = [[0.0] * n3 for _ in range(7)]
    a_scale = max(abs(a) for a in a0) or 1.0
    for _ in range(MAX_RADAU_ITERATIONS):
        change = 0.0
        for nn in range(1, 8):
            tau = h[nn]
            xn = [x0[c] + v0[c] * dt * tau + dt * dt * (a0[c] * tau * tau / 2.0 + sum(
                b[k][c] * tau ** (k + 3) / ((k + 2) * (k + 3)) for k in range(7))) for c in range(n3)]
            an = _flat(accelerations(s, _unflat(xn)))
            for c in range(n3):
                temp = (an[c] - a0[c]) * RADAU_R[nn][0]
                for j in range(1, nn):
                    temp = (temp - g[j - 1][c]) * RADAU_R[nn][j]
                g[nn - 1][c] = temp
            for c in range(n3):
                new = b_from_g([g[j][c] for j in range(7)])
                for k in range(7):
                    change = max(change, abs(new[k] - b[k][c]))
                    b[k][c] = new[k]
        if change <= 1e-16 * a_scale:
            break
    x1 = [x0[c] + v0[c] * dt + dt * dt * (a0[c] / 2.0 + sum(b[k][c] / ((k + 2) * (k + 3)) for k in range(7)))
          for c in range(n3)]
    v1 = [v0[c] + dt * (a0[c] + sum(b[k][c] / (k + 2) for k in range(7))) for c in range(n3)]
    err = max(abs(x) for x in b[6]) / a_scale
    return _unflat(x1), _unflat(v1), [tuple(bk) for bk in b], err


def step_ias15(s, dt, b_start=None):
    """One IAS15 step of a fixed size: returns the new system and the converged b coefficients (the predictor
    of the next step)."""
    if b_start is None:
        b_start = [(0.0,) * (3 * s["n"])] * 7
    x, v, b, _ = _radau_step(s, dt, b_start)
    return _with(s, x, v, s["t"] + dt), b


def steps_to(t, step):
    """The whole number of steps in a time, or an error when the time is not one within STEP_TOLERANCE."""
    if not (step > 0.0) or not (t >= 0.0):
        raise OrbitError("the step is positive and the time non-negative")
    n = round(t / step)
    if abs(t / step - n) > STEP_TOLERANCE:
        raise OrbitError("the time is a whole number of steps")
    return int(n)


def integrate(s, integrator, step, t):
    """The system `t` seconds later by a fixed step that divides t."""
    if integrator not in INTEGRATORS:
        raise OrbitError(f"the integrator is one of {INTEGRATORS}")
    n = steps_to(t, step)
    if n > MAX_STEPS:
        raise OrbitError(f"more than {MAX_STEPS} steps")
    out = s
    b = None
    for _ in range(n):
        if integrator == "leapfrog":
            out = step_leapfrog(out, step)
        elif integrator == "wisdomHolman":
            out = step_wisdom_holman(out, step)
        else:
            out, b = step_ias15(out, step, b)
    return out


def integrate_adaptive(s, t, dt0, epsilon, max_steps=MAX_STEPS):
    """IAS15 with the adaptive step of Rein and Spiegel: a step is rejected when max|b6| / max|a| exceeds
    epsilon and retried at dt (epsilon / error)^(1/7); an accepted step grows by at most 1.4; the last step lands
    on t. Returns the system and the count, smallest and largest accepted step."""
    if not (epsilon > 0.0) or not (dt0 > 0.0) or not (t >= 0.0):
        raise OrbitError("the tolerance, the first step and the time are positive")
    out, dt, b = s, min(dt0, t) if t > 0.0 else dt0, None
    end = s["t"] + t
    count, smallest, largest = 0, math.inf, 0.0
    while out["t"] < end - 1e-15 * max(1.0, abs(end)):
        if count >= max_steps:
            raise OrbitError(f"more than {max_steps} steps")
        dt = min(dt, end - out["t"])
        x, v, b_new, err = _radau_step(out, dt, b or [(0.0,) * (3 * s["n"])] * 7)
        ratio = (epsilon / err) ** (1.0 / 7.0) if err > 0.0 else 1.4
        if ratio < 1.0:
            dt *= 0.99 * ratio
            count += 1
            continue
        out, b = _with(out, x, v, out["t"] + dt), b_new
        count += 1
        smallest, largest = min(smallest, dt), max(largest, dt)
        dt *= min(ratio, 1.4)
    return _with(out, out["positions"], out["velocities"], end), {"count": count, "min": smallest, "max": largest}


def energy_drift(s, integrator, step, t):
    """The largest |E - E0| / |E0| over the steps."""
    e0 = energy(s)
    n = steps_to(t, step)
    out, b, worst = s, None, 0.0
    for _ in range(n):
        if integrator == "leapfrog":
            out = step_leapfrog(out, step)
        elif integrator == "wisdomHolman":
            out = step_wisdom_holman(out, step)
        elif integrator == "ias15":
            out, b = step_ias15(out, step, b)
        else:
            raise OrbitError(f"the integrator is one of {INTEGRATORS}")
        worst = max(worst, abs(energy(out) - e0) / abs(e0))
    return worst


def reversibility(s, integrator, step, t):
    """Forward for t, velocities reversed, forward for t again: the largest position error over the largest
    initial distance from the origin."""
    forward = integrate(s, integrator, step, t)
    flipped = _with(forward, forward["positions"], [mul(v, -1.0) for v in forward["velocities"]], forward["t"])
    back = integrate(flipped, integrator, step, t)
    scale = max(norm(p) for p in s["positions"]) or 1.0
    return max(norm(sub(a, b)) for a, b in zip(back["positions"], s["positions"])) / scale


def position_error(s, integrator, step, t):
    """For two bodies: the distance between the integrated relative position and Kepler's exact one."""
    if s["n"] != 2:
        raise OrbitError("the exact solution is the two-body one")
    mu = s["G"] * (s["masses"][0] + s["masses"][1])
    r0 = sub(s["positions"][1], s["positions"][0])
    v0 = sub(s["velocities"][1], s["velocities"][0])
    exact, _ = propagate(mu, r0, v0, t)
    out = integrate(s, integrator, step, t)
    return norm(sub(sub(out["positions"][1], out["positions"][0]), exact))


# ------------------------------------------------------------------------------------ rule 4: the Plummer cluster


def _u64(x):
    if not isinstance(x, int) or x < -(1 << 63) or x >= (1 << 64):
        raise OrbitError(f"not a 64-bit integer: {x!r}")
    return x & MASK64


def _mix64(z):
    z &= MASK64
    z = ((z ^ (z >> 30)) * MUL1) & MASK64
    z = ((z ^ (z >> 27)) * MUL2) & MASK64
    return z ^ (z >> 31)


def _splitmix64(x):
    return _mix64((_u64(x) + PHI) & MASK64)


def H(seed, channel, index):
    """The F1 lattice hash H(s, c, i) = splitmix64(s xor splitmix64(c xor splitmix64(i)))."""
    return _splitmix64(_u64(seed) ^ _splitmix64(_u64(channel) ^ _splitmix64(_u64(index))))


def U(seed, channel, index):
    """The F1 unit draw in [0, 1)."""
    return (H(seed, channel, index) >> 11) / TWO53


def plummer_radius(u, scale):
    """The inverse of the Plummer cumulative mass: r = a / sqrt(u^(-2/3) - 1)."""
    u = max(u, 1e-10)
    return scale / math.sqrt(u ** (-2.0 / 3.0) - 1.0)


def plummer_escape_speed(r, total_mass, scale, G):
    """sqrt(2 G M / a) (1 + r^2 / a^2)^(-1/4)."""
    return math.sqrt(2.0 * G * total_mass / scale) * (1.0 + (r / scale) ** 2) ** -0.25


def plummer_q(seed, channel, index):
    """Aarseth, Henon and Wielen (1974): q in [0, 1) with density q^2 (1 - q^2)^(7/2) by rejection against
    0.1 U; the draws of one body are MAX_TRIES consecutive indices of two channels, so the sequence is bounded."""
    for t in range(MAX_TRIES):
        k = index * MAX_TRIES + t
        q = U(seed, channel, k)
        y = 0.1 * U(seed, channel + 1, k)
        if y <= q * q * (1.0 - q * q) ** 3.5:
            return q, t + 1
    raise OrbitError(f"no Plummer speed accepted in {MAX_TRIES} draws")


def plummer_sample(seed, index, total_mass, scale, G):
    """One body of the cluster before recentring: channels 0 (radius), 1-2 (direction), 3-4 (speed), 5-6
    (velocity direction)."""
    r = plummer_radius(U(seed, 0, index), scale)
    ct = 2.0 * U(seed, 1, index) - 1.0
    ph = 2.0 * math.pi * U(seed, 2, index)
    st = math.sqrt(max(0.0, 1.0 - ct * ct))
    p = (r * st * math.cos(ph), r * st * math.sin(ph), r * ct)
    q, _ = plummer_q(seed, 3, index)
    speed = q * plummer_escape_speed(r, total_mass, scale, G)
    cv = 2.0 * U(seed, 5, index) - 1.0
    pv = 2.0 * math.pi * U(seed, 6, index)
    sv = math.sqrt(max(0.0, 1.0 - cv * cv))
    v = (speed * sv * math.cos(pv), speed * sv * math.sin(pv), speed * cv)
    return p, v


def plummer(seed, n, total_mass, scale, G=G):
    """A Plummer sphere of n equal masses drawn from the random streams, recentred and at rest."""
    if not isinstance(n, int) or n < 2 or n > MAX_BODIES:
        raise OrbitError(f"a cluster has 2 to {MAX_BODIES} bodies")
    if not (total_mass > 0.0) or not (scale > 0.0):
        raise OrbitError("the cluster's mass and scale radius are positive")
    samples = [plummer_sample(seed, i, total_mass, scale, G) for i in range(n)]
    s = system([total_mass / n] * n, [p for p, _ in samples], [v for _, v in samples], G=G)
    return at_rest(s)


# ------------------------------------------------------------------------------------ rules 5 and 6: trails, frames, seek


def trail_times(t, length, count):
    """The `count` sample times of a trail ending at t, evenly spaced over the last `length` seconds and clamped
    at the epoch (time 0)."""
    if not isinstance(count, int) or count < 2 or not (length > 0.0):
        raise OrbitError("a trail has two samples or more over a positive length")
    return tuple(max(0.0, t - length * (count - 1 - k) / (count - 1)) for k in range(count))


def trail_alpha(age, length, fade=True):
    """The opacity of a sample `age` seconds old: 1 - age / length when fading, else 1."""
    if not fade:
        return 1.0
    return max(0.0, min(1.0, 1.0 - age / length))


def orbit_trail(orb, t, length, count):
    """The positions of an orbit's trail."""
    return [orbit_state(orb, tk)[0] for tk in trail_times(t, length, count)]


def frame_state(s, integrator, step, frame, fps, rate):
    """The system at a frame: integrated from the epoch over frame / fps * rate seconds, a whole number of steps."""
    if not isinstance(frame, int) or frame < 0 or not (fps > 0) or not (rate >= 0.0):
        raise OrbitError("the frame is a non-negative integer, fps positive and the rate non-negative")
    return integrate(s, integrator, step, frame / fps * rate)


def seek_test(frames=240, fps=24, integrator="leapfrog"):
    """Frame `frames` integrated alone equals the frame reached by playing every frame (SREP 14)."""
    s = _pair()
    p = 2.0 * math.pi
    step, rate = p / 240.0, p / 10.0
    direct = frame_state(s, integrator, step, frames, fps, rate)
    played = s
    for k in range(1, frames + 1):
        played = integrate(played, integrator, step, k / fps * rate - (k - 1) / fps * rate)
    return all(norm(sub(a, b)) <= 1e-9 for a, b in zip(direct["positions"], played["positions"]))


def scene_position(p_m, origin_m, pixels_per_meter):
    """Scene units of a position in metres: (x, -z, y) of the offset from the origin times pixelsPerMeter."""
    if not (pixels_per_meter > 0.0):
        raise OrbitError("pixelsPerMeter is positive")
    d = sub(p_m, origin_m)
    return (d[0] * pixels_per_meter, -d[2] * pixels_per_meter, d[1] * pixels_per_meter)


# ------------------------------------------------------------------------------------ the draft's numeric table


def _pair():
    m, mu = 1e-3, 1.0 + 1e-3
    v = math.sqrt(mu)
    return system([1.0, m], [ZERO, (1.0, 0.0, 0.0)], [(0.0, -v * m / mu, 0.0), (0.0, v / mu, 0.0)], G=1.0)


def _three():
    s = system([1.0, 1e-3, 1e-4], [ZERO, (1.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
               [ZERO, (0.0, 1.0, 0.0), (-math.sqrt(0.5), 0.0, 0.0)], G=1.0)
    return at_rest(s)


def _eight():
    x1 = (0.97000436, -0.24308753, 0.0)
    v3 = (-0.93240737, -0.86473146, 0.0)
    return system([1.0, 1.0, 1.0], [x1, mul(x1, -1.0), ZERO], [mul(v3, -0.5), mul(v3, -0.5), v3], G=1.0)


EARTH_R, EARTH_V = (AU_M, 0.0, 0.0), (0.0, math.sqrt(GM_SUN / AU_M), 0.0)
TWO_PI = 2.0 * math.pi
EIGHT_PERIOD = 6.32591398

TABLE = [
    ("Earth's period at 1 au (days)", "period(GM_SUN, AU_M) / DAY_S", "365.257"),
    ("Kepler's equation, M 2, e 0.5", "kepler_elliptic(2.0, 0.5)", "2.35424"),
    ("hyperbolic Kepler, M 6, e 2", "kepler_hyperbolic(6.0, 2.0)", "2.10769"),
    ("Stumpff c2 and c3 at z 4", "(stumpff_c2(4.0), stumpff_c3(4.0))", "(0.354037, 0.136338)"),
    ("elements of the circular 1 au orbit: a over au, e", "(elements_from_state(GM_SUN, EARTH_R, EARTH_V)['a'] / AU_M, round(elements_from_state(GM_SUN, EARTH_R, EARTH_V)['e'], 12))", "(1, 0)"),
    ("state from elements: perihelion distance over au", "norm(state_from_elements(GM_SUN, AU_M, 0.0167, 0.0, 0.0, 102.9, 0.0)[0]) / AU_M", "0.9833"),
    ("true anomaly a quarter period after perihelion, e 0.3 (deg)", "elements_from_state(GM_SUN, *propagate(GM_SUN, *state_from_elements(GM_SUN, AU_M, 0.3, 0.0, 0.0, 0.0, 0.0), period(GM_SUN, AU_M) / 4.0))['nu']", "122.543"),
    ("two-body closure, e 0.3", "closure(GM_SUN, *state_from_elements(GM_SUN, AU_M, 0.3, 7.0, 10.0, 20.0, 30.0)) < 1e-12", "True"),
    ("two-body closure, e 0.9", "closure(GM_SUN, *state_from_elements(GM_SUN, 0.3 * AU_M, 0.9, 60.0, 0.0, 0.0, 170.0)) < 1e-12", "True"),
    ("hyperbolic round trip, 10 days (m)", "norm(sub(propagate(GM_SUN, *propagate(GM_SUN, *state_from_elements(GM_SUN, -0.5 * AU_M, 1.5, 30.0, 60.0, 90.0, 20.0), 10.0 * DAY_S), -10.0 * DAY_S)[0], state_from_elements(GM_SUN, -0.5 * AU_M, 1.5, 30.0, 60.0, 90.0, 20.0)[0])) < 1e-3", "True"),
    ("orbit element: aphelion over au half a period after a perihelion epoch", "norm(orbit_state(orbit(GM_SUN, AU_M, 0.0167, 0.0, 0.0, 102.9, 0.0, 0.0), period(GM_SUN, AU_M) / 2.0)[0]) / AU_M", "1.0167"),
    ("mu from a body and from a mass", "(orbit_mu(body=399), orbit_mu(mass=1.98892e30))", "(3.986e+14, 1.32746e+20)"),
    ("Sun-Earth acceleration of the Earth (m/s^2)", "norm(accelerations(system([1.98892e30, 5.9722e24], [ZERO, EARTH_R], [ZERO, EARTH_V]), [ZERO, EARTH_R])[1])", "0.0059316"),
    ("softened acceleration at 1e-3 with eps 1", "norm(accelerations(system([1.0, 1.0], [ZERO, (1e-3, 0.0, 0.0)], [ZERO, ZERO], G=1.0, softening=1.0), [ZERO, (1e-3, 0.0, 0.0)])[0])", "0.000999999"),
    ("energy of the unit pair", "energy(_pair())", "-0.0005"),
    ("leapfrog energy drift, 50 orbits at P / 200", "energy_drift(_pair(), 'leapfrog', TWO_PI / 200.0, 50.0 * TWO_PI)", "2.43649e-07"),
    ("leapfrog energy drift, 10 orbits at P / 200", "energy_drift(_pair(), 'leapfrog', TWO_PI / 200.0, 10.0 * TWO_PI)", "2.43649e-07"),
    ("leapfrog reversibility, 10 orbits", "reversibility(_pair(), 'leapfrog', TWO_PI / 200.0, 10.0 * TWO_PI) < 1e-10", "True"),
    ("leapfrog error ratio for halving the step", "position_error(_pair(), 'leapfrog', TWO_PI / 100.0, TWO_PI) / position_error(_pair(), 'leapfrog', TWO_PI / 200.0, TWO_PI)", "3.99551"),
    ("Wisdom-Holman energy drift, two bodies, 20 orbits at P / 20", "energy_drift(_pair(), 'wisdomHolman', TWO_PI / 20.0, 20.0 * TWO_PI) < 1e-9", "True"),
    ("leapfrog energy drift at the same step", "energy_drift(_pair(), 'leapfrog', TWO_PI / 20.0, 20.0 * TWO_PI)", "0.00212794"),
    ("Wisdom-Holman energy drift, three bodies, 50 orbits", "energy_drift(_three(), 'wisdomHolman', TWO_PI / 20.0, 50.0 * TWO_PI)", "1.31264e-06"),
    ("Wisdom-Holman reversibility, three bodies", "reversibility(_three(), 'wisdomHolman', TWO_PI / 20.0, 10.0 * TWO_PI) < 1e-9", "True"),
    ("Gauss-Radau nodes h1 and h7", "(RADAU_H[1], RADAU_H[7])", "(0.0562626, 0.977521)"),
    ("Gauss-Radau weights sum", "sum(RADAU_W)", "1"),
    ("Gauss-Radau exactness: integral of tau^14", "sum(w * h ** 14 for w, h in zip(RADAU_W, RADAU_H))", "0.0666667"),
    ("IAS15 position error, one orbit at P / 20", "position_error(_pair(), 'ias15', TWO_PI / 20.0, TWO_PI) < 1e-8", "True"),
    ("IAS15 position error, one orbit at P / 40", "position_error(_pair(), 'ias15', TWO_PI / 40.0, TWO_PI) < 1e-12", "True"),
    ("IAS15 energy drift, 20 orbits at P / 20", "energy_drift(_pair(), 'ias15', TWO_PI / 20.0, 20.0 * TWO_PI) < 1e-10", "True"),
    ("IAS15 reversibility, 10 orbits", "reversibility(_pair(), 'ias15', TWO_PI / 20.0, 10.0 * TWO_PI) < 1e-10", "True"),
    ("figure eight closes under IAS15 (largest error)", "max(norm(sub(a, b)) for a, b in zip(integrate(_eight(), 'ias15', EIGHT_PERIOD / 400.0, EIGHT_PERIOD)['positions'], _eight()['positions'])) < 1e-6", "True"),
    ("Plummer half-mass radius over the scale", "plummer_radius(0.5, 1.0)", "1.30477"),
    ("Plummer escape speed at the scale radius", "plummer_escape_speed(1.0, 1.0, 1.0, 1.0)", "1.18921"),
    ("Plummer cluster of 400: virial ratio 2K over the potential", "2.0 * kinetic(plummer(42, 400, 1.0, 1.0, 1.0)) / abs(potential(plummer(42, 400, 1.0, 1.0, 1.0)))", "0.975192"),
    ("Plummer cluster of 400: median radius", "sorted(norm(p) for p in plummer(42, 400, 1.0, 1.0, 1.0)['positions'])[200]", "1.33268"),
    ("random stream draw U(7, 3, 11)", "U(7, 3, 11)", "0.54057"),
    ("trail times, 4 samples over 30 s at t 100", "trail_times(100.0, 30.0, 4)", "(70, 80, 90, 100)"),
    ("trail alpha halfway", "trail_alpha(15.0, 30.0)", "0.5"),
    ("steps in 600 frames", "steps_to(600 / 24 * TWO_PI / 10.0, TWO_PI / 240.0)", "600"),
    ("scene position of (1e9, 2e9, 3e9) m at 1e-6 px/m", "scene_position((1e9, 2e9, 3e9), ZERO, 1e-6)", "(1000, -3000, 2000)"),
    ("seek check", "seek_test()", "True"),
]


def scope():
    s = dict(globals())
    s["math"] = math
    return s


def _same(a, b, rel=5e-4, abs_tol=5e-4):
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    return repr(v)


def main():
    s = scope()
    for name, expr, _ in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
