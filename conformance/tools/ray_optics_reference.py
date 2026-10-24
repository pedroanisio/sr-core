#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Add ray-optics diagrams" (srep/srep-0000-ray-optics.md, OW1 of
SREP 12).

Everything is a pure function over 2D points in the bench's pixel space (x right, y up on the bench; the axes
mapping of the draft turns them into frame pixels):

* Snell's law, total internal reflection, the Fresnel reflectances and Brewster's angle;
* thin lenses (slope_out = slope_in - h / f), thick lenses as two spherical surfaces (the lensmaker's equation,
  the principal planes, the traced paraxial focus), flat and spherical mirrors, prisms (minimum deviation),
  refracting blocks, GRIN slabs (the ray equation by RK4) and screens;
* non-sequential tracing (nearest hit among all elements) and sequential tracing (element order), with an
  optional Fresnel split into reflected and transmitted rays, a bounce bound and a power floor;
* image construction with the three principal rays of a thin lens;
* a keyed source angle as a pure function of the frame (the seek check).

Running the module prints the data rows of the draft's numeric table.
"""
import math

MODES = ("sequential", "nonSequential")
MAX_BOUNCES = 1024
MIN_DISTANCE = 1e-7
GRIN_STEP = 0.05
SEEK_FRAMES = 96
ELEMENT_KINDS = ("thin", "thick", "mirror", "sphericalMirror", "prism", "block", "grin", "screen")
SOURCE_KINDS = ("point", "parallel")


class OpticsError(ValueError):
    """A value outside the draft's domain."""


class TotalInternalReflection(OpticsError):
    """Snell's law has no real solution."""


# ------------------------------------------------------------------------------------ vectors


def norm(v):
    return math.hypot(v[0], v[1])


def unit(v):
    n = norm(v)
    if n == 0.0:
        raise OpticsError("a direction needs a non-zero vector")
    return (v[0] / n, v[1] / n)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, s):
    return (a[0] * s, a[1] * s)


