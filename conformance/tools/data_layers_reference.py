#!/usr/bin/env python3
"""Reference computations for the draft SREP "Add data layers to the map" (M2 of SREP 12).

The MapLibre `heatmap` layer (Gaussian kernel density, coloured by a ramp over `heatmap-density`), the
`fill-extrusion` layer (roofs lit by the style's `light` on a 2D map; SREP 10 prisms on a 3D map) and `symbol`
icons from sprite sheets declared as `sprite` children of `basemap`, placed together with SREP 9's labels.

Formulas follow MapLibre GL JS 5.6.0's heatmap, fill_extrusion and symbol_sdf shaders and its icon shaping
and placement code (BSD-3-Clause; read, not copied) with the MapLibre style specification v8 defaults. Written
for sr-core by Claude Fable 5.1 via Claude Code; GPL code was not consulted. Run as a script it prints the
draft's numeric table.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

import numpy as np

R = 6378137.0
TILE = 256
DIGEST_DECIMALS = 3

# heatmap (MapLibre heatmap.vertex/fragment shaders)
GAUSS_COEF = 0.3989422804014327
ZERO = 1.0 / 255.0 / 16.0
DEFAULT_HEATMAP_COLOR = ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(0,0,255,0)", 0.1, "royalblue",
                         0.3, "cyan", 0.5, "lime", 0.7, "yellow", 1, "red"]
HEATMAP_DEFAULTS = {"radius": 30.0, "weight": 1.0, "intensity": 1.0, "color": DEFAULT_HEATMAP_COLOR,
                    "opacity": 1.0}
HEATMAP_KEYS = {"heatmap-radius": "radius", "heatmap-weight": "weight", "heatmap-intensity": "intensity",
                "heatmap-color": "color", "heatmap-opacity": "opacity"}

# fill-extrusion (MapLibre fill_extrusion.vertex shader) and the style's light
AMBIENT = 0.03
GRADIENT_FLOOR = (0.7, 0.98)
GRADIENT_HEIGHT = 150.0
LIGHT_DEFAULTS = {"anchor": "viewport", "position": (1.15, 210.0, 30.0), "color": "#ffffff", "intensity": 0.5}
EXTRUSION_DEFAULTS = {"opacity": 1.0, "color": "#000000", "translate": (0.0, 0.0), "translateAnchor": "map",
                      "height": 0.0, "base": 0.0, "verticalGradient": True}
EXTRUSION_KEYS = {"fill-extrusion-opacity": "opacity", "fill-extrusion-color": "color",
                  "fill-extrusion-translate": "translate", "fill-extrusion-translate-anchor": "translateAnchor",
                  "fill-extrusion-height": "height", "fill-extrusion-base": "base",
                  "fill-extrusion-vertical-gradient": "verticalGradient"}

# symbol icons (MapLibre symbol layout and paint, symbol_sdf.fragment shader)
ANCHORS = ("center", "left", "right", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right")
OVERLAPS = ("never", "always", "cooperative")
PLACEMENTS = ("point", "line", "line-center")
TEXT_FITS = ("none", "width", "height", "both")
ALIGNMENTS = ("map", "viewport", "auto")
Z_ORDERS = ("auto", "viewport-y", "source")
TRANSLATE_ANCHORS = ("map", "viewport")
EDGE_GAMMA = 0.105
INNER_EDGE = 0.75
SDF_PX = 8.0
HALO_BLUR_SCALE = 1.19
ICON_LAYOUT_DEFAULTS = {"allowOverlap": False, "overlap": None, "ignorePlacement": False, "optional": False,
                        "rotationAlignment": "auto", "size": 1.0, "textFit": "none",
                        "textFitPadding": (0.0, 0.0, 0.0, 0.0), "image": None, "rotate": 0.0,
                        "padding": (2.0, 2.0, 2.0, 2.0), "keepUpright": False, "offset": (0.0, 0.0),
                        "anchor": "center", "pitchAlignment": "auto", "placement": "point", "spacing": 250.0,
                        "avoidEdges": False, "sortKey": None, "zOrder": "auto"}
ICON_LAYOUT_KEYS = {"icon-allow-overlap": "allowOverlap", "icon-overlap": "overlap",
                    "icon-ignore-placement": "ignorePlacement", "icon-optional": "optional",
                    "icon-rotation-alignment": "rotationAlignment", "icon-size": "size", "icon-text-fit": "textFit",
                    "icon-text-fit-padding": "textFitPadding", "icon-image": "image", "icon-rotate": "rotate",
                    "icon-padding": "padding", "icon-keep-upright": "keepUpright", "icon-offset": "offset",
                    "icon-anchor": "anchor", "icon-pitch-alignment": "pitchAlignment",
                    "symbol-placement": "placement", "symbol-spacing": "spacing", "symbol-avoid-edges": "avoidEdges",
                    "symbol-sort-key": "sortKey", "symbol-z-order": "zOrder"}
ICON_PAINT_DEFAULTS = {"opacity": 1.0, "color": "#000000", "haloColor": "rgba(0,0,0,0)", "haloWidth": 0.0,
                       "haloBlur": 0.0, "translate": (0.0, 0.0), "translateAnchor": "map"}
ICON_PAINT_KEYS = {"icon-opacity": "opacity", "icon-color": "color", "icon-halo-color": "haloColor",
                   "icon-halo-width": "haloWidth", "icon-halo-blur": "haloBlur", "icon-translate": "translate",
                   "icon-translate-anchor": "translateAnchor"}
SPRITE_KEYS = ("name", "index", "image")
DUPLICATE_BUCKET = 8.0

NAMED_COLOURS = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "lime": (0, 255, 0),
                 "green": (0, 128, 0), "blue": (0, 0, 255), "cyan": (0, 255, 255), "aqua": (0, 255, 255),
                 "magenta": (255, 0, 255), "fuchsia": (255, 0, 255), "yellow": (255, 255, 0),
                 "royalblue": (65, 105, 225), "orange": (255, 165, 0), "gray": (128, 128, 128),
                 "grey": (128, 128, 128), "navy": (0, 0, 128), "purple": (128, 0, 128), "silver": (192, 192, 192),
                 "maroon": (128, 0, 0), "olive": (128, 128, 0), "teal": (0, 128, 128)}


class DataLayersError(ValueError):
    """A document, style or sprite that the draft rejects."""


# ------------------------------------------------------------------------------------------------------- utilities


def digest(obj):
    """The first twelve hex digits of the sha256 of the object as JSON, floats rounded to three decimals."""
    def rnd(v):
        if isinstance(v, (float, np.floating)):
            return round(float(v), DIGEST_DECIMALS)
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        if isinstance(v, (int, np.integer)):
            return int(v)
        if isinstance(v, dict):
            return {k: rnd(x) for k, x in v.items()}
        if isinstance(v, (list, tuple, np.ndarray)):
            return [rnd(x) for x in v]
        return v
    text = json.dumps(rnd(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def colour(value):
    """A style colour as straight (r, g, b, a) integers 0..255: #RGB, #RRGGBB, #RRGGBBAA, rgb(), rgba() or a name."""
    s = str(value).strip()
    m = re.fullmatch(r"#([0-9A-Fa-f]{3})", s)
    if m:
        s = "#" + "".join(c * 2 for c in m.group(1))
    m = re.fullmatch(r"#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?", s)
    if m:
        rgb = m.group(1)
        a = m.group(2) or "FF"
        return tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4)) + (int(a, 16),)
    m = re.fullmatch(r"rgba?\(\s*([^)]*)\)", s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) not in (3, 4):
            raise DataLayersError(f"rgb()/rgba() needs three or four components: {value!r}")
        try:
            rgb = tuple(int(round(float(p))) for p in parts[:3])
            a = int(round(255 * float(parts[3]))) if len(parts) == 4 else 255
        except ValueError:
            raise DataLayersError(f"a numeric colour component is required: {value!r}") from None
        if not all(0 <= c <= 255 for c in rgb + (a,)):
            raise DataLayersError(f"colour components must lie in 0..255 and alpha in 0..1: {value!r}")
        return rgb + (a,)
    if s.lower() in NAMED_COLOURS:
        return NAMED_COLOURS[s.lower()] + (255,)
    if s.lower() == "transparent":
        return (0, 0, 0, 0)
    raise DataLayersError(f"a colour literal is required: {value!r}")


def straight(value):
    """A colour as straight (r, g, b, a) floats 0..1."""
    return tuple(c / 255.0 for c in colour(value))


def premultiplied(value):
    r, g, b, a = straight(value)
    return (r * a, g * a, b * a, a)


