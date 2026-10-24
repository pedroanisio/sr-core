#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add wave simulations" (srep/srep-0000-wave-sim.md, OW4 of
SREP 12).

Pure functions and plain dict states, standard library only:

* the ripple tank: a 2D finite-difference time-domain (FDTD) solver of the scalar wave equation on a regular
  grid, with the document's Courant number checked against the CFL bound, point and line sources that are
  continuous or pulsed, walls with slits, regions of a different wave speed, and reflecting, periodic or
  absorbing (sponge) boundaries; the discrete energy of the leapfrog scheme;
* the string: a 1D leapfrog solver with fixed or free ends, plucked, struck or driven, with viscous damping;
  the closed forms of the mode frequencies, nodes and standing waves;
* Chladni plates: the simply supported closed form sin(m pi x / a) sin(n pi y / b) and the free square plate by
  Ritz's method with the free-free beam functions, as Gander and Wanner (2012) retrace it; nodal lines by sign
  change and the descent of sand to them;
* hits sampled from an intensity profile with the document's random stream (shot 15's dots);
* every animation frame as a pure function of the frame index (the seek check).

Running the module prints the data rows of the draft's numeric table.
"""
import math

BOUNDARIES = ("absorbing", "reflecting", "periodic")
SOURCE_KINDS = ("point", "line")
WAVEFORMS = ("continuous", "pulse")
END_KINDS = ("fixed", "free")
PLATE_SUPPORTS = ("simplySupported", "free")
MAX_GRID = 4096
MAX_STEPS_PER_FRAME = 64
MAX_BASIS = 12
MIN_SEGMENTS = 4
COURANT_LIMIT_1D = 1.0
COURANT_LIMIT_2D = 1.0 / math.sqrt(2.0)
SPONGE_STRENGTH = 0.1            # per-step attenuation exponent at the outer edge of the sponge
QUADRATURE_PANELS = 200
SEEK_FRAMES = 7


class WaveSimError(ValueError):
    """A simulation document or a numeric request that the draft rejects."""


# ------------------------------------------------------------------------------------ the CFL condition


def courant_stable(courant, dimensions):
    """True when the Courant number keeps the leapfrog scheme stable in 1 or 2 dimensions."""
    if dimensions == 1:
        return 0.0 < courant <= COURANT_LIMIT_1D
    if dimensions == 2:
        return 0.0 < courant <= COURANT_LIMIT_2D
    raise WaveSimError(f"dimensions must be 1 or 2, not {dimensions!r}")


def cfl_dt(dx, speed, courant):
    """The tank's time step dt = courant * dx / speed with the Courant number courant = c dt / dx, refused above
    the 2D bound 1 / sqrt 2."""
    if not dx > 0.0:
        raise WaveSimError(f"dx must be positive, not {dx!r}")
    if not speed > 0.0:
        raise WaveSimError(f"speed must be positive, not {speed!r}")
    if not courant_stable(courant, 2):
        raise WaveSimError(f"courant must lie in (0, {COURANT_LIMIT_2D:.5f}], not {courant!r}")
    return courant * dx / speed


def sponge_factor(distance, width):
    """The per-step amplitude factor of a cell `distance` cells from the edge inside a sponge `width` cells deep."""
    if width <= 0 or distance >= width:
        return 1.0
    s = 1.0 - distance / width
    return math.exp(-SPONGE_STRENGTH * s * s)


# ------------------------------------------------------------------------------------ validation


def _check_int(d, key, lo, hi, required=True):
    if key not in d:
        if required:
            raise WaveSimError(f"{key} is required")
        return None
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise WaveSimError(f"{key} must be an integer in [{lo}, {hi}], not {v!r}")
    return v


def _check_number(d, key, lo=None, hi=None, required=True, strict_lo=False):
    if key not in d:
        if required:
            raise WaveSimError(f"{key} is required")
        return None
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
        raise WaveSimError(f"{key} must be a finite number, not {v!r}")
    if lo is not None and (v < lo or (strict_lo and v == lo)):
        raise WaveSimError(f"{key} must be {'above' if strict_lo else 'at least'} {lo}, not {v!r}")
    if hi is not None and v > hi:
        raise WaveSimError(f"{key} must be at most {hi}, not {v!r}")
    return v


def _check_choice(d, key, choices, required=True):
    if key not in d:
        if required:
            raise WaveSimError(f"{key} is required")
        return None
    if d[key] not in choices:
        raise WaveSimError(f"{key} must be one of {choices}, not {d[key]!r}")
    return d[key]


def validate_tank(doc):
    """Rules WS1 and V17 for a rippleTank: grid, speed, Courant number, boundary, sponge and steps per frame."""
    nx = _check_int(doc, "nx", 2, MAX_GRID)
    ny = _check_int(doc, "ny", 2, MAX_GRID)
    _check_number(doc, "dx", 0.0, strict_lo=True)
    _check_number(doc, "speed", 0.0, strict_lo=True)
    courant = _check_number(doc, "courant", 0.0, COURANT_LIMIT_2D, strict_lo=True)
    if not courant_stable(courant, 2):
        raise WaveSimError(f"courant {courant!r} breaks the CFL bound {COURANT_LIMIT_2D:.5f}")
    boundary = _check_choice(doc, "boundary", BOUNDARIES)
    sponge = _check_int(doc, "sponge", 0, min(nx, ny) // 2, required=False) or 0
    if sponge and boundary != "absorbing":
        raise WaveSimError("sponge applies to the absorbing boundary only")
    _check_int(doc, "stepsPerFrame", 1, MAX_STEPS_PER_FRAME, required=False)
    for src in doc.get("sources", ()):
        validate_source(src)
    return True


def validate_source(doc):
    """A point or line source with a positive frequency and a continuous or pulsed waveform."""
    kind = _check_choice(doc, "kind", SOURCE_KINDS)
    _check_number(doc, "x")
    if kind == "point":
        _check_number(doc, "y")
    _check_number(doc, "frequency", 0.0, strict_lo=True)
    _check_number(doc, "amplitude")
    waveform = _check_choice(doc, "waveform", WAVEFORMS)
    if waveform == "pulse":
        _check_int(doc, "cycles", 1, 1 << 20)
    _check_number(doc, "phase", required=False)
    return True


def validate_string(doc):
    """Rules WS2 and V17 for a string: segments, ends, the 1D Courant number and the damping rate."""
    _check_int(doc, "segments", MIN_SEGMENTS, MAX_GRID)
    _check_number(doc, "length", 0.0, strict_lo=True)
    _check_number(doc, "speed", 0.0, strict_lo=True)
    _check_choice(doc, "ends", END_KINDS)
    courant = _check_number(doc, "courant", 0.0, COURANT_LIMIT_1D, strict_lo=True)
    if not courant_stable(courant, 1):
        raise WaveSimError(f"courant {courant!r} breaks the 1D CFL bound 1")
    _check_number(doc, "damping", 0.0, required=False)
    return True


def validate_plate(doc):
    """Rules WS3 and V17 for a chladniPlate: the support, the Ritz basis and Poisson ratio or the (m, n) pair."""
    support = _check_choice(doc, "support", PLATE_SUPPORTS)
    if support == "free":
        basis = _check_int(doc, "basis", 2, MAX_BASIS)
        _check_number(doc, "poisson", 0.0, 0.5)
        if doc["poisson"] >= 0.5:
            raise WaveSimError("poisson must be below 0.5")
        _check_int(doc, "mode", 0, basis * basis - 1)
    else:
        _check_int(doc, "m", 1, MAX_GRID)
        _check_int(doc, "n", 1, MAX_GRID)
    return True


# ------------------------------------------------------------------------------------ the ripple tank


def tank(nx, ny, dx, speed, courant, boundary, sponge=0):
    """A ripple-tank state at rest: rows of field values indexed [y][x]."""
    doc = {"nx": nx, "ny": ny, "dx": dx, "speed": speed, "courant": courant, "boundary": boundary, "sponge": sponge}
    validate_tank(doc)
    zero = [0.0] * nx
    state = {
        "nx": nx, "ny": ny, "dx": float(dx), "speed": float(speed), "courant": float(courant),
        "boundary": boundary, "sponge": int(sponge), "t": 0.0, "step": 0,
        "c": [[float(speed)] * nx for _ in range(ny)],
        "u": [list(zero) for _ in range(ny)], "u_prev": [list(zero) for _ in range(ny)],
        "wall": [], "sq": None, "sq_steps": 0,
    }
    state["dt"] = cfl_dt(dx, speed, courant)
    state["sponge_rows"] = _sponge_rows(nx, ny, sponge) if boundary == "absorbing" and sponge else None
    return state


def _sponge_rows(nx, ny, width):
    rows = []
    for j in range(ny):
        dj = min(j, ny - 1 - j)
        rows.append([sponge_factor(min(dj, i, nx - 1 - i), width) for i in range(nx)])
    return rows


def set_speed(state, fn):
    """Give every cell the wave speed fn(x, y) (cell centres at i dx, j dx); dt follows the fastest cell."""
    dx = state["dx"]
    c = [[float(fn(i * dx, j * dx)) for i in range(state["nx"])] for j in range(state["ny"])]
    fastest = max(max(row) for row in c)
    slowest = min(min(row) for row in c)
    if not slowest > 0.0:
        raise WaveSimError("every wave speed must be positive")
    state["c"] = c
    state["speed"] = fastest
    state["dt"] = cfl_dt(dx, fastest, state["courant"])
    state.pop("_k2", None)
    return state


def add_wall(state, x=None, y=None, slits=()):
    """A wall along the column x (or the row y) with open intervals [lo, hi) of cells; wall cells stay at rest."""
    if (x is None) == (y is None):
        raise WaveSimError("a wall is a column x or a row y")
    cells = []
    if x is not None:
        for j in range(state["ny"]):
            if not any(lo <= j < hi for lo, hi in slits):
                cells.append((j, int(x)))
    else:
        for i in range(state["nx"]):
            if not any(lo <= i < hi for lo, hi in slits):
                cells.append((int(y), i))
    state["wall"].extend(cells)
    for j, i in cells:
        state["u"][j][i] = 0.0
        state["u_prev"][j][i] = 0.0
    return state


def source(kind, x, y=None, frequency=1.0, amplitude=1.0, waveform="continuous", cycles=None, phase=0.0):
    """A source document."""
    doc = {"kind": kind, "x": x, "frequency": frequency, "amplitude": amplitude, "waveform": waveform, "phase": phase}
    if y is not None:
        doc["y"] = y
    if cycles is not None:
        doc["cycles"] = cycles
    validate_source(doc)
    return doc


def source_value(src, t):
    """The source's displacement at time t: a sine, cut after `cycles` periods for a pulse."""
    if t < 0.0:
        return 0.0
    f = src["frequency"]
    if src["waveform"] == "pulse" and t >= src["cycles"] / f:
        return 0.0
    return src["amplitude"] * math.sin(2.0 * math.pi * f * t + src.get("phase", 0.0))


