#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add a style layer" (srep/srep-0000-style-layer.md), CL1 of
SREP 12: the four looks and their resolution down the node tree, toon bands that fall at their declared
thresholds, the specular and rim bands, flat shading, silhouette and crease edges of meshes, the outline
edge mask and its width, the sketch wobble (D24 gradient noise along the path's normals, with an endpoint
taper and whole-turn wavelengths on closed paths), overdraw passes and the boil step, marker widths and
hatching. Standard library only. `main()` prints the SREP's numeric table.

The D24 hash functions are copied from random_streams_reference.py so that this module stands alone.
"""
import math
import zlib

KINDS = ("flat", "sketch", "toon", "photoreal")
THREE_D = ("object3D", "model", "particles", "volume")
MAX_BANDS = 16
MAX_PASSES = 16
MAX_POINTS = 1_000_000
EPS = 1e-9
HATCH_TURN = 60.0

# --- D24 (random streams) ----------------------------------------------------------------------------------

MASK64 = (1 << 64) - 1
PHI = 0x9E3779B97F4A7C15


def u64(x):
    return x & MASK64


def mix64(z):
    z = u64(z)
    z = u64((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9)
    z = u64((z ^ (z >> 27)) * 0x94D049BB133111EB)
    return z ^ (z >> 31)


def splitmix64(x):
    return mix64(u64(x) + PHI)


def H(seed, channel, index):
    """The lattice hash H(s, c, i) = splitmix64(s xor splitmix64(c xor splitmix64(i)))."""
    return splitmix64(u64(seed) ^ splitmix64(u64(channel) ^ splitmix64(u64(index))))


def U(seed, channel, index):
    return (H(seed, channel, index) >> 11) * (1.0 / (1 << 53))


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def N(seed, channel, x):
    """D24's gradient noise: gradients 2 U - 1 at the integers, quintic fade; 0 at every integer."""
    fl = math.floor(x)
    f = x - fl
    i = int(fl)

    def g(k):
        return U(seed, channel, k & MASK64) * 2.0 - 1.0
    a = g(i) * f
    b = g((i + 1) & MASK64) * (f - 1.0)
    return 2.0 * (a + (b - a) * _fade(f))


def E(project, element_id, seed, purpose):
    """The element seed: CRC-32 of "project:id:seed:purpose" (D24 section 4)."""
    s = "" if seed is None else str(u64(seed))
    return zlib.crc32(f"{u64(project)}:{element_id}:{s}:{purpose}".encode("utf-8")) & 0xFFFFFFFF


def path_seed(project, element_id, look_seed):
    """The seed of a path's sketch streams: E(project, id, the look's seed, "sketch")."""
    return E(project, element_id, look_seed, "sketch")


# --- looks ------------------------------------------------------------------------------------------------------

def resolve_look(chain):
    """The look of the last node of `chain`, a list of (element name, @look kind or None) from the composition
    down: the nearest ancestor with a look wins; without one, 3D nodes are photoreal and vector nodes flat."""
    if not chain:
        raise ValueError("an empty node chain has no look")
    for name, kind in reversed(chain):
        if kind is not None:
            if kind not in KINDS:
                raise ValueError(f"unknown look {kind!r}")
            return kind
    return "photoreal" if chain[-1][0] in THREE_D else "flat"


# --- vectors ----------------------------------------------------------------------------------------------------

