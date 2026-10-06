"""SREP 13: segments in outputs (cut-downs and speed changes). The fragments (output segment, audioTrack and
captionTrack children, five output attributes, segmentType, audioRoleType, rules C54 to C59, R38 to R41 and the
amended C20, C33, R14) and the SREP's ten cases.

The 1.2 enumeration value of scene/@version and the version gate V5 are applied centrally, so the cases are
checked here with as written (version="1.2")."""
import glob
import json
import os

import pytest

from test_schema_rules import ROOT, verdict

CASES = sorted(glob.glob(os.path.join(ROOT, "conformance", "cases", "srep-0013-*.xml")))
OUT = 'path="o.mp4" codec="h264"'


def as_1_1(path):
    return open(path, "rb").read()


def scene(output="", tail="", head="", assets='<audio id="wav" src="x.wav"/>', duration=4):
    """A 1.1 scene with one output; `head` goes between the outputs and the composition, `tail` after it."""
    return (f'<scene version="1.2"><project width="100" height="100" fps="1" duration="{duration}"/>{output}'
            f'<assets>{assets}</assets>{head}<composition><shape id="s" shape="rect" width="10" height="10"/></composition>'
            f'{tail}</scene>')


def out(attrs="", children=""):
    return f'<output id="out" {OUT} {attrs}>{children}</output>'


MIX = '<audioMix><audioTrack id="mix" asset="wav"/><bus id="bus1"/></audioMix>'
MARKERS = '<markers><marker id="m1" time="1"/><marker id="m2" time="2"/></markers>'
SYMBOLS = '<symbols><symbol id="tag"/></symbols>'


def test_the_ten_cases_exist():
    assert [os.path.basename(c)[:-4] for c in CASES] == [
        "srep-0013-overlay-plain", "srep-0013-segment-align-end", "srep-0013-segment-clamp",
        "srep-0013-segment-crossfade", "srep-0013-segment-focus", "srep-0013-segment-join",
        "srep-0013-segment-map-speed", "srep-0013-segment-map", "srep-0013-segment-overlay",
        "srep-0013-segment-remap"]


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_validates(case):
    assert verdict(as_1_1(case)) == "ok"


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_has_an_expected_entry(case):
    cases = json.load(open(os.path.join(ROOT, "conformance", "expected.json")))["cases"]
    assert cases[os.path.basename(case)[:-4]]["rule"] == "SREP 13"


GOOD = {
    "two segments by time": scene(out(children='<segment from="2" to="3"/><segment from="0" to="1" speed="2"/>')),
    "segments by marker": scene(out(children='<segment fromMarker="m1" toMarker="m2" audio="mute"/>'), head=MARKERS),
    "a time and a marker": scene(out(children='<segment from="0" toMarker="m2"/>'), head=MARKERS),
    "segment with timeRemap": scene(out(children='<segment><timeRemap><key time="0" value="3"/><key time="1" value="1"/></timeRemap></segment>')),
    "segment with focus and animate": scene(out(children='<segment from="0" to="1" focusX="0.2" focusY="1">'
                                                         '<animate property="focusX"><key time="0" value="0"/><key time="1" value="1"/></animate></segment>')),
    "crossfade joining segments": scene(out(children='<segment from="2" to="3"><transition type="crossfade" duration="0.5"/></segment>'
                                                     '<segment from="0" to="1"/>')),
    "a segment transition names no nodes (C20)": scene(out(children='<segment from="0" to="1"><transition type="wipe" duration="0.5"/></segment>')),
    "segment to the project end": scene(out(children='<segment from="0" to="4"/>')),
    "start 0 with segments (C54)": scene(out('start="0"', '<segment from="0" to="1"/>')),
    "audio selection": scene(out('audioTracks="mix" audioBuses="bus1" audioRoles="music dialogue" joinFade="0"',
                                 '<segment from="0" to="1"/>'), tail=MIX),
    "overlay": scene(out('overlay="tag"'), head=SYMBOLS),
    "output audio track": scene(out(children='<audioTrack id="oa" asset="wav" role="music"/>')),
    "output caption track transcribes its own audio track (R41, C33)":
        scene(out(children='<audioTrack id="oa" asset="wav"/><captionTrack language="en" id="oc" transcribe="oa" cache="c.json" cacheSha256="0000000000000000000000000000000000000000000000000000000000000000"/>')),
    "burnCaptions names an output caption track (R14)":
        scene(out('burnCaptions="oc"', '<captionTrack language="en" id="oc"><cue start="0" end="1" text="x"/></captionTrack>')),
    "document caption track still names a mix track":
        scene(tail=MIX + '<captions><captionTrack language="en" id="c" transcribe="mix" cache="c.json" cacheSha256="0000000000000000000000000000000000000000000000000000000000000000"/></captions>'),
}


@pytest.mark.parametrize("name", sorted(GOOD))
def test_accepted(name):
    assert verdict(GOOD[name]) == "ok"


