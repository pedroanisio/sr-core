#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add cloth and soft bodies in 3D" (srep/srep-0000-softbody.md),
S1 of SREP 12.

Standard library only. The rules of the SREP's Semantics section are the functions below, in its order: the
meshes (rule 1), springs and bends (rule 2), the stable neo-Hookean tetrahedra (rule 3), Vertex Block Descent
(rules 4 to 6), offset contact (rules 7 and 8), the twisting test (rule 9), XPBD rods (rule 10), energy and
the rest-shape checks (rule 11) and the bounds (rule 12). `main()` prints the SREP's numeric table;
`tests/test_softbody.py` checks both.

Units: metres, kilograms, seconds; y is up. A sheet's columns run along +x and its rows along -z.
"""
import math

MAX_VERTICES = 65536      # vertices of one body
MAX_SIDE = 256            # rows or cols of a sheet
MAX_ITERATIONS = 256      # VBD or XPBD iterations per substep
MAX_SUBSTEPS = 64         # substeps per frame
MAX_FRAMES = 65536        # frames of one run
MAX_HALVINGS = 8          # halvings of a vertex step that raised its local energy
FD_EPS = 1e-6             # the finite-difference step of the tetrahedral Hessians

# --- vectors and 3x3 matrices ---------------------------------------------------------------------------------


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _outer(a, b):
    return tuple(tuple(a[i] * b[j] for j in range(3)) for i in range(3))


def _madd(A, B, s=1.0):
    return tuple(tuple(A[i][j] + s * B[i][j] for j in range(3)) for i in range(3))


def _identity(s=1.0):
    return ((s, 0.0, 0.0), (0.0, s, 0.0), (0.0, 0.0, s))


ZERO3 = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def _mat_vec(A, v):
    return tuple(_dot(A[i], v) for i in range(3))


def _mat_mul(A, B):
    return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _transpose(A):
    return tuple(tuple(A[j][i] for j in range(3)) for i in range(3))


def _det(A):
    return _dot(A[0], _cross(A[1], A[2]))


def _inverse(A):
    d = _det(A)
    if abs(d) < 1e-300:
        raise ValueError("the matrix is singular")
    c = _transpose((_cross(A[1], A[2]), _cross(A[2], A[0]), _cross(A[0], A[1])))
    return tuple(tuple(c[i][j] / d for j in range(3)) for i in range(3))


def solve3(A, b):
    """x with A x = b by Gaussian elimination with partial pivoting; a singular A is an error."""
    M = [list(A[i]) + [b[i]] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-14 * max(1.0, max(abs(v) for row in M for v in row[:3])):
            raise ValueError("the system is singular")
        M[col], M[pivot] = M[pivot], M[col]
        for r in range(col + 1, 3):
            f = M[r][col] / M[col][col]
            for c in range(col, 4):
                M[r][c] -= f * M[col][c]
    x = [0.0, 0.0, 0.0]
    for i in (2, 1, 0):
        x[i] = (M[i][3] - sum(M[i][j] * x[j] for j in range(i + 1, 3))) / M[i][i]
    return tuple(x)


def eigen_symmetric(A):
    """Eigenvalues and eigenvectors (columns) of a symmetric 3x3 by Jacobi rotations."""
    a = [list(row) for row in A]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(50):
        off = abs(a[0][1]) + abs(a[0][2]) + abs(a[1][2])
        if off < 1e-15 * max(1.0, abs(a[0][0]) + abs(a[1][1]) + abs(a[2][2])):
            break
        for p in range(3):
            for q in range(p + 1, 3):
                if abs(a[p][q]) < 1e-300:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0.0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(3):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(3):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
                for k in range(3):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    return (a[0][0], a[1][1], a[2][2]), tuple(tuple(row) for row in v)


def psd_project(A):
    """A with its negative eigenvalues clamped to 0."""
    values, vectors = eigen_symmetric(A)
    out = ZERO3
    for k in range(3):
        if values[k] > 0.0:
            col = (vectors[0][k], vectors[1][k], vectors[2][k])
            out = _madd(out, _outer(col, col), values[k])
    return out


def is_psd(A):
    return all(v >= -1e-9 for v in eigen_symmetric(A)[0])


# --- rule 1: the meshes ---------------------------------------------------------------------------------------


def sheet(rows, cols, height, width):
    """A rows x cols grid of vertices with the columns along +x (width) and the rows along -z (height),
    triangulated with one diagonal per quad in a checkerboard (so the mesh mirrors left to right when the
    quads per row are even); springs on the grid edges and the diagonals, bends between second neighbours
    along the rows and columns and across each quad's other diagonal; unit total mass shared equally."""
    if not (2 <= rows <= MAX_SIDE and 2 <= cols <= MAX_SIDE):
        raise ValueError("rows and cols are in 2..MAX_SIDE")
    if height <= 0.0 or width <= 0.0:
        raise ValueError("the sheet's size is positive")
    positions = [(width * c / (cols - 1), 0.0, -height * r / (rows - 1)) for r in range(rows) for c in range(cols)]
    idx = lambda r, c: r * cols + c
    triangles, edges, bends = [], [], []
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                edges.append((idx(r, c), idx(r, c + 1)))
            if c + 2 < cols:
                bends.append((idx(r, c), idx(r, c + 2)))
            if r + 1 < rows:
                edges.append((idx(r, c), idx(r + 1, c)))
            if r + 2 < rows:
                bends.append((idx(r, c), idx(r + 2, c)))
            if r + 1 < rows and c + 1 < cols:
                a, b, d, e = idx(r, c), idx(r, c + 1), idx(r + 1, c), idx(r + 1, c + 1)
                if (r + c) % 2 == 0:
                    triangles += [(a, d, e), (a, e, b)]
                    edges.append((a, e))
                    bends.append((b, d))
                else:
                    triangles += [(a, d, b), (b, d, e)]
                    edges.append((b, d))
                    bends.append((a, e))
    n = rows * cols
    return {"rows": rows, "cols": cols, "positions": positions, "triangles": triangles, "edges": edges,
            "bends": bends, "masses": [1.0 / n] * n}


