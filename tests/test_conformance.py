"""conformance/: the cases regenerate exactly, and run.py fails when an engine fails (usable as a CI gate)."""
import filecmp
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "conformance")


def _stale_outputs(copy, tree=CONF):
    """Regenerate cases/, assets/ and expected.json into `copy` from nothing and list what differs from the tree.
    The two output directories are removed first: copying them in would hand the generator its own orphans."""
    shutil.rmtree(copy / "cases", ignore_errors=True)
    shutil.rmtree(copy / "assets", ignore_errors=True)
    subprocess.run([sys.executable, str(copy / "make_cases.py")], check=True, capture_output=True)
    bad = []
    for sub in ("cases", "assets"):
        cmp = filecmp.dircmp(os.path.join(tree, sub), copy / sub)
        bad += [f"{sub}/{n}" for n in cmp.diff_files + cmp.left_only + cmp.right_only]
    if not filecmp.cmp(os.path.join(tree, "expected.json"), copy / "expected.json", shallow=False):
        bad.append("expected.json")
    return bad


def test_cases_regenerate_exactly(tmp_path):
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    assert _stale_outputs(copy) == []


def test_a_hand_written_file_in_cases_is_not_a_regeneration(tmp_path):
    """Drift-risk map finding 9: three hand-kept XMLs sat in cases/ and were invisible to this test, because the
    directory was copied in before the generator ran."""
    tree = tmp_path / "tree"
    shutil.copytree(CONF, tree, ignore=shutil.ignore_patterns("out", "__pycache__"))
    (tree / "cases" / "zz-hand-written.xml").write_text("<scene/>")
    copy = tmp_path / "copy"
    shutil.copytree(tree, copy)
    assert _stale_outputs(copy, tree) == ["cases/zz-hand-written.xml"]


def test_the_kit_fixtures_kept_by_hand_are_outside_the_generated_directory():
    kit = os.path.join(ROOT, "tests", "fixtures", "kit")
    assert sorted(os.listdir(kit)) == ["srep-0028-asset-kinds.xml", "srep-0033-safe-area-force.xml",
                                       "srep-0034-inert-and-mask-miss.xml"]
    assert not [n for n in os.listdir(os.path.join(CONF, "cases")) if n.startswith(("srep-0028-asset-kinds",
                "srep-0033-safe-area-force.", "srep-0034-inert-and-mask-miss"))]


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


# ---- regressions for the drift-risk map's two CRITICAL findings (conformance oracle vs prose; vacuous passes)
import json  # noqa: E402
import re  # noqa: E402


def test_the_constants_block_agrees_with_the_prose_and_the_kit():
    """CONVENTIONS.md 2.8 is the one place make_cases.py reads the camera constants from; the prose of 2.1-2.6 must
    state the same numbers, and the generated oracle must be computed from them."""
    text = open(os.path.join(CONF, "CONVENTIONS.md"), encoding="utf-8").read()
    blocks = re.findall(r"```json conventions-constants\n(.*?)\n```", text, re.S)
    assert len(blocks) == 1
    c = json.loads(blocks[0])
    assert set(c) == {"implicit_camera_hfov_degrees", "default_sensor_width", "default_pixels_per_meter"}
    assert [int(x) for x in re.findall(r"horizontal\*\* fov of \*\*(\d+)°", text)] == [c["implicit_camera_hfov_degrees"]]
    assert [int(x) for x in re.findall(r"sensorWidth default (\d+)", text)] == [c["default_sensor_width"]]
    ppm = [int(x) for x in re.findall(r"pixelsPerMeter`\s*\(default (\d+)\)", text)]
    assert ppm and set(ppm) == {c["default_pixels_per_meter"]}, ppm
    import math
    exp = json.load(open(os.path.join(CONF, "expected.json")))
    w = exp["frame"][0]
    d = (w / 2) / math.tan(math.radians(c["implicit_camera_hfov_degrees"]) / 2)
    assert exp["implicit_camera_distance"] == round(d, 3)
    src = open(os.path.join(CONF, "make_cases.py"), encoding="utf-8").read()
    assert not re.search(r"^HFOV = [\d.]+\s*$", src, re.M), "make_cases.py restates the fov; read it from CONVENTIONS.md"
    assert 'fov="60"' not in src


def test_changing_the_constants_block_changes_the_oracle(tmp_path):
    """The kit follows the block: with 90 degrees the implicit camera distance is W/2."""
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    p = copy / "CONVENTIONS.md"
    p.write_text(p.read_text(encoding="utf-8").replace('"implicit_camera_hfov_degrees": 60', '"implicit_camera_hfov_degrees": 90'),
                 encoding="utf-8")
    subprocess.run([sys.executable, str(copy / "make_cases.py")], check=True, capture_output=True)
    assert json.load(open(copy / "expected.json"))["implicit_camera_distance"] == 320.0


