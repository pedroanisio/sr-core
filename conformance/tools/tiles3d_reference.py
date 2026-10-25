#!/usr/bin/env python3
"""Reference for the draft SREP "Add 3D Tiles to the map" (srep/srep-0000-tiles3d.md, M5 of SREP 12).

A `tileset3d` asset names an OGC 3D Tiles 1.1 tileset and pins the archive the resolve step writes by SHA-256;
a `tiles3d` map child draws the tiles the camera selects by screen-space error. This module carries the tileset
reader (explicit and implicit tiling, external tilesets, request volumes), the subtree writer and reader, the
binary glTF and b3dm readers (positions only), the geodesy of the WGS 84 ellipsoid, the screen-space error and
the traversal, the resolve step and its archive, the top-down raster of a 2D map, and the numeric table of the
draft. Everything here is written from the specification (OGC 22-025r4) and uses nothing beyond the standard
library and numpy.

Usage: tiles3d_reference.py  prints the draft's numeric table.
"""
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import struct
import zipfile

import numpy as np

# -------------------------------------------------------------------------------------------------------- siblings

_HERE = os.path.dirname(os.path.abspath(__file__))


def _module(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ts = _module("time_series_reference")

# ------------------------------------------------------------------------------------------------------- constants

R_WGS = 6378137.0
F_WGS = 1.0 / 298.257223563
B_WGS = R_WGS * (1.0 - F_WGS)
E2_WGS = F_WGS * (2.0 - F_WGS)
TILE = _ts.TILE

TILESET_DEFAULTS = {"maxError": 16.0, "maxTiles": 4096}
TILES_DEFAULTS = {"heightOffset": 0.0, "opacity": 1.0, "color": None}
KNOWN_TILESET = ("id", "src", "cache", "cacheSha256", "maxError", "maxTiles", "credit")
KNOWN_TILES = ("id", "tileset", "heightOffset", "opacity", "color")
MAX_DEPTH = 32
MAX_TILES = 1000000
DEFAULT_COLOUR = (0.86, 0.85, 0.83)
LIGHT = (-1.0 / math.sqrt(6.0), -1.0 / math.sqrt(6.0), -2.0 / math.sqrt(6.0))
AMBIENT = 0.4
CODE_ORDER = ("TL1", "TL2", "TL3", "TL4", "V17")
VERSIONS = ("1.0", "1.1")
REFINES = ("ADD", "REPLACE")
SCHEMES = {"QUADTREE": 2, "OCTREE": 3}
CONTENT_KINDS = {".glb": "glb", ".b3dm": "b3dm", ".json": "tileset"}
SUBTREE_MAGIC = b"subt"
GLB_MAGIC = b"glTF"
B3DM_MAGIC = b"b3dm"
ARCHIVE_TIME = (1980, 1, 1, 0, 0, 0)

IDENTITY = np.eye(4)
Y_UP_TO_Z_UP = np.array([[1.0, 0.0, 0.0, 0.0],
                         [0.0, 0.0, -1.0, 0.0],
                         [0.0, 1.0, 0.0, 0.0],
                         [0.0, 0.0, 0.0, 1.0]])


class TilesError(ValueError):
    """A malformed tileset, subtree, content or document."""


def _is_number(v):
    return _ts._is_number(v)


def _numbers(values, n, what):
    if not isinstance(values, (list, tuple)) or len(values) != n or not all(_is_number(v) for v in values):
        raise TilesError(f"{what} needs {n} finite numbers")
    return [float(v) for v in values]


# --------------------------------------------------------------------------------------------------------- geodesy


def ecef(lon, lat, h):
    """WGS 84 geodetic degrees and metres to Earth-centred, Earth-fixed metres (EPSG:4978)."""
    lam, phi = math.radians(lon), math.radians(lat)
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    n = R_WGS / math.sqrt(1.0 - E2_WGS * sin_phi * sin_phi)
    return ((n + h) * cos_phi * math.cos(lam), (n + h) * cos_phi * math.sin(lam), (n * (1.0 - E2_WGS) + h) * sin_phi)


def geodetic(x, y, z):
    """The inverse of ecef: longitude and latitude in degrees, height in metres (Bowring's start, then the fixed
    point of the latitude to 1e-12 radians)."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    if p == 0.0:
        return (0.0, 90.0 if z >= 0.0 else -90.0, abs(z) - B_WGS)
    theta = math.atan2(z * R_WGS, p * B_WGS)
    ep2 = (R_WGS * R_WGS - B_WGS * B_WGS) / (B_WGS * B_WGS)
    phi = math.atan2(z + ep2 * B_WGS * math.sin(theta) ** 3, p - E2_WGS * R_WGS * math.cos(theta) ** 3)
    for _ in range(8):
        sin_phi = math.sin(phi)
        n = R_WGS / math.sqrt(1.0 - E2_WGS * sin_phi * sin_phi)
        phi_next = math.atan2(z + E2_WGS * n * sin_phi, p)
        done = abs(phi_next - phi) < 1e-12
        phi = phi_next
        if done:
            break
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    n = R_WGS / math.sqrt(1.0 - E2_WGS * sin_phi * sin_phi)
    if abs(cos_phi) > 1e-10:
        h = p / cos_phi - n
    else:
        h = abs(z) - B_WGS
    return (math.degrees(lon), math.degrees(phi), h)


def enu_matrix(lon, lat, h):
    """The east-north-up frame at a geodetic point as a column-major 4 x 4 matrix: columns east, north, up and
    the point in ECEF."""
    lam, phi = math.radians(lon), math.radians(lat)
    east = (-math.sin(lam), math.cos(lam), 0.0)
    north = (-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi))
    up = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = east, north, up, ecef(lon, lat, h)
    return m


def mat4(values):
    """A 3D Tiles transform: 16 numbers in column-major order."""
    v = _numbers(values, 16, "a transform")
    return np.array(v, dtype=float).reshape(4, 4).T


def compose(parent, child):
    """The child's matrix in the parent's parent frame: parent times child."""
    return np.asarray(parent, dtype=float) @ np.asarray(child, dtype=float)


def apply(matrix, point):
    p = np.asarray(matrix, dtype=float) @ np.array([point[0], point[1], point[2], 1.0])
    return (float(p[0]), float(p[1]), float(p[2]))


def apply_all(matrix, points):
    pts = np.asarray(points, dtype=float)
    m = np.asarray(matrix, dtype=float)
    return pts @ m[:3, :3].T + m[:3, 3]


# ------------------------------------------------------------------------------------------------- implicit tiling


def morton(x, y, z=None):
    """The Morton index of integer coordinates: x's bits least significant, then y's, then z's."""
    coords = (x, y) if z is None else (x, y, z)
    n = len(coords)
    out = 0
    bit = 0
    while any(c >> bit for c in coords):
        for k, c in enumerate(coords):
            out |= ((c >> bit) & 1) << (bit * n + k)
        bit += 1
    return out


def demorton(index, dims):
    coords = [0] * dims
    bit = 0
    while index >> (bit * dims):
        for k in range(dims):
            coords[k] |= ((index >> (bit * dims + k)) & 1) << bit
        bit += 1
    return tuple(coords)


def level_offset(level, n):
    """The nodes before a level in a tree with n children per node: (n^level - 1) / (n - 1)."""
    return (n ** level - 1) // (n - 1)


def availability_index(coord):
    """The bit of a local tile coordinate (level, x, y[, z]) in a subtree's tile or content availability."""
    n = 4 if len(coord) == 3 else 8
    return level_offset(coord[0], n) + morton(*coord[1:])


def child_coords(coord):
    """A tile's children in Morton order, as (level + 1, 2x + dx, 2y + dy[, 2z + dz])."""
    level, rest = coord[0], coord[1:]
    out = []
    for m in range(2 ** len(rest)):
        d = demorton(m, len(rest))
        out.append((level + 1,) + tuple(2 * c + dc for c, dc in zip(rest, d)))
    return out


def all_coords(levels, dims):
    """Every local coordinate of a subtree of `levels` levels, in availability order."""
    out = []
    for level in range(levels):
        for m in range(2 ** (dims * level)):
            out.append((level,) + demorton(m, dims))
    return out


def child_coords_at(levels, dims):
    """The local coordinates one level below a subtree's deepest level, in Morton order."""
    return [(levels,) + demorton(m, dims) for m in range(2 ** (dims * levels))]


def implicit_bounds(volume, coord):
    """The bounding volume of an implicit tile: the root's box or region halved along x and y (and z or height
    for an octree) `level` times, the (x, y[, z]) cell taken."""
    kind, v = volume
    level, rest = coord[0], coord[1:]
    n = 2 ** level
    if kind == "box":
        centre, ax, ay, az = np.array(v[0:3]), np.array(v[3:6]), np.array(v[6:9]), np.array(v[9:12])
        axes = [ax, ay, az]
        new_axes = []
        for k, a in enumerate(axes):
            if k < len(rest):
                i = rest[k]
                centre = centre + a * ((2 * i + 1) / n - 1.0)
                new_axes.append(a / n)
            else:
                new_axes.append(a)
        return ("box", [float(c) for c in centre] + [float(c) for a in new_axes for c in a])
    if kind == "region":
        west, south, east, north, low, high = v
        x, y = rest[0], rest[1]
        dl, dp = (east - west) / n, (north - south) / n
        out = [west + x * dl, south + y * dp, west + (x + 1) * dl, south + (y + 1) * dp, low, high]
        if len(rest) == 3:
            dh = (high - low) / n
            out[4], out[5] = low + rest[2] * dh, low + (rest[2] + 1) * dh
        return ("region", out)
    raise TilesError("an implicit tileset's bounding volume is a box or a region, not a sphere")


def implicit_error(root_error, level):
    return root_error / 2.0 ** level


def subtree_root(coord, subtree_levels):
    """The subtree root holding a global coordinate: the ancestor at the greatest multiple of subtreeLevels."""
    level = coord[0]
    root_level = level - level % subtree_levels
    shift = level - root_level
    return (root_level,) + tuple(c >> shift for c in coord[1:])


def local_coord(coord, root):
    shift = coord[0] - root[0]
    return (shift,) + tuple(c - (r << shift) for c, r in zip(coord[1:], root[1:]))


def template(uri, coord):
    names = ("level", "x", "y", "z")
    out = uri
    for name, value in zip(names, coord):
        out = out.replace("{" + name + "}", str(value))
    return out


def _bits(indices, count):
    data = bytearray((count + 7) // 8)
    for i in indices:
        data[i >> 3] |= 1 << (i & 7)
    return bytes(data)


def _availability(indices, count):
    present = set(indices)
    if not present:
        return {"constant": 0, "availableCount": 0}, None
    if len(present) == count:
        return {"constant": 1}, None
    return {"availableCount": len(present)}, _bits(present, count)


def subtree_write(scheme, levels, tiles, contents, children):
    """A subtree file: `tiles`, `contents` and `children` are sets of local coordinates (children at level
    `levels`); each availability is a constant when it is all 0 or all 1, else a bitstream in the internal buffer
    at an 8-byte-aligned view. A content available on an unavailable tile is an error."""
    dims = SCHEMES[scheme]
    n = 2 ** dims
    tile_count = level_offset(levels, n)
    child_count = n ** levels
    bad = set(contents) - set(tiles)
    if bad:
        raise TilesError(f"content available on unavailable tiles: {sorted(bad)}")
    tile_json, tile_bits = _availability([availability_index(c) for c in tiles], tile_count)
    content_json, content_bits = _availability([availability_index(c) for c in contents], tile_count)
    child_json, child_bits = _availability([morton(*c[1:]) for c in children], child_count)
    views = []
    binary = bytearray()
    for entry, bits in ((tile_json, tile_bits), (content_json, content_bits), (child_json, child_bits)):
        if bits is None:
            continue
        entry["bitstream"] = len(views)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(bits)})
        binary += bits
        binary += b"\x00" * (-len(binary) % 8)
    header = {}
    if views:
        header["buffers"] = [{"byteLength": len(binary)}]
        header["bufferViews"] = views
    header["tileAvailability"] = tile_json
    header["contentAvailability"] = [content_json]
    header["childSubtreeAvailability"] = child_json
    text = json.dumps(header, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 8)
    return struct.pack("<4sIQQ", SUBTREE_MAGIC, 1, len(text), len(binary)) + text + bytes(binary)


