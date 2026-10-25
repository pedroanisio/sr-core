"""Tests for the draft SREP "Add wildfire to the terrain grid" (T5 of SREP 12) and its reference module."""
from __future__ import annotations

import importlib.util
import math
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = os.path.join(ROOT, "conformance", "tools", "wildfire_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-wildfire.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wf = _load(MODULE, "wildfire_reference")
tg = wf.terrain()

MPH = 88.0            # ft/min per mi/h
TON_ACRE = 2000.0 / 43560.0   # lb/ft^2 per ton/acre


def _bed(classes, depth_ft, mx, moisture):
    """A fuel bed in the model's own units from (load ton/ac, sav 1/ft, live) classes."""
    return wf.FuelBed(
        classes=tuple(wf.FuelClass(load=l * TON_ACRE, sav=s, live=live, moisture=moisture(live, s))
                      for l, s, live in classes),
        depth=depth_ft, extinction=mx, heat=8000.0)


def _dead(m):
    return lambda live, sav: m


# ------------------------------------------------------------------------------------- the Rothermel equations


@pytest.mark.parametrize("one_h,ten_h,sav,beta_rel,wind_factor,ros", [
    (2.0, 0.0, 2500.0, 0.5195, 17.8, 81.6),
    (1.0, 1.0, 2400.0, 0.5025, 17.9, 40.2),
    (0.1, 1.9, 1417.0, 0.3263, 20.8, 32.0),
    (0.0, 2.0, 109.0, 0.0399, 81.9, 0.0),
])
def test_table_17_of_andrews_2018(one_h, ten_h, sav, beta_rel, wind_factor, ros):
    """Two tons per acre split between the 1-h (SAV 2500) and 10-h (109) classes, depth 1 ft, extinction 20 %,
    dead moisture 5 %, midflame wind 5 mi/h, no slope (Andrews 2018, table 17)."""
    bed = _bed([(one_h, 2500.0, False), (ten_h, 109.0, False)], 1.0, 0.20, _dead(0.05))
    f = wf.fire(bed, 5.0 * MPH, 0.0)
    assert math.isclose(f["bulk_density"], 0.0918, rel_tol=2e-3)
    assert math.isclose(f["packing_ratio"], 0.0029, rel_tol=0.02)
    assert math.isclose(f["sav"], sav, rel_tol=2e-3)
    assert math.isclose(f["relative_packing"], beta_rel, rel_tol=2e-3)
    assert math.isclose(f["wind_factor"], wind_factor, rel_tol=6e-3)
    if ros == 0.0:
        assert f["ros"] < 0.05       # the table prints 0 ft/min: a 10-h bed alone barely burns
    else:
        assert math.isclose(f["ros"], ros, rel_tol=5e-3), f["ros"]


def test_the_optimum_packing_ratio_of_sb4():
    """SB4 has packing ratio 0.00744, optimum 0.006896, relative 1.07996 (Andrews 2018, section 5.2.4.2)."""
    bed = wf.standard_bed("SB4", wf.D2L2)
    f = wf.fire(bed, 0.0, 0.0)
    assert math.isclose(f["packing_ratio"], 0.00744, rel_tol=2e-3)
    assert math.isclose(f["optimum_packing"], 0.006896, rel_tol=2e-3)
    assert math.isclose(f["relative_packing"], 1.07996, rel_tol=2e-3)


def test_bulk_density_of_tl1():
    """TL1 is the densest standard bed at 1.56 lb/ft^3 (Andrews 2018, section 5.2.4.4)."""
    f = wf.fire(wf.standard_bed("TL1", wf.D2L2), 0.0, 0.0)
    assert math.isclose(f["bulk_density"], 1.56, rel_tol=5e-3)


def test_gr2_dynamic_curing_against_behaveplus():
    """GR2, dead moisture 5 %, midflame wind 6 mi/h, no slope: 24.1 ft/min at 90 % live herbaceous moisture and
    6.5 ft/min at 100 % (Andrews 2018, figure 10); with the curing fixed at 50 %: 31.3 and 29.1 ft/min (figure 11)."""
    for herb, want in ((0.90, 24.1), (1.00, 6.5)):
        bed = wf.standard_bed("GR2", wf.moistures(0.05, 0.05, 0.05, herb, 0.90))
        assert math.isclose(wf.fire(bed, 6.0 * MPH, 0.0)["ros"], want, rel_tol=0.02), herb
    for herb, want in ((0.90, 31.3), (1.00, 29.1)):
        bed = wf.standard_bed("GR2", wf.moistures(0.05, 0.05, 0.05, herb, 0.90), curing=0.5)
        assert math.isclose(wf.fire(bed, 6.0 * MPH, 0.0)["ros"], want, rel_tol=0.02), herb
    green = wf.standard_bed("GR2", wf.moistures(0.05, 0.05, 0.05, 1.3, 0.90))
    # Only the 0.1 t/ac of 1-h fuel still carries fire once the herbaceous load is all live and past its extinction.
    assert wf.fire(green, 6.0 * MPH, 0.0)["ros"] < 2.0


def test_curing_follows_the_live_herbaceous_moisture():
    assert wf.curing(0.30) == 1.0 and wf.curing(0.20) == 1.0
    assert wf.curing(1.20) == 0.0 and wf.curing(1.50) == 0.0
    assert math.isclose(wf.curing(0.75), 0.5)
    assert math.isclose(wf.curing(1.00), 2.0 / 9.0)
    bed = wf.standard_bed("GR2", wf.moistures(0.05, 0.05, 0.05, 0.75, 0.90))
    dead_herb = [c for c in bed.classes if not c.live and c.sav == 1800.0]
    live_herb = [c for c in bed.classes if c.live and c.sav == 1800.0]
    assert len(dead_herb) == 1 and len(live_herb) == 1
    assert math.isclose(dead_herb[0].load, 0.5 * TON_ACRE) and math.isclose(live_herb[0].load, 0.5 * TON_ACRE)
    assert dead_herb[0].moisture == 0.05 and live_herb[0].moisture == 0.75


def test_sh8_near_the_live_extinction_moisture():
    """SH8 at 50 % live moisture, midflame wind 6 mi/h: 14 ft/min at 28 % dead moisture and 26 ft/min at 27 %
    (Andrews 2018, section 5.3.4)."""
    slow = wf.fire(wf.standard_bed("SH8", wf.moistures(0.28, 0.28, 0.28, 0.50, 0.50)), 6.0 * MPH, 0.0)["ros"]
    fast = wf.fire(wf.standard_bed("SH8", wf.moistures(0.27, 0.27, 0.27, 0.50, 0.50)), 6.0 * MPH, 0.0)["ros"]
    assert math.isclose(slow, 14.0, rel_tol=0.05), slow
    assert math.isclose(fast, 26.0, rel_tol=0.05), fast


def test_no_spread_at_or_above_the_extinction_moisture():
    bed = _bed([(2.0, 2500.0, False)], 1.0, 0.20, _dead(0.20))
    assert wf.fire(bed, 5.0 * MPH, 0.0)["ros"] == 0.0
    bed = _bed([(2.0, 2500.0, False)], 1.0, 0.20, _dead(0.25))
    assert wf.fire(bed, 5.0 * MPH, 0.0)["ros"] == 0.0
    assert wf.moisture_damping(1.0) == 0.0 and wf.moisture_damping(0.0) == 1.0
    assert math.isclose(wf.moisture_damping(0.5), 1.0 - 2.59 * 0.5 + 5.11 * 0.25 - 3.52 * 0.125)
    assert math.isclose(wf.mineral_damping(0.01), 0.174 * 0.01 ** -0.19)
    assert wf.mineral_damping(1e-9) == 1.0


def test_the_wind_and_slope_factors():
    bed = _bed([(2.0, 2500.0, False)], 1.0, 0.20, _dead(0.05))
    calm = wf.fire(bed, 0.0, 0.0)
    windy = wf.fire(bed, 5.0 * MPH, 0.0)
    steep = wf.fire(bed, 0.0, math.tan(math.radians(30.0)))
    assert calm["wind_factor"] == 0.0 and calm["slope_factor"] == 0.0
    assert math.isclose(windy["ros"], calm["ros"] * (1.0 + windy["wind_factor"]))
    assert math.isclose(steep["ros"], calm["ros"] * (1.0 + steep["slope_factor"]))
    assert math.isclose(steep["slope_factor"], 5.275 * calm["packing_ratio"] ** -0.3 * math.tan(math.radians(30.0)) ** 2)
    assert wf.fire(bed, 0.0, -0.5)["slope_factor"] == 0.0
    # the wind factor is C U^B (beta/beta_op)^-E
    sigma = calm["sav"]
    c, b, e = 7.47 * math.exp(-0.133 * sigma ** 0.55), 0.02526 * sigma ** 0.54, 0.715 * math.exp(-3.59e-4 * sigma)
    assert math.isclose(windy["wind_factor"], c * (5.0 * MPH) ** b * calm["relative_packing"] ** -e)


def test_the_wind_limit_is_an_option_off_by_default():
    bed = _bed([(0.1, 2500.0, False)], 1.0, 0.20, _dead(0.05))
    free = wf.fire(bed, 40.0 * MPH, 0.0)
    capped = wf.fire(bed, 40.0 * MPH, 0.0, wind_limit=True)
    assert free["ros"] > capped["ros"]
    assert math.isclose(capped["wind_factor"], wf.wind_factor(bed, 0.9 * capped["reaction_intensity"]), rel_tol=1e-9)


def test_byram_intensity_flame_length_and_residence_time():
    bed = _bed([(2.0, 2500.0, False)], 1.0, 0.20, _dead(0.05))
    f = wf.fire(bed, 5.0 * MPH, 0.0)
    assert math.isclose(f["residence_time"], 384.0 / f["sav"])
    assert math.isclose(f["fireline_intensity"], f["reaction_intensity"] * f["residence_time"] * f["ros"] / 60.0)
    assert math.isclose(f["flame_length"], 0.45 * f["fireline_intensity"] ** 0.46)
    assert f["flame_length"] > 0.0


# ------------------------------------------------------------------------------------- direction and the ellipse


def test_effective_wind_combines_the_wind_and_the_slope_as_vectors():
    bed = _bed([(2.0, 2500.0, False)], 1.0, 0.20, _dead(0.05))
    flat = wf.effective_wind(bed, (5.0 * MPH, 0.0), (0.0, 0.0))
    assert math.isclose(flat["speed"], 5.0 * MPH) and math.isclose(flat["direction"][0], 1.0)
    # a slope alone is an equivalent wind up the slope
    up = wf.effective_wind(bed, (0.0, 0.0), (0.0, 0.3))
    assert up["speed"] > 0.0 and math.isclose(up["direction"][1], 1.0, abs_tol=1e-12)
    f = wf.fire(bed, 0.0, 0.3)
    assert math.isclose(wf.wind_factor(bed, up["speed"]), f["slope_factor"], rel_tol=1e-9)
    # wind up the slope adds, wind down the slope subtracts
    # (a 1 mi/h wind, weaker than the slope's equivalent wind, so the opposed sum is the smaller)
    with_ = wf.effective_wind(bed, (0.0, 1.0 * MPH), (0.0, 0.3))
    against = wf.effective_wind(bed, (0.0, -1.0 * MPH), (0.0, 0.3))
    assert with_["speed"] > up["speed"] > against["speed"]
    assert math.isclose(with_["speed"], up["speed"] + 1.0 * MPH)
    # cross-slope wind: the head turns between the wind and the upslope
    cross = wf.effective_wind(bed, (5.0 * MPH, 0.0), (0.0, 0.3))
    assert cross["direction"][0] > 0.0 and cross["direction"][1] > 0.0


def test_the_length_to_breadth_ratio_and_the_ellipse():
    assert math.isclose(wf.length_to_breadth(0.0), 1.0, abs_tol=1e-9)
    assert wf.length_to_breadth(5.0 * MPH) > wf.length_to_breadth(2.0 * MPH) > 1.0
    assert wf.length_to_breadth(60.0 * MPH) == wf.length_to_breadth(80.0 * MPH)
    lb = wf.length_to_breadth(5.0 * MPH)
    assert math.isclose(lb, 0.936 * math.exp(0.2566 * 5.0) + 0.461 * math.exp(-0.1548 * 5.0) - 0.397)
    head = 10.0
    assert math.isclose(wf.spread_toward(head, lb, 0.0), head)
    back = wf.spread_toward(head, lb, math.pi)
    flank = wf.spread_toward(head, lb, math.pi / 2.0)
    assert back < flank < head
    e = math.sqrt(lb * lb - 1.0) / lb
    assert math.isclose(back, head * (1.0 - e) / (1.0 + e))
    assert math.isclose(flank, head * (1.0 - e))
    assert math.isclose(wf.spread_toward(head, 1.0, 2.0), head)


# ----------------------------------------------------------------------------------------- the grid and arrival


def _flat_doc(n=9, dx=10.0, model="GR2", wind=None, fuel=None):
    doc = {"version": "1.8", "project": 7, "id": "range", "x": 0.0, "y": 0.0, "width": n * dx, "height": n * dx,
           "cells": n, "metersPerCell": dx, "seed": 11, "display": "none",
           "layers": [{"kind": "bedrock", "value": 0.0}, {"kind": "burn", "value": 0.0}],
           "masks": [], "materials": [], "assets": {}}
    if fuel is not None:
        doc["layers"].append({"kind": "fuel", "value": fuel})
    doc["physics"] = {"winds": [{"id": "w1", "speed": wind or 0.0, "direction": 0.0, "seed": 3}]}
    doc["wildfire"] = {"fuelModel": model, "ignitionX": (n // 2 + 0.5) * dx, "ignitionY": (n // 2 + 0.5) * dx,
                       "ignitionTime": 0.0, "wind": "w1" if wind else None, "windAdjustment": 0.4,
                       "moisture1h": 0.06, "moisture10h": 0.07, "moisture100h": 0.08, "moistureHerb": 0.60,
                       "moistureWoody": 0.90}
    return doc


def test_arrival_times_grow_with_the_distance_on_flat_calm_ground():
    doc = _flat_doc()
    out = wf.arrival(doc)
    c = 4
    t = out["arrival"]
    assert t[c][c] == 0.0
    assert math.isclose(t[c][c + 1], t[c][c - 1]) and math.isclose(t[c + 1][c], t[c - 1][c])
    assert math.isclose(t[c][c + 1], t[c + 1][c])
    assert math.isclose(t[c][c + 2], 2.0 * t[c][c + 1])
    assert math.isclose(t[c + 1][c + 1], math.sqrt(2.0) * t[c][c + 1])
    ros = out["head"][c][c]          # metres per second at the ignition cell
    assert math.isclose(t[c][c + 1], 10.0 / ros)
    assert all(math.isfinite(v) for row in t for v in row)


def test_wind_pushes_the_head_downwind_and_slows_the_back():
    doc = _flat_doc(wind=5.0)
    out = wf.arrival(doc)
    c, t = 4, out["arrival"]
    assert t[c][c + 1] < t[c + 1][c] < t[c][c - 1]
    lb = wf.length_to_breadth(5.0 * 0.4 * wf.FT_PER_MIN_PER_M_S)
    e = math.sqrt(lb * lb - 1.0) / lb
    assert math.isclose(t[c][c - 1] / t[c][c + 1], (1.0 + e) / (1.0 - e), rel_tol=1e-6)
    assert math.isclose(t[c + 1][c] / t[c][c + 1], 1.0 / (1.0 - e), rel_tol=1e-6)


def test_the_fire_climbs_a_slope_faster_than_it_descends():
    doc = _flat_doc()
    flat = wf.arrival(doc)["arrival"]
    built = tg.build(doc)
    slope = [[-(j * 10.0) * 0.3 for i in range(9)] for j in range(9)]   # rising toward smaller j (up the grid)
    layers = dict(built["layers"], bedrock=slope)
    t = wf.arrival_from_layers(doc, layers)["arrival"]
    c = 4
    assert t[c - 1][c] < flat[c - 1][c]
    assert t[c - 1][c] < t[c + 1][c]
    assert math.isclose(t[c][c + 1], t[c][c - 1])


def test_a_firebreak_stops_the_fire_and_the_fuel_layer_scales_the_bed():
    doc = _flat_doc(fuel=0.5)
    base = wf.arrival(_flat_doc())["arrival"]
    half = wf.arrival(doc)["arrival"]
    assert half[4][5] != base[4][5]
    doc = _flat_doc(fuel=1.0)
    built = tg.build(doc)
    fuel = [[0.0 if i == 6 else wf.standard_load("GR2") for i in range(9)] for j in range(9)]
    out = wf.arrival_from_layers(doc, dict(built["layers"], fuel=fuel))
    t = out["arrival"]
    assert all(math.isinf(t[j][6]) for j in range(9))
    assert all(math.isinf(t[j][7]) and math.isinf(t[j][8]) for j in range(9))
    assert math.isfinite(t[4][5])
    # the fuel layer equal to the model's load reproduces the model
    same = wf.arrival_from_layers(doc, dict(built["layers"], fuel=tg.flat(9, 9, wf.standard_load("GR2"))))
    assert same["arrival"] == wf.arrival(_flat_doc())["arrival"]


def test_the_ignition_time_shifts_every_arrival():
    doc = _flat_doc()
    doc["wildfire"]["ignitionTime"] = 120.0
    t = wf.arrival(doc)["arrival"]
    base = wf.arrival(_flat_doc())["arrival"]
    assert all(math.isclose(t[j][i], base[j][i] + 120.0) for j in range(9) for i in range(9))


def test_a_time_varying_wind_is_read_when_the_fire_leaves_each_cell():
    doc = _flat_doc(wind=5.0)
    doc["physics"]["winds"][0]["speed"] = lambda t: 0.0 if t < 1e9 else 5.0
    calm = wf.arrival(_flat_doc())["arrival"]
    assert wf.arrival(doc)["arrival"] == calm


def test_run_writes_the_burn_and_fuel_layers():
    doc = wf.example_document()
    out = wf.run(doc, 600.0)
    burn = out["layers"]["burn"]
    assert out["shape"] == (16, 12)
    assert all(0.0 <= v <= 1.0 for row in burn for v in row)
    assert max(v for row in burn for v in row) == 1.0
    assert any(v == 0.0 for row in burn for v in row)
    assert out["burning"] > 0 and out["burnt"] > 0
    fuel = out["layers"]["fuel"]
    before = wf.run(doc, 0.0)["layers"]["fuel"]
    assert all(fuel[j][i] <= before[j][i] for j in range(12) for i in range(16))
    assert out["digest"] == wf.run(doc, 600.0)["digest"]
    assert out["digest"] != wf.run(doc, 300.0)["digest"]
    assert wf.run(doc, -1.0)["burnt"] == 0
    assert "flame" in out["layers"] or "flame" in out


def test_the_burn_fraction_rises_over_the_residence_time():
    assert wf.burn_fraction(0.0, 10.0, 30.0) == 0.0
    assert wf.burn_fraction(10.0, 10.0, 30.0) == 0.0
    assert math.isclose(wf.burn_fraction(25.0, 10.0, 30.0), 0.5)
    assert wf.burn_fraction(100.0, 10.0, 30.0) == 1.0
    assert wf.burn_fraction(100.0, math.inf, 30.0) == 0.0


# --------------------------------------------------------------------------------------------------- validation


def test_validation_lists_the_rules():
    assert wf.validate_document(wf.example_document()) == []
    assert wf.validate_document(wf.bad_document()) == ["WF1", "WF2", "WF3", "WF4", "WF5"]
    with pytest.raises(wf.WildfireError):
        wf.run(wf.bad_document(), 1.0)
    old = wf.example_document()
    old["version"] = "1.7"
    assert wf.validate_document(old) == ["V17"]
    plain = wf.example_document()
    del plain["wildfire"]
    assert wf.validate_document(plain) == []


@pytest.mark.parametrize("change,code", [
    (dict(moisture1h=-0.1), "WF1"), (dict(moisture10h=3.0), "WF1"), (dict(moistureHerb=-1.0), "WF1"),
    (dict(windAdjustment=1.5), "WF1"), (dict(curing=1.5), "WF1"), (dict(ignitionTime=-1.0), "WF1"),
    (dict(fuelModel="XX9"), "WF2"), (dict(ignitionX=-1.0), "WF4"), (dict(ignitionY=1e9), "WF4"),
    (dict(wind="w9"), "WF5"),
])
def test_validation_rules_one_at_a_time(change, code):
    doc = wf.example_document()
    doc["wildfire"].update(change)
    assert wf.validate_document(doc) == [code]


def test_validation_needs_the_burn_layer():
    doc = wf.example_document()
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "burn"]
    assert wf.validate_document(doc) == ["WF3"]


def test_the_standard_fuel_models():
    assert len(wf.FUEL_MODELS) == 40
    assert set(wf.FUEL_MODELS) >= {"GR1", "GR9", "GS1", "GS4", "SH1", "SH9", "TU1", "TU5", "TL1", "TL9", "SB1", "SB4"}
    gr1 = wf.FUEL_MODELS["GR1"]
    assert gr1["loads"] == (0.10, 0.00, 0.00, 0.30, 0.00) and gr1["sav"] == (2200, 2000, 9999)
    assert gr1["depth"] == 0.4 and gr1["extinction"] == 15 and gr1["heat"] == 8000 and gr1["dynamic"]
    sh5 = wf.FUEL_MODELS["SH5"]
    assert sh5["loads"] == (3.60, 2.10, 0.00, 0.00, 2.90) and sh5["sav"] == (750, 9999, 1600) and not sh5["dynamic"]
    assert wf.FUEL_MODELS["GR6"]["heat"] == 9000
    assert math.isclose(wf.standard_load("GR2"), 1.10 * TON_ACRE / wf.LB_PER_FT2_PER_KG_M2)
    assert wf.SAV_10H == 109.0 and wf.SAV_100H == 30.0 and wf.TOTAL_MINERAL == 0.0555
    assert wf.EFFECTIVE_MINERAL == 0.010 and wf.PARTICLE_DENSITY == 32.0


def test_constants():
    d = wf.DEFAULTS
    assert d["fuelModel"] == "GR2" and d["ignitionX"] == 0.0 and d["ignitionY"] == 0.0 and d["ignitionTime"] == 0.0
    assert d["wind"] is None and d["windAdjustment"] == 0.4 and d["curing"] is None
    assert d["moisture1h"] == 0.06 and d["moisture10h"] == 0.07 and d["moisture100h"] == 0.08
    assert d["moistureHerb"] == 0.60 and d["moistureWoody"] == 0.90 and d["windLimit"] is False
    assert math.isclose(wf.FT_PER_MIN_PER_M_S, 196.8503937, rel_tol=1e-9)
    assert math.isclose(wf.LB_PER_FT2_PER_KG_M2, 0.2048161436, rel_tol=1e-9)
    assert wf.MAX_LENGTH_TO_BREADTH == 8.0
    assert wf.D2L2 == (0.06, 0.07, 0.08, 0.60, 0.90)


# ------------------------------------------------------------------------------------------------ the draft


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
    for word in ("SR-109", "SR-100", "SR-101", "SREP 12", "SREP 14", "`wildfire`", "fuelModel", "ignitionX",
                 "ignitionY", "ignitionTime", "wind", "windAdjustment", "windLimit", "curing", "moisture1h",
                 "moisture10h", "moisture100h", "moistureHerb", "moistureWoody", "WF1", "WF2", "WF3", "WF4", "WF5",
                 "V17", "wildfire_reference.py", "terrain-grid", "wind-field", "Rothermel", "Albini", "Andrews",
                 "Scott", "Burgan", "BehavePlus", "Finney", "Anderson", "Byram", "Huygens", "minimum travel time",
                 "Dijkstra", "`fuel`", "`burn`", "`bedrock`", "length-to-breadth", "81.6", "24.1", "GR2", "SH8",
                 "SB4", "TL1", "residence", "flame length", "public domain", "dynamic", "extinction",
                 "packing ratio", "reaction intensity", "propagating flux", "ft/min", "mi/h"):
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
    assert len(wf.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in wf.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = wf.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert wf._same(value, want), (name, value, want)
