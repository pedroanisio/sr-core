#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add Kerr geodesics, ray bundles, beaming and a relativistic
camera" (srep/srep-0000-relativistic.md), SP7 of SREP 12 on top of SREP 76.

Standard library only. The rules of the SREP's Semantics section are the functions below, in its order:
the Kerr metric and its closed forms (rules 1 to 3), the static observer's momentum (rule 4), the Hamiltonian
trace and its outcomes (rules 5 and 6), the disk redshift (rule 7), the Schwarzschild checks (rule 8), the
relativistic camera (rules 9 and 10), beaming (rule 11), ray bundles (rule 12) and the bounds (rule 13).
`main()` prints the SREP's numeric table; `tests/test_relativistic.py` checks both.

Units: G = c = 1, lengths in units of the hole's mass M; a is the spin parameter, |a| <= M; angles are
Boyer-Lindquist. Local directions are triples in a static observer's orthonormal frame (e_r, e_theta, e_phi).
"""
import math

MAX_STEPS = 65536     # integration steps of one ray
MAX_BUNDLE = 4096     # samples of one ray bundle
STEP = 0.005          # step of the affine parameter as a fraction of r
CAPTURE = 1.02        # a ray below CAPTURE * r_plus is captured
SQRT27 = math.sqrt(27.0)

# --- rules 1 to 3: the metric and its closed forms -----------------------------------------------------------


def _check(M, a):
    if not M > 0.0:
        raise ValueError("the mass must be positive")
    if abs(a) > M:
        raise ValueError("the spin must satisfy |a| <= M")


def horizons(M, a):
    """The outer and inner horizons r+ and r-."""
    _check(M, a)
    s = math.sqrt(max(0.0, M * M - a * a))
    return (M + s, M - s)


def ergosphere(M, a, theta):
    """The outer boundary of the ergosphere at polar angle theta."""
    _check(M, a)
    return M + math.sqrt(max(0.0, M * M - a * a * math.cos(theta) ** 2))


def photon_orbit(M, a, prograde):
    """The radius of the equatorial circular photon orbit (Bardeen, Press and Teukolsky 1972)."""
    _check(M, a)
    sign = -1.0 if prograde else 1.0
    return 2.0 * M * (1.0 + math.cos(2.0 / 3.0 * math.acos(max(-1.0, min(1.0, sign * a / M)))))


def isco(M, a, prograde):
    """The innermost stable circular orbit (Bardeen, Press and Teukolsky 1972)."""
    _check(M, a)
    chi = abs(a) / M
    if a < 0.0:
        prograde = not prograde
    z1 = 1.0 + (1.0 - chi * chi) ** (1.0 / 3.0) * ((1.0 + chi) ** (1.0 / 3.0) + (1.0 - chi) ** (1.0 / 3.0))
    z2 = math.sqrt(3.0 * chi * chi + z1 * z1)
    root = math.sqrt(max(0.0, (3.0 - z1) * (3.0 + z1 + 2.0 * z2)))
    return M * (3.0 + z2 - root) if prograde else M * (3.0 + z2 + root)


def _sigma_delta(M, a, r, theta):
    return r * r + a * a * math.cos(theta) ** 2, r * r - 2.0 * M * r + a * a


def metric(M, a, r, theta):
    """The covariant Boyer-Lindquist components of the Kerr metric as a dict."""
    _check(M, a)
    sigma, delta = _sigma_delta(M, a, r, theta)
    s2 = math.sin(theta) ** 2
    return {
        "tt": -(1.0 - 2.0 * M * r / sigma),
        "tphi": -2.0 * M * a * r * s2 / sigma,
        "rr": sigma / delta,
        "thth": sigma,
        "phiphi": (r * r + a * a + 2.0 * M * a * a * r * s2 / sigma) * s2,
    }


def omega_zamo(M, a, r, theta):
    """The frame-dragging rate of the zero-angular-momentum observer."""
    _check(M, a)
    sigma, delta = _sigma_delta(M, a, r, theta)
    s2 = math.sin(theta) ** 2
    return 2.0 * M * a * r / ((r * r + a * a) ** 2 - a * a * delta * s2)


def omega_kepler(M, a, r, prograde):
    """The angular velocity of a circular equatorial orbit, negative when retrograde."""
    _check(M, a)
    root = math.sqrt(M)
    if prograde:
        return root / (r ** 1.5 + a * root)
    return -root / (r ** 1.5 - a * root)


# --- rule 4: the static observer -----------------------------------------------------------------------------


def _unit(d):
    n = math.sqrt(sum(c * c for c in d))
    if n == 0.0:
        raise ValueError("the direction is zero")
    return tuple(c / n for c in d)


def static_momentum(M, a, r, theta, d):
    """The conserved E and L and the covariant p_r and p_theta of a photon leaving a static observer at
    (r, theta) along the local direction d = (d_r, d_theta, d_phi), with unit local energy."""
    g = metric(M, a, r, theta)
    if r <= horizons(M, a)[0] or g["tt"] >= 0.0:
        raise ValueError("no static observer inside the ergosphere")
    dr, dth, dph = _unit(d)
    n = math.sqrt(g["phiphi"] - g["tphi"] ** 2 / g["tt"])
    kt = 1.0 / math.sqrt(-g["tt"]) - dph * g["tphi"] / (g["tt"] * n)
    kph = dph / n
    E = -(g["tt"] * kt + g["tphi"] * kph)
    L = g["tphi"] * kt + g["phiphi"] * kph
    pr = math.sqrt(g["rr"]) * dr
    pth = math.sqrt(g["thth"]) * dth
    return (E, L, pr, pth)


def hamiltonian(M, a, r, theta, pr, pth, E, L):
    """H = g^{mu nu} p_mu p_nu / 2, zero on a null geodesic."""
    sigma, delta = _sigma_delta(M, a, r, theta)
    s2 = math.sin(theta) ** 2
    w = L - a * E * s2
    b = (r * r + a * a) * E - a * L
    return (delta * pr * pr + pth * pth + w * w / s2 - b * b / delta) / (2.0 * sigma)


def carter(a, theta, pth, E, L):
    """Carter's constant of a null geodesic."""
    s2 = math.sin(theta) ** 2
    return pth * pth + math.cos(theta) ** 2 * (L * L / s2 - a * a * E * E)


