"""Reference for the draft SREP "Add wildfire to the terrain grid" (T5 of SREP 12).

One `wildfire` child of a `terrain` (the F2 terrain-grid draft) ignites a surface fire at a point and time and
spreads it over the grid by Rothermel's surface fire spread model (Rothermel 1972, with Albini's 1976
adjustments, as Andrews 2018 lays them out and BehavePlus computes them) on one of the 40 standard fire
behaviour fuel models of Scott and Burgan (2005), both USDA Forest Service publications in the public domain.
The midflame wind is the wind of the F4 draft times `windAdjustment`; wind and slope combine as vectors into
an effective wind (Andrews 2018, section 4.1) that sets the head's direction and rate; the fire's shape is the
ellipse of Anderson (1983) with the length-to-breadth ratio of the effective wind, so the rate toward any
direction is the head's times (1 - e) / (1 - e cos theta) (Finney 1998, as FARSITE); the arrival time of every
cell is the minimum travel time over the eight-neighbour graph (Finney 2002), the rate out of a cell read with
the wind at the moment the fire leaves it. Every frame reads the arrival map: a cell burns from its arrival over
the time the front takes to cross it plus Anderson's residence time 384 / sigma, its fuel going with the burn
fraction, its flame the Byram length of the fireline intensity.

The model runs in its own units (ft, lb, min, Btu; midflame wind in ft/min) and the document in SI; this module
converts at the boundary. `python wildfire_reference.py` prints the numeric table of the draft's conformance
section.
"""
from __future__ import annotations

import hashlib
import heapq
import importlib.util
import json
import math
import os
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))

FT_PER_MIN_PER_M_S = 60.0 / 0.3048           # 196.85 ft/min per m/s
M_S_PER_FT_MIN = 0.3048 / 60.0
LB_PER_FT2_PER_KG_M2 = (0.3048 ** 2) / 0.45359237   # 0.20482 lb/ft^2 per kg/m^2 (1 lb/ft^2 = 4.882 kg/m^2)
TON_ACRE_LB_FT2 = 2000.0 / 43560.0           # lb/ft^2 per ton/acre
MPH_FT_MIN = 88.0                            # ft/min per mi/h
FT_PER_M = 1.0 / 0.3048
SAV_10H = 109.0                              # 1/ft, every standard model (Scott and Burgan 2005)
SAV_100H = 30.0
TOTAL_MINERAL = 0.0555
EFFECTIVE_MINERAL = 0.010
PARTICLE_DENSITY = 32.0                      # lb/ft^3
MAX_LENGTH_TO_BREADTH = 8.0
RESIDENCE_CONSTANT = 384.0                   # Anderson 1969: t_r = 384 / sigma minutes
SUBCLASS_BOUNDS = (1200.0, 192.0, 96.0, 48.0, 16.0)
DIGEST_DECIMALS = 3
D2L2 = (0.06, 0.07, 0.08, 0.60, 0.90)        # the fuel-model charts' moisture scenario
DEFAULTS = {
    "fuelModel": "GR2", "ignitionX": 0.0, "ignitionY": 0.0, "ignitionTime": 0.0, "wind": None,
    "windAdjustment": 0.4, "windLimit": False, "curing": None,
    "moisture1h": 0.06, "moisture10h": 0.07, "moisture100h": 0.08, "moistureHerb": 0.60, "moistureWoody": 0.90,
}

