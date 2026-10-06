"""SREP 23: corner radii on rect shapes. Semantics only: the schema is unchanged. radius and cornerRadii were
already declared on every shape, so this file checks that the case documents are valid and that rect keeps
accepting both attributes (and still rejects malformed values). The pixels are checked by the compatibility kit.

The cases declare version="1.2"; the 1.2 value of scene/@version is applied centrally, so they are validated here
with the version attribute set to 1.1.
"""
import glob
import os

import pytest
from test_schema_rules import ROOT, doc, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0023-*.xml")))


def rect(attrs):
    return doc(f'<shape id="r" shape="rect" width="200" height="100" {attrs}/>')


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_cases_validate(case):
    assert len(CASES) == 3
    assert verdict(open(case).read().replace('version="1.2"', 'version="1.1"').encode()) == "ok"


@pytest.mark.parametrize("attrs", ['radius="30"', 'cornerRadii="30 0 0 0"', 'radius="0"', 'radius="8" cornerRadii="4 4 0 0"', ''])
def test_rect_accepts_radii(attrs):
    assert verdict(rect(attrs)) == "ok"


@pytest.mark.parametrize("attrs", ['radius="-1"', 'radius="round"', 'cornerRadii="a b c d"'])
def test_rect_rejects_malformed_radii(attrs):
    assert verdict(rect(attrs)) == "xsd"
