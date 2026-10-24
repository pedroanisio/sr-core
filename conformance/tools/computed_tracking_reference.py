#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add computed tracking" (srep/srep-0000-computed-tracking.md, LA1
of SREP 12).

Pure functions and plain dict documents, standard library only:

* synthetic plates: a procedural texture warped by known homographies, so that every test has ground truth;
* point tracks: a normalised cross-correlation search followed by Lucas-Kanade refinement to sub-pixel
  precision, with a confidence and a lost state;
* planar tracks: a grid of points inside the plane, a homography fitted by the normalised DLT with RANSAC,
  and the plane's corners carried by it;
* camera solves: from a planar target of known size (Zhang's homography decomposition) and from survey
  points of known position (DLT PnP), both refined by Gauss-Newton on the re-projection error, written as
  the engine's [tx, ty, tz, rx, ry, rz, fov] camera track;
* the resolve step that writes the pinned track cache in the engine's JSON format, and the seek check.

Running the module prints the data rows of the draft's numeric table.
"""
import hashlib
import json
import math

PROVIDER = "tracks"
TRACK_KINDS = ("point", "planar", "camera")
IMPORTED_KINDS = ("point", "planar", "camera", "mask", "face")
TEMPLATE_MODES = ("first", "previous")
CAMERA_TARGETS = ("planar", "survey")
MIN_WINDOW = 5
MAX_WINDOW = 63
MAX_SEARCH = 64
MAX_ITERATIONS = 20
LOST_THRESHOLD = 0.6
CACHE_DECIMALS = 4
MIN_SURVEY_POINTS = 6
MIN_GRID = 3
MAX_GRID = 16
RANSAC_ITERATIONS = 200
RANSAC_THRESHOLD = 1.0
MAX_FRAMES = 1 << 17
DEFAULT_FPS = 24


class TrackingError(ValueError):
    """A tracking document or a numeric request that the draft rejects."""


# ------------------------------------------------------------------------------------ small linear algebra


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))] for i in range(len(a))]


def transpose(a):
    return [list(col) for col in zip(*a)]


def determinant(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def invert3(m):
    d = determinant(m)
    if abs(d) < 1e-300:
        raise TrackingError("the matrix is singular")
    c = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            minor = [[m[r][s] for s in range(3) if s != j] for r in range(3) if r != i]
            c[j][i] = ((-1) ** (i + j)) * (minor[0][0] * minor[1][1] - minor[0][1] * minor[1][0]) / d
    return c


def jacobi_eigen(matrix):
    """Eigenvalues and eigenvectors (as columns) of a symmetric matrix by cyclic Jacobi rotations."""
    n = len(matrix)
    a = [row[:] for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    scale = max(1e-300, max(abs(a[i][j]) for i in range(n) for j in range(n)))
    for _ in range(100):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j))
        if off <= 1e-15 * scale:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) <= 1e-18 * scale:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0.0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    return [a[i][i] for i in range(n)], v


def _null_vector(rows, columns):
    """The unit vector x minimising |A x| for the rows of A, and the two smallest eigenvalues of A^T A."""
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(columns)] for i in range(columns)]
    values, vectors = jacobi_eigen(ata)
    order = sorted(range(columns), key=lambda k: values[k])
    x = [vectors[i][order[0]] for i in range(columns)]
    return x, values[order[0]], values[order[1]], values[order[-1]]


def solve_linear(a, b):
    """Gaussian elimination with partial pivoting."""
    n = len(a)
    m = [row[:] + [bi] for row, bi in zip(a, b)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            raise TrackingError("the normal equations are singular")
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                if f:
                    m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


# ------------------------------------------------------------------------------------ homographies


def homography_translate(tx, ty):
    return [[1.0, 0.0, float(tx)], [0.0, 1.0, float(ty)], [0.0, 0.0, 1.0]]


def homography_rotate_scale(cx, cy, degrees, scale):
    """Rotation by `degrees` (x toward y) and scaling about (cx, cy)."""
    c, s = math.cos(math.radians(degrees)) * scale, math.sin(math.radians(degrees)) * scale
    return [[c, -s, cx - c * cx + s * cy], [s, c, cy - s * cx - c * cy], [0.0, 0.0, 1.0]]


def compose(a, b):
    """The homography applying b first, then a."""
    return matmul(a, b)


def homography_invert(h):
    return invert3(h)


def apply_homography(h, point):
    x, y = point
    w = h[2][0] * x + h[2][1] * y + h[2][2]
    if abs(w) < 1e-12:
        raise TrackingError("the point maps to infinity")
    return ((h[0][0] * x + h[0][1] * y + h[0][2]) / w, (h[1][0] * x + h[1][1] * y + h[1][2]) / w)


def _normalise_points(points):
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    mean = sum(math.hypot(p[0] - cx, p[1] - cy) for p in points) / n
    s = math.sqrt(2.0) / mean if mean > 0.0 else 1.0
    T = [[s, 0.0, -s * cx], [0.0, s, -s * cy], [0.0, 0.0, 1.0]]
    return [((p[0] - cx) * s, (p[1] - cy) * s) for p in points], T


def fit_homography(src, dst):
    """The normalised direct linear transform (Hartley and Zisserman alg. 4.2) for four or more points."""
    if len(src) < 4 or len(src) != len(dst):
        raise TrackingError("a homography needs at least four point pairs")
    ns, Ts = _normalise_points(src)
    nd, Td = _normalise_points(dst)
    rows = []
    for (x, y), (u, v) in zip(ns, nd):
        rows.append([-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u])
        rows.append([0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v])
    h, smallest, second, largest = _null_vector(rows, 9)
    if second <= 1e-9 * largest:
        raise TrackingError("the point pairs are degenerate (collinear or repeated)")
    H = [h[0:3], h[3:6], h[6:9]]
    H = matmul(invert3(Td), matmul(H, Ts))
    norm = H[2][2] if abs(H[2][2]) > 1e-9 else math.sqrt(sum(v * v for row in H for v in row))
    return [[v / norm for v in row] for row in H]


def homography_from_corners(src, dst):
    if len(src) != 4 or len(dst) != 4:
        raise TrackingError("four corners map to four corners")
    return fit_homography(list(src), list(dst))


# ------------------------------------------------------------------------------------ deterministic draws

MASK64 = (1 << 64) - 1
PHI = 0x9E3779B97F4A7C15
MUL1 = 0xBF58476D1CE4E5B9
MUL2 = 0x94D049BB133111EB
TWO53 = float(1 << 53)


def u64(x):
    if isinstance(x, bool) or not isinstance(x, int) or x < -(1 << 63) or x >= (1 << 64):
        raise TrackingError(f"not a 64-bit integer: {x!r}")
    return x & MASK64


def mix64(z):
    z &= MASK64
    z = ((z ^ (z >> 30)) * MUL1) & MASK64
    z = ((z ^ (z >> 27)) * MUL2) & MASK64
    return z ^ (z >> 31)


def splitmix64(x):
    return mix64((u64(x) + PHI) & MASK64)


def H(seed, channel, index):
    return splitmix64(u64(seed) ^ splitmix64(u64(channel) ^ splitmix64(u64(index))))


def U(seed, channel, index):
    return (H(seed, channel, index) >> 11) / TWO53


CHANNEL_TEXTURE = 0x54455854   # "TEXT"
CHANNEL_RANSAC = 0x524E5343    # "RNSC"


def ransac_homography(src, dst, threshold=RANSAC_THRESHOLD, iterations=RANSAC_ITERATIONS, seed=0):
    """RANSAC over four-point samples drawn from the document's stream; the model is refitted on the inliers."""
    n = len(src)
    if n < 4:
        raise TrackingError("RANSAC needs at least four point pairs")
    best, best_inliers = None, []
    for it in range(iterations):
        picks = []
        k = 0
        while len(picks) < 4 and k < 64:
            idx = int(U(seed, CHANNEL_RANSAC, it * 64 + k) * n)
            k += 1
            if idx not in picks:
                picks.append(idx)
        if len(picks) < 4:
            continue
        try:
            Hc = fit_homography([src[i] for i in picks], [dst[i] for i in picks])
        except TrackingError:
            continue
        inliers = []
        for i in range(n):
            try:
                px, py = apply_homography(Hc, src[i])
            except TrackingError:
                continue
            if math.hypot(px - dst[i][0], py - dst[i][1]) <= threshold:
                inliers.append(i)
        if len(inliers) > len(best_inliers):
            best, best_inliers = Hc, inliers
            if len(inliers) == n:
                break
    if best is None or len(best_inliers) < 4:
        raise TrackingError("RANSAC found no homography with four inliers")
    refit = fit_homography([src[i] for i in best_inliers], [dst[i] for i in best_inliers])
    return refit, sorted(best_inliers)


# ------------------------------------------------------------------------------------ images and plates


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def texture(width, height, seed=0):
    """Value noise in three octaves, normalised to [0, 1]: a plate with contrast everywhere."""
    if width < 2 or height < 2:
        raise TrackingError("a texture is at least 2 x 2")
    img = [[0.0] * width for _ in range(height)]
    for octave, (cell, weight) in enumerate(((8.0, 0.5), (4.0, 0.3), (2.0, 0.2))):
        nx = int(width / cell) + 2
        ny = int(height / cell) + 2
        lattice = [[U(seed, CHANNEL_TEXTURE, (octave << 40) | (j << 20) | i) for i in range(nx)] for j in range(ny)]
        for y in range(height):
            fy = y / cell
            j = int(fy)
            ty = _smooth(fy - j)
            for x in range(width):
                fx = x / cell
                i = int(fx)
                tx = _smooth(fx - i)
                a = lattice[j][i] * (1.0 - tx) + lattice[j][i + 1] * tx
                b = lattice[j + 1][i] * (1.0 - tx) + lattice[j + 1][i + 1] * tx
                img[y][x] += weight * (a * (1.0 - ty) + b * ty)
    lo = min(min(row) for row in img)
    hi = max(max(row) for row in img)
    span = hi - lo if hi > lo else 1.0
    return [[(v - lo) / span for v in row] for row in img]


def bilinear(img, x, y):
    """Bilinear sample; pixels outside the image are 0."""
    h = len(img)
    w = len(img[0])
    x0 = math.floor(x)
    y0 = math.floor(y)
    fx = x - x0
    fy = y - y0

    def px(i, j):
        return img[j][i] if 0 <= i < w and 0 <= j < h else 0.0

    top = px(x0, y0) * (1.0 - fx) + px(x0 + 1, y0) * fx
    bottom = px(x0, y0 + 1) * (1.0 - fx) + px(x0 + 1, y0 + 1) * fx
    return top * (1.0 - fy) + bottom * fy


sample = bilinear


def warp(img, h, width, height):
    """The image seen through h: output pixel (x, y) samples the input at h^-1 (x, y)."""
    inv = homography_invert(h)
    out = []
    for y in range(height):
        row = []
        for x in range(width):
            sx, sy = apply_homography(inv, (float(x), float(y)))
            row.append(bilinear(img, sx, sy))
        out.append(row)
    return out


MOTIONS = ("translate", "rotateScale", "perspective", "camera")


def camera_pose(motion, frame):
    """The pose of the synthetic camera at a frame: the frame-0 camera looks down z at the target from tz and
    moves by the per-frame deltas dtx, dty, dtz (metres) and drx, dry, drz (degrees)."""
    R = euler_to_rotation(frame * motion.get("drx", 0.0), frame * motion.get("dry", 0.0), frame * motion.get("drz", 0.0))
    t = (frame * motion.get("dtx", 0.0), frame * motion.get("dty", 0.0), motion["tz"] + frame * motion.get("dtz", 0.0))
    return R, t


def plane_projection(K, R, t):
    """The homography from the target plane z = 0 (metres) to the image: K [r1 r2 t]."""
    return matmul(K, [[R[0][0], R[0][1], t[0]], [R[1][0], R[1][1], t[1]], [R[2][0], R[2][1], t[2]]])


def _camera_plane_homography(width, height, motion, frame):
    K = intrinsics(width, height, motion["fov"])
    R, t = camera_pose(motion, frame)
    return plane_projection(K, R, t)


def synthetic_plate(width, height, motion, frames, seed=0):
    """Frames of a plate under a known motion and the homographies from frame 0 to each frame."""
    if motion.get("kind") not in MOTIONS:
        raise TrackingError(f"motion kind must be one of {MOTIONS}")
    if not 1 <= frames <= MAX_FRAMES:
        raise TrackingError("frames must lie in [1, MAX_FRAMES]")
    tex = texture(2 * width, 2 * height, seed)
    m0 = homography_translate(-width / 2.0, -height / 2.0)
    out, truth = [], []
    for k in range(frames):
        if motion["kind"] == "translate":
            hk = homography_translate(k * motion["vx"], k * motion["vy"])
        elif motion["kind"] == "rotateScale":
            hk = homography_rotate_scale(motion["cx"], motion["cy"], k * motion["degreesPerFrame"],
                                         motion["scalePerFrame"] ** k)
        elif motion["kind"] == "perspective":
            d = k * motion["drift"]
            box = ((0.0, 0.0), (float(width), 0.0), (float(width), float(height)), (0.0, float(height)))
            moved = ((d, 1.5 * d), (width - 0.5 * d, -d), (width + d, height - 1.5 * d), (-1.5 * d, height + 0.5 * d))
            hk = homography_from_corners(box, moved)
        else:
            hk = compose(_camera_plane_homography(width, height, motion, k),
                         invert3(_camera_plane_homography(width, height, motion, 0)))
        mk = compose(hk, m0)
        out.append(warp(tex, mk, width, height))
        truth.append(hk)
    return out, truth


# ------------------------------------------------------------------------------------ point tracks


def window(img, x, y, size):
    """The size x size window centred at (x, y), bilinear when the centre is fractional."""
    if size % 2 == 0 or size < MIN_WINDOW:
        raise TrackingError("the window size is odd and at least 5")
    r = size // 2
    if float(x).is_integer() and float(y).is_integer():
        xi, yi = int(x), int(y)
        h, w = len(img), len(img[0])
        return [[img[yi + j][xi + i] if 0 <= xi + i < w and 0 <= yi + j < h else 0.0 for i in range(-r, r + 1)]
                for j in range(-r, r + 1)]
    return [[bilinear(img, x + i, y + j) for i in range(-r, r + 1)] for j in range(-r, r + 1)]


def window_inside(img, x, y, size):
    r = size // 2
    return x - r >= 0 and y - r >= 0 and x + r <= len(img[0]) - 1 and y + r <= len(img) - 1


def _stats(block):
    n = len(block) * len(block[0])
    mean = sum(sum(row) for row in block) / n
    var = sum((v - mean) ** 2 for row in block for v in row)
    return mean, var


def ncc(template, img, cx, cy):
    """Zero-mean normalised cross-correlation of the template with the window at (cx, cy)."""
    block = window(img, cx, cy, len(template))
    mt, vt = _stats(template)
    mb, vb = _stats(block)
    if vt <= 1e-18 or vb <= 1e-18:
        return 0.0
    cov = sum((t - mt) * (b - mb) for trow, brow in zip(template, block) for t, b in zip(trow, brow))
    return cov / math.sqrt(vt * vb)


def ncc_search(template, img, x, y, search):
    """The integer position within +-search of (x, y) whose window correlates best: (ix, iy, score)."""
    size = len(template)
    cx, cy = int(round(x)), int(round(y))
    best = (cx, cy, -2.0)
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            px, py = cx + dx, cy + dy
            if not window_inside(img, px, py, size):
                continue
            score = ncc(template, img, px, py)
            if score > best[2] or (score == best[2] and (abs(dx) + abs(dy)) < (abs(best[0] - cx) + abs(best[1] - cy))):
                best = (px, py, score)
    return best


def lucas_kanade(template, img, x, y, iterations=MAX_ITERATIONS):
    """Gauss-Newton on the translation that matches the template to the image around (x, y)."""
    size = len(template)
    r = size // 2
    residual = float("inf")
    done = 0
    for it in range(1, iterations + 1):
        done = it
        gxx = gxy = gyy = bx = by = 0.0
        residual = 0.0
        for j in range(-r, r + 1):
            for i in range(-r, r + 1):
                px, py = x + i, y + j
                v = bilinear(img, px, py)
                gx = bilinear(img, px + 0.5, py) - bilinear(img, px - 0.5, py)
                gy = bilinear(img, px, py + 0.5) - bilinear(img, px, py - 0.5)
                e = v - template[j + r][i + r]
                residual += e * e
                gxx += gx * gx
                gxy += gx * gy
                gyy += gy * gy
                bx += gx * e
                by += gy * e
        residual /= size * size
        det = gxx * gyy - gxy * gxy
        if det <= 1e-18:
            break
        dx = -(gyy * bx - gxy * by) / det
        dy = -(-gxy * bx + gxx * by) / det
        x += dx
        y += dy
        if math.hypot(dx, dy) < 1e-4:
            break
    return x, y, residual, done


def _solve_defaults(solve):
    s = dict(solve)
    s.setdefault("window", 15)
    s.setdefault("search", 8)
    s.setdefault("template", "first")
    s.setdefault("grid", 4)
    return s


def _track_one(frames, x0, y0, size, search, template_mode):
    """Track one point through the frames: a list of (x, y, confidence, status)."""
    out = [(float(x0), float(y0), 1.0, "tracked")]
    template = window(frames[0], float(x0), float(y0), size)
    x, y = float(x0), float(y0)
    lost = False
    for k in range(1, len(frames)):
        if lost:
            out.append((x, y, out[-1][2], "lost"))
            continue
        img = frames[k]
        ix, iy, score = ncc_search(template, img, x, y, search)
        if score < LOST_THRESHOLD:
            lost = True
            out.append((x, y, score, "lost"))
            continue
        nx, ny, _residual, _its = lucas_kanade(template, img, float(ix), float(iy))
        if not window_inside(img, nx, ny, size) or math.hypot(nx - ix, ny - iy) > 1.5:
            lost = True
            out.append((x, y, score, "lost"))
            continue
        confidence = ncc(template, img, nx, ny)
        if confidence < LOST_THRESHOLD:
            lost = True
            out.append((x, y, confidence, "lost"))
            continue
        x, y = nx, ny
        out.append((x, y, confidence, "tracked"))
        if template_mode == "previous":
            template = window(img, x, y, size)
    return out


def track_point(frames, solve):
    """A point track as the list of {frame, x, y, confidence, status}."""
    s = _solve_defaults(solve)
    validate_solve("point", s)
    if not frames:
        raise TrackingError("no frames")
    raw = _track_one(frames, s["x"], s["y"], s["window"], s["search"], s["template"])
    return [{"frame": k, "x": x, "y": y, "confidence": c, "status": st} for k, (x, y, c, st) in enumerate(raw)]


def point_error(track, truth, start):
    """The largest distance between the track and the true position over the frames."""
    worst = 0.0
    for t, h in zip(track, truth):
        tx, ty = apply_homography(h, start)
        worst = max(worst, math.hypot(t["x"] - tx, t["y"] - ty))
    return worst


# ------------------------------------------------------------------------------------ planar tracks


def convex_quad(corners):
    """True for four corners in order that make a convex, non-self-crossing quadrilateral."""
    if len(corners) != 4:
        return False
    signs = []
    for k in range(4):
        ax, ay = corners[k]
        bx, by = corners[(k + 1) % 4]
        cx, cy = corners[(k + 2) % 4]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) < 1e-12:
            return False
        signs.append(cross > 0.0)
    return all(signs) or not any(signs)


