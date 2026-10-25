"""Reference for the draft SREP "Add time-series layers to the map" (M3 of SREP 12).

Feature time on `geoLayer` (`timeBy`, `timeEndBy`, `timeOrigin`, `time`, `trail`, `fade`), trips on `route`
(`timeBy` per-vertex timestamps, `trail`, `fade`, the interpolated head) and the map's data time in style filters
(`["global-state", "time"]` on `basemap`). The trail and fade semantics follow deck.gl's TripsLayer (MIT; the
formulas are re-derived here, no code is copied). Prints the draft's numeric table when run as a script.

Every function is pure: a frame's result depends on the document and the composition time alone, so any frame
rendered alone equals the same frame rendered after the others (the seek check).
"""
import datetime
import hashlib
import json
import math
import re

import numpy as np

R = 6378137.0
TILE = 256
DIGEST_DECIMALS = 3

GEO_TIME_DEFAULTS = {"timeBy": None, "timeEndBy": None, "timeOrigin": 0.0, "time": 0.0, "trail": 0.0, "fade": False}
ROUTE_TRIP_DEFAULTS = {"timeBy": None, "timeOrigin": 0.0, "time": 0.0, "trail": 120.0, "fade": True,
                       "stroke": "#FFFFFF", "strokeWidth": 3.0, "opacity": 1.0, "headRadius": 0.0, "headFill": None}
BASEMAP_TIME_DEFAULTS = {"timeOrigin": 0.0, "time": 0.0}
STATES = ("visible", "pending", "expired", "ended", "unreadable")
TRIP_STATES = ("pending", "running", "complete", "gone")

TIME_ATTRIBUTES = ("timeBy", "timeEndBy", "timeOrigin", "time", "trail", "fade")
KNOWN_ATTRIBUTES = {
    "basemap": {"kind", "id", "tiles", "mapStyle", "opacity", "detail", "labels", "attribution", "icons", "sprites",
                "style", "timeOrigin", "time"},
    "geoLayer": {"kind", "id", "geo", "filter", "fill", "stroke", "strokeWidth", "opacity", "fillBy", "palette",
                 "domain", "scale", "noData", "keyBy", "label", "textStyle", "pointRadius", "progress",
                 *TIME_ATTRIBUTES},
    "route": {"kind", "id", "points", "geo", "filter", "progress", "stroke", "strokeWidth", "dash", "opacity",
              "headRadius", "headFill", "timeBy", "timeOrigin", "time", "trail", "fade"},
}

NAMED_COLOURS = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "lime": (0, 255, 0),
                 "blue": (0, 0, 255), "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
                 "gray": (128, 128, 128), "grey": (128, 128, 128), "orange": (255, 165, 0)}


class TimeSeriesError(ValueError):
    """A time, document or trip that the draft rejects."""


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
    """A colour as straight (r, g, b, a) integers 0..255: #RGB, #RRGGBB, #RRGGBBAA, rgb(), rgba() or a name."""
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
            raise TimeSeriesError(f"rgb()/rgba() needs three or four components: {value!r}")
        try:
            rgb = tuple(int(round(float(p))) for p in parts[:3])
            a = int(round(255 * float(parts[3]))) if len(parts) == 4 else 255
        except ValueError:
            raise TimeSeriesError(f"a numeric colour component is required: {value!r}") from None
        if not all(0 <= c <= 255 for c in rgb + (a,)):
            raise TimeSeriesError(f"colour components must lie in 0..255 and alpha in 0..1: {value!r}")
        return rgb + (a,)
    if s.lower() in NAMED_COLOURS:
        return NAMED_COLOURS[s.lower()] + (255,)
    if s.lower() == "transparent":
        return (0, 0, 0, 0)
    raise TimeSeriesError(f"a colour literal is required: {value!r}")


def straight(value):
    return tuple(c / 255.0 for c in colour(value))


def premultiplied(value):
    r, g, b, a = straight(value)
    return (r * a, g * a, b * a, a)


def _is_number(v):
    return isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, (bool, np.bool_)) \
        and math.isfinite(v)


# ------------------------------------------------------------------------------------------------------- data time


_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})")
_EPOCH = datetime.datetime(1970, 1, 1)