def subtree_read(data):
    """A subtree file as {"json": header, "tile": bits, "content": [bits], "child": bits}, each bits a bytes
    object or an int constant."""
    if len(data) < 24 or data[:4] != SUBTREE_MAGIC:
        raise TilesError("not a subtree file")
    version, json_length, binary_length = struct.unpack("<IQQ", data[4:24])
    if version != 1 or len(data) < 24 + json_length + binary_length:
        raise TilesError("subtree version or length is wrong")
    try:
        header = json.loads(data[24:24 + json_length].decode("utf-8"))
    except ValueError as e:
        raise TilesError(f"subtree JSON: {e}") from None
    binary = data[24 + json_length:24 + json_length + binary_length]
    views = header.get("bufferViews", [])
    buffers = header.get("buffers", [])

    def bits(entry):
        if not isinstance(entry, dict):
            raise TilesError("an availability is an object")
        if "constant" in entry:
            if entry["constant"] not in (0, 1):
                raise TilesError("an availability constant is 0 or 1")
            return int(entry["constant"])
        if "bitstream" not in entry or not isinstance(entry["bitstream"], int) or entry["bitstream"] >= len(views):
            raise TilesError("an availability names a constant or a bufferView")
        view = views[entry["bitstream"]]
        if view.get("buffer", 0) >= len(buffers) or "uri" in buffers[view.get("buffer", 0)]:
            raise TilesError("the reference reads availability from the internal buffer only")
        start, length = int(view["byteOffset"]), int(view["byteLength"])
        if start + length > len(binary):
            raise TilesError("a bufferView lies outside the binary chunk")
        return bytes(binary[start:start + length])

    contents = header.get("contentAvailability", [])
    if not isinstance(contents, list):
        raise TilesError("contentAvailability is a list")
    return {"json": header, "tile": bits(header.get("tileAvailability")),
            "content": [bits(c) for c in contents], "child": bits(header.get("childSubtreeAvailability"))}


def _bit(bits, index):
    if isinstance(bits, int):
        return bool(bits)
    if index >> 3 >= len(bits):
        return False
    return bool((bits[index >> 3] >> (index & 7)) & 1)


def tile_available(subtree, coord):
    return _bit(subtree["tile"], availability_index(coord))


def content_available(subtree, coord, which=0):
    if which >= len(subtree["content"]):
        return False
    return _bit(subtree["content"][which], availability_index(coord))


def child_available(subtree, coord):
    return _bit(subtree["child"], morton(*coord[1:]))


# -------------------------------------------------------------------------------------------------------- tilesets


def content_kind(uri):
    ext = os.path.splitext(str(uri))[1].lower()
    return CONTENT_KINDS.get(ext, "unsupported")


def _volume_errors(bv, what, errors, implicit=False):
    if not isinstance(bv, dict) or sum(k in bv for k in ("box", "region", "sphere")) != 1:
        errors.append(("TL4", f"{what}: boundingVolume holds exactly one of box, region, sphere"))
        return None
    if "box" in bv:
        v = bv["box"]
        if not isinstance(v, list) or len(v) != 12 or not all(_is_number(c) for c in v):
            errors.append(("TL4", f"{what}: a box is 12 numbers (centre and three half-axes)"))
            return None
        return ("box", [float(c) for c in v])
    if "region" in bv:
        v = bv["region"]
        if not isinstance(v, list) or len(v) != 6 or not all(_is_number(c) for c in v) or v[1] > v[3] or v[4] > v[5]:
            errors.append(("TL4", f"{what}: a region is [west, south, east, north, min height, max height] in "
                                  "radians and metres, south at most north and min at most max"))
            return None
        return ("region", [float(c) for c in v])
    v = bv["sphere"]
    if not isinstance(v, list) or len(v) != 4 or not all(_is_number(c) for c in v) or v[3] < 0:
        errors.append(("TL4", f"{what}: a sphere is [x, y, z, radius] with a non-negative radius"))
        return None
    if implicit:
        errors.append(("TL4", f"{what}: an implicit tileset's bounding volume is a box or a region, not a sphere"))
        return None
    return ("sphere", [float(c) for c in v])


def _tile_errors(tile, what, errors, depth=0):
    if not isinstance(tile, dict):
        errors.append(("TL4", f"{what}: a tile is an object"))
        return
    implicit = tile.get("implicitTiling")
    _volume_errors(tile.get("boundingVolume"), what, errors, implicit=implicit is not None)
    if "viewerRequestVolume" in tile:
        _volume_errors(tile["viewerRequestVolume"], what + " viewerRequestVolume", errors)
    if not _is_number(tile.get("geometricError")) or tile["geometricError"] < 0:
        errors.append(("TL4", f"{what}: geometricError is a non-negative number"))
    if depth == 0 and tile.get("refine") not in REFINES:
        errors.append(("TL4", f"{what}: the root's refine is ADD or REPLACE"))
    elif "refine" in tile and tile["refine"] not in REFINES:
        errors.append(("TL4", f"{what}: refine is ADD or REPLACE"))
    if "transform" in tile:
        t = tile["transform"]
        if not isinstance(t, list) or len(t) != 16 or not all(_is_number(c) for c in t):
            errors.append(("TL4", f"{what}: transform is 16 numbers"))
    contents = []
    if "content" in tile:
        contents.append(tile["content"])
    if "contents" in tile:
        if not isinstance(tile["contents"], list):
            errors.append(("TL4", f"{what}: contents is a list"))
        else:
            contents.extend(tile["contents"])
    for c in contents:
        if not isinstance(c, dict) or not isinstance(c.get("uri"), str) or not c["uri"]:
            errors.append(("TL4", f"{what}: a content has a uri"))
    if implicit is not None:
        if not isinstance(implicit, dict):
            errors.append(("TL4", f"{what}: implicitTiling is an object"))
        else:
            if implicit.get("subdivisionScheme") not in SCHEMES:
                errors.append(("TL4", f"{what}: subdivisionScheme is QUADTREE or OCTREE"))
            levels, available = implicit.get("subtreeLevels"), implicit.get("availableLevels")
            if not isinstance(levels, int) or isinstance(levels, bool) or levels < 1:
                errors.append(("TL4", f"{what}: subtreeLevels is a positive integer"))
            if not isinstance(available, int) or isinstance(available, bool) or available < 1 \
                    or (isinstance(levels, int) and available < levels):
                errors.append(("TL4", f"{what}: availableLevels is an integer of at least subtreeLevels"))
            uri = implicit.get("subtrees", {}).get("uri") if isinstance(implicit.get("subtrees"), dict) else None
            if not isinstance(uri, str) or "{level}" not in uri:
                errors.append(("TL4", f"{what}: subtrees.uri is a template with {{level}}"))
            if "children" in tile:
                errors.append(("TL4", f"{what}: an implicit tile has no children of its own"))
        return
    children = tile.get("children", [])
    if not isinstance(children, list):
        errors.append(("TL4", f"{what}: children is a list"))
        return
    for k, child in enumerate(children):
        _tile_errors(child, f"{what}/children[{k}]", errors, depth + 1)


