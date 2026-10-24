#!/usr/bin/env python3
"""Reference for the draft SREP "Add plate integration" (LA3 of SREP 12).

A camera track solved by the computed-tracking draft (or imported) drives a `camera`: the row's (R, t), with
x_cam = R x_world + t and R = Rz(rz) Ry(ry) Rx(rx), becomes the engine's pose T(eye) Ry(yaw) Rx(pitch) Rz(roll),
eye = -trackScale R^T t, and the row's horizontal fov becomes `fov`. The engine's projection is the pinhole
with y down and z forward: pixel = (w/2 + zoom x/z, h/2 + zoom y/z) with zoom = (w/2) / tan(fov/2), the
scene's z = 0 plane at pixel scale for the default camera. Its lens model is the post warp of
three_post.wgsl: an output pixel at normalised p (vertical half-height 0.5) samples the source at
p (1 + k1 |p|^2), so positive k1 is barrel. A planar track anchors an `object3D` on the tracked plane, and a
shadow catcher there darkens the plate by SREP 41's rule (black with alpha = opacity (1 - lit_sh / lit_un)).
The plumb-line method estimates k1 from the straight lines of a plate, and undistorting the tracked points
before the pose fit removes the lens error from the solve.

Every function is pure Python on lists and tuples; the module reuses the computed-tracking reference for the
rotation conventions, the pinhole and the pose fit. `main()` prints the numeric table of the draft.
"""
import importlib.util
import math
import os

DEFAULT_PIXELS_PER_METER = 100.0
REPROJECTION_TOLERANCE = 0.5     # px, the LA3 test of SREP 12
K1_TOLERANCE = 0.001             # the plumb-line estimate against the truth
MAX_K1 = 0.5                     # |k1| of a matched lens (PI4)
LENS_MODES = ("none", "plumb")
MIN_PLUMB_LINES = 2
MIN_LINE_POINTS = 5
LUMA = (0.2126, 0.7152, 0.0722)  # three.wgsl luma()
NEWTON_ITERATIONS = 32
GOLDEN_ITERATIONS = 80
GRID_SAMPLES = 41
CAMERA_KEYS = ("x", "y", "z", "yaw", "pitch", "roll", "fov")
ROW_KEYS = ("tx", "ty", "tz", "rx", "ry", "rz", "fov")
OBJECT_KEYS = ("x", "y", "z", "rotation", "rotationY", "rotationX")
PLANE_NORMAL = (0.0, 0.0, -1.0)  # the tracked target faces the camera, which looks along +z


class PlateError(ValueError):
    """A plate-integration rule or input is violated."""


_TRACKING = None


