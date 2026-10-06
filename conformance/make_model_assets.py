#!/usr/bin/env python3
"""Writes srep_cases/assets/joints.glb and srep_cases/assets/morphs.glb, the models of the SREP 43, 46 and 47 cases.

The files are committed as static assets (make_cases.py copies srep_cases/assets/ to assets/); this script is how they
were made, in the style of make_clip_asset.py (a hand-written minimal glTF 2.0 writer; no dependency).

A model point (gx, gy, gz) enters scene space as (100 gx, -100 gy, -100 gz) before the object's transform
(CONVENTIONS.md 2.6), so +x of the model is right on screen, +y is UP on screen, and one metre is 100 px.
Every mesh is a flat, unlit, double-sided, single-colour triangle in the plane z = 0 whose vertex average is its
centre c: vertices c + (-0.1, -0.1), c + (0.1, -0.1), c + (0, 0.2). Its pixel centroid is therefore c.

joints.glb (SREP 43 and 47), all nodes roots, names exact:
  "body"  red triangle centred on model (0, -0.8, 0), a fixed anchor: never moves in any case
  "Hand"  empty node at the origin; clip "slide" (2 s): x = 0 m at 0 s, 0.6 m at 1 s, 0.6 m at 2 s
  "Arm"   empty node at the origin; clip "turn" (1 s): a constant rotation of +90 degrees about z (two equal keys)
  "Head"  empty node at the origin that carries a blue triangle centred on model (0.4, 0, 0)
morphs.glb (SREP 46):
  one red triangle centred on the origin with two morph targets named by mesh.extras.targetNames,
  "right" (index 0: +0.4 m in x) and "up" (index 1: +0.4 m in y), default weights 0 0.
"""
import json
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "srep_cases", "assets")
S = 0.7071067811865476          # sin 45 degrees = cos 45 degrees


class Glb:
    """Accessors and buffer views appended in order; every view starts on a 4-byte boundary."""

    def __init__(self):
        self.bin, self.views, self.accs = b"", [], []

    def add(self, data, ctype, kind, count, target=None, minmax=None):
        self.bin += b"\0" * (-len(self.bin) % 4)
        view = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            view["target"] = target
        self.views.append(view)
        self.bin += data
        acc = {"bufferView": len(self.views) - 1, "componentType": ctype, "count": count, "type": kind}
        if minmax:
            acc["min"], acc["max"] = minmax
        self.accs.append(acc)
        return len(self.accs) - 1

    def floats(self, rows, kind, minmax=None, target=None):
        flat = [v for r in rows for v in (r if isinstance(r, tuple) else (r,))]
        return self.add(struct.pack(f"<{len(flat)}f", *flat), 5126, kind, len(rows), target, minmax)

    def indices(self, idx):
        return self.add(struct.pack(f"<{len(idx)}H", *idx), 5123, "SCALAR", len(idx), 34963)

    def write(self, path, gltf):
        gltf = {"asset": {"version": "2.0", "generator": "scene-render-conformance"}, "extensionsUsed": ["KHR_materials_unlit"],
                **gltf, "accessors": self.accs, "bufferViews": self.views}
        data = self.bin + b"\0" * (-len(self.bin) % 4)
        gltf["buffers"] = [{"byteLength": len(data)}]
        js = json.dumps(gltf, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        glb = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(data))
        glb += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(data), 0x004E4942) + data
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(glb)


def triangle(cx, cy):
    return [(cx - 0.1, cy - 0.1, 0.0), (cx + 0.1, cy - 0.1, 0.0), (cx, cy + 0.2, 0.0)]


def box(pts):
    return [[min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]]


def material(rgb, name=None):
    return {**({"name": name} if name else {}), "pbrMetallicRoughness": {"baseColorFactor": [*rgb, 1], "metallicFactor": 0, "roughnessFactor": 1},
            "doubleSided": True, "extensions": {"KHR_materials_unlit": {}}}