def _findings_engine():
    """Reports the document invalid with no diagnostics at all."""
    return "import json\nprint(json.dumps({'files': [{'valid': False, 'diagnostics': []}]}))\n"


def _with_entry(tmp_path, entry):
    """A kit copy whose expected.json holds only case a1-anchor-translate, with `entry`."""
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    spec = json.load(open(copy / "expected.json"))
    spec["cases"] = {"a1-anchor-translate": entry}
    json.dump(spec, open(copy / "expected.json", "w"))
    return copy


def _run_copy(tmp_path, copy, engine_script, *extra):
    eng = tmp_path / "engine"
    eng.write_text(f"#!{sys.executable}\n{engine_script}")
    eng.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "RS_RENDER_BIN"}
    env["RS_RENDER_BIN"] = str(eng)
    return subprocess.run([sys.executable, str(copy / "run.py"), "--renderers", "rs", "--cases", "a1", *extra],
                          capture_output=True, text=True, env=env)


@pytest.mark.parametrize("entry,why", [
    ({"rule": "x", "findings": {"cods": ["NOPE"], "valdi": True}}, "unknown key"),   # the verified vacuous pass
    ({"rule": "x", "findings": {}}, "no check"),
    ({"rule": "x", "findings": {"via": "render"}}, "via render"),
    ({"rule": "x"}, "no check"),
    ({"rule": "x", "reed": {"cx": 1}}, "unknown key"),
    ({"rule": "x", "red": {}}, "non-empty object"),
    ({"rule": "x", "red": {"cz": 1}}, "non-empty object"),
    ({"rule": "x", "captions": {"track": "cap"}}, "no check beyond"),
    ({"rule": "x", "captions": {"track": "cap", "page": ["a"]}}, "unknown key"),
    ({"rule": "x", "audio": {"output": "o", "tones": {}, "level": 1, "window": 1, "tolerance": 1, "gains": []}}, "empty"),
    ({"rule": "x", "absent": ["purple"]}, "'absent'"),
])
def test_an_entry_that_checks_nothing_is_an_error_not_a_pass(tmp_path, entry, why):
    r = _run_copy(tmp_path, _with_entry(tmp_path, entry), _findings_engine())
    report = json.loads((tmp_path / "conformance" / "out" / "report.json").read_text())["results"]["rs"]
    got = report["a1-anchor-translate"]
    assert r.returncode == 1 and got["status"] == "error", r.stdout
    assert why in " ".join(got["notes"]), got


def test_a_misspelt_findings_key_no_longer_passes_an_engine_that_reports_invalid(tmp_path):
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "findings": {"cods": ["NOPE"], "valdi": True}}),
                  _findings_engine())
    assert r.returncode == 1 and " pass " not in r.stdout, r.stdout


def test_a_well_formed_findings_entry_still_runs_and_can_fail(tmp_path):
    ok = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "findings": {"valid": False}}), _findings_engine())
    assert ok.returncode == 0 and " pass " in ok.stdout, ok.stdout
    other = tmp_path / "other"
    other.mkdir()
    bad = _run_copy(other, _with_entry(other, {"rule": "x", "findings": {"valid": True}}), _findings_engine())
    assert bad.returncode == 1 and " fail " in bad.stdout, bad.stdout


def _envelope_engine(result):
    """Reports `validate --format json` in the scene-render-cli/1 envelope, with `result` as its payload."""
    return ("import json\nprint(json.dumps({'format': 'scene-render-cli/1', 'command': 'validate', 'ok': True, "
            f"'exit_code': 0, 'error': None, 'diagnostics': [], 'result': {result!r}}}))\n")


def test_findings_are_read_from_the_cli_envelope(tmp_path):
    engine = _envelope_engine({"files": [{"valid": False, "diagnostics": [{"code": "E1", "message": "m"}]}], "valid": False})
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "findings": {"valid": False, "codes": ["E1"]}}), engine)
    assert r.returncode == 0 and " pass " in r.stdout, r.stdout


@pytest.mark.parametrize("result", [None, {}, {"files": []}, {"files": "x"}, {"filez": [{"valid": True}]}])
def test_an_envelope_without_files_is_an_error_not_a_pass(tmp_path, result):
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "findings": {"valid": True}}), _envelope_engine(result))
    got = json.loads((tmp_path / "conformance" / "out" / "report.json").read_text())["results"]["rs"]["a1-anchor-translate"]
    assert r.returncode == 1 and got["status"] == "error", r.stdout
    assert "validate failed" in " ".join(got["notes"]), got