def parse_time(value):
    """A time as seconds: a finite number, or an ISO 8601 date-time with seconds and a zone (`Z` or `±HH:MM`),
    read as seconds since 1970-01-01T00:00:00Z. Anything else raises TimeSeriesError."""
    if _is_number(value):
        return float(value)
    if not isinstance(value, str):
        raise TimeSeriesError(f"a time is a number or an ISO 8601 date-time: {value!r}")
    s = value.strip()
    try:
        f = float(s)
    except ValueError:
        f = None
    if f is not None:
        if not math.isfinite(f):
            raise TimeSeriesError(f"a time must be finite: {value!r}")
        return f
    m = _ISO.fullmatch(s)
    if not m:
        raise TimeSeriesError(f"a time is a number or an ISO 8601 date-time with seconds and a zone: {value!r}")
    y, mo, d, hh, mm, ss = (int(g) for g in m.groups()[:6])
    try:
        dt = datetime.datetime(y, mo, d, hh, mm, ss)
    except ValueError as e:
        raise TimeSeriesError(f"not a calendar date-time: {value!r} ({e})") from None
    seconds = (dt - _EPOCH).total_seconds()
    if m.group(7):
        seconds += float("0" + m.group(7))
    zone = m.group(8)
    if zone != "Z":
        sign = 1.0 if zone[0] == "+" else -1.0
        seconds -= sign * (int(zone[1:3]) * 3600 + int(zone[4:6]) * 60)
    return seconds


def data_time(origin, time):
    """The data time T: the origin (a time) plus the element's `time` offset in seconds."""
    return parse_time(origin) + float(time)


def animated(value, t):
    """An animatable number: a constant, or {"keys": [[t, v], ...]} read linearly between keys and clamped to the
    first and last key. Equal key times jump to the later value."""
    if _is_number(value):
        return float(value)
    if not isinstance(value, dict) or "keys" not in value:
        raise TimeSeriesError(f"an animatable number is a number or keys: {value!r}")
    keys = []
    for k in value["keys"]:
        if not isinstance(k, (list, tuple)) or len(k) != 2 or not _is_number(k[0]) or not _is_number(k[1]):
            raise TimeSeriesError(f"a key is a [time, value] pair: {k!r}")
        keys.append((float(k[0]), float(k[1])))
    if not keys:
        raise TimeSeriesError("keys must not be empty")
    if any(b[0] < a[0] for a, b in zip(keys, keys[1:])):
        raise TimeSeriesError("key times must not decrease")
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    i = max(j for j in range(len(keys)) if keys[j][0] <= t)
    (t0, v0), (t1, v1) = keys[i], keys[i + 1]
    if t1 == t0:
        return v1
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


# -------------------------------------------------------------------------------------------------- feature filters


def feature_state(properties, T, time_by, end_by, trail, fade):
    """Why a feature is drawn or not at data time T: `visible`, `pending` (its time is after T), `ended` (its end
    property is at or before T), `expired` (older than the trail; with fade, when its alpha reaches 0) or
    `unreadable` (its time or end property is missing or not a time)."""
    try:
        tau = parse_time(properties[time_by]) if time_by in properties else None
        end = parse_time(properties[end_by]) if end_by is not None and end_by in properties else None
    except TimeSeriesError:
        return "unreadable"
    if tau is None:
        return "unreadable"
    if tau > T:
        return "pending"
    if end is not None and end <= T:
        return "ended"
    if trail > 0:
        age = T - tau
        if (fade and age >= trail) or (not fade and age > trail):
            return "expired"
    return "visible"


def feature_alpha(properties, T, time_by, end_by, trail, fade):
    """The feature's alpha factor at T, or None when it is not drawn: 1, or 1 − (T − τ)/trail when fading."""
    if feature_state(properties, T, time_by, end_by, trail, fade) != "visible":
        return None
    if fade and trail > 0:
        tau = parse_time(properties[time_by])
        return min(1.0, max(0.0, 1.0 - (T - tau) / trail))
    return 1.0


# ------------------------------------------------------------------------------------------------------------ trips


