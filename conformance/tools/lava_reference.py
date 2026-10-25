"""Reference for the draft SREP "Add lava to the terrain grid" (T4 of SREP 12).

One `lavaFlow` child of a `terrain` (the F2 terrain-grid draft) erupts lava from a vent into the terrain's `lava`
layer and moves it over the terrain's surface as a Bingham fluid in a cellular automaton after MAGFLOW (Vicari et
al. 2007; Del Negro et al. 2008): each step, in this order, the vent adds `effusion` cubic metres per second
(varied through the random streams), every cell sends its lower neighbours the steady Bingham flux of Dragoni,
Bonafede and Boschi (1986) between the two surfaces, which is zero under the critical thickness
h_cr = tau_y / (rho g sin theta), inflow mixes the temperatures by volume, every warm cell radiates to the sky
(Stefan-Boltzmann) through the thermal mass of its lava or of its crust, and lava colder than the solidus becomes
bedrock. The viscosity and the yield strength are log-linear in the temperature (Ishihara et al. 1990, as MAGFLOW
uses them) from their values at the eruption temperature.

Lengths are metres on the terrain's grid (i right, j down, `metersPerCell` apart), temperatures kelvin (the
terrain's `temperature` layer is the temperature of the surface: of the lava where lava lies, of the cooling
crust where it solidified, `ambient` elsewhere), time seconds on the terrain's clock. `python lava_reference.py`
prints the numeric table of the draft's conformance section.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PURPOSE = 2 ** 31 + 2 ** 17     # the effusion draws: S(e, PURPOSE, step, 0), clear of the erode and snowpack purposes
GRAVITY = 9.81
STEFAN_BOLTZMANN = 5.670374419e-8
REST = 1e-3                     # a sheet within this fraction of its critical thickness is at rest
DIGEST_DECIMALS = 3
DEFAULTS = {
    "layer": "lava", "ventX": 0.0, "ventY": 0.0, "effusion": 0.0, "effusionVariation": 0.0,
    "eruptionTemperature": 1360.0, "ambient": 293.15, "density": 2600.0, "heatCapacity": 1150.0, "emissivity": 0.9,
    "crust": 0.5, "solidus": 1173.15, "viscosity": 1000.0, "viscosityRate": 0.02, "yieldStrength": 2000.0,
    "yieldRate": 0.01, "step": 1.0, "maxSteps": 100000,
}


class LavaError(ValueError):
    """A lava flow or input outside the draft's rules."""


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
    """The terrain-grid reference (grid, surface, D8, build, element seed)."""
    return _load("terrain_grid_reference")


def erosion():
    """The erosion reference (its purpose base, which this draft keeps clear of)."""
    return _load("erosion_reference")


def streams():
    """The random-streams reference (E, S) through the terrain reference."""
    return terrain().streams()


def _get(spec, key):
    return spec[key] if key in spec and spec[key] is not None else DEFAULTS[key]


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _copy(rows):
    return [list(row) for row in rows]


# ------------------------------------------------------------------------------------------------------ rheology


def viscosity(spec, temperature):
    """viscosity * 10^(viscosityRate * (eruptionTemperature - T)) pascal seconds (log-linear, Ishihara et al.
    1990)."""
    return _get(spec, "viscosity") * 10.0 ** (_get(spec, "viscosityRate") * (_get(spec, "eruptionTemperature")
                                                                             - temperature))


def yield_strength(spec, temperature):
    """yieldStrength * 10^(yieldRate * (eruptionTemperature - T)) pascals."""
    return _get(spec, "yieldStrength") * 10.0 ** (_get(spec, "yieldRate") * (_get(spec, "eruptionTemperature")
                                                                             - temperature))


def critical_thickness(tau, rho, sin_theta):
    """tau_y / (rho g sin theta): the thickness under which a Bingham sheet on the slope does not move; infinite
    on the flat."""
    if sin_theta <= 0.0:
        return math.inf
    return tau / (rho * GRAVITY * sin_theta)


