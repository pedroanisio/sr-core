"""Tests of the draft SREP "Add homogeneous and height media, UsdVol volumes and null-scattering transport"
(srep/srep-0000-volumes.md) and of its reference module conformance/tools/volumes_reference.py: homogeneous
and height media, their exact optical depths (Beer-Lambert), the UsdVol subset, the majorant, delta and ratio
tracking with seeded draws, the Henyey-Greenstein phase and its sampling, the white-furnace walk, froxel
slices and their front-to-back integration converging to the exact transport, and the SREP's numeric table.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "volumes_reference.py")
STREAMS = os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-volumes.md")

spec = importlib.util.spec_from_file_location("volumes_reference", MODULE)
vo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vo)

spec_rs = importlib.util.spec_from_file_location("random_streams_reference", STREAMS)
rs = importlib.util.module_from_spec(spec_rs)
spec_rs.loader.exec_module(rs)

USDA = '''#usda 1.0
(
    defaultPrim = "smoke"
)

def Volume "smoke"
{
    rel field:density = </smoke/density>
    rel field:temperature = </smoke/heat>

    def OpenVDBAsset "density"
    {
        asset filePath = @./smoke.vdb@
        token fieldName = "density"
        int fieldIndex = 0
    }
    def OpenVDBAsset "heat"
    {
        asset filePath = @./smoke.vdb@
        token fieldName = "temperature"
    }
}

def Volume "fog"
{
    rel field:density = </fog/d>
    def OpenVDBAsset "d"
    {
        asset filePath = @fog.vdb@
        token fieldName = "density"
    }
}
'''


def _close(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


# --------------------------------------------------------------------------------- homogeneous and height

def test_a_box_medium_has_density_one_inside_and_zero_outside():
    assert vo.homogeneous_density("box", (2.0, 4.0, 6.0), (0.9, -1.9, 2.9)) == 1.0
    assert vo.homogeneous_density("box", (2.0, 4.0, 6.0), (1.1, 0.0, 0.0)) == 0.0
    assert vo.homogeneous_density("sphere", (1.5,), (0.0, 1.4, 0.0)) == 1.0
    assert vo.homogeneous_density("sphere", (1.5,), (0.0, 1.6, 0.0)) == 0.0
    with pytest.raises(ValueError):
        vo.homogeneous_density("cone", (1.0,), (0.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        vo.homogeneous_density("box", (2.0, -4.0, 6.0), (0.0, 0.0, 0.0))


def test_a_height_medium_falls_off_above_its_base():
    assert vo.height_density((0.0, 0.0, 0.0), 0.0, 1.0) == 1.0
    assert _close(vo.height_density((0.0, 1.0, 0.0), 0.0, 1.0), math.exp(-1.0))
    assert _close(vo.height_density((0.0, 3.0, 0.0), 1.0, 2.0), math.exp(-1.0))
    assert vo.height_density((0.0, -5.0, 0.0), 0.0, 1.0) == 1.0
    with pytest.raises(ValueError):
        vo.height_density((0.0, 0.0, 0.0), 0.0, 0.0)


def test_the_height_optical_depth_is_exact():
    assert _close(vo.height_optical_depth((0.0, 0.0, 0.0), (0.0, 2.0, 0.0), 0.0, 1.0), 1.0 - math.exp(-2.0))
    assert _close(vo.height_optical_depth((0.0, 1.0, 0.0), (3.0, 1.0, 0.0), 0.0, 1.0), 3.0 * math.exp(-1.0))
    assert _close(vo.height_optical_depth((0.0, -2.0, 0.0), (0.0, -1.0, 0.0), 0.0, 1.0), 1.0)
    assert _close(vo.height_optical_depth((0.0, -1.0, 0.0), (0.0, 1.0, 0.0), 0.0, 1.0), 1.0 + 1.0 - math.exp(-1.0))
    assert _close(vo.height_optical_depth((0.0, 2.0, 0.0), (0.0, 0.0, 0.0), 0.0, 1.0), 1.0 - math.exp(-2.0))
    assert _close(vo.height_optical_depth((0.0, 0.0, 0.0), (0.0, 2.0, 0.0), 0.0, 1.0, extinction=3.0),
                  3.0 * (1.0 - math.exp(-2.0)))


def test_the_march_converges_to_the_exact_height_depth():
    exact = vo.height_optical_depth((0.0, 0.0, 0.0), (4.0, 3.0, 0.0), 0.0, 1.0)
    f = vo.height_field(0.0, 1.0)
    errors = [abs(vo.march_optical_depth(f, (0.0, 0.0, 0.0), (4.0, 3.0, 0.0), n) - exact) for n in (4, 8, 16)]
    assert errors[0] > errors[1] > errors[2]
    assert math.log2(errors[0] / errors[1]) > 1.8


def test_beer_lambert():
    assert _close(vo.transmittance(0.5, 2.0), math.exp(-1.0))
    assert vo.transmittance(0.0, 5.0) == 1.0


# --------------------------------------------------------------------------------------------- usdvol

def test_the_usdvol_subset_maps_channels_to_grids():
    fields = vo.usdvol_fields(USDA)
    assert fields == {"density": ("./smoke.vdb", "density", 0), "temperature": ("./smoke.vdb", "temperature", 0)}
    assert vo.usdvol_fields(USDA, prim="/fog") == {"density": ("fog.vdb", "density", 0)}
    assert vo.usdvol_fields(USDA, prim="/smoke") == fields


def test_the_usdvol_subset_rejects_what_it_cannot_read():
    with pytest.raises(ValueError):
        vo.usdvol_fields("#usda 1.0\n", prim=None)
    with pytest.raises(ValueError):
        vo.usdvol_fields(USDA, prim="/nothing")
    broken = USDA.replace("</smoke/density>", "</smoke/missing>")
    with pytest.raises(ValueError):
        vo.usdvol_fields(broken)
    with pytest.raises(ValueError):
        vo.usdvol_fields(USDA.replace('def OpenVDBAsset "d"', 'def Field3DAsset "d"'), prim="/fog")
    with pytest.raises(ValueError):
        vo.usdvol_fields("not usda at all")


# --------------------------------------------------------------------------------------------- tracking

SEED = rs.E(7, "fog", 3, "transport")


def test_draws_are_a_stream_of_the_element_seed_pixel_and_sample():
    u = vo.draws(SEED, vo.P_DISTANCE, pixel=5, sample=2)
    first = u()
    assert first == rs.S(SEED, vo.P_DISTANCE, 2, 5 * vo.DRAWS_PER_RAY)
    assert u() == rs.S(SEED, vo.P_DISTANCE, 2, 5 * vo.DRAWS_PER_RAY + 1)
    assert vo.draws(SEED, vo.P_DISTANCE, pixel=5, sample=2)() == first
    assert vo.draws(SEED, vo.P_PHASE, pixel=5, sample=2)() != first


def test_a_ray_has_a_bounded_number_of_draws():
    u = vo.draws(SEED, vo.P_DISTANCE, pixel=0, sample=0)
    for _ in range(vo.DRAWS_PER_RAY):
        u()
    with pytest.raises(ValueError):
        u()


def test_the_majorant_bounds_the_extinction():
    assert vo.majorant((0.0, 0.5, 2.0), density_scale=3.0, extinction=0.5) == 3.0
    assert vo.majorant((0.0, 0.0), density_scale=3.0, extinction=0.5) == 0.0
    with pytest.raises(ValueError):
        vo.majorant((0.0, -1.0), 1.0, 1.0)


def _const(value):
    return lambda p: value


def test_delta_tracking_in_a_homogeneous_medium_collides_at_the_free_path():
    draws = iter((0.5, 0.0))
    t, nulls = vo.delta_tracking(_const(1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 10.0, 2.0,
                                 lambda: next(draws), extinction=2.0)
    assert _close(t, math.log(2.0) / 2.0)
    assert nulls == 0


def test_delta_tracking_escapes_past_the_segment_end():
    draws = iter((0.5,))
    t, nulls = vo.delta_tracking(_const(1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 0.1, 2.0,
                                 lambda: next(draws), extinction=2.0)
    assert t is None and nulls == 0


def test_delta_tracking_takes_null_collisions_where_the_density_is_below_the_majorant():
    draws = iter((0.5, 0.9, 0.5, 0.1))
    t, nulls = vo.delta_tracking(_const(0.5), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 10.0, 1.0,
                                 lambda: next(draws), extinction=1.0)
    assert nulls == 1
    assert _close(t, math.log(2.0) + math.log(2.0))


def test_delta_tracking_is_bounded():
    draws = iter([0.999999] * 10 + [0.5] * 10)
    with pytest.raises(ValueError):
        vo.delta_tracking(_const(0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 1e9, 1.0, lambda: next(draws),
                          max_collisions=8)
    with pytest.raises(ValueError):
        vo.delta_tracking(_const(1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 10.0, 0.5, lambda: 0.5)


def test_ratio_tracking_is_unbiased():
    sigma = 0.7
    length = 2.0
    exact = math.exp(-sigma * length)
    for majorant in (sigma, 2.0 * sigma):
        estimates = []
        for pixel in range(400):
            u = vo.draws(SEED, vo.P_DISTANCE, pixel=pixel, sample=0)
            estimates.append(vo.ratio_tracking(_const(sigma), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, length,
                                               majorant, u))
        mean = sum(estimates) / len(estimates)
        assert abs(mean - exact) < 0.05, (majorant, mean, exact)
    assert vo.ratio_tracking(_const(sigma), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, length, sigma, lambda: 0.5) == 0.0
    assert vo.ratio_tracking(_const(sigma), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 0.01, sigma, lambda: 0.5) == 1.0


def test_ratio_tracking_of_a_height_medium_matches_its_exact_depth():
    a, b = (0.0, 0.0, 0.0), (4.0, 3.0, 0.0)
    exact = math.exp(-vo.height_optical_depth(a, b, 0.0, 1.0))
    f = vo.height_field(0.0, 1.0)
    estimates = [vo.ratio_tracking(f, a, (0.8, 0.6, 0.0), 0.0, 5.0, 1.0,
                                   vo.draws(SEED, vo.P_DISTANCE, pixel=p, sample=1)) for p in range(400)]
    assert abs(sum(estimates) / len(estimates) - exact) < 0.03


def test_the_tracking_is_a_function_of_its_draws():
    f = vo.height_field(0.0, 1.0)
    one = vo.ratio_tracking(f, (0.0, 0.0, 0.0), (0.8, 0.6, 0.0), 0.0, 5.0, 1.0, vo.draws(SEED, 0, pixel=3, sample=4))
    two = vo.ratio_tracking(f, (0.0, 0.0, 0.0), (0.8, 0.6, 0.0), 0.0, 5.0, 1.0, vo.draws(SEED, 0, pixel=3, sample=4))
    assert one == two


# ------------------------------------------------------------------------------------------------ phase

def test_the_phase_function_normalises():
    for g in (0.0, 0.5, -0.8):
        n = 2000
        total = 0.0
        for i in range(n):
            mu = -1.0 + (i + 0.5) * 2.0 / n
            total += vo.phase_hg(mu, g) * 2.0 / n
        assert abs(2.0 * math.pi * total - 1.0) < 1e-3, g
    assert _close(vo.phase_hg(0.3, 0.0), 1.0 / (4.0 * math.pi))
    with pytest.raises(ValueError):
        vo.phase_hg(0.0, 1.0)


def test_sampling_the_phase_function():
    assert _close(vo.sample_hg(0.0, 0.25, 0.0)[0], 0.5)
    cos, phi = vo.sample_hg(0.0, 0.75, 0.5)
    assert _close(cos, -0.5) and _close(phi, math.pi)
    cos, _ = vo.sample_hg(0.9, 0.5, 0.0)
    assert cos > 0.9
    cos, _ = vo.sample_hg(-0.9, 0.5, 0.0)
    assert cos < -0.9


def test_a_scattered_direction_is_unit_and_at_the_sampled_angle():
    d = (0.0, 0.0, 1.0)
    for g, u1, u2 in ((0.0, 0.3, 0.7), (0.6, 0.1, 0.2), (-0.4, 0.9, 0.95)):
        out = vo.scatter_direction(d, g, u1, u2)
        assert _close(math.sqrt(sum(c * c for c in out)), 1.0)
        assert _close(sum(a * b for a, b in zip(d, out)), vo.sample_hg(g, u1, u2)[0])


# ---------------------------------------------------------------------------------------------- furnace

def test_the_white_furnace_walk_keeps_all_its_energy_at_albedo_one():
    escaped = 0
    for pixel in range(50):
        result = vo.furnace_walk(_const(1.0), 1.0, 1.0, albedo=1.0, g=0.0, seed=SEED, pixel=pixel, max_bounces=32)
        if result["escaped"]:
            escaped += 1
            assert result["throughput"] == 1.0
    assert escaped >= 45


def test_the_white_furnace_loses_energy_as_albedo_falls():
    r = vo.furnace_walk(_const(1.0), 1.0, 1.0, albedo=0.5, g=0.0, seed=SEED, pixel=1, max_bounces=32)
    assert r["throughput"] == 0.5 ** r["bounces"]
    with pytest.raises(ValueError):
        vo.furnace_walk(_const(1.0), 1.0, 1.0, albedo=1.0, g=0.0, seed=SEED, pixel=1, max_bounces=vo.MAX_BOUNCES + 1)


def test_the_furnace_mean_is_near_one_for_a_thin_sphere():
    values = [vo.furnace_walk(_const(1.0), 1.0, 1.0, albedo=1.0, g=0.0, seed=SEED, pixel=p, max_bounces=32)["radiance"]
              for p in range(300)]
    assert sum(values) / len(values) > 0.98


# ---------------------------------------------------------------------------------------------- froxels

def test_froxel_slices_are_exponential_in_depth():
    assert _close(vo.froxel_depths(2, 1.0, 4.0), (1.0, 2.0, 4.0))
    assert _close(vo.froxel_depths(3, 1.0, 8.0), (1.0, 2.0, 4.0, 8.0))
    assert vo.froxel_index(2.9, 3, 1.0, 8.0) == 1
    assert vo.froxel_index(1.0, 3, 1.0, 8.0) == 0
    assert vo.froxel_index(8.0, 3, 1.0, 8.0) == 2
    with pytest.raises(ValueError):
        vo.froxel_depths(0, 1.0, 4.0)
    with pytest.raises(ValueError):
        vo.froxel_depths(vo.MAX_SLICES + 1, 1.0, 4.0)
    with pytest.raises(ValueError):
        vo.froxel_depths(4, 0.0, 4.0)


def test_froxel_integration_is_exact_on_a_homogeneous_slice():
    radiance, transmittance = vo.froxel_integrate(((1.0, (1.0, 1.0, 1.0), 1.0),))
    assert _close(radiance, ((1.0 - math.exp(-1.0),) * 3))
    assert _close(transmittance, math.exp(-1.0))
    radiance, transmittance = vo.froxel_integrate(((0.0, (2.0, 0.0, 0.0), 3.0),))
    assert _close(radiance, (6.0, 0.0, 0.0)) and transmittance == 1.0


def test_froxel_integration_composes_front_to_back():
    one = vo.froxel_integrate(((1.0, (1.0, 1.0, 1.0), 2.0),))
    two = vo.froxel_integrate(((1.0, (1.0, 1.0, 1.0), 1.0), (1.0, (1.0, 1.0, 1.0), 1.0)))
    assert _close(one, two)


def test_froxels_converge_to_the_exact_transport_of_a_height_medium():
    a, d = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    near, far = 0.5, 4.0
    exact = math.exp(-vo.height_optical_depth((0.0, near, 0.0), (0.0, far, 0.0), 0.0, 1.0))
    errors = [abs(vo.froxel_transmittance(vo.height_field(0.0, 1.0), a, d, n, near, far) - exact) for n in (8, 32, 128)]
    assert errors[0] > errors[1] > errors[2]
    assert errors[2] < 1e-3


def test_raster_converges_to_the_path_tracer():
    a, d = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    f = vo.height_field(0.0, 1.0)
    raster = vo.froxel_transmittance(f, a, d, 256, 0.5, 4.0)
    tracked = [vo.ratio_tracking(f, a, d, 0.5, 4.0, 1.0, vo.draws(SEED, vo.P_DISTANCE, pixel=p, sample=2))
               for p in range(400)]
    assert abs(raster - sum(tracked) / len(tracked)) < 0.03


def test_bounds():
    assert vo.MAX_DOMAINS == 64 and vo.MAX_BOUNCES == 32 and vo.MAX_SLICES == 1024 and vo.MAX_COLLISIONS == 65536


# ---------------------------------------------------------------------------------------------- the draft

@pytest.fixture(scope="module")
def draft():
    assert os.path.exists(DRAFT), "the draft SREP is missing"
    with open(DRAFT, encoding="utf-8") as f:
        return f.read()


def test_the_draft_has_the_srep_sections(draft):
    assert draft.startswith("```\nSREP:            0\n")
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft
    for section in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics",
                    "## Rationale", "## Rejected alternatives", "## Backwards compatibility", "## Engine impact",
                    "## Conformance", "### Numeric tests", "### Kit cases", "## Open issues", "## References",
                    "## History"):
        assert section in draft, section
    assert "... no" not in draft


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    assert "SR-78" in draft
    for word in ("usdvol", "source", "falloff", "transport", "froxelSlices", "V17", "majorant", "ratio tracking",
                 "delta tracking", "white furnace", "Beer", "seek check", "volumes_reference.py", "Miller"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [m.groups() for m in ROW.finditer(f.read())]
    rows = [r for r in rows if r[0] not in ("Test",)]
    return rows or [("empty table", "0", "1")]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 30


@pytest.mark.parametrize("name,expr,expected", _draft_rows(), ids=[r[0] for r in _draft_rows()])
def test_the_table_rows_hold(name, expr, expected):
    scope = vo.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert vo._same(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(draft, capsys):
    vo.main()
    out = capsys.readouterr().out.strip().splitlines()
    table = [line for line in draft.splitlines() if ROW.match(line) and not line.startswith("| Test")]
    assert out == table