# --- rules 5 and 6: the trace --------------------------------------------------------------------------------


def _rates(M, a, state, E, L):
    r, theta, phi, pr, pth = state
    sigma, delta = _sigma_delta(M, a, r, theta)
    s, c = math.sin(theta), math.cos(theta)
    s2 = s * s
    w = L - a * E * s2
    b = (r * r + a * a) * E - a * L
    f = delta * pr * pr + pth * pth + w * w / s2 - b * b / delta
    d_delta = 2.0 * r - 2.0 * M
    d_b = 2.0 * r * E
    f_r = d_delta * pr * pr - (2.0 * b * d_b * delta - b * b * d_delta) / (delta * delta)
    f_th = -4.0 * a * E * w * c / s - 2.0 * w * w * c / (s2 * s)
    sigma_r = 2.0 * r
    sigma_th = -2.0 * a * a * s * c
    return (
        delta * pr / sigma,
        pth / sigma,
        w / (sigma * s2) + a * b / (sigma * delta),
        -(f_r / (2.0 * sigma) - f * sigma_r / (2.0 * sigma * sigma)),
        -(f_th / (2.0 * sigma) - f * sigma_th / (2.0 * sigma * sigma)),
    )


def _rk4(M, a, state, E, L, h):
    k1 = _rates(M, a, state, E, L)
    k2 = _rates(M, a, tuple(x + 0.5 * h * k for x, k in zip(state, k1)), E, L)
    k3 = _rates(M, a, tuple(x + 0.5 * h * k for x, k in zip(state, k2)), E, L)
    k4 = _rates(M, a, tuple(x + h * k for x, k in zip(state, k3)), E, L)
    return tuple(x + h / 6.0 * (a1 + 2.0 * a2 + 2.0 * a3 + a4) for x, a1, a2, a3, a4 in zip(state, k1, k2, k3, k4))