def pins(mesh, mode):
    """The pinned vertices of a mesh: none, top (the first row), corners (its ends), ends (first and last
    rows), bottom (a block's lowest vertices)."""
    if mode == "none":
        return set()
    if "rows" in mesh:
        rows, cols = mesh["rows"], mesh["cols"]
        if mode == "top":
            return set(range(cols))
        if mode == "corners":
            return {0, cols - 1}
        if mode == "ends":
            return set(range(cols)) | set(range((rows - 1) * cols, rows * cols))
    if mode == "bottom":
        low = min(p[1] for p in mesh["positions"])
        return {i for i, p in enumerate(mesh["positions"]) if p[1] == low}
    raise ValueError(f"unknown pin mode {mode!r}")


def tet_volume(a, b, c, d):
    """The signed volume of the tetrahedron (a, b, c, d)."""
    return _dot(_sub(b, a), _cross(_sub(c, a), _sub(d, a))) / 6.0


def block(width, height, depth):
    """A box of eight vertices (index x + 2 z + 4 y) split into six tetrahedra of positive volume; unit mass."""
    if min(width, height, depth) <= 0.0:
        raise ValueError("the block's size is positive")
    positions = [(width * (i & 1), height * ((i >> 2) & 1), depth * ((i >> 1) & 1)) for i in range(8)]
    kuhn = [(0, 1, 3, 7), (0, 3, 2, 7), (0, 2, 6, 7), (0, 6, 4, 7), (0, 4, 5, 7), (0, 5, 1, 7)]
    tets = []
    for t in kuhn:
        if tet_volume(*(positions[i] for i in t)) < 0.0:
            t = (t[0], t[2], t[1], t[3])
        tets.append(t)
    return {"positions": positions, "tets": tets, "masses": [1.0 / 8.0] * 8}


# --- rule 2: springs ------------------------------------------------------------------------------------------


def spring_energy(a, b, rest, k):
    L = _norm(_sub(b, a))
    if L == 0.0:
        raise ValueError("a spring of zero length")
    return 0.5 * k * (L - rest) ** 2


def spring_force(a, b, rest, k):
    """The force on a of the spring to b."""
    d = _sub(b, a)
    L = _norm(d)
    if L == 0.0:
        raise ValueError("a spring of zero length")
    return _scale(d, k * (L - rest) / L)


def spring_hessian(a, b, rest, k):
    """The Hessian of the spring's energy at a, k (d d^T + max(0, 1 - rest/L)(I - d d^T)), positive semidefinite."""
    d = _sub(b, a)
    L = _norm(d)
    if L == 0.0:
        raise ValueError("a spring of zero length")
    u = _scale(d, 1.0 / L)
    uu = _outer(u, u)
    t = max(0.0, 1.0 - rest / L)
    return tuple(tuple(k * (uu[i][j] + t * ((1.0 if i == j else 0.0) - uu[i][j])) for j in range(3)) for i in range(3))


# --- rule 3: the stable neo-Hookean material ------------------------------------------------------------------


def lame(youngs, poisson):
    """Lamé's mu and lambda of Young's modulus and Poisson's ratio (below 0.5)."""
    if youngs <= 0.0 or not 0.0 <= poisson < 0.5:
        raise ValueError("Young's modulus is positive and Poisson's ratio in [0, 0.5)")
    return (youngs / (2.0 * (1.0 + poisson)), youngs * poisson / ((1.0 + poisson) * (1.0 - 2.0 * poisson)))


def snh_energy(F, mu, lam):
    """Smith, Goes and Kim (2018): mu/2 (I_C - 3) + lambda/2 (J - alpha)^2 - mu/2 ln(I_C + 1)."""
    ic = sum(F[i][j] ** 2 for i in range(3) for j in range(3))
    alpha = 1.0 + mu / lam - mu / (4.0 * lam)
    return 0.5 * mu * (ic - 3.0) + 0.5 * lam * (_det(F) - alpha) ** 2 - 0.5 * mu * math.log(ic + 1.0)


def snh_stress(F, mu, lam):
    """The first Piola-Kirchhoff stress of the stable neo-Hookean energy."""
    ic = sum(F[i][j] ** 2 for i in range(3) for j in range(3))
    alpha = 1.0 + mu / lam - mu / (4.0 * lam)
    cof = _transpose((_cross(F[1], F[2]), _cross(F[2], F[0]), _cross(F[0], F[1])))
    cof = _transpose(cof)
    s = mu * (1.0 - 1.0 / (ic + 1.0))
    t = lam * (_det(F) - alpha)
    return tuple(tuple(s * F[i][j] + t * cof[i][j] for j in range(3)) for i in range(3))


def _deformation(positions, tet, inverse):
    a, b, c, d = (positions[i] for i in tet)
    ds = _transpose((_sub(b, a), _sub(c, a), _sub(d, a)))
    return _mat_mul(ds, inverse)


def tet_energy(positions, tet, inverse, volume, mu, lam):
    """The tetrahedron's energy: its rest volume times the energy density at its deformation gradient."""
    return volume * snh_energy(_deformation(positions, tet, inverse), mu, lam)


def tet_gradients(positions, tet, inverse, volume, mu, lam):
    """The energy gradient of the tetrahedron at each of its four vertices."""
    P = snh_stress(_deformation(positions, tet, inverse), mu, lam)
    G = _mat_mul(P, _transpose(inverse))
    g1, g2, g3 = (tuple(volume * G[i][j] for i in range(3)) for j in range(3))
    g0 = _scale(_add(_add(g1, g2), g3), -1.0)
    return (g0, g1, g2, g3)


# --- rules 4 to 6: Vertex Block Descent -----------------------------------------------------------------------


