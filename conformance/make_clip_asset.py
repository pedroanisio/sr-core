#!/usr/bin/env python3
"""Writes assets/clips.glb for the SREP 42 cases: one unlit red triangle (0.2 m wide and tall, centred on the origin,
facing +Z like the red quad of marker.glb) on a node "tri" with two translation clips, both lasting 1 s:
"left" holds x = 0 m and "right" holds x = 0.6 m (a constant clip needs two keys to have a duration)."""
import json
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))


def build():
    pos = b"".join(struct.pack("<3f", *p) for p in [(-0.1, -0.1, 0), (0.1, -0.1, 0), (0.0, 0.1, 0)])   # 36 bytes
    idx = struct.pack("<3H", 0, 1, 2) + b"\0\0"                                                          # 6 + 2 pad
    times = struct.pack("<2f", 0.0, 1.0)                                                                  # 8
    left = b"".join(struct.pack("<3f", *p) for p in [(0, 0, 0), (0, 0, 0)])                              # 24
    right = b"".join(struct.pack("<3f", *p) for p in [(0.6, 0, 0), (0.6, 0, 0)])                         # 24
    chunks = [(pos, 34962), (idx, 34963), (times, None), (left, None), (right, None)]
    bin_, views = b"", []
    for data, target in chunks:
        v = {"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data) if target != 34963 else 6}
        if target:
            v["target"] = target
        views.append(v)
        bin_ += data
    accs = [
        {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [-0.1, -0.1, 0], "max": [0.1, 0.1, 0]},
        {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        {"bufferView": 2, "componentType": 5126, "count": 2, "type": "SCALAR", "min": [0.0], "max": [1.0]},
        {"bufferView": 3, "componentType": 5126, "count": 2, "type": "VEC3"},
        {"bufferView": 4, "componentType": 5126, "count": 2, "type": "VEC3"},
    ]
    anims = [{"name": name, "samplers": [{"input": 2, "output": out, "interpolation": "LINEAR"}],
              "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}]}
             for name, out in (("left", 3), ("right", 4))]
    gltf = {"asset": {"version": "2.0", "generator": "scene-render-conformance"}, "extensionsUsed": ["KHR_materials_unlit"],
            "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "tri"}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
            "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 1], "metallicFactor": 0, "roughnessFactor": 1},
                           "doubleSided": False, "extensions": {"KHR_materials_unlit": {}}}],
            "animations": anims, "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(bin_)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    bin_ += b"\0" * (-len(bin_) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    return out + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bin_


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "assets"), exist_ok=True)
    open(os.path.join(HERE, "assets", "clips.glb"), "wb").write(build())
    print("wrote assets/clips.glb")
