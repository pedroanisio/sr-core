"""Reference implementation of the draft SREP "Add ragdolls and physics interchange to 3D rigid bodies"
(srep/srep-0000-ragdolls-interchange.md; S4 of SREP 12, SRC-40).

Pure Python, standard library only. Three parts, each a set of functions that the draft's rules name:

1. Glue (SREP 80 section 6 and the engine's stress rule, restated): the seeded Voronoi partition in exact integers,
   the face-connected pieces in scan order, their moments, the joints (shared faces) and their sections, the cut
   stress of a load on a section (normal, shear, bending, twist; Rankine's principal tension), the glued cantilever.
2. Ragdolls: capsule limbs, planar hinge chains in reduced coordinates (the Lagrangian mass matrix, symplectic
   Euler), the blend weight (kinematic at 0, a PD drive scaled by 1 - blend above it, the drawn pose blended),
   hinge limits, the chain as a function of the step count.
3. Interchange: a world of SREP 11 rigid bodies and constraints written to and read from a UsdPhysics stage (a
   dict of prims, and its usda text) and a glTF with KHR_physics_rigid_bodies and KHR_implicit_shapes; the
   round trip is the identity, foreign assets fill the format's defaults, and what the format cannot express is
   a typed error.

`main()` prints the numeric table of the draft's Conformance section; the test parses it back.
"""
import math

# ---------------------------------------------------------------------------------------------------- bounds

MAX_SEEDS = 4096                # crates/sr-3d/src/pieces.rs:41
MAX_SEED_COORD = 1 << 40        # pieces.rs:43
MAX_PIECES = 4096               # fracture/@maxFragments upper bound
MAX_LIMBS = 256
MAX_STEPS = 65536
MAX_BODIES = 65536
MAX_CONSTRAINTS = 65536
GOLDEN = 0x9E3779B97F4A7C15
MASK = (1 << 64) - 1


class PartitionError(ValueError):
    """A partition or a glue rule that the document violates."""


class RagdollError(ValueError):
    """A ragdoll that the rules refuse."""


class InterchangeError(ValueError):
    """A physics asset the format cannot express, or a world the asset cannot."""


# ---------------------------------------------------------------------------------------------------- 1. partition


def splitmix64(state):
    z = state & MASK
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
    return z ^ (z >> 31)


def doubled(cell):
    return tuple(2 * int(k) + 1 for k in cell)


def seeds_in(count, seed, lo, hi):
    """The doubled coordinates of seeds 0..count drawn from (seed, index) in the doubled box lo..hi (pieces.rs:314-352)."""
    if count > MAX_SEEDS:
        raise PartitionError(f"{count} seeds, and a partition takes at most {MAX_SEEDS}")
    for a in range(3):
        if lo[a] > hi[a] or abs(lo[a]) > MAX_SEED_COORD or abs(hi[a]) > MAX_SEED_COORD:
            raise PartitionError(f"the box {lo} to {hi} of the seeds is upside down or farther than {MAX_SEED_COORD} from the origin")
    out = []
    for s in range(count):
        out.append(tuple(lo[a] + splitmix64((seed + (3 * s + a + 1) * GOLDEN) & MASK) % (hi[a] - lo[a] + 1)
                         for a in range(3)))
    return tuple(out)


def nearest(seeds, u):
    """The index of the seed nearest to the doubled point u, the lowest index on a tie (pieces.rs:362-373)."""
    best = None
    for i, s in enumerate(seeds):
        d = sum((u[a] - s[a]) ** 2 for a in range(3))
        if best is None or d < best[0]:
            best = (d, i)
    return best[1]


def bounds(cells):
    return (tuple(min(c[a] for c in cells) for a in range(3)), tuple(max(c[a] for c in cells) for a in range(3)))


def voronoi(cells, pieces, seed):
    """The label of every cell: the nearest of `pieces` seeds drawn from `seed` in the doubled box of the cells."""
    if not cells:
        raise PartitionError("a body with no cell has no pieces")
    if pieces < 1:
        raise PartitionError("a Voronoi partition needs at least one seed")
    lo, hi = bounds(cells)
    seeds = seeds_in(pieces, seed, doubled(lo), doubled(hi))
    return [nearest(seeds, doubled(c)) for c in cells]


def scan_key(cell):
    return (cell[2], cell[1], cell[0])


NEIGHBOURS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def components(cells):
    """The face-connected components of `cells`, each in scan order, listed by their first cell."""
    left = set(cells)
    out = []
    for start in sorted(left, key=scan_key):
        if start not in left:
            continue
        queue, part = [start], []
        left.discard(start)
        while queue:
            c = queue.pop()
            part.append(c)
            for d in NEIGHBOURS:
                n = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                if n in left:
                    left.discard(n)
                    queue.append(n)
        out.append(tuple(sorted(part, key=scan_key)))
    return sorted(out, key=lambda p: scan_key(p[0]))


def connected(cells):
    return len(components(cells)) == 1


def partition(cells, labels):
    """The pieces: the components of each label's cells, numbered by their first cell in scan order (pieces.rs:388-438)."""
    if not cells:
        raise PartitionError("a body with no cell has no pieces")
    if len(labels) != len(cells):
        raise PartitionError("one label for every cell")
    if len(set(cells)) != len(cells):
        raise PartitionError("a cell is listed twice")
    parts = {}
    for c, l in zip(cells, labels):
        parts.setdefault(l, []).append(tuple(c))
    found = [p for l in sorted(parts) for p in components(parts[l])]
    if len(found) > MAX_PIECES:
        raise PartitionError(f"the partition makes {len(found)} pieces and the limit is {MAX_PIECES} pieces")
    return tuple(sorted(found, key=lambda p: scan_key(p[0])))


def piece_of(pieces, cell):
    for i, p in enumerate(pieces):
        if tuple(cell) in p:
            return i
    return None


def volume(cells, size):
    return len(cells) * size[0] * size[1] * size[2]


def moments(cells, size, density):
    """Mass, centre and inertia about the centre of a set of cuboid cells of `size` and `density`."""
    m_cell = density * size[0] * size[1] * size[2]
    n = len(cells)
    mass = m_cell * n
    centre = tuple(sum((c[a] + 0.5) * size[a] for c in cells) * m_cell / mass for a in range(3))
    own = [m_cell / 12.0 * (size[1] ** 2 + size[2] ** 2), m_cell / 12.0 * (size[0] ** 2 + size[2] ** 2),
           m_cell / 12.0 * (size[0] ** 2 + size[1] ** 2)]
    inertia = [[0.0] * 3 for _ in range(3)]
    for c in cells:
        r = [(c[a] + 0.5) * size[a] - centre[a] for a in range(3)]
        rr = r[0] ** 2 + r[1] ** 2 + r[2] ** 2
        for a in range(3):
            for b in range(3):
                inertia[a][b] += m_cell * ((rr if a == b else 0.0) - r[a] * r[b])
            inertia[a][a] += own[a]
    return {"mass": mass, "centre": centre, "inertia": tuple(tuple(row) for row in inertia)}


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm(a):
    return math.sqrt(_dot(a, a))


def _mat_vec(m, v):
    return tuple(_dot(m[a], v) for a in range(3))


def momentum_test(cells, pieces, size, density, v, omega):
    """|sum of the pieces' momenta - the whole's|, linear and angular about the whole's centre, for a rigid motion."""
    whole = moments(cells, size, density)
    p_whole = _scale(v, whole["mass"])
    l_whole = _mat_vec(whole["inertia"], omega)
    p_sum, l_sum = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    for piece in pieces:
        m = moments(piece, size, density)
        r = _sub(m["centre"], whole["centre"])
        v_i = _add(v, _cross(omega, r))
        p_i = _scale(v_i, m["mass"])
        p_sum = _add(p_sum, p_i)
        l_sum = _add(l_sum, _add(_mat_vec(m["inertia"], omega), _cross(r, p_i)))
    return (_norm(_sub(p_sum, p_whole)), _norm(_sub(l_sum, l_whole)))


def volume_sum_test():
    cells = [(x, y, z) for x in range(6) for y in range(4) for z in range(3)]
    pieces = partition(cells, voronoi(cells, 8, 1))
    return (sum(len(p) for p in pieces) == len(cells), sorted(c for p in pieces for c in p) == sorted(cells),
            all(connected(p) for p in pieces))


# ---------------------------------------------------------------------------------------------------- 2. glue


def joints(pieces):
    """The shared faces between pieces: {(a, b): [(cell in a, cell in b, axis), ...]} with a < b, sorted."""
    owner = {c: i for i, p in enumerate(pieces) for c in p}
    out = {}
    for c, i in owner.items():
        for axis in range(3):
            n = list(c)
            n[axis] += 1
            n = tuple(n)
            j = owner.get(n)
            if j is None or j == i:
                continue
            if i < j:
                out.setdefault((i, j), []).append((c, n, axis))
            else:
                out.setdefault((j, i), []).append((n, c, axis))
    return {k: sorted(out[k]) for k in sorted(out)}


def section(faces, size):
    """Area, centroid, second moments about the centroid, box and mean normal (from a to b) of a joint's faces."""
    area = 0.0
    first = [0.0, 0.0, 0.0]
    normal = [0.0, 0.0, 0.0]
    centres = []
    for ca, cb, axis in faces:
        a_face = size[(axis + 1) % 3] * size[(axis + 2) % 3]
        centre = [(ca[k] + 0.5) * size[k] for k in range(3)]
        centre[axis] = max(ca[axis], cb[axis]) * size[axis]
        centres.append((a_face, tuple(centre), axis))
        area += a_face
        for k in range(3):
            first[k] += a_face * centre[k]
        normal[axis] += a_face * (1.0 if cb[axis] > ca[axis] else -1.0)
    centroid = tuple(f / area for f in first)
    second = [[0.0] * 3 for _ in range(3)]
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for a_face, centre, axis in centres:
        d = _sub(centre, centroid)
        for p in range(3):
            for q in range(3):
                second[p][q] += a_face * d[p] * d[q]
            if p != axis:
                second[p][p] += a_face * size[p] ** 2 / 12.0
                lo[p] = min(lo[p], centre[p] - size[p] / 2.0)
                hi[p] = max(hi[p], centre[p] + size[p] / 2.0)
            else:
                lo[p] = min(lo[p], centre[p])
                hi[p] = max(hi[p], centre[p])
    n = _norm(normal)
    return {"area": area, "centroid": centroid, "second": tuple(tuple(r) for r in second), "lo": tuple(lo),
            "hi": tuple(hi), "normal": tuple(c / n for c in normal) if n > 0 else (1.0, 0.0, 0.0)}


def principal_tension(sigma, tau):
    """Rankine: the largest principal stress of a normal stress sigma and a shear tau, zero when it only compresses."""
    return max(sigma / 2.0 + math.sqrt(sigma * sigma / 4.0 + tau * tau), 0.0)