def trace(M, a, r, theta, d, r_far, disk=None, max_steps=MAX_STEPS, step=STEP):
    """Trace the photon leaving the static observer at (r, theta) along d until it is captured, escapes past
    r_far or crosses the disk (r_in, r_out, prograde) in the equatorial plane. Returns a dict with the outcome,
    the end point, the disk redshift g when a disk was hit, the Hamiltonian and Carter constant at the end and
    the number of steps; a ray that reaches max_steps is "unresolved"."""
    if not 0 < max_steps <= MAX_STEPS:
        raise ValueError("max_steps must be in 1..MAX_STEPS")
    if not r < r_far:
        raise ValueError("r_far must lie outside the observer")
    E, L, pr, pth = static_momentum(M, a, r, theta, d)
    r_plus = horizons(M, a)[0]
    state = (r, theta, 0.0, pr, pth)
    outcome, steps, g = "unresolved", 0, None
    while steps < max_steps:
        h = step * state[0]
        new = _rk4(M, a, state, E, L, h)
        steps += 1
        if disk is not None and (math.cos(state[1]) > 0.0) != (math.cos(new[1]) > 0.0):
            t = math.cos(state[1]) / (math.cos(state[1]) - math.cos(new[1]))
            hit = tuple(x + t * (y - x) for x, y in zip(state, new))
            if disk[0] <= hit[0] <= disk[1]:
                state = (hit[0], math.pi / 2.0, hit[2], hit[3], hit[4])
                outcome = "disk"
                g = disk_redshift(M, a, hit[0], E, L, disk[2])
                break
        if new[0] < CAPTURE * r_plus:
            state = new
            outcome = "captured"
            break
        if new[0] >= r_far:
            t = (r_far - state[0]) / (new[0] - state[0])
            state = tuple(x + t * (y - x) for x, y in zip(state, new))
            outcome = "escaped"
            break
        state = new
    r_end, th_end, phi_end, pr_end, pth_end = state
    return {
        "outcome": outcome,
        "r": r_end,
        "theta": th_end,
        "phi": phi_end,
        "g": g,
        "p_r": pr_end,
        "p_theta": pth_end,
        "hamiltonian": hamiltonian(M, a, r_end, th_end, pr_end, pth_end, E, L),
        "carter": carter(a, th_end, pth_end, E, L),
        "steps": steps,
    }


# --- rule 7: the disk's redshift -----------------------------------------------------------------------------


def disk_redshift(M, a, r, E, L, prograde):
    """g = E / E_emitted for a photon of constants (E, L) leaving matter on the circular equatorial orbit at r."""
    g = metric(M, a, r, math.pi / 2.0)
    omega = omega_kepler(M, a, r, prograde)
    norm = -(g["tt"] + 2.0 * omega * g["tphi"] + omega * omega * g["phiphi"])
    if norm <= 0.0:
        raise ValueError("no timelike circular orbit at this radius")
    ut = 1.0 / math.sqrt(norm)
    return 1.0 / (ut * (1.0 - omega * L / E))


# --- rule 8: the Schwarzschild checks ------------------------------------------------------------------------


def _b_of_alpha(M, a, r_o, alpha, prograde):
    sign = 1.0 if prograde else -1.0
    E, L, _, _ = static_momentum(M, a, r_o, math.pi / 2.0, (-math.cos(alpha), 0.0, sign * math.sin(alpha)))
    return abs(L / E)


def critical_impact(M, a, prograde, r_o=50.0, tol=1e-4):
    """The capture boundary b_c = |L/E| found by bisection on traced equatorial rays."""
    _check(M, a)
    sign = 1.0 if prograde else -1.0
    lo, hi = 0.0, math.pi / 2.0
    while _b_of_alpha(M, a, r_o, hi, prograde) - _b_of_alpha(M, a, r_o, lo, prograde) > tol:
        mid = 0.5 * (lo + hi)
        out = trace(M, a, r_o, math.pi / 2.0, (-math.cos(mid), 0.0, sign * math.sin(mid)), 4.0 * r_o)
        if out["outcome"] == "captured":
            lo = mid
        else:
            hi = mid
    return 0.5 * (_b_of_alpha(M, a, r_o, lo, prograde) + _b_of_alpha(M, a, r_o, hi, prograde))


def critical_impact_exact(M, a, prograde):
    """b_c = sqrt(r_ph / M) (r_ph + 3M) / 2 at the equatorial photon orbit."""
    r_ph = photon_orbit(M, a, prograde)
    return math.sqrt(r_ph / M) * (r_ph + 3.0 * M) / 2.0


