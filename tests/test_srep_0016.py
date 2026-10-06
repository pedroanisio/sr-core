"""SREP 16: connectors (connectorType, nodeCoreAttributes split; rules V11, C60-C64, R48-from, R48-to, R49, R50).

Ids differ from the SREP's draft numbering by the coordinator's table: R42 -> R48, R43 -> R49, R44 -> R50, V8 -> V11.
"""
import pytest

from srep_support import case_verdict, verdict12, xsd_error
from test_schema_rules import doc

CASES = ["srep-0016-" + n for n in
         ("straight", "rotated-gap", "anchor", "orthogonal", "curved", "arrow", "trim-arrow", "follows", "absent",
          "group-box")]
RB = ('<shape id="r" shape="rect" width="80" height="60" x="100" y="150"/>'
      '<shape id="b" shape="rect" width="80" height="60" x="460" y="150"/>')


def conn(attrs='from="r" to="b"', inner="", head="", version="1.2", body=RB, assets=""):
    return doc(f'{body}<connector id="c" {attrs}>{inner}</connector>', version=version, head=head, assets=assets)


@pytest.mark.parametrize("name", CASES)
def test_case_validates(name):
    assert case_verdict(name) == "ok"


def test_minimal_connector_is_accepted():
    assert verdict12(conn()) == "ok"


def test_point_ends_are_accepted():
    assert verdict12(conn('fromX="10" fromY="20" toX="50%" toY="80"', body="")) == "ok"
    assert verdict12(conn('from="r" toX="300" toY="20" fromAnchor="right"')) == "ok"


def test_full_attribute_set_is_accepted():
    attrs = ('from="r" to="b" fromAnchor="top-left" toAnchor="bottom-right" fromGap="2" toGap="3" route="orthogonal" '
             'points="300,100 300,200" stroke="#FF0000FF" strokeWidth="3" strokeCap="round" strokeJoin="bevel" '
             'miterLimit="2" dash="4 2" dashOffset="1" blend="add" trimStart="0.1" trimEnd="0.9" markerStart="circle" '
             'markerEnd="open-arrow" markerSize="3" opacity="0.5" z="2"')
    assert verdict12(conn(attrs)) == "ok"
    assert verdict12(conn('from="r" to="b" route="curved" bend="-45"')) == "ok"


def test_connector_in_a_group_and_a_symbol():
    inner = RB + '<connector id="c" from="r" to="b"/>'
    assert verdict12(doc(f'<group id="g">{inner}</group>', version="1.2")) == "ok"
    sym = f'<symbols><symbol id="s">{inner}</symbol></symbols>'
    assert verdict12(doc('<instance id="i" symbol="s"/>', version="1.2", head=sym)) == "ok"


# ---- XSD ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("attrs", [
    'from="r" to="b" x="5"',                      # no transform of its own: the XSD rejects it
    'from="r" to="b" rotation="10"',
    'from="r" to="b" scaleX="2"',
    'from="r" to="b" parent="r"',
    'from="r" to="b" route="spline"',
    'from="r" to="b" bend="91"',
    'from="r" to="b" bend="-91"',
    'from="r" to="b" fromAnchor="middle"',
    'from="r" to="b" fromGap="-1"',
    'from="r" to="b" labelAt="1.5"',
    'from="r" to="b" labelOrient="vertical"',
    'from="r" to="b" points="1 2"',                # a point is "x,y"
])
def test_xsd_rejects(attrs):
    assert verdict12(conn(attrs)) == "xsd", xsd_error(conn(attrs))


def test_xsd_connector_needs_an_id():
    assert verdict12(doc(RB + '<connector from="r" to="b"/>', version="1.2")) == "xsd"


def test_nodeAttributes_split_keeps_other_nodes_unchanged():
    # every attribute the split moved is still accepted on a shape
    shape = ('<shape id="s" shape="rect" width="10" height="10" name="n" tags="a b" z="1" visible="false" opacity="0.5" '
             'start="0" end="1" condition="true" motionBlur="on" matteMode="alpha" matteVisible="true" parent="s2" '
             'threeD="true" zDepth="1" rotationX="1" rotationY="2" alignX="left" alignY="top" alignTo="frame" '
             'margin="3" x="1" y="2" rotation="3" scaleX="2" anchorX="1" skewX="1"/>'
             '<shape id="s2" shape="rect" width="10" height="10"/>')
    assert verdict12(doc(shape, version="1.1")) == "ok"


# ---- Schematron -----------------------------------------------------------------------------------------

def test_V11_connector_needs_version_1_2():
    for v in ("1.0", "1.1"):
        assert verdict12(conn(version=v)) == "sch:V11"
    assert verdict12(conn(version="1.2")) == "ok"
    assert verdict12(doc(RB, version="1.1")) == "ok"


