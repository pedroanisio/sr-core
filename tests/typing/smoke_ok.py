"""Must type-check: the generated signatures and descriptors accept correct code."""
from __future__ import annotations

from decimal import Decimal

from sr_core.scene import Scene, Still

scene = Scene(version="auto")
scene.add_project(width=1280, height=720, fps="30", duration=4)
composition = scene.add_composition()
layer = composition.add_layer(id="a", x="50%", rotation=3, tags=["t"], visible=True)
reveal: str | None = layer.id
visible: bool | None = layer.visible
tags: list[str] | None = layer.tags
layer.opacity = 0.5
layer.opacity = None
fractal = scene.add_assets().add_fractal(id="f", centerX=Decimal("1.5"))
centre: Decimal | None = fractal.centerX
thumb = Still(xml_name="thumbnail", path="a.png")
name: str = thumb.xml_name
