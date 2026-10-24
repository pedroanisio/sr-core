#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add tagged formula parts and shape morphing"
(srep/srep-0000-semantic-tex.md; MF3 of SREP 12): the \\part{name}{...} tag of the TeX subset, the matching of
parts between two formulas, the motion of a matched part and the fading of an unmatched one, and the morph of a
path into another: arc-length resampling, start alignment, sub-path matching and linear interpolation, with the
self-intersection count the kit uses. Standard library only.

    python3 semantic_tex_reference.py        # prints the SREP's numeric-test table

Every function is a pure function of its arguments. Section numbers refer to the SREP's Semantics.
"""
import math
import re
from dataclasses import dataclass

MORPH_SAMPLES = 64          # samples per sub-path of a morph (rule 8)
NMTOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")


# ------------------------------------------------------------------------------------------- 1. tagged parts

@dataclass(frozen=True)
class Part:
    """A tagged part: its name, its TeX (the group's content, tags included), its nesting depth and its index
    among the parts in order of their opening tag."""
    name: str
    tex: str
    depth: int
    index: int


def _group_end(s, i):
    """The index just past the group that opens at s[i] == '{', honouring nesting and backslash escapes."""
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ValueError("unclosed group")


def _scan(s):
    """Yields (name, start, body_start, end) for every \\part{name}{body} in s, outermost first by position."""
    i = 0
    while True:
        i = s.find("\\part{", i)
        if i < 0:
            return
        name_end = _group_end(s, i + 5)
        name = s[i + 6:name_end - 1]
        if not NMTOKEN.match(name):
            raise ValueError(f"part name {name!r} is not an NMTOKEN")
        if name_end >= len(s) or s[name_end] != "{":
            raise ValueError(f"part {name!r} has no body group")
        end = _group_end(s, name_end)
        yield name, i, name_end + 1, end
        i = name_end + 1          # continue inside the body, so nested parts are found


def parts(tex):
    """Rule 1: the tagged parts of a formula, in order of their opening tag, with their depth. Names are NMTOKENs
    and unique in the formula; a tag without its two groups, an unclosed group or a stray closing brace is an
    error."""
    # a stray closing brace anywhere is an error: count braces outside escapes
    depth = 0
    j = 0
    while j < len(tex):
        if tex[j] == "\\":
            j += 2
            continue
        depth += {"{": 1, "}": -1}.get(tex[j], 0)
        if depth < 0:
            raise ValueError("stray closing brace")
        j += 1
    if depth != 0:
        raise ValueError("unclosed group")
    found = list(_scan(tex))
    names = [f[0] for f in found]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ValueError(f"duplicate part names: {sorted(dup)}")
    out = []
    for k, (name, start, body_start, end) in enumerate(found):
        depth = sum(1 for (_, s2, b2, e2) in found if s2 < start and e2 >= end)
        out.append(Part(name, tex[body_start:end - 1], depth, k))
    return tuple(out)


def strip_parts(tex):
    """Rule 1: the formula the typesetter sees: every \\part{name}{body} replaced by {body}, so the part is a
    plain group with the same layout."""
    parts(tex)        # validates
    while True:
        i = tex.find("\\part{")
        if i < 0:
            return tex
        name_end = _group_end(tex, i + 5)
        tex = tex[:i] + tex[name_end:]


# ------------------------------------------------------------------------------------------------ 2. matching

@dataclass(frozen=True)
class Matching:
    """matched: (source name, target name, source tex, target tex)... as (name_a, name_b, tex_a, tex_b) is too
    wide for a table; the tuple holds (name, tex_a, tex_b) by name and (name_a, name_b, tex) by tex.
    out: source parts with no partner; incoming: target parts with no partner."""
    matched: tuple
    out: tuple
    incoming: tuple


def _norm(tex):
    return re.sub(r"\s+", "", tex)


def match_parts(a, b, by="name"):
    """Rule 2: by="name" pairs the parts with the same name; by="tex" pairs, in order, parts whose TeX is the
    same up to whitespace, each part at most once. The rest are out (from a) or incoming (to b)."""
    if by not in ("name", "tex"):
        raise ValueError("by: name or tex")
    matched, used = [], set()
    if by == "name":
        bn = {p.name: p for p in b}
        for p in a:
            if p.name in bn:
                matched.append((p.name, p.tex, bn[p.name].tex))
                used.add(p.name)
        out = tuple(p.name for p in a if p.name not in used)
        incoming = tuple(p.name for p in b if p.name not in used)
    else:
        taken = set()
        for p in a:
            for q in b:
                if q.name not in taken and _norm(q.tex) == _norm(p.tex):
                    matched.append((p.name, q.name, p.tex))
                    used.add(p.name)
                    taken.add(q.name)
                    break
        out = tuple(p.name for p in a if p.name not in used)
        incoming = tuple(q.name for q in b if q.name not in taken)
    return Matching(tuple(matched), out, incoming)


def pair_kind(tex_a, tex_b):
    """Rule 3: a matched pair with the same TeX (up to whitespace) moves; one with different TeX morphs."""
    return "move" if _norm(tex_a) == _norm(tex_b) else "morph"


# -------------------------------------------------------------------------------- 3 and 4. boxes and fades

@dataclass(frozen=True)
class Box:
    """A part's box in the formula image: top-left x, y and size, pixels."""
    x: float
    y: float
    w: float
    h: float


def _clamp(p):
    return min(1.0, max(0.0, float(p)))


def box_at(a, b, p):
    """Rule 3: the box of a matched part at progress p: centre and size interpolated linearly."""
    p = _clamp(p)
    ca = (a.x + a.w / 2, a.y + a.h / 2)
    cb = (b.x + b.w / 2, b.y + b.h / 2)
    w = a.w + (b.w - a.w) * p
    h = a.h + (b.h - a.h) * p
    cx = ca[0] + (cb[0] - ca[0]) * p
    cy = ca[1] + (cb[1] - ca[1]) * p
    return Box(cx - w / 2, cy - h / 2, w, h)


def part_transform(a, b, p):
    """Rule 3: the translation of the part's centre and the uniform scale (by height) that carry the source
    part's glyphs to the box of rule 3 at progress p."""
    if not (a.w > 0 and a.h > 0 and b.w > 0 and b.h > 0):
        raise ValueError("part boxes have positive size")
    p = _clamp(p)
    ca = (a.x + a.w / 2, a.y + a.h / 2)
    cb = (b.x + b.w / 2, b.y + b.h / 2)
    s = 1.0 + (b.h / a.h - 1.0) * p
    return ((cb[0] - ca[0]) * p, (cb[1] - ca[1]) * p, s)


def opacity_out(p):
    """Rule 4: an unmatched source part keeps its place and fades: opacity 1 − p."""
    return 1.0 - _clamp(p)


def opacity_in(p):
    """Rule 4: an unmatched target part appears in its place: opacity p."""
    return _clamp(p)


# ------------------------------------------------------------------------------------------ 5. polygons

def signed_area(poly):
    """Twice the shoelace sum halved: positive for a counter-clockwise polygon in a y-up frame (clockwise on
    screen, where y is down)."""
    n = len(poly)
    return sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n)) / 2