def _coefficients(state):
    cached = state.get("_k2")
    if cached is not None and cached[0] == state["dt"]:
        return cached[1]
    r = state["dt"] / state["dx"]
    k2 = [[(c * r) ** 2 for c in row] for row in state["c"]]
    state["_k2"] = (state["dt"], k2)
    return k2


def _neighbours(state, field, j):
    """The left, right, up and down neighbour rows of row j under the boundary rule."""
    ny = state["ny"]
    row = field[j]
    b = state["boundary"]
    if b == "periodic":
        return row[-1:] + row[:-1], row[1:] + row[:1], field[j - 1], field[(j + 1) % ny]
    if b == "reflecting":
        return (row[:1] + row[:-1], row[1:] + row[-1:],
                field[j - 1] if j else row, field[j + 1] if j < ny - 1 else row)
    zero = [0.0] * state["nx"]
    return [0.0] + row[:-1], row[1:] + [0.0], field[j - 1] if j else zero, field[j + 1] if j < ny - 1 else zero


def laplacian(state, field):
    """The five-point Laplacian of a field (in cells) under the tank's boundary rule."""
    out = []
    for j in range(state["ny"]):
        left, right, up, down = _neighbours(state, field, j)
        out.append([l + r + a + b - 4.0 * m for l, r, a, b, m in zip(left, right, up, down, field[j])])
    return out