def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _unit(v):
    n = math.sqrt(_dot(v, v))
    if not n > 0.0 or not math.isfinite(n):
        raise ValueError("zero or non-finite vector")
    return tuple(x / n for x in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


# --- toon -------------------------------------------------------------------------------------------------------

def lambert(n, l):
    """max(n . l, 0) of the unit vectors."""
    return max(_dot(_unit(n), _unit(l)), 0.0)


def validate_bands(thresholds, levels):
    """Thresholds strictly increasing in (0, 1], at most MAX_BANDS; levels one more than thresholds,
    nondecreasing in [0, 1]."""
    if len(thresholds) > MAX_BANDS:
        raise ValueError(f"at most {MAX_BANDS} thresholds")
    last = 0.0
    for t in thresholds:
        if not (last < t <= 1.0):
            raise ValueError("thresholds must increase strictly within (0, 1]")
        last = t
    if len(levels) != len(thresholds) + 1:
        raise ValueError("one level more than thresholds")
    prev = 0.0
    for v in levels:
        if not (prev <= v <= 1.0):
            raise ValueError("levels must be nondecreasing within [0, 1]")
        prev = v


def band_index(x, thresholds):
    """The band of x: the number of thresholds at or below x (a value at a threshold is in the upper band)."""
    return sum(1 for t in thresholds if x >= t)


def band_angle(threshold):
    """The angle, in degrees, between the normal and the light at which n . l equals the threshold."""
    if not 0.0 < threshold <= 1.0:
        raise ValueError("a threshold is in (0, 1]")
    return math.degrees(math.acos(threshold))


def toon_diffuse(nl, thresholds, levels):
    validate_bands(thresholds, levels)
    return levels[band_index(nl, thresholds)]


def toon_shade(albedo, light, nl, thresholds, levels, ambient):
    """albedo * (ambient + level * light), per channel, clamped to [0, 1]."""
    if not 0.0 <= ambient <= 1.0:
        raise ValueError("ambient is in [0, 1]")
    level = toon_diffuse(nl, thresholds, levels)
    return tuple(min(max(a * (ambient + level * c), 0.0), 1.0) for a, c in zip(albedo, light))


def toon_specular(n, l, v, shininess, threshold):
    """1 where (n . h)^shininess >= threshold on the lit side, h the half vector; 0 elsewhere."""
    if not shininess > 0.0:
        raise ValueError("shininess is positive")
    if not 0.0 < threshold <= 1.0:
        raise ValueError("a threshold is in (0, 1]")
    n, l, v = _unit(n), _unit(l), _unit(v)
    if _dot(n, l) <= 0.0:
        return 0.0
    h = _unit(tuple(a + b for a, b in zip(l, v)))
    nh = max(_dot(n, h), 0.0)
    return 1.0 if nh ** shininess >= threshold else 0.0


def rim(n, v, threshold):
    """1 where 1 - max(n . v, 0) >= threshold; 0 elsewhere."""
    if not 0.0 < threshold <= 1.0:
        raise ValueError("a threshold is in (0, 1]")
    return 1.0 if 1.0 - max(_dot(_unit(n), _unit(v)), 0.0) >= threshold else 0.0


def flat_shade(albedo):
    """The flat look: the albedo, no lights."""
    return tuple(albedo)


# --- edges ------------------------------------------------------------------------------------------------------

def face_normal(vertices, face):
    """The unit normal of a counter-clockwise triangle; a degenerate triangle is an error."""
    a, b, c = (vertices[i] for i in face)
    n = _cross(_sub(b, a), _sub(c, a))
    return _unit(n)


def _edges_of(vertices, faces):
    """edge (sorted vertex pair) -> list of face normals; checks the indices."""
    edges = {}
    for face in faces:
        if len(face) != 3 or any(not 0 <= i < len(vertices) for i in face):
            raise ValueError("faces are triangles of vertex indices")
        n = face_normal(vertices, face)
        for k in range(3):
            e = tuple(sorted((face[k], face[(k + 1) % 3])))
            edges.setdefault(e, []).append(n)
    return edges


def silhouette_edges(vertices, faces, view):
    """Boundary edges, and edges shared by a front-facing (n . view < 0) and a non-front-facing face."""
    view = _unit(view)
    out = set()
    for e, normals in _edges_of(vertices, faces).items():
        front = [_dot(n, view) < 0.0 for n in normals]
        if len(normals) == 1 or (any(front) and not all(front)):
            out.add(e)
    return out


def crease_edges(vertices, faces, angle):
    """Shared edges whose faces' normals differ by at least `angle` degrees."""
    if not 0.0 < angle <= 180.0:
        raise ValueError("the crease angle is in (0, 180]")
    out = set()
    for e, normals in _edges_of(vertices, faces).items():
        for i in range(len(normals)):
            for j in range(i + 1, len(normals)):
                c = max(-1.0, min(1.0, _dot(normals[i], normals[j])))
                if math.degrees(math.acos(c)) >= angle - EPS:
                    out.add(e)
    return out


def _shape(grid):
    rows = len(grid)
    if rows == 0:
        raise ValueError("an empty raster")
    cols = len(grid[0])
    if any(len(r) != cols for r in grid) or cols == 0:
        raise ValueError("a ragged raster")
    return rows, cols


def edge_mask(depth, normals, depth_threshold, normal_threshold):
    """1 at a pixel with a 4-neighbour farther by more than depth_threshold (the near side only) or whose
    normal differs by more than normal_threshold (1 - n . n'); 0 elsewhere."""
    if depth is None and normals is None:
        raise ValueError("an edge mask needs depth or normals")
    shape = None
    for grid in (depth, normals):
        if grid is not None:
            s = _shape(grid)
            if shape is not None and s != shape:
                raise ValueError("depth and normals differ in shape")
            shape = s
    rows, cols = shape
    out = []
    for i in range(rows):
        row = []
        for j in range(cols):
            hit = 0
            for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                a, b = i + di, j + dj
                if not (0 <= a < rows and 0 <= b < cols):
                    continue
                if depth is not None and depth[a][b] - depth[i][j] > depth_threshold:
                    hit = 1
                if normals is not None and 1.0 - _dot(normals[i][j], normals[a][b]) > normal_threshold:
                    hit = 1
            row.append(hit)
        out.append(tuple(row))
    return tuple(out)


def outline_radius(width):
    """The Chebyshev dilation radius of an outline `width` pixels wide: ceil((width - 1) / 2)."""
    if width < 0.0:
        raise ValueError("a width is not negative")
    return max(0, math.ceil((width - 1.0) / 2.0 - EPS))


def dilate(mask, width):
    """The mask dilated to the outline width; width 0 is no outline."""
    rows, cols = _shape(mask)
    if width < 0.0:
        raise ValueError("a width is not negative")
    if width == 0.0:
        return tuple((0,) * cols for _ in range(rows))
    r = outline_radius(width)
    out = []
    for i in range(rows):
        row = []
        for j in range(cols):
            hit = 0
            for a in range(max(0, i - r), min(rows, i + r + 1)):
                for b in range(max(0, j - r), min(cols, j + r + 1)):
                    if mask[a][b]:
                        hit = 1
            row.append(hit)
        out.append(tuple(row))
    return tuple(out)


# --- sketch -----------------------------------------------------------------------------------------------------

def _left_normal(d):
    return (-d[1], d[0])


def _segment_dir(a, b):
    d = (b[0] - a[0], b[1] - a[1])
    n = math.hypot(*d)
    return (d[0] / n, d[1] / n) if n > 0.0 else None


def vertex_normal(points, i, closed):
    """The left normal of the mean of the unit directions of the segments at point i (one segment at the
    ends of an open path)."""
    m = len(points)
    dirs = []
    if closed or i > 0:
        d = _segment_dir(points[(i - 1) % m], points[i])
        if d is not None:
            dirs.append(d)
    if closed or i < m - 1:
        d = _segment_dir(points[i], points[(i + 1) % m])
        if d is not None:
            dirs.append(d)
    if not dirs:
        raise ValueError("a point with no direction")
    s = (sum(d[0] for d in dirs), sum(d[1] for d in dirs))
    n = math.hypot(*s)
    if n == 0.0:
        s = dirs[0]
        n = 1.0
    return _left_normal((s[0] / n, s[1] / n))


def closed_wavelength(length, wavelength):
    """The wavelength of a closed path: the length over the nearest whole number of turns (at least one)."""
    return length / max(1, round(length / wavelength))


def _arc_lengths(points, closed):
    s = [0.0]
    for a, b in zip(points, points[1:]):
        s.append(s[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    length = s[-1]
    if closed:
        a, b = points[-1], points[0]
        length += math.hypot(b[0] - a[0], b[1] - a[1])
    return s, length


def wobble(points, amplitude, wavelength, seed, channel=0, closed=False):
    """Each point moved along its normal by amplitude * N(seed, channel, s / lambda) * taper, s its arc
    length from the first point. Open paths: taper = min(1, s / lambda, (L - s) / lambda), so the endpoints
    are fixed. Closed paths: lambda is closed_wavelength(L, lambda) and there is no taper."""
    points = tuple(tuple(float(c) for c in p) for p in points)
    if len(points) < (3 if closed else 2):
        raise ValueError("a path has at least two points, a closed one three")
    if len(points) > MAX_POINTS:
        raise ValueError(f"at most {MAX_POINTS} points")
    if amplitude < 0.0 or not wavelength > 0.0:
        raise ValueError("amplitude is not negative and the wavelength is positive")
    s, length = _arc_lengths(points, closed)
    if not length > 0.0:
        raise ValueError("a path of zero length")
    lam = closed_wavelength(length, wavelength) if closed else wavelength
    out = []
    for i, p in enumerate(points):
        taper = 1.0 if closed else min(1.0, s[i] / lam, (length - s[i]) / lam)
        d = amplitude * N(seed, channel, s[i] / lam) * taper
        if d == 0.0:
            out.append(p)
            continue
        n = vertex_normal(points, i, closed)
        out.append((p[0] + d * n[0], p[1] + d * n[1]))
    return tuple(out)


def boil_channel(pass_index, passes, time, boil):
    """The noise channel of a pass at a time: pass + passes * floor(time * boil + eps)."""
    if not 0 <= pass_index < passes:
        raise ValueError("the pass index is below the pass count")
    if time < 0.0 or boil < 0.0:
        raise ValueError("time and boil are not negative")
    return pass_index + passes * int(math.floor(time * boil + EPS))


def overdraw(points, passes, amplitude, wavelength, seed, closed=False, time=0.0, boil=0.0):
    """One wobbled copy per pass, pass k on channel boil_channel(k, passes, time, boil)."""
    if not 1 <= passes <= MAX_PASSES:
        raise ValueError(f"passes is 1 to {MAX_PASSES}")
    return tuple(wobble(points, amplitude, wavelength, seed, boil_channel(k, passes, time, boil), closed)
                 for k in range(passes))


def marker_width(s, length, width, taper):
    """width * (1 - taper + taper * sin(pi s / L)): the stroke's width at arc length s (sin(pi min(t, 1 - t))
    with t = s / L, which is the same value and exact at both ends)."""
    if not length > 0.0 or not 0.0 <= s <= length:
        raise ValueError("s lies on the path")
    if not 0.0 <= taper <= 1.0:
        raise ValueError("taper is in [0, 1]")
    t = s / length
    return width * (1.0 - taper + taper * math.sin(math.pi * min(t, 1.0 - t)))


def hatch_segments(box, spacing, angle, phase=0.0):
    """Lines at `angle` degrees spaced `spacing` apart (p . n = k spacing + phase, n the left normal of the
    direction), clipped to the box (x0, y0, x1, y1), in order of k."""
    x0, y0, x1, y1 = box
    if not (x1 > x0 and y1 > y0):
        raise ValueError("an empty box")
    if not spacing > 0.0:
        raise ValueError("spacing is positive")
    a = math.radians(angle)
    d = (math.cos(a), math.sin(a))
    n = _left_normal(d)
    corners = ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
    lo = min(_dot(c, n) for c in corners)
    hi = max(_dot(c, n) for c in corners)
    if (hi - lo) / spacing > MAX_POINTS:
        raise ValueError("too many hatch lines")
    k0 = math.ceil((lo - phase) / spacing - EPS)
    k1 = math.floor((hi - phase) / spacing + EPS)
    out = []
    for k in range(k0, k1 + 1):
        c = k * spacing + phase
        # the line p = c n + t d, clipped to the box by the slab method
        t_lo, t_hi = -math.inf, math.inf
        p0 = (c * n[0], c * n[1])
        for axis, (lo_a, hi_a) in enumerate(((x0, x1), (y0, y1))):
            if abs(d[axis]) < 1e-12:
                if not (lo_a - EPS <= p0[axis] <= hi_a + EPS):
                    t_lo, t_hi = 1.0, 0.0
                continue
            ta = (lo_a - p0[axis]) / d[axis]
            tb = (hi_a - p0[axis]) / d[axis]
            t_lo = max(t_lo, min(ta, tb))
            t_hi = min(t_hi, max(ta, tb))
        if t_hi - t_lo > EPS:
            out.append(((p0[0] + t_lo * d[0], p0[1] + t_lo * d[1]), (p0[0] + t_hi * d[0], p0[1] + t_hi * d[1])))
    return tuple(out)


def hatch_layers(band, bands):
    """The hatch layers of a surface in band `band` of `bands`: bands - 1 - band (the darkest band gets most)."""
    if not 0 <= band < bands:
        raise ValueError("the band is below the band count")
    return bands - 1 - band


def hatch_angle(angle, layer):
    """The angle of hatch layer `layer`: angle + 60 degrees per layer, modulo 180."""
    return (angle + HATCH_TURN * layer) % 180.0


def sketch_surface(nl, thresholds, levels, box, spacing, angle):
    """The sketch look of a surface: its toon band, the hatch layers of that band and their segments."""
    validate_bands(thresholds, levels)
    band = band_index(nl, thresholds)
    layers = hatch_layers(band, len(levels))
    segments = ()
    for layer in range(layers):
        segments += hatch_segments(box, spacing, hatch_angle(angle, layer))
    return {"band": band, "layers": layers, "segments": segments}


# --- table ------------------------------------------------------------------------------------------------------

def raises(f):
    try:
        f()
    except (ValueError, TypeError, IndexError, ZeroDivisionError, KeyError):
        return True
    return False


LINE = tuple((10.0 * i, 0.0) for i in range(11))
SQUARE = ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0))
FOLD_V = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))
FOLD_F = ((0, 1, 2), (1, 0, 3))