def test_an_unknown_envelope_format_is_an_error(tmp_path):
    engine = ("import json\nprint(json.dumps({'format': 'scene-render-cli/2', "
              "'result': {'files': [{'valid': True, 'diagnostics': []}]}}))\n")
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "findings": {"valid": True}}), engine)
    got = json.loads((tmp_path / "conformance" / "out" / "report.json").read_text())["results"]["rs"]["a1-anchor-translate"]
    assert r.returncode == 1 and got["status"] == "error" and "scene-render-cli/2" in " ".join(got["notes"]), got


def test_every_entry_of_the_committed_kit_is_well_formed():
    """The closed vocabulary holds for all of expected.json, so the runner's rejection never hits a real case."""
    spec = importlib_run().__dict__
    exp = json.load(open(os.path.join(CONF, "expected.json")))["cases"]
    bad = {n: spec["entry_problems"](e) for n, e in exp.items() if spec["entry_problems"](e)}
    assert not bad, bad


def importlib_run():
    import importlib.util
    s = importlib.util.spec_from_file_location("kit_run", os.path.join(CONF, "run.py"))
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# ---- pending cases are visible, and can be run (drift-risk map finding 4)
def _result(tmp_path):
    return json.loads((tmp_path / "conformance" / "out" / "report.json").read_text())["results"]["rs"]["a1-anchor-translate"]


def test_a_pending_case_is_counted_in_the_summary(tmp_path):
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "pending": "why", "findings": {"valid": False}}),
                  _findings_engine())
    assert r.returncode == 0 and "1 case runs pending" in r.stdout and _result(tmp_path)["status"] == "pending", r.stdout


def test_run_pending_retires_a_pending_case_that_now_passes(tmp_path):
    entry = {"rule": "x", "pending": "engine did not pass it", "findings": {"valid": False}}
    r = _run_copy(tmp_path, _with_entry(tmp_path, entry), _findings_engine(), "--run-pending")
    assert r.returncode == 1 and "retire" in r.stdout and "kit_pending.py" in r.stdout, r.stdout
    assert _result(tmp_path)["status"] == "retire"


def test_run_pending_leaves_a_still_failing_case_pending(tmp_path):
    entry = {"rule": "x", "pending": "engine does not pass it", "findings": {"valid": True}}
    r = _run_copy(tmp_path, _with_entry(tmp_path, entry), _findings_engine(), "--run-pending")
    assert r.returncode == 0 and _result(tmp_path)["status"] == "pending", r.stdout
    assert "still not passing" in " ".join(_result(tmp_path)["notes"])


def test_run_pending_says_when_no_check_form_can_run_a_case(tmp_path):
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "pending": "a render comparison"}),
                  _findings_engine(), "--run-pending")
    assert r.returncode == 0 and "no check form can run it yet" in r.stdout, r.stdout


FAILING = "import sys\nsys.stderr.write('error PRG12: fuel exhausted\\n')\nsys.exit(3)\n"


def test_the_failure_form_passes_when_the_render_fails_with_the_code(tmp_path):
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "failure": {"code": "PRG12"}}), FAILING)
    assert r.returncode == 0 and " pass " in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("engine,why", [
    ("import sys\nsys.exit(0)\n", "exits 0"),
    ("import sys\nsys.stderr.write('error PRG11\\n')\nsys.exit(3)\n", "another code"),
    ("import sys\nfrom PIL import Image\nImage.new('RGB',(4,4)).save(sys.argv[sys.argv.index('-o') + 1])\n"
     "sys.stderr.write('PRG12\\n')\nsys.exit(3)\n", "draws a picture"),
])
def test_the_failure_form_fails_otherwise(tmp_path, engine, why):
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "failure": {"code": "PRG12"}}), engine)
    assert r.returncode == 1 and " fail " in r.stdout, (why, r.stdout)


def test_a_malformed_failure_entry_is_an_error(tmp_path):
    r = _run_copy(tmp_path, _with_entry(tmp_path, {"rule": "x", "failure": "PRG12"}), FAILING)
    assert r.returncode == 1 and _result(tmp_path)["status"] == "error"


def test_run_pending_retires_a_failed_render_case_the_engine_now_passes(tmp_path):
    entry = {"rule": "x", "pending": "cannot check failed renders", "failure": {"code": "PRG12"}}
    r = _run_copy(tmp_path, _with_entry(tmp_path, entry), FAILING, "--run-pending")
    assert r.returncode == 1 and _result(tmp_path)["status"] == "retire", r.stdout
