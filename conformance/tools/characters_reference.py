#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add stylised characters" (srep/srep-0000-characters.md), CL2
of SREP 12: area-preserving squash and stretch in 2D and volume-preserving squash and stretch in 3D, the
floor contact under squash, velocity-driven stretch, eyes (a pupil that looks at a target within its travel,
a lid, seeded blinks) in 2D and 3D, and a bounce rig. Standard library only. `main()` prints the SREP's
numeric table.

The D24 hash functions are copied from random_streams_reference.py so that this module stands alone.
"""
import math

MAX_STRETCH = 100.0
EPS = 1e-9
AXES_2D = ("x", "y")
AXES_3D = ("x", "y", "z")

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


# --- squash and stretch -----------------------------------------------------------------------------------------

def _factor(kind, amount):
    """The scale along the axis: 1 - amount for squash (amount in [0, 1)), 1 + amount for stretch."""
    if kind == "squash":
        if not 0.0 <= amount < 1.0:
            raise ValueError("a squash amount is in [0, 1)")
        return 1.0 - amount
    if kind == "stretch":
        if not 0.0 <= amount <= MAX_STRETCH:
            raise ValueError(f"a stretch amount is in [0, {MAX_STRETCH}]")
        return 1.0 + amount
    raise ValueError(f"unknown deformation {kind!r}")


def scales_2d(kind, amount, axis):
    """(sx, sy) with the factor along the axis and its reciprocal across: the area is kept."""
    if axis not in AXES_2D:
        raise ValueError("a 2D axis is x or y")
    s = _factor(kind, amount)
    return (1.0 / s, s) if axis == "y" else (s, 1.0 / s)


def scales_3d(kind, amount, axis):
    """(sx, sy, sz) with the factor along the axis and 1 / sqrt(s) across each other axis: the volume is kept."""
    if axis not in AXES_3D:
        raise ValueError("a 3D axis is x, y or z")
    s = _factor(kind, amount)
    across = 1.0 / math.sqrt(s)
    return tuple(s if a == axis else across for a in AXES_3D)


def deform_points(points, kind, amount, axis, center):
    """Each 2D point scaled about the centre by scales_2d."""
    sx, sy = scales_2d(kind, amount, axis)
    return tuple((center[0] + (p[0] - center[0]) * sx, center[1] + (p[1] - center[1]) * sy) for p in points)


def deform_vertices(vertices, kind, amount, axis, center):
    """Each 3D vertex scaled about the centre by scales_3d."""
    s = scales_3d(kind, amount, axis)
    return tuple(tuple(c + (v[k] - c) * s[k] for k, c in enumerate(center)) for v in vertices)


def squashed_sdf(sdf, kind, amount, axis, center):
    """The signed distance field of the deformed solid: the field sampled at the inverse-mapped point."""
    s = scales_3d(kind, amount, axis)
    return lambda p: sdf(tuple(c + (p[k] - c) / s[k] for k, c in enumerate(center)))


def polygon_area(points):
    """The absolute shoelace area of a simple polygon."""
    if len(points) < 3:
        raise ValueError("a polygon has at least three points")
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def mesh_volume(vertices, faces):
    """The signed volume of a closed triangle mesh by the divergence theorem (positive for outward winding)."""
    total = 0.0
    for face in faces:
        if len(face) != 3 or any(not 0 <= i < len(vertices) for i in face):
            raise ValueError("faces are triangles of vertex indices")
        a, b, c = (vertices[i] for i in face)
        cross = (b[1] * c[2] - b[2] * c[1], b[2] * c[0] - b[0] * c[2], b[0] * c[1] - b[1] * c[0])
        total += a[0] * cross[0] + a[1] * cross[1] + a[2] * cross[2]
    return total / 6.0


def squash_on_floor(points, amount, floor_y):
    """A squash along y about (centroid x, floor): the points on the floor stay on it."""
    cx = sum(p[0] for p in points) / len(points)
    return deform_points(points, "squash", amount, "y", (cx, floor_y))


# --- velocity ---------------------------------------------------------------------------------------------------

def velocity(pos, t, dt, start=0.0):
    """The backward difference (pos(t) - pos(t - dt)) / dt, or zero when t - dt is before the start."""
    if not dt > 0.0:
        raise ValueError("dt is positive")
    if t - dt < start - EPS:
        return (0.0, 0.0)
    a = pos(t - dt)
    b = pos(t)
    return ((b[0] - a[0]) / dt, (b[1] - a[1]) / dt)


def velocity_stretch(v, gain, max_amount):
    """(amount, angle in degrees) of a stretch along the velocity: amount = min(max, gain * |v|)."""
    if gain < 0.0 or max_amount < 0.0:
        raise ValueError("gain and the amount are not negative")
    speed = math.hypot(v[0], v[1])
    if speed == 0.0:
        return (0.0, 0.0)
    return (min(max_amount, gain * speed), math.degrees(math.atan2(v[1], v[0])))


def stretch_along(points, amount, angle, center):
    """Points rotated so the angle lies on x, stretched along x (area kept), and rotated back."""
    s = _factor("stretch", amount)
    if amount == 0.0:
        return tuple(tuple(float(c) for c in p) for p in points)
    a = math.radians(angle)
    c, sn = math.cos(a), math.sin(a)
    out = []
    for p in points:
        dx, dy = p[0] - center[0], p[1] - center[1]
        u = dx * c + dy * sn
        w = -dx * sn + dy * c
        u, w = u * s, w / s
        out.append((center[0] + u * c - w * sn, center[1] + u * sn + w * c))
    return tuple(out)


# --- eyes -------------------------------------------------------------------------------------------------------

def _check_eye(radius, pupil, travel):
    if not 0.0 < pupil < radius:
        raise ValueError("the pupil is smaller than the eye")
    if not 0.0 <= travel <= 1.0:
        raise ValueError("travel is in [0, 1]")


def pupil_offset(center, target, radius, pupil, travel=1.0):
    """The 2D pupil's offset from the eye's centre: toward the target, at most (radius - pupil) * travel."""
    _check_eye(radius, pupil, travel)
    if target is None:
        return (0.0, 0.0)
    dx, dy = target[0] - center[0], target[1] - center[1]
    d = math.hypot(dx, dy)
    if d == 0.0:
        return (0.0, 0.0)
    limit = (radius - pupil) * travel
    if d <= limit:
        return (dx, dy)
    return (dx / d * limit, dy / d * limit)


def pupil_center_3d(center, radius, pupil, target, travel=1.0, forward=(0.0, 0.0, 1.0)):
    """The 3D pupil's centre: radius - pupil / 2 from the eye's centre along the gaze, the gaze being the
    direction to the target turned back toward `forward` to at most travel * 90 degrees from it."""
    _check_eye(radius, pupil, travel)
    f = _unit3(forward)
    reach = radius - pupil / 2.0
    if target is None:
        return tuple(c + f[k] * reach for k, c in enumerate(center))
    d = tuple(target[k] - center[k] for k in range(3))
    if not any(d):
        return tuple(c + f[k] * reach for k, c in enumerate(center))
    u = _unit3(d)
    limit = math.radians(travel * 90.0)
    cos_a = max(-1.0, min(1.0, sum(x * y for x, y in zip(u, f))))
    ang = math.acos(cos_a)
    if ang > limit + EPS:
        # the component of u across f, or nothing when u is parallel or anti-parallel to f
        across = tuple(u[k] - cos_a * f[k] for k in range(3))
        n = math.sqrt(sum(x * x for x in across))
        if n < EPS:
            u = f
        else:
            across = tuple(x / n for x in across)
            u = tuple(math.cos(limit) * f[k] + math.sin(limit) * across[k] for k in range(3))
    return tuple(c + u[k] * reach for k, c in enumerate(center))


def _unit3(v):
    n = math.sqrt(sum(x * x for x in v))
    if not n > 0.0:
        raise ValueError("a zero vector")
    return tuple(x / n for x in v)


def lid_line(center_y, radius, open_):
    """The lid's lower edge (y down): the top of the eye plus (1 - open) of its height."""
    if not 0.0 <= open_ <= 1.0:
        raise ValueError("open is in [0, 1]")
    return center_y - radius + (1.0 - open_) * 2.0 * radius


