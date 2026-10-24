#!/usr/bin/env python3
"""Writes the SREP 87 kit cases (ids emitted by a program are scoped by the program's id): the WebAssembly modules in
srep_cases/assets/srep87-*.wasm and the cases in srep_cases/srep-0087.json. The modules return constant fragments,
and every expected value is derived from the SREP's rules and those fragments (and SREP 66's srep66-rect.wasm, whose
output is a red 40 x 20 rect `g1` centred at (200, 120)), not from any engine.
Run from anywhere: python3 conformance/tools/srep87_cases.py; then python3 conformance/make_cases.py.
With --check, the files are written to a scratch directory and compared with the committed ones."""
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wasm_min as w  # noqa: E402
import kit_pending  # noqa: E402  which cases are pending (SREP 0)
from srep66_cases import RECT, exports  # noqa: E402,F401  srep66-rect.wasm's output

CONF = os.path.dirname(HERE)

# the fragments the SREP 87 modules return (SREP 66 Semantics 5: nodeChoice elements)
FRAGMENTS = {
    # a rect m (20 x 20, its right edge at x 200) and a rect s (40 x 20 centred at (200, 120)) matted by m: s draws
    # only over m's left half of s, and m itself is hidden (DEFINITIONS D15)
    "matted": ('<shape id="m" shape="rect" width="20" height="20" anchorX="20" anchorY="10" x="200" y="120" fill="#00FF00FF"/>'
               '<shape id="s" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="200" y="120" fill="#FF0000FF" matte="m"/>'),
    # the composed collision of Semantics 2: program a emitting b.c beside program a.b emitting c (both a.b.c)
    "b-c": '<shape id="b.c" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="200" y="120" fill="#FF0000FF"/>',
    "c": '<shape id="c" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="440" y="120" fill="#0000FFFF"/>',
    # two elements with the local id g1 (Semantics 1)
    "duplicate": ('<shape id="g1" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="200" y="120" fill="#FF0000FF"/>'
                  '<shape id="g1" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="440" y="120" fill="#FF0000FF"/>'),
    # a particle emitter without a seed: the reference seeds it from its id (Semantics 7)
    "particles": ('<particleEmitter id="g1" x="320" y="180" rate="0" lifetime="2" speed="120" speedVariance="80" '
                  'spread="360" size="6" color="#FF0000FF"><burst time="0" count="40"/></particleEmitter>'),
}

SLUGS = ["reuse", "local-ref", "local-wins", "qualified-prop", "bare-prop", "bare-prop-warning", "bare-override",
         "ambiguous", "composed-collision", "duplicate-local", "seed-local", "seed-local-by-hand", "beat-program",
         "beat-program-before", "output-sha256"]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def constant(frag: str) -> bytes:
    """A module whose generate() returns `frag` (SREP 66 Semantics 2)."""
    b = frag.encode()
    return w.module(types=[([], [w.I64])], funcs=[0], exports=exports(0),
                    codes=[w.i64_const(w.packed(16, len(b))) + w.END], data=[(16, b)])


def modules():
    return {k: constant(v) for k, v in FRAGMENTS.items()}


def doc(body, params="", output='<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>', markers=""):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<scene version="1.6">\n'
            f'<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="1"/>\n'
            f'{params}{output}\n{markers}<composition>\n{body}\n</composition>\n</scene>\n')


def box(cx, cy, w_=40, h=20):
    return {"cx": cx, "cy": cy, "w": w_, "h": h}