def grid_points(corners, grid):
    """grid x grid points spread inside the quadrilateral, bilinear in its corners, 15 % in from the edges."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = corners
    pts = []
    for a in range(grid):
        u = 0.15 + 0.7 * a / (grid - 1)
        for b in range(grid):
            v = 0.15 + 0.7 * b / (grid - 1)
            top = (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)
            bottom = (x3 + (x2 - x3) * u, y3 + (y2 - y3) * u)
            pts.append((top[0] + (bottom[0] - top[0]) * v, top[1] + (bottom[1] - top[1]) * v))
    return pts


def track_plane(frames, solve):
    """A planar track: {frame, corners, inliers, error} per frame."""
    s = _solve_defaults(solve)
    validate_solve("planar", s)
    if not frames:
        raise TrackingError("no frames")
    corners = [tuple(map(float, c)) for c in s["corners"]]
    seeds = grid_points(corners, s["grid"])
    tracks = [_track_one(frames, x, y, s["window"], s["search"], "previous") for x, y in seeds]
    out = [{"frame": 0, "corners": tuple(corners), "inliers": len(seeds), "error": 0.0}]
    last = None
    for k in range(1, len(frames)):
        src = [seeds[i] for i in range(len(seeds)) if tracks[i][k][3] == "tracked"]
        dst = [(tracks[i][k][0], tracks[i][k][1]) for i in range(len(seeds)) if tracks[i][k][3] == "tracked"]
        if len(src) < 4:
            if last is None:
                raise TrackingError(f"the plane was lost at frame {k}")
            out.append({"frame": k, "corners": out[-1]["corners"], "inliers": 0, "error": out[-1]["error"]})
            continue
        Hk, inliers = ransac_homography(src, dst, seed=k)
        err = 0.0
        for i in inliers:
            px, py = apply_homography(Hk, src[i])
            err += (px - dst[i][0]) ** 2 + (py - dst[i][1]) ** 2
        err = math.sqrt(err / len(inliers))
        last = Hk
        out.append({"frame": k, "corners": tuple(apply_homography(Hk, c) for c in corners),
                    "inliers": len(inliers), "error": err})
    return out


def plane_error(track, truth, corners):
    worst = 0.0
    for t, h in zip(track, truth):
        for c, got in zip(corners, t["corners"]):
            tx, ty = apply_homography(h, c)
            worst = max(worst, math.hypot(got[0] - tx, got[1] - ty))
    return worst


# ------------------------------------------------------------------------------------ cameras


def intrinsics(width, height, fov_degrees):
    """The pinhole matrix with the horizontal field of view fov (the engine's camera fov) and the centre."""
    if not 0.0 < fov_degrees < 180.0:
        raise TrackingError("fov lies strictly between 0 and 180 degrees")
    f = (width / 2.0) / math.tan(math.radians(fov_degrees) / 2.0)
    return [[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]]


def euler_to_rotation(rx, ry, rz):
    """R = Rz(rz) Ry(ry) Rx(rx), degrees."""
    ax, ay, az = (math.radians(v) for v in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    Rx = [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]]
    Ry = [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]]
    Rz = [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]
    return matmul(Rz, matmul(Ry, Rx))


