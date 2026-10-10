#!/usr/bin/env python3
"""Writes the SREP 85 kit cases (decimal and double attributes are tested by value) to srep_cases/srep-0085.json.

Each case writes one or two attributes that a changed rule reads as a number with a leading "+": the forms "+1" and
"+0.5" (for the integer attributes of ITR1, "+1" and "+20"), which XPath 1.0's number() reads as NaN. A case's
findings are the verdict with SREP 85; BEFORE gives its verdict under the text before SREP 85 (with SREP 84), which
tests/test_srep_0085.py checks too. Where a NaN made the rule pass (C37, C38, C53, PYRO4, OCN3's wavelength, OCN5), a
case writes a value that the rule refuses, so that its verdict changes; elsewhere the case with the value the rule
accepts changes.

One case, srep-0085-c15-speed-exponent, writes speed="1e0", which a strict XPath 1.0 number() does not read and the
native validator of SREP 85 does (its Semantics, 4): its entry has "native_only". libxml2, which the kit's tests use,
reads exponents, so the tests check it like the others.

The cases of SREP 78 (PYRO11, PYC6) and SREP 80 (FRX11) are those SREPs' kit cases with one attribute rewritten, and
need their syntax ("requires"). The cases of ITR1 and SRT1 are documents of SREP 67's syntax (version 1.6); they need
it ("requires": [67]). Usage: python3 conformance/tools/srep85_cases.py; then python3 conformance/make_cases.py.
"""
import json
import os
import kit_pending  # which cases are pending (SREP 0)

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)

HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<scene version="{v}"><project width="64" height="64" fps="24" duration="{d}"/>'
TILE = '<assets><image id="img" src="../assets/tile.png" width="16" height="16"/></assets>'
RECT = '<shape id="s" shape="rect" width="10" height="10" fill="#FFFFFF"/>'


def doc(body, version="1.2", head="", tail="", duration="1"):
    return HEAD.format(v=version, d=duration) + head + f"<composition>{body}</composition>{tail}</scene>\n"


def text(attrs):
    return doc('<layer id="l" asset="t"/>',
               head=f'<assets><text id="t" text="Hi" width="60" height="30" {attrs}/></assets>')


def c15(attrs):
    return doc(f'<layer id="l" asset="img" {attrs}><timeRemap><key time="0" value="0"/><key time="1" value="0.5"/>'
               '</timeRemap></layer>', head=TILE)


def c37(offsets):
    stops = "".join(f'<stop offset="{o}" color="#{c}"/>' for o, c in zip(offsets, ("FF0000", "00FF00", "0000FF")))
    return doc('<shape id="s" shape="rect" width="10" height="10" fill="url(#g)"/>',
               head=f'<paints><linearGradient id="g">{stops}</linearGradient></paints>')


def c38(times):
    keys = "".join(f'<key time="{t}" value="{v}"/>' for t, v in zip(times, ("0", "0.5", "1")))
    return doc(f'<shape id="s" shape="rect" width="10" height="10" fill="#FFFFFF"><animate property="opacity">{keys}'
               '</animate></shape>')


def output(attrs, inner=""):
    out = f'<output id="o" path="out/frame_%04d.png" codec="png-sequence" {attrs}>{inner}</output>'
    return doc(RECT, head=out)


def c52(attrs):
    return doc(f'<fluid id="f" width="10" height="10"><fluidSource {attrs}/></fluid>', version="1.1")


def c53(domain):
    return doc('<layer id="l" asset="m"/>', version="1.1",
               head='<assets><geo id="g" src="../assets/squares.geojson"/><map id="m" width="64" height="32">'
                    f'<geoLayer geo="g" fillBy="id" domain="{domain}"/></map></assets>')


def c56(segment, duration="1"):
    return doc(RECT, duration=duration,
               head=f'<output id="o" path="out/frame_%04d.png" codec="png-sequence"><segment {segment}/></output>')


PYRO = ('<object3D id="cloud" primitive="volume"><pyro width="8" height="8" depth="8" voxelSize="1" dt="0.1">'
        '<pyroSource shape="sphere" radius="2" densityRate="2" start="0.15" end="0.35"/></pyro>'
        '<medium blackbody="true" emissionScale="0.1"/></object3D>')


def pyro(old, new):
    assert PYRO.count(old) == 1, old
    return doc(PYRO.replace(old, new), version="1.3")