def check_timestamps(path, stamps):
    """A route feature's timestamps: one time per vertex, non-decreasing. Returns them as floats."""
    if not isinstance(stamps, (list, tuple)):
        raise TimeSeriesError(f"timestamps must be a list: {stamps!r}")
    if len(stamps) != len(path):
        raise TimeSeriesError(f"{len(stamps)} timestamps for {len(path)} vertices")
    out = [parse_time(s) for s in stamps]
    if any(b < a for a, b in zip(out, out[1:])):
        raise TimeSeriesError("timestamps must not decrease")
    return out


def interpolate(path, stamps, t):
    """The position along the path at time t: the vertex at or before t and the next one, linearly by time;
    clamped to the first and last vertex. Equal stamps jump to the later vertex."""
    if t < stamps[0] or len(path) == 1:
        return tuple(float(c) for c in path[0])
    if t >= stamps[-1]:
        return tuple(float(c) for c in path[-1])
    i = max(j for j in range(len(stamps) - 1) if stamps[j] <= t)
    (x0, y0), (x1, y1) = path[i], path[i + 1]
    t0, t1 = stamps[i], stamps[i + 1]
    u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
    return (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)


def trip_state(path, stamps, T, trail):
    """`pending` before the first stamp, `running` until the last, `complete` after it, `gone` once the trail
    (when positive) has passed the last stamp."""
    if T < stamps[0]:
        return "pending"
    if trail > 0 and T - stamps[-1] > trail:
        return "gone"
    if T >= stamps[-1]:
        return "complete"
    return "running"


def trip_window(path, stamps, T, trail, fade):
    """The drawn part of a trip at T: the vertices from T − trail (the tail, interpolated) to the head at T,
    with the alpha of each point (1 − (T − τ)/trail when fading, else 1). None when pending or gone."""
    state = trip_state(path, stamps, T, trail)
    if state in ("pending", "gone"):
        return None
    pts, ts = [], []
    tail = trail > 0 and T - trail > stamps[0]
    if tail:
        s = T - trail
        pts.append(interpolate(path, stamps, s))
        ts.append(s)
    for p, st in zip(path, stamps):
        if tail and st <= T - trail:
            continue
        if st < T or T >= stamps[-1]:
            pts.append(tuple(float(c) for c in p))
            ts.append(st)
    if T < stamps[-1]:
        pts.append(interpolate(path, stamps, T))
        ts.append(T)
    if fade and trail > 0:
        alphas = [min(1.0, max(0.0, 1.0 - (T - t) / trail)) for t in ts]
    else:
        alphas = [1.0] * len(ts)
    return {"points": pts, "alphas": alphas, "head": pts[-1]}


# --------------------------------------------------------------------------------------------------------- drawing


def _over(dst, src):
    return src + dst * (1.0 - src[..., 3:4])


def stroke_pixels(points, alphas, width, stroke, opacity, w, h):
    """A polyline stroked with round caps and joins: a pixel is covered when its centre lies within width/2 of the
    path, and takes the path's alpha at the nearest point (linear along each segment), premultiplied."""
    px = np.zeros((h, w, 4), dtype=np.float64)
    if not points:
        return px
    base = np.array(premultiplied(stroke)) * float(opacity)
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = xs + 0.5, ys + 0.5
    best = np.full((h, w), np.inf)
    abest = np.zeros((h, w))
    segments = list(zip(points, points[1:], alphas, alphas[1:])) or [(points[0], points[0], alphas[0], alphas[0])]
    for (x0, y0), (x1, y1), a0, a1 in segments:
        dx, dy = x1 - x0, y1 - y0
        l2 = dx * dx + dy * dy
        u = np.zeros_like(cx, dtype=float) if l2 == 0 else np.clip(((cx - x0) * dx + (cy - y0) * dy) / l2, 0.0, 1.0)
        d = np.hypot(cx - (x0 + u * dx), cy - (y0 + u * dy))
        closer = d < best
        best = np.where(closer, d, best)
        abest = np.where(closer, a0 + (a1 - a0) * u, abest)
    mask = best <= width / 2.0
    px[mask] = base[None, :] * abest[mask][:, None]
    return px


