#!/usr/bin/env python3
"""Writes the SREP 66 (<program>) kit cases: the WebAssembly modules in srep_cases/assets/srep66-*.wasm and the cases
in srep_cases/srep-0066.json. Every expected value is derived from the SREP text (the module's output, the SplitMix64
seeding of Semantics 4, the canonical NaN of Determinism 1, the memory limit of Determinism 3), not from any engine.
Run from anywhere: python3 conformance/tools/srep66_cases.py; then python3 conformance/make_cases.py."""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wasm_min as w  # noqa: E402

CONF = os.path.dirname(HERE)
ASSETS = os.path.join(CONF, "srep_cases", "assets")
PENDING = "SREP 66 is a draft; no engine implements <program> yet. The entry keeps the values derived from the SREP"
FAILED = PENDING + "; the expected result is a failed render with the error code in 'failure', which expected.json and run.py cannot express yet"

RED = '<shape id="g1" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="480" y="180" fill="#FF0000FF"/>'
BLUE = '<shape id="g1" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="160" y="180" fill="#0000FFFF"/>'
RECT = '<shape id="g1" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="200" y="120" fill="#FF0000FF"/>'


def exports(nimports):
    return [("memory", 2, 0), ("generate", 0, nimports)]


def choose(test: bytes, frags=(RED, BLUE), base=64):
    """A generate() body: run `test` (leaves an i32), return the first fragment when it is non-zero, else the second."""
    a, b = (f.encode() for f in frags)
    data = [(base, a), (base + 256, b)]
    body = test + w.if_(w.I64) + w.i64_const(w.packed(base, len(a))) + w.ELSE + \
        w.i64_const(w.packed(base + 256, len(b))) + w.END + w.END
    return body, data


def modules():
    m = {}
    # 1. a constant fragment
    rect = RECT.encode()
    m["rect"] = w.module(types=[([], [w.I64])], funcs=[0], exports=exports(0),
                         codes=[w.i64_const(w.packed(16, len(rect))) + w.END], data=[(16, rect)])
    # 2. the first sr.rand_u64 value: even gives the red fragment, odd the blue one
    body, data = choose(w.call(0) + w.i64_const(1) + w.I64_AND + w.I64_EQZ)
    m["seed"] = w.module(types=[([], [w.I64])], imports=[("sr", "rand_u64", 0)], funcs=[0], exports=exports(1),
                         codes=[body], data=data)
    # 3. parameter "side" (default 0): above 0.5 gives red
    body, data = choose(w.i32_const(0) + w.i32_const(4) + w.f64_const(0.0) + w.call(0) + w.f64_const(0.5) + w.F64_GT)
    m["param"] = w.module(types=[([w.I32, w.I32, w.F64], [w.F64]), ([], [w.I64])], imports=[("sr", "param_f64", 0)],
                          funcs=[1], exports=exports(1), codes=[body], data=[(0, b"side")] + data)
    # 4. z / z with z = 0 read from a parameter: red when the NaN's bits are the positive canonical NaN
    z = w.i32_const(0) + w.i32_const(1) + w.f64_const(1.0) + w.call(0)
    body, data = choose(z + z + w.F64_DIV + w.I64_REINTERPRET_F64 + w.i64_const(0x7FF8000000000000) + w.I64_EQ)
    m["nan"] = w.module(types=[([w.I32, w.I32, w.F64], [w.F64]), ([], [w.I64])], imports=[("sr", "param_f64", 0)],
                        funcs=[1], exports=exports(1), codes=[body], data=[(0, b"z")] + data)
    # 5. memory.grow by 1100 pages (68.75 MiB): red when it fails (returns -1)
    body, data = choose(w.i32_const(1100) + w.MEMORY_GROW + w.i32_const(-1) + w.I32_EQ)
    m["grow"] = w.module(types=[([], [w.I64])], funcs=[0], exports=exports(0), codes=[body], data=data)
    # 6. an endless loop: fuel runs out
    m["loop"] = w.module(types=[([], [w.I64])], funcs=[0], exports=exports(0),
                         codes=[w.loop_empty() + w.br(0) + w.END + w.UNREACHABLE + w.END])
    # 7. an import outside the set of Determinism 5
    m["wasi"] = w.module(types=[([w.I32] * 4, [w.I32]), ([], [w.I64])],
                         imports=[("wasi_snapshot_preview1", "fd_write", 0)], funcs=[1], exports=exports(1),
                         codes=[w.i64_const(w.packed(16, len(rect))) + w.END], data=[(16, rect)])
    # 8. a shared memory (the threads proposal)
    m["shared"] = w.module(types=[([], [w.I64])], funcs=[0], memory=(1, 1, True), exports=exports(0),
                           codes=[w.i64_const(w.packed(16, len(rect))) + w.END], data=[(16, rect)])
    # 9. a relaxed SIMD instruction (i8x16.relaxed_swizzle, opcode 0xFD 0x100)
    v = b"\xFD\x0C" + bytes(16)
    m["relaxed"] = w.module(types=[([], [w.I64])], funcs=[0], exports=exports(0),
                            codes=[v + v + b"\xFD" + w.uleb(0x100) + w.DROP + w.i64_const(w.packed(16, len(rect))) + w.END],
                            data=[(16, rect)])
    # 10. output that fails the schema
    bad = b'<shape id="g1" shape="hexagon"/>'
    m["bad-output"] = w.module(types=[([], [w.I64])], funcs=[0], exports=exports(0),
                               codes=[w.i64_const(w.packed(16, len(bad))) + w.END], data=[(16, bad)])
    # 11. data output: two rows
    rows = b'[{"a":1},{"a":2}]'
    m["rows"] = w.module(types=[([], [w.I64])], funcs=[0], exports=exports(0),
                         codes=[w.i64_const(w.packed(16, len(rows))) + w.END], data=[(16, rows)])
    return m


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def doc(body, version="1.6", seed=1, params=""):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<scene version="{version}">\n'
            f'<project width="640" height="360" fps="24" duration="1" background="#000000FF" seed="{seed}"/>\n'
            f'{params}<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'<composition>\n{body}\n</composition>\n</scene>\n')


