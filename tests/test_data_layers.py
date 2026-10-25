"""Tests for the draft SREP "Add data layers to the map" (M2 of SREP 12) and its reference module."""
import importlib.util
import math
import os
import re

import pytest

np = pytest.importorskip("numpy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "data_layers_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-data-layers.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dl = _load(MODULE, "data_layers_reference")

G = 0.3989422804014327
ZERO = 1.0 / 255.0 / 16.0


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list, np.ndarray)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _smoothstep(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def _box(candidate=None, **kw):
    """A placement candidate: boxes are (x1, y1, x2, y2) in map pixels."""
    c = {"text": None, "icon": None, "text_overlap": "never", "icon_overlap": "never", "text_ignore": False,
         "icon_ignore": False, "text_optional": False, "icon_optional": False, "text_padding": 0.0,
         "icon_padding": (0.0, 0.0, 0.0, 0.0), "text_key": None}
    if candidate:
        c.update(candidate)
    c.update(kw)
    return c


# ----------------------------------------------------------------------------------------------------------- heatmap


def test_the_kernel_is_maplibres_gaussian():
    assert dl.GAUSS_COEF == G and _close(dl.ZERO, ZERO, 1e-12)
    assert _close(dl.kernel(0.0, 30.0, 1.0, 1.0), G, 1e-12)
    assert _close(dl.kernel(30.0 ** 2, 30.0, 1.0, 1.0), G * math.exp(-4.5), 1e-12)
    assert _close(dl.kernel(0.0, 30.0, 2.0, 0.5), G, 1e-12)
    assert _close(dl.kernel(100.0, 10.0, 1.0, 1.0), G * math.exp(-4.5), 1e-12)


def test_the_kernel_extent_is_the_vertex_shaders_quad():
    s = math.sqrt(-2.0 * math.log(ZERO / (1.0 * 1.0 * G))) / 3.0
    assert _close(dl.kernel_extent(30.0, 1.0, 1.0), 30.0 * s, 1e-9)
    assert _close(dl.kernel_extent(10.0, 2.0, 0.5), 10.0 * s, 1e-9)
    assert dl.kernel_extent(30.0, 0.0, 1.0) == 0.0
    assert dl.kernel_extent(30.0, 1.0, 0.0) == 0.0
    # a point whose weight makes the kernel smaller than the cut-off draws nothing
    assert dl.kernel_extent(30.0, ZERO / G / 2.0, 1.0) == 0.0


def test_the_kernel_is_cut_at_the_quad_not_at_a_circle():
    e = dl.kernel_extent(30.0, 1.0, 1.0)
    d = dl.density([(50.0, 50.0, 1.0)], 100, 100, 30.0, 1.0)
    assert d.shape == (100, 100)
    # the corner of the quad is drawn (farther than e from the centre), a point just outside its side is not
    corner = int(50.0 + e - 0.5)
    assert d[corner, corner] > 0.0
    outside = int(50.0 + e + 1.0)
    assert d[50, outside] == 0.0
    assert d[50, corner] > 0.0


def test_density_is_evaluated_at_pixel_centres_and_adds_up():
    one = dl.density([(10.5, 10.5, 1.0)], 24, 24, 4.0, 1.0)
    assert _close(one[10, 10], G, 1e-12)
    assert _close(one[10, 11], G * math.exp(-4.5 / 16.0), 1e-12)
    two = dl.density([(10.5, 10.5, 1.0), (10.5, 10.5, 0.5)], 24, 24, 4.0, 1.0)
    assert _close(two[10, 10], 1.5 * G, 1e-12)
    assert _close(dl.density([(10.5, 10.5, 1.0)], 24, 24, 4.0, 2.0)[10, 10], 2 * G, 1e-12)
    assert np.all(dl.density([], 8, 8, 4.0, 1.0) == 0.0)


def test_the_default_ramp_is_the_style_specifications():
    stops = dl.ramp_stops(dl.DEFAULT_HEATMAP_COLOR, "heatmap-density")
    assert stops["kind"] == "interpolate"
    assert [t for t, _ in stops["stops"]] == [0, 0.1, 0.3, 0.5, 0.7, 1]
    assert stops["stops"][0][1] == (0, 0, 255, 0)
    assert stops["stops"][1][1] == (65, 105, 225, 255)
    assert stops["stops"][2][1] == (0, 255, 255, 255)
    assert stops["stops"][3][1] == (0, 255, 0, 255)
    assert stops["stops"][4][1] == (255, 255, 0, 255)
    assert stops["stops"][5][1] == (255, 0, 0, 255)


def test_ramp_colours_interpolate_straight_rgba_and_premultiply():
    stops = dl.ramp_stops(dl.DEFAULT_HEATMAP_COLOR, "heatmap-density")
    assert _close(dl.ramp_colour(stops, 0.4), (0.0, 1.0, 0.5, 1.0), 1e-9)
    assert _close(dl.ramp_colour(stops, 0.05), (32.5 / 255 * 0.5, 52.5 / 255 * 0.5, 240 / 255 * 0.5, 0.5), 1e-9)
    assert _close(dl.ramp_colour(stops, 0.0), (0.0, 0.0, 0.0, 0.0), 1e-9)
    assert _close(dl.ramp_colour(stops, 1.0), (1.0, 0.0, 0.0, 1.0), 1e-9)
    # density is clamped to [0, 1] before the lookup
    assert _close(dl.ramp_colour(stops, 7.0), (1.0, 0.0, 0.0, 1.0), 1e-9)
    assert _close(dl.ramp_colour(stops, -1.0), (0.0, 0.0, 0.0, 0.0), 1e-9)


def test_step_and_exponential_ramps():
    step = dl.ramp_stops(["step", ["heatmap-density"], "#000000", 0.5, "#FFFFFF"], "heatmap-density")
    assert step["kind"] == "step"
    assert _close(dl.ramp_colour(step, 0.49), (0.0, 0.0, 0.0, 1.0), 1e-9)
    assert _close(dl.ramp_colour(step, 0.5), (1.0, 1.0, 1.0, 1.0), 1e-9)
    expo = dl.ramp_stops(["interpolate", ["exponential", 2], ["heatmap-density"], 0, "#000000", 1, "#FFFFFF"],
                         "heatmap-density")
    # MapLibre's exponential interpolation factor (base^t - 1) / (base - 1)
    assert _close(dl.ramp_colour(expo, 0.5), ((2 ** 0.5 - 1),) * 3 + (1.0,), 1e-9)


def test_a_ramp_over_another_input_is_refused():
    with pytest.raises(dl.DataLayersError):
        dl.ramp_stops(["interpolate", ["linear"], ["zoom"], 0, "#000000", 1, "#FFFFFF"], "heatmap-density")
    with pytest.raises(dl.DataLayersError):
        dl.ramp_stops(["interpolate", ["linear"], ["heatmap-density"], 0, "#000000"], "heatmap-density")
    with pytest.raises(dl.DataLayersError):
        dl.ramp_stops("#FF0000", "heatmap-density")


def test_heatmap_pixels_are_the_ramp_of_the_density_times_opacity():
    paint = dl.heatmap_paint({"heatmap-radius": 4, "heatmap-opacity": 0.5})
    px = dl.heatmap_pixels([(10.5, 10.5, 1.0)], 24, 24, paint, 1.0)
    assert px.shape == (24, 24, 4)
    stops = dl.ramp_stops(dl.DEFAULT_HEATMAP_COLOR, "heatmap-density")
    want = np.array(dl.ramp_colour(stops, G)) * 0.5
    assert np.allclose(px[10, 10], want)
    assert np.all(px[0, 0] == 0.0)
    # the basemap's @opacity multiplies again
    assert np.allclose(dl.heatmap_pixels([(10.5, 10.5, 1.0)], 24, 24, paint, 0.5)[10, 10], want * 0.5)


def test_the_heatmap_paint_is_read_with_maplibre_defaults():
    p = dl.heatmap_paint({})
    assert p["radius"] == 30.0 and p["weight"] == 1.0 and p["intensity"] == 1.0 and p["opacity"] == 1.0
    assert p["color"] == dl.DEFAULT_HEATMAP_COLOR
    assert dl.heatmap_paint({"heatmap-radius": 12, "heatmap-weight": ["get", "w"]})["weight"] == ["get", "w"]
    for bad in ({"heatmap-radius": 0.5}, {"heatmap-weight": -1}, {"heatmap-intensity": -0.1},
                {"heatmap-opacity": 1.5}):
        with pytest.raises(dl.DataLayersError):
            dl.check_heatmap(dl.heatmap_paint(bad))


def test_every_vertex_of_a_feature_is_a_kernel_centre():
    pts = dl.kernel_centres({"type": "Point", "coordinates": [1.0, 2.0]})
    assert pts == [(1.0, 2.0)]
    pts = dl.kernel_centres({"type": "LineString", "coordinates": [[0, 0], [1, 1], [2, 2]]})
    assert pts == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
    pts = dl.kernel_centres({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})
    assert pts == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    pts = dl.kernel_centres({"type": "MultiPoint", "coordinates": [[0, 0], [3, 4]]})
    assert pts == [(0.0, 0.0), (3.0, 4.0)]


# ---------------------------------------------------------------------------------------------------- fill-extrusion


def test_the_light_is_read_with_maplibre_defaults():
    light = dl.light({})
    assert light["anchor"] == "viewport" and light["position"] == (1.15, 210.0, 30.0)
    assert light["color"] == (1.0, 1.0, 1.0) and light["intensity"] == 0.5
    assert dl.light({"anchor": "map", "position": [1, 90, 45], "color": "#FF0000", "intensity": 1})["color"] == (
        1.0, 0.0, 0.0)
    for bad in ({"anchor": "screen"}, {"position": [1, 2]}, {"intensity": 2}, {"color": "reddish"}):
        with pytest.raises(dl.DataLayersError):
            dl.light(bad)


def test_the_light_direction_is_spherical_to_cartesian_with_the_viewport_turn():
    d = dl.light_direction(dl.light({}), 0.0)
    assert _close(d, (1.15 * math.cos(math.radians(300)) * 0.5, 1.15 * math.sin(math.radians(300)) * 0.5,
                      1.15 * math.cos(math.radians(30))), 1e-9)
    # anchor viewport turns with the map's rotation, anchor map does not
    turned = dl.light_direction(dl.light({}), 90.0)
    assert _close(turned, (-d[1], d[0], d[2]), 1e-9)
    fixed = dl.light_direction(dl.light({"anchor": "map"}), 90.0)
    assert _close(fixed, d, 1e-9)
    straight_up = dl.light_direction(dl.light({"position": [1, 0, 0]}), 0.0)
    assert _close(straight_up, (0.0, 0.0, 1.0), 1e-9)


def test_the_roof_colour_is_maplibres_vertex_shader_without_the_gradient():
    light = dl.light({})
    c = dl.shade((0.6, 0.6, 0.6, 1.0), (0.0, 0.0, 1.0), light, 0.0, 0.0, 30.0, True, 1.0)
    directional = 0.5 + 0.5 * (1.15 * math.cos(math.radians(30)))
    want = 0.63 * directional
    assert _close(c, (want, want, want, 1.0), 1e-9)
    # a dark colour: 1 - luma + intensity exceeds 1, so the lit end of the mix is that value
    c = dl.shade((0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0), light, 0.0, 0.0, 30.0, True, 1.0)
    directional = 0.5 + (1.5 - 0.5) * (1.15 * math.cos(math.radians(30)))
    assert _close(c, (0.03 * directional,) * 3 + (1.0,), 1e-9)
    # opacity multiplies the premultiplied colour
    c = dl.shade((0.6, 0.6, 0.6, 1.0), (0.0, 0.0, 1.0), light, 0.0, 0.0, 30.0, True, 0.5)
    assert _close(c, (want * 0.5,) * 3 + (0.5,), 1e-9)


def test_walls_take_the_vertical_gradient():
    light = dl.light({})
    lx = 1.15 * math.cos(math.radians(300)) * 0.5
    directional = 0.5 + 0.5 * lx
    top = dl.shade((0.6, 0.6, 0.6, 1.0), (1.0, 0.0, 0.0), light, 1.0, 0.0, 600.0, True, 1.0)
    assert _close(top, (0.63 * directional,) * 3 + (1.0,), 1e-9)
    bottom = dl.shade((0.6, 0.6, 0.6, 1.0), (1.0, 0.0, 0.0), light, 0.0, 0.0, 600.0, True, 1.0)
    assert _close(bottom, (0.63 * directional * 0.84,) * 3 + (1.0,), 1e-9)
    short = dl.shade((0.6, 0.6, 0.6, 1.0), (1.0, 0.0, 0.0), light, 1.0, 0.0, 30.0, True, 1.0)
    assert _close(short, (0.63 * directional * max(0.84, math.sqrt(30.0 / 150.0)),) * 3 + (1.0,), 1e-9)
    plain = dl.shade((0.6, 0.6, 0.6, 1.0), (1.0, 0.0, 0.0), light, 0.0, 0.0, 600.0, False, 1.0)
    assert _close(plain, top, 1e-9)
    # a wall away from the light keeps the ambient floor 1 - intensity
    away = dl.shade((0.6, 0.6, 0.6, 1.0), (-1.0, 0.0, 0.0), light, 1.0, 0.0, 600.0, True, 1.0)
    assert _close(away, (0.63 * 0.5,) * 3 + (1.0,), 1e-9)


def test_the_light_colour_floors_the_channels():
    light = dl.light({"color": "#FF8000"})
    c = dl.shade((0.6, 0.6, 0.6, 1.0), (0.0, 0.0, 1.0), light, 0.0, 0.0, 30.0, True, 1.0)
    directional = 0.5 + 0.5 * (1.15 * math.cos(math.radians(30)))
    assert _close(c[0], 0.63 * directional, 1e-9)
    assert _close(c[1], max(0.63 * directional * (128 / 255), 0.3 * (1 - 128 / 255)), 1e-9)
    assert _close(c[2], 0.3, 1e-9)


def test_extrusion_paint_defaults_and_the_feature_rule():
    p = dl.extrusion_paint({})
    assert p["height"] == 0.0 and p["base"] == 0.0 and p["color"] == "#000000" and p["opacity"] == 1.0
    assert p["verticalGradient"] is True and p["translate"] == (0.0, 0.0) and p["translateAnchor"] == "map"
    p = dl.extrusion_paint({"fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 2,
                            "fill-extrusion-color": "#999"})
    assert dl.extrusion({"h": 30}, p) == {"top": 30.0, "base": 2.0, "color": (0.6, 0.6, 0.6, 1.0)}
    assert dl.extrusion({"h": 2}, p) is None
    assert dl.extrusion({}, p) is None
    # negative values are clamped to zero as the shader does
    p = dl.extrusion_paint({"fill-extrusion-height": 5, "fill-extrusion-base": -3})
    assert dl.extrusion({}, p) == {"top": 5.0, "base": 0.0, "color": (0.0, 0.0, 0.0, 1.0)}
    for bad in ({"fill-extrusion-opacity": 2}, {"fill-extrusion-translate-anchor": "screen"},
                {"fill-extrusion-vertical-gradient": "yes"}):
        with pytest.raises(dl.DataLayersError):
            dl.check_extrusion(dl.extrusion_paint(bad))


def test_fill_polygon_covers_pixel_centres_with_the_non_zero_rule():
    square = [[(2.0, 2.0), (6.0, 2.0), (6.0, 6.0), (2.0, 6.0), (2.0, 2.0)]]
    m = dl.fill_polygon(square, 8, 8)
    assert m.dtype == bool and m.sum() == 16
    assert m[2, 2] and m[5, 5] and not m[1, 2] and not m[6, 6]
    hole = square + [[(3.0, 3.0), (3.0, 5.0), (5.0, 5.0), (5.0, 3.0), (3.0, 3.0)]]
    assert dl.fill_polygon(hole, 8, 8).sum() == 12
    # a same-direction inner ring is not a hole under non-zero winding
    same = square + [[(3.0, 3.0), (5.0, 3.0), (5.0, 5.0), (3.0, 5.0), (3.0, 3.0)]]
    assert dl.fill_polygon(same, 8, 8).sum() == 16


def test_roof_pixels_paint_later_features_over_earlier_ones():
    light = dl.light({})
    paint = dl.extrusion_paint({"fill-extrusion-height": ["get", "h"], "fill-extrusion-color": ["get", "c"]})
    features = [
        {"geometry": {"type": "Polygon", "coordinates": [[[2, 2], [6, 2], [6, 6], [2, 6], [2, 2]]]},
         "properties": {"h": 30, "c": "#999"}},
        {"geometry": {"type": "Polygon", "coordinates": [[[4, 4], [7, 4], [7, 7], [4, 7], [4, 4]]]},
         "properties": {"h": 10, "c": "#FFFFFF"}},
        {"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
         "properties": {"h": 0, "c": "#FF0000"}},
    ]
    px, drawn, skipped = dl.roof_pixels(features, 8, 8, paint, light, 0.0, 1.0, lambda p: p)
    assert (drawn, skipped) == (2, 1)
    grey = dl.shade((0.6, 0.6, 0.6, 1.0), (0.0, 0.0, 1.0), light, 0.0, 0.0, 30.0, True, 1.0)
    white = dl.shade((1.0, 1.0, 1.0, 1.0), (0.0, 0.0, 1.0), light, 0.0, 0.0, 10.0, True, 1.0)
    assert np.allclose(px[2, 2], grey) and np.allclose(px[5, 5], white) and np.all(px[0, 0] == 0.0)


def test_prisms_for_the_3d_map_follow_srep_10s_rule():
    paint = dl.extrusion_paint({"fill-extrusion-height": ["get", "h"], "fill-extrusion-base": ["get", "b"],
                                "fill-extrusion-color": "#336699"})
    features = [{"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]},
                 "properties": {"h": 20, "b": 5}},
                {"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]},
                 "properties": {"h": 5, "b": 5}}]
    prisms = dl.prisms(features, paint, lambda p: p)
    assert len(prisms) == 1
    assert prisms[0]["top"] == 20.0 and prisms[0]["base"] == 5.0 and prisms[0]["color"] == (0.2, 0.4, 0.6, 1.0)
    assert prisms[0]["rings"] == [[(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]]


# ------------------------------------------------------------------------------------------------- sprites and icons


def test_sprite_entries_and_names():
    index = dl.sprite_index({"pin": {"x": 0, "y": 0, "width": 8, "height": 8, "pixelRatio": 1},
                             "big": {"x": 0, "y": 16, "width": 16, "height": 16, "pixelRatio": 2},
                             "dot.sdf": {"x": 8, "y": 0, "width": 16, "height": 16, "pixelRatio": 1, "sdf": True}})
    assert index["pin"]["displaySize"] == (8.0, 8.0) and index["pin"]["sdf"] is False
    assert index["big"]["displaySize"] == (8.0, 8.0)
    assert index["dot.sdf"]["sdf"] is True
    assert dl.sprite_name("pin", "default") == "pin"
    assert dl.sprite_name("pin", "ext") == "ext:pin"
    assert dl.style_sprites("https://x/sprite") == [{"id": "default", "url": "https://x/sprite"}]
    assert dl.style_sprites([{"id": "a", "url": "u"}]) == [{"id": "a", "url": "u"}]
    assert dl.style_sprites(None) == []


def test_sprite_entries_are_checked_against_the_sheet():
    good = {"pin": {"x": 0, "y": 0, "width": 8, "height": 8, "pixelRatio": 1}}
    dl.check_sprite(dl.sprite_index(good), 8, 8)
    for bad in ({"pin": {"x": 1, "y": 0, "width": 8, "height": 8, "pixelRatio": 1}},
                {"pin": {"x": 0, "y": 0, "width": 0, "height": 8, "pixelRatio": 1}},
                {"pin": {"x": 0, "y": 0, "width": 8, "height": 8, "pixelRatio": 0}}):
        with pytest.raises(dl.DataLayersError):
            dl.check_sprite(dl.sprite_index(bad), 8, 8)
    with pytest.raises(dl.DataLayersError):
        dl.sprite_index({"pin": {"x": 0, "y": 0, "width": 8}})


def test_the_symbol_layout_and_paint_are_read_with_maplibre_defaults():
    lay = dl.icon_layout({})
    assert lay["allowOverlap"] is False and lay["overlap"] is None and lay["ignorePlacement"] is False
    assert lay["optional"] is False and lay["rotationAlignment"] == "auto" and lay["size"] == 1.0
    assert lay["textFit"] == "none" and lay["textFitPadding"] == (0.0, 0.0, 0.0, 0.0) and lay["image"] is None
    assert lay["rotate"] == 0.0 and lay["padding"] == (2.0, 2.0, 2.0, 2.0) and lay["keepUpright"] is False
    assert lay["offset"] == (0.0, 0.0) and lay["anchor"] == "center" and lay["pitchAlignment"] == "auto"
    assert lay["placement"] == "point" and lay["spacing"] == 250.0 and lay["avoidEdges"] is False
    assert lay["sortKey"] is None and lay["zOrder"] == "auto"
    assert dl.icon_layout({"icon-padding": [1, 2, 3, 4]})["padding"] == (1.0, 2.0, 3.0, 4.0)
    assert dl.icon_layout({"icon-padding": 3})["padding"] == (3.0, 3.0, 3.0, 3.0)
    paint = dl.icon_paint({})
    assert paint["opacity"] == 1.0 and paint["color"] == "#000000" and paint["haloColor"] == "rgba(0,0,0,0)"
    assert paint["haloWidth"] == 0.0 and paint["haloBlur"] == 0.0 and paint["translate"] == (0.0, 0.0)
    assert paint["translateAnchor"] == "map"
    for bad in ({"icon-anchor": "middle"}, {"icon-overlap": "sometimes"}, {"icon-text-fit": "wide"},
                {"symbol-placement": "area"}, {"icon-rotation-alignment": "screen"}, {"icon-size": -1},
                {"icon-padding": [1, 2]}, {"symbol-z-order": "random"}):
        with pytest.raises(dl.DataLayersError):
            dl.check_symbol(dl.icon_layout(bad), dl.icon_paint({}))
    for bad in ({"icon-opacity": 2}, {"icon-halo-width": -1}, {"icon-translate-anchor": "screen"}):
        with pytest.raises(dl.DataLayersError):
            dl.check_symbol(dl.icon_layout({}), dl.icon_paint(bad))


def test_overlap_mode_prefers_icon_overlap_then_allow_overlap():
    assert dl.overlap_mode(dl.icon_layout({})) == "never"
    assert dl.overlap_mode(dl.icon_layout({"icon-allow-overlap": True})) == "always"
    assert dl.overlap_mode(dl.icon_layout({"icon-overlap": "cooperative"})) == "cooperative"
    assert dl.overlap_mode(dl.icon_layout({"icon-overlap": "never", "icon-allow-overlap": True})) == "never"


def test_anchor_fractions():
    assert dl.anchor_fractions("center") == (0.5, 0.5)
    assert dl.anchor_fractions("top-left") == (0.0, 0.0)
    assert dl.anchor_fractions("bottom-right") == (1.0, 1.0)
    assert dl.anchor_fractions("left") == (0.0, 0.5)
    assert dl.anchor_fractions("bottom") == (0.5, 1.0)


def test_the_icon_box_is_maplibres_shape_icon_scaled_by_icon_size():
    assert _close(dl.icon_box((32.0, 32.0), (18.0, 18.0), 1.0, "center", (0.0, 0.0)), (23.0, 23.0, 41.0, 41.0))
    assert _close(dl.icon_box((32.0, 32.0), (18.0, 18.0), 1.0, "top-left", (0.0, 0.0)), (32.0, 32.0, 50.0, 50.0))
    assert _close(dl.icon_box((32.0, 32.0), (18.0, 18.0), 1.0, "bottom", (0.0, 0.0)), (23.0, 14.0, 41.0, 32.0))
    # icon-offset is in icon pixels: it is multiplied by icon-size as the size is
    assert _close(dl.icon_box((32.0, 32.0), (18.0, 18.0), 2.0, "center", (2.0, -3.0)), (18.0, 8.0, 54.0, 44.0))


def test_the_rotated_icon_quad_and_its_bounds():
    quad = dl.icon_quad((32.0, 32.0), (23.0, 28.0, 41.0, 36.0), 90.0)
    # a clockwise quarter turn about the anchor takes the 18 x 8 box to 8 x 18
    assert _close(dl.bounds(quad), (28.0, 23.0, 36.0, 41.0), 1e-9)
    assert _close(dl.bounds(dl.icon_quad((32.0, 32.0), (23.0, 28.0, 41.0, 36.0), 0.0)), (23.0, 28.0, 41.0, 36.0))
    # the first corner is the box's top-left turned clockwise: (-9, -4) -> (4, -9)
    assert _close(quad[0], (36.0, 23.0), 1e-9)
    assert _close(dl.bounds(dl.icon_quad((0.0, 0.0), (-1.0, -1.0, 1.0, 1.0), 45.0)),
                  (-math.sqrt(2),) * 2 + (math.sqrt(2),) * 2, 1e-9)


def test_icon_text_fit_stretches_the_icon_to_the_text_box():
    text = (-20.0, -6.0, 20.0, 6.0)
    assert _close(dl.fit_icon_to_text((18.0, 18.0), text, "both", (1.0, 2.0, 3.0, 4.0), (0.0, 0.0)),
                  (-24.0, -7.0, 22.0, 9.0))
    assert _close(dl.fit_icon_to_text((18.0, 18.0), text, "width", (0.0, 0.0, 0.0, 0.0), (0.0, 0.0)),
                  (-20.0, -9.0, 20.0, 9.0))
    assert _close(dl.fit_icon_to_text((18.0, 18.0), text, "height", (0.0, 0.0, 0.0, 0.0), (0.0, 0.0)),
                  (-9.0, -6.0, 9.0, 6.0))
    assert _close(dl.fit_icon_to_text((18.0, 18.0), text, "none", (0.0, 0.0, 0.0, 0.0), (1.0, 1.0)),
                  (-8.0, -8.0, 10.0, 10.0))


def test_grown_boxes():
    assert dl.grow((10.0, 10.0, 20.0, 20.0), (1.0, 2.0, 3.0, 4.0)) == (6.0, 9.0, 22.0, 23.0)
    assert dl.grow((10.0, 10.0, 20.0, 20.0), 2.0) == (8.0, 8.0, 22.0, 22.0)
    assert dl.overlaps((0, 0, 10, 10), (10, 0, 20, 10)) is False
    assert dl.overlaps((0, 0, 10, 10), (9, 9, 20, 20)) is True


def test_placement_never_always_and_cooperative():
    a = _box(icon=(10.0, 10.0, 20.0, 20.0))
    b = _box(icon=(15.0, 15.0, 25.0, 25.0))
    assert dl.place([a, b], 100, 100) == [(False, True), (False, False)]
    assert dl.place([a, _box(b, icon_overlap="always")], 100, 100) == [(False, True), (False, True)]
    assert dl.place([a, _box(b, icon_overlap="cooperative")], 100, 100) == [(False, True), (False, False)]
    assert dl.place([_box(a, icon_overlap="always"), _box(b, icon_overlap="cooperative")], 100, 100) == [
        (False, True), (False, True)]
    assert dl.place([_box(a, icon_overlap="cooperative"), _box(b, icon_overlap="cooperative")], 100, 100) == [
        (False, True), (False, True)]
    # an icon that ignores placement occupies nothing
    assert dl.place([_box(a, icon_ignore=True), b], 100, 100) == [(False, True), (False, True)]
    # padding grows the boxes before the test
    c = _box(icon=(20.0, 10.0, 30.0, 20.0), icon_padding=(0.0, 0.0, 0.0, 1.0))
    assert dl.place([a, c], 100, 100) == [(False, True), (False, False)]
    assert dl.place([a, _box(c, icon_padding=(0.0, 0.0, 0.0, 0.0))], 100, 100) == [(False, True), (False, True)]


def test_placement_of_text_with_icon_and_the_optional_flags():
    blocker = _box(icon=(0.0, 0.0, 10.0, 10.0))
    both = _box(text=(50.0, 50.0, 70.0, 60.0), icon=(5.0, 5.0, 15.0, 15.0))
    assert dl.place([blocker, both], 100, 100) == [(False, True), (False, False)]
    assert dl.place([blocker, _box(both, icon_optional=True)], 100, 100) == [(False, True), (True, False)]
    text_blocker = _box(text=(50.0, 50.0, 70.0, 60.0))
    assert dl.place([text_blocker, both], 100, 100) == [(True, False), (False, False)]
    assert dl.place([text_blocker, _box(both, text_optional=True)], 100, 100) == [(True, False), (False, True)]
    # text and icon boxes collide with each other's kind too
    cross = _box(text=(5.0, 5.0, 15.0, 15.0))
    assert dl.place([blocker, cross], 100, 100) == [(False, True), (False, False)]


def test_placement_drops_boxes_wholly_outside_the_frame_and_duplicate_text():
    out = _box(icon=(-20.0, -20.0, -10.0, -10.0))
    assert dl.place([out], 100, 100) == [(False, False)]
    edge = _box(icon=(-5.0, -5.0, 5.0, 5.0))
    assert dl.place([edge], 100, 100) == [(False, True)]
    dup1 = _box(text=(10.0, 10.0, 30.0, 20.0), text_key="Rome")
    # the same text with its top-left in the same 8 px bucket, allowed to overlap: dropped as a duplicate
    dup2 = _box(text=(9.0, 11.0, 29.0, 21.0), text_key="Rome", text_overlap="always")
    assert dl.place([dup1, dup2], 100, 100) == [(True, False), (False, False)]
    assert dl.place([dup1, _box(dup2, text_key="Roma")], 100, 100) == [(True, False), (True, False)]
    far = _box(text=(43.0, 12.0, 63.0, 22.0), text_key="Rome")
    assert dl.place([dup1, far], 100, 100) == [(True, False), (True, False)]
    # the dropped duplicate occupies no space: a box over it, clear of the first, is placed
    after = _box(text=(22.0, 20.5, 40.0, 30.0), text_key="Milan")
    assert dl.place([dup1, dup2, after], 100, 100) == [(True, False), (False, False), (True, False)]


def test_candidate_anchors_follow_srep_9():
    assert dl.candidate_anchors({"type": "Point", "coordinates": [1.0, 2.0]}, "point") == [((1.0, 2.0), 0.0)]
    assert dl.candidate_anchors({"type": "LineString", "coordinates": [[0, 0], [10, 0]]}, "point") == []
    anchors = dl.candidate_anchors({"type": "LineString", "coordinates": [[0, 0], [10, 0], [10, 10]]}, "line")
    assert len(anchors) == 1 and _close(anchors[0][0], (10.0, 0.0)) and anchors[0][1] in (0.0, 90.0)
    anchors = dl.candidate_anchors({"type": "LineString", "coordinates": [[0, 0], [10, 0]]}, "line-center")
    assert len(anchors) == 1 and _close(anchors[0][0], (5.0, 0.0)) and anchors[0][1] == 0.0
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [2, 1], [1, 2], [1, 1]]]}
    assert _close(dl.candidate_anchors(poly, "point")[0][0], (1.6, 1.6))
    down = dl.candidate_anchors({"type": "LineString", "coordinates": [[0, 0], [0, 10]]}, "line")
    assert _close(down[0][1], 90.0)