def rotation_to_euler(R):
    sy = -R[2][0]
    sy = max(-1.0, min(1.0, sy))
    ry = math.asin(sy)
    if abs(math.cos(ry)) > 1e-9:
        rx = math.atan2(R[2][1], R[2][2])
        rz = math.atan2(R[1][0], R[0][0])
    else:
        rx = math.atan2(-R[1][2], R[1][1])
        rz = 0.0
    return (math.degrees(rx), math.degrees(ry), math.degrees(rz))


def rotation_vector(R):
    """The axis-angle vector of R (the logarithm map)."""
    trace = R[0][0] + R[1][1] + R[2][2]
    angle = math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))
    if angle < 1e-12:
        return (0.0, 0.0, 0.0)
    if abs(math.pi - angle) < 1e-6:
        # near pi the off-diagonals vanish: take the axis from the diagonal
        axis = [math.sqrt(max(0.0, (R[i][i] + 1.0) / 2.0)) for i in range(3)]
        if R[0][1] < 0.0:
            axis[1] = -axis[1]
        if R[0][2] < 0.0:
            axis[2] = -axis[2]
        return tuple(angle * a for a in axis)
    k = angle / (2.0 * math.sin(angle))
    return (k * (R[2][1] - R[1][2]), k * (R[0][2] - R[2][0]), k * (R[1][0] - R[0][1]))


