"""SREP 57: generated marker ids (beat.N, bar.N) are accepted where a marker is named (schema 1.4).

The fixtures are documents of the Rust reference's corpus (tests/fixtures/srep-0057/): the valid ones must validate
(three of them warn W04 and one W03 in a validator that reports warnings, which is not a schema matter); the invalid
ones must be rejected by R21. The five attributes are typed xs:NCName, the reference check lives in R21.
"""
import glob
import os
import re

import pytest

from test_schema_rules import ROOT, verdict

FIX = os.path.join(ROOT, "tests", "fixtures", "srep-0057")
VALID = sorted(glob.glob(os.path.join(FIX, "valid", "*.xml")))
INVALID = sorted(glob.glob(os.path.join(FIX, "invalid", "*.xml")))
XSD = open(os.path.join(ROOT, "schema", "scene-render.xsd")).read()


def test_the_fixtures_are_there():
    assert len(VALID) == 12 and len(INVALID) == 7


@pytest.mark.parametrize("path", VALID, ids=os.path.basename)
def test_valid_documents_validate(path):
    assert verdict(open(path, "rb").read()) == "ok"


@pytest.mark.parametrize("path", INVALID, ids=os.path.basename)
def test_invalid_documents_fail_r21(path):
    got = verdict(open(path, "rb").read())
    assert got.startswith("sch:") and "R21" in got[4:].split(","), got


def test_the_five_marker_attributes_are_ncnames_and_none_is_an_idref():
    # keyType/@marker, the timing group's startMarker and endMarker, audioTrackType/@startMarker, stillType/@marker
    assert len(re.findall(r'<xs:attribute name="(?:marker|startMarker|endMarker)" type="xs:NCName"', XSD)) == 5
    assert not re.findall(r'<xs:attribute name="(?:marker|startMarker|endMarker)" type="xs:IDREF"', XSD)


def test_a_dangling_poster_marker_is_no_longer_an_xsd_error():
    # the IDREF type rejected it; SREP 57 loosens it to the validator's warning W04
    doc = open(os.path.join(FIX, "valid", "w04-poster-dangling.xml"), "rb").read()
    assert b'marker="nowhere"' in doc and verdict(doc) == "ok"


def test_an_explicit_marker_still_has_to_exist():
    doc = open(os.path.join(FIX, "valid", "gm-explicit.xml"), "rb").read()
    assert verdict(doc) == "ok"
    names = re.findall(rb'startMarker="([^"]+)"', doc)
    assert names, "the control document names a marker"
    assert verdict(doc.replace(names[0], b"nosuch")).startswith("sch:")


def test_the_generated_id_needs_a_grid():
    doc = open(os.path.join(FIX, "valid", "gm-start.xml"), "rb").read()
    assert verdict(doc) == "ok"
    no_grid = re.sub(rb"<beatGrid[^>]*/>", b"", doc)
    assert verdict(no_grid).startswith("sch:") and "R21" in verdict(no_grid)
