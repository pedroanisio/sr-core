#!/usr/bin/env python3
"""Writes cases/*.xml, assets/marker.glb and expected.json from the rules in CONVENTIONS.md.

Every case is a 640x360 frame on black with flat, unlit, single-colour objects; run.py measures the
centroid and bounding box of each colour. Expected values are computed here from the normative rules,
so the cases and their answers cannot drift apart.
"""
import glob
import json
import math
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 640, 360
COL = {"red": "#FF0000FF", "green": "#00FF00FF", "blue": "#0000FFFF", "yellow": "#FFFF00FF"}
HFOV = 60.0
D = (W / 2) / math.tan(math.radians(HFOV) / 2)        # implicit camera distance, 554.256
F = D                                                   # focal length in pixels for hfov 60 at this width

cases, expected = {}, {}


def doc(body, extra_assets="", materials="", lights=""):
    mats = "".join(f'<material id="m-{c}" baseColor="{v}" unlit="true" doubleSided="true"/>' for c, v in COL.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<scene version="1.1">\n'
            f'<project width="{W}" height="{H}" fps="24" duration="1" background="#000000FF"/>\n'
            f'<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            + (f"<assets>{extra_assets}</assets>\n" if extra_assets else "")
            + f"<materials>{mats}{materials}</materials>\n"
            + f"<composition>\n{body}\n</composition>\n"
            + (f"<lights>{lights}</lights>\n" if lights else "")
            + "</scene>\n")


def box(cx, cy, w, h):
    return {"cx": round(cx, 2), "cy": round(cy, 2), "w": round(w, 2), "h": round(h, 2)}


# ---------------------------------------------------------------- 2D: rule 1
cases["a1-anchor-translate"] = doc('<shape id="r" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="200" y="120" fill="#FF0000FF"/>')
expected["a1-anchor-translate"] = {"rule": "1.1", "red": box(200, 120, 40, 20)}

# the anchor is the rect's top-left corner, so the sign of the rotation shows: +90 (clockwise on screen) swings the
# rect's centre (20, 10) to (-10, 20) about the anchor; -90 would put it at (10, -20)
cases["a2-anchor-rotate"] = doc('<shape id="r" shape="rect" width="40" height="20" anchorX="0" anchorY="0" x="400" y="180" rotation="90" fill="#FF0000FF"/>')
expected["a2-anchor-rotate"] = {"rule": "1.1 1.3", "red": box(390, 200, 20, 40)}

cases["a3-anchor-scale"] = doc(
    '<shape id="g" shape="rect" width="20" height="20" x="100" y="250" scaleX="2" scaleY="2" fill="#00FF00FF"/>\n'
    '<shape id="b" shape="rect" width="20" height="20" anchorX="20" anchorY="20" x="500" y="300" scaleX="2" scaleY="2" fill="#0000FFFF"/>')
expected["a3-anchor-scale"] = {"rule": "1.1", "green": box(120, 270, 40, 40), "blue": box(480, 280, 40, 40)}

# percent anchor refers to the parent box (the 640x360 frame at the root): 5% x 10% = (32, 36)
cases["a4-anchor-percent"] = doc('<shape id="r" shape="rect" width="40" height="20" anchorX="5%" anchorY="10%" x="300" y="200" fill="#FF0000FF"/>')
expected["a4-anchor-percent"] = {"rule": "1.2", "red": box(300 - 32 + 20, 200 - 36 + 10, 40, 20)}


# colour literals are display sRGB in any working space: grey 128 and an orange stay as written
cases["c1-colour-linear"] = doc(
    '<shape id="g" shape="rect" width="200" height="100" x="60" y="60" fill="#808080FF"/>\n'
    '<shape id="o" shape="rect" width="200" height="100" x="380" y="200" fill="#D2691EFF"/>'
).replace('background="#000000FF"/>', 'background="#000000FF" workingColorSpace="linear-srgb" linearLight="true"/>')
expected["c1-colour-linear"] = {"rule": "1.4", "regions": [
    {"box": [80, 80, 240, 140], "rgb": [128, 128, 128]},
    {"box": [400, 220, 560, 280], "rgb": [210, 105, 30]}]}


# ---------------------------------------------------------------- 3D: rule 2
def project(x, y, z, cam=(W / 2, H / 2, -D), yaw=0.0, pitch=0.0, f=F):
    """Pinhole projection under CONVENTIONS 2.1-2.4 (y down, z away; focal length f pixels, hfov 60 by default)."""
    px, py, pz = x - cam[0], y - cam[1], z - cam[2]
    # inverse of R_yaw (about +y, positive turns toward +x) then R_pitch (positive looks up, toward -y)
    a = math.radians(yaw)
    px, pz = px * math.cos(a) - pz * math.sin(a), px * math.sin(a) + pz * math.cos(a)
    b = math.radians(pitch)
    py, pz = py * math.cos(b) + pz * math.sin(b), -py * math.sin(b) + pz * math.cos(b)
    return W / 2 + f * px / pz, H / 2 + f * py / pz, f / pz


