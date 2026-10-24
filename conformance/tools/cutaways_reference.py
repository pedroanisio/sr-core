"""Reference implementation of the draft SREP "Add cutaways, exploded views and surface flow to 3D objects"
(srep/srep-0000-cutaways.md; S5 of SREP 12, SRC-41).

Standard library only. Meshes are tuples of triangles, each a tuple of three points (x, y, z) in object
space, wound counter-clockwise seen from outside. The module gives:

- section planes: a plane keeps the half-space behind its normal, every triangle is clipped by
  Sutherland-Hodgman with crossing points computed once per mesh edge, the cut's boundary loops are the
  on-plane edges that no second kept polygon cancels, and the cap is their ear-clipping triangulation with
  holes bridged, so the cut mesh of a closed mesh is closed and every cap vertex lies on the plane;
- hatching of a cap: lines centred between spacings, clipped to the loops by the even-odd rule;
- exploded views: parts displaced from the assembly centre in proportion to the amount (radial), along an
  axis, or by dense rank of their distance, so amount 0 is the identity exactly;
- flow lines over a surface: the field's tangent part integrated by classical Runge-Kutta with every stage
  projected to the surface, ending at a stagnation point, a reversal, a closure or the step bound, and
  evenly spaced families by the Jobard-Lefer seeding;
- `main()` prints the draft's numeric table.
"""
import math

MAX_SECTIONS = 8
MAX_TRIANGLES = 4_194_304
MAX_PARTS = 4096
MAX_HATCH = 100_000
MAX_STEPS = 1_000_000
MAX_LINES = 1_000_000

MODES = ("radial", "axis", "rank")
KEEPS = ("back", "front")


class CutawayError(ValueError):
    """A document value the draft rejects, or a construction that cannot be completed."""


# ------------------------------------------------------------------------------------ vectors


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    if n == 0.0:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _finite(p):
    return all(math.isfinite(c) for c in p)


# ------------------------------------------------------------------------------------ meshes


def box(size=(1.0, 1.0, 1.0), centre=(0.0, 0.0, 0.0)):
    """A closed box of the given size about the centre: 12 outward triangles."""
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    cx, cy, cz = centre
    p = {}
    for i in range(8):
        p[i] = (cx + (hx if i & 1 else -hx), cy + (hy if i & 2 else -hy), cz + (hz if i & 4 else -hz))
    quads = ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5))
    tris = []
    for a, b, c, d in quads:
        tris.append((p[a], p[b], p[c]))
        tris.append((p[a], p[c], p[d]))
    return tuple(tris)


def icosphere(radius=1.0, subdivisions=2):
    """The icosahedron subdivided `subdivisions` times, every vertex on the sphere of the radius."""
    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
             (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
             (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11),
             (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    # Rotate so that an axis of the icosahedron is the z axis: the vertex 0 becomes the north pole.
    pts = [_unit(v) for v in verts]
    pole = pts[0]
    axis = _unit(_cross(pole, (0.0, 0.0, 1.0)))
    ang = math.acos(max(-1.0, min(1.0, _dot(pole, (0.0, 0.0, 1.0)))))
    pts = [_rotate(p, axis, ang) for p in pts]
    pts = [(p[0] * radius, p[1] * radius, p[2] * radius) for p in pts]
    for _ in range(subdivisions):
        cache = {}

        def mid(i, j):
            key = (min(i, j), max(i, j))
            if key not in cache:
                a, b = pts[i], pts[j]
                m = _unit(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2))
                pts.append((m[0] * radius, m[1] * radius, m[2] * radius))
                cache[key] = len(pts) - 1
            return cache[key]

        new = []
        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            new += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new
    return tuple((pts[a], pts[b], pts[c]) for a, b, c in faces)


def _rotate(p, axis, angle):
    c, s = math.cos(angle), math.sin(angle)
    k = axis
    return _add(_add(_mul(p, c), _mul(_cross(k, p), s)), _mul(k, _dot(k, p) * (1 - c)))


def _turn(k, n):
    """(cos, sin) of k/n turns, exact at the quarter turns."""
    k %= n
    if (4 * k) % n == 0:
        q = (4 * k) // n
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[q]
    a = 2 * math.pi * k / n
    return (math.cos(a), math.sin(a))


def cylinder(radius=1.0, height=1.0, segments=32):
    """A closed cylinder along z, from -height/2 to height/2, with fanned caps."""
    h = height / 2
    ring = [(radius * c, radius * s) for c, s in (_turn(i, segments) for i in range(segments))]
    tris = []
    for i in range(segments):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % segments]
        a, b, c, d = (x0, y0, -h), (x1, y1, -h), (x1, y1, h), (x0, y0, h)
        tris += [(a, b, c), (a, c, d)]
        tris.append(((0.0, 0.0, h), d, c))
        tris.append(((0.0, 0.0, -h), b, a))
    return tuple(tris)


def torus(major=1.0, minor=0.25, around=32, across=16):
    """A closed torus about z of major and minor radii."""
    def pt(i, j):
        (cu, su), (cv, sv) = _turn(i, around), _turn(j, across)
        r = major + minor * cv
        return (r * cu, r * su, minor * sv)

    tris = []
    for i in range(around):
        for j in range(across):
            a, b = pt(i, j), pt(i + 1, j)
            c, d = pt(i + 1, j + 1), pt(i, j + 1)
            tris += [(a, b, c), (a, c, d)]
    return tuple(tris)


