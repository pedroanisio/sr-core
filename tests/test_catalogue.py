"""SREP 12 milestone 0 (SRC-17): the benchmark catalogue's probe scenes and the scoring script.

conformance/tools/srep12_cases.py lists the 36 shots of SREP 12 Appendix A (SHOTS) and writes one probe scene per shot
to srep_cases/srep-0012.json. conformance/catalogue.py scores the probes on an engine: a shot is native when its probe
renders under --strict with nothing reported as not rendered as authored, meets its pixel checks, and passes the seek
check of SREP 14 (the frame rendered alone equals the same frame rendered after playing from the start). A shot whose
probe needs custom work is "custom" and one whose defining element has no syntax is "gap", whatever the engine does.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "conformance")
TOOLS = os.path.join(CONF, "tools")
GENERATOR = os.path.join(TOOLS, "srep12_cases.py")
SCORER = os.path.join(CONF, "catalogue.py")
SREP12 = os.path.join(ROOT, "srep", "srep-0012.md")
CASES_FILE = os.path.join(CONF, "srep_cases", "srep-0012.json")


def _load(path, name):
    if name == "srep12_cases" and TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)             # the generators import kit_pending from their own directory
    if name == "catalogue" and CONF not in sys.path:
        sys.path.insert(0, CONF)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def shots():
    return _load(GENERATOR, "srep12_cases").SHOTS


@pytest.fixture(scope="module")
def scorer():
    return _load(SCORER, "catalogue")


@pytest.fixture(scope="module")
def kit_run():
    return _load(os.path.join(CONF, "run.py"), "kit_run")


# ---- the shot table


def test_the_generator_lists_the_36_shots_of_appendix_a(shots):
    assert [s["n"] for s in shots] == list(range(1, 37))
    slugs = [s["slug"] for s in shots]
    assert len(set(slugs)) == 36
    for s in shots:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s["slug"]), s["slug"]
        assert {"n", "slug", "channel", "video", "url", "shot", "track", "estimate", "technique",
                "seek_frame"} <= set(s), s["n"]
        assert s["estimate"] in ("native", "custom", "gap"), s["n"]
        assert not (s.get("custom") and s.get("gap")), f"shot {s['n']} is both custom and gap"
        assert isinstance(s["seek_frame"], int) and s["seek_frame"] >= 1, s["n"]
        assert isinstance(s["check_frame"], int) and 0 <= s["check_frame"] <= s["seek_frame"], s["n"]
        assert s["technique"], s["n"]
        for flag in ("custom", "gap"):
            if flag in s:
                assert isinstance(s[flag], str) and s[flag], f"shot {s['n']}: {flag} wants its reason"


def _appendix_rows():
    text = open(SREP12, encoding="utf-8").read()
    body = text[text.index("## Appendix A"):]
    rows = []
    for line in body.splitlines():
        m = re.match(r"\| (\d+) \| ([^|]+) \| \[([^\]]+)\]\((https?://[^)]+)\) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$", line)
        if m:
            rows.append({"n": int(m.group(1)), "channel": m.group(2).strip(), "video": m.group(3).strip(),
                         "url": m.group(4), "shot": m.group(5).strip(), "track": m.group(6).strip(),
                         "today": m.group(7).strip(), "milestone": m.group(8).strip()})
    return rows


def test_the_shots_are_the_rows_of_the_srep_table(shots):
    rows = _appendix_rows()
    assert [r["n"] for r in rows] == list(range(1, 37))
    for s, r in zip(shots, rows):
        assert (s["channel"], s["video"], s["url"]) == (r["channel"], r["video"], r["url"]), s["n"]
        assert s["shot"] == r["shot"], s["n"]
        assert s["track"] == r["track"], s["n"]


def test_the_srep_table_carries_the_measured_status_of_every_shot(shots):
    """Milestone 0 replaces the estimates: each row's Today cell names the measured status and its probe."""
    for s, r in zip(shots, _appendix_rows()):
        status = r["today"].split(" ")[0].rstrip(",;:")
        assert status in ("native", "custom", "gap", "degraded", "wrong", "error"), (s["n"], r["today"])
        assert "estimate" not in r["today"], (s["n"], r["today"])
        assert f"srep-0012-shot-{s['n']:02d}" in r["today"] or "probe" in r["today"], (s["n"], r["today"])


# ---- the probes


