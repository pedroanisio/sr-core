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