def cut_stress(sections, side_has_a, load):
    """The stress in each joint of a cut that carries `load` as one rigid section (stress.rs:114-230).

    `load` is {"force", "moment", "point"}: the wrench the rest of the body puts on the side, the force acting at
    `point` with `moment` about it. `side_has_a[i]` says whether piece a of joint i is on the side.
    """
    area = sum(s["area"] for s in sections)
    if not sections or area <= 0.0:
        return [{"normal": 0.0, "shear": 0.0, "bending": 0.0, "torsion": 0.0, "principal": 0.0} for _ in sections]
    centre = tuple(sum(s["area"] * s["centroid"][a] for s in sections) / area for a in range(3))
    second = [[0.0] * 3 for _ in range(3)]
    for s in sections:
        d = _sub(s["centroid"], centre)
        for a in range(3):
            for b in range(3):
                second[a][b] += s["second"][a][b] + s["area"] * d[a] * d[b]
    outward = [_scale(s["normal"], 1.0 if has_a else -1.0) for s, has_a in zip(sections, side_has_a)]
    mean = tuple(sum(s["area"] * o[a] for s, o in zip(sections, outward)) for a in range(3))
    if _norm(mean) > 1e-9 * area:
        n = _scale(mean, 1.0 / _norm(mean))
    elif _norm(load["force"]) > 0.0:
        n = _scale(load["force"], 1.0 / _norm(load["force"]))
    else:
        n = outward[0]
    pull = _dot(load["force"], n)
    across = _sub(load["force"], _scale(n, pull))
    moment = _add(load["moment"], _cross(_sub(load["point"], centre), load["force"]))
    twist = _dot(moment, n)
    bending_moment = _sub(moment, _scale(n, twist))
    helper = (1.0, 0.0, 0.0) if abs(n[0]) < 0.6 else (0.0, 1.0, 0.0)
    t = _sub(helper, _scale(n, _dot(helper, n)))
    u = _scale(t, 1.0 / _norm(t))
    v = _cross(n, u)
    juu, juv, jvv = _dot(u, _mat_vec(second, u)), _dot(u, _mat_vec(second, v)), _dot(v, _mat_vec(second, v))
    w = _cross(n, bending_moment)
    wu, wv = _dot(w, u), _dot(w, v)
    mean_j = (juu + jvv) / 2.0
    radius = math.sqrt(((juu - jvv) / 2.0) ** 2 + juv * juv)
    big, small = mean_j + radius, mean_j - radius
    angle = 0.5 * math.atan2(2.0 * juv, juu - jvv)
    c, s = math.cos(angle), math.sin(angle)
    w_big, w_small = c * wu + s * wv, -s * wu + c * wv

    def part(component, mom):
        if component == 0.0:
            return 0.0
        if mom > 1e-12 * max(big, 2.2250738585072014e-308):
            return component / mom
        return math.copysign(math.inf, component)

    g_big, g_small = part(w_big, big), part(w_small, small)
    direction_big = tuple(c * u[k] + s * v[k] for k in range(3))
    direction_small = tuple(-s * u[k] + c * v[k] for k in range(3))
    polar = juu + jvv
    out = []
    for j in sections:
        bending = -math.inf
        reach = 0.0
        for corner in range(8):
            p = tuple(j["hi"][a] if (corner >> a) & 1 else j["lo"][a] for a in range(3))
            r = _sub(p, centre)

            def along(g, d):
                x = _dot(d, r)
                return 0.0 if g == 0.0 or x == 0.0 else g * x

            bending = max(bending, along(g_big, direction_big) + along(g_small, direction_small))
            in_plane = _sub(r, _scale(n, _dot(r, n)))
            reach = max(reach, _norm(in_plane))
        normal = pull / area
        shear = _norm(across) / area
        if twist == 0.0:
            torsion = 0.0
        elif polar > 0.0:
            torsion = abs(twist) * reach / polar
        else:
            torsion = math.inf
        out.append({"normal": normal, "shear": shear, "bending": bending, "torsion": torsion,
                    "principal": principal_tension(normal + bending, shear + torsion)})
    return out


def cantilever(n, a, density, g):
    """A bar of n cells of side a glued cell to cell, cell 0 welded to the wall, loaded by its own weight across the
    bar: the stress in joint i (between cells i and i + 1), whose side is the free end beyond it."""
    if n < 2:
        raise PartitionError("a cantilever needs two cells")
    cells = [(i, 0, 0) for i in range(n)]
    pieces = partition(cells, list(range(n)))
    size = (a, a, a)
    js = joints(pieces)
    out = []
    for i in range(n - 1):
        sec = section(js[(i, i + 1)], size)
        side = moments(cells[i + 1:], size, density)
        load = {"force": (0.0, side["mass"] * g, 0.0), "moment": (0.0, 0.0, 0.0), "point": side["centre"]}
        out.append(cut_stress([sec], [False], load)[0])
    return out


def broken(stresses, strength):
    """The joints whose principal tension reaches `strength`."""
    if not strength > 0.0:
        raise PartitionError("a glue strength is positive")
    return tuple(i for i, s in enumerate(stresses) if s["principal"] >= strength)


def glue_test():
    stresses = cantilever(9, 0.1, 2000.0, 9.81)
    worst = max(s["principal"] for s in stresses)
    return (broken(stresses, worst * 1.001) == (), broken(stresses, worst * 0.999) == (0,),
            len(broken(stresses, stresses[3]["principal"])))


def cantilever_root(n, a, density, g):
    """The closed form of the root joint's bending and shear stress: 3 rho g L^2 / a and rho g L, L = (n - 1) a."""
    L = (n - 1) * a
    return (3.0 * density * g * L * L / a, density * g * L)


# ---------------------------------------------------------------------------------------------------- 3. ragdolls


def capsule_volume(radius, length):
    return math.pi * radius * radius * length + 4.0 / 3.0 * math.pi * radius ** 3


def capsule_inertia(mass, radius, length):
    """(axial, transverse) inertia of a capsule about its centre: a cylinder and two hemispheres (parallel axis)."""
    v_cyl = math.pi * radius * radius * length
    v_hemi = 2.0 / 3.0 * math.pi * radius ** 3
    total = v_cyl + 2.0 * v_hemi
    m_cyl = mass * v_cyl / total
    m_hemi = mass * v_hemi / total
    axial = 0.5 * m_cyl * radius ** 2 + 2.0 * (0.4 * m_hemi * radius ** 2)
    transverse = m_cyl * (3.0 * radius ** 2 + length ** 2) / 12.0
    # a hemisphere: 83/320 m r^2 about its own centre of mass, which sits 3 r / 8 from the flat face
    for _ in range(2):
        d = length / 2.0 + 3.0 * radius / 8.0
        transverse += m_hemi * 83.0 / 320.0 * radius ** 2 + m_hemi * d * d
    return (axial, transverse)


KINDS = ("hinge", "ball")


def limb(length, radius=None, mass=None, density=1000.0, kind="hinge", min_angle=None, max_angle=None):
    """A capsule limb along its bone: radius default 0.2 length, mass from the density when not given, a hinge
    (planar reference) or a ball joint to its parent, with angle limits in degrees."""
    if not length > 0.0:
        raise RagdollError("a limb's length is positive")
    if kind not in KINDS:
        raise RagdollError(f"a limb's joint is one of {KINDS}")
    radius = 0.2 * length if radius is None else radius
    if not radius > 0.0:
        raise RagdollError("a limb's radius is positive")
    if mass is None:
        mass = density * capsule_volume(radius, length)
    if not mass > 0.0:
        raise RagdollError("a limb's mass is positive")
    if (min_angle is None) != (max_angle is None):
        raise RagdollError("limits come as a pair")
    if min_angle is not None and min_angle > max_angle:
        raise RagdollError("minAngle is at most maxAngle")
    axial, transverse = capsule_inertia(mass, radius, length)
    return {"length": length, "radius": radius, "mass": mass, "d": length / 2.0, "I": transverse, "kind": kind,
            "min": None if min_angle is None else math.radians(min_angle),
            "max": None if max_angle is None else math.radians(max_angle)}


def chain(limbs, gravity=9.81, dt=1.0 / 240.0, stiffness=None, drive_damping=None, damping=0.0):
    """A planar chain of hinged limbs hanging from the origin (phi = 0 points down, along gravity).

    `stiffness` and `drive_damping` are the PD drive's per unit mass of the limb (defaults 50 and 5), `damping`
    the joint's own viscous damping (N m s / rad), all applied to every joint."""
    if not limbs:
        raise RagdollError("a ragdoll has a limb")
    if len(limbs) > MAX_LIMBS:
        raise RagdollError(f"{len(limbs)} limbs, and a ragdoll takes at most {MAX_LIMBS}")
    if not dt > 0.0:
        raise RagdollError("the step is positive")
    return {"limbs": tuple(limbs), "g": gravity, "dt": dt,
            "k": tuple((50.0 if stiffness is None else stiffness) * l["mass"] for l in limbs),
            "c": tuple((5.0 if drive_damping is None else drive_damping) * l["mass"] for l in limbs),
            "damping": damping}


def absolute(theta):
    out, total = [], 0.0
    for t in theta:
        total += t
        out.append(total)
    return tuple(out)


def relative(c, phi):
    return tuple(phi[i] - (phi[i - 1] if i > 0 else 0.0) for i in range(len(phi)))


def _lever(c, k, i):
    """The lever of joint i on the centre of limb k: L_i for i < k, d_k for i = k, 0 beyond."""
    if i < k:
        return c["limbs"][i]["length"]
    if i == k:
        return c["limbs"][k]["d"]
    return 0.0


def mass_matrix(c, phi):
    n = len(phi)
    e = [(math.cos(p), -math.sin(p)) for p in phi]
    M = [[0.0] * n for _ in range(n)]
    for i in range(n):
        M[i][i] += c["limbs"][i]["I"]
        for j in range(n):
            ee = e[i][0] * e[j][0] + e[i][1] * e[j][1]
            M[i][j] += sum(c["limbs"][k]["mass"] * _lever(c, k, i) * _lever(c, k, j) * ee for k in range(n))
    return M


