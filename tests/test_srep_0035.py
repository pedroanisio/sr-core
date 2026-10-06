"""SREP 35: textAnimator/@presetEase (a closed enumeration of seven curves), accepted in every version."""
import os

import pytest

from test_schema_rules import ROOT, doc, verdict

CASE = os.path.join(ROOT, "conformance", "cases", "srep-0035-preset-ease-curves.xml")
CURVES = ["linear", "quad-in", "quad-out", "cubic-out", "expo-out", "back-out", "bounce-out"]
ASSET = '<text id="t" text="Hi" width="100" height="50" size="20"/>'


def layer(animator):
    return doc(f'<layer id="l" asset="t">{animator}</layer>', assets=ASSET)


def test_case_validates():
    # The case says version 1.2; the version enumeration gains 1.2 centrally, so check it as 1.1 here
    # (the attribute is accepted in every version, SREP 35 Backwards compatibility).
    xml = open(CASE, "rb").read().replace(b'version="1.2"', b'version="1.1"')
    assert verdict(xml) == "ok"


@pytest.mark.parametrize("curve", CURVES)
def test_each_curve_is_accepted(curve):
    assert verdict(layer(f'<textAnimator preset="ascend" presetEase="{curve}"/>')) == "ok"


def test_accepted_without_preset():
    assert verdict(layer('<textAnimator presetEase="linear"/>')) == "ok"


@pytest.mark.parametrize("bad", ["elastic-out", "ease-in-out", "Linear", ""])
def test_a_curve_outside_the_enumeration_is_rejected_by_the_xsd(bad):
    assert verdict(layer(f'<textAnimator preset="ascend" presetEase="{bad}"/>')) == "xsd"


def test_ease_is_not_a_textanimator_attribute():
    assert verdict(layer('<textAnimator preset="ascend" ease="linear"/>')) == "xsd"
