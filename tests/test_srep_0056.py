"""SREP 56: strokeFont asset, shape="stroke-text" with @text, @strokeFont, @fontSize, and the rules PEN1 and PEN2.
The V5 version gate is applied centrally and is not tested here."""
import os

import pytest

from test_schema_rules import ROOT, doc as _doc, etree, verdict


def doc(*args, **kw):
    """A scene document that declares version 1.2, the version these features need (V5)."""
    kw.setdefault("version", "1.2")
    return _doc(*args, **kw)


CASES = os.path.join(ROOT, "conformance", "cases")
FONT = os.path.join(ROOT, "conformance", "assets", "stroke-hi.jhf")
XS = {"xs": "http://www.w3.org/2001/XMLSchema"}


def case(name):
    """A case of this SREP. It declares version="1.2"; the version enumeration and the V5 gate are applied centrally
    (release coordinator), so until then the document is checked as 1.1, which differs only in that attribute."""
    xml = open(os.path.join(CASES, name + ".xml"), "rb").read()
    assert b'<scene version="1.2">' in xml
    return xml


FONTS = '<strokeFont id="hand" src="hand.jhf"/>'


def text_shape(attrs=' text="HI" strokeFont="hand"', assets=FONTS, shape="stroke-text"):
    return doc(f'<shape id="t" shape="{shape}" width="100" height="50"{attrs} stroke="#FFFFFF" strokeWidth="2"/>', assets=assets)


# ---------------------------------------------------------------- the cases
@pytest.mark.parametrize("name", ["srep-0056-stroke-text-layout", "srep-0056-stroke-text-trim"])
def test_the_cases_validate(name):
    assert verdict(case(name)) == "ok"


# ---------------------------------------------------------------- the rules
def test_pen1_text_is_required():
    assert verdict(text_shape(' strokeFont="hand"')) == "sch:PEN1"


def test_pen1_stroke_font_is_required():
    assert verdict(text_shape(' text="HI"')) == "sch:PEN1"


def test_pen1_needs_both_and_names_only_pen1_when_neither_is_given():
    assert verdict(text_shape("")) == "sch:PEN1"


def test_pen2_the_font_must_be_a_stroke_font_asset():
    other = '<image id="hand" src="x.png" width="4" height="4"/>'
    assert verdict(text_shape(assets=other)) == "sch:PEN2"


def test_pen2_a_font_that_names_nothing_is_rejected():
    assert verdict(text_shape(' text="HI" strokeFont="nothing"', assets=FONTS)) == "sch:PEN2"


def test_a_complete_stroke_text_shape_is_accepted():
    assert verdict(text_shape()) == "ok"
    assert verdict(text_shape(' text="HI" strokeFont="hand" fontSize="42"')) == "ok"
    assert verdict(text_shape(' text="line&#10;two" strokeFont="hand"')) == "ok"


def test_the_rules_apply_to_stroke_text_only():
    # SREP 56: on other shapes the three attributes have no effect (an engine reports them as information); no rule fires
    assert verdict(text_shape(' text="HI"', assets="", shape="rect")) == "ok"
    assert verdict(text_shape(' strokeFont="nothing" fontSize="12"', assets="", shape="ellipse")) == "ok"


# ---------------------------------------------------------------- the declarations
def test_stroke_font_asset_attributes():
    assert verdict(doc(assets='<strokeFont id="a" src="a.jhf"/>')) == "ok"
    assert verdict(doc(assets='<strokeFont id="a" src="a.jhf" format="jhf"/>')) == "ok"
    assert verdict(doc(assets='<strokeFont id="a" src="a.jhf" format="ttf"/>')) == "xsd"
    assert verdict(doc(assets='<strokeFont id="a"/>')) == "xsd"
    assert verdict(doc(assets='<strokeFont src="a.jhf"/>')) == "xsd"


@pytest.mark.parametrize("value", ["0", "-5", "big"])
def test_font_size_is_a_positive_decimal(value):
    assert verdict(text_shape(f' text="HI" strokeFont="hand" fontSize="{value}"')) == "xsd"


def test_font_size_defaults_to_48_and_format_to_jhf():
    schema = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))
    size = schema.xpath("//xs:complexType[@name='shapeType']/xs:attribute[@name='fontSize']", namespaces=XS)[0]
    assert size.get("type") == "positiveDecimal" and size.get("default") == "48"
    fmt = schema.xpath("//xs:complexType[@name='strokeFontAssetType']/xs:attribute[@name='format']", namespaces=XS)[0]
    assert fmt.get("default") == "jhf"
    shape = schema.xpath("//xs:complexType[@name='shapeType']/xs:attribute[@name='shape']", namespaces=XS)[0]
    assert "stroke-text" in [e.get("value") for e in shape.xpath(".//xs:enumeration", namespaces=XS)]