def test_icon_rotation_alignment_auto_is_map_on_lines_and_viewport_on_points():
    assert dl.icon_rotation("auto", "point", 30.0, 10.0, False) == 10.0
    assert dl.icon_rotation("auto", "line", 30.0, 10.0, False) == 40.0
    assert dl.icon_rotation("viewport", "line", 30.0, 10.0, False) == 10.0
    assert dl.icon_rotation("map", "point", 30.0, 10.0, False) == 40.0
    # keep-upright folds the segment angle into [-90, 90)
    assert dl.icon_rotation("map", "line", 120.0, 0.0, True) == -60.0
    assert dl.icon_rotation("map", "line", 120.0, 0.0, False) == 120.0


def test_sdf_coverage_is_the_symbol_sdf_fragment_shader():
    gamma = 0.105 / 1.0
    assert _close(dl.sdf_fill(0.75, 1.0), 0.5, 1e-9)
    assert _close(dl.sdf_fill(1.0, 1.0), 1.0, 1e-9)
    assert _close(dl.sdf_fill(0.5, 1.0), 0.0, 1e-9)
    assert _close(dl.sdf_fill(0.75 + gamma / 2, 1.0), _smoothstep(0.75 - gamma, 0.75 + gamma, 0.75 + gamma / 2), 1e-9)
    # a bigger icon has a sharper edge
    assert dl.sdf_fill(0.75 + 0.05, 2.0) > dl.sdf_fill(0.75 + 0.05, 1.0)
    # the halo: edge (6 - width / size) / 8, hidden under the fill
    assert _close(dl.sdf_halo(0.5, 1.0, 2.0, 0.0), 0.5, 1e-9)
    assert _close(dl.sdf_halo(0.5, 1.0, 0.0, 0.0), 0.0, 1e-9)
    assert _close(dl.sdf_halo(1.0, 1.0, 2.0, 0.0), 0.0, 1e-9)
    blur = dl.sdf_halo(0.5 + 0.05, 1.0, 2.0, 1.0)
    gh = 1.0 * 1.19 / 8.0 + 0.105
    assert _close(blur, min(_smoothstep(0.5 - gh, 0.5 + gh, 0.55), 1.0 - dl.sdf_fill(0.55, 1.0)), 1e-9)