def rot(v, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (c * v[0] - s * v[1], s * v[0] + c * v[1])


# ------------------------------------------------------------------------------------ Snell, TIR and Fresnel


def _indices(n1, n2):
    if not (n1 > 0.0 and n2 > 0.0):
        raise OpticsError("indices must be positive")


def snell(n1, n2, theta_i):
    """The refracted angle: n1 sin(theta_i) = n2 sin(theta_t)."""
    _indices(n1, n2)
    s = n1 / n2 * math.sin(theta_i)
    if abs(s) > 1.0:
        raise TotalInternalReflection("beyond the critical angle")
    return math.asin(s)


def critical_angle(n1, n2):
    """asin(n2 / n1) for n1 > n2."""
    _indices(n1, n2)
    if n2 >= n1:
        raise OpticsError("there is no critical angle into a denser medium")
    return math.asin(n2 / n1)


def total_internal_reflection(n1, n2, theta_i):
    """True when Snell's law has no solution."""
    _indices(n1, n2)
    return abs(n1 / n2 * math.sin(theta_i)) > 1.0


def reflect(d, n):
    """d - 2 (d . n) n."""
    n = unit(n)
    return sub(d, mul(n, 2.0 * dot(d, n)))


def refract(d, n, n1, n2):
    """The transmitted unit direction, or None under total internal reflection; n may face either way."""
    _indices(n1, n2)
    d = unit(d)
    n = unit(n)
    cos_i = -dot(d, n)
    if cos_i < 0.0:
        n = mul(n, -1.0)
        cos_i = -cos_i
    eta = n1 / n2
    k = 1.0 - eta * eta * (1.0 - cos_i * cos_i)
    if k < 0.0:
        return None
    return unit(add(mul(d, eta), mul(n, eta * cos_i - math.sqrt(k))))


def fresnel(n1, n2, theta_i):
    """(Rs, Rp) of a dielectric interface; both 1 beyond the critical angle."""
    _indices(n1, n2)
    if not 0.0 <= theta_i <= math.pi / 2.0:
        raise OpticsError("the incidence angle lies in [0, pi / 2]")
    ci = math.cos(theta_i)
    s = n1 / n2 * math.sin(theta_i)
    if abs(s) >= 1.0:
        return (1.0, 1.0)
    ct = math.sqrt(1.0 - s * s)
    rs = (n1 * ci - n2 * ct) / (n1 * ci + n2 * ct)
    rp = (n1 * ct - n2 * ci) / (n1 * ct + n2 * ci)
    return (rs * rs, rp * rp)


def fresnel_unpolarised(n1, n2, theta_i):
    """(Rs + Rp) / 2."""
    rs, rp = fresnel(n1, n2, theta_i)
    return 0.5 * (rs + rp)


def transmittance(n1, n2, theta_i):
    """1 - R."""
    return 1.0 - fresnel_unpolarised(n1, n2, theta_i)


def brewster(n1, n2):
    """atan(n2 / n1)."""
    _indices(n1, n2)
    return math.atan(n2 / n1)


# ------------------------------------------------------------------------------------ lens formulae


def lensmaker(n, r1, r2, d):
    """1 / f = (n - 1) (1 / R1 - 1 / R2 + (n - 1) d / (n R1 R2)); inf when the power vanishes."""
    if not n >= 1.0:
        raise OpticsError("the index must be at least 1")
    if r1 == 0.0 or r2 == 0.0:
        raise OpticsError("radii must be non-zero")
    if d < 0.0:
        raise OpticsError("thickness must not be negative")
    power = (n - 1.0) * (1.0 / r1 - 1.0 / r2 + (n - 1.0) * d / (n * r1 * r2))
    if power == 0.0:
        return math.inf
    return 1.0 / power


def principal_planes(n, r1, r2, d):
    """(h1, h2): the principal planes measured from the first and second vertices, h1 = -f (n - 1) d / (n R2),
    h2 = -f (n - 1) d / (n R1)."""
    f = lensmaker(n, r1, r2, d)
    if f == math.inf:
        return (0.0, 0.0)
    return (-f * (n - 1.0) * d / (n * r2), -f * (n - 1.0) * d / (n * r1))


def back_focal_distance(n, r1, r2, d):
    """The distance from the second vertex to the paraxial focus: f + h2."""
    return lensmaker(n, r1, r2, d) + principal_planes(n, r1, r2, d)[1]


def thin_lens_image(so, f):
    """1 / so + 1 / si = 1 / f; inf for an object at the focus."""
    if not so > 0.0:
        raise OpticsError("the object distance must be positive")
    if f == 0.0:
        raise OpticsError("the focal length must be non-zero")
    if so == f:
        return math.inf
    return so * f / (so - f)


def magnification(so, si):
    """-si / so."""
    return -si / so


def mirror_focal_length(radius):
    """R / 2."""
    return radius / 2.0


# ------------------------------------------------------------------------------------ elements


def thin_lens(x, y, angle, focal, aperture):
    return {"kind": "thin", "x": x, "y": y, "angle": angle, "focal": focal, "aperture": aperture}


def thick_lens(x, y, angle, r1, r2, thickness, n, aperture):
    return {"kind": "thick", "x": x, "y": y, "angle": angle, "r1": r1, "r2": r2, "thickness": thickness, "n": n,
            "aperture": aperture}


def mirror(x, y, angle, aperture):
    return {"kind": "mirror", "x": x, "y": y, "angle": angle, "aperture": aperture}


def spherical_mirror(x, y, angle, radius, aperture):
    return {"kind": "sphericalMirror", "x": x, "y": y, "angle": angle, "radius": radius, "aperture": aperture}


def prism(x, y, angle, apex, size, n):
    return {"kind": "prism", "x": x, "y": y, "angle": angle, "apex": apex, "size": size, "n": n}


def block(points, n):
    return {"kind": "block", "points": [tuple(p) for p in points], "n": n}


def grin_slab(x, y, width, height, n0, alpha):
    return {"kind": "grin", "x": x, "y": y, "width": width, "height": height, "n0": n0, "alpha": alpha}


def screen(x, y, angle, length):
    return {"kind": "screen", "x": x, "y": y, "angle": angle, "length": length}


def point_source(x, y, angle, spread, rays, power=1.0):
    if rays < 1:
        raise OpticsError("a source needs at least one ray")
    if not 0.0 <= spread <= 360.0:
        raise OpticsError("spread lies in [0, 360] degrees")
    return {"kind": "point", "x": x, "y": y, "angle": angle, "spread": spread, "rays": rays, "power": power}


def parallel_source(x, y, angle, width, rays, power=1.0):
    if rays < 1:
        raise OpticsError("a source needs at least one ray")
    if not width > 0.0:
        raise OpticsError("width must be positive")
    return {"kind": "parallel", "x": x, "y": y, "angle": angle, "width": width, "rays": rays, "power": power}


def source_rays(src):
    """The rays a source emits: origin, unit direction and power."""
    if src["kind"] == "point":
        n = src["rays"]
        out = []
        for i in range(n):
            a = src["angle"] + (src["spread"] * (i / (n - 1) - 0.5) if n > 1 else 0.0)
            out.append({"origin": (src["x"], src["y"]), "direction": rot((1.0, 0.0), a), "power": src["power"]})
        return out
    if src["kind"] == "parallel":
        n = src["rays"]
        d = rot((1.0, 0.0), src["angle"])
        across = (-d[1], d[0])
        out = []
        for i in range(n):
            s = src["width"] * (i / (n - 1) - 0.5) if n > 1 else 0.0
            out.append({"origin": add((src["x"], src["y"]), mul(across, s)), "direction": d, "power": src["power"]})
        return out
    raise OpticsError(f"unknown source {src['kind']!r}")


# ------------------------------------------------------------------------------------ surfaces


def flat_surface(x, y, angle, aperture):
    """A segment of the given length centred at (x, y), across the direction `angle`."""
    return {"shape": "flat", "x": x, "y": y, "angle": angle, "aperture": aperture}


def spherical_surface(x, y, radius, aperture, angle=0.0):
    """A circular arc with vertex (x, y) on the axis `angle`, centre `radius` along the axis (convex toward -axis
    when radius is positive), spanning `aperture` across."""
    return {"shape": "sphere", "x": x, "y": y, "radius": radius, "aperture": aperture, "angle": angle}


def _axis(surface):
    return rot((1.0, 0.0), surface.get("angle", 0.0))


def intersect_segment(origin, d, a, b):
    """The ray parameter t > MIN_DISTANCE of the hit with segment ab, or None."""
    e = sub(b, a)
    denom = d[0] * e[1] - d[1] * e[0]
    if abs(denom) < 1e-15:
        return None
    w = sub(a, origin)
    t = (w[0] * e[1] - w[1] * e[0]) / denom
    u = (w[0] * d[1] - w[1] * d[0]) / denom
    if t <= MIN_DISTANCE or u < 0.0 or u > 1.0:
        return None
    return t


def intersect_surface(origin, d, surface):
    """The nearest hit of a ray with a surface: {'t', 'point', 'normal'} or None."""
    d = unit(d)
    axis = _axis(surface)
    across = (-axis[1], axis[0])
    if surface["shape"] == "flat":
        c = (surface["x"], surface["y"])
        a = add(c, mul(across, -surface["aperture"] / 2.0))
        b = add(c, mul(across, surface["aperture"] / 2.0))
        t = intersect_segment(origin, d, a, b)
        if t is None:
            return None
        return {"t": t, "point": add(origin, mul(d, t)), "normal": axis}
    r = surface["radius"]
    centre = add((surface["x"], surface["y"]), mul(axis, r))
    oc = sub(origin, centre)
    b = dot(oc, d)
    c = dot(oc, oc) - r * r
    disc = b * b - c
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    best = None
    for t in (-b - root, -b + root):
        if t <= MIN_DISTANCE:
            continue
        p = add(origin, mul(d, t))
        rel = sub(p, (surface["x"], surface["y"]))
        if abs(dot(rel, across)) > surface["aperture"] / 2.0:
            continue
        # keep the cap that contains the vertex: the side of the centre the vertex is on
        if dot(sub(p, centre), axis) * (-r) < 0.0:
            continue
        if best is None or t < best:
            best = t
            point = p
    if best is None:
        return None
    normal = unit(sub(point, centre))
    return {"t": best, "point": point, "normal": normal}


def _polygon_surfaces(points):
    n = len(points)
    return [(points[i], points[(i + 1) % n]) for i in range(n)]


def _prism_points(el):
    apex = math.radians(el["apex"])
    s = el["size"]
    h = (s / 2.0) / math.tan(apex / 2.0)
    local = [(0.0, h / 2.0), (-s / 2.0, -h / 2.0), (s / 2.0, -h / 2.0)]
    return [add((el["x"], el["y"]), rot(p, el["angle"])) for p in local]


def element_hit(origin, d, el):
    """The nearest hit of a ray with an element: {'t', 'point', 'normal', 'face'} or None."""
    kind = el["kind"]
    if kind in ("thin", "mirror", "screen"):
        length = el["aperture"] if kind != "screen" else el["length"]
        angle = el["angle"] + (90.0 if kind == "mirror" else 0.0) if kind != "screen" else el["angle"]
        # thin lenses and screens are segments across their angle; a mirror of angle a lies along direction a
        if kind == "mirror":
            s = flat_surface(el["x"], el["y"], el["angle"] + 90.0, length)
        else:
            s = flat_surface(el["x"], el["y"], el["angle"], length)
        hit = intersect_surface(origin, d, s)
        return None if hit is None else {**hit, "face": 0}
    if kind == "sphericalMirror":
        s = spherical_surface(el["x"], el["y"], -el["radius"], el["aperture"], el["angle"])
        hit = intersect_surface(origin, d, s)
        return None if hit is None else {**hit, "face": 0}
    if kind == "thick":
        axis = rot((1.0, 0.0), el["angle"])
        v2 = add((el["x"], el["y"]), mul(axis, el["thickness"]))
        s1 = spherical_surface(el["x"], el["y"], el["r1"], el["aperture"], el["angle"])
        s2 = spherical_surface(v2[0], v2[1], el["r2"], el["aperture"], el["angle"])
        best = None
        for face, s in enumerate((s1, s2)):
            hit = intersect_surface(origin, d, s)
            if hit is not None and (best is None or hit["t"] < best["t"]):
                best = {**hit, "face": face}
        return best
    if kind in ("prism", "block", "grin"):
        if kind == "prism":
            pts = _prism_points(el)
        elif kind == "block":
            pts = el["points"]
        else:
            x0, y0, w, h = el["x"], el["y"], el["width"], el["height"]
            pts = [(x0, y0 - h / 2.0), (x0 + w, y0 - h / 2.0), (x0 + w, y0 + h / 2.0), (x0, y0 + h / 2.0)]
        best = None
        for face, (a, b) in enumerate(_polygon_surfaces(pts)):
            t = intersect_segment(origin, d, a, b)
            if t is not None and (best is None or t < best["t"]):
                e = unit(sub(b, a))
                best = {"t": t, "point": add(origin, mul(d, t)), "normal": (-e[1], e[0]), "face": face}
        return best
    raise OpticsError(f"unknown element {kind!r}")


def _inside_polygon(p, pts):
    inside = False
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > p[0]:
                inside = not inside
    return inside


def _element_index(el):
    return el.get("n", el.get("n0", 1.0))


def deflect_thin(point, d, lens):
    """The direction after a thin lens: slope_out = slope_in - h / f in the lens frame."""
    axis = rot((1.0, 0.0), lens["angle"])
    across = (-axis[1], axis[0])
    d = unit(d)
    along = dot(d, axis)
    if along == 0.0:
        raise OpticsError("a ray along the lens plane is not deflected")
    sign = 1.0 if along > 0.0 else -1.0
    h = dot(sub(point, (lens["x"], lens["y"])), across)
    slope = dot(d, across) / along
    slope_out = slope - h / lens["focal"]
    return unit(add(mul(axis, sign), mul(across, sign * slope_out)))


def paraxial_focus(lens, h):
    """The x where a ray at height h parallel to a thick lens's axis crosses the axis (angle 0)."""
    segs = trace_ray((lens["x"] - 100.0 * abs(h) - 10.0, lens["y"] + h), (1.0, 0.0), [lens], 4)
    last = segs[-1]
    x0, y0 = last["start"]
    dx, dy = last["direction"]
    if dy == 0.0:
        return math.inf
    return x0 - (y0 - lens["y"]) * dx / dy


# ------------------------------------------------------------------------------------ GRIN


def grin_index(y, n0, alpha):
    """n(y) = n0 (1 - alpha^2 y^2 / 2), the parabolic profile."""
    if not n0 >= 1.0:
        raise OpticsError("n0 must be at least 1")
    if abs(alpha * y) >= 1.0:
        raise OpticsError("the profile needs |alpha y| < 1")
    return n0 * (1.0 - 0.5 * (alpha * y) ** 2)


def grin_period(alpha):
    """2 pi / alpha, the period of paraxial rays."""
    if not alpha > 0.0:
        raise OpticsError("alpha must be positive")
    return 2.0 * math.pi / alpha


def grin_trace(x0, y0, slope, n0, alpha, length, step):
    """The ray equation d/ds (n dr/ds) = grad n, by classical RK4 in the path parameter, from x0 to x0 + length."""
    if not n0 >= 1.0:
        raise OpticsError("n0 must be at least 1")
    if not step > 0.0:
        raise OpticsError("step must be positive")
    grin_index(y0, n0, alpha)

    def grad(y):
        return -n0 * alpha * alpha * y

    def rhs(state):
        x, y, px, py = state
        n = grin_index(y, n0, alpha)
        return (px / n, py / n, 0.0, grad(y))

    d = unit((1.0, slope))
    n = grin_index(y0, n0, alpha)
    state = (x0, y0, n * d[0], n * d[1])
    path = [(x0, y0)]
    s = 0.0
    while state[0] < x0 + length - 1e-12:
        h = step
        k1 = rhs(state)
        k2 = rhs(tuple(state[i] + 0.5 * h * k1[i] for i in range(4)))
        k3 = rhs(tuple(state[i] + 0.5 * h * k2[i] for i in range(4)))
        k4 = rhs(tuple(state[i] + h * k3[i] for i in range(4)))
        new = tuple(state[i] + h / 6.0 * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) for i in range(4))
        if new[0] > x0 + length:
            frac = (x0 + length - state[0]) / (new[0] - state[0])
            new = tuple(state[i] + frac * (new[i] - state[i]) for i in range(4))
        state = new
        path.append((state[0], state[1]))
        s += h
        if s > 1e7:
            raise OpticsError("the GRIN trace did not reach the slab's end")
    return path


