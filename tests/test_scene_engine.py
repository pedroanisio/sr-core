"""Level 3 runner and engine_info (SREP 91 sections 6 and 7), tested against a fake engine script."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from sr_core.scene import _generated, engine
from sr_core.scene.engine import EngineError, EngineInfo, engine_info, level3
from sr_core.scene.findings import Finding

SCRIPT = '''#!{python}
import json, os, sys
cfg = json.load(open({cfg!r}))
cmd = sys.argv[1]
if cmd == "capabilities":
    sys.stdout.write(cfg["caps_out"]); sys.stderr.write(cfg.get("caps_err", ""))
    sys.exit(cfg.get("caps_exit", 0))
if cmd == "validate":
    f = sys.argv[-1]
    json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd(), "file": f, "content": open(f).read()}},
              open({log!r}, "w"))
    if cfg.get("hang"):
        import time; time.sleep(60)
    sys.stdout.write(cfg["out"]); sys.stderr.write(cfg.get("err", ""))
    sys.exit(cfg.get("exit", 0))
sys.exit(2)
'''


def caps(schema=_generated.SCHEMA_RELEASE, name="fake", version="9.9.9"):
    return json.dumps({"format": "scene-render-capabilities/1", "engine": {"name": name, "version": version},
                       "schema": schema, "entries": []})


def report(*diags, valid=None):
    return json.dumps({"valid": not diags if valid is None else valid,
                       "files": [{"file": "x", "valid": not diags, "errors": len(diags), "warnings": 0,
                                  "diagnostics": list(diags)}]})


DIAG = {"severity": "error", "code": "E-X", "message": "bad thing", "path": "/scene/composition/layer[2]",
        "loc": {"line": 4, "column": 7, "offset": 99}, "help": "h"}


@pytest.fixture
def make_engine(tmp_path):
    counter = [0]

    def make(**cfg):
        counter[0] += 1
        cfg.setdefault("caps_out", caps())
        cfg.setdefault("out", report())
        cfgp = tmp_path / f"cfg{counter[0]}.json"
        logp = tmp_path / f"fake-engine-{counter[0]}.log"
        cfgp.write_text(json.dumps(cfg))
        exe = tmp_path / f"fake-engine-{counter[0]}"
        exe.write_text(SCRIPT.format(python=sys.executable, cfg=str(cfgp), log=str(logp)))
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        return exe

    return make


@pytest.fixture(autouse=True)
def _clear_cache():
    engine._INFO_CACHE.clear()
    yield
    engine._INFO_CACHE.clear()


def log_of(exe):
    return exe.with_name(exe.name + ".log")


def codes(findings):
    return [f.code for f in findings]


# ------------------------------------------------------------------ engine_info

def test_engine_info_reads_manifest(make_engine):
    exe = make_engine(caps_out=caps(schema="1.6.2", name="fake", version="2.0.1"))
    info = engine_info(exe)
    assert isinstance(info, EngineInfo)
    assert (info.name, info.version, info.schema) == ("fake", "2.0.1", "1.6.2")
    assert info.path == Path(exe).resolve()
    with pytest.raises(Exception):
        info.name = "x"  # type: ignore[misc]


def test_engine_info_cached_per_path_and_mtime(make_engine):
    exe = make_engine()
    a = engine_info(exe)
    assert engine_info(str(exe)) is a
    st = exe.stat()
    os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert engine_info(exe) is not a


@pytest.mark.parametrize("kw", [
    {"caps_out": "not json"},
    {"caps_out": "[]"},
    {"caps_out": json.dumps({"format": "other/1", "engine": {"name": "a", "version": "1"}, "schema": "1.7.0"})},
    {"caps_out": json.dumps({"format": "scene-render-capabilities/1", "engine": {"name": "a"}, "schema": "1.7.0"})},
    {"caps_out": caps(), "caps_exit": 3, "caps_err": "boom"},
])
def test_engine_info_errors(make_engine, kw):
    with pytest.raises(EngineError):
        engine_info(make_engine(**kw))


def test_engine_info_missing_and_not_executable(tmp_path):
    with pytest.raises(EngineError, match="not found|cannot run"):
        engine_info(tmp_path / "nope")
    plain = tmp_path / "plain"
    plain.write_text("x")
    with pytest.raises(EngineError):
        engine_info(plain)


def test_engine_info_timeout(make_engine, monkeypatch):
    exe = make_engine()
    exe.write_text(f"#!{sys.executable}\nimport time; time.sleep(30)\n")
    with pytest.raises(EngineError, match="timed out"):
        engine_info(exe, timeout=0.5)


# ------------------------------------------------------------------ level3

def test_level3_valid_document_no_findings(make_engine):
    exe = make_engine()
    assert level3(b"<scene/>", exe) == []


def test_level3_maps_diagnostics_unchanged(make_engine):
    warn = {"severity": "warning", "code": "W-Y", "message": "hmm", "path": "/scene",
            "loc": {"line": 1, "column": 1, "offset": 0}}
    exe = make_engine(out=report(DIAG, warn), exit=1)
    got = level3(b"<scene/>", exe)
    assert got == [Finding("error", "E-X", "bad thing", "/scene/composition/layer[2]", 4, 7),
                   Finding("warning", "W-Y", "hmm", "/scene", 1, 1)]


def test_level3_diagnostic_without_loc_or_path(make_engine):
    d = {"severity": "info", "code": "I-Z", "message": "m"}
    got = level3(b"<scene/>", make_engine(out=report(d), exit=1))
    assert got == [Finding("info", "I-Z", "m", None, None, None)]


def test_level3_passes_bytes_and_format_flags(make_engine, tmp_path):
    exe = make_engine()
    level3(b"<scene>\xc3\xa9</scene>", exe)
    log = json.loads(log_of(exe).read_text())
    assert log["argv"][:3] == ["validate", "--format", "json"]
    assert "--no-assets" in log["argv"]  # no data directory: relative assets cannot resolve
    assert "--deny-warnings" not in log["argv"]
    assert log["content"] == "<scene>é</scene>"
    assert not Path(log["file"]).exists()  # temp file removed


def test_level3_data_dir_holds_temp_file_and_enables_assets(make_engine, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    exe = make_engine()
    level3(b"<scene/>", exe, data=data)
    log = json.loads(log_of(exe).read_text())
    assert Path(log["file"]).parent == data.resolve() or Path(log["file"]).parent == data
    assert "--no-assets" not in log["argv"]
    assert list(data.iterdir()) == []  # cleaned up


def test_level3_temp_removed_on_engine_failure(make_engine, tmp_path):
    data = tmp_path / "d"
    data.mkdir()
    level3(b"<scene/>", make_engine(exit=2, out=""), data=data)
    assert list(data.iterdir()) == []


def test_level3_missing_data_dir(make_engine, tmp_path):
    got = level3(b"<scene/>", make_engine(), data=tmp_path / "absent")
    assert codes(got) == ["sdk:engine-failed"]


def test_level3_exit2_is_engine_failed_with_stderr(make_engine):
    got = level3(b"<scene/>", make_engine(exit=2, out="", err="usage: cannot read file\n"))
    assert len(got) == 1 and got[0].severity == "error" and got[0].code == "sdk:engine-failed"
    assert "cannot read file" in got[0].message


def test_level3_invalid_json_is_engine_failed(make_engine):
    got = level3(b"<scene/>", make_engine(out="garbage", exit=0, err="trace"))
    assert codes(got) == ["sdk:engine-failed"]
    assert "trace" in got[0].message


@pytest.mark.parametrize("out", ["[]", json.dumps({"valid": True}), json.dumps({"files": "x"}),
                                 json.dumps({"files": [{"diagnostics": [{"code": "x"}]}]})])
def test_level3_wrong_shape_is_engine_failed(make_engine, out):
    assert codes(level3(b"<scene/>", make_engine(out=out))) == ["sdk:engine-failed"]


def test_level3_stderr_excerpt_is_bounded(make_engine):
    got = level3(b"<scene/>", make_engine(exit=2, out="", err="x" * 10000))
    assert len(got[0].message) < 2000


def test_level3_unusable_engine_is_engine_failed(tmp_path):
    got = level3(b"<scene/>", tmp_path / "nope")
    assert codes(got) == ["sdk:engine-failed"]


def test_level3_validate_timeout(make_engine):
    exe = make_engine(hang=True)
    got = level3(b"<scene/>", exe, timeout=0.5)
    assert codes(got) == ["sdk:engine-failed"] and "timed out" in got[0].message


def test_level3_schema_skew_warning(make_engine):
    exe = make_engine(caps_out=caps(schema="1.8.0"))
    got = level3(b"<scene/>", exe)
    assert [(f.severity, f.code) for f in got] == [("warning", "sdk:schema-skew")]
    assert "1.8.0" in got[0].message and _generated.SCHEMA_RELEASE in got[0].message


def test_level3_no_skew_when_equal(make_engine):
    exe = make_engine(caps_out=caps(schema=_generated.SCHEMA_RELEASE))
    assert level3(b"<scene/>", exe) == []


def test_level3_engine_older_than_document(make_engine):
    exe = make_engine(caps_out=caps(schema="1.5.3"))
    got = level3(b"<scene/>", exe, document_version="1.7")
    assert ("error", "sdk:engine-version") in [(f.severity, f.code) for f in got]
    assert "sdk:schema-skew" in codes(got)


@pytest.mark.parametrize("schema,doc,expect", [
    ("1.7.0", "1.7", False), ("1.7.9", "1.7", False), ("1.8.0", "1.7", False), ("2.0.0", "1.7", False),
    ("1.6.9", "1.7", True), ("1.7.0", "2.0", True), ("1.10.0", "1.9", False), ("1.9.0", "1.10", True),
    ("1.0.0", "auto", False), ("1.0.0", None, False), ("1.0.0", "garbage", False),
])
def test_engine_version_comparison(make_engine, schema, doc, expect):
    got = level3(b"<scene/>", make_engine(caps_out=caps(schema=schema)), document_version=doc)
    assert ("sdk:engine-version" in codes(got)) is expect


def test_level3_order_engine_diagnostics_then_sdk(make_engine):
    exe = make_engine(caps_out=caps(schema="1.0.0"), out=report(DIAG), exit=1)
    assert codes(level3(b"<scene/>", exe, document_version="1.7")) == ["E-X", "sdk:schema-skew", "sdk:engine-version"]
