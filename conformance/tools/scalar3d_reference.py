#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add scalar 3D: isosurfaces and transfer-function volumes"
(srep/srep-0000-scalar3d.md), MF6 of SREP 12.

Standard library only. The rules of the SREP's Semantics section are the functions below, in its order:
the cell and its six tetrahedra (rule 1), the crossing of an edge (rule 2), the triangles of a tetrahedron
and their orientation (rule 3), the welded mesh (rule 4), its measures (rule 5), normals (rule 6), grid
functions (rule 7), transfer functions on a medium (rules 8 and 9), the march (rule 10) and the bounds
(rule 11). `main()` prints the SREP's numeric table; `tests/test_scalar3d.py` checks both.
"""
import functools
import math

MAX_RESOLUTION = 1024          # cells along one axis of an isosurface grid
MAX_CELLS = 1 << 24            # cells of one isosurface grid
MAX_STOPS = 256                # stops of one transfer function
MAX_STEPS = 65536              # steps of one march (medium/@maxSteps)

# The eight corners of a cell, bit order x, y, z: corner c has x bit (c & 1) ^ ((c >> 1) & 1), as in
# Lorensen and Cline (1987): 0 (0,0,0), 1 (1,0,0), 2 (1,1,0), 3 (0,1,0), 4 (0,0,1), 5 (1,0,1), 6 (1,1,1), 7 (0,1,1).
CORNERS = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))
# The six tetrahedra of a cell, all sharing the main diagonal 0-6 (Doi and Koide 1991); every cell face is
# split by the diagonal from its lowest corner to its highest, so neighbouring cells agree on their faces.
TETS = ((0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6))

UNIT = (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
BOX = (-1.25, 1.25, -1.25, 1.25, -1.25, 1.25)
RAMP = ((0.0, (0.0, 0.0, 1.0), 0.0), (1.0, (1.0, 0.0, 0.0), 1.0))


def sphere(x, y, z):
    """The unit sphere as f = 0: x² + y² + z² − 1."""
    return x * x + y * y + z * z - 1.0


def plane_x(x, y, z):
    """The plane x = 1/2 as f = 0."""
    return x - 0.5


# ------------------------------------------------------------------------------------ vectors

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    if n == 0.0:
        raise ValueError("zero vector has no direction")
    return (a[0] / n, a[1] / n, a[2] / n)


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_box(box):
    if len(box) != 6 or not all(_finite(v) for v in box):
        raise ValueError("a box is six finite numbers x0, x1, y0, y1, z0, z1")
    if not (box[0] < box[1] and box[2] < box[3] and box[4] < box[5]):
        raise ValueError("each box minimum is below its maximum")


# ------------------------------------------------------------------------------------ rule 1: the cell

def cell_corners(box):
    """The eight corner points of a box, in CORNERS order."""
    _check_box(box)
    x0, x1, y0, y1, z0, z1 = box
    return tuple((x1 if cx else x0, y1 if cy else y0, z1 if cz else z0) for cx, cy, cz in CORNERS)


def tet_volume(a, b, c, d):
    """The (unsigned) volume of a tetrahedron."""
    return abs(_dot(_sub(b, a), _cross(_sub(c, a), _sub(d, a)))) / 6.0


# ------------------------------------------------------------------------------------ rule 2: an edge

def edge_point(a, b, fa, fb, level):
    """The point of the edge a-b where the linear interpolation of fa and fb reaches the level.

    The edge must straddle the level, a corner at the level counting as on it; the point is then taken
    from a, so the two cells that share the edge share its crossing exactly.
    """
    da = fa - level
    db = fb - level
    if da * db > 0.0:
        raise ValueError("the edge does not cross the level")
    if fa == fb:
        return a
    t = da / (fa - fb)
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2]))


# ------------------------------------------------------------------------------------ rule 3: a tetrahedron

def tet_gradient(points, values):
    """The gradient of the linear function through four (point, value) pairs."""
    p0 = points[0]
    e = [_sub(points[i], p0) for i in (1, 2, 3)]
    d = [values[i] - values[0] for i in (1, 2, 3)]
    det = _dot(e[0], _cross(e[1], e[2]))
    if det == 0.0:
        raise ValueError("the tetrahedron is flat")
    # Cramer's rule on E g = d with E's rows the edges.
    g = []
    for axis in range(3):
        m = [list(row) for row in e]
        for r in range(3):
            m[r][axis] = d[r]
        g.append(_dot(m[0], _cross(m[1], m[2])) / det)
    return tuple(g)


def _tet_cut(ids, points, values, level):
    """The triangles of the level set inside one tetrahedron, as triples of (edge key, point).

    ids are the global corner ids (the edge key is the sorted pair), points and values the corners.
    """
    inside = [v >= level for v in values]
    k = sum(inside)
    if k == 0 or k == 4:
        return ()
    ins = [i for i in range(4) if inside[i]]
    outs = [i for i in range(4) if not inside[i]]

    def P(i, o):
        key = (ids[i], ids[o]) if ids[i] < ids[o] else (ids[o], ids[i])
        return (key, edge_point(points[i], points[o], values[i], values[o], level))

    if k == 1:
        i = ins[0]
        tris = [(P(i, outs[0]), P(i, outs[1]), P(i, outs[2]))]
    elif k == 3:
        o = outs[0]
        tris = [(P(ins[0], o), P(ins[1], o), P(ins[2], o))]
    else:
        i1, i2 = ins
        o1, o2 = outs
        q = (P(i1, o1), P(i1, o2), P(i2, o2), P(i2, o1))
        tris = [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
    grad = tet_gradient(points, values)
    out = []
    for tri in tris:
        pts = tuple(p for _, p in tri)
        n = _cross(_sub(pts[1], pts[0]), _sub(pts[2], pts[0]))
        if _norm(n) == 0.0:
            continue
        if _dot(n, grad) < 0.0:
            tri = (tri[0], tri[2], tri[1])
        out.append(tri)
    return tuple(out)


def tet_triangles(points, values, level):
    """The triangles (triples of points) of the level set inside one tetrahedron, facing the rising side."""
    return tuple(tuple(p for _, p in tri) for tri in _tet_cut((0, 1, 2, 3), points, values, level))


# ------------------------------------------------------------------------------------ rule 4: the mesh

def _resolution(res):
    if isinstance(res, int) and not isinstance(res, bool):
        res = (res, res, res)
    if len(res) != 3 or not all(isinstance(r, int) and not isinstance(r, bool) for r in res):
        raise ValueError("the resolution is an integer or three integers")
    if not all(1 <= r <= MAX_RESOLUTION for r in res):
        raise ValueError(f"the resolution is 1 to {MAX_RESOLUTION} cells per axis")
    if res[0] * res[1] * res[2] > MAX_CELLS:
        raise ValueError(f"the grid has more than {MAX_CELLS} cells")
    return tuple(res)


def isosurface(f, box, res, level=0.0):
    """The welded triangle mesh of f = level inside the box on a res grid: (vertices, faces).

    f is sampled once per grid corner (a non-finite sample is an error); cells are cut tetrahedron by
    tetrahedron in slice order (z outermost, then y, then x); a crossing is computed from its inside corner,
    so every tetrahedron on an edge gets the same point, and vertices are welded by that point (a crossing
    that lands on a corner is one vertex however many edges reach it); faces are index triples facing the
    side where f rises; zero-area triangles are dropped.
    """
    _check_box(box)
    nx, ny, nz = _resolution(res)
    if not _finite(level):
        raise ValueError("the level is a finite number")
    x0, x1, y0, y1, z0, z1 = box
    xs = [x0 + (x1 - x0) * i / nx for i in range(nx + 1)]
    ys = [y0 + (y1 - y0) * j / ny for j in range(ny + 1)]
    zs = [z0 + (z1 - z0) * k / nz for k in range(nz + 1)]
    sy = nz + 1
    sx = (ny + 1) * sy
    values = []
    for x in xs:
        for y in ys:
            for z in zs:
                v = f(x, y, z)
                if not _finite(v):
                    raise ValueError(f"f is not finite at ({x}, {y}, {z})")
                values.append(float(v))
    offsets = tuple(cx * sx + cy * sy + cz for cx, cy, cz in CORNERS)
    vertices = []
    index = {}
    faces = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                base = i * sx + j * sy + k
                ids = tuple(base + o for o in offsets)
                vals = tuple(values[c] for c in ids)
                if all(v >= level for v in vals) or all(v < level for v in vals):
                    continue
                pts = tuple((xs[i + cx], ys[j + cy], zs[k + cz]) for cx, cy, cz in CORNERS)
                for tet in TETS:
                    cut = _tet_cut(tuple(ids[t] for t in tet), tuple(pts[t] for t in tet),
                                   tuple(vals[t] for t in tet), level)
                    for tri in cut:
                        face = []
                        for _, p in tri:
                            n = index.get(p)
                            if n is None:
                                n = len(vertices)
                                index[p] = n
                                vertices.append(p)
                            face.append(n)
                        faces.append(tuple(face))
    return (tuple(vertices), tuple(faces))


@functools.lru_cache(maxsize=None)
def sphere_mesh(res):
    """The unit sphere's mesh on BOX at res cells per axis (cached)."""
    return isosurface(sphere, BOX, res)


