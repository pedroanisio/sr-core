#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add reactive values" (srep/srep-0000-reactive-values.md), written
from the SREP text, from SREP 14 and from D24 and D25 of conformance/DEFINITIONS.md, not from an engine. The
document's update expressions are stood in for by Python callables of a context; everything else is the SREP's
rules as pure functions. tests/test_reactive_values.py checks the rules and the SREP's numeric table against this
module.

Usage: python3 reactive_values_reference.py  (prints the numeric-test table of the SREP). Standard library only.
"""
import math
from dataclasses import dataclass
from typing import Callable, Optional

MAX_STEPS = 1_000_000        # rule 8: the most steps a time fold takes up to the composition's end
MAX_COUNT = 1_000_000        # rule 8: the most iterations of an index fold
EPS = 1e-9                   # rule 2: the tolerance of the step count, as D25's `frame`
BETWEEN = ("hold", "linear")

# --- the D24 hash, as conformance/tools/random_streams_reference.py states it ------------------------------------

MASK64 = (1 << 64) - 1
PHI = 0x9E3779B97F4A7C15
MUL1 = 0xBF58476D1CE4E5B9
MUL2 = 0x94D049BB133111EB
TWO53 = float(1 << 53)
LATTICE_BITS = 21
LATTICE_MASK = (1 << LATTICE_BITS) - 1
LATTICE_MIN, LATTICE_MAX = -(1 << (LATTICE_BITS - 1)), (1 << (LATTICE_BITS - 1)) - 1


def u64(x):
    """An integer in [-2^63, 2^64) as an unsigned 64-bit value."""
    if not isinstance(x, int) or x < -(1 << 63) or x >= (1 << 64):
        raise ValueError(f"not a 64-bit integer: {x!r}")
    return x & MASK64


def mix64(z):
    """The SplitMix64 finaliser."""
    z &= MASK64
    z = ((z ^ (z >> 30)) * MUL1) & MASK64
    z = ((z ^ (z >> 27)) * MUL2) & MASK64
    return z ^ (z >> 31)


def splitmix64(x):
    return mix64((u64(x) + PHI) & MASK64)


def H(seed, channel, index):
    """The lattice hash H(s, c, i) = splitmix64(s xor splitmix64(c xor splitmix64(i)))."""
    return splitmix64(u64(seed) ^ splitmix64(u64(channel) ^ splitmix64(u64(index))))


def U(seed, channel, index):
    """The unit draw U(s, c, i) = floor(H / 2^11) / 2^53, in [0, 1)."""
    return (H(seed, channel, index) >> 11) / TWO53


def pack(i, j, k):
    """The lattice index of (i, j, k): 21 bits of each as two's complement."""
    for v in (i, j, k):
        if not isinstance(v, int) or v < LATTICE_MIN or v > LATTICE_MAX:
            raise ValueError(f"lattice coordinate outside [-2^20, 2^20): {v!r}")
    return (i & LATTICE_MASK) | (j & LATTICE_MASK) << LATTICE_BITS | (k & LATTICE_MASK) << (2 * LATTICE_BITS)


def draw(seed, channel, index, i):
    """Rule 6: draw(channel, i) inside an update at fold index `index` is U(seed, channel, pack(index, i, 0)):
    a function of the value's seed, the channel, the step and i alone, so two values with one seed share it."""
    return U(seed, channel, pack(index, i, 0))


def rand(seed, index, site, property_channel=0):
    """Rule 6: random() inside an update is D25's draw with the fold index in place of the frame:
    U(seed, index, site + property channel * 2^32)."""
    return U(seed, index, site + (property_channel << 32))


# --- rules 1 and 2: keys and the step count ---------------------------------------------------------------------

def keys_at(keys, t):
    """Rule 1: a tracker's value at t from its keys ((t, v), ...) in time order: the first value before the
    first key, the last after the last, linear between (the document's keys follow D13's curves; the curve is
    not the subject here). A number is one key."""
    if isinstance(keys, (int, float)):
        return float(keys)
    keys = tuple(keys)
    if not keys:
        raise ValueError("a value needs at least one key")
    for (t0, _), (t1, _) in zip(keys, keys[1:]):
        if t1 < t0:
            raise ValueError("keys are in time order")
    if t <= keys[0][0]:
        return float(keys[0][1])
    if t >= keys[-1][0]:
        return float(keys[-1][1])
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            return float(v0) if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    raise AssertionError("unreachable")


def steps_at(start, step, t):
    """Rule 2: the number of steps at or before t: 0 before the start, else floor((t - start) / step + 10^-9),
    bounded by MAX_STEPS."""
    if not step > 0.0:
        raise ValueError(f"step is positive: {step!r}")
    if t < start:
        return 0
    n = math.floor((t - start) / step + EPS)
    if n > MAX_STEPS:
        raise ValueError(f"a time fold takes at most {MAX_STEPS} steps; {n} at t = {t}")
    return n


