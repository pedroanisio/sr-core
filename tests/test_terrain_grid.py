"""Tests for the draft SREP "Add the terrain grid" (F2 of SREP 12) and its reference module."""
import hashlib
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "terrain_grid_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-terrain-grid.md")


def _load():
    spec = importlib.util.spec_from_file_location("terrain_grid_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tg = _load()
rs = tg.streams()


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _flat(nx, ny, value):
    return [[float(value)] * nx for _ in range(ny)]


def _plane(nx, ny, gx, gy, dx=1.0):
    return [[gx * i * dx + gy * j * dx for i in range(nx)] for j in range(ny)]


# ------------------------------------------------------------------------------------ the grid and the layers


def test_grid_shape_follows_the_longer_side_and_the_aspect():
    assert tg.grid({"width": 300.0, "height": 200.0, "cells": 256}) == (256, 171)
    assert tg.grid({"width": 200.0, "height": 300.0, "cells": 256}) == (171, 256)
    assert tg.grid({"width": 100.0, "height": 100.0, "cells": 8}) == (8, 8)
    # a very thin rectangle still has at least 4 cells across
    assert tg.grid({"width": 1000.0, "height": 1.0, "cells": 64}) == (64, 4)
    with pytest.raises(tg.TerrainError):
        tg.grid({"width": 100.0, "height": 100.0, "cells": 3})
    with pytest.raises(tg.TerrainError):
        tg.grid({"width": 100.0, "height": 100.0, "cells": 4097})


def test_layer_kinds_have_units_and_the_solid_ones_make_the_surface():
    assert set(tg.LAYER_KINDS) == {"bedrock", "loose", "lava", "ice", "snow", "water", "sediment", "flow",
                                   "temperature", "fuel", "burn", "hardness", "wetness"}
    assert tg.SOLID_LAYERS == ("bedrock", "loose", "lava", "ice", "snow")
    assert tg.LAYER_KINDS["bedrock"]["unit"] == "m" and tg.LAYER_KINDS["flow"]["channels"] == 2
    assert tg.LAYER_KINDS["temperature"]["unit"] == "K" and tg.LAYER_KINDS["fuel"]["unit"] == "kg/m2"
    for kind in ("burn", "hardness", "wetness"):
        assert tg.LAYER_KINDS[kind]["range"] == (0.0, 1.0)
    layers = {"bedrock": _flat(3, 2, 10.0), "loose": _flat(3, 2, 0.5), "water": _flat(3, 2, 2.0),
              "snow:powder": _flat(3, 2, 0.25)}
    assert tg.surface(layers) == _flat(3, 2, 10.75)
    assert tg.water_surface(layers) == _flat(3, 2, 12.75)
    # a missing solid layer counts as zero; no solid layer is an error
    assert tg.surface({"water": _flat(2, 2, 1.0), "ice": _flat(2, 2, 3.0)}) == _flat(2, 2, 3.0)
    with pytest.raises(tg.TerrainError):
        tg.surface({"water": _flat(2, 2, 1.0)})


# ------------------------------------------------------------------------------------ noise and generation


def test_lattice_values_are_the_d24_draws_and_the_noise_interpolates_them():
    e = rs.E(7, "ground", None, tg.PURPOSE)
    assert tg.lattice_value(e, 3, 2, 5) == 2.0 * rs.U(e, 3, rs.pack(2, 5, 0)) - 1.0
    # at lattice points the value noise is the lattice value, between them the quintic blend
    assert _close(tg.value2(e, 3, 2.0, 5.0), tg.lattice_value(e, 3, 2, 5))
    a, b = tg.lattice_value(e, 3, 2, 5), tg.lattice_value(e, 3, 3, 5)
    assert _close(tg.value2(e, 3, 2.5, 5.0), (a + b) / 2.0)
    assert _close(tg.value2(e, 3, 2.25, 5.0), a + (b - a) * tg.fade(0.25))
    assert -1.0 <= tg.value2(e, 3, 17.3, -4.6) <= 1.0
    # negative coordinates address the lattice left of the origin
    assert tg.value2(e, 3, -1.0, 0.0) == tg.lattice_value(e, 3, -1, 0)


def test_fbm_ridged_and_billow_stay_in_range_and_differ():
    e = rs.E(7, "ground", None, tg.PURPOSE)
    gen = {"octaves": 6, "frequency": 3.0, "lacunarity": 2.0, "gain": 0.5}
    vals = {k: [tg.noise(k, e, 0, x * 0.37, y * 0.53, gen) for x in range(12) for y in range(12)]
            for k in tg.NOISE_KINDS}
    for k, v in vals.items():
        assert all(-1.0 <= x <= 1.0 for x in v), k
    assert all(x >= -1.0 for x in vals["ridged"]) and max(vals["ridged"]) > 0.0
    assert vals["fbm"] != vals["ridged"] != vals["billow"]
    # one octave of fbm is the value noise itself at the base frequency
    one = dict(gen, octaves=1)
    assert _close(tg.noise("fbm", e, 0, 1.3, 0.7, one), tg.value2(e, tg.octave_channel(0, 0), 1.3 * 3.0, 0.7 * 3.0))
    # octaves read as 1 to 16
    assert tg.noise("fbm", e, 0, 1.3, 0.7, dict(gen, octaves=16)) == tg.noise("fbm", e, 0, 1.3, 0.7, dict(gen, octaves=99))
    with pytest.raises(tg.TerrainError):
        tg.noise("simplex", e, 0, 1.0, 1.0, gen)


def test_terraces_quantise_with_a_sharpness_and_sharpness_one_is_the_identity():
    assert _close(tg.terrace(0.3, 4, 1.0), 0.3)
    assert _close(tg.terrace(0.3, 0, 8.0), 0.3)
    # with four levels 0.3 lies in the second step; a high sharpness pushes it to the step's floor
    assert _close(tg.terrace(0.3, 4, 8.0), (1.0 + 0.2 ** 8 / (0.2 ** 8 + 0.8 ** 8)) / 4.0)
    assert _close(tg.terrace(0.3, 4, 100.0), 0.25, 1e-6)
    assert _close(tg.terrace(1.0, 4, 8.0), 1.0) and _close(tg.terrace(0.0, 4, 8.0), 0.0)
    with pytest.raises(tg.TerrainError):
        tg.terrace(0.3, 4, 0.5)


def test_warp_displaces_the_sample_point_by_noise_in_cells():
    e = rs.E(7, "ground", None, tg.PURPOSE)
    gen = {"octaves": 3, "frequency": 2.0, "lacunarity": 2.0, "gain": 0.5, "warp": 5.0, "warpFrequency": 1.0}
    x, y = tg.warped(e, 0, 10.0, 6.0, gen, nx=64, ny=64)
    assert (x, y) != (10.0, 6.0)
    assert math.dist((x, y), (10.0, 6.0)) <= 5.0 * math.sqrt(2.0) + 1e-9
    assert tg.warped(e, 0, 10.0, 6.0, dict(gen, warp=0.0), nx=64, ny=64) == (10.0, 6.0)


def test_generate_layer_fills_the_grid_in_the_layer_unit_and_is_deterministic():
    spec = {"id": "ground", "width": 100.0, "height": 50.0, "cells": 16, "metersPerCell": 10.0, "seed": 5}
    gen = {"noise": "fbm", "octaves": 4, "frequency": 3.0, "amplitude": 200.0, "offset": 100.0}
    h = tg.generate_layer(spec, 0, gen, project=7)
    assert len(h) == 8 and len(h[0]) == 16
    assert all(100.0 <= v <= 300.0 for row in h for v in row)
    assert max(v for row in h for v in row) - min(v for row in h for v in row) > 20.0
    assert tg.generate_layer(spec, 0, gen, project=7) == h
    # another seed, another project or another layer index changes the layer; the id is part of the seed
    assert tg.generate_layer(dict(spec, seed=6), 0, gen, project=7) != h
    assert tg.generate_layer(spec, 0, gen, project=8) != h
    assert tg.generate_layer(spec, 1, gen, project=7) != h
    assert tg.generate_layer(dict(spec, id="other"), 0, gen, project=7) != h
    # terraces and warp apply inside the amplitude
    t = tg.generate_layer(spec, 0, dict(gen, terraces=4, terraceSharpness=50.0), project=7)
    levels = [(v - 100.0) / 50.0 for row in t for v in row]
    near = sum(1 for l in levels if abs(l - round(l)) < 0.05)
    assert near >= 0.9 * len(levels)
    # a flat layer is a value
    assert tg.generate_layer(spec, 2, {"value": 3.5}, project=7) == _flat(16, 8, 3.5)
    with pytest.raises(tg.TerrainError):
        tg.generate_layer(spec, 0, dict(gen, octaves=0), project=7)


def test_layers_from_images_decode_the_encodings_and_resample_nearest():
    gray = [[0.0, 0.5], [1.0, 0.25]]
    h = tg.from_image(gray, 4, 4, "gray", amplitude=100.0, offset=10.0)
    assert h[0][0] == 10.0 and h[0][2] == 60.0 and h[2][0] == 110.0 and h[3][3] == 35.0
    assert tg.decode("gray16", (32768,)) == pytest.approx(32768 / 65535)
    # Terrarium: (R 256 + G + B / 256) - 32768; Mapbox: -10000 + (R 65536 + G 256 + B) / 10
    assert tg.decode("terrarium", (128, 0, 0)) == 0.0
    assert tg.decode("terrarium", (128, 1, 128)) == 1.5
    assert _close(tg.decode("mapbox", (1, 134, 160)), -10000.0 + (65536 + 134 * 256 + 160) * 0.1)
    assert tg.decode("gray", (0.25,)) == 0.25
    with pytest.raises(tg.TerrainError):
        tg.decode("png", (0,))
    # elevation encodings are metres already: amplitude scales them, offset shifts
    dem = [[(128, 0, 0), (128, 100, 0)], [(128, 200, 0), (129, 0, 0)]]
    h = tg.from_image(dem, 2, 2, "terrarium", amplitude=1.0, offset=0.0)
    assert h == [[0.0, 100.0], [200.0, 256.0]]


# ------------------------------------------------------------------------------------ derived quantities and masks


def test_gradient_slope_and_curvature_in_physical_units():
    h = _plane(6, 5, 1.0, 0.0, dx=2.0)  # rises 1 m per metre along x, cells 2 m apart
    gx, gy = tg.gradient(h, 2.0)
    assert all(_close(v, 1.0) for row in gx for v in row) and all(v == 0.0 for row in gy for v in row)
    s = tg.slope_degrees(h, 2.0)
    assert all(_close(v, 45.0) for row in s for v in row)
    assert all(v == 0.0 for row in tg.slope_degrees(_flat(4, 4, 7.0), 1.0) for v in row)
    bowl = [[(i - 3) ** 2 + (j - 3) ** 2 for i in range(7)] for j in range(7)]
    c = tg.curvature(bowl, 1.0)
    assert _close(c[3][3], 4.0) and _close(c[2][4], 4.0)
    # cells 0.5 m apart make the same grid four times as curved
    assert _close(tg.curvature(bowl, 0.5)[3][3], 16.0)
    # the edge cells use the one-sided difference, so a plane has the same slope everywhere
    assert _close(tg.gradient(h, 2.0)[0][0][0], 1.0)


def test_flow_accumulation_routes_each_cell_to_its_steepest_lower_neighbour():
    h = _plane(3, 5, 0.0, -1.0)  # falls towards +y: every column drains downward
    acc = tg.flow_accumulation(h)
    assert acc[0] == [1, 1, 1] and acc[4] == [5, 5, 5]
    # a cone drains to its apex... inverted: a pit collects everything
    pit = [[max(abs(i - 2), abs(j - 2)) for i in range(5)] for j in range(5)]
    acc = tg.flow_accumulation(pit)
    assert acc[2][2] == 25
    # a flat grid has no flow: every cell keeps its own unit
    assert tg.flow_accumulation(_flat(3, 3, 1.0)) == [[1, 1, 1]] * 3
    # diagonals are reached by the steeper of the two routes (distance sqrt 2)
    ridge = [[0.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, -1.0]]
    assert tg.flow_accumulation(ridge)[2][2] >= 2


def test_masks_ramp_over_min_and_max_with_a_feather():
    q = [[0.0, 5.0, 10.0, 15.0, 20.0]]
    hard = tg.mask_values(q, {"min": 5.0, "max": 15.0})
    assert hard == [[0.0, 1.0, 1.0, 1.0, 0.0]]
    soft = tg.mask_values(q, {"min": 5.0, "max": 15.0, "feather": 10.0})
    assert _close(soft[0], (0.5, 1.0, 1.0, 1.0, 0.5))
    assert _close(tg.mask_values(q, {"min": 5.0, "max": 15.0, "feather": 10.0, "invert": True})[0], (0.5, 0.0, 0.0, 0.0, 0.5))
    assert tg.mask_values(q, {"min": 12.0})[0] == [0.0, 0.0, 0.0, 1.0, 1.0]
    with pytest.raises(tg.TerrainError):
        tg.mask_values(q, {"min": 9.0, "max": 1.0})


def test_mask_kinds_measure_the_ground_surface():
    spec = {"id": "g", "width": 60.0, "height": 60.0, "cells": 6, "metersPerCell": 1.0}
    layers = {"bedrock": _plane(6, 6, 1.0, 0.0), "water": _flat(6, 6, 3.0)}
    m = tg.mask(spec, layers, {"id": "steep", "kind": "slope", "min": 40.0})
    assert all(v == 1.0 for row in m for v in row)
    m = tg.mask(spec, layers, {"id": "high", "kind": "altitude", "min": 2.5})
    assert m[0][2] == 0.0 and m[0][3] == 1.0
    assert all(v == 0.0 for row in tg.mask(spec, layers, {"id": "c", "kind": "curvature", "min": 1.0}) for v in row)
    # flow is log10 of the D8 accumulation
    down = {"bedrock": _plane(6, 6, 0.0, -1.0)}
    m = tg.mask(spec, down, {"id": "river", "kind": "flow", "min": math.log10(4.0)})
    assert m[0][0] == 0.0 and m[5][0] == 1.0 and m[2][0] == 0.0 and m[3][0] == 1.0
    with pytest.raises(tg.TerrainError):
        tg.mask(spec, layers, {"id": "x", "kind": "aspect", "min": 0.0})


# ------------------------------------------------------------------------------------ display


def test_hillshade_is_the_engine_formula_with_physical_slopes():
    flat = tg.hillshade(_flat(4, 4, 3.0), 1.0, azimuth=315.0, elevation=45.0, relief=1.0)
    assert all(_close(v, 0.25 + 0.75 * math.sin(math.pi / 4.0)) for row in flat for v in row)
    # the sun straight overhead lights every slope the same from above: flat is 1
    assert _close(tg.hillshade(_flat(2, 2, 0.0), 1.0, 0.0, 90.0, 1.0)[0][0], 1.0)
    # a slope facing a low sun is brighter than one facing away; a steeper relief darkens it under a high sun
    h = _plane(5, 5, 0.0, -1.0)  # rises towards -y (up the image), so it faces down the image (azimuth 180)
    toward = tg.hillshade(h, 1.0, azimuth=180.0, elevation=20.0, relief=1.0)[2][2]
    away = tg.hillshade(h, 1.0, azimuth=0.0, elevation=20.0, relief=1.0)[2][2]
    assert toward > away >= 0.25
    assert tg.hillshade(h, 1.0, 0.0, 90.0, 4.0)[2][2] < tg.hillshade(h, 1.0, 0.0, 90.0, 1.0)[2][2]
    # the sun vector matches erosion.rs: (sin az cos el, -cos az cos el, sin el)
    assert _close(tg.sun_vector(90.0, 0.0), (1.0, 0.0, 0.0)) and _close(tg.sun_vector(0.0, 0.0), (0.0, -1.0, 0.0))


def test_picture_ramps_altitude_splats_materials_and_shades():
    spec = {"id": "g", "width": 40.0, "height": 40.0, "cells": 4, "metersPerCell": 1.0, "colorLow": (0.0, 0.0, 0.0, 1.0),
            "colorHigh": (1.0, 1.0, 1.0, 1.0), "sunElevation": 90.0, "sunAzimuth": 0.0, "relief": 1.0,
            "masks": [{"id": "high", "kind": "altitude", "min": 2.5}],
            "materials": [{"color": (1.0, 0.0, 0.0, 1.0), "mask": "high"}]}
    layers = {"bedrock": _plane(4, 4, 1.0, 0.0)}
    px = tg.picture(spec, layers)
    assert len(px) == 4 and len(px[0]) == 4
    # altitude 0..3 ramps black to white; the overhead sun on a 45 degree slope shades by cos 45
    shade = 0.25 + 0.75 * math.cos(math.pi / 4.0)
    assert _close(px[0][0], (0.0, 0.0, 0.0, 1.0))
    assert _close(px[0][1], (shade / 3.0, shade / 3.0, shade / 3.0, 1.0))
    # the material covers the cells above 2.5 m
    assert _close(px[0][3], (shade, 0.0, 0.0, 1.0))
    # without masks the picture is the ramp alone
    plain = tg.picture(dict(spec, masks=[], materials=[]), layers)
    assert _close(plain[0][3], (shade, shade, shade, 1.0))
    with pytest.raises(tg.TerrainError):
        tg.picture(dict(spec, materials=[{"color": (1.0, 0.0, 0.0, 1.0), "mask": "missing"}]), layers)


def test_mesh_is_the_heightfield_of_srep_70_over_the_physical_extent():
    spec = {"id": "g", "width": 40.0, "height": 40.0, "cells": 4, "metersPerCell": 10.0}
    layers = {"bedrock": _plane(4, 4, 1.0, 0.0, dx=10.0)}
    verts, tris = tg.mesh(spec, layers)
    assert len(verts) == 16 and len(tris) == 18
    # x spans the physical width (cells times metersPerCell) centred, z the physical depth, y is minus the height
    xs = sorted({v[0] for v in verts})
    zs = sorted({v[2] for v in verts})
    assert _close(xs, (-20.0, -20.0 / 3.0, 20.0 / 3.0, 20.0)) and _close(zs, (-20.0, -20.0 / 3.0, 20.0 / 3.0, 20.0))
    assert _close(verts[0], (-20.0, 0.0, -20.0))
    assert _close(verts[3][1], -30.0)
    assert all(0 <= k < 16 for t in tris for k in t) and all(len(t) == 3 for t in tris)
    assert tg.mesh_counts(spec) == (16, 18)
    # a grid side is never thinner than 4 cells, so a 2:1 rectangle at 4 cells is 4 x 4
    assert tg.mesh_counts({"id": "g", "width": 40.0, "height": 20.0, "cells": 4}) == (16, 18)


# ------------------------------------------------------------------------------------ the element end to end


def test_build_terrain_generates_every_layer_and_derives_masks_and_the_digest():
    doc = tg.example_document()
    t = tg.build(doc)
    assert set(t["layers"]) == {"bedrock", "loose", "water"}
    assert t["shape"] == (16, 12)
    assert set(t["masks"]) == {"steep", "high", "valley"}
    assert all(0.0 <= v <= 1.0 for m in t["masks"].values() for row in m for v in row)
    # the digest is the sha256 of the layers rounded to millimetres, so a re-run is byte-identical
    assert t["digest"] == tg.build(doc)["digest"]
    assert len(t["digest"]) == 64
    other = dict(doc, seed=doc["seed"] + 1)
    assert tg.build(other)["digest"] != t["digest"]
    assert tg.digest_of(t["layers"]) == t["digest"]


# ------------------------------------------------------------------------------------ validation


def test_validation_rules_tg1_to_tg6_and_v17():
    doc = tg.example_document()
    tg.validate_terrain(doc)
    d = tg.example_document()
    d["layers"].append({"kind": "bedrock", "value": 1.0})
    with pytest.raises(tg.TerrainError, match="TG1"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["layers"].append({"kind": "snow", "type": "powder", "value": 0.1})
    d["layers"].append({"kind": "snow", "type": "powder", "value": 0.2})
    with pytest.raises(tg.TerrainError, match="TG1"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["layers"].append({"kind": "mud", "value": 1.0})
    with pytest.raises(tg.TerrainError, match="TG1"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["cells"] = 2
    with pytest.raises(tg.TerrainError, match="TG2"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["metersPerCell"] = 0.0
    with pytest.raises(tg.TerrainError, match="TG2"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["layers"][0]["generate"]["octaves"] = 17
    with pytest.raises(tg.TerrainError, match="TG3"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["layers"][0]["generate"]["gain"] = 1.5
    with pytest.raises(tg.TerrainError, match="TG3"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["layers"][0]["generate"]["terraces"] = 65
    with pytest.raises(tg.TerrainError, match="TG3"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["layers"][0]["from"] = "dem"
    with pytest.raises(tg.TerrainError, match="TG3"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["masks"][0]["kind"] = "aspect"
    with pytest.raises(tg.TerrainError, match="TG4"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["masks"].append(dict(d["masks"][0]))
    with pytest.raises(tg.TerrainError, match="TG4"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["masks"][0]["feather"] = -1.0
    with pytest.raises(tg.TerrainError, match="TG4"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["materials"][0]["mask"] = "nowhere"
    with pytest.raises(tg.TerrainError, match="TG5"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["display"] = "hologram"
    with pytest.raises(tg.TerrainError, match="TG6"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["objects"] = [{"primitive": "terrain", "terrain": "nowhere"}]
    with pytest.raises(tg.TerrainError, match="TG6"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["objects"] = [{"primitive": "terrain"}]
    with pytest.raises(tg.TerrainError, match="TG6"):
        tg.validate_terrain(d)
    d = tg.example_document()
    d["version"] = "1.7"
    with pytest.raises(tg.TerrainError, match="V17"):
        tg.validate_terrain(d)


def test_constants():
    assert tg.PURPOSE == "terrain"
    assert tg.MIN_CELLS == 4 and tg.MAX_CELLS == 4096
    assert tg.MAX_OCTAVES == 16 and tg.MAX_TERRACES == 64
    assert tg.NOISE_KINDS == ("fbm", "ridged", "billow")
    assert tg.MASK_KINDS == ("slope", "altitude", "curvature", "flow")
    assert tg.DISPLAYS == ("picture", "surface", "none")
    assert tg.ENCODINGS == ("gray", "gray16", "terrarium", "mapbox")
    assert tg.DIGEST_DECIMALS == 3
    assert tg.OCTAVE_STRIDE == 1024 and tg.LAYER_STRIDE == 4096


# ------------------------------------------------------------------------------------ the draft and its table


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
    for word in ("SR-100", "SREP 12", "SREP 14", "SREP 70", "SREP 10", "terrain", "layer", "bedrock", "loose", "water",
                 "sediment", "lava", "snow", "ice", "fuel", "burn", "hardness", "wetness", "flow", "temperature",
                 "cells", "metersPerCell", "generate", "fbm", "ridged", "billow", "octaves", "frequency",
                 "lacunarity", "gain", "warp", "terraces", "terraceSharpness", "amplitude", "offset", "from",
                 "encoding", "terrarium", "mapbox", "mask", "slope", "altitude", "curvature", "material",
                 "display", "picture", "surface", "sunAzimuth", "sunElevation", "relief", "colorLow", "colorHigh",
                 "primitive=\"terrain\"", "heightfield", "D24", "pack(i, j, 0)", "random-streams", "TG1", "TG2",
                 "TG3", "TG4", "TG5", "TG6", "V17", "terrain_grid_reference.py", "Gaea", "World Machine",
                 "Houdini", "one grid resolution", "sha256"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 24


def test_the_table_is_what_the_module_prints(draft):
    assert len(tg.TABLE) == len(_draft_rows())
    for (name, expr, _value), (dname, dexpr, _dvalue) in zip(tg.TABLE, _draft_rows()):
        assert name == dname and expr == dexpr


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = tg.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or tg._same(got, want), f"{name}: {got!r} != {want!r}"