def plane(id, col, x, y, z, s):
    return f'<object3D id="{id}" primitive="plane" width="{s}" height="{s}" x="{x}" y="{y}" z="{z}" material="m-{col}"/>'


cases["b1-implicit-camera"] = doc(plane("p1", "red", 420, 180, 0, 40) + "\n" + plane("p2", "green", 320, 80, 0, 40))
expected["b1-implicit-camera"] = {"rule": "2.1 2.2", "red": box(420, 180, 40, 40), "green": box(320, 80, 40, 40)}

z = round(D, 3)
cx, cy, k = project(220, 260, z)
cases["b2-depth"] = doc(plane("p1", "blue", 220, 260, z, 40) + "\n" + plane("p2", "red", 420, 180, 0, 40))
expected["b2-depth"] = {"rule": "2.1 2.2", "blue": box(cx, cy, 40 * k, 40 * k), "red": box(420, 180, 40, 40)}

cam = f'<camera id="cam" fov="60" x="420" y="180" z="{-z}"/>'
cases["b3-explicit-camera"] = doc(cam + "\n" + plane("p1", "red", 420, 180, 0, 40) + "\n" + plane("p2", "green", 320, 180, 0, 40))
expected["b3-explicit-camera"] = {"rule": "2.3", "red": box(320, 180, 40, 40), "green": box(220, 180, 40, 40)}

cam = f'<camera id="cam" fov="60" x="320" y="180" z="{-z}" yaw="10"/>'
rx, ry, rk = project(320, 180, 0, yaw=10)
cases["b4-yaw-pitch"] = doc(cam + "\n" + plane("p1", "red", 320, 180, 0, 40))
expected["b4-yaw-pitch"] = {"rule": "2.4", "red": {"cx": round(rx, 2), "cy": round(ry, 2)}}
cam = f'<camera id="cam" fov="60" x="320" y="180" z="{-z}" pitch="10"/>'
gx, gy, gk = project(320, 180, 0, pitch=10)
cases["b4b-pitch"] = doc(cam + "\n" + plane("p1", "green", 320, 180, 0, 40))
expected["b4b-pitch"] = {"rule": "2.4", "green": {"cx": round(gx, 2), "cy": round(gy, 2)}}

# roll +30: the camera's right edge dips toward +y, so a point right of centre appears up and to the right
cam = f'<camera id="cam" fov="60" x="320" y="180" z="{-z}" roll="30"/>'
a = math.radians(30)
cases["b6-roll"] = doc(cam + "\n" + plane("p1", "red", 420, 180, 0, 30))
expected["b6-roll"] = {"rule": "2.4", "red": {"cx": round(W / 2 + 100 * math.cos(a), 2), "cy": round(H / 2 - 100 * math.sin(a), 2)}}


