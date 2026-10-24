#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add agent behaviours" (srep/srep-0000-agents.md), CL3 of
SREP 12: a seeded population of kinds on the rim of an arena that, each day, runs for the day's pellets,
races for them (the first arrival eats, up to `meals` a day, shared by up to two claimants with a payoff table), eats, survives
and reproduces by its food and two draws, mutates its speed, and exposes live counts. Standard library only.
`main()` prints the SREP's numeric table.

The D24 hash functions are copied from random_streams_reference.py so that this module stands alone.
"""
import math
import zlib
from collections import namedtuple

MAX_AGENTS = 100_000
MAX_PELLETS = 100_000
MAX_DAYS = 1_000_000
MAX_MEALS = 16
EPS = 1e-9

# stream purposes (the random-streams draft, section 5)
P_HOME = 0
P_FOOD = 1
P_SURVIVE = 2
P_REPRODUCE = 3
P_MUTATE = 4

# --- D24 (random streams) ----------------------------------------------------------------------------------

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1
PHI = 0x9E3779B97F4A7C15


def u64(x):
    return x & MASK64


def mix64(z):
    z = u64(z)
    z = u64((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9)
    z = u64((z ^ (z >> 27)) * 0x94D049BB133111EB)
    return z ^ (z >> 31)


def splitmix64(x):
    return mix64(u64(x) + PHI)


def H(seed, channel, index):
    """The lattice hash H(s, c, i) = splitmix64(s xor splitmix64(c xor splitmix64(i)))."""
    return splitmix64(u64(seed) ^ splitmix64(u64(channel) ^ splitmix64(u64(index))))


def U(seed, channel, index):
    return (H(seed, channel, index) >> 11) * (1.0 / (1 << 53))


def S(element_seed, purpose, step, index):
    """The stream draw S(e, p, t, i) = U(e, p + t 2^32, i)."""
    if not 0 <= purpose <= MASK32 or not 0 <= step <= MASK32:
        raise ValueError("purpose and step are integers in [0, 2^32)")
    return U(element_seed, purpose + (step << 32), index)


def S_signed(element_seed, purpose, step, index):
    return S(element_seed, purpose, step, index) * 2.0 - 1.0


def E(project, element_id, seed, purpose):
    """The element seed: CRC-32 of "project:id:seed:purpose" (D24 section 4)."""
    s = "" if seed is None else str(u64(seed))
    return zlib.crc32(f"{u64(project)}:{element_id}:{s}:{purpose}".encode("utf-8")) & 0xFFFFFFFF


# --- the spec ---------------------------------------------------------------------------------------------------

Agent = namedtuple("Agent", "kind x y speed")


class Spec:
    """The agents node's attributes and children, validated."""

    def __init__(self, count, seed=0, project=0, id="agents", width=100.0, height=100.0, speed=10.0, pellets=1,
                 units=1.0, share=1, meals=2, kinds=(("blob", 1.0),), payoffs=(), mutation=0.0, min_speed=1.0,
                 max_speed=1000.0):
        if not 1 <= count <= MAX_AGENTS:
            raise ValueError(f"count is 1 to {MAX_AGENTS}")
        if not 1 <= pellets <= MAX_PELLETS:
            raise ValueError(f"pellets is 1 to {MAX_PELLETS}")
        if share not in (1, 2):
            raise ValueError("share is 1 or 2")
        if not 1 <= meals <= MAX_MEALS:
            raise ValueError(f"meals is 1 to {MAX_MEALS}")
        if not units > 0.0 or not speed > 0.0 or not width > 0.0 or not height > 0.0:
            raise ValueError("units, speed, width and height are positive")
        if not kinds:
            raise ValueError("at least one kind")
        names = [k for k, _ in kinds]
        if len(set(names)) != len(names):
            raise ValueError("kind names are unique")
        if any(s < 0.0 for _, s in kinds) or abs(sum(s for _, s in kinds) - 1.0) > 1e-9:
            raise ValueError("kind shares are not negative and sum to 1")
        if mutation < 0.0:
            raise ValueError("mutation is not negative")
        if not 0.0 < min_speed <= max_speed:
            raise ValueError("0 < minSpeed <= maxSpeed")
        table = {}
        for (a, b), (fa, fb) in payoffs:
            if a not in names or b not in names:
                raise ValueError("payoffs name kinds")
            if fa < 0.0 or fb < 0.0:
                raise ValueError("payoff food is not negative")
            table[(a, b)] = (float(fa), float(fb))
            table.setdefault((b, a), (float(fb), float(fa)))
        self.count, self.seed, self.project, self.id = count, seed, project, id
        self.width, self.height, self.speed, self.pellets = float(width), float(height), float(speed), pellets
        self.units, self.share, self.meals = float(units), share, meals
        self.kinds = tuple((k, float(s)) for k, s in kinds)
        self.payoffs = table
        self.mutation, self.min_speed, self.max_speed = float(mutation), float(min_speed), float(max_speed)


