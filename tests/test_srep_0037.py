"""SREP 37: object3D/@tracking and Schematron rule TXT2 (tracking needs primitive="text")."""
import os

import pytest

from test_schema_rules import ROOT, doc, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0037-text3d-tracking.xml")
MAT = '<materials><material id="m" baseColor="#FFFFFF"/></materials>'


def obj(attrs, version="1.1"):
    return doc(f'<object3D id="o" material="m" {attrs}/>', version, head=MAT)


def test_case_validates():
    # version 1.2 is added to the enumeration centrally; checked here as 1.1 (tracking is accepted in every version).
    assert verdict(open(CASE, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok"


@pytest.mark.parametrize("primitive", ["box", "sphere", "plane", "mesh", "extrude", "clay", "cylinder"])
def test_tracking_on_any_other_primitive_fails_txt2(primitive):
    v = verdict(obj(f'primitive="{primitive}" tracking="100"'))
    assert v.startswith("sch:") and "TXT2" in v.split(":", 1)[1].split(","), v


@pytest.mark.parametrize("version", ["1.1"])
@pytest.mark.parametrize("value", ["0", "200", "-50", "12.5", "1e2"])
# primitive="text" is itself rejected in 1.0 documents (V7), so 1.1 is the lowest version that can carry tracking.
def test_tracking_on_text_passes_in_version_1_1(version, value):
    assert verdict(obj(f'primitive="text" text="II" height="100" tracking="{value}"', version)) == "ok"


def test_text_without_tracking_is_unchanged():
    assert verdict(obj('primitive="text" text="II"')) == "ok"
    assert verdict(obj('primitive="box"')) == "ok"


def test_tracking_must_be_a_number():
    assert verdict(obj('primitive="text" text="II" tracking="wide"')) == "xsd"


def test_txt2_is_reported_once_for_the_object():
    v = verdict(doc('<object3D id="a" primitive="box" tracking="1"/><object3D id="b" primitive="text" text="II" tracking="1"/>'))
    assert v == "sch:TXT2"