def _closest_u(M, b):
    """The smallest positive root u0 of 1/b^2 - u^2 + 2 M u^3, the inverse of the ray's closest approach."""
    if b <= SQRT27 * M:
        raise ValueError("the ray is captured")
    lo, hi = 0.0, 1.0 / (3.0 * M)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if 1.0 / (b * b) - mid * mid + 2.0 * M * mid ** 3 > 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def schwarzschild_deflection(M, b, n=4000):
    """The exact Schwarzschild deflection of a ray of impact parameter b by quadrature (Simpson, n panels)
    after the substitution u = u0 - s^2 that removes the turning-point singularity."""
    u0 = _closest_u(M, b)
    top = math.sqrt(u0)

    def integrand(s):
        g = 2.0 * u0 - 6.0 * M * u0 * u0 - s * s * (1.0 - 6.0 * M * u0) - 2.0 * M * s ** 4
        return 2.0 / math.sqrt(g)

    hs = top / n
    total = integrand(0.0) + integrand(top)
    for i in range(1, n):
        total += (4.0 if i % 2 else 2.0) * integrand(i * hs)
    return 2.0 * total * hs / 3.0 - math.pi


def traced_deflection(M, a, b, r_o=1.0e5):
    """The deflection of an equatorial ray of impact parameter b traced from r_o and back out to r_o; a > 0
    is a prograde ray, a < 0 a retrograde one."""
    _check(M, a)
    alpha = math.asin(min(1.0, b * math.sqrt(1.0 - 2.0 * M / r_o) / r_o))
    for _ in range(8):
        got = _b_of_alpha(M, a, r_o, alpha, True)
        alpha *= b / got
    out = trace(M, a, r_o, math.pi / 2.0, (-math.cos(alpha), 0.0, math.sin(alpha)), r_o * 1.000001)
    if out["outcome"] != "escaped":
        raise ValueError("the ray did not escape")
    return out["phi"] - math.pi + 2.0 * alpha


def shadow_angle(M, d):
    """The angular radius of the shadow for a static Schwarzschild observer at distance d (SREP 76)."""
    return math.asin(SQRT27 * M * math.sqrt(1.0 - 2.0 * M / d) / d)


# --- rules 9 and 10: the relativistic camera ----------------------------------------------------------------


def _gamma(beta):
    b2 = sum(c * c for c in beta)
    if b2 >= 1.0:
        raise ValueError("the speed must be below 1")
    return 1.0 / math.sqrt(1.0 - b2), math.sqrt(b2)


def doppler(d, beta):
    """The Doppler factor D = gamma (1 + beta . d) of light arriving from the unit view direction d at an
    observer moving with velocity beta."""
    gamma, _ = _gamma(beta)
    return gamma * (1.0 + sum(x * y for x, y in zip(d, beta)))


def aberration(d, beta):
    """The view direction d of the static frame as the moving observer sees it."""
    gamma, speed = _gamma(beta)
    if speed == 0.0:
        return tuple(d)
    hat = tuple(c / speed for c in beta)
    along = sum(x * y for x, y in zip(d, hat))
    scale = (gamma - 1.0) * along + gamma * speed
    denom = gamma * (1.0 + speed * along)
    return tuple((x + scale * h) / denom for x, h in zip(d, hat))


def orbit_speed(M, r):
    """The speed of a circular Schwarzschild orbit as the static observer measures it."""
    if r <= 3.0 * M:
        raise ValueError("no timelike circular orbit at r <= 3M")
    return math.sqrt(M / (r - 2.0 * M))


def infall_speed(M, r):
    """The speed of radial free fall from rest at infinity as the static observer measures it."""
    if r <= 2.0 * M:
        raise ValueError("no static observer at r <= 2M")
    return math.sqrt(2.0 * M / r)


def infall_redshift(M, r):
    """g of light from infinity, seen by the infalling observer looking back out: 1 / (1 + v)."""
    if r < 2.0 * M:
        raise ValueError("inside the horizon")
    return 1.0 / (1.0 + math.sqrt(2.0 * M / r))


def camera_velocity(motion, M, r):
    """The camera's velocity in the static frame (e_r, e_theta, e_phi) for camera/@motion."""
    if motion == "static":
        return (0.0, 0.0, 0.0)
    if motion == "orbit":
        return (0.0, 0.0, orbit_speed(M, r))
    if motion == "infall":
        return (-infall_speed(M, r), 0.0, 0.0)
    raise ValueError(f"unknown camera motion {motion!r}")


# --- rule 11: beaming ----------------------------------------------------------------------------------------


def searchlight(D):
    """The intensity factor D^4 of a Doppler factor D."""
    if D < 0.0:
        raise ValueError("the Doppler factor is not negative")
    return D ** 4


