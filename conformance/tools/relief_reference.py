"""Reference for the draft SREP "Add relief layers to the map" (M1 of SREP 12).

Basemap styles gain the MapLibre `raster`, `hillshade` and `color-relief` layer types that SREP 9 skips, reading
elevation tiles from `basemap/@elevation`; a `contours` child of `map` draws level lines by marching squares.
Heights are decoded from Terrarium or Mapbox tiles (SREP 10), signed, and assembled into one mosaic of the visible
tile set with a one-pixel border from the neighbouring tiles (x modulo 2^z across the antimeridian, rows
replicated beyond the poles), so no seam appears across tiles, the poles or the antimeridian. The Horn gradient
is taken in metres per metre with the Mercator ground size of each row. The hillshade methods basic, combined,
igor and multidirectional reproduce gdaldem's 8-bit levels (GDAL, MIT); standard is MapLibre's legacy formula
(BSD-3). Colour relief follows gdaldem's lookup, the raster adjustments MapLibre's raster shader. On a globe the
layers join the SREP 10 drape from a whole-world mosaic at the drape's zoom. Requires numpy.
`python relief_reference.py` prints the numeric table of the draft's conformance section.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

import numpy as np

R = 6378137.0
TILE = 256
MERCATOR_LIMIT = math.degrees(math.atan(math.sinh(math.pi)))   # 85.0511287798 degrees
METHODS = ("standard", "basic", "combined", "igor", "multidirectional")
ENCODINGS = ("terrarium", "mapbox")
RESAMPLINGS = ("linear", "nearest")
MODES = ("interpolate", "step")
ANCHORS = ("viewport", "map")
MAX_LEVELS = 4096           # contour levels a frame may draw
MAX_MOSAIC = 8192           # pixels along a side of the mosaic
DIGEST_DECIMALS = 3
HILLSHADE_DEFAULTS = {"direction": (335.0,), "altitude": (45.0,), "anchor": "viewport", "exaggeration": 0.5,
                      "shadow": ("#000000FF",), "highlight": ("#FFFFFFFF",), "accent": "#000000FF",
                      "method": "standard"}
RASTER_DEFAULTS = {"opacity": 1.0, "hueRotate": 0.0, "brightnessMin": 0.0, "brightnessMax": 1.0,
                   "saturation": 0.0, "contrast": 0.0, "resampling": "linear"}
RELIEF_DEFAULTS = {"opacity": 1.0, "color": None}
CONTOURS_DEFAULTS = {"encoding": "terrarium", "interval": 100.0, "base": 0.0, "index": 5, "minLevel": None,
                     "maxLevel": None, "stroke": "#5A3A1AB0", "strokeWidth": 0.5, "indexStroke": "#5A3A1AFF",
                     "indexStrokeWidth": 1.0, "opacity": 1.0, "detail": 0.0}
BASEMAP_RELIEF_DEFAULTS = {"elevation": None, "encoding": "terrarium"}
BASEMAP_KEYS = {"kind", "id", "tiles", "mapStyle", "opacity", "detail", "labels", "attribution", "style",
                "elevation", "encoding"}
CONTOURS_KEYS = {"kind", "id", "elevation"} | set(CONTOURS_DEFAULTS)
HILLSHADE_KEYS = {"hillshade-illumination-direction": "direction", "hillshade-illumination-altitude": "altitude",
                  "hillshade-illumination-anchor": "anchor", "hillshade-exaggeration": "exaggeration",
                  "hillshade-shadow-color": "shadow", "hillshade-highlight-color": "highlight",
                  "hillshade-accent-color": "accent", "hillshade-method": "method"}
RASTER_KEYS = {"raster-opacity": "opacity", "raster-hue-rotate": "hueRotate", "raster-brightness-min": "brightnessMin",
               "raster-brightness-max": "brightnessMax", "raster-saturation": "saturation",
               "raster-contrast": "contrast", "raster-resampling": "resampling"}


class ReliefError(ValueError):
    """A relief layer or contours element outside the draft's rules or bounds."""


def digest(obj):
    """sha256 of the object as JSON with sorted keys and floats rounded to three decimals."""
    def rnd(v):
        if isinstance(v, (float, np.floating)):
            return round(float(v), DIGEST_DECIMALS)
        if isinstance(v, (int, np.integer)):
            return int(v)
        if isinstance(v, dict):
            return {k: rnd(x) for k, x in v.items()}
        if isinstance(v, (list, tuple, np.ndarray)):
            return [rnd(x) for x in v]
        return v
    text = json.dumps(rnd(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hex(color):
    """A colour literal #RGB, #RRGGBB or #RRGGBBAA as (r, g, b, a) integers 0..255."""
    s = str(color)
    m = re.fullmatch(r"#([0-9A-Fa-f]{3})", s)
    if m:
        s = "#" + "".join(c * 2 for c in m.group(1))
    m = re.fullmatch(r"#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?", s)
    if not m:
        raise ReliefError(f"a literal colour #RGB, #RRGGBB or #RRGGBBAA is required: {color!r}")
    rgb = m.group(1)
    a = m.group(2) or "FF"
    return tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4)) + (int(a, 16),)


def _hex_text(color):
    return "#%02X%02X%02X%02X" % _hex(color)


def _premultiplied(color):
    r, g, b, a = (c / 255.0 for c in _hex(color))
    return np.array([r * a, g * a, b * a, a])


# ----------------------------------------------------------------------------------------------- encodings, world


def decode(encoding, pixel):
    """A pixel's height in metres: terrarium R*256 + G + B/256 - 32768, mapbox -10000 + (R*65536 + G*256 + B)*0.1."""
    if encoding == "terrarium":
        r, g, b = pixel[:3]
        return (r * 256.0 + g + b / 256.0) - 32768.0
    if encoding == "mapbox":
        r, g, b = pixel[:3]
        return -10000.0 + (r * 65536.0 + g * 256.0 + b) * 0.1
    raise ReliefError(f"RL3: encoding is one of {', '.join(ENCODINGS)}, not {encoding}")


def encode(encoding, h):
    """The pixel (r, g, b) nearest to the height h in the encoding."""
    if encoding == "terrarium":
        v = min(max(float(h) + 32768.0, 0.0), 65535.999)
        whole = math.floor(v)
        return whole // 256, whole % 256, min(255, int(round((v - whole) * 256.0)))
    if encoding == "mapbox":
        v = min(max(int(round((float(h) + 10000.0) * 10.0)), 0), 0xFFFFFF)
        return v >> 16, (v >> 8) & 255, v & 255
    raise ReliefError(f"RL3: encoding is one of {', '.join(ENCODINGS)}, not {encoding}")


def encode_array(encoding, h):
    """encode over an array of heights: a uint8 array of shape h.shape + (3,)."""
    h = np.asarray(h, dtype=float)
    if encoding == "terrarium":
        v = np.clip(h + 32768.0, 0.0, 65535.999)
        whole = np.floor(v)
        b = np.minimum(255, np.rint((v - whole) * 256.0))
        out = np.stack([whole // 256, whole % 256, b], axis=-1)
    elif encoding == "mapbox":
        v = np.clip(np.rint((h + 10000.0) * 10.0), 0, 0xFFFFFF).astype(np.int64)
        out = np.stack([v >> 16, (v >> 8) & 255, v & 255], axis=-1)
    else:
        raise ReliefError(f"RL3: encoding is one of {', '.join(ENCODINGS)}, not {encoding}")
    return out.astype(np.uint8)


def decode_array(encoding, pixels):
    """decode over an array of pixels (..., 3 or 4): a float array of heights."""
    p = np.asarray(pixels, dtype=float)
    if encoding == "terrarium":
        return p[..., 0] * 256.0 + p[..., 1] + p[..., 2] / 256.0 - 32768.0
    if encoding == "mapbox":
        return -10000.0 + (p[..., 0] * 65536.0 + p[..., 1] * 256.0 + p[..., 2]) * 0.1
    raise ReliefError(f"RL3: encoding is one of {', '.join(ENCODINGS)}, not {encoding}")


def pixel_size(z, lat):
    """Ground size in metres of a world pixel at zoom z and latitude lat (256-pixel tiles)."""
    return 2 * math.pi * R * math.cos(math.radians(lat)) / (TILE * 2 ** z)


def world_pixel(z, lon, lat):
    """Web Mercator world pixel (px, py) of a point at zoom z; the world is 256 * 2^z pixels wide."""
    n = TILE * 2 ** z
    phi = math.radians(lat)
    px = (lon + 180.0) / 360.0 * n
    py = (1.0 - math.log(math.tan(phi) + 1.0 / math.cos(phi)) / math.pi) / 2.0 * n
    return px, py


def lon_lat(z, px, py):
    """The inverse of world_pixel."""
    n = TILE * 2 ** z
    lon = px / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * py / n))))
    return lon, lat