def body(positions, masses, edges, bends, tets, pinned, triangles=(), thickness=0.0, contact_stiffness=0.0,
         damping=0.0, material=(1.0, 1.0)):
    """A simulated body: springs (i, j, rest, k), bends (i, j, rest, k), tetrahedra (i, j, k, l) with their
    rest-shape inverses and volumes computed from the positions, triangles for contact, a pinned set, the
    contact offset (thickness) and stiffness, the damping and the Lamé pair of the tetrahedra."""
    n = len(positions)
    if not 1 <= n <= MAX_VERTICES or len(masses) != n:
        raise ValueError("a body has 1..MAX_VERTICES vertices with one mass each")
    if thickness < 0.0 or contact_stiffness < 0.0 or not 0.0 <= damping < 1.0:
        raise ValueError("thickness and contact stiffness are not negative; damping is in [0, 1)")
    inverses, volumes = [], []
    for t in tets:
        a, b, c, d = (positions[i] for i in t)
        v = tet_volume(a, b, c, d)
        if v <= 0.0:
            raise ValueError("a tetrahedron of non-positive volume")
        inverses.append(_inverse(_transpose((_sub(b, a), _sub(c, a), _sub(d, a)))))
        volumes.append(v)
    return {"positions": [tuple(p) for p in positions], "masses": list(masses), "edges": list(edges),
            "bends": list(bends), "tets": [tuple(t) for t in tets], "tet_inverse": inverses,
            "tet_volume": volumes, "pinned": set(pinned), "triangles": list(triangles),
            "thickness": thickness, "contact_stiffness": contact_stiffness, "damping": damping,
            "material": material}


def cloth_body(mesh, stiffness, bending, pin, damping=0.0, mass=1.0, thickness=0.0, contact_stiffness=0.0):
    """A sheet as a body: grid springs at stiffness, diagonal springs at half of it, bends at bending."""
    pos = mesh["positions"]
    cols = mesh["cols"]
    edges = []
    for i, j in mesh["edges"]:
        diagonal = i // cols != j // cols and i % cols != j % cols
        edges.append((i, j, _norm(_sub(pos[j], pos[i])), stiffness * (0.5 if diagonal else 1.0)))
    bends = [(i, j, _norm(_sub(pos[j], pos[i])), bending) for i, j in mesh["bends"]]
    masses = [m * mass for m in mesh["masses"]]
    out = body(pos, masses, edges, bends, [], pins(mesh, pin), mesh["triangles"], thickness, contact_stiffness,
               damping)
    out["rows"], out["cols"] = mesh["rows"], mesh["cols"]
    return out


def solid_body(mesh, youngs, poisson, density, pin, damping=0.0):
    """A block as a body of stable neo-Hookean tetrahedra; the mass is the density times the volume, shared
    equally."""
    pos = mesh["positions"]
    volume = sum(tet_volume(*(pos[i] for i in t)) for t in mesh["tets"])
    n = len(pos)
    return body(pos, [density * volume / n] * n, [], [], mesh["tets"], pins(mesh, pin), damping=damping,
                material=lame(youngs, poisson))


def initial(body):
    return {"positions": list(body["positions"]), "velocities": [(0.0, 0.0, 0.0)] * len(body["positions"])}


def _incidence(body):
    """Per vertex: the springs, bends and tetrahedra it belongs to."""
    n = len(body["positions"])
    springs = [[] for _ in range(n)]
    tets = [[] for _ in range(n)]
    for e in body["edges"] + body["bends"]:
        springs[e[0]].append((e[1], e[2], e[3]))
        springs[e[1]].append((e[0], e[2], e[3]))
    for k, t in enumerate(body["tets"]):
        for slot in range(4):
            tets[t[slot]].append((k, slot))
    return springs, tets


def _vertex_energy(body, positions, i, springs, tets, contacts, mu, lam):
    e = 0.0
    for j, rest, k in springs[i]:
        e += spring_energy(positions[i], positions[j], rest, k)
    for k, _ in tets[i]:
        e += tet_energy(positions, body["tets"][k], body["tet_inverse"][k], body["tet_volume"][k], mu, lam)
    for c in contacts:
        if i in c["vertices"]:
            e += contact_energy(positions, c, body["thickness"], body["contact_stiffness"])
    return e


def _vertex_gradient_hessian(body, positions, i, springs, tets, contacts, mu, lam):
    g = (0.0, 0.0, 0.0)
    Hm = ZERO3
    for j, rest, k in springs[i]:
        g = _sub(g, spring_force(positions[i], positions[j], rest, k))
        Hm = _madd(Hm, spring_hessian(positions[i], positions[j], rest, k))
    for k, slot in tets[i]:
        t, inverse, volume = body["tets"][k], body["tet_inverse"][k], body["tet_volume"][k]
        grad = tet_gradients(positions, t, inverse, volume, mu, lam)[slot]
        g = _add(g, grad)
        cols = []
        base = positions[i]
        for axis in range(3):
            moved = list(positions)
            moved[i] = _add(base, tuple(FD_EPS if m == axis else 0.0 for m in range(3)))
            cols.append(_scale(_sub(tet_gradients(moved, t, inverse, volume, mu, lam)[slot], grad), 1.0 / FD_EPS))
        fd = tuple(tuple(0.5 * (cols[a][b] + cols[b][a]) for b in range(3)) for a in range(3))
        Hm = _madd(Hm, psd_project(fd))
    for c in contacts:
        if i in c["vertices"]:
            cg, ch = contact_gradient_hessian(positions, c, i, body["thickness"], body["contact_stiffness"])
            g = _add(g, cg)
            Hm = _madd(Hm, ch)
    return g, Hm