# ---------------------------------------------------------------- glTF marker: rule 2.6
def glb(path):
    """Unlit single-sided quads in the glTF z = 0 plane: red 0.4 m at the origin, green 0.2 m 1 m up (+Y) and blue
    0.2 m 0.6 m right (+X), all facing +Z; yellow 0.2 m 0.6 m left, facing -Z. Up/down and left/right mirroring move
    green and blue; a renderer that ignores back-face culling or flips the winding shows yellow."""
    def quad(cx, cy, s, back=False):
        h = s / 2
        q = [(cx - h, cy - h, 0), (cx + h, cy - h, 0), (cx + h, cy + h, 0), (cx - h, cy + h, 0)]
        return q[::-1] if back else q
    quads = [quad(0, 0, 0.4), quad(0, 1.0, 0.2), quad(0.6, 0, 0.2), quad(-0.6, 0, 0.2, back=True)]
    bin_, views, accs, meshes = b"", [], [], []
    for qi, q in enumerate(quads):
        pos = b"".join(struct.pack("<3f", *p) for p in q)
        idx = struct.pack("<6H", 0, 1, 2, 0, 2, 3)            # 12 bytes: keeps the next float view 4-byte aligned
        for data, target in ((pos, 34962), (idx, 34963)):
            views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), "target": target})
            bin_ += data
        xs, ys = [p[0] for p in q], [p[1] for p in q]
        accs.append({"bufferView": 2 * qi, "componentType": 5126, "count": 4, "type": "VEC3", "min": [min(xs), min(ys), 0], "max": [max(xs), max(ys), 0]})
        accs.append({"bufferView": 2 * qi + 1, "componentType": 5123, "count": 6, "type": "SCALAR"})
        meshes.append({"primitives": [{"attributes": {"POSITION": 2 * qi}, "indices": 2 * qi + 1, "material": qi}]})
    mats = [{"pbrMetallicRoughness": {"baseColorFactor": c, "metallicFactor": 0, "roughnessFactor": 1},
             "doubleSided": False, "extensions": {"KHR_materials_unlit": {}}}
            for c in ([1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1], [1, 1, 0, 1])]
    gltf = {"asset": {"version": "2.0", "generator": "scene-render-conformance"}, "extensionsUsed": ["KHR_materials_unlit"],
            "scene": 0, "scenes": [{"nodes": [0, 1, 2, 3]}],
            "nodes": [{"mesh": 0, "name": "red-origin"}, {"mesh": 1, "name": "green-up"}, {"mesh": 2, "name": "blue-right"},
                      {"mesh": 3, "name": "yellow-left-back-facing"}],
            "meshes": meshes, "materials": mats, "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(bin_)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    bin_ += b"\0" * (-len(bin_) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bin_
    open(path, "wb").write(out)


os.makedirs(os.path.join(HERE, "assets"), exist_ok=True)
glb(os.path.join(HERE, "assets", "marker.glb"))
cases["b5-gltf"] = doc('<object3D id="m" primitive="mesh" mesh="mesh-marker" x="320" y="200" z="0"/>',
                       extra_assets='<mesh id="mesh-marker" src="../assets/marker.glb" format="glb"/>')
expected["b5-gltf"] = {"rule": "2.6", "red": box(320, 200, 40, 40), "green": box(320, 100, 20, 20),
                       "blue": box(380, 200, 20, 20), "absent": ["yellow"]}


# ---------------------------------------------------------------- camera: combined yaw and pitch, focal length
cam = f'<camera id="cam" fov="60" x="320" y="180" z="{-z}" yaw="20" pitch="10"/>'
rx, ry, _ = project(420, 230, 0, yaw=20, pitch=10)
cases["b7-yaw-pitch-combined"] = doc(cam + "\n" + plane("p1", "red", 420, 230, 0, 30))
expected["b7-yaw-pitch-combined"] = {"rule": "2.4", "red": {"cx": round(rx, 2), "cy": round(ry, 2)}}

fl = (W / 2) / (36 / (2 * 50))                        # focalLength 50 on the default 36 mm sensor: hfov 2*atan(36/100)
cam = f'<camera id="cam" focalLength="50" x="320" y="180" z="{-z}"/>'
fx, fy, fk = project(400, 180, 0, f=fl)
cases["b8-focal-length"] = doc(cam + "\n" + plane("p1", "red", 400, 180, 0, 40))
expected["b8-focal-length"] = {"rule": "2.3", "red": box(fx, fy, 40 * fk, 40 * fk)}


# ---------------------------------------------------------------- rotations of 3D objects and 2.5D layers
def rot(p, axis, deg):
    """Right-handed rotation of point p about a scene axis (x right, y down, z away)."""
    x, y, zz = p
    c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    if axis == "x":
        return (x, y * c - zz * s_, y * s_ + zz * c)
    if axis == "y":
        return (x * c + zz * s_, y, -x * s_ + zz * c)
    return (x * c - y * s_, x * s_ + y * c, zz)


def shot(corners):
    """Projected bounding box and area centroid of a flat quad under the implicit camera."""
    pts = [project(*c)[:2] for c in corners]
    a = cx_ = cy_ = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        cr = x0 * y1 - x1 * y0
        a, cx_, cy_ = a + cr, cx_ + (x0 + x1) * cr, cy_ + (y0 + y1) * cr
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return box(cx_ / (3 * a), cy_ / (3 * a), max(xs) - min(xs), max(ys) - min(ys))


def placed(w, h, at, steps):
    corners = [(-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0)]
    out = []
    for c in corners:
        for axis, deg in steps:
            c = rot(c, axis, deg)
        out.append((c[0] + at[0], c[1] + at[1], c[2] + at[2]))
    return out


# 2.5: M = T . Rz(rotation) . Ry(rotationY) . Rx(rotationX): rotationX is applied first, then rotationY, then rotation
cases["d1-object3d-rotation-order"] = doc(
    '<object3D id="p" primitive="plane" width="160" height="80" x="320" y="180" z="0" rotation="30" rotationX="50" material="m-blue"/>')
expected["d1-object3d-rotation-order"] = {"rule": "2.5", "blue": shot(placed(160, 80, (320, 180, 0), [("x", 50), ("z", 30)]))}

# 2.5: rotationY > 0 on an object3D is right-handed: its right edge turns toward the viewer (-z)
cases["d3-object3d-rotation-y"] = doc(
    '<object3D id="p" primitive="plane" width="160" height="80" x="320" y="180" z="0" rotationY="40" material="m-blue"/>')
expected["d3-object3d-rotation-y"] = {"rule": "2.5", "blue": shot(placed(160, 80, (320, 180, 0), [("y", 40)]))}

# 5.14: rotationY > 0 on a 2.5D layer (After Effects) turns its right edge away from the viewer (+z)
cases["d2-layer-rotation-y"] = doc(
    '<shape id="r" shape="rect" width="160" height="80" anchorX="80" anchorY="40" x="320" y="180" threeD="true" rotationY="40" fill="#0000FFFF"/>')
expected["d2-layer-rotation-y"] = {"rule": "5.14", "blue": shot(placed(160, 80, (320, 180, 0), [("y", -40)]))}

# ---------------------------------------------------------------- draft SREPs for schema 1.2
def doc12(body, **kw):
    return doc(body, **kw).replace('<scene version="1.1">', '<scene version="1.2">')


def pmtiles_one_png(path, png):
    """A PMTiles v3 archive holding one PNG tile, z0/0/0, with no compression."""
    def varint(n):
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            out.append(b | (0x80 if n else 0))
            if not n:
                return bytes(out)
    # directory: one entry (tile id 0, run length 1, length, offset 0 written as 0 + 1)
    root = varint(1) + varint(0) + varint(1) + varint(len(png)) + varint(1)
    meta = b"{}"
    root_off, meta_off = 127, 127 + len(root)
    data_off = meta_off + len(meta)
    header = b"PMTiles" + bytes([3]) + struct.pack(
        "<11Q", root_off, len(root), meta_off, len(meta), data_off, 0, data_off, len(png), 1, 1, 1)
    # clustered, internal compression none, tile compression none, tile type png, zooms 0..0
    header += bytes([1, 1, 1, 2, 0, 0])
    header += struct.pack("<4i", -1800000000, -850511287, 1800000000, 850511287) + bytes([0]) + struct.pack("<2i", 0, 0)
    assert len(header) == 127
    open(path, "wb").write(header + root + meta + png)


def pmtiles(path, entries, tile_type, minz, maxz):
    """A PMTiles v3 archive of `entries` (tile id, run length, bytes) in id order, with no compression."""
    def varint(n):
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            out.append(b | (0x80 if n else 0))
            if not n:
                return bytes(out)
    ids, last, data = [], 0, b""
    root = varint(len(entries))
    for tid, _, _ in entries:
        root += varint(tid - last)
        last = tid
    root += b"".join(varint(run) for _, run, _ in entries)
    root += b"".join(varint(len(b)) for _, _, b in entries)
    # the first offset is written as offset + 1; the rest follow on contiguously (0)
    root += varint(1) + b"".join(varint(0) for _ in entries[1:])
    data = b"".join(b for _, _, b in entries)
    meta = b"{}"
    root_off, meta_off = 127, 127 + len(root)
    data_off = meta_off + len(meta)
    n = sum(run for _, run, _ in entries)
    header = b"PMTiles" + bytes([3]) + struct.pack(
        "<11Q", root_off, len(root), meta_off, len(meta), data_off, 0, data_off, len(data), n, len(entries), len(entries))
    header += bytes([1, 1, 1, tile_type, minz, maxz])
    header += struct.pack("<4i", -1800000000, -850511287, 1800000000, 850511287) + bytes([0]) + struct.pack("<2i", 0, 0)
    assert len(header) == 127
    open(path, "wb").write(header + root + meta + data)


def png(w, h, pixel):
    """A w x h RGB PNG whose pixel (x, y) is pixel(x, y)."""
    import zlib
    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def mvt_west_half():
    """A Mapbox Vector Tile (2.1) with layer "shapes": one polygon over the tile's west half (extent 4096)."""
    def key(field, wire):
        return bytes([(field << 3) | wire])
    def varint(n):
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            out.append(b | (0x80 if n else 0))
            if not n:
                return bytes(out)
    def lendelim(field, payload):
        return key(field, 2) + varint(len(payload)) + payload
    zz = lambda v: (v << 1) ^ (v >> 31)
    # MoveTo (0, 0); LineTo (2048, 0), (2048, 4096), (0, 4096); ClosePath: clockwise with y down
    cmds = [9, zz(0), zz(0), 26, zz(2048), zz(0), zz(0), zz(4096), zz(-2048), zz(0), 15]
    feature = key(3, 0) + varint(3) + lendelim(4, b"".join(varint(c) for c in cmds))
    layer = key(15, 0) + varint(2) + lendelim(1, b"shapes") + lendelim(2, feature) + key(5, 0) + varint(4096)
    return lendelim(3, layer)


def half_png():
    """A 256 x 256 PNG, the west half red and the east half blue."""
    import zlib
    row = b"\x00" + (b"\xff\x00\x00" * 128) + (b"\x00\x00\xff" * 128)
    raw = zlib.compress(row * 256, 9)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


pmtiles_one_png(os.path.join(HERE, "assets", "halves.pmtiles"), half_png())
# a 256 x 256 Web Mercator map at zoom 0 (the world 512 px wide) shows 90°W-90°E; its tile zoom is 1 for 256 px
# raster tiles, so the one zoom-0 tile is overzoomed: its west half fills the map's left half
MAP = ('<tiles id="t-halves" src="../assets/halves.pmtiles"/>'
       '<map id="map-halves" width="256" height="256" projection="web-mercator" centerLon="0" centerLat="0" zoom="0">'
       '<basemap tiles="t-halves" attribution="false"/></map>')
cases["srep-0009-basemap-raster"] = doc12('<layer id="l" asset="map-halves" x="192" y="52"/>', extra_assets=MAP)
expected["srep-0009-basemap-raster"] = {"rule": "SREP 9", "red": box(256, 180, 128, 256), "blue": box(384, 180, 128, 256)}

# the tile zoom: a 256 px raster tile at map zoom 0 (k = 512 / 2π) is round(log2(2π·k / 256)) = 1, so the red
# zoom-1 tiles are drawn, not the blue zoom-0 tile
BLUE, RED = png(256, 256, lambda x, y: (0, 0, 255)), png(256, 256, lambda x, y: (255, 0, 0))
pmtiles(os.path.join(HERE, "assets", "zooms.pmtiles"), [(0, 1, BLUE), (1, 4, RED)], 2, 0, 1)
cases["srep-0009-basemap-zoom"] = doc12(
    '<layer id="l" asset="map-zooms" x="192" y="52"/>',
    extra_assets='<tiles id="t-zooms" src="../assets/zooms.pmtiles"/>'
    '<map id="map-zooms" width="256" height="256" projection="web-mercator" centerLon="0" centerLat="0" zoom="0">'
    '<basemap tiles="t-zooms" attribution="false"/></map>')
expected["srep-0009-basemap-zoom"] = {"rule": "SREP 9", "regions": [{"box": [196, 56, 444, 304], "rgb": [255, 0, 0]}]}

# the warp: an equirectangular world 256 px wide (k = 256 / 2π px per radian) of a zoom-0 tile whose top quarter
# is red. That quarter spans Mercator latitudes 85.0511° to 66.5133°, at y = 128 - k·φ in the map
QUARTER = png(256, 256, lambda x, y: (255, 0, 0) if y < 64 else (0, 0, 255))
pmtiles_one_png(os.path.join(HERE, "assets", "quarter.pmtiles"), QUARTER)
kq = 256 / (2 * math.pi)
merc = lambda v: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * v))))
y_top, y_bot = 128 - kq * math.radians(merc(0)), 128 - kq * math.radians(merc(0.25))
cases["srep-0009-basemap-warp"] = doc12(
    '<layer id="l" asset="map-quarter" x="192" y="52"/>',
    extra_assets='<tiles id="t-quarter" src="../assets/quarter.pmtiles"/>'
    '<map id="map-quarter" width="256" height="256" projection="equirectangular" centerLon="0" centerLat="0" zoom="0">'
    '<basemap tiles="t-quarter" attribution="false"/></map>')