# ------------------------------------------------------------------------------------ rule 5: measures

def triangle_area(tri):
    return _norm(_cross(_sub(tri[1], tri[0]), _sub(tri[2], tri[0]))) / 2.0


def triangle_normal(tri):
    """The unit normal of a triangle by the right-hand rule."""
    return _unit(_cross(_sub(tri[1], tri[0]), _sub(tri[2], tri[0])))


def mesh_area(vertices, faces):
    return sum(triangle_area((vertices[a], vertices[b], vertices[c])) for a, b, c in faces)


def mesh_volume(vertices, faces):
    """The signed volume enclosed by a closed mesh (positive when its faces point outward)."""
    return sum(_dot(vertices[a], _cross(vertices[b], vertices[c])) for a, b, c in faces) / 6.0


def _edges(faces):
    edges = {}
    for a, b, c in faces:
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            edges.setdefault(key, []).append(u < v)
    return edges


def euler(vertices, faces):
    """V − E + F of a mesh (2 for a closed surface of genus 0, 1 for a disk)."""
    return len(vertices) - len(_edges(faces)) + len(faces)


def is_closed(vertices, faces):
    """Whether every edge is used by exactly two faces, once in each direction."""
    return all(len(d) == 2 and d[0] != d[1] for d in _edges(faces).values())


