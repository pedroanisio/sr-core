#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add computed masks and depth" (srep/srep-0000-computed-masks.md,
LA2 of SREP 12).

Pure functions and plain dict documents, standard library only; the camera functions come from the computed-
tracking reference (LA1), loaded from the same directory:

* synthetic plates with a known matte (a textured or flat shape over a key or textured background) and a
  synthetic stereo pair with a known depth;
* mattes: the engine's chroma key and difference key, region growing from seeds with a linear colour model on
  the boundary (re-seeded at the previous frame's centroid), keyframed roto polygons rasterised with supersampled
  coverage; expansion and feather as maskType;
* depth: the exact depth of the plane z = 0 through a solved camera, and block-matching stereo with parabolic
  sub-pixel disparity;
* the frame cache: one 16-bit PGM per frame plus a manifest JSON pinned by sha256, the resolve step and the seek
  check.

Running the module prints the data rows of the draft's numeric table.
"""
import hashlib
import importlib.util
import json
import math
import os
import re

MASK_PROVIDER = "masks"
DEPTH_PROVIDER = "depth"
SEGMENT_METHODS = ("chroma", "difference", "region", "roto")
DEPTH_METHODS = ("plane", "stereo")
MIN_IOU = 0.95
MAX_FEATHER = 64
MAX_EXPANSION = 64
MAX_DISPARITY = 256
MIN_WINDOW = 3
MAX_WINDOW = 31
PGM_MAX = 65535
DEPTH_SCALE = 0.001            # metres per unit of the depth PGM
DEPTH_FAR = PGM_MAX * DEPTH_SCALE   # 65.535 m: no surface, or clipped
KEY_COLOUR = (0.0, 1.0, 0.0)
SUPERSAMPLE = 4
DEFAULT_FPS = 24
MAX_FRAMES = 1 << 17
CHROMA_NORM = 0.7
CB = (-0.1146, -0.3854, 0.5)
CR = (0.5, -0.4542, -0.0458)


class MaskError(ValueError):
    """A mask or depth document, or a numeric request, that the draft rejects."""


def _load_tracking():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "computed_tracking_reference.py")
    spec = importlib.util.spec_from_file_location("computed_tracking_reference", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ct = _load_tracking()
intrinsics = _ct.intrinsics
euler_to_rotation = _ct.euler_to_rotation
texture = _ct.texture
bilinear = _ct.bilinear
transpose = _ct.transpose
invert3 = _ct.invert3


# ------------------------------------------------------------------------------------ coverage and shapes


def _smoothstep(a, b, x):
    if b <= a:
        return 0.0 if x < a else 1.0
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def coverage(inside, width, height):
    """The fraction of each pixel's area (the pixel (i, j) spans i - 0.5 .. i + 0.5) where inside(x, y) holds, by
    SUPERSAMPLE x SUPERSAMPLE samples."""
    n = SUPERSAMPLE
    offs = [(-0.5 + (s + 0.5) / n) for s in range(n)]
    out = []
    for j in range(height):
        row = []
        for i in range(width):
            hits = 0
            for dy in offs:
                for dx in offs:
                    if inside(i + dx, j + dy):
                        hits += 1
            row.append(hits / (n * n))
        out.append(row)
    return out


def point_in_polygon(points, x, y):
    """Even-odd rule."""
    inside = False
    n = len(points)
    for k in range(n):
        (x0, y0), (x1, y1) = points[k], points[(k + 1) % n]
        if (y0 > y) != (y1 > y):
            xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xc:
                inside = not inside
    return inside


def rasterise(points, width, height):
    """The coverage of a polygon, three or more points in pixel coordinates."""
    if len(points) < 3:
        raise MaskError("a polygon has at least three points")
    return coverage(lambda x, y: point_in_polygon(points, x, y), width, height)


SHAPES = ("disc", "ellipse", "polygon")


def shape_matte(shape, frame, width, height):
    """The truth matte of a shape at a frame: the shape moves by (vx, vy) per frame."""
    kind = shape.get("kind")
    if kind not in SHAPES:
        raise MaskError(f"shape kind is one of {SHAPES}")
    dx = frame * shape.get("vx", 0.0)
    dy = frame * shape.get("vy", 0.0)
    if kind == "disc":
        cx, cy, r = shape["cx"] + dx, shape["cy"] + dy, shape["radius"]
        return coverage(lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r, width, height)
    if kind == "ellipse":
        cx, cy, rx, ry = shape["cx"] + dx, shape["cy"] + dy, shape["rx"], shape["ry"]
        return coverage(lambda x, y: ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0, width, height)
    pts = [(x + dx, y + dy) for x, y in shape["points"]]
    return rasterise(pts, width, height)


def clean_plate(width, height, seed=0):
    """A bluish textured background: channels (0.2 + 0.3 a, 0.3 + 0.4 b, 0.5 + 0.5 c) of three value noises."""
    a, b, c = (texture(width, height, 3 * seed + k) for k in range(3))
    return [[(0.2 + 0.3 * a[j][i], 0.3 + 0.4 * b[j][i], 0.5 + 0.5 * c[j][i]) for i in range(width)] for j in range(height)]


def foreground_plate(width, height, seed=0):
    """A reddish textured foreground, far from the key and from the clean plate: (0.6 + 0.4 a, 0.05 b, 0.1 c)."""
    a, b, c = (texture(width, height, 3 * seed + 100 + k) for k in range(3))
    return [[(0.6 + 0.4 * a[j][i], 0.05 * b[j][i], 0.1 * c[j][i]) for i in range(width)] for j in range(height)]


FLAT_FOREGROUND = (0.8, 0.2, 0.1)


def synthetic_matte_plate(width, height, shape, frames, seed=0, background="key", foreground="texture"):
    """Frames of a shape over a background and the truth mattes; the shape's pixels are the foreground, the
    background shows where the matte is 0, and edge pixels mix by the matte."""
    if shape.get("kind") not in SHAPES:
        raise MaskError(f"shape kind is one of {SHAPES}")
    if not 1 <= frames <= MAX_FRAMES:
        raise MaskError("frames must lie in [1, MAX_FRAMES]")
    if background not in ("key", "texture") or foreground not in ("texture", "flat"):
        raise MaskError("background is key or texture; foreground is texture or flat")
    bg = clean_plate(width, height, seed) if background == "texture" else None
    fg = foreground_plate(width, height, seed) if foreground == "texture" else None
    out, truth = [], []
    for k in range(frames):
        m = shape_matte(shape, k, width, height)
        img = []
        for j in range(height):
            row = []
            for i in range(width):
                b = bg[j][i] if bg is not None else KEY_COLOUR
                f = fg[j][i] if fg is not None else FLAT_FOREGROUND
                a = m[j][i]
                if a <= 0.0:
                    row.append(b)
                elif a >= 1.0:
                    row.append(f)
                else:
                    row.append(tuple(f[c] * a + b[c] * (1.0 - a) for c in range(3)))
            img.append(row)
        out.append(img)
        truth.append(m)
    return out, truth


def iou(a, b, threshold=0.5):
    """Intersection over union of the two mattes thresholded at 0.5; 1 when both are empty."""
    inter = union = 0
    for ra, rb in zip(a, b):
        for x, y in zip(ra, rb):
            p, q = x >= threshold, y >= threshold
            inter += p and q
            union += p or q
    return inter / union if union else 1.0


def soft_iou(a, b):
    num = sum(min(x, y) for ra, rb in zip(a, b) for x, y in zip(ra, rb))
    den = sum(max(x, y) for ra, rb in zip(a, b) for x, y in zip(ra, rb))
    return num / den if den else 1.0


def centroid(mask):
    """The coverage-weighted centre of a matte, or None when it is empty."""
    total = sx = sy = 0.0
    for j, row in enumerate(mask):
        for i, v in enumerate(row):
            total += v
            sx += v * i
            sy += v * j
    if total <= 0.0:
        return None
    return (sx / total, sy / total)


# ------------------------------------------------------------------------------------ keys


def chroma_distance(colour, key):
    """The engine's distance in the Cb-Cr plane over CHROMA_NORM (effects.wgsl, chroma key)."""
    cb = sum(CB[c] * (colour[c] - key[c]) for c in range(3))
    cr = sum(CR[c] * (colour[c] - key[c]) for c in range(3))
    return math.hypot(cb, cr) / CHROMA_NORM


def chroma_key_coverage(colour, key, tolerance, softness):
    """Coverage kept by the chroma key: smoothstep(tolerance, tolerance + softness, chroma distance)."""
    return _smoothstep(tolerance, tolerance + max(softness, 1e-4), chroma_distance(colour, key))


def difference_coverage(colour, clean, tolerance, softness):
    """Coverage kept by the difference key: smoothstep over the RGB distance to the clean plate."""
    d = math.sqrt(sum((colour[c] - clean[c]) ** 2 for c in range(3)))
    return _smoothstep(tolerance, tolerance + max(softness, 1e-4), d)


# ------------------------------------------------------------------------------------ morphology


def expand(mask, pixels):
    """Grayscale dilation (positive) or erosion (negative) by a square of half-side |pixels|, as maskType's
    expansion."""
    if abs(pixels) > MAX_EXPANSION:
        raise MaskError(f"expansion lies in [-{MAX_EXPANSION}, {MAX_EXPANSION}]")
    if pixels == 0:
        return [row[:] for row in mask]
    r = abs(pixels)
    pick = max if pixels > 0 else min
    pad = 0.0 if pixels > 0 else 1.0
    h, w = len(mask), len(mask[0])
    rows = []
    for row in mask:
        rows.append([pick(row[max(0, i - r):i + r + 1]) if 0 <= i < w else pad for i in range(w)])
    out = []
    for j in range(h):
        out.append([pick(rows[jj][i] for jj in range(max(0, j - r), min(h, j + r + 1))) for i in range(w)])
    return out


def feather(mask, pixels):
    """A box blur of radius pixels (a (2r + 1)^2 mean, zero outside the frame), as maskType's feather."""
    if not 0 <= pixels <= MAX_FEATHER:
        raise MaskError(f"feather lies in [0, {MAX_FEATHER}]")
    if pixels == 0:
        return [row[:] for row in mask]
    r = pixels
    n = 2 * r + 1
    h, w = len(mask), len(mask[0])
    rows = [[sum(row[max(0, i - r):i + r + 1]) / n for i in range(w)] for row in mask]
    return [[sum(rows[jj][i] for jj in range(max(0, j - r), min(h, j + r + 1))) / n for i in range(w)] for j in range(h)]


def _finish(mask, spec):
    out = expand(mask, int(spec.get("expansion", 0)))
    return feather(out, int(spec.get("feather", 0)))


# ------------------------------------------------------------------------------------ region growing


def _dist(a, b):
    return math.sqrt(sum((a[c] - b[c]) ** 2 for c in range(3)))


def region_grow(frame, seeds, tolerance):
    """The 4-connected set of pixels within tolerance (RGB distance) of the mean colour of the seeds."""
    h, w = len(frame), len(frame[0])
    starts = []
    for x, y in seeds:
        i, j = int(round(x)), int(round(y))
        if not (0 <= i < w and 0 <= j < h):
            raise MaskError(f"seed ({x}, {y}) lies outside the frame")
        starts.append((i, j))
    ref = tuple(sum(frame[j][i][c] for i, j in starts) / len(starts) for c in range(3))
    inside = [[False] * w for _ in range(h)]
    stack = list(starts)
    for i, j in starts:
        inside[j][i] = True
    while stack:
        i, j = stack.pop()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ii, jj = i + di, j + dj
            if 0 <= ii < w and 0 <= jj < h and not inside[jj][ii] and _dist(frame[jj][ii], ref) <= tolerance:
                inside[jj][ii] = True
                stack.append((ii, jj))
    return inside, ref


def region_matte(frame, seeds, tolerance):
    """Region growing, then a linear colour model on the boundary (Smith and Blinn 1996): a pixel next to the
    region with colour c, region colour f and the nearest outside colour b two pixels further out has coverage
    ((c - b) . (f - b)) / |f - b|^2, clamped to [0, 1]."""
    inside, ref = region_grow(frame, seeds, tolerance)
    h, w = len(frame), len(frame[0])
    out = [[1.0 if inside[j][i] else 0.0 for i in range(w)] for j in range(h)]
    for j in range(h):
        for i in range(w):
            if inside[j][i]:
                continue
            touching = [(di, dj) for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))
                        if 0 <= i + di < w and 0 <= j + dj < h and inside[j + dj][i + di]]
            if not touching:
                continue
            # the local background: two pixels away from the region, opposite to the touching side
            di, dj = touching[0]
            bi, bj = i - 2 * di, j - 2 * dj
            if not (0 <= bi < w and 0 <= bj < h) or inside[bj][bi]:
                bi, bj = i - di, j - dj
                if not (0 <= bi < w and 0 <= bj < h) or inside[bj][bi]:
                    continue
            b = frame[bj][bi]
            f = ref
            fb = [f[c] - b[c] for c in range(3)]
            den = sum(v * v for v in fb)
            if den <= 1e-12:
                continue
            c = frame[j][i]
            alpha = sum((c[k] - b[k]) * fb[k] for k in range(3)) / den
            out[j][i] = min(1.0, max(0.0, alpha))
    return out


