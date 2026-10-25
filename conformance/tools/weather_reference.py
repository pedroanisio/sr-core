"""Reference for the draft SREP "Add a weather state" (A5 of SREP 12).

A `weather` element of `physics` holds one animatable state — temperature, humidity, precipitation, cloudiness,
visibility, lightning rate — and a wind. Elements that name it are driven by it instead of their own attributes:
cloud layers (coverage, precipitation), the terrain's snowpack (snowfall, temperature), its shallow water and
hydraulic erosion (rain), rain and snow emitters (their rate from the drop and flake fluxes), media (extinction
from the visibility) and materials (wetness and snow cover). The precipitation splits into rain and snow by the
temperature (Auer 1974); the drop spectrum is Marshall and Palmer's with the Atlas–Srivastava–Sekhon fall speed,
the flake spectrum Gunn and Marshall's; the extinction is Koschmieder's 3.912 / visibility; wetness and snow depth
on surfaces follow a stepped recurrence from the scene's start (SREP 14); wet albedo is the water-film formula
after Lekner and Dorf 1988; lightning strikes are a Poisson process by the time-change of the integrated rate with
draws from the random streams, each bolt a dielectric-breakdown channel (Niemeyer et al. 1984; Kim and Lin 2004)
grown with the fast potentials of Kim et al. 2007.

Units: kelvin, mm/h of water for rates, metres, seconds. `python weather_reference.py` prints the numeric table
of the draft's conformance section.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PURPOSE = "weather"            # E(project, id, seed, "weather")
STRIKE_PURPOSE = 1             # S(e, 1, k, 0) the k-th gap, S(e, 1, k, 1) the k-th position
GROWTH_PURPOSE = 2             # S(e, 2, k, n) the n-th growth draw of bolt k
FREEZING = 273.15
KOSCHMIEDER = 3.912            # ln(1 / 0.02): the contrast threshold of the visibility
WATER_IOR = 1.333
WATER_ROUGHNESS = 0.05
SNOW_ALBEDO = 0.85
SNOW_ROUGHNESS = 0.7
FRESH_SNOW_DENSITY = 0.1       # water equivalent of fresh snow
REFERENCE_RAIN = 10.0          # mm/h: the rain that wets a surface in wetTime
SNOWFLAKE_SPEED = 1.0          # m/s (Langleben 1954: about a metre per second)
MARSHALL_PALMER_N0 = 8000.0    # m^-3 mm^-1
DROP_MAX = 7.0                 # mm: the spectra are integrated from 0 to this diameter
DROP_STEP = 0.01               # mm
SPHERE_RADIUS = 0.5            # cells: the grounded-sphere radius of the fast potential
BRANCH_DIM = 0.3               # brightness factor per branch generation
DIGEST_DECIMALS = 6
DEFAULTS = {
    "wind": None, "temperature": 288.15, "humidity": 0.5, "precipitation": 0.0, "cloudiness": 0.5,
    "visibility": 20000.0, "lightning": 0.0, "rainMax": 50.0, "wetTime": 300.0, "dryTime": 1800.0,
    "snowScale": 0.02, "meltRate": 1e-7, "step": 1.0, "maxSteps": 100000, "seed": None,
    "lightningGrid": 32, "lightningEta": 2.0, "maxStrikes": 1000, "flashDuration": 0.2,
}
DRIVEN = {
    "cloudLayer": ("coverage", "precipitation"), "snowpack": ("snowfall", "temperature"),
    "shallowWater": ("rain",), "erode": ("rain",), "emitter": ("rate",), "medium": ("extinction",), "material": (),
}
ANIMATED = ("temperature", "humidity", "precipitation", "cloudiness", "visibility", "lightning")


class WeatherError(ValueError):
    """A weather or input outside the draft's rules."""


# ------------------------------------------------------------------------------------------------ the references

_streams = None