def rotation_from_vector(v):
    """Rodrigues' formula."""
    angle = math.sqrt(sum(c * c for c in v))
    if angle < 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    kx, ky, kz = (c / angle for c in v)
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return [[t * kx * kx + c, t * kx * ky - s * kz, t * kx * kz + s * ky],
            [t * kx * ky + s * kz, t * ky * ky + c, t * ky * kz - s * kx],
            [t * kx * kz - s * ky, t * ky * kz + s * kx, t * kz * kz + c]]


def _orthonormalise(m):
    """The nearest rotation to m by Higham's polar iteration, with a positive determinant."""
    R = [row[:] for row in m]
    if determinant(R) < 0.0:
        R = [[-v for v in row] for row in R]
    for _ in range(50):
        inv_t = transpose(invert3(R))
        nxt = [[0.5 * (R[i][j] + inv_t[i][j]) for j in range(3)] for i in range(3)]
        delta = max(abs(nxt[i][j] - R[i][j]) for i in range(3) for j in range(3))
        R = nxt
        if delta < 1e-15:
            break
    return R


def project(K, R, t, X):
    """The pixel of world point X through the camera (R, t): x = K (R X + t), z forward."""
    cam = [sum(R[i][k] * X[k] for k in range(3)) + t[i] for i in range(3)]
    if cam[2] <= 1e-12:
        raise TrackingError("the point is behind the camera")
    return (K[0][0] * cam[0] / cam[2] + K[0][2], K[1][1] * cam[1] / cam[2] + K[1][2])