# ------------------------------------------------------------------------------------ roto


def roto_polygon(keys, frame):
    """The polygon at a frame: linear between the two nearest keys, clamped outside them."""
    if not keys:
        raise MaskError("roto needs at least one key")
    n = len(keys[0]["points"])
    if n < 3 or any(len(k["points"]) != n for k in keys):
        raise MaskError("every roto key has the same three or more points")
    if any(keys[k]["frame"] >= keys[k + 1]["frame"] for k in range(len(keys) - 1)):
        raise MaskError("roto keys are in increasing frame order")
    if frame <= keys[0]["frame"]:
        return [tuple(map(float, p)) for p in keys[0]["points"]]
    if frame >= keys[-1]["frame"]:
        return [tuple(map(float, p)) for p in keys[-1]["points"]]
    k = 1
    while keys[k]["frame"] < frame:
        k += 1
    a, b = keys[k - 1], keys[k]
    t = (frame - a["frame"]) / (b["frame"] - a["frame"])
    return [(pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t) for pa, pb in zip(a["points"], b["points"])]


# ------------------------------------------------------------------------------------ segment


def segment(frames, spec, clean=None):
    """The matte of every frame for a segment child: chroma, difference, region or roto."""
    validate_segment(spec)
    if not frames:
        raise MaskError("no frames")
    method = spec["method"]
    h, w = len(frames[0]), len(frames[0][0])
    out = []
    if method == "chroma":
        key = tuple(spec.get("keyColor", KEY_COLOUR))
        tol, soft = spec.get("tolerance", 0.2), spec.get("softness", 0.1)
        for img in frames:
            out.append(_finish([[chroma_key_coverage(px, key, tol, soft) for px in row] for row in img], spec))
    elif method == "difference":
        if clean is None:
            raise MaskError("the difference key needs the clean plate")
        tol, soft = spec.get("tolerance", 0.2), spec.get("softness", 0.1)
        for img in frames:
            out.append(_finish([[difference_coverage(px, cpx, tol, soft) for px, cpx in zip(row, crow)]
                                for row, crow in zip(img, clean)], spec))
    elif method == "region":
        seeds = [tuple(map(float, s)) for s in spec["seeds"]]
        tol = spec.get("tolerance", 0.1)
        for img in frames:
            m = region_matte(img, seeds, tol)
            c = centroid(m)
            if c is None:
                raise MaskError("the region vanished")
            # the next frame starts from where the region is now, so the seeds follow the object
            shift = (c[0] - sum(s[0] for s in seeds) / len(seeds), c[1] - sum(s[1] for s in seeds) / len(seeds))
            seeds = [(s[0] + shift[0], s[1] + shift[1]) for s in seeds]
            out.append(_finish(m, spec))
    else:
        for k in range(len(frames)):
            out.append(_finish(rasterise(roto_polygon(spec["keys"], k), w, h), spec))
    return out


