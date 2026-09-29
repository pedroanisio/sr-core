#!/usr/bin/env python3
"""Writes cases/*.xml, assets/marker.glb and expected.json from the rules in CONVENTIONS.md.

Every case is a 640x360 frame on black with flat, unlit, single-colour objects; run.py measures the
centroid and bounding box of each colour. Expected values are computed here from the normative rules,
so the cases and their answers cannot drift apart.
"""
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

os.makedirs(os.path.join(HERE, "cases"), exist_ok=True)
for name, xml in cases.items():
    open(os.path.join(HERE, "cases", name + ".xml"), "w").write(xml)
json.dump({"frame": [W, H], "tolerance_px": 2.0, "implicit_camera_distance": round(D, 3), "cases": expected},
          open(os.path.join(HERE, "expected.json"), "w"), indent=2)
print(f"wrote {len(cases)} cases, assets/marker.glb, expected.json")