def _solve(M, b):
    n = len(b)
    A = [row[:] + [b[i]] for i, row in enumerate(M)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(A[r][col]))
        A[col], A[pivot] = A[pivot], A[col]
        for r in range(col + 1, n):
            f = A[r][col] / A[col][col]
            for k in range(col, n + 1):
                A[r][k] -= f * A[col][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (A[r][n] - sum(A[r][k] * x[k] for k in range(r + 1, n))) / A[r][r]
    return x


def accelerations(c, phi, omega, torques):
    """phi'' from Lagrange: M phi'' = Q - M' phi' + dT/dphi, with the joint torques as generalized forces."""
    n = len(phi)
    nrm = [(math.sin(p), math.cos(p)) for p in phi]
    e = [(math.cos(p), -math.sin(p)) for p in phi]
    m = [l["mass"] for l in c["limbs"]]
    cdot = []
    for k in range(n):
        vx = sum(_lever(c, k, j) * e[j][0] * omega[j] for j in range(n))
        vy = sum(_lever(c, k, j) * e[j][1] * omega[j] for j in range(n))
        cdot.append((vx, vy))
    Q = []
    for i in range(n):
        q = sum(m[k] * _lever(c, k, i) * c["g"] * e[i][1] for k in range(n))      # gravity along +y
        q += torques[i] - (torques[i + 1] if i + 1 < n else 0.0)
        # - M' phi'
        for j in range(n):
            ne = nrm[i][0] * e[j][0] + nrm[i][1] * e[j][1]
            en = e[i][0] * nrm[j][0] + e[i][1] * nrm[j][1]
            q -= sum(m[k] * _lever(c, k, i) * _lever(c, k, j) for k in range(n)) * (-omega[i] * ne - omega[j] * en) * omega[j]
        # + dT/dphi
        q += -omega[i] * sum(m[k] * _lever(c, k, i) * (cdot[k][0] * nrm[i][0] + cdot[k][1] * nrm[i][1]) for k in range(n))
        Q.append(q)
    return _solve(mass_matrix(c, phi), Q)


def drive_torque(k, c, w, theta_anim, theta, omega_anim, omega):
    """The PD drive toward the animated pose, scaled by 1 - blend."""
    if not 0.0 <= w <= 1.0:
        raise RagdollError("blend is between 0 and 1")
    return (1.0 - w) * (k * (theta_anim - theta) + c * (omega_anim - omega))


def blend_angle(theta_anim, theta, w):
    return (1.0 - w) * theta_anim + w * theta


def state(c, theta, omega=None):
    n = len(c["limbs"])
    if len(theta) != n:
        raise RagdollError("an angle for every limb")
    return {"phi": absolute(theta), "omega": tuple(omega) if omega is not None else (0.0,) * n, "step": 0}


def swing_animation(amplitudes, frequencies):
    """The relative angles amplitude_i sin(frequency_i t), a pose per limb."""
    return lambda t: [a * math.sin(f * t) for a, f in zip(amplitudes, frequencies)]


def _limits(c, phi, omega):
    phi, omega = list(phi), list(omega)
    n = len(phi)
    for i in range(n):
        lo, hi = c["limbs"][i]["min"], c["limbs"][i]["max"]
        if lo is None:
            continue
        theta = phi[i] - (phi[i - 1] if i > 0 else 0.0)
        target = min(max(theta, lo), hi)
        if target != theta:
            rel = omega[i] - (omega[i - 1] if i > 0 else 0.0)
            for j in range(i, n):
                phi[j] += target - theta
                omega[j] -= rel
    return tuple(phi), tuple(omega)


def _torques(c, phi, omega, w, ta, tb):
    """The joint torques at a state: the PD drive toward the animated pose (when there is one) and the joint damping."""
    n = len(phi)
    theta, theta_dot = relative(c, phi), relative(c, omega)
    dt = c["dt"]
    out = []
    for i in range(n):
        tau = -c["damping"] * theta_dot[i]
        if ta is not None:
            tau += drive_torque(c["k"][i], c["c"][i], w, ta[i], theta[i], (ta[i] - tb[i]) / dt, theta_dot[i])
        out.append(tau)
    return out


def step(c, st, w, anim=None):
    """One step of the chain: kinematic at blend 0; else the classical Runge-Kutta step of the Lagrangian dynamics
    with the drive and the damping, then the limits."""
    if not 0.0 <= w <= 1.0:
        raise RagdollError("blend is between 0 and 1")
    n = len(c["limbs"])
    dt = c["dt"]
    if w == 0.0:
        if anim is None:
            raise RagdollError("a kinematic ragdoll follows an animation")
        phi_next = absolute(anim((st["step"] + 1) * dt))
        omega = tuple((phi_next[i] - st["phi"][i]) / dt for i in range(n))
        return {"phi": phi_next, "omega": omega, "step": st["step"] + 1}
    ta, tb = (anim(st["step"] * dt), anim((st["step"] - 1) * dt)) if anim is not None else (None, None)

    def rates(phi, omega):
        return omega, accelerations(c, phi, omega, _torques(c, phi, omega, w, ta, tb))

    phi0, omega0 = st["phi"], st["omega"]
    k1 = rates(phi0, omega0)
    k2 = rates(tuple(phi0[i] + 0.5 * dt * k1[0][i] for i in range(n)), tuple(omega0[i] + 0.5 * dt * k1[1][i] for i in range(n)))
    k3 = rates(tuple(phi0[i] + 0.5 * dt * k2[0][i] for i in range(n)), tuple(omega0[i] + 0.5 * dt * k2[1][i] for i in range(n)))
    k4 = rates(tuple(phi0[i] + dt * k3[0][i] for i in range(n)), tuple(omega0[i] + dt * k3[1][i] for i in range(n)))
    phi = tuple(phi0[i] + dt / 6.0 * (k1[0][i] + 2.0 * k2[0][i] + 2.0 * k3[0][i] + k4[0][i]) for i in range(n))
    omega = tuple(omega0[i] + dt / 6.0 * (k1[1][i] + 2.0 * k2[1][i] + 2.0 * k3[1][i] + k4[1][i]) for i in range(n))
    phi, omega = _limits(c, phi, omega)
    return {"phi": phi, "omega": omega, "step": st["step"] + 1}


def run(c, steps, w, anim=None, st=None):
    if steps < 0 or steps > MAX_STEPS:
        raise RagdollError(f"{steps} steps, and a run takes at most {MAX_STEPS}")
    if st is None:
        st = state(c, anim(0.0) if anim is not None else [0.0] * len(c["limbs"]))
    for _ in range(steps):
        st = step(c, st, w, anim)
    return st


def drawn(st, theta_anim, w):
    """The drawn relative angles: the animation and the simulation blended by w."""
    theta = relative(None, st["phi"])
    return tuple(blend_angle(a, s, w) for a, s in zip(theta_anim, theta))


def energy(c, st):
    n = len(c["limbs"])
    phi, omega = st["phi"], st["omega"]
    e = [(math.cos(p), -math.sin(p)) for p in phi]
    total = 0.0
    y = 0.0
    x = 0.0
    for k in range(n):
        l = c["limbs"][k]
        vx = sum(_lever(c, k, j) * e[j][0] * omega[j] for j in range(n))
        vy = sum(_lever(c, k, j) * e[j][1] * omega[j] for j in range(n))
        cy = y + l["d"] * math.cos(phi[k])
        total += 0.5 * l["mass"] * (vx * vx + vy * vy) + 0.5 * l["I"] * omega[k] ** 2 - l["mass"] * c["g"] * cy
        x += l["length"] * math.sin(phi[k])
        y += l["length"] * math.cos(phi[k])
    return total


def energy_scale(c):
    return sum(l["mass"] for l in c["limbs"]) * c["g"] * sum(l["length"] for l in c["limbs"])


def pendulum_period(l, g=9.81):
    return 2.0 * math.pi * math.sqrt((l["I"] + l["mass"] * l["d"] ** 2) / (l["mass"] * g * l["d"]))


def measured_period(l, amplitude, dt, steps=1600):
    c = chain([l], dt=dt)
    st = state(c, [amplitude])
    crossings = []
    prev = st["phi"][0]
    for n in range(1, steps + 1):
        st = step(c, st, 1.0)
        cur = st["phi"][0]
        if prev < 0.0 <= cur:
            crossings.append((n - 1 + (-prev) / (cur - prev)) * dt)
        prev = cur
    if len(crossings) < 2:
        raise RagdollError("the run is too short for a period")
    return (crossings[-1] - crossings[0]) / (len(crossings) - 1)


def period_test():
    l = limb(1.0, mass=1.0, radius=0.05)
    return abs(measured_period(l, 0.02, 1.0 / 240.0) / pendulum_period(l) - 1.0)


def energy_test(steps=1600):
    """The worst energy error over 1600 steps of 1/240 s of a violent double pendulum, over the energy scale m g L."""
    c = chain([limb(1.0, mass=1.0), limb(0.8, mass=0.5)], dt=1.0 / 240.0)
    st = state(c, [1.0, 2.0])
    e0 = energy(c, st)
    worst = 0.0
    for _ in range(steps):
        st = step(c, st, 1.0)
        worst = max(worst, abs(energy(c, st) - e0))
    return worst / energy_scale(c)


def settled_angle(l, k, w, theta_anim, g=9.81):
    """Where the drive (1 - w) k (theta_anim - theta) balances the weight m g d sin(theta): a bisection."""
    if not 0.0 <= w <= 1.0:
        raise RagdollError("blend is between 0 and 1")
    if w == 1.0:
        return 0.0
    f = lambda th: (1.0 - w) * k * (theta_anim - th) - l["mass"] * g * l["d"] * math.sin(th)
    lo, hi = (0.0, theta_anim) if theta_anim >= 0.0 else (theta_anim, 0.0)
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if (f(lo) <= 0.0) == (f(mid) <= 0.0):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def settle_test(steps=2400):
    l = limb(1.0, mass=1.0, radius=0.05)
    k, w = 20.0, 0.5
    c = chain([l], dt=1.0 / 240.0, stiffness=k / l["mass"])
    st = run(c, steps, w, lambda t: [1.0])
    return abs(relative(c, st["phi"])[0] - settled_angle(l, k, w, 1.0))


def limit_test():
    l = limb(1.0, mass=1.0, radius=0.05, min_angle=-30.0, max_angle=30.0)
    c = chain([l], dt=1.0 / 240.0)
    st = state(c, [1.0])
    inside, stopped = True, False
    for _ in range(600):
        st = step(c, st, 1.0)
        th = relative(c, st["phi"])[0]
        inside = inside and math.radians(-30.0) - 1e-12 <= th <= math.radians(30.0) + 1e-12
        if abs(th - math.radians(30.0)) <= 1e-12 and st["omega"][0] == 0.0:
            stopped = True
    return (inside, stopped)


def seek_test():
    c = chain([limb(1.0), limb(0.7)], dt=1.0 / 240.0)
    anim = swing_animation((0.2, -0.4), (1.5, 2.0))
    a = run(c, 120, 0.5, anim)
    b = run(c, 60, 0.5, anim, run(c, 60, 0.5, anim))
    k = run(c, 30, 0.0, anim)
    return (a == b, k["phi"] == absolute(anim(30 * c["dt"])))


# ---------------------------------------------------------------------------------------------------- 4. interchange

BODY_KINDS = ("static", "kinematic", "dynamic")
SHAPES = ("box", "sphere", "capsule", "cylinder", "cone")
MESH_SHAPES = ("auto", "convex-hull", "trimesh", "decomposition")
JOINT_KINDS = ("spring", "distance", "pin", "rope", "hinge", "slider", "weld", "motor", "ball")
BODY_DEFAULTS = {"kind": "dynamic", "shape": "box", "mass": 1.0, "density": None, "friction": 0.5, "restitution": 0.0,
                 "linear_damping": 0.01, "angular_damping": 0.01, "velocity": (0.0, 0.0, 0.0),
                 "angular_velocity": (0.0, 0.0, 0.0), "group": 0, "collides_with": "all", "sensor": False,
                 "fixed_rotation": False, "bullet": False, "activate_at": 0.0, "pos": (0.0, 0.0, 0.0),
                 "rot": (0.0, 0.0, 0.0, 1.0)}


def body(id, **kw):
    """A rigidBody3D of SREP 11 on an object3D: `size` is the primitive's (width, height, depth) in pixels."""
    unknown = set(kw) - set(BODY_DEFAULTS) - {"size"}
    if unknown:
        raise InterchangeError(f"unknown body attributes {sorted(unknown)}")
    b = {"id": id, "size": tuple(kw.get("size", (100.0, 100.0, 100.0)))}
    for k, v in BODY_DEFAULTS.items():
        b[k] = kw.get(k, v)
    if b["kind"] not in BODY_KINDS:
        raise InterchangeError(f"a body is one of {BODY_KINDS}")
    if b["shape"] not in SHAPES + MESH_SHAPES:
        raise InterchangeError(f"a shape is one of {SHAPES + MESH_SHAPES}")
    if "density" in kw and "mass" not in kw:
        b["mass"] = None
    if b["mass"] is not None and b["density"] is not None:
        raise InterchangeError("mass or density, not both")
    for k in ("velocity", "angular_velocity", "pos"):
        b[k] = tuple(float(x) for x in b[k])
    b["rot"] = tuple(float(x) for x in b["rot"])
    if b["collides_with"] != "all":
        b["collides_with"] = tuple(sorted(int(g) for g in b["collides_with"]))
    return b


def constraint(id, kind, a, b=None, anchor=None, axis=None, rest_length=None, stiffness=None, damping=None,
               min_angle=None, max_angle=None, motor_speed=0.0, max_force=None, break_force=None):
    if kind not in JOINT_KINDS:
        raise InterchangeError(f"a constraint is one of {JOINT_KINDS}")
    if kind == "pin":
        if b is not None:
            raise InterchangeError("a pin has no b (C9)")
        if anchor is None:
            raise InterchangeError("a pin's anchor is given (C10)")
    if kind in ("spring", "distance", "rope", "weld") and anchor is not None:
        raise InterchangeError(f"a {kind} does not use the anchor")
    if (min_angle is None) != (max_angle is None):
        raise InterchangeError("limits come as a pair (only one given, there is no limit)")
    if axis is None:
        axis = (1.0, 0.0, 0.0) if kind == "slider" else (0.0, 0.0, 1.0)
    axis = tuple(float(x) for x in axis)
    if _norm(axis) == 0.0:
        axis = (1.0, 0.0, 0.0)
    return {"id": id, "kind": kind, "a": a, "b": b, "anchor": None if anchor is None else tuple(float(x) for x in anchor),
            "axis": axis, "rest_length": rest_length, "stiffness": stiffness, "damping": damping,
            "min": min_angle, "max": max_angle, "motor_speed": float(motor_speed), "max_force": max_force,
            "break_force": break_force}


def world(bodies, constraints, ppm=100.0, gravity=(0.0, -9.80665, 0.0), fixed_step=1.0 / 120.0, iterations=8,
          start=0.0, bounds="none", frame=(1920.0, 1080.0)):
    if len(bodies) > MAX_BODIES:
        raise InterchangeError(f"{len(bodies)} bodies, and a world takes at most {MAX_BODIES}")
    if len(constraints) > MAX_CONSTRAINTS:
        raise InterchangeError(f"{len(constraints)} constraints, and a world takes at most {MAX_CONSTRAINTS}")
    ids = [b["id"] for b in bodies]
    if len(set(ids)) != len(ids):
        raise InterchangeError("body ids are unique")
    for c in constraints:
        for end in ("a", "b"):
            if c[end] is not None and c[end] not in ids:
                raise InterchangeError(f"constraint {c['id']} names no body {c[end]!r}")
    if bounds not in ("none", "floor", "frame"):
        raise InterchangeError("bounds is none, floor or frame")
    return {"ppm": float(ppm), "gravity": tuple(float(g) for g in gravity), "fixed_step": fixed_step,
            "iterations": iterations, "start": start, "bounds": bounds, "frame": tuple(float(f) for f in frame),
            "bodies": list(bodies), "constraints": list(constraints)}


def to_metres(v, ppm):
    """A scene vector (x, y down, z away) in pixels to the physics frame (x, y up, z toward the camera) in metres."""
    return (v[0] / ppm, -v[1] / ppm, -v[2] / ppm)


def to_pixels(v, ppm):
    """The inverse of to_metres, rounded to a nanopixel so that a round trip returns the document's numbers."""
    return (round(v[0] * ppm, 9), round(-v[1] * ppm, 9), round(-v[2] * ppm, 9))


def flip_vec(v):
    return (v[0], -v[1], -v[2])


def flip_quat(q):
    return (q[0], -q[1], -q[2], q[3])


def quat_conj(q):
    return (-q[0], -q[1], -q[2], q[3])


def quat_mul(p, q):
    px, py, pz, pw = p
    qx, qy, qz, qw = q
    return (pw * qx + px * qw + py * qz - pz * qy, pw * qy - px * qz + py * qw + pz * qx,
            pw * qz + px * qy - py * qx + pz * qw, pw * qw - px * qx - py * qy - pz * qz)


def rotate(q, v):
    return quat_mul(quat_mul(q, (v[0], v[1], v[2], 0.0)), quat_conj(q))[:3]


def rotation_between(a, b):
    """The shortest-arc rotation taking unit `a` onto unit `b`; antiparallel axes turn 180 degrees about the next axis."""
    d = _dot(a, b)
    if d > 1.0 - 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    if d < -1.0 + 1e-12:
        k = max(range(3), key=lambda i: abs(a[i]))
        axis = [0.0, 0.0, 0.0]
        axis[(k + 1) % 3] = 1.0
        return (axis[0], axis[1], axis[2], 0.0)
    c = _cross(a, b)
    w = 1.0 + d
    n = math.sqrt(c[0] ** 2 + c[1] ** 2 + c[2] ** 2 + w * w)
    return (c[0] / n, c[1] / n, c[2] / n, w / n)


def shape_volume(shape, size):
    """The volume of a primitive shape in metres from its (width, height, depth)."""
    w, h, d = size
    if shape == "box":
        return w * h * d
    if shape == "sphere":
        return 4.0 / 3.0 * math.pi * (w / 2.0) ** 3
    if shape == "capsule":
        return capsule_volume(w / 2.0, h - w)
    if shape == "cylinder":
        return math.pi * (w / 2.0) ** 2 * h
    if shape == "cone":
        return math.pi * (w / 2.0) ** 2 * h / 3.0
    raise InterchangeError(f"the volume of a {shape} needs the object's triangles")


def body_mass(b, ppm):
    if b["mass"] is not None:
        return b["mass"]
    return b["density"] * shape_volume(b["shape"], tuple(s / ppm for s in b["size"]))


def _check_shape(b):
    if b["shape"] in MESH_SHAPES:
        raise InterchangeError(f"body {b['id']}: a {b['shape']} collider needs the object's triangles (the engine writes "
                               "PhysicsMeshCollisionAPI); the reference covers the primitive shapes")
    w, h, d = b["size"]
    if b["shape"] == "sphere" and not (w == h == d):
        raise InterchangeError(f"body {b['id']}: a sphere's size is one diameter on every axis")
    if b["shape"] in ("capsule", "cylinder", "cone") and w != d:
        raise InterchangeError(f"body {b['id']}: a {b['shape']} is round: width equals depth")
    if b["shape"] == "capsule" and h < w:
        raise InterchangeError(f"body {b['id']}: a capsule is at least as tall as it is wide")


AXIS_TOKENS = ("X", "Y", "Z")


def _joint_frame(axis_scene):
    """The joint frame of a scene axis: the USD axis token and the rotation that takes the token's axis onto it."""
    a = flip_vec(axis_scene)
    n = _norm(a)
    a = _scale(a, 1.0 / n)
    k = max(range(3), key=lambda i: abs(a[i]))
    aligned = all(abs(a[i]) < 1e-12 for i in range(3) if i != k)
    token_index = k if aligned else 0
    unit = [0.0, 0.0, 0.0]
    unit[token_index] = 1.0
    return AXIS_TOKENS[token_index], rotation_between(tuple(unit), a)


def _bodies_by_id(w):
    return {b["id"]: b for b in w["bodies"]}


def _anchor_scene(c, bodies):
    if c["anchor"] is not None:
        return c["anchor"]
    if c["b"] is not None and c["kind"] not in ("pin",):
        return bodies[c["b"]]["pos"]
    return bodies[c["a"]]["pos"]


def _local(b, point_m, ppm):
    """A physics-frame point in the frame of body b at the start."""
    q = flip_quat(b["rot"])
    return rotate(quat_conj(q), _sub(point_m, to_metres(b["pos"], ppm)))


def _num(x):
    return float(x)


def to_usd(w):
    """A UsdPhysics stage: {prim path: {"type", "apiSchemas", attributes...}} in metres, y up (SREP 11's physics frame)."""
    ppm = w["ppm"]
    stage = {"/": {"metersPerUnit": 1.0, "upAxis": "Y"}}
    g = w["gravity"]
    gn = _norm(g)
    stage["/World/PhysicsScene"] = {
        "type": "PhysicsScene",
        "physics:gravityDirection": _scale(g, 1.0 / gn) if gn > 0.0 else (0.0, -1.0, 0.0),
        "physics:gravityMagnitude": gn,
        "customData": {"sr:pixelsPerMeter": ppm, "sr:fixedStep": w["fixed_step"], "sr:solverIterations": w["iterations"],
                       "sr:start": w["start"], "sr:bounds": w["bounds"], "sr:frame": w["frame"]}}
    groups = sorted({b["group"] for b in w["bodies"]})
    for b in w["bodies"]:
        _check_shape(b)
        path = f"/World/{b['id']}"
        prim = {"apiSchemas": ("PhysicsRigidBodyAPI", "PhysicsMassAPI", "PhysicsCollisionAPI")}
        size_m = tuple(s / ppm for s in b["size"])
        wd, ht, dp = size_m
        if b["shape"] == "box":
            prim.update({"type": "Cube", "size": 1.0, "xformOp:scale": size_m})
        elif b["shape"] == "sphere":
            prim.update({"type": "Sphere", "radius": wd / 2.0})
        elif b["shape"] == "capsule":
            prim.update({"type": "Capsule", "radius": wd / 2.0, "height": ht - wd, "axis": "Y"})
        elif b["shape"] == "cylinder":
            prim.update({"type": "Cylinder", "radius": wd / 2.0, "height": ht, "axis": "Y"})
        else:
            prim.update({"type": "Cone", "radius": wd / 2.0, "height": ht, "axis": "Y"})
        prim["xformOp:translate"] = to_metres(b["pos"], ppm)
        q = flip_quat(b["rot"])
        prim["xformOp:orient"] = (q[3], q[0], q[1], q[2])
        prim["physics:rigidBodyEnabled"] = b["kind"] != "static"
        prim["physics:kinematicEnabled"] = b["kind"] == "kinematic"
        if b["mass"] is not None:
            prim["physics:mass"] = _num(b["mass"])
        else:
            prim["physics:density"] = _num(b["density"])
        prim["physics:velocity"] = to_metres(b["velocity"], ppm)
        prim["physics:angularVelocity"] = flip_vec(b["angular_velocity"])
        prim["material:binding:physics"] = f"/World/Materials/{b['id']}"
        stage[f"/World/Materials/{b['id']}"] = {"type": "Material", "apiSchemas": ("PhysicsMaterialAPI",),
                                                "physics:staticFriction": _num(b["friction"]),
                                                "physics:dynamicFriction": _num(b["friction"]),
                                                "physics:restitution": _num(b["restitution"])}
        prim["physics:collisionGroup"] = f"/World/Groups/g{b['group']}"
        custom = {}
        for key, name in (("linear_damping", "sr:linearDamping"), ("angular_damping", "sr:angularDamping"),
                          ("sensor", "sr:sensor"), ("fixed_rotation", "sr:fixedRotation"), ("bullet", "sr:bullet"),
                          ("activate_at", "sr:activateAt")):
            if b[key] != BODY_DEFAULTS[key]:
                custom[name] = b[key]
        if b["collides_with"] != "all":
            custom["sr:collidesWith"] = b["collides_with"]
        if custom:
            prim["customData"] = custom
        stage[path] = prim
    for gi in groups:
        members = tuple(f"/World/{b['id']}" for b in w["bodies"] if b["group"] == gi)
        # the groups a member does not collide with: USD filters pairs, so a group is filtered when any body of this group excludes it
        filtered = set()
        for b in w["bodies"]:
            if b["group"] == gi and b["collides_with"] != "all":
                filtered |= {gj for gj in groups if gj not in b["collides_with"]}
        prim = {"type": "PhysicsCollisionGroup", "collection:colliders:includes": members}
        if filtered:
            prim["physics:filteredGroups"] = tuple(f"/World/Groups/g{gj}" for gj in sorted(filtered))
        stage[f"/World/Groups/g{gi}"] = prim
    bodies = _bodies_by_id(w)
    for c in w["constraints"]:
        stage[f"/World/Joints/{c['id']}"] = _joint_to_usd(c, bodies, ppm)
    _bounds_to_usd(w, stage)
    return stage


def _bounds_to_usd(w, stage):
    ppm = w["ppm"]
    wf, hf = w["frame"][0] / ppm, w["frame"][1] / ppm
    if w["bounds"] == "floor":
        stage["/World/Ground"] = {"type": "Cube", "size": 1.0, "apiSchemas": ("PhysicsCollisionAPI",),
                                  "xformOp:scale": (20000.0, 5.0, 20000.0), "xformOp:translate": (wf / 2.0, -hf - 2.5, 0.0)}
    elif w["bounds"] == "frame":
        df = max(wf, hf)
        slabs = {"left": ((5.0, hf + 10.0, df + 10.0), (-2.5, -hf / 2.0, 0.0)),
                 "right": ((5.0, hf + 10.0, df + 10.0), (wf + 2.5, -hf / 2.0, 0.0)),
                 "top": ((wf + 10.0, 5.0, df + 10.0), (wf / 2.0, 2.5, 0.0)),
                 "bottom": ((wf + 10.0, 5.0, df + 10.0), (wf / 2.0, -hf - 2.5, 0.0)),
                 "back": ((wf + 10.0, hf + 10.0, 5.0), (wf / 2.0, -hf / 2.0, -df / 2.0 - 2.5)),
                 "front": ((wf + 10.0, hf + 10.0, 5.0), (wf / 2.0, -hf / 2.0, df / 2.0 + 2.5))}
        for name, (scale, pos) in slabs.items():
            stage[f"/World/Frame/{name}"] = {"type": "Cube", "size": 1.0, "apiSchemas": ("PhysicsCollisionAPI",),
                                             "xformOp:scale": scale, "xformOp:translate": pos}


USD_JOINT_TYPES = {"ball": "PhysicsSphericalJoint", "hinge": "PhysicsRevoluteJoint", "motor": "PhysicsRevoluteJoint",
                   "slider": "PhysicsPrismaticJoint", "weld": "PhysicsFixedJoint", "distance": "PhysicsDistanceJoint",
                   "rope": "PhysicsDistanceJoint", "spring": "PhysicsDistanceJoint", "pin": "PhysicsSphericalJoint"}


def _joint_to_usd(c, bodies, ppm):
    a, b = bodies[c["a"]], bodies.get(c["b"]) if c["b"] is not None else None
    prim = {"type": USD_JOINT_TYPES[c["kind"]], "physics:body0": f"/World/{c['a']}"}
    if b is not None:
        prim["physics:body1"] = f"/World/{c['b']}"
    anchor_m = to_metres(_anchor_scene(c, bodies), ppm)
    custom = {"sr:type": c["kind"]}
    unset = []
    if c["kind"] in ("spring", "distance", "rope"):
        frame_q = (0.0, 0.0, 0.0, 1.0)
        prim["physics:localPos0"] = (0.0, 0.0, 0.0)
        prim["physics:localPos1"] = (0.0, 0.0, 0.0)
        centres = _norm(_sub(to_metres(b["pos"], ppm), to_metres(a["pos"], ppm))) if b is not None else _norm(to_metres(a["pos"], ppm))
        length = centres if c["rest_length"] is None else c["rest_length"] / ppm
        if c["rest_length"] is None:
            unset.append("restLength")
        if c["kind"] != "rope":
            prim["physics:minDistance"] = length
        prim["physics:maxDistance"] = length
        if c["kind"] == "spring":
            for key, name in (("stiffness", "sr:stiffness"), ("damping", "sr:damping")):
                if c[key] is None:
                    unset.append(key)
                else:
                    custom[name] = c[key]
    else:
        token, frame_q = _joint_frame(c["axis"])
        if c["kind"] in ("hinge", "motor", "slider"):
            prim["physics:axis"] = token
        if c["kind"] in ("pin", "ball", "hinge", "motor", "slider") and c["anchor"] is None:
            unset.append("anchor")
        if c["kind"] == "weld":
            anchor_m = to_metres(b["pos"] if b is not None else a["pos"], ppm)
        prim["physics:localPos0"] = _local(a, anchor_m, ppm)
        q0 = quat_mul(quat_conj(flip_quat(a["rot"])), frame_q)
        prim["physics:localRot0"] = (q0[3], q0[0], q0[1], q0[2])
        if b is not None:
            prim["physics:localPos1"] = _local(b, anchor_m, ppm)
            q1 = quat_mul(quat_conj(flip_quat(b["rot"])), frame_q)
            prim["physics:localRot1"] = (q1[3], q1[0], q1[1], q1[2])
        else:
            prim["physics:localPos1"] = anchor_m
            prim["physics:localRot1"] = (frame_q[3], frame_q[0], frame_q[1], frame_q[2])
        if c["kind"] == "pin" and c["stiffness"] is not None:
            prim["type"] = "PhysicsDistanceJoint"
            prim["physics:minDistance"] = 0.0
            prim["physics:maxDistance"] = 0.0
            custom["sr:stiffness"] = c["stiffness"]
            if c["damping"] is None:
                unset.append("damping")
            else:
                custom["sr:damping"] = c["damping"]
        if c["min"] is not None:
            scale = 1.0 / ppm if c["kind"] == "slider" else 1.0
            prim["physics:lowerLimit"] = c["min"] * scale
            prim["physics:upperLimit"] = c["max"] * scale
        if c["kind"] == "motor":
            prim["apiSchemas"] = ("PhysicsDriveAPI:angular",)
            prim["drive:angular:physics:type"] = "acceleration"
            prim["drive:angular:physics:targetVelocity"] = c["motor_speed"]
            if c["max_force"] is not None:
                prim["drive:angular:physics:maxForce"] = c["max_force"]
    if c["break_force"] is not None:
        prim["physics:breakForce"] = c["break_force"]
    custom["sr:axis"] = c["axis"]
    if unset:
        custom["sr:unset"] = tuple(unset)
    prim["customData"] = custom
    return prim


USD_BODY_TYPES = {"Cube": "box", "Sphere": "sphere", "Capsule": "capsule", "Cylinder": "cylinder", "Cone": "cone"}
USD_BODY_KEYS = {"type", "apiSchemas", "customData", "size", "radius", "height", "axis", "xformOp:scale",
                 "xformOp:translate", "xformOp:orient", "physics:rigidBodyEnabled", "physics:kinematicEnabled",
                 "physics:mass", "physics:density", "physics:velocity", "physics:angularVelocity",
                 "material:binding:physics", "physics:collisionGroup", "physics:collisionEnabled"}
USD_JOINT_KEYS = {"type", "apiSchemas", "customData", "physics:body0", "physics:body1", "physics:localPos0",
                  "physics:localPos1", "physics:localRot0", "physics:localRot1", "physics:axis", "physics:lowerLimit",
                  "physics:upperLimit", "physics:minDistance", "physics:maxDistance", "physics:breakForce",
                  "physics:breakTorque", "physics:jointEnabled", "physics:collisionEnabled",
                  "drive:angular:physics:type", "drive:angular:physics:targetVelocity", "drive:angular:physics:maxForce"}
USD_MATERIAL_KEYS = {"type", "apiSchemas", "physics:staticFriction", "physics:dynamicFriction", "physics:restitution",
                     "physics:density"}
USD_GROUP_KEYS = {"type", "apiSchemas", "collection:colliders:includes", "physics:filteredGroups"}
USD_SCENE_KEYS = {"type", "apiSchemas", "customData", "physics:gravityDirection", "physics:gravityMagnitude"}


def _check_keys(path, prim, allowed):
    extra = set(prim) - allowed
    if extra:
        raise InterchangeError(f"{path}: the format has no reading of {sorted(extra)}")


def from_usd(stage):
    """A world from a UsdPhysics stage; foreign stages fill the format's defaults, and what has no reading is an error."""
    root = stage.get("/", {})
    mpu = float(root.get("metersPerUnit", 1.0))
    if root.get("upAxis", "Y") != "Y":
        raise InterchangeError("the stage is not y-up; the reference does not re-orient a z-up stage (open issue 2)")
    scene_prims = [p for p, v in stage.items() if v.get("type") == "PhysicsScene"]
    scene_custom = stage[scene_prims[0]].get("customData", {}) if scene_prims else {}
    ppm = float(scene_custom.get("sr:pixelsPerMeter", 100.0))
    if scene_prims:
        prim = stage[scene_prims[0]]
        _check_keys(scene_prims[0], prim, USD_SCENE_KEYS)
        direction = prim.get("physics:gravityDirection", (0.0, -1.0, 0.0))
        magnitude = prim.get("physics:gravityMagnitude", 9.80665)
        gravity = tuple(d * magnitude for d in direction)
    else:
        gravity = (0.0, -9.80665, 0.0)
    bounds = scene_custom.get("sr:bounds", "none")
    materials = {}
    groups = {}
    bodies = []
    joints = []
    for path, prim in stage.items():
        if path == "/" or path in scene_prims:
            continue
        kind = prim.get("type")
        if bounds == "floor" and path == "/World/Ground" or bounds == "frame" and path.startswith("/World/Frame/"):
            continue
        if kind == "Material":
            _check_keys(path, prim, USD_MATERIAL_KEYS)
            materials[path] = prim
        elif kind == "PhysicsCollisionGroup":
            _check_keys(path, prim, USD_GROUP_KEYS)
            groups[path] = prim
        elif kind in USD_BODY_TYPES:
            bodies.append((path, prim))
        elif kind in USD_JOINT_TYPES.values():
            joints.append((path, prim))
        elif kind == "PhysicsJoint":
            raise InterchangeError(f"{path}: a generic PhysicsJoint (six limits) has no reading in the format")
        else:
            raise InterchangeError(f"{path}: the format has no reading of a {kind} prim")
    out_bodies = []
    for path, prim in bodies:
        _check_keys(path, prim, USD_BODY_KEYS)
        apis = prim.get("apiSchemas", ())
        shape = USD_BODY_TYPES[prim["type"]]
        if shape == "box":
            size_m = tuple(s * prim.get("size", 2.0) * mpu for s in prim.get("xformOp:scale", (1.0, 1.0, 1.0)))
        else:
            r = prim["radius"] * mpu
            if shape == "sphere":
                size_m = (2 * r, 2 * r, 2 * r)
            elif shape == "capsule":
                size_m = (2 * r, prim["height"] * mpu + 2 * r, 2 * r)
            else:
                size_m = (2 * r, prim["height"] * mpu, 2 * r)
            if shape != "sphere" and prim.get("axis", "Z") != "Y":
                raise InterchangeError(f"{path}: a round shape is upright along y in the format")
        if "PhysicsRigidBodyAPI" not in apis or not prim.get("physics:rigidBodyEnabled", True):
            kind = "static"
        elif prim.get("physics:kinematicEnabled", False):
            kind = "kinematic"
        else:
            kind = "dynamic"
        mass = prim.get("physics:mass")
        density = prim.get("physics:density")
        material = materials.get(prim.get("material:binding:physics"), {})
        if mass is None and density is None:
            density = material.get("physics:density", 1000.0)
        custom = prim.get("customData", {})
        group_path = prim.get("physics:collisionGroup")
        group = int(group_path.rsplit("/g", 1)[1]) if group_path else 0
        if "sr:collidesWith" in custom:
            collides = tuple(custom["sr:collidesWith"])
        elif group_path and groups.get(group_path, {}).get("physics:filteredGroups"):
            filtered = {int(p.rsplit("/g", 1)[1]) for p in groups[group_path]["physics:filteredGroups"]}
            collides = tuple(sorted(int(p.rsplit("/g", 1)[1]) for p in groups if int(p.rsplit("/g", 1)[1]) not in filtered))
        else:
            collides = "all"
        q = prim.get("xformOp:orient", (1.0, 0.0, 0.0, 0.0))
        b = body(path.rsplit("/", 1)[1], kind=kind, shape=shape, size=to_pixels_size(size_m, ppm),
                 friction=material.get("physics:staticFriction", 0.5), restitution=material.get("physics:restitution", 0.0),
                 velocity=to_pixels(_scale(prim.get("physics:velocity", (0.0, 0.0, 0.0)), mpu), ppm),
                 angular_velocity=flip_vec(prim.get("physics:angularVelocity", (0.0, 0.0, 0.0))),
                 pos=to_pixels(_scale(prim.get("xformOp:translate", (0.0, 0.0, 0.0)), mpu), ppm),
                 rot=flip_quat((q[1], q[2], q[3], q[0])), group=group, collides_with=collides,
                 linear_damping=custom.get("sr:linearDamping", 0.01), angular_damping=custom.get("sr:angularDamping", 0.01),
                 sensor=custom.get("sr:sensor", False), fixed_rotation=custom.get("sr:fixedRotation", False),
                 bullet=custom.get("sr:bullet", False), activate_at=custom.get("sr:activateAt", 0.0),
                 **({"mass": mass} if mass is not None else {"density": density}))
        out_bodies.append(b)
    by_id = {b["id"]: b for b in out_bodies}
    out_joints = [_joint_from_usd(path, prim, by_id, ppm, mpu) for path, prim in joints]
    return world(out_bodies, out_joints, ppm=ppm, gravity=gravity, fixed_step=scene_custom.get("sr:fixedStep", 1.0 / 120.0),
                 iterations=scene_custom.get("sr:solverIterations", 8), start=scene_custom.get("sr:start", 0.0),
                 bounds=bounds, frame=tuple(scene_custom.get("sr:frame", (1920.0, 1080.0))))


def to_pixels_size(size_m, ppm):
    return tuple(round(s * ppm, 9) for s in size_m)


def _joint_from_usd(path, prim, by_id, ppm, mpu):
    _check_keys(path, prim, USD_JOINT_KEYS)
    custom = prim.get("customData", {})
    unset = set(custom.get("sr:unset", ()))
    a_id = prim["physics:body0"].rsplit("/", 1)[1]
    b_id = prim["physics:body1"].rsplit("/", 1)[1] if "physics:body1" in prim else None
    if a_id not in by_id or (b_id is not None and b_id not in by_id):
        raise InterchangeError(f"{path}: the joint names a body the stage has not")
    kind = custom.get("sr:type")
    t = prim["type"]
    if kind is None:
        kind = {"PhysicsSphericalJoint": "ball", "PhysicsRevoluteJoint": "hinge", "PhysicsPrismaticJoint": "slider",
                "PhysicsFixedJoint": "weld", "PhysicsDistanceJoint": "distance"}[t]
        if t == "PhysicsRevoluteJoint" and "drive:angular:physics:targetVelocity" in prim:
            kind = "motor"
        if t == "PhysicsSphericalJoint" and b_id is None:
            kind = "pin"
    has_limit = ("physics:lowerLimit" in prim) + ("physics:upperLimit" in prim)
    if has_limit == 1:
        raise InterchangeError(f"{path}: a limit is a pair; the format has no one-sided limit")
    a = by_id[a_id]
    kw = {"motor_speed": prim.get("drive:angular:physics:targetVelocity", 0.0),
          "max_force": prim.get("drive:angular:physics:maxForce"), "break_force": prim.get("physics:breakForce")}
    if kind in ("spring", "distance", "rope"):
        if "restLength" not in unset:
            kw["rest_length"] = round(prim["physics:maxDistance"] * mpu * ppm, 9)
        if kind == "spring":
            kw["stiffness"] = custom.get("sr:stiffness")
            kw["damping"] = custom.get("sr:damping")
    else:
        if "anchor" not in unset:
            q0 = prim.get("physics:localRot0", (1.0, 0.0, 0.0, 0.0))
            world_anchor = _add(rotate(flip_quat(a["rot"]), _scale(prim["physics:localPos0"], mpu)), to_metres(a["pos"], ppm))
            if kind != "weld":
                kw["anchor"] = tuple(round(x, 9) for x in to_pixels(world_anchor, ppm))
        if kind == "pin" and t == "PhysicsDistanceJoint":
            kw["stiffness"] = custom.get("sr:stiffness")
            kw["damping"] = custom.get("sr:damping")
        if has_limit == 2:
            scale = mpu * ppm if kind == "slider" else 1.0
            kw["min_angle"] = round(prim["physics:lowerLimit"] * scale, 9)
            kw["max_angle"] = round(prim["physics:upperLimit"] * scale, 9)
    if "sr:axis" in custom:
        kw["axis"] = tuple(custom["sr:axis"])
    elif "physics:axis" in prim:
        q0 = prim.get("physics:localRot0", (1.0, 0.0, 0.0, 0.0))
        unit = [0.0, 0.0, 0.0]
        unit[AXIS_TOKENS.index(prim["physics:axis"])] = 1.0
        axis_physics = rotate(quat_mul(flip_quat(a["rot"]), (q0[1], q0[2], q0[3], q0[0])), tuple(unit))
        kw["axis"] = tuple(round(x, 12) for x in flip_vec(axis_physics))
    return constraint(path.rsplit("/", 1)[1], kind, a_id, b_id, **kw)


def round_trip_test():
    w = _sample_world()
    stage = to_usd(w)
    g = to_gltf(w)
    return (from_usd(stage) == w and to_usd(from_usd(stage)) == stage, from_gltf(g) == w and to_gltf(from_gltf(g)) == g)


def _sample_world():
    bodies = [
        body("crate", shape="box", size=(100.0, 50.0, 20.0), mass=2.0, friction=0.4, restitution=0.2,
             velocity=(10.0, -5.0, 2.0), angular_velocity=(0.0, 90.0, 0.0), pos=(300.0, 200.0, -50.0),
             rot=(0.0, math.sin(0.3), 0.0, math.cos(0.3)), group=1, collides_with=(0, 2)),
        body("ball", shape="sphere", size=(40.0, 40.0, 40.0), mass=0.5, pos=(100.0, 100.0, 0.0), sensor=True, bullet=True,
             activate_at=0.5, linear_damping=0.1),
        body("post", kind="static", shape="capsule", size=(20.0, 120.0, 20.0)),
        body("lid", kind="kinematic", shape="cylinder", size=(30.0, 10.0, 30.0), pos=(50.0, 10.0, 0.0), fixed_rotation=True),
        body("cone", shape="cone", size=(30.0, 40.0, 30.0), density=700.0, pos=(0.0, 300.0, 0.0)),
    ]
    constraints = [
        constraint("h", "hinge", "crate", "post", anchor=(300.0, 200.0, 0.0), axis=(0.0, 0.0, 1.0), min_angle=-45.0,
                   max_angle=45.0, break_force=100.0),
        constraint("m", "motor", "lid", "post", axis=(0.0, 1.0, 0.0), motor_speed=180.0, max_force=5.0),
        constraint("s", "slider", "ball", "crate", axis=(1.0, 0.0, 0.0), min_angle=-10.0, max_angle=20.0),
        constraint("w", "weld", "cone", "crate"),
        constraint("b", "ball", "ball", "lid", anchor=(10.0, 20.0, 30.0)),
        constraint("d", "distance", "crate", "ball", rest_length=50.0),
        constraint("r", "rope", "crate", "cone", rest_length=80.0),
        constraint("k", "spring", "ball", "cone", stiffness=30.0, damping=2.0, rest_length=10.0),
        constraint("p", "pin", "crate", anchor=(300.0, 200.0, 0.0)),
    ]
    return world(bodies, constraints, bounds="floor")


# ---- glTF


def _gltf_shape(b, ppm):
    wd, ht, dp = (s / ppm for s in b["size"])
    if b["shape"] == "box":
        return {"type": "box", "box": {"size": [wd, ht, dp]}}
    if b["shape"] == "sphere":
        return {"type": "sphere", "sphere": {"radius": wd / 2.0}}
    if b["shape"] == "capsule":
        return {"type": "capsule", "capsule": {"height": ht - wd, "radiusBottom": wd / 2.0, "radiusTop": wd / 2.0}}
    if b["shape"] == "cylinder":
        return {"type": "cylinder", "cylinder": {"height": ht, "radiusBottom": wd / 2.0, "radiusTop": wd / 2.0}}
    return {"type": "cylinder", "cylinder": {"height": ht, "radiusBottom": wd / 2.0, "radiusTop": 0.0}}


def _index_of(items, item):
    for i, x in enumerate(items):
        if x == item:
            return i
    items.append(item)
    return len(items) - 1


def _joint_limits(c, ppm):
    """The KHR limits of a constraint in its joint frame (the hinge or slider axis is the frame's token axis)."""
    if c["kind"] in ("spring", "distance", "rope"):
        length = c["rest_length"] / ppm if c["rest_length"] is not None else None
        return [{"linearAxes": [0, 1, 2], "min": 0.0 if c["kind"] != "rope" else None, "max": length}]
    token, _ = _joint_frame(c["axis"])
    k = AXIS_TOKENS.index(token)
    others = [i for i in range(3) if i != k]
    limits = []
    if c["kind"] in ("ball", "pin"):
        limits.append({"linearAxes": [0, 1, 2], "min": 0.0, "max": 0.0})
    elif c["kind"] in ("hinge", "motor"):
        limits.append({"linearAxes": [0, 1, 2], "min": 0.0, "max": 0.0})
        limits.append({"angularAxes": others, "min": 0.0, "max": 0.0})
        if c["min"] is not None:
            limits.append({"angularAxes": [k], "min": math.radians(c["min"]), "max": math.radians(c["max"])})
    elif c["kind"] == "slider":
        limits.append({"linearAxes": others, "min": 0.0, "max": 0.0})
        if c["min"] is not None:
            limits.append({"linearAxes": [k], "min": c["min"] / ppm, "max": c["max"] / ppm})
        limits.append({"angularAxes": [0, 1, 2], "min": 0.0, "max": 0.0})
    elif c["kind"] == "weld":
        limits.append({"linearAxes": [0, 1, 2], "min": 0.0, "max": 0.0})
        limits.append({"angularAxes": [0, 1, 2], "min": 0.0, "max": 0.0})
    return limits


def to_gltf(w):
    """A glTF 2.0 document with KHR_physics_rigid_bodies and KHR_implicit_shapes (the Khronos drafts), y up, metres,
    radians per second."""
    ppm = w["ppm"]
    shapes, materials, filters, phys_joints, nodes = [], [], [], [], []
    groups = sorted({b["group"] for b in w["bodies"]})
    index = {}
    for b in w["bodies"]:
        _check_shape(b)
        ext = {}
        if b["kind"] != "static":
            motion = {}
            if b["kind"] == "kinematic":
                motion["isKinematic"] = True
            if b["mass"] is not None:
                motion["mass"] = _num(b["mass"])
            motion["linearVelocity"] = list(to_metres(b["velocity"], ppm))
            motion["angularVelocity"] = [math.radians(x) for x in flip_vec(b["angular_velocity"])]
            ext["motion"] = motion
        geometry = {"shape": _index_of(shapes, _gltf_shape(b, ppm))}
        flt = {"collisionSystems": [f"g{b['group']}"]}
        if b["collides_with"] != "all":
            flt["collideWithSystems"] = [f"g{g}" for g in b["collides_with"]]
        part = {"geometry": geometry, "collisionFilter": _index_of(filters, flt)}
        if b["sensor"]:
            ext["trigger"] = part
        else:
            part["physicsMaterial"] = _index_of(materials, {"staticFriction": _num(b["friction"]), "dynamicFriction": _num(b["friction"]),
                                                             "restitution": _num(b["restitution"])})
            ext["collider"] = part
        node = {"name": b["id"], "translation": list(to_metres(b["pos"], ppm)), "rotation": list(flip_quat(b["rot"])),
                "extensions": {"KHR_physics_rigid_bodies": ext}}
        extras = {}
        if b["density"] is not None:
            extras["sr:density"] = b["density"]
        for key, name in (("bullet", "sr:bullet"), ("activate_at", "sr:activateAt"), ("linear_damping", "sr:linearDamping"),
                          ("angular_damping", "sr:angularDamping"), ("fixed_rotation", "sr:fixedRotation")):
            if b[key] != BODY_DEFAULTS[key]:
                extras[name] = b[key]
        if extras:
            node["extras"] = extras
        index[b["id"]] = len(nodes)
        nodes.append(node)
    bodies = _bodies_by_id(w)
    roots = list(range(len(nodes)))
    for c in w["constraints"]:
        prim = _joint_to_usd(c, bodies, ppm)
        a_node = nodes[index[c["a"]]]
        joint_index = _index_of(phys_joints, {"limits": _joint_limits(c, ppm), **_joint_drives(c)})
        rot0 = prim.get("physics:localRot0", (1.0, 0.0, 0.0, 0.0))
        rot1 = prim.get("physics:localRot1", (1.0, 0.0, 0.0, 0.0))
        b_node = {"name": f"{c['id']}.b", "translation": list(prim["physics:localPos1"]), "rotation": [rot1[1], rot1[2], rot1[3], rot1[0]]}
        b_index = len(nodes)
        nodes.append(b_node)
        if c["b"] is not None:
            nodes[index[c["b"]]].setdefault("children", []).append(b_index)
        else:
            roots.append(b_index)
        j_node = {"name": c["id"], "translation": list(prim["physics:localPos0"]), "rotation": [rot0[1], rot0[2], rot0[3], rot0[0]],
                  "extensions": {"KHR_physics_rigid_bodies": {"joint": {"connectedNode": b_index, "joint": joint_index}}}}
        extras = {"sr:type": c["kind"], "sr:axis": list(c["axis"])}
        custom = prim["customData"]
        for key in ("sr:unset", "sr:stiffness", "sr:damping"):
            if key in custom:
                extras[key] = list(custom[key]) if key == "sr:unset" else custom[key]
        if c["break_force"] is not None:
            extras["sr:breakForce"] = c["break_force"]
        j_node["extras"] = extras
        a_node.setdefault("children", []).append(len(nodes))
        nodes.append(j_node)
    doc = {"asset": {"version": "2.0", "generator": "sr-core ragdoll_reference"},
           "extensionsUsed": ["KHR_physics_rigid_bodies", "KHR_implicit_shapes"],
           "extensions": {"KHR_implicit_shapes": {"shapes": shapes},
                          "KHR_physics_rigid_bodies": {"physicsMaterials": materials, "collisionFilters": filters,
                                                       "physicsJoints": phys_joints}},
           "scenes": [{"nodes": roots}], "scene": 0, "nodes": nodes,
           "extras": {"sr:gravity": list(w["gravity"]), "sr:pixelsPerMeter": ppm, "sr:fixedStep": w["fixed_step"],
                      "sr:solverIterations": w["iterations"], "sr:start": w["start"], "sr:bounds": w["bounds"],
                      "sr:frame": list(w["frame"])}}
    return doc


def _joint_drives(c):
    if c["kind"] != "motor":
        return {}
    token, _ = _joint_frame(c["axis"])
    drive = {"type": "angular", "mode": "acceleration", "axis": AXIS_TOKENS.index(token),
             "velocityTarget": math.radians(c["motor_speed"])}
    if c["max_force"] is not None:
        drive["maxForce"] = c["max_force"]
    return {"drives": [drive]}


GLTF_MOTION_KEYS = {"isKinematic", "mass", "linearVelocity", "angularVelocity"}
GLTF_BODY_EXTRAS = {"sr:density", "sr:bullet", "sr:activateAt", "sr:linearDamping", "sr:angularDamping", "sr:fixedRotation"}


def from_gltf(g):
    """A world from a glTF with KHR_physics_rigid_bodies; a property the format has no reading of is an error."""
    ext = g.get("extensions", {}).get("KHR_physics_rigid_bodies", {})
    shapes = g.get("extensions", {}).get("KHR_implicit_shapes", {}).get("shapes", [])
    materials = ext.get("physicsMaterials", [])
    filters = ext.get("collisionFilters", [])
    phys_joints = ext.get("physicsJoints", [])
    extras = g.get("extras", {})
    ppm = float(extras.get("sr:pixelsPerMeter", 100.0))
    nodes = g.get("nodes", [])
    parent = {}
    for i, n in enumerate(nodes):
        for ch in n.get("children", []):
            parent[ch] = i
    bodies, out_bodies = {}, []
    for i, n in enumerate(nodes):
        rb = n.get("extensions", {}).get("KHR_physics_rigid_bodies", {})
        if "joint" in rb or not rb:
            continue
        motion = rb.get("motion")
        if motion is not None and set(motion) - GLTF_MOTION_KEYS:
            raise InterchangeError(f"node {n.get('name', i)}: the format has no reading of {sorted(set(motion) - GLTF_MOTION_KEYS)}")
        part = rb.get("collider") or rb.get("trigger")
        if part is None or "shape" not in part.get("geometry", {}):
            raise InterchangeError(f"node {n.get('name', i)}: a body needs an implicit shape (a mesh collider needs the triangles)")
        shape = shapes[part["geometry"]["shape"]]
        if shape["type"] == "box":
            size_m = tuple(shape["box"]["size"])
        elif shape["type"] == "sphere":
            r = shape["sphere"]["radius"]
            size_m = (2 * r, 2 * r, 2 * r)
        elif shape["type"] in ("capsule", "cylinder"):
            s = shape[shape["type"]]
            if s["radiusBottom"] != s["radiusTop"] and (s["radiusTop"] != 0.0 or shape["type"] == "capsule"):
                raise InterchangeError(f"node {n.get('name', i)}: a frustum has no reading in the format")
            r = s["radiusBottom"]
            size_m = (2 * r, s["height"] + (2 * r if shape["type"] == "capsule" else 0.0), 2 * r)
        else:
            raise InterchangeError(f"node {n.get('name', i)}: the format has no reading of a {shape['type']} shape")
        if shape["type"] == "cylinder" and shape["cylinder"]["radiusTop"] == 0.0 and shape["cylinder"]["radiusBottom"] > 0.0:
            kind_shape = "cone"
        elif shape["type"] == "cylinder":
            kind_shape = "cylinder"
        else:
            kind_shape = shape["type"]
        if motion is None:
            kind = "static"
        elif motion.get("isKinematic", False):
            kind = "kinematic"
        else:
            kind = "dynamic"
        xs = n.get("extras", {})
        if set(xs) - GLTF_BODY_EXTRAS:
            raise InterchangeError(f"node {n.get('name', i)}: unknown extras {sorted(set(xs) - GLTF_BODY_EXTRAS)}")
        mat = materials[part["physicsMaterial"]] if "physicsMaterial" in part else {}
        flt = filters[part["collisionFilter"]] if "collisionFilter" in part else {}
        group = int(flt.get("collisionSystems", ["g0"])[0][1:])
        collides = tuple(sorted(int(s[1:]) for s in flt["collideWithSystems"])) if "collideWithSystems" in flt else "all"
        mass = (motion or {}).get("mass")
        density = xs.get("sr:density")
        if mass is None and density is None:
            if kind == "static":
                mass = 1.0
            else:
                density = 1000.0
        q = n.get("rotation", [0.0, 0.0, 0.0, 1.0])
        b = body(n["name"], kind=kind, shape=kind_shape, size=to_pixels_size(size_m, ppm),
                 friction=mat.get("staticFriction", 0.5), restitution=mat.get("restitution", 0.0),
                 velocity=to_pixels(tuple((motion or {}).get("linearVelocity", (0.0, 0.0, 0.0))), ppm),
                 angular_velocity=flip_vec(tuple(round(math.degrees(x), 9) for x in (motion or {}).get("angularVelocity", (0.0, 0.0, 0.0)))),
                 pos=to_pixels(tuple(n.get("translation", (0.0, 0.0, 0.0))), ppm), rot=flip_quat(tuple(q)), group=group,
                 collides_with=collides, sensor="trigger" in rb, bullet=xs.get("sr:bullet", False),
                 activate_at=xs.get("sr:activateAt", 0.0), linear_damping=xs.get("sr:linearDamping", 0.01),
                 angular_damping=xs.get("sr:angularDamping", 0.01), fixed_rotation=xs.get("sr:fixedRotation", False),
                 **({"mass": mass} if mass is not None else {"density": density}))
        bodies[i] = b
        out_bodies.append(b)
    out_joints = []
    for i, n in enumerate(nodes):
        rb = n.get("extensions", {}).get("KHR_physics_rigid_bodies", {})
        if "joint" not in rb:
            continue
        j = rb["joint"]
        a_index = parent.get(i)
        b_index = parent.get(j["connectedNode"])
        if a_index not in bodies or (b_index is not None and b_index not in bodies):
            raise InterchangeError(f"node {n.get('name', i)}: a joint node is a child of a body node")
        a = bodies[a_index]
        xs = n.get("extras", {})
        spec = phys_joints[j["joint"]]
        kind = xs.get("sr:type")
        if kind is None:
            raise InterchangeError(f"node {n.get('name', i)}: a foreign joint's limit set has no reading without sr:type (open issue 1)")
        unset = set(xs.get("sr:unset", ()))
        kw = {"axis": tuple(xs["sr:axis"]), "break_force": xs.get("sr:breakForce")}
        limits = spec.get("limits", [])
        if kind in ("spring", "distance", "rope"):
            if "restLength" not in unset:
                kw["rest_length"] = round(limits[0]["max"] * ppm, 9)
            if kind == "spring":
                kw["stiffness"], kw["damping"] = xs.get("sr:stiffness"), xs.get("sr:damping")
        else:
            if "anchor" not in unset and kind != "weld":
                local = tuple(n.get("translation", (0.0, 0.0, 0.0)))
                world_anchor = _add(rotate(flip_quat(a["rot"]), local), to_metres(a["pos"], ppm))
                kw["anchor"] = tuple(round(x, 9) for x in to_pixels(world_anchor, ppm))
            if kind == "pin" and "sr:stiffness" in xs:
                kw["stiffness"], kw["damping"] = xs.get("sr:stiffness"), xs.get("sr:damping")
            token, _ = _joint_frame(kw["axis"])
            k = AXIS_TOKENS.index(token)
            for lim in limits:
                if kind in ("hinge", "motor") and lim.get("angularAxes") == [k]:
                    kw["min_angle"], kw["max_angle"] = round(math.degrees(lim["min"]), 9), round(math.degrees(lim["max"]), 9)
                if kind == "slider" and lim.get("linearAxes") == [k]:
                    kw["min_angle"], kw["max_angle"] = round(lim["min"] * ppm, 9), round(lim["max"] * ppm, 9)
            for d in spec.get("drives", []):
                kw["motor_speed"] = round(math.degrees(d["velocityTarget"]), 9)
                kw["max_force"] = d.get("maxForce")
        out_joints.append(constraint(n["name"], kind, a["id"], bodies[b_index]["id"] if b_index is not None else None, **kw))
    return world(out_bodies, out_joints, ppm=ppm, gravity=tuple(extras.get("sr:gravity", (0.0, -9.80665, 0.0))),
                 fixed_step=extras.get("sr:fixedStep", 1.0 / 120.0), iterations=extras.get("sr:solverIterations", 8),
                 start=extras.get("sr:start", 0.0), bounds=extras.get("sr:bounds", "none"),
                 frame=tuple(extras.get("sr:frame", (1920.0, 1080.0))))


def unsupported_test():
    base = {"/": {"metersPerUnit": 1.0, "upAxis": "Y"}}
    probes = ({**base, "/World/j": {"type": "PhysicsJoint", "physics:body0": "/World/a"}},
              {"/": {"metersPerUnit": 1.0, "upAxis": "Z"}},
              {**base, "/World/m": {"type": "Mesh", "apiSchemas": ("PhysicsRigidBodyAPI",)}})
    out = []
    for stage in probes:
        try:
            from_usd(stage)
            out.append(False)
        except InterchangeError:
            out.append(True)
    return tuple(out)


# ---- usda text


def _usda_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return f"{v:.9g}"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, (tuple, list)):
        return "(" + ", ".join(_usda_value(x) for x in v) + ")"
    raise InterchangeError(f"no usda form for {v!r}")