def slope_sine(drop, distance):
    """sin theta of a surface dropping `drop` over the horizontal `distance`; zero when the drop is not positive."""
    if drop <= 0.0:
        return 0.0
    return drop / math.hypot(drop, distance)


def bingham_flux(h, h_cr, sin_theta, rho, eta):
    """Dragoni's steady flux per unit width of a Bingham sheet of thickness h on a slope, square metres per second:
    rho g sin theta h_cr^3 / (3 eta) (a^3 - 3 a^2 / 2 + 1 / 2), a = h / h_cr, zero for a <= 1 + REST (the flux
    vanishes as (a - 1)^2, so a sheet within REST of its critical thickness is at rest); the Nusselt film
    rho g sin theta h^3 / (3 eta) when the yield strength is zero."""
    if h <= h_cr * (1.0 + REST) or sin_theta <= 0.0:
        return 0.0
    g = rho * GRAVITY * sin_theta / (3.0 * eta)
    if h_cr == 0.0:
        return g * h ** 3
    a = h / h_cr
    return g * h_cr ** 3 * (a ** 3 - 1.5 * a ** 2 + 0.5)


# ---------------------------------------------------------------------------------------------------------- flow


def flow_step(layers, spec, dx, dt):
    """One cellular step: every cell with lava sends each lower eight-neighbour the Bingham flux across their
    shared edge (width dx) for dt, by the slope of the surface between them and the sender's thickness, rheology
    at the sender's temperature; a transfer never exceeds half the surface drop, and the cell's transfers together
    never take it under the smallest critical thickness of its receivers (the plug under h_cr does not move);
    inflow mixes the temperatures by volume. Returns the same layers when nothing moves."""
    tg = terrain()
    name = _get(spec, "layer")
    if name not in layers:
        raise LavaError(f"LV2: the terrain has no {name!r} layer")
    lava = layers[name]
    temps = layers["temperature"]
    h = tg.surface(layers)
    ny, nx = len(lava), len(lava[0])
    rho = _get(spec, "density")
    area = dx * dx
    out_volume = [[0.0] * nx for _ in range(ny)]
    in_volume = [[0.0] * nx for _ in range(ny)]
    in_heat = [[0.0] * nx for _ in range(ny)]
    moved = False
    for j in range(ny):
        for i in range(nx):
            thick = lava[j][i]
            if thick <= 0.0:
                continue
            t = temps[j][i]
            eta = viscosity(spec, t)
            tau = yield_strength(spec, t)
            sends = []
            for di, dj, dist in tg.D8:
                a, b = i + di, j + dj
                if not (0 <= a < nx and 0 <= b < ny):
                    continue
                drop = h[j][i] - h[b][a]
                s = slope_sine(drop, dist * dx)
                h_cr = critical_thickness(tau, rho, s)
                q = bingham_flux(thick, h_cr, s, rho, eta)
                if q <= 0.0:
                    continue
                sends.append((a, b, min(q * dx * dt, 0.5 * drop * area), h_cr))
            if not sends:
                continue
            total = sum(v for _, _, v, _ in sends)
            movable = (thick - min(c for _, _, _, c in sends)) * area
            scale = min(1.0, movable / total) if total > 0.0 else 0.0
            if scale <= 0.0:
                continue
            moved = True
            for a, b, v, _ in sends:
                v *= scale
                out_volume[j][i] += v
                in_volume[b][a] += v
                in_heat[b][a] += v * t
    if not moved:
        return layers
    new_lava = _copy(lava)
    new_temps = _copy(temps)
    for j in range(ny):
        for i in range(nx):
            kept = max(0.0, lava[j][i] * area - out_volume[j][i])
            got = in_volume[j][i]
            if got > 0.0:
                new_temps[j][i] = (kept * temps[j][i] + in_heat[j][i]) / (kept + got) if kept > 0.0 \
                    else in_heat[j][i] / got
            new_lava[j][i] = (kept + got) / area
    out = dict(layers)
    out[name] = new_lava
    out["temperature"] = new_temps
    return out


