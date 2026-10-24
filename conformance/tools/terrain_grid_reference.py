#!/usr/bin/env python3
"""Reference for the draft SREP "Add the terrain grid" (F2 of SREP 12).

A `terrain` element is a regular grid of layers over a rectangle: `cells` along the longer side, the other
side by the aspect, `metersPerCell` the physical cell size. Layers are named kinds with units (bedrock, loose,
lava, ice and snow by type in metres and solid; water and sediment in metres; flow in m^2/s with two channels;
temperature in kelvin; fuel in kg/m^2; burn, hardness and wetness in [0, 1]); the ground surface is the sum of
the solid layers and the water surface adds water. A layer is a flat `value`, a `generate` child (fbm, ridged
or billow noise on the D24 lattice of the random-streams draft, with lacunarity, gain, domain warp and
terraces, scaled by amplitude and offset) or an image or elevation asset (`from` with an encoding). Masks
measure the ground surface (slope in degrees, altitude in metres, curvature as the Laplacian, flow as the
log10 of the D8 accumulation) and ramp over min and max with a feather; materials splat over the altitude
ramp through them; the picture is hill-shaded as the baseline's erosion is, with the physical gradient; the
3D surface is SREP 70's heightfield over the physical extent. The same document generates byte-identical
layers, and the digest of the layers pins them.

Every function is pure Python on lists and tuples; the module reuses the random-streams reference for the
draws. `main()` prints the numeric table of the draft.
"""
import hashlib
import importlib.util
import json
import math
import os

PURPOSE = "terrain"
MIN_CELLS = 4
MAX_CELLS = 4096
MAX_OCTAVES = 16
MAX_TERRACES = 64
NOISE_KINDS = ("fbm", "ridged", "billow")
MASK_KINDS = ("slope", "altitude", "curvature", "flow")
DISPLAYS = ("picture", "surface", "none")
ENCODINGS = ("gray", "gray16", "terrarium", "mapbox")
DIGEST_DECIMALS = 3
OCTAVE_STRIDE = 1024   # a base channel b draws its octave k from channel b * OCTAVE_STRIDE + k (the W of F1)
LAYER_STRIDE = 4096    # layer l has the base channels l * LAYER_STRIDE (noise), + 1 and + 2 (warp x and y)
SOLID_LAYERS = ("bedrock", "loose", "lava", "ice", "snow")
LAYER_KINDS = {
    "bedrock": {"unit": "m", "solid": True, "channels": 1, "range": None},
    "loose": {"unit": "m", "solid": True, "channels": 1, "range": None},
    "lava": {"unit": "m", "solid": True, "channels": 1, "range": None},
    "ice": {"unit": "m", "solid": True, "channels": 1, "range": None},
    "snow": {"unit": "m", "solid": True, "channels": 1, "range": None, "typed": True},
    "water": {"unit": "m", "solid": False, "channels": 1, "range": None},
    "sediment": {"unit": "m", "solid": False, "channels": 1, "range": None},
    "flow": {"unit": "m2/s", "solid": False, "channels": 2, "range": None},
    "temperature": {"unit": "K", "solid": False, "channels": 1, "range": None},
    "fuel": {"unit": "kg/m2", "solid": False, "channels": 1, "range": None},
    "burn": {"unit": "1", "solid": False, "channels": 1, "range": (0.0, 1.0)},
    "hardness": {"unit": "1", "solid": False, "channels": 1, "range": (0.0, 1.0)},
    "wetness": {"unit": "1", "solid": False, "channels": 1, "range": (0.0, 1.0)},
}
GENERATE_DEFAULTS = {"noise": "fbm", "octaves": 6, "frequency": 3.0, "lacunarity": 2.0, "gain": 0.5, "warp": 0.0,
                     "warpFrequency": 1.0, "terraces": 0, "terraceSharpness": 1.0, "amplitude": 1.0, "offset": 0.0}
D8 = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, math.sqrt(2.0)), (1, -1, math.sqrt(2.0)),
      (-1, 1, math.sqrt(2.0)), (-1, -1, math.sqrt(2.0)))


