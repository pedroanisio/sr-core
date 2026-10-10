"""conformance/: the cases regenerate exactly, and run.py fails when an engine fails (usable as a CI gate)."""
import filecmp
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "conformance")


def test_cases_regenerate_exactly(tmp_path):
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    subprocess.run([sys.executable, str(copy / "make_cases.py")], check=True, capture_output=True)
    for sub in ("cases", "assets"):
        cmp = filecmp.dircmp(os.path.join(CONF, sub), copy / sub)
        assert not (cmp.diff_files or cmp.left_only or cmp.right_only), (sub, cmp.diff_files)
    assert filecmp.cmp(os.path.join(CONF, "expected.json"), copy / "expected.json", shallow=False)


def _run(tmp_path, engine_script: str | None, cases="a1"):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    # the stand-in engines below implement what a pending case waits for (the captions command of SREP 52, the
    # transition audio of SREP 82), so the copy runs those cases instead of listing them as pending
    for srep in ("srep-0052", "srep-0082"):     # captions (SREP 52) and audio (SREP 82)
        if engine_script is None or srep not in cases:
            continue
        import json
        spec = json.loads((copy / "expected.json").read_text())
        for c in spec["cases"]:
            if c.startswith(srep + "-"):
                spec["cases"][c].pop("pending", None)
        (copy / "expected.json").write_text(json.dumps(spec, indent=2))
    env = {k: v for k, v in os.environ.items() if k != "RS_RENDER_BIN"}
    env["PATH"] = str(tmp_path / "empty")
    if engine_script is not None:
        eng = tmp_path / "engine"
        eng.write_text(f"#!{sys.executable}\n{engine_script}")
        eng.chmod(0o755)
        env["RS_RENDER_BIN"] = str(eng)
    return subprocess.run([sys.executable, str(copy / "run.py"), "--renderers", "rs", "--cases", cases],
                          capture_output=True, text=True, env=env)


def test_an_engine_that_fails_fails_the_run(tmp_path):
    r = _run(tmp_path, "import sys; sys.exit(3)")
    assert r.returncode == 1 and "error" in r.stdout


def test_a_missing_engine_is_reported_not_a_traceback(tmp_path):
    r = _run(tmp_path, None)
    assert r.returncode == 1 and "Traceback" not in r.stderr


def test_a_wrong_picture_fails_the_run(tmp_path):
    black = ("import sys\nfrom PIL import Image\nImage.new('RGB', (640, 360)).save(sys.argv[sys.argv.index('-o') + 1])\n")
    r = _run(tmp_path, black)
    assert r.returncode == 1 and "fail" in r.stdout


def test_an_output_case_delivers_that_output_at_its_time(tmp_path):
    # the engine is asked to encode output "short" from output time 1; it writes the frame into the case folder
    red = ("import os, sys\nfrom PIL import Image\n"
            "a = sys.argv\n"
            "assert a[1] == 'encode' and a[a.index('--output') + 1] == 'short' and float(a[a.index('--start') + 1]) == 1.0, a\n"
            "d = os.path.join(os.path.dirname(a[2]), 'out')\nos.makedirs(d, exist_ok=True)\n"
            "Image.new('RGB', (640, 360), (255, 0, 0)).save(os.path.join(d, 'frame_0024.png'))\n")
    r = _run(tmp_path, red, cases="srep-0013-segment-join")
    assert r.returncode == 0 and "pass" in r.stdout, r.stdout + r.stderr


