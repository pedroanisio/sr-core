"""Reference for the draft SREP "Add snow and ice to the terrain grid" (T3 of SREP 12).

One `snowpack` child of a `terrain` (the F2 terrain-grid draft) acts on one of its snow layers, its `water` layer
and its `ice` layer. Each step, in this order: snowfall (varied through the random streams), degree-day melt
into the water layer, drift by the wind of the F4 draft (Pomeroy's saltation law with the exposure of
Fearing 2000: windward slopes lose, lee slopes gain), avalanches (the thermal relaxation of the erosion draft on
the snow layer at the angle of repose, Musgrave et al. 1989, as Cordonnier et al. 2018 use it), and, when
`iceTimeScale` is positive, the glacier flow of the ice layer by the shallow-ice approximation (Hutter 1983) in
adaptive explicit substeps that keep the ice non-negative and its volume constant.

Lengths are metres on the terrain's grid (i right, j down, `metersPerCell` apart), snow depths are metres of
snow, water depths metres of water, temperatures kelvin, time seconds on the terrain's clock except the ice,
which runs `iceTimeScale` ice-years per second. `python snow_reference.py` prints the numeric table of the
draft's conformance section.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PURPOSE = 2 ** 31 + 2 ** 16     # the snowfall draws: S(e, PURPOSE, step, pack(i, j, 0)), clear of the erode children
FREEZING = 273.15
GRAVITY = 9.81
ICE_DENSITY = 917.0             # kg/m^3
GLEN_N = 3
ICE_CFL = 0.125                 # explicit diffusion substep: ICE_CFL * dx^2 / max D (four neighbours, a half of the bound)
MAX_ICE_SUBSTEPS = 1000         # per step
DIGEST_DECIMALS = 3
DEFAULTS = {
    "layer": "snow", "snowfall": 0.0, "snowfallVariation": 0.0, "temperature": 268.15, "meltRate": 1e-5,
    "density": 0.3, "repose": 38.0, "avalancheRate": 0.5, "wind": None, "driftRate": 1e-4, "driftThreshold": 5.0,
    "exposureGain": 1.0, "iceFlow": 1e-16, "iceTimeScale": 0.0, "step": 0.02, "maxSteps": 100000,
}


class SnowError(ValueError):
    """A snowpack or input outside the draft's rules."""


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
    """The terrain-grid reference (grid, surface, gradient, D8, build, element seed)."""
    return _load("terrain_grid_reference")


def erosion():
    """The erosion reference (the thermal step the avalanche reuses)."""
    return _load("erosion_reference")


def wind():
    """The wind reference (wind_at)."""
    return _load("wind_reference")


def streams():
    """The random-streams reference (E, S, pack) through the terrain reference."""
    return terrain().streams()


def _get(spec, key):
    return spec[key] if key in spec and spec[key] is not None else DEFAULTS[key]


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _copy(rows):
    return [list(row) for row in rows]


def snow_key(layers, name):
    """The key of the snow layer `name` names: `snow:<type>` or `snow` for the layer without a type."""
    if name in layers and name.split(":")[0] == "snow":
        return name
    if name == "snow" and "snow:" in layers:
        return "snow:"
    raise SnowError(f"SN2: the terrain has no snow layer {name!r}")


# -------------------------------------------------------------------------------------------- snowfall and melt


def snowfall_depth(spec, e, step, i, j):
    """snowfall * step * (1 + snowfallVariation * (2 S - 1)), S = S(e, PURPOSE, step, pack(i, j, 0)); no draw when
    the variation is zero."""
    base = _get(spec, "snowfall") * _get(spec, "step")
    variation = _get(spec, "snowfallVariation")
    if base == 0.0 or variation == 0.0:
        return base
    rs = streams()
    s = rs.S(e, PURPOSE, step, rs.pack(i, j, 0))
    return base * (1.0 + variation * (2.0 * s - 1.0))