# Scott and Burgan 2005, table 7: loads (1-h, 10-h, 100-h, live herbaceous, live woody) in tons per acre, SAV of
# the 1-h, live herbaceous and live woody classes in 1/ft (9999 marks an empty class), depth ft, dead moisture of
# extinction percent, heat content Btu/lb, dynamic (herbaceous load cures into a dead class).
FUEL_MODELS = {
    "GR1": {"loads": (0.10, 0.00, 0.00, 0.30, 0.00), "sav": (2200, 2000, 9999), "depth": 0.4, "extinction": 15, "heat": 8000, "dynamic": True},
    "GR2": {"loads": (0.10, 0.00, 0.00, 1.00, 0.00), "sav": (2000, 1800, 9999), "depth": 1.0, "extinction": 15, "heat": 8000, "dynamic": True},
    "GR3": {"loads": (0.10, 0.40, 0.00, 1.50, 0.00), "sav": (1500, 1300, 9999), "depth": 2.0, "extinction": 30, "heat": 8000, "dynamic": True},
    "GR4": {"loads": (0.25, 0.00, 0.00, 1.90, 0.00), "sav": (2000, 1800, 9999), "depth": 2.0, "extinction": 15, "heat": 8000, "dynamic": True},
    "GR5": {"loads": (0.40, 0.00, 0.00, 2.50, 0.00), "sav": (1800, 1600, 9999), "depth": 1.5, "extinction": 40, "heat": 8000, "dynamic": True},
    "GR6": {"loads": (0.10, 0.00, 0.00, 3.40, 0.00), "sav": (2200, 2000, 9999), "depth": 1.5, "extinction": 40, "heat": 9000, "dynamic": True},
    "GR7": {"loads": (1.00, 0.00, 0.00, 5.40, 0.00), "sav": (2000, 1800, 9999), "depth": 3.0, "extinction": 15, "heat": 8000, "dynamic": True},
    "GR8": {"loads": (0.50, 1.00, 0.00, 7.30, 0.00), "sav": (1500, 1300, 9999), "depth": 4.0, "extinction": 30, "heat": 8000, "dynamic": True},
    "GR9": {"loads": (1.00, 1.00, 0.00, 9.00, 0.00), "sav": (1800, 1600, 9999), "depth": 5.0, "extinction": 40, "heat": 8000, "dynamic": True},
    "GS1": {"loads": (0.20, 0.00, 0.00, 0.50, 0.65), "sav": (2000, 1800, 1800), "depth": 0.9, "extinction": 15, "heat": 8000, "dynamic": True},
    "GS2": {"loads": (0.50, 0.50, 0.00, 0.60, 1.00), "sav": (2000, 1800, 1800), "depth": 1.5, "extinction": 15, "heat": 8000, "dynamic": True},
    "GS3": {"loads": (0.30, 0.25, 0.00, 1.45, 1.25), "sav": (1800, 1600, 1600), "depth": 1.8, "extinction": 40, "heat": 8000, "dynamic": True},
    "GS4": {"loads": (1.90, 0.30, 0.10, 3.40, 7.10), "sav": (1800, 1600, 1600), "depth": 2.1, "extinction": 40, "heat": 8000, "dynamic": True},
    "SH1": {"loads": (0.25, 0.25, 0.00, 0.15, 1.30), "sav": (2000, 1800, 1600), "depth": 1.0, "extinction": 15, "heat": 8000, "dynamic": True},
    "SH2": {"loads": (1.35, 2.40, 0.75, 0.00, 3.85), "sav": (2000, 9999, 1600), "depth": 1.0, "extinction": 15, "heat": 8000, "dynamic": False},
    "SH3": {"loads": (0.45, 3.00, 0.00, 0.00, 6.20), "sav": (1600, 9999, 1400), "depth": 2.4, "extinction": 40, "heat": 8000, "dynamic": False},
    "SH4": {"loads": (0.85, 1.15, 0.20, 0.00, 2.55), "sav": (2000, 1800, 1600), "depth": 3.0, "extinction": 30, "heat": 8000, "dynamic": False},
    "SH5": {"loads": (3.60, 2.10, 0.00, 0.00, 2.90), "sav": (750, 9999, 1600), "depth": 6.0, "extinction": 15, "heat": 8000, "dynamic": False},
    "SH6": {"loads": (2.90, 1.45, 0.00, 0.00, 1.40), "sav": (750, 9999, 1600), "depth": 2.0, "extinction": 30, "heat": 8000, "dynamic": False},
    "SH7": {"loads": (3.50, 5.30, 2.20, 0.00, 3.40), "sav": (750, 9999, 1600), "depth": 6.0, "extinction": 15, "heat": 8000, "dynamic": False},
    "SH8": {"loads": (2.05, 3.40, 0.85, 0.00, 4.35), "sav": (750, 9999, 1600), "depth": 3.0, "extinction": 40, "heat": 8000, "dynamic": False},
    "SH9": {"loads": (4.50, 2.45, 0.00, 1.55, 7.00), "sav": (750, 1800, 1500), "depth": 4.4, "extinction": 40, "heat": 8000, "dynamic": True},
    "TU1": {"loads": (0.20, 0.90, 1.50, 0.20, 0.90), "sav": (2000, 1800, 1600), "depth": 0.6, "extinction": 20, "heat": 8000, "dynamic": True},
    "TU2": {"loads": (0.95, 1.80, 1.25, 0.00, 0.20), "sav": (2000, 9999, 1600), "depth": 1.0, "extinction": 30, "heat": 8000, "dynamic": False},
    "TU3": {"loads": (1.10, 0.15, 0.25, 0.65, 1.10), "sav": (1800, 1600, 1400), "depth": 1.3, "extinction": 30, "heat": 8000, "dynamic": True},
    "TU4": {"loads": (4.50, 0.00, 0.00, 0.00, 2.00), "sav": (2300, 9999, 2000), "depth": 0.5, "extinction": 12, "heat": 8000, "dynamic": False},
    "TU5": {"loads": (4.00, 4.00, 3.00, 0.00, 3.00), "sav": (1500, 9999, 750), "depth": 1.0, "extinction": 25, "heat": 8000, "dynamic": False},
    "TL1": {"loads": (1.00, 2.20, 3.60, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 0.2, "extinction": 30, "heat": 8000, "dynamic": False},
    "TL2": {"loads": (1.40, 2.30, 2.20, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 0.2, "extinction": 25, "heat": 8000, "dynamic": False},
    "TL3": {"loads": (0.50, 2.20, 2.80, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 0.3, "extinction": 20, "heat": 8000, "dynamic": False},
    "TL4": {"loads": (0.50, 1.50, 4.20, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 0.4, "extinction": 25, "heat": 8000, "dynamic": False},
    "TL5": {"loads": (1.15, 2.50, 4.40, 0.00, 0.00), "sav": (2000, 9999, 1600), "depth": 0.6, "extinction": 25, "heat": 8000, "dynamic": False},
    "TL6": {"loads": (2.40, 1.20, 1.20, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 0.3, "extinction": 25, "heat": 8000, "dynamic": False},
    "TL7": {"loads": (0.30, 1.40, 8.10, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 0.4, "extinction": 25, "heat": 8000, "dynamic": False},
    "TL8": {"loads": (5.80, 1.40, 1.10, 0.00, 0.00), "sav": (1800, 9999, 9999), "depth": 0.3, "extinction": 35, "heat": 8000, "dynamic": False},
    "TL9": {"loads": (6.65, 3.30, 4.15, 0.00, 0.00), "sav": (1800, 9999, 1600), "depth": 0.6, "extinction": 35, "heat": 8000, "dynamic": False},
    "SB1": {"loads": (1.50, 3.00, 11.00, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 1.0, "extinction": 25, "heat": 8000, "dynamic": False},
    "SB2": {"loads": (4.50, 4.25, 4.00, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 1.0, "extinction": 25, "heat": 8000, "dynamic": False},
    "SB3": {"loads": (5.50, 2.75, 3.00, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 1.2, "extinction": 25, "heat": 8000, "dynamic": False},
    "SB4": {"loads": (5.25, 3.50, 5.25, 0.00, 0.00), "sav": (2000, 9999, 9999), "depth": 2.7, "extinction": 25, "heat": 8000, "dynamic": False},
}

FuelClass = namedtuple("FuelClass", "load sav live moisture")          # lb/ft^2, 1/ft, bool, fraction
FuelBed = namedtuple("FuelBed", "classes depth extinction heat")       # ft, fraction, Btu/lb


class WildfireError(ValueError):
    """A wildfire or input outside the draft's rules."""


# ------------------------------------------------------------------------------------------------- the references

_modules = {}


def _load(name):
    if name not in _modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _modules[name] = mod
    return _modules[name]


def terrain():
    """The terrain-grid reference (grid, build, D8, flat)."""
    return _load("terrain_grid_reference")


def wind():
    """The wind reference (wind_at)."""
    return _load("wind_reference")


def _get(spec, key):
    return spec[key] if key in spec and spec[key] is not None else DEFAULTS[key]


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ------------------------------------------------------------------------------------------------- fuel models


def moistures(m1, m10, m100, herb, woody):
    """A moisture tuple (1-h, 10-h, 100-h, live herbaceous, live woody), fractions."""
    return (m1, m10, m100, herb, woody)


def curing(herb_moisture):
    """The cured fraction of the herbaceous load from its moisture (Scott and Burgan 2005, after Burgan 1979):
    1 at or under 30 %, 0 at or over 120 %, linear between."""
    return min(1.0, max(0.0, (120.0 - 100.0 * herb_moisture) / 90.0))


_cured = curing


def standard_bed(code, moist, curing=None, scale=1.0):
    """The fuel bed of a standard model at the moistures (1-h, 10-h, 100-h, herb, woody), its loads times
    `scale`; a dynamic model moves the cured share of its herbaceous load (from `curing` or the herbaceous
    moisture) into a dead class with the herbaceous SAV at the 1-h moisture."""
    if code not in FUEL_MODELS:
        raise WildfireError(f"WF2: unknown fuel model {code!r}")
    fm = FUEL_MODELS[code]
    l1, l10, l100, lh, lw = (v * TON_ACRE_LB_FT2 * scale for v in fm["loads"])
    s1, sh, sw = fm["sav"]
    m1, m10, m100, mh, mw = moist
    classes = [FuelClass(l1, float(s1), False, m1), FuelClass(l10, SAV_10H, False, m10),
               FuelClass(l100, SAV_100H, False, m100)]
    if lh > 0.0:
        cured = (curing if curing is not None else _cured(mh)) if fm["dynamic"] else 0.0
        classes.append(FuelClass(lh * cured, float(sh), False, m1))
        classes.append(FuelClass(lh * (1.0 - cured), float(sh), True, mh))
    if lw > 0.0:
        classes.append(FuelClass(lw, float(sw), True, mw))
    return FuelBed(tuple(c for c in classes if c.load > 0.0), float(fm["depth"]), fm["extinction"] / 100.0,
                   float(fm["heat"]))


def standard_load(code):
    """The model's total oven-dry load in kg/m^2 (what a `fuel` layer equal to it reproduces)."""
    if code not in FUEL_MODELS:
        raise WildfireError(f"WF2: unknown fuel model {code!r}")
    return sum(FUEL_MODELS[code]["loads"]) * TON_ACRE_LB_FT2 / LB_PER_FT2_PER_KG_M2


# ------------------------------------------------------------------------------------------ the Rothermel model


def moisture_damping(r):
    """1 - 2.59 r + 5.11 r^2 - 3.52 r^3, r the moisture over the extinction moisture, at most 1."""
    if r >= 1.0:
        return 0.0
    r = max(0.0, r)
    return max(0.0, 1.0 - 2.59 * r + 5.11 * r * r - 3.52 * r ** 3)


def mineral_damping(se):
    """0.174 Se^-0.19, at most 1."""
    return min(1.0, 0.174 * se ** -0.19)


def _subclass(sav):
    for k, bound in enumerate(SUBCLASS_BOUNDS):
        if sav >= bound:
            return k
    return len(SUBCLASS_BOUNDS)


def characteristics(bed):
    """The weighted fuel-bed values of Rothermel 1972 and Albini 1976 (Andrews 2018, sections 3.2.2 to 3.2.5)."""
    classes = [c for c in bed.classes if c.load > 0.0]
    out = {"load": sum(c.load for c in classes)}
    if not classes:
        return None
    area = [c.sav * c.load / PARTICLE_DENSITY for c in classes]
    cat = [1 if c.live else 0 for c in classes]
    a_i = [sum(a for a, k in zip(area, cat) if k == i) for i in (0, 1)]
    a_t = a_i[0] + a_i[1]
    f_ij = [a / a_i[k] if a_i[k] > 0.0 else 0.0 for a, k in zip(area, cat)]
    f_i = [a_i[0] / a_t, a_i[1] / a_t]
    g_ij = []
    for c, k in zip(classes, cat):
        if c.sav < SUBCLASS_BOUNDS[-1]:
            g_ij.append(0.0)
        else:
            sub = _subclass(c.sav)
            g_ij.append(sum(f for f, d, kk in zip(f_ij, classes, cat) if kk == k and _subclass(d.sav) == sub))
    dead = [(c, f) for c, f, k in zip(classes, f_ij, cat) if k == 0]
    live = [(c, f) for c, f, k in zip(classes, f_ij, cat) if k == 1]
    mx = [bed.extinction, bed.extinction]
    if live:
        dead_fine = sum(c.load * math.exp(-138.0 / c.sav) for c, _ in dead)
        live_fine = sum(c.load * math.exp(-500.0 / c.sav) for c, _ in live)
        if dead_fine > 0.0 and live_fine > 0.0:
            w = dead_fine / live_fine
            m_dead = sum(c.moisture * c.load * math.exp(-138.0 / c.sav) for c, _ in dead) / dead_fine
            mx[1] = max(bed.extinction, 2.9 * w * (1.0 - m_dead / bed.extinction) - 0.226)
    terms = []
    sigma_i = []
    for i, group in enumerate((dead, live)):
        if not group:
            sigma_i.append(0.0)
            terms.append(0.0)
            continue
        wn = sum(g * c.load * (1.0 - TOTAL_MINERAL) for c, g in
                 [(c, g_ij[classes.index(c)]) for c, _ in group])
        mf = sum(f * c.moisture for c, f in group)
        eta_m = moisture_damping(mf / mx[i] if mx[i] > 0.0 else 1.0)
        eta_s = mineral_damping(EFFECTIVE_MINERAL)
        sigma_i.append(sum(f * c.sav for c, f in group))
        terms.append(wn * bed.heat * eta_m * eta_s)
    sigma = f_i[0] * sigma_i[0] + f_i[1] * sigma_i[1]
    rho_b = out["load"] / bed.depth
    beta = rho_b / PARTICLE_DENSITY
    beta_op = 3.348 * sigma ** -0.8189
    out.update(sav=sigma, bulk_density=rho_b, packing_ratio=beta, optimum_packing=beta_op,
               relative_packing=beta / beta_op, heat_source_terms=terms, extinction=tuple(mx))
    gamma_max = sigma ** 1.5 / (495.0 + 0.0594 * sigma ** 1.5)
    a = 133.0 * sigma ** -0.7913
    rel = beta / beta_op
    out["reaction_velocity"] = gamma_max * rel ** a * math.exp(a * (1.0 - rel))
    out["reaction_intensity"] = out["reaction_velocity"] * sum(terms)
    out["propagating_flux"] = math.exp((0.792 + 0.681 * math.sqrt(sigma)) * (beta + 0.1)) / (192.0 + 0.2595 * sigma)
    sink = 0.0
    for c, f, k in zip(classes, f_ij, cat):
        sink += f_i[k] * f * math.exp(-138.0 / c.sav) * (250.0 + 1116.0 * c.moisture)
    out["heat_sink"] = rho_b * sink
    out["wind_c"] = 7.47 * math.exp(-0.133 * sigma ** 0.55)
    out["wind_b"] = 0.02526 * sigma ** 0.54
    out["wind_e"] = 0.715 * math.exp(-3.59e-4 * sigma)
    return out


def wind_factor(bed, midflame):
    """C U^B (beta / beta_op)^-E, U the midflame wind in ft/min."""
    ch = characteristics(bed)
    if ch is None or midflame <= 0.0:
        return 0.0
    return ch["wind_c"] * midflame ** ch["wind_b"] * ch["relative_packing"] ** -ch["wind_e"]


def slope_factor(bed, tan_slope):
    """5.275 beta^-0.3 tan^2 phi for an upslope, 0 downslope."""
    ch = characteristics(bed)
    if ch is None or tan_slope <= 0.0:
        return 0.0
    return 5.275 * ch["packing_ratio"] ** -0.3 * tan_slope ** 2


def fire(bed, midflame, tan_slope, wind_limit=False):
    """Rothermel's spread: rate of spread R = I_R xi (1 + phi_w + phi_s) / (rho_b eps Q_ig) in ft/min with the
    midflame wind in ft/min and the slope as tan phi, and with it the reaction intensity (Btu/ft^2/min), the
    residence time (min), Byram's fireline intensity (Btu/ft/s) and flame length (ft). The wind limit
    U <= 0.9 I_R (Rothermel 1972) applies only when asked; Andrews et al. 2013 recommend against it."""
    ch = characteristics(bed)
    if ch is None:
        return {"ros": 0.0, "reaction_intensity": 0.0, "wind_factor": 0.0, "slope_factor": 0.0, "flame_length": 0.0,
                "fireline_intensity": 0.0, "residence_time": 0.0, "sav": 0.0, "bulk_density": 0.0,
                "packing_ratio": 0.0, "optimum_packing": 0.0, "relative_packing": 0.0, "heat_sink": 0.0,
                "propagating_flux": 0.0, "no_wind_ros": 0.0}
    u = midflame
    if wind_limit and u > 0.9 * ch["reaction_intensity"]:
        u = 0.9 * ch["reaction_intensity"]
    phi_w = ch["wind_c"] * u ** ch["wind_b"] * ch["relative_packing"] ** -ch["wind_e"] if u > 0.0 else 0.0
    phi_s = 5.275 * ch["packing_ratio"] ** -0.3 * tan_slope ** 2 if tan_slope > 0.0 else 0.0
    r0 = ch["reaction_intensity"] * ch["propagating_flux"] / ch["heat_sink"] if ch["heat_sink"] > 0.0 else 0.0
    ros = r0 * (1.0 + phi_w + phi_s)
    t_r = RESIDENCE_CONSTANT / ch["sav"]
    i_b = ch["reaction_intensity"] * t_r * ros / 60.0
    return {"ros": ros, "no_wind_ros": r0, "reaction_intensity": ch["reaction_intensity"], "wind_factor": phi_w,
            "slope_factor": phi_s, "residence_time": t_r, "fireline_intensity": i_b,
            "flame_length": 0.45 * i_b ** 0.46 if i_b > 0.0 else 0.0, "sav": ch["sav"],
            "bulk_density": ch["bulk_density"], "packing_ratio": ch["packing_ratio"],
            "optimum_packing": ch["optimum_packing"], "relative_packing": ch["relative_packing"],
            "heat_sink": ch["heat_sink"], "propagating_flux": ch["propagating_flux"]}


# ------------------------------------------------------------------------------------- direction and the ellipse


def effective_wind(bed, wind_vector, slope_vector):
    """Wind and slope as vectors (Andrews 2018, section 4.1): the slope factor's equivalent wind
    U_s = (phi_s / (C (beta / beta_op)^-E))^(1 / B) points up the slope; its vector sum with the midflame wind
    (ft/min) is the effective wind, whose direction is the head's. Returns speed (ft/min), unit direction and the
    effective wind factor; the direction is (1, 0) when both vanish."""
    ch = characteristics(bed)
    tan_slope = math.hypot(*slope_vector)
    ux, uy = float(wind_vector[0]), float(wind_vector[1])
    if ch is not None and tan_slope > 0.0:
        phi_s = 5.275 * ch["packing_ratio"] ** -0.3 * tan_slope ** 2
        u_s = (phi_s / (ch["wind_c"] * ch["relative_packing"] ** -ch["wind_e"])) ** (1.0 / ch["wind_b"])
        ux += u_s * slope_vector[0] / tan_slope
        uy += u_s * slope_vector[1] / tan_slope
    speed = math.hypot(ux, uy)
    direction = (ux / speed, uy / speed) if speed > 0.0 else (1.0, 0.0)
    return {"speed": speed, "direction": direction, "factor": wind_factor(bed, speed)}


def length_to_breadth(effective):
    """Anderson 1983 for the effective wind in ft/min: 0.936 e^(0.2566 U) + 0.461 e^(-0.1548 U) - 0.397, U in
    mi/h, at most 8."""
    u = effective / MPH_FT_MIN
    return min(MAX_LENGTH_TO_BREADTH, 0.936 * math.exp(0.2566 * u) + 0.461 * math.exp(-0.1548 * u) - 0.397)


def spread_toward(head, lb, theta):
    """The ellipse's rate at the angle theta from the head: head (1 - e) / (1 - e cos theta),
    e = sqrt(LB^2 - 1) / LB (Finney 1998)."""
    if lb <= 1.0:
        return head
    e = math.sqrt(lb * lb - 1.0) / lb
    return head * (1.0 - e) / (1.0 - e * math.cos(theta))


# ----------------------------------------------------------------------------------------- the grid and arrival


def _project_seed(doc):
    project = doc.get("project", 0)
    if isinstance(project, dict):
        return project.get("seed", 0)
    return project


def wind_at_cell(doc, wind_id, t, i, j, dx):
    """The grid-space wind (w_x, -w_y) in m/s at the centre of cell (i, j): the planar wind of the wind draft at
    the physics point ((i + 1/2) dx, -(j + 1/2) dx)."""
    shim = {"project": {"seed": _project_seed(doc)}, "physics": doc.get("physics", {})}
    wx, wy = wind().wind_at(shim, wind_id, ((i + 0.5) * dx, -(j + 0.5) * dx), t)
    return (wx, -wy)


def _gradient(h, dx, i, j):
    ny, nx = len(h), len(h[0])
    i0, i1 = max(i - 1, 0), min(i + 1, nx - 1)
    j0, j1 = max(j - 1, 0), min(j + 1, ny - 1)
    gx = (h[j][i1] - h[j][i0]) / ((i1 - i0) * dx) if i1 > i0 else 0.0
    gy = (h[j1][i] - h[j0][i]) / ((j1 - j0) * dx) if j1 > j0 else 0.0
    return gx, gy


def ignition_cell(spec, dx, nx, ny):
    """The cell holding the ignition point, or None outside the grid."""
    i = math.floor(_get(spec, "ignitionX") / dx)
    j = math.floor(_get(spec, "ignitionY") / dx)
    if 0 <= i < nx and 0 <= j < ny:
        return i, j
    return None


def cell_bed(spec, layers, i, j):
    """The fuel bed of a cell: the model at the attributes' moistures and curing, its loads scaled by the `fuel`
    layer over the model's load where the terrain has one; None where there is no fuel."""
    scale = 1.0
    if "fuel" in layers:
        load = standard_load(_get(spec, "fuelModel"))
        scale = layers["fuel"][j][i] / load if load > 0.0 else 0.0
    if scale <= 0.0:
        return None
    m = moistures(_get(spec, "moisture1h"), _get(spec, "moisture10h"), _get(spec, "moisture100h"),
                  _get(spec, "moistureHerb"), _get(spec, "moistureWoody"))
    return standard_bed(_get(spec, "fuelModel"), m, _get(spec, "curing"), scale)


def local_fire(doc, spec, layers, h, i, j, dx, t):
    """The head's rate (m/s), direction (unit, grid space), length-to-breadth ratio and the fire's values at
    cell (i, j) with the wind read at time t."""
    bed = cell_bed(spec, layers, i, j)
    if bed is None:
        return None
    wind_id = _get(spec, "wind")
    w = wind_at_cell(doc, wind_id, t, i, j, dx) if wind_id is not None else (0.0, 0.0)
    adj = _get(spec, "windAdjustment")
    midflame = (w[0] * adj * FT_PER_MIN_PER_M_S, w[1] * adj * FT_PER_MIN_PER_M_S)
    eff = effective_wind(bed, midflame, _gradient(h, dx, i, j))
    base = fire(bed, 0.0, 0.0)
    speed = eff["speed"]
    if _get(spec, "windLimit") and speed > 0.9 * base["reaction_intensity"]:
        speed = 0.9 * base["reaction_intensity"]
    head = base["no_wind_ros"] * (1.0 + wind_factor(bed, speed))
    t_r = base["residence_time"] * 60.0
    i_b = base["reaction_intensity"] * base["residence_time"] * head / 60.0
    return {"head": head * M_S_PER_FT_MIN, "direction": eff["direction"], "lb": length_to_breadth(speed),
            "residence": t_r, "flame": 0.45 * i_b ** 0.46 / FT_PER_M if i_b > 0.0 else 0.0,
            "effective_wind": speed}


def arrival_from_layers(doc, layers):
    """The minimum travel time (Finney 2002) from the ignition cell over the eight-neighbour graph: a cell
    settled at time T sends each neighbour T + distance / R(theta), R(theta) the ellipse rate toward the
    neighbour from the cell's head rate and direction with the wind read at T. Returns the arrival times
    (seconds, inf where the fire never arrives), the head rates (m/s), the burn durations (crossing plus
    residence) and the flame lengths (m) per cell."""
    tg = terrain()
    spec = doc["wildfire"]
    dx = float(doc.get("metersPerCell", 1.0))
    h = tg.surface(layers)
    ny, nx = len(h), len(h[0])
    start = ignition_cell(spec, dx, nx, ny)
    if start is None:
        raise WildfireError("WF4: the ignition point is off the grid")
    inf = math.inf
    arrival = [[inf] * nx for _ in range(ny)]
    head = [[0.0] * nx for _ in range(ny)]
    duration = [[inf] * nx for _ in range(ny)]
    flame = [[0.0] * nx for _ in range(ny)]
    si, sj = start
    t0 = float(_get(spec, "ignitionTime"))
    heap = [(t0, si, sj)]
    arrival[sj][si] = t0
    settled = [[False] * nx for _ in range(ny)]
    while heap:
        t, i, j = heapq.heappop(heap)
        if settled[j][i] or t > arrival[j][i]:
            continue
        settled[j][i] = True
        local = local_fire(doc, spec, layers, h, i, j, dx, t)
        if local is None or local["head"] <= 0.0:
            continue
        head[j][i] = local["head"]
        duration[j][i] = dx / local["head"] + local["residence"]
        flame[j][i] = local["flame"]
        d = local["direction"]
        for di, dj, dist in tg.D8:
            a, b = i + di, j + dj
            if not (0 <= a < nx and 0 <= b < ny) or settled[b][a]:
                continue
            if cell_bed(spec, layers, a, b) is None:
                continue
            cos_t = (di * d[0] + dj * d[1]) / dist
            rate = spread_toward(local["head"], local["lb"], math.acos(max(-1.0, min(1.0, cos_t))))
            if rate <= 0.0:
                continue
            candidate = t + dist * dx / rate
            if candidate < arrival[b][a]:
                arrival[b][a] = candidate
                heapq.heappush(heap, (candidate, a, b))
    return {"arrival": arrival, "head": head, "duration": duration, "flame": flame, "shape": (nx, ny)}


def arrival(doc):
    """The arrival map of a document (validated and built)."""
    codes = validate_document(doc)
    if codes:
        raise WildfireError("invalid document: " + ", ".join(codes))
    built = terrain().build(doc)
    return arrival_from_layers(doc, built["layers"])


def burn_fraction(t, arrival_time, duration):
    """clamp((t - arrival) / duration, 0, 1); 0 where the fire never arrives."""
    if not math.isfinite(arrival_time) or duration <= 0.0 or t <= arrival_time:
        return 0.0
    return min(1.0, (t - arrival_time) / duration)


def digest(layers):
    """sha256 of the layers as JSON with sorted keys and values rounded to three decimals."""
    rounded = {k: [[round(v, DIGEST_DECIMALS) for v in row] for row in rows] for k, rows in layers.items()}
    text = json.dumps(rounded, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(doc, t):
    """The terrain's layers at time t: `burn` the burn fraction of every cell, `fuel` (where the terrain has it)
    reduced by the burnt share; the flame lengths (m) of the burning cells, the counts of burning and burnt
    cells, and the digest."""
    codes = validate_document(doc)
    if codes:
        raise WildfireError("invalid document: " + ", ".join(codes))
    built = terrain().build(doc)
    layers = dict(built["layers"])
    amap = arrival_from_layers(doc, layers)
    nx, ny = amap["shape"]
    burn = [[burn_fraction(t, amap["arrival"][j][i], amap["duration"][j][i]) for i in range(nx)] for j in range(ny)]
    layers["burn"] = burn
    if "fuel" in layers:
        layers["fuel"] = [[layers["fuel"][j][i] * (1.0 - burn[j][i]) for i in range(nx)] for j in range(ny)]
    flame = [[amap["flame"][j][i] if 0.0 < burn[j][i] < 1.0 else 0.0 for i in range(nx)] for j in range(ny)]
    burning = sum(1 for row in burn for v in row if 0.0 < v < 1.0)
    burnt = sum(1 for row in burn for v in row if v >= 1.0)
    return {"shape": built["shape"], "layers": layers, "flame": flame, "burning": burning, "burnt": burnt,
            "arrival": amap["arrival"], "digest": digest(dict(layers, flame=flame))}


# ----------------------------------------------------------------------------------------------------- documents


def example_document():
    """The terrain draft's example with fuel and burn layers (GR2 at its standard load), a 5 m/s wind and a
    wildfire lit at (375, 275) m at t = 0."""
    doc = terrain().example_document()
    doc["layers"] += [{"kind": "fuel", "value": standard_load("GR2")}, {"kind": "burn", "value": 0.0}]
    doc["physics"] = {"winds": [{"id": "w1", "speed": 5.0, "direction": 30.0, "seed": 3}]}
    doc["wildfire"] = {
        "fuelModel": "GR2", "ignitionX": 375.0, "ignitionY": 275.0, "ignitionTime": 0.0, "wind": "w1",
        "windAdjustment": 0.4, "windLimit": False, "curing": None,
        "moisture1h": 0.06, "moisture10h": 0.07, "moisture100h": 0.08, "moistureHerb": 0.60, "moistureWoody": 0.90,
    }
    return doc


def bad_document():
    doc = example_document()
    doc["wildfire"].update(moisture1h=-1.0, fuelModel="XX9", ignitionX=-5.0, wind="w9")
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "burn"]
    return doc


def _unit(v):
    return _number(v) and 0.0 <= v <= 1.0


def _shape(doc):
    tg = terrain()
    try:
        return tg.grid(doc)
    except tg.TerrainError:
        return 0, 0


def validate_document(doc):
    """The draft's rules WF1 to WF5 and V17 over a terrain document, as sorted codes."""
    if "wildfire" not in doc:
        return []
    major, minor = (int(x) for x in str(doc.get("version", "1.8")).split(".")[:2])
    if (major, minor) < (1, 8):
        return ["V17"]
    codes = set()
    spec = doc["wildfire"]
    g = lambda key: _get(spec, key)      # noqa: E731
    moist = [g(k) for k in ("moisture1h", "moisture10h", "moisture100h", "moistureHerb", "moistureWoody")]
    adj = g("windAdjustment")
    cur = spec.get("curing")
    if not (all(_number(m) and 0.0 <= m <= 2.0 for m in moist) and _number(adj) and 0.0 < adj <= 1.0
            and (cur is None or _unit(cur)) and _number(g("ignitionTime")) and g("ignitionTime") >= 0.0
            and isinstance(g("windLimit"), bool)):
        codes.add("WF1")
    if g("fuelModel") not in FUEL_MODELS:
        codes.add("WF2")
    kinds = {terrain()._layer_key(layer) for layer in doc.get("layers", ())}
    if "burn" not in kinds:
        codes.add("WF3")
    nx, ny = _shape(doc)
    if not (_number(g("ignitionX")) and _number(g("ignitionY"))) or (
            nx > 0 and ignition_cell(spec, float(doc.get("metersPerCell", 1.0)), nx, ny) is None):
        codes.add("WF4")
    wind_id = g("wind")
    if wind_id is not None and not any(w.get("id") == wind_id for w in doc.get("physics", {}).get("winds", ())):
        codes.add("WF5")
    return sorted(codes)


# ------------------------------------------------------------------------------------------------- numeric table

TABLE = (
    ("ft/min per m/s", "FT_PER_MIN_PER_M_S", "196.85039370078738"),
    ("lb/ft² per kg/m²", "LB_PER_FT2_PER_KG_M2", "0.2048161436225217"),
    ("GR2 load, kg/m²", "standard_load('GR2')", "0.2465872543627803"),
    ("curing at 75 %", "curing(0.75)", "0.5"),
    ("table 17, 2 t/ac of 1-h: SAV", "T17[0]['sav']", "2500.0"),
    ("table 17, 2 t/ac of 1-h: relative packing ratio", "T17[0]['relative_packing']", "0.5195289651981287"),
    ("table 17, 2 t/ac of 1-h: wind factor", "T17[0]['wind_factor']", "17.823964264090975"),
    ("table 17, 2 t/ac of 1-h: rate of spread, ft/min", "T17[0]['ros']", "81.6156403505707"),
    ("table 17, 1 + 1 t/ac: rate of spread", "T17[1]['ros']", "40.247534454288235"),
    ("table 17, 0.1 + 1.9 t/ac: rate of spread", "T17[2]['ros']", "32.00021358354343"),
    ("table 17, 2 t/ac of 10-h: wind factor", "T17[3]['wind_factor']", "81.93262236589915"),
    ("table 17, 2 t/ac of 10-h: rate of spread", "T17[3]['ros']", "0.025110815062246633"),
    ("SB4 packing ratio", "fire(standard_bed('SB4', D2L2), 0.0, 0.0)['packing_ratio']", "0.007439717035676631"),
    ("SB4 optimum packing ratio", "fire(standard_bed('SB4', D2L2), 0.0, 0.0)['optimum_packing']", "0.006895914007804161"),
    ("TL1 bulk density, lb/ft³", "fire(standard_bed('TL1', D2L2), 0.0, 0.0)['bulk_density']", "1.5610651974288337"),
    ("GR2, live herb 90 %: rate of spread", "fire(standard_bed('GR2', moistures(0.05, 0.05, 0.05, 0.9, 0.9)), 528.0, 0.0)['ros']", "24.033292726757693"),
    ("GR2, live herb 100 %: rate of spread", "fire(standard_bed('GR2', moistures(0.05, 0.05, 0.05, 1.0, 0.9)), 528.0, 0.0)['ros']", "6.43557792508896"),
    ("GR2, curing 50 %, live herb 90 %", "fire(standard_bed('GR2', moistures(0.05, 0.05, 0.05, 0.9, 0.9), 0.5), 528.0, 0.0)['ros']", "31.328136175744355"),
    ("GR2, curing 50 %, live herb 100 %", "fire(standard_bed('GR2', moistures(0.05, 0.05, 0.05, 1.0, 0.9), 0.5), 528.0, 0.0)['ros']", "29.076929243197046"),
    ("SH8, dead 28 %, live 50 %", "fire(standard_bed('SH8', moistures(0.28, 0.28, 0.28, 0.5, 0.5)), 528.0, 0.0)['ros']", "13.552501680402624"),
    ("SH8, dead 27 %, live 50 %", "fire(standard_bed('SH8', moistures(0.27, 0.27, 0.27, 0.5, 0.5)), 528.0, 0.0)['ros']", "25.80094662971084"),
    ("GR2 at D2L2, 5 mi/h: flame length, ft", "fire(standard_bed('GR2', D2L2), 440.0, 0.0)['flame_length']", "4.572585376143725"),
    ("GR2 at D2L2: residence time, min", "fire(standard_bed('GR2', D2L2), 440.0, 0.0)['residence_time']", "0.21098901098901102"),
    ("slope factor at 30°", "fire(standard_bed('GR2', D2L2), 0.0, 0.5773502691896257)['slope_factor']", "12.179957133324665"),
    ("effective wind of a 30° slope, ft/min", "effective_wind(standard_bed('GR2', D2L2), (0.0, 0.0), (0.0, 0.5773502691896257))['speed']", "277.263585057121"),
    ("length-to-breadth at 5 mi/h", "length_to_breadth(440.0)", "3.1921662454003767"),
    ("back rate at 5 mi/h over the head", "spread_toward(1.0, length_to_breadth(440.0), math.pi)", "0.025817188788970987"),
    ("flank rate at 5 mi/h over the head", "spread_toward(1.0, length_to_breadth(440.0), math.pi / 2.0)", "0.05033487266761339"),
    ("flat calm GR2: arrival of the next cell, s", "FLAT['arrival'][4][5]", "1278.945178483041"),
    ("flat calm GR2: head rate, m/s", "FLAT['head'][4][4]", "0.00781894342950729"),
    ("flat, 5 m/s wind: arrival downwind", "WINDY['arrival'][4][5]", "60.082317305629786"),
    ("flat, 5 m/s wind: arrival upwind", "WINDY['arrival'][4][3]", "1740.184200444006"),
    ("flat, 5 m/s wind: arrival across", "WINDY['arrival'][5][4]", "900.1332588748177"),
    ("burn fraction", "burn_fraction(25.0, 10.0, 30.0)", "0.5"),
    ("run, burnt cells", "RUN['burnt']", "4"),
    ("run, burning cells", "RUN['burning']", "1"),
    ("run, fuel left, kg/m²", "sum(v for row in RUN['layers']['fuel'] for v in row)", "46.13105208388337"),
    ("run, tallest flame, m", "max(v for row in RUN['flame'] for v in row)", "1.6859440305774318"),
    ("run, digest", "RUN['digest']", "'9adaf355cd17fbe0979d34a44d4909ec7332c52ca7f296489c804ef6d4580b41'"),
    ("bad document", "validate_document(bad_document())", "['WF1', 'WF2', 'WF3', 'WF4', 'WF5']"),
)

_SCOPE = None


def _flat_document(wind_speed):
    n, dx = 9, 10.0
    doc = {"version": "1.8", "project": 7, "id": "range", "x": 0.0, "y": 0.0, "width": n * dx, "height": n * dx,
           "cells": n, "metersPerCell": dx, "seed": 11, "display": "none",
           "layers": [{"kind": "bedrock", "value": 0.0}, {"kind": "burn", "value": 0.0}],
           "masks": [], "materials": [], "assets": {},
           "physics": {"winds": [{"id": "w1", "speed": wind_speed, "direction": 0.0, "seed": 3}]},
           "wildfire": {"fuelModel": "GR2", "ignitionX": 45.0, "ignitionY": 45.0,
                        "wind": "w1" if wind_speed else None}}
    return doc


def scope():
    """The names the table's expressions use (computed once)."""
    global _SCOPE
    if _SCOPE is not None:
        return _SCOPE
    s = dict(globals())
    s["math"] = math
    beds = []
    for one_h, ten_h in ((2.0, 0.0), (1.0, 1.0), (0.1, 1.9), (0.0, 2.0)):
        beds.append(FuelBed((FuelClass(one_h * TON_ACRE_LB_FT2, 2500.0, False, 0.05),
                             FuelClass(ten_h * TON_ACRE_LB_FT2, 109.0, False, 0.05)), 1.0, 0.20, 8000.0))
    s["T17"] = [fire(b, 440.0, 0.0) for b in beds]
    s["FLAT"] = arrival(_flat_document(0.0))
    s["WINDY"] = arrival(_flat_document(5.0))
    s["RUN"] = run(example_document(), 600.0)
    _SCOPE = s
    return s


def _same(a, b, rel=5e-4, abs_tol=1e-9):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k!r}: {_fmt(x)}" for k, x in v.items()) + "}"
    return repr(v)


def main():
    s = scope()
    print("| Test | Expression | Value |")
    print("|---|---|---|")
    for name, expr, _ in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