# ------------------------------------------------------------------------------------------------------- cooling


def cool(spec, temperature, thickness, dt):
    """Radiative cooling for dt: T - emissivity sigma (T^4 - ambient^4) dt / (rho c max(thickness, crust)), never
    below ambient."""
    ambient = _get(spec, "ambient")
    if temperature <= ambient:
        return temperature
    eps = _get(spec, "emissivity")
    if eps == 0.0:
        return temperature
    mass = _get(spec, "density") * _get(spec, "heatCapacity") * max(thickness, _get(spec, "crust"))
    loss = eps * STEFAN_BOLTZMANN * (temperature ** 4 - ambient ** 4) * dt / mass
    return max(ambient, temperature - loss)


def cool_step(layers, spec, dt):
    name = _get(spec, "layer")
    lava = layers[name]
    temps = layers["temperature"]
    out = dict(layers)
    out["temperature"] = [[cool(spec, temps[j][i], lava[j][i], dt) for i in range(len(temps[0]))]
                          for j in range(len(temps))]
    return out


def solidify(layers, spec):
    """Lava colder than the solidus becomes bedrock. (layers, metres of lava solidified, summed over the cells)."""
    name = _get(spec, "layer")
    lava = layers[name]
    temps = layers["temperature"]
    solidus = _get(spec, "solidus")
    bed = None
    new_lava = None
    total = 0.0
    for j in range(len(lava)):
        for i in range(len(lava[0])):
            if lava[j][i] > 0.0 and temps[j][i] < solidus:
                if bed is None:
                    bed, new_lava = _copy(layers["bedrock"]), _copy(lava)
                bed[j][i] += lava[j][i]
                total += lava[j][i]
                new_lava[j][i] = 0.0
    if bed is None:
        return layers, 0.0
    out = dict(layers)
    out["bedrock"] = bed
    out[name] = new_lava
    return out, total


# ---------------------------------------------------------------------------------------------------------- vent


def vent_cell(spec, dx, nx, ny):
    """The cell holding the vent (floor of ventX / dx, ventY / dx), or None outside the grid."""
    i = math.floor(_get(spec, "ventX") / dx)
    j = math.floor(_get(spec, "ventY") / dx)
    if 0 <= i < nx and 0 <= j < ny:
        return i, j
    return None


def value(spec, key, t):
    """An attribute at time t: a number, or a callable of t (the document's animation of it)."""
    v = _get(spec, key)
    return v(t) if callable(v) else v


def effusion_volume(spec, e, step):
    """effusion(t) * step * (1 + effusionVariation * (2 S - 1)) cubic metres at t = step * stepLength,
    S = S(e, PURPOSE, step, 0); no draw when the variation is zero."""
    dt = _get(spec, "step")
    base = value(spec, "effusion", step * dt) * dt
    variation = _get(spec, "effusionVariation")
    if base == 0.0 or variation == 0.0:
        return base
    s = streams().S(e, PURPOSE, step, 0)
    return base * (1.0 + variation * (2.0 * s - 1.0))


def erupt(layers, spec, dx, e, step):
    """Add the step's effusion to the vent cell at the eruption temperature, mixing with the lava there by
    volume; the same layers when nothing erupts."""
    return _erupt(layers, spec, dx, effusion_volume(spec, e, step))


def _erupt(layers, spec, dx, volume):
    name = _get(spec, "layer")
    cell = vent_cell(spec, dx, len(layers[name][0]), len(layers[name]))
    if volume <= 0.0 or cell is None:
        return layers
    i, j = cell
    depth = volume / (dx * dx)
    lava = _copy(layers[name])
    temps = _copy(layers["temperature"])
    had = lava[j][i]
    t_e = _get(spec, "eruptionTemperature")
    temps[j][i] = (had * temps[j][i] + depth * t_e) / (had + depth) if had > 0.0 else t_e
    lava[j][i] = had + depth
    out = dict(layers)
    out[name] = lava
    out["temperature"] = temps
    return out


