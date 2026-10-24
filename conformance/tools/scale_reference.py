#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add scale: powers of ten, depth resolution and a floating origin"
(srep/srep-0000-scale.md, SP5 of SREP 12).

Four things, each a pure function:

* depth mappings and their resolution: the engine's reversed depth d = n (f - z) / ((f - n) z) and the
  logarithmic depth d = ln(z / n) / ln(f / n), the distance gap a binary32 or a 24-bit fixed-point depth buffer
  resolves at a distance z, and whether a near/far pair resolves one part in 10^5 at every decade;
* geometric key interpolation v(u) = v0 (v1 / v0)^u, the powers-of-ten camera and its seek check;
* the scale bar: pixels per metre from pixelsPerMeter, the focal length in pixels and the measured depth, the
  largest 1, 2 or 5 x 10^k bar of the chosen unit that fits maxWidth pixels, and its label;
* the floating origin: the binary32 error of world coordinates against camera-relative coordinates rebased in
  binary64, and the extent at which binary32 world coordinates stop resolving a gap.

Running the module prints the data rows of the draft's numeric table.
"""
import math
import struct

DEPTH_MODES = ("reversed", "logarithmic")
BUFFER_KINDS = ("float", "fixed")
F32_MANTISSA = 23
FIXED_BITS = 24
MAX_DEPTH_RATIO = 1.0e20
RESOLUTION = 1.0e-5
STEPS = (1, 2, 5)
AU_M = 149597870700.0
LY_M = 9460730472580800.0
PC_M = 648000.0 / math.pi * AU_M
UNITS = (("m", 1.0), ("au", AU_M), ("ly", LY_M), ("pc", PC_M))
UNIT_MODES = ("auto", "si")
KEY_MODES = ("linear", "geometric")
SI_PREFIXES = {-12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}
PREFIX_RANGE = {"m": (-12, 9), "pc": (0, 9)}
MIN_BAR_M = 1.0e-12
SEEK_FRAMES = 960


class ScaleError(ValueError):
    """A value outside the draft's domain."""


# ------------------------------------------------------------------------------------ binary32 helpers


def f32(x):
    """x rounded to binary32 (round to nearest, ties to even)."""
    try:
        return struct.unpack("<f", struct.pack("<f", float(x)))[0]
    except OverflowError as exc:
        raise ScaleError(f"{x!r} overflows binary32") from exc


def f32_ulp(x):
    """The spacing of binary32 values at |x|: 2^(e - 23) for 2^e <= |x| < 2^(e + 1), the smallest subnormal at 0."""
    a = abs(float(x))
    if a == 0.0:
        return 2.0 ** -149
    e = math.floor(math.log2(a))
    if 2.0 ** (e + 1) <= a:
        e += 1
    elif 2.0 ** e > a:
        e -= 1
    return 2.0 ** max(e - F32_MANTISSA, -149)


def f32_error(x):
    """|f32(x) - x|."""
    return abs(f32(x) - float(x))


# ------------------------------------------------------------------------------------ depth mappings


def _planes(near, far):
    if not near > 0.0:
        raise ScaleError("near must be positive")
    if not far > near:
        raise ScaleError("far must exceed near")


def _mode(mode):
    if mode not in DEPTH_MODES:
        raise ScaleError(f"unknown depth mode {mode!r}")


def depth(z, near, far, mode="reversed"):
    """Depth-buffer value of a point at distance z: 1 at near and 0 at far (reversed), 0 at near and 1 at far
    (logarithmic)."""
    _planes(near, far)
    _mode(mode)
    if not near <= z <= far:
        raise ScaleError("z must lie between near and far")
    if mode == "reversed":
        return near * (far - z) / ((far - near) * z)
    return math.log(z / near) / math.log(far / near)