def melt_depth(spec, temperature, dt):
    """The degree-day law: meltRate * max(0, T - 273.15) * dt metres of snow."""
    return _get(spec, "meltRate") * max(0.0, temperature - FREEZING) * dt


def cell_temperature(layers, spec, i, j):
    """The `temperature` layer where the terrain has one, else the attribute."""
    if "temperature" in layers:
        return layers["temperature"][j][i]
    return _get(spec, "temperature")


# -------------------------------------------------------------------------------------------------- avalanches


def max_slope(h, dx):
    """The steepest descent to any of the eight neighbours, in degrees (the erosion reference's)."""
    return erosion().max_neighbour_slope(h, dx)


def avalanche_step(layers, spec, dx):
    """The erosion draft's thermal step on the snow layer: talus = repose, rate = avalancheRate."""
    key = snow_key(layers, _get(spec, "layer"))
    thermal = {"layer": key, "talus": _get(spec, "repose"), "rate": _get(spec, "avalancheRate")}
    return erosion().thermal_step(layers, thermal, dx)


# ------------------------------------------------------------------------------------------------------- drift


def drift_flux(spec, speed):
    """Metres of snow per second leaving a cell: driftRate * max(0, speed - driftThreshold)^3."""
    excess = speed - _get(spec, "driftThreshold")
    if excess <= 0.0:
        return 0.0
    return _get(spec, "driftRate") * excess ** 3


def exposure(gx, gy, w, gain):
    """clamp(1 + gain * (grad h . unit w), 0, 2): a surface rising along the wind is exposed, one falling is in
    the lee; 1 on the flat and in calm air."""
    speed = math.hypot(w[0], w[1])
    if speed == 0.0:
        return 1.0
    return min(2.0, max(0.0, 1.0 + gain * (gx * w[0] + gy * w[1]) / speed))


def _project_seed(doc):
    project = doc.get("project", 0)
    if isinstance(project, dict):
        return project.get("seed", 0)
    return project


def wind_grid(doc, wind_id, t, nx, ny, dx):
    """The grid-space wind (w_x, -w_y) at the cell centres: cell (i, j) reads the planar wind of the wind draft at
    the physics point ((i + 1/2) dx, -(j + 1/2) dx), the terrain's top-left corner at the origin, +y up."""
    wr = wind()
    shim = {"project": {"seed": _project_seed(doc)}, "physics": doc.get("physics", {})}
    out = []
    for j in range(ny):
        row = []
        for i in range(nx):
            wx, wy = wr.wind_at(shim, wind_id, ((i + 0.5) * dx, -(j + 0.5) * dx), t)
            row.append((wx, -wy))
        out.append(row)
    return out


def drift_step(layers, spec, dx, winds, dt):
    """Synchronous upwind transport of the snow layer by the wind grid: the amount leaving a cell is the drift flux
    at its wind speed times its exposure times dt, never more than it holds, split between the downwind x and y
    neighbours by the wind's components; snow pushed over an edge is lost and returned. (layers, lost)."""
    tg = terrain()
    key = snow_key(layers, _get(spec, "layer"))
    snow = layers[key]
    ny, nx = len(snow), len(snow[0])
    gx, gy = tg.gradient(tg.surface(layers), dx)
    gain = _get(spec, "exposureGain")
    delta = [[0.0] * nx for _ in range(ny)]
    lost = 0.0
    moved = False
    for j in range(ny):
        for i in range(nx):
            w = winds[j][i]
            flux = drift_flux(spec, math.hypot(w[0], w[1]))
            if flux == 0.0:
                continue
            amount = min(snow[j][i], flux * exposure(gx[j][i], gy[j][i], w, gain) * dt)
            if amount <= 0.0:
                continue
            moved = True
            total = abs(w[0]) + abs(w[1])
            delta[j][i] -= amount
            for part, a, b in ((abs(w[0]) / total, i + (1 if w[0] > 0 else -1), j),
                               (abs(w[1]) / total, i, j + (1 if w[1] > 0 else -1))):
                if part == 0.0:
                    continue
                if 0 <= a < nx and 0 <= b < ny:
                    delta[b][a] += amount * part
                else:
                    lost += amount * part
    if not moved:
        return layers, 0.0
    out = dict(layers)
    out[key] = [[snow[j][i] + delta[j][i] for i in range(nx)] for j in range(ny)]
    return out, lost