def convergence_order(coarse_error, fine_error):
    """The observed order log2(e_h / e_{h/2}) between two resolutions."""
    if coarse_error <= 0.0 or fine_error <= 0.0:
        raise ValueError("errors must be positive")
    return math.log2(coarse_error / fine_error)


# ------------------------------------------------------------------------------------ rule 6: normals

def vertex_normals(vertices, faces):
    """Unit normals, the area-weighted mean of each vertex's face normals (normals="smooth")."""
    sums = [(0.0, 0.0, 0.0)] * len(vertices)
    for a, b, c in faces:
        n = _cross(_sub(vertices[b], vertices[a]), _sub(vertices[c], vertices[a]))
        for v in (a, b, c):
            s = sums[v]
            sums[v] = (s[0] + n[0], s[1] + n[1], s[2] + n[2])
    return tuple(_unit(s) for s in sums)


def gradient_normal(f, p, h):
    """The unit gradient of f at p by central differences of step h (normals="gradient")."""
    if not (_finite(h) and h > 0.0):
        raise ValueError("the step is positive")
    g = []
    for axis in range(3):
        hi = list(p)
        lo = list(p)
        hi[axis] += h
        lo[axis] -= h
        g.append((f(*hi) - f(*lo)) / (2.0 * h))
    return _unit(tuple(g))


# ------------------------------------------------------------------------------------ rule 7: grids

def grid_function(values, dims, box):
    """A trilinear interpolant of a dense grid of dims (nx, ny, nz) samples over the box.

    values are indexed i + nx·(j + ny·k); coordinates are clamped to the box; every dim is at least 2.
    """
    _check_box(box)
    if len(dims) != 3 or not all(isinstance(d, int) and not isinstance(d, bool) and d >= 2 for d in dims):
        raise ValueError("dims are three integers of at least 2")
    nx, ny, nz = dims
    if len(values) != nx * ny * nz:
        raise ValueError("the grid has nx * ny * nz values")
    if not all(_finite(v) for v in values):
        raise ValueError("grid values are finite")
    values = tuple(float(v) for v in values)
    x0, x1, y0, y1, z0, z1 = box

    def axis(u, u0, u1, n):
        t = (u - u0) / (u1 - u0) * (n - 1)
        t = min(max(t, 0.0), float(n - 1))
        i = min(int(t), n - 2)
        return i, t - i

    def f(x, y, z):
        i, tx = axis(x, x0, x1, nx)
        j, ty = axis(y, y0, y1, ny)
        k, tz = axis(z, z0, z1, nz)

        def at(di, dj, dk):
            return values[(i + di) + nx * ((j + dj) + ny * (k + dk))]

        c00 = at(0, 0, 0) * (1 - tx) + at(1, 0, 0) * tx
        c10 = at(0, 1, 0) * (1 - tx) + at(1, 1, 0) * tx
        c01 = at(0, 0, 1) * (1 - tx) + at(1, 0, 1) * tx
        c11 = at(0, 1, 1) * (1 - tx) + at(1, 1, 1) * tx
        c0 = c00 * (1 - ty) + c10 * ty
        c1 = c01 * (1 - ty) + c11 * ty
        return c0 * (1 - tz) + c1 * tz

    return f