def distance(d, near, far, mode="reversed"):
    """The distance whose depth is d (the inverse of depth)."""
    _planes(near, far)
    _mode(mode)
    if not 0.0 <= d <= 1.0:
        raise ScaleError("depth must lie in [0, 1]")
    if mode == "reversed":
        return near * far / (d * (far - near) + near)
    return near * (far / near) ** d


def depth_slope(z, near, far, mode="reversed"):
    """|dd/dz| at distance z."""
    _planes(near, far)
    _mode(mode)
    if not near <= z <= far:
        raise ScaleError("z must lie between near and far")
    if mode == "reversed":
        return near * far / ((far - near) * z * z)
    return 1.0 / (z * math.log(far / near))


def depth_ulp(d, kind="float"):
    """The smallest change a depth buffer of the given kind stores at value d."""
    if kind not in BUFFER_KINDS:
        raise ScaleError(f"unknown buffer kind {kind!r}")
    if kind == "float":
        return f32_ulp(d)
    return 2.0 ** -FIXED_BITS


def resolvable_gap(z, near, far, mode="reversed", kind="float"):
    """The smallest distance gap at z that maps to distinct depth values."""
    return depth_ulp(depth(z, near, far, mode), kind) / depth_slope(z, near, far, mode)


def relative_resolution(z, near, far, mode="reversed", kind="float"):
    """resolvable_gap(z) / z."""
    return resolvable_gap(z, near, far, mode, kind) / z


def worst_resolution(near, far, mode="reversed", kind="float"):
    """The largest relative resolution over the decades near x 10^k (k = 0, 1, ...) up to far."""
    _planes(near, far)
    worst = 0.0
    k = 0
    while True:
        z = near * 10.0 ** k
        if z >= far:
            break
        worst = max(worst, relative_resolution(z, near, far, mode, kind))
        k += 1
    worst = max(worst, relative_resolution(far * (1.0 - 1.0e-9), near, far, mode, kind))
    return worst


def resolves(near, far, mode="reversed", kind="float"):
    """True when the buffer resolves one part in 10^5 at every sampled distance."""
    return worst_resolution(near, far, mode, kind) <= RESOLUTION


def depth_ratio_valid(near, far):
    """SC1: 0 < near < far and far / near <= 1e20."""
    return near > 0.0 and far > near and far / near <= MAX_DEPTH_RATIO


def validate_camera(near, far, mode="reversed"):
    """SC1 and the depth mode enumeration."""
    if not depth_ratio_valid(near, far):
        raise ScaleError("SC1: far / near must not exceed 1e20")
    _mode(mode)


# ------------------------------------------------------------------------------------ geometric keys


def validate_keys(v0, v1, mode="linear"):
    """SC2: a geometric key pair is non-zero and of one sign."""
    if mode not in KEY_MODES:
        raise ScaleError(f"unknown interpolation {mode!r}")
    if mode == "geometric" and (v0 == 0.0 or v1 == 0.0 or (v0 < 0.0) != (v1 < 0.0)):
        raise ScaleError("SC2: geometric keys must be non-zero and of one sign")


def geometric(v0, v1, u):
    """v0 (v1 / v0)^u for u in [0, 1]."""
    validate_keys(v0, v1, "geometric")
    if not 0.0 <= u <= 1.0:
        raise ScaleError("u must lie in [0, 1]")
    if u == 0.0:
        return float(v0)
    if u == 1.0:
        return float(v1)
    return v0 * (v1 / v0) ** u


def interpolate(v0, v1, u, mode="linear"):
    """A key pair interpolated linearly or geometrically."""
    validate_keys(v0, v1, mode)
    if mode == "linear":
        return v0 + (v1 - v0) * u
    return geometric(v0, v1, u)


def decade(v):
    """floor(log10 v)."""
    if not v > 0.0:
        raise ScaleError("decade needs a positive value")
    k = math.floor(math.log10(v))
    if 10.0 ** (k + 1) <= v:
        k += 1
    elif 10.0 ** k > v:
        k -= 1
    return k