# ------------------------------------------------------------------------------------ tracing


def _hit_elements(origin, d, elements, order):
    """Hits in nonSequential (nearest) or sequential (first element in order that is hit after `order`)."""
    best = None
    for idx, el in enumerate(elements):
        if order is not None and idx < order:
            continue
        hit = element_hit(origin, d, el)
        if hit is None:
            if order is not None:
                continue
            continue
        if order is not None:
            return idx, hit
        if best is None or hit["t"] < best[1]["t"]:
            best = (idx, hit)
    return best


def _grin_exit(el, point, d):
    """Trace through a GRIN slab from an entry point to its exit: (points, exit direction)."""
    axis_x = el["x"]
    local_x = point[0] - axis_x
    length = el["width"] - local_x if d[0] > 0.0 else local_x
    if d[0] <= 0.0:
        # trace leftward by mirroring
        path = grin_trace(0.0, point[1] - el["y"], -d[1] / d[0] if d[0] != 0.0 else 0.0, el["n0"], el["alpha"], length, GRIN_STEP)
        pts = [(axis_x + local_x - px, el["y"] + py) for px, py in path]
    else:
        path = grin_trace(0.0, point[1] - el["y"], d[1] / d[0], el["n0"], el["alpha"], length, GRIN_STEP)
        pts = [(axis_x + local_x + px, el["y"] + py) for px, py in path]
    half = el["height"] / 2.0
    for i, (_px, py) in enumerate(pts):
        if abs(py - el["y"]) > half:
            # the ray leaves through a side wall: it stops there (open issue 4)
            return pts[: max(i, 1) + 1], None
    out = unit(sub(pts[-1], pts[-2]))
    return pts, out