def triangle_normal(tri):
    return _unit(_cross(_sub(tri[1], tri[0]), _sub(tri[2], tri[0])))


def area(mesh):
    return sum(_norm(_cross(_sub(b, a), _sub(c, a))) / 2 for a, b, c in mesh)


def volume(mesh):
    """Signed volume by the divergence theorem (positive for outward winding)."""
    return sum(_dot(a, _cross(b, c)) for a, b, c in mesh) / 6


def bounds(mesh):
    xs = [p[0] for t in mesh for p in t]
    ys = [p[1] for t in mesh for p in t]
    zs = [p[2] for t in mesh for p in t]
    if not xs:
        raise CutawayError("an empty mesh has no bounds")
    return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def centre(mesh):
    lo, hi = bounds(mesh)
    return tuple((a + b) / 2 for a, b in zip(lo, hi))


def closed(mesh):
    """True when every directed edge appears once and its reverse once (a 2-manifold without boundary)."""
    edges = {}
    for tri in mesh:
        for i in range(3):
            e = (tri[i], tri[(i + 1) % 3])
            if e in edges:
                return False
            edges[e] = True
    return all((b, a) in edges for a, b in edges)


# ------------------------------------------------------------------------------------ section planes


def plane(point, normal, offset=0.0, keep="back"):
    """A section plane: `point` on it, `normal` pointing at the removed material, moved by `offset` along
    the normal. `keep="front"` flips it (rule 1)."""
    n = _norm(normal)
    if n == 0.0 or not _finite(normal) or not _finite(point) or not math.isfinite(offset):
        raise CutawayError("a section plane needs a finite point and a nonzero normal")
    if keep not in KEEPS:
        raise CutawayError("keep is one of back, front")
    unit = (normal[0] / n, normal[1] / n, normal[2] / n)
    if keep == "front":
        unit = _mul(unit, -1.0)
        offset = -offset
    return {"point": tuple(float(c) for c in point), "normal": unit, "offset": float(offset)}


def signed_distance(pl, p):
    """Positive on the removed side (rule 1)."""
    return _dot(_sub(p, pl["point"]), pl["normal"]) - pl["offset"]


def _crossing(p, q, dp, dq):
    """The point of the edge p-q where the signed distance is zero, computed in a canonical order so both
    triangles of the edge get the identical point."""
    if q < p:
        p, q, dp, dq = q, p, dq, dp
    t = dp / (dp - dq)
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, p[2] + (q[2] - p[2]) * t)


def _clip_triangle(tri, pl, eps=0.0):
    """The kept polygon of a triangle as (point, on_plane) pairs; a vertex within `eps` of the plane counts
    as on it."""
    d = [signed_distance(pl, p) for p in tri]
    d = [0.0 if abs(x) <= eps else x for x in d]
    if all(x == 0.0 for x in d):
        # A triangle lying in the plane is the solid's own face there: kept when it faces the removed side.
        if _dot(_cross(_sub(tri[1], tri[0]), _sub(tri[2], tri[0])), pl["normal"]) > 0.0:
            return [(p, True) for p in tri]
        return []
    if all(x <= 0.0 for x in d):
        return [(p, x == 0.0) for p, x in zip(tri, d)]
    if all(x > 0.0 for x in d):
        return []
    out = []
    for i in range(3):
        p, q = tri[i], tri[(i + 1) % 3]
        dp, dq = d[i], d[(i + 1) % 3]
        if dp <= 0.0:
            out.append((p, dp == 0.0))
        if (dp < 0.0 < dq) or (dq < 0.0 < dp):
            out.append((_crossing(p, q, dp, dq), True))
    return out


def _fan(points):
    tris = []
    for i in range(1, len(points) - 1):
        a, b, c = points[0], points[i], points[i + 1]
        if a == b or b == c or a == c or _cross(_sub(b, a), _sub(c, a)) == (0.0, 0.0, 0.0):
            continue
        tris.append((a, b, c))
    return tris


def _basis(normal):
    """An orthonormal (U, V) in the plane with U x V = normal; U is x for the z normal."""
    comps = [abs(normal[0]), abs(normal[1]), abs(normal[2])]
    i = comps.index(min(comps))
    axis = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)][i]
    v = _unit(_cross(normal, axis))
    u = _cross(v, normal)
    return u, v


def _uv(pl, p, basis):
    d = _sub(p, pl["point"])
    return (_dot(d, basis[0]), _dot(d, basis[1]))


def _clip_mesh(mesh, pl):
    """Clip a mesh by one plane: the kept triangles and the on-plane edges, as a dict in which an edge
    that two kept polygons share in opposite directions has cancelled."""
    kept = []
    edges = {}
    eps = _snap(mesh)
    for tri in mesh:
        poly = _clip_triangle(tri, pl, eps)
        if len(poly) < 3:
            continue
        kept += _fan([p for p, _ in poly])
        for i in range(len(poly)):
            (a, on_a), (b, on_b) = poly[i], poly[(i + 1) % len(poly)]
            if on_a and on_b and a != b:
                _add_edge(edges, a, b)
    return tuple(kept), edges


def _snap(mesh):
    """The plane tolerance: 10^-12 of the mesh's diagonal (rule 1)."""
    if not mesh:
        return 0.0
    lo, hi = bounds(mesh)
    return 1e-12 * _norm(_sub(hi, lo))