def reprojection_error(K, R, t, world, image):
    """The root mean square distance between projected world points and their image positions."""
    total = 0.0
    for X, (u, v) in zip(world, image):
        px, py = project(K, R, t, X)
        total += (px - u) ** 2 + (py - v) ** 2
    return math.sqrt(total / len(world))


def planar_target_points(width, height):
    """Corners TL, TR, BR, BL of a width x height target on the plane z = 0, centred, metres, y down."""
    if not width > 0.0 or not height > 0.0:
        raise TrackingError("the target has positive width and height")
    w, h = width / 2.0, height / 2.0
    return ((-w, -h), (w, -h), (w, h), (-w, h))


def planar_pose(H, K):
    """Zhang's decomposition of the target-to-image homography: K^-1 H = lambda [r1 r2 t]."""
    B = matmul(invert3(K), H)
    b1 = [B[i][0] for i in range(3)]
    b2 = [B[i][1] for i in range(3)]
    b3 = [B[i][2] for i in range(3)]
    n1 = math.sqrt(sum(v * v for v in b1))
    n2 = math.sqrt(sum(v * v for v in b2))
    if n1 < 1e-300 or n2 < 1e-300:
        raise TrackingError("the homography is degenerate")
    lam = 2.0 / (n1 + n2)
    r1 = [v * lam for v in b1]
    r2 = [v * lam for v in b2]
    t = [v * lam for v in b3]
    if t[2] < 0.0:
        r1, r2, t = [-v for v in r1], [-v for v in r2], [-v for v in t]
    r3 = [r1[1] * r2[2] - r1[2] * r2[1], r1[2] * r2[0] - r1[0] * r2[2], r1[0] * r2[1] - r1[1] * r2[0]]
    R = _orthonormalise([[r1[i], r2[i], r3[i]] for i in range(3)])
    return {"R": R, "t": tuple(t)}


def refine_pose(pose, K, world, image, iterations=MAX_ITERATIONS):
    """Gauss-Newton on (rotation vector, translation) minimising the re-projection error."""
    params = list(rotation_vector(pose["R"])) + list(pose["t"])

    def residuals(p):
        R = rotation_from_vector(p[0:3])
        t = p[3:6]
        out = []
        for X, (u, v) in zip(world, image):
            px, py = project(K, R, t, X)
            out.extend((px - u, py - v))
        return out

    r = residuals(params)
    cost = sum(v * v for v in r)
    damping = 1e-3
    for _ in range(iterations):
        jac = []
        for k in range(6):
            step = 1e-6
            plus = params[:]
            plus[k] += step
            jac.append([(a - b) / step for a, b in zip(residuals(plus), r)])
        jtj = [[sum(jac[i][m] * jac[j][m] for m in range(len(r))) for j in range(6)] for i in range(6)]
        jtr = [sum(jac[i][m] * r[m] for m in range(len(r))) for i in range(6)]
        improved = False
        for _attempt in range(8):
            a = [[jtj[i][j] + (damping * jtj[i][i] if i == j else 0.0) for j in range(6)] for i in range(6)]
            try:
                delta = solve_linear(a, [-v for v in jtr])
            except TrackingError:
                damping *= 10.0
                continue
            trial = [p + d for p, d in zip(params, delta)]
            try:
                rt = residuals(trial)
            except TrackingError:
                damping *= 10.0
                continue
            ct = sum(v * v for v in rt)
            if ct < cost:
                params, r, cost = trial, rt, ct
                damping = max(1e-9, damping / 10.0)
                improved = True
                break
            damping *= 10.0
        if not improved or cost < 1e-24:
            break
    R = rotation_from_vector(params[0:3])
    t = tuple(params[3:6])
    return {"R": R, "t": t, "error": math.sqrt(cost / len(world))}


def pnp_dlt(world, image, K):
    """The direct linear transform for the projection matrix from six or more non-coplanar points."""
    if len(world) < MIN_SURVEY_POINTS or len(world) != len(image):
        raise TrackingError(f"the DLT needs at least {MIN_SURVEY_POINTS} point pairs")
    n = len(world)
    cx, cy, cz = (sum(p[i] for p in world) / n for i in range(3))
    cov = [[sum((p[i] - (cx, cy, cz)[i]) * (p[j] - (cx, cy, cz)[j]) for p in world) for j in range(3)] for i in range(3)]
    values, _ = jacobi_eigen(cov)
    if min(values) <= 1e-9 * max(values):
        raise TrackingError("the survey points are coplanar: use the planar target solve")
    Kinv = invert3(K)
    rows = []
    for (X, Y, Z), (u, v) in zip(world, image):
        xn = Kinv[0][0] * u + Kinv[0][1] * v + Kinv[0][2]
        yn = Kinv[1][1] * v + Kinv[1][2]
        rows.append([X, Y, Z, 1.0, 0.0, 0.0, 0.0, 0.0, -xn * X, -xn * Y, -xn * Z, -xn])
        rows.append([0.0, 0.0, 0.0, 0.0, X, Y, Z, 1.0, -yn * X, -yn * Y, -yn * Z, -yn])
    p, _smallest, _second, _largest = _null_vector(rows, 12)
    P = [p[0:4], p[4:8], p[8:12]]
    M = [row[0:3] for row in P]
    if determinant(M) < 0.0:
        P = [[-v for v in row] for row in P]
        M = [row[0:3] for row in P]
    scale = determinant(M) ** (1.0 / 3.0)
    R = _orthonormalise([[v / scale for v in row] for row in M])
    t = tuple(P[i][3] / scale for i in range(3))
    pose = {"R": R, "t": t}
    return refine_pose(pose, K, world, image)


