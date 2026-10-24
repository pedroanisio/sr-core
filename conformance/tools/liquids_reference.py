#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add particle liquids and granular media in 3D"
(srep/srep-0000-liquids.md), S3 of SREP 12.

Standard library only (the surface mesh reuses the marching tetrahedra of scalar3d_reference.py and the
diffuse-particle positions the D24 hash of random_streams_reference.py, both loaded by path). The rules of the
SREP's Semantics section are the functions below, in its order: the kernel (rule 1), the liquid and its
particles (rule 2), the transfers (rule 3), the projection (rule 4), the step (rule 5), the dam break (rule 6),
MLS-MPM for elastic, snow and sand (rule 7), whitewater (rule 8), the surface (rule 9) and the bounds (rule 10).
`main()` prints the SREP's numeric table; `tests/test_liquids.py` checks both.

The solver is written for d = 2 or 3 dimensions: the document's `liquid3D` is three-dimensional, and the
dam break of Martin and Moyce is a two-dimensional slice of it (their channel is uniform along the third axis).
Positions are in scene units; the grid has cells of size h, the component a of the velocity sits on the faces
normal to axis a (at integer multiples of h along a, at cell centres along the other axes), and every face array
carries PAD ghost layers so the quadratic B-spline of a particle at the wall has its nodes.
"""
import functools
import importlib.util
import itertools
import math
import os

MAX_PARTICLES = 1 << 20      # particles of one liquid (liquid3D/@maxParticles)
MAX_CELLS = 1 << 21          # cells of one grid (128 cubed)
MAX_STEPS = 65536            # steps of one run
MAX_ITERATIONS = 10000       # conjugate-gradient iterations of one projection (liquid3D/@pressureIterations)
MAX_SUBSTEPS = 64
MAX_PER_CELL = 64            # particles seeded per cell (liquid3D/@perCell)
PAD = 2                      # ghost layers of each face array
METHODS = ("apic", "flip", "mpm")
WALLS = ("slip", "noslip")
MATERIALS = ("elastic", "snow", "sand")
SPRAY_BELOW = 6              # a diffuse particle with fewer liquid neighbours is spray (Ihmsen et al. 2012)
FOAM_ABOVE = 20              # with more it is foam; between, a bubble
CREST_ALIGNMENT = 0.6        # v . n at or above this makes a crest particle a wave crest
MARTIN_MOYCE = ((2.11, 1.83), (3.00, 2.51), (3.89, 3.11))   # (Z, T) of the surge front, n^2 = 2 column


class ProjectionError(Exception):
    """The projection did not reach its tolerance within its iterations."""


def _load(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_scalar3d = _load("scalar3d_reference")
_streams = _load("random_streams_reference")


# --- small linear algebra ------------------------------------------------------------------------------------


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _scale(a, s):
    return tuple(x * s for x in a)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    return tuple(x / n for x in a) if n > 0.0 else tuple(0.0 for _ in a)


def identity(d):
    return tuple(tuple(1.0 if i == j else 0.0 for j in range(d)) for i in range(d))


def zeros(d):
    return tuple(tuple(0.0 for _ in range(d)) for _ in range(d))


def transpose(m):
    return tuple(tuple(m[j][i] for j in range(len(m))) for i in range(len(m[0])))


def matmul(a, b):
    bt = transpose(b)
    return tuple(tuple(_dot(row, col) for col in bt) for row in a)


def matvec(m, v):
    return tuple(_dot(row, v) for row in m)


def diag(values):
    d = len(values)
    return tuple(tuple(values[i] if i == j else 0.0 for j in range(d)) for i in range(d))


def madd(a, b, s=1.0):
    return tuple(tuple(x + s * y for x, y in zip(ra, rb)) for ra, rb in zip(a, b))


def determinant(m):
    d = len(m)
    if d == 1:
        return m[0][0]
    if d == 2:
        return m[0][0] * m[1][1] - m[0][1] * m[1][0]
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def trace(m):
    return sum(m[i][i] for i in range(len(m)))


def eigen_symmetric(m, sweeps=64):
    """Eigenvalues (descending) and the matrix whose columns are the eigenvectors, by Jacobi rotations."""
    d = len(m)
    a = [list(row) for row in m]
    v = [[1.0 if i == j else 0.0 for j in range(d)] for i in range(d)]
    for _ in range(sweeps):
        off = sum(a[i][j] ** 2 for i in range(d) for j in range(d) if i != j)
        if off < 1e-30:
            break
        for p in range(d):
            for q in range(p + 1, d):
                if abs(a[p][q]) < 1e-300:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0.0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(d):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(d):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(d):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    order = sorted(range(d), key=lambda i: -a[i][i])
    values = tuple(a[i][i] for i in order)
    vectors = tuple(tuple(v[r][i] for i in order) for r in range(d))
    return values, vectors


def svd(f):
    """F = U diag(sigma) V^T with det V > 0, sigma descending, and det U the sign of det F (the last singular
    value carries the sign of an inverted element)."""
    d = len(f)
    values, v = eigen_symmetric(matmul(transpose(f), f))
    v = [list(row) for row in v]
    if determinant(v) < 0.0:
        for r in range(d):
            v[r][d - 1] = -v[r][d - 1]
    v = tuple(tuple(row) for row in v)
    sigma = [math.sqrt(max(x, 0.0)) for x in values]
    fv = matmul(f, v)
    u = [[0.0] * d for _ in range(d)]
    for j in range(d):
        if sigma[j] > 1e-300:
            for r in range(d):
                u[r][j] = fv[r][j] / sigma[j]
        else:
            # complete U with a unit vector orthogonal to the columns found
            for cand in range(d):
                col = [1.0 if r == cand else 0.0 for r in range(d)]
                for k in range(j):
                    proj = sum(col[r] * u[r][k] for r in range(d))
                    col = [col[r] - proj * u[r][k] for r in range(d)]
                n = math.sqrt(sum(x * x for x in col))
                if n > 1e-6:
                    for r in range(d):
                        u[r][j] = col[r] / n
                    break
    if determinant(u) < 0.0:
        for r in range(d):
            u[r][d - 1] = -u[r][d - 1]
        sigma[d - 1] = -sigma[d - 1]
    return tuple(tuple(row) for row in u), tuple(sigma), v


def polar(f):
    """F = R S with R a rotation and S symmetric."""
    u, sigma, v = svd(f)
    r = matmul(u, transpose(v))
    s = matmul(matmul(v, diag(sigma)), transpose(v))
    return r, s


# --- rule 1: the kernel --------------------------------------------------------------------------------------


def bspline(x):
    """The quadratic B-spline N(x): 3/4 - x^2 for |x| < 1/2, (3/2 - |x|)^2 / 2 for 1/2 <= |x| < 3/2, else 0."""
    x = abs(x)
    if x < 0.5:
        return 0.75 - x * x
    if x < 1.5:
        return 0.5 * (1.5 - x) ** 2
    return 0.0


def stencil(x):
    """The lowest node and the three weights of a sample at x on nodes at the integers: the nodes are
    floor(x - 1/2) + k for k = 0, 1, 2, and the weights their B-spline values."""
    base = int(math.floor(x - 0.5))
    return base, tuple(bspline(x - base - k) for k in range(3))


def weights(x):
    return stencil(x)[1]


# --- rule 2: the liquid --------------------------------------------------------------------------------------


def spec(dt, method="apic", per_cell=4, flip=0.95, gravity=9.81, density=1000.0, iterations=200,
         tolerance=1e-6, walls="slip", substeps=1, correction=0.3, separation=0.75):
    """The solver settings of a liquid3D: dt per frame, the method, the particles seeded per cell (rounded to a
    lattice of round(perCell^(1/d)) per axis), the FLIP ratio, gravity along -y of the solver (+y of the
    document), the rest density, the projection's iterations and tolerance, the walls and the substeps."""
    if not (dt > 0.0 and math.isfinite(dt)):
        raise ValueError("dt is positive")
    if method not in METHODS:
        raise ValueError(f"method is one of {METHODS}")
    if not isinstance(per_cell, int) or not 1 <= per_cell <= MAX_PER_CELL:
        raise ValueError(f"perCell is 1 to {MAX_PER_CELL}")
    if not 0.0 <= flip <= 1.0:
        raise ValueError("flipRatio is 0 to 1")
    if not (gravity >= 0.0 and math.isfinite(gravity)):
        raise ValueError("gravity is non-negative")
    if not (density > 0.0 and math.isfinite(density)):
        raise ValueError("density is positive")
    if not isinstance(iterations, int) or not 1 <= iterations <= MAX_ITERATIONS:
        raise ValueError(f"pressureIterations is 1 to {MAX_ITERATIONS}")
    if not (tolerance > 0.0 and math.isfinite(tolerance)):
        raise ValueError("pressureTolerance is positive")
    if walls not in WALLS:
        raise ValueError(f"walls is one of {WALLS}")
    if not isinstance(substeps, int) or not 1 <= substeps <= MAX_SUBSTEPS:
        raise ValueError(f"substeps is 1 to {MAX_SUBSTEPS}")
    if not 0.0 <= correction <= 1.0:
        raise ValueError("densityCorrection is 0 to 1")
    if not 0.0 <= separation <= 1.0:
        raise ValueError("separation is 0 to 1 lattice spacings")
    return {"dt": dt, "method": method, "per_cell": per_cell, "flip": flip, "gravity": gravity,
            "density": density, "iterations": iterations, "tolerance": tolerance, "walls": walls,
            "substeps": substeps, "correction": correction, "separation": separation}