def _number(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise DataLayersError(f"{what} must be a finite number: {v!r}")
    return float(v)


def _pair(v, what):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise DataLayersError(f"{what} must be a pair of numbers: {v!r}")
    return (_number(v[0], what), _number(v[1], what))


def _padding(v, what):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (float(v),) * 4
    if isinstance(v, (list, tuple)) and len(v) == 1:
        return (_number(v[0], what),) * 4
    if isinstance(v, (list, tuple)) and len(v) == 4:
        return tuple(_number(x, what) for x in v)
    return v


def _is_expression(v):
    return isinstance(v, list) and v and isinstance(v[0], str)


# ---------------------------------------------------------------------------------------------- style expressions


_TOKEN = re.compile(r"\{([^{}]+)\}")


def evaluate(expr, properties):
    """A constant, a legacy `{token}` string or an expression over the feature's properties (SREP 9's subset that
    data layers need). Raises DataLayersError when the expression fails; the caller then takes the default."""
    if isinstance(expr, str):
        return _TOKEN.sub(lambda m: str(properties.get(m.group(1), "")), expr)
    if not _is_expression(expr):
        return expr
    op, args = expr[0], expr[1:]
    ev = lambda e: evaluate(e, properties)  # noqa: E731
    try:
        if op == "literal":
            return args[0]
        if op == "get":
            key = ev(args[0])
            if key not in properties:
                raise DataLayersError(f"property {key!r} is missing")
            return properties[key]
        if op == "has":
            return ev(args[0]) in properties
        if op == "coalesce":
            for a in args:
                try:
                    v = ev(a)
                except DataLayersError:
                    continue
                if v is not None:
                    return v
            raise DataLayersError("coalesce found no value")
        if op == "to-number":
            return float(ev(args[0]))
        if op == "to-string":
            return str(ev(args[0]))
        if op == "concat":
            return "".join(str(ev(a)) for a in args)
        if op in ("+", "*", "min", "max"):
            vals = [float(ev(a)) for a in args]
            if op == "+":
                return sum(vals)
            if op == "*":
                return math.prod(vals)
            return min(vals) if op == "min" else max(vals)
        if op == "-":
            vals = [float(ev(a)) for a in args]
            return -vals[0] if len(vals) == 1 else vals[0] - vals[1]
        if op == "/":
            a, b = (float(ev(x)) for x in args)
            if b == 0:
                raise DataLayersError("division by zero")
            return a / b
        if op == "%":
            a, b = (float(ev(x)) for x in args)
            return math.fmod(a, b)
        if op == "^":
            a, b = (float(ev(x)) for x in args)
            return a ** b
        if op in ("abs", "round", "floor", "ceil", "sqrt"):
            v = float(ev(args[0]))
            return {"abs": abs, "round": lambda x: math.floor(x + 0.5), "floor": math.floor, "ceil": math.ceil,
                    "sqrt": math.sqrt}[op](v)
        if op in ("==", "!=", "<", "<=", ">", ">="):
            a, b = ev(args[0]), ev(args[1])
            return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        if op == "!":
            return not ev(args[0])
        if op == "all":
            return all(ev(a) for a in args)
        if op == "any":
            return any(ev(a) for a in args)
        if op == "case":
            for i in range(0, len(args) - 1, 2):
                if ev(args[i]):
                    return ev(args[i + 1])
            return ev(args[-1])
        if op == "match":
            v = ev(args[0])
            for i in range(1, len(args) - 1, 2):
                labels = args[i] if isinstance(args[i], list) else [args[i]]
                if v in labels:
                    return ev(args[i + 1])
            return ev(args[-1])
    except (TypeError, ValueError, IndexError) as e:
        raise DataLayersError(f"expression failed: {e}") from None
    raise DataLayersError(f"operator {op!r} is not supported")


def value(expr, properties, default):
    """The expression's value for the feature, or the default when it fails."""
    try:
        v = evaluate(expr, properties)
    except DataLayersError:
        return default
    return default if v is None else v


# ----------------------------------------------------------------------------------------------------------- heatmap


def kernel(d2, radius, weight, intensity):
    """MapLibre's kernel: weight * intensity * GAUSS_COEF * exp(-0.5 * 3^2 * d^2 / radius^2)."""
    return weight * intensity * GAUSS_COEF * math.exp(-4.5 * d2 / (radius * radius))


def kernel_extent(radius, weight, intensity):
    """Half the side of the quad MapLibre's vertex shader draws for a point: radius * sqrt(-2 ln(ZERO / (w I G))) / 3.
    Zero when the kernel's peak is already below ZERO (nothing drawn)."""
    peak = weight * intensity * GAUSS_COEF
    if peak <= ZERO:
        return 0.0
    return radius * math.sqrt(-2.0 * math.log(ZERO / peak)) / 3.0


def density(points, width, height, radius, intensity):
    """The kernel sum at pixel centres over a width x height grid; points are (x, y, weight) in map pixels."""
    d = np.zeros((height, width))
    for x, y, w in points:
        e = kernel_extent(radius, w, intensity)
        if e <= 0.0:
            continue
        x0 = max(0, int(math.floor(x - e)))
        x1 = min(width, int(math.ceil(x + e)) + 1)
        y0 = max(0, int(math.floor(y - e)))
        y1 = min(height, int(math.ceil(y + e)) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        cx = np.arange(x0, x1) + 0.5 - x
        cy = np.arange(y0, y1) + 0.5 - y
        inside = (np.abs(cy)[:, None] <= e) & (np.abs(cx)[None, :] <= e)
        d2 = cy[:, None] ** 2 + cx[None, :] ** 2
        d[y0:y1, x0:x1] += np.where(inside, w * intensity * GAUSS_COEF * np.exp(-4.5 * d2 / (radius * radius)), 0.0)
    return d


def ramp_stops(expr, input_name):
    """A colour ramp `["interpolate", [...], [input], t0, c0, ...]` or `["step", [input], c0, t1, c1, ...]` over
    the named input, as {"kind", "base", "stops": [(t, straight rgba ints)]}."""
    if not _is_expression(expr) or expr[0] not in ("interpolate", "step"):
        raise DataLayersError(f"a colour ramp (interpolate or step) over [\"{input_name}\"] is required: {expr!r}")
    if expr[0] == "interpolate":
        if len(expr) < 3 or not isinstance(expr[1], list) or expr[1][:1] not in (["linear"], ["exponential"]):
            raise DataLayersError("interpolate needs [\"linear\"] or [\"exponential\", base]")
        base = 1.0 if expr[1][0] == "linear" else _number(expr[1][1], "the exponential base")
        inp, rest = expr[2], expr[3:]
        if len(rest) < 4 or len(rest) % 2:
            raise DataLayersError("interpolate needs at least two stops")
        stops = [(_number(rest[i], "a stop"), colour(rest[i + 1])) for i in range(0, len(rest), 2)]
        kind = "interpolate"
    else:
        inp, rest = expr[1], expr[2:]
        if len(rest) < 1 or len(rest) % 2 == 0:
            raise DataLayersError("step needs a first colour and (stop, colour) pairs")
        base = 1.0
        stops = [(-math.inf, colour(rest[0]))] + [(_number(rest[i], "a stop"), colour(rest[i + 1]))
                                                   for i in range(1, len(rest), 2)]
        kind = "step"
    if inp != [input_name]:
        raise DataLayersError(f"the ramp must be over [\"{input_name}\"], not {inp!r}")
    if any(stops[i][0] >= stops[i + 1][0] for i in range(len(stops) - 1)):
        raise DataLayersError("ramp stops must increase")
    return {"kind": kind, "base": base, "stops": stops}


def ramp_colours(stops, t):
    """Premultiplied rgba floats (..., 4) for densities t (clamped to [0, 1]); straight RGBA is interpolated."""
    t = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    pos = np.array([s[0] for s in stops["stops"]])
    cols = np.array([s[1] for s in stops["stops"]], dtype=float) / 255.0
    if stops["kind"] == "step":
        idx = np.searchsorted(pos, t, side="right") - 1
        out = cols[np.clip(idx, 0, len(pos) - 1)]
    else:
        idx = np.clip(np.searchsorted(pos, t, side="right") - 1, 0, len(pos) - 2)
        lo, hi = pos[idx], pos[idx + 1]
        progress = np.clip(t - lo, 0.0, None)
        span = hi - lo
        if stops["base"] == 1.0:
            f = progress / span
        else:
            f = (stops["base"] ** progress - 1.0) / (stops["base"] ** span - 1.0)
        f = np.clip(f, 0.0, 1.0)
        out = cols[idx] + (cols[idx + 1] - cols[idx]) * f[..., None]
    out = out.copy()
    out[..., :3] *= out[..., 3:4]
    return out


def ramp_colour(stops, t):
    return tuple(float(c) for c in ramp_colours(stops, float(t)))


def heatmap_paint(paint):
    out = dict(HEATMAP_DEFAULTS)
    for key, name in HEATMAP_KEYS.items():
        if key in paint:
            v = paint[key]
            out[name] = v if (_is_expression(v) or name == "color") else _number(v, key)
    return out


def check_heatmap(paint):
    if not _is_expression(paint["radius"]) and paint["radius"] < 1.0:
        raise DataLayersError("heatmap-radius must be at least 1")
    for name in ("weight", "intensity"):
        if not _is_expression(paint[name]) and paint[name] < 0.0:
            raise DataLayersError(f"heatmap-{name} must not be negative")
    if not _is_expression(paint["opacity"]) and not 0.0 <= paint["opacity"] <= 1.0:
        raise DataLayersError("heatmap-opacity must lie in 0..1")
    return paint


def kernel_centres(geometry):
    """Every vertex of the geometry (MapLibre's circle bucket feeds all of them to the heatmap)."""
    kind = geometry["type"]
    c = geometry["coordinates"]
    if kind == "Point":
        return [(float(c[0]), float(c[1]))]
    if kind in ("MultiPoint", "LineString"):
        return [(float(p[0]), float(p[1])) for p in c]
    if kind in ("MultiLineString", "Polygon"):
        return [(float(p[0]), float(p[1])) for ring in c for p in (ring[:-1] if kind == "Polygon" else ring)]
    if kind == "MultiPolygon":
        return [(float(p[0]), float(p[1])) for poly in c for ring in poly for p in ring[:-1]]
    raise DataLayersError(f"unknown geometry type {kind!r}")


def heatmap_pixels(points, width, height, paint, opacity):
    """Premultiplied rgba (height, width, 4): the ramp of the density, times heatmap-opacity and the basemap's."""
    radius = paint["radius"] if not _is_expression(paint["radius"]) else HEATMAP_DEFAULTS["radius"]
    intensity = paint["intensity"] if not _is_expression(paint["intensity"]) else HEATMAP_DEFAULTS["intensity"]
    layer_opacity = paint["opacity"] if not _is_expression(paint["opacity"]) else 1.0
    t = density(points, width, height, radius, intensity)
    px = ramp_colours(ramp_stops(paint["color"], "heatmap-density"), t)
    px[t <= 0.0] = 0.0
    return px * (layer_opacity * opacity)


# ---------------------------------------------------------------------------------------------------- fill-extrusion


def light(style_light):
    """The style's root `light` with MapLibre's defaults: anchor, position (r, azimuth, polar), colour, intensity."""
    style_light = style_light or {}
    out = {"anchor": style_light.get("anchor", LIGHT_DEFAULTS["anchor"]),
           "intensity": _number(style_light.get("intensity", LIGHT_DEFAULTS["intensity"]), "light.intensity")}
    if out["anchor"] not in TRANSLATE_ANCHORS:
        raise DataLayersError(f"light.anchor must be map or viewport: {out['anchor']!r}")
    pos = style_light.get("position", LIGHT_DEFAULTS["position"])
    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        raise DataLayersError("light.position must be [radial, azimuthal, polar]")
    out["position"] = tuple(_number(v, "light.position") for v in pos)
    out["color"] = straight(style_light.get("color", LIGHT_DEFAULTS["color"]))[:3]
    if not 0.0 <= out["intensity"] <= 1.0:
        raise DataLayersError("light.intensity must lie in 0..1")
    return out


def light_direction(light_, rotation):
    """MapLibre's sphericalToCartesian (azimuth measured from north: +90 degrees), turned by the map's rotation
    when the anchor is viewport."""
    r, azimuthal, polar = light_["position"]
    az = math.radians(azimuthal + 90.0)
    po = math.radians(polar)
    x, y, z = r * math.cos(az) * math.sin(po), r * math.sin(az) * math.sin(po), r * math.cos(po)
    if light_["anchor"] == "viewport":
        b = math.radians(rotation)
        x, y = x * math.cos(b) - y * math.sin(b), x * math.sin(b) + y * math.cos(b)
    return (x, y, z)


def _mix(a, b, t):
    return a * (1.0 - t) + b * t


def shade(color, normal, light_, t, base, height, vertical_gradient, opacity, rotation=0.0):
    """MapLibre's fill_extrusion vertex shader colour for a face with the unit normal: premultiplied rgba.
    `t` is 1 at the roof edge of a wall and 0 at its foot; roofs (normal z) take no vertical gradient."""
    r, g, b, a = color
    rgb = [r * a, g * a, b * a]
    luma = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
    rgb = [c + AMBIENT for c in rgb]
    lx, ly, lz = light_direction(light_, rotation)
    intensity = light_["intensity"]
    directional = min(1.0, max(0.0, normal[0] * lx + normal[1] * ly + normal[2] * lz))
    directional = _mix(1.0 - intensity, max(1.0 - luma + intensity, 1.0), directional)
    if abs(normal[2]) < 1.0 - 1e-12:
        floor = _mix(GRADIENT_FLOOR[0], GRADIENT_FLOOR[1], 1.0 - intensity)
        gradient = min(1.0, max(floor, (t + base) * math.sqrt(max(height, 0.0) / GRADIENT_HEIGHT)))
        vg = 1.0 if vertical_gradient else 0.0
        directional *= (1.0 - vg) + vg * gradient
    out = []
    for c, lc in zip(rgb, light_["color"]):
        out.append(min(1.0, max(_mix(0.0, 0.3, 1.0 - lc), c * directional * lc)) * opacity)
    return (out[0], out[1], out[2], a * opacity)


def extrusion_paint(paint):
    out = dict(EXTRUSION_DEFAULTS)
    for key, name in EXTRUSION_KEYS.items():
        if key in paint:
            v = paint[key]
            if _is_expression(v) or name == "color":
                out[name] = v
            elif name == "translate":
                out[name] = _pair(v, key)
            elif name in ("translateAnchor", "verticalGradient"):
                out[name] = v
            else:
                out[name] = _number(v, key)
    return out


def check_extrusion(paint):
    if not _is_expression(paint["opacity"]) and not 0.0 <= paint["opacity"] <= 1.0:
        raise DataLayersError("fill-extrusion-opacity must lie in 0..1")
    if paint["translateAnchor"] not in TRANSLATE_ANCHORS:
        raise DataLayersError("fill-extrusion-translate-anchor must be map or viewport")
    if not isinstance(paint["verticalGradient"], bool):
        raise DataLayersError("fill-extrusion-vertical-gradient must be a boolean")
    if not _is_expression(paint["color"]):
        colour(paint["color"])
    return paint


def extrusion(properties, paint):
    """The feature's extrusion {top, base, color (straight rgba floats)} or None when it is skipped: top and
    base are clamped to zero as the shader does, and a top not above the base draws nothing."""
    top = value(paint["height"], properties, EXTRUSION_DEFAULTS["height"])
    base = value(paint["base"], properties, EXTRUSION_DEFAULTS["base"])
    try:
        top, base = max(0.0, float(top)), max(0.0, float(base))
    except (TypeError, ValueError):
        return None
    if not top > base:
        return None
    col = value(paint["color"], properties, EXTRUSION_DEFAULTS["color"])
    try:
        rgba = straight(col)
    except DataLayersError:
        rgba = straight(EXTRUSION_DEFAULTS["color"])
    return {"top": top, "base": base, "color": rgba}


def fill_polygon(rings, width, height):
    """Pixel centres inside the rings under the non-zero winding rule, as a boolean (height, width) mask."""
    cy = np.arange(height) + 0.5
    cx = np.arange(width) + 0.5
    wn = np.zeros((height, width), dtype=int)
    for ring in rings:
        pts = [(float(p[0]), float(p[1])) for p in ring]
        if len(pts) > 1 and pts[0] != pts[-1]:
            pts.append(pts[0])
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            if y0 == y1:
                continue
            up = (y0 <= cy[:, None]) & (cy[:, None] < y1)
            down = (y1 <= cy[:, None]) & (cy[:, None] < y0)
            cross = (x1 - x0) * (cy[:, None] - y0) - (cx[None, :] - x0) * (y1 - y0)
            wn += np.where(up & (cross > 0), 1, 0)
            wn -= np.where(down & (cross < 0), 1, 0)
    return wn != 0


def _polygons(geometry, project):
    kind = geometry["type"]
    polys = geometry["coordinates"] if kind == "MultiPolygon" else [geometry["coordinates"]]
    if kind not in ("Polygon", "MultiPolygon"):
        return []
    return [[[tuple(float(c) for c in project((float(p[0]), float(p[1])))) for p in ring] for ring in poly]
            for poly in polys]


def _over(dst, src, mask):
    """Composite the premultiplied colour `src` over the pixels of `dst` selected by `mask`."""
    a = src[3]
    dst[mask] = dst[mask] * (1.0 - a) + np.asarray(src)


def roof_pixels(features, width, height, paint, light_, rotation, opacity, project):
    """Premultiplied rgba (height, width, 4) of the roofs on a 2D map, drawn in feature order, each lit as the
    shader lights an upward face; returns (pixels, drawn, skipped)."""
    px = np.zeros((height, width, 4))
    drawn = skipped = 0
    layer_opacity = paint["opacity"] if not _is_expression(paint["opacity"]) else 1.0
    for f in features:
        ext = extrusion(f.get("properties", {}), paint)
        if ext is None:
            skipped += 1
            continue
        col = shade(ext["color"], (0.0, 0.0, 1.0), light_, 0.0, ext["base"], ext["top"], paint["verticalGradient"],
                    layer_opacity * opacity, rotation)
        for rings in _polygons(f["geometry"], project):
            _over(px, col, fill_polygon(rings, width, height))
        drawn += 1
    return px, drawn, skipped


def prisms(features, paint, project):
    """SREP 10 prisms for a 3D map: {rings, top, base, color} per feature with top above base."""
    out = []
    for f in features:
        ext = extrusion(f.get("properties", {}), paint)
        if ext is None:
            continue
        for rings in _polygons(f["geometry"], project):
            out.append({"rings": rings, "top": ext["top"], "base": ext["base"], "color": ext["color"]})
    return out


# -------------------------------------------------------------------------------------------------- sprites and icons


def sprite_index(index):
    """The sprite index JSON as {name: {x, y, width, height, pixelRatio, sdf, displaySize, stretch}}."""
    out = {}
    if not isinstance(index, dict):
        raise DataLayersError("a sprite index is a JSON object")
    for name, entry in index.items():
        if not isinstance(entry, dict) or any(k not in entry for k in ("x", "y", "width", "height")):
            raise DataLayersError(f"sprite {name!r} needs x, y, width and height")
        ratio = _number(entry.get("pixelRatio", 1), f"sprite {name!r} pixelRatio")
        e = {"x": int(entry["x"]), "y": int(entry["y"]), "width": int(entry["width"]), "height": int(entry["height"]),
             "pixelRatio": ratio, "sdf": bool(entry.get("sdf", False)),
             "stretch": any(k in entry for k in ("stretchX", "stretchY", "content"))}
        e["displaySize"] = (e["width"] / ratio, e["height"] / ratio) if ratio > 0 else (0.0, 0.0)
        out[name] = e
    return out


def check_sprite(index, sheet_width, sheet_height):
    for name, e in index.items():
        if e["pixelRatio"] <= 0:
            raise DataLayersError(f"sprite {name!r} has a non-positive pixelRatio")
        if e["width"] < 1 or e["height"] < 1:
            raise DataLayersError(f"sprite {name!r} is empty")
        if e["x"] < 0 or e["y"] < 0 or e["x"] + e["width"] > sheet_width or e["y"] + e["height"] > sheet_height:
            raise DataLayersError(f"sprite {name!r} lies outside its sheet of {sheet_width} x {sheet_height}")
    return index


def sprite_name(name, sprite_id):
    """The icon-image name an icon of the sprite with this id takes: plain for `default`, `id:name` otherwise."""
    return name if sprite_id == "default" else f"{sprite_id}:{name}"


def style_sprites(value_):
    """The style's root `sprite` as a list of {id, url}."""
    if value_ is None:
        return []
    if isinstance(value_, str):
        return [{"id": "default", "url": value_}]
    if isinstance(value_, list) and all(isinstance(s, dict) and "id" in s and "url" in s for s in value_):
        return [{"id": str(s["id"]), "url": str(s["url"])} for s in value_]
    raise DataLayersError("sprite must be a URL or an array of {id, url}")


def icon_layout(layout):
    out = dict(ICON_LAYOUT_DEFAULTS)
    for key, name in ICON_LAYOUT_KEYS.items():
        if key in layout:
            v = layout[key]
            if _is_expression(v):
                out[name] = v
            elif name in ("padding", "textFitPadding"):
                out[name] = _padding(v, key)
            elif name == "offset":
                out[name] = _pair(v, key)
            elif name in ("size", "rotate", "spacing"):
                out[name] = _number(v, key)
            else:
                out[name] = v
    return out


def icon_paint(paint):
    out = dict(ICON_PAINT_DEFAULTS)
    for key, name in ICON_PAINT_KEYS.items():
        if key in paint:
            v = paint[key]
            if _is_expression(v):
                out[name] = v
            elif name == "translate":
                out[name] = _pair(v, key)
            elif name in ("opacity", "haloWidth", "haloBlur"):
                out[name] = _number(v, key)
            else:
                out[name] = v
    return out


def check_symbol(layout, paint):
    for name, allowed in (("anchor", ANCHORS), ("textFit", TEXT_FITS), ("placement", PLACEMENTS),
                          ("rotationAlignment", ALIGNMENTS), ("pitchAlignment", ALIGNMENTS), ("zOrder", Z_ORDERS)):
        if not _is_expression(layout[name]) and layout[name] not in allowed:
            raise DataLayersError(f"{name} must be one of {allowed}: {layout[name]!r}")
    if layout["overlap"] is not None and not _is_expression(layout["overlap"]) and layout["overlap"] not in OVERLAPS:
        raise DataLayersError(f"icon-overlap must be one of {OVERLAPS}")
    if not _is_expression(layout["size"]) and layout["size"] < 0.0:
        raise DataLayersError("icon-size must not be negative")
    for name in ("padding", "textFitPadding"):
        if not _is_expression(layout[name]) and not (isinstance(layout[name], tuple) and len(layout[name]) == 4):
            raise DataLayersError(f"{name} needs one number or four")
    for name in ("allowOverlap", "ignorePlacement", "optional", "keepUpright", "avoidEdges"):
        if not _is_expression(layout[name]) and not isinstance(layout[name], bool):
            raise DataLayersError(f"{name} must be a boolean")
    if not _is_expression(paint["opacity"]) and not 0.0 <= paint["opacity"] <= 1.0:
        raise DataLayersError("icon-opacity must lie in 0..1")
    for name in ("haloWidth", "haloBlur"):
        if not _is_expression(paint[name]) and paint[name] < 0.0:
            raise DataLayersError(f"icon-{name} must not be negative")
    if paint["translateAnchor"] not in TRANSLATE_ANCHORS:
        raise DataLayersError("icon-translate-anchor must be map or viewport")
    for name in ("color", "haloColor"):
        if not _is_expression(paint[name]):
            colour(paint[name])
    return layout, paint


def overlap_mode(layout, properties=None):
    """MapLibre's getOverlapMode: icon-overlap when set, else icon-allow-overlap as always/never."""
    props = properties or {}
    overlap = value(layout["overlap"], props, None)
    if overlap:
        return overlap
    return "always" if value(layout["allowOverlap"], props, False) else "never"


def anchor_fractions(anchor):
    ax = 1.0 if anchor in ("right", "top-right", "bottom-right") else 0.0 if anchor in (
        "left", "top-left", "bottom-left") else 0.5
    ay = 1.0 if anchor in ("bottom", "bottom-right", "bottom-left") else 0.0 if anchor in (
        "top", "top-right", "top-left") else 0.5
    return (ax, ay)


def icon_box(anchor_px, display_size, size, anchor, offset):
    """MapLibre's shapeIcon scaled by icon-size: the unrotated icon rectangle (x1, y1, x2, y2) in map pixels."""
    ax, ay = anchor_fractions(anchor)
    w, h = display_size
    x1 = anchor_px[0] + size * (offset[0] - w * ax)
    y1 = anchor_px[1] + size * (offset[1] - h * ay)
    return (x1, y1, x1 + size * w, y1 + size * h)


def icon_quad(anchor_px, box, rotate):
    """The box's corners (top-left, top-right, bottom-right, bottom-left) turned clockwise by `rotate` degrees
    about the anchor."""
    th = math.radians(rotate)
    c, s = math.cos(th), math.sin(th)
    x1, y1, x2, y2 = box
    out = []
    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        dx, dy = x - anchor_px[0], y - anchor_px[1]
        out.append((anchor_px[0] + dx * c - dy * s, anchor_px[1] + dx * s + dy * c))
    return out


def bounds(quad):
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return (min(xs), min(ys), max(xs), max(ys))


def fit_icon_to_text(display_size, text_box, fit, padding, offset):
    """MapLibre's fitIconToText: the icon box relative to the anchor, stretched to the text box (left, top,
    right, bottom, in pixels) in the fitted dimensions and centred on it in the others."""
    w, h = display_size
    left, top, right, bottom = text_box
    if fit in ("width", "both"):
        x1, x2 = offset[0] + left - padding[3], offset[0] + right + padding[1]
    else:
        x1 = offset[0] + (left + right - w) / 2.0
        x2 = x1 + w
    if fit in ("height", "both"):
        y1, y2 = offset[1] + top - padding[0], offset[1] + bottom + padding[2]
    else:
        y1 = offset[1] + (top + bottom - h) / 2.0
        y2 = y1 + h
    return (x1, y1, x2, y2)


def grow(box, padding):
    if isinstance(padding, (int, float)):
        padding = (padding,) * 4
    t, r, b, l = padding
    return (box[0] - l, box[1] - t, box[2] + r, box[3] + b)


def overlaps(a, b):
    return bool(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])


def _collides(box, mode, placed):
    if mode == "always":
        return False
    for other, other_mode in placed:
        if overlaps(box, other) and (mode == "never" or other_mode == "never"):
            return True
    return False


def place(candidates, width, height):
    """SREP 9's placement extended to icons: for each candidate (in priority order) whether its text and its
    icon are placed. A candidate has `text` and `icon` boxes (or None), `*_overlap` modes, `*_ignore`,
    `*_optional`, `text_padding`, `icon_padding` and `text_key` for the duplicate rule."""
    placed = []
    seen = set()
    frame = (0.0, 0.0, float(width), float(height))
    out = []
    for c in candidates:
        text = grow(c["text"], c["text_padding"]) if c["text"] is not None else None
        icon = grow(c["icon"], c["icon_padding"]) if c["icon"] is not None else None
        place_text = text is not None and overlaps(text, frame) and not _collides(text, c["text_overlap"], placed)
        place_icon = icon is not None and overlaps(icon, frame) and not _collides(icon, c["icon_overlap"], placed)
        bucket = None
        if place_text and c.get("text_key") is not None:
            bucket = (c["text_key"], round(c["text"][0] / DUPLICATE_BUCKET), round(c["text"][1] / DUPLICATE_BUCKET))
            if bucket in seen:
                place_text = False
        text_without_icon = c["icon"] is None or c["icon_optional"]
        icon_without_text = c["text"] is None or c["text_optional"]
        if not text_without_icon and not icon_without_text:
            place_text = place_icon = place_text and place_icon
        elif not text_without_icon:
            place_text = place_text and place_icon
        elif not icon_without_text:
            place_icon = place_text and place_icon
        if place_text:
            if bucket is not None:
                seen.add(bucket)
            if not c["text_ignore"]:
                placed.append((text, c["text_overlap"]))
        if place_icon and not c["icon_ignore"]:
            placed.append((icon, c["icon_overlap"]))
        out.append((bool(place_text), bool(place_icon)))
    return out


def _line_midpoint(points):
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points[:-1], points[1:])]
    total = sum(lengths)
    if total <= 0.0:
        return None
    half = total / 2.0
    run = 0.0
    for (a, b), seg in zip(zip(points[:-1], points[1:]), lengths):
        if run + seg >= half and seg > 0.0:
            f = (half - run) / seg
            angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            return ((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])), angle)
        run += seg
    return None


