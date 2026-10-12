"""The ``sr-scene`` command (SREP 91 section 8)."""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import sr_core
from sr_core.scene import _generated, cli
from sr_core.scene.findings import Finding

COMPACT = b'<scene version="1.7"><output><video width="2" height="2" fps="1"/></output></scene>'
PRETTY = (b'<?xml version="1.0" encoding="UTF-8"?>\n<scene version="1.7">\n  <output>\n'
          b'    <video width="2" height="2" fps="1"/>\n  </output>\n</scene>\n')
BOGUS = b'<scene version="1.7"><bogus/></scene>'

ERR = Finding("error", "xsd:element", "no such element", "/scene/bogus", 1, 22)
WARN = Finding("warning", "sdk:schema-skew", "skew")


@pytest.fixture(scope="module")
def have_real_checks():
    try:
        from sr_core.scene import checks  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture
def stub_checks(monkeypatch):
    """A recording replacement for sr_core.scene.checks, installed over the real module when there is one."""
    calls = []
    mod = types.ModuleType("sr_core.scene.checks")
    mod.results = {}

    def check(scene, *, schema=False, engine=None, data=None):
        calls.append({"schema": schema, "engine": engine, "data": data, "version": scene.attributes().get("version")})
        return list(mod.results.get(scene.attributes().get("version"), []))

    mod.check = check
    mod.min_version = lambda scene: "1.3"
    mod.calls = calls
    monkeypatch.setitem(sys.modules, "sr_core.scene.checks", mod)
    import sr_core.scene as pkg
    monkeypatch.setattr(pkg, "checks", mod, raising=False)
    return mod


@pytest.fixture
def doc(tmp_path):
    def make(content=COMPACT, name="a.xml"):
        p = tmp_path / name
        p.write_bytes(content)
        return str(p)
    return make


# ------------------------------------------------------------------ check

def test_check_valid_exit_0(stub_checks, doc, capsys):
    assert cli.main(["check", doc()]) == 0
    assert "a.xml: ok" in capsys.readouterr().out


@pytest.mark.parametrize("flags, said", [([], "ok (level 1)"), (["--schema"], "ok (levels 1, 2)"),
                                         (["--engine", "e"], "ok (levels 1, 3)"),
                                         (["--schema", "--engine", "e"], "ok (levels 1, 2, 3)")])
def test_check_ok_names_the_levels_that_ran(stub_checks, doc, capsys, flags, said):
    # review R6: level 1 alone runs the gate asserts, not the whole Schematron; a bare "ok" overstated it
    f = doc()
    assert cli.main(["check", f, *flags]) == 0
    assert capsys.readouterr().out.splitlines() == [f"{f}: {said}"]


