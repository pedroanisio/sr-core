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

from sr_core.scene import _generated
from sr_core.scene._generated import CLASSES, ELEMENT_CLASSES, GATES, SCHEMA_RELEASE, VERSIONS
from sr_core.scene._runtime import PI, Comment, Element, Text, Unknown, default_of
from sr_core.scene.checks import check, min_version, new_id
from sr_core.scene.engine import EngineError, EngineInfo, engine_info
from sr_core.scene.errors import IntegrityError, SchemaError, SchemaValueError
from sr_core.scene.findings import Finding
from sr_core.scene.gates import Gate
from sr_core.scene.io import read, to_bytes, write

globals().update({cls.__name__: cls for cls in CLASSES.values()})

__all__ = sorted(
    ["CLASSES", "ELEMENT_CLASSES", "GATES", "SCHEMA_RELEASE", "VERSIONS", "PI", "Comment", "Element", "Text",
     "Unknown", "default_of", "check", "min_version", "new_id", "EngineError", "EngineInfo", "engine_info",
     "IntegrityError", "SchemaError", "SchemaValueError", "Finding", "Gate", "read", "to_bytes", "write"]
    + [cls.__name__ for cls in CLASSES.values()])

del _generated