def tracking():
    """The computed-tracking reference module, loaded by path (it is not a package)."""
    global _TRACKING
    if _TRACKING is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "computed_tracking_reference.py")
        spec = importlib.util.spec_from_file_location("computed_tracking_reference", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TRACKING = mod
    return _TRACKING


# ------------------------------------------------------------------------------------ rotations


def rotation_x(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def rotation_y(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]


def rotation_z(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def apply(M, v):
    return tuple(sum(M[i][k] * v[k] for k in range(3)) for i in range(3))


def engine_orientation(yaw, pitch, roll):
    """The engine's camera and light orientation: Ry(yaw) Rx(pitch) Rz(roll) (render_three.rs pose3)."""
    ct = tracking()
    return ct.matmul(rotation_y(yaw), ct.matmul(rotation_x(pitch), rotation_z(roll)))


def engine_euler(M):
    """(yaw, pitch, roll) in degrees with M = Ry(yaw) Rx(pitch) Rz(roll); roll is 0 at the gimbal lock."""
    sp = max(-1.0, min(1.0, -M[1][2]))
    pitch = math.asin(sp)
    if abs(math.cos(pitch)) > 1e-9:
        yaw = math.atan2(M[0][2], M[2][2])
        roll = math.atan2(M[1][0], M[1][1])
    else:
        yaw = math.atan2(-M[2][0], M[0][0])
        roll = 0.0
    return (math.degrees(yaw), math.degrees(pitch), math.degrees(roll))


# ------------------------------------------------------------------------------------ the engine's camera


def engine_zoom(width, fov):
    """The focal length in pixels of a horizontal field of view over a width (sr-3d camera::zoom)."""
    if not 0.0 < fov < 180.0:
        raise PlateError("fov lies strictly between 0 and 180 degrees")
    return (width / 2.0) / math.tan(math.radians(fov) / 2.0)


def default_camera(width, height, fov=60.0):
    """The engine's default camera: at the frame centre, zoom in front of the z = 0 plane, looking along +z."""
    return {"x": width / 2.0, "y": height / 2.0, "z": -engine_zoom(width, fov), "yaw": 0.0, "pitch": 0.0,
            "roll": 0.0, "fov": fov}


def engine_view(camera):
    """The camera's frame in the world: (M, eye), M the rotation of cam_to_world."""
    M = engine_orientation(camera.get("yaw", 0.0), camera.get("pitch", 0.0), camera.get("roll", 0.0))
    eye = (camera.get("x", 0.0), camera.get("y", 0.0), camera.get("z", 0.0))
    return M, eye


def engine_project(camera, point, width, height):
    """The output pixel of a scene point: view (the inverse pose), the pinhole with y down and z forward, then
    the lens warp when `lensDistortion` is set."""
    M, eye = engine_view(camera)
    d = (point[0] - eye[0], point[1] - eye[1], point[2] - eye[2])
    local = apply(tracking().transpose(M), d)
    if local[2] <= 1e-12:
        raise PlateError("the point is behind the camera")
    zoom = engine_zoom(width, camera.get("fov", 60.0))
    pixel = (width / 2.0 + zoom * local[0] / local[2], height / 2.0 + zoom * local[1] / local[2])
    k1 = camera.get("lensDistortion", 0.0)
    if k1:
        return distort_pixel(pixel, k1, width, height)
    return pixel


def camera_from_row(row, track_scale):
    """The engine camera of a camera-track row: eye = -scale R^T t, (yaw, pitch, roll) of R^T, the row's fov."""
    if not track_scale > 0.0:
        raise PlateError("PI2: trackScale is positive")
    missing = [k for k in ROW_KEYS if k not in row]
    if missing:
        raise PlateError(f"the camera row lacks {', '.join(missing)}")
    ct = tracking()
    R = ct.euler_to_rotation(row["rx"], row["ry"], row["rz"])
    M = ct.transpose(R)
    t = (row["tx"], row["ty"], row["tz"])
    eye = apply(M, t)
    yaw, pitch, roll = engine_euler(M)
    return {"x": -track_scale * eye[0], "y": -track_scale * eye[1], "z": -track_scale * eye[2],
            "yaw": yaw, "pitch": pitch, "roll": roll, "fov": float(row["fov"])}


def camera_tuple(camera):
    return tuple(camera[k] for k in CAMERA_KEYS)


def camera_at(rows, frame, track_scale):
    """The camera at a frame: the row held from the last row at or before the frame (the first row before it)."""
    if not rows:
        raise PlateError("the camera track has no rows")
    ordered = sorted(rows, key=lambda r: r["frame"])
    held = ordered[0]
    for r in ordered:
        if r["frame"] <= frame:
            held = r
    return camera_from_row(held, track_scale)


def frame_zero_row():
    """The frame-0 row of the computed-tracking draft's synthetic camera."""
    ct = tracking()
    R, t = ct.camera_pose(ct.camera_motion(), 0)
    rx, ry, rz = ct.rotation_to_euler(R)
    return {"frame": 0, "tx": t[0], "ty": t[1], "tz": t[2], "rx": rx, "ry": ry, "rz": rz, "fov": 60.0}


def pinhole_agreement():
    """The worst distance between the tracking draft's pinhole and the engine projection over the synthetic
    camera's eight frames and the target's corners."""
    ct = tracking()
    motion = ct.camera_motion()
    K = ct.intrinsics(96, 72, 60.0)
    corners = ct.planar_target_points(0.48, 0.36)
    worst = 0.0
    for frame in range(8):
        R, t = ct.camera_pose(motion, frame)
        rx, ry, rz = ct.rotation_to_euler(R)
        cam = camera_from_row({"frame": frame, "tx": t[0], "ty": t[1], "tz": t[2], "rx": rx, "ry": ry, "rz": rz,
                               "fov": 60.0}, DEFAULT_PIXELS_PER_METER)
        for X, Y in corners:
            a = ct.project(K, R, t, (X, Y, 0.0))
            b = engine_project(cam, (DEFAULT_PIXELS_PER_METER * X, DEFAULT_PIXELS_PER_METER * Y, 0.0), 96, 72)
            worst = max(worst, math.dist(a, b))
    return worst


_SOLVED = None
PLATE_CORNERS = ((24.0, 18.0), (72.0, 18.0), (72.0, 54.0), (24.0, 54.0))


def solved_track():
    """The synthetic plate of the tracking draft's camera rows, its truth homographies and the solved track."""
    global _SOLVED
    if _SOLVED is None:
        ct = tracking()
        frames, truth = ct.synthetic_plate(96, 72, ct.camera_motion(), frames=8, seed=9)
        track = ct.solve_camera(frames, {"kind": "camera", "target": "planar", "corners": PLATE_CORNERS,
                                         "width": 0.48, "height": 0.36, "fov": 60.0, "grid": 4, "window": 11,
                                         "search": 6})
        _SOLVED = (frames, truth, track)
    return _SOLVED


def reprojection_run(track_scale=DEFAULT_PIXELS_PER_METER):
    """LA3's test: the solved camera, written as the engine camera, re-projects the target's corners (scene
    points anchored on the plane) onto their plate positions; the worst distance in pixels."""
    ct = tracking()
    _frames, truth, track = solved_track()
    target = ct.planar_target_points(0.48, 0.36)
    worst = 0.0
    for row, Hk in zip(track, truth):
        cam = camera_from_row(row, track_scale)
        for (X, Y), c in zip(target, PLATE_CORNERS):
            seen = ct.apply_homography(Hk, c)
            got = engine_project(cam, (track_scale * X, track_scale * Y, 0.0), 96, 72)
            worst = max(worst, math.dist(seen, got))
    return worst


# ------------------------------------------------------------------------------------ the lens


def normalised(pixel, width, height):
    """three_post.wgsl: p = (uv - 0.5) * (w / h, 1); the vertical half-height is 0.5."""
    asp = width / height
    return ((pixel[0] / width - 0.5) * asp, pixel[1] / height - 0.5)


def pixel_of(p, width, height):
    asp = width / height
    return ((p[0] / asp + 0.5) * width, (p[1] + 0.5) * height)


def source_of(p, k1):
    """Where an output pixel at normalised p samples the undistorted source: p (1 + k1 |p|^2)."""
    f = 1.0 + k1 * (p[0] * p[0] + p[1] * p[1])
    return (p[0] * f, p[1] * f)


def output_of(p_source, k1):
    """The output pixel that samples the source point: the inverse of source_of, by Newton on the radius."""
    rs = math.hypot(p_source[0], p_source[1])
    if rs == 0.0 or k1 == 0.0:
        return (p_source[0], p_source[1])
    fold = None
    if k1 < 0.0:
        fold = math.sqrt(-1.0 / (3.0 * k1))
        if rs > fold * (1.0 + k1 * fold * fold) + 1e-12:
            raise PlateError("the source point lies beyond the fold of the lens")
    r = min(rs, fold) if fold is not None else rs
    for _ in range(NEWTON_ITERATIONS):
        g = k1 * r ** 3 + r - rs
        if abs(g) < 1e-13:
            break
        dg = 3.0 * k1 * r * r + 1.0
        if dg <= 1e-12:
            dg = 1e-12
        r -= g / dg
        if fold is not None:
            r = max(0.0, min(r, fold))
        else:
            r = max(0.0, r)
    else:
        if abs(k1 * r ** 3 + r - rs) > 1e-9:
            raise PlateError("the lens inverse did not converge")
    return (p_source[0] * r / rs, p_source[1] * r / rs)


def distort_pixel(pixel, k1, width, height):
    """Where a source (pinhole) pixel appears in the output."""
    return pixel_of(output_of(normalised(pixel, width, height), k1), width, height)


def undistort_pixel(pixel, k1, width, height):
    """The source (pinhole) pixel an output pixel shows."""
    return pixel_of(source_of(normalised(pixel, width, height), k1), width, height)


def line_residual(points):
    """The root mean square distance of points to their total-least-squares line."""
    n = len(points)
    if n < 2:
        raise PlateError("a line needs at least two points")
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points) / n
    syy = sum((p[1] - my) ** 2 for p in points) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points) / n
    half = (sxx + syy) / 2.0
    det = sxx * syy - sxy * sxy
    smallest = half - math.sqrt(max(half * half - det, 0.0))
    return math.sqrt(max(smallest, 0.0))


def synthetic_lines(width, height, k1, rows=4, cols=4, samples=9):
    """The output positions of a grid of straight lines seen through a lens with k1."""
    lines = []
    for i in range(rows):
        y = height * (i + 1) / (rows + 1)
        lines.append([distort_pixel((width * j / (samples - 1), y), k1, width, height) for j in range(samples)])
    for i in range(cols):
        x = width * (i + 1) / (cols + 1)
        lines.append([distort_pixel((x, height * j / (samples - 1)), k1, width, height) for j in range(samples)])
    return lines


def plumb_line_k1(lines, width, height, bound=MAX_K1):
    """The k1 that straightens the lines: the plumb-line cost (sum of squared line residuals of the undistorted
    points) sampled on a grid over [-bound, bound], then a golden-section search in the best bracket."""
    if len(lines) < MIN_PLUMB_LINES:
        raise PlateError(f"the plumb-line fit needs at least {MIN_PLUMB_LINES} lines")
    if any(len(l) < MIN_LINE_POINTS for l in lines):
        raise PlateError(f"every plumb line needs at least {MIN_LINE_POINTS} points")
    norm = [[normalised(p, width, height) for p in l] for l in lines]

    def cost(k):
        return sum(line_residual([source_of(p, k) for p in l]) ** 2 for l in norm)

    grid = [-bound + 2.0 * bound * i / (GRID_SAMPLES - 1) for i in range(GRID_SAMPLES)]
    costs = [cost(k) for k in grid]
    best = min(range(GRID_SAMPLES), key=lambda i: costs[i])
    a = grid[max(best - 1, 0)]
    b = grid[min(best + 1, GRID_SAMPLES - 1)]
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc, fd = cost(c), cost(d)
    for _ in range(GOLDEN_ITERATIONS):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = cost(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = cost(d)
    return (a + b) / 2.0


LENS_CORNERS = ((8.0, 6.0), (88.0, 6.0), (88.0, 66.0), (8.0, 66.0))


def lens_run(k1, correct=True, grid=4):
    """A 0.8 x 0.6 m target seen through a lens with k1 over the synthetic camera's eight frames: the plate
    shows its grid points distorted; the pose is fitted from the points undistorted with k1 (correct) or as
    seen (not), and the engine camera, with lensDistortion k1 when corrected, re-projects the points; the
    worst distance to the plate positions in pixels."""
    ct = tracking()
    motion = dict(ct.camera_motion(), width=0.8, height=0.6)
    K = ct.intrinsics(96, 72, 60.0)
    target = [(-0.4 + 0.8 * i / (grid - 1), -0.3 + 0.6 * j / (grid - 1)) for j in range(grid) for i in range(grid)]
    world = [(X, Y, 0.0) for X, Y in target]
    worst = 0.0
    for frame in range(8):
        R, t = ct.camera_pose(motion, frame)
        seen = [distort_pixel(ct.project(K, R, t, X), k1, 96, 72) for X in world]
        fit = [undistort_pixel(p, k1, 96, 72) for p in seen] if correct else seen
        pose = ct.refine_pose(ct.planar_pose(ct.fit_homography(target, fit), K), K, world, fit)
        cam = camera_from_row(ct._camera_entry(frame, pose, 60.0), DEFAULT_PIXELS_PER_METER)
        cam["lensDistortion"] = k1 if correct else 0.0
        for X, s in zip(world, seen):
            got = engine_project(cam, (DEFAULT_PIXELS_PER_METER * X[0], DEFAULT_PIXELS_PER_METER * X[1], 0.0), 96, 72)
            worst = max(worst, math.dist(got, s))
    return worst


# ------------------------------------------------------------------------------------ the shadow catcher


def luma(rgb):
    return LUMA[0] * rgb[0] + LUMA[1] * rgb[1] + LUMA[2] * rgb[2]


def catcher_alpha(lit_shadowed, lit_unshadowed, opacity):
    """SREP 41 as three.wgsl draws it: black with alpha = opacity (1 - lit_sh / lit_un); nothing without light."""
    kept = lit_shadowed / lit_unshadowed if lit_unshadowed > 1e-6 else 1.0
    return max(0.0, min(1.0, opacity * (1.0 - kept)))


def composite_catcher(plate, alpha):
    return tuple(c * (1.0 - alpha) for c in plate)


def unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n == 0.0:
        raise PlateError("a zero vector has no direction")
    return (v[0] / n, v[1] / n, v[2] / n)


def sphere_shadow(point, sphere, direction):
    """Whether a sphere (centre, radius) blocks the light travelling along `direction` from reaching a point
    of the tracked plane z = 0, which faces -z; light from behind the plane never reaches it."""
    d = unit(direction)
    if d[2] <= 0.0:
        return False
    centre, radius = sphere
    back = (-d[0], -d[1], -d[2])
    oc = (point[0] - centre[0], point[1] - centre[1], point[2] - centre[2])
    b = oc[0] * back[0] + oc[1] * back[1] + oc[2] * back[2]
    cc = oc[0] * oc[0] + oc[1] * oc[1] + oc[2] * oc[2] - radius * radius
    disc = b * b - cc
    if disc < 0.0:
        return False
    s = -b - math.sqrt(disc)
    if s > 1e-9:
        return True
    return -b + math.sqrt(disc) > 1e-9


def shadow_alpha_at(point, scene):
    """The catcher's alpha at a plane point: directional lights arrive at the cosine of their angle to the
    plane's normal, each blocked or not by the sphere."""
    lit_un = 0.0
    lit_sh = 0.0
    for light in scene.get("lights", ()):
        d = unit(light["direction"])
        cosine = max(0.0, -(PLANE_NORMAL[0] * d[0] + PLANE_NORMAL[1] * d[1] + PLANE_NORMAL[2] * d[2]))
        contribution = luma(light.get("colour", (1.0, 1.0, 1.0))) * cosine
        lit_un += contribution
        if not sphere_shadow(point, scene["sphere"], d):
            lit_sh += contribution
    return catcher_alpha(lit_sh, lit_un, scene.get("opacity", 1.0))


def one_light_scene():
    return {"sphere": ((0.0, 0.0, -0.2), 0.1), "lights": [{"direction": (0.0, 0.0, 1.0), "colour": (1.0, 1.0, 1.0)}],
            "opacity": 1.0}


def two_light_scene():
    return {"sphere": ((0.0, 0.0, -0.2), 0.1),
            "lights": [{"direction": (0.0, 0.0, 1.0), "colour": (1.0, 1.0, 1.0)},
                       {"direction": unit((1.0, 0.0, 1.0)), "colour": (1.0, 1.0, 1.0)}],
            "opacity": 1.0}


def plane_point(camera, pixel, width, height, track_scale=DEFAULT_PIXELS_PER_METER):
    """The point of the tracked plane z = 0 (track units) an output pixel shows, through the camera's lens."""
    k1 = camera.get("lensDistortion", 0.0)
    src = undistort_pixel(pixel, k1, width, height) if k1 else pixel
    zoom = engine_zoom(width, camera.get("fov", 60.0))
    M, eye = engine_view(camera)
    d = apply(M, ((src[0] - width / 2.0) / zoom, (src[1] - height / 2.0) / zoom, 1.0))
    if abs(d[2]) < 1e-12:
        raise PlateError("the ray is parallel to the plane")
    s = -eye[2] / d[2]
    if s <= 0.0:
        raise PlateError("the plane is behind the camera")
    return tuple((eye[i] + s * d[i]) / track_scale for i in range(3))


def catcher_plate(camera, scene, width, height, plate, track_scale=DEFAULT_PIXELS_PER_METER):
    """The plate (a flat colour) composited with a shadow catcher on the tracked plane through the camera."""
    out = []
    for j in range(height):
        row = []
        for i in range(width):
            p = plane_point(camera, (i + 0.5, j + 0.5), width, height, track_scale)
            row.append(composite_catcher(plate, shadow_alpha_at(p, scene)))
        out.append(row)
    return out


def footprint_radius(image, plate):
    """The radius of the disc whose area equals the pixels the catcher darkened."""
    count = sum(1 for row in image for px in row if px != tuple(plate))
    return math.sqrt(count / math.pi)


# ------------------------------------------------------------------------------------ anchoring


def object_from_pose(R, position):
    """The engine's object attributes of a world pose: local3 is T(x, y, z) Rz(rotation) Ry(rotationY)
    Rx(rotationX) S, the tracking draft's Rz Ry Rx."""
    rx, ry, rz = tracking().rotation_to_euler(R)
    return {"x": position[0], "y": position[1], "z": position[2], "rotation": rz, "rotationY": ry, "rotationX": rx}


def anchor_from_plane(camera, plane_pose, track_scale):
    """The anchored object's pose: the plane's frame (R_p, t_p) in camera coordinates, carried into the world
    by the camera's frame (M, eye): (M R_p, eye + scale M t_p)."""
    if not track_scale > 0.0:
        raise PlateError("PI2: trackScale is positive")
    ct = tracking()
    M, eye = engine_view(camera)
    Rw = ct.matmul(M, plane_pose["R"])
    t = apply(M, plane_pose["t"])
    return object_from_pose(Rw, tuple(eye[i] + track_scale * t[i] for i in range(3)))


def anchor_drift(track_scale=DEFAULT_PIXELS_PER_METER):
    """How far the plane anchored through the solved camera sits from the world origin where the truth
    puts it: the worst position (scene units) and rotation (degrees) over the eight frames."""
    ct = tracking()
    _frames, _truth, track = solved_track()
    motion = ct.camera_motion()
    position = 0.0
    degrees = 0.0
    for row in track:
        R, t = ct.camera_pose(motion, row["frame"])
        obj = anchor_from_plane(camera_from_row(row, track_scale), {"R": R, "t": t}, track_scale)
        position = max(position, math.sqrt(obj["x"] ** 2 + obj["y"] ** 2 + obj["z"] ** 2))
        Rw = ct.euler_to_rotation(obj["rotationX"], obj["rotationY"], obj["rotation"])
        trace = Rw[0][0] + Rw[1][1] + Rw[2][2]
        degrees = max(degrees, math.degrees(math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))))
    return {"position": position, "degrees": degrees}