def test_the_generator_writes_one_probe_per_shot(tmp_path, shots, kit_run):
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    r = subprocess.run([sys.executable, str(copy / "tools" / "srep12_cases.py")], capture_output=True, text=True,
                       cwd=copy)
    assert r.returncode == 0, r.stderr[-600:]
    cases = json.load(open(copy / "srep_cases" / "srep-0012.json"))
    assert list(cases) == [f"srep-0012-shot-{s['n']:02d}-{s['slug']}" for s in shots]
    for s in shots:
        case = cases[f"srep-0012-shot-{s['n']:02d}-{s['slug']}"]
        assert case["expected"]["rule"].startswith(f"SREP 12 Appendix A, shot {s['n']}"), s["n"]
        assert kit_run.entry_problems(case["expected"]) == [], (s["n"], kit_run.entry_problems(case["expected"]))
        assert "pending" not in case["expected"] or isinstance(case["expected"]["pending"], str)


def test_every_committed_probe_validates_against_the_schema_and_its_rules():
    from srep_support import verdict12
    cases = json.load(open(CASES_FILE))
    assert len(cases) == 36
    bad = {n: verdict12(c["xml"]) for n, c in cases.items() if verdict12(c["xml"]) != "ok"}
    assert not bad, bad


def test_every_probe_names_the_kit_assets_it_uses_from_the_assets_directory():
    cases = json.load(open(CASES_FILE))
    assets = set(os.listdir(os.path.join(CONF, "srep_cases", "assets")))
    for name, c in cases.items():
        for ref in re.findall(r'"\.\./assets/([^"]+)"', c["xml"]):
            assert ref in assets, (name, ref)


# ---- the scorer: classification


@pytest.mark.parametrize("strict, checks, seek, shot, want", [
    ("pass", True, True, {}, "native"),
    ("pass", True, True, {"custom": "hand-keyed motion"}, "custom"),
    ("pass", True, True, {"gap": "no field element"}, "gap"),
    ("fallback", True, True, {}, "degraded"),
    ("fallback", True, True, {"custom": "x"}, "degraded"),
    ("fallback", True, True, {"gap": "x"}, "gap"),
    ("pass", False, True, {}, "wrong"),
    ("pass", True, False, {}, "wrong"),
    ("pass", False, True, {"custom": "x"}, "wrong"),
    ("error", True, True, {}, "error"),
    ("error", True, True, {"gap": "x"}, "error"),
    ("fallback", False, False, {}, "degraded"),
])
def test_classify(scorer, strict, checks, seek, shot, want):
    assert scorer.classify(strict, checks, seek, shot) == want


def test_the_outcomes_are_the_closed_vocabulary(scorer):
    assert scorer.OUTCOMES == ("native", "custom", "gap", "degraded", "wrong", "error")


@pytest.mark.parametrize("stdout, code, want", [
    ('{"format":"scene-render-cli/1","ok":true,"exit_code":0,"error":null,"result":{"unsupported":[],"written":[{"path":"f.png"}]}}',
     0, ("pass", [])),
    ('{"format":"scene-render-cli/1","ok":false,"exit_code":1,"error":{"kind":"failed","codes":[],"message":"--strict: 1 item(s) not rendered as authored"},'
     '"result":{"unsupported":["fx: GLSL compile/link failed; passed through."],"written":[{"path":"f.png"}]}}',
     1, ("fallback", ["fx: GLSL compile/link failed; passed through."])),
    ('{"format":"scene-render-cli/1","ok":false,"exit_code":1,"error":{"kind":"invalid","codes":["A01"],"message":"x.xml: 1 error(s)"},"result":null}',
     1, ("error", ["x.xml: 1 error(s)"])),
    ("not json", 0, ("error", ["not json"])),
    ('{"format":"other/9","ok":true,"exit_code":0,"error":null,"result":{}}', 0, ("error", ["unknown output format 'other/9'"])),
    ("", 2, ("error", ["exit status 2"])),
])
def test_strict_verdict_reads_the_cli_envelope(scorer, stdout, code, want):
    assert scorer.strict_verdict(stdout, code) == want


# ---- the scorer on a stand-in engine