def tileset_errors(obj):
    """The TL4 errors of a tileset JSON object (or text), each as (code, message); empty when it is well formed."""
    errors = []
    if isinstance(obj, (bytes, str)):
        try:
            obj = json.loads(obj)
        except ValueError as e:
            return [("TL4", f"tileset JSON: {e}")]
    if not isinstance(obj, dict):
        return [("TL4", "a tileset is a JSON object")]
    asset = obj.get("asset")
    if not isinstance(asset, dict) or asset.get("version") not in VERSIONS:
        errors.append(("TL4", "asset.version is \"1.0\" or \"1.1\""))
    if not _is_number(obj.get("geometricError")) or obj["geometricError"] < 0:
        errors.append(("TL4", "the tileset's geometricError is a non-negative number"))
    if "root" not in obj:
        errors.append(("TL4", "a tileset has a root tile"))
    else:
        _tile_errors(obj["root"], "root", errors)
    return errors


def _normalise(tile, base, parent_matrix, parent_refine, depth):
    matrix = parent_matrix if "transform" not in tile else compose(parent_matrix, mat4(tile["transform"]))
    refine = tile.get("refine", parent_refine)
    contents = []
    if "content" in tile:
        contents.append(tile["content"]["uri"])
    contents.extend(c["uri"] for c in tile.get("contents", []))
    bv = tile["boundingVolume"]
    kind = next(k for k in ("box", "region", "sphere") if k in bv)
    out = {"volume": (kind, [float(c) for c in bv[kind]]), "error": float(tile["geometricError"]),
           "refine": refine, "matrix": matrix, "contents": [base + c for c in contents],
           "children": [], "request": None, "implicit": None, "coord": None, "depth": depth, "base": base}
    if "viewerRequestVolume" in tile:
        rv = tile["viewerRequestVolume"]
        rk = next(k for k in ("box", "region", "sphere") if k in rv)
        out["request"] = (rk, [float(c) for c in rv[rk]])
    if "implicitTiling" in tile:
        it = tile["implicitTiling"]
        out["implicit"] = {"scheme": it["subdivisionScheme"], "subtreeLevels": int(it["subtreeLevels"]),
                           "availableLevels": int(it["availableLevels"]), "subtrees": base + it["subtrees"]["uri"],
                           "contents": [base + c for c in contents], "root": out}
        out["coord"] = (0, 0, 0) if it["subdivisionScheme"] == "QUADTREE" else (0, 0, 0, 0)
    else:
        out["children"] = [_normalise(c, base, matrix, refine, depth + 1) for c in tile.get("children", [])]
    return out


def parse_tileset(obj, base="", matrix=None):
    """A tileset as its normalised root tile: `volume`, `error`, `refine` (inherited), `matrix` (composed with
    the ancestors and `matrix`), `contents` (uris relative to `base`), `children`, `request`, `implicit`.
    Raises TilesError on the first TL4 error."""
    errors = tileset_errors(obj)
    if errors:
        raise TilesError(errors[0][1])
    if isinstance(obj, (bytes, str)):
        obj = json.loads(obj)
    root = _normalise(obj["root"], base, IDENTITY if matrix is None else np.asarray(matrix, dtype=float), None, 0)
    root["tilesetError"] = float(obj["geometricError"])
    return root


# --------------------------------------------------------------------------------------------------------- content


_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def glb_pack(header, binary):
    """A binary glTF from its JSON header and binary buffer."""
    text = json.dumps(header, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary = bytes(binary) + b"\x00" * (-len(binary) % 4)
    length = 12 + 8 + len(text) + (8 + len(binary) if binary else 0)
    out = struct.pack("<4sII", GLB_MAGIC, 2, length) + struct.pack("<I4s", len(text), b"JSON") + text
    if binary:
        out += struct.pack("<I4s", len(binary), b"BIN\x00") + binary
    return out


def glb_binary(data):
    """The BIN chunk of a binary glTF."""
    return _glb_chunks(data)[1]


def _glb_chunks(data):
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise TilesError("not a binary glTF")
    version, length = struct.unpack("<II", data[4:12])
    if version != 2 or length != len(data):
        raise TilesError("binary glTF version or length is wrong")
    pos = 12
    header, binary = None, b""
    while pos + 8 <= length:
        chunk_length, chunk_type = struct.unpack("<I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + chunk_length]
        if len(chunk) != chunk_length:
            raise TilesError("a glTF chunk is truncated")
        if chunk_type == b"JSON":
            try:
                header = json.loads(chunk.decode("utf-8"))
            except ValueError as e:
                raise TilesError(f"glTF JSON: {e}") from None
        elif chunk_type == b"BIN\x00":
            binary = bytes(chunk)
        else:
            raise TilesError(f"unknown glTF chunk {chunk_type!r}")
        pos += 8 + chunk_length
    if header is None:
        raise TilesError("a binary glTF has a JSON chunk")
    return header, binary


def _accessor(header, binary, index):
    try:
        acc = header["accessors"][index]
    except (KeyError, IndexError, TypeError):
        raise TilesError(f"accessor {index} is missing") from None
    if "sparse" in acc or "bufferView" not in acc:
        raise TilesError("the reference reads dense accessors with a bufferView only")
    view = header["bufferViews"][acc["bufferView"]]
    if view.get("buffer", 0) != 0 or "uri" in header["buffers"][0]:
        raise TilesError("the reference reads the internal buffer only")
    fmt, size = _COMPONENT[acc["componentType"]]
    count = _TYPE_COUNT[acc["type"]]
    n = int(acc["count"])
    stride = int(view.get("byteStride", size * count))
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    if start + (n - 1) * stride + size * count > len(binary) or start + (n - 1) * stride + size * count > \
            int(view.get("byteOffset", 0)) + int(view["byteLength"]):
        raise TilesError("an accessor lies outside its bufferView")
    out = np.empty((n, count), dtype=float)
    for i in range(n):
        off = start + i * stride
        out[i] = struct.unpack_from("<" + fmt * count, binary, off)
    return out


def _node_matrix(node):
    if "matrix" in node:
        return mat4(node["matrix"])
    m = np.eye(4)
    t = node.get("translation", [0.0, 0.0, 0.0])
    r = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    s = node.get("scale", [1.0, 1.0, 1.0])
    x, y, z, w = r
    rot = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m[:3, :3] = rot @ np.diag(s)
    m[:3, 3] = t
    return m


def glb_read(data):
    """The triangle meshes of a binary glTF: for every mesh primitive of mode 4 reached from the default scene (or
    every node when there is none), its positions after the node hierarchy and the y-up to z-up rotation, and
    its triangles' vertex indices (unindexed primitives are numbered in order)."""
    header, binary = _glb_chunks(data)
    nodes = header.get("nodes", [])
    scenes = header.get("scenes", [])
    if scenes:
        roots = scenes[header.get("scene", 0)].get("nodes", [])
    else:
        children = {c for n in nodes for c in n.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    meshes = []
    stack = [(i, IDENTITY) for i in reversed(roots)]
    seen = set()
    while stack:
        index, parent = stack.pop()
        if index in seen:
            raise TilesError("the node hierarchy is a tree")
        seen.add(index)
        node = nodes[index]
        m = compose(parent, _node_matrix(node))
        if "mesh" in node:
            for prim in header["meshes"][node["mesh"]].get("primitives", []):
                if prim.get("mode", 4) != 4 or "POSITION" not in prim.get("attributes", {}):
                    continue
                positions = _accessor(header, binary, prim["attributes"]["POSITION"])
                if positions.shape[1] != 3:
                    raise TilesError("POSITION is VEC3")
                if "indices" in prim:
                    idx = _accessor(header, binary, prim["indices"])[:, 0].astype(int)
                else:
                    idx = np.arange(len(positions))
                if len(idx) % 3:
                    raise TilesError("a triangle primitive's index count is a multiple of 3")
                if len(idx) and (idx.min() < 0 or idx.max() >= len(positions)):
                    raise TilesError("an index is outside the positions")
                world = apply_all(compose(Y_UP_TO_Z_UP, m), positions)
                meshes.append({"positions": world, "indices": idx.reshape(-1, 3)})
        for c in reversed(node.get("children", [])):
            stack.append((c, m))
    return meshes


def glb_write(meshes, node_translation=None, node_matrix=None, index_type=5123):
    """A binary glTF of (positions, indices) pairs, one node per mesh (sharing the optional node transform);
    indices None writes an unindexed primitive. For tests and the example tileset."""
    binary = bytearray()
    views, accessors, gltf_meshes, nodes = [], [], [], []
    for positions, indices in meshes:
        pos = np.asarray(positions, dtype=float).reshape(-1, 3)
        data = struct.pack("<%df" % pos.size, *pos.flatten().tolist())
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data), "target": 34962})
        binary += data
        binary += b"\x00" * (-len(binary) % 4)
        accessors.append({"bufferView": len(views) - 1, "componentType": 5126, "count": len(pos), "type": "VEC3",
                          "min": [float(v) for v in pos.min(axis=0)], "max": [float(v) for v in pos.max(axis=0)]})
        primitive = {"attributes": {"POSITION": len(accessors) - 1}, "mode": 4}
        if indices is not None:
            idx = [int(i) for tri in indices for i in tri]
            fmt = _COMPONENT[index_type][0]
            data = struct.pack("<%d%s" % (len(idx), fmt), *idx)
            views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data), "target": 34963})
            binary += data
            binary += b"\x00" * (-len(binary) % 4)
            accessors.append({"bufferView": len(views) - 1, "componentType": index_type, "count": len(idx),
                              "type": "SCALAR"})
            primitive["indices"] = len(accessors) - 1
        gltf_meshes.append({"primitives": [primitive]})
        node = {"mesh": len(gltf_meshes) - 1}
        if node_translation is not None:
            node["translation"] = [float(v) for v in node_translation]
        if node_matrix is not None:
            node["matrix"] = [float(v) for v in node_matrix]
        nodes.append(node)
    header = {"asset": {"version": "2.0", "generator": "tiles3d_reference"},
              "buffers": [{"byteLength": len(binary)}], "bufferViews": views, "accessors": accessors,
              "meshes": gltf_meshes, "nodes": nodes, "scenes": [{"nodes": list(range(len(nodes)))}], "scene": 0}
    return glb_pack(header, binary)