def vol4(old, new):
    head = ('<assets><volume id="smoke" src="../assets/srep79-uniform.srvol" boundsMinX="0" boundsMinY="0" '
            'boundsMinZ="0" boundsMaxX="32" boundsMaxY="32" boundsMaxZ="2"/></assets>')
    for o, n in zip(old, new):
        assert head.count(o) == 1, o
        head = head.replace(o, n)
    return doc('<object3D id="cloud" primitive="volume" volume="smoke"><medium emissionScale="0.1"/></object3D>',
               version="1.3", head=head)


def p3d3(attrs="", burst='time="0"'):
    return doc('<particles3D id="dust" rate="0" speed="5" spread="120" gravityY="8" lifetime="2" '
               f'{attrs}><burst {burst} count="12"/></particles3D>', version="1.3", duration="2")


def p3d10(angles):
    return doc('<object3D id="ball" primitive="sphere" radius="1" y="-10"><rigidBody mass="1" velocityY="20"/>'
               '</object3D><object3D id="ground" primitive="plane" width="40" height="40" segments="8" y="2" '
               'rotationX="-90"><crater id="pit" source="ball" targetMaterial="softRock"/></object3D>'
               f'<particles3D id="debris" rate="0" lifetime="1"><burst crater="pit" count="12" {angles}/></particles3D>',
               version="1.3", duration="2", tail='<physics pixelsPerMeter="1"/>')


OCEAN = ('<ocean id="sea" width="8" depth="8" cellSize="0.5" bottomDepth="2"><waterImpulse time="0.3" radius="2" '
         'amplitude="0.1"/><wave wavelength="4" amplitude="0.1" phase="0"/>'
         '<whitewater emissionRate="2" threshold="0.3"/></ocean>')


def ocean(old, new):
    assert OCEAN.count(old) == 1, old
    return doc(OCEAN.replace(old, new), version="1.3", duration="2")


SOURCES = {}


def kit(srep, case, old, new):
    xml = json.load(open(os.path.join(CONF, "srep_cases", f"srep-{srep:04d}.json")))[case]["xml"]
    for o, n in zip(old, new):
        assert xml.count(o) == 1, (case, o)
        xml = xml.replace(o, n)
    SOURCES[xml] = (f"kit case {case} (SREP {srep}) with " + ", ".join(f"{o} written {n}" for o, n in zip(old, new))
                    + ", by conformance/tools/srep85_cases.py")
    return xml


# SREP 67 (version 1.6): an iterate around a plain shape, and a segmented-sort effect (its kit case
# srep-0067-segmented-sort-ascending, with low and high)
def itr1(attrs):
    return (HEAD.format(v="1.6", d="1") + f'<composition><iterate id="it" {attrs}>{RECT}</iterate></composition>'
            '</scene>\n')


def srt1(attrs):
    return (HEAD.format(v="1.6", d="1") + f'<composition><group id="g" effects="ps">{RECT}</group></composition>'
            f'<effects><effect id="ps" type="segmented-sort" direction="horizontal" order="ascending" {attrs}/>'
            '</effects></scene>\n')


OK = {"valid": True}


def bad(*codes):
    return {"valid": False, "codes": list(codes)}


