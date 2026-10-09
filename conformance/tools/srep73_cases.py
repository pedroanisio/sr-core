#!/usr/bin/env python3
"""Writes the SREP 73 kit cases (flock/@orientToVelocity) to srep_cases/srep-0073.json and the sprite
srep_cases/assets/srep73-halves.png (8 x 8: the left half red, the right half blue). A one-agent flock in a 1 x 1 box
places its agent within 1 px of the node's origin at time 0 (the reference's flock init draws positions in the box:
crates/sr-sim/src/flock.rs, init). Upright, the sprite's red half is left of its blue half at the same height.
Assumption (stated in the SREP): a sprite is drawn as a size x size square centred on the agent.
Usage: python3 conformance/tools/srep73_cases.py; then python3 conformance/make_cases.py."""
import json
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PENDING = "SREP 73 is a draft; no engine implements flock/@orientToVelocity yet. The entry keeps the values derived from the SREP"


def png(w, h, pixel):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def doc(flock, version="1.6"):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            '<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="1"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            '<assets><image id="spr" src="../assets/srep73-halves.png" width="8" height="8"/></assets>\n'
            f'<composition>\n{flock}\n</composition>\n</scene>\n')


def main():
    open(os.path.join(CONF, "srep_cases", "assets", "srep73-halves.png"), "wb").write(
        png(8, 8, lambda x, y: (255, 0, 0, 255) if x < 4 else (0, 0, 255, 255)))
    cases = {}

    def add(slug, xml, **e):
        cases[f"srep-0073-{slug}"] = {"xml": xml, "expected": {"rule": "SREP 73", **e, "pending": PENDING}}

    f = '<flock id="f" count="1" seed="3" width="1" height="1" x="320" y="180" shape="{shape}" sprite="spr" size="40"{attr}/>'
    add("upright-sprite", doc(f.format(shape="sprite", attr=' orientToVelocity="false"')),
        red={"cx": 310, "cy": 180, "w": 20, "h": 40}, blue={"cx": 330, "cy": 180, "w": 20, "h": 40})
    # the node's own rotation still turns an upright sprite: 90 degrees clockwise puts red above blue
    add("upright-sprite-node-rotation", doc(f.format(shape="sprite", attr=' orientToVelocity="false" rotation="90"')),
        red={"cx": 320, "cy": 170, "w": 40, "h": 20}, blue={"cx": 320, "cy": 190, "w": 40, "h": 20})
    add("streak-inert", doc(f.format(shape="streak", attr=' orientToVelocity="false"')),
        findings={"valid": True, "codes": ["INERT-I16"]})
    add("default-no-finding", doc(f.format(shape="sprite", attr="")),
        findings={"valid": True, "absent": ["INERT-I16"]})
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0073.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
