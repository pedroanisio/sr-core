"""docs/scene-sdk-guide.md: every Python block runs, every claimed error is the real one, the codes table is current.

Conventions: a ```python block runs in a fresh namespace in a scratch folder and must not raise. A block whose first
line is ``# raises: Name`` must raise ``Name`` (a name exported by ``sr_core.scene``, or a builtin), and the guide must
quote the first line of the message. A ```bash block line starting with ``$ sr-scene`` runs through the command line and
must exit 0, or with the status of a trailing ``# exit N``.
"""
from __future__ import annotations

import builtins
import contextlib
import io
import os
import re
from pathlib import Path

import pytest

import sr_core.scene as sdk
from sr_core.scene import cli

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "scene-sdk-guide.md"
TEXT = GUIDE.read_text(encoding="utf-8")
BLOCK = re.compile(r"^```(\w+)\n(.*?)^```$", re.S | re.M)
BLOCKS = [(m.group(1), m.group(2)) for m in BLOCK.finditer(TEXT)]
PYTHON = [code for lang, code in BLOCKS if lang == "python"]
RAISES = re.compile(r"\A# raises: (\w+)\n")


def exception_class(name: str) -> type[BaseException]:
    cls = getattr(sdk, name, None) or getattr(builtins, name)
    assert isinstance(cls, type) and issubclass(cls, BaseException), name
    return cls


def ids() -> list[str]:
    return [f"block{i}:{code.strip().splitlines()[0][:40]}" for i, code in enumerate(PYTHON)]


def test_the_guide_has_python_blocks_and_both_kinds() -> None:
    assert len(PYTHON) >= 8
    assert any(RAISES.match(code) for code in PYTHON)
    assert any(not RAISES.match(code) for code in PYTHON)


@pytest.mark.parametrize("code", PYTHON, ids=ids())
def test_python_block(code: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    marker = RAISES.match(code)
    namespace: dict[str, object] = {"__name__": "__guide__"}
    if marker is None:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code, "<guide>", "exec"), namespace)
        return
    expected = exception_class(marker.group(1))
    with pytest.raises(expected) as info:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code, "<guide>", "exec"), namespace)
    first_line = str(info.value).splitlines()[0]
    assert first_line in TEXT, f"the guide does not quote the real message:\n{first_line}"


def test_a_failing_block_would_be_noticed(tmp_path: Path) -> None:
    """The convention is enforced: an unmarked block that raises fails, a marked block that does not raise fails."""
    with pytest.raises(NameError):
        exec(compile("undefined_name", "<guide>", "exec"), {})
    assert RAISES.match("# raises: UnknownNameError\nx = 1\n") is not None
    with pytest.raises(pytest.fail.Exception):
        with pytest.raises(UnicodeError):
            exec(compile("x = 1", "<guide>", "exec"), {})


def test_shell_lines_run() -> None:
    lines = [ln for lang, code in BLOCKS if lang == "bash" for ln in code.splitlines() if ln.startswith("$ sr-scene")]
    assert len(lines) >= 5
    for line in lines:
        status = re.search(r"# exit (\d+)\s*$", line)
        argv = line[2:].split("#")[0].split()[1:]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert cli.main(argv) == (int(status.group(1)) if status else 0), line


CODE_RE = re.compile(r'"((?:xsd|sdk):[a-z-]+)"')


def test_the_codes_table_matches_the_code() -> None:
    table = {c for c in re.findall(r"^\| `((?:xsd|sdk):[a-z-]+)` \|", TEXT, re.M)}
    source = ""
    for name in ("checks.py", "engine.py"):
        source += (ROOT / "sr_core" / "scene" / name).read_text(encoding="utf-8")
    in_code = {c for c in CODE_RE.findall(source) if c not in ("xsd:", "sdk:")}
    assert table == in_code, (sorted(table ^ in_code))


def test_gate_ids_named_in_the_guide_exist() -> None:
    ids_ = {g.id for g in sdk.GATES}
    for name in ("V1", "V9", "P3D1"):
        assert name in ids_ and f"`{name}`" in TEXT


def test_cross_references_resolve() -> None:
    for target in re.findall(r"\]\((\.\./[^)#]+)", TEXT):
        assert (GUIDE.parent / target).exists(), target


def test_the_guide_is_linked_from_the_readme() -> None:
    assert "docs/scene-sdk-guide.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_guide_does_not_name_a_private_path() -> None:
    assert os.path.expanduser("~") not in TEXT