def main(conf=CONF):
    mods = modules()
    rect = constant(RECT)          # the bytes of srep66-rect.wasm, which srep66_cases.py writes
    assets = os.path.join(conf, "srep_cases", "assets")
    os.makedirs(assets, exist_ok=True)
    for k, b in mods.items():
        open(os.path.join(assets, f"srep87-{k}.wasm"), "wb").write(b)

    def prog(pid, name, attrs=""):
        src, b = (("srep66-rect", rect) if name == "rect" else (f"srep87-{name}", mods[name]))
        return f'<program id="{pid}" src="../assets/{src}.wasm" sha256="{sha(b)}"{attrs}/>'

    def follower(expr):
        return ('<shape id="o" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="0" y="240" '
                f'fill="#0000FFFF"><expression property="x">{expr}</expression></shape>')

    cases = {}

    def add(slug, rule, xml, expected):
        cases[f"srep-0087-program-ids-{slug}"] = {"xml": xml, "expected": {"rule": f"SREP 87 ({rule})", **expected}}

    fail = lambda code: {"failure": {"code": code}}  # noqa: E731
    two = prog("a", "rect") + "\n" + prog("b", "rect", ' x="240"')
    add("reuse", "two programs running one module draw: a.g1 and b.g1, Semantics 2", doc(two),
        {"red": box(320, 120, 280, 20)})
    add("local-ref", "each output's matte=\"m\" names its own m, Semantics 3.1",
        doc(prog("a", "matted") + "\n" + prog("b", "matted", ' x="240"')),
        {"red": box(310, 120, 260, 20), "absent": ["green"]})
    add("local-wins", "the output's matte=\"m\" names p.m, not the document's m, Semantics 3.1",
        doc('<shape id="m" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="480" y="240" fill="#0000FFFF"/>\n'
            + prog("p", "matted")),
        {"red": box(190, 120, 20, 20), "blue": box(480, 240), "absent": ["green"]})
    add("qualified-prop", "prop(\"a.g1.x\") from outside follows a.g1 with no warning, Semantics 4",
        doc(prog("a", "rect") + "\n" + follower('prop("a.g1.x")')), {"red": box(200, 120), "blue": box(200, 240)})
    add("bare-prop", "prop(\"g1.x\") from outside with one emitter follows a.g1, Semantics 4",
        doc(prog("a", "rect") + "\n" + follower('prop("g1.x")')), {"red": box(200, 120), "blue": box(200, 240)})
    add("bare-prop-warning", "the same bare reference warns W13, Semantics 4",
        doc(prog("a", "rect") + "\n" + follower('prop("g1.x")')), {"findings": {"via": "render", "messages": ["W13"]}})
    add("bare-override", "a variant's override target=\"g1\" with one emitter applies to a.g1, Semantics 4",
        doc(prog("a", "rect"),
            params='<parameters><variant id="v"><override target="g1" property="x" value="440"/></variant></parameters>\n',
            output='<output id="still" path="out/frame_%04d.png" codec="png-sequence" variant="v"/>'),
        {"output": {"id": "still", "time": 0}, "red": box(440, 120)})
    add("ambiguous", "prop(\"g1.x\") from outside with emitters a and b fails PRG17, Semantics 4",
        doc(two + "\n" + follower('prop("g1.x")')), fail("PRG17"))
    add("composed-collision", "a emitting b.c beside a.b emitting c: both a.b.c, PRG14, Semantics 2",
        doc(prog("a", "b-c") + "\n" + prog("a.b", "c")), fail("PRG14"))
    add("duplicate-local", "an output with two elements g1 fails PRG14, Semantics 1",
        doc(prog("p", "duplicate")), fail("PRG14"))
    at_half = {"output": {"id": "still", "time": 0.5}}
    add("seed-local", "an emitted emitter without a seed draws as srep-0087-program-ids-seed-local-by-hand, its id "
                      "written by hand as g1: seeds use the local id, Semantics 7",
        doc(prog("a", "particles")),
        {**at_half, "compare": {"case": "srep-0087-program-ids-seed-local-by-hand", "tolerance": 0}})
    add("seed-local-by-hand", "the reference picture of srep-0087-program-ids-seed-local: the same emitter written by "
                              "hand in a group a, with the id g1",
        doc(f'<group id="a">{FRAGMENTS["particles"]}</group>'),
        {**at_half, "compare": {"case": "srep-0087-program-ids-seed-local", "tolerance": 0}})
    grid = '<markers><beatGrid bpm="120" offset="0"/></markers>\n'
    # n starts at the marker beat.1 and takes its x from the emitted node by its namespaced id beat.g1 (Semantics 4),
    # so the case needs both readings: beat.1 as the grid's generated id and beat.g1 as an element id. Without SREP 87
    # the emitted id is g1, beat.g1 names nothing and the document fails to build.
    late = ('<shape id="n" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="480" y="240" '
            'fill="#0000FFFF" startMarker="beat.1"><expression property="x">prop("beat.g1.x")</expression></shape>')
    # beat.1 is at offset + 60/bpm = 0.5 s (SREP 57); the program beat emits g1, whose id is beat.g1 (x 200)
    add("beat-program", "a program with the id beat beside a beatGrid: beat.1 is still the grid's beat at 0.5 s, and "
                        "prop(\"beat.g1.x\") names the emitted node, Hazards",
        doc(prog("beat", "rect") + "\n" + late, markers=grid),
        {"output": {"id": "still", "time": 0.75}, "red": box(200, 120), "blue": box(200, 240)})
    add("beat-program-before", "the same document before beat.1, Hazards",
        doc(prog("beat", "rect") + "\n" + late, markers=grid),
        {"output": {"id": "still", "time": 0.25}, "red": box(200, 120), "absent": ["blue"]})
    pin = f' outputSha256="{sha(RECT.encode())}"'
    add("output-sha256", "outputSha256 of srep66-rect.wasm's output holds for programs a and b, Semantics 6",
        doc(prog("a", "rect", pin) + "\n" + prog("b", "rect", ' x="240"' + pin)), {"red": box(320, 120, 280, 20)})

    assert [n.removeprefix("srep-0087-program-ids-") for n in cases] == SLUGS
    kit_pending.settle(cases, 87)
    with open(os.path.join(conf, "srep_cases", "srep-0087.json"), "w") as f:
        json.dump(cases, f, indent=1, ensure_ascii=False)
    return cases, mods


if __name__ == "__main__":
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "srep_cases"))
            main(tmp)
            for rel in ["srep_cases/srep-0087.json"] + [f"srep_cases/assets/srep87-{k}.wasm" for k in FRAGMENTS]:
                a, b = (open(os.path.join(d, rel), "rb").read() for d in (tmp, CONF))
                assert a == b, f"{rel} differs from what the generator writes"
        print("srep87_cases: the committed files are what the generator writes")
    else:
        cases, mods = main()
        print(f"wrote {len(cases)} cases, {len(mods)} modules")