def _sheet():
    sheet = np.zeros((32, 24, 4), dtype=np.uint8)
    sheet[0:8, 0:8] = (255, 0, 0, 255)
    j, i = np.mgrid[0:16, 0:16]
    r = np.hypot(i + 0.5 - 8.0, j + 0.5 - 8.0)
    sheet[0:16, 8:24, 3] = np.clip(np.round(255 * np.clip(0.75 + (5.0 - r) / 8.0, 0.0, 1.0)), 0, 255)
    sheet[16:32, 0:16] = (0, 0, 255, 255)
    index = dl.sprite_index({"pin": {"x": 0, "y": 0, "width": 8, "height": 8, "pixelRatio": 1},
                             "dot.sdf": {"x": 8, "y": 0, "width": 16, "height": 16, "pixelRatio": 1, "sdf": True},
                             "big": {"x": 0, "y": 16, "width": 16, "height": 16, "pixelRatio": 2}})
    return sheet, index


def test_an_unscaled_unrotated_icon_copies_its_sprite_pixels():
    sheet, index = _sheet()
    paint = dl.icon_paint({})
    quad = dl.icon_quad((10.0, 10.0), dl.icon_box((10.0, 10.0), (8.0, 8.0), 1.0, "top-left", (0.0, 0.0)), 0.0)
    px = dl.icon_pixels(sheet, index["pin"], quad, 1.0, paint, 1.0, 24, 24)
    assert px.shape == (24, 24, 4)
    assert np.allclose(px[10:18, 10:18], (1.0, 0.0, 0.0, 1.0))
    assert np.all(px[9, :] == 0.0) and np.all(px[:, 18] == 0.0) and np.all(px[18, :] == 0.0)
    half = dl.icon_pixels(sheet, index["pin"], quad, 1.0, dl.icon_paint({"icon-opacity": 0.5}), 1.0, 24, 24)
    assert np.allclose(half[12, 12], (0.5, 0.0, 0.0, 0.5))
    quarter = dl.icon_pixels(sheet, index["pin"], quad, 1.0, dl.icon_paint({"icon-opacity": 0.5}), 0.5, 24, 24)
    assert np.allclose(quarter[12, 12], (0.25, 0.0, 0.0, 0.25))