expected["srep-0009-basemap-warp"] = {"rule": "SREP 9",
                                      "red": box(320, 52 + (y_top + y_bot) / 2, 256, y_bot - y_top)}

# a vector tile: one polygon over the west half, filled red by the style over a blue background layer
pmtiles(os.path.join(HERE, "assets", "west.pmtiles"), [(0, 1, mvt_west_half())], 1, 0, 0)
json.dump({"version": 8, "sources": {"t": {"type": "vector"}},
           "layers": [{"id": "bg", "type": "background", "paint": {"background-color": "#0000ff"}},
                      {"id": "west", "type": "fill", "source": "t", "source-layer": "shapes",
                       "paint": {"fill-color": "#ff0000"}}]},
          open(os.path.join(HERE, "assets", "west-style.json"), "w"))
cases["srep-0009-basemap-vector"] = doc12(
    '<layer id="l" asset="map-west" x="192" y="52"/>',
    extra_assets='<tiles id="t-west" src="../assets/west.pmtiles"/>'
    '<map id="map-west" width="256" height="256" projection="web-mercator" centerLon="0" centerLat="0" zoom="0">'
    '<basemap tiles="t-west" mapStyle="../assets/west-style.json" labels="false" attribution="false"/></map>')
expected["srep-0009-basemap-vector"] = {"rule": "SREP 9", "red": box(256, 180, 128, 256), "blue": box(384, 180, 128, 256)}