def _add_edge(edges, a, b):
    if (b, a) in edges:
        del edges[(b, a)]
    else:
        edges[(a, b)] = True


def _loops(edges):
    """Chain the surviving on-plane edges into loops; the wall traverses them one way, the cap the other,
    so every loop is reversed."""
    nxt = {}
    for a, b in edges:
        nxt.setdefault(a, []).append(b)
    for a in nxt:
        nxt[a].sort()
    loops = []
    for start in sorted(nxt):
        if not nxt[start]:
            continue
        loop = [start]
        cur = start
        while True:
            cands = nxt.get(cur)
            if not cands:
                break
            cur = cands.pop(0)
            if cur == start:
                break
            loop.append(cur)
        if cur == start and len(loop) >= 3:
            loop.reverse()
            loops.append(tuple(loop))
    return tuple(loops)


def _cut_once(mesh, pl):
    kept, edges = _clip_mesh(mesh, pl)
    return kept, _loops(edges)


def loop_area(loop, pl):
    """Signed area of a loop in the plane: positive when it winds with the normal."""
    basis = _basis(pl["normal"])
    uv = [_uv(pl, p, basis) for p in loop]
    s = 0.0
    for i in range(len(uv)):
        (u0, v0), (u1, v1) = uv[i], uv[(i + 1) % len(uv)]
        s += u0 * v1 - u1 * v0
    return s / 2


def cap_area(loops, pl):
    return sum(loop_area(loop, pl) for loop in loops)