# ------------------------------------------------------------------------------------ depth


def plane_depth(K, R, t, width, height):
    """The camera-space depth of the plane z = 0 at every pixel, DEPTH_FAR where the ray misses it."""
    Kinv = invert3(K)
    Rt = transpose(R)
    origin = [-sum(Rt[i][k] * t[k] for k in range(3)) for i in range(3)]
    out = []
    for v in range(height):
        row = []
        for u in range(width):
            d = [Kinv[0][0] * u + Kinv[0][1] * v + Kinv[0][2], Kinv[1][1] * v + Kinv[1][2], 1.0]
            D = [sum(Rt[i][k] * d[k] for k in range(3)) for i in range(3)]
            if abs(D[2]) < 1e-9:
                row.append(DEPTH_FAR)
                continue
            s = -origin[2] / D[2]
            row.append(min(DEPTH_FAR, s) if s > 0.0 else DEPTH_FAR)
        out.append(row)
    return out


def synthetic_stereo(width, height, K, baseline, near, far, seed=0, radius=None):
    """A rectified pair: a frontal background plane at far and a frontal disc at near, both textured in world
    coordinates, seen by the left camera at the origin and the right camera at +baseline on x; and the left
    truth depth."""
    f, cx, cy = K[0][0], K[0][2], K[1][2]
    r = radius if radius is not None else 0.28 * height * near / f
    tex_bg = texture(width + 64, height + 8, seed)
    tex_fg = texture(width + 64, height + 8, seed + 7)

    def shade(X, Y, Z, tex):
        return bilinear(tex, cx + 32.0 + f * X / Z, cy + 4.0 + f * Y / Z)

    def cast(u, v, ox):
        xn, yn = (u - cx) / f, (v - cy) / f
        X, Y = ox + xn * near, yn * near
        if X * X + Y * Y <= r * r:
            return shade(X, Y, near, tex_fg), near
        return shade(ox + xn * far, yn * far, far, tex_bg), far

    left, right, truth = [], [], []
    for v in range(height):
        lrow, rrow, trow = [], [], []
        for u in range(width):
            value, z = cast(u, v, 0.0)
            lrow.append(value)
            trow.append(z)
            rrow.append(cast(u, v, baseline)[0])
        left.append(lrow)
        right.append(rrow)
        truth.append(trow)
    return left, right, truth


