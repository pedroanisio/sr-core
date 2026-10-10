#!/usr/bin/env python3
"""Writes the SREP 82 kit cases (transition/@audio mixes the sound of the video layers on a transition's sides) to
srep_cases/srep-0082.json. With --assets it also writes the two tone clips srep_cases/assets/srep82-tone-500.mkv and
srep82-tone-1250.mkv with ffmpeg: 2.2 s each, 64 x 36 black FFV1 video at 25 fps, and a sine of 500 Hz or 1250 Hz at
amplitude 0.25 (-12 dBFS), the same on both channels of 16 kHz stereo FLAC. The files are committed; ffmpeg is only
needed to write them again.

Every case renders its document's audio-only WAV output "mix" and is checked by run.py's "audio" form: at each listed
time t, the amplitude of each tone over the 40 ms window centred on t (one frame at 25 fps; both tones complete a
whole number of cycles in it, so neither leaks into the other's measurement), divided by 0.25, is that side's gain.
The transitions use curve="linear" except where a case says otherwise, so p is the fraction of the window elapsed.
Gains are measured at least one frame from any step, since an engine may sample them once per frame (SREP 82,
Semantics 5). Usage: python3 conformance/tools/srep82_cases.py [--assets]; then python3 conformance/make_cases.py."""
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
PENDING = ("SREP 82 is a draft; the Rust reference implements it on branch fix/transition-audio (61a85ebf), not yet "
           "on main. The entry keeps the values derived from the SREP")
TONES = {"a": 500, "b": 1250}
LEVEL = 0.25


def write_assets():
    for f in TONES.values():
        out = os.path.join(CONF, "srep_cases", "assets", f"srep82-tone-{f}.mkv")
        subprocess.run(["ffmpeg", "-v", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=black:s=64x36:r=25:d=2.2",
                        "-f", "lavfi", "-i", f"aevalsrc={LEVEL}*sin(2*PI*{f}*t)|{LEVEL}*sin(2*PI*{f}*t):s=16000:d=2.2",
                        "-map", "0:v", "-map", "1:a", "-c:v", "ffv1", "-c:a", "flac", "-shortest",
                        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                        "-map_metadata", "-1", out], check=True)


def doc(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<scene version="1.5">\n'
            '<project width="64" height="36" fps="25" duration="2" background="#000000FF" seed="1"/>\n'
            '<output id="mix" path="out/mix.wav" codec="audio-only" container="wav"/>\n'
            '<assets>\n'
            '<video id="ta" src="../assets/srep82-tone-500.mkv" width="64" height="36" fps="25" duration="2.2" hasAudio="true"/>\n'
            '<video id="tb" src="../assets/srep82-tone-1250.mkv" width="64" height="36" fps="25" duration="2.2" hasAudio="true"/>\n'
            '</assets>\n'
            f'<composition>\n{body}\n</composition>\n</scene>\n')


# a ends at the cut (1 s) and plays its media from 0; b starts at the cut with clipIn 1, so its media time is the
# composition time and its handle before the cut reads real media
A = '<layer id="a" asset="ta" end="1"{a}/>'
B = '<layer id="b" asset="tb" start="1" clipIn="1"/>'


def r(x):
    return round(x, 5)