def lame(youngs, poisson):
    mu = youngs / (2.0 * (1.0 + poisson))
    lam = youngs * poisson / ((1.0 + poisson) * (1.0 - 2.0 * poisson))
    return mu, lam


def friction_alpha(friction_degrees):
    """The Drucker-Prager cone's slope for a friction angle (Klar et al. 2016)."""
    s = math.sin(math.radians(friction_degrees))
    return math.sqrt(2.0 / 3.0) * 2.0 * s / (3.0 - s)


def material(kind, youngs, poisson, friction=30.0, hardening=10.0, compression=2.5e-2, stretch=7.5e-3):
    """An MLS-MPM material: `elastic` (fixed corotated), `snow` (fixed corotated with the hardening and the
    elastic clamp of Stomakhin et al. 2013) or `sand` (Hencky elasticity with the Drucker-Prager return of
    Klar et al. 2016, friction angle in degrees)."""
    if kind not in MATERIALS:
        raise ValueError(f"material is one of {MATERIALS}")
    if not (youngs > 0.0 and math.isfinite(youngs)):
        raise ValueError("youngs is positive")
    if not 0.0 <= poisson < 0.5:
        raise ValueError("poisson is 0 to below 0.5")
    if kind == "sand" and not 0.0 < friction < 90.0:
        raise ValueError("friction is an angle between 0 and 90 degrees")
    if kind == "snow" and not (hardening >= 0.0 and 0.0 <= compression < 1.0 and stretch >= 0.0):
        raise ValueError("snow needs a non-negative hardening, a compression below 1 and a non-negative stretch")
    mu, lam = lame(youngs, poisson)
    return {"kind": kind, "youngs": youngs, "poisson": poisson, "mu": mu, "lam": lam, "friction": friction,
            "alpha": friction_alpha(friction), "hardening": hardening, "compression": compression,
            "stretch": stretch}


def face_dims(cells, axis):
    return tuple(c + 1 + 2 * PAD if a == axis else c + 2 * PAD for a, c in enumerate(cells))


def _strides(dims):
    s = []
    acc = 1
    for n in dims:
        s.append(acc)
        acc *= n
    return tuple(s), acc


def liquid(cells, h, s, boxes, material=None, max_particles=MAX_PARTICLES):
    """A liquid in a closed box of `cells` cells of size h, filled with particles on a lattice in each box
    ((lo), (hi)) in scene units, at rest at step 0; the particles have a position x, a velocity v, an affine
    velocity C (d x d) and, with an MPM material, a deformation gradient F and the plastic volume Jp."""
    cells = tuple(cells)
    d = len(cells)
    if d not in (2, 3):
        raise ValueError("the grid has two or three axes")
    if any(not isinstance(c, int) or c < 1 for c in cells) or math.prod(cells) > MAX_CELLS:
        raise ValueError("a grid has 1..MAX_CELLS cells")
    if not (h > 0.0 and math.isfinite(h)):
        raise ValueError("the cell size is positive")
    if not 1 <= max_particles <= MAX_PARTICLES:
        raise ValueError(f"maxParticles is 1 to {MAX_PARTICLES}")
    if s["method"] == "mpm" and material is None:
        raise ValueError("the mpm method needs a material")
    k = max(1, int(round(s["per_cell"] ** (1.0 / d))))
    size = tuple(c * h for c in cells)
    xs = []
    for lo, hi in boxes:
        lo, hi = tuple(lo), tuple(hi)
        if len(lo) != d or len(hi) != d or any(a >= b for a, b in zip(lo, hi)):
            raise ValueError("a fill box has a lower corner below its upper corner on every axis")
        if any(a < 0.0 or b > size[i] + 1e-12 for i, (a, b) in enumerate(zip(lo, hi))):
            raise ValueError("a fill box lies inside the domain")
        first = tuple(int(math.floor(a / h + 1e-9)) for a in lo)
        last = tuple(int(math.ceil(b / h - 1e-9)) for b in hi)
        for cell in itertools.product(*(range(f, l) for f, l in zip(first, last))):
            for sub in itertools.product(range(k), repeat=d):
                p = tuple((cell[i] + (sub[i] + 0.5) / k) * h for i in range(d))
                if all(lo[i] <= p[i] <= hi[i] for i in range(d)):
                    xs.append(p)
        if len(xs) > max_particles:
            raise ValueError(f"more than {max_particles} particles")
    n = len(xs)
    liq = {"dim": d, "cells": cells, "h": h, "size": size, "spec": s, "k": k, "x": xs, "x0": list(xs),
           "v": [tuple(0.0 for _ in range(d)) for _ in range(n)], "C": [zeros(d) for _ in range(n)],
           "mass": s["density"] * h ** d / k ** d, "volume0": h ** d / k ** d, "step": 0, "material": material,
           "max_particles": max_particles}
    if material is not None:
        liq["F"] = [identity(d) for _ in range(n)]
        liq["Jp"] = [1.0] * n
    return liq


def _particle_stencils(liq, p):
    """Per axis a of the faces, the (array index, weight, offset) triples of the particle's 3^d nodes: the index
    into the face array, the B-spline weight and x_f - x_p in scene units."""
    d = liq["dim"]
    h = liq["h"]
    u = tuple(c / h for c in p)
    out = []
    for a in range(d):
        dims = face_dims(liq["cells"], a)
        strides, _ = _strides(dims)
        per_axis = []
        for b in range(d):
            base, w = stencil(u[b] if b == a else u[b] - 0.5)
            shift = 0.0 if b == a else 0.5
            per_axis.append(tuple((base + kk + PAD, w[kk], (base + kk + shift) * h - p[b]) for kk in range(3)))
        nodes = []
        for combo in itertools.product(*per_axis):
            weight = 1.0
            index = 0
            offset = []
            for b, (i, w, off) in enumerate(combo):
                weight *= w
                index += i * strides[b]
                offset.append(off)
            if weight > 0.0:
                nodes.append((index, weight, tuple(offset)))
        out.append(nodes)
    return out


# --- rule 3: the transfers -----------------------------------------------------------------------------------


def _stress_term(liq, i):
    """-dt (4/h^2) V0 P F^T of particle i (MLS-MPM), or None for a liquid."""
    m = liq["material"]
    if m is None:
        return None
    f = liq["F"][i]
    if m["kind"] == "sand":
        pft = hencky_kirchhoff(f, m["mu"], m["lam"])
    else:
        mu, lam = m["mu"], m["lam"]
        if m["kind"] == "snow":
            e = math.exp(m["hardening"] * (1.0 - liq["Jp"][i]))
            mu, lam = mu * e, lam * e
        pft = matmul(corotated_stress(f, mu, lam), transpose(f))
    scale = -liq["spec"]["dt"] / liq["spec"]["substeps"] * 4.0 / liq["h"] ** 2 * liq["volume0"]
    return tuple(tuple(x * scale for x in row) for row in pft)


