"""One class, several element names (SREP 0 runtime API): the name is chosen at construction with ``xml_name=``."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sr_core.scene import Output, Scene, SchemaValueError, Still, read, to_bytes
from sr_core.scene import _generated as gen


def test_the_class_covers_both_names() -> None:
    assert Still._element_names == ("poster", "thumbnail")


def test_default_name_is_the_first() -> None:
    assert Still(path="a.png").xml_name == "poster"
    assert b"<poster " in to_bytes(Still(path="a.png"))


def test_thumbnail_is_built_and_written() -> None:
    still = Still(xml_name="thumbnail", path="a.png")
    assert still.xml_name == "thumbnail"
    assert b"<thumbnail " in to_bytes(still)
    assert still.path == "a.png"  # xml_name is not an attribute


def test_unknown_name_is_refused() -> None:
    with pytest.raises(SchemaValueError):
        Still(xml_name="cover", path="a.png")
    with pytest.raises(SchemaValueError):
        Still(xml_name="", path="a.png")
    with pytest.raises(SchemaValueError):
        Still(xml_name=3, path="a.png")  # type: ignore[arg-type]


def test_single_name_class_accepts_only_its_name() -> None:
    assert Output(xml_name="output", id="o", path="o.mp4", codec="h264").xml_name == "output"
    with pytest.raises(SchemaValueError):
        Output(xml_name="poster", id="o", path="o.mp4", codec="h264")


def test_add_uses_the_chosen_name() -> None:
    out = Output(id="o", path="o.mp4", codec="h264")
    still = out.add(Still(xml_name="thumbnail", path="a.png"))
    assert still.xml_name == "thumbnail"
    assert still.xml_path.endswith("/output/thumbnail")
    assert b"<thumbnail " in to_bytes(out)
    assert b"<poster" not in to_bytes(out)


def test_parent_that_does_not_allow_the_name_refuses_it() -> None:
    scene = Scene(version="auto")
    with pytest.raises(SchemaValueError):
        scene.add(Still(xml_name="thumbnail", path="a.png"))


def _scene_with_thumbnail() -> Scene:
    scene = Scene(version="1.1")
    scene.add_project(fps="30", width=8, height=8)
    out = scene.add_output(id="o", path="o.mp4", codec="h264")
    out.add(Still(xml_name="thumbnail", path="a.png"))
    return scene


def test_read_keeps_the_name_and_copy_too() -> None:
    scene = read(to_bytes(_scene_with_thumbnail()))
    still = next(scene.iter("thumbnail"))
    assert isinstance(still, Still)
    assert still.xml_name == "thumbnail"
    assert still.copy().xml_name == "thumbnail"
    assert b"<thumbnail " in to_bytes(scene)


def test_level_one_check_uses_the_chosen_name() -> None:
    scene = _scene_with_thumbnail()
    assert [f for f in scene.check() if "thumbnail" in f.message or "thumbnail" in (f.path or "")] == []
    # the same name where the schema does not take it (directly in <scene>) is still found
    stray = to_bytes(scene).replace(b"<project", b"<thumbnail path='x.png'/><project", 1)
    assert any(f.code == "xsd:element" and "thumbnail" in f.message for f in read(stray).check())
    assert next(scene.iter("thumbnail")).xml_path == "/scene/output/thumbnail"


def test_generated_signature_types_the_name_only_where_it_varies() -> None:
    tree = ast.parse((Path(gen.__file__)).read_text(encoding="utf-8"))
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

    def init_params(name: str) -> dict[str, str]:
        for n in ast.walk(classes[name]):
            if isinstance(n, ast.FunctionDef) and n.name == "__init__":
                return {a.arg: ast.unparse(a.annotation) for a in n.args.kwonlyargs if a.annotation}
        return {}

    assert init_params("Still")["xml_name"] == "_t.Literal['poster', 'thumbnail'] | None"
    assert "xml_name" not in init_params("Output")