# ----------------------------------------------------------------------------------------------------------- run


def step(layers, spec, dx, e, n):
    """One step: erupt, flow, cool, solidify. (layers, erupted cubic metres, solidified metres)."""
    dt = _get(spec, "step")
    erupted = max(0.0, effusion_volume(spec, e, n))
    out = _erupt(layers, spec, dx, erupted)
    if out is layers:
        erupted = 0.0
    out = flow_step(out, spec, dx, dt)
    out = cool_step(out, spec, dt)
    out, solid = solidify(out, spec)
    return out, erupted, solid


def steps_for(t, step_length, max_steps):
    """round(t / step) steps, never more than maxSteps."""
    if not step_length > 0.0:
        raise LavaError("LV1: step is positive")
    return min(int(round(t / step_length)), max_steps)


def digest(layers):
    """sha256 of the layers as JSON with sorted keys and values rounded to three decimals."""
    rounded = {k: [[round(v, DIGEST_DECIMALS) if not isinstance(v, tuple) else [round(c, DIGEST_DECIMALS) for c in v]
                    for v in row] for row in rows] for k, rows in layers.items()}
    text = json.dumps(rounded, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(doc, t):
    """The terrain's layers at time t: the generated layers after round(t / step) lava steps."""
    tg = terrain()
    codes = validate_document(doc)
    if codes:
        raise LavaError("invalid document: " + ", ".join(codes))
    built = tg.build(doc)
    layers = built["layers"]
    spec = doc["lavaFlow"]
    dx = float(doc.get("metersPerCell", 1.0))
    e = tg.element_seed(doc, doc.get("project", 0))
    steps = steps_for(t, _get(spec, "step"), _get(spec, "maxSteps"))
    erupted = 0.0
    solidified = 0.0
    for n in range(steps):
        layers, got, solid = step(layers, spec, dx, e, n)
        erupted += got
        solidified += solid
    return {"shape": built["shape"], "layers": layers, "steps": steps, "erupted": erupted,
            "solidified": solidified, "digest": digest(layers)}


# ----------------------------------------------------------------------------------------------------- documents


def example_document():
    """The terrain draft's example with lava and temperature layers and a vent erupting 20 m^3/s near the top of
    the bowl's rim."""
    doc = terrain().example_document()
    doc["layers"] += [{"kind": "lava", "value": 0.0}, {"kind": "temperature", "value": 293.15}]
    doc["lavaFlow"] = {
        "layer": "lava", "ventX": 225.0, "ventY": 175.0, "effusion": 20.0, "effusionVariation": 0.25,
        "eruptionTemperature": 1360.0, "ambient": 293.15, "density": 2600.0, "heatCapacity": 1150.0,
        "emissivity": 0.9, "crust": 0.5, "solidus": 1173.15, "viscosity": 1000.0, "viscosityRate": 0.02,
        "yieldStrength": 2000.0, "yieldRate": 0.01, "step": 1.0, "maxSteps": 100000,
    }
    return doc


def example_seed():
    doc = example_document()
    return terrain().element_seed(doc, doc["project"])


def bad_document():
    doc = example_document()
    doc["lavaFlow"].update(effusion=-1.0, ventX=-5.0)
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] not in ("lava", "temperature")]
    return doc


def _non_negative(v):
    return _number(v) and v >= 0.0


def _positive(v):
    return _number(v) and v > 0.0


def _unit(v):
    return _number(v) and 0.0 <= v <= 1.0