def vbd_step(body, state, h, g, iterations, damping=None):
    """One Vertex Block Descent step of h under gravity g: the inertial target y = x + h v + h^2 g, then
    iterations Gauss-Seidel sweeps of local Newton steps over the free vertices in index order, each step
    halved while it raises the vertex's local energy; v = (x_new - x) / h, damped by the body's damping."""
    if not (isinstance(iterations, int) and 1 <= iterations <= MAX_ITERATIONS):
        raise ValueError("iterations are in 1..MAX_ITERATIONS")
    if h <= 0.0:
        raise ValueError("the step is positive")
    damping = body["damping"] if damping is None else damping
    x0 = list(state["positions"])
    n = len(x0)
    masses = body["masses"]
    pinned = body["pinned"]
    y = [x0[i] if i in pinned else _add(_add(x0[i], _scale(state["velocities"][i], h)), _scale(g, h * h))
         for i in range(n)]
    x = list(y)
    springs, tets = _incidence(body)
    contacts = find_contacts(body, x0)
    mu, lam = body["material"]
    inv = 1.0 / (h * h)
    for _ in range(iterations):
        for i in range(n):
            if i in pinned:
                continue
            grad, Hm = _vertex_gradient_hessian(body, x, i, springs, tets, contacts, mu, lam)
            f = _add(grad, _scale(_sub(x[i], y[i]), masses[i] * inv))
            Hm = _madd(Hm, _identity(masses[i] * inv))
            delta = solve3(Hm, f)
            if delta == (0.0, 0.0, 0.0):
                continue
            before = _vertex_energy(body, x, i, springs, tets, contacts, mu, lam) + 0.5 * masses[i] * inv * _dot(_sub(x[i], y[i]), _sub(x[i], y[i]))
            old = x[i]
            for _ in range(MAX_HALVINGS + 1):
                x[i] = _sub(old, delta)
                after = _vertex_energy(body, x, i, springs, tets, contacts, mu, lam) + 0.5 * masses[i] * inv * _dot(_sub(x[i], y[i]), _sub(x[i], y[i]))
                if after <= before:
                    break
                delta = _scale(delta, 0.5)
            else:
                x[i] = old
    velocities = [(0.0, 0.0, 0.0) if i in pinned else _scale(_sub(x[i], x0[i]), (1.0 - damping) / h)
                  for i in range(n)]
    return {"positions": x, "velocities": velocities}


def run(body, frames, h, g, iterations, substeps=1, state=None, damping=None):
    """frames frames of substeps VBD steps each; the state after frame f is a function of f alone."""
    if not (isinstance(frames, int) and 0 <= frames <= MAX_FRAMES):
        raise ValueError("frames are in 0..MAX_FRAMES")
    if not (isinstance(substeps, int) and 1 <= substeps <= MAX_SUBSTEPS):
        raise ValueError("substeps are in 1..MAX_SUBSTEPS")
    state = initial(body) if state is None else {"positions": list(state["positions"]), "velocities": list(state["velocities"])}
    for _ in range(frames * substeps):
        state = vbd_step(body, state, h / substeps, g, iterations, damping)
    return state


# --- rules 7 and 8: offset contact ----------------------------------------------------------------------------


