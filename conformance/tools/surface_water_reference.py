"""Reference for the draft SREP "Add shallow-water flow to the terrain grid" (T2 of SREP 12).

One `shallowWater` child of a `terrain` (the F2 terrain-grid draft) integrates the two-dimensional shallow-water
equations on the terrain's grid: the bed is the sum of the solid layers, the `water` layer is the depth h and
the `flow` layer the discharge (hu, hv). The scheme is the central-upwind flux of Kurganov and Petrova (2007) on
the hydrostatic reconstruction of Audusse, Bouchut, Bristeau, Klein and Perthame (2004), first order (piecewise
constant, forward Euler) or second order (minmod reconstruction of h, w = h + b and the discharges, Heun), so a
lake at rest with dry islands is kept exactly and the depth stays non-negative at Courant numbers up to one half.
Manning friction is semi-implicit; rain and `source` children add depth. A fixed `step` is subdivided into the
fewest equal substeps that satisfy `cfl`, so frame t is the state after round(t / step) steps from the start
(SREP 14), never more than `maxSteps`.

The analytic solutions used by the tests (Ritter's dry dam break, Thacker's planar oscillation in a parabolic
bowl, the SWASHES subcritical flow over a bump) are implemented from the papers; the SWASHES code (CeCILL) is
not used. `python surface_water_reference.py` prints the numeric table of the draft's conformance section.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

GRAVITY = 9.81
BOUNDARIES = ("open", "closed")
DEFAULTS = {"order": 1, "manning": 0.03, "cfl": 0.5, "rain": 0.0, "dryTolerance": 1e-6, "step": 0.02,
            "boundary": "closed", "maxSteps": 100000, "sources": ()}
NEGATIVE_DEPTH = 1e-14    # a depth this far below zero is floating-point residue and reads as zero
DIGEST_DECIMALS = 3


class SurfaceWaterError(ValueError):
    """A shallow-water element or state outside the draft's rules."""


# ------------------------------------------------------------------------------------------------- the references

_terrain = None