def stereo_disparity(left, right, window=7, max_disparity=64, consistency=True):
    """Block matching: for every left pixel the disparity d in [0, max_disparity] that minimises the sum of absolute
    differences between the left window and the right window d pixels to the left, refined by one-dimensional
    Lucas-Kanade; 0 (no match) where no window fits and, with the left-right consistency check, where the right
    image's own match disagrees by more than one pixel (occlusions)."""
    if window % 2 == 0 or not MIN_WINDOW <= window <= MAX_WINDOW:
        raise MaskError(f"window is odd and lies in [{MIN_WINDOW}, {MAX_WINDOW}]")
    if not 1 <= max_disparity <= MAX_DISPARITY:
        raise MaskError(f"maxDisparity lies in [1, {MAX_DISPARITY}]")
    if len(left) != len(right) or any(len(a) != len(b) for a, b in zip(left, right)):
        raise MaskError("the left and right frames have the same size")
    out = _match(left, right, window, max_disparity, +1)
    if consistency:
        back = _match(right, left, window, max_disparity, -1)
        h, w = len(left), len(left[0])
        for v in range(h):
            for u in range(w):
                d = out[v][u]
                if d <= 0.0:
                    continue
                x = int(round(u - d))
                if not 0 <= x < w or abs(back[v][x] - d) > 1.0:
                    out[v][u] = 0.0
    return out


def _match(a, b, window, max_disparity, sign):
    """The disparity of every pixel of a against b, b's window lying sign x d pixels to the left of a's."""
    h, w = len(a), len(a[0])
    r = window // 2
    out = [[0.0] * w for _ in range(h)]
    for v in range(r, h - r):
        for u in range(r, w - r):
            limit = min(max_disparity, u - r) if sign > 0 else min(max_disparity, w - 1 - r - u)
            costs = []
            for d in range(0, limit + 1):
                c = 0.0
                for j in range(-r, r + 1):
                    arow, brow = a[v + j], b[v + j]
                    for i in range(-r, r + 1):
                        c += abs(arow[u + i] - brow[u - sign * d + i])
                costs.append(c)
            if not costs:
                continue
            best = min(range(len(costs)), key=costs.__getitem__)
            d = float(best)
            if 0 < best < len(costs) - 1:
                d = _refine_disparity(a, b, u, v, r, d, sign)
            out[v][u] = d
    return out


def _row_sample(row, x):
    x0 = math.floor(x)
    fx = x - x0
    w = len(row)
    a = row[x0] if 0 <= x0 < w else 0.0
    b = row[x0 + 1] if 0 <= x0 + 1 < w else 0.0
    return a * (1.0 - fx) + b * fx


def _refine_disparity(left, right, u, v, r, d, sign=1, iterations=5):
    """One-dimensional Lucas-Kanade on the disparity: the window of the right row sampled bilinearly at u - d is
    moved by delta = sum(g e) / sum(g g) with g its horizontal gradient and e its difference to the left window."""
    for _ in range(iterations):
        gg = ge = 0.0
        for j in range(-r, r + 1):
            lrow, rrow = left[v + j], right[v + j]
            for i in range(-r, r + 1):
                x = u - sign * d + i
                e = _row_sample(rrow, x) - lrow[u + i]
                g = _row_sample(rrow, x + 0.5) - _row_sample(rrow, x - 0.5)
                gg += g * g
                ge += g * e
        if gg <= 1e-18:
            break
        delta = sign * ge / gg
        d += delta
        if abs(delta) < 1e-4:
            break
    return d


def disparity_to_depth(disparity, focal, baseline):
    """depth = focal x baseline / disparity, DEPTH_FAR where the disparity is 0."""
    return [[min(DEPTH_FAR, focal * baseline / d) if d > 1e-9 else DEPTH_FAR for d in row] for row in disparity]