# --- rules 3 to 7: folds ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Ctx:
    """What an update expression sees (rule 5): value (the previous state), index, count, time, dt, the reads of
    the other values of the system, and the two draws of rule 6."""
    value: float
    index: int
    count: int
    time: float
    dt: float
    read: Callable[[str], float]
    draw: Callable[[int, int], float]
    random: Callable[..., float]


@dataclass(frozen=True)
class Fold:
    """A value asset: `initial` is its keyed value (a number or keys), `update` the update expression, and exactly
    one of `step` (a time fold, rule 3) and `count` (an index fold, rule 4) is given."""
    id: str
    initial: object
    update: Callable[[Ctx], float]
    start: float = 0.0
    step: Optional[float] = None
    count: Optional[int] = None
    between: str = "hold"
    seed: int = 0

    def __post_init__(self):
        if (self.step is None) == (self.count is None):
            raise ValueError(f"value {self.id!r}: exactly one of step and count")
        if self.step is not None and not self.step > 0.0:
            raise ValueError(f"value {self.id!r}: step is positive")
        if self.count is not None and not (isinstance(self.count, int) and 1 <= self.count <= MAX_COUNT):
            raise ValueError(f"value {self.id!r}: count is an integer in [1, {MAX_COUNT}]")
        if self.between not in BETWEEN:
            raise ValueError(f"value {self.id!r}: between is hold or linear")
        if self.count is not None and self.between != "hold":
            raise ValueError(f"value {self.id!r}: between applies to a time fold only")
        if self.start < 0.0:
            raise ValueError(f"value {self.id!r}: start is not negative")


def _finite(fold, v):
    v = float(v)
    if not math.isfinite(v):
        raise ValueError(f"value {fold.id!r}: the update produced a non-finite state")
    return v


def _system(folds):
    folds = tuple(folds)
    if not folds:
        raise ValueError("a system has at least one value")
    ids = [f.id for f in folds]
    if len(set(ids)) != len(ids):
        raise ValueError("value ids are unique")
    for f in folds:
        if f.step is None:
            raise ValueError(f"value {f.id!r} is an index fold, not a time fold")
        if f.step != folds[0].step or f.start != folds[0].start:
            raise ValueError("values that read each other share step and start")
    return folds


def _step_once(folds, prev, k, time, dt):
    """One step of the system in gather form (rule 5): every update reads the states before the step."""
    def reader(name):
        if name not in prev:
            raise ValueError(f"no value {name!r} in the system")
        return prev[name]

    out = {}
    for f in folds:
        ctx = Ctx(prev[f.id], k, k + 1, time, dt, reader,
                  lambda channel, i, s=f.seed: draw(s, channel, k, i),
                  lambda site=0, pc=0, s=f.seed: rand(s, k, site, pc))
        out[f.id] = _finite(f, f.update(ctx))
    return out


def time_fold_states(folds, n):
    """Rule 3: the states s_0 .. s_n of a system of time folds; s_0 is each value's keys at the start, and step k
    (index k - 1) is the update with time = start + k step and dt = step."""
    folds = _system(folds)
    start, step = folds[0].start, folds[0].step
    states = [{f.id: keys_at(f.initial, start) for f in folds}]
    for k in range(n):
        states.append(_step_once(folds, states[-1], k, start + (k + 1) * step, step))
    return states


def time_fold_at(folds, t):
    """Rule 3: the values of a system at composition time t, from the step count alone: s_n with n the last step
    at or before t, or between s_n and s_(n+1) for a linear value."""
    folds = _system(folds)
    start, step = folds[0].start, folds[0].step
    n = steps_at(start, step, t)
    linear = any(f.between == "linear" for f in folds) and t > start
    states = time_fold_states(folds, n + 1 if linear else n)
    out = {}
    for f in folds:
        v = states[n][f.id]
        if f.between == "linear" and t > start:
            u = (t - start) / step - n
            u = min(max(u, 0.0), 1.0)
            v = v + (states[n + 1][f.id] - v) * u
        out[f.id] = v
    return out


def fold_value(fold, t):
    """The value of one time fold at t."""
    return time_fold_at((fold,), t)[fold.id]


def alone(folds, times):
    """Each frame computed by itself (rule 3): the first value's state at each time."""
    folds = _system(folds)
    return tuple(time_fold_at(folds, t)[folds[0].id] for t in times)


