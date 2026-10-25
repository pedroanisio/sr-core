"""Reference for the draft SREP "Add erosion processes to the terrain grid" (T1 of SREP 12).

`erode` children of a `terrain` (the F2 terrain-grid draft) act on its layers: `fluvial` is the linear stream
power law (uplift against K A^m S, n = 1) solved in closed form along the D8 flow paths of the generated surface
with a frozen drainage area, evaluated at a geological time, so any time is reached without stepping and every
frame renders alone; `thermal` is the talus relaxation of Musgrave, Kolb and Mace 1989 on one solid layer;
`hydraulic` is the virtual-pipes model of Mei, Decaudin and Hsu 2007 on the water, sediment, flow and loose
layers, with the sediment carried by the water fluxes so that the ground is conserved. The stepped processes
replay from the frame's start state, bounded by `maxSteps`.

Lengths are metres, the grid of the terrain draft (i right, j down, `metersPerCell` apart), fluvial time in
years, stepped time in seconds on the terrain's clock. `python erosion_reference.py` prints the numeric table
of the draft's conformance section.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

KINDS = ("fluvial", "thermal", "hydraulic")
GRAVITY = 9.81
PURPOSE_BASE = 2 ** 31    # erode child k draws its streams with purpose PURPOSE_BASE + k, clear of the generator channels
EPSILON_DEPTH = 1e-9      # below this water depth the velocity is zero
HYDRAULIC_DEFAULTS = {"rain": 0.01, "rainVariation": 0.0, "evaporation": 0.05, "capacity": 0.1, "erodeRate": 0.5,
                      "depositRate": 1.0, "pipeArea": 1.0, "minTilt": 0.1, "maxDepth": 0.05, "step": 0.02,
                      "boundary": "open", "maxSteps": 100000}
THERMAL_DEFAULTS = {"talus": 35.0, "rate": 0.5, "layer": "loose", "step": 0.02, "maxSteps": 100000}
FLUVIAL_DEFAULTS = {"uplift": 1e-3, "erodibility": 2e-5, "m": 0.5, "time": 0.0, "timeScale": 0.0, "layer": "bedrock"}
BOUNDARIES = ("open", "closed")
DIGEST_DECIMALS = 3


class ErosionError(ValueError):
    """An erosion process or input outside the draft's rules."""


# ------------------------------------------------------------------------------------------------- the references

_terrain = None