def depth_error(depth, truth, margin=4, edge=10, quantile=0.95):
    """The quantile of the relative error over the matched pixels (depth below DEPTH_FAR) at least margin from the
    border and at least edge from a depth discontinuity of the truth (a 4-neighbour differing by more than 1 %);
    unmatched_fraction counts the pixels left out as unmatched."""
    h, w = len(truth), len(truth[0])
    steps = [[False] * w for _ in range(h)]
    for j in range(h):
        for i in range(w):
            for di, dj in ((1, 0), (0, 1)):
                ii, jj = i + di, j + dj
                if ii < w and jj < h and abs(truth[j][i] - truth[jj][ii]) > 0.01 * truth[j][i]:
                    steps[j][i] = steps[jj][ii] = True
    errors = []
    for j in range(margin, h - margin):
        for i in range(margin, w - margin):
            if any(steps[jj][ii] for jj in range(max(0, j - edge), min(h, j + edge + 1))
                   for ii in range(max(0, i - edge), min(w, i + edge + 1))):
                continue
            if depth[j][i] >= DEPTH_FAR:
                continue
            errors.append(abs(depth[j][i] - truth[j][i]) / truth[j][i])
    if not errors:
        raise MaskError("no pixel to measure")
    errors.sort()
    return errors[min(len(errors) - 1, int(quantile * len(errors)))]


def unmatched_fraction(depth, truth, margin=4, edge=10):
    """The fraction of the measured region (as depth_error) where the depth reads DEPTH_FAR."""
    h, w = len(truth), len(truth[0])
    steps = [[False] * w for _ in range(h)]
    for j in range(h):
        for i in range(w):
            for di, dj in ((1, 0), (0, 1)):
                ii, jj = i + di, j + dj
                if ii < w and jj < h and abs(truth[j][i] - truth[jj][ii]) > 0.01 * truth[j][i]:
                    steps[j][i] = steps[jj][ii] = True
    total = far = 0
    for j in range(margin, h - margin):
        for i in range(margin, w - margin):
            if any(steps[jj][ii] for jj in range(max(0, j - edge), min(h, j + edge + 1))
                   for ii in range(max(0, i - edge), min(w, i + edge + 1))):
                continue
            total += 1
            far += depth[j][i] >= DEPTH_FAR
    if not total:
        raise MaskError("no pixel to measure")
    return far / total


def estimate_depth(frames, spec, cameras=None, right=None):
    """The depth map of every frame for an estimate child: plane (through the camera track) or stereo."""
    validate_estimate(spec, loose=True)
    if not frames:
        raise MaskError("no frames")
    h, w = len(frames[0]), len(frames[0][0])
    K = intrinsics(w, h, spec["fov"])
    out = []
    if spec["method"] == "plane":
        if not cameras:
            raise MaskError("the plane method needs the camera track")
        for k in range(len(frames)):
            cam = cameras[min(k, len(cameras) - 1)]
            R = euler_to_rotation(cam["rx"], cam["ry"], cam["rz"])
            out.append(plane_depth(K, R, (cam["tx"], cam["ty"], cam["tz"]), w, h))
    else:
        if right is None:
            raise MaskError("the stereo method needs the right footage")
        if "baseline" not in spec:
            raise MaskError("the stereo method needs the baseline")
        if len(right) != len(frames):
            raise MaskError("the right footage has the frames of the left")
        for L, Rf in zip(frames, right):
            d = stereo_disparity(_gray(L), _gray(Rf), spec.get("window", 7), spec.get("maxDisparity", 64))
            out.append(disparity_to_depth(d, K[0][0], spec["baseline"]))
    return out


def _gray(img):
    if isinstance(img[0][0], (tuple, list)):
        return [[0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2] for p in row] for row in img]
    return img


# ------------------------------------------------------------------------------------ the cache


def pgm16(values, scale):
    """A binary 16-bit PGM (P5, maxval 65535, big-endian) of the values over the full-scale value scale: a unit is
    scale / 65535, values are rounded and clipped to the range."""
    h, w = len(values), len(values[0])
    head = f"P5\n{w} {h}\n{PGM_MAX}\n".encode("ascii")
    body = bytearray()
    for row in values:
        for v in row:
            unit = int(round(v / scale * PGM_MAX))
            unit = max(0, min(PGM_MAX, unit))
            body += unit.to_bytes(2, "big")
    return bytes(head + body)


_PGM = re.compile(rb"^P5\n(\d+) (\d+)\n65535\n")


def read_pgm16(data, scale):
    m = _PGM.match(data)
    if not m:
        raise MaskError("not a 16-bit PGM written by the resolve step")
    w, h = int(m.group(1)), int(m.group(2))
    body = data[m.end():]
    if len(body) != 2 * w * h:
        raise MaskError("the PGM body has the wrong length")
    out = []
    for j in range(h):
        row = []
        for i in range(w):
            k = 2 * (j * w + i)
            row.append(int.from_bytes(body[k:k + 2], "big") / PGM_MAX * scale)
        out.append(row)
    return out


_HASHES = re.compile(r"#+")
_PRINTF = re.compile(r"%0?(\d*)d")


def frame_path(pattern, number):
    """The file of a frame: printf padding (%04d) or # characters, as imageSequence/@src."""
    if _HASHES.search(pattern):
        return _HASHES.sub(lambda m: str(number).zfill(len(m.group(0))), pattern, count=1)
    m = _PRINTF.search(pattern)
    if not m:
        raise MaskError("the src pattern has no frame number")
    width = int(m.group(1) or "0")
    return pattern[:m.start()] + str(number).zfill(width) + pattern[m.end():]