def trace_ray(origin, d, elements, max_bounces, inside=None, mode="nonSequential", fresnel_split=False,
              min_power=1e-3, power=1.0, spawned=None, generation=0):
    """Segments of one ray: each {'start', 'end', 'direction', 'power', 'medium', 'element'} (end None when it
    escapes). Reflected rays of a Fresnel split are appended to `spawned` as (origin, direction, power, inside)."""
    d = unit(d)
    segs = []
    medium = inside
    order = 0 if mode == "sequential" else None
    for bounce in range(max_bounces + 1):
        found = _hit_elements(origin, d, elements, order)
        if found is None:
            segs.append({"start": origin, "end": None, "direction": d, "power": power,
                         "medium": _element_index(medium) if medium else 1.0, "element": None})
            return segs
        idx, hit = found
        el = elements[idx]
        n_here = _element_index(medium) if medium else 1.0
        segs.append({"start": origin, "end": hit["point"], "direction": d, "power": power, "medium": n_here,
                     "element": idx})
        if bounce == max_bounces:
            segs[-1]["truncated"] = True
            return segs
        if order is not None:
            order = idx + 1
        kind = el["kind"]
        point = hit["point"]
        if kind == "screen":
            segs[-1]["absorbed"] = True
            return segs
        if kind == "thin":
            d = deflect_thin(point, d, el)
            origin = point
            continue
        if kind in ("mirror", "sphericalMirror"):
            d = reflect(d, hit["normal"])
            origin = point
            continue
        # refracting elements
        if kind == "grin":
            if medium is el:
                medium = None
                origin = point
                continue
            pts, out = _grin_exit(el, point, d)
            if out is None:
                segs.append({"start": pts[0], "end": pts[-1], "direction": d, "power": power, "medium": el["n0"],
                             "element": idx, "path": pts})
                segs.append({"start": pts[-1], "end": None, "direction": d, "power": power, "medium": 1.0,
                             "element": None})
                return segs
            segs.append({"start": pts[0], "end": pts[-1], "direction": out, "power": power, "medium": el["n0"],
                         "element": idx, "path": pts})
            origin = pts[-1]
            d = out
            continue
        n_in = el.get("n", 1.0)
        entering = medium is not el
        n1, n2 = (1.0 if medium is None else _element_index(medium), n_in) if entering else (n_in, 1.0)
        cos_i = abs(dot(d, hit["normal"]))
        theta_i = math.acos(min(1.0, cos_i))
        t = refract(d, hit["normal"], n1, n2)
        if t is None:
            d = reflect(d, hit["normal"])
            origin = point
            continue
        if fresnel_split:
            r = fresnel_unpolarised(n1, n2, theta_i)
            if spawned is not None and power * r >= min_power:
                spawned.append((point, reflect(d, hit["normal"]), power * r, medium, generation + 1))
            elif spawned is not None:
                spawned.append((None, None, power * r, None, generation + 1))
            power = power * (1.0 - r)
            if power < min_power:
                segs.append({"start": point, "end": None, "direction": t, "power": power, "medium": n2,
                             "element": None, "dropped": True})
                return segs
        medium = el if entering else None
        d = t
        origin = point
    return segs