def beamed_radiance(radiance, g):
    """The radiance of disk matter of rest-frame radiance, seen with redshift g."""
    return radiance * searchlight(g)


# --- rule 12: ray bundles ------------------------------------------------------------------------------------


def bundle_jacobian(f, x, y, h):
    """The central-difference Jacobian of the sky map f(x, y) -> (u, v) at (x, y)."""
    ux1, vx1 = f(x + h, y)
    ux0, vx0 = f(x - h, y)
    uy1, vy1 = f(x, y + h)
    uy0, vy0 = f(x, y - h)
    return ((ux1 - ux0) / (2.0 * h), (uy1 - uy0) / (2.0 * h)), ((vx1 - vx0) / (2.0 * h), (vy1 - vy0) / (2.0 * h))


def magnification(J):
    """|det J|, the area ratio of the bundle."""
    return abs(J[0][0] * J[1][1] - J[0][1] * J[1][0])


def ellipse_axes(J):
    """The singular values of J, major first: the semi-axes of the image of the unit circle."""
    a, b = J[0]
    c, d = J[1]
    s = a * a + b * b + c * c + d * d
    det = a * d - b * c
    root = math.sqrt(max(0.0, s * s - 4.0 * det * det))
    return (math.sqrt(max(0.0, (s + root) / 2.0)), math.sqrt(max(0.0, (s - root) / 2.0)))


def sky_direction(M, a, r_o, x, y, r_far=1.0e4):
    """The sky coordinates (azimuth, elevation) of the direction in which the ray leaving a static equatorial
    observer at r_o, looking x radians sideways and y radians up from the outward radial, travels at r_far."""
    d = (math.cos(x) * math.cos(y), -math.sin(y), math.sin(x) * math.cos(y))
    out = trace(M, a, r_o, math.pi / 2.0, d, r_far)
    if out["outcome"] != "escaped":
        raise ValueError("the ray did not reach the sky")
    E, L, _, _ = static_momentum(M, a, r_o, math.pi / 2.0, d)
    r, th, phi = out["r"], out["theta"], out["phi"]
    g = metric(M, a, r, th)
    dr, dth, dphi, _, _ = _rates(M, a, (r, th, phi, out["p_r"], out["p_theta"]), E, L)
    local = _unit((math.sqrt(g["rr"]) * dr, math.sqrt(g["thth"]) * dth, math.sqrt(g["phiphi"] - g["tphi"] ** 2 / g["tt"]) * dphi))
    s, c, sp, cp = math.sin(th), math.cos(th), math.sin(phi), math.cos(phi)
    v = (local[0] * s * cp + local[1] * c * cp - local[2] * sp,
         local[0] * s * sp + local[1] * c * sp + local[2] * cp,
         local[0] * c - local[1] * s)
    return (math.atan2(v[1], v[0]), math.asin(max(-1.0, min(1.0, v[2]))))


def sky_jacobian(M, a, r_o, look, h):
    """The bundle Jacobian of the sky map at the look angles (x, y)."""
    return bundle_jacobian(lambda x, y: sky_direction(M, a, r_o, x, y), look[0], look[1], h)


def bundle_filter(f, J, x, y, radius, n):
    """The mean of f over n points of the ellipse J . (radius cos t, radius sin t) around (x, y)."""
    if not 0 < n <= MAX_BUNDLE:
        raise ValueError("n must be in 1..MAX_BUNDLE")
    total = 0.0
    for i in range(n):
        t = 2.0 * math.pi * i / n
        cx, cy = radius * math.cos(t), radius * math.sin(t)
        total += f(x + J[0][0] * cx + J[0][1] * cy, y + J[1][0] * cx + J[1][1] * cy)
    return total / n


# --- the numeric table ---------------------------------------------------------------------------------------

