"""SREP 17: pdf page assets and text-anchored regions (pdfAssetType, pdfRegionType, shape/@region; rules V9, C66-C69,
R51, R52).

Ids differ from the SREP's draft numbering by the coordinator's table: R45 -> R51, R46 -> R52 (patterns p72, p73).
"""
import hashlib

import pytest

from srep_support import case_verdict, verdict12
from test_schema_rules import doc

CASES = ["srep-0017-pdf-" + n for n in ("page", "bad-cache", "region", "region-fit", "region-rotate")]
H = hashlib.sha256(b"x").hexdigest()


def pdf(extra="", regions='<region id="rg" x="20" y="10" width="60" height="20"/>', pid="p", drop=()):
    attrs = {"id": pid, "src": "a.pdf", "sha256": H, "cache": "a.png", "cacheSha256": H, "width": "200", "height": "100"}
    for d in drop:
        attrs.pop(d)
    return "<pdf " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + f"{extra}>{regions}</pdf>"


LAYER = '<layer id="l" asset="p" x="0" y="0"/>'
HL = '<shape id="hl" shape="rect" region="rg" regionLayer="l"/>'


def scene(body=LAYER + HL, assets=None, version="1.2"):
    return doc(body, version=version, assets=pdf() if assets is None else assets)


@pytest.mark.parametrize("name", CASES)
def test_case_validates(name):
    assert case_verdict(name) == "ok"


def test_pdf_with_a_region_shape_is_accepted():
    assert verdict12(scene()) == "ok"


def test_pdf_optional_attributes_and_hand_boxed_regions():
    extra = ' page="3" dpi="300" background="#00000000" annotations="true" license="CC0" credit="x"'
    regions = ('<region id="a" text="Abstract" occurrence="2" x="1.5" y="2" width="30" height="8"/>'
               '<region id="b" x="0" y="0" width="0" height="0"/>')
    assert verdict12(scene(LAYER, assets=pdf(extra, regions))) == "ok"
    assert verdict12(scene(LAYER, assets=pdf(regions=""))) == "ok"


def test_shape_with_its_own_size_still_validates():
    assert verdict12(doc('<shape id="s" shape="rect" width="10" height="10"/>', version="1.1")) == "ok"


def test_region_shape_with_padding_and_own_transform_is_accepted():
    hl = '<shape id="hl" shape="ellipse" region="rg" regionLayer="l" regionPadding="-2.5" rotation="3" scaleX="1.1"/>'
    assert verdict12(scene(LAYER + hl)) == "ok"


# ---- XSD ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,assets", [
    ("no src", pdf(drop=("src",))),
    ("no cache", pdf(drop=("cache",))),
    ("no cacheSha256", pdf(drop=("cacheSha256",))),
    ("no width", pdf(drop=("width",))),
    ("no height", pdf(drop=("height",))),
    ("dpi 17", pdf(' dpi="17"')),
    ("dpi 1201", pdf(' dpi="1201"')),
    ("page 0", pdf(' page="0"')),
    ("upper-case sha", pdf().replace(H, H.upper())),
    ("short sha", pdf().replace(H, H[:63])),
    ("region without x", pdf(regions='<region id="a" y="0" width="1" height="1"/>')),
    ("region negative width", pdf(regions='<region id="a" x="0" y="0" width="-1" height="1"/>')),
    ("region occurrence 0", pdf(regions='<region id="a" occurrence="0" x="0" y="0" width="1" height="1"/>')),
    ("region without id", pdf(regions='<region x="0" y="0" width="1" height="1"/>')),
])
def test_xsd_rejects(name, assets):
    assert verdict12(scene(LAYER, assets=assets)) == "xsd"


def test_xsd_rejects_a_non_numeric_region_padding():
    assert verdict12(scene(LAYER + '<shape id="hl" shape="rect" region="rg" regionLayer="l" regionPadding="x"/>')) == "xsd"


# ---- Schematron -----------------------------------------------------------------------------------------

def test_V9_pdf_needs_version_1_2():
    for v in ("1.0", "1.1"):
        assert verdict12(scene(LAYER, version=v)) == "sch:V9"
    assert verdict12(scene(LAYER, version="1.2")) == "ok"


def test_C66_pdf_pins_its_source():
    assert verdict12(scene(LAYER, assets=pdf(drop=("sha256",)))) == "sch:C66"


def test_C67_region_needs_its_layer():
    hl = '<shape id="hl" shape="rect" region="rg"/>'
    v = verdict12(scene(LAYER + hl))
    assert "C67" in v and v.startswith("sch:")


def test_C68_no_other_transform_parent_or_constraint():
    other = '<shape id="o" shape="rect" width="5" height="5"/>'
    parent = '<shape id="hl" shape="rect" region="rg" regionLayer="l" parent="o"/>'
    assert verdict12(scene(LAYER + other + parent)) == "sch:C68"
    constr = ('<shape id="hl" shape="rect" region="rg" regionLayer="l">'
              '<transformConstraint type="copy-position" target="o"/></shape>')
    assert verdict12(scene(LAYER + other + constr)) == "sch:C68"


def test_C69_size_unless_region():
    assert verdict12(scene(LAYER + '<shape id="s" shape="rect" width="10"/>')) == "sch:C69"
    assert verdict12(scene(LAYER + '<shape id="s" shape="rect" height="10"/>')) == "sch:C69"
    assert verdict12(scene(LAYER + '<shape id="s" shape="rect"/>')) == "sch:C69"
    assert verdict12(scene(LAYER + '<shape id="s" shape="rect" width="10" height="10"/>')) == "ok"


def test_R51_region_must_name_a_region_of_a_pdf_asset():
    other = '<shape id="o" shape="rect" width="5" height="5"/>'
    hl = '<shape id="hl" shape="rect" region="o" regionLayer="l"/>'
    assert verdict12(scene(LAYER + other + hl)) == "sch:R51,R52"
    # a region that exists only in a symbol is not a region of a pdf asset
    hl2 = '<shape id="hl" shape="rect" region="nope" regionLayer="l"/>'
    assert "R51" in verdict12(scene(LAYER + hl2))


def test_R52_region_layer_shows_the_page_that_holds_the_region():
    other = pdf(pid="q", regions='<region id="rq" x="0" y="0" width="1" height="1"/>')
    layers = LAYER + '<layer id="lq" asset="q" x="0" y="0"/>'
    assert verdict12(scene(layers + '<shape id="hl" shape="rect" region="rg" regionLayer="lq"/>',
                           assets=pdf() + other)) == "sch:R52"
    assert verdict12(scene(layers + '<shape id="hl" shape="rect" region="rq" regionLayer="lq"/>',
                           assets=pdf() + other)) == "ok"
    # regionLayer naming a shape, not a layer
    sh = '<shape id="s" shape="rect" width="5" height="5"/>'
    assert verdict12(scene(LAYER + sh + '<shape id="hl" shape="rect" region="rg" regionLayer="s"/>')) == "sch:R52"