def validate_document(doc):
    """The draft's rules LV1 to LV4 and V17 over a terrain document, as sorted codes."""
    if "lavaFlow" not in doc:
        return []
    major, minor = (int(x) for x in str(doc.get("version", "1.8")).split(".")[:2])
    if (major, minor) < (1, 8):
        return ["V17"]
    codes = set()
    spec = doc["lavaFlow"]
    g = lambda key: _get(spec, key)      # noqa: E731
    max_steps = g("maxSteps")
    if not (_non_negative(value(spec, "effusion", 0.0)) and _unit(g("effusionVariation")) and _positive(g("eruptionTemperature"))
            and _non_negative(g("ambient")) and _positive(g("density")) and _positive(g("heatCapacity"))
            and _unit(g("emissivity")) and _positive(g("crust")) and _non_negative(g("solidus"))
            and _positive(g("viscosity")) and _non_negative(g("viscosityRate"))
            and _non_negative(g("yieldStrength")) and _non_negative(g("yieldRate")) and _positive(g("step"))
            and isinstance(max_steps, int) and not isinstance(max_steps, bool) and max_steps > 0):
        codes.add("LV1")
    kinds = {terrain()._layer_key(layer) for layer in doc.get("layers", ())}
    if g("layer") != "lava" or "lava" not in kinds or "bedrock" not in kinds:
        codes.add("LV2")
    if "temperature" not in kinds:
        codes.add("LV3")
    nx, ny = _shape(doc)
    if not (_number(g("ventX")) and _number(g("ventY"))) or (
            nx > 0 and vent_cell(spec, float(doc.get("metersPerCell", 1.0)), nx, ny) is None):
        codes.add("LV4")
    return sorted(codes)


def _shape(doc):
    """The terrain's grid, or (0, 0) when the terrain's own rules refuse it (they report that themselves)."""
    tg = terrain()
    try:
        return tg.grid(doc)
    except tg.TerrainError:
        return 0, 0


# ------------------------------------------------------------------------------------------------- numeric table

TABLE = (
    ("element seed", "example_seed()", "1572054040"),
    ("effusion purpose", "PURPOSE", "2147614720"),
    ("viscosity at the eruption temperature", "viscosity(DEFAULTS, 1360.0)", "1000.0"),
    ("viscosity 100 K cooler", "viscosity(DEFAULTS, 1260.0)", "100000.0"),
    ("yield strength at the solidus", "yield_strength(DEFAULTS, 1173.15)", "147750.85259872698"),
    ("critical thickness", "critical_thickness(2000.0, 2600.0, 0.1)", "0.7841292244961968"),
    ("critical thickness on the flat", "math.isinf(critical_thickness(2000.0, 2600.0, 0.0))", "True"),
    ("slope sine", "slope_sine(3.0, 4.0)", "0.6"),
    ("flux under the critical thickness", "bingham_flux(0.5 * H_CR, H_CR, 0.1, 2600.0, 1000.0)", "0.0"),
    ("flux at twice the critical thickness", "bingham_flux(2.0 * H_CR, H_CR, 0.1, 2600.0, 1000.0)", "1.0247644011816783"),
    ("flux at twice, by hand", "2600.0 * GRAVITY * 0.1 * H_CR ** 3 / 3000.0 * (8.0 - 6.0 + 0.5)", "1.0247644011816783"),
    ("Nusselt film flux", "bingham_flux(1.0, 0.0, 0.1, 2600.0, 1000.0)", "0.8502000000000001"),
    ("incline, critical thickness", "INCLINE[1]", "0.45156202329990075"),
    ("incline, steps to halt", "INCLINE[2]", "3370"),
    ("incline, thickest cell", "max(INCLINE[0]['lava'][0])", "0.4514328792017486"),
    ("incline, cells covered", "sum(1 for v in INCLINE[0]['lava'][0] if v > 0.0)", "16"),
    ("incline, volume", "sum(INCLINE[0]['lava'][0])", "5.0"),
    ("spread, centre", "SPREAD['lava'][2][2]", "0.08265447764364975"),
    ("spread, neighbour", "SPREAD['lava'][2][3]", "0.36466819029454384"),
    ("spread, corner", "SPREAD['lava'][3][3]", "0.36466819029454384"),
    ("mixing", "MIXED['temperature'][3][3]", "1180.6865313378619"),
    ("cooling after one second", "cool(DEFAULTS, 1360.0, 1.0, 1.0)", "1359.9417360209059"),
    ("cooling after an hour", "COOLED", "1198.167315317712"),
    ("cooling of a crust", "cool(DEFAULTS, 1360.0, 0.0, 1.0)", "1359.8834720418117"),
    ("solidified", "SOLID[1]", "2.0"),
    ("vent cell", "vent_cell(dict(DEFAULTS, ventX=125.0, ventY=75.0), 50.0, 6, 4)", "(2, 1)"),
    ("effusion, varied", "effusion_volume(dict(DEFAULTS, effusion=10.0, effusionVariation=0.5), E, 3)", "11.584212274641509"),
    ("steps", "steps_for(300.0, 1.0, 100000)", "300"),
    ("run, steps", "RUN['steps']", "300"),
    ("run, erupted", "RUN['erupted']", "5991.748558218481"),
    ("run, lava", "sum(v for row in RUN['layers']['lava'] for v in row)", "2.39669942328739"),
    ("run, cells with lava", "sum(1 for row in RUN['layers']['lava'] for v in row if v > 0.0)", "8"),
    ("run, hottest cell", "max(v for row in RUN['layers']['temperature'] for v in row)", "1355.78658025027"),
    ("run, solidified", "RUN['solidified']", "0.0"),
    ("run, digest", "RUN['digest']", "'b44d547432279f53a15f1542dae655bce084a4e51ade0ff9bc27169c16399c9a'"),
    ("bad document", "validate_document(bad_document())", "['LV1', 'LV2', 'LV3', 'LV4']"),
)