def _inside_2d(pt, poly):
    """Even-odd point in polygon (2-D)."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xi:
                inside = not inside
    return inside


def _in_triangle_closed(p, a, b, c):
    def side(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])

    s1, s2, s3 = side(a, b, p), side(b, c, p), side(c, a, p)
    return s1 >= 0.0 and s2 >= 0.0 and s3 >= 0.0


def _bridge(outer, hole):
    """Splice a hole (clockwise) into the outer polygon (counter-clockwise) by Eberly's visible-vertex rule;
    the polygons are lists of (uv, index)."""
    mi = max(range(len(hole)), key=lambda i: (hole[i][0][0], -hole[i][0][1]))
    m = hole[mi][0]
    best = None
    n = len(outer)
    for i in range(n):
        (a, _), (b, _) = outer[i], outer[(i + 1) % n]
        if (a[1] <= m[1] < b[1]) or (b[1] <= m[1] < a[1]):
            if a[1] == b[1]:
                continue
            x = a[0] + (m[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x >= m[0] and (best is None or x < best[0]):
                best = (x, i)
    if best is None:
        raise CutawayError("a cap hole lies outside every outer loop")
    x, i = best
    a, b = outer[i][0], outer[(i + 1) % n][0]
    pi = i if a[0] > b[0] else (i + 1) % n
    p = outer[pi][0]
    inter = (x, m[1])
    choice = pi
    best_angle = None
    # The ray may hit the outer loop at a vertex; otherwise a reflex vertex inside the triangle
    # (m, inter, p) blocks the view, and the one of least angle is the bridge end.
    for j in (() if inter == p else range(n)):
        q = outer[j][0]
        if q in (m, p, inter):
            continue
        prev, nxt = outer[j - 1][0], outer[(j + 1) % n][0]
        reflex = (q[0] - prev[0]) * (nxt[1] - q[1]) - (q[1] - prev[1]) * (nxt[0] - q[0]) < 0.0
        if not reflex:
            continue
        if _in_triangle_closed(q, m, inter, p) or _in_triangle_closed(q, m, p, inter):
            ang = math.atan2(abs(q[1] - m[1]), q[0] - m[0])
            dist = math.hypot(q[0] - m[0], q[1] - m[1])
            if best_angle is None or (ang, dist) < best_angle:
                best_angle = (ang, dist)
                choice = j
    pi = choice
    rotated = hole[mi:] + hole[:mi]
    return outer[: pi + 1] + rotated + [hole[mi]] + outer[pi:]


def _ear_clip(poly):
    """Triangulate a simple counter-clockwise polygon of (uv, index); returns index triples."""
    verts = list(poly)
    tris = []
    guard = 0
    while len(verts) > 3:
        guard += 1
        if guard > 4 * len(poly) + 16:
            raise CutawayError("the cap polygon could not be triangulated")
        n = len(verts)
        found = False
        for i in range(n):
            a, b, c = verts[i - 1][0], verts[i][0], verts[(i + 1) % n][0]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cross <= 0.0:
                continue
            blocked = False
            for j in range(n):
                q = verts[j][0]
                if q == a or q == b or q == c:
                    continue
                if _in_triangle_closed(q, a, b, c):
                    blocked = True
                    break
            if blocked:
                continue
            tris.append((verts[i - 1][1], verts[i][1], verts[(i + 1) % n][1]))
            del verts[i]
            found = True
            break
        if not found:
            raise CutawayError("the cap polygon has no ear")
    if len(verts) == 3:
        a, b, c = verts[0][0], verts[1][0], verts[2][0]
        if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0.0:
            tris.append((verts[0][1], verts[1][1], verts[2][1]))
    return tris


def triangulate(loops, pl):
    """Cap triangles of the loops on the plane: outer loops wind with the normal, holes against it; a hole is
    bridged into the outer loop that contains it, then the polygon is ear-clipped (rule 2)."""
    basis = _basis(pl["normal"])
    points = []
    polys = []
    for loop in loops:
        poly = []
        for p in loop:
            points.append(p)
            poly.append((_uv(pl, p, basis), len(points) - 1))
        polys.append(poly)
    areas = [loop_area(loop, pl) for loop in loops]
    outers = [i for i, a in enumerate(areas) if a > 0.0]
    holes = [i for i, a in enumerate(areas) if a < 0.0]
    owner = {}
    for h in holes:
        uv = polys[h][0][0]
        inside = [o for o in outers if _inside_2d(uv, [q for q, _ in polys[o]])]
        if not inside:
            raise CutawayError("a cap hole lies outside every outer loop")
        owner[h] = min(inside, key=lambda o: areas[o])
    tris = []
    for o in outers:
        poly = list(polys[o])
        mine = sorted((h for h in holes if owner[h] == o), key=lambda h: -max(q[0] for q, _ in polys[h]))
        for h in mine:
            poly = _bridge(poly, polys[h])
        for a, b, c in _ear_clip(poly):
            tris.append((points[a], points[b], points[c]))
    return tuple(tris)


def section(mesh, planes, cap=True):
    """Cut a mesh by the planes in sequence (each removes its front). Returns the remaining wall triangles,
    the cap triangles of every cut, and the loops of the last cut."""
    if len(planes) > MAX_SECTIONS:
        raise CutawayError("at most %d section planes" % MAX_SECTIONS)
    if len(mesh) > MAX_TRIANGLES:
        raise CutawayError("at most %d triangles" % MAX_TRIANGLES)
    walls = tuple(mesh)
    caps = ()
    loops = ()
    for pl in planes:
        walls, edges = _clip_mesh(walls, pl)
        caps, cap_edges = _clip_mesh(caps, pl)
        for a, b in cap_edges:
            _add_edge(edges, a, b)
        loops = _loops(edges)
        if cap and loops:
            caps = caps + triangulate(loops, pl)
    return {"walls": walls, "cap": caps, "loops": loops}


def clipped(mesh, planes, cap=True):
    cut = section(mesh, planes, cap)
    return cut["walls"] + cut["cap"]


def on_plane(tris, pl, tol=1e-12):
    return all(abs(signed_distance(pl, p)) <= tol for tri in tris for p in tri)


# ------------------------------------------------------------------------------------ hatching


def hatch(loops, pl, spacing, angle):
    """Hatch segments on a cap: lines in the plane at angle degrees from the plane's U axis, at offsets
    (k + 1/2) spacing from the plane's point, clipped to the loops by the even-odd rule (rule 3)."""
    if not (spacing > 0.0) or not math.isfinite(spacing):
        raise CutawayError("hatch spacing must be positive")
    if not loops:
        return ()
    basis = _basis(pl["normal"])
    a = math.radians(angle)
    d2 = (math.cos(a), math.sin(a))
    n2 = (-math.sin(a), math.cos(a))
    uv_loops = [[_uv(pl, p, basis) for p in loop] for loop in loops]
    offs = [u * n2[0] + v * n2[1] for loop in uv_loops for (u, v) in loop]
    lo, hi = min(offs), max(offs)
    k0 = math.ceil(lo / spacing - 0.5)
    k1 = math.floor(hi / spacing - 0.5)
    if k1 - k0 + 1 > MAX_HATCH:
        raise CutawayError("at most %d hatch lines" % MAX_HATCH)
    segs = []
    for k in range(k0, k1 + 1):
        c = (k + 0.5) * spacing
        hits = []
        for loop, uvl in zip(loops, uv_loops):
            n = len(loop)
            for i in range(n):
                (u0, v0), (u1, v1) = uvl[i], uvl[(i + 1) % n]
                s0 = u0 * n2[0] + v0 * n2[1]
                s1 = u1 * n2[0] + v1 * n2[1]
                if (s0 <= c) != (s1 <= c):
                    t = (c - s0) / (s1 - s0)
                    along = (u0 + (u1 - u0) * t) * d2[0] + (v0 + (v1 - v0) * t) * d2[1]
                    p3 = _add(loop[i], _mul(_sub(loop[(i + 1) % n], loop[i]), t))
                    hits.append((along, p3))
        hits.sort()
        for i in range(0, len(hits) - 1, 2):
            segs.append((hits[i][1], hits[i + 1][1]))
    return tuple(segs)


def hatch_length(segs):
    return sum(_norm(_sub(b, a)) for a, b in segs)


# ------------------------------------------------------------------------------------ exploded views


def part(mesh, factor=1.0, direction=None):
    return {"mesh": tuple(mesh), "factor": factor, "direction": direction}


def part_centre(p):
    return centre(p["mesh"])


def assembly_centre(parts):
    return centre(tuple(t for p in parts.values() for t in p["mesh"]))


def _check_parts(parts, amount, mode):
    if not parts:
        raise CutawayError("an exploded view needs at least one part")
    if len(parts) > MAX_PARTS:
        raise CutawayError("at most %d parts" % MAX_PARTS)
    if not (amount >= 0.0) or not math.isfinite(amount):
        raise CutawayError("amount is a finite number at least 0")
    if mode not in MODES:
        raise CutawayError("mode is one of radial, axis, rank")


def ranks(parts, centre=None):
    """Dense rank of each part by the distance of its centre from the assembly centre (rule 6)."""
    c = assembly_centre(parts) if centre is None else centre
    dist = {name: _norm(_sub(part_centre(p), c)) for name, p in parts.items()}
    levels = sorted(set(dist.values()))
    return {name: levels.index(d) for name, d in dist.items()}