def _fake_engine(body):
    """A stand-in scene-render: `render SCENE (-f N | --frames A..=B) -o PATH [--strict] [--format json]`. `body`
    is Python run with `frame` (int), `strict` (bool), `path` (the PNG to write) and `played` (True when the frame
    is rendered by playing from the start) in scope; it must write `path`. It may set `envelope` (a dict printed as
    the JSON envelope) and `code` (the exit status)."""
    return ("import json, os, sys\nfrom PIL import Image, ImageDraw\n"
            "a = sys.argv\nassert a[1] == 'render', a\n"
            "strict = '--strict' in a\nout = a[a.index('-o') + 1]\n"
            "frames = [int(a[a.index('-f') + 1])] if '-f' in a else None\nplayed = False\n"
            "if '--frames' in a:\n"
            "    lo, hi = a[a.index('--frames') + 1].split('..=')\n"
            "    frames = list(range(int(lo), int(hi) + 1)); played = True\n"
            "code = 0\nenvelope = None\n"
            "for frame in frames:\n"
            "    path = out % frame if '%' in out else out\n"
            + "\n".join("    " + ln for ln in body.splitlines()) + "\n"
            "if '--format' in a and a[a.index('--format') + 1] == 'json':\n"
            "    print(json.dumps(envelope or {'format': 'scene-render-cli/1', 'ok': code == 0, 'exit_code': code,"
            " 'error': None, 'result': {'unsupported': [], 'written': [{'path': out}]}}))\n"
            "sys.exit(code)\n")


RED_SQUARE = ("im = Image.new('RGB', (640, 360))\nImageDraw.Draw(im).rectangle([310, 170, 329, 189], fill=(255, 0, 0))\n"
              "im.save(path)\n")


def _run_catalogue(tmp_path, engine_body, shot_n, expected=None, via_run_py=False):
    """Score shot `shot_n` on the stand-in engine; its expected entry is replaced by `expected` when given."""
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    if expected is not None:
        spec = json.loads((copy / "expected.json").read_text())
        name = [c for c in spec["cases"] if c.startswith(f"srep-0012-shot-{shot_n:02d}-")][0]
        spec["cases"][name] = expected
        (copy / "expected.json").write_text(json.dumps(spec))
    eng = tmp_path / "engine"
    eng.write_text(f"#!{sys.executable}\n{_fake_engine(engine_body)}")
    eng.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "RS_RENDER_BIN"}
    env["PATH"] = str(tmp_path / "empty")
    env["RS_RENDER_BIN"] = str(eng)
    script = [str(copy / "run.py"), "--catalogue"] if via_run_py else [str(copy / "catalogue.py")]
    r = subprocess.run([sys.executable, *script, "--renderers", "rs", "--shots", str(shot_n)],
                       capture_output=True, text=True, env=env)
    report = json.loads((copy / "out" / "catalogue.json").read_text()) if (copy / "out" / "catalogue.json").exists() else None
    return r, report


RED_AT_CENTRE = {"rule": "SREP 12 Appendix A, shot 0 (test)", "red": {"cx": 320, "cy": 180, "w": 20, "h": 20, "px": 400}}


def _plain_shot(shots):
    return [s for s in shots if not s.get("custom") and not s.get("gap")][0]["n"]


def test_a_probe_that_renders_checks_and_seeks_is_native(tmp_path, shots):
    pytest.importorskip("PIL")
    n = _plain_shot(shots)
    r, report = _run_catalogue(tmp_path, RED_SQUARE, n, RED_AT_CENTRE)
    assert r.returncode == 0, r.stdout + r.stderr
    row = report["shots"][str(n)]
    assert row["outcome"] == "native" and row["strict"] == "pass" and row["seek"] is True, row
    assert all(c["status"] == "pass" for c in row["checks"]), row
    assert "catalogue: 1 of 1 shots native" in r.stdout, r.stdout


def test_the_pixel_checks_look_at_the_shots_check_frame(tmp_path, shots):
    """A probe whose content needs time to appear names a check frame; the strict render is that frame, alone."""
    pytest.importorskip("PIL")
    s = [s for s in shots if s["check_frame"] > 0][0]
    body = (f"im = Image.new('RGB', (640, 360))\n"
            f"if frame == {s['check_frame']}: ImageDraw.Draw(im).rectangle([310, 170, 329, 189], fill=(255, 0, 0))\n"
            "if frame > 0: im.putpixel((5, 5), (1, 1, 1))\nim.save(path)\n")
    r, report = _run_catalogue(tmp_path, body, s["n"], RED_AT_CENTRE)
    row = report["shots"][str(s["n"])]
    assert row["check_frame"] == s["check_frame"] and row["strict"] == "pass", row
    assert all(c["status"] == "pass" for c in row["checks"]), row
    assert row["seek"] is True and row["outcome"] in ("custom", "gap", "native"), row


