"""``sr-scene describe``, ``list`` and ``new``, and the findings envelope (SREP 0 section 8)."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from sr_core.scene import VERSIONS, cli, read


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


# ------------------------------------------------------------------ describe

def test_describe_human(capsys) -> None:
    code, out, err = run(capsys, "describe", "layer")
    assert code == 0 and err == ""
    assert out.startswith("layer ")
    assert "Layer" in out and "Places an asset." in out
    assert "children:" in out and "attributes:" in out
    assert "opacity" in out and "unitDecimal" in out and "default 1" in out
    assert "id" in out and "required" in out


def test_describe_json_one_name(capsys) -> None:
    code, out, _ = run(capsys, "describe", "layer", "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert data["format"] == "sr-scene-describe/1"
    assert [e["class_name"] for e in data["elements"]] == ["Layer"]
    assert data["elements"][0]["attributes"][0]["python_name"] == "id"


def test_describe_several_names_and_class_names(capsys) -> None:
    code, out, _ = run(capsys, "describe", "layer", "poster", "Scene", "--format", "json")
    assert code == 0
    assert [e["class_name"] for e in json.loads(out)["elements"]] == ["Layer", "Still", "Scene"]


def test_describe_a_shared_name_describes_every_class(capsys) -> None:
    code, out, _ = run(capsys, "describe", "point", "--format", "json")
    assert code == 0
    assert {e["class_name"] for e in json.loads(out)["elements"]} == {"WarpPoint", "MeshPoint"}


def test_describe_unknown_name_exits_2_with_suggestions(capsys) -> None:
    code, out, err = run(capsys, "describe", "layr")
    assert code == 2 and out == ""
    assert "'layr'" in err and "did you mean 'layer'?" in err


def test_describe_unknown_does_not_hide_the_known_ones(capsys) -> None:
    code, out, err = run(capsys, "describe", "layer", "layr")
    assert code == 2 and out.startswith("layer ") and "did you mean 'layer'?" in err


def test_describe_all_json_is_compact(capsys) -> None:
    code, out, _ = run(capsys, "describe", "--all", "--format", "json")
    assert code == 0
    assert "\n" not in out.strip()          # one line, no indentation
    data = json.loads(out)
    assert data["format"] == "sr-scene-describe/1" and len(data["elements"]) == 169 and "types" in data


def test_describe_needs_names_or_all(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["describe"])
    assert info.value.code == 2
    with pytest.raises(SystemExit) as info:
        cli.main(["describe", "layer", "--all"])
    assert info.value.code == 2


# ------------------------------------------------------------------ list

def test_list_human(capsys) -> None:
    code, out, _ = run(capsys, "list")
    assert code == 0
    lines = out.splitlines()
    assert len(lines) >= 162
    layer = next(x for x in lines if x.startswith("layer "))
    assert "Places an asset." in layer and "timeRemap" not in layer  # the first sentence only


def test_list_json(capsys) -> None:
    code, out, _ = run(capsys, "list", "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert data["format"] == "sr-scene-list/1"
    row = next(r for r in data["elements"] if r["name"] == "layer")
    assert row["class_name"] == "Layer" and row["summary"].startswith("Places an asset.")
    assert {r["name"] for r in data["elements"]} >= {"poster", "thumbnail", "scene"}


# ------------------------------------------------------------------ new

def test_new_prints_a_scene_that_is_clean_at_levels_1_and_2(capsys, tmp_path) -> None:
    code, out, _ = run(capsys, "new")
    assert code == 0
    path = tmp_path / "n.xml"
    path.write_text(out, encoding="utf-8")
    scene = read(str(path))
    assert scene.check() == []
    pytest.importorskip("lxml")
    assert scene.check(schema=True) == []


@pytest.mark.parametrize("version", VERSIONS)
def test_new_for_every_version(capsys, tmp_path, version) -> None:
    code, out, _ = run(capsys, "new", "--version", version)
    assert code == 0 and f'version="{version}"' in out
    path = tmp_path / "n.xml"
    path.write_text(out, encoding="utf-8")
    assert read(str(path)).check() == []


def test_new_layouts_and_output_file(capsys, tmp_path) -> None:
    code, pretty, _ = run(capsys, "new", "--layout", "pretty")
    assert code == 0 and pretty.count("\n") > 3
    _, indent, _ = run(capsys, "new", "--layout", "indent")
    _, preserve, _ = run(capsys, "new", "--layout", "preserve")
    assert "<scene" in indent and "<scene" in preserve
    target = tmp_path / "out.xml"
    code, out, _ = run(capsys, "new", "-o", str(target))
    assert code == 0 and out == ""
    assert target.read_text(encoding="utf-8") == pretty
    assert read(str(target)).check() == []


def test_new_rejects_an_unknown_version(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["new", "--version", "9.9"])
    assert info.value.code == 2


# ------------------------------------------------------------------ check envelope

def test_check_json_has_codes_and_a_format_envelope(tmp_path, capsys) -> None:
    f = tmp_path / "b.xml"
    f.write_bytes(b'<scene version="1.7"><bogus/></scene>')
    code, out, _ = run(capsys, "check", str(f), "--format", "json")
    assert code == 1
    data = json.loads(out)
    assert data["format"] == "sr-scene-findings/1"
    assert data["valid"] is False and data["files"][0]["file"] == str(f)
    assert all("code" in x for x in data["files"][0]["findings"]) and data["files"][0]["findings"]


def test_the_module_entry_point_runs() -> None:
    done = subprocess.run([sys.executable, "-m", "sr_core.scene", "list"], capture_output=True, text=True)
    assert done.returncode == 0 and "layer" in done.stdout