# ------------------------------------------------------------------------------------ validation


def _version(doc):
    try:
        major, minor = (int(p) for p in str(doc.get("version", "1.8")).split(".")[:2])
    except ValueError as e:
        raise PlateError(f"the version is major.minor: {e}") from e
    return (major, minor)


def validate_document(doc):
    """Rules PI1-PI4 and V17 on a dict {version, tracks: {id: kind}, cameras, objects, solves}; raises
    PlateError, returns the warnings (ignored attributes)."""
    tracks = doc.get("tracks", {})
    warnings = []
    uses_new = False
    for cam in doc.get("cameras", ()):
        cid = cam.get("id", "?")
        if "track" in cam or "trackScale" in cam:
            uses_new = True
        if "track" in cam:
            kind = tracks.get(cam["track"])
            if kind is None:
                raise PlateError(f"PI1: camera {cid} tracks {cam['track']}, which is not a trackData")
            if kind != "camera":
                raise PlateError(f"PI1: camera {cid} tracks {cam['track']} of kind {kind}; a camera track is required")
            for key in CAMERA_KEYS:
                if key in cam:
                    warnings.append(f"PI1: camera {cid} has track and {key}; {key} is ignored")
        if "trackScale" in cam and not cam["trackScale"] > 0.0:
            raise PlateError(f"PI2: camera {cid} has trackScale {cam['trackScale']}; it is positive")
        if abs(cam.get("lensDistortion", 0.0)) > MAX_K1:
            raise PlateError(f"PI4: camera {cid} has lensDistortion beyond {MAX_K1}")
    for obj in doc.get("objects", ()):
        oid = obj.get("id", "?")
        if "anchor" in obj or "anchorName" in obj:
            uses_new = True
        if "anchor" in obj:
            kind = tracks.get(obj["anchor"])
            if kind is None:
                raise PlateError(f"PI3: object {oid} anchors to {obj['anchor']}, which is not a trackData")
            if kind != "planar":
                raise PlateError(f"PI3: object {oid} anchors to {obj['anchor']} of kind {kind}; a planar track is required")
    for solve in doc.get("solves", ()):
        if "lens" in solve:
            uses_new = True
            if solve["lens"] not in LENS_MODES:
                raise PlateError(f"PI4: lens is one of {', '.join(LENS_MODES)}, not {solve['lens']}")
            if solve.get("kind") != "camera":
                raise PlateError("PI4: lens applies to camera solves only")
    if uses_new and _version(doc) < (1, 8):
        raise PlateError("V17: track, trackScale, anchor, anchorName and lens require version 1.8")
    return warnings