def solve_camera(frames, solve):
    """The camera track {frame, tx, ty, tz, rx, ry, rz, fov, error} from a planar target or survey points."""
    s = _solve_defaults(solve)
    validate_solve("camera", s)
    if not frames:
        raise TrackingError("no frames")
    width, height = len(frames[0][0]), len(frames[0])
    K = intrinsics(width, height, s["fov"])
    out = []
    if s["target"] == "planar":
        target = planar_target_points(s["width"], s["height"])
        plane = [(X, Y, 0.0) for X, Y in target]
        planar = track_plane(frames, {"kind": "planar", "corners": s["corners"], "grid": s["grid"],
                                      "window": s["window"], "search": s["search"]})
        for entry in planar:
            Hk = homography_from_corners(target, entry["corners"])
            pose = refine_pose(planar_pose(Hk, K), K, plane, list(entry["corners"]))
            out.append(_camera_entry(entry["frame"], pose, s["fov"]))
    else:
        world = [(p["X"], p["Y"], p["Z"]) for p in s["points"]]
        tracks = [_track_one(frames, p["x"], p["y"], s["window"], s["search"], s["template"]) for p in s["points"]]
        for k in range(len(frames)):
            seen = [(tracks[i][k][0], tracks[i][k][1]) for i in range(len(world)) if tracks[i][k][3] == "tracked"]
            pts = [world[i] for i in range(len(world)) if tracks[i][k][3] == "tracked"]
            if len(pts) < MIN_SURVEY_POINTS:
                raise TrackingError(f"fewer than {MIN_SURVEY_POINTS} survey points tracked at frame {k}")
            out.append(_camera_entry(k, pnp_dlt(pts, seen, K), s["fov"]))
    return out


def _camera_entry(frame, pose, fov):
    rx, ry, rz = rotation_to_euler(pose["R"])
    tx, ty, tz = pose["t"]
    return {"frame": frame, "tx": tx, "ty": ty, "tz": tz, "rx": rx, "ry": ry, "rz": rz, "fov": float(fov),
            "error": pose.get("error", 0.0)}


# ------------------------------------------------------------------------------------ the cache