# ------------------------------------------------------------------------------------ rules 8 and 9: transfer

def validate_stops(stops):
    """Stops are 2 to MAX_STOPS (at, (r, g, b), opacity) with strictly rising at and components in [0, 1]."""
    if len(stops) < 2:
        raise ValueError("a transfer function has at least two stops")
    if len(stops) > MAX_STOPS:
        raise ValueError(f"a transfer function has at most {MAX_STOPS} stops")
    last = None
    for at, color, opacity in stops:
        if not _finite(at):
            raise ValueError("a stop's position is finite")
        if last is not None and at <= last:
            raise ValueError("stops rise strictly")
        last = at
        if len(color) != 3 or not all(_finite(c) and 0.0 <= c <= 1.0 for c in color):
            raise ValueError("a stop's colour has three components in [0, 1]")
        if not (_finite(opacity) and 0.0 <= opacity <= 1.0):
            raise ValueError("a stop's opacity is in [0, 1]")
    return tuple(stops)


def transfer(stops, s):
    """The (colour, opacity) of a scalar through the stops: piecewise linear, clamped to the end stops."""
    stops = validate_stops(stops)
    if s <= stops[0][0]:
        return (tuple(stops[0][1]), stops[0][2])
    if s >= stops[-1][0]:
        return (tuple(stops[-1][1]), stops[-1][2])
    for (a0, c0, o0), (a1, c1, o1) in zip(stops, stops[1:]):
        if a0 <= s < a1:
            t = (s - a0) / (a1 - a0)
            return (tuple(x + (y - x) * t for x, y in zip(c0, c1)), o0 + (o1 - o0) * t)
    raise ValueError("unreachable")


def medium_sample(stops, s, extinction=1.0, density_scale=1.0, emission_scale=0.0):
    """A medium sample under a transfer function: (extinction coefficient, emitted radiance).

    The stop's opacity replaces the density channel (times densityScale), the extinction is that density
    times the medium's extinction, and the stop's colour times the density and emissionScale is emitted.
    """
    color, opacity = transfer(stops, s)
    density = opacity * density_scale
    return (density * extinction, tuple(c * density * emission_scale for c in color))


# ------------------------------------------------------------------------------------ rule 10: the march

def transmittance(sigma, length):
    """Beer–Lambert: exp(−σ·L)."""
    return math.exp(-sigma * length)


def march_transmittance(stops, scalar_at, t0, t1, steps, extinction=1.0, density_scale=1.0):
    """Transmittance along a ray from t0 to t1 by the midpoint rule in `steps` equal steps."""
    if not (isinstance(steps, int) and not isinstance(steps, bool) and 1 <= steps <= MAX_STEPS):
        raise ValueError(f"steps is 1 to {MAX_STEPS}")
    if not (_finite(t0) and _finite(t1) and t1 > t0):
        raise ValueError("the march runs forward")
    step = (t1 - t0) / steps
    depth = 0.0
    for n in range(steps):
        sigma, _ = medium_sample(stops, scalar_at(t0 + (n + 0.5) * step), extinction, density_scale)
        depth += sigma * step
    return math.exp(-depth)


# ------------------------------------------------------------------------------------ the table