def head_pixels(centre, radius, fill, opacity, w, h):
    """A disc: pixels whose centre lies within the radius, premultiplied."""
    px = np.zeros((h, w, 4), dtype=np.float64)
    if radius <= 0:
        return px
    ys, xs = np.mgrid[0:h, 0:w]
    mask = np.hypot(xs + 0.5 - centre[0], ys + 0.5 - centre[1]) <= radius
    px[mask] = np.array(premultiplied(fill)) * float(opacity)
    return px


def trip_pixels(window, paint, w, h):
    """A trip window stroked, then its head dot (when headRadius > 0) over it."""
    px = stroke_pixels(window["points"], window["alphas"], paint["strokeWidth"], paint["stroke"], paint["opacity"],
                       w, h)
    if paint["headRadius"] > 0:
        fill = paint["headFill"] if paint["headFill"] is not None else paint["stroke"]
        px = _over(px, head_pixels(window["head"], paint["headRadius"], fill, paint["opacity"], w, h))
    return px


# ------------------------------------------------------------------------------------------- style filters by time


_TOKEN = re.compile(r"\{([^{}]+)\}")


def _is_expression(v):
    return isinstance(v, list) and v and isinstance(v[0], str)


def evaluate(expr, properties, state):
    """A constant, a legacy `{token}` string or an expression over the feature's properties and the global state
    (SREP 9's subset that data layers use, plus `global-state`). Raises TimeSeriesError when it fails."""
    if isinstance(expr, str):
        return _TOKEN.sub(lambda m: str(properties.get(m.group(1), "")), expr)
    if not _is_expression(expr):
        return expr
    op, args = expr[0], expr[1:]
    ev = lambda e: evaluate(e, properties, state)  # noqa: E731
    try:
        if op == "literal":
            return args[0]
        if op == "global-state":
            return state.get(ev(args[0]))
        if op == "get":
            key = ev(args[0])
            if key not in properties:
                raise TimeSeriesError(f"property {key!r} is missing")
            return properties[key]
        if op == "has":
            return ev(args[0]) in properties
        if op == "coalesce":
            for a in args:
                try:
                    v = ev(a)
                except TimeSeriesError:
                    continue
                if v is not None:
                    return v
            raise TimeSeriesError("coalesce found no value")
        if op == "to-number":
            return parse_time(ev(args[0]))
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
                raise TimeSeriesError("division by zero")
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
        if isinstance(e, TimeSeriesError):
            raise
        raise TimeSeriesError(f"expression failed: {e}") from None
    raise TimeSeriesError(f"operator {op!r} is not supported")


def keep_feature(filter_expr, properties, state):
    """SREP 9's filter rule with the data time in the global state: no filter keeps, a failing filter rejects."""
    if filter_expr is None:
        return True
    try:
        return bool(evaluate(filter_expr, properties, state))
    except TimeSeriesError:
        return False


# ----------------------------------------------------------------------------------------------------- the document


def world_pixel(lon, lat, zoom):
    """Web Mercator pixel of (lon, lat) at a world of 256 * 2^zoom pixels."""
    n = TILE * 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    phi = math.radians(lat)
    y = (1.0 - math.log(math.tan(phi) + 1.0 / math.cos(phi)) / math.pi) / 2.0 * n
    return (x, y)


def _frame(doc):
    m = doc["map"]
    cx, cy = world_pixel(m["centerLon"], m["centerLat"], m["zoom"])
    return {"zoom": m["zoom"], "width": m["width"], "height": m["height"],
            "origin": (cx - m["width"] / 2.0, cy - m["height"] / 2.0)}


def _project(frame):
    ox, oy = frame["origin"]
    z = frame["zoom"]

    def project(p):
        x, y = world_pixel(p[0], p[1], z)
        return (x - ox, y - oy)
    return project


def _filter_string(filter_, features):
    """The schema's `filter`: "prop=value;prop!=value" conditions, all of which must hold."""
    if not filter_:
        return list(features)
    conds = []
    for part in filter_.split(";"):
        part = part.strip()
        if "!=" in part:
            k, v = part.split("!=", 1)
            conds.append((k.strip(), v.strip(), False))
        elif "=" in part:
            k, v = part.split("=", 1)
            conds.append((k.strip(), v.strip(), True))
    out = []
    for f in features:
        props = f.get("properties", {})
        if all((str(props.get(k)) == v) == eq for k, v, eq in conds):
            out.append(f)
    return out