# the same map as flat ground facing the implicit camera, centred on the object's origin
cases["srep-0010-map-ground"] = doc12(
    '<object3D id="g" primitive="map" map="map-halves" material="m-white" x="320" y="180"/>', extra_assets=MAP,
    materials='<material id="m-white" baseColor="#FFFFFFFF" unlit="true" doubleSided="true"/>')
expected["srep-0010-map-ground"] = {"rule": "SREP 10", "red": box(256, 180, 128, 256), "blue": box(384, 180, 128, 256)}

# a globe of the halves map facing the implicit camera: 0° longitude towards the camera, east towards +x. A ray
# through screen x < 320 meets the sphere west of 0°, so the red west is the silhouette's left half. The
# silhouette of a sphere of radius r at distance D is a circle of radius r·D/sqrt(D² - r²); a half-disc's
# centroid lies 4R/(3π) from its diameter
RG = 60
RS = RG * D / math.sqrt(D * D - RG * RG)
cases["srep-0010-globe-orientation"] = doc12(
    f'<object3D id="g" primitive="globe" map="map-halves" radius="{RG}" segments="128" material="m-white" x="320" y="180"/>',
    extra_assets=MAP, materials='<material id="m-white" baseColor="#FFFFFFFF" unlit="true" doubleSided="true"/>')