def b3dm_write(glb, rtc=None):
    """A Batched 3D Model (legacy) around a binary glTF: a feature table with BATCH_LENGTH 0 and the optional
    RTC_CENTER, padded so the glTF starts on an 8-byte boundary and the tile ends on one."""
    table = {"BATCH_LENGTH": 0}
    if rtc is not None:
        table["RTC_CENTER"] = [float(v) for v in rtc]
    text = json.dumps(table, separators=(",", ":")).encode("utf-8")
    text += b" " * (-(28 + len(text)) % 8)
    body = text + bytes(glb)
    body += b"\x00" * (-(28 + len(body)) % 8)
    return struct.pack("<4sIIIIII", B3DM_MAGIC, 1, 28 + len(body), len(text), 0, 0, 0) + body


def b3dm_glb(data):
    """The binary glTF inside a b3dm and its RTC_CENTER (or None)."""
    if len(data) < 28 or data[:4] != B3DM_MAGIC:
        raise TilesError("not a b3dm")
    version, length, ft_json, ft_bin, bt_json, bt_bin = struct.unpack("<IIIIII", data[4:28])
    if version != 1 or length > len(data):
        raise TilesError("b3dm version or length is wrong")
    start = 28 + ft_json + ft_bin + bt_json + bt_bin
    if start + 12 > length:
        raise TilesError("a b3dm holds a binary glTF")
    try:
        table = json.loads(data[28:28 + ft_json].decode("utf-8")) if ft_json else {}
    except ValueError as e:
        raise TilesError(f"feature table JSON: {e}") from None
    rtc = table.get("RTC_CENTER")
    if rtc is not None:
        rtc = tuple(_numbers(rtc, 3, "RTC_CENTER"))
    glb_length = struct.unpack("<I", data[start + 8:start + 12])[0]
    return bytes(data[start:start + glb_length]), rtc


def content_meshes(kind, data):
    """The meshes of a content in the tile's frame (z-up, RTC_CENTER added)."""
    if kind == "glb":
        return glb_read(data)
    if kind == "b3dm":
        glb, rtc = b3dm_glb(data)
        meshes = glb_read(glb)
        if rtc is not None:
            for m in meshes:
                m["positions"] = m["positions"] + np.array(rtc)
        return meshes
    raise TilesError(f"no meshes for content of kind {kind}")


def tile_meshes(tile, files):
    """The tile's supported contents as meshes in ECEF: the content frame, then the tile's composed matrix."""
    out = []
    for uri in tile["contents"]:
        kind = content_kind(uri)
        if kind not in ("glb", "b3dm"):
            continue
        if uri not in files:
            raise TilesError(f"content {uri} is not in the archive")
        for m in content_meshes(kind, files[uri]):
            out.append({"positions": apply_all(tile["matrix"], m["positions"]), "indices": m["indices"], "uri": uri})
    return out


# ------------------------------------------------------------------------------------------- volumes and the view


def volume_corners(volume, matrix):
    """The eight corners of a bounding volume in ECEF: a box's corners through the matrix; a sphere's bounding
    cube through the matrix; a region's corners from its geodetic extent (a region is never transformed)."""
    kind, v = volume
    if kind == "region":
        west, south, east, north, low, high = v
        return np.array([ecef(math.degrees(lon), math.degrees(lat), h)
                         for h in (low, high) for lat in (south, north) for lon in (west, east)])
    if kind == "box":
        centre, ax, ay, az = np.array(v[0:3]), np.array(v[3:6]), np.array(v[6:9]), np.array(v[9:12])
        local = np.array([centre + sx * ax + sy * ay + sz * az for sz in (-1, 1) for sy in (-1, 1) for sx in (-1, 1)])
    else:
        centre, r = np.array(v[0:3]), v[3]
        local = np.array([centre + np.array([sx * r, sy * r, sz * r]) for sz in (-1, 1) for sy in (-1, 1)
                          for sx in (-1, 1)])
    return apply_all(matrix, local)


def aabb(points):
    pts = np.asarray(points, dtype=float)
    return (tuple(float(v) for v in pts.min(axis=0)), tuple(float(v) for v in pts.max(axis=0)))


def distance_to_aabb(point, box):
    lo, hi = box
    d = 0.0
    for p, a, b in zip(point, lo, hi):
        if p < a:
            d += (a - p) ** 2
        elif p > b:
            d += (p - b) ** 2
    return math.sqrt(d)


def inside_aabb(point, box):
    lo, hi = box
    return all(a <= p <= b for p, a, b in zip(point, lo, hi))


def focal_pixels(width, fov_degrees):
    """The schema's camera: fov is horizontal across the frame width."""
    return (width / 2.0) / math.tan(math.radians(fov_degrees) / 2.0)


def sse_perspective(error, distance, focal):
    if distance <= 0.0:
        return math.inf
    return error * focal / distance


def sse_orthographic(error, pixels_per_m):
    return error * pixels_per_m


def pixels_per_metre(zoom, lat):
    """Web Mercator pixels per ground metre at a latitude: TILE 2^zoom / (2 pi R cos lat)."""
    return TILE * 2.0 ** zoom / (2.0 * math.pi * R_WGS * math.cos(math.radians(lat)))


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n == 0.0:
        raise TilesError("a zero vector has no direction")
    return v / n


def camera_basis(view):
    """Forward, right and down unit vectors of a perspective view in the ground frame (x east, y south, z into
    the ground): forward from position to target, right the cross product of the down hint (0, 0, 1) with forward
    (or of (0, 1, 0), the map's south, when forward is vertical), down forward cross right."""
    forward = _unit(np.subtract(view["target"], view["position"]))
    hint = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(forward, hint))) > 1.0 - 1e-9:
        hint = np.array([0.0, 1.0, 0.0])
    right = _unit(np.cross(hint, forward))
    down = np.cross(forward, right)
    return (tuple(float(c) for c in forward), tuple(float(c) for c in right), tuple(float(c) for c in down))


def project(view, point):
    """The frame pixel of a scene point in a perspective view, or None behind the camera."""
    f, r, d = camera_basis(view)
    p = np.subtract(point, view["position"])
    depth = float(np.dot(p, f))
    if depth <= 0.0:
        return None
    focal = focal_pixels(view["width"], view["fov"])
    return (view["width"] / 2.0 + float(np.dot(p, r)) * focal / depth,
            view["height"] / 2.0 + float(np.dot(p, d)) * focal / depth)


def visible(box, view):
    """Whether a scene-frame AABB may be seen: in a map view, when it overlaps the window rectangle; in a
    perspective view, unless all eight corners lie behind the near plane or beyond one side plane."""
    lo, hi = box
    if view["kind"] == "map":
        w, h = view["width"] / 2.0, view["height"] / 2.0
        return lo[0] <= w and hi[0] >= -w and lo[1] <= h and hi[1] >= -h
    f, r, d = camera_basis(view)
    focal = focal_pixels(view["width"], view["fov"])
    near = float(view.get("near", 0.1))
    corners = [(x, y, z) for z in (lo[2], hi[2]) for y in (lo[1], hi[1]) for x in (lo[0], hi[0])]
    rel = [np.subtract(c, view["position"]) for c in corners]
    depths = [float(np.dot(p, f)) for p in rel]
    if all(z < near for z in depths):
        return False
    half_w, half_h = view["width"] / 2.0, view["height"] / 2.0
    xs = [float(np.dot(p, r)) for p in rel]
    ys = [float(np.dot(p, d)) for p in rel]
    for coords, half in ((xs, half_w), (ys, half_h)):
        if all(c * focal > half * z for c, z in zip(coords, depths)):
            return False
        if all(c * focal < -half * z for c, z in zip(coords, depths)):
            return False
    return True