def test_a_custom_shot_stays_custom_when_its_probe_is_native(tmp_path, shots):
    pytest.importorskip("PIL")
    n = [s for s in shots if s.get("custom")][0]["n"]
    r, report = _run_catalogue(tmp_path, RED_SQUARE, n, RED_AT_CENTRE)
    assert report["shots"][str(n)]["outcome"] == "custom", report["shots"][str(n)]
    assert "catalogue: 0 of 1 shots native (custom 1" in r.stdout, r.stdout


def test_a_gap_shot_stays_gap(tmp_path, shots):
    pytest.importorskip("PIL")
    n = [s for s in shots if s.get("gap")][0]["n"]
    r, report = _run_catalogue(tmp_path, RED_SQUARE, n, RED_AT_CENTRE)
    assert report["shots"][str(n)]["outcome"] == "gap", report["shots"][str(n)]


def test_a_strict_fallback_is_degraded(tmp_path, shots):
    pytest.importorskip("PIL")
    n = _plain_shot(shots)
    body = RED_SQUARE + ("if strict:\n    code = 1\n    envelope = {'format': 'scene-render-cli/1', 'ok': False, 'exit_code': 1,"
                         " 'error': {'kind': 'failed', 'codes': [], 'message': '--strict: 1 item(s) not rendered as authored'},"
                         " 'result': {'unsupported': ['fx: passed through'], 'written': [{'path': path}]}}\n")
    r, report = _run_catalogue(tmp_path, body, n, RED_AT_CENTRE)
    row = report["shots"][str(n)]
    assert row["outcome"] == "degraded" and row["strict"] == "fallback" and row["unsupported"] == ["fx: passed through"], row
    assert r.returncode == 0, r.stdout + r.stderr     # the score is a measurement, not a gate


def test_a_failed_pixel_check_is_wrong(tmp_path, shots):
    pytest.importorskip("PIL")
    n = _plain_shot(shots)
    green = RED_SQUARE.replace("(255, 0, 0)", "(0, 255, 0)")
    r, report = _run_catalogue(tmp_path, green, n, RED_AT_CENTRE)
    row = report["shots"][str(n)]
    assert row["outcome"] == "wrong" and row["strict"] == "pass" and row["seek"] is True, row


def test_a_frame_that_differs_when_played_from_the_start_fails_the_seek_check(tmp_path, shots):
    pytest.importorskip("PIL")
    n = _plain_shot(shots)
    body = ("im = Image.new('RGB', (640, 360))\nImageDraw.Draw(im).rectangle([310, 170, 329, 189], fill=(255, 0, 0))\n"
            "if played and frame > 0: im.putpixel((5, 5), (1, 1, 1))\n"      # one code value in one pixel
            "im.save(path)\n")
    r, report = _run_catalogue(tmp_path, body, n, RED_AT_CENTRE)
    row = report["shots"][str(n)]
    assert row["outcome"] == "wrong" and row["seek"] is False and row["checks"][0]["status"] == "pass", row
    assert row["seek_frame"] == [s for s in shots if s["n"] == n][0]["seek_frame"]
    assert any("seek" in note for note in row["notes"]), row


def test_an_engine_that_fails_is_an_error(tmp_path, shots):
    pytest.importorskip("PIL")
    n = _plain_shot(shots)
    r, report = _run_catalogue(tmp_path, "code = 3\n", n, RED_AT_CENTRE)
    row = report["shots"][str(n)]
    assert row["outcome"] == "error", row
    assert "Traceback" not in r.stderr