# ---------------------------------------------------------------------------------------------------- glaciers


def ice_diffusivity(thickness, slope, a):
    """The shallow-ice diffusivity 2A/(n+2) (rho g)^n H^(n+2) |grad s|^(n-1), n = 3, in m^2 per ice-year when A
    is in Pa^-3 per ice-year."""
    if thickness <= 0.0 or slope == 0.0:
        return 0.0
    return 2.0 * a / (GLEN_N + 2) * (ICE_DENSITY * GRAVITY) ** GLEN_N * thickness ** (GLEN_N + 2) * slope ** (GLEN_N - 1)


def ice_step(layers, spec, dx, dt):
    """The ice layer after dt ice-years of shallow-ice flow: explicit finite volumes on the ground surface, the
    face diffusivity from the mean thickness and the surface drop across the face, substeps of ICE_CFL dx^2 / max D
    (never more than MAX_ICE_SUBSTEPS), each cell's outflow scaled to what it holds. (layers, substeps)."""
    if "ice" not in layers:
        raise SnowError("SN4: the terrain has no ice layer")
    tg = terrain()
    a = _get(spec, "iceFlow")
    ice = _copy(layers["ice"])
    ny, nx = len(ice), len(ice[0])
    surface = tg.surface(layers)
    base = [[surface[j][i] - ice[j][i] for i in range(nx)] for j in range(ny)]
    remaining = dt
    substeps = 0
    while remaining > 0.0:
        faces = []
        dmax = 0.0
        for j in range(ny):
            for i in range(nx):
                for a2, b2 in ((i + 1, j), (i, j + 1)):
                    if a2 >= nx or b2 >= ny:
                        continue
                    drop = (base[j][i] + ice[j][i]) - (base[b2][a2] + ice[b2][a2])
                    d = ice_diffusivity((ice[j][i] + ice[b2][a2]) / 2.0, abs(drop) / dx, a)
                    if d > 0.0:
                        faces.append((i, j, a2, b2, d * drop / dx))        # m^2 per ice-year toward (a2, b2) if positive
                        dmax = max(dmax, d)
        if dmax == 0.0:
            break
        sub = min(remaining, ICE_CFL * dx * dx / dmax)
        substeps += 1
        if substeps > MAX_ICE_SUBSTEPS:
            raise SnowError(f"the ice step needs more than {MAX_ICE_SUBSTEPS} substeps")
        out = [[0.0] * nx for _ in range(ny)]
        for i, j, a2, b2, flux in faces:
            amount = flux * sub / dx
            if amount > 0.0:
                out[j][i] += amount
            else:
                out[b2][a2] -= amount
        factor = [[min(1.0, ice[j][i] / out[j][i]) if out[j][i] > 0.0 else 1.0 for i in range(nx)] for j in range(ny)]
        delta = [[0.0] * nx for _ in range(ny)]
        for i, j, a2, b2, flux in faces:
            amount = flux * sub / dx
            if amount > 0.0:
                amount *= factor[j][i]
            else:
                amount *= factor[b2][a2]
            delta[j][i] -= amount
            delta[b2][a2] += amount
        for j in range(ny):
            for i in range(nx):
                ice[j][i] = max(0.0, ice[j][i] + delta[j][i])
        remaining -= sub
    return dict(layers, ice=ice), substeps


# --------------------------------------------------------------------------------------------------- the element