def decades(v0, v1):
    """log10(v1 / v0)."""
    if not (v0 > 0.0 and v1 > 0.0):
        raise ScaleError("decades need positive values")
    return math.log10(v1 / v0)


def powers_of_ten(t, t0, t1, d0, d1):
    """The powers-of-ten camera distance at time t: geometric from d0 at t0 to d1 at t1, held outside."""
    if not t1 > t0:
        raise ScaleError("t1 must exceed t0")
    u = min(1.0, max(0.0, (t - t0) / (t1 - t0)))
    return geometric(d0, d1, u)


def time_at(d, t0, t1, d0, d1):
    """The time at which the powers-of-ten camera is at distance d."""
    if not t1 > t0:
        raise ScaleError("t1 must exceed t0")
    validate_keys(d0, d1, "geometric")
    u = math.log(d / d0) / math.log(d1 / d0)
    if not 0.0 <= u <= 1.0 + 1e-12:
        raise ScaleError("d lies outside [d0, d1]")
    return t0 + (t1 - t0) * min(u, 1.0)


def frame_distance(frame, fps, t0, t1, d0, d1):
    """powers_of_ten at frame / fps: a pure function of the frame number (the seek check)."""
    if frame < 0 or int(frame) != frame:
        raise ScaleError("frame must be a non-negative integer")
    if not fps > 0.0:
        raise ScaleError("fps must be positive")
    return powers_of_ten(frame / fps, t0, t1, d0, d1)


# ------------------------------------------------------------------------------------ the scale bar


def focal_pixels(fov_deg, width_px):
    """Focal length in pixels for the camera's horizontal field of view: (width / 2) / tan(fov / 2)."""
    if not 0.0 < fov_deg < 180.0:
        raise ScaleError("fov must lie in (0, 180) degrees")
    if not width_px > 0.0:
        raise ScaleError("width must be positive")
    return width_px / 2.0 / math.tan(math.radians(fov_deg) / 2.0)


def pixels_per_metre(depth_px, focal_px, ppm):
    """Screen pixels per metre at a depth of depth_px scene pixels: pixelsPerMeter x focal / depth."""
    if not depth_px > 0.0:
        raise ScaleError("depth must be positive")
    if not focal_px > 0.0:
        raise ScaleError("focal length must be positive")
    if not ppm > 0.0:
        raise ScaleError("pixelsPerMeter must be positive")
    return ppm * focal_px / depth_px


def pixels_per_metre_ortho(ortho_height_px, viewport_height_px, ppm):
    """Screen pixels per metre of an orthographic camera: pixelsPerMeter x viewport height / orthoHeight."""
    if not ortho_height_px > 0.0:
        raise ScaleError("orthoHeight must be positive")
    if not viewport_height_px > 0.0:
        raise ScaleError("viewport height must be positive")
    if not ppm > 0.0:
        raise ScaleError("pixelsPerMeter must be positive")
    return ppm * viewport_height_px / ortho_height_px


def nice_length(limit):
    """The largest 1, 2 or 5 x 10^k not above limit."""
    if not limit > 0.0:
        raise ScaleError("the limit must be positive")
    k = decade(limit)
    best = 10.0 ** k
    for s in STEPS:
        candidate = s * 10.0 ** k
        if candidate <= limit * (1.0 + 1e-12):
            best = candidate
    return best


def bar_unit(max_metres, units="auto"):
    """The largest of m, au, ly, pc not above max_metres; metres when units is "si"."""
    if units not in UNIT_MODES:
        raise ScaleError(f"unknown units {units!r}")
    chosen = UNITS[0]
    if units == "auto":
        for unit in UNITS:
            if unit[1] <= max_metres:
                chosen = unit
    return chosen


def _fmt_value(v):
    if float(v).is_integer() and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.6g}"