def test_a_scaled_icon_samples_bilinearly_and_a_pixel_ratio_2_sprite_is_half_size():
    sheet, index = _sheet()
    paint = dl.icon_paint({})
    quad = dl.icon_quad((0.0, 0.0), dl.icon_box((0.0, 0.0), (8.0, 8.0), 2.0, "top-left", (0.0, 0.0)), 0.0)
    px = dl.icon_pixels(sheet, index["pin"], quad, 2.0, paint, 1.0, 20, 20)
    assert np.allclose(px[0:16, 0:16], (1.0, 0.0, 0.0, 1.0)) and np.all(px[16, :] == 0.0)
    quad = dl.icon_quad((0.0, 0.0), dl.icon_box((0.0, 0.0), index["big"]["displaySize"], 1.0, "top-left", (0.0, 0.0)),
                        0.0)
    px = dl.icon_pixels(sheet, index["big"], quad, 1.0, paint, 1.0, 20, 20)
    assert np.allclose(px[0:8, 0:8], (0.0, 0.0, 1.0, 1.0)) and np.all(px[8, :] == 0.0)


def test_an_sdf_icon_is_coloured_and_haloed_by_the_paint():
    sheet, index = _sheet()
    quad = dl.icon_quad((8.0, 8.0), dl.icon_box((8.0, 8.0), (16.0, 16.0), 1.0, "center", (0.0, 0.0)), 0.0)
    paint = dl.icon_paint({"icon-color": "#00FF00"})
    px = dl.icon_pixels(sheet, index["dot.sdf"], quad, 1.0, paint, 1.0, 16, 16)
    # the centre is well inside the edge: full fill colour
    assert np.allclose(px[8, 8], (0.0, 1.0, 0.0, 1.0), atol=1e-6)
    # the corners are outside the disc and the halo is off
    assert np.all(px[0, 0] == 0.0)
    halo = dl.icon_pixels(sheet, index["dot.sdf"], quad, 1.0,
                          dl.icon_paint({"icon-color": "#00FF00", "icon-halo-color": "#FF0000", "icon-halo-width": 2}),
                          1.0, 16, 16)
    # at the disc's edge the fill is half and the halo fills the other half, under it
    edge = halo[8, 13]
    assert edge[3] > px[8, 13][3] and edge[0] > 0.0 and edge[1] > 0.0
    assert np.allclose(halo[8, 8], (0.0, 1.0, 0.0, 1.0), atol=1e-6)