def test_a_pending_case_is_listed_but_does_not_fail_the_run(tmp_path):
    import json
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    spec = json.load(open(copy / "expected.json"))
    spec["cases"]["zz-pending"] = {"rule": "SREP 0", "pending": "the engine does not implement it yet"}
    json.dump(spec, open(copy / "expected.json", "w"))
    env = {k: v for k, v in os.environ.items() if k != "RS_RENDER_BIN"}
    env["PATH"] = str(tmp_path / "empty")      # no engine: a case that ran would be an error
    r = subprocess.run([sys.executable, str(copy / "run.py"), "--renderers", "rs", "--cases", "zz-pending"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "pending" in r.stdout, (r.stdout, r.stderr)
    assert "zz-pending" in (copy / "out" / "report.md").read_text()


def _captions_engine(pages, words=None, active=None, status=0, greedy_words=None):
    """A stand-in engine for `captions <scene> [--at times]`: tracks "cap", "src" and "grd", each with these pages,
    these words in one cue (greedy_words instead for a case whose name says greedy) and these current words."""
    words = words if words is not None else [["aa", 0.0, 2.0], ["bb", 2.0, 4.0], ["cc", 4.0, 6.0], ["dd", 6.0, 8.0]]
    return ("import json, sys\n"
            "a = sys.argv\n"
            "assert a[1] == 'captions', a\n"
            "times = [float(t) for t in a[a.index('--at') + 1].split(',')] if '--at' in a else []\n"
            f"pages, words, active = {pages!r}, {words!r}, {active!r}\n"
            f"if 'greedy' in a[2] and {greedy_words!r}: words = {greedy_words!r}\n"
            "cue = {'start': 0.0, 'end': 8.0, 'words': [{'index': i, 'text': t, 'start': s, 'end': e} for i, (t, s, e) in enumerate(words)]}\n"
            "def track(i):\n"
            "    return {'id': i, 'burn': True, 'preset': 'classic', 'lineBreaks': 'source', 'wordCount': len(words),\n"
            "            'cues': [cue], 'pages': [{'text': p} for p in pages],\n"
            "            'at': [{'time': t, 'page': 0, 'cue': 0, 'word': (active or {}).get(str(t))} for t in times]}\n"
            "print(json.dumps({'tracks': [track('cap'), track('src'), track('grd')]}))\n"
            f"sys.exit({status})\n")


def test_a_captions_case_passes_on_the_pages_it_expects(tmp_path):
    r = _run(tmp_path, _captions_engine(["aa bb\ncc dd", "ee ff\ngg hh"]), cases="srep-0052-caption-lines-limits-chars")
    assert r.returncode == 0 and "pass" in r.stdout, r.stdout + r.stderr


def test_a_captions_case_fails_on_other_pages(tmp_path):
    r = _run(tmp_path, _captions_engine(["aa bb cc dd ee ff gg hh"]), cases="srep-0052-caption-lines-limits-chars")
    assert r.returncode == 1 and "fail" in r.stdout, r.stdout + r.stderr
    assert "captions: pages" in (tmp_path / "conformance" / "out" / "report.md").read_text()


def test_a_captions_case_checks_the_current_word_at_each_time(tmp_path):
    good = {"0.5": 0, "1.5": 1, "2.5": 2, "3.5": 3}
    engine = _captions_engine(["aa bb\ncc dd"], active=good)
    # the boxed-word case has two tracks; the stand-in gives both the same pages, so only "src" can pass on pages
    r = _run(tmp_path, engine, cases="srep-0052-caption-lines-presets-boxed-word")
    assert r.returncode == 1, r.stdout
    report = (tmp_path / "conformance" / "out" / "report.md").read_text()
    assert "grd" in report and "activeWord" not in report, report
    again = tmp_path / "again"
    again.mkdir()
    _run(again, _captions_engine(["aa bb\ncc dd"], active={**good, "2.5": 1}),
         cases="srep-0052-caption-lines-presets-boxed-word")
    assert "activeWord src at 2.5: 2 (got 1)" in (again / "conformance" / "out" / "report.md").read_text()


def test_a_captions_case_compares_words_and_times_with_another_case(tmp_path):
    import json

    def results(d):
        return json.loads((d / "conformance" / "out" / "report.json").read_text())["results"]["rs"]
    # the stand-in prints "aa bb\ncc dd" for both cases: blank passes, as its words and times equal blank-greedy's
    _run(tmp_path, _captions_engine(["aa bb\ncc dd"]), cases="srep-0052-caption-lines-blank")
    assert results(tmp_path)["srep-0052-caption-lines-blank"]["status"] == "pass", results(tmp_path)
    assert results(tmp_path)["srep-0052-caption-lines-blank-greedy"]["status"] == "fail", "its pages differ"
    # words that move in the greedy case fail the comparison
    moved = tmp_path / "moved"
    moved.mkdir()
    _run(moved, _captions_engine(["aa bb\ncc dd"], greedy_words=[["aa", 0.0, 1.0]]), cases="srep-0052-caption-lines-blank")
    blank = results(moved)["srep-0052-caption-lines-blank"]
    assert blank["status"] == "fail" and not blank["checks"]["wordsAndTimes"][0][1], blank


def test_a_captions_case_errors_when_the_engine_fails(tmp_path):
    r = _run(tmp_path, _captions_engine(["aa bb\ncc dd"], status=1), cases="srep-0052-caption-lines-limits-chars")
    assert r.returncode == 1 and "error" in r.stdout and "Traceback" not in r.stderr, r.stdout + r.stderr


def _audio_engine(gains: str, status=0, bits=24):
    """A stand-in engine for `encode <scene> --output <id>`: writes the output's WAV (48 kHz stereo, `bits`-bit PCM)
    holding the SREP 82 test tones a (500 Hz) and b (1250 Hz) at amplitude 0.25, each times the gain that the Python
    expression `gains` gives as a pair (ga, gb) of the time t in seconds."""
    return ("import re, sys, numpy as np\n"
            "a = sys.argv\n"
            "assert a[1] == 'encode' and a[3] == '--output', a\n"
            "xml = open(a[2]).read()\n"
            "out = re.search(r'<output\\b[^>]*id=\"%s\"[^>]*path=\"([^\"]+)\"' % a[4], xml).group(1)\n"
            "import os; path = os.path.join(os.path.dirname(a[2]), out); os.makedirs(os.path.dirname(path), exist_ok=True)\n"
            "r = 48000; t = np.arange(2 * r) / r\n"
            f"def g(t):\n    return {gains}\n"
            "ga, gb = np.vectorize(g)(t)\n"
            "x = 0.25 * (ga * np.sin(2 * np.pi * 500 * t) + gb * np.sin(2 * np.pi * 1250 * t))\n"
            f"bits = {bits}; w = bits // 8\n"
            "v = np.round(x * (2 ** (bits - 1) - 1)).astype(np.int64)\n"
            "s = np.repeat(v, 2)\n"
            "body = b''.join(int(q).to_bytes(w, 'little', signed=True) for q in s)\n"
            "fmt = (1).to_bytes(2, 'little') + (2).to_bytes(2, 'little') + r.to_bytes(4, 'little') + "
            "(r * 2 * w).to_bytes(4, 'little') + (2 * w).to_bytes(2, 'little') + bits.to_bytes(2, 'little')\n"
            "riff = b'WAVE' + b'fmt ' + len(fmt).to_bytes(4, 'little') + fmt + b'data' + len(body).to_bytes(4, 'little') + body\n"
            "open(path, 'wb').write(b'RIFF' + len(riff).to_bytes(4, 'little') + riff)\n"
            f"sys.exit({status})\n")


# SREP 82's default crossfade over the window [0.8, 1.2) of srep-0082-crossfade-default; before, a alone, after, b alone
CROSSFADE = "(1.0, 0.0) if t < 0.8 else (0.0, 1.0) if t >= 1.2 else (1 - (t - 0.8) / 0.4, (t - 0.8) / 0.4)"


def test_an_audio_case_passes_on_the_gains_it_expects(tmp_path):
    r = _run(tmp_path, _audio_engine(CROSSFADE), cases="srep-0082-crossfade-default")
    assert r.returncode == 0 and "pass" in r.stdout, r.stdout + r.stderr


def test_an_audio_case_reads_16_bit_wav_too(tmp_path):
    r = _run(tmp_path, _audio_engine(CROSSFADE, bits=16), cases="srep-0082-crossfade-default")
    assert r.returncode == 0 and "pass" in r.stdout, r.stdout + r.stderr


def test_an_audio_case_fails_when_the_transition_does_not_mix_the_sound(tmp_path):
    # what the reference did before SREP 82: both sides at full volume over the handles
    r = _run(tmp_path, _audio_engine("(1.0 if t < 1.2 else 0.0, 1.0 if t >= 0.8 else 0.0)"),
             cases="srep-0082-crossfade-default")
    assert r.returncode == 1 and "fail" in r.stdout, r.stdout + r.stderr
    report = (tmp_path / "conformance" / "out" / "report.md").read_text()
    assert "audio: gains a at 0.9: 0.75 (got 1.0)" in report, report


def test_an_audio_case_errors_when_the_engine_fails(tmp_path):
    r = _run(tmp_path, _audio_engine(CROSSFADE, status=1), cases="srep-0082-crossfade-default")
    assert r.returncode == 1 and "error" in r.stdout, r.stdout + r.stderr