BAD = {
    "C60 no end": ('from="r"', "C60"),
    "C60 no start": ('to="b"', "C60"),
    "C60 and C62 together": ('from="r" toX="5"', "C60,C62"),   # a lone toX is no end, and breaks the pair rule
    "C61 anchor and point": ('from="r" fromAnchor="top" fromX="1" fromY="2" to="b"', "C61"),
    "C61 to anchor and point": ('from="r" to="b" toAnchor="left" toX="1" toY="2"', "C61"),
    "C62 fromX alone": ('from="r" fromX="5" to="b"', "C62"),
    "C62 toY alone": ('from="r" to="b" toY="5"', "C62"),
    "C63 curved with points": ('from="r" to="b" route="curved" points="10,10"', "C63"),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_rejected_by_schematron(name):
    attrs, rule = BAD[name]
    assert verdict12(conn(attrs)) == "sch:" + rule


def test_C60_two_point_ends_pass():
    assert verdict12(conn('fromX="1" fromY="2" toX="3" toY="4"', body="")) == "ok"


def test_C61_explicit_auto_anchor_with_a_point_passes():
    assert verdict12(conn('from="r" fromAnchor="auto" fromX="1" fromY="2" to="b"')) == "ok"


@pytest.mark.parametrize("prop", ["x", "y", "rotation", "scaleX", "scaleY", "anchorX", "anchorY", "skewX", "skewY"])
def test_C64_connector_has_no_transform_animation(prop):
    inner = f'<animate property="{prop}"><key time="0" value="1"/></animate>'
    assert verdict12(conn(inner=inner)) == "sch:C64"


def test_C64_expression_on_other_than_opacity():
    assert verdict12(conn(inner='<expression property="rotation">time*10</expression>')) == "sch:C64"
    assert verdict12(conn(inner='<expression property="opacity">0.5</expression>')) == "ok"


def test_C64_animating_non_transform_properties_passes():
    inner = ('<animate property="opacity"><key time="0" value="0"/><key time="1" value="1"/></animate>'
             '<animate property="trimEnd"><key time="0" value="0"/><key time="1" value="1"/></animate>'
             '<animate property="bend"><key time="0" value="0"/><key time="1" value="30"/></animate>')
    assert verdict12(conn(inner=inner)) == "ok"


def test_R48_from_and_to_name_a_group_layer_shape_or_instance():
    flock = '<flock id="f" width="10" height="10"/>'
    assert verdict12(conn('from="f" to="b"', body=RB + flock)) == "sch:R48-from"
    assert verdict12(conn('from="r" to="f"', body=RB + flock)) == "sch:R48-to"
    grp = '<group id="g"><shape id="in" shape="rect" width="5" height="5"/></group>'
    assert verdict12(conn('from="g" to="in"', body=RB + grp)) == "ok"


def test_R48_unknown_id():
    assert verdict12(conn('from="nope" to="b"')) == "sch:R48-from"


def test_R48_not_2_5d():
    threed = '<shape id="t" shape="rect" width="10" height="10" threeD="true"/>'
    assert verdict12(conn('from="t" to="b"', body=RB + threed)) == "sch:R48-from"
    child = '<group id="g" threeD="true"><shape id="k" shape="rect" width="5" height="5"/></group>'
    assert verdict12(conn('from="r" to="k"', body=RB + child)) == "sch:R48-to"


def test_R48_not_inside_a_repeat():
    rep = '<repeat id="rp" count="2"><shape id="in" shape="rect" width="5" height="5"/></repeat>'
    assert verdict12(conn('from="in" to="b"', body=RB + rep)) == "sch:R48-from"


def test_R48_same_composition_or_symbol():
    sym = ('<symbols><symbol id="s"><shape id="sa" shape="rect" width="5" height="5"/>'
           '<connector id="sc" from="sa" to="r"/></symbol></symbols>')
    # r lives in the composition, the connector in the symbol
    assert verdict12(doc(RB + '<instance id="i" symbol="s"/>', version="1.2", head=sym)) == "sch:R48-to"
    ok = sym.replace('to="r"', 'to="sa"')
    assert verdict12(doc(RB + '<instance id="i" symbol="s"/>', version="1.2", head=ok)) == "ok"


def test_R49_nothing_is_positioned_by_a_connector():
    assert verdict12(conn(body=RB + '<shape id="k" shape="rect" width="5" height="5" parent="c"/>')) == "sch:R49"
    link = '<shape id="k" shape="rect" width="5" height="5"><link source="c.opacity" property="opacity"/></shape>'
    assert verdict12(conn(body=RB + link)) == "sch:R49"
    assert verdict12(conn(body=RB + '<shape id="k" shape="rect" width="5" height="5" parent="r"/>')) == "ok"


def test_R50_label_names_a_text_asset():
    txt = '<text id="t" text="Hi" width="100" height="20" size="12"/>'
    assert verdict12(conn('from="r" to="b" label="t"', assets=txt)) == "ok"
    assert verdict12(conn('from="r" to="b" label="t" labelAt="0.25" labelOffset="-8" labelOrient="along"',
                          assets=txt)) == "ok"
    assert verdict12(conn('from="r" to="b" label="a"', assets='<audio id="a" src="x.wav"/>')) == "sch:R50"
    assert verdict12(conn('from="r" to="b" label="r"')) == "sch:R50"