def manifest_path(pattern):
    """The manifest next to the frames: the pattern's number field replaced by manifest, extension .json."""
    stem = frame_path(pattern, 0)
    marker = _HASHES.search(pattern) or _PRINTF.search(pattern)
    head = pattern[:marker.start()] + "manifest" + pattern[marker.end():]
    base = head.rsplit(".", 1)[0] if "." in head.rsplit("/", 1)[-1] else head
    return base + ".json" if stem else base


def frame_cache(pattern, first, maps, scale, fps, kind):
    """The frame files [(path, bytes)] and the manifest text: {"fps", "frames": [{"file", "sha256"}], "kind",
    "scale"} with sorted keys, no spaces, one line, newline terminated."""
    files = []
    for k, m in enumerate(maps):
        data = pgm16(m, scale)
        files.append((frame_path(pattern, first + k), data))
    manifest = {"fps": fps, "kind": kind, "scale": scale,
                "frames": [{"file": p, "sha256": hashlib.sha256(d).hexdigest()} for p, d in files]}
    return files, json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"


def cache_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_cache(text, digest):
    got = cache_digest(text)
    if got != digest:
        raise MaskError(f"cache digest {got} differs from the pinned {digest}")
    return True


def resolve(doc, frames, clean=None, cameras=None, right=None):
    """The resolve step: segment or estimate on the footage frames; returns (manifest, digest, files)."""
    validate_asset(doc)
    if "provider" not in doc:
        raise MaskError("an imported sequence has nothing to resolve")
    fps = doc.get("fps", DEFAULT_FPS)
    first = doc.get("first", 0)
    if doc["provider"] == MASK_PROVIDER:
        maps = segment(frames, doc["segment"], clean=clean)
        files, manifest = frame_cache(doc["src"], first, maps, 1.0, fps, "matte")
    else:
        maps = estimate_depth(frames, doc["estimate"], cameras=cameras, right=right)
        files, manifest = frame_cache(doc["src"], first, maps, DEPTH_FAR, fps, "depth")
    return manifest, cache_digest(manifest), files


def seek_test():
    """Resolving twice gives the same bytes, and frame k of the cache is frame k of the segmentation."""
    frames, _ = synthetic_matte_plate(32, 24, {"kind": "disc", "cx": 12.0, "cy": 12.0, "radius": 6.0, "vx": 1.0, "vy": 0.5},
                                      frames=4, seed=5, background="key")
    doc = {"id": "seek", "provider": MASK_PROVIDER, "footage": "plate", "src": "mattes/seek_%04d.pgm", "first": 3, "fps": 24,
           "segment": {"method": "chroma", "keyColor": KEY_COLOUR, "tolerance": 0.5, "softness": 0.2}}
    a = resolve(doc, frames)
    b = resolve(doc, frames)
    if a != b:
        raise MaskError("the resolve step is not deterministic")
    masks = segment(frames, doc["segment"])
    for k, (path, data) in enumerate(a[2]):
        if path != f"mattes/seek_{3 + k:04d}.pgm":
            raise MaskError("frame files are numbered from first")
        back = read_pgm16(data, 1.0)
        if any(abs(x - y) > 0.5 / PGM_MAX for rx, ry in zip(back, masks[k]) for x, y in zip(rx, ry)):
            raise MaskError("the cache does not hold the matte")
    return True


# ------------------------------------------------------------------------------------ validation


def _num(d, key, lo=None, hi=None, strict_lo=False, strict_hi=False, required=True):
    if key not in d:
        if required:
            raise MaskError(f"{key} is required")
        return None
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
        raise MaskError(f"{key} must be a finite number")
    if lo is not None and (v < lo or (strict_lo and v == lo)):
        raise MaskError(f"{key} must be {'above' if strict_lo else 'at least'} {lo}")
    if hi is not None and (v > hi or (strict_hi and v == hi)):
        raise MaskError(f"{key} must be {'below' if strict_hi else 'at most'} {hi}")
    return v


def _int(d, key, lo, hi, default):
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise MaskError(f"{key} is an integer in [{lo}, {hi}]")
    return v


def validate_segment(spec):
    """Rule MD2 for a segment child."""
    if not isinstance(spec, dict) or spec.get("method") not in SEGMENT_METHODS:
        raise MaskError(f"method is one of {SEGMENT_METHODS}")
    _int(spec, "feather", 0, MAX_FEATHER, 0)
    _int(spec, "expansion", -MAX_EXPANSION, MAX_EXPANSION, 0)
    m = spec["method"]
    if m in ("chroma", "difference"):
        _num(spec, "tolerance", 0.0, 1.0, required=False)
        _num(spec, "softness", 0.0, 1.0, required=False)
        if m == "chroma":
            key = spec.get("keyColor", KEY_COLOUR)
            if len(key) != 3 or any(isinstance(c, bool) or not isinstance(c, (int, float)) or not 0.0 <= c <= 1.0 for c in key):
                raise MaskError("keyColor is three components in [0, 1]")
    elif m == "region":
        seeds = spec.get("seeds")
        if not isinstance(seeds, (list, tuple)) or not seeds or any(len(s) != 2 for s in seeds):
            raise MaskError("region needs one or more seeds (x, y)")
        _num(spec, "tolerance", 0.0, 1.0, strict_lo=True, required=False)
    else:
        keys = spec.get("keys")
        if not isinstance(keys, (list, tuple)) or not keys:
            raise MaskError("roto needs one or more keys")
        roto_polygon(keys, 0)
    return True