def step(layers, spec, dx, e, n, winds):
    """One step of the snowpack: snowfall, melt, drift (when a wind grid is given), avalanche, ice. (layers, lost)."""
    key = snow_key(layers, _get(spec, "layer"))
    dt = _get(spec, "step")
    density = _get(spec, "density")
    snow = _copy(layers[key])
    water = _copy(layers["water"]) if "water" in layers else None
    ny, nx = len(snow), len(snow[0])
    for j in range(ny):
        for i in range(nx):
            depth = snow[j][i] + snowfall_depth(spec, e, n, i, j)
            melt = min(depth, melt_depth(spec, cell_temperature(layers, spec, i, j), dt))
            snow[j][i] = depth - melt
            if water is not None and melt > 0.0:
                water[j][i] += density * melt
    out = dict(layers)
    out[key] = snow
    if water is not None:
        out["water"] = water
    lost = 0.0
    if winds is not None:
        out, lost = drift_step(out, spec, dx, winds, dt)
    out = avalanche_step(out, spec, dx)
    if _get(spec, "iceTimeScale") > 0.0 and "ice" in out:
        out, _ = ice_step(out, spec, dx, dt * _get(spec, "iceTimeScale"))
    return out, lost


def steps_for(t, step, max_steps):
    """round(t / step) steps, never more than maxSteps."""
    if not step > 0.0:
        raise SnowError("SN1: step is positive")
    return min(int(round(t / step)), max_steps)


def digest(layers):
    """sha256 of the layers as JSON with sorted keys and values rounded to three decimals."""
    rounded = {k: [[round(v, DIGEST_DECIMALS) if not isinstance(v, tuple) else [round(c, DIGEST_DECIMALS) for c in v]
                    for v in row] for row in rows] for k, rows in layers.items()}
    text = json.dumps(rounded, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(doc, t):
    """The terrain's layers at time t: the generated layers after round(t / step) snowpack steps, the wind grid
    read at each step's start time."""
    tg = terrain()
    codes = validate_document(doc)
    if codes:
        raise SnowError("invalid document: " + ", ".join(codes))
    built = tg.build(doc)
    layers = built["layers"]
    spec = doc["snowpack"]
    dx = float(doc.get("metersPerCell", 1.0))
    e = tg.element_seed(doc, doc.get("project", 0))
    dt = _get(spec, "step")
    steps = steps_for(t, dt, _get(spec, "maxSteps"))
    wind_id = _get(spec, "wind")
    ny, nx = len(layers[snow_key(layers, _get(spec, "layer"))]), len(layers[snow_key(layers, _get(spec, "layer"))][0])
    lost = 0.0
    for n in range(steps):
        winds = wind_grid(doc, wind_id, n * dt, nx, ny, dx) if wind_id is not None else None
        layers, gone = step(layers, spec, dx, e, n, winds)
        lost += gone
    return {"shape": built["shape"], "layers": layers, "steps": steps, "lost": lost, "digest": digest(layers)}


# ----------------------------------------------------------------------------------------------------- documents


def example_document():
    """The terrain draft's example with snow, ice and temperature layers, a steady 9 m/s wind and a snowpack."""
    doc = terrain().example_document()
    doc["layers"] += [{"kind": "snow", "value": 0.0}, {"kind": "ice", "value": 0.0},
                      {"kind": "temperature", "value": 270.15}]
    doc["physics"] = {"winds": [{"id": "w1", "speed": 9.0, "direction": 20.0, "seed": 3}]}
    doc["snowpack"] = {
        "layer": "snow", "snowfall": 0.002, "snowfallVariation": 0.25, "temperature": 268.15, "meltRate": 1e-5,
        "density": 0.3, "repose": 38.0, "avalancheRate": 0.5, "wind": "w1", "driftRate": 2e-5,
        "driftThreshold": 5.0, "exposureGain": 1.0, "iceFlow": 1e-16, "iceTimeScale": 1.0, "step": 0.02,
        "maxSteps": 100000,
    }
    return doc


def example_seed():
    doc = example_document()
    return terrain().element_seed(doc, doc["project"])


def bad_document():
    doc = example_document()
    doc["snowpack"].update(snowfall=-1.0, layer="snow:deep", wind="w9")
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] not in ("ice", "water")]
    return doc


