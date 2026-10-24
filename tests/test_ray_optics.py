"""Tests of the draft SREP "Add ray-optics diagrams" (srep/srep-0000-ray-optics.md) and of its reference
implementation conformance/tools/ray_optics_reference.py (OW1 of SREP 12, SRC-51).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "ray_optics_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-ray-optics.md")

_spec = importlib.util.spec_from_file_location("ray_optics_reference", MODULE)
ro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ro)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _rel(a, b, tol=1e-12):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


def _deg(x):
    return math.degrees(x)


# ------------------------------------------------------------------------------------ Snell, TIR and Fresnel


def test_snells_law_and_the_critical_angle():
    assert _close(_deg(ro.snell(1.0, 1.5, math.radians(30.0))), 19.4712206, 1e-6)
    assert _close(_deg(ro.snell(1.5, 1.0, math.radians(19.4712206))), 30.0, 1e-6)
    assert ro.snell(1.0, 1.5, 0.0) == 0.0
    assert _close(_deg(ro.critical_angle(1.5, 1.0)), 41.8103149, 1e-6)
    assert _close(_deg(ro.critical_angle(1.33, 1.0)), 48.7535, 1e-3)
    with pytest.raises(ro.OpticsError):
        ro.critical_angle(1.0, 1.5)
    with pytest.raises(ro.TotalInternalReflection):
        ro.snell(1.5, 1.0, math.radians(45.0))
    with pytest.raises(ro.OpticsError):
        ro.snell(0.0, 1.5, 0.1)
    assert ro.total_internal_reflection(1.5, 1.0, math.radians(45.0)) is True
    assert ro.total_internal_reflection(1.5, 1.0, math.radians(40.0)) is False
    assert ro.total_internal_reflection(1.0, 1.5, math.radians(89.0)) is False


def test_refract_and_reflect_on_directions():
    d = ro.unit((math.sin(math.radians(30.0)), -math.cos(math.radians(30.0))))
    n = (0.0, 1.0)  # the normal points toward the incoming side
    t = ro.refract(d, n, 1.0, 1.5)
    assert _close(math.asin(t[0]), math.radians(19.4712206), 1e-6)
    assert t[1] < 0.0
    assert _close(ro.norm(t), 1.0, 1e-12)
    r = ro.reflect(d, n)
    assert _close(r, (d[0], -d[1]), 1e-12)
    assert ro.refract(d, n, 1.5, 1.0) is not None
    steep = ro.unit((math.sin(math.radians(45.0)), -math.cos(math.radians(45.0))))
    assert ro.refract(steep, n, 1.5, 1.0) is None
    # straight through at normal incidence
    assert _close(ro.refract((0.0, -1.0), n, 1.0, 1.5), (0.0, -1.0), 1e-12)
    # the normal may be given facing away: the result is the same
    assert _close(ro.refract(d, (0.0, -1.0), 1.0, 1.5), t, 1e-12)


def test_fresnel_coefficients_brewster_and_conservation():
    rs, rp = ro.fresnel(1.0, 1.5, 0.0)
    assert _close(rs, 0.04, 1e-12) and _close(rp, 0.04, 1e-12)
    assert _close(ro.fresnel_unpolarised(1.0, 1.5, 0.0), 0.04, 1e-12)
    b = ro.brewster(1.0, 1.5)
    assert _close(_deg(b), 56.3099325, 1e-6)
    assert ro.fresnel(1.0, 1.5, b)[1] < 1e-12
    assert ro.fresnel(1.0, 1.5, b)[0] > 0.0
    for th in (0.0, 0.3, 0.9, 1.4):
        rs, rp = ro.fresnel(1.0, 1.5, th)
        assert 0.0 <= rs <= 1.0 and 0.0 <= rp <= 1.0
        assert _close(ro.fresnel_unpolarised(1.0, 1.5, th) + ro.transmittance(1.0, 1.5, th), 1.0, 1e-12)
    assert ro.fresnel_unpolarised(1.5, 1.0, math.radians(45.0)) == 1.0
    assert ro.transmittance(1.5, 1.0, math.radians(45.0)) == 0.0
    assert ro.fresnel_unpolarised(1.0, 1.5, math.radians(89.999)) > 0.99
    with pytest.raises(ro.OpticsError):
        ro.fresnel(1.0, 1.5, -0.1)


# ------------------------------------------------------------------------------------ lenses, mirrors, prisms


def test_lensmaker_and_the_thin_lens_equation():
    # symmetric biconvex, R 100, n 1.5: f = 100 for a thin lens
    assert _close(ro.lensmaker(1.5, 100.0, -100.0, 0.0), 100.0, 1e-12)
    # thick: 1/f = (n-1)(1/R1 - 1/R2 + (n-1) d / (n R1 R2))
    f = ro.lensmaker(1.5, 100.0, -100.0, 10.0)
    assert _close(1.0 / f, 0.5 * (0.02 + 0.5 * 10.0 / (1.5 * -10000.0)), 1e-15)
    assert f > 100.0
    assert ro.lensmaker(1.5, 100.0, 100.0, 0.0) == math.inf
    assert ro.lensmaker(1.5, -100.0, 100.0, 0.0) < 0.0
    assert _close(ro.thin_lens_image(300.0, 100.0), 150.0, 1e-12)
    assert _close(ro.thin_lens_image(50.0, 100.0), -100.0, 1e-12)
    assert ro.thin_lens_image(100.0, 100.0) == math.inf
    assert _close(ro.magnification(300.0, 150.0), -0.5, 1e-12)
    assert _close(ro.magnification(50.0, -100.0), 2.0, 1e-12)
    with pytest.raises(ro.OpticsError):
        ro.lensmaker(0.5, 100.0, -100.0, 0.0)
    with pytest.raises(ro.OpticsError):
        ro.lensmaker(1.5, 0.0, -100.0, 0.0)
    with pytest.raises(ro.OpticsError):
        ro.thin_lens_image(0.0, 100.0)


def test_thin_lens_deflection_is_slope_minus_height_over_focal():
    lens = ro.thin_lens(0.0, 0.0, 0.0, 100.0, 60.0)
    out = ro.deflect_thin((0.0, 20.0), (1.0, 0.0), lens)
    assert _close(out, ro.unit((1.0, -0.2)), 1e-12)
    out = ro.deflect_thin((0.0, 20.0), ro.unit((1.0, 0.1)), lens)
    assert _close(out[1] / out[0], 0.1 - 0.2, 1e-12)
    diverging = ro.thin_lens(0.0, 0.0, 0.0, -100.0, 60.0)
    out = ro.deflect_thin((0.0, 20.0), (1.0, 0.0), diverging)
    assert _close(out, ro.unit((1.0, 0.2)), 1e-12)
    # a parallel beam focuses at the focal point
    for h in (-25.0, -5.0, 0.0, 12.0, 30.0):
        d = ro.deflect_thin((0.0, h), (1.0, 0.0), lens)
        assert _close(h + 100.0 * d[1] / d[0], 0.0, 1e-9)
    # a ray through the centre is undeflected
    assert _close(ro.deflect_thin((0.0, 0.0), ro.unit((1.0, 0.3)), lens), ro.unit((1.0, 0.3)), 1e-12)


def test_a_traced_thick_lens_focuses_where_the_lensmaker_says():
    lens = ro.thick_lens(0.0, 0.0, 0.0, 100.0, -100.0, 10.0, 1.5, 40.0)
    f = ro.lensmaker(1.5, 100.0, -100.0, 10.0)
    focus = ro.paraxial_focus(lens, 0.01)
    # the focal length is measured from the second principal plane
    h2 = ro.principal_planes(1.5, 100.0, -100.0, 10.0)[1]
    assert _rel(focus - (lens["x"] + 10.0 + h2), f, 1e-6)
    assert _rel(ro.back_focal_distance(1.5, 100.0, -100.0, 10.0), focus - (lens["x"] + 10.0), 1e-6)
    # spherical aberration: a marginal ray crosses the axis before the paraxial focus
    assert ro.paraxial_focus(lens, 15.0) < focus
    assert ro.paraxial_focus(lens, 15.0) > lens["x"] + 10.0
    h1, h2 = ro.principal_planes(1.5, 100.0, -100.0, 10.0)
    assert h1 > 0.0 and h2 < 0.0 and _close(h1, -h2, 1e-12)


def test_spherical_surface_intersection_and_normals():
    # a surface of radius 100 whose vertex is at the origin, convex toward -x
    s = ro.spherical_surface(0.0, 0.0, 100.0, 40.0)
    hit = ro.intersect_surface((-50.0, 0.0), (1.0, 0.0), s)
    assert hit is not None
    assert _close(hit["point"], (0.0, 0.0), 1e-12)
    assert _close(hit["normal"], (-1.0, 0.0), 1e-12)
    hit = ro.intersect_surface((-50.0, 20.0), (1.0, 0.0), s)
    assert _close(hit["point"][0], 100.0 - math.sqrt(100.0 ** 2 - 20.0 ** 2), 1e-9)
    assert _close(ro.norm(hit["normal"]), 1.0, 1e-12)
    assert ro.intersect_surface((-50.0, 30.0), (1.0, 0.0), s) is None  # outside the aperture
    assert ro.intersect_surface((50.0, 0.0), (1.0, 0.0), s) is None  # behind the ray
    flat = ro.flat_surface(0.0, 0.0, 0.0, 40.0)
    hit = ro.intersect_surface((-50.0, 10.0), ro.unit((1.0, 0.0)), flat)
    assert _close(hit["point"], (0.0, 10.0), 1e-12)
    assert ro.intersect_surface((-50.0, 21.0), (1.0, 0.0), flat) is None


def test_mirrors_reflect_and_a_spherical_mirror_focuses_at_half_the_radius():
    flat = ro.mirror(0.0, 0.0, 45.0, 100.0)
    segs = ro.trace_ray((-50.0, 0.0), (1.0, 0.0), [flat], 4)
    assert len(segs) == 2
    assert _close(segs[0]["end"], (0.0, 0.0), 1e-9)
    assert _close(segs[1]["direction"], (0.0, 1.0), 1e-9)
    concave = ro.spherical_mirror(0.0, 0.0, 0.0, 200.0, 60.0)
    for h in (-1.0, 0.5, 1.0):
        segs = ro.trace_ray((-150.0, h), (1.0, 0.0), [concave], 4)
        assert len(segs) == 2
        x0, y0 = segs[1]["start"]
        dx, dy = segs[1]["direction"]
        assert dx < 0.0
        crossing = x0 - y0 * dx / dy
        assert _close(crossing, -100.0, 0.01), h
    assert _close(ro.mirror_focal_length(200.0), 100.0, 1e-12)


def test_a_prism_deviates_by_snell_at_both_faces():
    n, apex = 1.5, 60.0
    d_min = ro.minimum_deviation(n, apex)
    assert _close(d_min, 37.1807, 1e-3)
    incidence = (d_min + apex) / 2.0
    assert _close(ro.prism_deviation(n, apex, incidence), d_min, 1e-9)
    assert ro.prism_deviation(n, apex, 60.0) > d_min
    assert ro.prism_deviation(n, apex, 40.0) > d_min
    with pytest.raises(ro.TotalInternalReflection):
        ro.prism_deviation(n, apex, 20.0)
    with pytest.raises(ro.OpticsError):
        ro.minimum_deviation(2.5, 120.0)
    # the traced prism agrees with the formula
    prism = ro.prism(0.0, 0.0, 0.0, apex, 100.0, n)
    segs = ro.trace_prism(prism, incidence)
    assert len(segs) == 3
    out = segs[-1]["direction"]
    inc = segs[0]["direction"]
    dev = _deg(math.atan2(inc[0] * out[1] - inc[1] * out[0], inc[0] * out[0] + inc[1] * out[1]))
    assert _close(abs(dev), d_min, 1e-6)


def test_grin_slabs_bend_rays_into_sinusoids():
    n0, alpha = 1.5, 0.02
    assert _close(ro.grin_index(0.0, n0, alpha), n0, 1e-15)
    assert ro.grin_index(10.0, n0, alpha) < n0
    assert _close(ro.grin_index(10.0, n0, alpha), n0 * (1.0 - 0.5 * (alpha * 10.0) ** 2), 1e-12)
    assert _close(ro.grin_period(alpha), 2.0 * math.pi / alpha, 1e-12)
    path = ro.grin_trace(0.0, 0.5, 0.0, n0, alpha, ro.grin_period(alpha) / 4.0, 0.05)
    assert path[0] == (0.0, 0.5)
    assert abs(path[-1][1]) < 1e-4  # the parabolic profile is sinusoidal only to order (alpha y0)^2
    assert _close(path[-1][0], math.pi / (2.0 * alpha), 1e-3)
    # a ray launched at the axis with a small slope reaches y = y0 of a sinusoid: y = (s / alpha) sin(alpha x)
    path = ro.grin_trace(0.0, 0.0, 0.01, n0, alpha, ro.grin_period(alpha) / 4.0, 0.05)
    assert _close(path[-1][1], 0.01 / alpha, 1e-4)
    with pytest.raises(ro.OpticsError):
        ro.grin_index(60.0, n0, alpha)  # alpha y >= 1
    with pytest.raises(ro.OpticsError):
        ro.grin_trace(0.0, 0.0, 0.0, 0.5, alpha, 1.0, 0.1)
    with pytest.raises(ro.OpticsError):
        ro.grin_trace(0.0, 0.0, 0.0, n0, alpha, 1.0, 0.0)


# ------------------------------------------------------------------------------------ the bench


def _bench():
    return {"mode": "nonSequential", "maxBounces": 16, "minPower": 1e-3, "fresnel": False,
            "elements": [ro.thin_lens(100.0, 0.0, 0.0, 50.0, 80.0), ro.screen(200.0, 0.0, 0.0, 200.0)]}


def test_sources_make_fans_and_beams():
    fan = ro.source_rays(ro.point_source(0.0, 0.0, 0.0, 20.0, 5))
    assert len(fan) == 5
    assert _close(fan[0]["direction"], ro.unit((math.cos(math.radians(-10.0)), math.sin(math.radians(-10.0)))), 1e-12)
    assert _close(fan[2]["direction"], (1.0, 0.0), 1e-12)
    assert all(r["power"] == 1.0 and r["origin"] == (0.0, 0.0) for r in fan)
    one = ro.source_rays(ro.point_source(0.0, 0.0, 30.0, 20.0, 1))
    assert _close(one[0]["direction"], (math.cos(math.radians(30.0)), math.sin(math.radians(30.0))), 1e-12)
    beam = ro.source_rays(ro.parallel_source(0.0, 0.0, 0.0, 40.0, 5))
    assert len(beam) == 5
    assert _close(beam[0]["origin"], (0.0, -20.0), 1e-12)
    assert _close(beam[4]["origin"], (0.0, 20.0), 1e-12)
    assert all(_close(r["direction"], (1.0, 0.0), 1e-12) for r in beam)
    with pytest.raises(ro.OpticsError):
        ro.point_source(0.0, 0.0, 0.0, 20.0, 0)
    with pytest.raises(ro.OpticsError):
        ro.point_source(0.0, 0.0, 0.0, 361.0, 3)


def test_a_parallel_beam_through_a_thin_lens_meets_on_the_screen_at_the_focus():
    bench = _bench()
    bench["elements"][1] = ro.screen(150.0, 0.0, 0.0, 200.0)
    result = ro.trace_bench(bench, [ro.parallel_source(0.0, 0.0, 0.0, 40.0, 5)])
    assert len(result["rays"]) == 5
    for polyline in result["rays"]:
        assert len(polyline["segments"]) == 2
        assert _close(polyline["segments"][-1]["end"], (150.0, 0.0), 1e-6)
    assert len(result["hits"]) == 5
    assert all(h["element"] == 1 and _close(h["point"], (150.0, 0.0), 1e-6) for h in result["hits"])
    assert _close(result["power"]["absorbed"], 5.0, 1e-12)
    assert result["power"]["escaped"] == 0.0 and result["power"]["truncated"] == 0.0


def test_non_sequential_tracing_takes_the_nearest_hit_and_sequential_the_element_order():
    far = ro.mirror(300.0, 0.0, 90.0, 100.0)
    near = ro.mirror(100.0, 0.0, 90.0, 100.0)
    bench = {"mode": "nonSequential", "maxBounces": 4, "minPower": 1e-3, "fresnel": False, "elements": [far, near]}
    result = ro.trace_bench(bench, [ro.point_source(0.0, 0.0, 0.0, 0.0, 1)])
    segs = result["rays"][0]["segments"]
    assert _close(segs[0]["end"], (100.0, 0.0), 1e-9)
    assert _close(segs[1]["direction"], (-1.0, 0.0), 1e-9)
    assert result["power"]["escaped"] == 1.0
    bench["mode"] = "sequential"
    result = ro.trace_bench(bench, [ro.point_source(0.0, 0.0, 0.0, 0.0, 1)])
    segs = result["rays"][0]["segments"]
    assert _close(segs[0]["end"], (300.0, 0.0), 1e-9)
    assert _close(segs[1]["end"], (100.0, 0.0), 1e-9)
    assert _close(segs[2]["direction"], (1.0, 0.0), 1e-9)
    with pytest.raises(ro.OpticsError):
        ro.trace_bench({**bench, "mode": "random"}, [ro.point_source(0.0, 0.0, 0.0, 0.0, 1)])


def test_the_bounce_bound_and_the_power_floor_belong_to_the_document():
    left = ro.mirror(0.0, 0.0, 90.0, 100.0)
    right = ro.mirror(100.0, 0.0, 90.0, 100.0)
    bench = {"mode": "nonSequential", "maxBounces": 7, "minPower": 1e-3, "fresnel": False, "elements": [left, right]}
    result = ro.trace_bench(bench, [ro.point_source(50.0, 0.0, 0.0, 0.0, 1)])
    assert len(result["rays"][0]["segments"]) == 8
    assert result["power"]["truncated"] == 1.0
    assert result["power"]["escaped"] == 0.0
    glass = ro.block([(0.0, -50.0), (100.0, -50.0), (100.0, 50.0), (0.0, 50.0)], 1.5)
    bench = {"mode": "nonSequential", "maxBounces": 64, "minPower": 0.05, "fresnel": True, "elements": [glass]}
    result = ro.trace_bench(bench, [ro.point_source(-50.0, 0.0, 0.0, 0.0, 1)])
    powers = result["power"]
    assert _close(powers["absorbed"] + powers["escaped"] + powers["truncated"] + powers["dropped"], 1.0, 1e-9)
    assert powers["dropped"] > 0.0
    assert powers["truncated"] == 0.0
    assert all(p["power"] >= 0.05 for p in result["rays"] if p["segments"])
    with pytest.raises(ro.OpticsError):
        ro.trace_bench({**bench, "maxBounces": 0}, [ro.point_source(-50.0, 0.0, 0.0, 0.0, 1)])
    with pytest.raises(ro.OpticsError):
        ro.trace_bench({**bench, "minPower": 0.0}, [ro.point_source(-50.0, 0.0, 0.0, 0.0, 1)])
    assert ro.MAX_BOUNCES == 1024


def test_fresnel_splitting_conserves_power_and_refraction_follows_snell():
    glass = ro.block([(0.0, -50.0), (100.0, -50.0), (100.0, 50.0), (0.0, 50.0)], 1.5)
    bench = {"mode": "nonSequential", "maxBounces": 64, "minPower": 1e-6, "fresnel": True, "elements": [glass]}
    src = ro.point_source(-50.0, -20.0, 30.0, 0.0, 1)
    result = ro.trace_bench(bench, [src])
    powers = result["power"]
    assert _close(powers["absorbed"] + powers["escaped"] + powers["truncated"] + powers["dropped"], 1.0, 1e-9)
    assert powers["escaped"] > 0.99
    # the first transmitted ray bends to Snell's angle
    first = [p for p in result["rays"] if p["generation"] == 0][0]
    inside = first["segments"][1]["direction"]
    assert _close(math.asin(inside[1]), math.radians(19.4712206), 1e-6)
    assert _close(first["segments"][1]["power"], 1.0 - ro.fresnel_unpolarised(1.0, 1.5, math.radians(30.0)), 1e-12)
    reflected = [p for p in result["rays"] if p["generation"] == 1][0]
    assert _close(reflected["segments"][0]["power"], ro.fresnel_unpolarised(1.0, 1.5, math.radians(30.0)), 1e-12)
    # without Fresnel the transmitted ray keeps the whole power and nothing is reflected below the critical angle
    bench["fresnel"] = False
    result = ro.trace_bench(bench, [src])
    assert len(result["rays"]) == 1
    assert all(s["power"] == 1.0 for s in result["rays"][0]["segments"])


def test_total_internal_reflection_inside_a_block():
    glass = ro.block([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)], 1.5)
    bench = {"mode": "nonSequential", "maxBounces": 16, "minPower": 1e-3, "fresnel": False, "elements": [glass]}
    # a ray starting inside the block at 45 degrees to the top face reflects totally
    segs = ro.trace_ray((50.0, 50.0), ro.unit((1.0, 1.0)), [glass], 16, inside=glass)
    assert _close(segs[0]["end"], (100.0, 100.0), 1e-9) or _close(segs[0]["end"][1], 100.0, 1e-9)
    assert segs[1]["direction"][1] < 0.0 or segs[1]["direction"][0] < 0.0
    assert segs[0]["medium"] == 1.5
    result = ro.trace_bench(bench, [ro.point_source(-50.0, 50.0, 0.0, 0.0, 1)])
    assert result["power"]["escaped"] == 1.0


def test_image_construction_with_principal_rays():
    img = ro.image_construction(300.0, 20.0, 100.0)
    assert _close(img["si"], 150.0, 1e-12)
    assert _close(img["height"], -10.0, 1e-12)
    assert img["virtual"] is False
    assert len(img["rays"]) == 3
    for ray in img["rays"]:
        assert _close(ray[-1], (150.0, -10.0), 1e-9), ray
    virtual = ro.image_construction(50.0, 20.0, 100.0)
    assert virtual["virtual"] is True
    assert _close(virtual["si"], -100.0, 1e-12)
    assert _close(virtual["height"], 40.0, 1e-12)
    for ray in virtual["rays"]:
        assert _close(ray[-1], (-100.0, 40.0), 1e-9), ray
    with pytest.raises(ro.OpticsError):
        ro.image_construction(100.0, 20.0, 100.0)


def test_screen_hits_and_ray_alpha():
    bench = _bench()
    # a source at the front focus leaves the lens as a parallel beam, so the three hits are distinct
    result = ro.trace_bench(bench, [ro.point_source(50.0, 0.0, 0.0, 10.0, 3)])
    assert len(result["hits"]) == 3
    assert all(h["element"] == 1 for h in result["hits"])
    xs = sorted(h["point"][1] for h in result["hits"])
    assert xs[0] < xs[1] < xs[2]
    assert ro.ray_alpha(1.0) == 1.0
    assert _close(ro.ray_alpha(0.25), 0.5, 1e-12)
    assert ro.ray_alpha(0.0) == 0.0
    with pytest.raises(ro.OpticsError):
        ro.ray_alpha(1.5)


def test_a_keyed_source_angle_traces_as_a_pure_function_of_the_frame():
    bench = _bench()
    a = ro.frame_trace(bench, 0.0, 0.0, -20.0, 20.0, 0.0, 4.0, 48, 24.0)
    b = ro.frame_trace(bench, 0.0, 0.0, -20.0, 20.0, 0.0, 4.0, 48, 24.0)
    assert a == b
    assert _close(ro.frame_angle(48, 24.0, -20.0, 20.0, 0.0, 4.0), 0.0, 1e-12)
    assert _close(ro.frame_angle(0, 24.0, -20.0, 20.0, 0.0, 4.0), -20.0, 1e-12)
    assert _close(ro.frame_angle(960, 24.0, -20.0, 20.0, 0.0, 4.0), 20.0, 1e-12)
    assert ro.seek_test() is True
    with pytest.raises(ro.OpticsError):
        ro.frame_angle(-1, 24.0, -20.0, 20.0, 0.0, 4.0)


# ------------------------------------------------------------------------------------ validation


def test_validation_ro1_to_ro4():
    ro.validate_bench("nonSequential", 32, 0.01, [ro.thin_lens(0.0, 0.0, 0.0, 50.0, 20.0)])
    ro.validate_bench("sequential", 1, 0.5, [ro.mirror(0.0, 0.0, 0.0, 20.0)])
    for args in (("random", 32, 0.01, [ro.mirror(0.0, 0.0, 0.0, 20.0)]), ("sequential", 0, 0.01, [ro.mirror(0.0, 0.0, 0.0, 20.0)]),
                 ("sequential", 1025, 0.01, [ro.mirror(0.0, 0.0, 0.0, 20.0)]), ("sequential", 32, 0.0, [ro.mirror(0.0, 0.0, 0.0, 20.0)]),
                 ("sequential", 32, 1.0, [ro.mirror(0.0, 0.0, 0.0, 20.0)]), ("sequential", 32, 0.01, [])):
        with pytest.raises(ro.OpticsError):
            ro.validate_bench(*args)
    ro.validate_element(ro.thick_lens(0.0, 0.0, 0.0, 100.0, -100.0, 10.0, 1.5, 40.0))
    ro.validate_element(ro.grin_slab(0.0, 0.0, 100.0, 40.0, 1.5, 0.02))
    with pytest.raises(ro.OpticsError):
        ro.validate_element(ro.thin_lens(0.0, 0.0, 0.0, 0.0, 20.0))
    with pytest.raises(ro.OpticsError):
        ro.validate_element(ro.thick_lens(0.0, 0.0, 0.0, 100.0, -100.0, 10.0, 0.9, 40.0))
    with pytest.raises(ro.OpticsError):
        ro.validate_element(ro.thick_lens(0.0, 0.0, 0.0, 100.0, -100.0, 10.0, 1.5, 250.0))
    with pytest.raises(ro.OpticsError):
        ro.validate_element(ro.thick_lens(0.0, 0.0, 0.0, 100.0, -100.0, 0.0, 1.5, 40.0))
    with pytest.raises(ro.OpticsError):
        ro.validate_element(ro.prism(0.0, 0.0, 0.0, 180.0, 100.0, 1.5))
    with pytest.raises(ro.OpticsError):
        ro.validate_element(ro.block([(0.0, 0.0), (1.0, 0.0)], 1.5))
    with pytest.raises(ro.OpticsError):
        ro.validate_element(ro.grin_slab(0.0, 0.0, 100.0, 40.0, 1.5, 0.06))
    with pytest.raises(ro.OpticsError):
        ro.validate_element({"kind": "hologram"})
    ro.validate_source(ro.point_source(0.0, 0.0, 0.0, 20.0, 5))
    with pytest.raises(ro.OpticsError):
        ro.validate_source({**ro.point_source(0.0, 0.0, 0.0, 20.0, 5), "rays": 0})
    with pytest.raises(ro.OpticsError):
        ro.validate_source({**ro.parallel_source(0.0, 0.0, 0.0, 20.0, 5), "width": 0.0})


def test_scope_and_same():
    s = ro.scope()
    assert s["math"] is math
    assert s["snell"] is ro.snell
    assert ro._same(1.0, 1.0 + 1e-7)
    assert not ro._same(1.0, 1.01)
    assert ro._same((1.0, 2.0), (1.0, 2.0 + 1e-9))
    assert ro._same({"a": 1.0}, {"a": 1.0})
    assert ro._fmt(2.0) == "2"
    assert ro._fmt(True) == "True"


# ------------------------------------------------------------------------------------ the draft and its table


@pytest.fixture(scope="module")
def draft():
    assert os.path.exists(DRAFT), "the draft SREP is missing"
    with open(DRAFT, encoding="utf-8") as f:
        return f.read()


def test_the_draft_has_the_srep_sections(draft):
    for heading in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics", "## Rationale",
                    "## Rejected alternatives", "## Backwards compatibility", "## Engine impact", "## Conformance",
                    "### Numeric tests", "### Kit cases", "## Open issues", "## References", "## History"):
        assert heading in draft, heading
    assert "SREP:            0" in draft
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft
    assert "... no" not in draft


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    assert "SR-93" in draft
    for word in ("opticalBench", "source", "lens", "mirror", "prism", "block", "grin", "screen", "object",
                 "mode", "maxBounces", "minPower", "fresnel", "sequential", "nonSequential", "focal", "aperture",
                 "thickness", "apex", "alpha", "Snell", "Fresnel", "lensmaker", "total internal reflection",
                 "Brewster", "principal", "GRIN", "RO1", "RO2", "RO3", "RO4", "V17", "seek check",
                 "ray_optics_reference.py", "SREP 14", "Hecht", "Born", "Wolf", "Pedrotti", "Marchand", "SR-93"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 30


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = ro.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or ro._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    ro.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())