def row_latitude(z, y):
    """Latitude at the centre of world pixel row y (y + 0.5) at zoom z; y may be an array."""
    n = TILE * 2 ** z
    return np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * (np.asarray(y, dtype=float) + 0.5) / n))))


def _round_half_away(x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def mosaic_zoom(k, detail, min_zoom, max_zoom):
    """The raster tile zoom of SREP 9, round(log2(2 pi k / 256) + detail) in [0, 24], clamped to the archive."""
    z = _round_half_away(math.log2(2 * math.pi * k / TILE) + detail)
    z = min(max(z, 0), 24)
    return min(max(z, min_zoom), max_zoom)


def globe_mosaic_zoom(texture, detail, min_zoom, max_zoom):
    """The world mosaic zoom of a globe drape 2T wide: round(log2(2T / 256) + detail), clamped like mosaic_zoom."""
    z = _round_half_away(math.log2(2.0 * texture / TILE) + detail)
    z = min(max(z, 0), 24)
    return min(max(z, min_zoom), max_zoom)


# ------------------------------------------------------------------------------------------------ archives, tiles


class Archive:
    """A tile archive: uint8 tiles (h, w, 3 or 4) by (z, x, y), with the zoom range of its header."""

    def __init__(self, tiles, min_zoom, max_zoom, kind="raster"):
        self.tiles = dict(tiles)
        self.min_zoom = int(min_zoom)
        self.max_zoom = int(max_zoom)
        self.kind = kind

    def tile(self, z, x, y):
        return self.tiles.get((int(z), int(x), int(y)))


def _centres(z, x, y):
    """World pixel centres (px, py) of tile z/x/y, two (256, 256) arrays."""
    j, i = np.mgrid[0:TILE, 0:TILE]
    return x * TILE + i + 0.5, y * TILE + j + 0.5


def synthetic_archive(zoom, field, encoding="terrarium", tiles=None, min_zoom=None):
    """An elevation archive at one zoom: field(px, py) over world pixel centres, encoded; all tiles or the listed ones."""
    n = 2 ** zoom
    keys = [(x, y) for y in range(n) for x in range(n)] if tiles is None else list(tiles)
    out = {}
    for x, y in keys:
        px, py = _centres(zoom, x, y)
        out[(zoom, x, y)] = encode_array(encoding, field(px, py))
    return Archive(out, zoom if min_zoom is None else min_zoom, zoom)


def synthetic_photo(zoom, tiles=None):
    """A raster photo archive at one zoom: a smooth colour field over the world, opaque."""
    n = 2 ** zoom
    keys = [(x, y) for y in range(n) for x in range(n)] if tiles is None else list(tiles)
    size = TILE * n
    out = {}
    for x, y in keys:
        px, py = _centres(zoom, x, y)
        r = 128 + 100 * np.sin(2 * np.pi * px / size)
        g = 128 + 100 * np.cos(2 * np.pi * py / size)
        b = 96 + 64 * np.sin(2 * np.pi * (px + py) / size)
        a = np.full_like(r, 255.0)
        out[(zoom, x, y)] = np.clip(np.rint(np.stack([r, g, b, a], axis=-1)), 0, 255).astype(np.uint8)
    return Archive(out, zoom, zoom)


def source_square(archive, z, x, y):
    """SREP 9's source of a raster tile: the tile, else the first ancestor present down to min_zoom, with the square
    (origin ox, oy and side in the ancestor's tile units) the tile covers; None when nothing is found."""
    n = 2 ** z
    x %= n
    if y < 0 or y >= n:
        return None
    d = 0
    while z - d >= archive.min_zoom:
        tile = archive.tile(z - d, x >> d, y >> d)
        if tile is not None:
            s = 1.0 / 2 ** d
            return tile, x * s - (x >> d), y * s - (y >> d), s
        d += 1
    return None


def resample(data, ox, oy, side, resampling="linear"):
    """The square (ox, oy, side) of a tile's float data (h, w, ...) resampled to 256 x 256 at pixel centres."""
    h, w = data.shape[:2]
    i = np.arange(TILE)
    fx = (ox + (i + 0.5) / TILE * side) * w       # pixel coordinates in the source, centres at k + 0.5
    fy = (oy + (i + 0.5) / TILE * side) * h
    if resampling == "nearest":
        xi = np.clip(np.floor(fx).astype(int), 0, w - 1)
        yi = np.clip(np.floor(fy).astype(int), 0, h - 1)
        return data[yi[:, None], xi[None, :]]
    if resampling != "linear":
        raise ReliefError(f"RL4: resampling is one of {', '.join(RESAMPLINGS)}, not {resampling}")
    gx = np.clip(fx - 0.5, 0, w - 1)
    gy = np.clip(fy - 0.5, 0, h - 1)
    x0 = np.floor(gx).astype(int)
    y0 = np.floor(gy).astype(int)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    tx = (gx - x0)[None, :]
    ty = (gy - y0)[:, None]
    if data.ndim == 3:
        tx = tx[..., None]
        ty = ty[..., None]
    top = data[y0[:, None], x0[None, :]] * (1 - tx) + data[y0[:, None], x1[None, :]] * tx
    bottom = data[y1[:, None], x0[None, :]] * (1 - tx) + data[y1[:, None], x1[None, :]] * tx
    return top * (1 - ty) + bottom * ty


def sample(tile, x, y, resampling="linear"):
    """One sample of a tile's float data at pixel coordinates (x, y), nearest or bilinear at pixel centres."""
    h, w = tile.shape[:2]
    if resampling == "nearest":
        return tile[min(max(int(math.floor(y)), 0), h - 1), min(max(int(math.floor(x)), 0), w - 1)]
    if resampling != "linear":
        raise ReliefError(f"RL4: resampling is one of {', '.join(RESAMPLINGS)}, not {resampling}")
    gx = min(max(x - 0.5, 0.0), w - 1.0)
    gy = min(max(y - 0.5, 0.0), h - 1.0)
    x0, y0 = int(math.floor(gx)), int(math.floor(gy))
    x1, y1 = min(x0 + 1, w - 1), min(y0 + 1, h - 1)
    tx, ty = gx - x0, gy - y0
    top = tile[y0, x0] * (1 - tx) + tile[y0, x1] * tx
    bottom = tile[y1, x0] * (1 - tx) + tile[y1, x1] * tx
    return top * (1 - ty) + bottom * ty


def source_heights(archive, encoding, z, x, y):
    """The 256 x 256 heights of tile z/x/y from its source square (bilinear when overzoomed), or None."""
    found = source_square(archive, z, x, y)
    if found is None:
        return None
    tile, ox, oy, side = found
    h = decode_array(encoding, tile)
    if side == 1.0:
        return h
    return resample(h, ox, oy, side, "linear")


def heights(archive, encoding, z, x, y):
    """source_heights, or a tile of zeros when the archive holds nothing for it (SREP 10: h = 0)."""
    h = source_heights(archive, encoding, z, x, y)
    return np.zeros((TILE, TILE)) if h is None else h


def source_pixels(archive, z, x, y, resampling="linear"):
    """The 256 x 256 premultiplied RGBA floats of a raster tile from its source square, or None."""
    found = source_square(archive, z, x, y)
    if found is None:
        return None
    tile, ox, oy, side = found
    data = tile.astype(float) / 255.0
    if data.shape[2] == 3:
        data = np.concatenate([data, np.ones(data.shape[:2] + (1,))], axis=2)
    data = np.concatenate([data[..., :3] * data[..., 3:4], data[..., 3:4]], axis=2)
    if side == 1.0:
        return data
    return resample(data, ox, oy, side, resampling)


class Mosaic:
    """The heights of nx x ny tiles from (x0, y0) at zoom z with a one-pixel border: h has shape
    (ny * 256 + 2, nx * 256 + 2); world (east) and rows (south) are padded from the neighbouring tiles."""

    def __init__(self, z, x0, y0, nx, ny, h):
        self.z, self.x0, self.y0, self.nx, self.ny, self.h = z, x0, y0, nx, ny, h

    @property
    def wraps(self):
        return self.nx >= 2 ** self.z


def _assemble(z, x0, y0, nx, ny, tile_fn, limit):
    """A padded mosaic of tile_fn(z, x, y) (256 x 256 arrays or None): neighbours fill the border, x modulo 2^z,
    missing border tiles and rows beyond the world extrapolate the edge linearly (2 * edge - next)."""
    if nx * TILE > limit or ny * TILE > limit:
        raise ReliefError(f"RL6: the mosaic of {nx} x {ny} tiles exceeds {limit} pixels along a side")
    n = 2 ** z
    cols = {}
    for tx in range(-1, nx + 1):
        col = []
        for ty in range(-1, ny + 1):
            yy = y0 + ty
            if 0 <= yy < n:
                col.append(tile_fn(z, (x0 + tx) % n, yy))
            else:
                col.append(None)
        cols[tx] = col

    def block(tx, ty):
        t = cols[tx][ty + 1]
        inside = 0 <= tx < nx and 0 <= ty < ny
        if t is None and inside:
            t = tile_fn(z, (x0 + tx) % n, y0 + ty)
        return t

    sample_tile = next(t for c in cols.values() for t in c if t is not None)
    shape = sample_tile.shape
    out = np.zeros((ny * TILE + 2, nx * TILE + 2) + shape[2:])
    inner = {}
    for ty in range(ny):
        for tx in range(nx):
            t = block(tx, ty)
            if t is None:
                t = np.zeros(shape)
            inner[(tx, ty)] = t
            out[1 + ty * TILE:1 + (ty + 1) * TILE, 1 + tx * TILE:1 + (tx + 1) * TILE] = t
    # columns of the border: the neighbour's edge column, else the edge extrapolated
    for ty in range(ny):
        rows = slice(1 + ty * TILE, 1 + (ty + 1) * TILE)
        west = block(-1, ty)
        out[rows, 0] = west[:, -1] if west is not None else 2 * inner[(0, ty)][:, 0] - inner[(0, ty)][:, 1]
        east = block(nx, ty)
        out[rows, -1] = east[:, 0] if east is not None else 2 * inner[(nx - 1, ty)][:, -1] - inner[(nx - 1, ty)][:, -2]
    # rows of the border: the neighbour's edge row over the inner columns, else extrapolated
    for tx in range(nx):
        cols_ = slice(1 + tx * TILE, 1 + (tx + 1) * TILE)
        north = block(tx, -1)
        out[0, cols_] = north[-1, :] if north is not None else 2 * inner[(tx, 0)][0, :] - inner[(tx, 0)][1, :]
        south = block(tx, ny)
        out[-1, cols_] = south[0, :] if south is not None else 2 * inner[(tx, ny - 1)][-1, :] - inner[(tx, ny - 1)][-2, :]
    # corners: the diagonal neighbour's corner pixel, else extrapolated along the border column
    for cx, tx in ((0, -1), (-1, nx)):
        for cy, ty in ((0, -1), (-1, ny)):
            diag = block(tx, ty)
            if diag is not None:
                out[cy, cx] = diag[0 if ty == ny else -1, 0 if tx == nx else -1]
            else:
                out[cy, cx] = 2 * out[1 if cy == 0 else -2, cx] - out[2 if cy == 0 else -3, cx]
    return out


def mosaic(archive, encoding, z, x0, y0, nx, ny, limit=MAX_MOSAIC):
    """The height mosaic of nx x ny tiles from (x0, y0) at zoom z, bordered by the neighbouring tiles."""
    h = _assemble(z, x0, y0, nx, ny, lambda zz, x, y: source_heights(archive, encoding, zz, x, y), limit)
    return Mosaic(z, x0, y0, nx, ny, h)


def raster_mosaic(archive, z, x0, y0, nx, ny, resampling="linear", limit=MAX_MOSAIC):
    """The premultiplied RGBA mosaic of raster tiles (the border is dropped): shape (ny * 256, nx * 256, 4)."""
    data = _assemble(z, x0, y0, nx, ny, lambda zz, x, y: source_pixels(archive, zz, x, y, resampling), limit)
    return data[1:-1, 1:-1]


# ------------------------------------------------------------------------------------------------------ gradient


def pad_grid(h):
    """A grid padded by one pixel of linear extrapolation, 2 * edge - next (gdaldem's -compute_edges rule), columns
    first and then rows, so a plane keeps its gradient up to its edge."""
    g = np.asarray(h, dtype=float)
    if g.shape[0] < 2 or g.shape[1] < 2:
        return np.pad(g, 1, mode="edge")
    g = np.concatenate([2 * g[:, :1] - g[:, 1:2], g, 2 * g[:, -1:] - g[:, -2:-1]], axis=1)
    return np.concatenate([2 * g[:1] - g[1:2], g, 2 * g[-1:] - g[-2:-1]], axis=0)


def gradient(padded, size):
    """Horn's gradient of the interior of a padded grid, in height units per metre: (dh/dEast, dh/dNorth).
    `size` is the ground size of a pixel in metres, a scalar or one value per interior row."""
    p = np.asarray(padded, dtype=float)
    a, b, c = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    d, f = p[1:-1, :-2], p[1:-1, 2:]
    g, h, i = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
    s = np.asarray(size, dtype=float)
    if s.ndim == 1:
        s = s[:, None]
    ge = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * s)
    gn = ((a + 2 * b + c) - (g + 2 * h + i)) / (8.0 * s)
    return ge, gn