def _non_negative(v):
    return _number(v) and v >= 0.0


def _positive(v):
    return _number(v) and v > 0.0


def _unit(v):
    return _number(v) and 0.0 <= v <= 1.0


def validate_document(doc):
    """The draft's rules SN1 to SN5 and V17 over a terrain document, as sorted codes."""
    if "snowpack" not in doc:
        return []
    major, minor = (int(x) for x in str(doc.get("version", "1.8")).split(".")[:2])
    if (major, minor) < (1, 8):
        return ["V17"]
    codes = set()
    spec = doc["snowpack"]
    g = lambda key: _get(spec, key)      # noqa: E731
    max_steps = g("maxSteps")
    if not (_non_negative(g("snowfall")) and _unit(g("snowfallVariation")) and _positive(g("temperature"))
            and _non_negative(g("meltRate")) and _number(g("density")) and 0.0 < g("density") <= 1.0
            and _number(g("repose")) and 0.0 < g("repose") < 90.0 and _unit(g("avalancheRate"))
            and _non_negative(g("driftRate")) and _non_negative(g("driftThreshold"))
            and _non_negative(g("exposureGain")) and _non_negative(g("iceFlow")) and _non_negative(g("iceTimeScale"))
            and _positive(g("step"))
            and isinstance(max_steps, int) and not isinstance(max_steps, bool) and max_steps > 0):
        codes.add("SN1")
    kinds = {terrain()._layer_key(layer) for layer in doc.get("layers", ())}
    try:
        snow_key(kinds, g("layer"))
    except SnowError:
        codes.add("SN2")
    wind_id = g("wind")
    if wind_id is not None and not any(w.get("id") == wind_id for w in doc.get("physics", {}).get("winds", ())):
        codes.add("SN3")
    if _number(g("iceTimeScale")) and g("iceTimeScale") > 0.0 and "ice" not in kinds:
        codes.add("SN4")
    if _number(g("meltRate")) and g("meltRate") > 0.0 and "water" not in kinds:
        codes.add("SN5")
    return sorted(codes)


# ------------------------------------------------------------------------------------------------- numeric table

