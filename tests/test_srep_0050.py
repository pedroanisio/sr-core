"""SREP 50: key/@carry. The XSD adds a boolean with default false and no Schematron rule, so rejection is by the XSD."""
import os

import pytest

from test_schema_rules import ROOT, doc, verdict

CASES = os.path.join(ROOT, "conformance", "cases")


def case(name):
    """A case of this SREP. It declares version="1.2"; the version enumeration and the V5 gate are applied centrally
    (release coordinator), so until then the document is checked as 1.1, which differs only in that attribute."""
    xml = open(os.path.join(CASES, name + ".xml"), "rb").read()
    assert b'<scene version="1.2">' in xml
    return xml.replace(b'<scene version="1.2">', b'<scene version="1.1">')


def keyed(carry, interpolation="spring"):
    attr = "" if carry is None else f' carry="{carry}"'
    return doc('<shape id="r" shape="rect" width="10" height="10"><animate property="x">'
               '<key time="0" value="0"/>'
               f'<key time="1" value="100" interpolation="{interpolation}"{attr}/>'
               '<key time="3" value="0"/></animate></shape>')


@pytest.mark.parametrize("name", ["srep-0050-spring-carry", "srep-0050-spring-carry-neutral"])
def test_the_cases_validate(name):
    assert verdict(case(name)) == "ok"


def test_the_carry_case_uses_the_attribute_and_the_neutral_case_does_not():
    assert b'carry="true"' in case("srep-0050-spring-carry")
    assert b"carry" not in case("srep-0050-spring-carry-neutral")


@pytest.mark.parametrize("value", [None, "true", "false", "1", "0"])
def test_carry_accepts_booleans_or_nothing(value):
    assert verdict(keyed(value)) == "ok"


def test_carry_on_a_non_spring_key_is_valid_and_only_inert():
    # SREP 50, Semantics 1: elsewhere it has no effect (an engine reports it as information); it is not a schema error
    assert verdict(keyed("true", "linear")) == "ok"


@pytest.mark.parametrize("value", ["maybe", "yes", "", "2"])
def test_carry_rejects_a_non_boolean(value):
    assert verdict(keyed(value)) == "xsd"