def trace_bench(bench, sources):
    """All rays of a bench: {'rays': [{'segments', 'power', 'generation'}], 'hits', 'power'}."""
    mode = bench["mode"]
    if mode not in MODES:
        raise OpticsError(f"unknown mode {mode!r}")
    max_bounces = bench["maxBounces"]
    if not (isinstance(max_bounces, int) and 1 <= max_bounces <= MAX_BOUNCES):
        raise OpticsError("maxBounces lies in 1 .. 1024")
    min_power = bench["minPower"]
    if not 0.0 < min_power < 1.0:
        raise OpticsError("minPower lies strictly between 0 and 1")
    elements = bench["elements"]
    rays, hits = [], []
    power = {"absorbed": 0.0, "escaped": 0.0, "truncated": 0.0, "dropped": 0.0}
    for src in sources:
        for ray in source_rays(src):
            queue = [(ray["origin"], ray["direction"], ray["power"], None, 0)]
            while queue:
                origin, d, p, medium, gen = queue.pop(0)
                if origin is None:
                    power["dropped"] += p
                    continue
                spawned = []
                segs = trace_ray(origin, d, elements, max_bounces, medium, mode, bench["fresnel"], min_power, p,
                                 spawned, gen)
                rays.append({"segments": segs, "power": p, "generation": gen})
                last = segs[-1]
                if last.get("absorbed"):
                    power["absorbed"] += last["power"]
                    hits.append({"element": last["element"], "point": last["end"], "power": last["power"]})
                elif last.get("truncated"):
                    power["truncated"] += last["power"]
                elif last.get("dropped"):
                    power["dropped"] += last["power"]
                else:
                    power["escaped"] += last["power"]
                queue.extend(spawned)
    return {"rays": rays, "hits": hits, "power": power}


