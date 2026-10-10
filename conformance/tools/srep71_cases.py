#!/usr/bin/env python3
"""Writes the SREP 71 kit cases (procedural sky, generator-fed material maps, subsurface) to srep_cases/srep-0071.json.
Sky values: the radiance of SREP 71, Semantics 2, along the implicit camera's pixel rays (CONVENTIONS 2.2: horizontal
fov 60 degrees, so the focal length is 320 / tan(30 degrees) px for a 640 px frame), with colour literals decoded and
encoded by the sRGB transfer function (CONVENTIONS 1.4). Not from an engine.
Usage: python3 conformance/tools/srep71_cases.py; then python3 conformance/make_cases.py."""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PENDING = "SREP 71 is a draft; no engine implements it yet. The entry keeps the values derived from the SREP"
W, H = 640, 360
F = (W / 2) / math.tan(math.radians(30))


def dec(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def enc(v):
    v = min(1.0, max(0.0, v))
    return 255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)


def lin(hexrgb):
    return [dec(int(hexrgb[i:i + 2], 16)) for i in (1, 3, 5)]


ZEN, HOR, GRD = "#2050A0", "#C0D0E0", "#403020"


def sky(px, py, k=1.0):
    d = (px - W / 2, py - H / 2, F)
    s = -d[1] / math.sqrt(sum(c * c for c in d))      # sin(elevation); up is -y
    z, h, g = lin(ZEN), lin(HOR), lin(GRD)
    if s >= 0:
        L = [hc + (zc - hc) * s ** k for zc, hc in zip(z, h)]
    else:
        L = [hc + (gc - hc) * (-s) ** k for gc, hc in zip(g, h)]
    return [round(enc(v), 1) for v in L]


def doc(body="", lights="", materials="", assets="", version="1.6"):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            '<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="1"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'{assets}{materials}<composition>\n{body}\n</composition>\n{lights}</scene>\n')


def main():
    cases = {}

    def add(slug, xml, **e):
        rule = "SREP 71" + (f" ({e.pop('note')})" if "note" in e else "")
        cases[f"srep-0071-{slug}"] = {"xml": xml, "expected": {"rule": rule, **e, "pending": e.pop("pending", PENDING)}}

    dome = (f'<lights><light id="sky" type="dome" sky="gradient" skyZenith="{ZEN}" skyHorizon="{HOR}" skyGround="{GRD}" '
            'skyExponent="1" environmentVisible="true"{extra}/></lights>\n')
    rows = [(320, 0), (320, 90), (320, 270), (320, 359), (0, 0)]
    add("sky-gradient", doc(lights=dome.format(extra="")),
        regions=[{"box": [x, y, x + 1, y + 1], "rgb": sky(x + 0.5, y + 0.5)} for x, y in rows])
    add("sky-horizon", doc(lights=dome.format(extra="")),
        regions=[{"box": [300, 179, 340, 181], "rgb": [round(enc(v), 1) for v in lin(HOR)]}])
    # a red sun of 5 degrees straight ahead on a black sky: a disc of radius F * tan(2.5 deg) px at the centre
    r = F * math.tan(math.radians(2.5))
    add("sky-sun", doc(lights='<lights><light id="sky" type="dome" sky="gradient" skyZenith="#000000" skyHorizon="#000000" '
                               'skyGround="#000000" sunAzimuth="0" sunElevation="0" sunSize="5" sunColor="#FF0000" sunIntensity="1" '
                               'environmentVisible="true"/></lights>\n'),
        red={"cx": 320, "cy": 180, "w": round(2 * r, 1), "h": round(2 * r, 1)})
    add("sky-sun-azimuth", doc(lights='<lights><light id="sky" type="dome" sky="gradient" skyZenith="#000000" skyHorizon="#000000" '
                                       'skyGround="#000000" sunAzimuth="10" sunElevation="5" sunSize="5" sunColor="#FF0000" sunIntensity="1" '
                                       'environmentVisible="true"/></lights>\n'),
        red={"cx": round(320 + F * math.tan(math.radians(10)), 1),
             "cy": round(180 - F * math.tan(math.radians(5)) / math.cos(math.radians(10)), 1)},
        note="sun centre direction (sin10 cos5, -sin5, cos10 cos5) projected; the disc's own centroid is offset by under 1 px")
    add("sky-not-dome", doc(lights='<lights><light id="k" type="directional" sky="gradient"/></lights>\n'),
        findings={"valid": False, "codes": ["SKY1"]})
    add("sky-and-environment", doc(lights='<lights><light id="sky" type="dome" sky="gradient" environment="x.hdr"/></lights>\n'),
        findings={"valid": False, "codes": ["SKY2"]})
    # a solid generator feeds the base colour map of an unlit plane: the plane shows the generator's colour
    gen = '<assets><generator id="g" kind="solid" width="16" height="16" paint="#00FF00FF"/><image id="im" src="../assets/tile.png" width="8" height="8"/></assets>\n'
    mat = '<materials><material id="m" baseColor="#FFFFFFFF" unlit="true" baseColorMap="{ref}"/></materials>\n'
    plane = '<object3D id="o" primitive="plane" width="100" height="100" x="320" y="180" material="m"/>'
    add("map-generator", doc(plane, assets=gen, materials=mat.format(ref="#g")), green={"cx": 320, "cy": 180, "w": 100, "h": 100})
    add("map-not-an-image-source", doc(plane, assets=gen, materials=mat.format(ref="#m")),
        findings={"valid": False, "codes": ["MTX1-baseColorMap"]})
    # subsurface: weight 0 is the neutral case; no pixel values are stated for the scattering itself
    sss = ('<materials><material id="m" baseColor="#B0B0B0FF" roughness="0.5" subsurface="{w}" subsurfaceColor="#E0F0D0FF" '
           'subsurfaceRadius="20"/></materials>\n')
    lit = '<lights><light id="sun" type="directional" yaw="60" intensity="3"/></lights>\n'
    ball = '<object3D id="o" primitive="sphere" radius="80" x="320" y="180" material="m"/>'
    add("subsurface-zero-neutral", doc(ball, lights=lit, materials=sss.format(w=0)),
        note="renders the same as the scene without the subsurface attributes",
        pending=PENDING + "; the check is equality with another render, which run.py cannot express yet")
    add("subsurface-wraps-terminator", doc(ball, lights=lit, materials=sss.format(w=1)),
        note="the region just past the shadow terminator is brighter than with subsurface=0 (Semantics 1, item 3)",
        pending=PENDING + "; the check is a comparison with another render, which run.py cannot express yet")
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0071.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")
    for k in ("srep-0071-sky-gradient", "srep-0071-sky-horizon", "srep-0071-sky-sun", "srep-0071-sky-sun-azimuth"):
        print(k, json.dumps(cases[k]["expected"].get("regions") or cases[k]["expected"].get("red")))


if __name__ == "__main__":
    main()