def test_a_rotated_icon_covers_its_turned_quad():
    sheet, index = _sheet()
    box = dl.icon_box((12.0, 12.0), (8.0, 8.0), 1.0, "center", (0.0, 0.0))
    px = dl.icon_pixels(sheet, index["pin"], dl.icon_quad((12.0, 12.0), box, 45.0), 1.0, dl.icon_paint({}), 1.0, 24,
                        24)
    assert px[12, 12][3] > 0.99
    assert px[12, 16][3] > 0.99 and px[12, 7][3] > 0.99  # inside the turned square's diamond (|dx| + |dy| <= 5.66)
    assert px[12, 18][3] == 0.0 and px[8, 8][3] == 0.0  # beyond the diamond and at the old corner: empty


# ----------------------------------------------------------------------------------------------------- the document


def test_world_pixel_and_the_tile_of_a_point():
    assert _close(dl.world_pixel(0.0, 0.0, 0), (128.0, 128.0), 1e-9)
    assert _close(dl.world_pixel(180.0, 0.0, 1), (512.0, 256.0), 1e-9)
    assert dl.tile_of(0.0, 0.0, 2) == (2, 2)
    assert dl.tile_of(-180.0, 70.0, 2) == (0, 0)
    assert dl.tile_of(179.9999, -70.0, 2) == (3, 3)
    assert dl.tile_of(-180.0, 60.0, 2) == (0, 1)


