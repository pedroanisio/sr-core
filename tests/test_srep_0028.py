"""SREP 28: R42, R43, R44 check the kind of asset a reference names."""
import os

import pytest

etree = pytest.importorskip("lxml.etree")
from test_schema_rules import ROOT, verdict  # noqa: E402


def case(name):
    """A conformance case; the 1.2 version gate is applied centrally later, so the case is validated as 1.1."""
    with open(os.path.join(ROOT, "conformance", "cases", name), "rb") as f:
        return f.read().replace(b'<scene version="1.2">', b'<scene version="1.1">')


def scene(assets="", paints="", body="", effects="", symbols=""):
    return ('<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/>'
            f'<assets>{assets}</assets>'
            + (f"<paints>{paints}</paints>" if paints else "")
            + (f"<symbols>{symbols}</symbols>" if symbols else "")
            + f"<composition>{body}</composition>"
            + (f"<effects>{effects}</effects>" if effects else "") + "</scene>")


IMG = '<image id="img" src="x.png" width="4" height="4"/>'
GEN = '<generator id="gen" kind="noise" width="4" height="4"/>'
TXT = '<text id="txt" text="hi" width="40" height="10" size="8"/>'


def rules(xml):
    v = verdict(xml)
    return v.split(":", 1)[1].split(",") if v.startswith("sch:") else [v]


def test_case_validates():
    assert verdict(case("srep-0028-asset-kinds.xml")) == "ok"


def test_r42_pattern_naming_a_generator_is_rejected():
    assert "R42" in rules(scene(IMG + GEN, '<pattern id="pp" asset="gen"/>'))


def test_r42_pattern_naming_a_text_asset_is_rejected():
    assert "R42" in rules(scene(IMG + TXT, '<pattern id="pp" asset="txt"/>'))


def test_r42_pattern_naming_an_image_is_accepted():
    assert verdict(scene(IMG, '<pattern id="pp" asset="img"/>')) == "ok"


def test_r42_only_pattern_paints():
    # a gradient paint has no @asset: the rule must not fire on it
    assert verdict(scene(IMG, '<linearGradient id="lg"><stop offset="0" color="#000000"/><stop offset="1" color="#FFFFFF"/></linearGradient>')) == "ok"


def test_r43_emitter_naming_a_text_asset_is_rejected():
    assert "R43" in rules(scene(IMG + TXT, body='<particleEmitter id="pe" emitterAsset="txt"/>'))


def test_r43_emitter_naming_an_image_is_accepted():
    assert verdict(scene(IMG, body='<particleEmitter id="pe" emitterAsset="img"/>')) == "ok"


LAYER = '<layer id="lay" asset="img" visible="false"/>'


@pytest.mark.parametrize("etype", ["displacement-map", "difference-key", "shader"])
def test_r44_effect_source_naming_an_asset_is_rejected(etype):
    assert "R44" in rules(scene(IMG, body=LAYER, effects=f'<effect id="e" type="{etype}" source="img"/>'))


@pytest.mark.parametrize("etype", ["displacement-map", "difference-key", "shader"])
def test_r44_effect_source_naming_a_composition_node_is_accepted(etype):
    assert verdict(scene(IMG, body=LAYER, effects=f'<effect id="e" type="{etype}" source="lay"/>')) == "ok"


def test_r44_effect_source_naming_a_node_inside_a_symbol_is_accepted():
    sym = '<symbol id="sy"><layer id="in-sym" asset="img" visible="false"/></symbol>'
    xml = scene(IMG, body=LAYER, symbols=sym, effects='<effect id="e" type="displacement-map" source="in-sym"/>')
    assert verdict(xml) == "ok"


def test_r44_other_effect_types_are_not_checked():
    # an effect type outside the three keeps whatever @source meant before; the rule's context excludes it
    xml = scene(IMG, body=LAYER, effects='<effect id="e" type="blur" source="img"/>')
    assert "R44" not in rules(xml)