expected["srep-0010-globe-orientation"] = {"rule": "SREP 10", "red": box(320 - 4 * RS / (3 * math.pi), 180, RS, 2 * RS),
                                           "blue": box(320 + 4 * RS / (3 * math.pi), 180, RS, 2 * RS)}

# free fall for 1 s at fixedStep 0.1 with solverIterations 4, 20 px per metre: N = 40 semi-implicit Euler
# substeps of h = 0.025 s move a body g·h²·N(N+1)/2 metres (5.026 m = 100.5 px). Whole steps would give 107.9 px
# and the exact fall 98.1 px, both outside the tolerance, so the case checks the substeps.
G, DT, K, PPM, STEPS = 9.80665, 0.1, 4, 20, 10
FALL = '<physics start="-1" fixedStep="0.1" solverIterations="4" pixelsPerMeter="20"{extra}/>'
N, Hs = STEPS * K, DT / K
cases["srep-0011-rigid3d-fall"] = doc12(
    '<object3D id="s" primitive="sphere" radius="10" material="m-red" x="320" y="100" start="-2">'
    '<rigidBody linearDamping="0" activateAt="-10"/></object3D>').replace("</composition>", "</composition>\n" + FALL.format(extra=""))
expected["srep-0011-rigid3d-fall"] = {"rule": "SREP 11", "red": {"cx": 320, "cy": round(100 + G * Hs * Hs * N * (N + 1) / 2 * PPM, 2)}}

# the same with linearDamping c = 1 at 30 px per metre: damping is applied once per step, v ← v / (1 + c·Δt),
# after its substeps (113.7 px); damping every substep instead would give 109.6 px
def damped_fall(c):
    v = x = 0.0
    for _ in range(STEPS):
        for _ in range(K):
            v += G * Hs
            x += v * Hs
        v /= 1 + c * DT
    return x
cases["srep-0011-rigid3d-damped"] = doc12(
    '<object3D id="s" primitive="sphere" radius="10" material="m-red" x="320" y="100" start="-2">'
    '<rigidBody linearDamping="1" activateAt="-10"/></object3D>').replace(
    "</composition>", "</composition>\n" + FALL.format(extra="").replace('pixelsPerMeter="20"', 'pixelsPerMeter="30"'))
expected["srep-0011-rigid3d-damped"] = {"rule": "SREP 11", "red": {"cx": 320, "cy": round(100 + damped_fall(1) * 30, 2)}}

# velocityX is scene pixels per second: without gravity or damping a body moves 50 px in 1 s
cases["srep-0011-rigid3d-velocity"] = doc12(
    '<object3D id="s" primitive="sphere" radius="10" material="m-red" x="270" y="180" start="-2">'
    '<rigidBody linearDamping="0" velocityX="50" activateAt="-10"/></object3D>').replace(
    "</composition>", "</composition>\n" + FALL.format(extra=' gravityY="0"'))
expected["srep-0011-rigid3d-velocity"] = {"rule": "SREP 11", "red": {"cx": 320, "cy": 180}}

# dropped onto a static box whose top is at y = 250, a sphere of radius 10 comes to rest at y = 240
cases["srep-0011-rigid3d-rest"] = doc12(
    '<object3D id="floor" primitive="box" width="200" height="40" depth="200" material="m-blue" x="320" y="270" start="-3">'
    '<rigidBody type="static"/></object3D>\n'
    '<object3D id="s" primitive="sphere" radius="10" material="m-red" x="320" y="200" start="-3">'
    '<rigidBody activateAt="-10"/></object3D>').replace("</composition>", '</composition>\n<physics start="-2"/>')