def mosaic_gradient(m):
    """The gradient of a mosaic's interior with the Mercator ground size of each row."""
    rows = m.y0 * TILE + np.arange(m.ny * TILE)
    sizes = 2 * math.pi * R * np.cos(np.radians(row_latitude(m.z, rows))) / (TILE * 2 ** m.z)
    return gradient(m.h, sizes)


# ------------------------------------------------------------------------------------------------------ hillshade


def hillshade_paint(paint):
    """The hillshade paint read with MapLibre's defaults: direction/altitude/shadow/highlight as tuples."""
    out = dict(HILLSHADE_DEFAULTS)
    for key, name in HILLSHADE_KEYS.items():
        if key not in paint or paint[key] is None:
            continue
        v = paint[key]
        if name in ("direction", "altitude"):
            out[name] = tuple(float(x) for x in (v if isinstance(v, (list, tuple)) else [v]))
        elif name in ("shadow", "highlight"):
            out[name] = tuple(_hex_text(x) for x in (v if isinstance(v, (list, tuple)) else [v]))
        elif name == "accent":
            out[name] = _hex_text(v)
        elif name == "exaggeration":
            out[name] = float(v)
        else:
            out[name] = str(v)
    return out


def check_hillshade(paint):
    """RL4: the method, the anchor, the light arrays (equal lengths, at least one) and the altitudes (0..90)."""
    if paint["method"] not in METHODS:
        raise ReliefError(f"RL4: hillshade-method is one of {', '.join(METHODS)}, not {paint['method']}")
    if paint["anchor"] not in ANCHORS:
        raise ReliefError(f"RL4: hillshade-illumination-anchor is viewport or map, not {paint['anchor']}")
    n = len(paint["direction"])
    if n < 1 or len(paint["altitude"]) != n or len(paint["shadow"]) != n or len(paint["highlight"]) != n:
        raise ReliefError("RL4: hillshade-illumination-direction, -altitude, hillshade-shadow-color and "
                          "hillshade-highlight-color have the same length, at least one")
    if any(not 0.0 <= a <= 90.0 for a in paint["altitude"]):
        raise ReliefError("RL4: hillshade-illumination-altitude is between 0 and 90 degrees")
    if not 0.0 <= paint["exaggeration"] <= 1.0:
        raise ReliefError("RL4: hillshade-exaggeration is between 0 and 1")


def _azimuth(paint, index, rotation):
    """The light's azimuth in degrees clockwise from north: the direction, less the map's rotation for viewport."""
    d = paint["direction"][index]
    return d - rotation if paint["anchor"] == "viewport" else d


def _round_level(x):
    return np.floor(x + 0.5).astype(int)