def terrain():
    """The terrain-grid reference module (grid, surface, D8, flow accumulation, build), loaded by path."""
    global _terrain
    if _terrain is None:
        path = os.path.join(HERE, "terrain_grid_reference.py")
        spec = importlib.util.spec_from_file_location("terrain_grid_reference", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _terrain = mod
    return _terrain


def streams():
    """The random-streams reference (E, S, pack) through the terrain reference."""
    return terrain().streams()


def _get(spec, key, defaults):
    return spec[key] if key in spec and spec[key] is not None else defaults[key]


def _defaults(kind):
    return {"fluvial": FLUVIAL_DEFAULTS, "thermal": THERMAL_DEFAULTS, "hydraulic": HYDRAULIC_DEFAULTS}[kind]


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _copy(rows):
    return [list(row) for row in rows]


# ------------------------------------------------------------------------------------------------- routing


def routing(h, dx):
    """D8 routing of a surface: each cell's receiver (its steepest strictly lower neighbour of eight, None at a
    pit or an outlet), the distance to it in metres, the D8 accumulation in cells and the drainage area in m^2."""
    tg = terrain()
    ny, nx = len(h), len(h[0])
    receiver, distance = {}, {}
    for j in range(ny):
        for i in range(nx):
            best, steepest, best_dist = None, 0.0, 0.0
            for di, dj, dist in tg.D8:
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny:
                    s = (h[j][i] - h[b][a]) / dist
                    if s > steepest:
                        best, steepest, best_dist = (a, b), s, dist
            receiver[(i, j)] = best
            distance[(i, j)] = best_dist * dx
    acc = tg.flow_accumulation(h)
    area = [[acc[j][i] * dx * dx for i in range(nx)] for j in range(ny)]
    order = sorted(receiver, key=lambda c: h[c[1]][c[0]])
    return {"receiver": receiver, "distance": distance, "accumulation": acc, "area": area, "order": order}


def travel_time(route, erodibility, m):
    """tau(i) = tau(receiver) + distance / (K A^m), zero at a base-level cell: the time a knickpoint needs to
    travel from the base level up to the cell."""
    tau = {}
    for cell in route["order"]:                           # receivers are lower, so already done
        r = route["receiver"][cell]
        if r is None:
            tau[cell] = 0.0
        else:
            a = route["area"][cell[1]][cell[0]]
            tau[cell] = tau[r] + route["distance"][cell] / (erodibility * a ** m)
    return tau


def _path(route, cell):
    path = [cell]
    while route["receiver"][path[-1]] is not None:
        path.append(route["receiver"][path[-1]])
    return path


def fluvial_surface(h0, route, tau, uplift, T):
    """The characteristic solution of dh/dt = U - K A^m S with frozen drainage: at a cell with travel time tau,
    h(T) = h0 at the point of the flow path with travel time tau - T plus U T while T < tau, and the steady
    profile h_base + U tau once T >= tau; a base-level cell keeps its height."""
    out = _copy(h0)
    for cell, t in tau.items():
        i, j = cell
        path = _path(route, cell)
        if T >= t:
            base = path[-1]
            out[j][i] = h0[base[1]][base[0]] + uplift * t
            continue
        target = t - T
        for a, b in zip(path, path[1:]):
            ta, tb = tau[a], tau[b]
            if tb <= target <= ta:
                f = (ta - target) / (ta - tb)
                ha, hb = h0[a[1]][a[0]], h0[b[1]][b[0]]
                out[j][i] = ha + f * (hb - ha) + uplift * T
                break
    return out


def geological_time(spec, t):
    """T = time + timeScale t, in years."""
    return _get(spec, "time", FLUVIAL_DEFAULTS) + _get(spec, "timeScale", FLUVIAL_DEFAULTS) * t


def fluvial(layers, spec, dx, T):
    """Apply the closed form at geological time T: the named solid layer changes by the surface's change."""
    tg = terrain()
    name = _get(spec, "layer", FLUVIAL_DEFAULTS)
    if name not in layers:
        raise ErosionError(f"ER4: the terrain has no {name!r} layer")
    h0 = tg.surface(layers)
    route = routing(h0, dx)
    tau = travel_time(route, _get(spec, "erodibility", FLUVIAL_DEFAULTS), _get(spec, "m", FLUVIAL_DEFAULTS))
    h = fluvial_surface(h0, route, tau, _get(spec, "uplift", FLUVIAL_DEFAULTS), T)
    out = dict(layers)
    out[name] = [[layers[name][j][i] + (h[j][i] - h0[j][i]) for i in range(len(h0[0]))] for j in range(len(h0))]
    return out


# ------------------------------------------------------------------------------------------------- thermal


def max_neighbour_slope(h, dx):
    """The steepest descent to any of the eight neighbours over the grid, in degrees."""
    tg = terrain()
    ny, nx = len(h), len(h[0])
    best = 0.0
    for j in range(ny):
        for i in range(nx):
            for di, dj, dist in tg.D8:
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny:
                    best = max(best, (h[j][i] - h[b][a]) / (dist * dx))
    return math.degrees(math.atan(best))


def thermal_step(layers, spec, dx):
    """One Musgrave step: a cell whose drop to a neighbour exceeds tan(talus) times the distance moves `rate`
    times half its largest excess from the named layer to the lower neighbours in proportion to their excess,
    never more than the layer holds; synchronous, mass-conserving, closed edges."""
    tg = terrain()
    name = _get(spec, "layer", THERMAL_DEFAULTS)
    if name not in layers or name.split(":")[0] not in tg.SOLID_LAYERS:
        raise ErosionError(f"ER3: the terrain has no solid {name!r} layer")
    h = tg.surface(layers)
    ny, nx = len(h), len(h[0])
    tan_t = math.tan(math.radians(_get(spec, "talus", THERMAL_DEFAULTS)))
    rate = _get(spec, "rate", THERMAL_DEFAULTS)
    delta = [[0.0] * nx for _ in range(ny)]
    moved = False
    for j in range(ny):
        for i in range(nx):
            excess = []
            for di, dj, dist in tg.D8:
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny:
                    ex = h[j][i] - h[b][a] - tan_t * dist * dx
                    if ex > 0.0:
                        excess.append((a, b, ex))
            if not excess:
                continue
            total = sum(ex for _, _, ex in excess)
            move = min(rate * max(ex for _, _, ex in excess) / 2.0, layers[name][j][i])
            if move <= 0.0:
                continue
            moved = True
            delta[j][i] -= move
            for a, b, ex in excess:
                delta[b][a] += move * ex / total
    if not moved:
        return layers
    out = dict(layers)
    out[name] = [[layers[name][j][i] + delta[j][i] for i in range(nx)] for j in range(ny)]
    return out


# ------------------------------------------------------------------------------------------------ hydraulic

DIRECTIONS = ((-1, 0), (1, 0), (0, -1), (0, 1))          # left, right, top, bottom; opposite of k is k ^ 1


def initial_state(layers):
    """The hydraulic state: the layers (a float `flow` layer becomes pairs) and zero pipe fluxes."""
    layers = dict(layers)
    ny, nx = len(layers["bedrock"]), len(layers["bedrock"][0])
    if "flow" in layers:
        layers["flow"] = [[v if isinstance(v, tuple) else (0.0, 0.0) for v in row] for row in layers["flow"]]
    return {"layers": layers, "flux": [[[0.0, 0.0, 0.0, 0.0] for _ in range(nx)] for _ in range(ny)]}


def rain_depth(spec, e, purpose, step, i, j):
    """The rain of one step on cell (i, j): rain dt (1 + rainVariation (2 S(e, purpose, step, pack(i, j, 0)) - 1))."""
    rs = streams()
    rain = _get(spec, "rain", HYDRAULIC_DEFAULTS) * _get(spec, "step", HYDRAULIC_DEFAULTS)
    rv = _get(spec, "rainVariation", HYDRAULIC_DEFAULTS)
    if rv == 0.0:
        return rain
    return rain * (1.0 + rv * (2.0 * rs.S(e, purpose, step, rs.pack(i, j, 0)) - 1.0))


def capacity(spec, tilt, speed):
    """The sediment capacity C = capacity max(sin tilt, minTilt) |v| (Mei et al. 2007, equation 10)."""
    return (_get(spec, "capacity", HYDRAULIC_DEFAULTS) * max(math.sin(tilt), _get(spec, "minTilt", HYDRAULIC_DEFAULTS))
            * speed)


def depth_factor(spec, depth):
    """Stava et al. 2008's shallow-water limiter l_max: zero without water, rising linearly to one at maxDepth, so
    the capacity of a film of water vanishes with its depth instead of growing with its pipe velocity."""
    return min(1.0, max(0.0, depth / _get(spec, "maxDepth", HYDRAULIC_DEFAULTS)))


def torricelli(depth, head, dx):
    """The discharge bound of a pipe: the cell's water column, dx wide, leaving at the free-fall speed of the
    head, sqrt(2 g head); zero when the head is not positive."""
    return depth * dx * math.sqrt(2.0 * GRAVITY * head) if head > 0.0 and depth > 0.0 else 0.0


def erode_cell(cell, amount, spec):
    """Remove up to `amount` of ground from a cell's column: the loose layer first, then the bedrock scaled by
    1 - hardness; returns the new layer values."""
    out = dict(cell)
    take = min(amount, max(cell.get("loose", 0.0), 0.0))
    out["loose"] = cell.get("loose", 0.0) - take
    remaining = amount - take
    if remaining > 0.0 and "bedrock" in cell:
        out["bedrock"] = cell["bedrock"] - remaining * (1.0 - cell.get("hardness", 0.0))
    return out


def hydraulic_step(state, spec, dx, e, purpose, step):
    """One virtual-pipes step (Mei, Decaudin and Hsu 2007): rain, pipe fluxes with the outflow scaling, the water
    update, the velocity, erosion and deposition against the capacity, the sediment carried by the fluxes, and
    the evaporation."""
    layers = state["layers"]
    for need in ("loose", "water", "sediment"):
        if need not in layers:
            raise ErosionError(f"ER5: the hydraulic process needs a {need!r} layer")
    tg = terrain()
    dt = _get(spec, "step", HYDRAULIC_DEFAULTS)
    area = _get(spec, "pipeArea", HYDRAULIC_DEFAULTS)
    closed = _get(spec, "boundary", HYDRAULIC_DEFAULTS) == "closed"
    ground = tg.surface(layers)
    ny, nx = len(ground), len(ground[0])
    water = layers["water"]
    cell_area = dx * dx

    # 1. rain
    d1 = [[water[j][i] + rain_depth(spec, e, purpose, step, i, j) for i in range(nx)] for j in range(ny)]

    # 2. fluxes
    flux = [[list(state["flux"][j][i]) for i in range(nx)] for j in range(ny)]
    for j in range(ny):
        for i in range(nx):
            total = 0.0
            for k, (di, dj) in enumerate(DIRECTIONS):
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny:
                    dh = ground[j][i] + d1[j][i] - ground[b][a] - d1[b][a]
                elif closed:
                    flux[j][i][k] = 0.0
                    continue
                else:
                    dh = d1[j][i]                              # the outside: the same ground, no water
                f = max(0.0, flux[j][i][k] + dt * area * GRAVITY * dh / dx)
                flux[j][i][k] = min(f, torricelli(d1[j][i], dh, dx))
                total += flux[j][i][k]
            if total > 0.0:
                scale = min(1.0, d1[j][i] * cell_area / (total * dt))
                flux[j][i] = [f * scale for f in flux[j][i]]

    # 3. water volume
    d2 = [[0.0] * nx for _ in range(ny)]
    for j in range(ny):
        for i in range(nx):
            inflow = 0.0
            for k, (di, dj) in enumerate(DIRECTIONS):
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny:
                    inflow += flux[b][a][k ^ 1]
            d2[j][i] = d1[j][i] + dt * (inflow - sum(flux[j][i])) / cell_area

    # 4. velocity
    def fl(i, j, k):
        return flux[j][i][k] if 0 <= i < nx and 0 <= j < ny else 0.0
    velocity = [[(0.0, 0.0)] * nx for _ in range(ny)]
    for j in range(ny):
        for i in range(nx):
            dbar = 0.5 * (d1[j][i] + d2[j][i])
            if dbar < EPSILON_DEPTH:
                continue
            wx = 0.5 * (fl(i - 1, j, 1) - flux[j][i][0] + flux[j][i][1] - fl(i + 1, j, 0))
            wy = 0.5 * (fl(i, j - 1, 3) - flux[j][i][2] + flux[j][i][3] - fl(i, j + 1, 2))
            velocity[j][i] = (wx / (dx * dbar), wy / (dx * dbar))

    # 5. erosion and deposition
    gx, gy = tg.gradient(ground, dx)
    sediment = _copy(layers["sediment"])
    loose = _copy(layers["loose"])
    bedrock = _copy(layers["bedrock"]) if "bedrock" in layers else None
    hardness = layers.get("hardness")
    ks = _get(spec, "erodeRate", HYDRAULIC_DEFAULTS)
    kd = _get(spec, "depositRate", HYDRAULIC_DEFAULTS)
    for j in range(ny):
        for i in range(nx):
            g = math.hypot(gx[j][i], gy[j][i])
            tilt = math.atan(g)
            c = capacity(spec, tilt, math.hypot(*velocity[j][i])) * depth_factor(spec, 0.5 * (d1[j][i] + d2[j][i]))
            s = sediment[j][i]
            if s < c:
                cell = {"loose": loose[j][i]}
                if bedrock is not None:
                    cell["bedrock"] = bedrock[j][i]
                if hardness is not None:
                    cell["hardness"] = hardness[j][i]
                new = erode_cell(cell, ks * (c - s), spec)
                removed = (cell["loose"] - new["loose"]) + (cell.get("bedrock", 0.0) - new.get("bedrock", 0.0))
                loose[j][i] = new["loose"]
                if bedrock is not None:
                    bedrock[j][i] = new["bedrock"]
                sediment[j][i] = s + removed
            else:
                drop = kd * (s - c)
                loose[j][i] += drop
                sediment[j][i] = s - drop

    # 6. sediment carried by the fluxes
    carried = _copy(sediment)
    for j in range(ny):
        for i in range(nx):
            if d1[j][i] <= 0.0 or sediment[j][i] <= 0.0:
                continue
            volume = d1[j][i] * cell_area
            for k, (di, dj) in enumerate(DIRECTIONS):
                part = sediment[j][i] * flux[j][i][k] * dt / volume
                if part <= 0.0:
                    continue
                carried[j][i] -= part
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny:
                    carried[b][a] += part

    # 7. evaporation
    ke = _get(spec, "evaporation", HYDRAULIC_DEFAULTS)
    d3 = [[max(0.0, d2[j][i] * (1.0 - ke * dt)) for i in range(nx)] for j in range(ny)]

    out = dict(layers)
    out["water"] = d3
    out["sediment"] = [[max(0.0, v) for v in row] for row in carried]
    out["loose"] = loose
    if bedrock is not None:
        out["bedrock"] = bedrock
    if "flow" in layers:
        out["flow"] = [[(velocity[j][i][0] * 0.5 * (d1[j][i] + d2[j][i]), velocity[j][i][1] * 0.5 * (d1[j][i] + d2[j][i]))
                        for i in range(nx)] for j in range(ny)]
    return {"layers": out, "flux": flux}


def ground_volume(layers, dx):
    """The volume of the solid layers plus the suspended sediment, in m^3."""
    tg = terrain()
    total = 0.0
    for key, rows in layers.items():
        if key.split(":")[0] in tg.SOLID_LAYERS or key == "sediment":
            total += sum(v for row in rows for v in row)
    return total * dx * dx


def water_volume(layers, dx):
    return sum(v for row in layers["water"] for v in row) * dx * dx


# ------------------------------------------------------------------------------------------------------ run


def steps_for(t, step, max_steps):
    """round(t / step) steps, never more than maxSteps."""
    if not step > 0.0:
        raise ErosionError("ER2: step is positive")
    return min(int(round(t / step)), max_steps)


def digest(layers):
    """sha256 of the layers as JSON with sorted keys, pairs as lists and values rounded to three decimals."""
    def cell(v):
        if isinstance(v, tuple):
            return [round(c, DIGEST_DECIMALS) for c in v]
        return round(v, DIGEST_DECIMALS)
    rounded = {k: [[cell(v) for v in row] for row in rows] for k, rows in layers.items()}
    text = json.dumps(rounded, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(doc, t):
    """The terrain's layers at time t: the generated layers, each fluvial child at its geological time, then the
    steps of the thermal and hydraulic children in document order."""
    tg = terrain()
    codes = validate_document(doc)
    if codes:
        raise ErosionError("invalid document: " + ", ".join(codes))
    built = tg.build(doc)
    layers = built["layers"]
    dx = float(doc.get("metersPerCell", 1.0))
    e = tg.element_seed(doc, doc.get("project", 0))
    processes = list(doc.get("processes", ()))
    for spec in processes:
        if spec["kind"] == "fluvial":
            layers = fluvial(layers, spec, dx, geological_time(spec, t))
    stepped = [(k, spec) for k, spec in enumerate(processes) if spec["kind"] in ("thermal", "hydraulic")]
    steps = {}
    state = initial_state(layers) if any(s["kind"] == "hydraulic" for _, s in stepped) else {"layers": layers}
    counts = {}
    for k, spec in stepped:
        d = _defaults(spec["kind"])
        counts[k] = steps_for(t, _get(spec, "step", d), _get(spec, "maxSteps", d))
        steps[spec["kind"]] = counts[k]
    for n in range(max(counts.values(), default=0)):
        for k, spec in stepped:
            if n >= counts[k]:
                continue
            if spec["kind"] == "thermal":
                state = dict(state, layers=thermal_step(state["layers"], spec, dx))
            else:
                state = hydraulic_step(state, spec, dx, e, PURPOSE_BASE + k, n)
    return {"shape": built["shape"], "layers": state["layers"], "steps": steps, "digest": digest(state["layers"])}


# ------------------------------------------------------------------------------------------------ documents


def example_document():
    """The terrain draft's example with sediment and flow layers and three processes."""
    doc = terrain().example_document()
    doc["layers"] += [{"kind": "sediment", "value": 0.0}, {"kind": "flow", "value": 0.0}]
    doc["processes"] = [
        {"kind": "fluvial", "uplift": 1e-3, "erodibility": 2e-5, "m": 0.5, "time": 1e5, "timeScale": 0.0, "layer": "bedrock"},
        {"kind": "thermal", "talus": 35.0, "rate": 0.5, "layer": "loose", "step": 0.02},
        {"kind": "hydraulic", "rain": 0.01, "rainVariation": 0.25, "evaporation": 0.05, "capacity": 0.1,
         "erodeRate": 0.5, "depositRate": 1.0, "pipeArea": 1.0, "minTilt": 0.1, "maxDepth": 0.05, "step": 0.02,
         "boundary": "open", "maxSteps": 100000},
    ]
    return doc


def example_seed():
    doc = example_document()
    return terrain().element_seed(doc, doc["project"])


def bad_document():
    doc = example_document()
    doc["processes"][0]["kind"] = "glacial"
    doc["processes"][1]["talus"] = 0.0
    doc["processes"][2]["rain"] = -1.0
    doc["processes"].append({"kind": "fluvial", "uplift": -1.0})
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "sediment"]
    return doc


def _non_negative(v):
    return _number(v) and v >= 0.0


def _positive(v):
    return _number(v) and v > 0.0


def _unit(v):
    return _number(v) and 0.0 <= v <= 1.0


def _solid_present(name, kinds):
    return name.split(":")[0] in terrain().SOLID_LAYERS and name in kinds


def validate_document(doc):
    """The draft's rules ER1 to ER5 and V17 over a terrain document, as sorted codes."""
    codes = set()
    processes = doc.get("processes", ())
    if not processes:
        return []
    major, minor = (int(x) for x in str(doc.get("version", "1.8")).split(".")[:2])
    if (major, minor) < (1, 8):
        return ["V17"]
    kinds = {terrain()._layer_key(layer) for layer in doc.get("layers", ())}
    stepped_steps = set()
    for spec in processes:
        kind = spec.get("kind")
        if kind not in KINDS:
            codes.add("ER1")
            continue
        g = lambda key: _get(spec, key, _defaults(kind))      # noqa: E731
        if kind == "hydraulic":
            if not (_non_negative(g("rain")) and _unit(g("rainVariation")) and _non_negative(g("evaporation"))
                    and _non_negative(g("capacity")) and _unit(g("erodeRate")) and _unit(g("depositRate"))
                    and _positive(g("pipeArea")) and _unit(g("minTilt")) and _positive(g("maxDepth"))
                    and _positive(g("step"))
                    and g("boundary") in BOUNDARIES
                    and isinstance(g("maxSteps"), int) and not isinstance(g("maxSteps"), bool) and g("maxSteps") > 0):
                codes.add("ER2")
            if not all(k in kinds for k in ("loose", "water", "sediment")):
                codes.add("ER5")
            if _positive(g("step")):
                stepped_steps.add(g("step"))
        elif kind == "thermal":
            if not (_number(g("talus")) and 0.0 < g("talus") < 90.0 and _unit(g("rate")) and _positive(g("step"))
                    and _solid_present(g("layer"), kinds)):
                codes.add("ER3")
            if _positive(g("step")):
                stepped_steps.add(g("step"))
        else:
            if not (_non_negative(g("uplift")) and _positive(g("erodibility")) and _unit(g("m"))
                    and _non_negative(g("time")) and _non_negative(g("timeScale")) and _solid_present(g("layer"), kinds)):
                codes.add("ER4")
    if len(stepped_steps) > 1:
        codes.add("ER5")
    return sorted(codes)


# ----------------------------------------------------------------------------------------------- numeric table

TABLE = (
    ("element seed", "example_seed()", "1572054040"),
    ("receiver on the plane", "routing(PLANE, 10.0)['receiver'][(3, 1)]", "(2, 1)"),
    ("drainage area", "routing(PLANE, 10.0)['area'][1][0]", "800.0"),
    ("travel time", "travel_time(routing(PLANE, 10.0), 2e-5, 0.5)[(5, 1)]", "115538.83140813369"),
    ("closed form at T = 0", "fluvial_surface(PLANE, ROUTE, TAU, 1e-3, 0.0)[1][5]", "2.5"),
    ("closed form at T = 2e5 years", "fluvial_surface(PLANE, ROUTE, TAU, 1e-3, 2e5)[1][5]", "115.53883140813369"),
    ("steady profile", "fluvial_surface(PLANE, ROUTE, TAU, 1e-3, 1e12)[1][5]", "115.53883140813369"),
    ("steady slope times A^m", "(STEADY[1][5] - STEADY[1][4]) / 10.0 * ROUTE['area'][1][5] ** 0.5", "50.0"),
    ("geological time", "geological_time(dict(FLUVIAL_DEFAULTS, time=1e5, timeScale=10.0), 2.5)", "100025.0"),
    ("fluvial on the example", "fluvial(BUILT, DOC['processes'][0], 50.0, 1e5)['bedrock'][6][8]", "1099.7782270078244"),
    ("thermal, slope before", "max_neighbour_slope(terrain().surface(PIT), 1.0)", "89.42706130231652"),
    ("thermal, slope after 600 steps", "max_neighbour_slope(terrain().surface(RELAXED), 1.0)", "35.00000000000612"),
    ("thermal, mass", "ground_volume(RELAXED, 1.0) - ground_volume(PIT, 1.0)", "3.637978807091713e-12"),
    ("rain depth", "rain_depth(dict(HYDRAULIC_DEFAULTS, rainVariation=0.5), E, 1, 3, 2, 4)", "0.00025160583800450223"),
    ("capacity", "capacity(dict(HYDRAULIC_DEFAULTS, capacity=2.0), math.radians(30.0), 2.0)", "1.9999999999999998"),
    ("depth factor", "depth_factor(HYDRAULIC_DEFAULTS, 0.02)", "0.39999999999999997"),
    ("Torricelli bound", "torricelli(0.01, 4.0, 1.0)", "0.08858893836140042"),
    ("erode a column", "erode_cell({'loose': 0.3, 'bedrock': 10.0, 'hardness': 0.5}, 0.5, HYDRAULIC_DEFAULTS)", "{'loose': 0.0, 'bedrock': 9.9, 'hardness': 0.5}"),
    ("hydraulic, water after 60 steps", "water_volume(WET['layers'], 1.0)", "0.4320000000000001"),
    ("hydraulic, water at the bottom", "WET['layers']['water'][2][2]", "0.08610198290165076"),
    ("hydraulic, sediment", "sum(v for row in WET['layers']['sediment'] for v in row)", "0.8617920054771845"),
    ("hydraulic, ground", "ground_volume(WET['layers'], 1.0) - ground_volume(BOWL['layers'], 1.0)", "0.0"),
    ("hydraulic, flow", "WET['layers']['flow'][2][1]", "(0.027173322259948982, 0.006900854953478987)"),
    ("steps", "steps_for(0.5, 0.02, 100000)", "25"),
    ("run, steps", "RUN['steps']", "{'thermal': 25, 'hydraulic': 25}"),
    ("run, water", "RUN['layers']['water'][6][8]", "0.004097350689363983"),
    ("run, digest", "RUN['digest']", "'7f1e4c69c84f5f9cc09964050e836aae050e18f9edf56e537d1780e367fe8760'"),
    ("bad document", "validate_document(bad_document())", "['ER1', 'ER2', 'ER3', 'ER4', 'ER5']"),
)


def _bowl_state():
    tg = terrain()
    n = 6
    return initial_state({"bedrock": tg.bowl(n), "loose": tg.flat(n, n, 0.5), "water": tg.flat(n, n, 0.0),
                          "sediment": tg.flat(n, n, 0.0), "flow": [[(0.0, 0.0)] * n for _ in range(n)]})


def scope():
    """The names the table's expressions use."""
    tg = terrain()
    s = dict(globals())
    s["E"] = example_seed()
    s["DOC"] = example_document()
    s["BUILT"] = tg.build(s["DOC"])["layers"]
    s["PLANE"] = tg.plane(8, 3, 0.05, 0.0, dx=10.0)
    s["ROUTE"] = routing(s["PLANE"], 10.0)
    s["TAU"] = travel_time(s["ROUTE"], 2e-5, 0.5)
    s["STEADY"] = fluvial_surface(s["PLANE"], s["ROUTE"], s["TAU"], 1e-3, 1e12)
    pit = {"bedrock": [[100.0 * v for v in row] for row in tg.pit(9)]}
    s["PIT"] = pit
    relaxed = pit
    thermal = dict(THERMAL_DEFAULTS, layer="bedrock")
    for _ in range(600):
        relaxed = thermal_step(relaxed, thermal, 1.0)
    s["RELAXED"] = relaxed
    s["BOWL"] = _bowl_state()
    wet = s["BOWL"]
    hydraulic = dict(HYDRAULIC_DEFAULTS, evaporation=0.0, boundary="closed")
    for step in range(60):
        wet = hydraulic_step(wet, hydraulic, 1.0, s["E"], 1, step)
    s["WET"] = wet
    s["RUN"] = run(s["DOC"], 0.5)
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
