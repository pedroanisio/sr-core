"""The 1.5.0 baseline of SREPs 76 to 85 does not depend on a git tag (drift-risk map finding 8).

The tests of those SREPs used to skip their whole module when `git` had no tag `schema-1.5.0` and `schema/` had moved
on, which is exactly the state of an unpacked sdist or a shallow clone. The 1.5.0 files are now committed in
conformance/tools/baseline-1.5.0/ and must hash to the inventory.
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "conformance", "tools"))
import engine_gap as gap  # noqa: E402


def _no_tag(*a, **k):
    raise subprocess.CalledProcessError(128, "git show")


def test_the_baseline_is_available_without_the_tag(monkeypatch):
    with_tag = gap.baseline()
    monkeypatch.setattr(gap, "git_bytes", _no_tag)
    without = gap.baseline()
    assert without is not None and without == with_tag


def test_the_committed_baseline_hashes_to_the_inventory():
    want = {p: v["base_sha256"] for p, v in json.load(open(gap.DEFAULT_OUT))["files"].items()}
    for path in gap.FILES:
        data = open(os.path.join(gap.BASELINE_DIR, os.path.basename(path)), "rb").read()
        assert hashlib.sha256(data).hexdigest() == want[path], path


def test_a_wrong_committed_copy_is_refused_not_used(monkeypatch, tmp_path):
    for name in ("scene-render.xsd", "scene-render.sch"):
        (tmp_path / name).write_bytes(open(os.path.join(gap.BASELINE_DIR, name), "rb").read() + b"\n")
    monkeypatch.setattr(gap, "git_bytes", _no_tag)
    monkeypatch.setattr(gap, "BASELINE_DIR", str(tmp_path))
    assert gap.baseline() is None


def test_no_tag_and_no_copy_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr(gap, "git_bytes", _no_tag)
    monkeypatch.setattr(gap, "BASELINE_DIR", str(tmp_path / "missing"))
    assert gap.baseline() is None


def test_the_tests_of_the_dependent_sreps_cannot_skip_on_a_missing_baseline():
    for n in ("0076_0081", "0083", "0084", "0085"):
        name = f"test_srep_{n}.py"
        text = open(os.path.join(ROOT, "tests", name), encoding="utf-8").read()
        assert "gap.baseline() is not None" in text, name
        assert "the schema 1.5.0 files are not available" not in text, name