def candidate_anchors(geometry, placement):
    """SREP 9's anchors as ((x, y), segment angle in degrees): every point of a Point, the mean of the vertices
    of a Polygon's largest ring, the midpoint by length of each line piece when the placement is `line`, the
    midpoint of the whole line for `line-center`, none for lines placed as points."""
    kind = geometry["type"]
    c = geometry["coordinates"]
    if kind == "Point":
        return [((float(c[0]), float(c[1])), 0.0)]
    if kind == "MultiPoint":
        return [((float(p[0]), float(p[1])), 0.0) for p in c]
    if kind in ("Polygon", "MultiPolygon"):
        rings = [ring for poly in (c if kind == "MultiPolygon" else [c]) for ring in poly]
        best, area = None, -1.0
        for ring in rings:
            pts = [(float(p[0]), float(p[1])) for p in ring]
            a = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2.0
            if a > area:
                best, area = pts, a
        if not best:
            return []
        return [((sum(p[0] for p in best) / len(best), sum(p[1] for p in best) / len(best)), 0.0)]
    if kind in ("LineString", "MultiLineString"):
        if placement == "point":
            return []
        lines = [c] if kind == "LineString" else c
        pieces = [[(float(p[0]), float(p[1])) for p in line] for line in lines]
        if placement == "line-center":
            pieces = [[p for piece in pieces for p in piece]]
        out = [_line_midpoint(piece) for piece in pieces]
        return [m for m in out if m is not None]
    raise DataLayersError(f"unknown geometry type {kind!r}")


