#!/usr/bin/env python3
"""Writes the SREP 74 kit cases (viewport3D) to srep_cases/srep-0074.json. Expected positions follow from SREP 74:
a viewport's 3D space is the pixel space of its own width x height frame, seen by its own camera (CONVENTIONS 2.2 and
2.3 applied to that frame), drawn at the node's origin and clipped to the frame. Not from an engine.
Usage: python3 conformance/tools/srep74_cases.py; then python3 conformance/make_cases.py."""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PENDING = "SREP 74 is a draft; no engine implements viewport3D yet. The entry keeps the values derived from the SREP"
MAT = ('<materials><material id="m-red" baseColor="#FF0000FF" unlit="true" doubleSided="true"/>'
       '<material id="m-green" baseColor="#00FF00FF" unlit="true" doubleSided="true"/></materials>\n')
VW, VH = 200, 100
DV = (VW / 2) / math.tan(math.radians(30))   # the viewport's implicit camera distance


def doc(body, version="1.6"):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            '<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="1"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'{MAT}<composition>\n{body}\n</composition>\n</scene>\n')


def vp(inner, attrs=""):
    return f'<viewport3D id="v" width="{VW}" height="{VH}" x="100" y="100"{attrs}>{inner}</viewport3D>'


def plane(x, y, w=40, h=20, m="m-red", id_="p"):
    return f'<object3D id="{id_}" primitive="plane" width="{w}" height="{h}" x="{x}" y="{y}" material="{m}"/>'


def main():
    cases = {}

    def add(slug, xml, **e):
        cases[f"srep-0074-{slug}"] = {"xml": xml, "expected": {"rule": "SREP 74", **e, "pending": PENDING}}

    add("implicit-camera", doc(vp(plane(100, 50))), red={"cx": 200, "cy": 150, "w": 40, "h": 20})
    # a main-scene camera far to the right moves the main scene's 3D, not the viewport's
    add("main-camera-does-not-reach", doc('<camera id="c" x="1320" y="180" z="-554.256"/>\n' + vp(plane(100, 50))),
        red={"cx": 200, "cy": 150, "w": 40, "h": 20})
    # the viewport's own camera, 30 px right of its implicit position, shows the plane 30 px left
    add("own-camera", doc(vp(f'<camera id="vc" x="{VW / 2 + 30}" y="{VH / 2}" z="{-DV:.3f}"/>' + plane(100, 50), ' camera="vc"')),
        red={"cx": 170, "cy": 150, "w": 40, "h": 20})
    # a camera inside a viewport is not a candidate for the main scene's active camera
    add("viewport-camera-stays-inside", doc(plane(500, 300) + "\n" +
                                           vp(f'<camera id="vc" x="900" y="900" z="-50"/>' + plane(100, 50, m="m-green", id_="q"))),
        red={"cx": 500, "cy": 300, "w": 40, "h": 20})
    # content beyond the viewport's frame is clipped: a 100 px plane centred on the left edge shows its right half
    add("clipped", doc(vp(plane(0, 50, w=100))), red={"cx": 125, "cy": 150, "w": 50, "h": 20})
    add("version-gate", doc(vp(plane(100, 50)), version="1.5"), findings={"valid": False, "codes": ["V15"]})
    add("camera-must-be-inside", doc('<camera id="c" x="0" y="0" z="-100"/>\n' + vp(plane(100, 50), ' camera="c"')),
        findings={"valid": False, "codes": ["VP1"]})
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0074.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