def trace_prism(prism_el, incidence_deg):
    """A ray into the first face of a prism at the given incidence, traced through it."""
    pts = _prism_points(prism_el)
    a, b = pts[0], pts[1]
    mid = mul(add(a, b), 0.5)
    e = unit(sub(b, a))
    normal = (-e[1], e[0])  # outward of the first face
    centre = mul(add(add(pts[0], pts[1]), pts[2]), 1.0 / 3.0)
    if dot(normal, sub(mid, centre)) < 0.0:
        normal = mul(normal, -1.0)
    # incoming direction: tilted from -normal by the incidence toward the apex
    toward_apex = unit(sub(pts[0], mid))
    i = math.radians(incidence_deg)
    d = unit(add(mul(normal, -math.cos(i)), mul(toward_apex, math.sin(i))))
    origin = sub(mid, mul(d, 100.0 * prism_el["size"]))
    return trace_ray(origin, d, [prism_el], 8)


def minimum_deviation(n, apex_deg):
    """2 asin(n sin(A / 2)) - A, degrees."""
    if not n >= 1.0:
        raise OpticsError("the index must be at least 1")
    s = n * math.sin(math.radians(apex_deg) / 2.0)
    if not 0.0 < apex_deg < 180.0 or s >= 1.0:
        raise OpticsError("no ray passes this prism")
    return math.degrees(2.0 * math.asin(s)) - apex_deg


def prism_deviation(n, apex_deg, incidence_deg):
    """The deviation of a ray at the given incidence on the first face, degrees."""
    a = math.radians(apex_deg)
    t1 = snell(1.0, n, math.radians(incidence_deg))
    t2 = a - t1
    i2 = snell(n, 1.0, t2)
    return math.degrees(math.radians(incidence_deg) + i2) - apex_deg


# ------------------------------------------------------------------------------------ image construction


def image_construction(so, height, f):
    """The image of an arrow of the given height so in front of a thin lens at the origin, with the three
    principal rays as point lists ending at the image tip."""
    si = thin_lens_image(so, f)
    if si == math.inf:
        raise OpticsError("the object at the focus has no image")
    m = magnification(so, si)
    tip = (-so, height)
    image = (si, m * height)
    rays = []
    # parallel then through the focus
    rays.append([tip, (0.0, height), image])
    # through the centre
    rays.append([tip, (0.0, 0.0), image])
    # through the front focus then parallel
    slope = height / (f - so) if so != f else 0.0
    y_at_lens = height + slope * so
    rays.append([tip, (0.0, y_at_lens), image])
    return {"si": si, "height": m * height, "virtual": si < 0.0, "rays": rays, "magnification": m}


def ray_alpha(power):
    """The stroke alpha of a ray: sqrt(power)."""
    if not 0.0 <= power <= 1.0:
        raise OpticsError("power lies in [0, 1]")
    return math.sqrt(power)


# ------------------------------------------------------------------------------------ animation