def main():
    if "--assets" in sys.argv:
        write_assets()
    cases = {}

    def add(slug, body, gains, note):
        cases[f"srep-0082-{slug}"] = {"xml": doc(body), "expected": {
            "rule": "SREP 82",
            "audio": {"output": "mix", "tones": TONES, "level": LEVEL, "window": 0.04, "tolerance": 0.01,
                      "gains": [[t, {k: r(v) for k, v in g.items()}] for t, g in gains], "note": note},
            "pending": PENDING}}

    def two(audio="", a="", kind="wipe"):
        attr = f' audio="{audio}"' if audio else ""
        return "\n".join([A.format(a=a), B,
                          f'<transition type="{kind}" from="a" to="b" duration="0.4" curve="linear"{attr}/>'])

    # window [0.8, 1.2); p = (t - 0.8) / 0.4; outside it a has ended or b has not started
    outside = [[0.6, {"a": 1, "b": 0}], [1.4, {"a": 0, "b": 1}]]
    ps = [0.25, 0.5, 0.75]
    at = lambda p: r(0.8 + 0.4 * p)
    add("crossfade-default", two(),
        outside[:1] + [[at(p), {"a": 1 - p, "b": p}] for p in ps] + outside[1:],
        "no audio attribute: crossfade, a = 1 - p, b = p (Semantics 1, 2)")
    add("crossfade-explicit", two("crossfade"),
        [[at(p), {"a": 1 - p, "b": p}] for p in ps], "audio=crossfade (Semantics 2)")
    add("equal-power", two("equal-power"),
        [[at(p), {"a": math.cos(math.pi * p / 2), "b": math.sin(math.pi * p / 2)}] for p in ps],
        "a = cos(pi p / 2), b = sin(pi p / 2) (Semantics 2)")
    add("cut", two("cut"),
        [[at(0.25), {"a": 1, "b": 0}], [at(0.75), {"a": 0, "b": 1}]],
        "a while p < 1/2, b from p = 1/2; measured a frame or more from the step (Semantics 2, 5)")
    add("none", two("none"),
        outside[:1] + [[at(p), {"a": 1, "b": 1}] for p in ps] + outside[1:],
        "both sides at their own volume over the whole window, handles included (Semantics 2)")
    add("volume-multiplies", two(a=' volume="0.8"'),
        [[0.6, {"a": 0.8, "b": 0}]] + [[at(p), {"a": 0.8 * (1 - p), "b": p}] for p in ps],
        "the gain multiplies the layer's own volume (Semantics 4)")
    add("cut-picture-crossfades-sound", two(kind="cut"),
        [[at(p), {"a": 1 - p, "b": p}] for p in ps],
        "type=cut with no audio attribute: the picture cuts, the sound crossfades (Semantics 1)")
    # one-sided: a group fades out over [0.6, 1.0); b alone fades in over [1.0, 1.4)
    add("one-sided-group-out",
        '<group id="g" end="1">' + A.format(a="") + '</group>\n'
        '<transition type="crossfade" from="g" duration="0.4" alignment="end" curve="linear"/>',
        [[0.5, {"a": 1}]] + [[r(0.6 + 0.4 * p), {"a": 1 - p}] for p in ps],
        "the outgoing side is a group: the layer inside it fades with 1 - p (Semantics 3)")
    add("one-sided-layer-in",
        B + '\n<transition type="crossfade" to="b" duration="0.4" alignment="start" curve="linear"/>',
        [[r(1.0 + 0.4 * p), {"b": p}] for p in ps] + [[1.6, {"b": 1}]],
        "the incoming side alone fades in with p (Semantics 3)")
    # a sequence junction: b is placed at a's end (1 s); the window [0.8, 1.2) eases in and out, so p = 1/2 only at
    # its centre, where both gains are 1/2 whatever the ease-in-out curve is, since that curve is symmetric
    add("sequence-junction",
        '<sequence id="s" transition="wipe" transitionDuration="0.4">\n'
        '<layer id="a" asset="ta" end="1"/>\n<layer id="b" asset="tb" end="1" clipIn="1"/>\n</sequence>',
        [[0.6, {"a": 1, "b": 0}], [1.0, {"a": 0.5, "b": 0.5}], [1.4, {"a": 0, "b": 1}]],
        "a sequence junction of a type other than cut crossfades its sound (Semantics 3)")
    # a cut junction switches its sound where its picture switches (p = 1/2, the window's centre under the symmetric
    # ease-in-out); at 0.9 s and 1.1 s p is below and above 1/2, and both are more than a frame from the step
    add("sequence-cut-junction",
        '<sequence id="s" transition="cut" transitionDuration="0.4">\n'
        '<layer id="a" asset="ta" end="1"/>\n<layer id="b" asset="tb" end="1" clipIn="1"/>\n</sequence>',
        [[0.6, {"a": 1, "b": 0}], [0.9, {"a": 1, "b": 0}], [1.1, {"a": 0, "b": 1}], [1.4, {"a": 0, "b": 1}]],
        "a cut junction cuts its sound where its picture cuts (Semantics 3, 5)")
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0082.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