def p2g(liq):
    """Particles to faces: each face gets the mass-weighted velocity of the particles in reach, with the affine
    term C (x_f - x_p) (APIC, Jiang et al. 2015) and, for an MPM material, the stress term (Hu et al. 2018)."""
    d = liq["dim"]
    m = liq["mass"]
    mass = []
    mom = []
    for a in range(d):
        _, n = _strides(face_dims(liq["cells"], a))
        mass.append([0.0] * n)
        mom.append([0.0] * n)
    affine = liq["spec"]["method"] != "flip"
    for i, p in enumerate(liq["x"]):
        v = liq["v"][i]
        c = liq["C"][i]
        q = _stress_term(liq, i)
        rows = []
        for a in range(d):
            row = tuple(m * x for x in c[a]) if affine else tuple(0.0 for _ in range(d))
            if q is not None:
                row = _add(row, q[a])
            rows.append(row)
        for a, nodes in enumerate(_particle_stencils(liq, p)):
            for index, w, off in nodes:
                mass[a][index] += w * m
                mom[a][index] += w * (m * v[a] + _dot(rows[a], off))
    vel = [[mo / ma if ma > 0.0 else 0.0 for mo, ma in zip(mom[a], mass[a])] for a in range(d)]
    return {"mass": mass, "vel": vel}


def interpolate(liq, faces, p):
    """The B-spline interpolation of the face velocities at p."""
    return tuple(sum(w * faces["vel"][a][index] for index, w, _ in nodes)
                 for a, nodes in enumerate(_particle_stencils(liq, p)))


def g2p(liq, old, new):
    """Faces to particles: the PIC velocity and the affine C from the new faces (APIC), or the FLIP blend of the
    particle's velocity plus the faces' change with the PIC velocity; then the particle moves by dt times its
    PIC velocity and is clamped to the box. For an MPM material F becomes (I + dt C) F and the material's
    plasticity applies."""
    d = liq["dim"]
    s = liq["spec"]
    dt = s["dt"] / s["substeps"]
    inv_d = 4.0 / liq["h"] ** 2
    size = liq["size"]
    for i, p in enumerate(liq["x"]):
        stencils = _particle_stencils(liq, p)
        pic = []
        delta = []
        rows = []
        for a, nodes in enumerate(stencils):
            va = 0.0
            da = 0.0
            row = [0.0] * d
            for index, w, off in nodes:
                un = new["vel"][a][index]
                va += w * un
                da += w * (un - old["vel"][a][index])
                for b in range(d):
                    row[b] += w * un * off[b]
            pic.append(va)
            delta.append(da)
            rows.append(tuple(x * inv_d for x in row))
        pic = tuple(pic)
        if s["method"] == "flip":
            r = s["flip"]
            liq["v"][i] = tuple(r * (liq["v"][i][a] + delta[a]) + (1.0 - r) * pic[a] for a in range(d))
            liq["C"][i] = zeros(d)
        else:
            liq["v"][i] = pic
            liq["C"][i] = tuple(rows)
        moved = tuple(min(max(p[a] + dt * pic[a], 0.0), size[a]) for a in range(d))
        liq["x"][i] = moved
        if liq["material"] is not None:
            f = matmul(madd(identity(d), liq["C"][i], dt), liq["F"][i])
            liq["F"][i], liq["Jp"][i] = plasticity(f, liq["Jp"][i], liq["material"])


# --- rule 4: walls and the projection ------------------------------------------------------------------------


def _mirror(j, n):
    if j < 0:
        return -1 - j
    if j >= n:
        return 2 * n - 1 - j
    return j