def scale_label(value, unit):
    """The bar's label: SI prefixes on metres and parsecs, plain values on au and ly."""
    if unit not in dict(UNITS):
        raise ScaleError(f"unknown unit {unit!r}")
    if unit not in PREFIX_RANGE:
        return f"{_fmt_value(value)} {unit}"
    lo, hi = PREFIX_RANGE[unit]
    e = 3 * math.floor(decade(value) / 3)
    e = min(hi, max(lo, e))
    return f"{_fmt_value(value / 10.0 ** e)} {SI_PREFIXES[e]}{unit}"


def scale_bar(px_per_m, max_width, units="auto"):
    """The largest 1, 2 or 5 x 10^k bar of the chosen unit that fits max_width pixels."""
    if not px_per_m > 0.0:
        raise ScaleError("pixels per metre must be positive")
    if not max_width > 0:
        raise ScaleError("maxWidth must be positive")
    max_metres = max_width / px_per_m
    if max_metres < MIN_BAR_M:
        raise ScaleError("no scale bar of one picometre or more fits")
    unit, unit_m = bar_unit(max_metres, units)
    value = nice_length(max_metres / unit_m)
    metres = value * unit_m
    return {"metres": metres, "pixels": metres * px_per_m, "unit": unit, "value": value,
            "label": scale_label(value, unit)}


def scale_bar_at(depth_px, focal_px, ppm, max_width, units="auto"):
    """scale_bar at a perspective depth."""
    return scale_bar(pixels_per_metre(depth_px, focal_px, ppm), max_width, units)


def scale_bar_frame(frame, fps, t0, t1, d0, d1, focal_px, ppm, max_width, units="auto"):
    """The scale bar of a powers-of-ten camera at a frame."""
    return scale_bar_at(frame_distance(frame, fps, t0, t1, d0, d1), focal_px, ppm, max_width, units)


def seek_test():
    """Frame-by-frame play (a running geometric product) matches direct evaluation at every frame."""
    fps, t0, t1, d0, d1 = 24.0, 2.0, 40.0, 10.0, 1.0e20
    focal = focal_pixels(60.0, 1920.0)
    hold = int(round(t0 * fps))
    ratio = (d1 / d0) ** (1.0 / ((t1 - t0) * fps))
    played = d0
    for frame in range(SEEK_FRAMES + 1):
        if frame > hold:
            played = min(played * ratio, d1)
        direct = frame_distance(frame, fps, t0, t1, d0, d1)
        if abs(direct - played) > 1e-9 * direct:
            return False
        if scale_bar_at(direct, focal, 100.0, 200) != scale_bar_at(played, focal, 100.0, 200):
            if scale_bar_at(direct, focal, 100.0, 200)["label"] != scale_bar_at(played, focal, 100.0, 200)["label"]:
                return False
    return True


# ------------------------------------------------------------------------------------ the floating origin


def world_error(p, eye):
    """Error of p - eye computed in binary32 world coordinates."""
    exact = float(p) - float(eye)
    return abs(f32(f32(p) - f32(eye)) - exact)


def rebased_error(p, eye):
    """Error of p - eye computed in binary64 and then rounded to binary32."""
    exact = float(p) - float(eye)
    return abs(f32(exact) - exact)


def _vec3(v):
    if len(v) != 3:
        raise ScaleError("positions are triples")
    return tuple(float(c) for c in v)


def floating_origin(positions, eye):
    """Every position rebased about the eye in binary64 and rounded to binary32."""
    e = _vec3(eye)
    return tuple(tuple(f32(c - ec) for c, ec in zip(_vec3(p), e)) for p in positions)


def world_positions(positions, eye):
    """The same subtraction done in binary32 world coordinates (what the floating origin avoids)."""
    e = tuple(f32(c) for c in _vec3(eye))
    return tuple(tuple(f32(f32(c) - ec) for c, ec in zip(_vec3(p), e)) for p in positions)


