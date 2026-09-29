"""scenerender-vpkg: scene video packages (.vpkg.zip) -- a scene-render video with everything needed to
rebuild it except the render engine: scenes, assets, fonts, scripts, pipeline, pinned downloads and credits.

Uses only the standard library and never imports the renderer. Format: SREP 1 (srep/srep-0001.md) and
schema/vpkg-1.schema.json (format 1.1: SREP 6).
"""
from .. import __version__  # noqa: F401  (one version for the whole distribution)