def point_triangle_distance(p, a, b, c):
    """The distance from p to the triangle and the closest point (Ericson 2005, 5.1.5)."""
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return _norm(ap), a
    bp = _sub(p, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return _norm(bp), b
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        q = _add(a, _scale(ab, v))
        return _norm(_sub(p, q)), q
    cp = _sub(p, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return _norm(cp), c
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        q = _add(a, _scale(ac, w))
        return _norm(_sub(p, q)), q
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        q = _add(b, _scale(_sub(c, b), w))
        return _norm(_sub(p, q)), q
    denom = 1.0 / (va + vb + vc)
    v, w = vb * denom, vc * denom
    q = _add(_add(a, _scale(ab, v)), _scale(ac, w))
    return _norm(_sub(p, q)), q


def barycentric(q, a, b, c):
    """The barycentric weights of a point of the triangle's plane."""
    v0, v1, v2 = _sub(b, a), _sub(c, a), _sub(q, a)
    d00, d01, d11, d20, d21 = _dot(v0, v0), _dot(v0, v1), _dot(v1, v1), _dot(v2, v0), _dot(v2, v1)
    denom = d00 * d11 - d01 * d01
    if denom == 0.0:
        return (1.0, 0.0, 0.0)
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    return (1.0 - v - w, v, w)


def edge_edge_distance(p1, q1, p2, q2):
    """The distance between two segments and their closest points (Ericson 2005, 5.1.9)."""
    return _edge_edge(p1, q1, p2, q2)[:3]


def _edge_edge(p1, q1, p2, q2):
    """edge_edge_distance with the closest points' parameters s and t along each segment."""
    d1, d2, r = _sub(q1, p1), _sub(q2, p2), _sub(p1, p2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    if a <= 1e-300 and e <= 1e-300:
        return _norm(r), p1, p2, 0.0, 0.0
    if a <= 1e-300:
        s, t = 0.0, min(1.0, max(0.0, f / e))
    else:
        c = _dot(d1, r)
        if e <= 1e-300:
            s, t = min(1.0, max(0.0, -c / a)), 0.0
        else:
            b = _dot(d1, d2)
            denom = a * e - b * b
            s = min(1.0, max(0.0, (b * f - c * e) / denom)) if denom != 0.0 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, min(1.0, max(0.0, -c / a))
            elif t > 1.0:
                t, s = 1.0, min(1.0, max(0.0, (b - c) / a))
    cp = _add(p1, _scale(d1, s))
    cq = _add(p2, _scale(d2, t))
    return _norm(_sub(cp, cq)), cp, cq, s, t


def _edges_of(triangles):
    edges = set()
    for t in triangles:
        for k in range(3):
            i, j = t[k], t[(k + 1) % 3]
            edges.add((min(i, j), max(i, j)))
    return sorted(edges)


def find_contacts(body, positions):
    """The vertex-triangle and edge-edge pairs within twice the thickness, found once per step."""
    thickness, k = body["thickness"], body["contact_stiffness"]
    if thickness <= 0.0 or k <= 0.0 or not body["triangles"]:
        return []
    reach = 2.0 * thickness
    contacts = []
    triangles = body["triangles"]
    for v in range(len(positions)):
        for t in triangles:
            if v in t:
                continue
            d, _ = point_triangle_distance(positions[v], *(positions[i] for i in t))
            if d < reach:
                contacts.append({"kind": "vt", "vertices": (v,) + tuple(t)})
    edges = _edges_of(triangles)
    for a in range(len(edges)):
        for b in range(a + 1, len(edges)):
            e1, e2 = edges[a], edges[b]
            if set(e1) & set(e2):
                continue
            d = _edge_edge(positions[e1[0]], positions[e1[1]], positions[e2[0]], positions[e2[1]])[0]
            if d < reach:
                contacts.append({"kind": "ee", "vertices": e1 + e2})
    return contacts


def _contact_geometry(positions, c):
    """The gap d, its direction n (from the other primitive toward the first) and the weights of the
    contact's vertices along n."""
    vs = c["vertices"]
    if c["kind"] == "vt":
        p, a, b, cc = (positions[i] for i in vs)
        d, q = point_triangle_distance(p, a, b, cc)
        w = barycentric(q, a, b, cc)
        n = _scale(_sub(p, q), 1.0 / d) if d > 0.0 else (0.0, 1.0, 0.0)
        return d, n, (1.0, -w[0], -w[1], -w[2])
    p1, q1, p2, q2 = (positions[i] for i in vs)
    d, cp, cq, s, t = _edge_edge(p1, q1, p2, q2)
    n = _scale(_sub(cp, cq), 1.0 / d) if d > 0.0 else (0.0, 1.0, 0.0)
    return d, n, (1.0 - s, s, -(1.0 - t), -t)


def contact_energy(positions, c, thickness, k):
    """k/2 (thickness - d)^2 while the gap d is below the thickness, else 0."""
    d = _contact_geometry(positions, c)[0]
    return 0.5 * k * (thickness - d) ** 2 if d < thickness else 0.0


def contact_gradient_hessian(positions, c, i, thickness, k):
    """The contact energy's gradient and Gauss-Newton Hessian at vertex i of the contact."""
    d, n, weights = _contact_geometry(positions, c)
    if d >= thickness:
        return (0.0, 0.0, 0.0), ZERO3
    w = weights[c["vertices"].index(i)]
    g = _scale(n, -k * (thickness - d) * w)
    return g, _madd(ZERO3, _outer(n, n), k * w * w)


def segment_triangle_intersects(p, q, a, b, c):
    """Whether the segment pq crosses the triangle abc (Möller and Trumbore 1997)."""
    d = _sub(q, p)
    e1, e2 = _sub(b, a), _sub(c, a)
    h = _cross(d, e2)
    det = _dot(e1, h)
    if abs(det) < 1e-14:
        return False
    s = _sub(p, a)
    u = _dot(s, h) / det
    if u < 0.0 or u > 1.0:
        return False
    qv = _cross(s, e1)
    v = _dot(d, qv) / det
    if v < 0.0 or u + v > 1.0:
        return False
    t = _dot(e2, qv) / det
    return 0.0 <= t <= 1.0


def triangles_intersect(t1, t2):
    """Whether two triangles intersect: an edge of either crosses the other."""
    for (a, b, c), other in ((t1, t2), (t2, t1)):
        for p, q in ((a, b), (b, c), (c, a)):
            if segment_triangle_intersects(p, q, *other):
                return True
    return False


def self_intersections(positions, triangles):
    """The number of intersecting pairs of triangles that share no vertex."""
    count = 0
    for a in range(len(triangles)):
        for b in range(a + 1, len(triangles)):
            if set(triangles[a]) & set(triangles[b]):
                continue
            if triangles_intersect(tuple(positions[i] for i in triangles[a]), tuple(positions[i] for i in triangles[b])):
                count += 1
    return count


# --- rule 9: the twisting test --------------------------------------------------------------------------------


def twist_test(body, turns, frames, H, iterations):
    """A sheet pinned at both ends whose end rows turn about the sheet's long axis in opposite senses, turns
    turns in all over frames frames; counts self-intersections after every frame and the contacts used."""
    rows, cols = body["rows"], body["cols"]
    rest = body["positions"]
    cx = sum(p[0] for p in rest) / len(rest)
    first = list(range(cols))
    last = list(range((rows - 1) * cols, rows * cols))
    state = initial(body)
    intersections = contacts = 0
    max_stretch = 1.0
    for f in range(1, frames + 1):
        angle = math.pi * turns * f / frames
        for group, sign in ((first, 1.0), (last, -1.0)):
            for i in group:
                px, py, pz = rest[i]
                c, s = math.cos(sign * angle), math.sin(sign * angle)
                state["positions"][i] = (cx + (px - cx) * c - py * s, (px - cx) * s + py * c, pz)
        contacts += len(find_contacts(body, state["positions"]))
        state = vbd_step(body, state, H, (0.0, 0.0, 0.0), iterations)
        intersections += self_intersections(state["positions"], body["triangles"])
        for i, j, rest_len, _ in body["edges"]:
            max_stretch = max(max_stretch, _norm(_sub(state["positions"][j], state["positions"][i])) / rest_len)
    return {"intersections": intersections, "contacts": contacts, "max_stretch": max_stretch, "frames": frames}


# --- rule 10: XPBD rods ---------------------------------------------------------------------------------------


def rope(count, length):
    """count points hanging straight down from the origin over length; unit mass shared equally."""
    if not (isinstance(count, int) and 2 <= count <= MAX_VERTICES):
        raise ValueError("a rope has 2..MAX_VERTICES points")
    if length <= 0.0:
        raise ValueError("the length is positive")
    return {"positions": [(0.0, -length * i / (count - 1), 0.0) for i in range(count)], "masses": [1.0 / count] * count}


def rope_body(mesh, stiffness, bending, pin, damping=0.0, mass=1.0):
    """A rope as XPBD constraints: distance between neighbours (compliance 1/stiffness) and between second
    neighbours (compliance 1/bending, none when bending is 0)."""
    pos = mesh["positions"]
    n = len(pos)
    if stiffness <= 0.0 or bending < 0.0:
        raise ValueError("stiffness is positive and bending not negative")
    if pin == "top":
        pinned = {0}
    elif pin == "ends":
        pinned = {0, n - 1}
    elif pin == "none":
        pinned = set()
    else:
        raise ValueError(f"unknown pin mode {pin!r}")
    constraints = [(i, i + 1, _norm(_sub(pos[i + 1], pos[i])), 1.0 / stiffness) for i in range(n - 1)]
    if bending > 0.0:
        constraints += [(i, i + 2, _norm(_sub(pos[i + 2], pos[i])), 1.0 / bending) for i in range(n - 2)]
    return {"positions": list(pos), "masses": [m * mass for m in mesh["masses"]], "constraints": constraints,
            "pinned": pinned, "damping": damping}


def xpbd_distance(a, b, rest, w_a, w_b, lagrange, compliance, h):
    """One XPBD projection of the distance constraint |a - b| - rest with the inverse masses w, the
    accumulated multiplier and the compliance; returns the new positions and multiplier."""
    d = _sub(b, a)
    L = _norm(d)
    if L == 0.0:
        return a, b, lagrange
    alpha = compliance / (h * h)
    denom = w_a + w_b + alpha
    if denom == 0.0:
        return a, b, lagrange
    dl = (-(L - rest) - alpha * lagrange) / denom
    n = _scale(d, 1.0 / L)
    return _sub(a, _scale(n, w_a * dl)), _add(b, _scale(n, w_b * dl)), lagrange + dl


def xpbd_step(body, state, h, g, iterations):
    """One XPBD substep: predict, iterations sweeps over the constraints in order, velocities from positions."""
    if not (isinstance(iterations, int) and 1 <= iterations <= MAX_ITERATIONS):
        raise ValueError("iterations are in 1..MAX_ITERATIONS")
    n = len(body["positions"])
    pinned = body["pinned"]
    w = [0.0 if i in pinned else 1.0 / body["masses"][i] for i in range(n)]
    x0 = list(state["positions"])
    x = [x0[i] if i in pinned else _add(_add(x0[i], _scale(state["velocities"][i], h)), _scale(g, h * h)) for i in range(n)]
    lagrange = [0.0] * len(body["constraints"])
    for _ in range(iterations):
        for k, (i, j, rest, compliance) in enumerate(body["constraints"]):
            x[i], x[j], lagrange[k] = xpbd_distance(x[i], x[j], rest, w[i], w[j], lagrange[k], compliance, h)
    damping = body["damping"]
    velocities = [(0.0, 0.0, 0.0) if i in pinned else _scale(_sub(x[i], x0[i]), (1.0 - damping) / h) for i in range(n)]
    return {"positions": x, "velocities": velocities}


def run_rope(body, frames, h, g, iterations, substeps=1, state=None):
    if not (isinstance(frames, int) and 0 <= frames <= MAX_FRAMES):
        raise ValueError("frames are in 0..MAX_FRAMES")
    if not (isinstance(substeps, int) and 1 <= substeps <= MAX_SUBSTEPS):
        raise ValueError("substeps are in 1..MAX_SUBSTEPS")
    state = initial(body) if state is None else {"positions": list(state["positions"]), "velocities": list(state["velocities"])}
    for _ in range(frames * substeps):
        state = xpbd_step(body, state, h / substeps, g, iterations)
    return state


def rod_curvature(positions):
    """The sum of the turning angles between consecutive segments."""
    total = 0.0
    for a, b, c in zip(positions, positions[1:], positions[2:]):
        u, v = _sub(b, a), _sub(c, b)
        nu, nv = _norm(u), _norm(v)
        if nu == 0.0 or nv == 0.0:
            continue
        total += math.acos(max(-1.0, min(1.0, _dot(u, v) / (nu * nv))))
    return total


# --- rule 11: energy and the rest-shape checks ----------------------------------------------------------------


def elastic_energy(body, positions):
    mu, lam = body["material"]
    e = sum(spring_energy(positions[i], positions[j], rest, k) for i, j, rest, k in body["edges"] + body["bends"])
    rest_density = snh_energy(_identity(), mu, lam) if body["tets"] else 0.0
    e += sum(tet_energy(positions, t, inv, vol, mu, lam) - vol * rest_density
             for t, inv, vol in zip(body["tets"], body["tet_inverse"], body["tet_volume"]))
    for c in find_contacts(body, positions):
        e += contact_energy(positions, c, body["thickness"], body["contact_stiffness"])
    return e


def total_energy(body, state):
    """Kinetic plus elastic energy (the tetrahedra's energy relative to the rest state)."""
    kinetic = sum(0.5 * m * _dot(v, v) for m, v in zip(body["masses"], state["velocities"]))
    return kinetic + elastic_energy(body, state["positions"])


def energy_gain(energies):
    """The largest rise between consecutive energies; at most 0 when none rises."""
    return max(b - a for a, b in zip(energies, energies[1:]))


def residual(body, state, g):
    """The largest static force imbalance |grad E - m g| over the free vertices."""
    springs, tets = _incidence(body)
    mu, lam = body["material"]
    contacts = find_contacts(body, state["positions"])
    worst = 0.0
    for i in range(len(body["positions"])):
        if i in body["pinned"]:
            continue
        grad, _ = _vertex_gradient_hessian(body, state["positions"], i, springs, tets, contacts, mu, lam)
        worst = max(worst, _norm(_sub(grad, _scale(g, body["masses"][i]))))
    return worst


def weight(body, g):
    return sum(body["masses"]) * _norm(g)


def hanging_sheet(frames):
    """The 5 x 5 sheet of the SREP's hanging test: its top speed, residual and the sag of its bottom row."""
    body = cloth_body(sheet(5, 5, 1.0, 1.0), stiffness=200.0, bending=0.5, pin="top", damping=0.05)
    state = run(body, frames, 1.0 / 60.0, (0.0, -9.80665, 0.0), iterations=8)
    speed = max(_norm(v) for v in state["velocities"])
    return (speed, residual(body, state, (0.0, -9.80665, 0.0)) / weight(body, (0.0, -9.80665, 0.0)),
            min(p[1] for p in state["positions"]))


def energy_test(frames):
    body = cloth_body(sheet(4, 4, 1.0, 1.0), stiffness=100.0, bending=0.5, pin="none")
    state = initial(body)
    state["positions"] = [(1.2 * p[0], p[1] + 0.05 * math.sin(3.0 * p[0]), 1.1 * p[2]) for p in state["positions"]]
    energies = [total_energy(body, state)]
    for _ in range(frames):
        state = vbd_step(body, state, 1.0 / 60.0, (0.0, 0.0, 0.0), iterations=16)
        energies.append(total_energy(body, state))
    return (energies[0], energies[-1], energy_gain(energies))


def block_test(frames):
    body = solid_body(block(1.0, 1.0, 1.0), youngs=400.0, poisson=0.45, density=1.0, pin="bottom")
    state = run(body, frames, 1.0 / 60.0, (0.0, -9.80665, 0.0), iterations=8, damping=0.1)
    volume = sum(tet_volume(*(state["positions"][i] for i in t)) for t in body["tets"])
    return (volume, min(state["positions"][i][1] for i in range(4, 8)), max(_norm(v) for v in state["velocities"]))


def twist_summary():
    body = cloth_body(sheet(13, 3, 1.2, 0.3), stiffness=300.0, bending=0.2, pin="ends", thickness=0.03, contact_stiffness=2e3)
    out = twist_test(body, turns=1.5, frames=90, H=1.0 / 60.0, iterations=6)
    return (out["intersections"], out["contacts"] > 0, out["max_stretch"])


def rod_test():
    """A six-point rod bent into a sine, pinned at the top, straightening under its bending constraints
    (damping 0.2, no gravity): its curvature before and after 200 frames."""
    body = rope_body(rope(6, 1.0), 1e4, 50.0, "top", damping=0.2)
    state = {"positions": [body["positions"][0]] + [(0.2 * math.sin(2.0 * i), -i / 5.0, 0.0) for i in range(1, 6)],
             "velocities": [(0.0, 0.0, 0.0)] * 6}
    after = run_rope(body, 200, 1.0 / 60.0, (0.0, 0.0, 0.0), 8, 2, state=state)
    return (rod_curvature(state["positions"]), rod_curvature(after["positions"]))


def rope_test(frames):
    body = rope_body(rope(10, 1.0), stiffness=1e4, bending=0.0, pin="top", damping=0.1)
    state = run_rope(body, frames, 1.0 / 60.0, (0.0, -9.80665, 0.0), iterations=8, substeps=4)
    length = sum(_norm(_sub(b, a)) for a, b in zip(state["positions"], state["positions"][1:]))
    return (max(abs(p[0]) + abs(p[2]) for p in state["positions"]), length, max(_norm(v) for v in state["velocities"]))


# --- the numeric table ----------------------------------------------------------------------------------------

TABLE = (
    ("spring energy and force", "(spring_energy((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 1.0, 10.0), spring_force((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 1.0, 10.0))", "(5.0, (10.0, 0.0, 0.0))"),
    ("spring hessian, stretched", "spring_hessian((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 1.0, 10.0)", "((10.0, 0.0, 0.0), (0.0, 5.0, 0.0), (0.0, 0.0, 5.0))"),
    ("spring hessian, compressed", "spring_hessian((0.0, 0.0, 0.0), (0.5, 0.0, 0.0), 1.0, 10.0)", "((10.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))"),
    ("the spring hessian is positive semidefinite", "(is_psd(spring_hessian((0.0, 0.0, 0.0), (0.5, 0.0, 0.0), 1.0, 10.0)), is_psd(((1.0, 0.0, 0.0), (0.0, -2.0, 0.0), (0.0, 0.0, 3.0))))", "(True, False)"),
    ("psd projection", "tuple(tuple(round(v, 9) for v in row) for row in psd_project(((1.0, 0.0, 0.0), (0.0, -2.0, 0.0), (0.0, 0.0, 3.0))))", "((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 3.0))"),
    ("eigenvalues of a symmetric matrix", "tuple(round(v, 9) for v in sorted(eigen_symmetric(((2.0, 1.0, 0.0), (1.0, 2.0, 0.0), (0.0, 0.0, 5.0)))[0]))", "(1.0, 3.0, 5.0)"),
    ("solve3", "tuple(round(v, 12) for v in solve3(((2.0, 1.0, 0.0), (1.0, 3.0, 1.0), (0.0, 1.0, 4.0)), (3.0, 5.0, 5.0)))", "(1.0, 1.0, 1.0)"),
    ("the sheet mesh", "(lambda s: (len(s['positions']), len(s['triangles']), len(s['edges']), len(s['bends'])))(sheet(3, 4, 1.0, 1.5))", "(12, 12, 23, 16)"),
    ("the sheet's corners", "(lambda s: (s['positions'][0], s['positions'][11], round(sum(s['masses']), 12)))(sheet(3, 4, 1.0, 1.5))", "((0.0, 0.0, 0.0), (1.5, 0.0, -1.0), 1.0)"),
    ("pins", "(sorted(pins(sheet(3, 3, 1.0, 1.0), 'top')), sorted(pins(sheet(3, 3, 1.0, 1.0), 'corners')), sorted(pins(sheet(3, 3, 1.0, 1.0), 'ends')))", "([0, 1, 2], [0, 2], [0, 1, 2, 6, 7, 8])"),
    ("the block", "(lambda b: (len(b['tets']), round(sum(tet_volume(*(b['positions'][i] for i in t)) for t in b['tets']), 12), round(sum(b['masses']), 12)))(block(1.0, 1.0, 1.0))", "(6, 1.0, 1.0)"),
    ("tet volume", "tet_volume((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))", "round(1.0 / 6.0, 15)"),
    ("lame", "tuple(round(v, 9) for v in lame(1000.0, 0.3))", "(round(1000.0 / 2.6, 9), round(1000.0 * 0.3 / (1.3 * 0.4), 9))"),
    ("the rest state is stress free", "tuple(round(v, 12) for row in snh_stress(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), 1.0, 10.0) for v in row)", "(0.0,) * 9"),
    ("stretched, sheared, compressed and inverted cost energy", "tuple(round(snh_energy(F, 1.0, 10.0) - snh_energy(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), 1.0, 10.0), 6) for F in (((1.5, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), ((1.0, 0.3, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), ((0.5, 0.0, 0.0), (0.0, 0.5, 0.0), (0.0, 0.0, 0.5)), ((-0.5, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))))", "(1.364033, 0.033875, 3.772714, 12.10382)"),
    ("the stress is the energy's gradient", "round(snh_stress(((1.5, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), 1.0, 10.0)[0][0] - (snh_energy(((1.5 + 1e-6, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), 1.0, 10.0) - snh_energy(((1.5 - 1e-6, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), 1.0, 10.0)) / 2e-6, 6)", "0.0"),
    ("the stress is finite through inversion", "round(snh_stress(((-0.5, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), 1.0, 10.0)[0][0], 6)", "-16.096154"),
    ("free fall is exact", "(lambda s: tuple(round(v, 12) for v in s['positions'][0] + s['velocities'][0]))(run(body([(0.0, 1.0, 0.0)], [1.0], [], [], [], set()), 10, 1.0 / 60.0, (0.0, -9.80665, 0.0), 1))", "(0.0, round(1.0 - 9.80665 * (10 * 11 / 2) / 3600.0, 12), 0.0, 0.0, round(-9.80665 * 10 / 60.0, 12), 0.0)"),
    ("a pinned vertex stays", "run(body([(0.0, 1.0, 0.0)], [1.0], [], [], [], {0}), 10, 1.0 / 60.0, (0.0, -9.80665, 0.0), 1)", "{'positions': [(0.0, 1.0, 0.0)], 'velocities': [(0.0, 0.0, 0.0)]}"),
    ("the hanging sheet comes to rest", "(lambda r: (r[0] < 1e-3, r[1] < 1e-2, round(r[2], 3)))(hanging_sheet(400))", "(True, True, -1.017)"),
    ("no energy gain without forces", "(lambda r: (round(r[0], 6), r[1] < 0.1 * r[0], r[2] <= 0.0))(energy_test(200))", "(4.673716, True, True)"),
    ("the block keeps its volume under gravity", "(lambda r: (round(r[0], 4), round(r[1], 4), r[2] < 1e-2))(block_test(240))", "(0.9977, 0.9841, True)"),
    ("point to triangle", "(round(point_triangle_distance((0.2, 0.5, 0.2), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))[0], 12), round(point_triangle_distance((-1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))[0], 12))", "(0.5, 1.0)"),
    ("barycentric weights", "tuple(round(v, 12) for v in barycentric((0.25, 0.0, 0.25), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))", "(0.5, 0.25, 0.25)"),
    ("edge to edge", "(lambda r: (round(r[0], 12), r[1], r[2]))(edge_edge_distance((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, -1.0), (0.5, 1.0, 1.0)))", "(1.0, (0.5, 0.0, 0.0), (0.5, 1.0, 0.0))"),
    ("a segment through a triangle", "(segment_triangle_intersects((0.2, -1.0, 0.2), (0.2, 1.0, 0.2), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), segment_triangle_intersects((0.2, 0.5, 0.2), (0.2, 1.0, 0.2), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))", "(True, False)"),
    ("triangles intersect", "(triangles_intersect(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), ((0.2, -0.5, 0.2), (0.3, 0.5, 0.2), (0.2, 0.5, 0.3))), triangles_intersect(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), ((0.2, 0.5, 0.2), (0.3, 1.5, 0.2), (0.2, 1.5, 0.3))))", "(True, False)"),
    ("contact energy below the offset", "(lambda b: (round(contact_energy(b['positions'], find_contacts(b, b['positions'])[0], 0.05, 1e4), 6), len(find_contacts(b, b['positions']))))(body(list(sheet(2, 2, 1.0, 1.0)['positions']) + [(0.5, 0.03, -0.5)], [1.0] * 5, [], [], [], {0, 1, 2, 3}, sheet(2, 2, 1.0, 1.0)['triangles'], 0.05, 1e4))", "(2.0, 2)"),
    ("contact stops a vertex at the offset", "(lambda b: (lambda s: (s['positions'][4][1] > 0.05, round(s['positions'][4][1], 4)))(run(b, 60, 1.0 / 60.0, (0.0, 0.0, 0.0), 8, state={'positions': list(b['positions']), 'velocities': [(0.0, 0.0, 0.0)] * 4 + [(0.0, -2.0, 0.0)]})))(body(list(sheet(2, 2, 1.0, 1.0)['positions']) + [(0.5, 0.3, -0.5)], [1.0] * 5, [], [], [], {0, 1, 2, 3}, sheet(2, 2, 1.0, 1.0)['triangles'], 0.05, 1e4))", "(True, 0.1841)"),
    ("the twisting strip has no self-intersections", "(lambda r: (r[0], r[1], round(r[2], 3)))(twist_summary())", "(0, True, 1.343)"),
    ("xpbd distance", "(lambda r: (tuple(round(v, 12) for v in r[0]), tuple(round(v, 12) for v in r[1]), round(r[2], 12)))(xpbd_distance((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 1.0, 1.0, 1.0, 0.0, 0.0, 1.0 / 60.0))", "((0.5, 0.0, 0.0), (1.5, 0.0, 0.0), -0.5)"),
    ("xpbd distance with a pinned end", "(lambda r: (r[0], tuple(round(v, 12) for v in r[1])))(xpbd_distance((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 1.0, 0.0, 1.0, 0.0, 0.0, 1.0 / 60.0))", "((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))"),
    ("the rope hangs straight", "(lambda r: (r[0] < 1e-3, round(r[1], 4), r[2] < 1e-3))(rope_test(600))", "(True, 1.0045, True)"),
    ("bending straightens a rod", "(lambda r: (round(r[0], 4), round(r[1], 4)))(rod_test())", "(5.5979, 0.6064)"),
    ("a run is a function of the frame", "(lambda b: run(b, 30, 1.0 / 60.0, (0.0, -9.80665, 0.0), 4, 2) == run(b, 15, 1.0 / 60.0, (0.0, -9.80665, 0.0), 4, 2, state=run(b, 15, 1.0 / 60.0, (0.0, -9.80665, 0.0), 4, 2)))(cloth_body(sheet(3, 3, 1.0, 1.0), 100.0, 0.5, 'corners'))", "True"),
    ("bounds", "(MAX_VERTICES, MAX_SIDE, MAX_ITERATIONS, MAX_SUBSTEPS, MAX_FRAMES, MAX_HALVINGS)", "(65536, 256, 256, 64, 65536, 8)"),
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