def displacements(parts, amount, mode="radial", axis=None, spacing=1.0, centre=None):
    """Displacement of every part at the amount (rules 4 to 6): radial = amount x factor x (c - C); axis =
    its component along the axis; rank = amount x factor x spacing x rank along the unit offset. A part's
    direction override replaces c - C."""
    _check_parts(parts, amount, mode)
    if mode == "axis":
        if axis is None or _norm(axis) == 0.0:
            raise CutawayError("axis mode needs a nonzero axis")
        a = _unit(axis)
    c = assembly_centre(parts) if centre is None else centre
    rk = ranks(parts, c) if mode == "rank" else None
    out = {}
    for name, p in parts.items():
        r = p["direction"] if p["direction"] is not None else _sub(part_centre(p), c)
        if mode == "radial":
            base = r
        elif mode == "axis":
            base = _mul(a, _dot(r, a))
        else:
            base = _mul(_unit(r), spacing * rk[name])
        out[name] = _mul(base, amount * p["factor"])
    return out


def explode(parts, amount, mode="radial", axis=None, spacing=1.0, centre=None):
    d = displacements(parts, amount, mode, axis, spacing, centre)
    return {name: tuple(tuple(_add(q, d[name]) for q in tri) for tri in p["mesh"]) for name, p in parts.items()}


def overlap(a, b):
    """True when the bounds of two meshes intersect or touch."""
    (alo, ahi), (blo, bhi) = bounds(a), bounds(b)
    return all(alo[i] <= bhi[i] and blo[i] <= ahi[i] for i in range(3))


def cutaway(meshes, planes, cap=True):
    """Section every part of an exploded view; parts wholly in front of a plane disappear (rule 7)."""
    out = {}
    for name, mesh in meshes.items():
        m = clipped(mesh, planes, cap)
        if m:
            out[name] = m
    return out


# ------------------------------------------------------------------------------------ surface flow


def sphere_surface(radius=1.0):
    def project(p):
        n = _norm(p)
        if n == 0.0:
            raise CutawayError("the centre of a sphere has no nearest point")
        return (p[0] * radius / n, p[1] * radius / n, p[2] * radius / n)

    return {"project": project, "normal": _unit}


def plane_surface(z=0.0):
    return {"project": lambda p: (p[0], p[1], z), "normal": lambda p: (0.0, 0.0, 1.0)}


def cylinder_surface(radius=1.0):
    def project(p):
        r = math.hypot(p[0], p[1])
        if r == 0.0:
            raise CutawayError("the axis of a cylinder has no nearest point")
        return (p[0] * radius / r, p[1] * radius / r, p[2])

    def normal(p):
        r = math.hypot(p[0], p[1])
        return (p[0] / r, p[1] / r, 0.0)

    return {"project": project, "normal": normal}


def uniform(v):
    v = tuple(float(c) for c in v)
    return lambda x, y, z: v


def field(f):
    return f


def tangent(surface, fld, p):
    """The field minus its part along the surface normal (rule 8)."""
    v = fld(*p)
    if not _finite(v):
        raise CutawayError("the field is not finite at %r" % (p,))
    n = surface["normal"](p)
    return _sub(v, _mul(n, _dot(v, n)))


def _direction(surface, fld, p):
    t = tangent(surface, fld, p)
    m = _norm(t)
    if m < 1e-12:
        return None
    return (t[0] / m, t[1] / m, t[2] / m)


def _advance(surface, fld, p, step, sign):
    """One classical Runge-Kutta step of the unit tangent field, every stage on the surface."""
    proj = surface["project"]

    def f(q):
        d = _direction(surface, fld, q)
        return None if d is None else _mul(d, sign)

    k1 = f(p)
    if k1 is None:
        return None, None
    euler = proj(_add(p, _mul(k1, step)))
    k2 = f(proj(_add(p, _mul(k1, step / 2))))
    if k2 is None or _dot(k2, k1) < 0.0:
        return euler, k1
    k3 = f(proj(_add(p, _mul(k2, step / 2))))
    if k3 is None or _dot(k3, k1) < 0.0:
        return euler, k1
    k4 = f(proj(_add(p, _mul(k3, step))))
    if k4 is None or _dot(k4, k1) < 0.0:
        return euler, k1
    s = _add(_add(k1, _mul(k2, 2.0)), _add(_mul(k3, 2.0), k4))
    return proj(_add(p, _mul(s, step / 6))), k1


def _grow(surface, fld, start, step, max_steps, sign=1.0, blocked=None, inside=None):
    """Points from `start` along the field (sign +1) or against it (-1): the line ends at a stagnation
    point, a reversal of the direction, a closure onto its own earlier points, a blocked or outside point,
    or the step bound (rule 9)."""
    pts = [start]
    prev = None
    for _ in range(max_steps):
        p = pts[-1]
        q, d = _advance(surface, fld, p, step, sign)
        if q is None:
            break
        if prev is not None and _dot(d, prev) < 0.0:
            break
        prev = d
        if inside is not None and not inside(q):
            break
        if blocked is not None and blocked(q):
            break
        if any(_norm(_sub(q, pts[k])) <= step / 2 for k in range(len(pts) - 3)):
            pts.append(q)
            break
        pts.append(q)
    return pts