def shade_level(method, ge, gn, paint, rotation=0.0):
    """gdaldem's 8-bit level (1..255) for basic, combined, igor and multidirectional, from the gradient in metres
    per metre scaled by p = 2 * exaggeration * grad h. GDAL's x is west minus east (-pE), its y north minus south
    (pN); the azimuth is clockwise from north, the altitude above the horizon."""
    if method not in METHODS:
        raise ReliefError(f"RL4: hillshade-method is one of {', '.join(METHODS)}, not {method}")
    if method == "standard":
        raise ReliefError("the standard method shades colours directly and has no gdaldem level")
    e = float(paint["exaggeration"])
    pe = 2.0 * e * np.asarray(ge, dtype=float)
    pn = 2.0 * e * np.asarray(gn, dtype=float)
    al = math.radians(paint["altitude"][0])
    sin_alt, cos_alt = math.sin(al), math.cos(al)
    th = math.radians(_azimuth(paint, 0, rotation))
    xx_yy = pe * pe + pn * pn
    if method == "basic":
        cang = (sin_alt - cos_alt * (pe * math.sin(th) + pn * math.cos(th))) / np.sqrt(1.0 + xx_yy)
        return np.where(cang <= 0.0, 1, _round_level(1.0 + 254.0 * cang))
    if method == "combined":
        c = (sin_alt - cos_alt * (pe * math.sin(th) + pn * math.cos(th))) / np.sqrt(1.0 + xx_yy)
        cang = 1.0 - np.arccos(np.clip(c, -1.0, 1.0)) * np.arctan(np.sqrt(xx_yy)) * 4.0 / (math.pi ** 2)
        return np.where(cang <= 0.0, 1, _round_level(1.0 + 254.0 * cang))
    if method == "igor":
        slope_strength = np.degrees(np.arctan(np.sqrt(xx_yy))) / 90.0
        aspect = np.arctan2(-pn, -pe)
        target = 1.5 * math.pi - th
        diff = np.abs(np.mod(aspect, 2 * math.pi) - np.mod(target, 2 * math.pi))
        diff = np.where(diff > math.pi, 2 * math.pi - diff, diff)
        aspect_strength = 1.0 - diff / math.pi
        return _round_level(255.0 * (1.0 - slope_strength * aspect_strength))
    # multidirectional: USGS Open-File Report 92-422, as gdaldem (lights at 225, 270, 315 and 360 degrees)
    x, y = -pe, pn
    c225 = math.cos(math.radians(225.0))
    v225 = np.maximum(0.0, sin_alt + (x - y) * c225 * cos_alt)
    v270 = np.maximum(0.0, sin_alt - x * cos_alt)
    v315 = np.maximum(0.0, sin_alt + (x + y) * c225 * cos_alt)
    v360 = np.maximum(0.0, sin_alt - y * cos_alt)
    xx, yy = x * x, y * y
    w225 = 0.5 * (xx + yy) - x * y
    w315 = (xx + yy) - w225
    safe = np.where(xx_yy == 0.0, 1.0, xx_yy)
    cang = (w225 * v225 + xx * v270 + w315 * v315 + yy * v360) / safe / np.sqrt(1.0 + xx_yy)
    flat = _round_level(np.full_like(cang, 1.0 + 254.0 * sin_alt))
    return np.where(xx_yy == 0.0, flat, _round_level(1.0 + 127.0 * cang))


def shade_colour(levels, method, paint):
    """The premultiplied colour of a level: s above one half draws the highlight at alpha 2s - 1, below it the
    shadow at alpha 1 - 2s (MapLibre's basic rule); s is (level - 1) / 254, for igor level / 255."""
    lv = np.asarray(levels, dtype=float)
    s = lv / 255.0 if method == "igor" else (lv - 1.0) / 254.0
    shadow = _premultiplied(paint["shadow"][0])
    highlight = _premultiplied(paint["highlight"][0])
    w_hi = np.clip(2.0 * s - 1.0, 0.0, 1.0)[..., None]
    w_sh = np.clip(1.0 - 2.0 * s, 0.0, 1.0)[..., None]
    return highlight * w_hi + shadow * w_sh


def _igor_pixels(pe, pn, paint, rotation):
    th = math.radians(_azimuth(paint, 0, rotation))
    slope_strength = np.degrees(np.arctan(np.hypot(pe, pn))) / 90.0
    aspect = np.arctan2(-pn, -pe)
    target = 1.5 * math.pi - th
    diff = np.abs(np.mod(aspect, 2 * math.pi) - np.mod(target, 2 * math.pi))
    diff = np.where(diff > math.pi, 2 * math.pi - diff, diff)
    aspect_strength = 1.0 - diff / math.pi
    shadow_w = (slope_strength * aspect_strength)[..., None]
    highlight_w = (slope_strength * (1.0 - aspect_strength))[..., None]
    return _premultiplied(paint["shadow"][0]) * shadow_w + _premultiplied(paint["highlight"][0]) * highlight_w


def _standard_pixels(pe, pn_south, paint, rotation):
    """MapLibre's legacy hillshade (hillshade.fragment.glsl): deriv = (pE, pSouth), azimuth = direction + pi."""
    e = float(paint["exaggeration"])
    az = math.radians(_azimuth(paint, 0, rotation)) + math.pi
    slope = np.arctan(0.625 * np.hypot(pe, pn_south))
    aspect = np.where(pe != 0.0, np.arctan2(pn_south, -pe), np.where(pn_south > 0.0, math.pi / 2, -math.pi / 2))
    base = 1.875 - e * 1.75
    max_value = 0.5 * math.pi
    if e != 0.5:
        scaled = ((np.power(base, slope) - 1.0) / (math.pow(base, max_value) - 1.0)) * max_value
    else:
        scaled = slope
    k = min(max(e * 2.0, 0.0), 1.0)
    accent = np.cos(scaled)
    accent_colour = (1.0 - accent)[..., None] * _premultiplied(paint["accent"]) * k
    shade = np.abs(np.mod((aspect + az) / math.pi + 0.5, 2.0) - 1.0)[..., None]
    shadow = _premultiplied(paint["shadow"][0])
    highlight = _premultiplied(paint["highlight"][0])
    shade_colour_ = (shadow * (1.0 - shade) + highlight * shade) * np.sin(scaled)[..., None] * k
    return accent_colour * (1.0 - shade_colour_[..., 3:4]) + shade_colour_


def hillshade_pixels(method, ge, gn, paint, rotation=0.0):
    """The premultiplied RGBA of a hillshade layer from the gradient (dh/dEast, dh/dNorth) in metres per metre."""
    if method not in METHODS:
        raise ReliefError(f"RL4: hillshade-method is one of {', '.join(METHODS)}, not {method}")
    e = float(paint["exaggeration"])
    pe = 2.0 * e * np.asarray(ge, dtype=float)
    pn = 2.0 * e * np.asarray(gn, dtype=float)
    if method == "standard":
        return _standard_pixels(pe, -pn, paint, rotation)
    if method == "igor":
        return _igor_pixels(pe, pn, paint, rotation)
    return shade_colour(shade_level(method, ge, gn, paint, rotation), method, paint)


def hillshade_levels(h, size, method, paint, rotation=0.0):
    """shade_level over a plain height grid with edge replication and one ground size (gdaldem on a raster)."""
    ge, gn = gradient(pad_grid(h), size)
    return shade_level(method, ge, gn, paint, rotation)


def mosaic_levels(m, method, paint, rotation=0.0):
    """shade_level over a mosaic's interior with the ground size of each row."""
    ge, gn = mosaic_gradient(m)
    return shade_level(method, ge, gn, paint, rotation)


def mosaic_hillshade(m, method, paint, rotation=0.0):
    ge, gn = mosaic_gradient(m)
    return hillshade_pixels(method, ge, gn, paint, rotation)


# -------------------------------------------------------------------------------------------------- colour relief


def relief_paint(paint):
    out = dict(RELIEF_DEFAULTS)
    if paint.get("color-relief-opacity") is not None:
        out["opacity"] = float(paint["color-relief-opacity"])
    if paint.get("color-relief-color") is not None:
        out["color"] = paint["color-relief-color"]
    return out


def relief_stops(expr):
    """The stops of color-relief-color: ["interpolate", ["linear"], ["elevation"], e0, c0, ...] (elevations strictly
    increasing, at least one stop) or ["step", ["elevation"], c0, e1, c1, ...]; ((elevation, rgba), ...), mode."""
    if not isinstance(expr, (list, tuple)) or not expr:
        raise ReliefError("RL5: color-relief-color is an interpolate or step expression over [\"elevation\"]")
    op = expr[0]
    if op == "interpolate":
        if len(expr) < 5 or list(expr[1]) != ["linear"] or list(expr[2]) != ["elevation"] or (len(expr) - 3) % 2:
            raise ReliefError("RL5: color-relief-color interpolates linearly over [\"elevation\"] with at least one stop")
        pairs = list(zip(expr[3::2], expr[4::2]))
        mode = "interpolate"
    elif op == "step":
        if len(expr) < 3 or list(expr[1]) != ["elevation"] or (len(expr) - 3) % 2:
            raise ReliefError("RL5: color-relief-color steps over [\"elevation\"] with a first colour and stops")
        pairs = [(-math.inf, expr[2])] + list(zip(expr[3::2], expr[4::2]))
        mode = "step"
    else:
        raise ReliefError("RL5: color-relief-color is an interpolate or step expression over [\"elevation\"]")
    stops = []
    for e, c in pairs:
        if isinstance(e, bool) or not isinstance(e, (int, float)) or (math.isnan(e)):
            raise ReliefError("RL5: color-relief-color stops are numbers")
        stops.append((float(e), _hex(c)))
    for (e0, _), (e1, _) in zip(stops, stops[1:]):
        if not e1 > e0:
            raise ReliefError("RL5: color-relief-color stops increase strictly")
    return tuple(stops), mode