def icon_rotation(alignment, placement, segment_angle, icon_rotate, keep_upright):
    """The icon's rotation: icon-rotate alone when aligned to the viewport; plus the segment angle (folded into
    [-90, 90) when icon-keep-upright) when aligned to the map. `auto` is map on lines and viewport on points."""
    if alignment == "auto":
        alignment = "viewport" if placement == "point" else "map"
    if alignment == "viewport":
        return float(icon_rotate)
    angle = float(segment_angle)
    if keep_upright:
        angle = (angle + 90.0) % 180.0 - 90.0
    return angle + float(icon_rotate)


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def sdf_fill(dist, size):
    """MapLibre's symbol_sdf fragment shader fill coverage for an icon: smoothstep about the 0.75 edge with
    gamma 0.105 / icon-size."""
    gamma = EDGE_GAMMA / size
    return _smoothstep(INNER_EDGE - gamma, INNER_EDGE + gamma, dist)


def sdf_halo(dist, size, halo_width, halo_blur):
    """The halo coverage: edge (6 - halo-width / size) / 8, gamma (blur * 1.19 / 8 + 0.105) / size, under the
    fill."""
    gamma = (halo_blur * HALO_BLUR_SCALE / SDF_PX + EDGE_GAMMA) / size
    edge = (6.0 - halo_width / size) / SDF_PX
    return np.minimum(_smoothstep(edge - gamma, edge + gamma, dist), 1.0 - sdf_fill(dist, size))