TABLE = (
    ("horizons, Schwarzschild", "horizons(1.0, 0.0)", "(2.0, 0.0)"),
    ("horizons, a = 0.6", "tuple(round(v, 12) for v in horizons(1.0, 0.6))", "(1.8, 0.2)"),
    ("horizons, extremal", "horizons(1.0, 1.0)", "(1.0, 1.0)"),
    ("ergosphere, equator", "round(ergosphere(1.0, 0.6, math.pi / 2.0), 12)", "2.0"),
    ("ergosphere, pole", "round(ergosphere(1.0, 0.6, 0.0), 12)", "1.8"),
    ("photon sphere, Schwarzschild", "round(photon_orbit(1.0, 0.0, True), 12)", "3.0"),
    ("photon orbits, extremal", "(round(photon_orbit(1.0, 1.0, True), 12), round(photon_orbit(1.0, 1.0, False), 12))", "(1.0, 4.0)"),
    ("photon orbits, a = 0.5", "(round(photon_orbit(1.0, 0.5, True), 6), round(photon_orbit(1.0, 0.5, False), 6))", "(2.347296, 3.532089)"),
    ("isco, Schwarzschild", "round(isco(1.0, 0.0, True), 12)", "6.0"),
    ("isco, extremal", "(round(isco(1.0, 1.0, True), 12), round(isco(1.0, 1.0, False), 12))", "(1.0, 9.0)"),
    ("isco, a = 0.9", "(round(isco(1.0, 0.9, True), 6), round(isco(1.0, 0.9, False), 6))", "(2.320883, 8.717352)"),
    ("frame dragging, a = 0.9 at 10M", "round(omega_zamo(1.0, 0.9, 10.0, math.pi / 2.0), 6)", "0.001783"),
    ("keplerian rate, a = 0.9 at 4M", "(round(omega_kepler(1.0, 0.9, 4.0, True), 6), round(omega_kepler(1.0, 0.9, 4.0, False), 6))", "(0.112360, -0.140845)"),
    ("metric, Schwarzschild at 10M", "tuple(round(metric(1.0, 0.0, 10.0, math.pi / 2.0)[k], 12) for k in ('tt', 'tphi', 'rr', 'thth', 'phiphi'))", "(-0.8, 0.0, 1.25, 100.0, 100.0)"),
    ("static momentum, inward", "tuple(round(v, 12) for v in static_momentum(1.0, 0.0, 10.0, math.pi / 2.0, (-1.0, 0.0, 0.0)))", "(round(math.sqrt(0.8), 12), 0.0, round(-math.sqrt(1.25), 12), 0.0)"),
    ("static momentum is null", "round(hamiltonian(1.0, 0.7, 10.0, 1.1, *(lambda m: (m[2], m[3], m[0], m[1]))(static_momentum(1.0, 0.7, 10.0, 1.1, (-0.6, 0.3, 0.74)))), 12)", "0.0"),
    ("impact parameter", "round(abs((lambda m: m[1] / m[0])(static_momentum(1.0, 0.0, 10.0, math.pi / 2.0, (-math.cos(0.3), 0.0, math.sin(0.3))))), 12)", "round(10.0 * math.sin(0.3) / math.sqrt(0.8), 12)"),
    ("captured and escaped", "(trace(1.0, 0.0, 10.0, math.pi / 2.0, (-1.0, 0.0, 0.0), 50.0)['outcome'], trace(1.0, 0.0, 10.0, math.pi / 2.0, (1.0, 0.0, 0.0), 50.0)['outcome'])", "('captured', 'escaped')"),
    ("the constants hold", "(lambda o: (abs(o['hamiltonian']) < 1e-6, abs(o['carter'] - carter(0.8, 1.2, *(lambda m: (m[3], m[0], m[1]))(static_momentum(1.0, 0.8, 12.0, 1.2, (-0.9, 0.3, 0.3))))) < 1e-5))(trace(1.0, 0.8, 12.0, 1.2, (-0.9, 0.3, 0.3), 60.0))", "(True, True)"),
    ("shadow, Schwarzschild", "round(critical_impact(1.0, 0.0, True), 3)", "round(math.sqrt(27.0), 3)"),
    ("shadow, exact Kerr", "(round(critical_impact_exact(1.0, 0.95, True), 6), round(critical_impact_exact(1.0, 0.95, False), 6))", "(2.582212, 6.916417)"),
    ("shadow, traced Kerr", "(round(critical_impact(1.0, 0.95, True), 2), round(critical_impact(1.0, 0.95, False), 2))", "(2.58, 6.92)"),
    ("shadow, extremal", "(round(critical_impact_exact(1.0, 1.0, True), 12), round(critical_impact_exact(1.0, 1.0, False), 12))", "(2.0, 7.0)"),
    ("deflection, quadrature", "tuple(round(schwarzschild_deflection(1.0, b), 6) for b in (10.0, 20.0, 100.0))", "(0.590396, 0.236136, 0.041223)"),
    ("deflection, weak field", "tuple(round(schwarzschild_deflection(1.0, b) / (4.0 / b), 4) for b in (400.0, 1600.0))", "(1.0074, 1.0018)"),
    ("deflection, traced", "tuple(round(traced_deflection(1.0, 0.0, b), 3) for b in (10.0, 30.0))", "(0.59, 0.148)"),
    ("deflection, prograde and retrograde", "tuple(round(traced_deflection(1.0, a, 8.0), 3) for a in (0.9, 0.0, -0.9))", "(0.676, 0.859, 1.253)"),
    ("shadow angle", "tuple(round(shadow_angle(1.0, d), 5) for d in (10.0, 50.0, 1000.0))", "(0.48336, 0.102, 0.00519)"),
    ("disk crossing", "(lambda o: (o['outcome'], round(o['r'], 3), round(o['g'], 4)))(trace(1.0, 0.0, 30.0, 1.3, (-1.0, 0.25, 0.0), 100.0, disk=(6.0, 20.0, True)))", "('disk', 14.97, 0.8942)"),
    ("disk redshift, face on", "tuple(round(disk_redshift(1.0, 0.0, r, 1.0, 0.0, True), 6) for r in (6.0, 10.0))", "(round(math.sqrt(0.5), 6), round(math.sqrt(0.7), 6))"),
    ("disk redshift, approaching and receding", "(round(disk_redshift(1.0, 0.0, 10.0, 1.0, 2.0, True), 6), round(disk_redshift(1.0, 0.0, 10.0, 1.0, -2.0, True), 6))", "(0.893148, 0.786893)"),
    ("doppler", "(lambda g: tuple(round(doppler(d, (0.5, 0.0, 0.0)) / g, 12) for d in ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0))))(1.0 / math.sqrt(0.75))", "(1.5, 0.5, 1.0)"),
    ("aberration", "tuple(round(c, 6) for c in aberration((0.0, 1.0, 0.0), (0.5, 0.0, 0.0)))", "(0.5, 0.866025, 0.0)"),
    ("aberration inverts", "tuple(round(c, 12) for c in aberration(aberration((0.2, -0.5, math.sqrt(0.71)), (0.3, 0.4, 0.0)), (-0.3, -0.4, 0.0)))", "(0.2, -0.5, round(math.sqrt(0.71), 12))"),
    ("searchlight", "(searchlight(2.0), round(beamed_radiance(0.5, math.sqrt(0.5)), 12))", "(16.0, 0.125)"),
    ("camera speeds", "(round(orbit_speed(1.0, 6.0), 12), round(infall_speed(1.0, 8.0), 12), round(infall_redshift(1.0, 8.0), 12), infall_redshift(1.0, 2.0))", "(0.5, 0.5, round(2.0 / 3.0, 12), 0.5)"),
    ("camera velocity", "(camera_velocity('static', 1.0, 10.0), tuple(round(c, 6) for c in camera_velocity('orbit', 1.0, 10.0)), tuple(round(c, 6) for c in camera_velocity('infall', 1.0, 10.0)))", "((0.0, 0.0, 0.0), (0.0, 0.0, 0.353553), (-0.447214, 0.0, 0.0))"),
    ("bundle of a linear map", "(lambda J: (tuple(round(v, 6) for v in J[0] + J[1]), round(magnification(J), 6), tuple(round(v, 6) for v in ellipse_axes(J))))(bundle_jacobian(lambda x, y: (2.0 * x, 3.0 * y), 0.0, 0.0, 1e-3))", "((2.0, 0.0, 0.0, 3.0), 6.0, (3.0, 2.0))"),
    ("bundle on the sky", "(lambda J: (round(magnification(J), 2), tuple(round(v, 2) for v in ellipse_axes(J))))(sky_jacobian(1.0, 0.0, 10.0, (0.3, 0.0), 1e-4))", "(1.25, (1.12, 1.11))"),
    ("bundle filter", "(bundle_filter(lambda x, y: 1.0, ((1.0, 0.0), (0.0, 1.0)), 0.0, 0.0, 0.1, 16), round(bundle_filter(lambda x, y: x, ((1.0, 0.0), (0.0, 1.0)), 0.5, 0.0, 0.1, 16), 12))", "(1.0, 0.5)"),
    ("bounds", "(MAX_STEPS, MAX_BUNDLE, STEP, CAPTURE)", "(65536, 4096, 0.005, 1.02)"),
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