def relief_colour(stops, mode, h):
    """gdaldem's colour of a height: clamped at the ends, exact at a stop, else linear between the neighbouring
    stops with int(0.5 + c0 + ratio * (c1 - c0)) per channel; step takes the last stop at or below h."""
    elevations = [e for e, _ in stops]
    if mode == "step":
        i = 0
        for k, e in enumerate(elevations):
            if h >= e:
                i = k
        return stops[i][1]
    if h <= elevations[0]:
        return stops[0][1]
    if h > elevations[-1]:
        return stops[-1][1]
    i = next(k for k, e in enumerate(elevations) if h <= e)
    if elevations[i] == h:
        return stops[i][1]
    e0, c0 = stops[i - 1]
    e1, c1 = stops[i]
    ratio = (h - e0) / (e1 - e0)
    return tuple(min(255, max(0, int(0.5 + a + ratio * (b - a)))) for a, b in zip(c0, c1))


def relief_pixels(h, stops, mode, opacity=1.0):
    """relief_colour over a grid, premultiplied floats scaled by color-relief-opacity: shape h.shape + (4,)."""
    h = np.asarray(h, dtype=float)
    elev = np.array([e for e, _ in stops])
    cols = np.array([c for _, c in stops], dtype=float)
    if mode == "step":
        i = np.clip(np.searchsorted(elev, h, side="right") - 1, 0, len(stops) - 1)
        out = cols[i]
    else:
        i = np.searchsorted(elev, h, side="left")
        lo = np.clip(i - 1, 0, len(stops) - 1)
        hi = np.clip(i, 0, len(stops) - 1)
        e0, e1 = elev[lo], elev[hi]
        span = np.where(e1 > e0, e1 - e0, 1.0)
        ratio = np.clip((h - e0) / span, 0.0, 1.0)[..., None]
        out = np.floor(0.5 + cols[lo] + ratio * (cols[hi] - cols[lo]))
        out = np.where((i == 0)[..., None], cols[0], out)
        out = np.where((i >= len(stops))[..., None], cols[-1], out)
        exact = (hi < len(stops)) & (elev[hi] == h)
        out = np.where(exact[..., None], cols[hi], out)
        out = np.clip(out, 0, 255)
    rgba = out / 255.0
    a = rgba[..., 3:4] * float(opacity)
    return np.concatenate([rgba[..., :3] * a, a], axis=-1)


# -------------------------------------------------------------------------------------------------------- raster


def raster_paint(paint):
    out = dict(RASTER_DEFAULTS)
    for key, name in RASTER_KEYS.items():
        if paint.get(key) is None:
            continue
        v = paint[key]
        out[name] = str(v) if name == "resampling" else float(v)
    out["hueRotate"] = out["hueRotate"] % 360.0
    return out


def check_raster(paint):
    if paint["resampling"] not in RESAMPLINGS:
        raise ReliefError(f"RL4: raster-resampling is one of {', '.join(RESAMPLINGS)}, not {paint['resampling']}")
    for key, lo, hi in (("opacity", 0, 1), ("brightnessMin", 0, 1), ("brightnessMax", 0, 1), ("saturation", -1, 1),
                        ("contrast", -1, 1)):
        if not lo <= paint[key] <= hi:
            raise ReliefError(f"RL4: raster {key} is between {lo} and {hi}")


def spin_weights(angle):
    """MapLibre's hue rotation weights for an angle in degrees."""
    a = math.radians(angle)
    s, c = math.sin(a), math.cos(a)
    return (2 * c + 1) / 3, (-math.sqrt(3) * s - c + 1) / 3, (math.sqrt(3) * s - c + 1) / 3


def contrast_factor(contrast):
    return 1 / (1 - contrast) if contrast > 0 else 1 + contrast


def saturation_factor(saturation):
    return 1 - 1 / (1.001 - saturation) if saturation > 0 else -saturation


def raster_pixels(pixels, paint):
    """MapLibre's raster shader over premultiplied RGBA floats: un-premultiply, alpha times raster-opacity, hue
    spin, saturation about the channel average, contrast about one half, brightness min..max, clamp, premultiply."""
    p = np.asarray(pixels, dtype=float)
    a = p[..., 3:4]
    rgb = np.where(a > 0.0, p[..., :3] / np.where(a > 0.0, a, 1.0), p[..., :3])
    a = a * float(paint["opacity"])
    w0, w1, w2 = spin_weights(paint["hueRotate"])
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    rgb = np.stack([r * w0 + g * w1 + b * w2, r * w2 + g * w0 + b * w1, r * w1 + g * w2 + b * w0], axis=-1)
    average = rgb.mean(axis=-1, keepdims=True)
    rgb = rgb + (average - rgb) * saturation_factor(paint["saturation"])
    rgb = (rgb - 0.5) * contrast_factor(paint["contrast"]) + 0.5
    lo, hi = float(paint["brightnessMin"]), float(paint["brightnessMax"])
    rgb = lo + rgb * (hi - lo)
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.concatenate([rgb * a, a], axis=-1)


# ------------------------------------------------------------------------------------------------------- contours


def levels(hmin, hmax, interval, base, lo=None, hi=None):
    """base + n * interval for every n with max(hmin, lo) <= level <= min(hmax, hi); at most MAX_LEVELS."""
    if not (interval > 0.0) or math.isinf(interval):
        raise ReliefError("RL2: contours/@interval is a positive number")
    low = hmin if lo is None else max(hmin, lo)
    high = hmax if hi is None else min(hmax, hi)
    if high < low:
        return []
    n0 = math.ceil((low - base) / interval - 1e-9)
    n1 = math.floor((high - base) / interval + 1e-9)
    if n1 - n0 + 1 > MAX_LEVELS:
        raise ReliefError(f"RL2: {n1 - n0 + 1} contour levels exceed {MAX_LEVELS}; raise the interval")
    return [base + n * interval for n in range(n0, n1 + 1)]


def is_index(level, interval, base, index):
    """Whether a level is an index contour: every `index`-th level counted from the base."""
    n = int(round((level - base) / interval))
    return n % int(index) == 0


def _edge_point(i0, j0, i1, j1, h0, h1, level):
    t = 0.0 if h1 == h0 else (level - h0) / (h1 - h0)
    return i0 + 0.5 + (i1 - i0) * t, j0 + 0.5 + (j1 - j0) * t


def marching_squares(h, level):
    """The level lines of a grid at `level` as polylines of (x, y) in pixel-centre coordinates (pixel (i, j) at
    (i + 0.5, j + 0.5)); a vertex at or above the level is inside, saddles join the inside corners when the cell
    mean is at or above the level. Closed lines repeat their first point last."""
    g = np.asarray(h, dtype=float)
    ny, nx = g.shape
    inside = g >= level
    # edge keys: ("h", i, j) between (i, j) and (i + 1, j); ("v", i, j) between (i, j) and (i, j + 1)
    points = {}
    adjacency = {}

    def point(kind, i, j):
        key = (kind, i, j)
        if key not in points:
            if kind == "h":
                points[key] = _edge_point(i, j, i + 1, j, g[j, i], g[j, i + 1], level)
            else:
                points[key] = _edge_point(i, j, i, j + 1, g[j, i], g[j + 1, i], level)
        return key

    def link(a, b):
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    codes = (inside[:-1, :-1].astype(int) << 3) | (inside[:-1, 1:].astype(int) << 2) | \
            (inside[1:, 1:].astype(int) << 1) | inside[1:, :-1].astype(int)
    active = np.argwhere((codes != 0) & (codes != 15))
    for j, i in active:
        j, i = int(j), int(i)
        code = int(codes[j, i])
        top, right, bottom, left = ("h", i, j), ("v", i + 1, j), ("h", i, j + 1), ("v", i, j)
        if code in (1, 14):
            link(point(*left), point(*bottom))
        elif code in (2, 13):
            link(point(*bottom), point(*right))
        elif code in (3, 12):
            link(point(*left), point(*right))
        elif code in (4, 11):
            link(point(*top), point(*right))
        elif code in (6, 9):
            link(point(*top), point(*bottom))
        elif code in (7, 8):
            link(point(*top), point(*left))
        else:
            mean = (g[j, i] + g[j, i + 1] + g[j + 1, i + 1] + g[j + 1, i]) / 4.0
            joined = mean >= level
            if (code == 5) == joined:       # 5: tr and bl inside; joined 5 or separated 10 cut tl and br
                link(point(*top), point(*left))
                link(point(*bottom), point(*right))
            else:
                link(point(*top), point(*right))
                link(point(*bottom), point(*left))
    # chain the segments
    seen = set()
    lines = []
    ends = [k for k, nb in adjacency.items() if len(nb) == 1]
    order = ends + [k for k in adjacency if len(adjacency[k]) != 1]
    for start in order:
        if start in seen:
            continue
        chain = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxt = [k for k in adjacency[cur] if k != prev and k not in seen]
            if not nxt:
                if start in adjacency[cur] and len(chain) > 2 and cur != start and prev != start:
                    chain.append(start)
                break
            prev, cur = cur, nxt[0]
            chain.append(cur)
            seen.add(cur)
        lines.append([points[k] for k in chain])
    return lines


