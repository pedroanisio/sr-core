#!/usr/bin/env python3
"""Writes the SREP 68 kit cases (stepsPerFrame, prewarm, render-order independence) to srep_cases/srep-0068.json and
the counter shader to srep_cases/assets/srep68-counter.fs. The shader adds 1 to a persistent float buffer per step and
draws red once the count reaches the parameter "target", blue before; the expected colour follows from the step count
of SREP 68, Semantics 1: prewarm + s(f) * stepsPerFrame, s(f) the frames from f0 to f at which the node is drawn.
Usage: python3 conformance/tools/srep68_cases.py; then python3 conformance/make_cases.py."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PENDING = "SREP 68 is a draft; no engine implements stepsPerFrame, prewarm or node-local replay yet. The entry keeps the values derived from the SREP"
COUNTER = """/*{"ISFVSN":"2","DESCRIPTION":"SREP 68 kit: adds 1 to a float buffer per step; red once it reaches target, else blue",
"INPUTS":[{"NAME":"inputImage","TYPE":"image"},{"NAME":"target","TYPE":"float","DEFAULT":10}],
"PASSES":[{"TARGET":"acc","PERSISTENT":true,"FLOAT":true},{}]}*/
void main() {
    if (PASSINDEX == 0) {
        vec4 prev = IMG_NORM_PIXEL(acc, isf_FragNormCoord);
        gl_FragColor = vec4(prev.r + 1.0, 0.0, 0.0, 1.0);
    } else {
        float n = IMG_NORM_PIXEL(acc, isf_FragNormCoord).r;
        vec4 src = IMG_NORM_PIXEL(inputImage, isf_FragNormCoord);
        gl_FragColor = (n >= target - 0.5) ? vec4(1.0, 0.0, 0.0, src.a) : vec4(0.0, 0.0, 1.0, src.a);
    }
}
"""
SQ = {"cx": 320, "cy": 180, "w": 100, "h": 100}


def steps(f, spf=1, prewarm=0, f0=0):
    return prewarm + (f - f0 + 1) * spf


def doc(target, attrs="", node_attrs="", version="1.6", effect_type="shader"):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            '<project width="640" height="360" fps="10" duration="2" background="#000000FF" seed="1"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            '<composition>\n'
            f'<shape id="s" shape="rect" width="100" height="100" anchorX="50" anchorY="50" x="320" y="180" fill="#FFFFFFFF" effects="fx"{node_attrs}/>\n'
            '</composition>\n'
            f'<effects><effect id="fx" type="{effect_type}" src="../assets/srep68-counter.fs"{attrs}><param name="target" value="{target}"/></effect></effects>\n'
            '</scene>\n')


def main():
    open(os.path.join(CONF, "srep_cases", "assets", "srep68-counter.fs"), "w").write(COUNTER)
    cases = {}

    def add(slug, xml, red, time=None, **extra):
        e = {"rule": "SREP 68"}
        if time is not None:
            e["output"] = {"id": "still", "time": time}
        e.update({"red": SQ, "absent": ["blue"]} if red else {"blue": SQ, "absent": ["red"]})
        e.update(extra)
        e["pending"] = PENDING
        cases[f"srep-0068-{slug}"] = {"xml": xml, "expected": e}

    add("one-step-per-frame", doc(steps(0)), True)
    add("one-step-per-frame-short", doc(steps(0) + 1), False)
    add("steps-per-frame", doc(steps(0, spf=10), ' stepsPerFrame="10"'), True)
    add("steps-per-frame-short", doc(steps(0, spf=10) + 1, ' stepsPerFrame="10"'), False)
    add("prewarm", doc(steps(0, prewarm=9), ' prewarm="9"'), True)
    add("prewarm-short", doc(steps(0, prewarm=9) + 1, ' prewarm="9"'), False)
    # render-order independence: the encode starts at 0.4 s (frame 4), so earlier frames were never rendered by it
    add("seek", doc(steps(4)), True, time=0.4)
    add("seek-short", doc(steps(4) + 1), False, time=0.4)
    add("seek-combined", doc(steps(4, spf=3, prewarm=2), ' stepsPerFrame="3" prewarm="2"'), True, time=0.4)
    add("seek-combined-short", doc(steps(4, spf=3, prewarm=2) + 1, ' stepsPerFrame="3" prewarm="2"'), False, time=0.4)
    # a node first active at frame 2 steps at frames 2, 3 and 4
    add("late-start", doc(steps(4, f0=2), node_attrs=' start="0.2"'), True, time=0.4)
    add("late-start-short", doc(steps(4, f0=2) + 1, node_attrs=' start="0.2"'), False, time=0.4)
    # a node hidden at frame 2 takes no step there: stepping frames 0, 1, 3 and 4
    add("hidden-frame", doc(4, node_attrs=' condition="frame != 2"'), True, time=0.4)
    add("hidden-frame-short", doc(5, node_attrs=' condition="frame != 2"'), False, time=0.4)
    cases["srep-0068-not-a-stateful-effect"] = {
        "xml": doc(1, ' stepsPerFrame="2"', effect_type="blur"),
        "expected": {"rule": "SREP 68", "findings": {"valid": False, "codes": ["STP1"]}, "pending": PENDING}}
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0068.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
