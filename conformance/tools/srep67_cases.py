#!/usr/bin/env python3
"""Writes the SREP 67 kit cases (compute with integer accumulation, the density tonemap, iterate, and the serial image
operations error-diffusion and segmented-sort): the shaders in srep_cases/assets/srep67-* and srep_cases/srep-0067.json.
The expected values come from the SREP's formulas, evaluated here (the tonemap of Semantics 3, the integer error
diffusion of Semantics 6, the sort of Semantics 7), not from an engine. Standard library only.
Usage: python3 conformance/tools/srep67_cases.py; then python3 conformance/make_cases.py."""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
ASSETS = os.path.join(CONF, "srep_cases", "assets")
PENDING = "SREP 67 is a draft; no engine implements it yet. The entry keeps the values derived from the SREP"

THREE = """// SREP 67 kit: 1000 points on (100, 100), 100 on (200, 100), 10 on (300, 100).
fn sr_point(i: u32) {
  if (i < 1000u) { sr_accumulate(100, 100, 0u, 1u); }
  else if (i < 1100u) { sr_accumulate(200, 100, 0u, 1u); }
  else { sr_accumulate(300, 100, 0u, 1u); }
}
"""
THREE_INTERLEAVED = """// SREP 67 kit: the same counts as srep67-three.wgsl (1000, 100, 10), issued in another order.
fn sr_point(i: u32) {
  if (i < 30u) {
    let k = i % 3u;
    if (k == 0u) { sr_accumulate(100, 100, 0u, 1u); }
    else if (k == 1u) { sr_accumulate(200, 100, 0u, 1u); }
    else { sr_accumulate(300, 100, 0u, 1u); }
  } else if (i < 210u) {
    if (i % 2u == 0u) { sr_accumulate(100, 100, 0u, 1u); } else { sr_accumulate(200, 100, 0u, 1u); }
  } else { sr_accumulate(100, 100, 0u, 1u); }
}
"""
COLOUR = """// SREP 67 kit: channels="4". 50 points on (100, 100) carry red, 50 on (200, 100) carry blue (amounts in 1/256).
fn sr_point(i: u32) {
  if (i < 50u) {
    sr_accumulate(100, 100, 0u, 256u); sr_accumulate(100, 100, 1u, 256u);
  } else {
    sr_accumulate(200, 100, 0u, 256u); sr_accumulate(200, 100, 3u, 256u);
  }
}
"""
COUNTER = """/*{"ISFVSN":"2","DESCRIPTION":"SREP 67/68 kit: adds 1 to a float buffer per step; red once it reaches target, else blue",
"INPUTS":[{"NAME":"inputImage","TYPE":"image"},{"NAME":"target","TYPE":"float","DEFAULT":10}],
"PASSES":[{"TARGET":"acc","PERSISTENT":true,"FLOAT":true},{}]}*/
void main() {
    if (PASSINDEX == 0) {
        vec4 prev = IMG_NORM_PIXEL(acc, isf_FragNormCoord);
        gl_FragColor = vec4(prev.r + 1.0, 0.0, 0.0, 1.0);
    } else {
        float n = IMG_NORM_PIXEL(acc, isf_FragNormCoord).r;
        vec4 src = IMG_NORM_PIXEL(inputImage, isf_FragNormCoord);
        gl_FragColor = (n >= target - 0.5) ? vec4(1.0, 0.0, 0.0, src.a) : vec4(0.0, 0.0, 1.0, src.a);
    }
}
"""

KERNELS = {  # (dx, dy, weight) and the denominator; SREP 67, Semantics 6
    "floyd-steinberg": ([(1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)], 16),
    "atkinson": ([(1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1)], 8),
}


def tonemap(n, N, gain=1.0, gamma=1.0, scale="log"):
    if N <= 0:
        return 0.0
    v = math.log1p(gain * n) / math.log1p(gain * N) if scale == "log" else n / N
    return min(1.0, max(0.0, v)) ** (1.0 / gamma)


def code(v):
    return round(255 * v, 1)


def diffuse(w, h, value16, kernel, palette16):
    nb, den = KERNELS[kernel]
    W = [[value16] * w for _ in range(h)]
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            v = W[y][x]
            best = min(range(len(palette16)), key=lambda k: ((v - palette16[k]) ** 2, k))
            q = palette16[best]
            out[y][x] = q
            e = v - q
            for dx, dy, num in nb:
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h:
                    W[yy][xx] += (e * num) // den
    return out


def doc(body, version="1.6", extra=""):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<scene version="{version}">\n'
            '<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="1"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'<composition>\n{body}\n</composition>\n{extra}</scene>\n')


def px(x, y, rgb):
    return {"box": [x, y, x + 1, y + 1], "rgb": rgb}


