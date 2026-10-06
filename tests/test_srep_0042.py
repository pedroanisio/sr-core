"""SREP 42: object3D/@animationClipTo, @animationBlend, @animationOffsetTo (types and defaults; no Schematron rule)."""
import glob
import json
import os
import struct

import pytest

from test_schema_rules import ROOT, etree, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0042-*.xml")))
XSD_PATH = os.path.join(ROOT, "schema", "scene-render.xsd")
NS = {"xs": "http://www.w3.org/2001/XMLSchema"}
ASSETS = '<mesh id="set" src="x.glb"/>'


def mesh(attrs, version="1.1"):
    return (f'<scene version="{version}"><project width="100" height="100" fps="1" duration="1"/>'
            f'<assets>{ASSETS}</assets><composition><object3D id="o" primitive="mesh" mesh="set" {attrs}/></composition></scene>')


def test_cases_exist():
    assert len(CASES) == 5


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_validates(case):
    # version 1.2 is added to the enumeration centrally; the attributes are accepted in every version.
    assert verdict(open(case, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


def test_the_clip_asset_has_the_two_clips_the_cases_name():
    data = open(os.path.join(ROOT, "conformance", "assets", "clips.glb"), "rb").read()
    n = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + n])
    assert [a["name"] for a in gltf["animations"]] == ["left", "right"]
    assert struct.unpack("<I", data[8:12])[0] == len(data)


def test_defaults():
    tree = etree.parse(XSD_PATH)
    got = {a: tree.xpath(f"//xs:complexType[@name='object3DType']/xs:attribute[@name='{a}']/@default", namespaces=NS)
           for a in ("animationClipTo", "animationBlend", "animationOffsetTo")}
    assert got == {"animationClipTo": [], "animationBlend": ["0"], "animationOffsetTo": ["0"]}


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_accepted_in_every_version(version):
    assert verdict(mesh('animationClip="a" animationClipTo="b" animationBlend="0.5" animationOffsetTo="-2.5"', version)) == "ok"


@pytest.mark.parametrize("attrs", ['animationBlend="0"', 'animationBlend="1"', 'animationClipTo="2"',
                                   'animationOffsetTo="1e1"', 'animationBlend="0.25" animationOffsetTo="3"'])
def test_valid_values_are_accepted(attrs):
    assert verdict(mesh(attrs)) == "ok"


@pytest.mark.parametrize("attrs", ['animationBlend="1.5"', 'animationBlend="-0.1"', 'animationBlend="half"',
                                   'animationOffsetTo="soon"', 'animationOffsetTo=""'])
def test_invalid_values_are_rejected_by_the_xsd(attrs):
    assert verdict(mesh(attrs)) == "xsd"


def test_the_weight_may_be_animated():
    xml = mesh("").replace('/></composition>', '><animate property="animationBlend"><key time="0" value="0"/>'
                                                '<key time="1" value="1"/></animate></object3D></composition>')
    assert verdict(xml) == "ok"