def element_seed(spec):
    return E(spec.project, spec.id, spec.seed, "agents")


def kind_of(i, count, kinds):
    """The kind of agent i of count: the kind whose cumulative share bracket holds (i + 1/2) / count."""
    if not 0 <= i < count:
        raise ValueError("the index is below the count")
    u = (i + 0.5) / count
    acc = 0.0
    for name, share in kinds:
        acc += share
        if u < acc + EPS:
            return name
    return kinds[-1][0]


def rim_point(u, width, height):
    """The point at fraction u of the perimeter, clockwise from the origin: top, right, bottom, left edges."""
    if not 0.0 <= u < 1.0:
        raise ValueError("u is in [0, 1)")
    d = u * 2.0 * (width + height)
    if d < width:
        return (d, 0.0)
    d -= width
    if d < height:
        return (width, d)
    d -= height
    if d < width:
        return (width - d, height)
    d -= width
    return (0.0, height - d)


def init(spec):
    """The population at the start: kinds by share, homes on the rim by the day-0 home stream, cruise speed."""
    e = element_seed(spec)
    out = []
    for i in range(spec.count):
        x, y = rim_point(S(e, P_HOME, 0, i), spec.width, spec.height)
        out.append(Agent(kind_of(i, spec.count, spec.kinds), x, y, spec.speed))
    return tuple(out)


def pellets(spec, k):
    """The day's pellets, uniform in the arena from the food stream of day k."""
    e = element_seed(spec)
    return tuple((S(e, P_FOOD, k, 2 * j) * spec.width, S(e, P_FOOD, k, 2 * j + 1) * spec.height)
                 for j in range(spec.pellets))


# --- claims -----------------------------------------------------------------------------------------------------

def claims(positions, speeds, pellets_, share, meals):
    """The day's race, as events in time. Every agent heads for the free pellet it would reach first (ties to
    the lower pellet index); the earliest arrival (ties to the lower agent index) eats, and heads for its next
    pellet unless it has had `meals`; when a pellet is full, the agents heading for it turn, from where they
    are at that moment, toward their next pellet; the day ends when nobody has a pellet to reach. Returns the
    claimed pellet indices per agent and the claimant indices per pellet."""
    n = len(positions)
    if len(speeds) != n:
        raise ValueError("one speed per agent")
    if any(not s > 0.0 for s in speeds):
        raise ValueError("speeds are positive")
    pos = [tuple(p) for p in positions]
    clock = [0.0] * n
    eaten = [0] * n
    per_agent = [[] for _ in range(n)]
    per_pellet = [[] for _ in pellets_]

    def pick(i):
        if eaten[i] >= meals:
            return None
        best = None
        for j, claimants in enumerate(per_pellet):
            if len(claimants) >= share:
                continue
            d = math.hypot(pellets_[j][0] - pos[i][0], pellets_[j][1] - pos[i][1])
            t = clock[i] + d / speeds[i]
            if best is None or t < best[0] - EPS:
                best = (t, j)
        return best

    target = [pick(i) for i in range(n)]
    for _ in range(n * max(len(pellets_), 1) * max(meals, 1) + 1):
        events = [(t, i) for i, tj in enumerate(target) if tj is not None for t, _ in (tj,)]
        if not events:
            break
        ta, i = min(events)
        j = target[i][1]
        per_pellet[j].append(i)
        per_agent[i].append(j)
        pos[i] = tuple(pellets_[j])
        clock[i] = ta
        eaten[i] += 1
        if len(per_pellet[j]) >= share:
            for a in range(n):
                if a != i and target[a] is not None and target[a][1] == j:
                    pos[a] = _toward(pos[a], pellets_[j], speeds[a] * (ta - clock[a]))
                    clock[a] = ta
                    target[a] = pick(a)
        target[i] = pick(i)
    return tuple(tuple(c) for c in per_agent), tuple(tuple(c) for c in per_pellet)