def _bilinear(sheet, entry, sx, sy):
    """Premultiplied rgba of the sheet at the (sx, sy) sample positions (pixel centres at integers), clamped to the
    entry's rectangle; the straight PNG pixels are premultiplied before interpolation."""
    x0 = entry["x"]
    y0 = entry["y"]
    x1 = x0 + entry["width"] - 1
    y1 = y0 + entry["height"] - 1
    sx = np.clip(sx, x0, x1)
    sy = np.clip(sy, y0, y1)
    ix = np.floor(sx).astype(int)
    iy = np.floor(sy).astype(int)
    fx = (sx - ix)[..., None]
    fy = (sy - iy)[..., None]
    ix2 = np.minimum(ix + 1, x1)
    iy2 = np.minimum(iy + 1, y1)
    img = sheet.astype(float) / 255.0
    img = np.concatenate([img[..., :3] * img[..., 3:4], img[..., 3:4]], axis=-1)
    top = img[iy, ix] * (1 - fx) + img[iy, ix2] * fx
    bottom = img[iy2, ix] * (1 - fx) + img[iy2, ix2] * fx
    return top * (1 - fy) + bottom * fy


def icon_pixels(sheet, entry, quad, size, paint, opacity, width, height):
    """Premultiplied rgba (height, width, 4) of one icon: pixel centres inside the quad sample the sprite
    bilinearly; SDF sprites are coloured by icon-color with the icon-halo under it."""
    px = np.zeros((height, width, 4))
    (ax, ay), (bx, by), _, (dx, dy) = quad
    ux, uy = bx - ax, by - ay
    vx, vy = dx - ax, dy - ay
    det = ux * vy - uy * vx
    if abs(det) < 1e-12:
        return px
    cy, cx = np.mgrid[0:height, 0:width]
    rx = cx + 0.5 - ax
    ry = cy + 0.5 - ay
    u = (rx * vy - ry * vx) / det
    v = (ux * ry - uy * rx) / det
    inside = (u >= 0.0) & (u < 1.0) & (v >= 0.0) & (v < 1.0)
    if not inside.any():
        return px
    sx = entry["x"] + u[inside] * entry["width"] - 0.5
    sy = entry["y"] + v[inside] * entry["height"] - 0.5
    sampled = _bilinear(sheet, entry, sx, sy)
    alpha = value(paint["opacity"], {}, 1.0) * opacity
    if entry["sdf"]:
        dist = sampled[..., 3]
        fill = sdf_fill(dist, size)[..., None]
        fill_col = np.array(premultiplied(value(paint["color"], {}, ICON_PAINT_DEFAULTS["color"])))
        halo_w = value(paint["haloWidth"], {}, 0.0)
        halo = sdf_halo(dist, size, halo_w, value(paint["haloBlur"], {}, 0.0))[..., None] if halo_w > 0 else 0.0
        halo_col = np.array(premultiplied(value(paint["haloColor"], {}, ICON_PAINT_DEFAULTS["haloColor"])))
        fill_px = fill_col * fill
        halo_px = halo_col * halo
        out = fill_px + halo_px * (1.0 - fill_px[..., 3:4])
    else:
        out = sampled
    px[inside] = out * alpha
    return px


# -------------------------------------------------------------------------------------------------------- the world


def world_pixel(lon, lat, zoom):
    """Web Mercator pixel of (lon, lat) at a world of 256 * 2^zoom pixels."""
    n = TILE * 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    phi = math.radians(lat)
    y = (1.0 - math.log(math.tan(phi) + 1.0 / math.cos(phi)) / math.pi) / 2.0 * n
    return (x, y)


def tile_of(lon, lat, z):
    x, y = world_pixel(lon, lat, z)
    n = 2 ** z
    return (min(n - 1, max(0, int(math.floor(x / TILE)))), min(n - 1, max(0, int(math.floor(y / TILE)))))


def _frame(doc):
    m = doc["map"]
    cx, cy = world_pixel(m["centerLon"], m["centerLat"], m["zoom"])
    return {"zoom": m["zoom"], "width": m["width"], "height": m["height"], "rotation": m.get("rotation", 0.0),
            "origin": (cx - m["width"] / 2.0, cy - m["height"] / 2.0)}


def _project(frame):
    ox, oy = frame["origin"]
    z = frame["zoom"]

    def project(p):
        x, y = world_pixel(p[0], p[1], z)
        return (x - ox, y - oy)
    return project