def test_the_example_document_runs_and_its_summary_is_stable():
    doc = dl.example_document()
    out = dl.run(doc)
    assert out["zoom"] == 3 and out["tiles"] == (2, 2)
    assert out["heatmap"]["peak"] > 0.5 and out["heatmap"]["covered"] > 100
    assert out["extrusion"]["roofs"] == 3 and out["extrusion"]["skipped"] == 1
    assert out["icons"]["placed"] == 3 and out["icons"]["dropped"] == 1
    assert out["warnings"] == ["W-DL1"]
    assert out == dl.run(doc)
    assert all(re.fullmatch(r"[0-9a-f]{12}", d) for d in out["digests"])


def test_the_example_document_is_valid_and_the_bad_one_lists_every_code():
    assert dl.validate_document(dl.example_document()) == []
    codes = [c for c, _ in dl.validate_document(dl.bad_document())]
    assert codes == ["DL1", "DL2", "DL3", "DL4", "DL5", "DL6", "DL7", "V17"]


def test_validation_one_at_a_time():
    base = dl.example_document()

    def only(child_patch=None, style_patch=None, assets_patch=None):
        doc = dl.example_document()
        child = doc["map"]["children"][0]
        if child_patch:
            child_patch(child)
        if style_patch:
            style_patch(child["style"])
        if assets_patch:
            assets_patch(doc["assets"])
        return [c for c, _ in dl.validate_document(doc)]

    assert only(lambda c: c["sprites"].__setitem__(0, dict(c["sprites"][0], index="nowhere"))) == ["DL1"]
    assert only(lambda c: c["sprites"].__setitem__(0, dict(c["sprites"][0], image="nowhere"))) == ["DL1"]
    assert only(assets_patch=lambda a: a["sprites"]["index"].__setitem__(
        "pin", {"x": 20, "y": 0, "width": 8, "height": 8, "pixelRatio": 1})) == ["DL2"]
    assert only(style_patch=lambda s: s["layers"][0]["paint"].__setitem__("heatmap-radius", 0)) == ["DL3"]
    assert only(style_patch=lambda s: s.__setitem__("light", {"intensity": 2})) == ["DL4"]
    assert only(style_patch=lambda s: s["layers"][2]["layout"].__setitem__("icon-anchor", "middle")) == ["DL5"]
    assert only(style_patch=lambda s: s["layers"][1]["paint"].__setitem__("fill-extrusion-opacity", 3)) == ["DL5"]
    assert only(style_patch=lambda s: s["layers"][0]["paint"].__setitem__(
        "heatmap-color", ["interpolate", ["linear"], ["zoom"], 0, "#000000", 1, "#FFFFFF"])) == ["DL6"]
    assert only(lambda c: c["sprites"].append(dict(c["sprites"][0]))) == ["DL7"]
    assert only(lambda c: c["sprites"][0].__setitem__("scale", 2)) == ["V17"]
    assert dl.validate_document(base) == []