class TerrainError(ValueError):
    """A terrain-grid rule or input is violated."""


_STREAMS = None


def streams():
    """The random-streams reference module (F1), loaded by path."""
    global _STREAMS
    if _STREAMS is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "random_streams_reference.py")
        spec = importlib.util.spec_from_file_location("random_streams_reference", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _STREAMS = mod
    return _STREAMS


# ------------------------------------------------------------------------------------ grids and layers


def flat(nx, ny, value):
    return [[float(value)] * nx for _ in range(ny)]


def plane(nx, ny, gx, gy, dx=1.0):
    return [[gx * i * dx + gy * j * dx for i in range(nx)] for j in range(ny)]


def bowl(n):
    c = (n - 1) / 2.0
    return [[(i - c) ** 2 + (j - c) ** 2 for i in range(n)] for j in range(n)]


def pit(n):
    c = (n - 1) // 2
    return [[float(max(abs(i - c), abs(j - c))) for i in range(n)] for j in range(n)]


def extent(rows):
    values = [v for row in rows for v in row]
    return (min(values), max(values))


def grid(spec):
    """(nx, ny): `cells` along the longer side, the other by the aspect, at least 4 each (the erosion rule)."""
    cells = spec.get("cells", 256)
    if not isinstance(cells, int) or isinstance(cells, bool) or cells < MIN_CELLS or cells > MAX_CELLS:
        raise TerrainError(f"TG2: cells is an integer from {MIN_CELLS} to {MAX_CELLS}")
    w, h = float(spec["width"]), float(spec["height"])
    if not w > 0.0 or not h > 0.0:
        raise TerrainError("TG2: width and height are positive")
    step = max(w, h) / cells
    return (max(int(round(w / step)), MIN_CELLS), max(int(round(h / step)), MIN_CELLS))


def _kind(key):
    return key.split(":", 1)[0]


def surface(layers):
    """The ground surface: the sum of the solid layers (snow layers of every type included)."""
    solid = [v for k, v in layers.items() if _kind(k) in SOLID_LAYERS]
    if not solid:
        raise TerrainError("the terrain has no solid layer")
    ny, nx = len(solid[0]), len(solid[0][0])
    return [[sum(layer[j][i] for layer in solid) for i in range(nx)] for j in range(ny)]


def water_surface(layers):
    ground = surface(layers)
    water = layers.get("water")
    if water is None:
        return ground
    return [[ground[j][i] + water[j][i] for i in range(len(ground[0]))] for j in range(len(ground))]


# ------------------------------------------------------------------------------------ noise


def fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def lattice_value(e, channel, i, j):
    """2 U(e, c, pack(i, j, 0)) - 1: the lattice value of the random-streams draft at the 2D index (i, j)."""
    rs = streams()
    return 2.0 * rs.U(e, channel, rs.pack(i, j, 0)) - 1.0


def value2(e, channel, x, y):
    """Value noise on the plane: the lattice values blended by the quintic fade; in [-1, 1]."""
    fx, fy = math.floor(x), math.floor(y)
    i, j = int(fx), int(fy)
    u, v = fade(x - fx), fade(y - fy)
    a = lattice_value(e, channel, i, j)
    b = lattice_value(e, channel, i + 1, j)
    c = lattice_value(e, channel, i, j + 1)
    d = lattice_value(e, channel, i + 1, j + 1)
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v


def octave_channel(layer_index, octave):
    return layer_index * LAYER_STRIDE * OCTAVE_STRIDE + octave


def warp_channel(layer_index, axis):
    return (layer_index * LAYER_STRIDE + 1 + axis) * OCTAVE_STRIDE


def _generate(gen):
    g = dict(GENERATE_DEFAULTS)
    g.update(gen)
    return g


def noise(kind, e, layer_index, u, v, gen):
    """The octave sum of kind fbm, ridged or billow at (u, v) in fractions of the longer side: octave k weighs
    gain^k and samples the value noise at frequency * lacunarity^k; the sum is divided by the sum of the
    weights, so the result lies in [-1, 1]."""
    if kind not in NOISE_KINDS:
        raise TerrainError(f"TG3: noise is one of {', '.join(NOISE_KINDS)}, not {kind}")
    g = _generate(gen)
    octaves = min(max(int(g["octaves"]), 1), MAX_OCTAVES)
    total = norm = 0.0
    weight, f = 1.0, float(g["frequency"])
    for k in range(octaves):
        n = value2(e, octave_channel(layer_index, k), u * f, v * f)
        if kind == "ridged":
            n = 2.0 * (1.0 - abs(n)) ** 2 - 1.0
        elif kind == "billow":
            n = 2.0 * abs(n) - 1.0
        total += weight * n
        norm += weight
        weight *= float(g["gain"])
        f *= float(g["lacunarity"])
    return total / norm


def terrace(h, levels, sharpness):
    """Quantises h in [0, 1] into `levels` steps; within a step the fraction f becomes f^s / (f^s + (1 - f)^s),
    the identity at sharpness 1 and a hard step as it grows; 0 levels leave h."""
    if not sharpness >= 1.0:
        raise TerrainError("TG3: terraceSharpness is at least 1")
    if levels <= 0:
        return h
    t = h * levels
    k = math.floor(t)
    f = t - k
    if f > 0.0:
        a, b = f ** sharpness, (1.0 - f) ** sharpness
        f = a / (a + b) if a + b > 0.0 else f
    return (k + f) / levels


def warped(e, layer_index, x, y, gen, nx, ny):
    """The sample point of cell (x, y) after the domain warp: `warp` cells along the value noise of each axis at
    `warpFrequency` features across the longer side."""
    g = _generate(gen)
    w = float(g["warp"])
    if w == 0.0:
        return (float(x), float(y))
    long = float(max(nx, ny))
    u, v = x / long * float(g["warpFrequency"]), y / long * float(g["warpFrequency"])
    return (x + w * value2(e, warp_channel(layer_index, 0), u, v), y + w * value2(e, warp_channel(layer_index, 1), u, v))


def validate_generate(gen):
    g = _generate(gen)
    if g["noise"] not in NOISE_KINDS:
        raise TerrainError(f"TG3: noise is one of {', '.join(NOISE_KINDS)}")
    if not isinstance(g["octaves"], int) or not 1 <= g["octaves"] <= MAX_OCTAVES:
        raise TerrainError(f"TG3: octaves is an integer from 1 to {MAX_OCTAVES}")
    if not g["frequency"] > 0.0 or not g["warpFrequency"] > 0.0:
        raise TerrainError("TG3: frequency and warpFrequency are positive")
    if not g["lacunarity"] >= 1.0:
        raise TerrainError("TG3: lacunarity is at least 1")
    if not 0.0 < g["gain"] <= 1.0:
        raise TerrainError("TG3: gain lies in (0, 1]")
    if not g["warp"] >= 0.0:
        raise TerrainError("TG3: warp is not negative")
    if not isinstance(g["terraces"], int) or not 0 <= g["terraces"] <= MAX_TERRACES:
        raise TerrainError(f"TG3: terraces is an integer from 0 to {MAX_TERRACES}")
    if not g["terraceSharpness"] >= 1.0:
        raise TerrainError("TG3: terraceSharpness is at least 1")
    return g


def element_seed(spec, project):
    return streams().E(project, spec["id"], spec.get("seed"), PURPOSE)


def generate_layer(spec, layer_index, gen, project):
    """The layer's grid: a flat `value`, or offset + amplitude * (terraced 0..1 noise) at every cell, the cell
    warped first; the seed is E(project, id, seed, "terrain")."""
    nx, ny = grid(spec)
    if "value" in gen:
        return flat(nx, ny, gen["value"])
    g = validate_generate(gen)
    e = element_seed(spec, project)
    long = float(max(nx, ny))
    out = []
    for j in range(ny):
        row = []
        for i in range(nx):
            x, y = warped(e, layer_index, i, j, g, nx, ny)
            n = noise(g["noise"], e, layer_index, x / long, y / long, g)
            h = terrace(0.5 + 0.5 * n, g["terraces"], g["terraceSharpness"])
            row.append(float(g["offset"]) + float(g["amplitude"]) * h)
        out.append(row)
    return out


def decode(encoding, pixel):
    """A pixel's value: gray in [0, 1] as is, gray16 over 65535, Terrarium and Mapbox elevations in metres."""
    if encoding == "gray":
        return float(pixel[0])
    if encoding == "gray16":
        return pixel[0] / 65535.0
    if encoding == "terrarium":
        r, g, b = pixel[:3]
        return (r * 256.0 + g + b / 256.0) - 32768.0
    if encoding == "mapbox":
        r, g, b = pixel[:3]
        return -10000.0 + (r * 65536.0 + g * 256.0 + b) * 0.1
    raise TerrainError(f"TG3: encoding is one of {', '.join(ENCODINGS)}, not {encoding}")


def from_image(pixels, nx, ny, encoding, amplitude=1.0, offset=0.0):
    """The layer resampled from an image by nearest pixel (the erosion rule): offset + amplitude * decoded."""
    h, w = len(pixels), len(pixels[0])
    out = []
    for j in range(ny):
        y = min(j * h // ny, h - 1)
        row = []
        for i in range(nx):
            x = min(i * w // nx, w - 1)
            px = pixels[y][x]
            if not isinstance(px, (tuple, list)):
                px = (px,)
            row.append(offset + amplitude * decode(encoding, px))
        out.append(row)
    return out


# ------------------------------------------------------------------------------------ derived quantities


def gradient(h, dx):
    """(gx, gy) by central differences, one-sided at the edges, per metre."""
    ny, nx = len(h), len(h[0])
    gx = [[0.0] * nx for _ in range(ny)]
    gy = [[0.0] * nx for _ in range(ny)]
    for j in range(ny):
        for i in range(nx):
            i0, i1 = max(i - 1, 0), min(i + 1, nx - 1)
            j0, j1 = max(j - 1, 0), min(j + 1, ny - 1)
            gx[j][i] = (h[j][i1] - h[j][i0]) / ((i1 - i0) * dx) if i1 > i0 else 0.0
            gy[j][i] = (h[j1][i] - h[j0][i]) / ((j1 - j0) * dx) if j1 > j0 else 0.0
    return gx, gy


def slope_degrees(h, dx):
    gx, gy = gradient(h, dx)
    return [[math.degrees(math.atan(math.hypot(gx[j][i], gy[j][i]))) for i in range(len(h[0]))] for j in range(len(h))]


def curvature(h, dx):
    """The Laplacian (d2h/dx2 + d2h/dy2) by second differences, in 1/m; an edge cell takes the second
    difference of the nearest interior cell along that axis (0 when the side has fewer than three cells)."""
    ny, nx = len(h), len(h[0])

    def second(values, k):
        n = len(values)
        if n < 3:
            return 0.0
        k = min(max(k, 1), n - 2)
        return values[k + 1] + values[k - 1] - 2.0 * values[k]

    out = []
    for j in range(ny):
        row = []
        for i in range(nx):
            row.append((second(h[j], i) + second([h[b][i] for b in range(ny)], j)) / (dx * dx))
        out.append(row)
    return out


def flow_accumulation(h):
    """D8: every cell drains to its steepest strictly lower neighbour (diagonals over sqrt 2); the accumulation
    counts the cell and everything upstream of it."""
    ny, nx = len(h), len(h[0])
    receiver = {}
    for j in range(ny):
        for i in range(nx):
            best, steepest = None, 0.0
            for di, dj, dist in D8:
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny:
                    s = (h[j][i] - h[b][a]) / dist
                    if s > steepest:
                        best, steepest = (a, b), s
            receiver[(i, j)] = best
    acc = [[1] * nx for _ in range(ny)]
    for (i, j) in sorted(receiver, key=lambda c: -h[c[1]][c[0]]):
        r = receiver[(i, j)]
        if r is not None:
            acc[r[1]][r[0]] += acc[j][i]
    return acc


def mask_values(q, m):
    """[0, 1] per cell: 1 inside [min, max], falling to 0 over `feather` outside it (hard without), inverted
    when asked."""
    lo = float(m.get("min", -math.inf))
    hi = float(m.get("max", math.inf))
    feather = float(m.get("feather", 0.0))
    if lo > hi:
        raise TerrainError("TG4: min is at most max")
    if feather < 0.0:
        raise TerrainError("TG4: feather is not negative")
    out = []
    for row in q:
        vals = []
        for v in row:
            if feather > 0.0:
                a = (v - (lo - feather)) / feather if lo > -math.inf else math.inf
                b = ((hi + feather) - v) / feather if hi < math.inf else math.inf
                x = max(0.0, min(1.0, min(a, b)))
            else:
                x = 1.0 if lo <= v <= hi else 0.0
            vals.append(1.0 - x if m.get("invert", False) else x)
        out.append(vals)
    return out


def quantity(kind, spec, layers):
    ground = surface(layers)
    dx = float(spec.get("metersPerCell", 1.0))
    if kind == "slope":
        return slope_degrees(ground, dx)
    if kind == "altitude":
        return ground
    if kind == "curvature":
        return curvature(ground, dx)
    if kind == "flow":
        return [[math.log10(a) for a in row] for row in flow_accumulation(ground)]
    raise TerrainError(f"TG4: mask kind is one of {', '.join(MASK_KINDS)}, not {kind}")


def mask(spec, layers, m):
    return mask_values(quantity(m["kind"], spec, layers), m)


# ------------------------------------------------------------------------------------ display


def sun_vector(azimuth, elevation):
    """erosion.rs: (sin az cos el, -cos az cos el, sin el); azimuth 0 is up the image, clockwise."""
    az, el = math.radians(azimuth), math.radians(elevation)
    return (math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))


def hillshade(h, dx, azimuth, elevation, relief):
    """0.25 + 0.75 max(0, n . sun) with n the unit normal of the relief-scaled physical gradient."""
    sun = sun_vector(azimuth, elevation)
    gx, gy = gradient(h, dx)
    out = []
    for j in range(len(h)):
        row = []
        for i in range(len(h[0])):
            n = (-gx[j][i] * relief, -gy[j][i] * relief, 1.0)
            l = math.sqrt(n[0] * n[0] + n[1] * n[1] + 1.0)
            lambert = max(0.0, (n[0] * sun[0] + n[1] * sun[1] + n[2] * sun[2]) / l)
            row.append(0.25 + 0.75 * lambert)
        out.append(row)
    return out


def _colour(c):
    return tuple(float(v) for v in c)


def picture(spec, layers):
    """The 2D picture: the altitude ramp colorLow to colorHigh, the materials over it through their masks in
    order, the RGB shaded by the hillshade; premultiplied straight colours with the ramp's alpha."""
    ground = surface(layers)
    lo, hi = extent(ground)
    span = max(hi - lo, 1e-9)
    low = _colour(spec.get("colorLow", (0.231, 0.290, 0.184, 1.0)))
    high = _colour(spec.get("colorHigh", (0.910, 0.886, 0.816, 1.0)))
    masks = {m["id"]: mask(spec, layers, m) for m in spec.get("masks", ())}
    materials = []
    for mat in spec.get("materials", ()):
        if mat.get("mask") not in masks:
            raise TerrainError(f"TG5: material mask {mat.get('mask')!r} is not a mask of the terrain")
        materials.append((_colour(mat["color"]), masks[mat["mask"]]))
    shade = hillshade(ground, float(spec.get("metersPerCell", 1.0)), float(spec.get("sunAzimuth", 315.0)),
                      float(spec.get("sunElevation", 45.0)), float(spec.get("relief", 1.0)))
    out = []
    for j in range(len(ground)):
        row = []
        for i in range(len(ground[0])):
            v = (ground[j][i] - lo) / span
            c = [low[k] + (high[k] - low[k]) * v for k in range(4)]
            for colour, mvals in materials:
                w = mvals[j][i]
                c = [c[k] * (1.0 - w) + colour[k] * w for k in range(4)]
            s = shade[j][i]
            row.append((c[0] * s, c[1] * s, c[2] * s, c[3]))
        out.append(row)
    return out


def mesh_counts(spec):
    nx, ny = grid(spec)
    return (nx * ny, 2 * (nx - 1) * (ny - 1))


def mesh(spec, layers):
    """SREP 70's heightfield over the grid: vertices (x, -h, z) row by row over the physical extent (cells times
    metersPerCell, centred) and two triangles per cell."""
    nx, ny = grid(spec)
    ground = surface(layers)
    dx = float(spec.get("metersPerCell", 1.0))
    w, d = nx * dx, ny * dx
    verts = []
    for j in range(ny):
        for i in range(nx):
            x = -w / 2.0 + w * i / (nx - 1)
            z = -d / 2.0 + d * j / (ny - 1)
            verts.append((x, -ground[j][i], z))
    tris = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, e = j * nx + i, j * nx + i + 1, (j + 1) * nx + i, (j + 1) * nx + i + 1
            tris.append((a, c, b))
            tris.append((b, c, e))
    return verts, tris


# ------------------------------------------------------------------------------------ the element


def example_generate():
    return {"noise": "fbm", "octaves": 6, "frequency": 3.0, "lacunarity": 2.0, "gain": 0.5}


def example_document():
    """A 160 x 120 terrain at 16 cells of 50 m: fbm bedrock with terraces, ridged loose material warped, dry."""
    return {
        "version": "1.8", "project": 7, "id": "ground", "x": 0.0, "y": 0.0, "width": 160.0, "height": 120.0,
        "cells": 16, "metersPerCell": 50.0, "seed": 11, "display": "picture",
        "sunAzimuth": 315.0, "sunElevation": 45.0, "relief": 1.0,
        "colorLow": (0.231, 0.290, 0.184, 1.0), "colorHigh": (0.910, 0.886, 0.816, 1.0),
        "layers": [
            {"kind": "bedrock", "generate": {"noise": "fbm", "octaves": 6, "frequency": 3.0, "amplitude": 2000.0,
                                             "offset": 200.0, "terraces": 5, "terraceSharpness": 3.0}},
            {"kind": "loose", "generate": {"noise": "ridged", "octaves": 4, "frequency": 5.0, "amplitude": 40.0,
                                           "warp": 2.0, "warpFrequency": 2.0}},
            {"kind": "water", "value": 0.0},
        ],
        "masks": [
            {"id": "steep", "kind": "slope", "min": 20.0, "feather": 5.0},
            {"id": "high", "kind": "altitude", "min": 1500.0, "feather": 200.0},
            {"id": "valley", "kind": "flow", "min": 1.0},
        ],
        "materials": [
            {"color": (0.45, 0.42, 0.40, 1.0), "mask": "steep"},
            {"color": (0.95, 0.95, 0.97, 1.0), "mask": "high"},
            {"color": (0.30, 0.36, 0.22, 1.0), "mask": "valley"},
        ],
        "assets": {},
    }


def _layer_key(layer):
    kind = layer["kind"]
    if LAYER_KINDS.get(kind, {}).get("typed"):
        return f"{kind}:{layer.get('type', '')}"
    return kind


def digest_of(layers):
    """sha256 of the layers as JSON with sorted keys and values rounded to DIGEST_DECIMALS."""
    rounded = {k: [[round(v, DIGEST_DECIMALS) for v in row] for row in rows] for k, rows in layers.items()}
    text = json.dumps(rounded, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(doc):
    """Generates every layer, derives the masks and the digest."""
    validate_terrain(doc)
    nx, ny = grid(doc)
    layers = {}
    for index, layer in enumerate(doc["layers"]):
        if "generate" in layer:
            rows = generate_layer(doc, index, layer["generate"], doc.get("project", 0))
        elif "from" in layer:
            asset = doc["assets"][layer["from"]]
            rows = from_image(asset["pixels"], nx, ny, layer.get("encoding", "gray"), layer.get("amplitude", 1.0),
                              layer.get("offset", 0.0))
        else:
            rows = flat(nx, ny, layer.get("value", 0.0))
        layers[_layer_key(layer)] = rows
    masks = {m["id"]: mask(doc, layers, m) for m in doc.get("masks", ())}
    return {"shape": (nx, ny), "layers": layers, "masks": masks, "digest": digest_of(layers)}


# ------------------------------------------------------------------------------------ validation


def _version(doc):
    try:
        major, minor = (int(p) for p in str(doc.get("version", "1.8")).split(".")[:2])
    except ValueError as e:
        raise TerrainError(f"the version is major.minor: {e}") from e
    return (major, minor)


def validate_terrain(doc):
    """Rules TG1-TG6 and V17 on a dict of the element; raises TerrainError naming the rule."""
    if _version(doc) < (1, 8):
        raise TerrainError("V17: terrain requires version 1.8")
    grid(doc)
    if not float(doc.get("metersPerCell", 1.0)) > 0.0:
        raise TerrainError("TG2: metersPerCell is positive")
    seen = set()
    for layer in doc.get("layers", ()):
        kind = layer.get("kind")
        if kind not in LAYER_KINDS:
            raise TerrainError(f"TG1: layer kind {kind!r} is not one of {', '.join(LAYER_KINDS)}")
        key = _layer_key(layer)
        if key in seen:
            raise TerrainError(f"TG1: layer {key} appears twice")
        seen.add(key)
        sources = [k for k in ("value", "generate", "from") if k in layer]
        if len(sources) > 1:
            raise TerrainError(f"TG3: layer {key} has {', '.join(sources)}; one source only")
        if "generate" in layer:
            validate_generate(layer["generate"])
        if "from" in layer:
            if layer.get("encoding", "gray") not in ENCODINGS:
                raise TerrainError(f"TG3: encoding is one of {', '.join(ENCODINGS)}")
            if layer["from"] not in doc.get("assets", {}):
                raise TerrainError(f"TG3: layer {key} reads asset {layer['from']!r}, which does not exist")
        rng = LAYER_KINDS[kind]["range"]
        if rng is not None and "value" in layer and not rng[0] <= float(layer["value"]) <= rng[1]:
            raise TerrainError(f"TG1: layer {key} lies in [{rng[0]}, {rng[1]}]")
    ids = set()
    for m in doc.get("masks", ()):
        if m.get("kind") not in MASK_KINDS:
            raise TerrainError(f"TG4: mask kind is one of {', '.join(MASK_KINDS)}")
        if m.get("id") in ids:
            raise TerrainError(f"TG4: mask id {m.get('id')!r} appears twice")
        ids.add(m.get("id"))
        mask_values([[0.0]], m)
    for mat in doc.get("materials", ()):
        if mat.get("mask") not in ids:
            raise TerrainError(f"TG5: material mask {mat.get('mask')!r} is not a mask of the terrain")
    if doc.get("display", "picture") not in DISPLAYS:
        raise TerrainError(f"TG6: display is one of {', '.join(DISPLAYS)}")
    for obj in doc.get("objects", ()):
        if obj.get("primitive") == "terrain" and obj.get("terrain") != doc.get("id"):
            raise TerrainError("TG6: object3D primitive=\"terrain\" names a terrain element in @terrain")
    return True


# ------------------------------------------------------------------------------------ the table


def example_seed():
    return element_seed(example_document(), 7)


TABLE = (
    ("the grid of 300 x 200 at 256 cells", "grid({'width': 300.0, 'height': 200.0, 'cells': 256})", "(256, 171)"),
    ("the element seed of the example", "example_seed()", "1572054040"),
    ("the lattice value at (2, 5)", "lattice_value(example_seed(), 3, 2, 5)", "0.965131"),
    ("value noise at a lattice point is the lattice value", "value2(example_seed(), 3, 2.0, 5.0) == lattice_value(example_seed(), 3, 2, 5)", "True"),
    ("value noise midway between two lattice points", "value2(example_seed(), 3, 2.5, 5.0)", "0.472962"),
    ("fbm at (0.37, 0.53)", "noise('fbm', example_seed(), 0, 0.37, 0.53, example_generate())", "0.000443216"),
    ("ridged at (0.37, 0.53)", "noise('ridged', example_seed(), 0, 0.37, 0.53, example_generate())", "-0.287994"),
    ("billow at (0.37, 0.53)", "noise('billow', example_seed(), 0, 0.37, 0.53, example_generate())", "-0.152268"),
    ("terrace of 0.3 in four steps at sharpness 8", "terrace(0.3, 4, 8.0)", "0.250004"),
    ("terrace at sharpness 1 is the identity", "terrace(0.3, 4, 1.0)", "0.3"),
    ("the warped sample point of cell (10, 6)", "warped(example_seed(), 0, 10.0, 6.0, dict(example_generate(), warp=5.0, warpFrequency=1.0), 64, 64)", "(5.93264, 3.34906)"),
    ("the bedrock range of the example (m)", "extent(build(example_document())['layers']['bedrock'])", "(600.007, 1846.15)"),
    ("the digest of the example's layers", "build(example_document())['digest'][:16]", "'b1544be8285adfeb'"),
    ("Terrarium decoding", "decode('terrarium', (128, 1, 128))", "1.5"),
    ("Mapbox decoding", "decode('mapbox', (1, 134, 160))", "0"),
    ("the surface of two solid layers under water", "surface({'bedrock': flat(2, 2, 10.0), 'loose': flat(2, 2, 0.5), 'water': flat(2, 2, 2.0)})[0][0]", "10.5"),
    ("the water surface", "water_surface({'bedrock': flat(2, 2, 10.0), 'loose': flat(2, 2, 0.5), 'water': flat(2, 2, 2.0)})[0][0]", "12.5"),
    ("the slope of a plane rising 1 m per metre", "slope_degrees(plane(6, 5, 1.0, 0.0, 2.0), 2.0)[2][2]", "45"),
    ("the curvature of a bowl", "curvature(bowl(7), 1.0)[3][3]", "4"),
    ("D8 accumulation at the foot of a slope", "flow_accumulation(plane(3, 5, 0.0, -1.0))[4][1]", "5"),
    ("a pit collects every cell", "flow_accumulation(pit(5))[2][2]", "25"),
    ("a mask ramp with a feather of 10", "mask_values([[0.0, 5.0, 10.0, 15.0, 20.0]], {'min': 5.0, 'max': 15.0, 'feather': 10.0})[0]", "(0.5, 1, 1, 1, 0.5)"),
    ("flat ground under a 45 degree sun", "hillshade(flat(4, 4, 3.0), 1.0, 315.0, 45.0, 1.0)[1][1]", "0.78033"),
    ("the sun vector at azimuth 315, elevation 45", "sun_vector(315.0, 45.0)", "(-0.5, -0.5, 0.707107)"),
    ("a picture pixel of the example", "picture(example_document(), build(example_document())['layers'])[6][8]", "(0.2375, 0.2375, 0.2425, 1)"),
    ("the mesh counts of the example", "mesh_counts(example_document())", "(192, 330)"),
    ("the first vertex of the example's mesh", "mesh(example_document(), build(example_document())['layers'])[0][0]", "(-400, -1002.92, -300)"),
    ("the largest grid", "MAX_CELLS", "4096"),
    ("the most octaves", "MAX_OCTAVES", "16"),
)


def scope():
    s = dict(globals())
    s["math"] = math
    return s


def _same(a, b, rel=5e-4, abs_tol=5e-4):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _fmt(v):
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and abs(v) < 1e-12:
        v = 0.0
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, (tuple, list)):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    return repr(v)


def main():
    s = scope()
    for name, expr, _expected in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
