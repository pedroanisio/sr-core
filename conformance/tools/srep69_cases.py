#!/usr/bin/env python3
"""Writes the SREP 69 (<program mode="step">) kit cases: the modules srep_cases/assets/srep69-*.wasm and the cases in
srep_cases/srep-0069.json. Each module draws a 100 x 100 RGBA picture: red or blue by a test on its state. The
expected colour follows from SREP 69 (the step count of SREP 68, Semantics 1; the generator of SREP 66, Semantics 4
continuing across steps), not from an engine. Usage: python3 conformance/tools/srep69_cases.py; then make_cases.py."""
import functools
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wasm_min as w  # noqa: E402

CONF = os.path.dirname(HERE)
PENDING = "SREP 69 is a draft; no engine implements <program mode=\"step\"> yet. The entry keeps the values derived from the SREP"
FAILED = PENDING + "; the expected result is a failed render with the error code in 'failure', which expected.json and run.py cannot express yet"
RED, BLUE = 0xFF0000FF - (1 << 32), 0xFFFF0000 - (1 << 32)   # RGBA bytes FF 00 00 FF and 00 00 FF FF, little-endian
BASE, SIZE = 1024, 100 * 100 * 4


def frame_body(test: bytes) -> tuple:
    """frame(): fill the picture with red when `test` (an i32) is non-zero, else blue; return (BASE << 32) | SIZE."""
    body = (test + w.if_(w.I32) + w.i32_const(RED) + w.ELSE + w.i32_const(BLUE) + w.END + w.local_set(1) +
            w.loop_empty() + w.local_get(0) + w.local_get(1) + w.i32_store(BASE) +
            w.local_get(0) + w.i32_const(4) + w.I32_ADD + w.local_tee(0) + w.i32_const(SIZE) + w.I32_LT_U + w.br_if(0) +
            w.END + w.i64_const(w.packed(BASE, SIZE)) + w.END)
    return ([(2, w.I32)], body)


T_VOID, T_STEP, T_FRAME = ([], []), ([w.I64], []), ([], [w.I64])


def modules():
    m = {}
    # counter: global 0 counts steps; red once count >= param "target" - 0.5
    count_test = w.global_get(0) + w.F64_CONVERT_I64_S + w.i32_const(0) + w.i32_const(6) + w.f64_const(1.0) + w.call(0) + \
        w.f64_const(0.5) + b"\xA1" + w.F64_GE   # f64.sub = 0xA1
    m["counter"] = w.module(
        types=[([w.I32, w.I32, w.F64], [w.F64]), T_VOID, T_STEP, T_FRAME], imports=[("sr", "param_f64", 0)],
        funcs=[1, 2, 3], globals_=[(w.I64, 0)],
        exports=[("memory", 2, 0), ("init", 0, 1), ("step", 0, 2), ("frame", 0, 3)],
        codes=[w.END, w.global_get(0) + w.i64_const(1) + w.I64_ADD + w.global_set(0) + w.END, frame_body(count_test)],
        data=[(0, b"target")])
    # rng: each step XORs the next sr.rand_u64 value into global 0; red when the low bit is 1
    m["rng"] = w.module(
        types=[([], [w.I64]), T_VOID, T_STEP, T_FRAME], imports=[("sr", "rand_u64", 0)],
        funcs=[1, 2, 3], globals_=[(w.I64, 0)],
        exports=[("memory", 2, 0), ("init", 0, 1), ("step", 0, 2), ("frame", 0, 3)],
        codes=[w.END, w.global_get(0) + w.call(0) + w.I64_XOR + w.global_set(0) + w.END,
               frame_body(w.global_get(0) + w.i64_const(1) + w.I64_AND + w.i64_const(0) + w.I64_NE)])
    # no step export
    m["no-step"] = w.module(types=[T_VOID, T_FRAME], funcs=[0, 1], exports=[("memory", 2, 0), ("init", 0, 0), ("frame", 0, 1)],
                            codes=[w.END, frame_body(w.i32_const(1))])
    return m


def sha(b):
    return hashlib.sha256(b).hexdigest()


def doc(mods, name, attrs="", params="", version="1.6", seed=1):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            f'<project width="640" height="360" fps="10" duration="2" background="#000000FF" seed="{seed}"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n<composition>\n'
            f'<program id="p" mode="step" width="100" height="100" x="270" y="130" src="../assets/srep69-{name}.wasm" '
            f'sha256="{sha(mods[name])}"{attrs}>{params}</program>\n</composition>\n</scene>\n')


@functools.lru_cache(None)
def parity(project_seed, program_seed, n):
    g, acc = w.program_rng(project_seed, program_seed), 0
    for _ in range(n):
        acc ^= next(g)
    return acc & 1


def main():
    mods = modules()
    for k, b in mods.items():
        open(os.path.join(CONF, "srep_cases", "assets", f"srep69-{k}.wasm"), "wb").write(b)
    sq = {"cx": 320, "cy": 180, "w": 100, "h": 100}
    cases = {}

    def add(slug, xml, red=None, time=None, **extra):
        e = {"rule": "SREP 69"}
        if time is not None:
            e["output"] = {"id": "still", "time": time}
        if red is not None:
            e.update({"red": sq, "absent": ["blue"]} if red else {"blue": sq, "absent": ["red"]})
        e.update(extra)
        e.setdefault("pending", PENDING)
        cases[f"srep-0069-{slug}"] = {"xml": xml, "expected": e}

    target = lambda n: f'<param name="target" value="{n}"/>'  # noqa: E731
    add("step-frame-0", doc(mods, "counter", params=target(1)), True)
    add("step-frame-0-short", doc(mods, "counter", params=target(2)), False)
    add("step-per-frame", doc(mods, "counter", ' stepsPerFrame="5"', target(5)), True)
    add("step-per-frame-short", doc(mods, "counter", ' stepsPerFrame="5"', target(6)), False)
    add("step-prewarm", doc(mods, "counter", ' prewarm="4"', target(5)), True)
    add("step-seek", doc(mods, "counter", "", target(5)), True, time=0.4)
    add("step-seek-short", doc(mods, "counter", "", target(6)), False, time=0.4)
    # the generator continues across steps and is part of the state: 5 steps at frame 4
    seeds = {}
    for s in range(1, 60):
        seeds.setdefault(parity(1, s, 5), s)
    add("step-rng-odd", doc(mods, "rng", f' seed="{seeds[1]}"'), True, time=0.4)
    add("step-rng-even", doc(mods, "rng", f' seed="{seeds[0]}"'), False, time=0.4)
    add("step-missing-export", doc(mods, "no-step"), failure={"code": "PRG11"}, pending=FAILED)
    add("step-needs-size", doc(mods, "counter").replace(' width="100" height="100"', ""),
        findings={"valid": False, "codes": ["PRG3"]})
    add("build-mode-no-steps", doc(mods, "counter", ' stepsPerFrame="2"').replace(' mode="step"', ""),
        findings={"valid": False, "codes": ["STP1"]})
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0069.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases; odd seed {seeds[1]}, even seed {seeds[0]}")


if __name__ == "__main__":
    main()