def visible_area(radius, open_):
    """The area of the eye below the lid: the circular segment of height open * 2 radius."""
    if not 0.0 <= open_ <= 1.0:
        raise ValueError("open is in [0, 1]")
    if open_ == 0.0:
        return 0.0
    h = open_ * 2.0 * radius
    return radius * radius * math.acos((radius - h) / radius) - (radius - h) * math.sqrt(2.0 * radius * h - h * h)


def blink_start(k, period, duration, seed, start=0.0):
    """Blink k begins at start + k * period + U(seed, 0, k) * (period - duration)."""
    if k < 0:
        raise ValueError("blinks count from 0")
    if not period > 0.0 or not 0.0 < duration < period:
        raise ValueError("0 < duration < period")
    return start + k * period + U(seed if seed is not None else 0, 0, k) * (period - duration)


def blink_open(t, period, duration, seed, start=0.0):
    """1 outside blinks; within blink k, |2 u / duration - 1| for u the time since its start (1 -> 0 -> 1).
    Without a period or a seed the eye never blinks."""
    if period is None or seed is None:
        if period is not None and not period > 0.0:
            raise ValueError("period is positive")
        return 1.0
    if not period > 0.0 or not 0.0 < duration < period:
        raise ValueError("0 < duration < period")
    if t < start:
        return 1.0
    k = int(math.floor((t - start) / period))
    for kk in (k - 1, k):
        if kk < 0:
            continue
        b = blink_start(kk, period, duration, seed, start)
        if b <= t < b + duration:
            return abs(2.0 * (t - b) / duration - 1.0)
    return 1.0


