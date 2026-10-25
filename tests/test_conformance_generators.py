"""The kit generators reproduce the committed srep_cases/ exactly (drift-risk map finding 3).

conformance/tools/srep*_cases.py write srep_cases/srep-00NN.json and the assets those cases name; conformance/tools/
kit_pending.py decides which cases are `pending`. Nothing but a re-run showed whether a committed file was stale, and
only SREP 87's generator had a --check. Each generator is run here in a scratch copy and its output compared with
the committed files, so an edit to a generator or to kit_pending.py without a re-run fails.
"""
import filecmp
import glob
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "conformance")
TOOLS = os.path.join(CONF, "tools")
# engine_gap_cases.py measures a clone of the engine (--engine-repo); every other generator is offline
OFFLINE = sorted(os.path.basename(p) for p in glob.glob(os.path.join(TOOLS, "srep*_cases.py")))


def test_every_case_generator_is_either_offline_or_known_to_need_an_engine():
    others = sorted(os.path.basename(p) for p in glob.glob(os.path.join(TOOLS, "*_cases.py")))
    assert set(others) - set(OFFLINE) == {"engine_gap_cases.py"}
    assert len(OFFLINE) >= 15, OFFLINE


def _same_tree(a, b):
    cmp = filecmp.dircmp(a, b)
    bad = list(cmp.diff_files) + list(cmp.left_only) + list(cmp.right_only)
    for sub in cmp.common_dirs:
        bad += [f"{sub}/{x}" for x in _same_tree(os.path.join(a, sub), os.path.join(b, sub))]
    return bad


@pytest.mark.parametrize("script", OFFLINE)
def test_generator_reproduces_the_committed_cases(tmp_path, script):
    copy = tmp_path / "conformance"
    shutil.copytree(CONF, copy, ignore=shutil.ignore_patterns("out", "__pycache__"))
    r = subprocess.run([sys.executable, str(copy / "tools" / script)], capture_output=True, text=True, cwd=copy)
    assert r.returncode == 0, r.stderr[-400:]
    stale = _same_tree(os.path.join(CONF, "srep_cases"), str(copy / "srep_cases"))
    assert not stale, f"{script} writes different files than are committed: {stale}; re-run it and commit"


def test_every_pending_reason_in_kit_pending_is_in_expected_json():
    sys.path.insert(0, TOOLS)
    try:
        import kit_pending
    finally:
        sys.path.remove(TOOLS)
    exp = json.load(open(os.path.join(CONF, "expected.json")))["cases"]
    for name, why in kit_pending.PENDING.items():
        assert name in exp, name
        assert exp[name].get("pending") == why, name


def test_the_matte_choke_grow_and_resample_mitchell_cases_run_again():
    """SR-59 and SR-60 are fixed on the engine's feat/sr-67-fields at bb4e662 (the merge of perf/sr-70-denoise-prep):
    run.py --run-pending retires both on a release build of that snapshot, so neither is pending any more."""
    exp = json.load(open(os.path.join(CONF, "expected.json")))["cases"]
    for srep, name in (("0029", "srep-0029-matte-choke-grow"), ("0032", "srep-0032-resample-mitchell")):
        src = json.load(open(os.path.join(CONF, "srep_cases", f"srep-{srep}.json")))
        assert "pending" not in src[name]["expected"], name
        assert "pending" not in exp[name], name
        assert set(exp[name]) & {"regions"}, name