TABLE = [
    ("look of a group's object", 'resolve_look([("composition", None), ("group", "toon"), ("object3D", None)])', "'toon'"),
    ("look of a bare object", 'resolve_look([("composition", None), ("object3D", None)])', "'photoreal'"),
    ("look of a bare shape", 'resolve_look([("composition", None), ("shape", None)])', "'flat'"),
    ("lambert at 45 degrees", "round(lambert((0, 0, 1), (0, 1, 1)), 12)", "0.707106781187"),
    ("band at a threshold", "band_index(0.5, (0.2, 0.5, 0.8))", "2"),
    ("band just below a threshold", "band_index(0.5 - 1e-12, (0.2, 0.5, 0.8))", "1"),
    ("band of the unlit side", "band_index(0.0, (0.2, 0.5, 0.8))", "0"),
    ("band of the brightest", "band_index(1.0, (0.2, 0.5, 0.8))", "3"),
    ("band angle of 0.5", "round(band_angle(0.5), 9)", "60.0"),
    ("band on a sphere at 60 degrees", "band_index(math.cos(math.radians(60.0)), (0.5,))", "1"),
    ("toon diffuse level", "toon_diffuse(0.6, (0.2, 0.5, 0.8), (0.1, 0.4, 0.7, 1.0))", "0.7"),
    ("toon shade", "tuple(round(c, 12) for c in toon_shade((1.0, 0.5, 0.25), (1.0, 1.0, 1.0), 0.6, (0.2, 0.5, 0.8), (0.1, 0.4, 0.7, 1.0), 0.1))", "(0.8, 0.4, 0.2)"),
    ("toon shade clamps", "toon_shade((1.0, 1.0, 1.0), (2.0, 2.0, 2.0), 0.9, (0.2, 0.5, 0.8), (0.1, 0.4, 0.7, 1.0), 0.5)", "(1.0, 1.0, 1.0)"),
    ("specular band on", "toon_specular((0, 0, 1), (1, 0, 1), (0, 0, 1), 4.0, 0.5)", "1.0"),
    ("specular band off", "toon_specular((0, 0, 1), (1, 0, 1), (0, 0, 1), 32.0, 0.5)", "0.0"),
    ("rim band", "(rim((0, 0, 1), (0, 0, 1), 0.7), rim((0, 0, 1), (1, 0, 0), 0.7))", "(0.0, 1.0)"),
    ("flat shade", "flat_shade((0.2, 0.4, 0.6))", "(0.2, 0.4, 0.6)"),
    ("silhouette of the fold", "sorted(silhouette_edges(FOLD_V, FOLD_F, (0, 0, -1)))", "[(0, 1), (0, 2), (0, 3), (1, 2), (1, 3)]"),
    ("crease of the fold at 90", "sorted(crease_edges(FOLD_V, FOLD_F, 90.0))", "[(0, 1)]"),
    ("crease of the fold above 90", "sorted(crease_edges(FOLD_V, FOLD_F, 90.001))", "[]"),
    ("depth edge on the near side", "edge_mask(((1.0, 1.0, 5.0),), None, 0.5, 0.2)", "((0, 1, 0),)"),
    ("normal edge on both sides", "edge_mask(None, (((0, 0, 1), (0, 0, 1), (1, 0, 0)),), 0.5, 0.2)", "((0, 1, 1),)"),
    ("outline of width 3", "dilate(((0, 0, 1, 0, 0),), 3.0)", "((0, 1, 1, 1, 0),)"),
    ("outline radii", "tuple(outline_radius(w) for w in (1.0, 2.0, 3.0, 4.0))", "(0, 1, 1, 2)"),
    ("wobble on whole wavelengths", "wobble(LINE, 2.0, 10.0, 1) == LINE", "True"),
    ("wobble endpoints fixed", "(wobble(LINE, 2.0, 20.0, 1)[0], wobble(LINE, 2.0, 20.0, 1)[-1])", "((0.0, 0.0), (100.0, 0.0))"),
    ("wobble at half a wavelength", "round(wobble(LINE, 2.0, 20.0, 1)[1][1], 12)", "round(2.0 * N(1, 0, 0.5) * 0.5, 12)"),
    ("wobble at 1.5 wavelengths", "round(wobble(LINE, 2.0, 20.0, 1)[3][1], 12)", "round(2.0 * N(1, 0, 1.5), 12)"),
    ("closed wavelength", "closed_wavelength(400.0, 30.0)", "400.0 / 13"),
    ("closed square corner stays", "wobble(SQUARE, 2.0, 100.0, 7, closed=True)[1]", "(100.0, 0.0)"),
    ("vertex normal of a corner", "tuple(round(c, 12) for c in vertex_normal(SQUARE, 1, True))", "(-0.707106781187, 0.707106781187)"),
    ("overdraw passes", "len(overdraw(LINE, 3, 2.0, 20.0, 1))", "3"),
    ("boil channel", "boil_channel(1, 2, 0.5, 4.0)", "5"),
    ("boil channel under eps", "boil_channel(0, 3, 0.1 * 3, 10.0)", "9"),
    ("path seed", 'path_seed(0, "p1", 5) == E(0, "p1", 5, "sketch")', "True"),
    ("marker width at the ends", "(marker_width(0.0, 100.0, 4.0, 0.5), marker_width(100.0, 100.0, 4.0, 0.5))", "(2.0, 2.0)"),
    ("marker width at the middle", "round(marker_width(50.0, 100.0, 4.0, 0.5), 12)", "4.0"),
    ("hatch count", "len(hatch_segments((0, 0, 10, 10), 2.5, 0.0))", "5"),
    ("hatch diagonal", "tuple(tuple(round(c, 9) for c in p) for p in hatch_segments((0, 0, 10, 10), 2.5, 45.0)[2])", "((0.0, 0.0), (10.0, 10.0))"),
    ("hatch layers", "(hatch_layers(0, 4), hatch_layers(3, 4))", "(3, 0)"),
    ("hatch angle", "hatch_angle(30.0, 2)", "150.0"),
    ("sketch surface", "(sketch_surface(0.0, (0.2, 0.5, 0.8), (0.1, 0.4, 0.7, 1.0), (0, 0, 10, 10), 2.5, 0.0)['layers'], len(sketch_surface(0.0, (0.2, 0.5, 0.8), (0.1, 0.4, 0.7, 1.0), (0, 0, 10, 10), 2.5, 0.0)['segments']))", "(3, 15)"),
    ("unknown look", 'raises(lambda: resolve_look([("composition", "cartoon")]))', "True"),
    ("bands out of order", "raises(lambda: validate_bands((0.5, 0.2), (0.1, 0.4, 1.0)))", "True"),
    ("too many passes", "raises(lambda: overdraw(LINE, 17, 2.0, 20.0, 1))", "True"),
]


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["__builtins__"] = {"round": round, "tuple": tuple, "len": len, "sorted": sorted, "min": min, "max": max,
                         "abs": abs, "range": range, "list": list, "set": set, "dict": dict, "True": True,
                         "False": False, "None": None, "any": any, "all": all, "int": int, "float": float,
                         "ValueError": ValueError}
    return s


def main():
    s = scope()
    for name, expr, expected in TABLE:
        got = eval(expr, s)
        want = eval(expected, s)
        if got != want and not _same(got, want):
            raise SystemExit(f"{name}: {got!r} != {want!r}")
        print(f"| {name} | `{expr}` | `{expected}` |")


def _same(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    return a == b


if __name__ == "__main__":
    main()