def test_run_py_reports_the_native_count(tmp_path, shots):
    pytest.importorskip("PIL")
    n = _plain_shot(shots)
    r, report = _run_catalogue(tmp_path, RED_SQUARE, n, RED_AT_CENTRE, via_run_py=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "catalogue: 1 of 1 shots native" in r.stdout
    assert (tmp_path / "conformance" / "out" / "catalogue.md").exists()


def test_the_markdown_report_has_one_row_per_shot_with_its_outcome(tmp_path, shots):
    pytest.importorskip("PIL")
    n = _plain_shot(shots)
    _run_catalogue(tmp_path, RED_SQUARE, n, RED_AT_CENTRE)
    md = (tmp_path / "conformance" / "out" / "catalogue.md").read_text()
    assert re.search(rf"^\| {n} \| .* \| native \|", md, re.M), md


# ---- the coverage form of run.py, which the simulation probes need


@pytest.mark.parametrize("entry, ok", [
    ({"coverage": [{"colour": "red", "box": [0, 0, 10, 10], "min": 0.5}]}, True),
    ({"coverage": [{"colour": "lit", "box": [0, 0, 10, 10], "min": 0.1, "max": 0.9}]}, True),
    ({"coverage": [{"colour": "dark", "box": [0, 0, 10, 10], "max": 0.2}]}, True),
    ({"coverage": [{"colour": "red", "box": [0, 0, 10, 10]}]}, False),              # no bound
    ({"coverage": [{"colour": "pink", "box": [0, 0, 10, 10], "min": 0.5}]}, False),  # not a class
    ({"coverage": [{"colour": "red", "box": [0, 0, 10], "min": 0.5}]}, False),       # bad box
    ({"coverage": [{"colour": "red", "box": [10, 0, 0, 10], "min": 0.5}]}, False),   # empty box
    ({"coverage": [{"colour": "red", "box": [0, 0, 10, 10], "min": 1.5}]}, False),   # out of [0, 1]
    ({"coverage": [{"colour": "red", "box": [0, 0, 10, 10], "min": 0.5, "why": "x"}]}, False),  # unknown key
    ({"coverage": {"colour": "red", "box": [0, 0, 10, 10], "min": 0.5}}, False),     # not a list
    ({"coverage": []}, False),
])
def test_entry_problems_on_the_coverage_form(kit_run, entry, ok):
    problems = kit_run.entry_problems({"rule": "SREP 12", **entry})
    assert (problems == []) == ok, problems


def test_coverage_is_the_fraction_of_the_box_in_the_colour_class(tmp_path, kit_run):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    im = Image.new("RGB", (640, 360))
    ImageDraw.Draw(im).rectangle([0, 0, 99, 49], fill=(255, 0, 0))      # the left half of a 200 x 50 box
    ImageDraw.Draw(im).rectangle([100, 0, 149, 49], fill=(90, 90, 90))  # a quarter lit grey
    png = tmp_path / "f.png"
    im.save(png)
    assert kit_run.coverage(str(png), "red", [0, 0, 200, 50]) == pytest.approx(0.5)
    assert kit_run.coverage(str(png), "lit", [0, 0, 200, 50]) == pytest.approx(0.75)
    assert kit_run.coverage(str(png), "dark", [0, 0, 200, 50]) == pytest.approx(0.25)
    exp = {"coverage": [{"colour": "red", "box": [0, 0, 200, 50], "min": 0.5},
                        {"colour": "red", "box": [0, 0, 200, 50], "min": 0.6},
                        {"colour": "lit", "box": [0, 0, 200, 50], "max": 0.5}]}
    rows = kit_run.check(kit_run.measure(str(png)), exp, 2.0, str(png))
    assert [r[1] for r in rows] == ["pass", "fail", "fail"], rows
    assert rows[0][0] == "coverage0" and rows[0][3] == {"fraction": 0.5}, rows[0]


def test_a_coverage_case_runs_through_run_py(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    spec = json.loads((copy / "expected.json").read_text())
    spec["cases"]["a1-anchor-translate"] = {"rule": "SREP 12", "coverage": [{"colour": "red", "box": [300, 160, 340, 200], "min": 0.9}]}
    (copy / "expected.json").write_text(json.dumps(spec))
    eng = tmp_path / "engine"
    eng.write_text(f"#!{sys.executable}\nimport sys\nfrom PIL import Image, ImageDraw\n"
                   "im = Image.new('RGB', (640, 360))\nImageDraw.Draw(im).rectangle([300, 160, 339, 199], fill=(255, 0, 0))\n"
                   "im.save(sys.argv[sys.argv.index('-o') + 1])\n")
    eng.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "RS_RENDER_BIN"}
    env["PATH"] = str(tmp_path / "empty")
    env["RS_RENDER_BIN"] = str(eng)
    r = subprocess.run([sys.executable, str(copy / "run.py"), "--renderers", "rs", "--cases", "a1-anchor-translate"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "pass" in r.stdout, r.stdout + r.stderr
    spec["cases"]["a1-anchor-translate"]["coverage"][0]["colour"] = "green"
    (copy / "expected.json").write_text(json.dumps(spec))
    r = subprocess.run([sys.executable, str(copy / "run.py"), "--renderers", "rs", "--cases", "a1-anchor-translate"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "fail" in r.stdout, r.stdout + r.stderr