def _usda_attr(name, value):
    if isinstance(value, bool):
        return f"bool {name} = {_usda_value(value)}"
    if isinstance(value, (int, float)):
        return f"float {name} = {_usda_value(value)}"
    if isinstance(value, str):
        if name.startswith(("physics:body", "material:binding", "physics:collisionGroup")):
            return f"rel {name} = <{value}>"
        return f"token {name} = {_usda_value(value)}"
    if isinstance(value, (tuple, list)):
        if value and isinstance(value[0], str):
            return f"rel {name} = [" + ", ".join(f"<{x}>" for x in value) + "]"
        if len(value) == 4 and name == "xformOp:orient":
            return f"quatf {name} = {_usda_value(value)}"
        return f"float3 {name} = {_usda_value(value)}"
    raise InterchangeError(f"no usda form for {name}")


def usda(stage):
    """The stage as deterministic usda text: prims nested by path, attributes in a fixed order."""
    root = stage["/"]
    lines = ["#usda 1.0", "(", f"    metersPerUnit = {_usda_value(root['metersPerUnit'])}", f"    upAxis = {_usda_value(root['upAxis'])}", ")", ""]
    paths = sorted(p for p in stage if p != "/")
    tree = {}
    for p in paths:
        parts = p.strip("/").split("/")
        for depth in range(1, len(parts) + 1):
            sub = "/" + "/".join(parts[:depth])
            tree.setdefault(sub, stage.get(sub, {"type": "Xform"} if sub != p else stage[p]))

    def emit(path, indent):
        prim = tree[path]
        name = path.rsplit("/", 1)[1]
        pad = "    " * indent
        apis = prim.get("apiSchemas", ())
        custom = prim.get("customData")
        meta = []
        if apis:
            meta.append(f"{pad}    prepend apiSchemas = [" + ", ".join(f'"{a}"' for a in apis) + "]")
        if custom:
            meta.append(f"{pad}    customData = {{")
            for k in sorted(custom):
                meta.append(f'{pad}        {_usda_custom(custom[k])} "{k}" = {_usda_custom_value(custom[k])}')
            meta.append(f"{pad}    }}")
        header = f'{pad}def {prim.get("type", "Xform")} "{name}"'
        if meta:
            lines.append(header + " (")
            lines.extend(meta)
            lines.append(f"{pad})")
            lines.append(f"{pad}{{")
        else:
            lines.append(header)
            lines.append(f"{pad}{{")
        for k in sorted(prim):
            if k in ("type", "apiSchemas", "customData"):
                continue
            lines.append(f"{pad}    {_usda_attr(k, prim[k])}")
        ops = [k for k in ("xformOp:translate", "xformOp:orient", "xformOp:scale") if k in prim]
        if ops:
            lines.append(f"{pad}    uniform token[] xformOpOrder = [" + ", ".join(f'"{o}"' for o in ops) + "]")
        for child in sorted(p for p in tree if p.rsplit("/", 1)[0] == path and p != path):
            lines.append("")
            emit(child, indent + 1)
        lines.append(f"{pad}}}")

    for top in sorted(p for p in tree if p.count("/") == 1):
        emit(top, 0)
        lines.append("")
    return "\n".join(lines)