def frame_angle(frame, fps, a0, a1, t0, t1):
    """A source angle keyed linearly from a0 at t0 to a1 at t1, held outside, at a frame."""
    if frame < 0 or int(frame) != frame:
        raise OpticsError("frame must be a non-negative integer")
    if not fps > 0.0 or not t1 > t0:
        raise OpticsError("fps must be positive and t1 must exceed t0")
    u = min(1.0, max(0.0, (frame / fps - t0) / (t1 - t0)))
    return a0 + (a1 - a0) * u


def frame_trace(bench, x, y, a0, a1, t0, t1, frame, fps):
    """The trace of a one-ray source whose angle is keyed, at a frame."""
    return trace_bench(bench, [point_source(x, y, frame_angle(frame, fps, a0, a1, t0, t1), 0.0, 1)])


def seek_test():
    """Frame k rendered alone equals frame k of a run over all frames (the trace has no state)."""
    bench = {"mode": "nonSequential", "maxBounces": 16, "minPower": 1e-3, "fresnel": True,
             "elements": [thin_lens(100.0, 0.0, 0.0, 50.0, 80.0),
                          block([(120.0, -40.0), (160.0, -40.0), (160.0, 40.0), (120.0, 40.0)], 1.5),
                          screen(200.0, 0.0, 0.0, 200.0)]}
    run = [frame_trace(bench, 0.0, 0.0, -20.0, 20.0, 0.0, 4.0, k, 24.0) for k in range(SEEK_FRAMES + 1)]
    for k in (0, 17, 48, 96):
        if frame_trace(bench, 0.0, 0.0, -20.0, 20.0, 0.0, 4.0, k, 24.0) != run[k]:
            return False
    return True


# ------------------------------------------------------------------------------------ validation


def validate_bench(mode, max_bounces, min_power, elements):
    """RO3: mode in the enumeration, maxBounces 1 .. 1024, minPower in (0, 1), at least one element."""
    if mode not in MODES:
        raise OpticsError("RO3: mode is sequential or nonSequential")
    if not (isinstance(max_bounces, int) and 1 <= max_bounces <= MAX_BOUNCES):
        raise OpticsError("RO3: maxBounces lies in 1 .. 1024")
    if not 0.0 < min_power < 1.0:
        raise OpticsError("RO3: minPower lies strictly between 0 and 1")
    if not elements:
        raise OpticsError("RO3: a bench has at least one element")


def validate_element(el):
    """RO1: indices at least 1 and GRIN profiles positive across the slab; RO2: non-zero focal lengths and
    radii, positive thickness and apertures within the surfaces, prism apex in (0, 180), blocks of three or more
    points."""
    kind = el.get("kind")
    if kind not in ELEMENT_KINDS:
        raise OpticsError("RO1: unknown element")
    if kind == "thin" and el["focal"] == 0.0:
        raise OpticsError("RO2: focal must be non-zero")
    if kind == "thick":
        if not el["n"] >= 1.0:
            raise OpticsError("RO1: n must be at least 1")
        if el["r1"] == 0.0 or el["r2"] == 0.0 or not el["thickness"] > 0.0:
            raise OpticsError("RO2: radii non-zero and thickness positive")
        if el["aperture"] > 2.0 * min(abs(el["r1"]), abs(el["r2"])):
            raise OpticsError("RO2: the aperture must fit both surfaces")
    if kind in ("prism", "block") and not el["n"] >= 1.0:
        raise OpticsError("RO1: n must be at least 1")
    if kind == "prism" and not 0.0 < el["apex"] < 180.0:
        raise OpticsError("RO2: apex lies in (0, 180)")
    if kind == "block" and len(el["points"]) < 3:
        raise OpticsError("RO2: a block needs three points")
    if kind == "grin":
        if not el["n0"] >= 1.0:
            raise OpticsError("RO1: n0 must be at least 1")
        if not abs(el["alpha"] * el["height"] / 2.0) < 1.0:
            raise OpticsError("RO1: alpha times half the height must be below 1")


def validate_source(src):
    """RO4: rays at least 1, spread in [0, 360], width positive."""
    if src.get("kind") not in SOURCE_KINDS:
        raise OpticsError("RO4: unknown source")
    if src["rays"] < 1:
        raise OpticsError("RO4: rays at least 1")
    if src["kind"] == "point" and not 0.0 <= src["spread"] <= 360.0:
        raise OpticsError("RO4: spread in [0, 360]")
    if src["kind"] == "parallel" and not src["width"] > 0.0:
        raise OpticsError("RO4: width positive")


# ------------------------------------------------------------------------------------ the table

