#!/usr/bin/env python3
"""Writes srep_cases/assets/srep-test-font.ttf, the pinned test font of the SREP 20 cases (and the font asset of the
SREP 21 case): unitsPerEm 1000, hhea ascender 800 and descender -200, every glyph a rectangle from x 50 to 550 and from
the baseline up to 700 units, advance 600 (SREP 20, Conformance). OS/2 fsType is 0 (embedding allowed): the engine
refuses a font whose fsType forbids embedding. Needs fontTools; the output is committed as a static asset.
"""
import os

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

HERE = os.path.dirname(os.path.abspath(__file__))
CHARS = "H"            # the cases set the text HH; more glyphs would not change the pinned metrics


def rect():
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((50, 700))
    pen.lineTo((550, 700))
    pen.lineTo((550, 0))
    pen.closePath()
    return pen.glyph()


def build(path):
    names = [".notdef"] + list(CHARS)
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({ord(c): c for c in CHARS})
    fb.setupGlyf({n: rect() for n in names})
    fb.setupHorizontalMetrics({n: (600, 50) for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200, lineGap=0)
    fb.setupNameTable({"familyName": "SREPTest", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0, usWinAscent=800, usWinDescent=200, fsType=0)
    fb.setupPost()
    fb.font["head"].created = fb.font["head"].modified = 3534000000   # fixed, so the file is reproducible
    fb.save(path)


if __name__ == "__main__":
    out = os.path.join(HERE, "srep_cases", "assets", "srep-test-font.ttf")
    build(out)
    print("wrote", out)
