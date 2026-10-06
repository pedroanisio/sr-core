"""SREP 20: where lines of text sit in a text box. Semantics only: the schema is unchanged, so this file checks
that the case documents are valid and that the attributes the rules read stay accepted. The pixel positions are
checked by the compatibility kit with the pinned test font (see conformance/expected.json).

The cases declare version="1.2"; the 1.2 value of scene/@version is applied centrally, so they are validated here
with the version attribute set to 1.1.
"""
import glob
import os

import pytest
from test_schema_rules import ROOT, doc, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0020-*.xml")))


def text(attrs):
    return doc('<layer id="l" asset="t"/>',
               assets=f'<text id="t" text="HH" width="400" height="300" size="100" {attrs}/>')


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_cases_validate(case):
    assert len(CASES) == 7
    assert verdict(open(case).read().replace('version="1.2"', 'version="1.1"').encode()) == "ok"


@pytest.mark.parametrize("attrs", [
    'lineHeight="1.5" verticalAlign="top" align="start"',
    'verticalAlign="middle" align="center"',
    'verticalAlign="bottom" align="end"',
    'align="justify" maxLines="3"',
])
def test_attributes_the_rules_read_are_accepted(attrs):
    assert verdict(text(attrs)) == "ok"


@pytest.mark.parametrize("attrs", ['verticalAlign="centre"', 'align="left"', 'lineHeight="0"', 'lineHeight="tall"'])
def test_values_the_rules_do_not_define_are_rejected(attrs):
    assert verdict(text(attrs)) == "xsd"