def played(folds, times):
    """The same frames by an engine that keeps the last state and steps forward from it, restarting from the
    start when a time comes before the last step (SREP 14 rule 1 allows checkpoints; the result is fixed)."""
    folds = _system(folds)
    start, step = folds[0].start, folds[0].step
    state, done = {f.id: keys_at(f.initial, start) for f in folds}, 0
    out = []
    for t in times:
        n = steps_at(start, step, t)
        if n < done:
            state, done = {f.id: keys_at(f.initial, start) for f in folds}, 0
        while done < n:
            state = _step_once(folds, state, done, start + (done + 1) * step, step)
            done += 1
        v = state[folds[0].id]
        if folds[0].between == "linear" and t > start:
            nxt = _step_once(folds, state, done, start + (done + 1) * step, step)[folds[0].id]
            u = min(max((t - start) / step - n, 0.0), 1.0)
            v = v + (nxt - v) * u
        out.append(v)
    return tuple(out)


def seek_check(folds, times):
    """SREP 14 rule 5: a frame rendered alone equals the frame played in sequence, exactly."""
    return alone(folds, times) == played(folds, times)


def index_fold(initial, count, update, t=0.0, seed=0):
    """Rule 4: at frame time t the update runs count times from the keyed value, with index 0 .. count - 1,
    time = t and dt = 0, in increasing index."""
    if not (isinstance(count, int) and 1 <= count <= MAX_COUNT):
        raise ValueError(f"count is an integer in [1, {MAX_COUNT}]")
    fold = Fold("fold", initial, update, count=count, seed=seed)
    v = keys_at(initial, t)

    def reader(name):
        raise ValueError(f"no value {name!r} in the system")

    for k in range(count):
        ctx = Ctx(v, k, count, t, 0.0, reader, lambda channel, i: draw(seed, channel, k, i),
                  lambda site=0, pc=0: rand(seed, k, site, pc))
        v = _finite(fold, update(ctx))
    return v


# --- the shots ---------------------------------------------------------------------------------------------------

def fourier_centre(signal, winding, samples, duration):
    """Shot 9: the centre of mass of the signal wound at `winding` cycles per second, as two index folds over
    `samples` samples of [0, duration): x = mean g cos(2 pi f tau), y = -mean g sin(2 pi f tau)."""
    def tau(c):
        return c.index / c.count * duration

    x = index_fold(0.0, samples, lambda c: c.value + signal(tau(c)) * math.cos(math.tau * winding * tau(c)) / c.count)
    y = index_fold(0.0, samples, lambda c: c.value - signal(tau(c)) * math.sin(math.tau * winding * tau(c)) / c.count)
    return (x, y)


def einstein_folds(energies, seed, step=1.0 / 60.0):
    """Shot 5: an Einstein solid of N cells on a ring, one value per cell. At each step the draws pick a source
    cell (channel 0) and a direction (channel 1); one packet hops to the neighbour when the source has one. Every
    cell's update computes the same hop from the same draws (one seed) and reads the source's energy before the
    step, so the total is conserved exactly."""
    n = len(energies)
    if n < 2:
        raise ValueError("a solid has at least two cells")

    def update_for(i):
        def update(c):
            src = min(int(c.draw(0, 0) * n), n - 1)
            dst = (src + (n - 1 if c.draw(1, 0) < 0.5 else 1)) % n
            ok = c.read(f"e{src}") > 0.0
            return c.value - (1.0 if ok and src == i else 0.0) + (1.0 if ok and dst == i else 0.0)
        return update

    return tuple(Fold(f"e{i}", float(e), update_for(i), step=step, seed=seed) for i, e in enumerate(energies))


def einstein_solid(energies, steps, seed, step=1.0 / 60.0):
    """The cells' energies after `steps` steps."""
    folds = einstein_folds(energies, seed, step)
    states = time_fold_states(folds, steps)
    return tuple(states[-1][f.id] for f in folds)


# --- the numeric table -------------------------------------------------------------------------------------------

def raises(f):
    """True when f() raises ValueError (the rows that state an error)."""
    try:
        f()
    except ValueError:
        return True
    return False


