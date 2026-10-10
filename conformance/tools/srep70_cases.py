#!/usr/bin/env python3
"""Writes the SREP 70 kit cases (parametricPath, parametricSurface, heightfield) to srep_cases/srep-0070.json.
Expected centroids and extents follow from the SREP's sampling rules and from CONVENTIONS 2.2 (the implicit camera maps
the plane z = 0 pixel for pixel) and 2.5 (object3D rotations), not from an engine.
Usage: python3 conformance/tools/srep70_cases.py; then python3 conformance/make_cases.py."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PENDING = "SREP 70 is a draft; no engine implements parametric geometry yet. The entry keeps the values derived from the SREP"
MATERIALS = ('<materials><material id="m-red" baseColor="#FF0000FF" unlit="true"/>'
             '<material id="m-red2" baseColor="#FF0000FF" unlit="true" doubleSided="true"/></materials>\n')


def doc(body, version="1.6", materials=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            '<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="1"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'{materials}<composition>\n{body}\n</composition>\n</scene>\n')


def main():
    cases = {}

    def add(slug, xml, **e):
        cases[f"srep-0070-{slug}"] = {"xml": xml, "expected": {"rule": "SREP 70", **e, "pending": PENDING}}

    # a closed ellipse: 256 samples include t = 0, pi/2, pi, 3pi/2, so the polygon's extremes are exact
    add("path-ellipse", doc('<shape id="e" shape="parametric" fill="#FF0000FF">'
                            '<parametricPath x="320 + 100 * Math.cos(t)" y="180 + 50 * Math.sin(t)" t0="0" t1="6.283185307179586" samples="256" closed="true"/></shape>'),
        red={"cx": 320, "cy": 180, "w": 200, "h": 100})
    # an open Lissajous figure (3:2), symmetric about (320, 180); a 4 px stroke adds 2 px at each extreme
    add("path-lissajous", doc('<shape id="l" shape="parametric" fill="#00000000" stroke="#FF0000FF" strokeWidth="4">'
                              '<parametricPath x="320 + 100 * Math.sin(3 * t)" y="180 + 80 * Math.sin(2 * t)" t0="0" t1="6.283185307179586" samples="2000"/></shape>'),
        red={"cx": 320, "cy": 180, "w": 204, "h": 164})
    # a non-finite point breaks the path: samples 46..54 of 0..100 are NaN, leaving a gap from x = 300 to x = 340
    add("path-break", doc('<shape id="b" shape="parametric" fill="#00000000" stroke="#FF0000FF" strokeWidth="10">'
                          '<parametricPath x="120 + 400 * t" y="(t &gt; 0.455 &amp;&amp; t &lt; 0.545) ? NaN : 180" t0="0" t1="1" samples="101"/></shape>'),
        regions=[{"box": [315, 176, 325, 184], "rgb": [0, 0, 0]}, {"box": [196, 177, 204, 183], "rgb": [255, 0, 0]},
                 {"box": [436, 177, 444, 183], "rgb": [255, 0, 0]}])
    add("path-needs-curve", doc('<shape id="e" shape="parametric" fill="#FF0000FF"/>'),
        findings={"valid": False, "codes": ["PAR1"]})
    add("path-version-gate", doc('<shape id="e" shape="parametric" fill="#FF0000FF"><parametricPath x="t" y="t"/></shape>', version="1.5"),
        findings={"valid": False, "codes": ["V14"]})
    # a parametric plane x = u, y = v at z = 0 faces the camera (normal = dP/dv x dP/du = -z) and maps pixel for pixel
    surf = ('<object3D id="s" primitive="parametric" material="{m}" x="320" y="180">'
            '<parametricSurface x="{x}" y="v" z="0" u0="-50" u1="50" v0="-25" v1="25" uSamples="8" vSamples="8"/></object3D>')
    add("surface-plane", doc(surf.format(m="m-red", x="u"), materials=MATERIALS), red={"cx": 320, "cy": 180, "w": 100, "h": 50})
    add("surface-plane-mirrored-culled", doc(surf.format(m="m-red", x="-u"), materials=MATERIALS), absent=["red"])
    add("surface-plane-mirrored-double-sided", doc(surf.format(m="m-red2", x="-u"), materials=MATERIALS),
        red={"cx": 320, "cy": 180, "w": 100, "h": 50})
    # a flat heightfield turned 90 degrees about x shows its top face as a 100 x 50 rectangle
    add("heightfield-flat", doc('<object3D id="h" primitive="heightfield" material="m-red" x="320" y="180" rotationX="90">'
                                '<heightfield height="0" width="100" depth="50" xSamples="4" zSamples="4"/></object3D>', materials=MATERIALS),
        red={"cx": 320, "cy": 180, "w": 100, "h": 50})
    add("heightfield-underside-culled", doc('<object3D id="h" primitive="heightfield" material="m-red" x="320" y="180" rotationX="-90">'
                                            '<heightfield height="0" width="100" depth="50" xSamples="4" zSamples="4"/></object3D>', materials=MATERIALS),
        absent=["red"])
    add("surface-needs-child", doc('<object3D id="s" primitive="parametric" material="m-red"/>', materials=MATERIALS),
        findings={"valid": False, "codes": ["PAR2"]})
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0070.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
