#!/usr/bin/env python3
"""Writes the SREP 83 kit cases (the version gates of SREP 40 admit later versions) to srep_cases/srep-0083.json.

Each case is an existing kit case that uses one gated feature, with nothing changed but scene/@version:
- to 1.4 and 1.5, which SREP 83's gates accept (SREP 40's refuse them): valid;
- to 1.2, which both refuse: invalid with the gate (at 1.0 and 1.1 the gates of 1.1 and 1.2, such as V5 and V6,
  would refuse these documents too). The base of MSQ1 is SREP 40's own case at 1.2, so it has no such case.
The bases are SREP 40's valid cases, one per gate, and one case of each of SREPs 77 to 80 that puts its attributes
on an SREP 40 element (those need the drafts' syntax as well; the "requires" entry names them). sr-core's schema up to
1.5.0 has no version 1.6, so no case uses it. Usage: python3 conformance/tools/srep83_cases.py; then
python3 conformance/make_cases.py.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)

# gate: (SREP, base case, what it shows)
BASES = {
    "V8": (40, "srep-0040-pyro", "a pyro volume and its medium"),
    "MSQ1": (40, "srep-0040-msq1-rejected", "a mesh sequence"),
    "P3D1": (40, "srep-0040-particles3d", "particles3D"),
    "OCN1": (40, "srep-0040-ocean", "an ocean"),
    "CRT1": (40, "srep-0040-crater", "a crater"),
    "FRX1": (40, "srep-0040-fracture", "a fracture"),
    "GEO1": (None, None, "globe elevation"),
}
# a globe with elevation: GEO1's own subject (no SREP 40 kit case has one); the tiles are an existing kit asset
GLOBE = ('<?xml version="1.0" encoding="UTF-8"?>\n'
         '<scene version="1.3"><project width="64" height="64" fps="24" duration="2"/><assets>'
         '<tiles id="dem" src="../assets/halves.pmtiles"/><map id="m" width="64" height="32" background="#FFFFFF"/>'
         '</assets><composition><object3D id="earth" primitive="globe" map="m" terrain="dem" terrainTileSize="2" '
         'terrainZoom="0" planetRadius="1000" radius="20" x="32" y="32" segments="32"/></composition></scene>\n')
# the drafts' attributes on SREP 40 elements, at a later version: (SREP, base case, gates it passes)
LATER_SYNTAX = [
    (77, "srep-0077-valid-crater-mantle", ["CRT1"]),
    (77, "srep-0077-valid-fracture-contact", ["FRX1"]),
    (77, "srep-0077-valid-ocean-density", ["OCN1"]),
    (78, "srep-0078-valid-pyro-follow", ["V8"]),
    (79, "srep-0079-valid-volume-scatter-bounces", ["V8"]),
    (80, "srep-0080-valid-voxel-crater", ["CRT1", "VOX1"]),
    (80, "srep-0080-valid-voxel-fracture", ["FRX1", "VOX1"]),
]


def load(srep):
    return json.load(open(os.path.join(CONF, "srep_cases", f"srep-{srep:04d}.json")))


def with_version(xml, version):
    out, n = re.subn(r'<scene version="[^"]*"', f'<scene version="{version}"', xml)
    assert n == 1, xml[:120]
    return out


def main():
    cases = {}
    kit = {40: load(40)}
    for gate, (srep, base, what) in BASES.items():
        xml = GLOBE if base is None else kit[srep][base]["xml"]
        source = "written by conformance/tools/srep83_cases.py" if base is None else f"kit case {base}, scene/@version changed"
        stem = gate.lower()
        for version in ("1.4", "1.5"):
            cases[f"srep-0083-{stem}-version-{version}"] = {"xml": with_version(xml, version), "expected": {
                "rule": f"SREP 83 {gate}", "source": source, "findings": {"valid": True}}}
        for version in ("1.2",) if 'version="1.2"' not in xml[:200] else ():
            cases[f"srep-0083-{stem}-rejected-version-{version}"] = {"xml": with_version(xml, version), "expected": {
                "rule": f"SREP 83 {gate}", "source": source, "findings": {"valid": False, "codes": [gate]}}}
        if base is None:   # GEO1's case at 1.3, valid under both texts
            cases[f"srep-0083-{stem}-version-1.3"] = {"xml": xml, "expected": {
                "rule": f"SREP 83 {gate}", "source": source, "findings": {"valid": True}}}
    for srep, base, gates in LATER_SYNTAX:
        kit.setdefault(srep, load(srep))
        name = base.replace(f"srep-{srep:04d}-valid-", "")
        cases[f"srep-0083-srep{srep}-{name}-version-1.5"] = {
            "xml": with_version(kit[srep][base]["xml"], "1.5"), "expected": {
                "rule": "SREP 83 " + " ".join(g for g in gates if g != "VOX1"),
                "source": f"kit case {base}, scene/@version changed",
                "requires": [srep] + ([80] if "VOX1" in gates and srep != 80 else []),
                "findings": {"valid": True}}}
    with open(os.path.join(CONF, "srep_cases", "srep-0083.json"), "w") as fh:
        json.dump(cases, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