def ring_error(line, cx, cy, r):
    """The largest distance of a line's vertices from the circle of radius r about (cx, cy)."""
    return max(abs(math.hypot(x - cx, y - cy) - r) for x, y in line)


def point_segment_distance(p, a, b):
    """Distance from p to the segment ab."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _split_at_world_edges(line, width):
    """Pieces of a line in world pixels with x kept in [0, width]: cut where x crosses 0 or width, wrapped."""
    pieces, current = [], []
    for k, (x, y) in enumerate(line):
        if k > 0:
            x0, y0 = line[k - 1]
            for edge in (0.0, width):
                if (x0 - edge) * (x - edge) < 0:
                    t = (edge - x0) / (x - x0)
                    yc = y0 + t * (y - y0)
                    current.append((edge, yc))
                    pieces.append(current)
                    current = [(edge, yc)]
        current.append((x, y))
    pieces.append(current)
    out = []
    for piece in pieces:
        if len(piece) < 2:
            continue
        mid = sum(x for x, _ in piece) / len(piece)
        shift = -width if mid > width else (width if mid < 0 else 0.0)
        out.append([(min(max(x + shift, 0.0), width), y) for x, y in piece])
    return out


def contours(m, interval, base, lo=None, hi=None):
    """The level lines of a mosaic, by level, as polylines of (lon, lat): marching squares over the padded grid
    (so lines run through tile seams and the border), world pixels from the mosaic's origin, lines cut and
    wrapped at the antimeridian, rows clamped to the world."""
    h = m.h
    out = {}
    width = TILE * 2 ** m.z
    for level in levels(float(h.min()), float(h.max()), interval, base, lo, hi):
        lines = []
        for line in marching_squares(h, level):
            world = [(m.x0 * TILE + x - 1.0, min(max(m.y0 * TILE + y - 1.0, 0.0), width)) for x, y in line]
            for piece in _split_at_world_edges(world, width):
                lines.append([lon_lat(m.z, px, py) for px, py in piece])
        out[level] = lines
    return out


# ---------------------------------------------------------------------------------------------------------- globe


def globe_row(z, lat):
    """The world mosaic row (centre-indexed, 0 .. n - 1) of a latitude, clamped beyond the Mercator limit."""
    n = TILE * 2 ** z
    lat = min(max(lat, -MERCATOR_LIMIT), MERCATOR_LIMIT)
    _, py = world_pixel(z, 0.0, lat)
    return min(max(py - 0.5, 0.0), n - 1.0)


def globe_drape_heights(m, texture):
    """Heights over an equirectangular drape of 2T x T pixels from a whole-world mosaic: bilinear, longitude
    wrapped, latitude rows clamped beyond the Mercator limit."""
    T = int(texture)
    n = TILE * 2 ** m.z
    inner = m.h[1:-1, 1:-1]
    u = np.arange(2 * T)
    v = np.arange(T)
    lon = (u + 0.5) / (2 * T) * 360.0 - 180.0
    lat = 90.0 - (v + 0.5) / T * 180.0
    px = (lon + 180.0) / 360.0 * n - 0.5                      # centre-indexed column, wraps
    rows = np.array([globe_row(m.z, la) for la in lat])
    x0 = np.floor(px).astype(int)
    tx = (px - x0)[None, :]
    xa, xb = x0 % n, (x0 + 1) % n
    y0 = np.floor(rows).astype(int)
    ty = (rows - y0)[:, None]
    ya, yb = np.clip(y0, 0, n - 1), np.clip(y0 + 1, 0, n - 1)
    top = inner[ya[:, None], xa[None, :]] * (1 - tx) + inner[ya[:, None], xb[None, :]] * tx
    bottom = inner[yb[:, None], xa[None, :]] * (1 - tx) + inner[yb[:, None], xb[None, :]] * tx
    return top * (1 - ty) + bottom * ty


# ------------------------------------------------------------------------------------------------- the document


def _get(spec, key, defaults):
    v = spec.get(key)
    return defaults[key] if v is None else v


def _tiles_asset(doc, ref):
    return doc.get("tiles", {}).get(ref) if ref is not None else None


def _visible_tiles(doc, z):
    """The tiles of the map's frame at zoom z: the world-pixel rectangle about the centre, x wrapped, y clamped."""
    m = doc["map"]
    n = 2 ** z
    cx, cy = world_pixel(z, float(m.get("centerLon", 0.0)), float(m.get("centerLat", 0.0)))
    w, h = float(m["width"]), float(m["height"])
    scale = (TILE * 2 ** z) / (512.0 * 2 ** float(m.get("zoom", 0.0)))      # mosaic pixels per map pixel
    x_lo, x_hi = cx - w / 2 * scale, cx + w / 2 * scale
    y_lo, y_hi = cy - h / 2 * scale, cy + h / 2 * scale
    tx0, tx1 = math.floor(x_lo / TILE), math.ceil(x_hi / TILE) - 1
    ty0, ty1 = max(0, math.floor(y_lo / TILE)), min(n - 1, math.ceil(y_hi / TILE) - 1)
    nx = min(n, tx1 - tx0 + 1)
    return tx0 % n, ty0, nx, ty1 - ty0 + 1


def _sample_grid(pixels, k=4):
    """k x k samples of a pixel array, rounded, as nested lists (the frame's digest input)."""
    h, w = pixels.shape[:2]
    rows = [int((j + 0.5) * h / k) for j in range(k)]
    cols = [int((i + 0.5) * w / k) for i in range(k)]
    return [[[round(float(v), 4) for v in pixels[r, c]] for c in cols] for r in rows]


def _layer_summary(pixels):
    grid = _sample_grid(pixels)
    return {"pixels": grid, "digest": digest(grid), "mean": round(float(pixels[..., 3].mean()), 4)}


def warnings(doc):
    """W-RL1: a hillshade or color-relief layer on a basemap without @elevation is skipped, as SREP 9 skips it."""
    out = []
    for child in doc["map"].get("children", []):
        if child.get("kind") == "basemap" and child.get("elevation") is None:
            if any(layer.get("type") in ("hillshade", "color-relief") for layer in child.get("style", [])):
                out.append("W-RL1")
    return out