expected["srep-0011-rigid3d-rest"] = {"rule": "SREP 11", "red": {"cx": 320, "cy": 240}}

# ---------------------------------------------------------------- SREP 13: outputs with segments
# The composition holds red on [0, 1), green on [1, 2) and blue on [2, 3); each case renders its output "short" at
# one output time ("output" in expected.json) and checks the whole frame's colour or a centroid.
CLOCK = ('<shape id="clock" shape="rect" width="640" height="360" x="0" y="0" fill="#FF0000FF">'
         '<animate property="fill"><key time="0" value="#FF0000FF" interpolation="hold"/>'
         '<key time="1" value="#00FF00FF" interpolation="hold"/><key time="2" value="#0000FFFF" interpolation="hold"/>'
         '</animate></shape>')
FULL = [0, 0, W, H]


def seg_doc(segments, fps=24, extra="", overlay=""):
    out = f'<output id="short" path="out/frame_%04d.png" codec="png-sequence"{overlay}>{segments}</output>'
    d = doc12(CLOCK).replace('duration="1"', 'duration="3"').replace('fps="24"', f'fps="{fps}"')
    d = d.replace('<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>', out)
    return d.replace("<composition>", extra + "<composition>")


def srgb8(v):
    """A linear value as an 8-bit sRGB code."""
    return round(255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055))


# 2..3 at speed 1, then 0..1 at speed 2: output 0.5 is composition 2.5 (blue), output 1.25 is 0.5 (red)
MAP2 = '<segment from="2" to="3"/><segment from="0" to="1" speed="2"/>'
cases["srep-0013-segment-map"] = seg_doc(MAP2)
expected["srep-0013-segment-map"] = {"rule": "SREP 13", "output": {"id": "short", "time": 0.5},
                                     "regions": [{"box": FULL, "rgb": [0, 0, 255]}]}
cases["srep-0013-segment-map-speed"] = seg_doc(MAP2)
expected["srep-0013-segment-map-speed"] = {"rule": "SREP 13", "output": {"id": "short", "time": 1.25},
                                           "regions": [{"box": FULL, "rgb": [255, 0, 0]}]}

# the frame exactly at the join (output 1) belongs to the incoming segment: composition 0, red
cases["srep-0013-segment-join"] = seg_doc(MAP2)
expected["srep-0013-segment-join"] = {"rule": "SREP 13", "output": {"id": "short", "time": 1.0},
                                      "regions": [{"box": FULL, "rgb": [255, 0, 0]}]}

# a backwards remap, 0 -> 3 to 1 -> 1, linear: segment time 0.25 is composition 2.5 (blue)
cases["srep-0013-segment-remap"] = seg_doc(
    '<segment><timeRemap><key time="0" value="3" interpolation="linear"/><key time="1" value="1"/></timeRemap></segment>')
expected["srep-0013-segment-remap"] = {"rule": "SREP 13", "output": {"id": "short", "time": 0.25},
                                       "regions": [{"box": FULL, "rgb": [0, 0, 255]}]}

# blue (2..3) into red (0..1) through a linear crossfade of 0.5 s centred on the join at 1: at output 0.875 the
# progress is 0.25 and the incoming side, 0.125 s before its start, is clamped to composition 0 (red). The mix is
# a(1 - p) + b p on linear working values (the default working space).
cases["srep-0013-segment-crossfade"] = seg_doc(
    '<segment from="2" to="3"><transition type="crossfade" duration="0.5" curve="linear"/></segment>'
    '<segment from="0" to="1"/>')
expected["srep-0013-segment-crossfade"] = {"rule": "SREP 13", "output": {"id": "short", "time": 0.875},
                                       "regions": [{"box": FULL, "rgb": [srgb8(0.25), 0, srgb8(0.75)]}]}

# clamping: a remap reaching composition time -0.5 at its start. The yellow square moves x = 100 + 200·t and
# extrapolates linearly before 0, so an unclamped map would draw it at x = 0; clamped, it is at x = 100
MOVER = ('<shape id="mv" shape="rect" width="20" height="20" x="100" y="170" fill="#FFFF00FF">'
         '<animate property="x" extrapolateBefore="linear"><key time="0" value="100" interpolation="linear"/>'
         '<key time="1" value="300"/></animate></shape>')
cases["srep-0013-segment-clamp"] = seg_doc(
    '<segment><timeRemap><key time="0" value="-0.5" interpolation="linear"/><key time="1" value="0.5"/></timeRemap></segment>'
    ).replace(CLOCK, MOVER)
expected["srep-0013-segment-clamp"] = {"rule": "SREP 13", "output": {"id": "short", "time": 0.0}, "yellow": box(110, 180, 20, 20)}