def eye_open(open_, t, period, duration, seed, start=0.0):
    """The eye's opening at a frame: the authored open times the blink."""
    if not 0.0 <= open_ <= 1.0:
        raise ValueError("open is in [0, 1]")
    return open_ * blink_open(t, period, duration, seed, start)


# --- bounce -----------------------------------------------------------------------------------------------------

def hop(t, height, period):
    """(y, vy) of a parabolic hop repeating every period: y = 4 h u (1 - u), u = (t mod period) / period."""
    if not period > 0.0 or height < 0.0:
        raise ValueError("period is positive and the height not negative")
    if t < 0.0:
        raise ValueError("time is not negative")
    u = math.fmod(t, period) / period
    return (4.0 * height * u * (1.0 - u), 4.0 * height * (1.0 - 2.0 * u) / period)


def bounce_rig(t, height, period, contact, squash_max, gain, stretch_max):
    """Below contact * height the body squashes by squash_max * (1 - y / (contact * height)); above it the
    body stretches along the vertical by min(stretch_max, gain * |vy|)."""
    if not 0.0 < contact < 1.0:
        raise ValueError("contact is in (0, 1)")
    if not 0.0 <= squash_max < 1.0:
        raise ValueError("squash_max is in [0, 1)")
    y, vy = hop(t, height, period)
    floor = contact * height
    if y < floor:
        return {"y": y, "kind": "squash", "amount": squash_max * (1.0 - y / floor)}
    amount, _ = velocity_stretch((0.0, vy), gain, stretch_max)
    return {"y": y, "kind": "stretch", "amount": amount}


# --- table ------------------------------------------------------------------------------------------------------

def raises(f):
    try:
        f()
    except (ValueError, TypeError, IndexError, ZeroDivisionError, KeyError):
        return True
    return False


SQUARE = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
CUBE_V = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
          (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0))
CUBE_F = ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
          (2, 3, 7), (2, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5))
SPHERE = lambda p: math.sqrt(sum(c * c for c in p)) - 1.0   # noqa: E731