def _visible_tiles(frame, archive, detail):
    z = int(math.floor(frame["zoom"] + detail))
    z = min(max(z, archive["minZoom"]), archive["maxZoom"])
    scale = 2.0 ** (z - frame["zoom"])
    ox, oy = frame["origin"]
    n = 2 ** z
    x0 = int(math.floor(ox * scale / TILE))
    x1 = int(math.floor((ox + frame["width"]) * scale / TILE - 1e-9))
    y0 = max(0, int(math.floor(oy * scale / TILE)))
    y1 = min(n - 1, int(math.floor((oy + frame["height"]) * scale / TILE - 1e-9)))
    tiles = [(x % n, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    return z, (x1 - x0 + 1, y1 - y0 + 1), set(tiles)


def _features(archive, layer_name, z, tiles):
    """The archive layer's features whose first vertex falls in a visible tile, in archive order."""
    out = []
    for f in archive["layers"].get(layer_name, []):
        first = kernel_centres(f["geometry"])[0]
        if tile_of(first[0], first[1], z) in tiles:
            out.append(f)
    return out


def _sprite_sheets(doc, child):
    """{sprite name: (index, sheet pixels)} from the basemap's sprite children."""
    sheets = {}
    for s in child.get("sprites", []):
        index_asset = doc["assets"].get(s["index"])
        image_asset = doc["assets"].get(s["image"])
        if not index_asset or not image_asset or "index" not in index_asset or "pixels" not in image_asset:
            continue
        sheets[s.get("name", "default")] = (sprite_index(index_asset["index"]), np.asarray(image_asset["pixels"]))
    return sheets


def _lookup_icon(name, sheets, style_sprite_ids):
    if ":" in name:
        sprite_id, plain = name.split(":", 1)
    else:
        sprite_id, plain = "default", name
    if sprite_id not in sheets or plain not in sheets[sprite_id][0]:
        return None
    index, sheet = sheets[sprite_id]
    return index[plain], sheet


def warnings(doc):
    return run(doc)["warnings"]


def run(doc):
    """Draw the first basemap's data layers and summarise them."""
    frame = _frame(doc)
    project = _project(frame)
    child = doc["map"]["children"][0]
    archive = doc["tiles"][child["tiles"]]
    z, counts, tiles = _visible_tiles(frame, archive, child.get("detail", 0.0))
    opacity = child.get("opacity", 1.0)
    style = child["style"]
    light_ = light(style.get("light"))
    w, h = frame["width"], frame["height"]
    heat = np.zeros((h, w, 4))
    roofs = np.zeros((h, w, 4))
    icons = np.zeros((h, w, 4))
    peak = 0.0
    covered = 0
    drawn = skipped = 0
    warn = []
    sheets = _sprite_sheets(doc, child) if child.get("icons", True) else {}
    candidates = []
    for layer in style["layers"]:
        features = _features(archive, layer.get("source-layer", ""), z, tiles)
        if layer["type"] == "heatmap":
            paint = heatmap_paint(layer.get("paint", {}))
            pts = []
            for f in features:
                wgt = max(0.0, float(value(paint["weight"], f.get("properties", {}), 1.0)))
                pts.extend((x, y, wgt) for x, y in (project(p) for p in kernel_centres(f["geometry"])))
            radius = paint["radius"] if not _is_expression(paint["radius"]) else HEATMAP_DEFAULTS["radius"]
            intensity = paint["intensity"] if not _is_expression(paint["intensity"]) else 1.0
            t = density(pts, w, h, radius, intensity)
            peak = max(peak, float(t.max()) if t.size else 0.0)
            covered += int((t > 0.0).sum())
            px = heatmap_pixels(pts, w, h, paint, opacity)
            heat = heat * (1.0 - px[..., 3:4]) + px
        elif layer["type"] == "fill-extrusion":
            paint = extrusion_paint(layer.get("paint", {}))
            px, d, s = roof_pixels(features, w, h, paint, light_, frame["rotation"], opacity, project)
            roofs = roofs * (1.0 - px[..., 3:4]) + px
            drawn += d
            skipped += s
        elif layer["type"] == "symbol" and child.get("icons", True):
            layout = icon_layout(layer.get("layout", {}))
            paint = icon_paint(layer.get("paint", {}))
            if layout["image"] is None:
                continue
            layer_candidates = []
            missing = False
            for order, f in enumerate(features):
                props = f.get("properties", {})
                name = value(layout["image"], props, None)
                if name is None or name == "":
                    continue
                found = _lookup_icon(str(name), sheets, None)
                if found is None:
                    missing = True
                    continue
                entry, sheet = found
                size = max(0.0, float(value(layout["size"], props, 1.0)))
                placement = value(layout["placement"], props, "point")
                for anchor_px, seg in candidate_anchors(f["geometry"], placement):
                    anchor_px = project(anchor_px)
                    box = icon_box(anchor_px, entry["displaySize"], size, value(layout["anchor"], props, "center"),
                                   value(layout["offset"], props, (0.0, 0.0)))
                    rot = icon_rotation(value(layout["rotationAlignment"], props, "auto"), placement, seg,
                                        value(layout["rotate"], props, 0.0), value(layout["keepUpright"], props, False))
                    quad = icon_quad(anchor_px, box, rot)
                    sort_key = value(layout["sortKey"], props, None)
                    layer_candidates.append((sort_key if isinstance(sort_key, (int, float)) else math.inf, order, {
                        "text": None, "icon": bounds(quad), "text_overlap": "never",
                        "icon_overlap": overlap_mode(layout, props), "text_ignore": False,
                        "icon_ignore": bool(value(layout["ignorePlacement"], props, False)), "text_optional": False,
                        "icon_optional": bool(value(layout["optional"], props, False)), "text_padding": 0.0,
                        "icon_padding": value(layout["padding"], props, (2.0,) * 4), "text_key": None,
                        "draw": (sheet, entry, quad, size, paint)}))
            if missing:
                warn.append("W-DL1")
            layer_candidates.sort(key=lambda c: (c[0], c[1]))
            candidates.insert(0, [c[2] for c in layer_candidates])  # later layers first
    flat = [c for layer in candidates for c in layer]
    placements = place(flat, w, h)
    placed = dropped = 0
    for c, (_, ok) in zip(flat, placements):
        if not ok:
            dropped += 1
            continue
        placed += 1
        sheet, entry, quad, size, paint = c["draw"]
        px = icon_pixels(sheet, entry, quad, size, paint, opacity, w, h)
        icons = icons * (1.0 - px[..., 3:4]) + px
    return {"zoom": z, "tiles": counts,
            "heatmap": {"peak": round(peak, 6), "covered": covered},
            "extrusion": {"roofs": drawn, "skipped": skipped},
            "icons": {"placed": placed, "dropped": dropped},
            "warnings": sorted(set(warn)),
            "digests": [digest(heat), digest(roofs), digest(icons),
                        digest([[round(v, 3) for v in c["icon"]] + [int(p[1])] for c, p in zip(flat, placements)])]}


def building_prisms(doc):
    """SREP 10 prisms from every fill-extrusion layer of the first basemap, in map pixels (the 3D map's rule)."""
    frame = _frame(doc)
    project = _project(frame)
    child = doc["map"]["children"][0]
    archive = doc["tiles"][child["tiles"]]
    z, _, tiles = _visible_tiles(frame, archive, child.get("detail", 0.0))
    out = []
    for layer in child["style"]["layers"]:
        if layer["type"] == "fill-extrusion":
            paint = extrusion_paint(layer.get("paint", {}))
            out.extend(prisms(_features(archive, layer.get("source-layer", ""), z, tiles), paint, project))
    return out


# ------------------------------------------------------------------------------------------------------- validation


def validate_document(doc):
    """(code, message) pairs sorted by code: DL1 sprite assets, DL2 sprite entries, DL3 heatmap paint, DL4 light,
    DL5 symbol and fill-extrusion properties, DL6 heatmap ramp, DL7 duplicate sprite names, V18 unknown sprite
    attributes."""
    out = []
    for child in doc["map"]["children"]:
        if child.get("kind") != "basemap":
            continue
        names = []
        for s in child.get("sprites", []):
            for k in s:
                if k not in SPRITE_KEYS:
                    out.append(("V18", f"sprite has no attribute {k!r}"))
            name = s.get("name", "default")
            if name in names:
                out.append(("DL7", f"sprite name {name!r} is used twice in one basemap"))
            names.append(name)
            index_asset = doc["assets"].get(s.get("index"))
            image_asset = doc["assets"].get(s.get("image"))
            if not index_asset or "index" not in index_asset:
                out.append(("DL1", f"sprite/@index {s.get('index')!r} is not a file asset"))
            if not image_asset or "pixels" not in image_asset:
                out.append(("DL1", f"sprite/@image {s.get('image')!r} is not an image asset"))
            if index_asset and "index" in index_asset and image_asset and "pixels" in image_asset:
                try:
                    sheet = np.asarray(image_asset["pixels"])
                    check_sprite(sprite_index(index_asset["index"]), sheet.shape[1], sheet.shape[0])
                except DataLayersError as e:
                    out.append(("DL2", str(e)))
        style = child.get("style", {})
        try:
            light(style.get("light"))
        except DataLayersError as e:
            out.append(("DL4", str(e)))
        for layer in style.get("layers", []):
            try:
                if layer["type"] == "heatmap":
                    paint = heatmap_paint(layer.get("paint", {}))
                    try:
                        check_heatmap(paint)
                    except DataLayersError as e:
                        out.append(("DL3", f"{layer.get('id', layer['type'])}: {e}"))
                    try:
                        ramp_stops(paint["color"], "heatmap-density")
                    except DataLayersError as e:
                        out.append(("DL6", f"{layer.get('id', layer['type'])}: {e}"))
                elif layer["type"] == "fill-extrusion":
                    check_extrusion(extrusion_paint(layer.get("paint", {})))
                elif layer["type"] == "symbol":
                    check_symbol(icon_layout(layer.get("layout", {})), icon_paint(layer.get("paint", {})))
            except DataLayersError as e:
                out.append(("DL5", f"{layer.get('id', layer['type'])}: {e}"))
    return sorted(out, key=lambda c: c[0])


# ---------------------------------------------------------------------------------------------------- the example


def _example_sheet():
    sheet = np.zeros((32, 24, 4), dtype=np.uint8)
    sheet[0:8, 0:8] = (200, 30, 30, 255)
    j, i = np.mgrid[0:16, 0:16]
    r = np.hypot(i + 0.5 - 8.0, j + 0.5 - 8.0)
    sheet[0:16, 8:24, 3] = np.clip(np.round(255 * np.clip(0.75 + (5.0 - r) / 8.0, 0.0, 1.0)), 0, 255)
    sheet[16:32, 0:16] = (30, 30, 200, 255)
    return sheet


EXAMPLE_INDEX = {"pin": {"x": 0, "y": 0, "width": 8, "height": 8, "pixelRatio": 1},
                 "dot.sdf": {"x": 8, "y": 0, "width": 16, "height": 16, "pixelRatio": 1, "sdf": True},
                 "big": {"x": 0, "y": 16, "width": 16, "height": 16, "pixelRatio": 2}}


def _square(lon, lat, half):
    return {"type": "Polygon", "coordinates": [[[lon - half, lat - half], [lon + half, lat - half],
                                                [lon + half, lat + half], [lon - half, lat + half],
                                                [lon - half, lat - half]]]}


def example_document():
    poi = [{"geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"w": w}}
           for lon, lat, w in ((0.0, 0.0, 1.0), (0.4, 0.3, 1.0), (-0.5, 0.2, 2.0), (0.2, -0.6, 1.0),
                               (-1.5, -1.0, 0.5), (3.0, 2.0, 1.0), (-4.0, 3.5, 1.0), (5.5, -3.0, 1.5),
                               (-7.0, -5.0, 1.0), (0.1, 0.1, 1.0), (8.0, 6.0, 0.0), (-9.0, 7.5, 1.0))]
    blocks = [dict(geometry=_square(-6.0, -4.0, 1.5), properties={"h": 30, "c": "#999"}),
              dict(geometry=_square(6.0, 4.0, 1.2), properties={"h": 120, "c": "#B08040"}),
              dict(geometry=_square(5.0, -5.0, 1.0), properties={"h": 12, "b": 4, "c": "#6080A0"}),
              dict(geometry=_square(-6.0, 5.0, 1.0), properties={"h": 0, "c": "#FF0000"})]
    pins = [{"geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"icon": icon}}
            for lon, lat, icon in ((0.0, 0.0, "pin"), (0.0, 0.0, "pin"), (-8.0, 2.0, "dot.sdf"), (8.0, -2.0, "big"))]
    return {
        "project": "data-layers",
        "assets": {"sprites": {"kind": "file", "index": json.loads(json.dumps(EXAMPLE_INDEX))},
                   "sheet": {"kind": "image", "pixels": _example_sheet()}},
        "tiles": {"data": {"kind": "vector", "minZoom": 0, "maxZoom": 5,
                           "layers": {"poi": poi, "blocks": blocks, "pins": pins}}},
        "map": {"width": 160, "height": 120, "zoom": 3.0, "centerLon": 0.0, "centerLat": 0.0, "rotation": 0.0,
                "children": [
                    {"kind": "basemap", "id": "base", "tiles": "data", "opacity": 1.0, "detail": 0.0, "icons": True,
                     "sprites": [{"name": "default", "index": "sprites", "image": "sheet"}],
                     "style": {"version": 8, "sprite": [{"id": "default", "url": "sprites/data"}], "light": {},
                               "layers": [
                                   {"id": "heat", "type": "heatmap", "source-layer": "poi",
                                    "paint": {"heatmap-radius": 12, "heatmap-weight": ["get", "w"]}},
                                   {"id": "blocks", "type": "fill-extrusion", "source-layer": "blocks",
                                    "paint": {"fill-extrusion-height": ["get", "h"],
                                              "fill-extrusion-base": ["coalesce", ["get", "b"], 0],
                                              "fill-extrusion-color": ["get", "c"]}},
                                   {"id": "pins", "type": "symbol", "source-layer": "pins",
                                    "layout": {"icon-image": ["get", "icon"], "icon-anchor": "bottom"},
                                    "paint": {"icon-color": "#208020", "icon-halo-color": "#FFFFFF",
                                              "icon-halo-width": 1}},
                                   {"id": "missing", "type": "symbol", "source-layer": "pins",
                                    "layout": {"icon-image": "nowhere"}}]}}]}}


def bad_document():
    """One offender per code: DL1 (sprite index asset unknown), DL2 (an entry outside its sheet), DL3
    (heatmap-radius 0), DL4 (light intensity 2), DL5 (icon-anchor), DL6 (ramp over zoom), DL7 (a sprite name
    twice), V18 (unknown sprite attribute)."""
    doc = example_document()
    doc["assets"]["bad_sprites"] = {"kind": "file", "index": {"pin": {"x": 20, "y": 0, "width": 8, "height": 8,
                                                                    "pixelRatio": 1}}}
    child = doc["map"]["children"][0]
    child["sprites"] = [{"name": "default", "index": "nowhere", "image": "sheet"},
                        {"name": "ext", "index": "bad_sprites", "image": "sheet"},
                        {"name": "good", "index": "sprites", "image": "sheet", "scale": 2},
                        {"name": "good", "index": "sprites", "image": "sheet"}]
    child["style"]["light"] = {"intensity": 2}
    child["style"]["layers"] = [
        {"id": "heat", "type": "heatmap", "source-layer": "poi", "paint": {"heatmap-radius": 0}},
        {"id": "ramp", "type": "heatmap", "source-layer": "poi",
         "paint": {"heatmap-color": ["interpolate", ["linear"], ["zoom"], 0, "#000000", 1, "#FFFFFF"]}},
        {"id": "pins", "type": "symbol", "source-layer": "pins",
         "layout": {"icon-image": ["get", "icon"], "icon-anchor": "middle"}}]
    return doc


# ------------------------------------------------------------------------------------------------------ the table


TABLE = (
    ("the kernel's peak", "round(kernel(0.0, 30.0, 1.0, 1.0), 6)", "0.398942"),
    ("the kernel at one radius", "round(kernel(900.0, 30.0, 1.0, 1.0), 6)", "0.004432"),
    ("the quad's half-side at radius 30", "round(kernel_extent(30.0, 1.0, 1.0), 4)", "38.4575"),
    ("a kernel below the cut-off draws nothing", "kernel_extent(30.0, 0.0001, 1.0)", "0.0"),
    ("two points add", "round(float(density([(10.5, 10.5, 1.0), (10.5, 10.5, 0.5)], 24, 24, 4.0, 1.0)[10, 10]), 6)", "0.598413"),
    ("the default ramp at 0.4", "tuple(round(c, 6) for c in ramp_colour(RAMP, 0.4))", "(0.0, 1.0, 0.5, 1.0)"),
    ("the default ramp at 0.05", "tuple(round(c, 6) for c in ramp_colour(RAMP, 0.05))", "(0.063725, 0.102941, 0.470588, 0.5)"),
    ("a density above 1 is red", "ramp_colour(RAMP, 7.0)", "(1.0, 0.0, 0.0, 1.0)"),
    ("a step ramp", "ramp_colour(ramp_stops(['step', ['heatmap-density'], '#000000', 0.5, '#FFFFFF'], 'heatmap-density'), 0.5)", "(1.0, 1.0, 1.0, 1.0)"),
    ("one point at half opacity", "tuple(round(float(c), 6) for c in heatmap_pixels([(10.5, 10.5, 1.0)], 24, 24, heatmap_paint({'heatmap-radius': 4, 'heatmap-opacity': 0.5}), 1.0)[10, 10])", "(0.0, 0.5, 0.252644, 0.5)"),
    ("the default light direction", "tuple(round(c, 6) for c in light_direction(LIGHT, 0.0))", "(0.2875, -0.497965, 0.995929)"),
    ("the light turned with the map", "tuple(round(c, 6) for c in light_direction(LIGHT, 90.0))", "(0.497965, 0.2875, 0.995929)"),
    ("a grey roof", "tuple(round(c, 6) for c in shade(GREY, UP, LIGHT, 0.0, 0.0, 30.0, True, 1.0))", "(0.628718, 0.628718, 0.628718, 1.0)"),
    ("a black roof", "tuple(round(c, 6) for c in shade((0.0, 0.0, 0.0, 1.0), UP, LIGHT, 0.0, 0.0, 30.0, True, 1.0))", "(0.044878, 0.044878, 0.044878, 1.0)"),
    ("an east wall at its top", "tuple(round(c, 6) for c in shade(GREY, EAST, LIGHT, 1.0, 0.0, 600.0, True, 1.0))", "(0.405563, 0.405563, 0.405563, 1.0)"),
    ("an east wall at its foot", "tuple(round(c, 6) for c in shade(GREY, EAST, LIGHT, 0.0, 0.0, 600.0, True, 1.0))", "(0.340673, 0.340673, 0.340673, 1.0)"),
    ("a west wall", "tuple(round(c, 6) for c in shade(GREY, (-1.0, 0.0, 0.0), LIGHT, 1.0, 0.0, 600.0, True, 1.0))", "(0.315, 0.315, 0.315, 1.0)"),
    ("an orange light floors the channels", "tuple(round(c, 6) for c in shade(GREY, UP, light({'color': '#FF8000'}), 0.0, 0.0, 30.0, True, 1.0))", "(0.628718, 0.315592, 0.3, 1.0)"),
    ("an extrusion", "extrusion({'h': 30}, extrusion_paint({'fill-extrusion-height': ['get', 'h'], 'fill-extrusion-base': 2, 'fill-extrusion-color': '#999'}))", "{'top': 30.0, 'base': 2.0, 'color': (0.6, 0.6, 0.6, 1.0)}"),
    ("a flat extrusion is skipped", "extrusion({}, extrusion_paint({'fill-extrusion-height': ['get', 'h']}))", "None"),
    ("a square with a hole", "int(fill_polygon([[(2.0, 2.0), (6.0, 2.0), (6.0, 6.0), (2.0, 6.0)], [(3.0, 3.0), (3.0, 5.0), (5.0, 5.0), (5.0, 3.0)]], 8, 8).sum())", "12"),
    ("a sprite at pixel ratio 2", "INDEX['big']['displaySize']", "(8.0, 8.0)"),
    ("an icon of a named sprite", "sprite_name('pin', 'ext')", "'ext:pin'"),
    ("an 18 px icon anchored centre", "icon_box((32.0, 32.0), (18.0, 18.0), 1.0, 'center', (0.0, 0.0))", "(23.0, 23.0, 41.0, 41.0)"),
    ("anchored top-left", "icon_box((32.0, 32.0), (18.0, 18.0), 1.0, 'top-left', (0.0, 0.0))", "(32.0, 32.0, 50.0, 50.0)"),
    ("offset (2, -3) at icon-size 2", "icon_box((32.0, 32.0), (18.0, 18.0), 2.0, 'center', (2.0, -3.0))", "(18.0, 8.0, 54.0, 44.0)"),
    ("an 18 x 8 box turned 90 degrees", "tuple(round(c, 6) for c in bounds(icon_quad((32.0, 32.0), (23.0, 28.0, 41.0, 36.0), 90.0)))", "(28.0, 23.0, 36.0, 41.0)"),
    ("icon-text-fit both with padding", "fit_icon_to_text((18.0, 18.0), (-20.0, -6.0, 20.0, 6.0), 'both', (1.0, 2.0, 3.0, 4.0), (0.0, 0.0))", "(-24.0, -7.0, 22.0, 9.0)"),
    ("overlap never", "place([A, B], 100, 100)", "[(False, True), (False, False)]"),
    ("overlap always", "place([A, dict(B, icon_overlap='always')], 100, 100)", "[(False, True), (False, True)]"),
    ("cooperative after never", "place([A, dict(B, icon_overlap='cooperative')], 100, 100)", "[(False, True), (False, False)]"),
    ("cooperative after always", "place([dict(A, icon_overlap='always'), dict(B, icon_overlap='cooperative')], 100, 100)", "[(False, True), (False, True)]"),
    ("text and icon together", "place([A, BOTH], 100, 100)", "[(False, True), (False, False)]"),
    ("icon-optional", "place([A, dict(BOTH, icon_optional=True)], 100, 100)", "[(False, True), (True, False)]"),
    ("keep-upright folds the segment", "icon_rotation('map', 'line', 120.0, 0.0, True)", "-60.0"),
    ("SDF fill at the edge", "round(float(sdf_fill(0.75, 1.0)), 6)", "0.5"),
    ("SDF halo of width 2 at 0.5", "round(float(sdf_halo(0.5, 1.0, 2.0, 0.0)), 6)", "0.5"),
    ("a copied sprite pixel", "tuple(round(float(c), 6) for c in icon_pixels(SHEET, INDEX['pin'], PIN_QUAD, 1.0, icon_paint({}), 1.0, 24, 24)[12, 12])", "(0.784314, 0.117647, 0.117647, 1.0)"),
    ("an SDF icon's centre", "tuple(round(float(c), 6) for c in icon_pixels(SHEET, INDEX['dot.sdf'], DOT_QUAD, 1.0, HALO, 1.0, 16, 16)[8, 8])", "(0.0, 1.0, 0.0, 1.0)"),
    ("an SDF icon's edge with its halo", "tuple(round(float(c), 6) for c in icon_pixels(SHEET, INDEX['dot.sdf'], DOT_QUAD, 1.0, HALO, 1.0, 16, 16)[8, 13])", "(0.808731, 0.100705, 0.0, 0.909436)"),
    ("the tile of a point", "tile_of(-180.0, 70.0, 2)", "(0, 0)"),
    ("the example's zoom and tiles", "(RUN['zoom'], RUN['tiles'])", "(3, (2, 2))"),
    ("the example's heatmap", "(RUN['heatmap']['peak'], RUN['heatmap']['covered'])", "(1.976113, 5671)"),
    ("the example's roofs and icons", "(RUN['extrusion']['roofs'], RUN['extrusion']['skipped'], RUN['icons']['placed'], RUN['icons']['dropped'])", "(3, 1, 3, 1)"),
    ("the example's warnings", "RUN['warnings']", "['W-DL1']"),
    ("the example's digests", "RUN['digests']", "['3df3492b56b8', 'f35876a0f2cd', 'e9f3942b0591', 'f9ad00499edc']"),
    ("the example's prisms", "len(building_prisms(EXAMPLE))", "3"),
    ("the bad document's codes", "[c for c, _ in validate_document(bad_document())]", "['DL1', 'DL2', 'DL3', 'DL4', 'DL5', 'DL6', 'DL7', 'V18']"),
)


_SCOPE = {}


def scope():
    """The names the numeric table evaluates in; built once per process."""
    if _SCOPE:
        return dict(_SCOPE)
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["LIGHT"] = light({})
    s["RAMP"] = ramp_stops(DEFAULT_HEATMAP_COLOR, "heatmap-density")
    s["GREY"] = (0.6, 0.6, 0.6, 1.0)
    s["UP"] = (0.0, 0.0, 1.0)
    s["EAST"] = (1.0, 0.0, 0.0)
    s["EXAMPLE"] = example_document()
    s["SHEET"] = _example_sheet()
    s["INDEX"] = sprite_index(EXAMPLE_INDEX)
    s["PIN_QUAD"] = icon_quad((10.0, 10.0), icon_box((10.0, 10.0), (8.0, 8.0), 1.0, "top-left", (0.0, 0.0)), 0.0)
    s["DOT_QUAD"] = icon_quad((8.0, 8.0), icon_box((8.0, 8.0), (16.0, 16.0), 1.0, "center", (0.0, 0.0)), 0.0)
    s["HALO"] = icon_paint({"icon-color": "#00FF00", "icon-halo-color": "#FF0000", "icon-halo-width": 2})
    s["A"] = {"text": None, "icon": (10.0, 10.0, 20.0, 20.0), "text_overlap": "never", "icon_overlap": "never",
              "text_ignore": False, "icon_ignore": False, "text_optional": False, "icon_optional": False,
              "text_padding": 0.0, "icon_padding": (0.0,) * 4, "text_key": None}
    s["B"] = dict(s["A"], icon=(15.0, 15.0, 25.0, 25.0))
    s["BOTH"] = dict(s["A"], text=(50.0, 50.0, 70.0, 60.0), icon=(5.0, 5.0, 15.0, 15.0))
    s["RUN"] = run(s["EXAMPLE"])
    _SCOPE.update(s)
    return dict(s)


def _same(a, b, rel=5e-4, abs_tol=1e-9):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (set, frozenset)) and isinstance(b, (set, frozenset)):
        return a == b
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), rtol=rel, atol=abs_tol)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)):
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v))
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return repr(float(v) + 0.0)
    if isinstance(v, set):
        return "{" + ", ".join(_fmt(x) for x in sorted(v)) + "}"
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    if isinstance(v, (list, np.ndarray)):
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
