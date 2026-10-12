"""Typing of the generated module (SREP 0, D10): explicit keyword-only signatures, two-parameter ``Attr``, py.typed.

The signatures live in an ``if TYPE_CHECKING:`` block of each class, so that the runtime keeps raising
``AttributeError`` for an attribute the element does not declare (SREP 3.3), while a type checker sees keyword-only
parameters with the types of the attribute hints, all defaulting to ``None``. The tests read the generated source
with ``ast``.
"""
from __future__ import annotations

import ast
import typing
from pathlib import Path

import pytest

from sr_core.scene import _generated as gen
from sr_core.scene import _runtime

PKG = Path(gen.__file__).parent
TREE = ast.parse((PKG / "_generated.py").read_text(encoding="utf-8"))
CLASSES = {n.name: n for n in TREE.body if isinstance(n, ast.ClassDef)}


def attrs_of(cls: ast.ClassDef) -> list[tuple[str, ast.Subscript]]:
    return [(n.target.id, n.annotation) for n in cls.body if isinstance(n, ast.AnnAssign)]  # type: ignore[misc]


def hint(ann: ast.expr) -> str:
    return ", ".join(ast.unparse(e) for e in ann.slice.elts)  # type: ignore[attr-defined]


def checking_block(cls: ast.ClassDef) -> list[ast.stmt]:
    blocks = [n for n in cls.body if isinstance(n, ast.If) and ast.unparse(n.test) == "_t.TYPE_CHECKING"]
    assert len(blocks) <= 1
    return blocks[0].body if blocks else []


def test_py_typed_ships_with_the_package() -> None:
    assert (PKG / "py.typed").is_file()


def test_every_attr_declaration_has_a_getter_and_a_setter_type() -> None:
    total = 0
    for cls in CLASSES.values():
        for name, ann in attrs_of(cls):
            assert isinstance(ann, ast.Subscript) and ann.value.id == "Attr", (cls.name, name)  # type: ignore[attr-defined]
            assert isinstance(ann.slice, ast.Tuple) and len(ann.slice.elts) == 2, (cls.name, name)
            total += 1
    assert total == gen.COUNTS["attributes"]


def test_getter_types_are_the_parsed_types() -> None:
    layer = {name: hint(ann) for name, ann in attrs_of(CLASSES["Layer"])}  # type: ignore[attr-defined]
    assert layer["id"] == "str, str"
    assert layer["tags"] == "_t.List[str], _t.Sequence[str]"
    assert layer["visible"] == "bool, _t.Union[bool, str]"
    text = {name: hint(ann) for name, ann in attrs_of(CLASSES["FractalAsset"])}  # type: ignore[attr-defined]
    assert text["centerX"] == "_Decimal, _t.Union[_Decimal, float, int, str]"
    project = {name: hint(ann) for name, ann in attrs_of(CLASSES["Project"])}  # type: ignore[attr-defined]
    assert project["width"] == "int, _t.Union[int, str]"
    assert project["shutterPhase"] == "float, _t.Union[float, int, str]"
    assert project["motionBlur"] == "bool, _t.Union[bool, str]"
    refs = [hint(ann) for c in CLASSES.values() for _, ann in attrs_of(c)  # type: ignore[attr-defined]
            if hint(ann).startswith("str, _t.Union[str, Element]")]
    assert refs, "an xs:IDREF attribute reads as str and takes a str or an Element"
    lists = [hint(ann) for c in CLASSES.values() for _, ann in attrs_of(c)  # type: ignore[attr-defined]
             if hint(ann).startswith("_t.List[str], _t.Sequence[_t.Union[str, Element]]")]
    assert lists, "an xs:IDREFS attribute reads as list[str] and takes a sequence of str or Element"


def test_every_class_has_a_keyword_only_init_over_its_attributes() -> None:
    for cls in CLASSES.values():
        init = [n for n in checking_block(cls) if isinstance(n, ast.FunctionDef) and n.name == "__init__"]
        assert len(init) == 1, cls.name
        fn = init[0]
        assert [a.arg for a in fn.args.args] == ["self"] and fn.args.kwarg is None and fn.args.vararg is None
        assert [a.arg for a in fn.args.kwonlyargs] == [n for n, _ in attrs_of(cls)], cls.name
        assert all(isinstance(d, ast.Constant) and d.value is None for d in fn.args.kw_defaults)
        assert all(ast.unparse(a.annotation).endswith("| None") for a in fn.args.kwonlyargs)


