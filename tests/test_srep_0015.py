"""SREP 15: stroke markers (strokeMarkerType, strokeMarkers, rule C65)."""
import glob
import os

import pytest

from srep_support import ROOT, case_verdict, verdict12
from test_schema_rules import doc

CASES = ("srep-0015-arrow", "srep-0015-trim-arrow", "srep-0015-both-ends", "srep-0015-union")


def shape(kind, extra=""):
    path = ' path="M0 0 L50 0"' if kind == "path" else ""
    return doc(f'<shape id="s" shape="{kind}"{path} width="50" height="50" stroke="#00FF00FF" strokeWidth="2"{extra}/>')


@pytest.mark.parametrize("name", CASES)
def test_case_validates(name):
    assert case_verdict(name) == "ok"


@pytest.mark.parametrize("kind", ["rect", "ellipse", "rounded-rect", "polygon", "star"])
def test_c65_rejects_a_marker_on_a_closed_outline(kind):
    assert verdict12(shape(kind, ' markerEnd="arrow"')) == "sch:C65"
    assert verdict12(shape(kind, ' markerStart="circle"')) == "sch:C65"


@pytest.mark.parametrize("kind", ["path", "line"])
def test_markers_on_an_open_outline_are_accepted(kind):
    assert verdict12(shape(kind, ' markerStart="bar" markerEnd="open-arrow" markerSize="2.5"')) == "ok"


def test_none_is_neutral_on_a_closed_outline():
    assert verdict12(shape("rect", ' markerEnd="none" markerStart="none"')) == "ok"
    assert verdict12(shape("rect")) == "ok"


@pytest.mark.parametrize("value", ["none", "arrow", "open-arrow", "circle", "square", "diamond", "bar"])
def test_every_marker_kind_is_accepted(value):
    assert verdict12(shape("path", f' markerEnd="{value}"')) == "ok"


@pytest.mark.parametrize("extra", [' markerEnd="triangle"', ' markerSize="0"', ' markerSize="-1"'])
def test_xsd_rejects_unknown_marker_or_nonpositive_size(extra):
    assert verdict12(shape("path", extra)) == "xsd"


def test_accepted_in_every_version():
    assert verdict12(shape("path", ' markerEnd="arrow"').replace('version="1.1"', 'version="1.0"')) == "ok"
    assert verdict12(shape("path", ' markerEnd="arrow"')) == "ok"


def test_schema_ids_are_unique():
    from lxml import etree
    sch = etree.parse(os.path.join(ROOT, "schema", "scene-render.sch"))
    ns = {"s": "http://purl.oclc.org/dsdl/schematron"}
    for xp in ("//s:pattern/@id", "//s:assert/@id"):
        ids = sch.xpath(xp, namespaces=ns)
        assert len(ids) == len(set(ids)), sorted(i for i in set(ids) if ids.count(i) > 1)