def tank_step(state, sources=(), accumulate=False):
    """One leapfrog step: u_new = 2u - u_prev + (c dt / dx)^2 lap u, then walls, sources and the sponge."""
    u, p = state["u"], state["u_prev"]
    k2 = _coefficients(state)
    new = []
    for j in range(state["ny"]):
        left, right, up, down = _neighbours(state, u, j)
        new.append([2.0 * a - b + k * (l + r + d1 + d2 - 4.0 * a)
                    for a, b, k, l, r, d1, d2 in zip(u[j], p[j], k2[j], left, right, up, down)])
    t_new = state["t"] + state["dt"]
    for src in sources:
        v = source_value(src, t_new)
        xi = int(round(src["x"]))
        if src["kind"] == "point":
            new[int(round(src["y"]))][xi] += v
        else:
            for row in new:
                row[xi] += v
    for j, i in state["wall"]:
        new[j][i] = 0.0
    sp = state.get("sponge_rows")
    if sp is not None:
        new = [[a * f for a, f in zip(row, frow)] for row, frow in zip(new, sp)]
        u = [[a * f for a, f in zip(row, frow)] for row, frow in zip(u, sp)]
    state["u_prev"], state["u"] = u, new
    state["t"] = t_new
    state["step"] += 1
    if accumulate:
        if state["sq"] is None:
            state["sq"] = [[0.0] * state["nx"] for _ in range(state["ny"])]
            state["sq_steps"] = 0
        state["sq"] = [[s + a * a for s, a in zip(srow, row)] for srow, row in zip(state["sq"], new)]
        state["sq_steps"] += 1
    return state