# name: (rule, document, findings with SREP 85, verdict before SREP 85, requires)
CASES = {
    # C13, C14 (assets/text: minSize, maxSize positiveDecimal; letterSpacing, size restrictions of xs:double)
    "c13-min-size-plus-0.5": ("C13", text('size="10" minSize="+0.5" maxSize="1"'), OK, "sch:C13", None),
    "c13-max-size-plus-1": ("C13", text('size="10" minSize="0.5" maxSize="+1"'), OK, "sch:C13", None),
    "c13-min-size-plus-1-above-max": ("C13", text('size="10" minSize="+1" maxSize="0.5"'), bad("C13"), "sch:C13", None),
    "c14-size-plus-1": ("C14", text('size="+1" letterSpacing="2"'), OK, "sch:C14", None),
    "c14-letter-spacing-plus-0.5": ("C14", text('size="10" letterSpacing="+0.5"'), OK, "sch:C14", None),
    "c14-letter-spacing-plus-5-size-plus-1": ("C14", text('size="+1" letterSpacing="+5"'), bad("C14"), "sch:C14", None),
    # C15 (layer/@speed, xs:double, beside a timeRemap)
    "c15-speed-plus-1": ("C15", c15('speed="+1"'), OK, "sch:C15", None),
    "c15-speed-plus-0.5": ("C15", c15('speed="+0.5"'), bad("C15"), "sch:C15", None),
    "c15-speed-exponent": ("C15", c15('speed="1e0"'), OK, "ok", None),
    # C37 (stop/@offset, unitDecimal), C38 (key/@time, xs:double): a NaN made the order test pass
    "c37-offsets-plus-0.5-plus-1": ("C37", c37(("0", "+0.5", "+1")), OK, "ok", None),
    "c37-offsets-plus-1-then-plus-0.5": ("C37", c37(("0", "+1", "+0.5")), bad("C37"), "ok", None),
    "c38-times-plus-0.5-plus-1": ("C38", c38(("0", "+0.5", "+1")), OK, "ok", None),
    "c38-times-plus-1-then-plus-0.5": ("C38", c38(("0", "+1", "+0.5")), bad("C38"), "ok", None),
    # C44, C54 (output/@start, output/@end, xs:double)
    "c44-end-plus-1": ("C44", output('end="+1"'), OK, "sch:C44", None),
    "c44-start-plus-0.5": ("C44", output('start="+0.5" end="1"'), OK, "sch:C44", None),
    "c44-end-plus-0.5-before-start-plus-1": ("C44", output('start="+1" end="+0.5"'), bad("C44"), "sch:C44", None),
    "c54-start-plus-0": ("C54", output('start="+0"', '<segment from="0" to="1"/>'), OK, "sch:C54", None),
    "c54-start-plus-0.5": ("C54", output('start="+0.5"', '<segment from="0" to="1"/>'), bad("C54"), "sch:C54", None),
    "c54-start-plus-1": ("C54", output('start="+1"', '<segment from="0" to="1"/>'), bad("C54"), "sch:C54", None),
    # C52 (fluidSource/@start, @end, xs:double)
    "c52-end-plus-1": ("C52", c52('start="0.5" end="+1"'), OK, "sch:C52", None),
    "c52-start-plus-0.5": ("C52", c52('start="+0.5" end="1"'), OK, "sch:C52", None),
    "c52-end-plus-0.5-before-start-plus-1": ("C52", c52('start="+1" end="+0.5"'), bad("C52"), "sch:C52", None),
    # C53 (geoLayer/@domain, a list of xs:double): a NaN made the order test pass
    "c53-domain-plus-0.5-plus-1": ("C53", c53("0 +0.5 +1"), OK, "ok", None),
    "c53-domain-plus-1-then-plus-0.5": ("C53", c53("0 +1 +0.5"), bad("C53"), "ok", None),
    # C56 (segment/@from, @to, xs:double; project/@duration, durationType)
    "c56-to-plus-1": ("C56", c56('from="0" to="+1"'), OK, "sch:C56", None),
    "c56-from-plus-0.5": ("C56", c56('from="+0.5" to="1"'), OK, "sch:C56", None),
    "c56-duration-plus-1": ("C56", c56('from="0" to="1"', duration="+1"), OK, "sch:C56", None),
    "c56-to-plus-1-after-duration-0.5": ("C56", c56('from="0" to="+1"', duration="0.5"), bad("C56"), "sch:C56", None),
    # PYRO1 (pyro/@width, @height, @depth, @voxelSize, positiveDecimal, read by the lets nx, ny, nz)
    "pyro1-voxel-size-plus-1": ("PYRO1", pyro('voxelSize="1"', 'voxelSize="+1"'), OK, "sch:PYRO1", None),
    "pyro1-voxel-size-plus-0.5": ("PYRO1", pyro('voxelSize="1"', 'voxelSize="+0.5"'), OK, "sch:PYRO1", None),
    "pyro1-width-plus-8.5": ("PYRO1", pyro('width="8"', 'width="+8.5"'), bad("PYRO1"), "sch:PYRO1", None),
    # PYRO2, PYRO4 (pyroSource/@start, @end, @scaleX, @scaleY, @scaleZ, xs:double)
    "pyro2-end-plus-1": ("PYRO2", pyro('end="0.35"', 'end="+1"'), OK, "sch:PYRO2", None),
    "pyro2-start-plus-0.5": ("PYRO2", pyro('start="0.15" end="0.35"', 'start="+0.5" end="1"'), OK, "sch:PYRO2", None),
    "pyro2-end-plus-0.5-before-start-plus-1": ("PYRO2", pyro('start="0.15" end="0.35"', 'start="+1" end="+0.5"'),
                                               bad("PYRO2"), "sch:PYRO2", None),
    "pyro4-scale-x-plus-1": ("PYRO4", pyro('radius="2"', 'radius="2" scaleX="+1"'), OK, "ok", None),
    "pyro4-scale-y-plus-0.5": ("PYRO4", pyro('radius="2"', 'radius="2" scaleY="+0.5"'), OK, "ok", None),
    "pyro4-scale-z-plus-0": ("PYRO4", pyro('radius="2"', 'radius="2" scaleZ="+0"'), bad("PYRO4"), "ok", None),
    # VOL4 (volume/@boundsMinX ... @boundsMaxZ, xs:double)
    "vol4-bounds-max-z-plus-1": ("VOL4", vol4(['boundsMaxZ="2"'], ['boundsMaxZ="+1"']), OK, "sch:VOL4", None),
    "vol4-bounds-min-z-plus-0.5": ("VOL4", vol4(['boundsMinZ="0"'], ['boundsMinZ="+0.5"']), OK, "sch:VOL4", None),
    "vol4-bounds-min-z-plus-1-above-max-plus-0.5": ("VOL4", vol4(['boundsMinZ="0"', 'boundsMaxZ="2"'],
                                                             ['boundsMinZ="+1"', 'boundsMaxZ="+0.5"']),
                                                    bad("VOL4"), "sch:VOL4", None),
    # P3D3 (particles3D: lifetime, lifetimeVariance, speed, speedVariance (decimals), burst/@time (xs:double))
    "p3d3-lifetime-plus-1": ("P3D3", p3d3('lifetime="+1"').replace(' lifetime="2" ', ' '), OK, "sch:P3D3", None),
    "p3d3-speed-variance-plus-0.5": ("P3D3", p3d3('speedVariance="+0.5"'), OK, "sch:P3D3", None),
    "p3d3-burst-time-plus-0.5": ("P3D3", p3d3(burst='time="+0.5"'), OK, "sch:P3D3", None),
    "p3d3-lifetime-variance-plus-1-lifetime-plus-0.5": ("P3D3", p3d3('lifetime="+0.5" lifetimeVariance="+1"')
                                                        .replace(' lifetime="2" ', ' '), bad("P3D3"), "sch:P3D3", None),
    # P3D10 (burst/@angle, @angleSpread, decimals, read by the lets angle and spread)
    "p3d10-angle-plus-1-spread-plus-0.5": ("P3D10", p3d10('angle="+1" angleSpread="+0.5"'), OK, "sch:P3D10", None),
    "p3d10-angle-plus-0.5-spread-plus-1": ("P3D10", p3d10('angle="+0.5" angleSpread="+1"'), bad("P3D10"),
                                           "sch:P3D10", None),
    # OCN3 (ocean/@cellSize (let cell), waterImpulse/@x (finite), wave/@wavelength), OCN5 (whitewater/@start, @end)
    "ocn3-cell-size-plus-0.5": ("OCN3", ocean('cellSize="0.5"', 'cellSize="+0.5"'), OK, "sch:OCN3", None),
    "ocn3-impulse-x-plus-1": ("OCN3", ocean('radius="2"', 'radius="2" x="+1"'), OK, "sch:OCN3", None),
    "ocn3-wavelength-plus-0.5": ("OCN3", ocean('wavelength="4"', 'wavelength="+0.5"'), bad("OCN3"), "ok", None),
    "ocn5-whitewater-plus-0.5-to-plus-1": ("OCN5", ocean('threshold="0.3"', 'threshold="0.3" start="+0.5" end="+1"'),
                                           OK, "ok", None),
    "ocn5-whitewater-end-plus-0.5-before-start-plus-1": ("OCN5", ocean('threshold="0.3"',
                                                                       'threshold="0.3" start="+1" end="+0.5"'),
                                                         bad("OCN5"), "ok", None),
    # PYRO11 (SREP 78: pyro/@voxelSize, @width, @height, @depth; the 1.5.0 lets of PYRO1 read voxelSize too)
    "pyro11-voxel-size-plus-1": ("PYRO11", kit(78, "srep-0078-valid-pyro-follow", ['voxelSize="1"'], ['voxelSize="+1"']),
                                 OK, "sch:PYRO1,PYRO11", [78]),
    "pyro11-voxel-size-plus-0.5": ("PYRO11", kit(78, "srep-0078-valid-pyro-follow", ['voxelSize="1"'],
                                                 ['voxelSize="+0.5"']), OK, "sch:PYRO1,PYRO11", [78]),
    # PYC6 (SREP 78: pyroBlast/@x, @y, xs:double, against the pyro's width and height)
    "pyc6-x-plus-1": ("PYC6", kit(78, "srep-0078-valid-pyro-blast", ['x="1"'], ['x="+1"']), OK, "sch:PYC6", [78]),
    "pyc6-y-plus-0.5": ("PYC6", kit(78, "srep-0078-valid-pyro-blast", ['y="-1"'], ['y="+0.5"']), OK, "sch:PYC6", [78]),
    "pyc6-x-plus-5": ("PYC6", kit(78, "srep-0078-valid-pyro-blast", ['x="1"'], ['x="+5"']), bad("PYC6"), "sch:PYC6", [78]),
    # FRX11 (SREP 80: fracture/@planes, four numbers per plane)
    "frx11-planes-plus-1": ("FRX11", kit(80, "srep-0080-valid-voxel-fracture-planes", ['planes="1 0 0 2 0 1 0 0.5"'],
                                         ['planes="+1 0 0 2 0 +1 0 0.5"']), OK, "sch:FRX11", [80]),
    "frx11-planes-plus-0.5": ("FRX11", kit(80, "srep-0080-valid-voxel-fracture-planes", ['planes="1 0 0 2 0 1 0 0.5"'],
                                           ['planes="1 0 0 2 0 1 0 +0.5"']), OK, "sch:FRX11", [80]),
    "frx11-planes-plus-0-normal": ("FRX11", kit(80, "srep-0080-valid-voxel-fracture-planes",
                                                ['planes="1 0 0 2 0 1 0 0.5"'], ['planes="1 0 0 2 +0 +0 +0 0.5"']),
                                   bad("FRX11"), "sch:FRX11", [80]),
    # ITR1 (SREP 67: iterate/@checkEvery, @steps, xs:positiveInteger)
    "itr1-check-every-plus-1": ("ITR1", itr1('steps="10" checkEvery="+1"'), OK, "sch:ITR1", [67]),
    "itr1-steps-plus-20": ("ITR1", itr1('steps="+20" checkEvery="20"'), OK, "sch:ITR1", [67]),
    "itr1-check-every-plus-20-above-steps": ("ITR1", itr1('steps="10" checkEvery="+20"'), bad("ITR1"), "sch:ITR1", [67]),
    # SRT1 (SREP 67: effect/@low, @high, unitDecimal)
    "srt1-low-plus-0.5": ("SRT1", srt1('low="+0.5" high="1"'), OK, "sch:SRT1", [67]),
    "srt1-high-plus-1": ("SRT1", srt1('low="0.5" high="+1"'), OK, "sch:SRT1", [67]),
    "srt1-low-plus-1-above-high-plus-0.5": ("SRT1", srt1('low="+1" high="+0.5"'), bad("SRT1"), "sch:SRT1", [67]),
}
NATIVE_ONLY = {"c15-speed-exponent": "speed is written 1e0, which a strict XPath 1.0 number() reads as NaN; the native "
                                     "validator is normative for it (SREP 85, Semantics 4)"}
BEFORE = {f"srep-0085-{k}": v[3] for k, v in CASES.items()}


def main():
    out = {}
    for name, (rule, xml, findings, before, requires) in CASES.items():
        expected = {"rule": f"SREP 85 {rule}",
                    "source": SOURCES.get(xml, "written by conformance/tools/srep85_cases.py"), "findings": findings}
        if requires:
            expected["requires"] = requires
        if name in NATIVE_ONLY:
            expected["native_only"] = NATIVE_ONLY[name]
        out[f"srep-0085-{name}"] = {"xml": xml, "expected": expected}
    kit_pending.settle(out, 85)
    with open(os.path.join(CONF, "srep_cases", "srep-0085.json"), "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {len(out)} cases")


if __name__ == "__main__":
    main()