def _element_time(child, defaults, t):
    origin = child.get("timeOrigin", defaults["timeOrigin"])
    return data_time(origin, animated(child.get("time", defaults["time"]), t))


def _first_point(geometry):
    g = geometry["type"]
    c = geometry["coordinates"]
    if g == "Point":
        return c
    if g in ("LineString", "MultiPoint"):
        return c[0]
    return c[0][0]


def _run_basemap(child, doc, T):
    archive = doc["tiles"][child["tiles"]]
    kept = dropped = 0
    kept_ids = []
    state = {"time": T}
    for layer in child.get("style", {}).get("layers", []):
        features = archive["layers"].get(layer.get("source-layer"), [])
        for i, f in enumerate(features):
            if keep_feature(layer.get("filter"), f.get("properties", {}), state):
                kept += 1
                kept_ids.append((layer["id"], i))
            else:
                dropped += 1
    return {"kept": kept, "dropped": dropped}, kept_ids


def _run_geo_layer(child, doc, T, frame, warnings):
    project = _project(frame)
    cfg = {k: child.get(k, v) for k, v in GEO_TIME_DEFAULTS.items()}
    features = _filter_string(child.get("filter"), doc["assets"][child["geo"]]["features"])
    px = np.zeros((frame["height"], frame["width"], 4))
    alphas = []
    hidden = 0
    for f in features:
        props = f.get("properties", {})
        if cfg["timeBy"] is None:
            a = 1.0
        else:
            state = feature_state(props, T, cfg["timeBy"], cfg["timeEndBy"], cfg["trail"], cfg["fade"])
            if state == "unreadable":
                warnings.add("W-TS2")
            a = feature_alpha(props, T, cfg["timeBy"], cfg["timeEndBy"], cfg["trail"], cfg["fade"])
        if a is None:
            hidden += 1
            continue
        alphas.append(a)
        px = _over(px, head_pixels(project(_first_point(f["geometry"])), child.get("pointRadius", 3.0),
                                   child.get("fill", "#D9D9D9"), child.get("opacity", 1.0) * a,
                                   frame["width"], frame["height"]))
    return {"visible": len(alphas), "hidden": hidden, "alphas": alphas}, px


def _run_route(child, doc, T, frame, warnings):
    project = _project(frame)
    paint = {k: child.get(k, v) for k, v in ROUTE_TRIP_DEFAULTS.items()}
    px = np.zeros((frame["height"], frame["width"], 4))
    out = {"drawn": 0, "pending": 0, "gone": 0, "heads": []}
    features = _filter_string(child.get("filter"), doc["assets"][child["geo"]]["features"])
    for f in features:
        if f["geometry"]["type"] != "LineString":
            continue
        path = [project(c) for c in f["geometry"]["coordinates"]]
        try:
            stamps = check_timestamps(path, f.get("properties", {}).get(paint["timeBy"]))
        except TimeSeriesError:
            warnings.add("W-TS1")
            continue
        state = trip_state(path, stamps, T, paint["trail"])
        if state in ("pending", "gone"):
            out[state] += 1
            continue
        window = trip_window(path, stamps, T, paint["trail"], paint["fade"])
        out["drawn"] += 1
        out["heads"].append(window["head"])
        px = _over(px, trip_pixels(window, paint, frame["width"], frame["height"]))
    return out, px


def run(doc, t):
    """One frame of the example document at composition time t: the data time of every timed element, the
    basemap's filter counts, each geoLayer's visible features and alphas, each route's trips, warnings and the
    digests of the drawn pixels."""
    frame = _frame(doc)
    warnings = set()
    out = {"T": {}}
    digests = []
    for child in doc["map"]["children"]:
        kind = child["kind"]
        if kind == "basemap":
            T = _element_time(child, BASEMAP_TIME_DEFAULTS, t)
            out["T"][child["id"]] = T
            counts, kept = _run_basemap(child, doc, T)
            out["basemap"] = counts
            digests.append(digest(kept))
        elif kind == "geoLayer":
            T = _element_time(child, GEO_TIME_DEFAULTS, t)
            out["T"][child["id"]] = T
            summary, px = _run_geo_layer(child, doc, T, frame, warnings)
            out[child["id"]] = summary
            digests.append(digest(px))
        elif kind == "route":
            T = _element_time(child, ROUTE_TRIP_DEFAULTS, t)
            out["T"][child["id"]] = T
            summary, px = _run_route(child, doc, T, frame, warnings)
            out[child["id"]] = summary
            digests.append(digest(px))
    out["warnings"] = sorted(warnings)
    digests.append(digest(out["T"]))
    out["digests"] = digests
    return out


