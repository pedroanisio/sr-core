#!/usr/bin/env python3
"""Writes the SREP 72 kit cases (working precision, sr_PixelCoord and sr_ContentRect, edgeBlend, supersample) to
srep_cases/srep-0072.json and two shaders to srep_cases/assets/srep72-*.fs. Expected values follow from SREP 72's
formulas: edge coverage mixed in linear or encoded values, and the box and Lanczos-3 downsampling kernels evaluated
here. Assumption (stated in the SREP): edge coverage is the exact area fraction of the pixel.
Usage: python3 conformance/tools/srep72_cases.py; then python3 conformance/make_cases.py."""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PENDING = "SREP 72 is a draft; no engine implements it yet. The entry keeps the values derived from the SREP"

F32 = """/*{"ISFVSN":"2","DESCRIPTION":"SREP 72 kit: stores 2049 in a FLOAT pass target and reads it back; red when exact",
"INPUTS":[{"NAME":"inputImage","TYPE":"image"}],"PASSES":[{"TARGET":"buf","FLOAT":true},{}]}*/
void main() {
    if (PASSINDEX == 0) {
        gl_FragColor = vec4(2049.0, 0.0, 0.0, 1.0);
    } else {
        float v = IMG_NORM_PIXEL(buf, isf_FragNormCoord).r;
        vec4 src = IMG_NORM_PIXEL(inputImage, isf_FragNormCoord);
        gl_FragColor = (v == 2049.0) ? vec4(1.0, 0.0, 0.0, src.a) : vec4(0.0, 0.0, 1.0, src.a);
    }
}
"""
STRIPE = """/*{"ISFVSN":"2","DESCRIPTION":"SREP 72 kit: red in the first 10 px of the content box (sr_PixelCoord), the input elsewhere",
"INPUTS":[{"NAME":"inputImage","TYPE":"image"}]}*/
void main() {
    vec4 src = IMG_NORM_PIXEL(inputImage, isf_FragNormCoord);
    gl_FragColor = (sr_PixelCoord.x >= 0.0 && sr_PixelCoord.x < 10.0) ? vec4(1.0, 0.0, 0.0, src.a) : vec4(0.0, 0.0, src.a, src.a);
}
"""


def enc(v):
    v = min(1.0, max(0.0, v))
    return 255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)


def lanczos3(x):
    if x == 0:
        return 1.0
    if abs(x) >= 3:
        return 0.0
    px = math.pi * x
    return 3 * math.sin(px) * math.sin(px / 3) / (px * px)


def down(n, edge, i, kernel):
    """Output pixel i of a step from 0 (x < edge) to 1 (x >= edge), rendered at n samples per pixel (sample k of the
    row has its centre at (k + 0.5) / n output pixels), filtered by `kernel` (SREP 72, Semantics 4)."""
    c = i + 0.5
    num = den = 0.0
    for k in range(int((c - 4) * n), int((c + 4) * n) + 1):
        s = (k + 0.5) / n
        w = 1.0 if kernel == "box" and math.floor(s) == i else (lanczos3(s - c) if kernel == "lanczos3" else 0.0)
        num += w * (1.0 if s >= edge else 0.0)
        den += w
    return min(1.0, max(0.0, num / den))


def doc(body, project="", extra="", version="1.6"):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            f'<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="1"{project}/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'<composition>\n{body}\n</composition>\n{extra}</scene>\n')


def main():
    for name, text in [("f32.fs", F32), ("stripe.fs", STRIPE)]:
        open(os.path.join(CONF, "srep_cases", "assets", "srep72-" + name), "w").write(text)
    cases = {}

    def add(slug, xml, **e):
        cases[f"srep-0072-{slug}"] = {"xml": xml, "expected": {"rule": "SREP 72", **e, "pending": PENDING}}

    sq = '<shape id="s" shape="rect" width="100" height="100" anchorX="50" anchorY="50" x="320" y="180" fill="#FFFFFFFF" effects="fx"/>'
    fx = '<effects><effect id="fx" type="shader" src="../assets/srep72-{}.fs"/></effects>\n'
    add("precision-f32", doc(sq, ' precision="f32"', fx.format("f32")), red={"cx": 320, "cy": 180, "w": 100, "h": 100}, absent=["blue"])
    add("content-rect-stripe", doc(sq, "", fx.format("stripe")), red={"cx": 275, "cy": 180, "w": 10, "h": 100})
    add("content-rect-stripe-fractional", doc(sq.replace('x="320"', 'x="320.4"'), "", fx.format("stripe")),
        red={"cx": 275.4, "cy": 180, "w": 10, "h": 100})
    # a white rect whose left edge is at x = 100.5 covers half of column 100
    edge = '<shape id="e" shape="rect" width="100" height="50" x="100.5" y="100" fill="#FFFFFFFF"{}/>'
    half_lin, half_enc = round(enc(0.5), 1), 127.5
    add("edge-blend-linear", doc(edge.format(' edgeBlend="linear"'), ' linearLight="false"'),
        regions=[{"box": [100, 110, 101, 140], "rgb": [half_lin] * 3}])
    add("edge-blend-encoded", doc(edge.format(' edgeBlend="encoded"')),
        regions=[{"box": [100, 110, 101, 140], "rgb": [half_enc] * 3}])
    add("edge-blend-inherit", doc(edge.format("")),
        regions=[{"box": [100, 110, 101, 140], "rgb": [half_lin] * 3}])
    # supersampling a pixel-aligned step edge at x = 100: box leaves it sharp; Lanczos-3 rings (values clamped to [0, 1])
    step = '<shape id="e" shape="rect" width="200" height="50" x="100" y="100" fill="#FFFFFFFF"/>'
    for kernel in ("box", "lanczos3"):
        cols = range(96, 104)
        add(f"supersample-{kernel}", doc(step, f' supersample="2" supersampleFilter="{kernel}"'),
            regions=[{"box": [i, 110, i + 1, 140], "rgb": [round(enc(down(2, 100, i, kernel)), 1)] * 3} for i in cols])
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0072.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")
    for k in ("srep-0072-supersample-lanczos3", "srep-0072-edge-blend-linear"):
        print(k, [r["rgb"][0] for r in cases[k]["expected"]["regions"]])


if __name__ == "__main__":
    main()