def centroid(poly):
    """The area centroid; the mean of the vertices when the area is 0."""
    a = signed_area(poly)
    n = len(poly)
    if abs(a) < 1e-12:
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    cx = cy = 0.0
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    return (cx / (6 * a), cy / (6 * a))


def perimeter(poly):
    n = len(poly)
    return sum(math.dist(poly[i], poly[(i + 1) % n]) for i in range(n))


def resample(poly, n):
    """Rule 6: n points evenly spaced by arc length around the closed polygon, the first at the first vertex,
    in the polygon's own direction."""
    if n < 3:
        raise ValueError("samples: at least 3")
    total = perimeter(poly)
    if total <= 0:
        raise ValueError("polygon: zero perimeter")
    m = len(poly)
    out = []
    step = total / n
    edge, pos, acc = 0, 0.0, 0.0          # edge index and distance along it
    for k in range(n):
        target = k * step
        while True:
            a, b = poly[edge % m], poly[(edge + 1) % m]
            length = math.dist(a, b)
            if acc + length >= target - 1e-12 * total or edge >= 2 * m:
                t = 0.0 if length == 0 else (target - acc) / length
                t = min(1.0, max(0.0, t))
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                break
            acc += length
            edge += 1
    return tuple(out)


def _segments_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


def self_intersections(poly):
    """The number of pairs of non-adjacent edges that properly cross (the kit's mid-morph check)."""
    n = len(poly)
    count = 0
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_cross(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                count += 1
    return count


# ------------------------------------------------------------------------------- 7. alignment and morph

def rotate(poly, k):
    """poly started k vertices later: rotate(poly, k)[i] = poly[(i + k) % n]."""
    n = len(poly)
    return tuple(poly[(i + k) % n] for i in range(n))


def align_start(a, b):
    """Rule 7: the rotation k of b (same count as a) that minimises Σ|a_i − b_{(i+k) mod n}|²; the smallest k
    on a tie."""
    n = len(a)
    if len(b) != n:
        raise ValueError("align: equal sample counts")
    best, best_k = None, 0
    for k in range(n):
        cost = sum((a[i][0] - b[(i + k) % n][0]) ** 2 + (a[i][1] - b[(i + k) % n][1]) ** 2 for i in range(n))
        if best is None or cost < best - 1e-12:
            best, best_k = cost, k
    return best_k


def align(a, b):
    """Rule 7: b reversed when its winding differs from a's (keeping its first vertex first), then rotated by
    align_start."""
    if len(a) != len(b):
        raise ValueError("align: equal sample counts")
    if signed_area(a) * signed_area(b) < 0:
        b = (b[0],) + tuple(reversed(b[1:]))
    return rotate(b, align_start(a, b))


def morph_polygon(a, b, p, n=MORPH_SAMPLES):
    """Rule 8: a resampled to n, b resampled to n and aligned to a, and the point-wise linear interpolation at
    progress p; exactly a's samples at 0 and b's aligned samples at 1."""
    p = _clamp(p)
    ra = resample(a, n)
    rb = align(ra, resample(b, n))
    if p == 0.0:
        return ra
    if p == 1.0:
        return rb
    return tuple((q[0] + (r[0] - q[0]) * p, q[1] + (r[1] - q[1]) * p) for q, r in zip(ra, rb))


def match_subpaths(A, B):
    """Rule 9: the sub-paths of A and B paired greedily by nearest centroids (the closest pair first); a sub-path
    left over is paired with None and collapses to, or grows from, the centroid of the nearest sub-path of the
    other path. The result lists A's sub-paths in order, then B's unpaired ones as (None, j)."""
    if not A or not B:
        raise ValueError("paths: at least one sub-path each")
    ca = [centroid(s) for s in A]
    cb = [centroid(s) for s in B]
    cand = sorted(((math.dist(ca[i], cb[j]), i, j) for i in range(len(A)) for j in range(len(B))))
    pa, pb = {}, {}
    for _, i, j in cand:
        if i not in pa and j not in pb:
            pa[i], pb[j] = j, i
    out = [(i, pa.get(i)) for i in range(len(A))]
    out += [(None, j) for j in range(len(B)) if j not in pb]
    return tuple(out)


def _nearest(c, centroids):
    return min(range(len(centroids)), key=lambda k: (math.dist(c, centroids[k]), k))


def morph_path(A, B, p, n=MORPH_SAMPLES):
    """Rule 9: every pair of rule 9's matching morphed by rule 8; an unpaired sub-path of A morphs to the point
    at the centroid of B's nearest sub-path, and an unpaired sub-path of B grows from the centroid of A's
    nearest sub-path."""
    pairs = match_subpaths(A, B)
    ca = [centroid(s) for s in A]
    cb = [centroid(s) for s in B]
    p = _clamp(p)
    out = []
    for i, j in pairs:
        if i is not None and j is not None:
            out.append(morph_polygon(A[i], B[j], p, n))
        elif j is None:
            ra = resample(A[i], n)
            c = cb[_nearest(ca[i], cb)]
            out.append(tuple((q[0] + (c[0] - q[0]) * p, q[1] + (c[1] - q[1]) * p) for q in ra))
        else:
            rb = resample(B[j], n)
            c = ca[_nearest(cb[j], ca)]
            out.append(tuple((c[0] + (q[0] - c[0]) * p, c[1] + (q[1] - c[1]) * p) for q in rb))
    return tuple(out)


# -------------------------------------------------------------------------------------- the numeric table

SQ = "((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))"
TRI = "((0.0, 0.0), (10.0, 0.0), (5.0, 8.0))"
BOW = "((0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0))"
EQ = r"'\\part{lhs}{E} = \\part{rhs}{m c^2}'"
NEST = r"'\\part{f}{\\frac{\\part{n}{a}}{\\part{d}{b}}}'"
A3 = r"'\\part{a}{x} + \\part{b}{y} = \\part{c}{z}'"
B3 = r"'\\part{c}{z} - \\part{b}{y} = \\part{d}{w}'"
TABLE = [
    ("part names", f"tuple(p.name for p in parts({EQ}))"),
    ("part tex", f"tuple(p.tex for p in parts({EQ}))"),
    ("nested part depths", f"tuple((p.name, p.depth) for p in parts({NEST}))"),
    ("outer part tex", f"parts({NEST})[0].tex"),
    ("no parts", r"parts('\\sqrt{x^2 + y^2}')"),
    ("strip parts", f"strip_parts({EQ})"),
    ("strip nested parts", f"strip_parts({NEST})"),
    ("match by name", f"match_parts(parts({A3}), parts({B3})).matched"),
    ("match out and incoming", f"(match_parts(parts({A3}), parts({B3})).out, match_parts(parts({A3}), parts({B3})).incoming)"),
    ("match by tex", r"match_parts(parts('\\part{p}{x^2} + \\part{q}{2x} + \\part{r}{x^2}'), parts('\\part{u}{x^2} + \\part{v}{x^2}'), by='tex').matched"),
    ("pair kinds", "(pair_kind('x ^ 2', 'x^2'), pair_kind('x^2', 'y^2'))"),
    ("box midway", "box_at(Box(10.0, 20.0, 40.0, 10.0), Box(100.0, 50.0, 80.0, 20.0), 0.5)"),
    ("part transform midway", "part_transform(Box(0.0, 0.0, 20.0, 10.0), Box(100.0, 100.0, 40.0, 20.0), 0.5)"),
    ("fades", "(opacity_out(0.25), opacity_in(0.25))"),
    ("signed area", f"(signed_area({SQ}), signed_area(tuple(reversed({SQ}))))"),
    ("centroid", f"centroid({TRI})"),
    ("perimeter", f"perimeter({SQ})"),
    ("resample a square", f"resample({SQ}, 8)"),
    ("resample a triangle", f"resample({TRI}, 6)"),
    ("self intersections", f"(self_intersections({SQ}), self_intersections({BOW}))"),
    ("align start", f"align_start(resample({SQ}, 8), rotate(resample({SQ}, 8), 2))"),
    ("align reverses", f"align(resample({SQ}, 8), tuple(reversed(resample({SQ}, 8)))) == resample({SQ}, 8)"),
    ("morph at 0", f"morph_polygon({SQ}, {TRI}, 0.0, 8) == resample({SQ}, 8)"),
    ("morph at 1", f"morph_polygon({SQ}, {TRI}, 1.0, 8) == align(resample({SQ}, 8), resample({TRI}, 8))"),
    ("morph midway", f"morph_polygon({SQ}, {TRI}, 0.5, 4)"),
    ("square to triangle crossings", f"max(self_intersections(morph_polygon({SQ}, {TRI}, p / 10, 64)) for p in (1, 2, 3, 4, 5, 6, 7, 8, 9))"),
    ("match subpaths", f"match_subpaths(({SQ}, tuple((x + 100.0, y) for x, y in {SQ})), (tuple((x + 100.0, y + 1.0) for x, y in {TRI}), tuple((x, y + 1.0) for x, y in {TRI})))"),
    ("extra subpath", f"match_subpaths(({SQ}, tuple((x + 100.0, y) for x, y in {SQ})), ({TRI},))"),
    ("incoming subpath", f"match_subpaths(({SQ},), ({TRI}, tuple((x + 100.0, y) for x, y in {TRI})))"),
    ("collapsed subpath", f"morph_path(({SQ}, tuple((x + 100.0, y) for x, y in {SQ})), ({TRI},), 1.0, 4)[1]"),
]


def main():
    scope = {k: v for k, v in globals().items() if not k.startswith("_")}
    scope["math"] = math
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "max": max, "reversed": reversed, "all": all}
    print("| Test | Expression | Expected |")
    print("|---|---|---|")
    for name, expr in TABLE:
        got = eval(expr, scope)
        print(f"| {name} | `{expr}` | `{got!r}` |")


if __name__ == "__main__":
    main()