def terrain():
    """The terrain-grid reference module, loaded by path."""
    global _terrain
    if _terrain is None:
        path = os.path.join(HERE, "terrain_grid_reference.py")
        spec = importlib.util.spec_from_file_location("terrain_grid_reference", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _terrain = mod
    return _terrain


def _get(spec, key):
    v = spec.get(key)
    return DEFAULTS[key] if v is None else v


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ------------------------------------------------------------------------------------------------- the pieces


def reconstruct(w_left, b_left, w_right, b_right):
    """Hydrostatic reconstruction (Audusse et al. 2004): the depths the two sides of an interface present to the
    flux, max(0, w - max(b_left, b_right)) on each side."""
    b = max(b_left, b_right)
    return max(0.0, w_left - b), max(0.0, w_right - b)


def _physical(h, u, v, g):
    return (h * u, h * u * u + 0.5 * g * h * h, h * u * v)


def flux_x(h_l, u_l, v_l, h_r, u_r, v_r, g):
    """The central-upwind flux of Kurganov and Petrova (2007) across an x interface, for the mass, the x momentum
    and the y momentum; with the roles of u and v exchanged it serves the y direction."""
    c_l, c_r = math.sqrt(g * h_l), math.sqrt(g * h_r)
    a_plus = max(u_l + c_l, u_r + c_r, 0.0)
    a_minus = min(u_l - c_l, u_r - c_r, 0.0)
    width = a_plus - a_minus
    if width == 0.0:
        return (0.0, 0.0, 0.0)
    f_l = _physical(h_l, u_l, v_l, g)
    f_r = _physical(h_r, u_r, v_r, g)
    du = (h_r - h_l, h_r * u_r - h_l * u_l, h_r * v_r - h_l * v_l)
    k = a_plus * a_minus / width
    return tuple((a_plus * fl - a_minus * fr) / width + k * d for fl, fr, d in zip(f_l, f_r, du))


def velocity(h, hu, dry):
    """hu / h, and zero in a cell drier than `dryTolerance`."""
    return hu / h if h >= dry else 0.0


def friction(h, hu, manning, dt, g):
    """Semi-implicit Manning friction: hu / (1 + dt g n^2 |u| / h^(4/3))."""
    if h <= 0.0 or manning == 0.0:
        return hu if h > 0.0 else 0.0
    u = hu / h
    return hu / (1.0 + dt * g * manning * manning * abs(u) / h ** (4.0 / 3.0))


def minmod(a, b):
    if a > 0.0 and b > 0.0:
        return min(a, b)
    if a < 0.0 and b < 0.0:
        return max(a, b)
    return 0.0


# ----------------------------------------------------------------------------------------------------- the state


def initial_state(layers, dx):
    """The state from the terrain's layers: the bed (sum of the solid layers), h from `water`, (hu, hv) from
    `flow` when present."""
    tg = terrain()
    bed = tg.surface(layers)
    ny, nx = len(bed), len(bed[0])
    h = [list(row) for row in layers["water"]]
    flow = layers.get("flow")
    hu = [[0.0] * nx for _ in range(ny)]
    hv = [[0.0] * nx for _ in range(ny)]
    if flow is not None:
        for j in range(ny):
            for i in range(nx):
                v = flow[j][i]
                if isinstance(v, tuple):
                    hu[j][i], hv[j][i] = float(v[0]), float(v[1])
    return {"bed": bed, "h": h, "hu": hu, "hv": hv, "nx": nx, "ny": ny, "dx": dx, "layers": layers, "substeps": 0}


def max_speed(state, dry, g=GRAVITY):
    s = 0.0
    for j in range(state["ny"]):
        for i in range(state["nx"]):
            h = state["h"][j][i]
            if h >= dry:
                c = math.sqrt(g * h)
                s = max(s, abs(state["hu"][j][i] / h) + c, abs(state["hv"][j][i] / h) + c)
    return s


def substeps(state, spec, dx):
    """The fewest equal substeps of `step` whose Courant number stays under `cfl`."""
    s = max_speed(state, _get(spec, "dryTolerance"))
    if s == 0.0:
        return 1
    return max(1, math.ceil(_get(spec, "step") * s / (_get(spec, "cfl") * dx)))


def _ghost(state, i, j, closed, axis):
    """The state across the grid's edge: a mirror with the normal discharge reversed (closed) or a copy (open)."""
    ii = min(max(i, 0), state["nx"] - 1)
    jj = min(max(j, 0), state["ny"] - 1)
    h, hu, hv, b = state["h"][jj][ii], state["hu"][jj][ii], state["hv"][jj][ii], state["bed"][jj][ii]
    if closed:
        if axis == 0:
            hu = -hu
        else:
            hv = -hv
    return h, hu, hv, b


def _rhs(state, spec, dx, order, closed, dry, g, ghosts=None):
    """L(U): minus the divergence of the fluxes plus the bed source, per cell, from the hydrostatic
    reconstruction at every interface (Audusse et al. 2004, first and second order)."""
    nx, ny = state["nx"], state["ny"]
    H, HU, HV, B = state["h"], state["hu"], state["hv"], state["bed"]

    def cell(i, j):
        if 0 <= i < nx and 0 <= j < ny:
            return H[j][i], HU[j][i], HV[j][i], B[j][i]
        if ghosts is not None:
            return ghosts(i, j)
        return _ghost(state, i, j, closed, 0 if (i < 0 or i >= nx) else 1)

    def slopes(i, j, axis):
        if order == 1:
            return (0.0, 0.0, 0.0, 0.0)
        di, dj = (1, 0) if axis == 0 else (0, 1)
        c = cell(i, j)
        m = cell(i - di, j - dj)
        p = cell(i + di, j + dj)
        out = []
        for k in range(3):
            out.append(minmod(c[k] - m[k], p[k] - c[k]))
        wc, wm, wp = c[0] + c[3], m[0] + m[3], p[0] + p[3]
        out.append(minmod(wc - wm, wp - wc))
        return tuple(out)

    def faces(i, j, axis):
        """(h, hu, hv, b) at the cell's minus and plus faces along the axis."""
        c = cell(i, j)
        s = slopes(i, j, axis)
        w = c[0] + c[3]
        minus = (c[0] - 0.5 * s[0], c[1] - 0.5 * s[1], c[2] - 0.5 * s[2])
        plus = (c[0] + 0.5 * s[0], c[1] + 0.5 * s[1], c[2] + 0.5 * s[2])
        w_minus, w_plus = w - 0.5 * s[3], w + 0.5 * s[3]
        return (minus + (w_minus - minus[0],)), (plus + (w_plus - plus[0],))

    dh = [[0.0] * nx for _ in range(ny)]
    dhu = [[0.0] * nx for _ in range(ny)]
    dhv = [[0.0] * nx for _ in range(ny)]
    for axis in (0, 1):
        di, dj = (1, 0) if axis == 0 else (0, 1)
        face_cache = {}

        def face(i, j):
            key = (i, j)
            if key not in face_cache:
                face_cache[key] = faces(i, j, axis)
            return face_cache[key]

        for j in range(ny):
            for i in range(nx):
                f_minus, f_plus = face(i, j)
                # interface on the plus side: this cell's plus face against the neighbour's minus face
                for side, (mine, other) in (("plus", (f_plus, face(i + di, j + dj)[0])),
                                            ("minus", (f_minus, face(i - di, j - dj)[1]))):
                    h_mine, hu_mine, hv_mine, b_mine = mine
                    h_other, hu_other, hv_other, b_other = other
                    u_mine = velocity(h_mine, hu_mine, dry)
                    v_mine = velocity(h_mine, hv_mine, dry)
                    u_other = velocity(h_other, hu_other, dry)
                    v_other = velocity(h_other, hv_other, dry)
                    hs_mine, hs_other = reconstruct(h_mine + b_mine, b_mine, h_other + b_other, b_other)
                    if axis == 0:
                        if side == "plus":
                            f = flux_x(hs_mine, u_mine, v_mine, hs_other, u_other, v_other, g)
                        else:
                            f = flux_x(hs_other, u_other, v_other, hs_mine, u_mine, v_mine, g)
                        f_mass, f_normal, f_tangent = f
                    else:
                        if side == "plus":
                            f = flux_x(hs_mine, v_mine, u_mine, hs_other, v_other, u_other, g)
                        else:
                            f = flux_x(hs_other, v_other, u_other, hs_mine, v_mine, u_mine, g)
                        f_mass, f_normal, f_tangent = f
                    # the hydrostatic correction of the pressure term on this cell's side
                    f_normal += 0.5 * g * (h_mine * h_mine - hs_mine * hs_mine)
                    sign = 1.0 if side == "plus" else -1.0
                    dh[j][i] -= sign * f_mass / dx
                    if axis == 0:
                        dhu[j][i] -= sign * f_normal / dx
                        dhv[j][i] -= sign * f_tangent / dx
                    else:
                        dhv[j][i] -= sign * f_normal / dx
                        dhu[j][i] -= sign * f_tangent / dx
                if order == 2:
                    # the centred bed source of the second-order scheme
                    h_m, _, _, b_m = f_minus
                    h_p, _, _, b_p = f_plus
                    s_c = g * 0.5 * (h_m + h_p) * (b_m - b_p) / dx
                    if axis == 0:
                        dhu[j][i] += s_c
                    else:
                        dhv[j][i] += s_c
    return dh, dhu, dhv


def _advance(state, rhs, dt, dry):
    nx, ny = state["nx"], state["ny"]
    dh, dhu, dhv = rhs
    h = [[0.0] * nx for _ in range(ny)]
    hu = [[0.0] * nx for _ in range(ny)]
    hv = [[0.0] * nx for _ in range(ny)]
    for j in range(ny):
        for i in range(nx):
            v = state["h"][j][i] + dt * dh[j][i]
            if v < 0.0:
                if v < -NEGATIVE_DEPTH:
                    raise SurfaceWaterError(f"negative depth {v!r} at cell ({i}, {j})")
                v = 0.0
            h[j][i] = v
            if v >= dry:
                hu[j][i] = state["hu"][j][i] + dt * dhu[j][i]
                hv[j][i] = state["hv"][j][i] + dt * dhv[j][i]
    return dict(state, h=h, hu=hu, hv=hv)


def source_cells(source, nx, ny, dx):
    """The cells whose centre lies within the source's disk."""
    return sum(1 for j in range(ny) for i in range(nx)
               if math.hypot((i + 0.5) * dx - source["x"], (j + 0.5) * dx - source["y"]) <= source["radius"])


def _add_water(state, spec, dx, t, dt):
    rain = _get(spec, "rain") * dt
    active = [s for s in _get(spec, "sources") if s.get("start", 0.0) <= t and (s.get("end") is None or t < s["end"])]
    if rain == 0.0 and not active:
        return state
    nx, ny = state["nx"], state["ny"]
    h = [list(row) for row in state["h"]]
    for j in range(ny):
        for i in range(nx):
            add = rain
            for s in active:
                if math.hypot((i + 0.5) * dx - s["x"], (j + 0.5) * dx - s["y"]) <= s["radius"]:
                    add += s["rate"] * dt
            h[j][i] += add
    return dict(state, h=h)


def step(state, spec, dx, n=0, ghosts=None):
    """One `step` of the element from step index n: the substeps of the scheme, each followed by the friction
    and the added water."""
    order = int(_get(spec, "order"))
    closed = _get(spec, "boundary") == "closed"
    dry = _get(spec, "dryTolerance")
    manning = _get(spec, "manning")
    size = _get(spec, "step")
    count = substeps(state, spec, dx)
    dt = size / count
    g = GRAVITY
    for k in range(count):
        t = (n + k / count) * size
        if order == 1:
            state = _advance(state, _rhs(state, spec, dx, 1, closed, dry, g, ghosts), dt, dry)
        else:
            s1 = _advance(state, _rhs(state, spec, dx, 2, closed, dry, g, ghosts), dt, dry)
            s2 = _advance(s1, _rhs(s1, spec, dx, 2, closed, dry, g, ghosts), dt, dry)
            state = dict(state, h=[[0.5 * (a + b) for a, b in zip(ra, rb)] for ra, rb in zip(state["h"], s2["h"])],
                         hu=[[0.5 * (a + b) for a, b in zip(ra, rb)] for ra, rb in zip(state["hu"], s2["hu"])],
                         hv=[[0.5 * (a + b) for a, b in zip(ra, rb)] for ra, rb in zip(state["hv"], s2["hv"])])
        if manning > 0.0:
            hu = [[friction(h, q, manning, dt, g) for h, q in zip(rh, rq)] for rh, rq in zip(state["h"], state["hu"])]
            hv = [[friction(h, q, manning, dt, g) for h, q in zip(rh, rq)] for rh, rq in zip(state["h"], state["hv"])]
            state = dict(state, hu=hu, hv=hv)
        state = _add_water(state, spec, dx, t, dt)
    return dict(state, substeps=state["substeps"] + count)


# ------------------------------------------------------------------------------------------- analytic solutions


def ritter(x, t, x0, h_l, g):
    """Ritter's dry-bed dam break (Ritter 1892; SWASHES 4.1.2): the depth and velocity at x and t > 0 for a
    dam at x0 holding h_l on its left over a dry bed."""
    c0 = math.sqrt(g * h_l)
    xi = (x - x0) / t
    if xi <= -c0:
        return (h_l, 0.0)
    if xi >= 2.0 * c0:
        return (0.0, 0.0)
    return (4.0 / (9.0 * g) * (c0 - 0.5 * xi) ** 2, 2.0 / 3.0 * (xi + c0))


def thacker_case():
    """Thacker's planar oscillation in a one-dimensional parabolic bowl (Thacker 1981; SWASHES 4.2.1): the bowl
    z = h0 ((x - L/2)^2 / a^2 - 1), a surface that stays planar, A(t) = A0 cos(omega t)."""
    return {"L": 4.0, "a": 1.0, "h0": 0.5, "A0": 0.3, "nx": 200, "dx": 0.02, "g": GRAVITY}


def thacker_omega(case):
    return math.sqrt(2.0 * case["g"] * case["h0"]) / case["a"]


def thacker_period(case):
    return 2.0 * math.pi / thacker_omega(case)


def thacker_bed(x, case):
    return case["h0"] * (((x - case["L"] / 2.0) / case["a"]) ** 2 - 1.0)


def thacker_surface(t, case):
    """A(t) and C(t) of the planar surface eta = A (x - L/2) + C: A = A0 cos(omega t), C = g A0^2 sin^2(omega t)
    / (2 omega^2), from the momentum equation u' = -g A and the continuity equation A' = 2 u h0 / a^2, C' = -u A."""
    w = thacker_omega(case)
    a_t = case["A0"] * math.cos(w * t)
    c_t = case["g"] * case["A0"] ** 2 * math.sin(w * t) ** 2 / (2.0 * w * w)
    return a_t, c_t


def thacker(x, t, case):
    """The depth and velocity at x and t: h = max(0, eta - z), u = -(g A0 / omega) sin(omega t) where wet."""
    a_t, c_t = thacker_surface(t, case)
    h = a_t * (x - case["L"] / 2.0) + c_t - thacker_bed(x, case)
    if h <= 0.0:
        return (0.0, 0.0)
    return (h, -case["g"] * case["A0"] / thacker_omega(case) * math.sin(thacker_omega(case) * t))


def thacker_volume(t, case):
    """The exact wet volume per unit width at t: the integral of eta - z between its two roots."""
    a_t, c_t = thacker_surface(t, case)
    h0, a = case["h0"], case["a"]
    # eta - z = -(h0 / a^2) s^2 + a_t s + (c_t + h0), s = x - L/2
    p, q, r = -h0 / (a * a), a_t, c_t + h0
    disc = math.sqrt(q * q - 4.0 * p * r)
    s1, s2 = sorted(((-q + disc) / (2.0 * p), (-q - disc) / (2.0 * p)))
    f = lambda s: p * s ** 3 / 3.0 + q * s * s / 2.0 + r * s     # noqa: E731
    return f(s2) - f(s1)


def thacker_run(case, order, periods=1.0, size=0.005):
    """Integrate the bowl from the exact state at t = 0 over `periods` periods and return the state and the
    exact depths at the time reached."""
    nx, dx = case["nx"], case["dx"]
    xs = [(i + 0.5) * dx for i in range(nx)]
    layers = {"bedrock": [[thacker_bed(x, case) for x in xs]], "water": [[thacker(x, 0.0, case)[0] for x in xs]]}
    spec = dict(DEFAULTS, order=order, step=size, manning=0.0, boundary="closed")
    state = initial_state(layers, dx)
    steps = int(round(periods * thacker_period(case) / size))
    for n in range(steps):
        state = step(state, spec, dx, n)
    t = steps * size
    return state, [[thacker(x, t, case)[0] for x in xs]]


def bump_case():
    """SWASHES 3.1.1, subcritical flow over a bump: L = 25 m, z = 0.2 - 0.05 (x - 10)^2 on 8 < x < 12, discharge
    q = 4.42 m^2/s in, depth 2 m out."""
    nx = 80
    dx = 25.0 / nx
    return {"L": 25.0, "nx": nx, "dx": dx, "xs": [(i + 0.5) * dx for i in range(nx)], "q": 4.42, "h_out": 2.0,
            "g": GRAVITY, "t_end": 60.0}


def bump_bed(x):
    return 0.2 - 0.05 * (x - 10.0) ** 2 if 8.0 < x < 12.0 else 0.0


def bump_depth(x, case):
    """The subcritical steady depth from Bernoulli: h^3 + (z - q^2 / (2 g h_out^2) - h_out) h^2 + q^2 / (2 g) = 0,
    the largest root, by Newton from h_out - z."""
    g, q, h_out = case["g"], case["q"], case["h_out"]
    z = bump_bed(x)
    b = z - q * q / (2.0 * g * h_out * h_out) - h_out
    c = q * q / (2.0 * g)
    h = h_out - z
    for _ in range(100):
        f = h ** 3 + b * h * h + c
        df = 3.0 * h * h + 2.0 * b * h
        nh = h - f / df
        if abs(nh - h) < 1e-15:
            h = nh
            break
        h = nh
    return h


def bump_run(case, order=1):
    """Integrate the bump from the outflow depth at rest with the inflow discharge, inflow ghost cell carrying
    q and the cell's depth, outflow ghost cell carrying h_out and the cell's discharge, to t_end."""
    nx, dx = case["nx"], case["dx"]
    layers = {"bedrock": [[bump_bed(x) for x in case["xs"]]], "water": [[case["h_out"] - bump_bed(x) for x in case["xs"]]]}
    state = initial_state(layers, dx)
    state["hu"] = [[case["q"]] * nx]

    def ghosts(i, j):
        if j < 0 or j >= 1:
            jj = 0
            ii = min(max(i, 0), nx - 1)
            return state["h"][jj][ii], state["hu"][jj][ii], -state["hv"][jj][ii], state["bed"][jj][ii]
        if i < 0:
            return state["h"][0][0], case["q"], 0.0, state["bed"][0][0]
        return case["h_out"], state["hu"][0][nx - 1], 0.0, state["bed"][0][nx - 1]

    spec = dict(DEFAULTS, order=order, step=0.05, manning=0.0, boundary="open")
    steps = int(round(case["t_end"] / 0.05))
    for n in range(steps):
        state = step(state, spec, dx, n, ghosts=ghosts)
    return state


# ------------------------------------------------------------------------------------------------------ run


def steps_for(t, size, max_steps):
    if not size > 0.0:
        raise SurfaceWaterError("SW1: step is positive")
    return min(int(round(t / size)), max_steps)


def digest(layers):
    def cell(v):
        if isinstance(v, tuple):
            return [round(c, DIGEST_DECIMALS) for c in v]
        return round(v, DIGEST_DECIMALS)
    rounded = {k: [[cell(v) for v in row] for row in rows] for k, rows in layers.items()}
    text = json.dumps(rounded, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(doc, t):
    """The terrain's layers at time t: the generated layers, then round(t / step) steps of the element; the
    `water` layer holds h and the `flow` layer (hu, hv)."""
    tg = terrain()
    codes = validate_document(doc)
    if codes:
        raise SurfaceWaterError("invalid document: " + ", ".join(codes))
    built = tg.build(doc)
    layers = dict(built["layers"])
    spec = doc["shallowWater"]
    dx = float(doc.get("metersPerCell", 1.0))
    state = initial_state(layers, dx)
    count = steps_for(t, _get(spec, "step"), _get(spec, "maxSteps"))
    for n in range(count):
        state = step(state, spec, dx, n)
    layers["water"] = state["h"]
    if "flow" in layers:
        layers["flow"] = [[(state["hu"][j][i], state["hv"][j][i]) for i in range(state["nx"])] for j in range(state["ny"])]
    return {"shape": built["shape"], "layers": layers, "steps": count, "substeps": state["substeps"],
            "digest": digest(layers)}


# ------------------------------------------------------------------------------------------------ documents


def example_document():
    """The terrain draft's example with water and flow layers, rain and one source."""
    doc = terrain().example_document()
    doc["layers"] += [{"kind": "flow", "value": 0.0}]
    if not any(layer["kind"] == "water" for layer in doc["layers"]):
        doc["layers"].append({"kind": "water", "value": 0.0})
    doc["shallowWater"] = {"order": 2, "manning": 0.03, "cfl": 0.5, "rain": 0.001, "dryTolerance": 1e-6, "step": 0.02,
                           "boundary": "closed", "maxSteps": 100000,
                           "sources": [{"x": 400.0, "y": 300.0, "radius": 60.0, "rate": 0.05, "start": 0.0, "end": None}]}
    return doc


def bad_document():
    doc = example_document()
    doc["shallowWater"]["order"] = 3
    doc["shallowWater"]["boundary"] = "periodic"
    doc["shallowWater"]["sources"][0]["radius"] = 0.0
    doc["processes"] = [{"kind": "hydraulic"}]
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "water"]
    return doc


def _extent(doc):
    """The grid's extent in metres, from the terrain draft's shape."""
    tg = terrain()
    nx, ny = tg.shape(doc) if hasattr(tg, "shape") else tg.build(doc)["shape"]
    dx = float(doc.get("metersPerCell", 1.0))
    return nx * dx, ny * dx


def validate_document(doc):
    """The draft's rules SW1 to SW5 and V17 over a terrain document, as sorted codes."""
    spec = doc.get("shallowWater")
    if spec is None:
        return []
    major, minor = (int(x) for x in str(doc.get("version", "1.8")).split(".")[:2])
    if (major, minor) < (1, 8):
        return ["V17"]
    codes = set()
    g = lambda key: _get(spec, key)      # noqa: E731
    order = g("order")
    if not (isinstance(order, int) and not isinstance(order, bool) and order in (1, 2)
            and _number(g("manning")) and g("manning") >= 0.0
            and _number(g("cfl")) and 0.0 < g("cfl") <= 1.0
            and _number(g("rain")) and g("rain") >= 0.0
            and _number(g("dryTolerance")) and g("dryTolerance") > 0.0
            and _number(g("step")) and g("step") > 0.0
            and isinstance(g("maxSteps"), int) and not isinstance(g("maxSteps"), bool) and g("maxSteps") > 0):
        codes.add("SW1")
    if any(p.get("kind") == "hydraulic" for p in doc.get("processes", ())) or isinstance(spec, list):
        codes.add("SW2")
    width, height = _extent(doc)
    for s in g("sources"):
        end = s.get("end")
        start = s.get("start", 0.0)
        if not (_number(s.get("radius")) and s["radius"] > 0.0 and _number(s.get("rate")) and s["rate"] >= 0.0
                and _number(s.get("x")) and 0.0 <= s["x"] <= width and _number(s.get("y")) and 0.0 <= s["y"] <= height
                and _number(start) and start >= 0.0 and (end is None or (_number(end) and end > start))):
            codes.add("SW3")
    kinds = {terrain()._layer_key(layer) for layer in doc.get("layers", ())}
    if "water" not in kinds:
        codes.add("SW4")
    if g("boundary") not in BOUNDARIES:
        codes.add("SW5")
    return sorted(codes)


# ----------------------------------------------------------------------------------------------- numeric table

TABLE = (
    ("hydrostatic reconstruction", "reconstruct(2.0, 0.5, 2.0, 1.0)", "(1.0, 1.0)"),
    ("reconstruction at a dry wall", "reconstruct(2.0, 0.5, 3.0, 3.0)", "(0.0, 0.0)"),
    ("flux of equal states", "flux_x(1.5, 0.7, -0.2, 1.5, 0.7, -0.2, GRAVITY)", "(1.0499999999999998, 11.771249999999998, -0.20999999999999996)"),
    ("flux into a dry cell", "flux_x(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, GRAVITY)", "(1.5660459763365826, 2.4525, 0.0)"),
    ("Manning friction", "friction(1.0, 2.0, 0.03, 0.1, GRAVITY)", "1.996474625106986"),
    ("substeps of a still lake", "substeps(LAKE0, dict(DEFAULTS, step=0.1), 1.0)", "1"),
    ("lake at rest, surface error", "LAKE_ERROR", "0.0"),
    ("lake at rest, discharge", "LAKE_FLOW", "6.589407495776083e-16"),
    ("Ritter at the dam", "ritter(10.0, 1.0, 10.0, 1.0, GRAVITY)", "(0.4444444444444444, 2.08806130178211)"),
    ("Ritter front", "10.0 + 2.0 * math.sqrt(GRAVITY)", "16.26418390534633"),
    ("dam break, order 1 L1 error", "RITTER1_ERROR", "0.008072546012923542"),
    ("dam break, order 2 L1 error", "RITTER2_ERROR", "0.0026969248616714727"),
    ("dam break, mass", "sum(RITTER2['h'][0]) * 0.05", "10.0"),
    ("Thacker period", "thacker_period(THACKER)", "2.006066680710647"),
    ("Thacker volume", "thacker_volume(0.0, THACKER)", "0.7586622729808333"),
    ("Thacker volume at a quarter period", "thacker_volume(thacker_period(THACKER) / 4.0, THACKER)", "0.7586622729808333"),
    ("Thacker centre velocity at a quarter period", "thacker(2.0, thacker_period(THACKER) / 4.0, THACKER)[1]", "-0.9396275858019495"),
    ("Thacker, order 1 L1 error after one period", "THACKER1_ERROR", "0.025301209556228478"),
    ("Thacker, order 2 L1 error after one period", "THACKER2_ERROR", "0.0015514211584164946"),
    ("bump crest depth", "bump_depth(10.0, BUMP)", "1.707347467915034"),
    ("bump, L1 error at steady state", "BUMP_ERROR", "0.001891827550793766"),
    ("bump, discharge at the crest", "BUMP_STATE['hu'][0][BUMP['nx'] // 2 - 8]", "4.420761646098794"),
    ("source cells", "source_cells(DOC['shallowWater']['sources'][0], 16, 12, 50.0)", "4"),
    ("run, steps", "RUN['steps']", "25"),
    ("run, substeps", "RUN['substeps']", "25"),
    ("run, water under the source", "RUN['layers']['water'][6][8]", "0.025420659798999372"),
    ("run, digest", "RUN['digest']", "'cba257f34e7c253db3f3c19dcc7c030e242117ca33e79260883912bb8c58597b'"),
    ("bad document", "validate_document(bad_document())", "['SW1', 'SW2', 'SW3', 'SW4', 'SW5']"),
)

_SCOPE = None


def _l1(a, b):
    num = sum(abs(x - y) for ra, rb in zip(a, b) for x, y in zip(ra, rb))
    den = sum(abs(y) for rb in b for y in rb)
    return num / den


def _lake():
    tg = terrain()
    nx, ny = 24, 6
    bed = [[0.2 * math.exp(-((i - 8) ** 2 + (j - 3) ** 2) / 6.0) + (1.5 if 16 <= i <= 18 and 2 <= j <= 3 else 0.0)
            for i in range(nx)] for j in range(ny)]
    water = [[max(0.0, 1.0 - bed[j][i]) for i in range(nx)] for j in range(ny)]
    state0 = initial_state({"bedrock": bed, "water": water}, 1.0)
    state = state0
    spec = dict(DEFAULTS, order=2, step=0.05, manning=0.0)
    for _ in range(40):
        state = step(state, spec, 1.0)
    err = max(abs(state["h"][j][i] + bed[j][i] - 1.0) if water[j][i] > 0.0 else abs(state["h"][j][i])
              for j in range(ny) for i in range(nx))
    flow = max(max(abs(v) for v in row) for row in state["hu"] + state["hv"])
    del tg
    return state0, err, flow


def _ritter(order):
    nx, length, h_l = 400, 20.0, 1.0
    dx = length / nx
    water = [[h_l if (i + 0.5) * dx < length / 2 else 0.0 for i in range(nx)]]
    spec = dict(DEFAULTS, order=order, step=0.01, manning=0.0, boundary="closed")
    state = initial_state({"bedrock": [[0.0] * nx], "water": water}, dx)
    for _ in range(100):
        state = step(state, spec, dx)
    exact = [[ritter((i + 0.5) * dx, 1.0, length / 2, h_l, GRAVITY)[0] for i in range(nx)]]
    return state, _l1(state["h"], exact)


def scope():
    """The names the table's expressions use (computed once)."""
    global _SCOPE
    if _SCOPE is None:
        s = dict(globals())
        s["math"] = math
        s["LAKE0"], s["LAKE_ERROR"], s["LAKE_FLOW"] = _lake()
        s["RITTER1"], s["RITTER1_ERROR"] = _ritter(1)
        s["RITTER2"], s["RITTER2_ERROR"] = _ritter(2)
        s["THACKER"] = thacker_case()
        for order in (1, 2):
            st, ex = thacker_run(s["THACKER"], order)
            s[f"THACKER{order}_ERROR"] = _l1(st["h"], ex)
        s["BUMP"] = bump_case()
        s["BUMP_STATE"] = bump_run(s["BUMP"], 1)
        s["BUMP_ERROR"] = _l1([s["BUMP_STATE"]["h"][0]], [[bump_depth(x, s["BUMP"]) for x in s["BUMP"]["xs"]]])
        s["DOC"] = example_document()
        s["RUN"] = run(s["DOC"], 0.5)
        _SCOPE = s
    return _SCOPE


def _same(a, b, rel=5e-4, abs_tol=1e-9):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
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
