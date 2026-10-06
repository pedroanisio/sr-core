"""SREP 19: legibility checks. XSD attributes only; no Schematron rule is added.

The cases declare version="1.2". The 1.2 value of scene/@version and the V5 gate are applied centrally, so the
cases are validated here with the version attribute set to 1.1 (the fragment accepts the attributes in every version).
"""
import glob
import os

import pytest
from test_schema_rules import ROOT, doc, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0019-*.xml")))


def acc(attrs):
    return doc(head=f"<metadata><accessibility {attrs}/></metadata>")


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_cases_validate(case):
    assert len(CASES) == 4
    assert verdict(open(case).read().replace('version="1.2"', 'version="1.1"').encode()) == "ok"


@pytest.mark.parametrize("attrs", [
    'legibilityCheck="warn"',
    'legibilityCheck="error" readingSpeed="17" minDisplayTime="0.8333" minTextSize="3vh"',
    'minTextSize="24"',
    'legibilityCheck="off" minDisplayTime="0"',
])
def test_accepted(attrs):
    assert verdict(acc(attrs)) == "ok"


@pytest.mark.parametrize("attrs", [
    'legibilityCheck="maybe"',
    'readingSpeed="0"',
    'readingSpeed="fast"',
    'minDisplayTime="-1"',
    'minTextSize="big"',
])
def test_rejected_by_xsd(attrs):
    assert verdict(acc(attrs)) == "xsd"


def test_caption_track_reading_speed():
    def track(a):
        return (f'<scene version="1.1"><project width="100" height="100" fps="1" duration="1"/><composition/>'
                f'<captions><captionTrack id="en" language="en-US" {a}><cue start="0" end="1" text="x"/>'
                f'</captionTrack></captions></scene>').replace("<composition/>", "<composition></composition>")
    assert verdict(track('readingSpeed="20"')) == "ok"
    assert verdict(track('readingSpeed="0"')) == "xsd"
    assert verdict(track('readingSpeed="slow"')) == "xsd"
