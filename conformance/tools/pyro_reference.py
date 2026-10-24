#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add combustion and sparse tiles to pyro"
(srep/srep-0000-pyro-combustion.md), S2 of SREP 12.

Standard library only. The rules of the SREP's Semantics section are the functions below, in its order: the
grid and its samples (rule 1), advection (rule 2), sources (rule 3), combustion (rule 4), forces (rule 5), the
projection (rule 6), the step (rule 7), active tiles and the sparse step (rules 8 and 9), the plume checks
(rule 10) and the bounds (rule 11). `main()` prints the SREP's numeric table; `tests/test_pyro_combustion.py`
checks both.

Positions are in grid units (cell (i, j, k) has its centre at (i + 0.5, j + 0.5, k + 0.5)); velocities are in
scene units per second with the voxel size h converting; axis 1 is the document's y, and hot air accelerates
toward negative y as SREP 40 states.
"""
import math

MAX_CELLS = 1 << 21          # cells of one grid (128 cubed)
MAX_STEPS = 65536            # steps of one run
MAX_ITERATIONS = 10000       # conjugate-gradient iterations of one projection (pyro/@pressureIterations)
MIN_TILE = 4                 # cells along each axis of a tile
MAX_TILE = 32
CONFINEMENT_FLOOR = 1e-9     # a |grad |omega|| below this share of the peak |omega| over h is rounding, not a core direction


class ProjectionError(Exception):
    """The projection did not reach its tolerance within its iterations, or the domain cannot meet its target."""


# --- rule 1: the grid -----------------------------------------------------------------------------------------


def index(p, cells):
    return p[0] + cells[0] * (p[1] + cells[1] * p[2])


def coords(k, cells):
    return (k % cells[0], (k // cells[0]) % cells[1], k // (cells[0] * cells[1]))


def face_dims(cells, axis):
    d = list(cells)
    d[axis] += 1
    return tuple(d)


def grid(nx, ny, nz, h, ambient=300.0):
    """A grid of nx x ny x nz cells of size h: cell-centred density, temperature (ambient) and fuel, face-centred
    velocities (axis a has cells[a] + 1 faces along a), at rest at step 0."""
    cells = (nx, ny, nz)
    if any(not isinstance(c, int) or c < 1 for c in cells) or nx * ny * nz > MAX_CELLS:
        raise ValueError("a grid has 1..MAX_CELLS cells")
    if h <= 0.0 or ambient <= 0.0:
        raise ValueError("the voxel size and the ambient temperature are positive")
    n = nx * ny * nz
    return {"cells": cells, "h": h, "ambient": ambient, "density": [0.0] * n, "temperature": [ambient] * n,
            "fuel": [0.0] * n, "velocity": [[0.0] * (face_dims(cells, a)[0] * face_dims(cells, a)[1] * face_dims(cells, a)[2]) for a in range(3)],
            "step": 0}


def _lerp_index(x, n):
    """The lower index and fraction of a sample at x (in units where element e sits at e), clamped to the ends."""
    if x <= 0.0:
        return 0, 0.0
    if x >= n - 1:
        return n - 1, 0.0
    i = int(math.floor(x))
    return i, x - i


def _trilinear(values, dims, q):
    i, fx = _lerp_index(q[0], dims[0])
    j, fy = _lerp_index(q[1], dims[1])
    k, fz = _lerp_index(q[2], dims[2])
    i1 = min(i + 1, dims[0] - 1)
    j1 = min(j + 1, dims[1] - 1)
    k1 = min(k + 1, dims[2] - 1)
    nx, nxy = dims[0], dims[0] * dims[1]

    def at(a, b, c):
        return values[a + nx * b + nxy * c]

    c00 = at(i, j, k) * (1.0 - fx) + at(i1, j, k) * fx
    c10 = at(i, j1, k) * (1.0 - fx) + at(i1, j1, k) * fx
    c01 = at(i, j, k1) * (1.0 - fx) + at(i1, j, k1) * fx
    c11 = at(i, j1, k1) * (1.0 - fx) + at(i1, j1, k1) * fx
    c0 = c00 * (1.0 - fy) + c10 * fy
    c1 = c01 * (1.0 - fy) + c11 * fy
    return c0 * (1.0 - fz) + c1 * fz


def _corner_values(values, dims, q):
    i, _ = _lerp_index(q[0], dims[0])
    j, _ = _lerp_index(q[1], dims[1])
    k, _ = _lerp_index(q[2], dims[2])
    i1, j1, k1 = min(i + 1, dims[0] - 1), min(j + 1, dims[1] - 1), min(k + 1, dims[2] - 1)
    nx, nxy = dims[0], dims[0] * dims[1]
    return [values[a + nx * b + nxy * c] for a in (i, i1) for b in (j, j1) for c in (k, k1)]


def sample(g, field, p):
    """The trilinear sample of a cell-centred field at a grid position, clamped to the border cells."""
    return _trilinear(field, g["cells"], (p[0] - 0.5, p[1] - 0.5, p[2] - 0.5))


def _face_offset(axis):
    return tuple(0.0 if a == axis else 0.5 for a in range(3))


def velocity_at(g, p):
    """The velocity at a grid position: each component sampled from its faces."""
    out = []
    for a in range(3):
        off = _face_offset(a)
        out.append(_trilinear(g["velocity"][a], face_dims(g["cells"], a), (p[0] - off[0], p[1] - off[1], p[2] - off[2])))
    return tuple(out)


# --- the spec, sources and combustion ------------------------------------------------------------------------


def spec(dt=1.0 / 60.0, boundary="closed", advection="semilagrangian", buoyancy=0.0, vorticity=0.0,
         dissipation=0.0, cooling=0.0, iterations=200, tolerance=1e-6, combustion=None, tile=0, margin=1,
         threshold=1e-6):
    if dt <= 0.0:
        raise ValueError("dt is positive")
    if boundary not in ("closed", "open"):
        raise ValueError("boundary is closed or open")
    if advection not in ("semilagrangian", "maccormack"):
        raise ValueError("advection is semilagrangian or maccormack")
    if not (isinstance(iterations, int) and 1 <= iterations <= MAX_ITERATIONS):
        raise ValueError("iterations are in 1..MAX_ITERATIONS")
    if tolerance <= 0.0:
        raise ValueError("the tolerance is positive")
    if min(buoyancy, vorticity, dissipation, cooling) < 0.0:
        raise ValueError("buoyancy, vorticity, dissipation and cooling are not negative")
    if tile != 0 and not (isinstance(tile, int) and MIN_TILE <= tile <= MAX_TILE):
        raise ValueError("tile is 0 (dense) or in MIN_TILE..MAX_TILE")
    if not (isinstance(margin, int) and margin >= 0):
        raise ValueError("margin is a count of tiles")
    if threshold <= 0.0:
        raise ValueError("the threshold is positive")
    return {"dt": dt, "boundary": boundary, "advection": advection, "buoyancy": buoyancy, "vorticity": vorticity,
            "dissipation": dissipation, "cooling": cooling, "iterations": iterations, "tolerance": tolerance,
            "combustion": combustion, "tile": tile, "margin": margin, "threshold": threshold}


def combustion(ignition, rate, heat, expansion, soot):
    """Fuel at or above the ignition temperature burns at rate per second, releasing heat kelvin, expansion
    (divergence integrated over the step, per unit fuel) and soot density per unit fuel burnt."""
    if ignition <= 0.0:
        raise ValueError("the ignition temperature is positive")
    if min(rate, heat, expansion, soot) < 0.0:
        raise ValueError("rate, heat, expansion and soot are not negative")
    return {"ignition": ignition, "rate": rate, "heat": heat, "expansion": expansion, "soot": soot}


def source(shape, density_rate=0.0, temperature_rate=0.0, fuel_rate=0.0, velocity_rate=(0.0, 0.0, 0.0),
           expansion=0.0, start=0.0, end=None):
    """A source over a sphere (centre, radius) or box (low, high corner), in grid units, active from start
    until end: rates per second of density, temperature, fuel and velocity, and a target divergence."""
    if shape[0] == "sphere":
        if len(shape) != 3 or shape[2] <= 0.0:
            raise ValueError("a sphere is (centre, radius)")
    elif shape[0] == "box":
        if len(shape) != 3 or any(shape[1][a] >= shape[2][a] for a in range(3)):
            raise ValueError("a box is (low, high)")
    else:
        raise ValueError("a source is a sphere or a box")
    if min(density_rate, temperature_rate, fuel_rate) < 0.0:
        raise ValueError("rates of density, temperature and fuel are not negative")
    if end is not None and end <= start:
        raise ValueError("end is after start")
    return {"shape": shape, "density_rate": density_rate, "temperature_rate": temperature_rate,
            "fuel_rate": fuel_rate, "velocity_rate": tuple(velocity_rate), "expansion": expansion, "start": start,
            "end": end}


def inside(src, p):
    shape = src["shape"]
    if shape[0] == "sphere":
        c, r = shape[1], shape[2]
        return (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2 < r * r
    lo, hi = shape[1], shape[2]
    return all(lo[a] <= p[a] < hi[a] for a in range(3))


def active(src, t):
    return src["start"] <= t and (src["end"] is None or t < src["end"])


# --- rule 2: advection ----------------------------------------------------------------------------------------


def _trace(g, p, dt_h, sign):
    """The midpoint semi-Lagrangian origin of p: sign -1 traces back, +1 forward."""
    v1 = velocity_at(g, p)
    mid = tuple(p[a] + sign * 0.5 * dt_h * v1[a] for a in range(3))
    v2 = velocity_at(g, mid)
    return tuple(p[a] + sign * dt_h * v2[a] for a in range(3))


def _advect_channel(g, values, dims, offset, dt_h, maccormack, mask=None):
    n = dims[0] * dims[1] * dims[2]
    out = list(values)
    origins = []
    for e in range(n):
        if mask is not None and not mask[e]:
            origins.append(None)
            continue
        c = coords(e, dims)
        p = (c[0] + offset[0], c[1] + offset[1], c[2] + offset[2])
        back = _trace(g, p, dt_h, -1.0)
        q = (back[0] - offset[0], back[1] - offset[1], back[2] - offset[2])
        out[e] = _trilinear(values, dims, q)
        origins.append((p, q))
    if not maccormack:
        return out
    hat = out
    limited = list(hat)
    for e in range(n):
        if origins[e] is None:
            continue
        p, q = origins[e]
        fwd = _trace(g, p, dt_h, 1.0)
        til = _trilinear(hat, dims, (fwd[0] - offset[0], fwd[1] - offset[1], fwd[2] - offset[2]))
        value = hat[e] + 0.5 * (values[e] - til)
        corners = _corner_values(values, dims, q)
        limited[e] = min(max(value, min(corners)), max(corners))
    return limited


def advect(g, s, mask=None):
    """The fields carried by the velocity over dt: midpoint semi-Lagrangian or MacCormack with the extrema
    limiter; dissipation and cooling applied to the carried value. Returns a new grid."""
    dt_h = s["dt"] / g["h"]
    mac = s["advection"] == "maccormack"
    cells = g["cells"]
    out = dict(g)
    centre = (0.5, 0.5, 0.5)
    out["density"] = _advect_channel(g, g["density"], cells, centre, dt_h, mac, mask)
    out["temperature"] = _advect_channel(g, g["temperature"], cells, centre, dt_h, mac, mask)
    out["fuel"] = _advect_channel(g, g["fuel"], cells, centre, dt_h, mac, mask)
    out["velocity"] = []
    for a in range(3):
        fmask = None if mask is None else _face_mask(mask, cells, a)
        out["velocity"].append(_advect_channel(g, g["velocity"][a], face_dims(cells, a), _face_offset(a), dt_h, mac, fmask))
    decay = math.exp(-s["dissipation"] * s["dt"])
    cool = math.exp(-s["cooling"] * s["dt"])
    amb = g["ambient"]
    out["density"] = [d * decay for d in out["density"]]
    out["temperature"] = [amb + (t - amb) * cool for t in out["temperature"]]
    return out


# --- rule 3: sources ------------------------------------------------------------------------------------------


def _cell_faces(c, cells, a):
    d = face_dims(cells, a)
    hi = list(c)
    hi[a] += 1
    return index(c, d), index(tuple(hi), d)


def apply_sources(g, s, sources, t):
    """Adds each active source's rates times dt to the cells whose centre it contains and returns the target
    divergence per cell (the sources' expansion)."""
    cells = g["cells"]
    n = cells[0] * cells[1] * cells[2]
    target = [0.0] * n
    dt = s["dt"]
    for src in sources:
        if not active(src, t):
            continue
        faces = [set(), set(), set()]
        for k in range(n):
            c = coords(k, cells)
            if not inside(src, (c[0] + 0.5, c[1] + 0.5, c[2] + 0.5)):
                continue
            g["density"][k] += src["density_rate"] * dt
            g["temperature"][k] += src["temperature_rate"] * dt
            g["fuel"][k] += src["fuel_rate"] * dt
            target[k] += src["expansion"]
            for a in range(3):
                faces[a].update(_cell_faces(c, cells, a))
        for a in range(3):
            if src["velocity_rate"][a] != 0.0:
                for f in faces[a]:
                    g["velocity"][a][f] += src["velocity_rate"][a] * dt
    return target


# --- rule 4: combustion ---------------------------------------------------------------------------------------


def burn(g, s, target):
    """Fuel in cells at or above the ignition temperature burns by the fraction 1 - exp(-rate dt): the fuel
    falls, the temperature rises by heat per unit burnt, soot is added to the density and the target divergence
    gains expansion per unit burnt over dt. Returns the fuel burnt."""
    c = s["combustion"]
    if c is None:
        return 0.0
    frac = 1.0 - math.exp(-c["rate"] * s["dt"])
    burnt_total = 0.0
    fuel, temp, dens = g["fuel"], g["temperature"], g["density"]
    for k in range(len(fuel)):
        if fuel[k] > 0.0 and temp[k] >= c["ignition"]:
            burnt = fuel[k] * frac
            fuel[k] -= burnt
            temp[k] += c["heat"] * burnt
            dens[k] += c["soot"] * burnt
            target[k] += c["expansion"] * burnt / s["dt"]
            burnt_total += burnt
    return burnt_total


# --- rule 5: forces -------------------------------------------------------------------------------------------


def curl(g):
    """The curl at every cell centre by central differences of the interpolated velocity one cell apart."""
    cells, h = g["cells"], g["h"]
    out = []
    for k in range(cells[0] * cells[1] * cells[2]):
        c = coords(k, cells)
        p = (c[0] + 0.5, c[1] + 0.5, c[2] + 0.5)
        d = []
        for a in range(3):
            lo = list(p)
            lo[a] -= 1.0
            hi = list(p)
            hi[a] += 1.0
            vl, vh = velocity_at(g, lo), velocity_at(g, hi)
            d.append(tuple((vh[b] - vl[b]) / (2.0 * h) for b in range(3)))
        out.append((d[1][2] - d[2][1], d[2][0] - d[0][2], d[0][1] - d[1][0]))
    return out


def forces(g, s, acceleration, mask=None):
    """Adds dt times the cell accelerations (external, buoyancy -buoyancy (T - ambient) along y, vorticity
    confinement vorticity h (N x omega)) to the faces: an interior face takes the mean of its two cells, a
    domain face its one cell when the boundary is open and nothing when closed."""
    cells, h, dt = g["cells"], g["h"], s["dt"]
    n = cells[0] * cells[1] * cells[2]
    amb = g["ambient"]
    f = [[acceleration[0], acceleration[1] - s["buoyancy"] * (g["temperature"][k] - amb), acceleration[2]] for k in range(n)]
    if s["vorticity"] > 0.0:
        w = curl(g)
        mag = [math.sqrt(c[0] * c[0] + c[1] * c[1] + c[2] * c[2]) for c in w]
        floor = CONFINEMENT_FLOOR * max(mag) / h
        for k in range(n):
            if mask is not None and not mask[k]:
                continue
            c = coords(k, cells)
            grad = []
            for a in range(3):
                lo = list(c)
                lo[a] = max(lo[a] - 1, 0)
                hi = list(c)
                hi[a] = min(hi[a] + 1, cells[a] - 1)
                grad.append((mag[index(tuple(hi), cells)] - mag[index(tuple(lo), cells)]) / (2.0 * h))
            length = math.sqrt(grad[0] ** 2 + grad[1] ** 2 + grad[2] ** 2)
            if length > floor:
                nx, ny, nz = (v / length for v in grad)
                ox, oy, oz = w[k]
                f[k][0] += s["vorticity"] * h * (ny * oz - nz * oy)
                f[k][1] += s["vorticity"] * h * (nz * ox - nx * oz)
                f[k][2] += s["vorticity"] * h * (nx * oy - ny * ox)
    open_walls = s["boundary"] == "open"
    for a in range(3):
        d = face_dims(cells, a)
        faces = g["velocity"][a]
        for e in range(len(faces)):
            c = coords(e, d)
            hi = list(c)
            lo = list(c)
            lo[a] -= 1
            has_lo, has_hi = lo[a] >= 0, hi[a] < cells[a]
            if has_lo and has_hi:
                klo, khi = index(tuple(lo), cells), index(tuple(hi), cells)
                if mask is not None and not (mask[klo] or mask[khi]):
                    continue
                faces[e] += dt * 0.5 * (f[klo][a] + f[khi][a])
            elif open_walls:
                k = index(tuple(hi), cells) if has_hi else index(tuple(lo), cells)
                if mask is not None and not mask[k]:
                    continue
                faces[e] += dt * f[k][a]
    return g


# --- rule 6: the projection -----------------------------------------------------------------------------------


def divergence(g):
    cells, h = g["cells"], g["h"]
    out = []
    for k in range(cells[0] * cells[1] * cells[2]):
        c = coords(k, cells)
        d = 0.0
        for a in range(3):
            lo, hi = _cell_faces(c, cells, a)
            d += g["velocity"][a][hi] - g["velocity"][a][lo]
        out.append(d / h)
    return out


def project(g, s, target, fluid=None):
    """Makes the divergence equal the target: solves -div grad p = (target - div u) / dt by Jacobi-preconditioned
    conjugate gradients over the fluid cells (all cells, or the active ones) with no-through domain walls
    (closed; the mean of the right-hand side is removed, so a net expansion stays in the measured error) or
    zero pressure outside (open; cells outside the fluid set are also at zero pressure), then subtracts dt grad p
    from the faces. Stops when the RMS divergence error is at most the tolerance; more iterations than allowed,
    or a recomputed error above 1.01 times the tolerance, is a ProjectionError. Returns (iterations, error)."""
    cells, h, dt = g["cells"], g["h"], s["dt"]
    n = cells[0] * cells[1] * cells[2]
    if fluid is None:
        fluid = [True] * n
    closed = s["boundary"] == "closed"
    if closed:
        for a in range(3):
            d = face_dims(cells, a)
            for e in range(len(g["velocity"][a])):
                c = coords(e, d)
                if c[a] == 0 or c[a] == cells[a]:
                    g["velocity"][a][e] = 0.0
    div = divergence(g)
    unknowns = [k for k in range(n) if fluid[k]]
    if not unknowns:
        return 0, 0.0
    pos = {k: i for i, k in enumerate(unknowns)}
    neighbours, diag = [], []
    inv_h2 = 1.0 / (h * h)
    for k in unknowns:
        c = coords(k, cells)
        nb = []
        count = 0
        for a in range(3):
            for step in (-1, 1):
                q = list(c)
                q[a] += step
                if 0 <= q[a] < cells[a]:
                    kq = index(tuple(q), cells)
                    if fluid[kq]:
                        nb.append(pos[kq])
                        count += 1
                    else:
                        count += 1            # a cell outside the fluid set is at zero pressure
                elif not closed:
                    count += 1                # an open wall is at zero pressure
        neighbours.append(nb)
        diag.append(count * inv_h2)
    b = [(target[k] - div[k]) / dt for k in unknowns]
    m = len(unknowns)
    if closed and all(d == len(nb) * inv_h2 for d, nb in zip(diag, neighbours)):
        mean = sum(b) / m                  # a pure Neumann system: the mean of b has no solution
        b = [v - mean for v in b]
    x = [0.0] * m
    r = list(b)
    inv_diag = [1.0 / d if d > 0.0 else 0.0 for d in diag]
    z = [r[i] * inv_diag[i] for i in range(m)]
    p = list(z)
    rz = sum(r[i] * z[i] for i in range(m))
    iterations = 0
    tol = s["tolerance"]

    def error_of(res):
        return dt * math.sqrt(sum(v * v for v in res) / m)

    err = error_of(r)
    while err > tol:
        if iterations >= s["iterations"]:
            raise ProjectionError(f"the projection did not converge: error {err:.3e} after {iterations} iterations")
        ap = [diag[i] * p[i] - inv_h2 * sum(p[j] for j in neighbours[i]) for i in range(m)]
        pap = sum(p[i] * ap[i] for i in range(m))
        if pap <= 0.0:
            break
        alpha = rz / pap
        for i in range(m):
            x[i] += alpha * p[i]
            r[i] -= alpha * ap[i]
        iterations += 1
        err = error_of(r)
        if err <= tol:
            break
        z = [r[i] * inv_diag[i] for i in range(m)]
        rz_new = sum(r[i] * z[i] for i in range(m))
        beta = rz_new / rz
        rz = rz_new
        p = [z[i] + beta * p[i] for i in range(m)]
    pressure = [0.0] * n
    for i, k in enumerate(unknowns):
        pressure[k] = x[i]
    for a in range(3):
        d = face_dims(cells, a)
        faces = g["velocity"][a]
        for e in range(len(faces)):
            c = coords(e, d)
            hi = list(c)
            lo = list(c)
            lo[a] -= 1
            has_lo, has_hi = lo[a] >= 0, hi[a] < cells[a]
            klo = index(tuple(lo), cells) if has_lo else None
            khi = index(tuple(hi), cells) if has_hi else None
            flo = klo is not None and fluid[klo]
            fhi = khi is not None and fluid[khi]
            if not (flo or fhi):
                continue
            if closed and (klo is None or khi is None):
                continue
            plo = pressure[klo] if klo is not None else 0.0
            phi = pressure[khi] if khi is not None else 0.0
            faces[e] -= dt * (phi - plo) / h
    after = divergence(g)
    err = dt * math.sqrt(sum(((after[k] - target[k]) / dt) ** 2 for k in unknowns) / m)
    if err > 1.01 * tol:
        raise ProjectionError(f"the divergence error after the solve is {err:.3e}")
    return iterations, err


# --- rules 7 to 9: the step, active tiles and the sparse step -------------------------------------------------


def _copy(g):
    return {"cells": g["cells"], "h": g["h"], "ambient": g["ambient"], "density": list(g["density"]),
            "temperature": list(g["temperature"]), "fuel": list(g["fuel"]),
            "velocity": [list(v) for v in g["velocity"]], "step": g["step"]}


def step(g, s, sources, acceleration=(0.0, 0.0, 0.0)):
    """One step: advect, add the sources, burn, apply the forces, project; the step count rises by one."""
    if s["tile"]:
        return step_sparse(g, s, sources, acceleration)
    t = g["step"] * s["dt"]
    out = advect(g, s)
    out = _copy(out)
    target = apply_sources(out, s, sources, t)
    burn(out, s, target)
    forces(out, s, acceleration)
    project(out, s, target)
    out["step"] = g["step"] + 1
    return out


def run(g, s, sources, steps, acceleration=(0.0, 0.0, 0.0)):
    if not (isinstance(steps, int) and 0 <= steps <= MAX_STEPS):
        raise ValueError("steps are in 0..MAX_STEPS")
    if s["tile"] and any(c % s["tile"] for c in g["cells"]):
        raise ValueError("the tile divides every dimension")
    out = _copy(g)
    for _ in range(steps):
        out = step(out, s, sources, acceleration)
    return out


def active_tiles(g, s):
    """The tiles holding density or fuel above the threshold, or heat beyond the threshold times ambient,
    dilated by the margin; velocity alone wakes no tile (a semi-Lagrangian support grows by a cell per step
    at any speed, so a floor is what keeps the tiles few)."""
    t = s["tile"]
    cells = g["cells"]
    if any(c % t for c in cells):
        raise ValueError("the tile divides every dimension")
    tiles = tuple(c // t for c in cells)
    amb = g["ambient"]
    live = set()
    n = cells[0] * cells[1] * cells[2]
    th = s["threshold"]
    for k in range(n):
        if g["density"][k] > th or g["fuel"][k] > th or abs(g["temperature"][k] - amb) > th * amb:
            c = coords(k, cells)
            live.add((c[0] // t, c[1] // t, c[2] // t))
    out = set()
    m = s["margin"]
    for (i, j, k) in live:
        for di in range(-m, m + 1):
            for dj in range(-m, m + 1):
                for dk in range(-m, m + 1):
                    q = (i + di, j + dj, k + dk)
                    if all(0 <= q[a] < tiles[a] for a in range(3)):
                        out.add(q)
    return out


def _cell_mask(g, tiles, t):
    cells = g["cells"]
    return [(lambda c: (c[0] // t, c[1] // t, c[2] // t) in tiles)(coords(k, cells)) for k in range(cells[0] * cells[1] * cells[2])]


def _face_mask(mask, cells, a):
    d = face_dims(cells, a)
    out = []
    for e in range(d[0] * d[1] * d[2]):
        c = coords(e, d)
        hi = list(c)
        lo = list(c)
        lo[a] -= 1
        live = False
        if hi[a] < cells[a] and mask[index(tuple(hi), cells)]:
            live = True
        if lo[a] >= 0 and mask[index(tuple(lo), cells)]:
            live = True
        out.append(live)
    return out


def step_sparse(g, s, sources, acceleration=(0.0, 0.0, 0.0)):
    """The step of rule 7 on the active tiles only, decided from the state at the start of the step: the faces
    with no active cell are cleared, so cells outside the tiles are at rest and ambient; the projection takes
    them at zero pressure."""
    t = g["step"] * s["dt"]
    tiles = active_tiles(g, s)
    mask = _cell_mask(g, tiles, s["tile"])
    g = _copy(g)
    for a in range(3):
        fmask = _face_mask(mask, g["cells"], a)
        faces = g["velocity"][a]
        for e in range(len(faces)):
            if not fmask[e]:
                faces[e] = 0.0
    out = advect(g, s, mask)
    out = _copy(out)
    target = apply_sources(out, s, sources, t)
    burn(out, s, target)
    forces(out, s, acceleration, mask)
    project(out, s, target, mask)
    out["step"] = g["step"] + 1
    return out


# --- rule 10: the plume checks --------------------------------------------------------------------------------


def _centroid_y(g):
    cells = g["cells"]
    total = sum(g["density"])
    if total == 0.0:
        return 0.0
    return sum(d * (coords(k, cells)[1] + 0.5) for k, d in enumerate(g["density"])) / total


def mirror_error(g, axis):
    """The largest difference between the density and its mirror image across the grid's middle plane."""
    cells = g["cells"]
    worst = 0.0
    for k, d in enumerate(g["density"]):
        c = list(coords(k, cells))
        c[axis] = cells[axis] - 1 - c[axis]
        worst = max(worst, abs(d - g["density"][index(tuple(c), cells)]))
    return worst


def symmetric_plume(steps, advection="semilagrangian"):
    """A hot source at the centre of the bottom of an 8 x 12 x 8 closed box with buoyancy and confinement:
    the mirror errors across x and z, the density centroid's y and the peak density after the steps."""
    g = grid(8, 12, 8, 1.0)
    s = spec(buoyancy=0.05, vorticity=0.5, advection=advection)
    src = [source(("sphere", (4.0, 10.0, 4.0), 1.2), density_rate=3.0, temperature_rate=600.0)]
    out = run(g, s, src, steps)
    return {"mirror_x": mirror_error(out, 0), "mirror_z": mirror_error(out, 2), "centroid_y": _centroid_y(out),
            "peak": max(out["density"])}


def divergence_test():
    """A random-looking face field in an open 8-cube: the RMS divergence before, the iterations, the error after
    and the worst cell's error."""
    g = grid(8, 8, 8, 0.5)
    for a in range(3):
        g["velocity"][a] = [math.sin(1.7 * e + a) + 0.3 * math.cos(0.4 * e) for e in range(len(g["velocity"][a]))]
    before = divergence(g)
    s = spec(boundary="open", tolerance=1e-8)
    its, err = project(g, s, [0.0] * 512)
    after = divergence(g)
    return {"before": math.sqrt(sum(d * d for d in before) / 512), "after": err, "iterations": its,
            "worst_cell": max(abs(d) for d in after)}


def combustion_test(steps=40, burn_fuel=True):
    """A fuel source heated past ignition in a closed 8 x 12 x 8 box at rest (no buoyancy, no expansion, so the
    air never moves and the rule is seen alone), with or without combustion: the fuel added, burnt and left,
    the soot and the peak temperature."""
    c = combustion(ignition=600.0, rate=20.0, heat=2000.0, expansion=0.0, soot=0.2) if burn_fuel else None
    g = grid(8, 12, 8, 1.0)
    s = spec(combustion=c)
    src = [source(("sphere", (4.0, 10.0, 4.0), 1.2), temperature_rate=1200.0, fuel_rate=1.0, start=0.0, end=0.25)]
    out = _copy(g)
    added = burnt = 0.0
    for _ in range(steps):
        t = out["step"] * s["dt"]
        if active(src[0], t):
            inside_count = sum(1 for k in range(len(out["fuel"])) if inside(src[0], tuple(v + 0.5 for v in coords(k, g["cells"]))))
            added += inside_count * s["dt"]
        nxt = advect(out, s)
        nxt = _copy(nxt)
        target = apply_sources(nxt, s, src, t)
        burnt += burn(nxt, s, target)
        forces(nxt, s, (0.0, 0.0, 0.0))
        project(nxt, s, target)
        nxt["step"] = out["step"] + 1
        out = nxt
    return {"fuel_added": added, "burnt": burnt, "fuel_left": sum(out["fuel"]), "soot": sum(out["density"]),
            "peak_temperature": max(out["temperature"])}


def fire_test(steps=30):
    """The same source with and without fuel and combustion: the centroids and peak temperatures."""
    c = combustion(ignition=600.0, rate=20.0, heat=2000.0, expansion=0.5, soot=0.2)
    g = grid(8, 12, 8, 1.0)
    smoke = run(g, spec(boundary="open", buoyancy=0.02), [source(("sphere", (4.0, 10.0, 4.0), 1.2), density_rate=1.0, temperature_rate=1200.0)], steps)
    fire_spec = spec(boundary="open", buoyancy=0.02, combustion=c)
    src = [source(("sphere", (4.0, 10.0, 4.0), 1.2), density_rate=1.0, temperature_rate=1200.0, fuel_rate=1.0)]
    out = _copy(g)
    burnt = 0.0
    for _ in range(steps):
        t = out["step"] * fire_spec["dt"]
        nxt = _copy(advect(out, fire_spec))
        target = apply_sources(nxt, fire_spec, src, t)
        burnt += burn(nxt, fire_spec, target)
        forces(nxt, fire_spec, (0.0, 0.0, 0.0))
        project(nxt, fire_spec, target)
        nxt["step"] = out["step"] + 1
        out = nxt
    return {"fire_centroid_y": _centroid_y(out), "smoke_centroid_y": _centroid_y(smoke),
            "fire_peak_temperature": max(out["temperature"]), "smoke_peak_temperature": max(smoke["temperature"]),
            "burnt": burnt}


def confinement_test(steps=8):
    """A Gaussian vortex about y in a 10 x 4 x 10 box carried with and without confinement: the peak |curl| at
    the start and after the steps."""
    def vortex():
        g = grid(10, 4, 10, 1.0)
        for a in (0, 2):
            d = face_dims(g["cells"], a)
            off = _face_offset(a)
            for e in range(len(g["velocity"][a])):
                c = coords(e, d)
                x, z = c[0] + off[0] - 5.0, c[2] + off[2] - 5.0
                w = 3.0 * math.exp(-(x * x + z * z) / 4.0)
                g["velocity"][a][e] = -z * w if a == 0 else x * w
        return g

    def peak(g):
        return max(math.sqrt(c[0] ** 2 + c[1] ** 2 + c[2] ** 2) for c in curl(g))

    start = vortex()
    plain = run(start, spec(), [], steps)
    confined = run(start, spec(vorticity=2.0), [], steps)
    return {"curl_peak": peak(start), "plain_peak": peak(plain), "confined_peak": peak(confined)}


def sparse_test(steps=12):
    """A plume in an open 16 x 12 x 16 box stepped densely and on tiles of 4 with a margin of 1: the active
    fraction at the end, the peaks and the largest density difference."""
    g = grid(16, 12, 16, 1.0)
    src = [source(("sphere", (6.0, 6.0, 6.0), 1.2), density_rate=3.0, temperature_rate=600.0)]
    dense = run(g, spec(boundary="open", buoyancy=0.05, vorticity=0.5), src, steps)
    sparse_spec = spec(boundary="open", buoyancy=0.05, vorticity=0.5, tile=4, margin=1)
    sparse = run(g, sparse_spec, src, steps)
    tiles = active_tiles(sparse, sparse_spec)
    return {"active_fraction": len(tiles) / (4 * 3 * 4), "peak": max(sparse["density"]),
            "dense_peak": max(dense["density"]),
            "max_difference": max(abs(a - b) for a, b in zip(dense["density"], sparse["density"]))}


def raises_projection_error(thunk):
    """Whether calling the thunk raises ProjectionError."""
    try:
        thunk()
    except ProjectionError:
        return True
    return False


# --- the numeric table ----------------------------------------------------------------------------------------

TABLE = (
    ("cell and face counts", "(lambda g: (len(g['density']), len(g['velocity'][0]), len(g['velocity'][1]), len(g['velocity'][2])))(grid(4, 6, 5, 0.5))", "(120, 150, 140, 144)"),
    ("index and coords", "(index((1, 2, 3), (4, 6, 5)), coords(index((1, 2, 3), (4, 6, 5)), (4, 6, 5)))", "(81, (1, 2, 3))"),
    ("a linear field samples linearly", "(lambda g: (round(sample(g, [float(coords(k, g['cells'])[0]) for k in range(64)], (1.75, 2.0, 2.0)), 12), round(sample(g, [float(coords(k, g['cells'])[0]) for k in range(64)], (9.0, 2.0, 2.0)), 12)))(grid(4, 4, 4, 1.0))", "(1.25, 3.0)"),
    ("a uniform face field at a centre", "(lambda g: (g['velocity'][0].__setitem__(slice(None), [1.0] * len(g['velocity'][0])), tuple(round(v, 12) for v in velocity_at(g, (1.5, 1.5, 1.5))))[1])(grid(3, 3, 3, 1.0))", "(1.0, 0.0, 0.0)"),
    ("the spec's defaults", "(lambda s: (s['dt'], s['boundary'], s['advection'], s['iterations'], s['tolerance'], s['tile'], s['margin']))(spec())", "(1.0 / 60.0, 'closed', 'semilagrangian', 200, 1e-06, 0, 1)"),
    ("a sphere source contains its centre's cell", "(inside(source(('sphere', (1.0, 1.0, 1.0), 0.5)), (1.2, 1.0, 1.0)), inside(source(('sphere', (1.0, 1.0, 1.0), 0.5)), (1.6, 1.0, 1.0)), active(source(('box', (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), start=1.0, end=2.0), 2.0))", "(True, False, False)"),
    ("semi-Lagrangian carries a blob one cell", "(lambda g: (g['density'].__setitem__(index((3, 1, 1), g['cells']), 1.0), g['velocity'].__setitem__(0, [60.0] * len(g['velocity'][0])), (lambda o: (round(o['density'][index((4, 1, 1), g['cells'])], 12), round(o['density'][index((3, 1, 1), g['cells'])], 12)))(advect(g, spec())))[2])(grid(12, 4, 4, 1.0))", "(1.0, 0.0)"),
    ("MacCormack creates no new extremum", "(lambda g: ([g['density'].__setitem__(index((i, 1, 1), g['cells']), 1.0) for i in range(3, 7)], g['velocity'].__setitem__(0, [20.0] * len(g['velocity'][0])), (lambda o: (round(max(o['density']), 12), round(min(o['density']), 12)))(advect(g, spec(advection='maccormack'))))[2])(grid(12, 4, 4, 1.0))", "(1.0, 0.0)"),
    ("dissipation and cooling", "(lambda g: (g['density'].__setitem__(21, 1.0), g['temperature'].__setitem__(21, 500.0), (lambda o: (round(o['density'][21], 12), round(o['temperature'][21], 9)))(advect(g, spec(dissipation=3.0, cooling=6.0))))[2])(grid(4, 4, 4, 1.0))", "(round(math.exp(-3.0 / 60.0), 12), round(300.0 + 200.0 * math.exp(-6.0 / 60.0), 9))"),
    ("a source adds its rates over the step", "(lambda g: (lambda t: (round(g['density'][index((4, 4, 4), g['cells'])], 12), round(g['fuel'][index((4, 4, 4), g['cells'])], 12), t[index((4, 4, 4), g['cells'])]))(apply_sources(g, spec(), [source(('sphere', (4.0, 4.0, 4.0), 1.2), density_rate=3.0, fuel_rate=1.5, expansion=0.5)], 0.0)))(grid(8, 8, 8, 1.0))", "(round(3.0 / 60.0, 12), round(1.5 / 60.0, 12), 0.5)"),
    ("hot fuel burns, cold fuel waits", "(lambda g: (g['fuel'].__setitem__(21, 1.0), g['fuel'].__setitem__(42, 1.0), g['temperature'].__setitem__(21, 700.0), (lambda t: (round(g['fuel'][21], 12), round(g['temperature'][21], 9), round(g['density'][21], 12), round(t[21], 9), g['fuel'][42], g['temperature'][42]))((lambda t: (burn(g, spec(combustion=combustion(600.0, 20.0, 2000.0, 0.5, 0.2)), t), t)[1])([0.0] * 64)))[3])(grid(4, 4, 4, 1.0))", "(round(math.exp(-20.0 / 60.0), 12), round(700.0 + 2000.0 * (1.0 - math.exp(-20.0 / 60.0)), 9), round(0.2 * (1.0 - math.exp(-20.0 / 60.0)), 12), round(0.5 * (1.0 - math.exp(-20.0 / 60.0)) * 60.0, 9), 1.0, 300.0)"),
    ("fuel is conserved through burning", "(lambda r: (round(r['fuel_added'], 9), round(r['fuel_left'] + r['burnt'], 9), r['burnt'] > 0.5 * r['fuel_added'], round(r['soot'] / r['burnt'], 9), r['peak_temperature'] > 1000.0))(combustion_test(40))", "(2.0, 2.0, True, 0.2, True)"),
    ("without combustion fuel is only carried", "(lambda r: (r['burnt'], round(r['fuel_left'] - r['fuel_added'], 9)))(combustion_test(20, burn_fuel=False))", "(0.0, 0.0)"),
    ("buoyancy accelerates a hot cell against y", "(lambda g: (g['temperature'].__setitem__(index((1, 3, 1), g['cells']), 400.0), forces(g, spec(buoyancy=2.0), (0.0, 0.0, 0.0)), (round(g['velocity'][1][index((1, 3, 1), (4, 7, 4))], 12), round(g['velocity'][1][index((1, 4, 1), (4, 7, 4))], 12)))[2])(grid(4, 6, 4, 1.0))", "(round(-100.0 / 60.0, 12), round(-100.0 / 60.0, 12))"),
    ("confinement keeps a vortex's peak", "(lambda r: (round(r['curl_peak'], 6), r['confined_peak'] > r['plain_peak'], r['plain_peak'] < r['curl_peak']))(confinement_test())", "(3.533714, True, True)"),
    ("a uniform field has no divergence", "(lambda g: (g['velocity'].__setitem__(0, [1.0] * len(g['velocity'][0])), max(abs(d) for d in divergence(g)))[1])(grid(4, 4, 4, 0.5))", "0.0"),
    ("the projection removes divergence", "(lambda r: (r['before'] > 1.0, r['after'] <= 1e-8, r['iterations'], r['worst_cell'] < 1e-7))(divergence_test())", "(True, True, 32, True)"),
    ("the projection meets a target", "(lambda g: (lambda t: (project(g, spec(boundary='open'), t), round(divergence(g)[index((3, 3, 3), g['cells'])], 5))[1])((lambda t: (t.__setitem__(index((3, 3, 3), (6, 6, 6)), 2.0), t)[1])([0.0] * 216)))(grid(6, 6, 6, 1.0))", "2.0"),
    ("closed walls carry no flow", "(lambda g: (g['velocity'].__setitem__(0, [1.0] * len(g['velocity'][0])), project(g, spec(), [0.0] * 64), max(abs(v) for v in g['velocity'][0]))[2])(grid(4, 4, 4, 1.0))", "0.0"),
    ("a run is a function of the count", "(lambda g, s, src: run(g, s, src, 12) == run(run(g, s, src, 6), s, src, 6))(grid(6, 8, 6, 1.0), spec(boundary='open', buoyancy=0.05, vorticity=0.5), [source(('sphere', (3.0, 1.5, 3.0), 1.1), density_rate=2.0, temperature_rate=300.0)])", "True"),
    ("the plume is symmetric", "(lambda r: (r['mirror_x'] <= 1e-7 * r['peak'], r['mirror_z'] <= 1e-7 * r['peak'], round(r['centroid_y'], 4), round(r['peak'], 6)))(symmetric_plume(30))", "(True, True, 9.835, 1.456509)"),
    ("the MacCormack plume is symmetric", "(lambda r: (r['mirror_x'] <= 1e-7 * r['peak'], r['mirror_z'] <= 1e-7 * r['peak'], round(r['centroid_y'], 4)))(symmetric_plume(20, 'maccormack'))", "(True, True, 9.973)"),
    ("fire rises faster than smoke", "(lambda r: (round(r['fire_centroid_y'], 4), round(r['smoke_centroid_y'], 4), r['fire_peak_temperature'] > r['smoke_peak_temperature'], r['burnt'] > 0.0))(fire_test(30))", "(9.7617, 9.8543, True, True)"),
    ("active tiles with a margin", "(lambda g: (g['density'].__setitem__(index((5, 5, 5), g['cells']), 1.0), (lambda t: (len(t), (0, 0, 0) in t, (3, 3, 3) in t))(active_tiles(g, spec(tile=4, margin=1))))[1])(grid(16, 16, 16, 1.0))", "(27, True, False)"),
    ("a moving face alone wakes no tile", "(lambda g: (g['velocity'][1].__setitem__(index((13, 13, 13), (16, 17, 16)), 1.0), len(active_tiles(g, spec(tile=4, margin=0))))[1])(grid(16, 16, 16, 1.0))", "0"),
    ("heat below the threshold wakes no tile", "(lambda g: (g['temperature'].__setitem__(0, 300.0 * (1.0 + 1e-7)), g['temperature'].__setitem__(1, 300.0 * (1.0 + 1e-5)), sorted(active_tiles(g, spec(tile=4, margin=0))))[2])(grid(16, 16, 16, 1.0))", "[(0, 0, 0)]"),
    ("the sparse step follows the dense step", "(lambda r: (round(r['active_fraction'], 4), r['max_difference'] <= 1e-3 * r['peak'], abs(r['dense_peak'] - r['peak']) <= 1e-3 * r['peak']))(sparse_test(12))", "(0.5625, True, True)"),
    ("the sparse run is a function of the count", "(lambda g, s, src: run(g, s, src, 6) == run(run(g, s, src, 3), s, src, 3))(grid(16, 16, 16, 1.0), spec(boundary='open', buoyancy=0.05, tile=4, margin=1), [source(('sphere', (8.0, 4.0, 8.0), 1.5), density_rate=2.0, temperature_rate=300.0)])", "True"),
    ("a closed box cannot expand", "raises_projection_error(lambda: project(grid(4, 4, 4, 1.0), spec(), [1.0] * 64))", "True"),
    ("bounds", "(MAX_CELLS, MAX_STEPS, MAX_ITERATIONS, MIN_TILE, MAX_TILE, CONFINEMENT_FLOOR)", "(2097152, 65536, 10000, 4, 32, 1e-09)"),
)


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["__builtins__"] = {"round": round, "tuple": tuple, "len": len, "sorted": sorted, "min": min, "max": max,
                         "abs": abs, "range": range, "list": list, "set": set, "dict": dict, "True": True,
                         "False": False, "None": None, "any": any, "all": all, "int": int, "float": float,
                         "zip": zip, "sum": sum, "slice": slice, "ValueError": ValueError}
    return s


def _same(a, b, tol=1e-9):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
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
