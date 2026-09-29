"""sr-core: scene-render core formats and tools shared by every engine.

Three version lines, each Semantic Versioning, each moving only when its own contract changes (SREP 4):

- this distribution and its commands (`scenerender-vpkg`, `sr-schemadoc`): ``__version__`` below;
- the scene schema: ``xs:schema/@version`` in ``schema/scene-render.xsd``; documents declare its MAJOR.MINOR;
- the package format: ``sr_core.vpkg.manifest.FORMAT_VERSION`` (MAJOR.MINOR, written into ``vpkg.json``).

Release numbers are computed from the changelogs by ``tools/release.py``, never edited by hand.
"""
__version__ = "1.0.0"
