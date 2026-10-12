"""Must NOT type-check: each marked line is an error a checker has to report."""
from __future__ import annotations

from sr_core.scene import Scene

scene = Scene(version="1.0")
composition = scene.add_composition()
layer = composition.add_layer(id="a")
layer.bogus = 1                                  # E1: no such attribute
composition.add_layer(id="b", bogus=1)           # E2: no such keyword
composition.add_layer(id=3)                      # E3: wrong value type in a factory
layer.visible = "yes"                            # E4: wrong value type in a setter
layer.id = ["a"]                                 # E5: wrong value type in a setter
n: int | None = layer.tags                       # E6: a getter reads as list[str]