# ------------------------------------------------------------------------------------------------------ validation


def _check_time_attributes(child, defaults, errors, what):
    if "timeOrigin" in child:
        try:
            parse_time(child["timeOrigin"])
        except TimeSeriesError as e:
            errors.append(("TS1", f"{what}: timeOrigin: {e}"))
    if "time" in child:
        try:
            animated(child["time"], 0.0)
        except TimeSeriesError as e:
            errors.append(("TS1", f"{what}: time: {e}"))
    if "trail" in child or "fade" in child:
        trail = child.get("trail", defaults["trail"])
        fade = child.get("fade", defaults["fade"])
        if not _is_number(trail) or trail < 0:
            errors.append(("TS2", f"{what}: trail must be a number of at least 0: {trail!r}"))
        elif not isinstance(fade, bool):
            errors.append(("TS2", f"{what}: fade must be a boolean: {fade!r}"))
        elif fade and trail == 0:
            errors.append(("TS2", f"{what}: fade needs a positive trail"))


def validate_document(doc):
    """The draft's rules on a document: TS1 (timeOrigin or time not a time), TS2 (trail negative, fade not a
    boolean, or fade with trail 0), TS3 (time attributes without timeBy, or a route's timeBy without geo), TS4
    (timeEndBy equal to timeBy), V19 (an attribute the schema does not declare). Sorted by code."""
    errors = []
    for i, child in enumerate(doc["map"]["children"]):
        kind = child["kind"]
        what = f"{kind} {child.get('id', i)}"
        unknown = sorted(set(child) - KNOWN_ATTRIBUTES.get(kind, set(child)))
        if unknown:
            errors.append(("V19", f"{what}: unknown attributes {unknown}"))
        if kind == "basemap":
            _check_time_attributes(child, {"trail": 0.0, "fade": False}, errors, what)
        elif kind == "geoLayer":
            _check_time_attributes(child, GEO_TIME_DEFAULTS, errors, what)
            timed = [k for k in ("timeEndBy", "timeOrigin", "time", "trail", "fade") if k in child]
            if timed and "timeBy" not in child:
                errors.append(("TS3", f"{what}: {timed} need timeBy"))
            elif child.get("timeEndBy") is not None and child.get("timeEndBy") == child.get("timeBy"):
                errors.append(("TS4", f"{what}: timeEndBy must differ from timeBy"))
        elif kind == "route":
            _check_time_attributes(child, ROUTE_TRIP_DEFAULTS, errors, what)
            timed = [k for k in ("timeOrigin", "time", "trail", "fade") if k in child]
            if timed and "timeBy" not in child:
                errors.append(("TS3", f"{what}: {timed} need timeBy"))
            elif "timeBy" in child and "geo" not in child:
                errors.append(("TS3", f"{what}: timeBy needs geo (points carry no properties)"))
    return sorted(errors, key=lambda e: e[0])


# --------------------------------------------------------------------------------------------------------- example