def test_icons_without_a_sprite_warn_and_the_rest_draws():
    doc = dl.example_document()
    doc["map"]["children"][0]["sprites"] = []
    out = dl.run(doc)
    assert out["warnings"] == ["W-DL1"] and out["icons"]["placed"] == 0
    assert out["heatmap"]["peak"] > 0.5 and out["extrusion"]["roofs"] == 3
    doc = dl.example_document()
    doc["map"]["children"][0]["style"]["layers"] = doc["map"]["children"][0]["style"]["layers"][:3]
    assert dl.run(doc)["warnings"] == []


def test_the_3d_map_turns_the_extrusion_layers_into_prisms():
    doc = dl.example_document()
    prisms = dl.building_prisms(doc)
    assert len(prisms) == 3
    assert all(p["top"] > p["base"] for p in prisms)
    assert prisms[0]["color"] == (0.6, 0.6, 0.6, 1.0)


def test_constants():
    assert dl.ANCHORS == ("center", "left", "right", "top", "bottom", "top-left", "top-right", "bottom-left",
                          "bottom-right")
    assert dl.OVERLAPS == ("never", "always", "cooperative")
    assert dl.PLACEMENTS == ("point", "line", "line-center")
    assert dl.TEXT_FITS == ("none", "width", "height", "both")
    assert dl.ALIGNMENTS == ("map", "viewport", "auto")
    assert dl.Z_ORDERS == ("auto", "viewport-y", "source")
    assert dl.EDGE_GAMMA == 0.105 and dl.INNER_EDGE == 0.75 and dl.SDF_PX == 8.0
    assert dl.AMBIENT == 0.03 and dl.GRADIENT_FLOOR == (0.7, 0.98) and dl.GRADIENT_HEIGHT == 150.0
    assert dl.R == 6378137.0 and dl.TILE == 256