def prog(name, mods, attrs="", inner=""):
    return (f'<program id="p" src="../assets/srep66-{name}.wasm" sha256="{sha(mods[name])}"{attrs}>{inner}</program>')


def box(cx, cy, w_=40, h=20):
    return {"cx": cx, "cy": cy, "w": w_, "h": h}


def main():
    mods = modules()
    os.makedirs(ASSETS, exist_ok=True)
    for k, b in mods.items():
        open(os.path.join(ASSETS, f"srep66-{k}.wasm"), "wb").write(b)
    cases = {}

    def add(slug, xml, expected):
        cases[f"srep-0066-{slug}"] = {"xml": xml, "expected": {"rule": "SREP 66", **expected, "pending": expected.get("pending", PENDING)}}

    red_right = {"red": box(480, 180), "absent": ["blue"]}
    blue_left = {"blue": box(160, 180), "absent": ["red"]}
    add("program-nodes", doc(prog("rect", mods)), {"red": box(200, 120)})
    add("program-group-transform", doc(prog("rect", mods, ' x="100" y="40"')), {"red": box(300, 160)})
    # seeds: project seed 1; program seeds chosen so that the first value is even for one and odd for the other
    parity = {}
    for s in range(1, 50):
        parity.setdefault(next(w.program_rng(1, s)) & 1, s)
    even, odd = parity[0], parity[1]
    add("program-seed-even", doc(prog("seed", mods, f' seed="{even}"')), red_right)
    add("program-seed-odd", doc(prog("seed", mods, f' seed="{odd}"')), blue_left)
    add("program-param", doc(prog("param", mods, "", '<param name="side" value="1"/>')), red_right)
    add("program-param-default", doc(prog("param", mods)), blue_left)
    add("program-nan-canonical", doc(prog("nan", mods, "", '<param name="z" value="0"/>')), red_right)
    add("program-memory-limit", doc(prog("grow", mods)), red_right)
    add("program-memory-limit-raised", doc(prog("grow", mods, ' memoryLimit="128"')), blue_left)
    add("program-data-rows", doc('<repeat id="rep" over="rows" offsetX="320">'
                                 '<shape id="c" shape="rect" width="40" height="20" anchorX="20" anchorY="10" x="160" y="180" fill="#FF0000FF"/>'
                                 '</repeat>',
                                 params=f'<parameters><program id="rows" src="../assets/srep66-rows.wasm" sha256="{sha(mods["rows"])}"/></parameters>\n'),
        {"red": {"cx": 320, "cy": 180, "w": 360, "h": 20}})
    fail = lambda code: {"failure": {"code": code}, "pending": FAILED}  # noqa: E731
    add("program-fuel", doc(prog("loop", mods, ' fuel="1000000"')), fail("PRG12"))
    add("program-import-forbidden", doc(prog("wasi", mods)), fail("PRG11"))
    add("program-threads-forbidden", doc(prog("shared", mods)), fail("PRG11"))
    add("program-relaxed-simd-forbidden", doc(prog("relaxed", mods)), fail("PRG11"))
    add("program-output-invalid", doc(prog("bad-output", mods)), fail("PRG14"))
    add("program-id-collision", doc(prog("rect", mods) + "\n" +
                                    '<shape id="g1" shape="rect" width="10" height="10" fill="#00FF00FF"/>'), fail("PRG14"))
    add("program-sha256-mismatch", doc(prog("rect", mods).replace(sha(mods["rect"]), "0" * 64)), fail("PRG10"))
    add("program-output-sha256", doc(prog("rect", mods, f' outputSha256="{sha(RECT.encode())}"')), {"red": box(200, 120)})
    add("program-output-sha256-mismatch", doc(prog("rect", mods, f' outputSha256="{"1" * 64}"')), fail("PRG15"))
    # validation (Schematron): the version gate and duplicate parameter names
    add("program-version-gate", doc(prog("rect", mods), version="1.5"),
        {"findings": {"valid": False, "codes": ["V12"]}})
    add("program-param-unique", doc(prog("param", mods, "", '<param name="side" value="1"/><param name="side" value="0"/>')),
        {"findings": {"valid": False, "codes": ["PRG1"]}})
    add("program-over-names-data", doc('<repeat id="rep" over="p2" offsetX="320"><shape id="c" shape="rect" width="4" height="4" fill="#FF0000FF"/></repeat>\n'
                                       + prog("rect", mods).replace('id="p"', 'id="p2"')),
        {"findings": {"valid": False, "codes": ["PRG2"]}})
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0066.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases, {len(mods)} modules; even seed {even}, odd seed {odd}")


if __name__ == "__main__":
    main()