def validate_estimate(spec, loose=False):
    """Rule MD3 for an estimate child; loose skips the references (camera, right) that the resolve step binds."""
    if not isinstance(spec, dict) or spec.get("method") not in DEPTH_METHODS:
        raise MaskError(f"method is one of {DEPTH_METHODS}")
    _num(spec, "fov", 0.0, 180.0, strict_lo=True, strict_hi=True)
    if spec["method"] == "plane":
        if not loose and not spec.get("camera"):
            raise MaskError("the plane method names the camera track")
    else:
        if not loose:
            _num(spec, "baseline", 0.0, strict_lo=True)
            if not spec.get("right"):
                raise MaskError("the stereo method names the right footage")
        elif "baseline" in spec:
            _num(spec, "baseline", 0.0, strict_lo=True)
        w = _int(spec, "window", MIN_WINDOW, MAX_WINDOW, 7)
        if w % 2 == 0:
            raise MaskError("window is odd")
        _int(spec, "maxDisparity", 1, MAX_DISPARITY, 64)
    return True


def validate_asset(doc):
    """Rule MD1 for an imageSequence: imported as today, or provider masks with one segment child or provider
    depth with one estimate child, a footage and a frame pattern in src; MD4 for depthScale and sha256."""
    if not isinstance(doc.get("src"), str) or not doc["src"]:
        raise MaskError("src is required")
    if "provider" not in doc:
        return True
    if doc["provider"] not in (MASK_PROVIDER, DEPTH_PROVIDER):
        raise MaskError(f"provider is {MASK_PROVIDER!r} or {DEPTH_PROVIDER!r}")
    if not isinstance(doc.get("footage"), str) or not doc["footage"]:
        raise MaskError("a computed sequence names its footage")
    frame_path(doc["src"], 0)
    if "fps" in doc:
        _num(doc, "fps", 0.0, strict_lo=True)
    if ("segment" in doc) == ("estimate" in doc):
        raise MaskError("exactly one of segment and estimate")
    if doc["provider"] == MASK_PROVIDER:
        if "segment" not in doc:
            raise MaskError("provider masks has a segment child")
        validate_segment(doc["segment"])
    else:
        if "estimate" not in doc:
            raise MaskError("provider depth has an estimate child")
        validate_estimate(doc["estimate"])
    if "depthScale" in doc:
        _num(doc, "depthScale", 0.0, strict_lo=True)
    sha = doc.get("sha256")
    if sha is not None and not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
        raise MaskError("sha256 is 64 lowercase hexadecimal digits")
    return True


# ------------------------------------------------------------------------------------ the table


def _disc(vx=1.0, vy=0.0, frames=4, seed=5, background="key", foreground="texture", radius=12.0):
    return synthetic_matte_plate(64, 48, {"kind": "disc", "cx": 30.0, "cy": 24.0, "radius": radius, "vx": vx, "vy": vy},
                                 frames=frames, seed=seed, background=background, foreground=foreground)


def _ellipse():
    return synthetic_matte_plate(128, 96, {"kind": "ellipse", "cx": 60.0, "cy": 48.0, "rx": 28.0, "ry": 18.0, "vx": 0.5, "vy": 1.0},
                                 frames=4, seed=8, background="texture")


def _iou_run(method):
    if method == "chroma":
        frames, truth = _disc()
        masks = segment(frames, {"method": "chroma", "keyColor": KEY_COLOUR, "tolerance": 0.5, "softness": 0.2})
    elif method == "difference":
        frames, truth = _ellipse()
        masks = segment(frames, {"method": "difference", "tolerance": 0.1, "softness": 0.1}, clean=clean_plate(128, 96, 8))
    elif method == "region":
        frames, truth = _disc(vx=3.0, vy=1.0, background="texture", foreground="flat", radius=10.0)
        masks = segment(frames, {"method": "region", "seeds": [(30.0, 24.0)], "tolerance": 0.15})
    else:
        pts = [(10.0, 10.0), (30.0, 12.0), (26.0, 34.0), (8.0, 30.0)]
        frames, truth = synthetic_matte_plate(64, 48, {"kind": "polygon", "points": pts, "vx": 1.0, "vy": 0.0}, frames=4,
                                              seed=1, background="texture")
        masks = segment(frames, {"method": "roto", "keys": [{"frame": 0, "points": pts},
                                                           {"frame": 3, "points": [(x + 3.0, y) for x, y in pts]}]})
    return min(iou(m, t) for m, t in zip(masks, truth))


def _stereo_run():
    K = intrinsics(96, 64, 60.0)
    left, right, truth = synthetic_stereo(96, 64, K, baseline=0.3, near=2.0, far=4.0, seed=6)
    depth = disparity_to_depth(stereo_disparity(left, right, 7, 32), K[0][0], 0.3)
    return depth_error(depth, truth, margin=16)


def _stereo_unmatched():
    K = intrinsics(96, 64, 60.0)
    left, right, truth = synthetic_stereo(96, 64, K, baseline=0.3, near=2.0, far=4.0, seed=6)
    depth = disparity_to_depth(stereo_disparity(left, right, 7, 32), K[0][0], 0.3)
    return unmatched_fraction(depth, truth, margin=16)


def _square():
    return rasterise([(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)], 40, 40)


def _seek_cache():
    frames, _ = synthetic_matte_plate(32, 24, {"kind": "disc", "cx": 12.0, "cy": 12.0, "radius": 6.0, "vx": 1.0, "vy": 0.5},
                                      frames=4, seed=5, background="key")
    doc = {"id": "seek", "provider": MASK_PROVIDER, "footage": "plate", "src": "mattes/seek_%04d.pgm", "first": 3, "fps": 24,
           "segment": {"method": "chroma", "keyColor": KEY_COLOUR, "tolerance": 0.5, "softness": 0.2}}
    return resolve(doc, frames)


