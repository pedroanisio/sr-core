#!/usr/bin/env python3
"""Writes the SREP 89 kit case srep-0089-supersample-hdr (the supersample clamp keeps values above 1) to
srep_cases/srep-0089.json: three documents, at n = 1, at n = 2 with box and at n = 3 with lanczos3, one per case,
since supersample belongs to project.

Each fills the frame with white under an exposure effect of 2 stops, a flat working value of 4.0 (DEFINITIONS, Colour
grade), and finishes with colorManagement toneMapping="none" exposure="-3". The kit reads 8-bit PNG, where 4.0 and 1.0
both encode to 255; the finishing exposure, after the filter, brings 4.0 to 0.5 (187.5) and SREP 72's clamped 1.0 to
0.125 (99.1). The expected values come from the filter of SREP 72 Semantics 4 with SREP 89's clamp, evaluated here.
Assumption (stated in SREP 89, Conformance): colorManagement/@exposure scales by 2^exposure, as the effect does.
Usage: python3 conformance/tools/srep89_cases.py; then python3 conformance/make_cases.py."""
import json
import math
import os
import kit_pending  # which cases are pending (SREP 0)
from srep72_cases import enc, lanczos3

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)

WHITE = 1.0            # #FFFFFF in the linear working space
EFFECT_STOPS = 2       # the exposure effect: 1.0 x 2^2 = 4.0
FINISH_STOPS = -3      # colorManagement/@exposure, colour finishing after the filter
W, H = 640, 360
# the centre of the frame and two corners, where the weights renormalise at the frame's edges
BOXES = [[300, 160, 340, 200], [0, 0, 8, 8], [W - 8, H - 8, W, H]]
RUNS = [("n1", 1, "box"), ("box-n2", 2, "box"), ("lanczos3-n3", 3, "lanczos3")]


def weight(kernel, i, s, c):
    if kernel == "box":
        return 1.0 if math.floor(s) == i else 0.0
    return lanczos3(s - c)


def down(n, sample, i, kernel, size, srep89=True):
    """Output pixel i of one axis of `size` output pixels, from n samples per pixel whose values are sample(k), with
    the kernel of SREP 72 Semantics 4 and its clamp: [0, 1] (SREP 72) or [0, max(1, M)], M the largest sample of
    non-zero weight (SREP 89). Samples exist for k in 0 .. n * size - 1 only (the weights renormalise)."""
    if n == 1:
        return sample(i)
    c = i + 0.5
    num = den = 0.0
    top = 1.0
    for k in range(max(0, int((c - 4) * n)), min(n * size, int((c + 4) * n) + 1)):
        s = (k + 0.5) / n
        w = weight(kernel, i, s, c)
        if w != 0.0:
            num += w * sample(k)
            den += w
            top = max(top, sample(k))
    return min(top if srep89 else 1.0, max(0.0, num / den))


def expected_value(n, kernel, i, j, srep89=True):
    """The code value at output pixel (i, j): the flat 4.0 filtered along x then y, finished, encoded."""
    flat = WHITE * 2 ** EFFECT_STOPS
    row = down(n, lambda k: flat, i, kernel, W, srep89)
    v = down(n, lambda k: row, j, kernel, H, srep89)
    return enc(v * 2 ** FINISH_STOPS)


def region(n, kernel, box, srep89=True):
    x0, y0, x1, y1 = box
    vals = [expected_value(n, kernel, i, j, srep89) for i in range(x0, x1) for j in range(y0, y1)]
    return round(sum(vals) / len(vals), 1)


def document(n, kernel):
    project = "" if n == 1 else f' supersample="{n}" supersampleFilter="{kernel}"'
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<scene version="1.6">\n'
            f'<project width="{W}" height="{H}" fps="24" duration="1" background="#000000FF" seed="1"{project}/>\n'
            f'<colorManagement toneMapping="none" exposure="{FINISH_STOPS}"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'<composition>\n<shape id="s" shape="rect" width="{W}" height="{H}" x="0" y="0" fill="#FFFFFFFF" '
            'effects="e"/>\n</composition>\n'
            f'<effects><effect id="e" type="exposure" exposure="{EFFECT_STOPS}"/></effects>\n</scene>\n')


def main():
    cases = {}
    for slug, n, kernel in RUNS:
        cases[f"srep-0089-supersample-hdr-{slug}"] = {
            "xml": document(n, kernel),
            "expected": {"rule": "SREP 89",
                         "regions": [{"box": b, "rgb": [region(n, kernel, b)] * 3} for b in BOXES]}}
    kit_pending.settle(cases, 89)
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0089.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")
    for slug, n, kernel in RUNS:
        print(slug, "SREP 89:", [region(n, kernel, b) for b in BOXES],
              "SREP 72 as written:", [region(n, kernel, b, srep89=False) for b in BOXES])


if __name__ == "__main__":
    main()