def _usda_custom_value(v):
    if isinstance(v, (tuple, list)):
        return "[" + ", ".join(_usda_value(x) for x in v) + "]"
    return _usda_value(v)


def _usda_custom(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "double"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (tuple, list)):
        return "string[]" if v and isinstance(v[0], str) else "double[]"
    raise InterchangeError(f"no usda form for {v!r}")


def usda_test():
    text = usda(to_usd(_sample_world()))
    return (text.startswith("#usda 1.0\n"), 'def PhysicsScene "PhysicsScene"' in text, text == usda(to_usd(_sample_world())))


# ---------------------------------------------------------------------------------------------------- the table


def world_summary():
    stage = to_usd(_sample_world())
    crate = stage["/World/crate"]
    return (crate["type"], tuple(round(x, 9) for x in crate["xformOp:translate"]),
            tuple(round(x, 9) for x in crate["physics:velocity"]), crate["physics:angularVelocity"],
            stage["/World/Joints/h"]["type"], stage["/World/Joints/h"]["physics:axis"],
            stage["/World/Joints/m"]["drive:angular:physics:targetVelocity"], len(stage))


def gltf_summary():
    g = to_gltf(_sample_world())
    crate = g["nodes"][0]["extensions"]["KHR_physics_rigid_bodies"]
    return (len(g["nodes"]), len(g["extensions"]["KHR_implicit_shapes"]["shapes"]),
            len(g["extensions"]["KHR_physics_rigid_bodies"]["physicsJoints"]),
            tuple(round(x, 12) for x in crate["motion"]["angularVelocity"]))