def _point(lon, lat, **props):
    return {"geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


def _line(coords, **props):
    return {"geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]}, "properties": props}


def example_document():
    """A 160×120 map at zoom 3 over (0, 0), twelve seconds long. The basemap's data time runs 0..480 and its
    style keeps the quakes whose time has come; the events layer plays six hours of 2024-01-01 with a one-hour
    fading trail; the trips route plays two tracks with the default two-minute trail."""
    quakes = [_point(lon, 1.0 + 0.5 * i, time=100 * i) for i, lon in enumerate((-2.0, -1.0, 0.0, 1.0, 2.0))]
    events = [_point(-1.5, -1.0, time="2024-01-01T00:00:00Z"),
              _point(-0.5, -1.0, time="2024-01-01T02:30:00Z"),
              _point(0.5, -1.0, time="2024-01-01T03:00:00Z"),
              _point(1.5, -1.0, time="2024-01-01T05:30:00Z"),
              _point(-1.0, -2.0, time="2024-01-01T01:00:00Z"),
              _point(0.0, -2.0, time="2024-01-01T02:45:00Z", end="2024-01-01T02:50:00Z"),
              _point(1.0, -2.0, time="soon")]
    tracks = [_line([(-1.0, 0.0), (-0.4, 0.0), (0.2, 0.0)], stamps=[0, 240, 350]),
              _line([(0.0, 1.0), (0.5, 1.0)], stamps=[300, 340]),
              _line([(0.0, 2.0), (0.5, 2.0), (1.0, 2.0)], stamps=[0, 10])]
    return {
        "project": "time-series",
        "assets": {"events": {"kind": "geo", "features": events}, "tracks": {"kind": "geo", "features": tracks}},
        "tiles": {"data": {"kind": "vector", "minZoom": 0, "maxZoom": 5, "layers": {"quakes": quakes}}},
        "map": {"width": 160, "height": 120, "zoom": 3.0, "centerLon": 0.0, "centerLat": 0.0,
                "children": [
                    {"kind": "basemap", "id": "base", "tiles": "data", "timeOrigin": 0.0,
                     "time": {"keys": [[0.0, 0.0], [12.0, 480.0]]},
                     "style": {"version": 8, "layers": [
                         {"id": "quakes", "type": "circle", "source-layer": "quakes",
                          "filter": ["<=", ["get", "time"], ["global-state", "time"]]}]}},
                    {"kind": "geoLayer", "id": "events", "geo": "events", "fill": "#FF8000", "pointRadius": 3.0,
                     "timeBy": "time", "timeEndBy": "end", "timeOrigin": "2024-01-01T00:00:00Z",
                     "time": {"keys": [[0.0, 0.0], [12.0, 21600.0]]}, "trail": 3600.0, "fade": True},
                    {"kind": "route", "id": "trips", "geo": "tracks", "timeBy": "stamps", "timeOrigin": 0.0,
                     "time": {"keys": [[0.0, 0.0], [12.0, 480.0]]}, "stroke": "#40C0FF", "strokeWidth": 3.0,
                     "headRadius": 3.0, "headFill": "#FFFFFF"}]}}


def bad_document():
    """One offender per code: TS1 (a basemap timeOrigin that is not a time), TS2 (a negative trail), TS3 (a
    route's timeBy without geo), TS4 (timeEndBy equal to timeBy), V19 (an attribute the schema does not declare)."""
    doc = example_document()
    doc["map"]["children"][0]["timeOrigin"] = "yesterday"
    doc["map"]["children"][1]["trail"] = -1.0
    doc["map"]["children"][2] = {"kind": "route", "id": "trips", "points": [(0.0, 0.0), (1.0, 1.0)],
                                 "timeBy": "stamps"}
    doc["map"]["children"].append({"kind": "geoLayer", "id": "twice", "geo": "events", "timeBy": "time",
                                   "timeEndBy": "time"})
    doc["map"]["children"].append({"kind": "route", "id": "scaled", "geo": "tracks", "timeBy": "stamps",
                                   "timeScale": 2})
    return doc


# ------------------------------------------------------------------------------------------------------- the table


TABLE = (
    ("an ISO 8601 date-time as seconds", "parse_time('2024-03-01T12:00:00Z')", "1709294400.0"),
    ("a zone offset", "parse_time('2024-03-01T12:00:00+02:00')", "1709287200.0"),
    ("a number with blanks", "parse_time(' 42 ')", "42.0"),
    ("the data time", "data_time('2024-01-01T00:00:00Z', 3600.0)", "1704070800.0"),
    ("an animated time between keys", "animated({'keys': [[0.0, 0.0], [10.0, 100.0]]}, 5.0)", "50.0"),
    ("a feature half-way down its trail", "feature_alpha({'time': 1000.0}, 1050.0, 'time', None, 100.0, True)", "0.5"),
    ("a pending feature", "feature_state({'time': 20}, 10.0, 'time', None, 0.0, False)", "'pending'"),
    ("an ended feature", "feature_state({'time': 0, 'end': 5}, 10.0, 'time', 'end', 0.0, False)", "'ended'"),
    ("an unreadable feature", "feature_state({'time': 'soon'}, 10.0, 'time', None, 0.0, False)", "'unreadable'"),
    ("timestamps read as times", "check_timestamps(PATH, ISO_STAMPS)", "[0.0, 10.0, 30.0]"),
    ("the head on the first segment", "interpolate(PATH, STAMPS, 5.0)", "(5.0, 0.0)"),
    ("the head on the second segment", "interpolate(PATH, STAMPS, 20.0)", "(10.0, 5.0)"),
    ("the head on equal stamps", "interpolate([(0.0, 0.0), (4.0, 0.0), (8.0, 0.0)], [0.0, 0.0, 8.0], 0.0)", "(4.0, 0.0)"),
    ("the trip states", "[trip_state(PATH, STAMPS, t, 120.0) for t in (-1.0, 20.0, 150.0, 200.0)]", "['pending', 'running', 'complete', 'gone']"),
    ("the window's points with a short trail", "W['points']", "[(5.0, 0.0), (10.0, 0.0), (10.0, 5.0)]"),
    ("the window's alphas", "[round(a, 6) for a in W['alphas']]", "[0.0, 0.333333, 1.0]"),
    ("the tail's alpha after the trip", "round(trip_window(PATH, STAMPS, 40.0, 120.0, True)['alphas'][0], 6)", "0.666667"),
    ("pixels of a 2-px stroke with round caps", "int((PX[..., 3] > 0).sum())", "16"),
    ("the stroke's alpha near its end", "round(float(PX2[4, 7][3]), 6)", "0.916667"),
    ("pixels of a head of radius 2", "int((HEAD[..., 3] > 0).sum())", "12"),
    ("a filter on the data time", "evaluate(FILTER, {'time': 5}, {'time': 10.0})", "True"),
    ("the example's data times at six seconds", "RUN['T']", "{'base': 240.0, 'events': 1704078000.0, 'trips': 240.0}"),
    ("the basemap's filter counts", "RUN['basemap']", "{'kept': 3, 'dropped': 2}"),
    ("the events drawn and hidden", "(RUN['events']['visible'], RUN['events']['hidden'])", "(2, 5)"),
    ("the events' alphas", "RUN['events']['alphas']", "[0.5, 1.0]"),
    ("the trips drawn, pending and gone", "tuple(RUN['trips'][k] for k in ('drawn', 'pending', 'gone'))", "(1, 1, 0)"),
    ("the first trip's head pixel", "tuple(round(c, 3) for c in RUN['trips']['heads'][0])", "(77.724, 60.0)"),
    ("the example's warnings", "RUN['warnings']", "['W-TS1', 'W-TS2']"),
    ("the example's digests", "RUN['digests']", "['641da128a8bc', '031f84f9cffc', 'a7a297cca286', 'd55beb01b780']"),
    ("the bad document's codes", "[c for c, _ in validate_document(bad_document())]", "['TS1', 'TS2', 'TS3', 'TS4', 'V19']"),
    ("the seek check", "run(EXAMPLE, 6.0) == RUN", "True"),
)

PATH = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
STAMPS = [0.0, 10.0, 30.0]
ISO_STAMPS = ["1970-01-01T00:00:00Z", "1970-01-01T00:00:10Z", 30]
FILTER = ["<=", ["get", "time"], ["global-state", "time"]]

_SCOPE = {}


def scope():
    """The names the numeric table evaluates in; built once per process."""
    if _SCOPE:
        return dict(_SCOPE)
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["EXAMPLE"] = example_document()
    s["W"] = trip_window(PATH, STAMPS, 20.0, 15.0, True)
    s["PX"] = stroke_pixels([(2.0, 5.0), (8.0, 5.0)], [1.0, 1.0], 2.0, "#FF0000", 1.0, 10, 10)
    s["HEAD"] = head_pixels((5.0, 5.0), 2.0, "#00FF00", 1.0, 10, 10)
    s["PX2"] = stroke_pixels([(2.0, 5.0), (8.0, 5.0)], [0.0, 1.0], 2.0, "#FFFFFF", 1.0, 10, 10)
    s["RUN"] = run(s["EXAMPLE"], 6.0)
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