def joints():
    g = Glb()
    body, head = triangle(0.0, -0.8), triangle(0.4, 0.0)
    pb = g.floats(body, "VEC3", box(body), 34962)
    ph = g.floats(head, "VEC3", box(head), 34962)
    idx = g.indices([0, 1, 2])
    slide_t = g.floats([0.0, 1.0, 2.0], "SCALAR", [[0.0], [2.0]])
    slide_v = g.floats([(0.0, 0.0, 0.0), (0.6, 0.0, 0.0), (0.6, 0.0, 0.0)], "VEC3")
    turn_t = g.floats([0.0, 1.0], "SCALAR", [[0.0], [1.0]])
    turn_v = g.floats([(0.0, 0.0, S, S)] * 2, "VEC4")
    g.write(os.path.join(OUT, "joints.glb"), {
        "scene": 0, "scenes": [{"nodes": [0, 1, 2, 3]}],
        "nodes": [{"name": "body", "mesh": 0}, {"name": "Hand"}, {"name": "Arm"}, {"name": "Head", "mesh": 1}],
        "meshes": [{"name": "bodyMesh", "primitives": [{"attributes": {"POSITION": pb}, "indices": idx, "material": 0}]},
                   {"name": "headMesh", "primitives": [{"attributes": {"POSITION": ph}, "indices": idx, "material": 1}]}],
        "materials": [material((1, 0, 0)), material((0, 0, 1))],
        "animations": [
            {"name": "slide", "samplers": [{"input": slide_t, "output": slide_v, "interpolation": "LINEAR"}],
             "channels": [{"sampler": 0, "target": {"node": 1, "path": "translation"}}]},
            {"name": "turn", "samplers": [{"input": turn_t, "output": turn_v, "interpolation": "LINEAR"}],
             "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}]},
        ]})


def morphs():
    g = Glb()
    base = triangle(0.0, 0.0)
    pb = g.floats(base, "VEC3", box(base), 34962)
    right = g.floats([(0.4, 0.0, 0.0)] * 3, "VEC3", [[0.4, 0.0, 0.0], [0.4, 0.0, 0.0]], 34962)
    up = g.floats([(0.0, 0.4, 0.0)] * 3, "VEC3", [[0.0, 0.4, 0.0], [0.0, 0.4, 0.0]], 34962)
    idx = g.indices([0, 1, 2])
    g.write(os.path.join(OUT, "morphs.glb"), {
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": "face", "mesh": 0}],
        "meshes": [{"name": "faceMesh", "weights": [0, 0], "extras": {"targetNames": ["right", "up"]},
                    "primitives": [{"attributes": {"POSITION": pb}, "indices": idx, "material": 0,
                                    "targets": [{"POSITION": right}, {"POSITION": up}]}]}],
        "materials": [material((1, 0, 0))]})


def materials():
    """materials.glb (SREP 38): one mesh of two primitives side by side with named materials, `stone` (red, left, x = -0.4 m)
    and `old` (green, right, x = +0.4 m); a materialOverride pair names them."""
    g = Glb()
    left, right = triangle(-0.4, 0.0), triangle(0.4, 0.0)
    pl = g.floats(left, "VEC3", box(left), 34962)
    pr = g.floats(right, "VEC3", box(right), 34962)
    idx = g.indices([0, 1, 2])
    g.write(os.path.join(OUT, "materials.glb"), {
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": "pair", "mesh": 0}],
        "meshes": [{"name": "pairMesh", "primitives": [
            {"attributes": {"POSITION": pl}, "indices": idx, "material": 0},
            {"attributes": {"POSITION": pr}, "indices": idx, "material": 1}]}],
        "materials": [material((1, 0, 0), "stone"), material((0, 1, 0), "old")]})


if __name__ == "__main__":
    joints()
    morphs()
    materials()
    print("wrote srep_cases/assets/joints.glb, morphs.glb and materials.glb")
