"""Reference for the draft SREP "Add scattering and vegetation to the terrain grid" (G1 of SREP 12).

Three children of a `terrain` (the F2 terrain-grid draft): `tree` prototypes grown by an L-system (Lindenmayer;
Prusinkiewicz and Lindenmayer 1990), by space colonisation (Runions, Lane and Prusinkiewicz 2007) or by the
parametric model of Weber and Penn (1995); `scatter` elements that place a prototype on the terrain by Bridson's
(2007) Poisson-disk sampling, gated by a terrain mask, with every draw from the random streams, exchanged as a
USD PointInstancer or a glTF node with EXT_mesh_gpu_instancing written and read by this module; and one
`ecosystem` that starts from a scatter and grows it year by year with logistic growth, death by age, offspring
and the self-thinning of Deussen et al. (1998). Every instance sways as a cantilever under the drag of the
wind-field draft's wind at its own position. `python vegetation_reference.py` prints the numeric table of the
draft's conformance section.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import math
import os
import re
import struct

HERE = os.path.dirname(os.path.abspath(__file__))

SCATTER_PURPOSE = 1          # S(e, 1, n, k): draw n of the sampling, k its component
LSYSTEM_PURPOSE = 1          # S(e, 1, iteration, position): a stochastic rule's choice
ATTRACTOR_PURPOSE = 2        # S(e, 2, k, 0..2): the k-th attractor
PARAMETRIC_PURPOSE = 3       # S(e, 3, stem, 0..1): a stem's length and down-angle variation
SPECIES_PURPOSE = 1          # S(e, 1, 0, k): the species of the k-th founding plant
OFFSPRING_PURPOSE = 2        # S(e, 2, year, plant * 64 + k + 32 * component)
YAW_PURPOSE = 3              # S(e, 3, 0, plant): a plant's yaw
MAX_ITERATIONS = 12
MAX_STEMS = 100000
MAX_PLANTS = 1000000
SEED_DRAWS = 1000            # uniform draws tried for a scatter's first point
AIR_DENSITY = 1.225          # kg/m^3
DRAG_COEFFICIENT = 0.5       # of a crown (Mayhead 1973 range 0.2 to 0.6 at speed)
MAX_DEFLECTION = 0.5         # of the height
SEEDLING_RADIUS = 0.25       # m
DIGEST_DECIMALS = 3
SHAPES = ("conical", "spherical", "hemispherical", "cylindrical", "taperedCylindrical", "flame", "inverseConical",
          "tendFlame")
METHODS = ("lsystem", "colonisation", "parametric")
SCATTER_DEFAULTS = {"radius": 1.0, "mask": None, "density": 1.0, "attempts": 30, "maxPoints": 100000,
                    "scaleMin": 1.0, "scaleMax": 1.0, "rotate": True, "prototype": None, "wind": None, "seed": None}
LSYSTEM_DEFAULTS = {"axiom": "F", "rules": (), "iterations": 4, "angle": 25.0, "length": 1.0, "lengthRatio": 1.0,
                    "radius": 0.05, "radiusRatio": 1.0, "maxSymbols": 1000000}
COLONISATION_DEFAULTS = {"attractors": 200, "crownRadius": 2.0, "crownHeight": 3.0, "crownBase": 2.0,
                         "influence": 1.5, "kill": 0.4, "segment": 0.2, "maxIterations": 1000, "tipRadius": 0.01}
PARAMETRIC_DEFAULTS = {"levels": 3, "scale": 10.0, "baseSize": 0.3, "ratio": 0.015, "ratioPower": 1.2,
                       "shape": "conical", "length": (1.0, 0.5, 0.4, 0.3), "lengthVariation": (0.0,),
                       "branches": (1, 8, 5, 3), "downAngle": (0.0, 60.0, 45.0, 45.0), "downAngleVariation": (0.0,),
                       "rotate": (0.0, 140.0, 140.0, 77.0), "curve": (0.0,), "curveRes": (5, 4, 3, 2)}
SWAY_DEFAULTS = {"dragArea": 20.0, "stiffness": 2.0e6}
ECOSYSTEM_DEFAULTS = {"yearsPerSecond": 1.0, "maxYears": 10000}
SPECIES_DEFAULTS = {"growth": 0.3, "maxRadius": 5.0, "maxAge": 100, "maturity": 5, "offspring": 1, "spread": 5.0}


class VegetationError(ValueError):
    """A scatter, tree or ecosystem outside the draft's rules or bounds."""


# ------------------------------------------------------------------------------------------------- the references

_modules = {}


def _load(name):
    if name not in _modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _modules[name] = mod
    return _modules[name]


def terrain():
    return _load("terrain_grid_reference")


def streams():
    return _load("random_streams_reference")


def wind():
    return _load("wind_reference")


def _project_seed(doc):
    project = doc.get("project", 0)
    if isinstance(project, dict):
        return project.get("seed", 0)
    return project


def _get(spec, key, defaults):
    return spec[key] if key in spec and spec[key] is not None else defaults[key]


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


