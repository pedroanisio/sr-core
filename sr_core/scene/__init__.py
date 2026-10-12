"""Python scene SDK generated from the scene-render schema (SREP draft ``srep-0000-python-scene-sdk.md``).

Build, read, write and check scene documents with the classes generated from ``schema/scene-render.xsd`` and the
version gates compiled from ``schema/scene-render.sch``::

    from sr_core.scene import Scene, read, to_bytes

    scene = Scene(version="auto")
    scene.add_project(width=1280, height=720, fps=30, duration=4)
    ...
    findings = scene.check()          # level 1; check(scene, schema=True) for level 2, engine=PATH for level 3
    data = scene.to_bytes(layout="pretty")

Building, reading, writing and level 1 use the standard library only; level 2 needs ``sr-core[validate]`` (lxml).
"""

from __future__ import annotations

import typing as _t

from sr_core.scene import _generated
from sr_core.scene._generated import CLASSES, ELEMENT_CLASSES, GATES, SCHEMA_RELEASE, VERSIONS
from sr_core.scene._runtime import PI, Comment, Element, Text, Unknown, default_of
from sr_core.scene.checks import check, min_version, new_id
from sr_core.scene.engine import EngineError, EngineInfo, engine_info
from sr_core.scene.errors import IntegrityError, SchemaError, SchemaValueError, UnknownNameError, suggest
from sr_core.scene.findings import Finding
from sr_core.scene.gates import Gate
from sr_core.scene.introspect import describe, describe_all, element_names
from sr_core.scene.io import read, to_bytes, write

globals().update({cls.__name__: cls for cls in CLASSES.values()})
if _t.TYPE_CHECKING:  # the classes are bound by the line above; type checkers need to see their names
    from sr_core.scene._generated import *  # noqa: F401,F403

__all__ = sorted(
    ["CLASSES", "ELEMENT_CLASSES", "GATES", "SCHEMA_RELEASE", "VERSIONS", "PI", "Comment", "Element", "Text",
     "Unknown", "default_of", "check", "min_version", "new_id", "EngineError", "EngineInfo", "engine_info",
     "IntegrityError", "SchemaError", "SchemaValueError", "UnknownNameError", "Finding", "Gate", "read", "to_bytes", "write", "describe", "describe_all", "element_names"]
    + [cls.__name__ for cls in CLASSES.values()])


if not _t.TYPE_CHECKING:  # a type checker must keep flagging a name that is not exported, so it never sees this

    def __getattr__(name: str) -> _t.Any:
        """A name this package does not export: say which class was probably meant (an ``AttributeError`` still).

        ``from sr_core.scene import Layr`` is an ``ImportError`` as before (Python converts the ``AttributeError``).
        Dunder names (``__path__``, ``__wrapped__``, ...) are probes by tools and stay plain errors.
        """
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        by_element: dict[str, list[str]] = {}
        for (_, xml_name), cls in ELEMENT_CLASSES.items():
            if cls.__name__ not in by_element.setdefault(xml_name, []):
                by_element[xml_name].append(cls.__name__)
        classes = sorted(cls.__name__ for cls in CLASSES.values())
        found: list[str] = list(by_element.get(name, ()))  # S.layer, S.image: the class(es) of that element name
        for hit in suggest(name, classes + sorted(by_element)):
            for cls_name in (by_element[hit] if hit in by_element and hit not in classes else [hit]):
                if cls_name not in found:
                    found.append(cls_name)
        raise UnknownNameError(name, __name__, classes, kind="class", suggestions=found[:3])


del _generated
