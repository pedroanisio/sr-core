"""SREP 52: captionTrack/@lineBreaks (greedy | source, default greedy). No Schematron rule; rejection is by the XSD."""
import os

import pytest

from test_schema_rules import ROOT, doc, etree, verdict

CASES = os.path.join(ROOT, "conformance", "cases")
XS = {"xs": "http://www.w3.org/2001/XMLSchema"}


def case(name):
    """A case of this SREP. It declares version="1.2"; the version enumeration and the V5 gate are applied centrally
    (release coordinator), so until then the document is checked as 1.1, which differs only in that attribute."""
    xml = open(os.path.join(CASES, name + ".xml"), "rb").read()
    assert b'<scene version="1.2">' in xml
    return xml.replace(b'<scene version="1.2">', b'<scene version="1.1">')


def track(line_breaks, preset="classic"):
    attr = "" if line_breaks is None else f' lineBreaks="{line_breaks}"'
    return doc().replace("</scene>", f'<captions><captionTrack id="c" language="en" preset="{preset}"{attr}>'
                                     '<cue start="0" end="1" text="a b&#10;c"/></captionTrack></captions></scene>')


@pytest.mark.parametrize("name", ["srep-0052-caption-lines-source", "srep-0052-caption-lines-greedy"])
def test_the_cases_validate(name):
    assert verdict(case(name)) == "ok"


def test_the_source_case_has_source_newlines_in_its_cue():
    xml = case("srep-0052-caption-lines-source")
    assert b'lineBreaks="source"' in xml and xml.count(b"&#10;") == 2


@pytest.mark.parametrize("value", [None, "greedy", "source"])
def test_line_breaks_accepts_its_two_values_or_nothing(value):
    assert verdict(track(value)) == "ok"


def test_source_with_one_word_preset_is_valid_and_only_inert():
    # SREP 52 Semantics 4: one-word pages each word alone, source breaks have no effect; not a schema error
    assert verdict(track("source", "one-word")) == "ok"


@pytest.mark.parametrize("value", ["Source", "legacy", "", "true"])
def test_line_breaks_rejects_other_values(value):
    assert verdict(track(value)) == "xsd"


def test_the_default_is_greedy():
    schema = etree.parse(os.path.join(ROOT, "schema", "scene-render.xsd"))
    attr = schema.xpath("//xs:complexType[@name='captionTrackType']/xs:attribute[@name='lineBreaks']", namespaces=XS)[0]
    assert attr.get("default") == "greedy"
    assert [e.get("value") for e in attr.xpath(".//xs:enumeration", namespaces=XS)] == ["greedy", "source"]
