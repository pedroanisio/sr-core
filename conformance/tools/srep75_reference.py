#!/usr/bin/env python3
"""Reference escape counts for the SREP 75 kit cases, in exact decimal arithmetic (Python's decimal module), and the
cases in srep_cases/srep-0075.json. For each chosen pixel the count is computed at the pixel centre with 60 and 90
significant digits and at the four points offset by 2^-20 of a pixel (SREP 75, Semantics 3); a pixel enters the kit
only when all ten counts agree, so any conforming engine must give that count. Standard library only.
Usage: python3 conformance/tools/srep75_reference.py; then python3 conformance/make_cases.py."""
import json
import os
from decimal import Decimal, localcontext

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PENDING = "SREP 75 is a draft; no engine implements the fractal asset yet. The entry keeps the values derived from the SREP"
W, H = 640, 360
CX = "-0.743643887037158704752191506114774"
CY = "0.131825904205311970493132056385139"
JX = "-0.7453000000000000000000000000000000000001"     # 40 digits after the point
JY = "0.1127000000000000000000000000000000000001"
# The centres have 33 digits. They are valid xs:decimal values, but XSD 1.0 lets a validator limit the digits it
# supports (Part 2, 3.2.3: at least 18), and libxml2 before 2.13.0 refuses more than 24 (SREP 75, Semantics 1).
LONG = ("the centre has 33 digits: valid, but a validator that limits xs:decimal to fewer digits, such as libxml2 "
        "before 2.13.0 (24 digits), refuses the document; such a validator is not the oracle for this case")


def count(cx, cy, max_iter, digits, bailout=2):
    with localcontext() as ctx:
        ctx.prec = digits
        x = y = Decimal(0)
        r2 = Decimal(bailout) ** 2
        for n in range(1, max_iter + 1):
            x, y = x * x - y * y + cx, 2 * x * y + cy
            if x * x + y * y > r2:
                return n
        return None


def pixel_c(i, j, zoom, span=4, dx=Decimal(0), dy=Decimal(0)):
    with localcontext() as ctx:
        ctx.prec = 120
        p = Decimal(span) * Decimal(10) ** (-zoom) / W
        return (Decimal(CX) + (Decimal(i) + Decimal("0.5") - Decimal(W) / 2 + dx) * p,
                Decimal(CY) - (Decimal(j) + Decimal("0.5") - Decimal(H) / 2 + dy) * p)


def robust(i, j, zoom, max_iter):
    e = Decimal(2) ** -20
    counts = set()
    for digits in (60, 90):
        counts.add(count(*pixel_c(i, j, zoom), max_iter, digits))
        for dx, dy in ((e, 0), (-e, 0), (0, e), (0, -e)):
            counts.add(count(*pixel_c(i, j, zoom, dx=Decimal(dx), dy=Decimal(dy)), max_iter, digits))
    return counts.pop() if len(counts) == 1 else "unstable"


def doc(zoom, max_iter, extra="", version="1.6"):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            '<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="1"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'<assets><fractal id="f" kind="mandelbrot" width="640" height="360" centerX="{CX}" centerY="{CY}" zoom="{zoom}" '
            f'maxIterations="{max_iter}" colorMode="bands" palette="#FF0000FF #0000FFFF" insideColor="#000000FF"{extra}/></assets>\n'
            '<composition>\n<layer id="l" asset="f"/>\n</composition>\n</scene>\n')


def main():
    cases = {}
    samples = [(40, 30), (600, 30), (320, 180), (40, 330), (600, 330), (160, 90), (480, 270), (100, 200), (520, 120)]
    for zoom, max_iter in ((6, 3000), (12, 12000), (20, 20000)):
        regions, notes = [], []
        for i, j in samples:
            n = robust(i, j, zoom, max_iter)
            notes.append(f"({i},{j}):{n}")
            if n == "unstable":
                continue
            rgb = [0, 0, 0] if n is None else ([255, 0, 0] if n % 2 == 0 else [0, 0, 255])
            regions.append({"box": [i, j, i + 1, j + 1], "rgb": rgb})
        print(f"zoom {zoom}:", " ".join(notes))
        cases[f"srep-0075-mandelbrot-zoom-{zoom}"] = {
            "xml": doc(zoom, max_iter),
            "expected": {"rule": f"SREP 75 (escape counts at zoom {zoom}: " + ", ".join(notes) + "; " + LONG + ")",
                         "regions": regions, "pending": PENDING}}
    cases["srep-0075-version-gate"] = {"xml": doc(6, 100, version="1.5"),
                                       "expected": {"rule": "SREP 75", "findings": {"valid": False, "codes": ["V16"]}, "pending": PENDING}}
    cases["srep-0075-long-decimals-valid"] = {
        "xml": doc(6, 100, extra=f' juliaX="{JX}" juliaY="{JY}"').replace('kind="mandelbrot"', 'kind="julia"'),
        "expected": {"rule": "SREP 75 Semantics 1 (an engine reads the four decimal attributes at any length: 33-digit "
                             "centre, 40-digit juliaX and juliaY; valid, no finding)",
                     "findings": {"valid": True}, "pending": PENDING}}
    cases["srep-0075-julia-needs-c"] = {"xml": doc(6, 100).replace('kind="mandelbrot"', 'kind="julia"'),
                                        "expected": {"rule": "SREP 75", "findings": {"valid": False, "codes": ["FRC1"]}, "pending": PENDING}}
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0075.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