# reframing: a 360 x 360 crop of the 640 x 360 frame with the segment's focusX 0 shows columns 0..359: the left
# half's red over 320 columns, then 40 of the right half's blue
HALVES = ('<shape id="l" shape="rect" width="320" height="360" x="0" y="0" fill="#FF0000FF"/>'
          '<shape id="r" shape="rect" width="320" height="360" x="320" y="0" fill="#0000FFFF"/>')
cases["srep-0013-segment-focus"] = seg_doc('<segment from="0" to="1" focusX="0"/>').replace(CLOCK, HALVES).replace(
    'codec="png-sequence"', 'codec="png-sequence" layout="sq"').replace(
    "</output>\n", '</output>\n<layouts><layout id="sq" width="360" height="360" reframe="crop"/></layouts>\n', 1)
expected["srep-0013-segment-focus"] = {"rule": "SREP 13", "output": {"id": "short", "time": 0.0},
                                       "red": box(160, 180, 320, 360), "blue": box(340, 180, 40, 360)}

# alignment end: the 0.5 s window ends on the join at 1 (0.5..1), so at output 0.75 the linear crossfade is half way:
# 0.5 blue + 0.5 red in linear light (a centred window, 0.75..1.25, would still be all blue)
cases["srep-0013-segment-align-end"] = seg_doc(
    '<segment from="2" to="3"><transition type="crossfade" duration="0.5" curve="linear" alignment="end"/></segment>'
    '<segment from="0" to="1"/>')
expected["srep-0013-segment-align-end"] = {"rule": "SREP 13", "output": {"id": "short", "time": 0.75},
                                           "regions": [{"box": FULL, "rgb": [srgb8(0.5), 0, srgb8(0.5)]}]}

# the overlay's yellow square moves from x = 100 to 500 over output 0..0.8: at output 0.4 its top-left is at
# x = 300, whatever composition time the segment shows (at 10 fps, 0.4 is frame 4)
TAG = ('<symbols><symbol id="tag"><shape id="sq" shape="rect" width="20" height="20" x="100" y="170" fill="#FFFF00FF">'
       '<animate property="x"><key time="0" value="100" interpolation="linear"/><key time="0.8" value="500"/></animate>'
       '</shape></symbol></symbols>')
cases["srep-0013-segment-overlay"] = seg_doc('<segment from="1" to="3" speed="2"/>', fps=10, extra=TAG,
                                             overlay=' overlay="tag"')
expected["srep-0013-segment-overlay"] = {"rule": "SREP 13", "output": {"id": "short", "time": 0.4},
                                         "yellow": box(310, 180, 20, 20)}

# an overlay also draws on an output without segments, in output time (here from composition time 0)
cases["srep-0013-overlay-plain"] = seg_doc("", fps=10, extra=TAG, overlay=' overlay="tag"')
expected["srep-0013-overlay-plain"] = {"rule": "SREP 13", "output": {"id": "short", "time": 0.4},
                                       "yellow": box(310, 180, 20, 20)}

# cases of SREPs 15 and later live in srep_cases/*.json, each {name: {"xml": <document text>, "expected": {...}}};
# an expected entry with "pending": "<reason>" is listed in the kit but not run (the engine does not pass it yet, or
# the SREP states no pixel-level value)
for path in sorted(glob.glob(os.path.join(HERE, "srep_cases", "*.json"))):
    for name, case in json.load(open(path)).items():
        cases[name] = case["xml"]
        expected[name] = case["expected"]

# ---------------------------------------------------------------- SREP 50: key/@carry
# A red square (40 x 40, centre anchor) moves in x: linear 100 -> 400 over 0.5 s, then a spring (100, 10, 1) back to 100.
# The keys are shifted so that the render at composition time 0 is 0.15 s after the spring key (the kit renders frame 0).
def carry_doc(carry):
    u = 0.15
    return doc12(
        '<shape id="r" shape="rect" width="40" height="40" anchorX="20" anchorY="20" x="100" y="180" fill="#FF0000FF">'
        '<animate property="x">'
        f'<key time="{-u - 0.5}" value="100"/>'
        f'<key time="{-u}" value="400" interpolation="spring" stiffness="100" damping="10" mass="1"{carry}/>'
        f'<key time="{2 - u}" value="100"/>'
        '</animate></shape>')


cases["srep-0050-spring-carry"] = carry_doc(' carry="true"')
cases["srep-0050-spring-carry-neutral"] = carry_doc("")

os.makedirs(os.path.join(HERE, "cases"), exist_ok=True)
for name, xml in cases.items():
    open(os.path.join(HERE, "cases", name + ".xml"), "w").write(xml)
json.dump({"frame": [W, H], "tolerance_px": 2.0, "implicit_camera_distance": round(D, 3), "cases": expected},
          open(os.path.join(HERE, "expected.json"), "w"), indent=2)
print(f"wrote {len(cases)} cases, assets/marker.glb, expected.json")