def averaging_window(steps, dt, sources=()):
    """The number of closing steps averaged for RMS maps: the last quarter, cut to whole periods of the slowest
    continuous source when at least one period fits."""
    window = max(1, steps // 4)
    continuous = [s["frequency"] for s in sources if s["waveform"] == "continuous"]
    if continuous:
        period_steps = 1.0 / (min(continuous) * dt)
        whole = math.floor(window / period_steps)
        if whole >= 1:
            window = max(1, int(round(whole * period_steps)))
    return window


def run(state, steps, sources=None):
    """Advance `steps` steps; the mean square of the field is accumulated over the closing averaging window."""
    sources = list(sources or ())
    for src in sources:
        validate_source(src)
    if steps < 0:
        raise WaveSimError("steps must not be negative")
    window = averaging_window(steps, state["dt"], sources)
    state["sq"], state["sq_steps"] = None, 0
    for k in range(steps):
        tank_step(state, sources, accumulate=k >= steps - window)
    return state


def inject_pulse(state, x, width, amplitude, y=None):
    """A Gaussian pulse of the given width (cells): a line pulse travelling in +x when y is None, else a
    stationary blob started at rest."""
    nx, ny = state["nx"], state["ny"]
    two_w2 = 2.0 * width * width
    if y is None:
        c = state["c"][ny // 2][int(round(x))]
        shift = c * state["dt"] / state["dx"]
        for j in range(ny):
            for i in range(nx):
                state["u"][j][i] += amplitude * math.exp(-((i - x) ** 2) / two_w2)
                state["u_prev"][j][i] += amplitude * math.exp(-((i + shift - x) ** 2) / two_w2)
        return state
    g = [[amplitude * math.exp(-((i - x) ** 2 + (j - y) ** 2) / two_w2) for i in range(nx)] for j in range(ny)]
    lap = laplacian(state, g)
    k2 = _coefficients(state)
    for j in range(ny):
        for i in range(nx):
            state["u"][j][i] += g[j][i]
            state["u_prev"][j][i] += g[j][i] + 0.5 * k2[j][i] * lap[j][i]
    return state


def crest_x(state):
    """The x position (in length units) of the field maximum along the middle row, parabola-refined."""
    row = state["u"][state["ny"] // 2]
    i = max(range(len(row)), key=row.__getitem__)
    offset = 0.0
    if 0 < i < len(row) - 1:
        denom = row[i - 1] - 2.0 * row[i] + row[i + 1]
        if denom != 0.0:
            offset = 0.5 * (row[i - 1] - row[i + 1]) / denom
    return (i + offset) * state["dx"]


def energy(state):
    """The conserved discrete energy of the leapfrog scheme, per unit c^2: kinetic + 1/2 <u, -lap u_prev> / dx^2."""
    u, p = state["u"], state["u_prev"]
    dt, dx = state["dt"], state["dx"]
    lap = laplacian(state, p)
    kinetic = potential = 0.0
    for j in range(state["ny"]):
        for a, b, c, l in zip(u[j], p[j], state["c"][j], lap[j]):
            v = (a - b) / (c * dt)
            kinetic += 0.5 * v * v
            potential -= 0.5 * a * l / (dx * dx)
    return kinetic + potential


def max_abs(state):
    return max(max(abs(v) for v in row) for row in state["u"])


def field_at(state, x, y):
    return state["u"][int(y)][int(x)]


def rms_region(state, xs, ys):
    """The RMS of the field over cells x in [xs[0], xs[1]) and y in [ys[0], ys[1]) across the averaging window."""
    if state["sq"] is None or state["sq_steps"] == 0:
        raise WaveSimError("run the tank before asking for an RMS")
    total = 0.0
    count = 0
    for j in range(ys[0], ys[1]):
        for i in range(xs[0], xs[1]):
            total += state["sq"][j][i]
            count += 1
    return math.sqrt(total / (count * state["sq_steps"]))


def rms_column(state, x, y0, y1):
    return [rms_region(state, (x, x + 1), (j, j + 1)) for j in range(y0, y1)]


def local_maxima(profile):
    return [i for i in range(1, len(profile) - 1) if profile[i] > profile[i - 1] and profile[i] > profile[i + 1]]


# ------------------------------------------------------------------------------------ strings


def mode_frequency(n, length, speed, ends):
    """Mode n of a string: n c / 2L with both ends fixed, (2n - 1) c / 4L with one end free."""
    if not isinstance(n, int) or n < 1:
        raise WaveSimError(f"the mode number must be a positive integer, not {n!r}")
    if ends not in END_KINDS:
        raise WaveSimError(f"ends must be one of {END_KINDS}, not {ends!r}")
    if ends == "fixed":
        return n * speed / (2.0 * length)
    return (2 * n - 1) * speed / (4.0 * length)


def mode_wavelength(n, length):
    if not isinstance(n, int) or n < 1:
        raise WaveSimError(f"the mode number must be a positive integer, not {n!r}")
    return 2.0 * length / n


def node_positions(n, length):
    """The n + 1 nodes of mode n with fixed ends, a half wavelength apart."""
    if not isinstance(n, int) or n < 1:
        raise WaveSimError(f"the mode number must be a positive integer, not {n!r}")
    return tuple(k * length / n for k in range(n + 1))


def standing_wave(x, t, n, length, speed, amplitude):
    f = mode_frequency(n, length, speed, "fixed")
    return amplitude * math.sin(n * math.pi * x / length) * math.cos(2.0 * math.pi * f * t)


def string(n, length, speed, ends, courant, damping=0.0):
    """A string of n segments (n + 1 points) at rest."""
    validate_string({"segments": n, "length": length, "speed": speed, "ends": ends, "courant": courant,
                     "damping": damping})
    dx = length / n
    return {"n": n, "length": float(length), "dx": dx, "speed": float(speed), "ends": ends,
            "courant": float(courant), "damping": float(damping), "dt": courant * dx / speed,
            "u": [0.0] * (n + 1), "u_prev": [0.0] * (n + 1), "t": 0.0, "step": 0}


def _string_laplacian(s, u):
    n = s["n"]
    lap = [0.0] * (n + 1)
    for i in range(1, n):
        lap[i] = u[i - 1] + u[i + 1] - 2.0 * u[i]
    if s["ends"] == "free":
        lap[n] = 2.0 * u[n - 1] - 2.0 * u[n]
    return lap


def _start_from(s, shape, velocity):
    """Set u(0) = shape and u(-dt) by the Taylor start u - dt v + (c dt / dx)^2 lap u / 2."""
    k2 = (s["speed"] * s["dt"] / s["dx"]) ** 2
    u = [float(v) for v in shape]
    u[0] = 0.0
    if s["ends"] == "fixed":
        u[s["n"]] = 0.0
    lap = _string_laplacian(s, u)
    s["u"] = u
    s["u_prev"] = [a - s["dt"] * v + 0.5 * k2 * l for a, v, l in zip(u, velocity, lap)]
    s["u_prev"][0] = 0.0
    if s["ends"] == "fixed":
        s["u_prev"][s["n"]] = 0.0
    s["t"], s["step"] = 0.0, 0
    return s


def set_shape(s, fn):
    """Start from rest with the displacement fn(x)."""
    shape = [fn(i * s["dx"]) for i in range(s["n"] + 1)]
    return _start_from(s, shape, [0.0] * (s["n"] + 1))


def pluck(s, position, amplitude):
    """A triangle of the given amplitude with its apex at the fraction `position` of the length, released."""
    if not 0.0 < position < 1.0:
        raise WaveSimError("the pluck position is a fraction strictly inside (0, 1)")
    xp = position * s["length"]
    L = s["length"]

    def tri(x):
        return amplitude * (x / xp if x <= xp else (L - x) / (L - xp))

    return set_shape(s, tri)


def strike(s, position, width, velocity):
    """Start at rest in shape with a cosine-squared bump of velocity, `width` long, centred at the fraction
    `position` of the length."""
    if not 0.0 < position < 1.0 or not width > 0.0:
        raise WaveSimError("the strike position is a fraction inside (0, 1) and the width positive")
    xp = position * s["length"]
    v = []
    for i in range(s["n"] + 1):
        d = i * s["dx"] - xp
        v.append(velocity * math.cos(math.pi * d / width) ** 2 if abs(d) < width / 2.0 else 0.0)
    return _start_from(s, [0.0] * (s["n"] + 1), v)


def drive(frequency, amplitude, phase=0.0):
    if not frequency > 0.0:
        raise WaveSimError("the drive frequency must be positive")
    return {"frequency": float(frequency), "amplitude": float(amplitude), "phase": float(phase)}


def string_step(s, drive=None):
    """One damped leapfrog step: u_new (1 + g) = 2u - (1 - g) u_prev + (c dt / dx)^2 lap u, g = damping dt;
    a driven string's x = 0 end follows amplitude sin(2 pi f t)."""
    n = s["n"]
    u, p = s["u"], s["u_prev"]
    k2 = (s["speed"] * s["dt"] / s["dx"]) ** 2
    g = s["damping"] * s["dt"]
    lap = _string_laplacian(s, u)
    new = [(2.0 * a - (1.0 - g) * b + k2 * l) / (1.0 + g) for a, b, l in zip(u, p, lap)]
    t_new = s["t"] + s["dt"]
    new[0] = (drive["amplitude"] * math.sin(2.0 * math.pi * drive["frequency"] * t_new + drive["phase"])
              if drive is not None else 0.0)
    if s["ends"] == "fixed":
        new[n] = 0.0
    s["u_prev"], s["u"] = u, new
    s["t"] = t_new
    s["step"] += 1
    return s


def string_energy(s):
    """The conserved discrete energy: dx [ sum v^2 / 2 + (c / dx)^2 sum (du)(du_prev) / 2 ]."""
    u, p = s["u"], s["u_prev"]
    dt, dx, c = s["dt"], s["dx"], s["speed"]
    kinetic = sum(((a - b) / dt) ** 2 for a, b in zip(u, p)) * 0.5
    potential = 0.5 * (c / dx) ** 2 * sum((u[i + 1] - u[i]) * (p[i + 1] - p[i]) for i in range(s["n"]))
    return dx * (kinetic + potential)


def period_from_history(history, dt):
    """The mean spacing of upward zero crossings, linearly interpolated."""
    crossings = []
    for i in range(1, len(history)):
        a, b = history[i - 1], history[i]
        if a < 0.0 <= b:
            crossings.append((i - 1 + a / (a - b)) * dt)
    if len(crossings) < 2:
        raise WaveSimError("fewer than two upward zero crossings")
    return (crossings[-1] - crossings[0]) / (len(crossings) - 1)


# ------------------------------------------------------------------------------------ simply supported plates


def _check_mode_pair(m, n):
    if not isinstance(m, int) or not isinstance(n, int) or m < 1 or n < 1:
        raise WaveSimError(f"m and n must be positive integers, not {m!r}, {n!r}")


def plate_mode_ss(m, n, a, b, x, y):
    """The (m, n) mode of a simply supported a x b plate, sin(m pi x / a) sin(n pi y / b)."""
    _check_mode_pair(m, n)
    return math.sin(m * math.pi * x / a) * math.sin(n * math.pi * y / b)


def plate_frequency_ss(m, n, a, b, stiffness):
    """f = (pi / 2) sqrt(D / rho h) ((m / a)^2 + (n / b)^2); `stiffness` is sqrt(D / rho h)."""
    _check_mode_pair(m, n)
    return 0.5 * math.pi * stiffness * ((m / a) ** 2 + (n / b) ** 2)


def nodal_lines_ss(m, n, a, b):
    _check_mode_pair(m, n)
    return {"x": tuple(k * a / m for k in range(1, m)), "y": tuple(k * b / n for k in range(1, n))}


# ------------------------------------------------------------------------------------ the free plate by Ritz

_GL5 = ((0.0, 0.5688888888888889),
        (0.5384693101056831, 0.4786286704993665), (-0.5384693101056831, 0.4786286704993665),
        (0.9061798459386640, 0.2369268850561891), (-0.9061798459386640, 0.2369268850561891))


def integrate(f, a=-1.0, b=1.0, panels=QUADRATURE_PANELS):
    """Composite five-point Gauss-Legendre quadrature of f over [a, b]."""
    h = (b - a) / panels
    total = 0.0
    for p in range(panels):
        mid = a + (p + 0.5) * h
        total += sum(w * f(mid + 0.5 * h * x) for x, w in _GL5)
    return 0.5 * h * total


def beam_roots(count):
    """The first `count` roots of the free-free beam on [-1, 1]: even roots of tan k + tanh k = 0 and odd roots
    of tan k - tanh k = 0, interleaved in increasing order."""
    roots = []
    for i in range(count):
        even = i % 2 == 0
        centre = (0.75 + 0.5 * i) * math.pi
        lo, hi = centre - 0.25 * math.pi, centre + 0.25 * math.pi

        def g(k):
            return math.sin(k) * math.cosh(k) + (1.0 if even else -1.0) * math.cos(k) * math.sinh(k)

        flo = g(lo)
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            fm = g(mid)
            if (fm < 0.0) == (flo < 0.0):
                lo, flo = mid, fm
            else:
                hi = mid
            if hi - lo < 1e-15:
                break
        roots.append(0.5 * (lo + hi))
    return tuple(roots)


_BEAMS = {}


def _beam(i):
    """(u, u', u'') of the i-th orthonormal free-free beam function on [-1, 1]."""
    if i in _BEAMS:
        return _BEAMS[i]
    if i == 0:
        c = 1.0 / math.sqrt(2.0)
        trio = ((lambda x: c), (lambda x: 0.0), (lambda x: 0.0))
    elif i == 1:
        c = math.sqrt(1.5)
        trio = ((lambda x: c * x), (lambda x: c), (lambda x: 0.0))
    else:
        k = beam_roots(i - 1)[i - 2]
        if (i - 2) % 2 == 0:
            ch, co = math.cosh(k), math.cos(k)
            raw = (lambda x: math.cosh(k * x) / ch + math.cos(k * x) / co)
            d1 = (lambda x: k * (math.sinh(k * x) / ch - math.sin(k * x) / co))
            d2 = (lambda x: k * k * (math.cosh(k * x) / ch - math.cos(k * x) / co))
        else:
            sh, si = math.sinh(k), math.sin(k)
            raw = (lambda x: math.sinh(k * x) / sh + math.sin(k * x) / si)
            d1 = (lambda x: k * (math.cosh(k * x) / sh + math.cos(k * x) / si))
            d2 = (lambda x: k * k * (math.sinh(k * x) / sh - math.sin(k * x) / si))
        norm = 1.0 / math.sqrt(integrate(lambda x: raw(x) ** 2))
        trio = ((lambda x, f=raw, n=norm: n * f(x)), (lambda x, f=d1, n=norm: n * f(x)),
                (lambda x, f=d2, n=norm: n * f(x)))
    _BEAMS[i] = trio
    return trio


def beam_functions(count):
    return [_beam(i)[0] for i in range(count)]


def beam_derivative(i):
    return _beam(i)[1]


def beam_second_derivative(i):
    return _beam(i)[2]


def _parity(i):
    return "even" if i % 2 == 0 else "odd"


def jacobi_eigen(matrix):
    """Eigenvalues and eigenvectors (as columns) of a symmetric matrix by cyclic Jacobi rotations."""
    n = len(matrix)
    a = [row[:] for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    scale = max(1e-300, max(abs(a[i][j]) for i in range(n) for j in range(n)))
    for _ in range(100):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j))
        if off <= 1e-15 * scale:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) <= 1e-18 * scale:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0.0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    return [a[i][i] for i in range(n)], v


def ritz_plate(basis, poisson):
    """Ritz's method for the free square plate [-1, 1]^2 with `basis` beam functions per axis.

    The stiffness matrix of the products u_i(x) u_j(y) is A (x) I + I (x) A + nu (C^T (x) C + C (x) C^T) +
    2 (1 - nu) B (x) B with A = <u_i'', u_k''>, B = <u_i', u_k'>, C = <u_i, u_k''>; the mass matrix is the
    identity. The problem splits by parity in x and y and, for equal parities, by symmetry under the swap of x
    and y, so every mode carries a definite symmetry class even when eigenvalues repeat."""
    validate_plate({"support": "free", "basis": basis, "poisson": poisson, "mode": 0})
    fns = [_beam(i) for i in range(basis)]
    A = [[integrate(lambda x: fns[i][2](x) * fns[k][2](x)) for k in range(basis)] for i in range(basis)]
    B = [[integrate(lambda x: fns[i][1](x) * fns[k][1](x)) for k in range(basis)] for i in range(basis)]
    C = [[integrate(lambda x: fns[i][0](x) * fns[k][2](x)) for k in range(basis)] for i in range(basis)]
    nu = poisson

    def k_entry(i, j, k, l):
        val = 0.0
        if j == l:
            val += A[i][k]
        if i == k:
            val += A[j][l]
        val += nu * (C[k][i] * C[j][l] + C[i][k] * C[l][j])
        val += 2.0 * (1.0 - nu) * B[i][k] * B[j][l]
        return val

    modes = []
    for px in ("even", "odd"):
        for py in ("even", "odd"):
            I = [i for i in range(basis) if _parity(i) == px]
            J = [j for j in range(basis) if _parity(j) == py]
            if px == py:
                blocks = {"sym": [], "anti": []}
                for a_ in range(len(I)):
                    for b_ in range(a_, len(I)):
                        i, j = I[a_], I[b_]
                        if i == j:
                            blocks["sym"].append({(i, j): 1.0})
                        else:
                            r = 1.0 / math.sqrt(2.0)
                            blocks["sym"].append({(i, j): r, (j, i): r})
                            blocks["anti"].append({(i, j): r, (j, i): -r})
            else:
                blocks = {None: [{(i, j): 1.0} for i in I for j in J]}
            for swap, vecs in blocks.items():
                if not vecs:
                    continue
                m = len(vecs)
                K = [[0.0] * m for _ in range(m)]
                for a_ in range(m):
                    for b_ in range(a_, m):
                        val = 0.0
                        for (i, j), ca in vecs[a_].items():
                            for (k, l), cb in vecs[b_].items():
                                val += ca * cb * k_entry(i, j, k, l)
                        K[a_][b_] = K[b_][a_] = val
                values, vectors = jacobi_eigen(K)
                for col in range(m):
                    coeffs = {}
                    for a_ in range(m):
                        for key, c in vecs[a_].items():
                            coeffs[key] = coeffs.get(key, 0.0) + vectors[a_][col] * c
                    largest = max(coeffs, key=lambda key: abs(coeffs[key]))
                    if coeffs[largest] < 0.0:
                        coeffs = {key: -c for key, c in coeffs.items()}
                    modes.append({"value": values[col], "parity": (px, py), "swap": swap, "coefficients": coeffs})
    modes.sort(key=lambda mode: mode["value"])
    return {"basis": basis, "poisson": poisson, "modes": modes,
            "eigenvalues": [mode["value"] for mode in modes]}


def plate_mode_free(res, index):
    """The mode as a callable w(x, y) on [-1, 1]^2, normalised to unit mean square."""
    if not 0 <= index < len(res["modes"]):
        raise WaveSimError(f"mode index {index!r} is outside the {len(res['modes'])} Ritz modes")
    terms = [(c, _beam(i)[0], _beam(j)[0]) for (i, j), c in res["modes"][index]["coefficients"].items()]

    def w(x, y):
        return sum(c * ux(x) * uy(y) for c, ux, uy in terms)

    return w


def mode_symmetry(res, index):
    return res["modes"][index]["parity"]


def first_mode_with_symmetry(res, parity, swap=None):
    for idx, mode in enumerate(res["modes"]):
        if mode["parity"] == tuple(parity) and (swap is None or mode["swap"] == swap):
            return idx
    raise WaveSimError(f"no mode with parity {parity!r} and swap {swap!r}")


def nodal_points(mode, grid=41):
    """Points of the nodal lines: grid samples that vanish and sign changes between neighbouring samples,
    linearly interpolated, along both grid directions."""
    xs = [-1.0 + 2.0 * i / (grid - 1) for i in range(grid)]
    vals = [[mode(x, y) for y in xs] for x in xs]
    found = set()

    def between(x0, y0, v0, x1, y1, v1):
        if v0 == 0.0:
            found.add((round(x0, 9), round(y0, 9)))
        if v1 == 0.0:
            found.add((round(x1, 9), round(y1, 9)))
        if v0 * v1 < 0.0:
            s = v0 / (v0 - v1)
            found.add((round(x0 + s * (x1 - x0), 9), round(y0 + s * (y1 - y0), 9)))

    for i in range(grid):
        for j in range(grid):
            if i + 1 < grid:
                between(xs[i], xs[j], vals[i][j], xs[i + 1], xs[j], vals[i + 1][j])
            if j + 1 < grid:
                between(xs[i], xs[j], vals[i][j], xs[i], xs[j + 1], vals[i][j + 1])
    return sorted(found)


def chladni_sand(mode, particles, steps=200, step_size=0.01):
    """Sand grains walk down |w| toward the nodal lines: a Newton step |w| / |grad w| along -sign(w) grad w,
    capped at step_size, clamped to the plate."""
    if steps < 0 or not step_size > 0.0:
        raise WaveSimError("steps must not be negative and step_size must be positive")
    h = 1e-4
    out = []
    for x, y in particles:
        for _ in range(steps):
            w = mode(x, y)
            if abs(w) < 1e-12:
                break
            gx = (mode(x + h, y) - mode(x - h, y)) / (2.0 * h)
            gy = (mode(x, y + h) - mode(x, y - h)) / (2.0 * h)
            norm = math.hypot(gx, gy)
            if norm < 1e-12:
                break
            d = min(step_size, abs(w) / norm)
            sign = 1.0 if w > 0.0 else -1.0
            x = min(1.0, max(-1.0, x - sign * d * gx / norm))
            y = min(1.0, max(-1.0, y - sign * d * gy / norm))
        out.append((x, y))
    return out


# ------------------------------------------------------------------------------------ sampled hits (shot 15)

MASK64 = (1 << 64) - 1
PHI = 0x9E3779B97F4A7C15
MUL1 = 0xBF58476D1CE4E5B9
MUL2 = 0x94D049BB133111EB
TWO53 = float(1 << 53)
CHANNEL_HIT = 0x48495453            # "HITS": the path stream channel of the hit draws, requested of SREP 92
MAX_HITS = 1 << 20


def u64(x):
    if isinstance(x, bool) or not isinstance(x, int) or x < -(1 << 63) or x >= (1 << 64):
        raise WaveSimError(f"not a 64-bit integer: {x!r}")
    return x & MASK64


def mix64(z):
    z &= MASK64
    z = ((z ^ (z >> 30)) * MUL1) & MASK64
    z = ((z ^ (z >> 27)) * MUL2) & MASK64
    return z ^ (z >> 31)


def splitmix64(x):
    return mix64((u64(x) + PHI) & MASK64)


def H(seed, channel, index):
    return splitmix64(u64(seed) ^ splitmix64(u64(channel) ^ splitmix64(u64(index))))


def U(seed, channel, index):
    return (H(seed, channel, index) >> 11) / TWO53


def hit_unit(seed, index):
    """The unit draw of hit `index` from the document's stream (SREP 92, channel HITS)."""
    return U(seed, CHANNEL_HIT, index)


def sample_hits(intensity, count, seed=0, first=0):
    """Hits `first` to `first + count - 1` drawn from a non-negative intensity profile by inverting its
    cumulative sum: the cell index and the position inside the cell, so that the dots build the pattern in the
    same order at every seek."""
    if not intensity or any(v < 0.0 for v in intensity):
        raise WaveSimError("the intensity profile is non-empty and non-negative")
    if not 0 <= count <= MAX_HITS or first < 0:
        raise WaveSimError(f"count must lie in [0, {MAX_HITS}] and first must not be negative")
    total = float(sum(intensity))
    if not total > 0.0:
        raise WaveSimError("the intensity profile has no power")
    cumulative = []
    acc = 0.0
    for v in intensity:
        acc += v / total
        cumulative.append(acc)
    cumulative[-1] = 1.0
    out = []
    for k in range(first, first + count):
        u = hit_unit(seed, k)
        lo, hi = 0, len(cumulative) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cumulative[mid] > u:
                hi = mid
            else:
                lo = mid + 1
        prev = cumulative[lo - 1] if lo else 0.0
        width = cumulative[lo] - prev
        out.append(lo + ((u - prev) / width if width > 0.0 else 0.5))
    return out


def hit_histogram(hits, cells):
    counts = [0] * cells
    for h in hits:
        counts[min(cells - 1, max(0, int(h)))] += 1
    return counts


# ------------------------------------------------------------------------------------ frames and the seek check


def frame_state(spec, frame):
    """The tank after frame * stepsPerFrame steps from rest with the spec's sources: a pure function of frame."""
    validate_tank(spec)
    if not isinstance(frame, int) or frame < 0:
        raise WaveSimError(f"the frame must be a non-negative integer, not {frame!r}")
    per = spec.get("stepsPerFrame", 1)
    state = tank(spec["nx"], spec["ny"], spec["dx"], spec["speed"], spec["courant"], spec["boundary"],
                 spec.get("sponge", 0))
    sources = list(spec.get("sources", ()))
    for _ in range(frame * per):
        tank_step(state, sources)
    return state


def seek_test(frames=SEEK_FRAMES):
    """Seeking to a frame equals playing to it: frame_state(spec, k) matches one more frame of steps after
    frame_state(spec, k - 1), bit for bit."""
    spec = {"nx": 24, "ny": 16, "dx": 1.0, "speed": 1.0, "courant": 0.5, "boundary": "absorbing", "sponge": 4,
            "stepsPerFrame": 2, "sources": [source(kind="point", x=8, y=8, frequency=0.1, amplitude=1.0,
                                                   waveform="pulse", cycles=2)]}
    direct = frame_state(spec, frames)
    played = frame_state(spec, frames - 1)
    for _ in range(spec["stepsPerFrame"]):
        tank_step(played, spec["sources"])
    if direct["u"] != played["u"] or direct["step"] != played["step"]:
        raise WaveSimError("seeking and playing disagree")
    return True


# ------------------------------------------------------------------------------------ the table


def _speed_run(slow):
    t = tank(nx=200, ny=4, dx=1.0, speed=1.0, courant=0.5, boundary="periodic")
    if slow:
        set_speed(t, lambda x, y: 1.0 if x < 100 else 0.5)
    inject_pulse(t, x=120 if slow else 20, width=4.0, amplitude=1.0)
    x0 = crest_x(t)
    run(t, 100)
    return (crest_x(t) - x0) / (100 * t["dt"])


def _energy_run(boundary, sponge, steps):
    t = tank(nx=64, ny=64, dx=1.0, speed=1.0, courant=0.5, boundary=boundary, sponge=sponge)
    inject_pulse(t, x=32, y=32, width=3.0, amplitude=1.0)
    e0 = energy(t)
    run(t, steps)
    return energy(t) / e0


def _string_mode_run():
    s = string(n=200, length=1.0, speed=1.0, ends="fixed", courant=0.5)
    set_shape(s, lambda x: math.sin(2.0 * math.pi * x))
    history = []
    for _ in range(2400):
        string_step(s)
        history.append(s["u"][50])
    return 1.0 / period_from_history(history, s["dt"])


def _string_energy_run(damping):
    s = string(n=100, length=1.0, speed=1.0, ends="fixed", courant=0.5, damping=damping)
    pluck(s, position=0.3, amplitude=0.01)
    e0 = string_energy(s)
    for _ in range(400):
        string_step(s)
    return string_energy(s) / e0


def _sand_run():
    res = ritz_plate(basis=4, poisson=0.225)
    mode = plate_mode_free(res, 3)
    particles = [(-0.8 + 1.6 * i / 9.0, -0.8 + 1.6 * j / 9.0) for i in range(10) for j in range(10)]
    amp = max(abs(mode(x, y)) for x, y in particles)
    settled = chladni_sand(mode, particles)
    return max(abs(mode(x, y)) for x, y in settled) / amp


TABLE = (
    ("2D Courant limit", "COURANT_LIMIT_2D", "0.707107"),
    ("time step for dx 0.01, c 1.5, courant 0.5", "cfl_dt(0.01, 1.5, 0.5)", "0.00333333"),
    ("courant 0.7 is stable in 2D", "courant_stable(0.7, 2)", "True"),
    ("courant 0.71 is unstable in 2D", "courant_stable(0.71, 2)", "False"),
    ("sponge factor at the edge", "sponge_factor(0, 16)", "0.904837"),
    ("sponge factor half way in", "sponge_factor(8, 16)", "0.97531"),
    ("measured pulse speed, c 1", "_speed_run(False)", "0.994283"),
    ("measured pulse speed in a c 0.5 region", "_speed_run(True)", "0.496449"),
    ("energy ratio after 200 reflecting steps", "_energy_run('reflecting', 0, 200)", "1"),
    ("energy ratio after 200 absorbing steps", "_energy_run('absorbing', 16, 200)", "0.00245987"),
    ("seek check", "seek_test()", "True"),
    ("frame 12 field sum of the seek spec", "sum(sum(row) for row in frame_state({'nx': 24, 'ny': 16, 'dx': 1.0, 'speed': 1.0, 'courant': 0.5, 'boundary': 'absorbing', 'sponge': 4, 'stepsPerFrame': 2, 'sources': [source(kind='point', x=8, y=8, frequency=0.1, amplitude=1.0, waveform='pulse', cycles=2)]}, 12)['u'])", "2.95641"),
    ("fixed string mode 1, L 1, c 2", "mode_frequency(1, 1, 2, 'fixed')", "1"),
    ("fixed-free string mode 2, L 1, c 2", "mode_frequency(2, 1, 2, 'free')", "1.5"),
    ("nodes of mode 3 on a 1 m string", "node_positions(3, 1)", "(0, 0.333333, 0.666667, 1)"),
    ("wavelength of mode 2 on 0.65 m", "mode_wavelength(2, 0.65)", "0.65"),
    ("standing wave at x 0.25, t 0.1, mode 2", "standing_wave(0.25, 0.1, 2, 1, 1, 1)", "0.809017"),
    ("measured frequency of the simulated mode 2", "_string_mode_run()", "0.999969"),
    ("plucked string energy ratio after 400 steps", "_string_energy_run(0)", "1"),
    ("heavily damped energy ratio, gamma 2, t 2", "_string_energy_run(2)", "0.000561315"),
    ("lightly damped energy ratio, gamma 0.1, t 2", "_string_energy_run(0.1)", "0.670177"),
    ("damping law e^(-2 gamma t), gamma 0.1, t 2", "math.exp(-2 * 0.1 * 2)", "0.67032"),
    ("simply supported f11, 2 x 1, stiffness 1", "plate_frequency_ss(1, 1, 2, 1, 1)", "1.9635"),
    ("f21 / f11 on the 2 x 1 plate", "plate_frequency_ss(2, 1, 2, 1, 1) / plate_frequency_ss(1, 1, 2, 1, 1)", "1.6"),
    ("nodal x lines of mode (3, 2) on 2 x 1", "nodal_lines_ss(3, 2, 2, 1)['x']", "(0.666667, 1.33333)"),
    ("free-free beam roots", "beam_roots(4)", "(2.36502, 3.9266, 5.4978, 7.06858)"),
    ("norm of the third beam function", "integrate(lambda x, f=beam_functions(3)[2]: f(x) ** 2)", "1"),
    ("bending integral of the third beam function", "integrate(lambda x: beam_second_derivative(2)(x) ** 2)", "31.2852"),
    ("single-term bound 18 (1 - nu), nu 0.225", "18 * (1 - 0.225)", "13.95"),
    ("Ritz twist eigenvalue, basis 4", "ritz_plate(4, 0.225)['eigenvalues'][3]", "12.5831"),
    ("Ritz twist eigenvalue, basis 6", "ritz_plate(6, 0.225)['eigenvalues'][3]", "12.488"),
    ("Ritz eigenvalues 4 and 5, basis 6", "tuple(ritz_plate(6, 0.225)['eigenvalues'][4:6])", "(26.2406, 35.8997)"),
    ("rigid modes of the free plate", "sum(1 for v in ritz_plate(4, 0.225)['eigenvalues'] if abs(v) < 1e-8)", "3"),
    ("symmetry of the twist mode", "mode_symmetry(ritz_plate(4, 0.225), 3)", "('odd', 'odd')"),
    ("twist mode at the corner quarter point", "abs(plate_mode_free(ritz_plate(4, 0.225), 3)(0.5, 0.5))", "0.410366"),
    ("saddle mode on the diagonal", "plate_mode_free(ritz_plate(4, 0.225), first_mode_with_symmetry(ritz_plate(4, 0.225), ('even', 'even'), swap='anti'))(0.6, 0.6)", "0"),
    ("sand settles below 5 percent of the amplitude", "_sand_run() < 0.05", "True"),
    ("first hit draw of seed 7", "hit_unit(7, 0)", "0.693032"),
    ("hits follow the profile 1:2:1 over 4000 draws", "hit_histogram(sample_hits([1, 2, 1], 4000, 7), 3)", "(1003, 2008, 989)"),
    ("hits 10 to 12 equal the run's hits 10 to 12", "sample_hits([1, 2, 1], 3, 7, 10) == sample_hits([1, 2, 1], 13, 7)[10:]", "True"),
    ("largest grid", "MAX_GRID", "4096"),
    ("largest Ritz basis", "MAX_BASIS", "12"),
)


def scope():
    s = dict(globals())
    s["math"] = math
    return s


def _same(a, b, rel=5e-4, abs_tol=5e-4):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], rel, abs_tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _fmt(v):
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and abs(v) < 1e-12:
        v = 0.0  # round-off residuals of exact zeros print as 0
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, (int, float)):
        return f"{v:.6g}"
    if isinstance(v, (tuple, list)):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    return repr(v)


def main():
    s = scope()
    for name, expr, _expected in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