TABLE = [
    ("2D squash scales", 'scales_2d("squash", 0.5, "y")', "(2.0, 0.5)"),
    ("2D stretch scales", 'scales_2d("stretch", 1.0, "y")', "(0.5, 2.0)"),
    ("2D scales keep the area", 'round(scales_2d("squash", 0.3, "x")[0] * scales_2d("squash", 0.3, "x")[1], 12)', "1.0"),
    ("squashed square", 'deform_points(SQUARE, "squash", 0.5, "y", (1.0, 1.0))', "((-1.0, 0.5), (3.0, 0.5), (3.0, 1.5), (-1.0, 1.5))"),
    ("squashed square area", 'round(polygon_area(deform_points(SQUARE, "squash", 0.5, "y", (1.0, 1.0))), 12)', "4.0"),
    ("floor contact stays", "round(squash_on_floor(SQUARE, 0.4, 2.0)[2][1], 12)", "2.0"),
    ("floor squash area", "round(polygon_area(squash_on_floor(SQUARE, 0.4, 2.0)), 12)", "4.0"),
    ("3D squash scales", 'tuple(round(s, 12) for s in scales_3d("squash", 0.5, "y"))', "(1.414213562373, 0.5, 1.414213562373)"),
    ("3D stretch scales", 'tuple(round(s, 12) for s in scales_3d("stretch", 1.0, "z"))', "(0.707106781187, 0.707106781187, 2.0)"),
    ("cube volume", "round(mesh_volume(CUBE_V, CUBE_F), 12)", "1.0"),
    ("squashed cube volume", 'round(mesh_volume(deform_vertices(CUBE_V, "squash", 0.5, "y", (0.5, 0.5, 0.5)), CUBE_F), 12)', "1.0"),
    ("stretched cube volume", 'round(mesh_volume(deform_vertices(CUBE_V, "stretch", 2.0, "x", (0.5, 0.5, 0.5)), CUBE_F), 12)', "1.0"),
    ("squashed sphere pole", 'round(squashed_sdf(SPHERE, "squash", 0.5, "y", (0.0, 0.0, 0.0))((0.0, 0.5, 0.0)), 12)', "0.0"),
    ("squashed sphere equator", 'round(squashed_sdf(SPHERE, "squash", 0.5, "y", (0.0, 0.0, 0.0))((math.sqrt(2.0), 0.0, 0.0)), 12)', "0.0"),
    ("velocity by backward difference", "velocity(lambda t: (10.0 * t, 0.0), 1.0, 0.1)", "((10.0 - 9.0) / 0.1, 0.0)"),
    ("velocity at the start", "velocity(lambda t: (10.0 * t, 0.0), 0.05, 0.1)", "(0.0, 0.0)"),
    ("velocity stretch clamped", "tuple(round(v, 9) for v in velocity_stretch((30.0, 40.0), 0.01, 0.4))", "(0.4, 53.130102354)"),
    ("velocity stretch by gain", "tuple(round(v, 9) for v in velocity_stretch((30.0, 40.0), 0.001, 0.4))", "(0.05, 53.130102354)"),
    ("velocity stretch at rest", "velocity_stretch((0.0, 0.0), 0.01, 0.4)", "(0.0, 0.0)"),
    ("stretch along x", "tuple(tuple(round(c, 12) for c in p) for p in stretch_along(((1.0, 0.0), (0.0, 1.0)), 1.0, 0.0, (0.0, 0.0)))", "((2.0, 0.0), (0.0, 0.5))"),
    ("stretch along y", "tuple(tuple(round(c, 12) + 0.0 for c in p) for p in stretch_along(((1.0, 0.0), (0.0, 1.0)), 1.0, 90.0, (0.0, 0.0)))", "((0.5, 0.0), (0.0, 2.0))"),
    ("stretch at an angle keeps the area", "round(polygon_area(stretch_along(SQUARE, 0.5, 30.0, (1.0, 1.0))), 12)", "4.0"),
    ("pupil at its travel", "pupil_offset((0.0, 0.0), (100.0, 0.0), 10.0, 4.0)", "(6.0, 0.0)"),
    ("pupil within its travel", "pupil_offset((0.0, 0.0), (3.0, 4.0), 10.0, 4.0)", "(3.0, 4.0)"),
    ("pupil at half travel", "tuple(round(c, 12) for c in pupil_offset((0.0, 0.0), (30.0, 40.0), 10.0, 4.0, travel=0.5))", "(1.8, 2.4)"),
    ("pupil without a target", "pupil_offset((5.0, 5.0), None, 10.0, 4.0)", "(0.0, 0.0)"),
    ("3D pupil ahead", "pupil_center_3d((0.0, 0.0, 0.0), 10.0, 4.0, (0.0, 0.0, 50.0))", "(0.0, 0.0, 8.0)"),
    ("3D pupil at half travel", "tuple(round(c, 12) for c in pupil_center_3d((0.0, 0.0, 0.0), 10.0, 4.0, (100.0, 0.0, 0.0), travel=0.5))", "(5.656854249492, 0.0, 5.656854249492)"),
    ("3D pupil behind", "tuple(round(c, 12) for c in pupil_center_3d((0.0, 0.0, 0.0), 10.0, 4.0, (0.0, 0.0, -50.0)))", "(0.0, 0.0, 8.0)"),
    ("lid lines", "(lid_line(50.0, 10.0, 1.0), lid_line(50.0, 10.0, 0.5), lid_line(50.0, 10.0, 0.0))", "(40.0, 50.0, 60.0)"),
    ("visible area half open", "round(visible_area(10.0, 0.5), 9)", "round(50.0 * math.pi, 9)"),
    ("visible area quarter open", "round(visible_area(10.0, 0.25), 9)", "round(100.0 * math.acos(0.5) - 5.0 * math.sqrt(75.0), 9)"),
    ("blink 0 start", "round(blink_start(0, 4.0, 0.2, 3), 12)", "round(U(3, 0, 0) * 3.8, 12)"),
    ("blink closed at its middle", "round(blink_open(blink_start(0, 4.0, 0.2, 3) + 0.1, 4.0, 0.2, 3), 12)", "0.0"),
    ("blink half way", "round(blink_open(blink_start(0, 4.0, 0.2, 3) + 0.05, 4.0, 0.2, 3), 12)", "0.5"),
    ("blink over", "blink_open(blink_start(0, 4.0, 0.2, 3) + 0.2, 4.0, 0.2, 3)", "1.0"),
    ("no blink without a period", "blink_open(2.0, None, 0.2, 3)", "1.0"),
    ("eye open during a blink", "round(eye_open(0.6, blink_start(0, 4.0, 0.2, 3) + 0.05, 4.0, 0.2, 3), 12)", "0.3"),
    ("hop at a quarter period", "hop(0.5, 100.0, 2.0)", "(75.0, 100.0)"),
    ("bounce rig in contact", "bounce_rig(0.0, 100.0, 2.0, 0.2, 0.3, 0.002, 0.5)", "{'y': 0.0, 'kind': 'squash', 'amount': 0.3}"),
    ("bounce rig leaving the floor", "{k: round(v, 12) if k != 'kind' else v for k, v in bounce_rig(0.1, 100.0, 2.0, 0.2, 0.3, 0.002, 0.5).items()}", "{'y': 19.0, 'kind': 'squash', 'amount': 0.015}"),
    ("bounce rig in flight", "{k: round(v, 12) if k != 'kind' else v for k, v in bounce_rig(0.5, 100.0, 2.0, 0.2, 0.3, 0.002, 0.5).items()}", "{'y': 75.0, 'kind': 'stretch', 'amount': 0.2}"),
    ("bounce rig at the top", "bounce_rig(1.0, 100.0, 2.0, 0.2, 0.3, 0.002, 0.5)", "{'y': 100.0, 'kind': 'stretch', 'amount': 0.0}"),
    ("squash of 1 is an error", 'raises(lambda: scales_2d("squash", 1.0, "y"))', "True"),
    ("pupil larger than the eye", "raises(lambda: pupil_offset((0.0, 0.0), (1.0, 0.0), 4.0, 4.0))", "True"),
    ("blink longer than its period", "raises(lambda: blink_open(1.0, 1.0, 1.0, 3))", "True"),
]


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["__builtins__"] = {"round": round, "tuple": tuple, "len": len, "sorted": sorted, "min": min, "max": max,
                         "abs": abs, "range": range, "list": list, "set": set, "dict": dict, "True": True,
                         "False": False, "None": None, "any": any, "all": all, "int": int, "float": float,
                         "ValueError": ValueError}
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