SCH_BAD = {
    "C54 segments with start": (scene(out('start="1"', '<segment from="0" to="1"/>')), "C54"),
    "C54 segments with end": (scene(out('end="2"', '<segment from="0" to="1"/>')), "C54"),
    "C55 segment without a span": (scene(out(children='<segment/>')), "C55"),
    "C55 segment with only from": (scene(out(children='<segment from="1"/>')), "C55"),
    "C55 segment with only toMarker": (scene(out(children='<segment toMarker="m1"/>'), head=MARKERS), "C55"),
    "C56 from after to": (scene(out(children='<segment from="2" to="1"/>')), "C56"),
    "C56 from equals to": (scene(out(children='<segment from="1" to="1"/>')), "C56"),
    "C56 negative from": (scene(out(children='<segment from="-1" to="1"/>')), "C56"),
    "C56 to past the duration": (scene(out(children='<segment from="0" to="5"/>')), "C56"),
    "C57 from and fromMarker": (scene(out(children='<segment from="0" fromMarker="m1" to="2"/>'), head=MARKERS), "C57"),
    "C57 to and toMarker": (scene(out(children='<segment from="0" to="2" toMarker="m2"/>'), head=MARKERS), "C57"),
    "C58 two timeRemaps": (scene(out(children='<segment><timeRemap><key time="0" value="1"/></timeRemap>'
                                              '<timeRemap><key time="0" value="1"/></timeRemap></segment>')), "C58"),
    "C58 two transitions": (scene(out(children='<segment from="0" to="1"><transition type="crossfade"/>'
                                               '<transition type="crossfade"/></segment>')), "C58"),
    "R38 fromMarker names no marker": (scene(out(children='<segment fromMarker="nope" to="2"/>')), "R38"),
    "R38 toMarker names no marker": (scene(out(children='<segment from="0" toMarker="nope"/>'), head=MARKERS), "R38"),
    "C59 transition with from": (scene(out(children='<segment from="0" to="1"><transition type="crossfade" from="s"/></segment>')), "C59"),
    "C59 morph transition": (scene(out(children='<segment from="0" to="1"><transition type="morph"/></segment>')), "C59"),
    "C59 luma transition": (scene(out(children='<segment from="0" to="1"><transition type="luma" matte="s"/></segment>')), "C59"),
    "R39 audioTracks names no mix track": (scene(out('audioTracks="nope"'), tail=MIX), "R39"),
    "R39 audioTracks names a bus": (scene(out('audioTracks="bus1"'), tail=MIX), "R39"),
    "R39 audioBuses names a track": (scene(out('audioBuses="mix"'), tail=MIX), "R39"),
    "R40 overlay names no symbol": (scene(out('overlay="nope"')), "R40"),
    "R40 overlay names a shape": (scene(out('overlay="s"')), "R40"),
    "R41 transcribes a mix track, not its own": (scene(out(children='<captionTrack language="en" id="oc" transcribe="mix" cache="c.json" cacheSha256="0000000000000000000000000000000000000000000000000000000000000000"/>'), tail=MIX), "R41"),
    "R41 transcribes nothing": (scene(out(children='<captionTrack language="en" id="oc" transcribe="nope" cache="c.json" cacheSha256="0000000000000000000000000000000000000000000000000000000000000000"/>')), "R41"),
    "R14 burnCaptions names nothing": (scene(out('burnCaptions="nope"')), "R14"),
    "C33 document caption track names no audio track": (scene(tail='<captions><captionTrack language="en" id="c" transcribe="nope" cache="c.json" cacheSha256="0000000000000000000000000000000000000000000000000000000000000000"/></captions>'), "C33"),
    "C20 transition outside a segment needs from or to": (
        scene(head='<symbols><symbol id="tag"><transition type="crossfade"/></symbol></symbols>'), "C20"),
}


@pytest.mark.parametrize("name", sorted(SCH_BAD))
def test_rejected_by_schematron(name):
    xml, rule = SCH_BAD[name]
    v = verdict(xml)
    assert v.startswith("sch:") and rule in v.split(":", 1)[1].split(","), v


XSD_BAD = {
    "segment speed 0": scene(out(children='<segment from="0" to="1" speed="0"/>')),
    "segment audio unknown": scene(out(children='<segment from="0" to="1" audio="loud"/>')),
    "segment focusX 2": scene(out(children='<segment from="0" to="1" focusX="2"/>')),
    "segment unknown child": scene(out(children='<segment from="0" to="1"><shape id="q" shape="rect"/></segment>')),
    "audioRoles unknown role": scene(out('audioRoles="music karaoke"')),
    "joinFade negative": scene(out('joinFade="-1"')),
    "audioTrack role unknown": scene(tail='<audioMix><audioTrack id="mix" asset="wav" role="karaoke"/></audioMix>'),
}


@pytest.mark.parametrize("name", sorted(XSD_BAD))
def test_rejected_by_xsd(name):
    assert verdict(XSD_BAD[name]) == "xsd"