def test_check_json_names_the_levels_that_ran(stub_checks, doc, capsys):
    assert cli.main(["check", doc(), "--schema", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["levels"] == [1, 2]


def test_check_errors_exit_1_human(stub_checks, doc, capsys):
    stub_checks.results["1.7"] = [ERR]
    f = doc()
    assert cli.main(["check", f]) == 1
    out = capsys.readouterr().out
    assert f"{f}:1:22: error: xsd:element: /scene/bogus: no such element" in out


def test_check_warnings_alone_exit_0_unless_deny(stub_checks, doc):
    stub_checks.results["1.7"] = [WARN]
    f = doc()
    assert cli.main(["check", f]) == 0
    assert cli.main(["check", f, "--deny-warnings"]) == 1


def test_check_info_never_fails(stub_checks, doc):
    stub_checks.results["1.7"] = [Finding("info", "i", "m")]
    assert cli.main(["check", doc(), "--deny-warnings"]) == 0


def test_check_passes_options(stub_checks, doc, tmp_path):
    cli.main(["check", doc(), "--schema", "--engine", "/e/x", "--data", str(tmp_path)])
    assert stub_checks.calls[-1] == {"schema": True, "engine": "/e/x", "data": str(tmp_path), "version": "1.7"}
    cli.main(["check", doc()])
    assert stub_checks.calls[-1]["schema"] is False and stub_checks.calls[-1]["engine"] is None


def test_check_data_without_engine_is_usage_error(stub_checks, doc, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["check", doc(), "--data", "."])
    assert e.value.code == 2


def test_check_json_format(stub_checks, doc, capsys):
    stub_checks.results["1.7"] = [ERR, WARN]
    f = doc()
    assert cli.main(["check", f, "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert payload["files"] == [{"file": f, "valid": False, "findings": [ERR.to_dict(), WARN.to_dict()]}]


def test_check_json_valid(stub_checks, doc, capsys):
    assert cli.main(["check", doc(), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True and payload["files"][0]["findings"] == []


def test_check_missing_file_exit_2(stub_checks, tmp_path, capsys):
    assert cli.main(["check", str(tmp_path / "nope.xml")]) == 2
    assert "nope.xml" in capsys.readouterr().err


def test_check_malformed_xml_exit_2_and_continues(stub_checks, doc, capsys):
    bad = doc(b"<scene", "bad.xml")
    good = doc()
    stub_checks.results["1.7"] = [ERR]
    assert cli.main(["check", bad, good]) == 2  # read error outranks findings
    cap = capsys.readouterr()
    assert "bad.xml" in cap.err and "xsd:element" in cap.out


def test_check_json_read_error_listed(stub_checks, tmp_path, capsys):
    assert cli.main(["check", str(tmp_path / "nope.xml"), "--format", "json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False and payload["files"][0]["error"]


def test_check_requires_file():
    with pytest.raises(SystemExit) as e:
        cli.main(["check"])
    assert e.value.code == 2


# ------------------------------------------------------------------ min-version

def test_min_version(stub_checks, doc, capsys):
    a, b = doc(name="a.xml"), doc(name="b.xml")
    assert cli.main(["min-version", a, b]) == 0
    assert capsys.readouterr().out.splitlines() == [f"{a}: 1.3", f"{b}: 1.3"]


def test_min_version_read_error(stub_checks, tmp_path, capsys):
    assert cli.main(["min-version", str(tmp_path / "x.xml")]) == 2


# ------------------------------------------------------------------ format

def test_format_rewrites_in_place(doc, capsys):
    f = doc()
    assert cli.main(["format", f]) == 0
    assert Path(f).read_bytes() == PRETTY
    assert "formatted" in capsys.readouterr().out
    assert cli.main(["format", f]) == 0  # idempotent
    assert Path(f).read_bytes() == PRETTY


def test_format_check_reports_without_writing(doc, capsys):
    f = doc()
    assert cli.main(["format", f, "--check"]) == 1
    assert Path(f).read_bytes() == COMPACT
    assert f in capsys.readouterr().out


def test_format_check_clean_exit_0(doc):
    assert cli.main(["format", doc(PRETTY), "--check"]) == 0


def test_format_unchanged_file_not_touched(doc):
    f = doc(PRETTY)
    before = Path(f).stat().st_mtime_ns
    assert cli.main(["format", f]) == 0
    assert Path(f).stat().st_mtime_ns == before


def test_format_read_error(tmp_path, doc):
    assert cli.main(["format", str(tmp_path / "x.xml")]) == 2
    assert cli.main(["format", doc(b"<scene", "bad.xml")]) == 2


# ------------------------------------------------------------------ misc

def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("sr-scene ") and sr_core.__version__ in out and _generated.SCHEMA_RELEASE in out


def test_prog_name_and_no_command(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2
    assert "sr-scene" in capsys.readouterr().err


def test_main_default_argv(stub_checks, doc, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sr-scene", "min-version", doc()])
    assert cli.main() == 0


def test_python_dash_m():
    done = subprocess.run([sys.executable, "-m", "sr_core.scene", "--version"], capture_output=True, text=True)
    assert done.returncode == 0 and _generated.SCHEMA_RELEASE in done.stdout


# ------------------------------------------------------------------ against the real checks module

@pytest.fixture
def real(have_real_checks):
    if not have_real_checks:
        pytest.skip("sr_core.scene.checks not present yet")


def test_real_checks_reports_unknown_element(real, doc, capsys):
    f = doc(BOGUS)
    assert cli.main(["check", f]) == 1
    assert "xsd:element" in capsys.readouterr().out


def test_real_checks_min_version(real, doc, capsys):
    f = doc()
    assert cli.main(["min-version", f]) == 0
    assert capsys.readouterr().out.startswith(f + ": 1.")


def test_real_checks_json_roundtrip(real, doc, capsys):
    cli.main(["check", doc(BOGUS), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert any(x["code"] == "xsd:element" for x in payload["files"][0]["findings"])