def _check_flow(step, max_steps):
    if not (step > 0.0) or not math.isfinite(step):
        raise CutawayError("the flow step must be positive")
    if not (1 <= max_steps <= MAX_STEPS):
        raise CutawayError("maxSteps is 1 to %d" % MAX_STEPS)


def flow_line(surface, fld, start, step, max_steps):
    """One flow line from the start's nearest surface point (rule 9)."""
    _check_flow(step, max_steps)
    return tuple(_grow(surface, fld, surface["project"](start), step, max_steps))


def closes(line, step):
    return any(_norm(_sub(line[-1], line[k])) <= step / 2 for k in range(len(line) - 3))


def arc_length(line):
    return sum(_norm(_sub(line[i + 1], line[i])) for i in range(len(line) - 1))


class _Grid:
    def __init__(self, cell):
        self.cell = cell
        self.cells = {}

    def key(self, p):
        return tuple(math.floor(c / self.cell) for c in p)

    def add(self, p, line):
        self.cells.setdefault(self.key(p), []).append((p, line))

    def near(self, p, radius, skip=None):
        kx, ky, kz = self.key(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q, line in self.cells.get((kx + dx, ky + dy, kz + dz), ()):
                        if line == skip:
                            continue
                        if _norm(_sub(q, p)) < radius:
                            return True
        return False


def flow_lines(surface, fld, seed, separation, test, step, max_steps, max_lines, bounds=None):
    """Evenly spaced flow lines by the Jobard-Lefer rule (rule 10): a line grows from the seed until it comes
    within `test` of another line; candidate seeds sit `separation` to either side of every point of every
    line, in order, and are taken when no point of any line is nearer than `separation`."""
    _check_flow(step, max_steps)
    if not (0.0 < test <= separation) or not math.isfinite(separation):
        raise CutawayError("test is positive and at most separation")
    if not (1 <= max_lines <= MAX_LINES):
        raise CutawayError("maxLines is 1 to %d" % MAX_LINES)
    grid = _Grid(separation)
    proj = surface["project"]

    def inside(p):
        if bounds is None:
            return True
        return all(bounds[0][i] - 1e-12 <= p[i] <= bounds[1][i] + 1e-12 for i in range(3))

    lines = []

    def grow_line(start):
        idx = len(lines)
        blocked = lambda q: grid.near(q, test, skip=idx)
        fwd = _grow(surface, fld, start, step, max_steps, 1.0, blocked, inside)
        back = _grow(surface, fld, start, step, max_steps, -1.0, blocked, inside)
        pts = tuple(reversed(back[1:])) + tuple(fwd)
        if len(pts) < 2:
            return False
        lines.append(pts)
        for p in pts:
            grid.add(p, idx)
        return True

    s0 = proj(seed)
    if not inside(s0):
        raise CutawayError("the seed lies outside the bounds")
    grow_line(s0)
    i = 0
    while i < len(lines) and len(lines) < max_lines:
        for p in lines[i]:
            d = _direction(surface, fld, p)
            if d is None:
                continue
            b = _unit(_cross(surface["normal"](p), d))
            for sign in (1.0, -1.0):
                cand = _offset(surface, p, _mul(b, sign), separation)
                if not inside(cand) or grid.near(cand, separation * (1 - 1e-9)):
                    continue
                grow_line(cand)
                if len(lines) >= max_lines:
                    break
            if len(lines) >= max_lines:
                break
        i += 1
    return tuple(lines)


def _offset(surface, p, b, distance):
    """The surface point in the direction b whose straight distance from p is `distance`: the offset along
    b is found by bisection, since the projection pulls a curved surface's point back toward p."""
    proj = surface["project"]

    def chord(t):
        return _norm(_sub(proj(_add(p, _mul(b, t))), p)) - distance

    lo, hi = distance, 4 * distance
    if chord(lo) == 0.0:
        return proj(_add(p, _mul(b, lo)))
    if chord(hi) <= 0.0:
        return proj(_add(p, _mul(b, hi)))
    for _ in range(80):
        mid = (lo + hi) / 2
        if chord(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    return proj(_add(p, _mul(b, hi)))


def min_separation(lines, radius=0.5):
    """The least distance between points of different lines, or `radius` when none is nearer."""
    grid = _Grid(radius)
    for i, line in enumerate(lines):
        for p in line:
            grid.add(p, i)
    best = radius
    for i, line in enumerate(lines):
        for p in line:
            kx, ky, kz = grid.key(p)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for q, j in grid.cells.get((kx + dx, ky + dy, kz + dz), ()):
                            if j != i:
                                best = min(best, _norm(_sub(q, p)))
    return best


# ------------------------------------------------------------------------------------ the draft's checks


def sample_parts():
    return {
        "hub": part(box((0.4, 0.4, 0.4))),
        "left": part(box((0.4, 0.4, 0.4), (-1.0, 0.0, 0.0))),
        "right": part(box((0.4, 0.4, 0.4), (1.0, 0.0, 0.0))),
        "top": part(box((0.4, 0.4, 0.4), (0.0, 2.0, 0.0))),
    }


def _z_plane(z=0.0):
    return plane((0.0, 0.0, z), (0.0, 0.0, 1.0))


def plane_test():
    pl = plane((0.1, -0.2, 0.3), (0.3, -0.4, 1.0))
    cut = section(box(), [pl])
    faces = all(_norm(_sub(triangle_normal(t), pl["normal"])) < 1e-9 for t in cut["cap"])
    return (bool(cut["cap"]), on_plane(cut["cap"], pl, 1e-12), faces)


def volume_test():
    out = []
    for normal in ((0.0, 0.0, 1.0), (1.0, 1.0, 0.0), (0.3, -0.4, 1.0)):
        a = clipped(box(), [plane((0.1, 0.0, 0.05), normal)])
        b = clipped(box(), [plane((0.1, 0.0, 0.05), normal, keep="front")])
        out.append(closed(a) and closed(b) and abs(volume(a) + volume(b) - 1.0) <= 1e-12)
    return tuple(out)


def identity_test():
    m = box()
    return (clipped(m, [_z_plane(0.5)]) == m, clipped(m, [_z_plane(-0.5)]) == ())


def sphere_test():
    m = icosphere(1.0, 2)
    cut = section(m, [_z_plane()])
    k = cut["walls"] + cut["cap"]
    return (closed(k), abs(volume(k) - volume(m) / 2) <= 1e-12, len(cut["loops"]) == 1)


def torus_test():
    t = torus(2.0, 0.5, 48, 24)
    cut = section(t, [_z_plane()])
    k = cut["walls"] + cut["cap"]
    areas = sorted((loop_area(loop, _z_plane()) for loop in cut["loops"]), key=abs, reverse=True)
    return (len(cut["loops"]) == 2 and areas[0] > 0 > areas[1], closed(k), abs(volume(k) - volume(t) / 2) <= 1e-9)


def hatch_test():
    pl = _z_plane(0.3)
    loops = section(box(), [pl])["loops"]
    h0 = hatch(loops, pl, 0.25, 0.0)
    h45 = hatch(loops, pl, 0.25, 45.0)
    want = math.sqrt(2.0) * sum(1.0 - abs(c) * math.sqrt(2.0) for c in (-0.625, -0.375, -0.125, 0.125, 0.375, 0.625))
    return (len(h0) == 4, abs(hatch_length(h0) - 4.0) <= 1e-12, abs(hatch_length(h45) - want) <= 1e-9)


def hatch_diagonal():
    pl = _z_plane(0.3)
    return hatch_length(hatch(section(box(), [pl])["loops"], pl, 0.25, 45.0))


def return_test():
    parts = sample_parts()
    out = []
    for mode in MODES:
        e = explode(parts, 0.0, mode=mode, axis=(0.0, 1.0, 0.0))
        out.append(all(e[n] == parts[n]["mesh"] for n in parts))
    return tuple(out)


def rank_test():
    parts = sample_parts()
    r = ranks(parts, centre=(0.0, 0.0, 0.0))
    d = displacements(parts, 1.0, mode="rank", spacing=0.5, centre=(0.0, 0.0, 0.0))
    return (r == {"hub": 0, "left": 1, "right": 1, "top": 2}, _norm(_sub(d["top"], (0.0, 1.0, 0.0))) <= 1e-12)


def separation_test():
    parts = {k: part(box((1.5, 1.5, 1.5), part_centre(v))) for k, v in sample_parts().items()}
    touch = explode(parts, 0.5, centre=(0.0, 0.0, 0.0))
    apart = explode(parts, 0.5 + 1e-9, centre=(0.0, 0.0, 0.0))
    return (overlap(touch["left"], touch["hub"]), not overlap(apart["left"], apart["hub"]))


def meridian_line():
    return flow_line(sphere_surface(1.0), uniform((0.0, 0.0, -1.0)), (math.sin(math.pi / 6), 0.0, math.cos(math.pi / 6)),
                     0.01, 1000)


def meridian_test():
    line = meridian_line()
    on = all(abs(_norm(p) - 1.0) <= 1e-12 and p[1] == 0.0 for p in line)
    return (on, _norm(_sub(line[-1], (0.0, 0.0, -1.0))) <= 0.01, abs(arc_length(line) - 5 * math.pi / 6) <= 0.02)


def latitude_line(z0=0.5):
    return flow_line(sphere_surface(1.0), lambda x, y, z: (-y, x, 0.0), (math.sqrt(1 - z0 * z0), 0.0, z0), 0.01, 10000)


def latitude_drift():
    return max(abs(p[2] - 0.5) for p in latitude_line())


def latitude_test():
    line = latitude_line()
    return (closes(line, 0.01), latitude_drift() <= 1e-4,
            abs(arc_length(line) - 2 * math.pi * math.sqrt(0.75)) <= 0.02)


def straight_test():
    a = flow_line(plane_surface(0.0), uniform((2.0, 0.0, 0.5)), (-1.0, 0.25, 0.0), 0.1, 20)
    b = flow_line(cylinder_surface(1.0), uniform((0.0, 0.0, 1.0)), (0.6, 0.8, 0.0), 0.1, 20)
    return (all(_norm(_sub(p, (-1.0 + 0.1 * i, 0.25, 0.0))) <= 1e-12 for i, p in enumerate(a)),
            all(_norm(_sub(p, (0.6, 0.8, 0.1 * i))) <= 1e-12 for i, p in enumerate(b)))


def plane_lines():
    return flow_lines(plane_surface(0.0), uniform((1.0, 0.0, 0.0)), (0.0, 0.0, 0.0), 0.2, 0.1, 0.05, 1000, 100,
                      bounds=((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)))


def sphere_lines():
    return flow_lines(sphere_surface(1.0), uniform((0.0, 0.0, -1.0)), (1.0, 0.0, 0.0), 0.3, 0.15, 0.03, 1000, 100)


def spacing_test():
    lines = plane_lines()
    ys = sorted(round(line[0][1], 9) for line in lines)
    return (ys == [round(-1.0 + 0.2 * i, 9) for i in range(11)], min_separation(sphere_lines()) >= 0.15 - 0.03 - 1e-9)


def seek_test():
    parts = sample_parts()
    pl = plane((0.0, 0.0, 0.1), (0.3, 0.2, 1.0), offset=0.05)
    first = cutaway(explode(parts, 0.7), [pl])
    cutaway(explode(parts, 0.2), [plane((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))])
    again = cutaway(explode(parts, 0.7), [pl])
    lines = sphere_lines()
    return (first == again, sphere_lines() == lines)


# ------------------------------------------------------------------------------------ the numeric table

TABLE = (
    ("box volume", "volume(box())", "1.0"),
    ("box area", "area(box())", "6.0"),
    ("box closed", "closed(box())", "True"),
    ("icosphere faces", "len(icosphere(1.0, 3))", "1280"),
    ("icosphere volume", "round(volume(icosphere(1.0, 3)), 9)", "4.087389416"),
    ("cut volume", "round(volume(clipped(box(), [_z_plane(0.3)])), 12)", "0.8"),
    ("cut closed", "closed(clipped(box(), [_z_plane(0.3)]))", "True"),
    ("cut bounds", "tuple(tuple(round(c, 9) for c in q) for q in bounds(clipped(box(), [_z_plane(0.3)])))", "((-0.5, -0.5, -0.5), (0.5, 0.5, 0.3))"),
    ("offset", "round(volume(clipped(box(), [plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), offset=0.3)])), 12)", "0.8"),
    ("front", "round(volume(clipped(box(), [plane((0.0, 0.0, 0.3), (0.0, 0.0, 1.0), keep='front')])), 12)", "0.2"),
    ("diagonal cap", "round(cap_area(section(box(), [plane((0.0, 0.0, 0.0), (1.0, 1.0, 0.0))])['loops'], plane((0.0, 0.0, 0.0), (1.0, 1.0, 0.0))), 12)", "1.414213562373"),
    ("plane test", "plane_test()", "(True, True, True)"),
    ("volume test", "volume_test()", "(True, True, True)"),
    ("identity test", "identity_test()", "(True, True)"),
    ("sequence", "round(volume(clipped(box(), [plane((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), plane((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))])), 12)", "0.25"),
    ("sphere loops", "len(section(icosphere(1.0, 2), [_z_plane()])['loops'])", "1"),
    ("sphere test", "sphere_test()", "(True, True, True)"),
    ("torus loops", "len(section(torus(2.0, 0.5, 48, 24), [_z_plane()])['loops'])", "2"),
    ("torus test", "torus_test()", "(True, True, True)"),
    ("hatch count", "len(hatch(section(box(), [_z_plane(0.3)])['loops'], _z_plane(0.3), 0.25, 0.0))", "4"),
    ("hatch length", "round(hatch_length(hatch(section(box(), [_z_plane(0.3)])['loops'], _z_plane(0.3), 0.25, 0.0)), 12)", "4.0"),
    ("hatch diagonal", "round(hatch_diagonal(), 9)", "3.985281374"),
    ("hatch test", "hatch_test()", "(True, True, True)"),
    ("assembly centre", "assembly_centre(sample_parts())", "(0.0, 1.0, 0.0)"),
    ("radial", "displacements(sample_parts(), 0.5)['left']", "(-0.5, -0.5, 0.0)"),
    ("axis", "displacements(sample_parts(), 1.0, mode='axis', axis=(0.0, 2.0, 0.0), centre=(0.0, 0.0, 0.0))['top']", "(0.0, 2.0, 0.0)"),
    ("ranks", "ranks(sample_parts(), centre=(0.0, 0.0, 0.0))", "{'hub': 0, 'left': 1, 'right': 1, 'top': 2}"),
    ("return test", "return_test()", "(True, True, True)"),
    ("rank test", "rank_test()", "(True, True)"),
    ("separation test", "separation_test()", "(True, True)"),
    ("tangent", "tangent(sphere_surface(1.0), uniform((0.0, 0.0, -1.0)), (0.0, 0.0, 1.0))", "(0.0, 0.0, 0.0)"),
    ("meridian points", "len(meridian_line())", "263"),
    ("meridian length", "round(arc_length(meridian_line()), 6)", "2.617994"),
    ("meridian test", "meridian_test()", "(True, True, True)"),
    ("latitude drift", "round(latitude_drift(), 12)", "0.0"),
    ("latitude test", "latitude_test()", "(True, True, True)"),
    ("straight test", "straight_test()", "(True, True)"),
    ("plane lines", "len(plane_lines())", "11"),
    ("sphere lines", "len(sphere_lines())", "0"),
    ("sphere separation", "round(min_separation(sphere_lines()), 6)", "0.0"),
    ("spacing test", "spacing_test()", "(True, True)"),
    ("seek test", "seek_test()", "(True, True)"),
)


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["sqrt"] = math.sqrt
    s["pi"] = math.pi
    return s


def _same(a, b, tol=1e-9):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


def main():
    s = scope()
    for name, expr, expected in TABLE:
        got = eval(expr, s)
        if isinstance(got, float):
            got = repr(got)
        print("| %s | `%s` | `%s` |" % (name, expr, got))


if __name__ == "__main__":
    main()