TABLE = (
    ("area of a disc of radius 10 by supersampled coverage", "sum(sum(r) for r in shape_matte({'kind': 'disc', 'cx': 20, 'cy': 24, 'radius': 10}, 0, 64, 48))", "314"),
    ("half-covered pixel on a square's edge", "_square()[20][10]", "0.5"),
    ("area of the 20 px square", "sum(sum(r) for r in _square())", "400"),
    ("IoU of two half-overlapping strips", "iou([[1.0, 1.0, 0.0, 0.0]], [[0.0, 1.0, 1.0, 0.0]])", "0.333333"),
    ("chroma distance of the key from itself", "chroma_distance(KEY_COLOUR, KEY_COLOUR)", "0"),
    ("chroma distance of pure red from the key", "chroma_distance((1, 0, 0), KEY_COLOUR)", "1.41697"),
    ("chroma coverage half way up the ramp", "chroma_key_coverage((0.2938, 1, 0.2938), KEY_COLOUR, 0.2, 0.1)", "0.500211"),
    ("difference coverage at the tolerance", "difference_coverage((0.5, 0.5, 0.5), (0.5, 0.5, 0.4), 0.1, 0.1)", "0"),
    ("difference coverage past the ramp", "difference_coverage((0.5, 0.5, 0.5), (0.5, 0.5, 0.2), 0.1, 0.1)", "1"),
    ("lowest chroma-key IoU over 4 frames", "_iou_run('chroma')", "1"),
    ("lowest difference-key IoU over 4 frames, 128 x 96 plate", "_iou_run('difference')", "0.97066"),
    ("lowest region IoU over 4 frames at 3 px per frame", "_iou_run('region')", "0.950769"),
    ("lowest roto IoU over 4 frames", "_iou_run('roto')", "1"),
    ("centroid of the region on frame 3", "centroid(segment(_disc(vx=3.0, vy=1.0, background='texture', foreground='flat', radius=10.0)[0], {'method': 'region', 'seeds': [(30.0, 24.0)], 'tolerance': 0.15})[3])", "(39.0141, 27.0191)"),
    ("roto polygon half way between keys", "roto_polygon([{'frame': 0, 'points': [(0, 0), (4, 0), (4, 4)]}, {'frame': 4, 'points': [(2, 0), (6, 0), (6, 4)]}], 2)", "((1, 0), (5, 0), (5, 4))"),
    ("area after expansion by 2", "sum(sum(r) for r in expand(_square(), 2))", "576"),
    ("area after contraction by 2", "sum(sum(r) for r in expand(_square(), -2))", "256"),
    ("area after a 3 px feather", "sum(sum(r) for r in feather(_square(), 3))", "400"),
    ("feathered edge pixel", "feather(_square(), 3)[20][10]", "0.5"),
    ("depth of a frontal plane at 2 m", "plane_depth(intrinsics(64, 48, 60), euler_to_rotation(0, 0, 0), (0, 0, 2), 64, 48)[24][32]", "2"),
    ("depth at the left edge of a plane turned 30 degrees", "plane_depth(intrinsics(64, 48, 60), euler_to_rotation(0, 30, 0), (0, 0, 2), 64, 48)[24][0]", "3"),
    ("edge-on plane reads far", "plane_depth(intrinsics(64, 48, 60), euler_to_rotation(0, 90, 0), (0, 0, 2), 64, 48)[24][32]", "65.535"),
    ("disparity of 2 m at f 83.1384, baseline 0.3", "intrinsics(96, 64, 60)[0][0] * 0.3 / 2", "12.4708"),
    ("stereo depth error, 95th percentile", "_stereo_run()", "0.00565087"),
    ("stereo pixels left unmatched", "_stereo_unmatched()", "0"),
    ("depth of a 6 px disparity", "disparity_to_depth([[6.0]], intrinsics(96, 64, 60)[0][0], 0.3)[0][0]", "4.15692"),
    ("PGM header", "pgm16([[0.0, 1.0]], 1.0)[:12]", "b'P5\\n2 1\\n65535'"),
    ("PGM full scale", "pgm16([[1.0]], 1.0)[-2:]", "b'\\xff\\xff'"),
    ("depth of 1.234 m through the PGM", "read_pgm16(pgm16([[1.234]], DEPTH_FAR), DEPTH_FAR)[0][0]", "1.234"),
    ("frame path with hashes", "frame_path('m_####.pgm', 7)", "'m_0007.pgm'"),
    ("manifest path of a pattern", "manifest_path('mattes/roto_%04d.pgm')", "'mattes/roto_manifest.json'"),
    ("digest of the seek cache", "_seek_cache()[1]", "'5964a8df9b9a0f97833d8eb49ff638891c7ac4fd28f2afdde15fe536a5117e53'"),
    ("frames in the seek cache", "len(_seek_cache()[2])", "4"),
    ("seek check", "seek_test()", "True"),
    ("the IoU floor", "MIN_IOU", "0.95"),
)


def scope():
    s = dict(globals())
    s["math"] = math
    s["json"] = json
    return s


def _same(a, b, rel=5e-4, abs_tol=5e-4):
    if isinstance(a, (str, bytes)) or isinstance(b, (str, bytes)):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if a is None or b is None:
        return a is b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _fmt(v):
    if isinstance(v, (str, bytes)):
        return repr(v)
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and abs(v) < 1e-12:
        v = 0.0  # round-off residuals of exact zeros print as 0
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, (int, float)):
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