class MapPlacement:
    """SREP 10's ground: an ECEF point lands at map pixel (px, py) of the Web Mercator window centred on
    (centerLon, centerLat) at `zoom`, as scene point (px - W/2, py - H/2, -(h + heightOffset) s e) with s the
    pixels per metre at the window centre."""

    def __init__(self, center_lon, center_lat, zoom, width, height, height_offset=0.0, exaggeration=1.0):
        self.lon, self.lat, self.zoom = float(center_lon), float(center_lat), float(zoom)
        self.width, self.height = width, height
        self.height_offset, self.exaggeration = float(height_offset), float(exaggeration)
        cx, cy = _ts.world_pixel(self.lon, self.lat, self.zoom)
        self.origin = (cx - width / 2.0, cy - height / 2.0)
        self.scale = pixels_per_metre(self.zoom, self.lat)

    def scene(self, point):
        lon, lat, h = geodetic(*point)
        x, y = _ts.world_pixel(lon, lat, self.zoom)
        return (x - self.origin[0] - self.width / 2.0, y - self.origin[1] - self.height / 2.0,
                -(h + self.height_offset) * self.scale * self.exaggeration)

    def scene_all(self, points):
        return np.array([self.scene(p) for p in np.asarray(points, dtype=float)])

    def viewer(self):
        """The 2D viewer stands at the window's centre at height 0 (in ECEF)."""
        return ecef(self.lon, self.lat, 0.0)

    def viewer_scene(self):
        return (0.0, 0.0, 0.0)


class IdentityPlacement:
    """The tile frame is the scene frame, one metre per unit: for tests of the traversal alone."""
    scale = 1.0
    exaggeration = 1.0

    def scene(self, point):
        return (float(point[0]), float(point[1]), float(point[2]))

    def scene_all(self, points):
        return np.asarray(points, dtype=float)

    def viewer(self):
        return (0.0, 0.0, 0.0)

    def viewer_scene(self):
        return (0.0, 0.0, 0.0)


# ------------------------------------------------------------------------------------------------------- selection


def _load_tileset(files, path, base, matrix, errors=None):
    if path not in files:
        raise TilesError(f"tileset {path} is not available")
    return parse_tileset(files[path], base=base, matrix=matrix)


def _implicit_children(tile, files, cache):
    """The available children of an implicit tile from its subtree files."""
    it = tile["implicit"]
    dims = SCHEMES[it["scheme"]]
    coord = tile["coord"]
    if coord[0] + 1 >= it["availableLevels"]:
        return []
    out = []
    for child in child_coords(coord):
        root = subtree_root(child, it["subtreeLevels"])
        key = template(it["subtrees"], root)
        if key not in cache:
            if root[0] == coord[0] + 1:
                parent_root = subtree_root(coord, it["subtreeLevels"])
                parent_key = template(it["subtrees"], parent_root)
                if not child_available(cache[parent_key], local_coord(child, parent_root)):
                    continue
            if key not in files:
                raise TilesError(f"subtree {key} is not available")
            cache[key] = subtree_read(files[key])
        sub = cache[key]
        local = local_coord(child, root)
        if not tile_available(sub, local):
            continue
        contents = [template(c, child) for k, c in enumerate(it["contents"]) if content_available(sub, local, k)]
        out.append({"volume": implicit_bounds(it["root"]["volume"], child),
                    "error": implicit_error(it["root"]["error"], child[0]), "refine": tile["refine"],
                    "matrix": tile["matrix"], "contents": contents, "children": [], "request": None,
                    "implicit": it, "coord": child, "depth": tile["depth"] + 1, "base": tile["base"]})
    return out


def _children(tile, files, state):
    """A tile's children: its explicit children, its implicit children from the subtrees, or the root of the
    external tileset its content names (in place of the tile, with the tile's matrix)."""
    if tile["implicit"] is not None:
        if tile["coord"] == (0,) * len(tile["coord"]):
            key = template(tile["implicit"]["subtrees"], tile["coord"])
            if key not in state["subtrees"]:
                if key not in files:
                    raise TilesError(f"subtree {key} is not available")
                state["subtrees"][key] = subtree_read(files[key])
            sub = state["subtrees"][key]
            tile["contents"] = [template(c, tile["coord"]) for k, c in enumerate(tile["implicit"]["contents"])
                                if content_available(sub, tile["coord"], k)]
        return _implicit_children(tile, files, state["subtrees"])
    external = [c for c in tile["contents"] if content_kind(c) == "tileset"]
    if external:
        if len(tile["contents"]) != 1 or tile["children"]:
            raise TilesError("a tile with an external tileset has that content alone and no children")
        path = external[0]
        base = path[:path.rfind("/") + 1]
        root = _load_tileset(files, path, base, tile["matrix"])
        root["depth"] = tile["depth"] + 1
        state["loaded"].add(path)
        return [root]
    return tile["children"]


def _tile_aabb(tile, placement):
    corners = volume_corners(tile["volume"], tile["matrix"])
    return aabb(placement.scene_all(corners))


def _centre_latitude(tile):
    corners = volume_corners(tile["volume"], tile["matrix"])
    c = corners.mean(axis=0)
    return geodetic(float(c[0]), float(c[1]), float(c[2]))[1]


def _sse(tile, view, placement, box):
    if view["kind"] == "map":
        lat = _centre_latitude(tile) if not isinstance(placement, IdentityPlacement) else 0.0
        ppm = pixels_per_metre(placement.zoom, lat) if not isinstance(placement, IdentityPlacement) else 1.0
        return sse_orthographic(tile["error"], ppm)
    d = distance_to_aabb(view["position"], box)
    focal = focal_pixels(view["width"], view["fov"])
    return sse_perspective(tile["error"] * placement.scale * placement.exaggeration, d, focal)


def _viewer_inside(tile, view, placement):
    if tile["request"] is None:
        return True
    corners = volume_corners(tile["request"], tile["matrix"])
    box = aabb(placement.scene_all(corners))
    viewer = view["position"] if view["kind"] == "perspective" else placement.viewer_scene()
    return inside_aabb(viewer, box)


def select(files, view, max_error=TILESET_DEFAULTS["maxError"], max_tiles=TILESET_DEFAULTS["maxTiles"],
           max_depth=MAX_DEPTH, placement=None, root="tileset.json"):
    """The contents a view draws, in traversal order: depth first from the root; a tile outside the view or whose
    request volume the viewer is outside is skipped with its subtree; a tile whose screen-space error exceeds
    `max_error` and that has children (and lies above `max_depth`) is refined, its children visited and, with
    REPLACE, its own contents dropped; a tile whose content is an external tileset is always refined into that
    tileset's root; every other visited tile's contents are listed. The traversal visits at most `max_tiles`
    tiles (W-TL1). Returns {"tiles": [...], "visited", "warnings", "loaded"}."""
    placement = placement or IdentityPlacement()
    state = {"subtrees": {}, "loaded": {root}}
    base = root[:root.rfind("/") + 1]
    top = _load_tileset(files, root, base, IDENTITY)
    warnings = []
    out = []
    visited = 0
    stack = [(top, 0)]
    while stack:
        tile, depth = stack.pop()
        if visited >= max_tiles:
            if "W-TL1" not in warnings:
                warnings.append("W-TL1")
            break
        visited += 1
        box = _tile_aabb(tile, placement)
        if not visible(box, view):
            continue
        if not _viewer_inside(tile, view, placement):
            continue
        children = _children(tile, files, state)
        sse = _sse(tile, view, placement, box)
        external = any(content_kind(c) == "tileset" for c in tile["contents"])
        refine = bool(children) and depth < max_depth and (external or sse > max_error)
        if not refine or tile["refine"] == "ADD":
            for uri in tile["contents"]:
                kind = content_kind(uri)
                if kind == "tileset":
                    continue
                if kind == "unsupported" and "W-TL2" not in warnings:
                    warnings.append("W-TL2")
                out.append({"uri": uri, "kind": kind, "depth": depth, "sse": sse, "error": tile["error"],
                            "refine": tile["refine"], "coord": tile["coord"], "aabb": box,
                            "matrix": tile["matrix"]})
        if refine:
            for child in reversed(children):
                stack.append((child, depth + 1))
    return {"tiles": out, "visited": visited, "warnings": warnings,
            "loaded": sorted(state["loaded"] | set(state["subtrees"]))}


# ------------------------------------------------------------------------------------------- resolve and archive