def enforce_walls(liq, faces):
    """The faces at and beyond a wall normal to it are zero (no through-flow). Slip walls mirror the interior
    face across the wall onto the ghost faces tangential to it; no-slip walls hold every face within one cell
    of the wall at rest (the ghost faces and the first interior layer, the sticky boundary of Stomakhin et al.
    2013), so a liquid or a granular body sticks to them."""
    d = liq["dim"]
    cells = liq["cells"]
    noslip = liq["spec"]["walls"] == "noslip"
    for a in range(d):
        dims = face_dims(cells, a)
        strides, n = _strides(dims)
        vel = faces["vel"][a]
        for flat in range(n):
            idx = [(flat // strides[b]) % dims[b] - PAD for b in range(d)]
            if idx[a] <= 0 or idx[a] >= cells[a]:
                vel[flat] = 0.0
                continue
            if noslip:
                if any(idx[b] < 1 or idx[b] >= cells[b] - 1 for b in range(d) if b != a):
                    vel[flat] = 0.0
                continue
            outside = [b for b in range(d) if b != a and not 0 <= idx[b] < cells[b]]
            if outside:
                src = 0
                for b in range(d):
                    j = _mirror(idx[b], cells[b]) if b in outside else idx[b]
                    src += (j + PAD) * strides[b]
                vel[flat] = vel[src]
    return faces


def face_index(liq, axis, idx):
    """The flat index of the face of `axis` at the integer coordinates idx (face index along the axis, cell
    index along the others; negatives and overflows address the ghost layers)."""
    strides, _ = _strides(face_dims(liq["cells"], axis))
    return sum((j + PAD) * strides[b] for b, j in enumerate(idx))


def cell_index(liq, cell):
    strides, _ = _strides(liq["cells"])
    return sum(j * s for j, s in zip(cell, strides))


def mark(liq):
    """The fluid cells: those holding a particle."""
    n = math.prod(liq["cells"])
    fluid = [False] * n
    for p in liq["x"]:
        cell = tuple(min(int(c // liq["h"]), liq["cells"][a] - 1) for a, c in enumerate(p))
        fluid[cell_index(liq, cell)] = True
    return fluid


def counts(liq):
    n = math.prod(liq["cells"])
    out = [0] * n
    for p in liq["x"]:
        cell = tuple(min(int(c // liq["h"]), liq["cells"][a] - 1) for a, c in enumerate(p))
        out[cell_index(liq, cell)] += 1
    return out


def _cell_faces(liq, cell, a):
    lo = list(cell)
    hi = list(cell)
    hi[a] += 1
    return face_index(liq, a, lo), face_index(liq, a, hi)


def divergence(liq, faces, fluid):
    """The divergence of every cell (zero where not fluid): the outward face velocities over h."""
    d = liq["dim"]
    h = liq["h"]
    out = [0.0] * math.prod(liq["cells"])
    for flat, is_fluid in enumerate(fluid):
        if not is_fluid:
            continue
        cell = _coords(liq, flat)
        div = 0.0
        for a in range(d):
            lo, hi = _cell_faces(liq, cell, a)
            div += faces["vel"][a][hi] - faces["vel"][a][lo]
        out[flat] = div / h
    return out


def _coords(liq, flat):
    out = []
    for n in liq["cells"]:
        out.append(flat % n)
        flat //= n
    return tuple(out)


def project(liq, faces, fluid, dt=None, target=None):
    """Make the fluid cells divergence free, or give them the divergence `target` (per cell, 1/s): solve
    -laplacian q = target - div u over the fluid cells (q = dt p / rho) by Jacobi-preconditioned conjugate
    gradients from q = 0, with the walls as Neumann faces and the empty cells at q = 0, until dt times the RMS
    residual is at most the tolerance; then the faces of fluid cells lose (q_hi - q_lo) / h. Returns
    (iterations, error); reaching the iteration bound raises ProjectionError."""
    s = liq["spec"]
    if dt is None:
        dt = s["dt"] / s["substeps"]
    d = liq["dim"]
    h = liq["h"]
    cells = liq["cells"]
    ids = [flat for flat, f in enumerate(fluid) if f]
    if not ids:
        return 0, 0.0
    where = {flat: k for k, flat in enumerate(ids)}
    n = len(ids)
    strides, _ = _strides(cells)
    neighbours = []
    diagonal = []
    for flat in ids:
        cell = _coords(liq, flat)
        nb = []
        diag_count = 0
        for a in range(d):
            for side in (-1, 1):
                j = cell[a] + side
                if 0 <= j < cells[a]:
                    other = flat + side * strides[a]
                    diag_count += 1
                    if fluid[other]:
                        nb.append(where[other])
        neighbours.append(nb)
        diagonal.append(diag_count / (h * h))
    div = divergence(liq, faces, fluid)
    b = [(target[flat] if target is not None else 0.0) - div[flat] for flat in ids]
    inv_h2 = 1.0 / (h * h)

    def apply(q):
        return [diagonal[k] * q[k] - inv_h2 * sum(q[j] for j in neighbours[k]) for k in range(n)]

    def error(r):
        return dt * math.sqrt(sum(x * x for x in r) / n)

    q = [0.0] * n
    r = list(b)
    err = error(r)
    iterations = 0
    if err > s["tolerance"]:
        z = [r[k] / diagonal[k] for k in range(n)]
        p = list(z)
        rz = sum(r[k] * z[k] for k in range(n))
        while True:
            if iterations >= s["iterations"]:
                raise ProjectionError(f"the projection is at {err:.3e} after {iterations} iterations")
            ap = apply(p)
            pap = sum(p[k] * ap[k] for k in range(n))
            if pap <= 0.0:
                raise ProjectionError("the projection's system is not positive")
            alpha = rz / pap
            q = [q[k] + alpha * p[k] for k in range(n)]
            r = [r[k] - alpha * ap[k] for k in range(n)]
            iterations += 1
            err = error(r)
            if err <= s["tolerance"]:
                break
            z = [r[k] / diagonal[k] for k in range(n)]
            rz_new = sum(r[k] * z[k] for k in range(n))
            beta = rz_new / rz
            rz = rz_new
            p = [z[k] + beta * p[k] for k in range(n)]
        r = [b[k] - x for k, x in enumerate(apply(q))]
        err = error(r)
        if err > 1.01 * s["tolerance"]:
            raise ProjectionError(f"the recomputed error {err:.3e} is above the tolerance")
    for k, flat in enumerate(ids):
        cell = _coords(liq, flat)
        for a in range(d):
            for side in (-1, 1):
                j = cell[a] + side
                if not 0 <= j < cells[a]:
                    continue
                other = flat + side * strides[a]
                q_other = q[where[other]] if fluid[other] else 0.0
                if fluid[other] and side > 0:
                    continue    # that face is updated from the other cell's side (lo side) once
                lo, hi = _cell_faces(liq, cell, a)
                if side < 0:
                    faces["vel"][a][lo] -= (q[k] - q_other) / h
                else:
                    faces["vel"][a][hi] -= (q_other - q[k]) / h
    return iterations, err


def _face_cells(liq, a, idx):
    """The two cells of the face of axis a at idx (None for a cell outside the domain)."""
    lo = list(idx)
    lo[a] -= 1
    out = []
    for cell in (lo, list(idx)):
        if all(0 <= j < n for j, n in zip(cell, liq["cells"])):
            out.append(cell_index(liq, cell))
        else:
            out.append(None)
    return out


def extrapolate(liq, faces, fluid, layers=2):
    """Faces not touching a fluid cell take the mean of their valid face neighbours along the axes, layer by
    layer (a Jacobi sweep per layer, in index order), so the particles near the free surface read projected
    velocities and not the unprojected ones of the air; two layers cover the B-spline's reach."""
    d = liq["dim"]
    cells = liq["cells"]
    for a in range(d):
        dims = face_dims(cells, a)
        strides, n = _strides(dims)
        vel = faces["vel"][a]
        valid = [False] * n
        for flat in range(n):
            idx = [(flat // strides[b]) % dims[b] - PAD for b in range(d)]
            if not (0 <= idx[a] <= cells[a]) or any(not 0 <= idx[b] < cells[b] for b in range(d) if b != a):
                continue
            lo, hi = _face_cells(liq, a, idx)
            valid[flat] = (lo is not None and fluid[lo]) or (hi is not None and fluid[hi])
        for _ in range(layers):
            updates = {}
            for flat in range(n):
                if valid[flat]:
                    continue
                idx = [(flat // strides[b]) % dims[b] for b in range(d)]
                total = 0.0
                count = 0
                for b in range(d):
                    for side in (-1, 1):
                        j = idx[b] + side
                        if 0 <= j < dims[b]:
                            other = flat + side * strides[b]
                            if valid[other]:
                                total += vel[other]
                                count += 1
                if count:
                    updates[flat] = total / count
            for flat, value in updates.items():
                vel[flat] = value
                valid[flat] = True
    return faces


def separate(liq, fraction=None, strength=0.5):
    """Push particles apart when they come within `fraction` of the lattice spacing of each other: each
    particle moves by `strength` times the sum of the shortfalls along the pair directions, computed from the
    positions before the move (Ando, Thurey and Wojtan 2012), so the result is independent of the order."""
    d = liq["dim"]
    if fraction is None:
        fraction = liq["spec"]["separation"]
    if fraction == 0.0:
        return 0
    spacing = liq["h"] / liq["k"]
    d_min = fraction * spacing
    cells = liq["cells"]
    buckets = {}
    keys = []
    for i, p in enumerate(liq["x"]):
        key = tuple(min(int(c // liq["h"]), cells[a] - 1) for a, c in enumerate(p))
        keys.append(key)
        buckets.setdefault(key, []).append(i)
    moves = {}
    for i, p in enumerate(liq["x"]):
        shift = [0.0] * d
        touched = False
        for offset in itertools.product((-1, 0, 1), repeat=d):
            for j in buckets.get(tuple(k + o for k, o in zip(keys[i], offset)), ()):
                if j == i:
                    continue
                diff = _sub(p, liq["x"][j])
                r = _norm(diff)
                if 0.0 < r < d_min:
                    touched = True
                    push = strength * (d_min - r) / r
                    for a in range(d):
                        shift[a] += push * diff[a]
        if touched:
            moves[i] = shift
    for i, shift in moves.items():
        p = liq["x"][i]
        liq["x"][i] = tuple(min(max(p[a] + shift[a], 0.0), liq["size"][a]) for a in range(d))
    return len(moves)


def raises_projection_error(fn):
    try:
        fn()
    except ProjectionError:
        return True
    return False


# --- rule 5: the step ----------------------------------------------------------------------------------------


def apply_gravity(liq, faces, dt):
    """Faces with mass take dt times gravity along -y (axis 1 of the solver)."""
    g = liq["spec"]["gravity"]
    if g == 0.0:
        return faces
    vel = faces["vel"][1]
    for i, m in enumerate(faces["mass"][1]):
        if m > 0.0:
            vel[i] -= g * dt
    return faces


def density_target(liq, dt):
    """The divergence target of the density correction: a cell holding more particles than it was seeded with
    expands by `correction` times its excess fraction per step; a cell holding fewer (the free surface) is not
    contracted. None when the correction is off."""
    c = liq["spec"]["correction"]
    if c == 0.0:
        return None
    d = liq["dim"]
    cells = liq["cells"]
    strides, _ = _strides(cells)
    full = liq["k"] ** d
    n = counts(liq)
    out = [0.0] * len(n)
    for flat, count in enumerate(n):
        if count == 0:
            continue
        cell = _coords(liq, flat)
        interior = True
        for a in range(d):
            for side in (-1, 1):
                j = cell[a] + side
                if 0 <= j < cells[a] and n[flat + side * strides[a]] == 0:
                    interior = False
        if interior:
            out[flat] = c * (count - full) / full / dt
    return out


def substep(liq, dt):
    old = p2g(liq)
    new = {"mass": old["mass"], "vel": [list(v) for v in old["vel"]]}
    apply_gravity(liq, new, dt)
    enforce_walls(liq, new)
    if liq["spec"]["method"] != "mpm":
        fluid = mark(liq)
        project(liq, new, fluid, dt, density_target(liq, dt))
        extrapolate(liq, new, fluid)
        enforce_walls(liq, new)
    g2p(liq, old, new)
    if liq["spec"]["method"] != "mpm":
        separate(liq)


def step(liq):
    s = liq["spec"]
    for _ in range(s["substeps"]):
        substep(liq, s["dt"] / s["substeps"])
    liq["step"] += 1
    return liq


def run(liq, steps):
    if not isinstance(steps, int) or not 0 <= steps <= MAX_STEPS:
        raise ValueError(f"a run has 0 to {MAX_STEPS} steps")
    if liq["step"] + steps > MAX_STEPS:
        raise ValueError(f"a liquid runs at most {MAX_STEPS} steps")
    for _ in range(steps):
        step(liq)
    return liq


def momentum(liq):
    d = liq["dim"]
    m = liq["mass"]
    return tuple(sum(v[a] for v in liq["v"]) * m for a in range(d))


def kinetic_energy(liq):
    return 0.5 * liq["mass"] * sum(_dot(v, v) for v in liq["v"])


def volume(liq):
    """The liquid's volume estimated from the particles per cell: each cell counts min(n, k^d) / k^d cells."""
    full = liq["k"] ** liq["dim"]
    return sum(min(n, full) for n in counts(liq)) / full * liq["h"] ** liq["dim"]


def density_drift(liq):
    """The bulk density drift: the mean particle count of the interior fluid cells (those whose axis
    neighbours inside the domain all hold particles) over the seeded count, minus 1; None without interior."""
    d = liq["dim"]
    cells = liq["cells"]
    strides, _ = _strides(cells)
    c = counts(liq)
    total = 0
    interior = 0
    for flat, n in enumerate(c):
        if n == 0:
            continue
        cell = _coords(liq, flat)
        ok = True
        for a in range(d):
            for side in (-1, 1):
                j = cell[a] + side
                if 0 <= j < cells[a] and c[flat + side * strides[a]] == 0:
                    ok = False
        if ok:
            total += n
            interior += 1
    if interior == 0:
        return None
    return total / interior / liq["k"] ** d - 1.0


def seek_check(steps):
    s = spec(1.0 / 120.0, per_cell=4)
    boxes = [((0.0, 0.0), (1.0, 2.0))]
    a = run(liquid((12, 12), 0.25, s, boxes), steps)
    b = run(run(liquid((12, 12), 0.25, s, boxes), steps // 2), steps - steps // 2)
    return a["x"] == b["x"] and a["v"] == b["v"]


@functools.lru_cache(maxsize=None)
def hydrostatic_test(steps=60):
    """A layer at rest under gravity stays at rest: the largest particle displacement, the largest speed and
    the volume and bulk density drifts after the steps."""
    s = spec(1.0 / 120.0, per_cell=4, tolerance=1e-12, iterations=2000)
    liq = liquid((8, 12), 0.25, s, [((0.0, 0.0), (2.0, 1.5))])
    v0 = volume(liq)
    run(liq, steps)
    drift = max(_norm(_sub(p, q)) for p, q in zip(liq["x"], liq["x0"]))
    speed = max(_norm(v) for v in liq["v"])
    return {"drift": drift, "speed": speed, "volume_drift": (volume(liq) - v0) / v0,
            "density_drift": density_drift(liq), "steps": steps}


# --- rule 6: the dam break -----------------------------------------------------------------------------------


def nondimensional_time(t, a, g):
    """Martin and Moyce's T = n t sqrt(g / a) with n^2 = 2 (the column is 2a high and a wide)."""
    return t * math.sqrt(2.0 * g / a)


def front_position(xs, a):
    """The surge front Z = x / a: the farthest particle along x over the column's width."""
    return max(p[0] for p in xs) / a


def crossing_time(samples, z):
    """The first time at which the sampled (T, Z) curve reaches z, interpolated linearly; None if never."""
    for k in range(1, len(samples)):
        t0, z0 = samples[k - 1]
        t1, z1 = samples[k]
        if z1 >= z > z0:
            return t0 + (z - z0) / (z1 - z0) * (t1 - t0)
        if z0 >= z:
            return t0
    if samples and samples[0][1] >= z:
        return samples[0][0]
    return None


@functools.lru_cache(maxsize=None)
def dam_break(cells_per_a=8, width_a=4.5, height_a=2.5, dt=1.0 / 120.0, t_max_nd=3.4, method="apic",
              walls="slip"):
    """The n^2 = 2 column of Martin and Moyce: a column a wide and 2a high at the left wall of a channel, released
    at rest; the front Z is sampled every step against T, and the times at which it crosses the three measured
    positions are compared to the measurements."""
    a = 1.0
    h = a / cells_per_a
    nx = int(round(width_a * cells_per_a))
    ny = int(round(height_a * cells_per_a))
    s = spec(dt, method=method, per_cell=4, walls=walls, tolerance=1e-7, iterations=2000)
    liq = liquid((nx, ny), h, s, [((0.0, 0.0), (a, 2.0 * a))])
    g = s["gravity"]
    v0 = volume(liq)
    samples = [(0.0, front_position(liq["x"], a))]
    steps = 0
    while nondimensional_time(steps * dt, a, g) < t_max_nd:
        step(liq)
        steps += 1
        samples.append((nondimensional_time(steps * dt, a, g), front_position(liq["x"], a)))
    front_times = tuple(crossing_time(samples, z) for z, _ in MARTIN_MOYCE)
    errors = [abs(t - t_exp) / t_exp if t is not None else float("inf") for t, (_, t_exp) in zip(front_times, MARTIN_MOYCE)]
    return {"a": a, "h": h, "cells": (nx, ny), "steps": steps, "particles": len(liq["x0"]),
            "particles_at_end": len(liq["x"]), "front_times": front_times, "front_error": max(errors),
            "volume_drift": (volume(liq) - v0) / v0, "density_drift": density_drift(liq),
            "samples": tuple(samples), "liquid": liq}


# --- rule 7: MLS-MPM materials -------------------------------------------------------------------------------


def corotated_stress(f, mu, lam):
    """The first Piola-Kirchhoff stress of the fixed corotated model: 2 mu (F - R) + lam (J - 1) J F^-T."""
    d = len(f)
    r, _ = polar(f)
    j = determinant(f)
    f_inv_t = transpose(inverse(f))
    return tuple(tuple(2.0 * mu * (f[i][k] - r[i][k]) + lam * (j - 1.0) * j * f_inv_t[i][k] for k in range(d))
                 for i in range(d))


def corotated_energy(f, mu, lam):
    _, sigma, _ = svd(f)
    j = determinant(f)
    return mu * sum((x - 1.0) ** 2 for x in sigma) + 0.5 * lam * (j - 1.0) ** 2


def inverse(m):
    d = len(m)
    det = determinant(m)
    if det == 0.0:
        raise ValueError("the matrix is singular")
    if d == 2:
        return ((m[1][1] / det, -m[0][1] / det), (-m[1][0] / det, m[0][0] / det))
    c = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            minor = [[m[r][s] for s in range(3) if s != j] for r in range(3) if r != i]
            c[j][i] = ((-1) ** (i + j)) * (minor[0][0] * minor[1][1] - minor[0][1] * minor[1][0]) / det
    return tuple(tuple(row) for row in c)


def hencky_kirchhoff(f, mu, lam):
    """The Kirchhoff stress P F^T of the Hencky (log-strain) elasticity: U (2 mu eps + lam tr eps) U^T."""
    d = len(f)
    u, sigma, _ = svd(f)
    eps = [math.log(max(x, 1e-300)) for x in sigma]
    t = sum(eps)
    core = diag(tuple(2.0 * mu * e + lam * t for e in eps))
    return matmul(matmul(u, core), transpose(u))


def yield_value(sigma, mu, lam, alpha):
    """The Drucker-Prager yield function of the singular values: |dev eps| + alpha (d lam + 2 mu) / (2 mu) tr eps."""
    d = len(sigma)
    eps = [math.log(max(x, 1e-300)) for x in sigma]
    t = sum(eps)
    dev = [e - t / d for e in eps]
    return math.sqrt(sum(x * x for x in dev)) + alpha * (d * lam + 2.0 * mu) / (2.0 * mu) * t


def on_yield_surface(sigma, mu, lam, alpha, tol=1e-9):
    return abs(yield_value(sigma, mu, lam, alpha)) <= tol


def drucker_prager(sigma, mu, lam, alpha):
    """The return mapping of Klar et al. 2016 on the singular values of the elastic deformation: a state in
    tension (tr eps > 0) returns to the origin; a state inside the cone stays; a state outside is projected
    along the deviatoric direction onto it. Returns (sigma, delta_gamma)."""
    d = len(sigma)
    eps = [math.log(max(x, 1e-300)) for x in sigma]
    t = sum(eps)
    dev = [e - t / d for e in eps]
    dev_norm = math.sqrt(sum(x * x for x in dev))
    if dev_norm == 0.0 or t > 0.0:
        if t > 0.0:
            return tuple(1.0 for _ in sigma), math.sqrt(sum(e * e for e in eps))
        return sigma, 0.0
    delta = dev_norm + alpha * (d * lam + 2.0 * mu) / (2.0 * mu) * t
    if delta <= 0.0:
        return sigma, 0.0
    new = [e - delta * x / dev_norm for e, x in zip(eps, dev)]
    return tuple(math.exp(e) for e in new), delta


def plasticity(f, jp, m):
    """The material's plastic update of a trial deformation gradient: elastic keeps it; snow clamps the singular
    values to [1 - compression, 1 + stretch] and moves the rest into Jp; sand applies the return mapping."""
    if m["kind"] == "elastic":
        return f, jp
    u, sigma, v = svd(f)
    if m["kind"] == "snow":
        clamped = tuple(min(max(x, 1.0 - m["compression"]), 1.0 + m["stretch"]) for x in sigma)
        j_trial = math.prod(sigma)
        j_new = math.prod(clamped)
        jp = jp * j_trial / j_new if j_new != 0.0 else jp
        return matmul(matmul(u, diag(clamped)), transpose(v)), jp
    mapped, delta = drucker_prager(sigma, m["mu"], m["lam"], m["alpha"])
    return matmul(matmul(u, diag(mapped)), transpose(v)), jp + delta


def plastic_flow(liq):
    """The accumulated plastic measure of an MPM body: the sum of Jp - 1 over the particles for sand."""
    return sum(jp - 1.0 for jp in liq["Jp"])


@functools.lru_cache(maxsize=None)
def sand_collapse(steps=180, friction=30.0):
    """A column of sand 1 wide and 1 high on a no-slip floor collapses: its runout (the farthest particle from
    the column's centre over the initial half-width), its height over the initial height, the slope of the
    pile's flank (from the peak to the toe, the last column at a tenth of the peak) and the plastic flow."""
    h = 0.1
    s = spec(1.0 / 120.0, method="mpm", per_cell=4, walls="noslip", density=1500.0)
    m = material("sand", 3.0e4, 0.3, friction=friction)
    liq = liquid((60, 20), h, s, [((2.5, 0.0), (3.5, 1.0))], material=m)
    run(liq, steps)
    centre = 3.0
    runout = max(abs(p[0] - centre) for p in liq["x"]) / 0.5
    height = max(p[1] for p in liq["x"]) / 1.0
    # the surface profile: the highest particle per column of cells, from the peak to the right toe
    columns = {}
    for p in liq["x"]:
        i = int(p[0] // h)
        columns[i] = max(columns.get(i, 0.0), p[1])
    peak_i = max(columns, key=lambda i: columns[i])
    toe_i = max(i for i in columns if columns[i] >= 0.1 * columns[peak_i])
    slope = (columns[peak_i] - columns[toe_i]) / ((toe_i - peak_i) * h) if toe_i > peak_i else 0.0
    return {"runout": runout, "height": height, "slope": slope, "friction": friction, "plastic": plastic_flow(liq),
            "steps": steps, "particles": len(liq["x"])}


# --- rule 8: whitewater --------------------------------------------------------------------------------------


def radial_kernel(r, h):
    """W(r, h) = 1 - r / h for r < h, else 0 (Ihmsen et al. 2012)."""
    return 1.0 - r / h if r < h else 0.0


def clamp_potential(value, lo, hi):
    """Phi(I, tau_min, tau_max) = (min(I, tau_max) - min(I, tau_min)) / (tau_max - tau_min)."""
    return (min(value, hi) - min(value, lo)) / (hi - lo)


def trapped_air(i, x, v, h):
    """v_diff of particle i: the sum over its neighbours of |v_ij| (1 - v^_ij . x^_ij) W(|x_ij|, h)."""
    total = 0.0
    for j, xj in enumerate(x):
        if j == i:
            continue
        xij = _sub(x[i], xj)
        r = _norm(xij)
        if r >= h or r == 0.0:
            continue
        vij = _sub(v[i], v[j])
        speed = _norm(vij)
        if speed == 0.0:
            continue
        total += speed * (1.0 - _dot(_scale(vij, 1.0 / speed), _scale(xij, 1.0 / r))) * radial_kernel(r, h)
    return total


def wave_crest(i, x, n, v, h):
    """kappa_i Delta_i of particle i: the curvature sum (1 - n^_i . n^_j) W over the neighbours below its
    tangent plane, times 1 when the particle moves along its normal (v^ . n^ >= 0.6)."""
    ni = n[i]
    vi = v[i]
    speed = _norm(vi)
    if speed == 0.0 or _dot(_scale(vi, 1.0 / speed), ni) < CREST_ALIGNMENT:
        return 0.0
    total = 0.0
    for j, xj in enumerate(x):
        if j == i:
            continue
        xji = _sub(xj, x[i])
        r = _norm(xji)
        if r >= h or r == 0.0 or _dot(xji, ni) >= 0.0:
            continue
        total += (1.0 - _dot(ni, n[j])) * radial_kernel(r, h)
    return total


def kinetic(mass, v):
    return 0.5 * mass * _dot(v, v)


def classify(neighbours):
    if neighbours < SPRAY_BELOW:
        return "spray"
    if neighbours > FOAM_ABOVE:
        return "foam"
    return "bubble"


def whitewater_spec(trapped_air, wave_crest, kinetic, rate_air=1000.0, rate_crest=1000.0, lifetime=2.0,
                    max_particles=10000, seed=0, radius=0.05):
    """The thresholds (tau_min, tau_max) of the three potentials, the generation rates of the two sources, the
    lifetime, the particle bound, the seed and the spawn radius."""
    for name, pair in (("trappedAir", trapped_air), ("waveCrest", wave_crest), ("kineticEnergy", kinetic)):
        if len(pair) != 2 or not pair[0] < pair[1] or pair[0] < 0.0:
            raise ValueError(f"{name} thresholds are 0 <= min < max")
    if rate_air < 0.0 or rate_crest < 0.0:
        raise ValueError("rates are non-negative")
    if not lifetime > 0.0:
        raise ValueError("lifetime is positive")
    if not isinstance(max_particles, int) or not 1 <= max_particles <= 1000000:
        raise ValueError("maxParticles is 1 to 1000000")
    if not radius > 0.0:
        raise ValueError("radius is positive")
    return {"trapped_air": tuple(trapped_air), "wave_crest": tuple(wave_crest), "kinetic": tuple(kinetic),
            "rate_air": rate_air, "rate_crest": rate_crest, "lifetime": lifetime, "max_particles": max_particles,
            "seed": seed, "radius": radius}


def emission_count(i_ta, i_wc, i_k, s, dt, carry):
    """The diffuse particles a liquid particle emits in a step: floor((I_ta k_ta + I_wc k_wc) I_k dt + carry),
    the fraction carried to the next step (the potentials already clamped to 0..1)."""
    n = (i_ta * s["rate_air"] + i_wc * s["rate_crest"]) * i_k * dt + carry
    count = int(math.floor(n))
    return count, n - count


def _u01(seed, channel, index):
    return _streams.H(seed, channel, index) / float(1 << 64)


def diffuse_position(x, direction, r, seed, index):
    """A diffuse particle's spawn position: on the cylinder of radius r around the direction through x, at the
    angle, radius and height drawn from the D24 hash H(seed, channel, index) with channels 0, 1 and 2."""
    e1 = _unit(_sub((1.0, 0.0, 0.0), _scale(direction, direction[0]))) if abs(direction[0]) < 0.9 else \
        _unit(_sub((0.0, 1.0, 0.0), _scale(direction, direction[1])))
    e2 = (direction[1] * e1[2] - direction[2] * e1[1], direction[2] * e1[0] - direction[0] * e1[2],
          direction[0] * e1[1] - direction[1] * e1[0])
    theta = 2.0 * math.pi * _u01(seed, 0, index)
    rad = r * math.sqrt(_u01(seed, 1, index))
    height = r * _u01(seed, 2, index)
    return tuple(x[a] + rad * (math.cos(theta) * e1[a] + math.sin(theta) * e2[a]) + height * direction[a]
                 for a in range(3))


def surface_normals(x, h):
    """n_i = the unit vector from the kernel-weighted neighbour centroid to x_i (zero deep inside)."""
    out = []
    for i, xi in enumerate(x):
        acc = (0.0, 0.0, 0.0)
        for j, xj in enumerate(x):
            if j == i:
                continue
            r = _norm(_sub(xi, xj))
            if r < h:
                acc = _add(acc, _scale(_sub(xi, xj), radial_kernel(r, h)))
        out.append(_unit(acc) if _norm(acc) > 1e-9 else (0.0, 0.0, 0.0))
    return out


def neighbour_count(p, x, h):
    return sum(1 for xj in x if _norm(_sub(p, xj)) < h)


def emit(x, v, mass, s, dt, h, carries=None, index0=0):
    """One step of whitewater generation over a liquid's particles: the emitted diffuse particles (position,
    velocity, class, lifetime) and the carries. Classes come from the liquid neighbours of the spawn point."""
    n = surface_normals(x, h)
    carries = list(carries) if carries is not None else [0.0] * len(x)
    out = []
    index = index0
    for i, xi in enumerate(x):
        i_ta = clamp_potential(trapped_air(i, x, v, h), *s["trapped_air"])
        i_wc = clamp_potential(wave_crest(i, x, n, v, h), *s["wave_crest"])
        i_k = clamp_potential(kinetic(mass, v[i]), *s["kinetic"])
        count, carries[i] = emission_count(i_ta, i_wc, i_k, s, dt, carries[i])
        direction = _unit(v[i]) if _norm(v[i]) > 0.0 else (0.0, 1.0, 0.0)
        for _ in range(count):
            if len(out) >= s["max_particles"]:
                return out, carries, index
            p = diffuse_position(xi, direction, s["radius"], s["seed"], index)
            index += 1
            out.append((p, v[i], classify(neighbour_count(p, x, h)), s["lifetime"]))
    return out, carries, index


@functools.lru_cache(maxsize=None)
def whitewater_test():
    """Two blocks of liquid particles crashing into each other (trapped air inside, crests on top) emit diffuse
    particles of all three classes, the same on a second call."""
    spacing = 0.1
    h = 2.0 * spacing
    x = []
    v = []
    for i in range(6):
        for j in range(4):
            for k in range(4):
                x.append((i * spacing, j * spacing, k * spacing))
                v.append((2.0, 0.0, 0.0) if i < 3 else (-2.0, 0.0, 0.0))
    top = [i for i, p in enumerate(x) if p[1] >= 3 * spacing - 1e-9]
    for i in top:
        v[i] = (v[i][0] * 0.2, 3.0, 0.0)
    mass = 1000.0 * spacing ** 3
    s = whitewater_spec(trapped_air=(0.5, 8.0), wave_crest=(0.2, 2.0), kinetic=(0.0, 1.0), rate_air=400.0,
                        rate_crest=400.0, max_particles=1000, seed=3, radius=0.1)
    first, _, _ = emit(x, v, mass, s, 1.0 / 60.0, h)
    second, _, _ = emit(x, v, mass, s, 1.0 / 60.0, h)
    classes = {"spray": 0, "bubble": 0, "foam": 0}
    for _, _, c, _ in first:
        classes[c] += 1
    return {"total": len(first), "first": first, "second": second, **classes}


# --- rule 9: the surface -------------------------------------------------------------------------------------


def isotropic_kernel(s):
    """k(s) = max(0, 1 - s^2)^3 (Zhu and Bridson 2005)."""
    return max(0.0, 1.0 - s * s) ** 3


def level_set_at(p, x, r, h):
    """phi(p) = |p - x_bar| - r with x_bar the kernel-weighted average of the particle centres within h; h when
    no particle is within reach."""
    total = 0.0
    acc = tuple(0.0 for _ in p)
    for xi in x:
        w = isotropic_kernel(_norm(_sub(p, xi)) / h)
        if w > 0.0:
            total += w
            acc = _add(acc, _scale(xi, w))
    if total == 0.0:
        return h
    return _norm(_sub(p, _scale(acc, 1.0 / total))) - r


def surface_mesh(x, r, h, box, res):
    """The marching-tetrahedra mesh of the level set on the box at res cells per axis (scalar3d draft)."""
    return _scalar3d.isosurface(lambda a, b, c: level_set_at((a, b, c), x, r, h), box, res)


@functools.lru_cache(maxsize=None)
def surface_test():
    """A ball of particles of radius 1 on a lattice of spacing 0.25: the level set is negative at the centre and
    positive outside, its zero set sits at the ball's radius, and the mesh is a closed sphere of its volume."""
    spacing = 0.25
    radius = 1.0
    x = []
    for i in range(-4, 5):
        for j in range(-4, 5):
            for k in range(-4, 5):
                p = ((i + 0.5) * spacing, (j + 0.5) * spacing, (k + 0.5) * spacing)
                if _norm(p) <= radius - spacing / 2.0:
                    x.append(p)
    r = spacing
    h = 2.0 * spacing
    inside = level_set_at((0.0, 0.0, 0.0), x, r, h)
    outside = level_set_at((2.0, 0.0, 0.0), x, r, h)
    vertices, faces = surface_mesh(x, r, h, (-1.5, 1.5, -1.5, 1.5, -1.5, 1.5), 24)
    mean_radius = sum(_norm(v) for v in vertices) / len(vertices)
    vol = _scalar3d.mesh_volume(vertices, faces)
    return {"particles": len(x), "inside": inside, "outside": outside,
            "radius_error": (mean_radius - radius) / h, "closed": _scalar3d.is_closed(vertices, faces),
            "euler": _scalar3d.euler(vertices, faces), "volume_error": (vol - 4.0 / 3.0 * math.pi * radius ** 3)
            / (4.0 / 3.0 * math.pi * radius ** 3), "vertices": len(vertices), "faces": len(faces)}


# --- the table -----------------------------------------------------------------------------------------------


def _r(x, n=4):
    return round(x, n)


def transfer_test():
    """The affine field v = A x (a rotation) is recovered exactly by the APIC transfers away from the walls."""
    s = spec(1.0 / 120.0, per_cell=4)
    liq = liquid((12, 12), 0.25, s, [((0.75, 0.75), (2.25, 2.25))])
    A = ((0.0, 1.0), (-1.0, 0.0))
    liq["v"] = [matvec(A, p) for p in liq["x"]]
    liq["C"] = [A for _ in liq["x"]]
    faces = p2g(liq)
    g2p(liq, faces, faces)
    inner = [i for i, p in enumerate(liq["x0"]) if 1.25 < p[0] < 1.75 and 1.25 < p[1] < 1.75]
    err_v = max(_norm(_sub(liq["v"][i], matvec(A, liq["x0"][i]))) for i in inner)
    err_c = max(abs(liq["C"][i][r][c] - A[r][c]) for i in inner for r in range(2) for c in range(2))
    return len(inner), err_v < 1e-12, err_c < 1e-12


def projection_test():
    s = spec(1.0 / 120.0, per_cell=4, tolerance=1e-9, iterations=500)
    liq = liquid((8, 8), 0.25, s, [((0.5, 0.5), (1.5, 1.5))])
    liq["v"] = [(p[0] - 1.0, p[1] - 1.0) for p in liq["x"]]
    faces = p2g(liq)
    fluid = mark(liq)
    before = max(abs(x) for x in divergence(liq, faces, fluid))
    iterations, err = project(liq, faces, fluid)
    after = max(abs(x) for x in divergence(liq, faces, fluid))
    return sum(fluid), _r(before, 3), iterations, err < 1e-9, after < 1e-7


def projection_error_test():
    """The expanding block with a tolerance of 1e-12 and one iteration raises ProjectionError."""
    s = spec(1.0 / 120.0, per_cell=4, tolerance=1e-12, iterations=1)
    liq = liquid((8, 8), 0.25, s, [((0.5, 0.5), (1.5, 1.5))])
    liq["v"] = [(p[0] - 1.0, p[1] - 1.0) for p in liq["x"]]
    faces = p2g(liq)
    return raises_projection_error(lambda: project(liq, faces, mark(liq)))


def momentum_test():
    s = spec(1.0 / 120.0, per_cell=4, method="mpm", gravity=0.0)
    body = liquid((12, 12), 0.25, s, [((1.0, 1.0), (2.0, 2.0))], material=material("elastic", 2000.0, 0.3))
    body["v"] = [(0.4, -0.3) for _ in body["x"]]
    before = momentum(body)
    run(body, 10)
    after = momentum(body)
    f_err = max(abs(f[r][c] - (1.0 if r == c else 0.0)) for f in body["F"] for r in range(2) for c in range(2))
    return _norm(_sub(before, after)) < 1e-9, f_err < 1e-9


def rest_test():
    s = spec(1.0 / 120.0, per_cell=4, method="mpm", gravity=0.0)
    body = liquid((12, 12), 0.25, s, [((1.0, 1.0), (2.0, 2.0))], material=material("elastic", 2000.0, 0.3))
    run(body, 20)
    return body["x"] == body["x0"]


def whitewater_summary():
    r = whitewater_test()
    return r["total"], r["spray"] > 0, r["bubble"] > 0, r["foam"] > 0, r["first"] == r["second"]


def dam_break_summary():
    r = dam_break()
    return tuple(_r(t, 3) for t in r["front_times"]), _r(r["front_error"], 3), _r(r["volume_drift"], 4)


def dam_break_resolution():
    """The front error at 6 and 10 cells per a with APIC, and at 8 with FLIP."""
    return (_r(dam_break(cells_per_a=6)["front_error"], 3), _r(dam_break(cells_per_a=10)["front_error"], 3),
            _r(dam_break(method="flip")["front_error"], 3))


def hydrostatic_summary():
    r = hydrostatic_test()
    return r["drift"] < 1e-9, r["speed"] < 1e-9, r["volume_drift"]


def sand_summary():
    r = sand_collapse()
    return _r(r["runout"], 3), _r(r["height"], 3), _r(r["slope"], 3), r["slope"] <= math.tan(math.radians(30.0)) * 1.05, r["plastic"] > 0.0


def repose_test():
    """The pile's flank rises with the friction angle and stays below its tangent."""
    slopes = tuple(sand_collapse(friction=f)["slope"] for f in (15.0, 30.0, 45.0))
    return tuple(_r(x, 3) for x in slopes), slopes[0] < slopes[1] < slopes[2], all(
        x <= math.tan(math.radians(f)) for x, f in zip(slopes, (15.0, 30.0, 45.0)))


def surface_summary():
    r = surface_test()
    return r["particles"], r["inside"] < 0.0, r["outside"] > 0.0, _r(r["radius_error"], 3), r["closed"], r["euler"], _r(r["volume_error"], 3)


TABLE = (
    ("bspline-centre", "bspline(0.0)", "0.75"),
    ("bspline-half", "bspline(0.5)", "0.5"),
    ("bspline-one", "bspline(1.0)", "0.125"),
    ("bspline-support", "bspline(1.5)", "0.0"),
    ("partition", "round(sum(weights(0.37)), 12)", "1.0"),
    ("second-moment", "round(sum(w * (stencil(0.37)[0] + k - 0.37) ** 2 for k, w in enumerate(weights(0.37))), 12)", "0.25"),
    ("seeding", "len(liquid((8, 6), 0.25, spec(1 / 120, per_cell=4), [((0.0, 0.0), (0.5, 0.5))])['x'])", "16"),
    ("seeding-3d", "len(liquid((4, 4, 4), 0.5, spec(1 / 120, per_cell=8), [((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))])['x'])", "64"),
    ("mass", "liquid((8, 6), 0.25, spec(1 / 120, per_cell=4), [((0.0, 0.0), (0.5, 0.5))])['mass']", "15.625"),
    ("affine-transfer", "transfer_test()", "(16, True, True)"),
    ("projection", "projection_test()", "(16, 1.96, 3, True, True)"),
    ("projection-error", "projection_error_test()", "True"),
    ("hydrostatic", "hydrostatic_summary()", "(True, True, 0.0)"),
    ("seek", "seek_check(12)", "True"),
    ("nondimensional", "round(nondimensional_time(1.0, 1.0, 9.81), 6)", "4.429447"),
    ("crossing", "crossing_time([(0.0, 1.0), (1.0, 2.0), (2.0, 4.0)], 3.0)", "1.5"),
    ("dam-break", "dam_break_summary()", "((1.726, 2.363, 2.95), 0.058, -0.0547)"),
    ("dam-break-steps", "dam_break()['steps']", "93"),
    ("dam-break-resolution", "dam_break_resolution()", "(0.018, 0.088, 0.035)"),
    ("polar", "round(max(abs(matmul(*polar(((1.2, 0.3), (-0.1, 0.9))))[r][c] - ((1.2, 0.3), (-0.1, 0.9))[r][c]) for r in range(2) for c in range(2)), 12)", "0.0"),
    ("svd-3d", "round(max(abs(matmul(matmul(svd(F)[0], diag(svd(F)[1])), transpose(svd(F)[2]))[r][c] - F[r][c]) for F in (((1.1, 0.2, 0.0), (0.0, 0.9, 0.1), (0.3, 0.0, 1.0)),) for r in range(3) for c in range(3)), 12)", "0.0"),
    ("corotated-rest", "corotated_stress(identity(2), *lame(1000.0, 0.3))", "((0.0, 0.0), (0.0, 0.0))"),
    ("corotated-stretch", "round(corotated_stress(((1.1, 0.0), (0.0, 1.0)), *lame(1000.0, 0.3))[0][0], 4)", "134.6154"),
    ("friction-alpha", "round(friction_alpha(30.0), 6)", "0.326599"),
    ("drucker-inside", "drucker_prager((0.95, 0.95), *lame(1000.0, 0.3), friction_alpha(30.0))[1]", "0.0"),
    ("drucker-projected", "on_yield_surface(drucker_prager((1.2, 0.8), *lame(1000.0, 0.3), friction_alpha(30.0))[0], *lame(1000.0, 0.3), friction_alpha(30.0))", "True"),
    ("drucker-tension", "drucker_prager((1.1, 1.05), *lame(1000.0, 0.3), friction_alpha(30.0))[0]", "(1.0, 1.0)"),
    ("momentum", "momentum_test()", "(True, True)"),
    ("rest", "rest_test()", "True"),
    ("sand", "sand_summary()", "(2.945, 0.517, 0.257, True, True)"),
    ("repose", "repose_test()", "((0.1, 0.257, 0.43), True, True)"),
    ("clamp", "(clamp_potential(0.0, 1.0, 3.0), clamp_potential(2.0, 1.0, 3.0), clamp_potential(9.0, 1.0, 3.0))", "(0.0, 0.5, 1.0)"),
    ("trapped-air", "(trapped_air(0, ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0)), ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0)), 1.0), trapped_air(0, ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0)), ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)), 1.0))", "(0.0, 2.0)"),
    ("wave-crest", "round(wave_crest(0, ((0.0, 0.0, 0.0), (-0.5, -0.3, 0.0), (0.5, -0.3, 0.0)), ((0.0, 1.0, 0.0), (-0.6, 0.8, 0.0), (0.6, 0.8, 0.0)), ((0.0, 1.0, 0.0),) * 3, 1.0), 6)", "0.166762"),
    ("classes", "(classify(5), classify(6), classify(20), classify(21))", "('spray', 'bubble', 'bubble', 'foam')"),
    ("emission", "emission_count(1.0, 1.0, 0.5, whitewater_spec((5.0, 20.0), (2.0, 8.0), (5.0, 50.0), rate_air=200.0, rate_crest=400.0), 1 / 120, 0.0)", "(2, 0.5)"),
    ("whitewater", "whitewater_summary()", "(300, True, True, True, True)"),
    ("level-set", "(level_set_at((0.0, 0.0, 0.0), ((0.0, 0.0, 0.0),), 0.5, 1.0), round(level_set_at((0.3, 0.0, 0.0), ((0.0, 0.0, 0.0),), 0.5, 1.0), 12), level_set_at((5.0, 0.0, 0.0), ((0.0, 0.0, 0.0),), 0.5, 1.0))", "(-0.5, -0.2, 1.0)"),
    ("surface", "surface_summary()", "(160, True, True, -0.037, True, 2, -0.081)"),
    ("bounds", "(MAX_PARTICLES, MAX_CELLS, MAX_STEPS, MAX_ITERATIONS, MAX_SUBSTEPS, MAX_PER_CELL, SPRAY_BELOW, FOAM_ABOVE)", "(1048576, 2097152, 65536, 10000, 64, 64, 6, 20)"),
)


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["__builtins__"] = {"round": round, "tuple": tuple, "len": len, "sorted": sorted, "min": min, "max": max,
                         "abs": abs, "range": range, "list": list, "set": set, "dict": dict, "True": True,
                         "False": False, "None": None, "any": any, "all": all, "int": int, "float": float,
                         "zip": zip, "sum": sum, "slice": slice, "ValueError": ValueError, "enumerate": enumerate}
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