TABLE = (
    ("element seed", "example_seed()", "1572054040"),
    ("snowfall purpose", "PURPOSE", "2147549184"),
    ("snowfall, no variation", "snowfall_depth(dict(DEFAULTS, snowfall=0.001, step=0.1), E, 3, 2, 4)", "0.0001"),
    ("snowfall, varied", "snowfall_depth(dict(DEFAULTS, snowfall=0.001, snowfallVariation=0.5, step=0.1), E, 3, 2, 4)", "0.00013778532762148574"),
    ("melt below freezing", "melt_depth(DEFAULTS, 263.15, 1.0)", "0.0"),
    ("melt, degree-day", "melt_depth(dict(DEFAULTS, meltRate=1e-3), 275.15, 0.1)", "0.0002"),
    ("cell temperature from the layer", "cell_temperature(COLD, DEFAULTS, 3, 2)", "280.15"),
    ("cell temperature from the attribute", "cell_temperature({'bedrock': [[0.0]]}, dict(DEFAULTS, temperature=275.15), 0, 0)", "275.15"),
    ("pile, slope before", "max_slope(PILE['snow'], 1.0)", "80.53767779197439"),
    ("pile, slope after 400 steps", "max_slope(RELAXED['snow'], 1.0)", "38.000000000000014"),
    ("pile, mass", "sum(v for row in RELAXED['snow'] for v in row)", "6.000000000000001"),
    ("drift flux", "drift_flux(dict(DEFAULTS, driftRate=1e-4, driftThreshold=5.0), 7.0)", "0.0008"),
    ("exposure, windward", "exposure(0.1, 0.0, (8.0, 0.0), 1.0)", "1.1"),
    ("exposure, lee", "exposure(-0.1, 0.0, (8.0, 0.0), 1.0)", "0.9"),
    ("wind grid", "wind_grid(WINDY, 'w1', 0.0, 3, 2, 10.0)[1][2]", "(4.898587196589413e-16, -8.0)"),
    ("drift, upwind edge", "DRIFTED[0]['snow'][2][0]", "0.4973"),
    ("drift, interior", "DRIFTED[0]['snow'][2][3]", "0.5"),
    ("drift, lost", "DRIFTED[1]", "0.016200000000000003"),
    ("drift, lee of the ridge", "RIDGE['snow'][4][5]", "0.43601170854452553"),
    ("drift, foot of the ridge", "RIDGE['snow'][4][3]", "0.16795522905394863"),
    ("ice diffusivity", "ice_diffusivity(100.0, 0.1, 1e-16)", "2911.8903721304528"),
    ("ice dome, substeps", "DOME[1]", "4"),
    ("ice dome, centre", "DOME[0]['ice'][0][20]", "99.97193132114218"),
    ("ice dome, volume", "sum(DOME[0]['ice'][0])", "1597.2222222222222"),
    ("steps", "steps_for(0.5, 0.02, 100000)", "25"),
    ("run, steps", "RUN['steps']", "25"),
    ("run, snow", "sum(v for row in RUN['layers']['snow:'] for v in row)", "0.18596718532685694"),
    ("run, deepest snow", "max(v for row in RUN['layers']['snow:'] for v in row)", "0.025962109894478665"),
    ("run, lost", "RUN['lost']", "0.00575764954799598"),
    ("run, digest", "RUN['digest']", "'27b25c6cef96968af912cf1614ee75deb9ff92c7b01c1a01d5dd39654c33e1f3'"),
    ("bad document", "validate_document(bad_document())", "['SN1', 'SN2', 'SN3', 'SN4', 'SN5']"),
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
    cold = {"bedrock": tg.flat(6, 6, 0.0), "temperature": tg.flat(6, 6, 263.15)}
    cold["temperature"][2][3] = 280.15
    s["COLD"] = cold
    pile = {"bedrock": tg.flat(9, 9, 0.0), "snow": tg.flat(9, 9, 0.0)}
    pile["snow"][4][4] = 6.0
    s["PILE"] = pile
    relaxed = pile
    for _ in range(400):
        relaxed = avalanche_step(relaxed, DEFAULTS, 1.0)
    s["RELAXED"] = relaxed
    s["WINDY"] = {"version": "1.8", "project": 7,
                  "physics": {"winds": [{"id": "w1", "speed": 8.0, "direction": 90.0, "seed": 3}]}}
    drift = dict(DEFAULTS, driftRate=1e-3, driftThreshold=5.0, step=0.1)
    s["DRIFTED"] = drift_step({"bedrock": tg.flat(6, 6, 0.0), "snow": tg.flat(6, 6, 0.5)}, drift, 1.0,
                              [[(8.0, 0.0)] * 6 for _ in range(6)], 0.1)
    ridge = {"bedrock": [[5.0 if i == 4 else 0.0 for i in range(9)] for _ in range(9)], "snow": tg.flat(9, 9, 0.3)}
    for _ in range(20):
        ridge, _ = drift_step(ridge, drift, 1.0, [[(9.0, 0.0)] * 9 for _ in range(9)], 0.1)
    s["RIDGE"] = ridge
    dome = [[max(0.0, 100.0 * (1.0 - ((i - 20.0) / 12.0) ** 2)) for i in range(41)]]
    s["DOME"] = ice_step({"bedrock": tg.flat(41, 1, 0.0), "ice": dome}, dict(DEFAULTS, iceTimeScale=1.0), 100.0, 10.0)
    s["RUN"] = run(example_document(), 0.5)
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