# ------------------------------------------------------------------------------------ the table


TABLE = (
    ("the focal length in pixels", "engine_zoom(96, 60.0)", "83.1384"),
    ("yaw, pitch and roll round trip", "engine_euler(engine_orientation(20.0, -10.0, 5.0))", "(20, -10, 5)"),
    ("yaw 90 turns +z to +x", "apply(engine_orientation(90.0, 0.0, 0.0), (0.0, 0.0, 1.0))", "(1, 0, 0)"),
    ("pitch 90 turns +z to -y (up)", "apply(engine_orientation(0.0, 90.0, 0.0), (0.0, 0.0, 1.0))", "(0, -1, 0)"),
    ("the default camera draws z = 0 at pixel scale", "engine_project(default_camera(96, 72), (96.0, 72.0, 0.0), 96, 72)", "(96, 72)"),
    ("the frame-0 row as the engine camera", "camera_tuple(camera_from_row(frame_zero_row(), 100.0))", "(0, 0, -83.1384, 0, 0, 0, 60)"),
    ("the target corner through it", "engine_project(camera_from_row(frame_zero_row(), 100.0), (-24.0, -18.0, 0.0), 96, 72)", "(24, 18)"),
    ("the engine projection equals the pinhole", "pinhole_agreement() < 1e-6", "True"),
    ("re-projection of the solved camera (px)", "reprojection_run()", "0.326918"),
    ("the anchored plane's drift (scene units)", "anchor_drift()['position']", "0.187955"),
    ("the anchored plane's drift (degrees)", "anchor_drift()['degrees']", "1.77685"),
    ("the normalised corner of the frame", "normalised((96.0, 0.0), 96, 72)", "(0.666667, -0.5)"),
    ("the shader's warp", "source_of((0.6, -0.5), 0.08)", "(0.62928, -0.5244)"),
    ("its inverse", "output_of((0.62928, -0.5244), 0.08)", "(0.6, -0.5)"),
    ("barrel pulls a pixel in", "distort_pixel((90.0, 10.0), 0.08, 96, 72)", "(88.5742, 10.8827)"),
    ("undistort round trip", "undistort_pixel(distort_pixel((90.0, 10.0), 0.08, 96, 72), 0.08, 96, 72)", "(90, 10)"),
    ("straight points have no residual", "line_residual([(0.0, 0.0), (1.0, 0.5), (2.0, 1.0), (3.0, 1.5), (4.0, 2.0)])", "0"),
    ("the bend of the synthetic grid (px)", "max(line_residual(l) for l in synthetic_lines(96, 72, 0.08))", "0.244266"),
    ("plumb-line k1, barrel", "plumb_line_k1(synthetic_lines(96, 72, 0.08), 96, 72)", "0.08"),
    ("plumb-line k1, pincushion", "plumb_line_k1(synthetic_lines(96, 72, -0.05), 96, 72)", "-0.05"),
    ("pose fit after undistortion (px)", "lens_run(0.15)", "0"),
    ("pose fit without undistortion (px)", "lens_run(0.15, correct=False)", "0.695566"),
    ("catcher alpha, the one light blocked", "catcher_alpha(0.0, 1.0, 1.0)", "1"),
    ("catcher alpha, half the light at opacity 0.8", "catcher_alpha(0.5, 1.0, 0.8)", "0.4"),
    ("catcher alpha without light", "catcher_alpha(0.0, 0.0, 1.0)", "0"),
    ("two lights, the vertical one blocked", "shadow_alpha_at((0.0, 0.0, 0.0), two_light_scene())", "0.585786"),
    ("outside the shadow", "shadow_alpha_at((0.5, 0.0, 0.0), two_light_scene())", "0"),
    ("the footprint's radius on the plate (px)", "footprint_radius(catcher_plate(camera_from_row(frame_zero_row(), 100.0), one_light_scene(), 96, 72, (0.5, 0.5, 0.5)), (0.5, 0.5, 0.5))", "10.0293"),
    ("luma of green", "luma((0.0, 1.0, 0.0))", "0.7152"),
    ("the re-projection tolerance (px)", "REPROJECTION_TOLERANCE", "0.5"),
)


def scope():
    s = dict(globals())
    s["math"] = math
    return s


def _same(a, b, rel=5e-4, abs_tol=5e-4):
    return tracking()._same(a, b, rel, abs_tol)


def _fmt(v):
    return tracking()._fmt(v)


def main():
    s = scope()
    for name, expr, _expected in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