# ---------------------------------------------------------------- the expected values of the layout cases, recomputed
# An independent reading of SREP 56 Semantics 1 to 5, used to check the numbers given for conformance/expected.json.
def parse_jhf(text):
    s = text.replace("\n", "").replace("\r", "")
    i, glyphs = 0, []
    while i < len(s):
        n = int(s[i + 5:i + 8])
        data = s[i + 8:i + 8 + 2 * n]
        i += 8 + 2 * n
        v = lambda c: ord(c) - ord("R")
        left, right = v(data[0]), v(data[1])
        strokes, run = [], []
        for k in range(2, len(data), 2):
            if data[k:k + 2] == " R":
                if len(run) >= 2:
                    strokes.append(run)
                run = []
            else:
                run.append((v(data[k]), v(data[k + 1])))
        if len(run) >= 2:
            strokes.append(run)
        glyphs.append((left, right, strokes))
    return glyphs


def layout(glyphs, text, size):
    s = size / 21
    pen, base, out = 0.0, size, []
    for ch in text:
        if ch == "\n":
            pen, base = 0.0, base + size * 32 / 21
            continue
        left, right, strokes = glyphs[ord(ch) - 0x20]
        for st in strokes:
            out.append([(pen + (x - left) * s, base + (y - 9) * s) for x, y in st])
        pen += (right - left) * s
    return out


def raster(strokes, origin, width, trim_end=1.0):
    """Pixels covered by axis-aligned strokes of the given width with butt caps, trimmed sequentially over the whole text."""
    total = sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for st in strokes for a, b in zip(st, st[1:]))
    left, rects = total * trim_end, []
    for st in strokes:
        for (x0, y0), (x1, y1) in zip(st, st[1:]):
            length = abs(x1 - x0) + abs(y1 - y0)
            use = min(length, max(left, 0.0))
            left -= length
            if use <= 0:
                continue
            x1, y1 = x0 + (x1 - x0) * use / length, y0 + (y1 - y0) * use / length
            h = width / 2
            rects.append((min(x0, x1) - (h if y0 != y1 else 0), min(y0, y1) - (h if x0 != x1 else 0),
                          max(x0, x1) + (h if y0 != y1 else 0), max(y0, y1) + (h if x0 != x1 else 0)))
    ox, oy = origin
    px = [(x, y) for x in range(ox - 10, ox + 120) for y in range(oy - 10, oy + 70)
          if any(r[0] + ox <= x + 0.5 <= r[2] + ox and r[1] + oy <= y + 0.5 <= r[3] + oy for r in rects)]
    xs, ys = [p[0] for p in px], [p[1] for p in px]
    return {"cx": round(sum(xs) / len(xs) + 0.5, 2), "cy": round(sum(ys) / len(ys) + 0.5, 2),
            "w": max(xs) - min(xs) + 1, "h": max(ys) - min(ys) + 1}


def test_the_font_asset_is_a_well_formed_jhf_with_h_and_i_at_their_code_points():
    glyphs = parse_jhf(open(FONT).read())
    assert len(glyphs) == 42
    assert all(not g[2] for g in glyphs[:40])
    assert glyphs[ord("H") - 0x20][2] == [[(-3, -12), (-3, 9)], [(3, -12), (3, 9)], [(-3, -1), (3, -1)]]
    assert glyphs[ord("I") - 0x20][2] == [[(0, -12), (0, 9)]]


def test_the_layout_case_expected_values():
    strokes = layout(parse_jhf(open(FONT).read()), "HI", 42)
    # scale 2; H: margins -5 and 5, stems at (-3 + 5) * 2 = 4 and (3 + 5) * 2 = 16, crossbar at y = 42 + (-1 - 9) * 2 = 22,
    # advance 20; I: margins -2 and 2, stem at 20 + (0 + 2) * 2 = 24; tops at y 0, feet at y 42 (SREP 56 Semantics 3 and 4)
    assert strokes[0] == [(4, 0), (4, 42)] and strokes[1] == [(16, 0), (16, 42)] and strokes[2] == [(4, 22), (16, 22)]
    assert strokes[3] == [(24, 0), (24, 42)]
    # by hand: stems 3 x 84 px^2 at x = 104, 116, 124 (+ 100), crossbar between the stems 10 x 2 = 20 px^2 at x = 110, y = 122;
    # cx = (84 * (104 + 116 + 124) + 20 * 110) / 272 = 114.32, cy = (252 * 121 + 20 * 122) / 272 = 121.07;
    # ink spans x 103 to 125 (22 px) and y 100 to 142 (42 px)
    assert raster(strokes, (100, 100), 2) == {"cx": 114.32, "cy": 121.07, "w": 22, "h": 42}


def test_the_trim_case_expected_values():
    strokes = layout(parse_jhf(open(FONT).read()), "HI", 42)
    # total length 42 + 42 + 12 + 42 = 138; trimEnd 0.5 walks 69: the whole left stem (42) and the first 27 of the right stem
    # (drawn from its top, so y 100 to 127). By hand: areas 84 (x = 104, y 100 to 142) and 54 (x = 116, y 100 to 127):
    # cx = (84 * 104 + 54 * 116) / 138 = 108.70, cy = (84 * 121 + 54 * 113.5) / 138 = 118.07; ink x 103 to 117 (14 px), 42 px high
    assert raster(strokes, (100, 100), 2, 0.5) == {"cx": 108.7, "cy": 118.07, "w": 14, "h": 42}