def rebase_needed(p, eye):
    """True when the binary32 world error exceeds RESOLUTION of the gap."""
    gap = abs(float(p) - float(eye))
    if gap == 0.0:
        return False
    return world_error(p, eye) > RESOLUTION * gap


def world_extent(gap):
    """The magnitude below which binary32 world coordinates still resolve a gap: 2^(24 + floor(log2 gap))."""
    if not gap > 0.0:
        raise ScaleError("gap must be positive")
    return 2.0 ** (F32_MANTISSA + 1 + math.floor(math.log2(gap)))


# ------------------------------------------------------------------------------------ validation


def validate_scale_bar(max_width, units, distance_px, near, far, scene_width):
    """SC3: maxWidth is a positive integer not above the scene width and units is auto or si;
    SC4: a fixed distance lies between near and far."""
    if not (isinstance(max_width, int) and 0 < max_width <= scene_width):
        raise ScaleError("SC3: maxWidth must be a positive integer not above the scene width")
    if units not in UNIT_MODES:
        raise ScaleError("SC3: units must be auto or si")
    if distance_px is not None and not near <= distance_px <= far:
        raise ScaleError("SC4: distance must lie between near and far")


# ------------------------------------------------------------------------------------ the table

_FOCAL = "focal_pixels(60, 1920)"
TABLE = (
    ("binary32 spacing at 1", "f32_ulp(1.0)", "1.19209e-07"),
    ("binary32 spacing at 1e20", "f32_ulp(1e20)", "8796093022208"),
    ("binary32 spacing at 1e-20", "f32_ulp(1e-20)", "8.07794e-28"),
    ("reversed depth at near", "depth(0.1, 0.1, 1e19)", "1"),
    ("reversed depth at twice near", "depth(0.2, 0.1, 1e19)", "0.5"),
    ("reversed depth at 1e10", "depth(1e10, 0.1, 1e19)", "1e-11"),
    ("logarithmic depth at the geometric mean", "depth(1e9, 0.1, 1e19, 'logarithmic')", "0.5"),
    ("logarithmic depth at 1e15", "depth(1e15, 0.1, 1e19, 'logarithmic')", "0.8"),
    ("distance of reversed depth 1e-11", "distance(1e-11, 0.1, 1e19)", "9999999990"),
    ("distance of logarithmic depth 0.8", "distance(0.8, 0.1, 1e19, 'logarithmic')", "1e+15"),
    ("reversed slope at 1e10", "depth_slope(1e10, 0.1, 1e19)", "1e-21"),
    ("logarithmic slope at 1e10", "depth_slope(1e10, 0.1, 1e19, 'logarithmic')", "2.17147e-12"),
    ("reversed float gap at 1e10", "resolvable_gap(1e10, 0.1, 1e19)", "867.362"),
    ("reversed float resolution at 1e10", "relative_resolution(1e10, 0.1, 1e19)", "8.67362e-08"),
    ("reversed fixed resolution at 1e10", "relative_resolution(1e10, 0.1, 1e19, 'reversed', 'fixed')", "5960.46"),
    ("logarithmic fixed resolution at 1e10", "relative_resolution(1e10, 0.1, 1e19, 'logarithmic', 'fixed')",
     "2.7449e-06"),
    ("logarithmic float resolution at 1e10", "relative_resolution(1e10, 0.1, 1e19, 'logarithmic', 'float')",
     "2.7449e-06"),
    ("worst reversed float resolution", "worst_resolution(0.1, 1e19)", "1.19209e-07"),
    ("worst logarithmic float resolution", "worst_resolution(0.1, 1e19, 'logarithmic')", "2.7449e-06"),
    ("worst reversed fixed resolution", "worst_resolution(0.1, 1e19, 'reversed', 'fixed')", "5.96046e+12"),
    ("reversed float resolves 1e20", "resolves(0.1, 1e19)", "True"),
    ("reversed fixed resolves 1e20", "resolves(0.1, 1e19, 'reversed', 'fixed')", "False"),
    ("logarithmic fixed resolves 1e20", "resolves(0.1, 1e19, 'logarithmic', 'fixed')", "True"),
    ("depth ratio of 1e20 is valid", "depth_ratio_valid(0.1, 1e19)", "True"),
    ("depth ratio of 2e20 is invalid", "depth_ratio_valid(0.1, 2e19)", "False"),
    ("geometric midpoint 10 to 1e20", "geometric(10, 1e20, 0.5)", "3.16228e+10"),
    ("geometric at 4 of 19 decades", "geometric(10, 1e20, 4 / 19)", "100000"),
    ("linear midpoint 10 to 1e20", "interpolate(10, 1e20, 0.5)", "5e+19"),
    ("decades 10 to 1e20", "decades(10, 1e20)", "19"),
    ("powers of ten at 10 s", "powers_of_ten(10, 2, 40, 10, 1e20)", "100000"),
    ("time at 1e15", "time_at(1e15, 2, 40, 10, 1e20)", "30"),
    ("frame 96 distance at 24 fps", "frame_distance(96, 24, 2, 40, 10, 1e20)", "100"),
    ("focal length of 60 degrees over 1920 px", _FOCAL, "1662.77"),
    ("pixels per metre at 1000 px", f"pixels_per_metre(1000, {_FOCAL}, 100)", "166.277"),
    ("orthographic pixels per metre", "pixels_per_metre_ortho(2000, 1080, 100)", "54"),
    ("nice length under 2.1383", "nice_length(2.1383)", "2"),
    ("nice length under 0.9", "nice_length(0.9)", "0.5"),
    ("bar at 1000 px", f"scale_bar_at(1000, {_FOCAL}, 100, 200)['label']", "'1 m'"),
    ("bar pixels at 1000 px", f"scale_bar_at(1000, {_FOCAL}, 100, 200)['pixels']", "166.277"),
    ("bar at 1e10 px", f"scale_bar_at(1e10, {_FOCAL}, 100, 200)['label']", "'10 Mm'"),
    ("bar at 1e15 px", f"scale_bar_at(1e15, {_FOCAL}, 100, 200)['label']", "'5 au'"),
    ("bar at 1e18 px", f"scale_bar_at(1e18, {_FOCAL}, 100, 200)['label']", "'5000 au'"),
    ("bar at 1e20 px", f"scale_bar_at(1e20, {_FOCAL}, 100, 200)['label']", "'2 pc'"),
    ("bar at 1e20 px in SI", f"scale_bar_at(1e20, {_FOCAL}, 100, 200, 'si')['label']", "'100000000 Gm'"),
    ("bar at frame 960", f"scale_bar_frame(960, 24, 2, 40, 10, 1e20, {_FOCAL}, 100, 200)['label']", "'2 pc'"),
    ("seek check", "seek_test()", "True"),
    ("world error of 2^17 at 1e20", "world_error(1e20 + 2 ** 17, 1e20)", "131072"),
    ("rebased error of 2^17 at 1e20", "rebased_error(1e20 + 2 ** 17, 1e20)", "0"),
    ("world error of 0.1 at 1e8", "world_error(1e8 + 0.1, 1e8)", "0.1"),
    ("rebased error of 0.1 at 1e8", "rebased_error(1e8 + 0.1, 1e8)", "0"),
    ("rebase needed at 1e20", "rebase_needed(1e20 + 2 ** 17, 1e20)", "True"),
    ("rebase needed at 1e6", "rebase_needed(1e6 + 0.25, 1e6)", "False"),
    ("world extent for a 1 unit gap", "world_extent(1)", "16777216"),
    ("world extent for a 1e13 gap", "world_extent(1e13)", "1.47574e+20"),
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
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, (int, float)):
        return f"{v:.6g}"
    return repr(v)


def main():
    s = scope()
    for name, expr, _expected in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