def main():
    os.makedirs(ASSETS, exist_ok=True)
    for name, text in [("three.wgsl", THREE), ("three-interleaved.wgsl", THREE_INTERLEAVED),
                       ("colour.wgsl", COLOUR), ("counter.fs", COUNTER)]:
        open(os.path.join(ASSETS, "srep67-" + name), "w").write(text)
    cases = {}

    def add(slug, xml, expected):
        cases[f"srep-0067-{slug}"] = {"xml": xml, "expected": {"rule": "SREP 67", **expected, "pending": PENDING}}

    def compute(src, inv, tm="", channels="", attrs=""):
        ch = f' channels="{channels}"' if channels else ""
        return (f'<compute id="c" src="../assets/srep67-{src}" width="400" height="200" invocations="{inv}"{ch}{attrs}>'
                f'<tonemap ramp="#000000FF #FFFFFFFF"{tm}/></compute>')

    def grey(n, N, **kw):
        return [code(tonemap(n, N, **kw))] * 3

    pts = [(100, 100), (200, 100), (300, 100)]
    add("compute-log-density", doc(compute("three.wgsl", 1110)),
        {"regions": [px(x, y, grey(n, N=1000)) for (x, y), n in zip(pts, (1000, 100, 10))]})
    add("compute-order", doc(compute("three-interleaved.wgsl", 1110)),
        {"regions": [px(x, y, grey(n, N=1000)) for (x, y), n in zip(pts, (1000, 100, 10))]})
    add("compute-reference", doc(compute("three.wgsl", 1110, ' reference="2000"')),
        {"regions": [px(x, y, grey(n, N=2000)) for (x, y), n in zip(pts, (1000, 100, 10))]})
    add("compute-gain-gamma", doc(compute("three.wgsl", 1110, ' gain="0.01" gamma="2.2"')),
        {"regions": [px(x, y, grey(n, N=1000, gain=0.01, gamma=2.2)) for (x, y), n in zip(pts, (1000, 100, 10))]})
    add("compute-linear", doc(compute("three.wgsl", 1110, ' scale="linear"')),
        {"regions": [px(x, y, grey(n, N=1000, scale="linear")) for (x, y), n in zip(pts, (1000, 100, 10))]})
    add("compute-empty-pixel", doc(compute("three.wgsl", 1110)), {"regions": [px(150, 150, [0.0, 0.0, 0.0])]})
    add("compute-colour", doc(compute("colour.wgsl", 100, "", channels=4, attrs=' fractionBits="8"')),
        {"regions": [px(100, 100, [255.0, 0.0, 0.0]), px(200, 100, [0.0, 0.0, 255.0])]})
    add("compute-version-gate", doc(compute("three.wgsl", 1110), version="1.5"),
        {"findings": {"valid": False, "codes": ["V13"]}})

    # iterate: the counter shader reaches 10 after 10 steps
    def counter(steps, check=""):
        return (f'<iterate id="it" steps="{steps}"{check}>'
                '<shape id="s" shape="rect" width="100" height="100" anchorX="50" anchorY="50" x="320" y="180" fill="#FFFFFFFF" effects="fx"/>'
                '</iterate>')
    fx = ('<effects><effect id="fx" type="shader" src="../assets/srep67-counter.fs">'
          '<param name="target" value="10"/></effect></effects>\n')
    sq = {"cx": 320, "cy": 180, "w": 100, "h": 100}
    add("iterate-steps", doc(counter(10), extra=fx), {"red": sq, "absent": ["blue"]})
    add("iterate-steps-short", doc(counter(9), extra=fx), {"blue": sq, "absent": ["red"]})
    add("iterate-check-every", doc(counter(10, ' checkEvery="20"'), extra=fx),
        {"findings": {"valid": False, "codes": ["ITR1"]}})

    # error diffusion of mid grey (#808080: 128 * 257 = 32896) on a 64 x 64 square, black and white palette
    pal = [0, 65535]
    for kernel in KERNELS:
        out = diffuse(64, 64, 128 * 257, kernel, pal)
        white = sum(v == 65535 for row in out for v in row)
        mean = round(255 * white / 4096, 1)
        first = [255.0 if v == 65535 else 0.0 for v in out[0][:4]]
        add(f"error-diffusion-{kernel}",
            doc('<shape id="g" shape="rect" width="64" height="64" x="100" y="100" fill="#808080FF" effects="ed"/>',
                extra=f'<effects><effect id="ed" type="error-diffusion" kernel="{kernel}" palette="#000000FF #FFFFFFFF"/></effects>\n'),
            {"regions": [{"box": [100, 100, 164, 164], "rgb": [mean] * 3}] +
                        [px(100 + k, 100, [first[k]] * 3) for k in range(4)]})
    # segmented sort: white then black in a 64 x 8 strip sorts to black then white (ascending luma)
    strip = ('<group id="g" effects="ps">'
             '<shape id="w" shape="rect" width="32" height="8" x="100" y="100" fill="#FFFFFFFF"/>'
             '<shape id="b" shape="rect" width="32" height="8" x="132" y="100" fill="#000000FF"/></group>')
    for order, left, right in [("ascending", 0.0, 255.0), ("descending", 255.0, 0.0)]:
        add(f"segmented-sort-{order}",
            doc(strip, extra=f'<effects><effect id="ps" type="segmented-sort" direction="horizontal" order="{order}"/></effects>\n'),
            {"regions": [{"box": [100, 100, 132, 108], "rgb": [left] * 3}, {"box": [132, 100, 164, 108], "rgb": [right] * 3}]})
    # a threshold that excludes white: the white pixels stay, nothing moves
    add("segmented-sort-threshold",
        doc(strip, extra='<effects><effect id="ps" type="segmented-sort" direction="horizontal" low="0" high="0.5"/></effects>\n'),
        {"regions": [{"box": [100, 100, 132, 108], "rgb": [255.0] * 3}, {"box": [132, 100, 164, 108], "rgb": [0.0] * 3}]})
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0067.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")
    for k, v in cases.items():
        e = v["expected"]
        if "regions" in e:
            print(k, [r["rgb"][0] for r in e["regions"]])


if __name__ == "__main__":
    main()