def streams():
    """The random-streams reference (E, S, pack), loaded by path."""
    global _streams
    if _streams is None:
        path = os.path.join(HERE, "random_streams_reference.py")
        spec = importlib.util.spec_from_file_location("random_streams_reference", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _streams = mod
    return _streams


def value(spec, key, t):
    """An attribute at time t: a number, or an animated value given as a function of time."""
    v = spec.get(key, DEFAULTS[key])
    if v is None:
        v = DEFAULTS[key]
    return v(t) if callable(v) else v


def _get(spec, key):
    return spec[key] if key in spec and spec[key] is not None else DEFAULTS[key]


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def element_seed(project, weather_id, seed):
    return streams().E(project, weather_id, seed, PURPOSE)


# ------------------------------------------------------------------------------------------------ precipitation


def snow_fraction(temperature):
    """1 at or under 274.15 K, 0 at or over 277.15 K, linear between: half at 2.5 degrees (Auer 1974)."""
    return min(1.0, max(0.0, (277.15 - temperature) / 3.0))


def rain_rate(spec, t):
    """rainMax * precipitation(t), mm/h of water."""
    return _get(spec, "rainMax") * value(spec, "precipitation", t)


def split_rate(spec, t):
    """(rain, snow) in mm/h of water by the snow fraction of the temperature at t."""
    r = rain_rate(spec, t)
    f = snow_fraction(value(spec, "temperature", t))
    return (r * (1.0 - f), r * f)


def marshall_palmer(rate):
    """(N0, lambda): N0 = 8000 m^-3 mm^-1, lambda = 4.1 R^-0.21 mm^-1 (Marshall and Palmer 1948)."""
    return (MARSHALL_PALMER_N0, 4.1 * rate ** -0.21)


def drop_density(rate, diameter):
    """N(D) = N0 exp(-lambda D) drops per cubic metre per millimetre of diameter."""
    n0, lam = marshall_palmer(rate)
    return n0 * math.exp(-lam * diameter)


def rain_speed(diameter):
    """The fall speed 9.65 - 10.3 exp(-0.6 D) m/s, D in mm, floored at 0 (Atlas, Srivastava and Sekhon 1973)."""
    return max(0.0, 9.65 - 10.3 * math.exp(-0.6 * diameter))


def _integrate(f, lo, hi, step):
    n = int(round((hi - lo) / step))
    h = (hi - lo) / n
    total = 0.5 * (f(lo) + f(hi))
    for k in range(1, n):
        total += f(lo + k * h)
    return total * h


def drop_flux(rate):
    """Drops crossing a square metre per second: the integral of N(D) v(D) dD."""
    if rate <= 0.0:
        return 0.0
    return _integrate(lambda d: drop_density(rate, d) * rain_speed(d), 0.0, DROP_MAX, DROP_STEP)


def implied_rain_rate(rate):
    """The rain rate the spectrum carries, mm/h: 3.6e6 * pi/6 * the integral of D^3 N(D) v(D) dD in SI."""
    if rate <= 0.0:
        return 0.0
    volume = _integrate(lambda d: math.pi / 6.0 * (d * 1e-3) ** 3 * drop_density(rate, d) * rain_speed(d),
                        0.0, DROP_MAX, DROP_STEP)                                 # m^3 per m^2 per s
    return volume * 3.6e6


def gunn_marshall(rate):
    """(N0, lambda) of the flake spectrum in melted diameters: N0 = 3800 R^-0.87, lambda = 2.55 R^-0.48
    (Gunn and Marshall 1958)."""
    return (3800.0 * rate ** -0.87, 2.55 * rate ** -0.48)


def flake_flux(rate):
    """Flakes crossing a square metre per second at the flake speed."""
    if rate <= 0.0:
        return 0.0
    n0, lam = gunn_marshall(rate)
    return _integrate(lambda d: n0 * math.exp(-lam * d) * SNOWFLAKE_SPEED, 0.0, DROP_MAX, DROP_STEP)


def implied_snow_rate(rate):
    """The water-equivalent rate the flake spectrum carries at the flake speed, mm/h."""
    if rate <= 0.0:
        return 0.0
    n0, lam = gunn_marshall(rate)
    volume = _integrate(lambda d: math.pi / 6.0 * (d * 1e-3) ** 3 * n0 * math.exp(-lam * d) * SNOWFLAKE_SPEED,
                        0.0, DROP_MAX, DROP_STEP)
    return volume * 3.6e6


def particle_fluxes(spec, t):
    """{"rain": drops per m^2 per s, "snow": flakes per m^2 per s} at t."""
    rain, snow = split_rate(spec, t)
    return {"rain": drop_flux(rain), "snow": flake_flux(snow)}


def extinction(visibility):
    """Koschmieder: 3.912 / visibility per metre."""
    if not visibility > 0.0:
        raise WeatherError("WX1: visibility is positive")
    return KOSCHMIEDER / visibility


def extinction_at(spec, t):
    return extinction(value(spec, "visibility", t))


# ------------------------------------------------------------------------------------------------------ surfaces


def _fresnel(cos_i, n):
    """Unpolarised Fresnel reflectance from air into a medium of index n."""
    sin_t2 = (1.0 - cos_i * cos_i) / (n * n)
    if sin_t2 >= 1.0:
        return 1.0
    cos_t = math.sqrt(1.0 - sin_t2)
    rs = (cos_i - n * cos_t) / (cos_i + n * cos_t)
    rp = (n * cos_i - cos_t) / (n * cos_i + cos_t)
    return 0.5 * (rs * rs + rp * rp)


def diffuse_fresnel(n, samples=2000):
    """The hemispherical reflectance of diffuse light at an air-medium interface: the integral of F(theta)
    2 sin(theta) cos(theta) d theta."""
    return _integrate(lambda th: _fresnel(math.cos(th), n) * 2.0 * math.sin(th) * math.cos(th),
                      0.0, math.pi / 2.0, math.pi / 2.0 / samples)


def internal_reflectance(n):
    """The diffuse reflectance from inside the film: 1 - (1 - R_e) / n^2."""
    return 1.0 - (1.0 - diffuse_fresnel(n)) / (n * n)


_FILM = {}


def _film():
    if not _FILM:
        _FILM["re"] = diffuse_fresnel(WATER_IOR)
        _FILM["ri"] = internal_reflectance(WATER_IOR)
    return _FILM["re"], _FILM["ri"]


def wet_albedo(albedo, wetness, metallic=0.0):
    """lerp(a, a_film, wetness (1 - metallic)) per channel, a_film = (1 - R_e)(1 - r_i) a / (1 - a r_i): the
    water film's geometric series of internal reflections (after Lekner and Dorf 1988)."""
    if isinstance(albedo, (tuple, list)):
        return tuple(wet_albedo(a, wetness, metallic) for a in albedo)
    re_, ri = _film()
    film = (1.0 - re_) * (1.0 - ri) * albedo / (1.0 - albedo * ri)
    w = wetness * (1.0 - metallic)
    return albedo + (film - albedo) * w


def wet_roughness(roughness, wetness):
    """lerp(r, min(r, WATER_ROUGHNESS), wetness): the film is smooth, and never rougher than the surface."""
    return roughness + (min(roughness, WATER_ROUGHNESS) - roughness) * wetness


def snow_cover(depth, spec):
    """1 - exp(-depth / snowScale)."""
    return 1.0 - math.exp(-depth / _get(spec, "snowScale"))


def _upward(up):
    return max(0.0, min(1.0, up))


def snowy_albedo(albedo, cover, up):
    """lerp(a, SNOW_ALBEDO, cover * max(0, up)) per channel; up is the surface normal's upward component."""
    if isinstance(albedo, (tuple, list)):
        return tuple(snowy_albedo(a, cover, up) for a in albedo)
    k = cover * _upward(up)
    return albedo + (SNOW_ALBEDO - albedo) * k


def snowy_roughness(roughness, cover, up):
    k = cover * _upward(up)
    return roughness + (SNOW_ROUGHNESS - roughness) * k


def surface_look(material, state, up):
    """The material's baseColor and roughness under the surface state: wet first, then the snow on top."""
    metallic = material.get("metallic", 0.0)
    color = wet_albedo(material["baseColor"], state["wetness"], metallic)
    rough = wet_roughness(material["roughness"], state["wetness"])
    color = snowy_albedo(color, state["snow"], up)
    rough = snowy_roughness(rough, state["snow"], up)
    return {"baseColor": color, "roughness": rough, "metallic": metallic}


def steps_for(t, step, max_steps):
    """round(t / step) steps, never more than maxSteps."""
    if not step > 0.0:
        raise WeatherError("WX1: step is positive")
    return min(int(round(t / step)), max_steps)


def surface_state(spec, t):
    """{"wetness", "snow", "steps"}: wetness w and snow depth d (metres of snow) after round(t / step) steps from
    zero: w += dt (rain / REFERENCE_RAIN / wetTime (1 - w) - (1 - humidity) / dryTime w), clipped to [0, 1];
    d += dt (snow / 3.6e6 / FRESH_SNOW_DENSITY - meltRate max(0, T - 273.15)), clipped at 0."""
    dt = _get(spec, "step")
    steps = steps_for(t, dt, _get(spec, "maxSteps"))
    wet_time, dry_time, melt = _get(spec, "wetTime"), _get(spec, "dryTime"), _get(spec, "meltRate")
    w = d = 0.0
    for n in range(steps):
        tau = n * dt
        rain, snow = split_rate(spec, tau)
        humidity = value(spec, "humidity", tau)
        temperature = value(spec, "temperature", tau)
        w += dt * (rain / REFERENCE_RAIN / wet_time * (1.0 - w) - (1.0 - humidity) / dry_time * w)
        w = min(1.0, max(0.0, w))
        d += dt * (snow / 3.6e6 / FRESH_SNOW_DENSITY - melt * max(0.0, temperature - FREEZING))
        d = max(0.0, d)
    return {"wetness": w, "snow": d, "steps": steps}


# ------------------------------------------------------------------------------------------------- lightning


def strikes(spec, e, t):
    """The strikes up to t: the k-th (k from 1) falls where the integrated rate L(tau) = integral of lightning
    first reaches the sum of the unit-exponential gaps -ln(1 - S(e, 1, i, 0)), i <= k (the time-change of a
    Poisson process), L accumulated by the trapezoid over the steps and the crossing placed linearly inside the
    step; its position across the sky is S(e, 1, k, 1). Never more than maxStrikes."""
    rs = streams()
    dt = _get(spec, "step")
    steps = steps_for(t, dt, _get(spec, "maxSteps"))
    max_strikes = _get(spec, "maxStrikes")
    out = []
    k = 1
    threshold = -math.log(1.0 - rs.S(e, STRIKE_PURPOSE, k, 0))
    integral = 0.0
    rate_prev = value(spec, "lightning", 0.0)
    for n in range(1, steps + 1):
        tau = n * dt
        rate = value(spec, "lightning", tau)
        gained = 0.5 * (rate_prev + rate) * dt
        while gained > 0.0 and integral + gained >= threshold and len(out) < max_strikes:
            frac = (threshold - integral) / gained
            time = tau - dt + frac * dt
            if time > t:
                return out
            out.append({"time": time, "x": rs.S(e, STRIKE_PURPOSE, k, 1)})
            k += 1
            threshold += -math.log(1.0 - rs.S(e, STRIKE_PURPOSE, k, 0))
        integral += gained
        rate_prev = rate
        if len(out) >= max_strikes:
            break
    return [h for h in out if h["time"] <= t]


def max_growth(n):
    """The most cells a bolt may grow on an n x n grid."""
    return 4 * n * n


def potential(p, channel, ground, attraction):
    """phi(p) = mean over the channel of (1 - R / max(R, |p - c|)) + attraction * mean over the ground of
    R / max(R, |p - g|): the channel's grounded spheres (0 on them, 1 far away) and the ground row's pull
    (Kim et al. 2007), the distances floored at the sphere radius."""
    r = SPHERE_RADIUS
    phi_c = sum(1.0 - r / max(r, math.hypot(p[0] - c[0], p[1] - c[1])) for c in channel) / len(channel)
    phi_g = sum(r / max(r, math.hypot(p[0] - g[0], p[1] - g[1])) for g in ground) / len(ground)
    return phi_c + attraction * phi_g


def growth_weights(candidates, channel, ground, attraction, eta):
    """(phi - min phi)^eta over the candidates, normalised; uniform when every potential is the minimum."""
    phis = [potential(p, channel, ground, attraction) for p in candidates]
    lo = min(phis)
    weights = [(phi - lo) ** eta for phi in phis]
    total = sum(weights)
    if total <= 0.0:
        return [1.0 / len(candidates)] * len(candidates)
    return [w / total for w in weights]


def pick(weights, u):
    """The index whose cumulative weight first exceeds u."""
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if u < acc:
            return i
    return len(weights) - 1


_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def bolt(e, k, x, spec):
    """Bolt k from the top cell nearest x (0 to 1 across) to the ground row of the lightningGrid: dielectric
    breakdown with exponent lightningEta, the growth site of step n drawn with S(e, 2, k, n). {"cells", "parent",
    "hit", "main", "brightness"}."""
    rs = streams()
    n = _get(spec, "lightningGrid")
    eta = _get(spec, "lightningEta")
    start = (int(round(x * (n - 1))), 0)
    ground = [(i, n - 1) for i in range(n)]
    cells = [start]
    in_channel = {start}
    parent = {}
    hit = None
    step = 0
    limit = max_growth(n)
    while hit is None and len(cells) < limit:
        candidates = []
        seen = set()
        for c in cells:
            for di, dj in _NEIGHBOURS:
                p = (c[0] + di, c[1] + dj)
                if 0 <= p[0] < n and 0 <= p[1] < n and p not in in_channel and p not in seen:
                    seen.add(p)
                    candidates.append((p, c))
        weights = growth_weights([p for p, _ in candidates], cells, ground, 1.0, eta)
        chosen, from_cell = candidates[pick(weights, rs.S(e, GROWTH_PURPOSE, k, step))]
        cells.append(chosen)
        in_channel.add(chosen)
        parent[chosen] = from_cell
        if chosen[1] == n - 1:
            hit = chosen
        step += 1
    if hit is None:
        raise WeatherError(f"bolt {k} did not reach the ground within {limit} cells")
    main = [hit]
    while main[-1] != start:
        main.append(parent[main[-1]])
    main.reverse()
    on_main = set(main)
    brightness = {}
    for c in cells:
        if c in on_main:
            brightness[c] = 1.0
            continue
        generations = 0
        q = c
        while q not in on_main:
            p = parent[q]
            if p in on_main or _branch_root(p, parent, on_main) != _branch_root(q, parent, on_main):
                generations += 1
            q = p
        brightness[c] = BRANCH_DIM ** max(1, generations)
    return {"cells": cells, "parent": parent, "hit": hit, "main": main, "brightness": brightness}


def _branch_root(c, parent, on_main):
    """The first cell off the main channel on c's way to it."""
    q = c
    while parent[q] not in on_main:
        q = parent[q]
    return q


def flash(spec, t, hits):
    """The sum over the strikes at or before t of exp(-(t - t_k) / flashDuration)."""
    tau = _get(spec, "flashDuration")
    return sum(math.exp(-(t - h["time"]) / tau) for h in hits if h["time"] <= t)


# ------------------------------------------------------------------------------------------------- the element


def _find(doc, weather_id):
    for spec in doc.get("physics", {}).get("weathers", ()):
        if spec.get("id") == weather_id:
            return spec
    raise WeatherError(f"no weather {weather_id!r}")


def _project_seed(doc):
    project = doc.get("project", 0)
    return project.get("seed", 0) if isinstance(project, dict) else project


def state(doc, weather_id, t):
    """Everything the readers of a weather take from it at t."""
    spec = _find(doc, weather_id)
    e = element_seed(_project_seed(doc), weather_id, spec.get("seed", DEFAULTS["seed"]))
    rain, snow = split_rate(spec, t)
    hits = strikes(spec, e, t)
    out = {
        "wind": _get(spec, "wind"),
        "cloud": {"coverage": value(spec, "cloudiness", t), "precipitation": value(spec, "precipitation", t)},
        "terrain": {"rain": rain / 3.6e6, "snowfall": snow / 3.6e6 / FRESH_SNOW_DENSITY,
                    "temperature": value(spec, "temperature", t)},
        "medium": {"extinction": extinction_at(spec, t)},
        "particles": particle_fluxes(spec, t),
        "surface": surface_state(spec, t),
        "strikes": hits,
        "flash": flash(spec, t, hits),
    }
    out["digest"] = digest(out)
    return out


def digest(state_):
    """sha256 of the state as JSON with sorted keys and floats rounded to six decimals."""
    def rnd(v):
        if isinstance(v, float):
            return round(v, DIGEST_DECIMALS)
        if isinstance(v, dict):
            return {k: rnd(x) for k, x in v.items() if k != "digest"}
        if isinstance(v, (list, tuple)):
            return [rnd(x) for x in v]
        return v
    text = json.dumps(rnd(state_), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -------------------------------------------------------------------------------------------------- documents


def example_weather():
    """A cold front: 3 degrees above freezing, humid, rain rising after ten minutes, overcast, a kilometre of
    visibility, a strike every ten seconds once the rain is up; seed 11."""
    return {
        "id": "wx", "wind": "w1",
        "temperature": lambda t: 276.15 - 2.0 * min(1.0, t / 1800.0),
        "humidity": 0.85,
        "precipitation": lambda t: 0.0 if t < 600.0 else 0.4,
        "cloudiness": lambda t: 0.6 + 0.4 * min(1.0, t / 600.0),
        "visibility": 1000.0,
        "lightning": lambda t: 0.0 if t < 600.0 else 0.1,
        "rainMax": 50.0, "wetTime": 300.0, "dryTime": 1800.0, "snowScale": 0.02, "meltRate": 1e-7,
        "step": 1.0, "maxSteps": 100000, "seed": 11, "lightningGrid": 32, "lightningEta": 2.0,
        "maxStrikes": 1000, "flashDuration": 0.2,
    }


def example_document():
    return {
        "version": "1.8",
        "project": {"seed": 7},
        "physics": {"winds": [{"id": "w1", "speed": 6.0, "direction": 30.0, "seed": 3}],
                    "weathers": [example_weather()]},
        "readers": [
            {"element": "cloudLayer", "id": "c1", "weather": "wx"},
            {"element": "snowpack", "id": "ground", "weather": "wx"},
            {"element": "shallowWater", "id": "ground", "weather": "wx"},
            {"element": "emitter", "id": "rain", "preset": "rain", "weather": "wx"},
            {"element": "medium", "id": "fog", "weather": "wx"},
            {"element": "material", "id": "road", "weather": "wx"},
        ],
    }


def example_seed():
    return element_seed(7, "wx", 11)


def bad_document():
    doc = example_document()
    doc["physics"]["weathers"][0].update(humidity=1.5, wind="w9")
    doc["readers"].append({"element": "cloudLayer", "id": "c9", "weather": "ghost"})
    doc["readers"][0]["coverage"] = 0.3
    return doc


def _non_negative(v):
    return _number(v) and v >= 0.0


def _positive(v):
    return _number(v) and v > 0.0


def _unit(v):
    return _number(v) and 0.0 <= v <= 1.0


def _positive_int(v, lo=1, hi=None):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo and (hi is None or v <= hi)


def _sample(spec, key):
    """Animated attributes are checked at their value at t = 0 (the keyframes' ranges are the schema's)."""
    return value(spec, key, 0.0)


def validate_document(doc):
    """The draft's rules WX1 to WX4 and V17 over a document, as sorted codes."""
    weathers = doc.get("physics", {}).get("weathers", ())
    if not weathers:
        return []
    major, minor = (int(x) for x in str(doc.get("version", "1.8")).split(".")[:2])
    if (major, minor) < (1, 8):
        return ["V17"]
    codes = set()
    ids = set()
    winds = {w.get("id") for w in doc.get("physics", {}).get("winds", ())}
    for spec in weathers:
        ids.add(spec.get("id"))
        g = lambda key: _get(spec, key)      # noqa: E731
        s = lambda key: _sample(spec, key)   # noqa: E731
        if not (_positive(s("temperature")) and _unit(s("humidity")) and _unit(s("precipitation"))
                and _unit(s("cloudiness")) and _positive(s("visibility")) and _non_negative(s("lightning"))
                and _non_negative(g("rainMax")) and _positive(g("wetTime")) and _positive(g("dryTime"))
                and _positive(g("snowScale")) and _non_negative(g("meltRate")) and _positive(g("step"))
                and _positive_int(g("maxSteps")) and _positive_int(g("lightningGrid"), 8, 256)
                and _non_negative(g("lightningEta")) and _positive_int(g("maxStrikes"))
                and _positive(g("flashDuration"))):
            codes.add("WX1")
        if g("wind") is not None and g("wind") not in winds:
            codes.add("WX2")
    for reader in doc.get("readers", ()):
        if "weather" not in reader:
            continue
        if reader["weather"] not in ids:
            codes.add("WX3")
        if any(key in reader for key in DRIVEN.get(reader.get("element"), ())):
            codes.add("WX4")
    return sorted(codes)


# ----------------------------------------------------------------------------------------------- numeric table

TABLE = (
    ("element seed", "example_seed()", "2908410751"),
    ("snow fraction at 2.5 degrees", "snow_fraction(275.65)", "0.5"),
    ("rain rate", "rain_rate(dict(DEFAULTS, precipitation=0.4), 0.0)", "20.0"),
    ("rain and snow at 2.5 degrees", "split_rate(dict(DEFAULTS, precipitation=0.4, temperature=275.65), 0.0)", "(10.0, 10.0)"),
    ("Marshall-Palmer lambda at 5 mm/h", "marshall_palmer(5.0)[1]", "2.924153426923764"),
    ("drops of 1 mm at 5 mm/h", "drop_density(5.0, 1.0)", "429.6811378547337"),
    ("fall speed of a 2 mm drop", "rain_speed(2.0)", "6.547699617304318"),
    ("drop flux at 5 mm/h", "drop_flux(5.0)", "3271.3865248495467"),
    ("the spectrum's own rate at 5 mm/h", "implied_rain_rate(5.0)", "5.900091594466843"),
    ("Gunn-Marshall at 2 mm/h", "gunn_marshall(2.0)", "(2079.158032395405, 1.8282929412201796)"),
    ("flake flux at 2 mm/h", "flake_flux(2.0)", "1137.2412755381818"),
    ("extinction at 1 km", "extinction(1000.0)", "0.003912"),
    ("diffuse Fresnel of water", "diffuse_fresnel(WATER_IOR)", "0.06640565988029733"),
    ("internal reflectance of the film", "internal_reflectance(WATER_IOR)", "0.47459051177664857"),
    ("wet albedo of 0.5", "wet_albedo(0.5, 1.0)", "0.32156567022656957"),
    ("half-wet albedo of 0.5", "wet_albedo(0.5, 0.5)", "0.4107828351132848"),
    ("wet roughness of 0.6", "wet_roughness(0.6, 1.0)", "0.050000000000000044"),
    ("snow cover at the scale", "snow_cover(0.02, DEFAULTS)", "0.6321205588285577"),
    ("snowy albedo, half cover", "snowy_albedo(0.2, 0.5, 1.0)", "0.5249999999999999"),
    ("wetness after 300 s of 10 mm/h", "surface_state(WET, 300.0)['wetness']", "0.6112592930606419"),
    ("snow after an hour at 10 mm/h", "surface_state(COLD, 3600.0)['snow']", "0.10000000000000467"),
    ("strikes in 400 s at 0.5 per s", "len(STRIKES)", "212"),
    ("first strike", "STRIKES[0]", "{'time': 1.6104867814517827, 'x': 0.24929459691110478}"),
    ("bolt cells", "len(BOLT['cells'])", "161"),
    ("bolt hit", "BOLT['hit']", "(16, 23)"),
    ("bolt main channel length", "len(BOLT['main'])", "24"),
    ("bolt digest", "hashlib.sha256(repr(BOLT['cells']).encode()).hexdigest()", "'b5d50d1c9e2d8cafd5ebf54ba693a3be9a5712a6d2f2d39714e65f59014ac3b8'"),
    ("potential near the ground", "potential((5, 9), [(5, 0), (5, 1)], [(i, 11) for i in range(12)], 1.0)", "1.0923452356919794"),
    ("flash", "flash(DEFAULTS, 1.2, [{'time': 1.0, 'x': 0.3}])", "0.3678794411714424"),
    ("state, terrain rain", "STATE['terrain']['rain']", "1.234567901234603e-06"),
    ("state, wetness", "STATE['surface']['wetness']", "0.720735037370518"),
    ("state, strikes", "len(STATE['strikes'])", "73"),
    ("state, digest", "STATE['digest']", "'f6110b71599a06e41e112b9df136bca7eeac5d68f67a3e4fa5b71a448f779ecd'"),
    ("bad document", "validate_document(bad_document())", "['WX1', 'WX2', 'WX3', 'WX4']"),
)

_SCOPE = None


def scope():
    """The names the table's expressions use (computed once)."""
    global _SCOPE
    if _SCOPE is not None:
        return _SCOPE
    s = dict(globals())
    s["E"] = example_seed()
    s["WET"] = dict(DEFAULTS, precipitation=0.2, temperature=290.0, humidity=0.5)
    s["COLD"] = dict(DEFAULTS, precipitation=0.2, temperature=270.0)
    s["STRIKES"] = strikes(dict(DEFAULTS, lightning=0.5), s["E"], 400.0)
    s["BOLT"] = bolt(s["E"], 1, 0.5, dict(DEFAULTS, lightningGrid=24))
    s["STATE"] = state(example_document(), "wx", 1200.0)
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
