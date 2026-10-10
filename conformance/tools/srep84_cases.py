#!/usr/bin/env python3
"""Writes the SREP 84 kit cases (boolean and integer attributes are tested by value, not by spelling) to
srep_cases/srep-0084.json.

Each case writes one attribute that a changed rule reads in a lexical form other than the one the rule compared
literally: "1", "0", a padded " true ", a "+0" or "00". The documents are small and written here; the pyro cases
are SREP 78's own kit cases (draft) with one attribute rewritten, and need that draft ("requires").

A case whose document names a file the kit does not ship (a video with an audio track) checks only that the rule is
absent ({"absent": [rule]}), not the whole verdict, since a renderer reports the missing file. Every other case
checks the verdict. BEFORE gives the verdict of each document under the text before SREP 84 (Schematron and XSD),
which tests/test_srep_0084.py checks too. Usage: python3 conformance/tools/srep84_cases.py; then
python3 conformance/make_cases.py.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)

HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<scene version="{v}"><project width="64" height="64" fps="24" duration="1"/>'
TILE = '<assets><image id="img" src="../assets/tile.png" width="16" height="16"/></assets>'


def doc(body, version="1.2", head="", tail=""):
    return HEAD.format(v=version) + head + f"<composition>{body}</composition>{tail}</scene>\n"


def c15(attrs):
    return doc(f'<layer id="l" asset="img" {attrs}><timeRemap><key time="0" value="0"/><key time="1" value="0.5"/>'
               '</timeRemap></layer>', head=TILE)


def c43(alpha):
    return (HEAD.format(v="1.2") + f'<output id="o" path="out/o.mp4" codec="h264" alpha="{alpha}"/>'
            '<composition><shape id="s" shape="rect" width="10" height="10" fill="#FFFFFF"/></composition></scene>\n')


def r15(has_audio):
    return doc('<shape id="s" shape="rect" width="10" height="10" fill="#FFFFFF"/>',
               head=f'<assets><video id="v" src="../assets/srep84-absent.mp4" width="64" height="64" fps="24" duration="1" hasAudio="{has_audio}"/></assets>',
               tail='<audioMix><audioTrack id="t" asset="v"/></audioMix>')


R48_BODY = ('<shape id="r" shape="rect" width="8" height="8" x="4" y="4" fill="#FF0000"/>'
            '<shape id="b" shape="rect" width="8" height="8" x="40" y="40" fill="#0000FF"/>')


def r48(threed, end="from"):
    group = f'<group id="g" threeD="{threed}"><shape id="k" shape="rect" width="5" height="5" fill="#00FF00"/></group>'
    ends = 'from="k" to="b"' if end == "from" else 'from="r" to="k"'
    return doc(R48_BODY + group + f'<connector id="c" {ends} stroke="#FFFFFF" strokeWidth="2"/>')


def vol5(blackbody):
    return doc('<object3D id="cloud" primitive="volume" volume="smoke">'
               f'<medium blackbody="{blackbody}" emissionScale="0.1"/></object3D>', version="1.3",
               head='<assets><volume id="smoke" src="../assets/srep79-uniform.srvol" boundsMinX="0" boundsMinY="0" '
                    'boundsMinZ="0" boundsMaxX="32" boundsMaxY="32" boundsMaxZ="2"/></assets>')


def c80(attrs):
    return doc(f'<repeat id="r" x="32" y="32" {attrs}><points type="grid" columns="3" rows="2"/>'
               '<shape id="s" shape="rect" width="4" height="4" fill="#FF0000"/></repeat>')


def geo2(size):
    return (HEAD.format(v="1.3") + '<assets><tiles id="dem" src="../assets/halves.pmtiles"/>'
            '<map id="m" width="64" height="32" background="#FFFFFF"/></assets><composition>'
            '<object3D id="earth" primitive="globe" map="m" terrain="dem" '
            f'terrainTileSize="{size}" terrainZoom="0" planetRadius="1000" radius="20" x="32" y="32" segments="32"/>'
            '</composition></scene>\n')


SOURCES = {}


def srep78(case, old, new):
    xml = json.load(open(os.path.join(CONF, "srep_cases", "srep-0078.json")))[case]["xml"]
    assert xml.count(old) == 1, (case, old)
    out = xml.replace(old, new)
    SOURCES[out] = f"kit case {case} (SREP 78, draft) with {old} written {new}, by conformance/tools/srep84_cases.py"
    return out


# name: (rule, document, findings with SREP 84, verdict before SREP 84, requires, source)
CASES = {
    # C15 (SREP 13's time remap; reverse is xs:boolean, loop xs:nonNegativeInteger)
    "c15-reverse-0": ("C15", c15('reverse="0"'), {"valid": True}, "sch:C15", None),
    "c15-reverse-padded-false": ("C15", c15('reverse=" false "'), {"valid": True}, "sch:C15", None),
    "c15-reverse-1": ("C15", c15('reverse="1"'), {"valid": False, "codes": ["C15"]}, "sch:C15", None),
    "c15-loop-00": ("C15", c15('loop="00"'), {"valid": True}, "sch:C15", None),
    "c15-loop-plus-0": ("C15", c15('loop="+0"'), {"valid": True}, "sch:C15", None),
    "c15-loop-padded-0": ("C15", c15('loop=" 0 "'), {"valid": True}, "sch:C15", None),
    "c15-loop-plus-2": ("C15", c15('loop="+2"'), {"valid": False, "codes": ["C15"]}, "sch:C15", None),
    # C43 (output/@alpha, xs:boolean)
    "c43-alpha-1": ("C43", c43("1"), {"valid": False, "codes": ["C43"]}, "ok", None),
    "c43-alpha-padded-true": ("C43", c43(" true "), {"valid": False, "codes": ["C43"]}, "ok", None),
    "c43-alpha-0": ("C43", c43("0"), {"valid": True}, "ok", None),
    # R15 (video/@hasAudio, xs:boolean); the kit ships no video, so only the rule is checked
    "r15-has-audio-padded-true": ("R15", r15(" true "), {"absent": ["R15"]}, "sch:R15", None),
    "r15-has-audio-padded-1": ("R15", r15(" 1 "), {"absent": ["R15"]}, "sch:R15", None),
    "r15-has-audio-0": ("R15", r15("0"), {"valid": False, "codes": ["R15"]}, "sch:R15", None),
    # R48-from, R48-to (threeD, xs:boolean, on the target or an ancestor)
    "r48-from-threed-1": ("R48-from", r48("1"), {"valid": False, "codes": ["R48-from"]}, "ok", None),
    "r48-from-threed-padded-true": ("R48-from", r48(" true "), {"valid": False, "codes": ["R48-from"]}, "ok", None),
    "r48-to-threed-1": ("R48-to", r48("1", end="to"), {"valid": False, "codes": ["R48-to"]}, "ok", None),
    "r48-from-threed-0": ("R48-from", r48("0"), {"valid": True}, "ok", None),
    # VOL5 (medium/@blackbody, xs:boolean)
    "vol5-blackbody-padded-true": ("VOL5", vol5(" true "), {"valid": False, "codes": ["VOL5"]}, "ok", None),
    "vol5-blackbody-padded-1": ("VOL5", vol5(" 1 "), {"valid": False, "codes": ["VOL5"]}, "ok", None),
    "vol5-blackbody-0": ("VOL5", vol5("0"), {"valid": True}, "ok", None),
    # C80 (repeat/@from xs:nonNegativeInteger, repeat/@step xs:positiveInteger, with a points child)
    "c80-from-plus-0": ("C80", c80('from="+0"'), {"valid": True}, "sch:C80", None),
    "c80-step-plus-1": ("C80", c80('step="+1"'), {"valid": True}, "sch:C80", None),
    "c80-step-01": ("C80", c80('step="01"'), {"valid": True}, "ok", None),
    "c80-from-plus-2": ("C80", c80('from="+2"'), {"valid": False, "codes": ["C80"]}, "sch:C80", None),
    # GEO2 (object3D/@terrainTileSize, xs:positiveInteger, a power of two)
    "geo2-tile-size-plus-64": ("GEO2", geo2("+64"), {"valid": True}, "sch:GEO2", None),
    "geo2-tile-size-064": ("GEO2", geo2("064"), {"valid": True}, "ok", None),
    "geo2-tile-size-plus-48": ("GEO2", geo2("+48"), {"valid": False, "codes": ["GEO2"]}, "sch:GEO2", None),
    # PYRO9, PYRO10, PYRO11 (draft SREP 78: pyro/@follow xs:boolean, pyro/@followMargin xs:positiveInteger)
    "pyro9-follow-padded-true-closed": ("PYRO9", srep78("srep-0078-pyro9-closed", 'follow="true"', 'follow=" true "'),
                                        {"valid": False, "codes": ["PYRO9"]}, "sch:PYRO10", [78]),
    "pyro10-follow-padded-1": ("PYRO10", srep78("srep-0078-valid-pyro-follow", 'follow="true"', 'follow=" 1 "'),
                               {"valid": True}, "sch:PYRO10", [78]),
    "pyro10-follow-0": ("PYRO10", srep78("srep-0078-valid-pyro-follow", 'follow="true"', 'follow="0"'),
                        {"valid": False, "codes": ["PYRO10"]}, "sch:PYRO10", [78]),
    "pyro11-margin-plus-2": ("PYRO11", srep78("srep-0078-valid-pyro-follow", 'followMargin="2"', 'followMargin="+2"'),
                             {"valid": True}, "sch:PYRO11", [78]),
    "pyro11-margin-plus-4": ("PYRO11", srep78("srep-0078-pyro11-margin", 'followMargin="4"', 'followMargin="+4"'),
                             {"valid": False, "codes": ["PYRO11"]}, "sch:PYRO11", [78]),
}
BEFORE = {f"srep-0084-{k}": v[3] for k, v in CASES.items()}


def main():
    out = {}
    for name, (rule, xml, findings, before, requires) in CASES.items():
        expected = {"rule": f"SREP 84 {rule}",
                    "source": SOURCES.get(xml, "written by conformance/tools/srep84_cases.py"), "findings": findings}
        if requires:
            expected["requires"] = requires
        out[f"srep-0084-{name}"] = {"xml": xml, "expected": expected}
    with open(os.path.join(CONF, "srep_cases", "srep-0084.json"), "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {len(out)} cases")


if __name__ == "__main__":
    main()