def test_every_factory_takes_the_keywords_of_the_class_it_builds() -> None:
    seen = 0
    for cls in CLASSES.values():
        factories = [n for n in checking_block(cls) if isinstance(n, ast.FunctionDef) and n.name.startswith("add_")]
        runtime = [n for n in ast.walk(cls) if isinstance(n, ast.FunctionDef) and n.name.startswith("add_")
                   and n not in factories]
        assert [f.name for f in factories] == [f.name for f in runtime], cls.name
        for fn in factories:
            built = CLASSES[ast.unparse(fn.returns)]
            assert [a.arg for a in fn.args.kwonlyargs] == [n for n, _ in attrs_of(built)], (cls.name, fn.name)
            assert all(isinstance(d, ast.Constant) and d.value is None for d in fn.args.kw_defaults)
            seen += 1
    assert seen == 616


def test_the_parameter_types_are_the_setter_types() -> None:
    fn = next(n for n in checking_block(CLASSES["Layer"]) if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    annotation = {a.arg: ast.unparse(a.annotation) for a in fn.args.kwonlyargs}
    assert annotation["id"] == "str | None"
    assert annotation["tags"] == "_t.Sequence[str] | None"
    assert annotation["effects"].startswith("_t.Sequence[_t.Union[str, Element]]")


def test_the_runtime_still_refuses_an_undeclared_attribute() -> None:
    with pytest.raises(AttributeError):
        gen.Layer(bogus="1")  # type: ignore[call-arg]
    scene = gen.Scene(version="1.0")
    with pytest.raises(AttributeError):
        scene.add_composition(bogus="1")  # type: ignore[call-arg]
    with pytest.raises(AttributeError):
        scene.bogus = 1  # type: ignore[attr-defined]


def test_attr_is_generic_in_getter_and_setter_and_the_setter_takes_none() -> None:
    assert [p.__name__ for p in _runtime.Attr.__parameters__] == ["G", "S"]
    hints = typing.get_type_hints(_runtime.Attr.__set__)
    assert hints["value"] == typing.Optional[_runtime.S]


def test_from_keeps_its_underscore_in_signatures() -> None:
    names = [a.arg for c in CLASSES.values() for n in checking_block(c) if isinstance(n, ast.FunctionDef)
             for a in n.args.kwonlyargs]
    assert "from_" in names and "from" not in names


def test_the_root_version_also_takes_and_reads_auto() -> None:
    version = dict(attrs_of(CLASSES["Scene"]))["version"]
    both = [ast.unparse(e) for e in version.slice.elts]  # type: ignore[attr-defined]
    assert all("Literal['auto']" in h and "'1.7'" in h for h in both)


# ------------------------------------------------------------------------------------------------- mypy smoke

@pytest.mark.skipif(__import__("os").environ.get("SR_SCENE_TYPING") != "1",
                    reason="set SR_SCENE_TYPING=1 (and install mypy, which is not a test dependency)")
def test_a_type_checker_accepts_the_good_file_and_flags_every_marked_line_of_the_bad_one() -> None:
    import re
    import subprocess
    import sys

    pytest.importorskip("mypy")
    here = Path(__file__).parent / "typing"

    def run(name: str) -> list[str]:
        done = subprocess.run([sys.executable, "-m", "mypy", "--follow-imports=silent", "--ignore-missing-imports",
                               str(here / name)], capture_output=True, text=True, check=False)
        return [ln for ln in done.stdout.splitlines() if ln.split(":")[0].endswith(name)]

    assert [ln for ln in run("smoke_ok.py") if ": error:" in ln] == []
    flagged = {int(m.group(1)) for ln in run("smoke_bad.py") if (m := re.match(r".*smoke_bad.py:(\d+): error:", ln))}
    marked = {i for i, ln in enumerate((here / "smoke_bad.py").read_text().splitlines(), 1) if "# E" in ln}
    assert flagged == marked and len(marked) == 6