_LENS = "thick_lens(0, 0, 0, 100, -100, 10, 1.5, 40)"
_GLASS = "block([(0, -50), (100, -50), (100, 50), (0, 50)], 1.5)"
TABLE = (
    ("Snell: 30 degrees into n 1.5", "math.degrees(snell(1, 1.5, math.radians(30)))", "19.4712"),
    ("critical angle of n 1.5", "math.degrees(critical_angle(1.5, 1))", "41.8103"),
    ("critical angle of water", "math.degrees(critical_angle(1.33, 1))", "48.7535"),
    ("TIR at 45 degrees inside n 1.5", "total_internal_reflection(1.5, 1, math.radians(45))", "True"),
    ("Fresnel at normal incidence", "fresnel_unpolarised(1, 1.5, 0)", "0.04"),
    ("Fresnel Rs at 60 degrees", "fresnel(1, 1.5, math.radians(60))[0]", "0.176571"),
    ("Fresnel Rp at 60 degrees", "fresnel(1, 1.5, math.radians(60))[1]", "0.00180194"),
    ("Brewster's angle", "math.degrees(brewster(1, 1.5))", "56.3099"),
    ("Rp at Brewster's angle", "fresnel(1, 1.5, brewster(1, 1.5))[1]", "0"),
    ("R + T at 60 degrees", "fresnel_unpolarised(1, 1.5, math.radians(60)) + transmittance(1, 1.5, math.radians(60))", "1"),
    ("thin biconvex R 100 n 1.5", "lensmaker(1.5, 100, -100, 0)", "100"),
    ("thick biconvex, d 10", "lensmaker(1.5, 100, -100, 10)", "101.695"),
    ("principal planes of the thick lens", "principal_planes(1.5, 100, -100, 10)", "(3.38983, -3.38983)"),
    ("back focal distance", "back_focal_distance(1.5, 100, -100, 10)", "98.3051"),
    ("traced paraxial focus", f"paraxial_focus({_LENS}, 0.01)", "108.305"),
    ("traced marginal focus at h 15", f"paraxial_focus({_LENS}, 15)", "104.68"),
    ("thin-lens image of so 300, f 100", "thin_lens_image(300, 100)", "150"),
    ("magnification of so 300, si 150", "magnification(300, 150)", "-0.5"),
    ("virtual image of so 50, f 100", "thin_lens_image(50, 100)", "-100"),
    ("thin-lens deflection at h 20", "deflect_thin((0, 20), (1, 0), thin_lens(0, 0, 0, 100, 60))", "(0.980581, -0.196116)"),
    ("spherical mirror focal length", "mirror_focal_length(200)", "100"),
    ("minimum deviation of a 60 degree prism", "minimum_deviation(1.5, 60)", "37.1808"),
    ("deviation at 60 degrees incidence", "prism_deviation(1.5, 60, 60)", "38.8768"),
    ("GRIN index at y 10", "grin_index(10, 1.5, 0.02)", "1.47"),
    ("GRIN period", "grin_period(0.02)", "314.159"),
    ("GRIN ray height after a quarter period", "grin_trace(0, 0.5, 0, 1.5, 0.02, grin_period(0.02) / 4, 0.05)[-1][1]", "-2.45449e-05"),
    ("GRIN axial ray height after a quarter period", "grin_trace(0, 0, 0.01, 1.5, 0.02, grin_period(0.02) / 4, 0.05)[-1][1]", "0.499981"),
    ("parallel beam hits at the focus", "trace_bench({'mode': 'nonSequential', 'maxBounces': 16, 'minPower': 1e-3, 'fresnel': False, 'elements': [thin_lens(100, 0, 0, 50, 80), screen(150, 0, 0, 200)]}, [parallel_source(0, 0, 0, 40, 5)])['hits'][0]['point']", "(150, 0)"),
    ("escaped power of a glass block with Fresnel", f"trace_bench({{'mode': 'nonSequential', 'maxBounces': 64, 'minPower': 1e-6, 'fresnel': True, 'elements': [{_GLASS}]}}, [point_source(-50, -20, 30, 0, 1)])['power']['escaped']", "1"),
    ("transmitted power at 30 degrees", f"trace_bench({{'mode': 'nonSequential', 'maxBounces': 64, 'minPower': 1e-6, 'fresnel': True, 'elements': [{_GLASS}]}}, [point_source(-50, -20, 30, 0, 1)])['rays'][0]['segments'][1]['power']", "0.958477"),
    ("rays between two mirrors are bounded", "len(trace_bench({'mode': 'nonSequential', 'maxBounces': 7, 'minPower': 1e-3, 'fresnel': False, 'elements': [mirror(0, 0, 90, 100), mirror(100, 0, 90, 100)]}, [point_source(50, 0, 0, 0, 1)])['rays'][0]['segments'])", "8"),
    ("image of a 20 high object at 300", "image_construction(300, 20, 100)['height']", "-10"),
    ("virtual image of a 20 high object at 50", "image_construction(50, 20, 100)['height']", "40"),
    ("ray alpha at power 0.25", "ray_alpha(0.25)", "0.5"),
    ("source angle at frame 48", "frame_angle(48, 24, -20, 20, 0, 4)", "0"),
    ("seek check", "seek_test()", "True"),
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