def digest(obj):
    """sha256 of the object as JSON with sorted keys and floats rounded to three decimals."""
    def rnd(v):
        if isinstance(v, float):
            return round(v, DIGEST_DECIMALS)
        if isinstance(v, dict):
            return {k: rnd(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [rnd(x) for x in v]
        return v
    text = json.dumps(rnd(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------- Poisson-disk scattering


def scatter_seed(doc, spec):
    """E(project, id, seed, "scatter")."""
    return streams().E(_project_seed(doc), spec["id"], spec.get("seed"), "scatter")


def first_point(spec, e, width, height):
    """The first uniform draw: (S(e, 1, 0, 0) width, S(e, 1, 0, 1) height)."""
    rs = streams()
    return (rs.S(e, SCATTER_PURPOSE, 0, 0) * width, rs.S(e, SCATTER_PURPOSE, 0, 1) * height)


def candidate(centre, r, e, n):
    """Draw n's candidate in the annulus [r, 2 r] around the centre: angle 2 pi S(e, 1, n, 0), distance
    r (1 + S(e, 1, n, 1))."""
    rs = streams()
    a = 2.0 * math.pi * rs.S(e, SCATTER_PURPOSE, n, 0)
    d = r * (1.0 + rs.S(e, SCATTER_PURPOSE, n, 1))
    return (centre[0] + d * math.cos(a), centre[1] + d * math.sin(a))


def _mask_grid(doc, spec, layers):
    mask_id = spec.get("mask")
    if mask_id is None:
        return None
    m = next((m for m in doc.get("masks", ()) if m.get("id") == mask_id), None)
    if m is None:
        raise VegetationError(f"VG2: mask {mask_id!r} is not a mask of the terrain")
    return terrain().mask(doc, layers, m)


class _Hash:
    """Points in buckets of side r / sqrt(2), so that a bucket holds at most one sample and the neighbours within
    two buckets are the candidates for a conflict."""

    def __init__(self, r):
        self.side = r / math.sqrt(2.0)
        self.buckets = {}

    def key(self, p):
        return (math.floor(p[0] / self.side), math.floor(p[1] / self.side))

    def add(self, p):
        self.buckets.setdefault(self.key(p), []).append(p)

    def near(self, p, r):
        a, b = self.key(p)
        for i in range(a - 2, a + 3):
            for j in range(b - 2, b + 3):
                for q in self.buckets.get((i, j), ()):
                    if math.hypot(q[0] - p[0], q[1] - p[1]) < r:
                        return True
        return False


def scatter_on(doc, spec, layers):
    """Bridson 2007 over the terrain's rectangle (grid metres, i right, j down): the first point is the first of
    at most SEED_DRAWS uniform draws that the mask admits; then, while points are active, draw n picks an active
    point (S(e, 1, n, 2)) and offers up to `attempts` candidates in its annulus, accepting the first that lies on
    the grid, is at least r from every point and passes the mask (S(e, 1, n, 3) < mask * density); an active point
    with no accepted candidate retires. A point's scale is scaleMin + (scaleMax - scaleMin) S(e, 1, n, 4) and
    its yaw 360 S(e, 1, n, 5) degrees when `rotate`, else 0. Stops at maxPoints."""
    rs = streams()
    tg = terrain()
    nx, ny = tg.grid(doc)
    dx = float(doc.get("metersPerCell", 1.0))
    width, height = nx * dx, ny * dx
    r = float(_get(spec, "radius", SCATTER_DEFAULTS))
    k = int(_get(spec, "attempts", SCATTER_DEFAULTS))
    cap = int(_get(spec, "maxPoints", SCATTER_DEFAULTS))
    density = float(_get(spec, "density", SCATTER_DEFAULTS))
    s_min = float(_get(spec, "scaleMin", SCATTER_DEFAULTS))
    s_max = float(_get(spec, "scaleMax", SCATTER_DEFAULTS))
    rotate = bool(_get(spec, "rotate", SCATTER_DEFAULTS))
    e = scatter_seed(doc, spec)
    mask = _mask_grid(doc, spec, layers)
    ground = tg.surface(layers)

    def cell(p):
        return (min(nx - 1, int(p[0] // dx)), min(ny - 1, int(p[1] // dx)))

    def admitted(p, n):
        if not (0.0 <= p[0] < width and 0.0 <= p[1] < height):
            return False
        i, j = cell(p)
        m = (mask[j][i] if mask is not None else 1.0) * density
        return m > 0.0 and rs.S(e, SCATTER_PURPOSE, n, 3) < m

    def point(p, n):
        i, j = cell(p)
        return {"position": (p[0], p[1]), "height": ground[j][i],
                "yaw": 360.0 * rs.S(e, SCATTER_PURPOSE, n, 5) if rotate else 0.0,
                "scale": s_min + (s_max - s_min) * rs.S(e, SCATTER_PURPOSE, n, 4)}

    points = []
    grid = _Hash(r)
    active = []
    n = 0
    while n < SEED_DRAWS and cap > 0:
        p = (rs.S(e, SCATTER_PURPOSE, n, 0) * width, rs.S(e, SCATTER_PURPOSE, n, 1) * height)
        if admitted(p, n):
            points.append(point(p, n))
            grid.add(p)
            active.append(p)
            n += 1
            break
        n += 1
    while active and len(points) < cap:
        pick = min(len(active) - 1, int(rs.S(e, SCATTER_PURPOSE, n, 2) * len(active)))
        centre = active[pick]
        found = False
        for _ in range(k):
            c = candidate(centre, r, e, n)
            if not grid.near(c, r) and admitted(c, n):
                points.append(point(c, n))
                grid.add(c)
                active.append(c)
                found = True
                n += 1
                break
            n += 1
        if not found:
            active[pick] = active[-1]
            active.pop()
    return {"points": points, "count": len(points), "seed": e, "digest": digest(points)}


def scatter(doc, spec):
    built = terrain().build(doc)
    return scatter_on(doc, spec, built["layers"])


# ------------------------------------------------------------------------------------------- exchange (USD, glTF)


def instance_transform(pt):
    """Translation, rotation (x, y, z, w) and scale of an instance in the y-up frame of USD and glTF: the grid's
    (x, y, height) maps to (x, height, y); the yaw turns about +y."""
    x, y = pt["position"]
    half = math.radians(pt["yaw"]) / 2.0
    s = pt["scale"]
    return (x, pt["height"], y), (0.0, math.sin(half), 0.0, math.cos(half)), (s, s, s)


def _point_from_transform(t, r, s):
    yaw = math.degrees(2.0 * math.atan2(r[1], r[3])) % 360.0
    return {"position": (t[0], t[2]), "height": t[1], "yaw": yaw, "scale": s[0]}


def same_point(p, q, tol=1e-9):
    """Equal within tol on the position, height and scale, and within 360 tol degrees of yaw."""
    dyaw = abs((p["yaw"] - q["yaw"] + 180.0) % 360.0 - 180.0)
    return (all(abs(a - b) <= tol for a, b in zip(p["position"], q["position"])) and abs(p["height"] - q["height"]) <= tol
            and abs(p["scale"] - q["scale"]) <= tol and dyaw <= 360.0 * tol)


def to_point_instancer(points, name, prototype="/Prototypes/tree"):
    """A usda text with one PointInstancer: positions (point3f), orientations (quath, real part first), scales
    (float3), protoIndices (all 0) and one prototype path."""
    t_r_s = [instance_transform(p) for p in points]
    lines = ["#usda 1.0", "(", '    upAxis = "Y"', '    metersPerUnit = 1', ")", "", f'def PointInstancer "{name}"', "{",
             "    int[] protoIndices = [" + ", ".join("0" for _ in points) + "]",
             "    point3f[] positions = [" + ", ".join(f"({t[0]!r}, {t[1]!r}, {t[2]!r})" for t, _, _ in t_r_s) + "]",
             "    quath[] orientations = [" + ", ".join(f"({r[3]!r}, {r[0]!r}, {r[1]!r}, {r[2]!r})" for _, r, _ in t_r_s) + "]",
             "    float3[] scales = [" + ", ".join(f"({s[0]!r}, {s[1]!r}, {s[2]!r})" for _, _, s in t_r_s) + "]",
             f"    rel prototypes = <{prototype}>", "}", ""]
    return "\n".join(lines)


_ARRAY = re.compile(r"(\w+)\[\]\s+(\w+)\s*=\s*\[(.*?)\]", re.S)
_TUPLE = re.compile(r"\(([^()]*)\)")


def from_point_instancer(text):
    arrays = {m.group(2): m.group(3) for m in _ARRAY.finditer(text)}
    positions = [tuple(float(v) for v in m.group(1).split(",")) for m in _TUPLE.finditer(arrays["positions"])]
    quats = [tuple(float(v) for v in m.group(1).split(",")) for m in _TUPLE.finditer(arrays["orientations"])]
    scales = [tuple(float(v) for v in m.group(1).split(",")) for m in _TUPLE.finditer(arrays["scales"])]
    out = []
    for t, q, s in zip(positions, quats, scales):
        out.append(_point_from_transform(t, (q[1], q[2], q[3], q[0]), s))
    return out


def to_gltf_instancing(points, name):
    """A glTF 2.0 asset with one node carrying EXT_mesh_gpu_instancing: TRANSLATION (VEC3), ROTATION (VEC4) and
    SCALE (VEC3) float accessors over one embedded little-endian buffer."""
    t_r_s = [instance_transform(p) for p in points]
    n = len(points)
    blobs = [b"".join(struct.pack("<3f", *t) for t, _, _ in t_r_s), b"".join(struct.pack("<4f", *r) for _, r, _ in t_r_s),
             b"".join(struct.pack("<3f", *s) for _, _, s in t_r_s)]
    views, accessors, offset = [], [], 0
    for blob, kind, comps in zip(blobs, ("VEC3", "VEC4", "VEC3"), (3, 4, 3)):
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(blob)})
        acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": n, "type": kind}
        if n:
            vals = struct.unpack(f"<{n * comps}f", blob)
            acc["min"] = [min(vals[c::comps]) for c in range(comps)]
            acc["max"] = [max(vals[c::comps]) for c in range(comps)]
        accessors.append(acc)
        offset += len(blob)
    data = b"".join(blobs)
    return {
        "asset": {"version": "2.0", "generator": "sr-core vegetation_reference"},
        "extensionsUsed": ["EXT_mesh_gpu_instancing"], "extensionsRequired": ["EXT_mesh_gpu_instancing"],
        "buffers": [{"byteLength": len(data), "uri": "data:application/octet-stream;base64," + base64.b64encode(data).decode("ascii")}],
        "bufferViews": views, "accessors": accessors,
        "nodes": [{"name": name, "extensions": {"EXT_mesh_gpu_instancing": {"attributes": {"TRANSLATION": 0, "ROTATION": 1, "SCALE": 2}}}}],
        "scenes": [{"nodes": [0]}], "scene": 0,
    }


def from_gltf_instancing(g):
    uri = g["buffers"][0]["uri"]
    data = base64.b64decode(uri.split(",", 1)[1])
    node = g["nodes"][0]
    attrs = node["extensions"]["EXT_mesh_gpu_instancing"]["attributes"]

    def read(index, comps):
        acc = g["accessors"][index]
        view = g["bufferViews"][acc["bufferView"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        vals = struct.unpack_from(f"<{acc['count'] * comps}f", data, start)
        return [vals[k:k + comps] for k in range(0, len(vals), comps)]

    out = []
    for t, r, s in zip(read(attrs["TRANSLATION"], 3), read(attrs["ROTATION"], 4), read(attrs["SCALE"], 3)):
        out.append(_point_from_transform(t, r, s))
    return out


# ------------------------------------------------------------------------------------------- L-systems


def _rules(spec):
    table = {}
    for rule in spec.get("rules", ()) or ():
        table.setdefault(rule["from"], []).append((rule["to"], float(rule.get("weight", 1.0))))
    return table


def lsystem_string(spec, iterations, e=None):
    """The axiom rewritten `iterations` times (at most MAX_ITERATIONS, at most maxSymbols symbols); a symbol
    with several rules takes the one whose cumulative weight passes S(e, 1, iteration, position)."""
    if not _integer(iterations) or iterations < 0 or iterations > MAX_ITERATIONS:
        raise VegetationError(f"VG4: iterations is an integer in [0, {MAX_ITERATIONS}]")
    limit = int(_get(spec, "maxSymbols", LSYSTEM_DEFAULTS))
    table = _rules(spec)
    rs = streams()
    s = str(_get(spec, "axiom", LSYSTEM_DEFAULTS))
    for it in range(iterations):
        out = []
        for pos, ch in enumerate(s):
            options = table.get(ch)
            if not options:
                out.append(ch)
            elif len(options) == 1:
                out.append(options[0][0])
            else:
                if e is None:
                    raise VegetationError("VG4: stochastic rules need the tree's element seed")
                total = sum(w for _, w in options)
                u = rs.S(e, LSYSTEM_PURPOSE, it, pos) * total
                acc = 0.0
                chosen = options[-1][0]
                for to, w in options:
                    acc += w
                    if u < acc:
                        chosen = to
                        break
                out.append(chosen)
        s = "".join(out)
        if len(s) > limit:
            raise VegetationError(f"VG4: the L-system passed maxSymbols ({limit}) at iteration {it + 1}")
    return s


def _rot(frame, axis, degrees):
    """Rotate the frame (H, L, U as columns) about one of its own axes: 'U' (turn), 'L' (pitch), 'H' (roll)."""
    h, l_, u = frame
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))

    def comb(a, b, ca, sa):
        return tuple(ca * a[k] + sa * b[k] for k in range(3))
    if axis == "U":
        return comb(h, l_, c, s), comb(l_, h, c, -s), u
    if axis == "L":
        return comb(h, u, c, -s), l_, comb(u, h, c, s)
    return h, comb(l_, u, c, s), comb(u, l_, c, -s)


def turtle(s, spec):
    """The 3D turtle of Prusinkiewicz and Lindenmayer (1990): heading up (+z), F draws a segment of
    length lengthRatio^depth and radius radiusRatio^depth times the base values, f moves, + - turn about U,
    & ^ pitch about L, \\ / roll about H, | turns around, [ ] push and pop (depth + 1 inside)."""
    angle = float(_get(spec, "angle", LSYSTEM_DEFAULTS))
    base_len = float(_get(spec, "length", LSYSTEM_DEFAULTS))
    len_ratio = float(_get(spec, "lengthRatio", LSYSTEM_DEFAULTS))
    base_rad = float(_get(spec, "radius", LSYSTEM_DEFAULTS))
    rad_ratio = float(_get(spec, "radiusRatio", LSYSTEM_DEFAULTS))
    pos = (0.0, 0.0, 0.0)
    frame = ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    depth = 0
    stack = []
    segments = []
    for ch in s:
        if ch in "Ff":
            step = base_len * len_ratio ** depth
            end = tuple(pos[k] + frame[0][k] * step for k in range(3))
            if ch == "F":
                segments.append({"start": pos, "end": end, "radius": base_rad * rad_ratio ** depth, "depth": depth})
            pos = end
        elif ch == "+":
            frame = _rot(frame, "U", angle)
        elif ch == "-":
            frame = _rot(frame, "U", -angle)
        elif ch == "&":
            frame = _rot(frame, "L", angle)
        elif ch == "^":
            frame = _rot(frame, "L", -angle)
        elif ch == "\\":
            frame = _rot(frame, "H", angle)
        elif ch == "/":
            frame = _rot(frame, "H", -angle)
        elif ch == "|":
            frame = _rot(frame, "U", 180.0)
        elif ch == "[":
            stack.append((pos, frame, depth))
            depth += 1
        elif ch == "]":
            if not stack:
                raise VegetationError("VG4: a ] without a [")
            pos, frame, depth = stack.pop()
    return segments


def tree_seed(doc, spec):
    return streams().E(_project_seed(doc), spec["id"], spec.get("seed"), "tree")


def lsystem_tree(doc, spec):
    e = tree_seed(doc, spec)
    s = lsystem_string(spec, int(_get(spec, "iterations", LSYSTEM_DEFAULTS)), e)
    segments = turtle(s, spec)
    return {"method": "lsystem", "segments": segments, "symbols": len(s), "height": _height(segments),
            "digest": digest(segments)}


def _height(segments):
    return max((max(s["start"][2], s["end"][2]) for s in segments), default=0.0)


# ------------------------------------------------------------------------------------------- space colonisation


def attractor_point(u, spec):
    """A point uniform in the crown ellipsoid (semi-axes crownRadius, crownRadius, crownHeight / 2, centred
    crownBase + crownHeight / 2 up the trunk) from three unit draws: radius u0^(1/3), azimuth 2 pi u1,
    cos(polar) 2 u2 - 1."""
    rr = float(_get(spec, "crownRadius", COLONISATION_DEFAULTS))
    hh = float(_get(spec, "crownHeight", COLONISATION_DEFAULTS))
    base = float(_get(spec, "crownBase", COLONISATION_DEFAULTS))
    rad = u[0] ** (1.0 / 3.0)
    az = 2.0 * math.pi * u[1]
    cz = 2.0 * u[2] - 1.0
    sz = math.sqrt(max(0.0, 1.0 - cz * cz))
    return (rr * rad * sz * math.cos(az), rr * rad * sz * math.sin(az), base + hh / 2.0 + hh / 2.0 * rad * cz)


def attractors(spec, e):
    rs = streams()
    n = int(_get(spec, "attractors", COLONISATION_DEFAULTS))
    return [attractor_point((rs.S(e, ATTRACTOR_PURPOSE, k, 0), rs.S(e, ATTRACTOR_PURPOSE, k, 1),
                             rs.S(e, ATTRACTOR_PURPOSE, k, 2)), spec) for k in range(n)]


def colonise(doc, spec):
    """Runions, Lane and Prusinkiewicz 2007: from a root at the origin the trunk grows straight up by one segment
    per iteration until an attractor is within the influence distance of a node; then each iteration assigns
    every live attractor to its nearest node within the influence distance, grows from each such node one
    segment toward the mean direction of its attractors, and kills the attractors within the kill distance of a
    node; it stops when no attractor influences a node, when an iteration adds nothing, or at maxIterations.
    Radii follow Murray's law with exponent 2 from tipRadius at the leaves."""
    e = tree_seed(doc, spec)
    pts = attractors(spec, e)
    alive = [True] * len(pts)
    d_i = float(_get(spec, "influence", COLONISATION_DEFAULTS))
    d_k = float(_get(spec, "kill", COLONISATION_DEFAULTS))
    seg = float(_get(spec, "segment", COLONISATION_DEFAULTS))
    limit = int(_get(spec, "maxIterations", COLONISATION_DEFAULTS))
    tip = float(_get(spec, "tipRadius", COLONISATION_DEFAULTS))
    nodes = [(0.0, 0.0, 0.0)]
    parents = [None]
    killed = 0

    def kill_near(node):
        nonlocal killed
        for a, p in enumerate(pts):
            if alive[a] and math.dist(p, node) <= d_k:
                alive[a] = False
                killed += 1

    kill_near(nodes[0])
    iterations = 0
    while iterations < limit:
        iterations += 1
        pulls = {}
        for a, p in enumerate(pts):
            if not alive[a]:
                continue
            best, best_d = None, d_i
            for k, node in enumerate(nodes):
                d = math.dist(p, node)
                if d <= best_d:
                    best, best_d = k, d
            if best is not None:
                node = nodes[best]
                d = max(best_d, 1e-12)
                acc = pulls.setdefault(best, [0.0, 0.0, 0.0])
                for c in range(3):
                    acc[c] += (p[c] - node[c]) / d
        if not pulls:
            if any(alive):
                top = nodes[-1] if parents[-1] is None or parents[-1] == len(nodes) - 2 else nodes[0]
                new = (top[0], top[1], top[2] + seg)
                nodes.append(new)
                parents.append(len(nodes) - 2)
                kill_near(new)
                continue
            iterations -= 1
            break
        added = 0
        for k in sorted(pulls):
            v = pulls[k]
            norm = math.hypot(*v)
            if norm < 1e-9:
                continue
            node = nodes[k]
            new = tuple(node[c] + seg * v[c] / norm for c in range(3))
            if any(math.dist(new, q) < 1e-9 for q in nodes):
                continue
            nodes.append(new)
            parents.append(k)
            added += 1
            kill_near(new)
        if added == 0:
            break
    radii = [0.0] * len(nodes)
    sums = [0.0] * len(nodes)
    has_child = [False] * len(nodes)
    for k, p in enumerate(parents):
        if p is not None:
            has_child[p] = True
    for k in range(len(nodes) - 1, -1, -1):
        radii[k] = math.sqrt(sums[k]) if has_child[k] else tip
        if parents[k] is not None:
            sums[parents[k]] += radii[k] ** 2
    segments = [{"start": nodes[parents[k]], "end": nodes[k], "radius": radii[k]} for k in range(1, len(nodes))]
    return {"method": "colonisation", "nodes": nodes, "parents": parents, "radii": radii, "segments": segments,
            "attractors": [{"position": p, "alive": alive[a]} for a, p in enumerate(pts)], "killed": killed,
            "iterations": iterations, "height": _height(segments) if segments else 0.0, "digest": digest(segments)}


# ------------------------------------------------------------------------------------------- Weber and Penn


def shape_ratio(shape, ratio):
    """Weber and Penn 1995, table 1: the crown shape as the relative branch length at a relative height."""
    if shape == "conical":
        return 0.2 + 0.8 * ratio
    if shape == "spherical":
        return 0.2 + 0.8 * math.sin(math.pi * ratio)
    if shape == "hemispherical":
        return 0.2 + 0.8 * math.sin(0.5 * math.pi * ratio)
    if shape == "cylindrical":
        return 1.0
    if shape == "taperedCylindrical":
        return 0.5 + 0.5 * ratio
    if shape == "flame":
        return ratio / 0.7 if ratio <= 0.7 else (1.0 - ratio) / 0.3
    if shape == "inverseConical":
        return 1.0 - 0.8 * ratio
    if shape == "tendFlame":
        return 0.5 + 0.5 * ratio / 0.7 if ratio <= 0.7 else 0.5 + 0.5 * (1.0 - ratio) / 0.3
    raise VegetationError(f"VG4: shape is one of {', '.join(SHAPES)}, not {shape!r}")


def _level(spec, key, level):
    values = _get(spec, key, PARAMETRIC_DEFAULTS)
    if isinstance(values, (int, float)):
        return values
    return values[min(level, len(values) - 1)]


def _perp(d):
    """Two unit vectors perpendicular to d."""
    a = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    p = (d[1] * a[2] - d[2] * a[1], d[2] * a[0] - d[0] * a[2], d[0] * a[1] - d[1] * a[0])
    n = math.hypot(*p)
    p = tuple(v / n for v in p)
    q = (d[1] * p[2] - d[2] * p[1], d[2] * p[0] - d[0] * p[2], d[0] * p[1] - d[1] * p[0])
    return p, q


def _tilt(d, degrees, azimuth):
    """d turned by `degrees` away from itself toward the perpendicular at `azimuth` (degrees)."""
    p, q = _perp(d)
    a, b = math.radians(degrees), math.radians(azimuth)
    ca, sa = math.cos(a), math.sin(a)
    cb, sb = math.cos(b), math.sin(b)
    return tuple(ca * d[c] + sa * (cb * p[c] + sb * q[c]) for c in range(3))


def _polyline(start, direction, length, res, curve):
    """res segments of length / res, the direction turning curve / res degrees per segment in its own plane."""
    pts = [start]
    d = direction
    p, _ = _perp(d)
    axis_p = p
    for k in range(res):
        if k > 0 and curve != 0.0:
            a = math.radians(curve / res)
            d = tuple(math.cos(a) * d[c] + math.sin(a) * axis_p[c] for c in range(3))
            n = math.hypot(*d)
            d = tuple(v / n for v in d)
            # keep the bending axis perpendicular to the new direction (rotate it with the stem)
            axis_p = tuple(math.cos(a) * axis_p[c] - math.sin(a) * pts[-1 - 0][c] * 0.0 for c in range(3))
            pp, qq = _perp(d)
            # project the old bending direction on the new perpendicular plane
            dot_p = sum(axis_p[c] * pp[c] for c in range(3))
            dot_q = sum(axis_p[c] * qq[c] for c in range(3))
            n = math.hypot(dot_p, dot_q)
            axis_p = tuple((dot_p * pp[c] + dot_q * qq[c]) / n for c in range(3)) if n > 0.0 else pp
        pts.append(tuple(pts[-1][c] + d[c] * length / res for c in range(3)))
    return pts


def _along(pts, offset):
    """The point and unit direction of the polyline at arc length offset."""
    walked = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if offset <= walked + seg or (a, b) == (pts[-2], pts[-1]):
            t = min(1.0, max(0.0, (offset - walked) / seg)) if seg > 0.0 else 0.0
            d = tuple((b[c] - a[c]) / seg for c in range(3)) if seg > 0.0 else (0.0, 0.0, 1.0)
            return tuple(a[c] + t * (b[c] - a[c]) for c in range(3)), d
        walked += seg
    return pts[-1], (0.0, 0.0, 1.0)


def weber_penn(doc, spec):
    """Weber and Penn 1995, reduced: `levels` levels of stems; the trunk has length scale * length[0] and radius
    length * ratio; a level-n stem gets branches[n] children spread evenly along it (from baseSize of the trunk),
    each leaving at downAngle[n] from the parent with rotate[n] of azimuth between successive children, with
    length parent * length[n] * shapeRatio(shape, position) at level 1 and length[n] * (parent - 0.6 offset)
    deeper, radius parent_radius * (length / parent_length)^ratioPower, in curveRes[n] segments turning
    curve[n] over the stem. lengthVariation[n] and downAngleVariation[n] scale S(e, 3, stem, 0 | 1)."""
    rs = streams()
    e = tree_seed(doc, spec)
    levels = int(_get(spec, "levels", PARAMETRIC_DEFAULTS))
    scale = float(_get(spec, "scale", PARAMETRIC_DEFAULTS))
    base_size = float(_get(spec, "baseSize", PARAMETRIC_DEFAULTS))
    ratio = float(_get(spec, "ratio", PARAMETRIC_DEFAULTS))
    power = float(_get(spec, "ratioPower", PARAMETRIC_DEFAULTS))
    shape = _get(spec, "shape", PARAMETRIC_DEFAULTS)
    if shape not in SHAPES:
        raise VegetationError(f"VG4: shape is one of {', '.join(SHAPES)}, not {shape!r}")
    expected = 1
    for lv in range(levels):
        expected *= max(1, int(_level(spec, "branches", lv)))
        if expected > MAX_STEMS:
            raise VegetationError(f"VG4: more than {MAX_STEMS} stems")
    stems, segments = [], []

    def variation(key, lv, index, comp):
        v = float(_level(spec, key, lv)) if key in spec or key in PARAMETRIC_DEFAULTS else 0.0
        return v * (2.0 * rs.S(e, PARAMETRIC_PURPOSE, index, comp) - 1.0) if v else 0.0

    def grow(level, parent, offset, start, direction, length, radius):
        index = len(stems)
        res = max(1, int(_level(spec, "curveRes", level)))
        curve = float(_level(spec, "curve", level))
        pts = _polyline(start, direction, length, res, curve)
        stems.append({"level": level, "parent": parent, "offset": offset, "start": start, "direction": direction,
                      "length": length, "radius": radius, "points": pts})
        for a, b in zip(pts, pts[1:]):
            segments.append({"start": a, "end": b, "radius": radius, "level": level})
        if level + 1 >= levels:
            return
        count = max(0, int(_level(spec, "branches", level + 1)))
        first = base_size * length if level == 0 else 0.0
        span = length - first
        for k in range(count):
            child_index = len(stems)
            off = first + (k + 0.5) / count * span
            point, d = _along(pts, off)
            down = float(_level(spec, "downAngle", level + 1)) + variation("downAngleVariation", level + 1, child_index, 1)
            az = k * float(_level(spec, "rotate", level + 1))
            cd = _tilt(d, down, az)
            rel = (length - off) / span if span > 0.0 else 1.0
            lf = float(_level(spec, "length", level + 1)) * (1.0 + variation("lengthVariation", level + 1, child_index, 0))
            cl = length * lf * shape_ratio(shape, rel) if level == 0 else lf * (length - 0.6 * off)
            cl = max(cl, 0.0)
            cr = radius * (cl / length) ** power if length > 0.0 else 0.0
            grow(level + 1, index, off, point, cd, cl, cr)

    trunk_len = scale * float(_level(spec, "length", 0)) * (1.0 + variation("lengthVariation", 0, 0, 0))
    grow(0, None, 0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), trunk_len, trunk_len * ratio)
    return {"method": "parametric", "stems": stems, "segments": segments, "height": _height(segments),
            "digest": digest(segments)}


# ------------------------------------------------------------------------------------------- trees and sway


def tree(doc, spec):
    method = spec.get("method", "lsystem")
    if method == "lsystem":
        return lsystem_tree(doc, spec)
    if method == "colonisation":
        return colonise(doc, spec)
    if method == "parametric":
        return weber_penn(doc, spec)
    raise VegetationError(f"VG4: method is one of {', '.join(METHODS)}, not {method!r}")


def sway(tree_params, w):
    """A cantilever under the crown's drag: F = 1/2 rho Cd A |w|^2, tip deflection F H^3 / (3 EI) capped at
    MAX_DEFLECTION H, the lean angle atan(deflection / H) in degrees, toward the wind."""
    speed = math.hypot(w[0], w[1])
    h = float(tree_params["height"])
    if speed <= 0.0 or h <= 0.0:
        return {"angle": 0.0, "direction": (1.0, 0.0), "deflection": 0.0}
    force = 0.5 * AIR_DENSITY * DRAG_COEFFICIENT * float(_get(tree_params, "dragArea", SWAY_DEFAULTS)) * speed ** 2
    deflection = min(force * h ** 3 / (3.0 * float(_get(tree_params, "stiffness", SWAY_DEFAULTS))), MAX_DEFLECTION * h)
    return {"angle": math.degrees(math.atan(deflection / h)), "direction": (w[0] / speed, w[1] / speed),
            "deflection": deflection}


def wind_at_point(doc, wind_id, x, y, t):
    """The grid-space wind (w_x, -w_y) at the grid point (x, y): the wind-field draft's planar wind at the physics
    point (x, -y)."""
    shim = {"project": {"seed": _project_seed(doc)}, "physics": doc.get("physics", {})}
    wx, wy = wind().wind_at(shim, wind_id, (x, -y), t)
    return (wx, -wy)


# ------------------------------------------------------------------------------------------- ecosystem


def years_for(t, years_per_second, max_years):
    return min(int(round(t * years_per_second)), int(max_years))


def ecosystem_seed(doc, spec):
    return streams().E(_project_seed(doc), spec.get("id", "ecosystem"), spec.get("seed"), "ecosystem")


class _PlantGrid:
    def __init__(self, side):
        self.side = max(side, 1e-9)
        self.cells = {}

    def key(self, p):
        return (math.floor(p[0] / self.side), math.floor(p[1] / self.side))

    def add(self, plant):
        self.cells.setdefault(self.key(plant["position"]), []).append(plant)

    def overlapping(self, position, radius):
        a, b = self.key(position)
        for i in range(a - 1, a + 2):
            for j in range(b - 1, b + 2):
                for q in self.cells.get((i, j), ()):
                    if math.hypot(q["position"][0] - position[0], q["position"][1] - position[1]) < radius + q["radius"]:
                        return True
        return False


def ecosystem_on(doc, t, layers):
    """Deussen et al. 1998 on the scatter's points: every plant starts as a seedling of SEEDLING_RADIUS; each
    year it ages, grows by growth (1 - r / maxRadius), dies at maxAge and, from `maturity` years of age, spawns
    `offspring` seedlings at r + spread S from itself at azimuth 2 pi S' where the grid, the mask and the other
    plants admit them; then
    the stand thins: plants are kept largest first, an overlapping smaller plant dies. years_for(t) years."""
    rs = streams()
    tg = terrain()
    spec = doc["ecosystem"]
    sc = next((s for s in doc.get("scatters", ()) if s.get("id") == spec.get("scatter")), None)
    if sc is None:
        raise VegetationError("VG5: the ecosystem's scatter is not a scatter of the terrain")
    species = [dict(SPECIES_DEFAULTS, **s) for s in spec.get("species", ())]
    if not species:
        raise VegetationError("VG5: an ecosystem has at least one species")
    e = ecosystem_seed(doc, spec)
    years = years_for(t, float(_get(spec, "yearsPerSecond", ECOSYSTEM_DEFAULTS)),
                      int(_get(spec, "maxYears", ECOSYSTEM_DEFAULTS)))
    nx, ny = tg.grid(doc)
    dx = float(doc.get("metersPerCell", 1.0))
    width, height = nx * dx, ny * dx
    mask = _mask_grid(doc, sc, layers)
    points = scatter_on(doc, sc, layers)["points"]
    plants = []
    for k, p in enumerate(points):
        sp = min(len(species) - 1, int(rs.S(e, SPECIES_PURPOSE, 0, k) * len(species))) if len(species) > 1 else 0
        plants.append({"id": k, "position": p["position"], "species": sp, "radius": SEEDLING_RADIUS, "age": 0,
                       "parent": None})
    next_id = len(points)
    largest = max(float(s["maxRadius"]) for s in species)

    def admitted(pos, draw_step, draw_index):
        if not (0.0 <= pos[0] < width and 0.0 <= pos[1] < height):
            return False
        if mask is None:
            return True
        m = mask[min(ny - 1, int(pos[1] // dx))][min(nx - 1, int(pos[0] // dx))]
        return m > 0.0 and rs.S(e, OFFSPRING_PURPOSE, draw_step, draw_index) < m

    for year in range(1, years + 1):
        grown = []
        for p in plants:
            sp = species[p["species"]]
            r = p["radius"] + float(sp["growth"]) * (1.0 - p["radius"] / float(sp["maxRadius"]))
            age = p["age"] + 1
            if age >= int(sp["maxAge"]):
                continue
            grown.append(dict(p, radius=r, age=age))
        grid = _PlantGrid(2.0 * max(largest, SEEDLING_RADIUS))
        for p in grown:
            grid.add(p)
        born = []
        for p in grown:
            sp = species[p["species"]]
            if p["age"] < int(sp["maturity"]):
                continue
            for k in range(int(sp["offspring"])):
                if next_id >= MAX_PLANTS:
                    raise VegetationError(f"VG5: more than {MAX_PLANTS} plants")
                base = p["id"] * 64 + k
                d = p["radius"] + float(sp["spread"]) * rs.S(e, OFFSPRING_PURPOSE, year, base)
                a = 2.0 * math.pi * rs.S(e, OFFSPRING_PURPOSE, year, base + 16)
                pos = (p["position"][0] + d * math.cos(a), p["position"][1] + d * math.sin(a))
                if not admitted(pos, year, base + 32) or grid.overlapping(pos, SEEDLING_RADIUS):
                    continue
                child = {"id": next_id, "position": pos, "species": p["species"], "radius": SEEDLING_RADIUS, "age": 0,
                         "parent": p["id"]}
                next_id += 1
                grid.add(child)
                born.append(child)
        candidates = sorted(grown + born, key=lambda q: (-q["radius"], q["age"] * -1, q["id"]))
        kept = _PlantGrid(2.0 * max(largest, SEEDLING_RADIUS))
        survivors = []
        for q in candidates:
            if kept.overlapping(q["position"], q["radius"]):
                continue
            kept.add(q)
            survivors.append(q)
        plants = sorted(survivors, key=lambda q: q["id"])
    return {"plants": plants, "years": years, "digest": digest(plants)}


def ecosystem(doc, t):
    built = terrain().build(doc)
    return ecosystem_on(doc, t, built["layers"])


# ------------------------------------------------------------------------------------------- instances and the run


def _tree_specs(doc):
    return {t["id"]: t for t in doc.get("trees", ())}


def _tree_params(spec, grown, scale):
    return {"height": grown["height"] * scale, "dragArea": float(_get(spec, "dragArea", SWAY_DEFAULTS)) * scale * scale,
            "stiffness": float(_get(spec, "stiffness", SWAY_DEFAULTS))}


def instances_on(doc, t, layers, grown=None):
    """The instances at time t: the ecosystem's plants when the terrain has one (scale radius / maxRadius, yaw
    360 S(e, 3, 0, id)), else every scatter's points; each with its prototype, its height on the surface and its
    sway under the scatter's wind read at its own position at t."""
    rs = streams()
    tg = terrain()
    specs = _tree_specs(doc)
    grown = grown if grown is not None else {k: tree(doc, s) for k, s in specs.items()}
    ground = tg.surface(layers)
    nx, ny = tg.grid(doc)
    dx = float(doc.get("metersPerCell", 1.0))
    out = []
    years = None
    eco = doc.get("ecosystem")
    if eco:
        state = ecosystem_on(doc, t, layers)
        years = state["years"]
        sc = next(s for s in doc["scatters"] if s.get("id") == eco.get("scatter"))
        species = [dict(SPECIES_DEFAULTS, **s) for s in eco["species"]]
        e = ecosystem_seed(doc, eco)
        rows = [(p["position"], species[p["species"]]["prototype"], p["radius"] / float(species[p["species"]]["maxRadius"]),
                 360.0 * rs.S(e, YAW_PURPOSE, 0, p["id"]), sc, p) for p in state["plants"]]
    else:
        rows = []
        for sc in doc.get("scatters", ()):
            for p in scatter_on(doc, sc, layers)["points"]:
                rows.append((p["position"], sc.get("prototype"), p["scale"], p["yaw"], sc, None))
    for position, proto, scale, yaw, sc, plant in rows:
        i, j = min(nx - 1, int(position[0] // dx)), min(ny - 1, int(position[1] // dx))
        wind_id = sc.get("wind")
        w = wind_at_point(doc, wind_id, position[0], position[1], t) if wind_id else (0.0, 0.0)
        params = _tree_params(specs[proto], grown[proto], scale) if proto in specs else {"height": 0.0}
        inst = {"position": position, "height": ground[j][i], "yaw": yaw, "scale": scale, "prototype": proto,
                "sway": sway(params, w)}
        if plant is not None:
            inst["radius"] = plant["radius"]
            inst["age"] = plant["age"]
        out.append(inst)
    return {"instances": out, "years": years, "digest": digest(out)}


def instances(doc, t):
    built = terrain().build(doc)
    return instances_on(doc, t, built["layers"])


def run(doc, t):
    codes = validate_document(doc)
    if codes:
        raise VegetationError("invalid document: " + ", ".join(codes))
    built = terrain().build(doc)
    grown = {k: tree(doc, s) for k, s in _tree_specs(doc).items()}
    inst = instances_on(doc, t, built["layers"], grown)
    return {"shape": built["shape"], "trees": grown, "instances": inst["instances"], "years": inst["years"],
            "digest": digest({"trees": {k: g["digest"] for k, g in grown.items()}, "instances": inst["instances"]})}


# ------------------------------------------------------------------------------------------- documents


def example_document():
    """The terrain draft's example with a lowland mask, three prototypes (an L-system birch, a parametric oak, a
    colonised maple), a grove scattered on the lowland in a 4 m/s wind and an ecosystem of oaks and birches."""
    doc = terrain().example_document()
    doc["masks"].append({"id": "lowland", "kind": "altitude", "max": 1500.0, "feather": 200.0})
    doc["physics"] = {"winds": [{"id": "w1", "speed": 4.0, "direction": 30.0, "turbulence": 0.2, "seed": 3}]}
    doc["trees"] = [
        {"id": "birch", "method": "lsystem", "axiom": "F", "rules": [{"from": "F", "to": "FF-[-F+F+F]+[+F-F-F]"}],
         "iterations": 3, "angle": 22.5, "length": 1.5, "radius": 0.12, "radiusRatio": 0.7, "seed": 1,
         "dragArea": 12.0, "stiffness": 1.0e6},
        {"id": "oak", "method": "parametric", "levels": 2, "scale": 12.0, "baseSize": 0.3, "ratio": 0.02,
         "ratioPower": 1.2, "shape": "spherical", "length": [1.0, 0.45], "lengthVariation": [0.0, 0.1],
         "branches": [1, 8], "downAngle": [0.0, 55.0], "downAngleVariation": [0.0, 10.0], "rotate": [0.0, 140.0],
         "curve": [0.0, 20.0], "curveRes": [4, 3], "seed": 2, "dragArea": 30.0, "stiffness": 4.0e6},
        {"id": "maple", "method": "colonisation", "attractors": 80, "crownRadius": 3.0, "crownHeight": 4.0,
         "crownBase": 3.0, "influence": 2.0, "kill": 0.6, "segment": 0.3, "maxIterations": 300, "tipRadius": 0.01,
         "seed": 3},
    ]
    doc["scatters"] = [{"id": "grove", "radius": 40.0, "mask": "lowland", "prototype": "oak", "wind": "w1",
                        "scaleMin": 0.8, "scaleMax": 1.2, "seed": 5}]
    doc["ecosystem"] = {"scatter": "grove", "species": [
        {"prototype": "oak", "growth": 0.4, "maxRadius": 8.0, "maxAge": 120, "maturity": 15, "offspring": 1, "spread": 10.0},
        {"prototype": "birch", "growth": 0.6, "maxRadius": 4.0, "maxAge": 60, "maturity": 12, "offspring": 1, "spread": 12.0}],
        "yearsPerSecond": 1.0, "maxYears": 10000, "seed": 8}
    return doc


def bad_document():
    doc = example_document()
    doc["scatters"][0].update(radius=0.0, mask="nowhere", prototype="ghost")
    doc["trees"][0]["iterations"] = 13
    doc["ecosystem"]["species"][0]["growth"] = -1.0
    return doc


def _positive(v):
    return _number(v) and v > 0.0


def _nonneg(v):
    return _number(v) and v >= 0.0


def _check_tree(t):
    method = t.get("method", "lsystem")
    if method not in METHODS or not isinstance(t.get("id"), str):
        return False
    if not (_positive(_get(t, "stiffness", SWAY_DEFAULTS)) and _nonneg(_get(t, "dragArea", SWAY_DEFAULTS))):
        return False
    if method == "lsystem":
        it = _get(t, "iterations", LSYSTEM_DEFAULTS)
        ok = _integer(it) and 0 <= it <= MAX_ITERATIONS and _integer(_get(t, "maxSymbols", LSYSTEM_DEFAULTS))
        ok = ok and _get(t, "maxSymbols", LSYSTEM_DEFAULTS) >= 1 and _number(_get(t, "angle", LSYSTEM_DEFAULTS))
        ok = ok and _positive(_get(t, "length", LSYSTEM_DEFAULTS)) and _positive(_get(t, "lengthRatio", LSYSTEM_DEFAULTS))
        ok = ok and _positive(_get(t, "radius", LSYSTEM_DEFAULTS)) and _positive(_get(t, "radiusRatio", LSYSTEM_DEFAULTS))
        ok = ok and isinstance(_get(t, "axiom", LSYSTEM_DEFAULTS), str)
        for rule in t.get("rules", ()) or ():
            ok = ok and isinstance(rule.get("from"), str) and len(rule["from"]) == 1 and isinstance(rule.get("to"), str)
            ok = ok and _positive(rule.get("weight", 1.0))
        return ok
    if method == "colonisation":
        d_i, d_k = _get(t, "influence", COLONISATION_DEFAULTS), _get(t, "kill", COLONISATION_DEFAULTS)
        ok = _integer(_get(t, "attractors", COLONISATION_DEFAULTS)) and _get(t, "attractors", COLONISATION_DEFAULTS) >= 1
        ok = ok and _positive(_get(t, "crownRadius", COLONISATION_DEFAULTS)) and _positive(_get(t, "crownHeight", COLONISATION_DEFAULTS))
        ok = ok and _nonneg(_get(t, "crownBase", COLONISATION_DEFAULTS)) and _positive(d_k) and _positive(d_i) and d_k < d_i
        ok = ok and _positive(_get(t, "segment", COLONISATION_DEFAULTS)) and _positive(_get(t, "tipRadius", COLONISATION_DEFAULTS))
        mi = _get(t, "maxIterations", COLONISATION_DEFAULTS)
        return ok and _integer(mi) and mi >= 1
    levels = _get(t, "levels", PARAMETRIC_DEFAULTS)
    ok = _integer(levels) and 1 <= levels <= 4 and _get(t, "shape", PARAMETRIC_DEFAULTS) in SHAPES
    ok = ok and _positive(_get(t, "scale", PARAMETRIC_DEFAULTS)) and _positive(_get(t, "ratio", PARAMETRIC_DEFAULTS))
    ok = ok and _nonneg(_get(t, "ratioPower", PARAMETRIC_DEFAULTS))
    bs = _get(t, "baseSize", PARAMETRIC_DEFAULTS)
    ok = ok and _number(bs) and 0.0 <= bs < 1.0
    for key in ("length", "lengthVariation", "branches", "downAngle", "downAngleVariation", "rotate", "curve", "curveRes"):
        values = _get(t, key, PARAMETRIC_DEFAULTS)
        if isinstance(values, (int, float)):
            values = (values,)
        ok = ok and len(values) >= 1 and all(_number(v) for v in values)
        if key in ("branches", "curveRes"):
            ok = ok and all(_integer(v) and v >= (1 if key == "curveRes" else 0) for v in values)
        if key in ("length", "lengthVariation", "downAngleVariation"):
            ok = ok and all(v >= 0.0 for v in values)
    if ok:
        expected = 1
        for lv in range(levels):
            expected *= max(1, int(_level(t, "branches", lv)))
        ok = expected <= MAX_STEMS
    return ok


def validate_document(doc):
    """The draft's rules VG1 to VG5 and V17 over a terrain document, as sorted codes."""
    if not any(doc.get(k) for k in ("trees", "scatters", "ecosystem")):
        return []
    major, minor = (int(x) for x in str(doc.get("version", "1.8")).split(".")[:2])
    if (major, minor) < (1, 8):
        return ["V17"]
    codes = set()
    trees = {t.get("id") for t in doc.get("trees", ()) or ()}
    masks = {m.get("id") for m in doc.get("masks", ())}
    winds = {w.get("id") for w in doc.get("physics", {}).get("winds", ())}
    scatters = {s.get("id") for s in doc.get("scatters", ()) or ()}
    for s in doc.get("scatters", ()) or ():
        g = lambda key: _get(s, key, SCATTER_DEFAULTS)      # noqa: E731
        if not (isinstance(s.get("id"), str) and _positive(g("radius")) and _integer(g("attempts")) and g("attempts") >= 1
                and _integer(g("maxPoints")) and g("maxPoints") >= 1 and _number(g("density")) and 0.0 <= g("density") <= 1.0
                and _positive(g("scaleMin")) and _number(g("scaleMax")) and g("scaleMin") <= g("scaleMax")
                and isinstance(g("rotate"), bool)):
            codes.add("VG1")
        if (s.get("mask") is not None and s["mask"] not in masks) or (s.get("wind") is not None and s["wind"] not in winds):
            codes.add("VG2")
        if s.get("prototype") is not None and s["prototype"] not in trees:
            codes.add("VG3")
    for t in doc.get("trees", ()) or ():
        if not _check_tree(t):
            codes.add("VG4")
    eco = doc.get("ecosystem")
    if eco:
        ok = eco.get("scatter") in scatters and isinstance(eco.get("species"), list) and len(eco["species"]) >= 1
        ok = ok and _positive(_get(eco, "yearsPerSecond", ECOSYSTEM_DEFAULTS))
        my = _get(eco, "maxYears", ECOSYSTEM_DEFAULTS)
        ok = ok and _integer(my) and my >= 0
        for sp in eco.get("species", ()) or ():
            ok = ok and sp.get("prototype") in trees and _nonneg(_get(sp, "growth", SPECIES_DEFAULTS))
            ok = ok and _positive(_get(sp, "maxRadius", SPECIES_DEFAULTS)) and _integer(_get(sp, "maxAge", SPECIES_DEFAULTS))
            ok = ok and _get(sp, "maxAge", SPECIES_DEFAULTS) >= 1 and _integer(_get(sp, "offspring", SPECIES_DEFAULTS))
            ok = ok and _integer(_get(sp, "maturity", SPECIES_DEFAULTS)) and _get(sp, "maturity", SPECIES_DEFAULTS) >= 0
            ok = ok and _get(sp, "offspring", SPECIES_DEFAULTS) >= 0 and _nonneg(_get(sp, "spread", SPECIES_DEFAULTS))
        if not ok:
            codes.add("VG5")
    return sorted(codes)


# ------------------------------------------------------------------------------------------- numeric table

TABLE = (
    ("seedling radius, m", "SEEDLING_RADIUS", "0.25"),
    ("iteration bound", "MAX_ITERATIONS", "12"),
    ("scatter seed of the example", "scatter_seed(example_document(), example_document()['scatters'][0])", "763477113"),
    ("flat field: points", "FLAT['count']", "103"),
    ("flat field: closest pair, m", "CLOSEST", "8.019057355754535"),
    ("flat field: farthest probe, m", "FARTHEST", "8.339224374594922"),
    ("flat field: first point", "FLAT['points'][0]['position']", "(15.160139936102212, 90.58569701195451)"),
    ("candidate 7 around the origin", "candidate((0.0, 0.0), 1.0, FLAT['seed'], 7)", "(0.6551200282681434, 1.8654653382226145)"),
    ("flat field: PointInstancer lines", "len(to_point_instancer(FLAT['points'], 'f').splitlines())", "14"),
    ("flat field: glTF buffer bytes", "to_gltf_instancing(FLAT['points'], 'f')['buffers'][0]['byteLength']", "4120"),
    ("instance transform", "instance_transform({'position': (3.0, 4.0), 'height': 5.0, 'yaw': 90.0, 'scale': 2.0})", "((3.0, 5.0, 4.0), (0.0, 0.7071067811865475, 0.0, 0.7071067811865476), (2.0, 2.0, 2.0))"),
    ("Fibonacci algae, 7 iterations", "len(lsystem_string({'axiom': 'A', 'rules': [{'from': 'A', 'to': 'AB'}, {'from': 'B', 'to': 'A'}]}, 7))", "34"),
    ("Koch curve, 4 iterations: segments", "len(turtle(lsystem_string(KOCH, 4), KOCH))", "625"),
    ("Koch curve, 4 iterations: far end", "turtle(lsystem_string(KOCH, 4), KOCH)[-1]['end']", "(-1.1102230246251563e-16, 0.0, 81.0)"),
    ("birch: segments", "BIRCH['symbols'], len(BIRCH['segments'])", "(1388, 512)"),
    ("birch: height, m", "BIRCH['height']", "40.27567454780148"),
    ("maple: nodes, killed, iterations", "(len(MAPLE['nodes']), MAPLE['killed'], MAPLE['iterations'])", "(136, 78, 29)"),
    ("maple: trunk radius, m", "MAPLE['radii'][0]", "0.04795831523312719"),
    ("maple: height, m", "MAPLE['height']", "6.353610701705003"),
    ("oak: stems, segments", "(len(OAK['stems']), len(OAK['segments']))", "(9, 28)"),
    ("oak: height, m", "OAK['height']", "13.122793231748883"),
    ("conical shape ratio at 0.25", "shape_ratio('conical', 0.25)", "0.4"),
    ("flame shape ratio at 0.9", "shape_ratio('flame', 0.9)", "0.33333333333333326"),
    ("sway of a 10 m tree in 6 m/s", "sway({'height': 10.0, 'dragArea': 20.0, 'stiffness': 2.0e6}, (6.0, 0.0))", "{'angle': 0.21056104179450139, 'direction': (1.0, 0.0), 'deflection': 0.03675}"),
    ("years for 3 s at 2 a year, bound 7", "years_for(3.0, 2.0, 7)", "6"),
    ("stand: plants at 0, 5, 10 and 20 years", "[len(ecosystem(STAND, t)['plants']) for t in (0.0, 5.0, 10.0, 20.0)]", "[714, 223, 86, 45]"),
    ("stand: mean radius at 20 years, m", "sum(p['radius'] for p in ecosystem(STAND, 20.0)['plants']) / len(ecosystem(STAND, 20.0)['plants'])", "4.9909873131122415"),
    ("run: instances at 30 years", "len(RUN['instances'])", "2141"),
    ("run: oaks and birches", "(sum(1 for i in RUN['instances'] if i['prototype'] == 'oak'), sum(1 for i in RUN['instances'] if i['prototype'] == 'birch'))", "(644, 1497)"),
    ("run: largest sway, degrees", "max(i['sway']['angle'] for i in RUN['instances'])", "2.070556265324576"),
    ("run: digest", "RUN['digest']", "'552353d45f002fb8166553aeaea4681358f0050062aed8e0a86e90c5c6e2d133'"),
    ("bad document", "validate_document(bad_document())", "['VG1', 'VG2', 'VG3', 'VG4', 'VG5']"),
)

_SCOPE = None


def scope():
    global _SCOPE
    if _SCOPE is not None:
        return _SCOPE
    s = dict(globals())
    s["math"] = math
    n, dx = 20, 5.0
    flat = {"version": "1.8", "project": 7, "id": "field", "x": 0.0, "y": 0.0, "width": n * dx, "height": n * dx,
            "cells": n, "metersPerCell": dx, "seed": 11, "display": "none",
            "layers": [{"kind": "bedrock", "value": 0.0}], "masks": [], "materials": [], "assets": {},
            "trees": [], "scatters": [{"id": "s1", "radius": 8.0, "seed": 3}], "ecosystem": None}
    s["FLAT"] = scatter(flat, flat["scatters"][0])
    pts = [p["position"] for p in s["FLAT"]["points"]]
    s["CLOSEST"] = min(math.dist(pts[a], pts[b]) for a in range(len(pts)) for b in range(a + 1, len(pts)))
    probes = [(x, y) for x in range(4, 100, 4) for y in range(4, 100, 4)]
    s["FARTHEST"] = max(min(math.dist(q, p) for p in pts) for q in probes)
    s["KOCH"] = {"axiom": "F", "rules": [{"from": "F", "to": "F+F-F-F+F"}], "angle": 90.0}
    ex = example_document()
    s["BIRCH"] = tree(ex, ex["trees"][0])
    s["OAK"] = tree(ex, ex["trees"][1])
    s["MAPLE"] = tree(ex, ex["trees"][2])
    stand = dict(flat, scatters=[{"id": "s1", "radius": 3.0, "seed": 3, "prototype": "oak"}],
                 trees=[{"id": "oak", "method": "lsystem", "axiom": "F", "rules": [], "length": 8.0, "radius": 0.3}],
                 ecosystem={"scatter": "s1", "species": [{"prototype": "oak", "growth": 0.5, "maxRadius": 6.0,
                                                          "maxAge": 500, "offspring": 0, "spread": 3.0}],
                            "yearsPerSecond": 1.0, "maxYears": 1000})
    s["STAND"] = stand
    s["RUN"] = run(ex, 30.0)
    _SCOPE = s
    return s


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