def run(doc):
    """Every basemap's relief layers and every contours child at the map's view: a summary per child."""
    m = doc["map"]
    k = 512.0 / (2 * math.pi) * 2 ** float(m.get("zoom", 0.0))
    rotation = float(m.get("rotation", 0.0))
    out = []
    for child in m.get("children", []):
        kind = child.get("kind")
        if kind == "basemap":
            photo = _tiles_asset(doc, child.get("tiles"))
            dem = _tiles_asset(doc, child.get("elevation"))
            archive = dem["archive"] if dem is not None else photo["archive"]
            z = mosaic_zoom(k, float(_get(child, "detail", {"detail": 0.0})), archive.min_zoom, archive.max_zoom)
            x0, y0, nx, ny = _visible_tiles(doc, z)
            encoding = _get(child, "encoding", BASEMAP_RELIEF_DEFAULTS)
            heights_ = mosaic(dem["archive"], encoding, z, x0, y0, nx, ny) if dem is not None else None
            layers = {}
            for layer in child.get("style", []):
                t = layer.get("type")
                paint = layer.get("paint", {})
                if t == "raster":
                    rp = raster_paint(paint)
                    pixels = raster_mosaic(photo["archive"], z, x0, y0, nx, ny, rp["resampling"])
                    layers["raster"] = _layer_summary(raster_pixels(pixels, rp))
                elif t == "hillshade" and heights_ is not None:
                    hp = hillshade_paint(paint)
                    ge, gn = mosaic_gradient(heights_)
                    summary = _layer_summary(hillshade_pixels(hp["method"], ge, gn, hp, rotation))
                    if hp["method"] != "standard":
                        lv = shade_level(hp["method"], ge, gn, hp, rotation)
                        summary["mean"] = round(float(lv.mean()), 4)
                        summary["levels"] = [int(lv.min()), int(lv.max())]
                    layers["hillshade"] = summary
                elif t == "color-relief" and heights_ is not None:
                    cp = relief_paint(paint)
                    stops, mode = relief_stops(cp["color"])
                    layers["color-relief"] = _layer_summary(relief_pixels(heights_.h[1:-1, 1:-1], stops, mode,
                                                                          cp["opacity"]))
            out.append({"kind": "basemap", "zoom": z, "tiles": (nx, ny), "layers": layers})
        elif kind == "contours":
            dem = _tiles_asset(doc, child.get("elevation"))
            archive = dem["archive"]
            z = mosaic_zoom(k, float(_get(child, "detail", CONTOURS_DEFAULTS)), archive.min_zoom, archive.max_zoom)
            x0, y0, nx, ny = _visible_tiles(doc, z)
            heights_ = mosaic(archive, _get(child, "encoding", CONTOURS_DEFAULTS), z, x0, y0, nx, ny)
            interval = float(_get(child, "interval", CONTOURS_DEFAULTS))
            base = float(_get(child, "base", CONTOURS_DEFAULTS))
            lines = contours(heights_, interval, base, child.get("minLevel"), child.get("maxLevel"))
            index = int(_get(child, "index", CONTOURS_DEFAULTS))
            vertices = sum(len(line) for ls in lines.values() for line in ls)
            rounded = {str(lv): [[(round(lon, 4), round(lat, 4)) for lon, lat in line] for line in ls]
                       for lv, ls in lines.items()}
            out.append({"kind": "contours", "zoom": z, "tiles": (nx, ny), "levels": len(lines),
                        "index": sum(1 for lv in lines if is_index(lv, interval, base, index)),
                        "vertices": vertices, "digest": digest(rounded)})
    return out


def _check_basemap(doc, child):
    for key in child:
        if key not in BASEMAP_KEYS:
            raise ReliefError(f"V17: unknown attribute {key} on basemap")
    if child.get("elevation") is not None and _tiles_asset(doc, child["elevation"]) is None:
        raise ReliefError("RL1: basemap/@elevation must name a tiles asset")
    if _get(child, "encoding", BASEMAP_RELIEF_DEFAULTS) not in ENCODINGS:
        raise ReliefError(f"RL3: basemap/@encoding is one of {', '.join(ENCODINGS)}")
    for layer in child.get("style", []):
        t = layer.get("type")
        paint = layer.get("paint", {})
        if t == "hillshade":
            check_hillshade(hillshade_paint(paint))
        elif t == "raster":
            check_raster(raster_paint(paint))
        elif t == "color-relief":
            cp = relief_paint(paint)
            if not 0.0 <= cp["opacity"] <= 1.0:
                raise ReliefError("RL5: color-relief-opacity is between 0 and 1")
            relief_stops(cp["color"])


def _check_contours(doc, child):
    for key in child:
        if key not in CONTOURS_KEYS:
            raise ReliefError(f"V17: unknown attribute {key} on contours")
    if _tiles_asset(doc, child.get("elevation")) is None:
        raise ReliefError("RL1: contours/@elevation must name a tiles asset")
    interval = float(_get(child, "interval", CONTOURS_DEFAULTS))
    index = int(_get(child, "index", CONTOURS_DEFAULTS))
    lo, hi = child.get("minLevel"), child.get("maxLevel")
    if not interval > 0.0 or math.isinf(interval) or index < 1 or (lo is not None and hi is not None and hi < lo):
        raise ReliefError("RL2: contours/@interval is positive, @index at least 1, @maxLevel not below @minLevel")
    if _get(child, "encoding", CONTOURS_DEFAULTS) not in ENCODINGS:
        raise ReliefError(f"RL3: contours/@encoding is one of {', '.join(ENCODINGS)}")
    for key in ("strokeWidth", "indexStrokeWidth", "opacity"):
        if float(_get(child, key, CONTOURS_DEFAULTS)) < 0.0:
            raise ReliefError(f"RL2: contours/@{key} is not negative")
    _hex(_get(child, "stroke", CONTOURS_DEFAULTS))
    _hex(_get(child, "indexStroke", CONTOURS_DEFAULTS))


def validate_document(doc):
    """The sorted codes of every failing rule, each element's first failure counted once."""
    codes = set()
    for child in doc["map"].get("children", []):
        try:
            if child.get("kind") == "basemap":
                _check_basemap(doc, child)
            elif child.get("kind") == "contours":
                _check_contours(doc, child)
        except ReliefError as err:
            codes.add(str(err).split(":")[0])
    return sorted(codes)


RAMP = ["interpolate", ["linear"], ["elevation"], -4000, "#000080", 0, "#0000FF", 0.001, "#008000", 1000, "#FFFF00",
        3000, "#FFFFFF"]


EXAMPLE_ZOOM = 6
EXAMPLE_TILES = [(x, y) for y in range(30, 34) for x in range(30, 34)]     # the frame's tiles and their neighbours


def _example_field(px, py):
    """A signed relief about the equator at zoom 6 (2.4 km pixels): ridges 2.5 km high and basins 2.5 km deep,
    sloping 300 m from north to south, with a 60 x 60 pixel plateau on the east."""
    plateau = (px > 8300) & (py > 8100) & (py < 8160) & (px < 8360)
    return np.where(plateau, 1800.0, 2500.0 * np.sin(px / 8.0) * np.cos(py / 10.0) + 1.5 * (py - 8192.0))


_EXAMPLE_ARCHIVES = {}


def _example_archives():
    if not _EXAMPLE_ARCHIVES:
        _EXAMPLE_ARCHIVES["dem"] = synthetic_archive(EXAMPLE_ZOOM, _example_field, "mapbox", tiles=EXAMPLE_TILES)
        _EXAMPLE_ARCHIVES["photo"] = synthetic_photo(EXAMPLE_ZOOM, tiles=EXAMPLE_TILES)
    return _EXAMPLE_ARCHIVES


def example_document():
    archives = _example_archives()
    return {
        "project": "relief",
        "tiles": {"dem": {"kind": "raster", "archive": archives["dem"]},
                  "photo": {"kind": "raster", "archive": archives["photo"]}},
        "map": {"width": 512, "height": 384, "zoom": 5.0, "centerLon": 0.0, "centerLat": 0.0, "rotation": 0.0,
                "children": [
                    {"kind": "basemap", "id": "base", "tiles": "photo", "elevation": "dem", "encoding": "mapbox",
                     "detail": 0.0, "style": [
                         {"type": "raster", "paint": {"raster-saturation": -0.2, "raster-contrast": 0.1}},
                         {"type": "hillshade", "paint": {"hillshade-method": "basic",
                                                         "hillshade-illumination-direction": 315,
                                                         "hillshade-exaggeration": 0.5}},
                         {"type": "color-relief", "paint": {"color-relief-color": RAMP, "color-relief-opacity": 0.6}}]},
                    {"kind": "contours", "id": "lines", "elevation": "dem", "encoding": "mapbox", "interval": 200.0,
                     "base": 0.0, "index": 5, "stroke": "#5A3A1AB0", "strokeWidth": 0.5}]}}


def bad_document():
    """One element per rule: RL1 (unknown elevation), RL2 (interval 0), RL3 (encoding), RL4 (method), RL5 (ramp
    over zoom), V17 (unknown attribute)."""
    doc = example_document()
    doc["map"]["children"] = [
        {"kind": "contours", "elevation": "nowhere"},
        {"kind": "contours", "elevation": "dem", "interval": 0.0},
        {"kind": "contours", "elevation": "dem", "encoding": "gray16"},
        {"kind": "basemap", "tiles": "photo", "elevation": "dem",
         "style": [{"type": "hillshade", "paint": {"hillshade-method": "shiny"}}]},
        {"kind": "basemap", "tiles": "photo", "elevation": "dem",
         "style": [{"type": "color-relief", "paint": {"color-relief-color": ["interpolate", ["linear"], ["zoom"], 0,
                                                                              "#000000", 1, "#FFFFFF"]}}]},
        {"kind": "contours", "elevation": "dem", "smooth": True},
    ]
    return doc