# ---------------------------------------------------------------------------------------------------------- the draft


@pytest.fixture(scope="module")
def draft():
    assert os.path.exists(DRAFT), "the draft SREP is missing"
    with open(DRAFT, encoding="utf-8") as f:
        return f.read()


def test_the_draft_has_the_srep_sections(draft):
    for heading in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics", "## Rationale",
                    "## Rejected alternatives", "## Backwards compatibility", "## Engine impact", "## Conformance",
                    "### Numeric tests", "### Kit cases", "## Open issues", "## References", "## History"):
        assert heading in draft, heading
    assert "SREP:            0" in draft
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft
    assert "... no" not in draft


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    for word in ("SR-113", "SREP 9", "SREP 10", "SREP 12", "SREP 14", "`heatmap`", "`fill-extrusion`", "`symbol`",
                 "`sprite`", "`basemap`", "`name`", "`index`", "`image`", "`icons`", "`buildings`", "`light`",
                 "heatmap-radius", "heatmap-weight", "heatmap-intensity", "heatmap-color", "heatmap-opacity",
                 "heatmap-density", "fill-extrusion-height", "fill-extrusion-base", "fill-extrusion-color",
                 "fill-extrusion-opacity", "fill-extrusion-vertical-gradient", "icon-image", "icon-size",
                 "icon-anchor", "icon-offset", "icon-rotate", "icon-padding", "icon-allow-overlap", "icon-overlap",
                 "icon-ignore-placement", "icon-optional", "icon-rotation-alignment", "icon-keep-upright",
                 "icon-text-fit", "icon-text-fit-padding", "icon-opacity", "icon-color", "icon-halo-color",
                 "icon-halo-width", "icon-halo-blur", "symbol-placement", "symbol-spacing", "symbol-sort-key",
                 "pixelRatio", "sdf", "Gaussian", "0.3989422804014327", "1/4080", "smoothstep", "non-zero",
                 "cooperative", "MapLibre", "BSD-3", "render-test", "DL1", "DL2", "DL3", "DL4", "DL5", "DL6", "DL7",
                 "W-DL1", "V17", "data_layers_reference.py", "numpy", "bilinear", "premultiplied", "6378137",
                 "ambient", "luma", "walls", "roofs"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 20
    assert len(dl.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in dl.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = dl.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert dl._same(value, want), (name, value, want)