def _toward(p, q, distance):
    """p moved `distance` toward q, never past it."""
    d = math.hypot(q[0] - p[0], q[1] - p[1])
    if d <= distance or d == 0.0:
        return tuple(q)
    t = distance / d
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


# --- food and fate ----------------------------------------------------------------------------------------------

def payoff(spec, kind_a, kind_b):
    """The food of two claimants of one pellet: the payoff table, or an equal split of the pellet's units."""
    names = [k for k, _ in spec.kinds]
    if kind_a not in names or kind_b not in names:
        raise ValueError("unknown kind")
    return spec.payoffs.get((kind_a, kind_b), (spec.units / 2.0, spec.units / 2.0))


def food(spec, kinds, per_pellet):
    """Food per agent: a sole claimant eats the pellet's units; two claimants take the payoff."""
    out = [0.0] * len(kinds)
    for claimants in per_pellet:
        if len(claimants) == 1:
            out[claimants[0]] += spec.units
        elif len(claimants) == 2:
            a, b = claimants
            fa, fb = payoff(spec, kinds[a], kinds[b])
            out[a] += fa
            out[b] += fb
        elif len(claimants) > 2:
            raise ValueError("at most two claimants")
    return tuple(out)


def fate(food_, draw_survive, draw_reproduce):
    """(survives, children): survives when food >= 1 or the draw is below the food; children are
    floor(food - 1) plus one more when the draw is below the fraction of food - 1."""
    if food_ < 0.0:
        raise ValueError("food is not negative")
    survives = food_ >= 1.0 or draw_survive < food_
    if not survives:
        return (False, 0)
    extra = food_ - 1.0
    whole = int(math.floor(extra + EPS))
    frac = extra - whole
    return (True, whole + (1 if frac > EPS and draw_reproduce < frac else 0))


def mutated_speed(parent_speed, mutation, min_speed, max_speed, e, k, child_index):
    """parent speed * (1 + mutation * S_signed(e, P_MUTATE, k, child)), clamped to [minSpeed, maxSpeed]."""
    if mutation == 0.0:
        return parent_speed
    s = parent_speed * (1.0 + mutation * S_signed(e, P_MUTATE, k, child_index))
    return min(max(s, min_speed), max_speed)


# --- the day ----------------------------------------------------------------------------------------------------

def grow_check(n):
    if n > MAX_AGENTS:
        raise ValueError(f"the population would exceed {MAX_AGENTS}")


def day_report(spec, agents, k):
    """Day k in full: pellets, claims, food, fates and the next day's population."""
    if not 0 <= k <= MAX_DAYS:
        raise ValueError(f"days are 0 to {MAX_DAYS}")
    e = element_seed(spec)
    pel = pellets(spec, k)
    kinds = [a.kind for a in agents]
    per_agent, per_pellet = claims([(a.x, a.y) for a in agents], [a.speed for a in agents], pel, spec.share,
                                   spec.meals)
    foods = food(spec, kinds, per_pellet)
    fates = tuple(fate(f, S(e, P_SURVIVE, k, i), S(e, P_REPRODUCE, k, i)) for i, f in enumerate(foods))
    survivors = [a for a, (alive, _) in zip(agents, fates) if alive]
    children = []
    for a, (alive, c) in zip(agents, fates):
        for _ in range(c):
            children.append(Agent(a.kind, a.x, a.y, mutated_speed(a.speed, spec.mutation, spec.min_speed,
                                                                 spec.max_speed, e, k, len(children))))
    grow_check(len(survivors) + len(children))
    nxt = []
    for i, a in enumerate(survivors + children):
        x, y = rim_point(S(e, P_HOME, k + 1, i), spec.width, spec.height)
        nxt.append(Agent(a.kind, x, y, a.speed))
    return {"pellets": pel, "claims": per_agent, "per_pellet": per_pellet, "food": foods, "fate": fates,
            "next": tuple(nxt)}


def day(spec, agents, k):
    """The population after day k, from the population before it."""
    if not agents:
        return ()
    return day_report(spec, agents, k)["next"]


def run(spec, days):
    """The population after `days` days from the start."""
    if not 0 <= days <= MAX_DAYS:
        raise ValueError(f"days are 0 to {MAX_DAYS}")
    agents = init(spec)
    for k in range(days):
        agents = day(spec, agents, k)
    return agents