_SCOPE = None


def scope():
    """The names the table's expressions use (computed once)."""
    global _SCOPE
    if _SCOPE is not None:
        return _SCOPE
    tg = terrain()
    s = dict(globals())
    s["E"] = example_seed()
    s["H_CR"] = critical_thickness(2000.0, 2600.0, 0.1)
    iso = dict(DEFAULTS, emissivity=0.0, solidus=0.0, viscosity=100.0, yieldStrength=2000.0, viscosityRate=0.0,
               yieldRate=0.0)
    nx, dx, angle = 60, 10.0, 10.0
    layers = {"bedrock": [[-(i * dx) * math.tan(math.radians(angle)) for i in range(nx)]],
              "lava": tg.flat(nx, 1, 0.0), "temperature": tg.flat(nx, 1, 1360.0)}
    for i in range(5):
        layers["lava"][0][i] = 1.0
    n = 0
    while True:
        after = flow_step(layers, iso, dx, 1.0)
        if after is layers:
            break
        layers = after
        n += 1
    s["INCLINE"] = (layers, critical_thickness(2000.0, DEFAULTS["density"], math.sin(math.radians(angle))), n)
    spread = {"bedrock": tg.flat(5, 5, 0.0), "lava": tg.flat(5, 5, 0.0), "temperature": tg.flat(5, 5, 1360.0)}
    spread["lava"][2][2] = 3.0
    s["SPREAD"] = flow_step(spread, iso, 1.0, 1.0)
    mixed = {"bedrock": tg.plane(6, 6, -0.5, 0.0, 1.0), "lava": tg.flat(6, 6, 0.0), "temperature": tg.flat(6, 6, 293.15)}
    mixed["lava"][3][2], mixed["temperature"][3][2] = 1.0, 1300.0
    mixed["lava"][3][3], mixed["temperature"][3][3] = 1.0, 1100.0
    s["MIXED"] = flow_step(mixed, iso, 1.0, 1.0)
    cooled = 1360.0
    for _ in range(3600):
        cooled = cool(DEFAULTS, cooled, 1.0, 1.0)
    s["COOLED"] = cooled
    solid = {"bedrock": tg.flat(4, 4, 0.0), "lava": tg.flat(4, 4, 0.0), "temperature": tg.flat(4, 4, 293.15)}
    solid["lava"][1][1], solid["temperature"][1][1] = 2.0, 1100.0
    s["SOLID"] = solidify(solid, DEFAULTS)
    s["RUN"] = run(example_document(), 300.0)
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