def archive(files):
    """A deterministic ZIP (stored, 1980-01-01, sorted names) of relative paths to bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=ARCHIVE_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0o600 << 16
            z.writestr(info, files[name])
    return buf.getvalue()


def read_archive(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return {i.filename: z.read(i) for i in z.infolist()}
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        raise TilesError(f"not an archive: {e}") from None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def resolve(asset, files, views, placements=None):
    """The resolve step: traverse the tileset for every view (with its placement) and collect the root tileset,
    every external tileset and subtree loaded, and every supported content selected; write them as the archive
    and its SHA-256. A selected content absent from `files` is an error; unsupported contents are not fetched
    (W-TL2)."""
    max_error = float(asset.get("maxError", TILESET_DEFAULTS["maxError"]))
    max_tiles = int(asset.get("maxTiles", TILESET_DEFAULTS["maxTiles"]))
    needed = set()
    warnings = []
    for k, view in enumerate(views):
        placement = placements[k] if placements else None
        out = select(files, view, max_error=max_error, max_tiles=max_tiles, placement=placement)
        needed.update(out["loaded"])
        for e in out["tiles"]:
            if e["kind"] in ("glb", "b3dm"):
                needed.add(e["uri"])
        for w in out["warnings"]:
            if w not in warnings:
                warnings.append(w)
    missing = sorted(n for n in needed if n not in files)
    if missing:
        raise TilesError(f"not available: {', '.join(missing)}")
    collected = {n: files[n] for n in needed}
    data = archive(collected)
    return {"cache": data, "cacheSha256": sha256(data), "files": sorted(collected), "warnings": warnings}


# ----------------------------------------------------------------------------------------------------------- raster


def shade(normal):
    """AMBIENT + (1 - AMBIENT) max(0, n . LIGHT): the light from the north-west above the map."""
    n = _unit(normal)
    return AMBIENT + (1.0 - AMBIENT) * max(0.0, float(np.dot(n, LIGHT)))


def raster_top(buf, height, points, triangles, colour, opacity, width, height_px):
    """Draw triangles (scene-frame points, counter-clockwise outward) into an RGBA buffer seen from above: a
    pixel is covered when its centre lies in the triangle; the surface with the greatest height (-z) wins; faces
    whose normal points down are skipped; the colour is the material colour times the shade."""
    pts = np.asarray(points, dtype=float)
    for tri in triangles:
        a, b, c = pts[tri[0]], pts[tri[1]], pts[tri[2]]
        normal = np.cross(b - a, c - a)
        if np.linalg.norm(normal) == 0.0 or normal[2] >= 0.0:
            continue
        s = shade(normal)
        px = [(p[0] + width / 2.0, p[1] + height_px / 2.0, -p[2]) for p in (a, b, c)]
        x0 = max(0, int(math.floor(min(p[0] for p in px))))
        x1 = min(width - 1, int(math.ceil(max(p[0] for p in px))))
        y0 = max(0, int(math.floor(min(p[1] for p in px))))
        y1 = min(height_px - 1, int(math.ceil(max(p[1] for p in px))))
        if x1 < x0 or y1 < y0:
            continue
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = px
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if area == 0.0:
            continue
        for j in range(y0, y1 + 1):
            yc = j + 0.5
            for i in range(x0, x1 + 1):
                xc = i + 0.5
                w0 = ((bx - xc) * (cy - yc) - (by - yc) * (cx - xc)) / area
                w1 = ((cx - xc) * (ay - yc) - (cy - yc) * (ax - xc)) / area
                w2 = 1.0 - w0 - w1
                if w0 < 0.0 or w1 < 0.0 or w2 < 0.0:
                    continue
                z = w0 * az + w1 * bz + w2 * cz
                if z <= height[j, i]:
                    continue
                height[j, i] = z
                rgb = np.array(colour[:3]) * s
                buf[j, i, :3] = rgb * opacity
                buf[j, i, 3] = opacity


# ------------------------------------------------------------------------------------------------------ the document


def _tiles_child(doc):
    for child in doc["map"]["children"]:
        if child.get("kind") == "tiles3d":
            return child
    raise TilesError("the map has no tiles3d child")


def map_view(doc, frame):
    m = doc["map"]
    zoom = _ts.animated(m["zoom"], frame / float(doc["project"]["fps"]))
    return {"kind": "map", "width": int(m["width"]), "height": int(m["height"]), "zoom": zoom,
            "centerLon": float(m["centerLon"]), "centerLat": float(m["centerLat"])}


def _placement(doc, view, child):
    return MapPlacement(view["centerLon"], view["centerLat"], view["zoom"], view["width"], view["height"],
                        height_offset=float(child.get("heightOffset", TILES_DEFAULTS["heightOffset"])))


def _colour(child):
    value = child.get("color", TILES_DEFAULTS["color"])
    if value is None:
        return DEFAULT_COLOUR
    return _ts.straight(value)[:3]


def _files_of(asset):
    data = asset.get("data")
    if not isinstance(data, (bytes, bytearray)) or sha256(data) != asset.get("cacheSha256"):
        raise TilesError("the archive's SHA-256 differs from the asset's cacheSha256")
    return read_archive(bytes(data))


def select_document(doc, view, frame=0):
    """The selection of the document's tiles3d child under a view: the map view of `frame`, or a perspective
    view in the ground frame of the map at `frame`."""
    child = _tiles_child(doc)
    asset = doc["assets"][child["tileset"]]
    files = _files_of(asset)
    base = map_view(doc, frame)
    placement = _placement(doc, base, child)
    out = select(files, view if view["kind"] == "perspective" else base,
                 max_error=float(asset.get("maxError", TILESET_DEFAULTS["maxError"])),
                 max_tiles=int(asset.get("maxTiles", TILESET_DEFAULTS["maxTiles"])), placement=placement)
    return out


def run(doc, frame):
    """Frame `frame` of the document's map: the selection under the frame's map view, the top-down raster of
    the selected contents the archive holds (W-TL3 for one it lacks), and the digest of the buffer."""
    child = _tiles_child(doc)
    asset = doc["assets"][child["tileset"]]
    files = _files_of(asset)
    view = map_view(doc, frame)
    placement = _placement(doc, view, child)
    out = select(files, view, max_error=float(asset.get("maxError", TILESET_DEFAULTS["maxError"])),
                 max_tiles=int(asset.get("maxTiles", TILESET_DEFAULTS["maxTiles"])), placement=placement)
    warnings = list(out["warnings"])
    w, h = view["width"], view["height"]
    buf = np.zeros((h, w, 4))
    height = np.full((h, w), -math.inf)
    colour = _colour(child)
    opacity = float(child.get("opacity", TILES_DEFAULTS["opacity"]))
    drawn = 0
    max_height = 0.0
    for e in out["tiles"]:
        if e["kind"] not in ("glb", "b3dm"):
            continue
        if e["uri"] not in files:
            if "W-TL3" not in warnings:
                warnings.append("W-TL3")
            continue
        drawn += 1
        for m in content_meshes(e["kind"], files[e["uri"]]):
            world = apply_all(e["matrix"], m["positions"])
            scene = placement.scene_all(world)
            if len(scene):
                max_height = max(max_height, float((-scene[:, 2]).max()) / placement.scale)
            raster_top(buf, height, scene, m["indices"].tolist(), colour, opacity, w, h)
    return {"zoom": float(view["zoom"]), "selected": [e["uri"] for e in out["tiles"]], "drawn": drawn,
            "covered": int((buf[..., 3] > 0).sum()), "maxHeight": max_height, "digest": _ts.digest(buf.tolist()),
            "warnings": warnings, "visited": out["visited"]}


def trace(doc, last):
    """The digests of frames 0 to `last`, each from its own run: the renderer keeps no state between frames, so
    a frame rendered alone is the played frame."""
    return [run(doc, k)["digest"] for k in range(last + 1)]


def _building(lon, lat, width, depth, height):
    """A box building as a glb at the east-north-up frame of (lon, lat): y-up in glTF (x east, y up, z south),
    its twelve triangles wound counter-clockwise seen from outside."""
    hx, hz = width / 2.0, depth / 2.0
    corners = [(-hx, 0.0, -hz), (hx, 0.0, -hz), (hx, 0.0, hz), (-hx, 0.0, hz),
               (-hx, height, -hz), (hx, height, -hz), (hx, height, hz), (-hx, height, hz)]
    faces = [(4, 5, 6, 7), (0, 1, 2, 3), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    centre = np.array([0.0, height / 2.0, 0.0])
    tris = []
    for face in faces:
        a, b, c, d = (np.array(corners[i]) for i in face)
        normal = np.cross(b - a, c - a)
        outward = float(np.dot(normal, (a + b + c + d) / 4.0 - centre)) > 0.0
        if outward:
            tris += [(face[0], face[1], face[2]), (face[0], face[2], face[3])]
        else:
            tris += [(face[0], face[2], face[1]), (face[0], face[3], face[2])]
    return glb_write([(corners, tris)]), enu_matrix(lon, lat, 0.0)


def _offset(lon, lat, east_m, north_m):
    """A point east_m and north_m metres from (lon, lat), to first order."""
    return (lon + east_m / (111320.0 * math.cos(math.radians(lat))), lat + north_m / 111320.0)


def _column_major(m):
    return [float(v) for v in np.asarray(m).T.flatten()]


def _region(lon0, lat0, lon1, lat1, low, high):
    return {"region": [math.radians(lon0), math.radians(lat0), math.radians(lon1), math.radians(lat1), low, high]}


EXAMPLE_CENTRE = (24.94, 60.17)


def example_tileset():
    """A synthetic city tileset in the structure of the CesiumGS samples: a REPLACE root region with four box
    buildings as children (one a b3dm), an external tileset (ADD, a low building and an unsupported point
    cloud) and an implicit quadtree of small boxes (two subtree levels, three available levels)."""
    lon, lat = EXAMPLE_CENTRE
    files = {}
    children = []
    # four buildings within 40 m of the centre: east and north offsets in metres, width, depth, height
    buildings = [(-30.0, 18.0, 12.0, 10.0, 40.0, "b1.glb"),
                 (28.0, 18.0, 10.0, 10.0, 28.0, "b2.glb"),
                 (-30.0, -18.0, 14.0, 8.0, 16.0, "b3.b3dm"),
                 (30.0, -16.0, 8.0, 12.0, 34.0, "b4.glb")]
    for east, north, bw, bd, bh, name in buildings:
        glb, m = _building(*_offset(lon, lat, east, north), bw, bd, bh)
        files[name] = b3dm_write(glb) if name.endswith(".b3dm") else glb
        children.append({"transform": _column_major(m),
                         "boundingVolume": {"box": [0, 0, bh / 2.0, bw / 2.0, 0, 0, 0, bd / 2.0, 0, 0, 0, bh / 2.0]},
                         "geometricError": 0.0, "content": {"uri": name}})
    # the external tileset: a park pavilion and a point cloud the reference cannot draw
    park_region = _region(*_offset(lon, lat, 0.0, -12.0), *_offset(lon, lat, 16.0, 0.0), 0.0, 6.0)
    glb, m = _building(*_offset(lon, lat, 8.0, -6.0), 4.0, 4.0, 4.0)
    files["park/pavilion.glb"] = glb
    files["park/trees.pnts"] = b"pnts" + b"\x00" * 24
    park = {"asset": {"version": "1.1"}, "geometricError": 40.0,
            "root": {"boundingVolume": park_region, "geometricError": 20.0, "refine": "ADD",
                     "children": [{"transform": _column_major(m),
                                   "boundingVolume": {"box": [0, 0, 2, 2, 0, 0, 0, 2, 0, 0, 0, 2]},
                                   "geometricError": 0.0, "content": {"uri": "pavilion.glb"}},
                                  {"boundingVolume": park_region, "geometricError": 0.0,
                                   "content": {"uri": "trees.pnts"}}]}}
    files["park/tileset.json"] = json.dumps(park, separators=(",", ":")).encode()
    children.append({"boundingVolume": park_region, "geometricError": 20.0, "content": {"uri": "park/tileset.json"}})
    # the implicit quadtree of kiosks: a root region west of the park, contents at levels 1 and 2 only, the
    # contents placed by their node matrices relative to the root's transform (the east-north-up frame of the
    # region's centre)
    grid_region = _region(*_offset(lon, lat, -16.0, -12.0), *_offset(lon, lat, 0.0, 0.0), 0.0, 6.0)
    grid_matrix = enu_matrix(*_offset(lon, lat, -8.0, -6.0), 0.0)
    kiosks = {(1, 0, 0): 5.0, (1, 1, 1): 3.0, (2, 1, 0): 6.0, (2, 3, 3): 4.0}
    tiles = {(0, 0, 0)} | set(kiosks)
    root_sub = {c for c in tiles if c[0] < 2}
    root_contents = {c for c in kiosks if c[0] < 2}
    child_subs = {c for c in tiles if c[0] == 2}
    files["grid/subtrees/0.0.0.subtree"] = subtree_write("QUADTREE", 2, root_sub, root_contents, child_subs)
    for c in child_subs:
        files["grid/subtrees/%d.%d.%d.subtree" % c] = subtree_write("QUADTREE", 2, {(0, 0, 0)}, {(0, 0, 0)}, set())
    west, south, east, north = (math.degrees(v) for v in grid_region["region"][:4])
    for c, h in kiosks.items():
        level, x, y = c
        n = 2 ** level
        clon = west + (east - west) * (x + 0.5) / n
        clat = south + (north - south) * (y + 0.5) / n
        glb, m = _building(clon, clat, 3.0, 3.0, h)
        files["grid/kiosk_%d_%d_%d.glb" % c] = _placed_glb(glb, np.linalg.inv(grid_matrix) @ m)
    grid = {"asset": {"version": "1.1"}, "geometricError": 64.0,
            "root": {"transform": _column_major(grid_matrix), "boundingVolume": grid_region, "geometricError": 16.0,
                     "refine": "ADD", "content": {"uri": "kiosk_{level}_{x}_{y}.glb"},
                     "implicitTiling": {"subdivisionScheme": "QUADTREE", "subtreeLevels": 2, "availableLevels": 3,
                                        "subtrees": {"uri": "subtrees/{level}.{x}.{y}.subtree"}}}}
    files["grid/tileset.json"] = json.dumps(grid, separators=(",", ":")).encode()
    children.append({"boundingVolume": grid_region, "geometricError": 16.0, "content": {"uri": "grid/tileset.json"}})
    root = {"asset": {"version": "1.1", "tilesetVersion": "example-1"}, "geometricError": 200.0,
            "root": {"boundingVolume": _region(*_offset(lon, lat, -45.0, -30.0), *_offset(lon, lat, 45.0, 30.0),
                                               0.0, 45.0),
                     "geometricError": 60.0, "refine": "REPLACE", "children": children}}
    files["tileset.json"] = json.dumps(root, separators=(",", ":")).encode()
    return files


def _placed_glb(glb, matrix):
    """A glb whose single node carries an ECEF matrix (as a tile's content may: the glTF transform precedes the
    y-up to z-up rotation, so the ECEF frame is given in y-up terms)."""
    header, binary = _glb_chunks(glb)
    # node matrix N such that Y_UP_TO_Z_UP @ N == matrix @ Y_UP_TO_Z_UP, i.e. positions end in the ENU frame
    n = np.linalg.inv(Y_UP_TO_Z_UP) @ np.asarray(matrix) @ Y_UP_TO_Z_UP
    header["nodes"][0]["matrix"] = _column_major(n)
    return glb_pack(header, binary)


def example_document():
    files = example_tileset()
    views = [map_view({"project": {"fps": 24}, "map": _example_map()}, k) for k in (0, 24, 48)]
    placements = [MapPlacement(v["centerLon"], v["centerLat"], v["zoom"], v["width"], v["height"]) for v in views]
    asset = {"kind": "tileset3d", "id": "hki", "src": "https://example.org/helsinki/tileset.json",
             "cache": "hki.3tz", "maxError": 16.0, "credit": "synthetic"}
    resolved = resolve(asset, files, views, placements)
    asset.update(cacheSha256=resolved["cacheSha256"], data=resolved["cache"])
    return {"project": {"fps": 24, "seed": 0},
            "map": dict(_example_map(), children=[{"kind": "tiles3d", "id": "city", "tileset": "hki"}]),
            "assets": {"hki": asset}}


def _example_map():
    return {"width": 160, "height": 120, "centerLon": EXAMPLE_CENTRE[0], "centerLat": EXAMPLE_CENTRE[1],
            "zoom": {"keys": [[0.0, 15.0], [2.0, 17.0]]}}


def example_camera():
    """A perspective camera in the ground frame of the example map at frame 0: above and south of the centre,
    looking north and down."""
    return {"kind": "perspective", "position": (0.0, 90.0, -70.0), "target": (0.0, -10.0, 0.0), "fov": 60.0,
            "width": 640, "height": 360}


def bad_document():
    doc = example_document()
    doc["map"]["children"][0].update({"tileset": "ghost", "opacity": 2.0, "glow": 1})
    bad = archive({"tileset.json": b'{"asset": {"version": "0.9"}}'})
    doc["assets"]["nowhere"] = {"kind": "tileset3d", "id": "nowhere", "src": "x", "cache": "x.3tz",
                                "cacheSha256": "abc", "maxError": 0.0, "data": bad}
    del doc["assets"]["hki"]
    return doc


def validate_document(doc):
    """TL1 to TL4 and V17 for the document's tileset3d assets and tiles3d children, one entry per code, in
    CODE_ORDER."""
    found = {}

    def add(code, message):
        found.setdefault(code, message)

    assets = {k: v for k, v in doc.get("assets", {}).items() if v.get("kind") == "tileset3d"}
    for key, asset in assets.items():
        for attr in asset:
            if attr not in KNOWN_TILESET + ("kind", "data"):
                add("V17", f"tileset3d {key}: unknown attribute {attr}")
        digest = asset.get("cacheSha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            add("TL1", f"tileset3d {key}: cacheSha256 is 64 hex digits")
        elif "data" in asset and sha256(asset["data"]) != digest:
            add("TL1", f"tileset3d {key}: the archive's SHA-256 differs from cacheSha256")
        me = asset.get("maxError", TILESET_DEFAULTS["maxError"])
        if not _is_number(me) or me <= 0:
            add("TL2", f"tileset3d {key}: maxError is positive")
        mt = asset.get("maxTiles", TILESET_DEFAULTS["maxTiles"])
        if not isinstance(mt, int) or isinstance(mt, bool) or not 1 <= mt <= MAX_TILES:
            add("TL2", f"tileset3d {key}: maxTiles is an integer in 1..{MAX_TILES}")
        if "data" in asset and isinstance(asset["data"], (bytes, bytearray)):
            try:
                files = read_archive(bytes(asset["data"]))
                if "tileset.json" not in files:
                    raise TilesError("the archive holds tileset.json at its root")
                errors = tileset_errors(files["tileset.json"])
                if errors:
                    raise TilesError(errors[0][1])
            except TilesError as e:
                add("TL4", f"tileset3d {key}: {e}")
    for child in doc.get("map", {}).get("children", []):
        if child.get("kind") != "tiles3d":
            continue
        cid = child.get("id", "?")
        for attr in child:
            if attr not in KNOWN_TILES + ("kind",):
                add("V17", f"tiles3d {cid}: unknown attribute {attr}")
        if child.get("tileset") not in assets:
            add("TL3", f"tiles3d {cid}: tileset must name a tileset3d asset")
        op = child.get("opacity", TILES_DEFAULTS["opacity"])
        if not _is_number(op) or not 0.0 <= op <= 1.0:
            add("TL2", f"tiles3d {cid}: opacity is in 0..1")
        if not _is_number(child.get("heightOffset", TILES_DEFAULTS["heightOffset"])):
            add("TL2", f"tiles3d {cid}: heightOffset is a number")
        colour = child.get("color", TILES_DEFAULTS["color"])
        if colour is not None:
            try:
                _ts.colour(colour)
            except _ts.TimeSeriesError as e:
                add("TL2", f"tiles3d {cid}: {e}")
    return [(code, found[code]) for code in CODE_ORDER if code in found]


# ------------------------------------------------------------------------------------------------- the numeric table


TABLE = (
    ("the equator's ECEF x", "ecef(0.0, 0.0, 0.0)[0]", "6378137.0"),
    ("the pole's ECEF z", "round(ecef(0.0, 90.0, 0.0)[2], 6)", "6356752.314245"),
    ("the example centre's height back", "round(geodetic(*ecef(24.94, 60.17, 35.5))[2], 6)", "35.5"),
    ("the east axis at the centre", "tuple(round(c, 6) for c in enu_matrix(24.94, 60.17, 0.0)[:3, 0])", "(-0.421669, 0.90675, 0.0)"),
    ("a Morton index", "morton(0b1010, 0b0011)", "78"),
    ("an octree Morton index", "morton(1, 2, 4)", "273"),
    ("the offset of level 3", "(level_offset(3, 4), level_offset(3, 8))", "(21, 73)"),
    ("a subtree root", "subtree_root((5, 13, 6), 3)", "(3, 3, 1)"),
    ("the sample subtree's tile bits", "SAMPLE_BITS.hex()", "'0d3201'"),
    ("the sample subtree's length", "len(SAMPLE_SUBTREE)", "352"),
    ("an implicit child box", "implicit_bounds(('box', [0.5, 0.5, 0.5, 0.5, 0, 0, 0, 0.5, 0, 0, 0, 0.5]), (1, 1, 0))[1][:3]", "[0.75, 0.25, 0.5]"),
    ("a triangle's glb length", "len(TRI_GLB)", "612"),
    ("the triangle lands z-up", "glb_read(TRI_GLB)[0]['positions'][2].tolist()", "[0.0, 0.0, 1.0]"),
    ("a b3dm's padded feature table", "struct.unpack('<I', b3dm_write(TRI_GLB)[12:16])[0]", "20"),
    ("the focal length of 90 degrees", "round(focal_pixels(400, 90.0), 9)", "200.0"),
    ("a perspective error", "round(sse_perspective(10.0, 995.0, 200.0), 6)", "2.01005"),
    ("pixels per metre at zoom 17 at 60 N", "round(pixels_per_metre(17, 60.17), 6)", "1.683239"),
    ("the far camera's choice", "[e['uri'] for e in select(LOD, CAMERA(-1000.0))['tiles']]", "['low.glb']"),
    ("the near camera's choice", "[e['uri'] for e in select(LOD, CAMERA(-12.0))['tiles']]", "['high.glb']"),
    ("the additive tree near", "len(select(ADDITIVE, CAMERA(-20.0))['tiles'])", "3"),
    ("the implicit tree's choice", "[e['coord'] for e in select(IMPLICIT, CAMERA(-10.0))['tiles']]", "[(0, 0, 0), (1, 1, 0), (2, 2, 0), (2, 3, 1), (1, 0, 1)]"),
    ("the archive of the LOD chain", "RESOLVED['files']", "['low.glb', 'medium.glb', 'tileset.json']"),
    ("the archive's digest", "RESOLVED['cacheSha256'][:12]", "'0976a41fa1fb'"),
    ("the roof's shade", "round(shade((0.0, 0.0, -1.0)), 6)", "0.889898"),
    ("the example's tiles at frame 0", "RUN0['selected']", "['b1.glb', 'b2.glb', 'b3.b3dm', 'b4.glb']"),
    ("the example's cover at frame 0", "RUN0['covered']", "78"),
    ("the example's tiles at frame 48", "len(RUN48['selected'])", "8"),
    ("the example's cover at frame 48", "RUN48['covered']", "1297"),
    ("the example's tallest building", "round(RUN48['maxHeight'], 3)", "40.0"),
    ("the example's digest", "RUN48['digest']", "'2b41b8d27c93'"),
    ("the seek check", "trace(EXAMPLE, 6)[4] == run(EXAMPLE, 4)['digest']", "True"),
    ("the camera's choice over the example", "len(select_document(EXAMPLE, example_camera())['tiles'])", "10"),
    ("the bad document's codes", "[c for c, _ in validate_document(bad_document())]", "['TL1', 'TL2', 'TL3', 'TL4', 'V17']"),
)

_SCOPE = {}


def scope():
    """The names the numeric table evaluates in; built once per process."""
    if _SCOPE:
        return dict(_SCOPE)
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["np"] = np
    s["struct"] = struct
    sample_tiles = {(0, 0, 0), (1, 1, 0), (1, 0, 1)} | {(2,) + demorton(m, 2) for m in (4, 7, 8, 11)}
    sample_children = {(3,) + demorton(m, 2) for m in (1, 2, 13, 14, 17, 18, 29, 30)}
    s["SAMPLE_SUBTREE"] = subtree_write("QUADTREE", 3, sample_tiles, set(), sample_children)
    s["SAMPLE_BITS"] = subtree_read(s["SAMPLE_SUBTREE"])["tile"]
    tri = ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2)])
    s["TRI_GLB"] = glb_write([tri])

    def box(cx=0.0, cy=0.0, cz=0.0, hx=5.0, hy=5.0, hz=5.0):
        return {"box": [cx, cy, cz, hx, 0, 0, 0, hy, 0, 0, 0, hz]}

    def tileset(root):
        return json.dumps({"asset": {"version": "1.1"}, "geometricError": 100.0, "root": root}).encode()

    lod = tileset({"boundingVolume": box(), "geometricError": 10.0, "refine": "REPLACE", "content": {"uri": "low.glb"},
                   "children": [{"boundingVolume": box(), "geometricError": 1.0, "content": {"uri": "medium.glb"},
                                 "children": [{"boundingVolume": box(), "geometricError": 0.0,
                                               "content": {"uri": "high.glb"}}]}]})
    s["LOD"] = {"tileset.json": lod, "low.glb": s["TRI_GLB"], "medium.glb": s["TRI_GLB"], "high.glb": s["TRI_GLB"]}
    s["ADDITIVE"] = {"tileset.json": tileset({"boundingVolume": box(), "geometricError": 10.0, "refine": "ADD",
                                              "content": {"uri": "root.glb"},
                                              "children": [{"boundingVolume": box(-2.5, 0, 0, 2.5, 5, 5),
                                                            "geometricError": 0.0, "content": {"uri": "c0.glb"}},
                                                           {"boundingVolume": box(2.5, 0, 0, 2.5, 5, 5),
                                                            "geometricError": 0.0, "content": {"uri": "c1.glb"}}]}),
                     "root.glb": s["TRI_GLB"], "c0.glb": s["TRI_GLB"], "c1.glb": s["TRI_GLB"]}
    root = {"boundingVolume": {"box": [0, 0, 0, 8, 0, 0, 0, 8, 0, 0, 0, 1]}, "geometricError": 8.0, "refine": "ADD",
            "content": {"uri": "content/{level}_{x}_{y}.glb"},
            "implicitTiling": {"subdivisionScheme": "QUADTREE", "subtreeLevels": 2, "availableLevels": 3,
                               "subtrees": {"uri": "subtrees/{level}.{x}.{y}.subtree"}}}
    tiles = {(0, 0, 0), (1, 1, 0), (1, 0, 1)}
    implicit = {"tileset.json": tileset(root),
                "subtrees/0.0.0.subtree": subtree_write("QUADTREE", 2, tiles, tiles, {(2, 2, 0), (2, 3, 1)}),
                "subtrees/2.2.0.subtree": subtree_write("QUADTREE", 2, {(0, 0, 0)}, {(0, 0, 0)}, set()),
                "subtrees/2.3.1.subtree": subtree_write("QUADTREE", 2, {(0, 0, 0)}, {(0, 0, 0)}, set())}
    for c in ((0, 0, 0), (1, 1, 0), (1, 0, 1), (2, 2, 0), (2, 3, 1)):
        implicit[template("content/{level}_{x}_{y}.glb", c)] = s["TRI_GLB"]
    s["IMPLICIT"] = implicit

    def camera(z):
        return {"kind": "perspective", "position": (0.0, 0.0, z), "target": (0.0, 0.0, 0.0), "fov": 90.0,
                "width": 400, "height": 300}

    s["CAMERA"] = camera
    s["RESOLVED"] = resolve({"kind": "tileset3d", "id": "t", "src": "t/tileset.json", "cache": "t.3tz"}, s["LOD"],
                            [camera(-1000.0), camera(-100.0)])
    s["EXAMPLE"] = example_document()
    s["RUN0"] = run(s["EXAMPLE"], 0)
    s["RUN48"] = run(s["EXAMPLE"], 48)
    _SCOPE.update(s)
    return dict(s)


_same = _ts._same
_fmt = _ts._fmt


def main():
    s = scope()
    print("| Test | Expression | Value |")
    print("|---|---|---|")
    for name, expr, _ in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