TABLE = [
    ("keys hold before the first", "keys_at(((1.0, 2.0), (3.0, 6.0)), 0.0)"),
    ("keys linear between", "keys_at(((1.0, 2.0), (3.0, 6.0)), 2.0)"),
    ("keys hold after the last", "keys_at(((1.0, 2.0), (3.0, 6.0)), 9.0)"),
    ("steps at t", "steps_at(0.0, 0.1, 1.0)"),
    ("steps with the tolerance", "steps_at(0.0, 0.1, 0.3)"),
    ("steps before the start", "steps_at(1.0, 0.5, 0.5)"),
    ("steps bound", "raises(lambda: steps_at(0.0, 1e-7, 1.0))"),
    ("constant rate integrates", "fold_value(Fold('x', 0.0, lambda c: c.value + 2.0 * c.dt, step=0.25), 1.0)"),
    ("hold between steps", "fold_value(Fold('x', 0.0, lambda c: c.value + 1.0, step=1.0), 2.5)"),
    ("linear between steps", "fold_value(Fold('x', 0.0, lambda c: c.value + 1.0, step=1.0, between='linear'), 2.5)"),
    ("initial state before the start",
     "fold_value(Fold('x', 5.0, lambda c: c.value + 1.0, start=2.0, step=1.0), 1.0)"),
    ("initial state from keys at the start",
     "fold_value(Fold('x', ((0.0, 0.0), (2.0, 4.0)), lambda c: c.value + 1.0, start=1.0, step=1.0), 1.0)"),
    ("index in the update", "fold_value(Fold('x', 0.0, lambda c: c.value + c.index, step=1.0), 4.0)"),
    ("time in the update", "fold_value(Fold('x', 0.0, lambda c: c.time, step=0.5), 2.0)"),
    ("euler integrator of cos",
     "abs(fold_value(Fold('x', 0.0, lambda c: c.value + math.cos(c.time - c.dt) * c.dt, step=0.001), 1.0)"
     " - math.sin(1.0)) < 0.001"),
    ("played frames", "played((Fold('x', 0.0, lambda c: c.value + c.index, step=0.1),), (0.0, 0.5, 1.0))"),
    ("frames alone", "alone((Fold('x', 0.0, lambda c: c.value + c.index, step=0.1),), (0.0, 0.5, 1.0))"),
    ("seek check", "seek_check((Fold('x', 0.0, lambda c: c.value + c.index, step=0.1),), (0.0, 0.55, 0.3, 1.0, 0.3))"),
    ("gather form swaps",
     "time_fold_at((Fold('a', 1.0, lambda c: c.read('b'), step=1.0), Fold('b', 2.0, lambda c: c.read('a'), step=1.0)), 1.0)"),
    ("gather form swaps back",
     "time_fold_at((Fold('a', 1.0, lambda c: c.read('b'), step=1.0), Fold('b', 2.0, lambda c: c.read('a'), step=1.0)), 2.0)"),
    ("different steps are an error",
     "raises(lambda: time_fold_at((Fold('a', 0.0, lambda c: c.value, step=1.0), Fold('b', 0.0, lambda c: c.value, step=0.5)), 1.0))"),
    ("unknown read is an error", "raises(lambda: fold_value(Fold('a', 0.0, lambda c: c.read('zz'), step=1.0), 1.0))"),
    ("step and count together are an error", "raises(lambda: Fold('x', 0.0, lambda c: c.value, step=1.0, count=3))"),
    ("draw", "draw(7, 0, 3, 1)"),
    ("draw in the unit interval", "0.0 <= draw(1, 2, 3, 4) < 1.0"),
    ("draw depends on the step", "draw(1, 2, 3, 4) != draw(1, 2, 4, 4)"),
    ("random by step index", "rand(1, 5, 0)"),
    ("index fold sum", "index_fold(0.0, 10, lambda c: c.value + c.index)"),
    ("index fold count", "index_fold(0.0, 4, lambda c: c.value + 1.0 / c.count)"),
    ("index fold frame time", "index_fold(0.0, 3, lambda c: c.time, t=2.5)"),
    ("count bound", "raises(lambda: index_fold(0.0, 1000001, lambda c: c.value))"),
    ("fourier centre at the signal frequency",
     "tuple(round(v, 9) + 0.0 for v in fourier_centre(lambda tau: math.cos(math.tau * 3.0 * tau), 3.0, 400, 4.0))"),
    ("fourier centre off frequency",
     "tuple(round(v, 9) + 0.0 for v in fourier_centre(lambda tau: math.cos(math.tau * 3.0 * tau), 2.0, 400, 4.0))"),
    ("einstein solid after 20 steps", "einstein_solid((3.0, 0.0, 0.0, 0.0), 20, 1)"),
    ("einstein solid conserves", "sum(einstein_solid((3.0, 0.0, 0.0, 0.0), 500, 1))"),
    ("einstein solid by seed", "einstein_solid((3.0, 0.0, 0.0, 0.0), 20, 1) != einstein_solid((3.0, 0.0, 0.0, 0.0), 20, 2)"),
    ("einstein solid seek check", "seek_check(einstein_folds((3.0, 0.0, 0.0, 0.0), 1), (0.5, 0.2, 1.0, 0.2))"),
]


def _fmt(v):
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k!r}: {_fmt(x)}" for k, x in v.items()) + "}"
    return repr(v)


def main():
    scope = {k: v for k, v in globals().items() if not k.startswith("_")}
    scope["math"] = math
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "sum": sum, "all": all,
                             "max": max, "min": min}
    print("| Test | Expression | Expected |")
    print("|---|---|---|")
    for name, expr in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, scope))}` |")   # one scope: lambdas see the globals


if __name__ == "__main__":
    main()