TABLE = (
    ("six tetrahedra on the diagonal", "(len(TETS), all(t[0] == 0 and t[3] == 6 for t in TETS))", "(6, True)"),
    ("tetrahedra fill the cell", "round(sum(tet_volume(*(cell_corners(UNIT)[i] for i in t)) for t in TETS), 12)", "1.0"),
    ("cell corners", "cell_corners((0.0, 2.0, 0.0, 4.0, 0.0, 8.0))[6]", "(2.0, 4.0, 8.0)"),
    ("edge crossing", "edge_point((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), -1.0, 3.0, 0.0)", "(0.5, 0.0, 0.0)"),
    ("edge crossing at a level", "edge_point((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), -1.0, 1.0, 0.5)", "(1.5, 0.0, 0.0)"),
    ("corner at the level", "edge_point((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 0.0, 3.0, 0.0)", "(0.0, 0.0, 0.0)"),
    ("one corner inside", "len(tet_triangles(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (1.0, -1.0, -1.0, -1.0), 0.0))", "1"),
    ("two corners inside", "len(tet_triangles(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (1.0, 1.0, -1.0, -1.0), 0.0))", "2"),
    ("three corners inside", "len(tet_triangles(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (-1.0, 1.0, 1.0, 1.0), 0.0))", "1"),
    ("no crossing", "tet_triangles(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (1.0, 1.0, 1.0, 1.0), 0.0)", "()"),
    ("the triangle of one corner", "sorted(tet_triangles(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (1.0, -1.0, -1.0, -1.0), 0.0)[0])", "[(0.0, 0.0, 0.5), (0.0, 0.5, 0.0), (0.5, 0.0, 0.0)]"),
    ("tetrahedron gradient", "tet_gradient(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (7.0, 9.0, 4.0, 7.5))", "(2.0, -3.0, 0.5)"),
    ("triangles face the rising side", "all(sum(a * b for a, b in zip(triangle_normal(tri), tet_gradient(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (1.0, 1.0, -1.0, -1.0)))) > 0.0 for tri in tet_triangles(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (1.0, 1.0, -1.0, -1.0), 0.0))", "True"),
    ("plane in the unit cell", "(len(isosurface(plane_x, UNIT, 1)[0]), len(isosurface(plane_x, UNIT, 1)[1]), round(mesh_area(*isosurface(plane_x, UNIT, 1)), 12))", "(9, 8, 1.0)"),
    ("plane is a disk", "euler(*isosurface(plane_x, UNIT, 1))", "1"),
    ("plane at any resolution", "tuple(round(mesh_area(*isosurface(plane_x, UNIT, r)), 12) for r in (1, 2, 3))", "(1.0, 1.0, 1.0)"),
    ("surface on a grid line", "(len(isosurface(plane_x, UNIT, (2, 1, 3))[1]), round(mesh_area(*isosurface(plane_x, UNIT, (2, 1, 3))), 12))", "(6, 1.0)"),
    ("level shifts the surface", "all(abs(v[0] - 0.25) < 1e-12 for v in isosurface(lambda x, y, z: x, UNIT, 2, level=0.25)[0])", "True"),
    ("diagonal plane", "round(mesh_area(*isosurface(lambda x, y, z: x + y + z - 1.0, UNIT, 1)), 12)", "round(math.sqrt(3.0) / 2.0, 12)"),
    ("sphere is closed", "(euler(*sphere_mesh(6)), is_closed(*sphere_mesh(6)))", "(2, True)"),
    ("sphere faces outward", "mesh_volume(*sphere_mesh(6)) > 0.0", "True"),
    ("sphere areas", "tuple(round(mesh_area(*sphere_mesh(r)), 6) for r in (6, 12, 24))", "(11.718454, 12.331032, 12.509223)"),
    ("sphere area errors fall", "tuple(round(abs(mesh_area(*sphere_mesh(r)) - 4.0 * math.pi), 6) for r in (6, 12, 24))", "(0.847916, 0.235339, 0.057147)"),
    ("sphere area order", "tuple(round(convergence_order(a, b), 2) for a, b in ((abs(mesh_area(*sphere_mesh(6)) - 4.0 * math.pi), abs(mesh_area(*sphere_mesh(12)) - 4.0 * math.pi)), (abs(mesh_area(*sphere_mesh(12)) - 4.0 * math.pi), abs(mesh_area(*sphere_mesh(24)) - 4.0 * math.pi))))", "(1.85, 2.04)"),
    ("sphere volume errors fall", "tuple(round(abs(mesh_volume(*sphere_mesh(r)) - 4.0 * math.pi / 3.0), 6) for r in (6, 12, 24))", "(0.513729, 0.13833, 0.034184)"),
    ("mesh is a function", "isosurface(sphere, BOX, 6) == sphere_mesh(6)", "True"),
    ("frame alone equals frame played", "[isosurface(sphere, BOX, 4, level=l) for l in (-0.5, 0.0, 0.5)][2] == isosurface(sphere, BOX, 4, level=0.5)", "True"),
    ("vertex normals are unit", "all(abs(math.sqrt(sum(c * c for c in n)) - 1.0) < 1e-12 for n in vertex_normals(*sphere_mesh(6)))", "True"),
    ("vertex normals point out", "min(sum(a * b for a, b in zip(v, n)) for v, n in zip(sphere_mesh(12)[0], vertex_normals(*sphere_mesh(12)))) > 0.9", "True"),
    ("gradient normal", "tuple(round(c, 9) for c in gradient_normal(sphere, (0.6, 0.0, 0.8), 1e-3))", "(0.6, 0.0, 0.8)"),
    ("trilinear corners", "(grid_function(tuple(float(i) for i in range(8)), (2, 2, 2), UNIT)(1.0, 0.0, 0.0), grid_function(tuple(float(i) for i in range(8)), (2, 2, 2), UNIT)(0.0, 1.0, 0.0), grid_function(tuple(float(i) for i in range(8)), (2, 2, 2), UNIT)(0.0, 0.0, 1.0))", "(1.0, 2.0, 4.0)"),
    ("trilinear centre", "grid_function(tuple(float(i) for i in range(8)), (2, 2, 2), UNIT)(0.5, 0.5, 0.5)", "3.5"),
    ("trilinear clamps", "grid_function(tuple(float(i) for i in range(8)), (2, 2, 2), UNIT)(2.0, 2.0, 2.0)", "7.0"),
    ("grid ramp isosurface", "round(mesh_area(*isosurface(grid_function(tuple(float(i % 3) / 2.0 for i in range(12)), (3, 2, 2), UNIT), UNIT, (2, 1, 1), level=0.25)), 12)", "1.0"),
    ("transfer interpolates", "transfer(RAMP, 0.25)", "((0.25, 0.0, 0.75), 0.25)"),
    ("transfer clamps", "(transfer(RAMP, -3.0), transfer(RAMP, 7.0))", "(((0.0, 0.0, 1.0), 0.0), ((1.0, 0.0, 0.0), 1.0))"),
    ("transfer is piecewise linear", "transfer(((0.0, (0.0, 0.0, 0.0), 0.0), (0.5, (1.0, 1.0, 1.0), 1.0), (1.0, (0.0, 0.0, 0.0), 0.0)), 0.75)", "((0.5, 0.5, 0.5), 0.5)"),
    ("medium sample", "medium_sample(RAMP, 0.25, extinction=2.0, density_scale=3.0, emission_scale=4.0)", "(1.5, (0.75, 0.0, 2.25))"),
    ("beer lambert", "round(transmittance(0.5, 2.0), 12)", "round(math.exp(-1.0), 12)"),
    ("one step of a constant medium", "round(march_transmittance(((0.0, (0.0, 0.0, 0.0), 0.0), (1.0, (0.0, 0.0, 0.0), 1.0)), lambda t: 0.5, 0.0, 2.0, 1), 12)", "round(math.exp(-1.0), 12)"),
    ("the march converges", "abs(march_transmittance(((0.0, (0.0, 0.0, 0.0), 0.0), (1.0, (0.0, 0.0, 0.0), 1.0)), lambda t: t * t, 0.0, 1.0, 64) - math.exp(-1.0 / 3.0)) < abs(march_transmittance(((0.0, (0.0, 0.0, 0.0), 0.0), (1.0, (0.0, 0.0, 0.0), 1.0)), lambda t: t * t, 0.0, 1.0, 4) - math.exp(-1.0 / 3.0))", "True"),
    ("bounds", "(MAX_RESOLUTION, MAX_CELLS, MAX_STOPS, MAX_STEPS)", "(1024, 16777216, 256, 65536)"),
)


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["__builtins__"] = {"round": round, "tuple": tuple, "len": len, "sorted": sorted, "min": min, "max": max,
                         "abs": abs, "range": range, "list": list, "set": set, "dict": dict, "True": True,
                         "False": False, "None": None, "any": any, "all": all, "int": int, "float": float,
                         "zip": zip, "sum": sum, "ValueError": ValueError}
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