def counts(agents):
    out = {}
    for a in agents:
        out[a.kind] = out.get(a.kind, 0) + 1
    return out


def count(agents, kind=None):
    return len(agents) if kind is None else sum(1 for a in agents if a.kind == kind)


def mean_speed(agents):
    return sum(a.speed for a in agents) / len(agents) if agents else 0.0


# --- the path ---------------------------------------------------------------------------------------------------

def day_path(home, claimed):
    """home -> each claimed pellet in order -> home; a home alone when nothing was claimed."""
    home = tuple(home)
    if not claimed:
        return (home,)
    return (home,) + tuple(tuple(p) for p in claimed) + (home,)


def path_length(path):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))


def along(path, distance):
    """The point at `distance` along the polyline, the end beyond its length."""
    if distance < 0.0:
        raise ValueError("distance is not negative")
    for a, b in zip(path, path[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if distance <= seg:
            if seg == 0.0:
                return tuple(a)
            t = distance / seg
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        distance -= seg
    return tuple(path[-1])


def position_at(home, claimed, speed, u):
    """Where an agent of `speed` is `u` seconds into its day."""
    return along(day_path(home, claimed), speed * u)


# --- table ------------------------------------------------------------------------------------------------------

def raises(f):
    try:
        f()
    except (ValueError, TypeError, IndexError, ZeroDivisionError, KeyError):
        return True
    return False


HAWK_DOVE = ((("hawk", "dove"), (1.5, 0.5)), (("hawk", "hawk"), (0.0, 0.0)), (("dove", "dove"), (1.0, 1.0)))
SEL = Spec(count=6, seed=1, width=100.0, height=100.0, speed=10.0, pellets=4, units=1.0, share=1, meals=2)
AGG = Spec(count=6, seed=2, width=100.0, height=100.0, speed=10.0, pellets=3, units=2.0, share=2, meals=1,
           kinds=(("hawk", 0.5), ("dove", 0.5)), payoffs=HAWK_DOVE)
LINE = ((0.0, 0.0), (10.0, 0.0))
TWO = ((4.0, 0.0), (20.0, 0.0))

TABLE = [
    ("element seed", 'element_seed(Spec(count=6, seed=1, project=0, id="agents"))', 'E(0, "agents", 1, "agents")'),
    ("kinds by share", '[kind_of(i, 4, (("a", 0.25), ("b", 0.75))) for i in range(4)]', "['a', 'b', 'b', 'b']"),
    ("rim quarter", "rim_point(0.25, 100.0, 100.0)", "(100.0, 0.0)"),
    ("rim nine tenths", "rim_point(0.9, 100.0, 100.0)", "(0.0, 40.0)"),
    ("initial kinds", "[a.kind for a in init(AGG)]", "['hawk', 'hawk', 'hawk', 'dove', 'dove', 'dove']"),
    ("initial homes on the rim", "all(a.x in (0.0, 100.0) or a.y in (0.0, 100.0) for a in init(SEL))", "True"),
    ("pellets per day", "len(pellets(SEL, 0))", "4"),
    ("pellets differ by day", "pellets(SEL, 0) != pellets(SEL, 1)", "True"),
    ("claims by arrival", "claims(LINE, (1.0, 1.0), TWO, 1, 2)", "(((0,), (1,)), ((0,), (1,)))"),
    ("a fast agent takes both", "claims(LINE, (10.0, 1.0), TWO, 1, 2)[0]", "((0, 1), ())"),
    ("ties to the lower index", "claims(((0.0, 0.0), (8.0, 0.0)), (1.0, 1.0), ((4.0, 0.0),), 1, 1)[0]", "((0,), ())"),
    ("two share a pellet", "claims(((0.0, 0.0), (10.0, 0.0), (50.0, 50.0)), (1.0, 1.0, 1.0), ((5.0, 0.0),), 2, 1)[1]", "((0, 1),)"),
    ("one meal each", "claims(LINE, (1.0, 1.0), TWO + ((40.0, 0.0),), 1, 1)[1]", "((0,), (1,), ())"),
    ("the loser turns from where it is", "claims(LINE, (1.0, 1.0), TWO + ((40.0, 0.0),), 1, 5)", "(((0,), (1, 2)), ((0,), (1,), (1,)))"),
    ("sole claimant eats the units", 'food(AGG, ("hawk", "dove"), ((1,),))', "(0.0, 2.0)"),
    ("hawk and dove payoff", 'payoff(AGG, "hawk", "dove")', "(1.5, 0.5)"),
    ("dove and hawk payoff", 'payoff(AGG, "dove", "hawk")', "(0.5, 1.5)"),
    ("two hawks", 'payoff(AGG, "hawk", "hawk")', "(0.0, 0.0)"),
    ("equal split without a table", 'payoff(Spec(count=2, units=2.0, kinds=(("a", 0.5), ("b", 0.5))), "a", "b")', "(1.0, 1.0)"),
    ("fate starving", "fate(0.0, 0.0, 0.0)", "(False, 0)"),
    ("fate fed", "fate(1.0, 0.99, 0.99)", "(True, 0)"),
    ("fate fed twice", "fate(2.0, 0.99, 0.99)", "(True, 1)"),
    ("fate half fed survives", "fate(0.5, 0.4, 0.0)", "(True, 0)"),
    ("fate half fed dies", "fate(0.5, 0.6, 0.0)", "(False, 0)"),
    ("fate one and a half", "(fate(1.5, 0.0, 0.4), fate(1.5, 0.0, 0.6))", "((True, 1), (True, 0))"),
    ("no mutation", "mutated_speed(10.0, 0.0, 1.0, 100.0, 12345, 3, 0)", "10.0"),
    ("mutation by the signed draw", "round(mutated_speed(10.0, 0.2, 1.0, 100.0, 12345, 3, 0), 12)", "round(10.0 * (1.0 + 0.2 * S_signed(12345, P_MUTATE, 3, 0)), 12)"),
    ("day 0 population", "len(day(SEL, init(SEL), 0))", "len([f for f in day_report(SEL, init(SEL), 0)['food'] if f >= 1.0]) + sum(max(0, int(f) - 1) for f in day_report(SEL, init(SEL), 0)['food'])"),
    ("day is pure", "day(SEL, init(SEL), 0) == day(SEL, init(SEL), 0)", "True"),
    ("seeded populations reproduce exactly", "counts(run(SEL, 10)) == counts(run(SEL, 10))", "True"),
    ("frame alone equals frame played", "run(AGG, 5) == day(AGG, run(AGG, 4), 4)", "True"),
    ("counts at the start", "counts(init(AGG))", "{'hawk': 3, 'dove': 3}"),
    ("count of a kind", '(count(init(AGG), "dove"), count(init(AGG), "owl"))', "(3, 0)"),
    ("mean speed", "mean_speed(init(SEL))", "10.0"),
    ("empty population", "(day(SEL, (), 0), counts(()), mean_speed(()))", "((), {}, 0.0)"),
    ("day path", "day_path((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0)))", "((0.0, 0.0), (3.0, 0.0), (3.0, 4.0), (0.0, 0.0))"),
    ("day path length", "path_length(day_path((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0))))", "12.0"),
    ("along the path", "along(day_path((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0))), 5.0)", "(3.0, 2.0)"),
    ("position within the day", "position_at((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0)), 2.0, 2.5)", "(3.0, 2.0)"),
    ("home after the day", "along(day_path((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0))), 50.0)", "(0.0, 0.0)"),
    ("too many days", "raises(lambda: run(SEL, MAX_DAYS + 1))", "True"),
    ("three claimants are an error", 'raises(lambda: food(AGG, ("hawk", "dove", "hawk"), ((0, 1, 2),)))', "True"),
    ("shares must sum to 1", 'raises(lambda: Spec(count=2, kinds=(("a", 0.5), ("b", 0.4))))', "True"),
]


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["__builtins__"] = {"round": round, "tuple": tuple, "len": len, "sorted": sorted, "min": min, "max": max,
                         "abs": abs, "range": range, "list": list, "set": set, "dict": dict, "True": True,
                         "False": False, "None": None, "any": any, "all": all, "int": int, "float": float,
                         "sum": sum, "ValueError": ValueError}
    return s


def _same(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    return a == b


def main():
    s = scope()
    for name, expr, expected in TABLE:
        got = eval(expr, s)
        want = eval(expected, s)
        if got != want and not _same(got, want):
            raise SystemExit(f"{name}: {got!r} != {want!r}")
        print(f"| {name} | `{expr}` | `{expected}` |")


if __name__ == "__main__":
    main()