TABLE = (
    ("splitmix64", "(splitmix64(0), hex(splitmix64(GOLDEN)))", "(0, '0xe220a8397b1dcdaf')"),
    ("seeds", "seeds_in(2, 7, doubled((0, 0, 0)), doubled((3, 2, 1)))", "((3, 5, 1), (4, 5, 1))"),
    ("nearest", "(nearest(((1, 1, 1), (9, 1, 1), (5, 1, 1)), (7, 1, 1)), nearest(((1, 1, 1), (9, 1, 1), (5, 1, 1)), (8, 1, 1)))", "(1, 1)"),
    ("partition", "partition([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [0, 1, 1, 1])", "(((0, 0, 0),), ((1, 0, 0), (0, 1, 0), (1, 1, 0)))"),
    ("volume-sum", "volume_sum_test()", "(True, True, True)"),
    ("momenta", "tuple(x < 1e-12 for x in momentum_test([(x, y, z) for x in range(4) for y in range(3) for z in range(2)], partition([(x, y, z) for x in range(4) for y in range(3) for z in range(2)], voronoi([(x, y, z) for x in range(4) for y in range(3) for z in range(2)], 4, 3)), (0.1, 0.1, 0.1), 1500.0, (1.0, -2.0, 0.5), (0.3, 1.1, -0.7)))", "(True, True)"),
    ("cube-inertia", "moments([(0, 0, 0)], (1.0, 1.0, 1.0), 6.0)['inertia']", "((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))"),
    ("section", "(section(joints(partition([(x, y, 0) for y in range(2) for x in range(3)], [0, 0, 1, 0, 0, 1]))[(0, 1)], (0.5, 0.5, 0.5))['area'], section(joints(partition([(x, y, 0) for y in range(2) for x in range(3)], [0, 0, 1, 0, 0, 1]))[(0, 1)], (0.5, 0.5, 0.5))['centroid'])", "(0.5, (1.0, 0.5, 0.25))"),
    ("bending", "round(cut_stress([section([((0, 0, 0), (1, 0, 0), 0)], (1.0, 1.0, 1.0))], [True], {'force': (0.0, 0.0, 0.0), 'moment': (0.0, 0.0, 0.5), 'point': (1.0, 0.5, 0.5)})[0]['bending'], 12)", "3.0"),
    ("push", "cut_stress([section([((0, 0, 0), (1, 0, 0), 0)], (1.0, 1.0, 1.0))], [True], {'force': (-2.0, 0.0, 0.0), 'moment': (0.0, 0.0, 0.0), 'point': (1.0, 0.5, 0.5)})[0]['principal']", "0.0"),
    ("rankine", "(principal_tension(2.0, 1.5), principal_tension(-4.0, 0.0))", "(2.802775637731995, 0.0)"),
    ("cantilever-root", "(round(cantilever(9, 0.1, 2000.0, 9.81)[0]['bending'], 6), round(cantilever(9, 0.1, 2000.0, 9.81)[0]['shear'], 6), tuple(round(x, 6) for x in cantilever_root(9, 0.1, 2000.0, 9.81)))", "(376704.0, 15696.0, (376704.0, 15696.0))"),
    ("glue", "glue_test()", "(True, True, 4)"),
    ("capsule", "(round(capsule_volume(0.5, 2.0), 12), tuple(round(x, 12) for x in capsule_inertia(1.0, 0.5, 0.0)))", "(2.094395102393, (0.1, 0.1))"),
    ("limb", "(limb(2.0)['radius'], round(limb(2.0)['mass'], 9), limb(1.0, mass=3.0)['mass'])", "(0.4, 1273.392222255, 3.0)"),
    ("mass-matrix", "tuple(tuple(round(x, 6) for x in row) for row in mass_matrix(chain([limb(1.0, mass=1.0, radius=1e-9)] * 2), [math.pi / 2, math.pi / 2]))", "((1.333333, 0.5), (0.5, 0.333333))"),
    ("kinematic", "seek_test()[1]", "True"),
    ("period", "round(pendulum_period(limb(1.0, mass=1.0, radius=0.05)), 6)", "1.667741"),
    ("period-measured", "period_test() < 1e-3", "True"),
    ("energy", "energy_test() < 1e-3", "True"),
    ("drive", "(drive_torque(10.0, 2.0, 0.0, 0.5, 0.2, 0.0, 1.0), drive_torque(10.0, 2.0, 0.5, 0.5, 0.2, 0.0, 1.0), drive_torque(10.0, 2.0, 1.0, 0.5, 0.2, 0.0, 1.0))", "(1.0, 0.5, 0.0)"),
    ("blend", "blend_angle(0.5, 1.5, 0.25)", "0.75"),
    ("settled", "round(settled_angle(limb(1.0, mass=1.0, radius=0.05), 20.0, 0.5, 1.0), 9)", "0.68838853"),
    ("settle-measured", "settle_test() < 1e-5", "True"),
    ("limits", "limit_test()", "(True, True)"),
    ("seek", "seek_test()", "(True, True)"),
    ("axes", "(to_metres((100.0, 50.0, -25.0), 100.0), flip_quat((0.1, 0.2, 0.3, 0.9)))", "((1.0, -0.5, 0.25), (0.1, -0.2, -0.3, 0.9))"),
    ("joint-frame", "(_joint_frame((0.0, 0.0, 1.0)), _joint_frame((0.0, 1.0, 0.0)), _joint_frame((1.0, 0.0, 0.0)))", "(('Z', (1.0, 0.0, 0.0, 0.0)), ('Y', (0.0, 0.0, 1.0, 0.0)), ('X', (0.0, 0.0, 0.0, 1.0)))"),
    ("volumes", "tuple(round(shape_volume(s, (0.4, 1.2, 0.4)), 9) for s in SHAPES)", "(0.192, 0.033510322, 0.134041287, 0.150796447, 0.050265482)"),
    ("usd", "world_summary()", "('Cube', (3.0, -2.0, 0.5), (0.1, 0.05, -0.02), (0.0, -90.0, 0.0), 'PhysicsRevoluteJoint', 'Z', 180.0, 24)"),
    ("gltf", "gltf_summary()", "(23, 5, 8, (0.0, -1.570796326795, 0.0))"),
    ("foreign-density", "round(body_mass(from_usd({'/': {'metersPerUnit': 1.0, 'upAxis': 'Y'}, '/World/rock': {'type': 'Sphere', 'radius': 0.5, 'apiSchemas': ('PhysicsRigidBodyAPI', 'PhysicsCollisionAPI')}})['bodies'][0], 100.0), 9)", "523.598775598"),
    ("centimetres", "from_usd({'/': {'metersPerUnit': 0.01, 'upAxis': 'Y'}, '/World/rock': {'type': 'Sphere', 'radius': 50.0, 'apiSchemas': ('PhysicsRigidBodyAPI',), 'xformOp:translate': (100.0, 0.0, 0.0)}})['bodies'][0]['pos']", "(100.0, 0.0, 0.0)"),
    ("round-trip", "round_trip_test()", "(True, True)"),
    ("unsupported", "unsupported_test()", "(True, True, True)"),
    ("usda", "usda_test()", "(True, True, True)"),
    ("bounds", "(MAX_SEEDS, MAX_SEED_COORD, MAX_PIECES, MAX_LIMBS, MAX_STEPS, MAX_BODIES, MAX_CONSTRAINTS)", "(4096, 1099511627776, 4096, 256, 65536, 65536, 65536)"),
)


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["__builtins__"] = {"round": round, "tuple": tuple, "len": len, "sorted": sorted, "min": min, "max": max,
                         "abs": abs, "range": range, "list": list, "set": set, "dict": dict, "True": True,
                         "False": False, "None": None, "any": any, "all": all, "int": int, "float": float,
                         "zip": zip, "sum": sum, "slice": slice, "ValueError": ValueError, "enumerate": enumerate,
                         "hex": hex}
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