def _round(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    r = round(float(v), CACHE_DECIMALS)
    return 0.0 if r == 0.0 else r


def cache_json(fps, points, planes, cameras):
    """The engine's JSON track format with sorted keys and values rounded to CACHE_DECIMALS, one line, newline
    terminated, so that the same tracks give the same bytes."""
    doc = {
        "fps": fps,
        "points": {name: [[int(f), _round(x), _round(y)] for f, x, y in rows] for name, rows in sorted(points.items())},
        "planes": {name: [[int(f)] + [_round(v) for v in flat] for f, flat in rows] for name, rows in sorted(planes.items())},
        "cameras": {name: [[int(row[0])] + [_round(v) for v in row[1:]] for row in rows] for name, rows in sorted(cameras.items())},
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n"


def cache_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_cache(text, digest):
    got = cache_digest(text)
    if got != digest:
        raise TrackingError(f"cache digest {got} differs from the pinned {digest}")
    return True


def _interp(rows, frame, width):
    if not rows:
        raise TrackingError("the track is empty")
    if frame <= rows[0][0]:
        return tuple(rows[0][1:1 + width])
    if frame >= rows[-1][0]:
        return tuple(rows[-1][1:1 + width])
    k = 1
    while rows[k][0] <= frame:
        k += 1
    a, b = rows[k - 1], rows[k]
    t = (frame - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(1, 1 + width))


def frame_sample(cache, name, frame):
    """What the engine reads at a frame: a point, a plane's centre or a camera, linear between frames."""
    if name in cache.get("points", {}):
        return _interp(cache["points"][name], frame, 2)
    if name in cache.get("planes", {}):
        flat = _interp(cache["planes"][name], frame, 8)
        return (sum(flat[0::2]) / 4.0, sum(flat[1::2]) / 4.0)
    if name in cache.get("cameras", {}):
        return _interp(cache["cameras"][name], frame, 7)
    raise TrackingError(f"no track named {name!r}")


def resolve(doc, frames):
    """The resolve step: run the document's solve on the footage frames and return the cache text and digest."""
    validate_track_data(doc)
    if doc.get("provider") != PROVIDER:
        raise TrackingError("only provider tracks resolves")
    if doc["solve"]["kind"] != doc["kind"]:
        raise TrackingError("the solve kind must match the track kind")
    fps = doc.get("fps", DEFAULT_FPS)
    name = doc["id"]
    points, planes, cameras = {}, {}, {}
    if doc["kind"] == "point":
        points[name] = [(t["frame"], t["x"], t["y"]) for t in track_point(frames, doc["solve"])]
    elif doc["kind"] == "planar":
        planes[name] = [(t["frame"], tuple(v for c in t["corners"] for v in c)) for t in track_plane(frames, doc["solve"])]
    else:
        cameras[name] = [(t["frame"], t["tx"], t["ty"], t["tz"], t["rx"], t["ry"], t["rz"], t["fov"])
                         for t in solve_camera(frames, doc["solve"])]
    text = cache_json(fps, points, planes, cameras)
    return text, cache_digest(text)


def seek_test():
    """Resolving twice gives the same bytes, and a frame read from the cache is the tracked position."""
    frames, _ = synthetic_plate(48, 36, {"kind": "translate", "vx": 0.8, "vy": 0.4}, frames=5, seed=21)
    doc = {"id": "seek", "kind": "point", "footage": "plate", "provider": PROVIDER, "src": "tracks/seek.json",
           "solve": {"kind": "point", "x": 20.0, "y": 16.0, "window": 9, "search": 4}}
    a, da = resolve(doc, frames)
    b, db = resolve(doc, frames)
    if a != b or da != db:
        raise TrackingError("the resolve step is not deterministic")
    cache = json.loads(a)
    track = track_point(frames, doc["solve"])
    for t in track:
        x, y = frame_sample(cache, "seek", float(t["frame"]))
        if abs(x - t["x"]) > 10.0 ** -CACHE_DECIMALS or abs(y - t["y"]) > 10.0 ** -CACHE_DECIMALS:
            raise TrackingError("the cache does not hold the track")
    return True


# ------------------------------------------------------------------------------------ validation


def _number(d, key, lo=None, hi=None, strict=False):
    if key not in d:
        raise TrackingError(f"{key} is required")
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
        raise TrackingError(f"{key} must be a finite number, not {v!r}")
    if lo is not None and (v < lo or (strict and v == lo)):
        raise TrackingError(f"{key} must be {'above' if strict else 'at least'} {lo}")
    if hi is not None and (v > hi or (strict and v == hi)):
        raise TrackingError(f"{key} must be {'below' if strict else 'at most'} {hi}")
    return v


def _corners(d):
    corners = d.get("corners")
    if not isinstance(corners, (list, tuple)) or len(corners) != 4 or any(len(c) != 2 for c in corners):
        raise TrackingError("corners are four (x, y) pairs")
    corners = [tuple(float(v) for v in c) for c in corners]
    if not convex_quad(corners):
        raise TrackingError("corners must form a convex quadrilateral in order")
    return corners


def validate_solve(kind, s):
    """Rules CT2 (point), CT3 (planar) and CT4 (camera) for a solve child."""
    if s.get("kind", kind) != kind:
        raise TrackingError("the solve kind must match the track kind")
    w = s.get("window", 15)
    if isinstance(w, bool) or not isinstance(w, int) or w % 2 == 0 or not MIN_WINDOW <= w <= MAX_WINDOW:
        raise TrackingError(f"window is an odd integer in [{MIN_WINDOW}, {MAX_WINDOW}]")
    sr = s.get("search", 8)
    if isinstance(sr, bool) or not isinstance(sr, int) or not 1 <= sr <= MAX_SEARCH:
        raise TrackingError(f"search is an integer in [1, {MAX_SEARCH}]")
    if s.get("template", "first") not in TEMPLATE_MODES:
        raise TrackingError(f"template is one of {TEMPLATE_MODES}")
    if kind == "point":
        _number(s, "x")
        _number(s, "y")
    elif kind == "planar":
        _corners(s)
        g = s.get("grid", 4)
        if isinstance(g, bool) or not isinstance(g, int) or not MIN_GRID <= g <= MAX_GRID:
            raise TrackingError(f"grid is an integer in [{MIN_GRID}, {MAX_GRID}]")
    elif kind == "camera":
        if s.get("target") not in CAMERA_TARGETS:
            raise TrackingError(f"target is one of {CAMERA_TARGETS}")
        _number(s, "fov", 0.0, 180.0, strict=True)
        if s["target"] == "planar":
            _corners(s)
            _number(s, "width", 0.0, strict=True)
            _number(s, "height", 0.0, strict=True)
        else:
            pts = s.get("points")
            if not isinstance(pts, (list, tuple)) or len(pts) < MIN_SURVEY_POINTS:
                raise TrackingError(f"survey needs at least {MIN_SURVEY_POINTS} points")
            for p in pts:
                for key in ("x", "y", "X", "Y", "Z"):
                    _number(p, key)
    else:
        raise TrackingError(f"kind is one of {TRACK_KINDS}")
    return True


def validate_track_data(doc):
    """Rule CT1 for trackData: imported tracks as today; provider tracks needs footage, src and a matching solve."""
    if not isinstance(doc.get("id"), str) or not doc["id"]:
        raise TrackingError("id is required")
    if not isinstance(doc.get("src"), str) or not doc["src"]:
        raise TrackingError("src is required")
    sha = doc.get("sha256")
    if sha is not None and not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
        raise TrackingError("sha256 is 64 lowercase hexadecimal digits")
    if "provider" not in doc:
        if doc.get("kind") not in IMPORTED_KINDS:
            raise TrackingError(f"kind is one of {IMPORTED_KINDS}")
        return True
    if doc["provider"] != PROVIDER:
        raise TrackingError(f"provider must be {PROVIDER!r}")
    if doc.get("kind") not in TRACK_KINDS:
        raise TrackingError(f"a computed track's kind is one of {TRACK_KINDS}")
    if not isinstance(doc.get("footage"), str) or not doc["footage"]:
        raise TrackingError("a computed track names its footage")
    if not isinstance(doc.get("solve"), dict):
        raise TrackingError("a computed track has one solve child")
    if "fps" in doc:
        _number(doc, "fps", 0.0, strict=True)
    validate_solve(doc["kind"], doc["solve"])
    return True


# ------------------------------------------------------------------------------------ the table


def _point_run(kind):
    if kind == "translate":
        motion = {"kind": "translate", "vx": 1.7, "vy": -0.9}
        template = "first"
    else:
        motion = {"kind": "rotateScale", "cx": 48.0, "cy": 36.0, "degreesPerFrame": 1.5, "scalePerFrame": 1.01}
        template = "previous"
    frames, truth = synthetic_plate(96, 72, motion, frames=16, seed=11)
    track = track_point(frames, {"kind": "point", "x": 40.0, "y": 30.0, "window": 11, "search": 6, "template": template})
    return point_error(track, truth, (40.0, 30.0))


def _lost_run():
    frames, _ = synthetic_plate(64, 48, {"kind": "translate", "vx": 6.0, "vy": 0.0}, frames=12, seed=2)
    track = track_point(frames, {"kind": "point", "x": 50.0, "y": 24.0, "window": 11, "search": 8})
    return [t["status"] for t in track].index("lost")


def _plane_run():
    frames, truth = synthetic_plate(96, 72, {"kind": "perspective", "drift": 0.4}, frames=12, seed=7)
    corners = ((20.0, 14.0), (72.0, 14.0), (72.0, 56.0), (20.0, 56.0))
    return plane_error(track_plane(frames, {"kind": "planar", "corners": corners, "grid": 4, "window": 11, "search": 6}),
                       truth, corners)


def camera_motion():
    """The synthetic camera of the draft's camera rows: the 0.48 x 0.36 m target fills (24, 18)-(72, 54) of a
    96 x 72 plate at 60 degrees, then the camera moves and turns a little every frame."""
    f = intrinsics(96, 72, 60.0)[0][0]
    return {"kind": "camera", "fov": 60.0, "width": 0.48, "height": 0.36, "tz": f / 100.0,
            "dtx": 0.004, "dty": -0.002, "dtz": 0.01, "drx": 0.6, "dry": -0.8, "drz": 0.4}


def _camera_run():
    frames, truth = synthetic_plate(96, 72, camera_motion(), frames=8, seed=9)
    corners = ((24.0, 18.0), (72.0, 18.0), (72.0, 54.0), (24.0, 54.0))
    track = solve_camera(frames, {"kind": "camera", "target": "planar", "corners": corners, "width": 0.48,
                                  "height": 0.36, "fov": 60.0, "grid": 4, "window": 11, "search": 6})
    K = intrinsics(96, 72, 60.0)
    plane = [(X, Y, 0.0) for X, Y in planar_target_points(0.48, 0.36)]
    worst = 0.0
    for t, Hk in zip(track, truth):
        R = euler_to_rotation(t["rx"], t["ry"], t["rz"])
        seen = [apply_homography(Hk, c) for c in corners]
        worst = max(worst, reprojection_error(K, R, (t["tx"], t["ty"], t["tz"]), plane, seen))
    return worst


def _survey_run():
    K = intrinsics(640, 480, 50.0)
    R = euler_to_rotation(-8.0, 15.0, 40.0)
    t = (-0.3, 0.2, 4.0)
    world = [(x, y, z) for x in (-1.0, 0.0, 1.0) for y in (-0.5, 0.5) for z in (0.0, 0.7)]
    image = [project(K, R, t, X) for X in world]
    jitter = [(x + 0.4 * math.sin(k), y + 0.4 * math.cos(k)) for k, (x, y) in enumerate(image)]
    pose = refine_pose(pnp_dlt(world, jitter, K), K, world, jitter)
    return reprojection_error(K, pose["R"], pose["t"], world, jitter)


def _seek_cache():
    frames, _ = synthetic_plate(48, 36, {"kind": "translate", "vx": 0.8, "vy": 0.4}, frames=5, seed=21)
    doc = {"id": "seek", "kind": "point", "footage": "plate", "provider": PROVIDER, "src": "tracks/seek.json",
           "solve": {"kind": "point", "x": 20.0, "y": 16.0, "window": 9, "search": 4}}
    return resolve(doc, frames)


TABLE = (
    ("translation of (10, 10) by (3, -2)", "apply_homography(homography_translate(3, -2), (10, 10))", "(13, 8)"),
    ("quarter turn doubled about (48, 36) moves (49, 36)", "apply_homography(homography_rotate_scale(48, 36, 90, 2), (49, 36))", "(48, 38)"),
    ("texture contrast, 64 x 48, seed 3", "max(max(r) for r in texture(64, 48, 3)) - min(min(r) for r in texture(64, 48, 3))", "1"),
    ("integer warp moves pixels exactly", "warp(texture(64, 48, 3), homography_translate(5, 0), 64, 48)[20][30] - texture(64, 48, 3)[20][25]", "0"),
    ("NCC of a window with itself", "ncc(window(texture(80, 60, 5), 40, 30, 11), texture(80, 60, 5), 40, 30)", "1"),
    ("NCC search finds the integer offset", "ncc_search(window(texture(80, 60, 5), 40, 30, 11), warp(texture(80, 60, 5), homography_translate(2.3, -1.4), 80, 60), 40, 30, 5)[:2]", "(42, 29)"),
    ("Lucas-Kanade refines to (42.3, 28.6)", "lucas_kanade(window(texture(80, 60, 5), 40, 30, 11), warp(texture(80, 60, 5), homography_translate(2.3, -1.4), 80, 60), 42, 29)[:2]", "(42.2667, 28.6105)"),
    ("point track error, translation 1.7, -0.9 px per frame, 16 frames", "_point_run('translate')", "0.0376976"),
    ("point track error, 1.5 degrees and 1 percent per frame, 16 frames", "_point_run('rotateScale')", "0.422971"),
    ("frame at which a point leaving the plate is lost", "_lost_run()", "2"),
    ("DLT residual on 25 exact pairs", "max(math.hypot(*(a - b for a, b in zip(apply_homography(fit_homography([(5 + 7 * i, 4 + 5 * j) for i in range(5) for j in range(5)], [apply_homography(homography_from_corners(((0, 0), (40, 0), (40, 30), (0, 30)), ((2, 1), (43, 0.5), (41, 32), (1, 29))), (5 + 7 * i, 4 + 5 * j)) for i in range(5) for j in range(5)]), (5 + 7 * i, 4 + 5 * j)), apply_homography(homography_from_corners(((0, 0), (40, 0), (40, 30), (0, 30)), ((2, 1), (43, 0.5), (41, 32), (1, 29))), (5 + 7 * i, 4 + 5 * j))))) for i in range(5) for j in range(5))", "0"),
    ("planar track corner error, perspective drift 0.4 px per frame, 12 frames", "_plane_run()", "0.188339"),
    ("focal length of a 1920 px frame at 90 degrees", "intrinsics(1920, 1080, 90)[0][0]", "960"),
    ("Euler round trip", "rotation_to_euler(euler_to_rotation(10, -20, 30))", "(10, -20, 30)"),
    ("a point 1 m right at 2 m lands at", "project(intrinsics(1920, 1080, 90), euler_to_rotation(0, 0, 0), (0, 0, 0), (1, 0, 2))", "(1440, 540)"),
    ("planar pose recovers tz 2.5", "planar_pose(homography_from_corners(planar_target_points(0.8, 0.6), [project(intrinsics(640, 480, 60), euler_to_rotation(12, -25, 5), (0.1, -0.05, 2.5), (X, Y, 0)) for X, Y in planar_target_points(0.8, 0.6)]), intrinsics(640, 480, 60))['t']", "(0.1, -0.05, 2.5)"),
    ("survey solve RMS error with 0.4 px jitter", "_survey_run()", "0.383124"),
    ("camera track re-projection error, 8 frames", "_camera_run()", "0.199182"),
    ("cache rounds to four decimals", "json.loads(cache_json(24, {'p': [(0, 10.123456, 20)]}, {}, {}))['points']['p'][0]", "(0, 10.1235, 20)"),
    ("cache keys are sorted", "list(json.loads(cache_json(24, {'p': [(0, 1, 2)]}, {}, {})))", "('cameras', 'fps', 'planes', 'points')"),
    ("digest of the seek cache", "_seek_cache()[1]", "'b5991b861f95726c394ab2bafa0de8c3ee2dfb72a8b37d50677139a3c1130b12'"),
    ("length of the seek cache", "len(_seek_cache()[0])", "150"),
    ("frame 2 of the seek cache", "frame_sample(json.loads(_seek_cache()[0]), 'seek', 2)", "(21.5956, 16.8313)"),
    ("half a frame between (10, 20) and (11, 21.5)", "frame_sample({'points': {'p': [[0, 10, 20], [1, 11, 21.5]]}}, 'p', 0.5)", "(10.5, 20.75)"),
    ("seek check", "seek_test()", "True"),
    ("lost threshold", "LOST_THRESHOLD", "0.6"),
    ("largest window", "MAX_WINDOW", "63"),
)


def scope():
    s = dict(globals())
    s["math"] = math
    s["json"] = json
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