# ------------------------------------------------------------------------------------------------------ the table


TABLE = (
    ("terrarium of sea level", "encode('terrarium', 0.0)", "(128, 0, 0)"),
    ("mapbox of Everest", "encode('mapbox', 8848.0)", "(2, 224, 64)"),
    ("Everest decoded", "round(decode('terrarium', encode('terrarium', 8848.0)), 4)", "8848.0"),
    ("a 4 km depth decoded", "round(decode('mapbox', encode('mapbox', -4000.0)), 4)", "-4000.0"),
    ("ground size at zoom 0", "round(pixel_size(0, 0.0), 2)", "156543.03"),
    ("ground size at 60 N, zoom 3", "round(pixel_size(3, 60.0), 2)", "9783.94"),
    ("Rome's world pixel at zoom 5", "tuple(round(v, 2) for v in world_pixel(5, 12.4964, 41.9028))", "(4380.36, 3043.98)"),
    ("latitude of row 100 at zoom 2", "round(float(row_latitude(2, 100)), 4)", "80.8449"),
    ("tile zoom of a zoom-3.4 map", "mosaic_zoom(K0 * 2 ** 3.4, 0.0, 0, 12)", "4"),
    ("drape zoom of a 2048 texture", "globe_mosaic_zoom(2048, 0.0, 0, 12)", "4"),
    ("plane gradient", "tuple(round(float(g[4, 4]), 4) for g in gradient(pad_grid(PLANE), 30.0))", "(0.1, 0.05)"),
    ("basic level of the plane", "int(hillshade_levels(PLANE, 30.0, 'basic', PAINT)[4, 4])", "186"),
    ("combined level of the plane", "int(hillshade_levels(PLANE, 30.0, 'combined', PAINT)[4, 4])", "246"),
    ("igor level of the plane", "int(hillshade_levels(PLANE, 30.0, 'igor', PAINT)[4, 4])", "248"),
    ("multidirectional level of the plane", "int(hillshade_levels(PLANE, 30.0, 'multidirectional', PAINT)[4, 4])", "195"),
    ("standard colour of the plane", "tuple(round(float(v), 4) for v in hillshade_pixels('standard', *gradient(pad_grid(PLANE), 30.0), PAINT)[4, 4])", "(0.042, 0.042, 0.042, 0.072)"),
    ("flat levels", "[int(shade_level(m, ZERO, ZERO, PAINT)[0, 0]) for m in ('basic', 'combined', 'igor', 'multidirectional')]", "[181, 255, 255, 181]"),
    ("the mosaic's padded shape", "MOSAIC.h.shape", "(258, 514)"),
    ("mosaic levels at the tile seam", "[int(v) for v in mosaic_levels(MOSAIC, 'basic', PAINT)[128, 254:258]]", "[184, 184, 184, 184]"),
    ("world shade at the antimeridian", "[int(v) for v in mosaic_levels(STEEP, 'basic', WEST)[256, [0, 1, 510, 511]]]", "[202, 202, 202, 202]"),
    ("relief colour at 500 m", "relief_colour(STOPS, 'interpolate', 500.0)", "(127, 191, 0, 255)"),
    ("relief colour of a 2 km depth", "relief_colour(STOPS, 'interpolate', -2000.0)", "(0, 0, 192, 255)"),
    ("hue weights at 120 degrees", "tuple(round(w, 6) + 0.0 for w in spin_weights(120.0))", "(0.0, 0.0, 1.0)"),
    ("a raster pixel adjusted", "tuple(round(float(v), 4) for v in raster_pixels(PIXEL, ADJUST)[0, 0])", "(0.5276, 0.3892, 0.0432, 0.8)"),
    ("contour levels of the cone", "levels(float(CONE.min()), float(CONE.max()), 100.0, 0.0)", "[600.0, 700.0, 800.0, 900.0]"),
    ("ring vertices at 800 m", "len(marching_squares(CONE, 800.0)[0])", "161"),
    ("ring radius error at 800 m", "round(ring_error(marching_squares(CONE, 800.0)[0], 32.0, 32.0, 20.0), 4)", "0.0028"),
    ("contour levels in the mosaic", "len(contours(MOSAIC, 100000.0, 0.0))", "13"),
    ("world contour points on the antimeridian", "sum(1 for line in contours(WORLD, 50.0, 0.0)[150.0] for p in line if abs(abs(p[0]) - 180.0) < 1e-6)", "4"),
    ("globe row of 80 N at zoom 2", "round(globe_row(2, 80.0), 3)", "114.454"),
    ("drape heights down a meridian", "tuple(round(float(v), 2) for v in globe_drape_heights(WORLD, 32)[[0, 16, 31], 0])", "(100.03, 177.88, 253.33)"),
    ("the example's zooms and tiles", "(RUN[0]['zoom'], RUN[0]['tiles'], RUN[1]['levels'], RUN[1]['index'])", "(6, (2, 2), 29, 5)"),
    ("the example's hillshade", "(RUN[0]['layers']['hillshade']['mean'], RUN[0]['layers']['hillshade']['levels'])", "(180.0731, [57, 227])"),
    ("the example's digests", "[RUN[0]['layers'][k]['digest'][:12] for k in ('raster', 'hillshade', 'color-relief')] + [RUN[1]['digest'][:12]]", "['37faa991ecd8', '24cc946f3d67', 'b9455e8d0f38', '0ae4a60f07b2']"),
    ("bad document codes", "validate_document(bad_document())", "['RL1', 'RL2', 'RL3', 'RL4', 'RL5', 'V17']"),
    ("warnings without elevation", "warnings(NO_ELEVATION)", "['W-RL1']"),
)


_SCOPE = {}


def scope():
    """The names the numeric table evaluates in; built once per process (the example's run is the costly part)."""
    if _SCOPE:
        return dict(_SCOPE)
    j, i = np.mgrid[0:9, 0:9]
    plane = 0.1 * i * 30.0 - 0.05 * j * 30.0 + 500.0
    jj, ii = np.mgrid[0:64, 0:64]
    cone = 1000.0 - 10.0 * np.hypot(ii + 0.5 - 32.0, jj + 0.5 - 32.0)
    archive = synthetic_archive(2, lambda px, py: 2000.0 * px - 1000.0 * py, "mapbox")
    world = synthetic_archive(1, lambda px, py: 100.0 * np.cos(2 * np.pi * px / 512.0) + 0.3 * py, "terrarium")
    steep = synthetic_archive(1, lambda px, py: 800000.0 * np.sin(2 * np.pi * px / 512.0) + 300.0 * py, "mapbox")
    no_elevation = example_document()
    del no_elevation["map"]["children"][0]["elevation"]
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s.update({
        "K0": 512.0 / (2 * math.pi),
        "PLANE": plane,
        "ZERO": np.zeros((1, 1)),
        "PAINT": hillshade_paint({"hillshade-illumination-direction": 315}),
        "WEST": hillshade_paint({"hillshade-illumination-direction": 270}),
        "MOSAIC": mosaic(archive, "mapbox", 2, 1, 1, 2, 1),
        "WORLD": mosaic(world, "terrarium", 1, 0, 0, 2, 2),
        "STEEP": mosaic(steep, "mapbox", 1, 0, 0, 2, 2),
        "STOPS": relief_stops(RAMP)[0],
        "PIXEL": np.array([[[0.6, 0.3, 0.2, 1.0]]]),
        "ADJUST": raster_paint({"raster-hue-rotate": 30, "raster-saturation": 0.25, "raster-contrast": 0.2,
                                "raster-brightness-min": 0.1, "raster-opacity": 0.8}),
        "CONE": cone,
        "EXAMPLE": example_document(),
        "NO_ELEVATION": no_elevation,
    })
    s["RUN"] = run(s["EXAMPLE"])
    _SCOPE.update(s)
    return dict(s)


def _same(a, b, rel=5e-4, abs_tol=1e-9):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (set, frozenset)) and isinstance(b, (set, frozenset)):
        return a == b
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)):
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return repr(float(v))
    if isinstance(v, set):
        return "{" + ", ".join(_fmt(x) for x in sorted(v)) + "}"
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
