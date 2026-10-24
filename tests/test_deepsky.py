"""Tests of the draft SREP "Add deep sky: procedural galaxies, N-body mergers and emission-line nebulae"
(srep/srep-0000-deepsky.md) and of its reference module conformance/tools/deepsky_reference.py: the exponential
and Sersic profiles and their enclosed fractions, inverse-CDF sampling of radii, heights and azimuths, spiral arms
and dust lanes, the seeded star catalogue whose histogram follows the laws, star colours from the blackbody, the
rotation curve, the softened leapfrog N-body (Kepler orbit, energy, momentum, determinism, bounds), merger initial
conditions, the emission lines, their colours and palettes, the nebula sample for A2 media, and the SREP's numeric
table against the module.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "deepsky_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-deepsky.md")
STREAMS = os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py")

spec = importlib.util.spec_from_file_location("deepsky_reference", MODULE)
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

spec_rs = importlib.util.spec_from_file_location("random_streams_reference", STREAMS)
rs = importlib.util.module_from_spec(spec_rs)
spec_rs.loader.exec_module(rs)

DISK = dict(scale_length=1.0, scale_height=0.1, share=0.7, temperature=6000.0)
BULGE = dict(effective_radius=0.5, sersic_index=4.0, share=0.3, temperature=4500.0)
ARMS = dict(count=2, pitch=math.radians(15.0), amplitude=0.6, radius=0.5, dust=1.0, dust_width=0.15, dust_offset=0.25)
HALO = dict(speed=1.0, core_radius=0.5)
SEED = rs.E(7, "m51", 3, "stars")


def _close(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


# ------------------------------------------------------------------------------------ profiles

def test_the_exponential_profile_and_its_enclosed_fraction():
    assert ds.exponential_profile(2.0, 1.0, 0.0) == 2.0
    assert _close(ds.exponential_profile(2.0, 1.0, 1.0), 2.0 * math.exp(-1.0))
    assert ds.exponential_enclosed(1.0, 0.0) == 0.0
    assert _close(ds.exponential_enclosed(1.0, 1.0), 1.0 - 2.0 * math.exp(-1.0))
    assert _close(ds.exponential_enclosed(2.0, 2.0), 1.0 - 2.0 * math.exp(-1.0))
    assert ds.exponential_enclosed(1.0, 50.0) > 0.9999
    with pytest.raises(ValueError):
        ds.exponential_profile(1.0, 0.0, 1.0)


def test_the_regularised_gamma():
    assert _close(ds.gamma_p(1.0, 1.0), 1.0 - math.exp(-1.0), 1e-12)
    assert _close(ds.gamma_p(2.0, 1.0), 1.0 - 2.0 * math.exp(-1.0), 1e-12)
    assert _close(ds.gamma_p(0.5, 2.0), math.erf(math.sqrt(2.0)), 1e-10)
    assert ds.gamma_p(3.0, 0.0) == 0.0
    assert _close(ds.gamma_p(8.0, 60.0), 1.0, 1e-9)


def test_the_sersic_b_solves_the_half_light_condition():
    for n in (0.5, 1.0, 2.0, 4.0, 8.0):
        b = ds.sersic_b(n)
        assert _close(ds.gamma_p(2.0 * n, b), 0.5, 1e-9), n
        approx = 2.0 * n - 1.0 / 3.0 + 4.0 / (405.0 * n) + 46.0 / (25515.0 * n * n)
        assert abs(b - approx) < 2e-3, n
    assert _close(ds.sersic_b(1.0), 1.6783469900, 1e-7)
    assert _close(ds.sersic_b(4.0), 7.6692494, 1e-5)
    with pytest.raises(ValueError):
        ds.sersic_b(0.2)


def test_the_sersic_profile_and_its_enclosed_fraction():
    assert _close(ds.sersic_profile(3.0, 2.0, 4.0, 2.0), 3.0)
    assert ds.sersic_profile(3.0, 2.0, 4.0, 0.1) > 3.0 > ds.sersic_profile(3.0, 2.0, 4.0, 5.0)
    for n in (1.0, 4.0):
        assert _close(ds.sersic_enclosed(n, 2.0, 2.0), 0.5, 1e-9)
    assert ds.sersic_enclosed(4.0, 1.0, 0.0) == 0.0
    h = 1.0 / ds.sersic_b(1.0)
    for r in (0.3, 1.0, 2.5):
        assert _close(ds.sersic_enclosed(1.0, 1.0, r), ds.exponential_enclosed(h, r), 1e-9)


# ------------------------------------------------------------------------------------ sampling

def test_inverse_cdf_sampling_of_the_disk_radius():
    assert ds.sample_disk_radius(0.0, 1.0) == 0.0
    r = ds.sample_disk_radius(0.5, 1.0)
    assert _close(ds.exponential_enclosed(1.0, r), 0.5, 1e-9)
    assert _close(ds.sample_disk_radius(0.5, 2.0), 2.0 * r, 1e-8)
    assert ds.sample_disk_radius(0.999999, 1.0) <= ds.RADIUS_CUT
    with pytest.raises(ValueError):
        ds.sample_disk_radius(1.5, 1.0)


def test_inverse_cdf_sampling_of_the_bulge_radius():
    assert _close(ds.sample_bulge_radius(0.5, 0.5, 4.0), 0.5, 1e-8)
    r = ds.sample_bulge_radius(0.2, 1.0, 2.0)
    assert _close(ds.sersic_enclosed(2.0, 1.0, r), 0.2, 1e-9)


def test_the_height_follows_sech_squared():
    assert ds.sample_height(0.5, 0.1) == 0.0
    z = ds.sample_height(0.9, 0.1)
    assert _close((1.0 + math.tanh(z / 0.1)) / 2.0, 0.9, 1e-12)
    assert _close(ds.sample_height(0.1, 0.1), -z, 1e-12)
    assert _close(ds.sech2(0.0, 0.1), 1.0)
    assert ds.sech2(0.3, 0.1) < 0.01


def test_the_arm_phase_is_a_logarithmic_spiral():
    assert ds.arm_phase(0.5, 0.5, math.radians(15.0)) == 0.0
    phase = ds.arm_phase(1.0, 0.5, math.radians(15.0))
    assert _close(phase, math.log(2.0) / math.tan(math.radians(15.0)))
    assert ds.arm_phase(2.0, 0.5, math.radians(15.0)) > phase


def test_the_arm_density_and_the_azimuth_sampler():
    on_arm = ds.arm_density(1.0, ds.arm_phase(1.0, 0.5, ARMS["pitch"]), ARMS)
    assert _close(on_arm, 1.0 + ARMS["amplitude"])
    between = ds.arm_density(1.0, ds.arm_phase(1.0, 0.5, ARMS["pitch"]) + math.pi / 2.0, ARMS)
    assert _close(between, 1.0 - ARMS["amplitude"])
    assert _close(ds.arm_density(1.0, 0.3, dict(ARMS, amplitude=0.0)), 1.0)
    theta = ds.sample_azimuth(0.25, 1.0, ARMS)
    assert _close(ds.azimuth_cdf(theta, 1.0, ARMS), 0.25, 1e-9)
    assert _close(ds.sample_azimuth(0.0, 1.0, ARMS), 0.0, 1e-9)
    assert _close(ds.sample_azimuth(1.0, 1.0, ARMS), 2.0 * math.pi, 1e-6)
    assert _close(ds.sample_azimuth(0.25, 1.0, dict(ARMS, amplitude=0.0)), math.pi / 2.0, 1e-9)
    with pytest.raises(ValueError):
        ds.arm_density(1.0, 0.0, dict(ARMS, amplitude=1.5))
    with pytest.raises(ValueError):
        ds.arm_density(1.0, 0.0, dict(ARMS, count=ds.MAX_ARMS + 1))


def test_the_dust_lane_darkens_the_inner_edge_of_the_arm():
    phase = ds.arm_phase(1.0, 0.5, ARMS["pitch"])
    lane = ds.dust_transmission(1.0, phase - ARMS["dust_offset"], ARMS)
    assert _close(lane, math.exp(-ARMS["dust"]), 1e-9)
    assert ds.dust_transmission(1.0, phase + math.pi / 2.0, ARMS) > 0.999
    assert ds.dust_transmission(1.0, phase - ARMS["dust_offset"] + math.pi, ARMS) == pytest.approx(lane, abs=1e-9)
    assert ds.dust_transmission(1.0, 0.3, dict(ARMS, dust=0.0)) == 1.0


# ------------------------------------------------------------------------------------ the catalogue

def test_a_star_is_a_function_of_its_index_and_seed():
    one = ds.star(SEED, 17, DISK, BULGE, ARMS)
    two = ds.star(SEED, 17, DISK, BULGE, ARMS)
    assert one == two
    assert one != ds.star(SEED, 18, DISK, BULGE, ARMS)
    assert one != ds.star(SEED + 1, 17, DISK, BULGE, ARMS)
    assert set(one) == {"x", "y", "z", "component", "colour", "brightness"}
    assert one["component"] in ("disk", "bulge")


def test_the_catalogue_draws_from_the_streams():
    s = ds.star(SEED, 5, DISK, dict(BULGE, share=0.0), dict(ARMS, amplitude=0.0))
    u_r = rs.S(SEED, ds.P_RADIUS, 0, 5)
    assert _close(math.hypot(s["x"], s["z"]), ds.sample_disk_radius(u_r, DISK["scale_length"]), 1e-9)
    assert _close(s["y"], ds.sample_height(rs.S(SEED, ds.P_HEIGHT, 0, 5), DISK["scale_height"]), 1e-9)


def test_the_catalogue_is_stable_under_the_count():
    short = ds.galaxy_stars(SEED, 100, DISK, BULGE, ARMS)
    long = ds.galaxy_stars(SEED, 200, DISK, BULGE, ARMS)
    assert short == long[:100]
    with pytest.raises(ValueError):
        ds.galaxy_stars(SEED, ds.MAX_STARS + 1, DISK, BULGE, ARMS)
    with pytest.raises(ValueError):
        ds.galaxy_stars(SEED, 10, dict(DISK, share=0.8), BULGE, ARMS)


def test_the_disk_histogram_follows_the_exponential_law():
    stars = ds.galaxy_stars(SEED, 20000, DISK, dict(BULGE, share=0.0), dict(ARMS, amplitude=0.0))
    radii = sorted(math.hypot(s["x"], s["z"]) for s in stars)
    for x in (0.5, 1.0, 2.0, 3.0):
        frac = sum(1 for r in radii if r <= x) / len(radii)
        assert abs(frac - ds.exponential_enclosed(1.0, x)) < 0.015, x
    assert ds.profile_error(radii, lambda r: ds.exponential_enclosed(1.0, r)) < 0.015


def test_the_bulge_histogram_follows_the_sersic_law():
    stars = ds.galaxy_stars(SEED, 20000, dict(DISK, share=0.0), dict(BULGE, share=1.0), ARMS)
    radii = sorted(math.sqrt(s["x"] ** 2 + s["y"] ** 2 + s["z"] ** 2) for s in stars)
    assert all(s["component"] == "bulge" for s in stars)
    half = sum(1 for r in radii if r <= BULGE["effective_radius"]) / len(radii)
    assert abs(half - 0.5) < 0.015
    assert ds.profile_error(radii, lambda r: ds.sersic_enclosed(4.0, 0.5, r)) < 0.015


def test_the_arms_modulate_the_azimuths():
    stars = ds.galaxy_stars(SEED, 20000, DISK, dict(BULGE, share=0.0), ARMS)
    on, off = 0, 0
    for s in stars:
        r = math.hypot(s["x"], s["z"])
        theta = math.atan2(s["z"], s["x"]) % (2.0 * math.pi)
        d = ds.arm_density(r, theta, ARMS)
        if d > 1.3:
            on += 1
        elif d < 0.7:
            off += 1
    assert on > 2 * off


def test_star_colours_come_from_the_blackbody():
    hot = ds.blackbody_colour(30000.0)
    cool = ds.blackbody_colour(3000.0)
    assert max(hot) == 1.0 and max(cool) == 1.0
    assert hot[2] > hot[0] and cool[0] > cool[2]
    sun = ds.blackbody_colour(5778.0)
    assert sun[0] == 1.0 and sun[1] > 0.85 and sun[2] > 0.75
    with pytest.raises(ValueError):
        ds.blackbody_colour(0.0)


def test_the_bulge_is_redder_than_the_disk():
    stars = ds.galaxy_stars(SEED, 2000, DISK, BULGE, ARMS)
    disk = [s["colour"] for s in stars if s["component"] == "disk"]
    bulge = [s["colour"] for s in stars if s["component"] == "bulge"]
    assert disk and bulge
    assert sum(c[2] for c in disk) / len(disk) > sum(c[2] for c in bulge) / len(bulge)


# ------------------------------------------------------------------------------------ dynamics

def test_the_rotation_curve_is_flat_far_out():
    v1 = ds.rotation_speed(1.0, DISK, BULGE, HALO, mass=1.0)
    v20 = ds.rotation_speed(20.0, DISK, BULGE, HALO, mass=1.0)
    v40 = ds.rotation_speed(40.0, DISK, BULGE, HALO, mass=1.0)
    assert v1 > 0.0
    assert abs(v40 - v20) < 0.05 * v20
    assert abs(v40 - HALO["speed"]) < 0.1 * HALO["speed"]
    assert ds.rotation_speed(2.0, DISK, BULGE, dict(HALO, speed=0.0), mass=1.0) < ds.rotation_speed(2.0, DISK, BULGE, HALO, mass=1.0)


def test_accelerations_are_softened_and_newtonian():
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    acc = ds.accelerations(pos, [1.0, 1.0], softening=0.0, G=1.0)
    assert _close(acc[0], (1.0, 0.0, 0.0), 1e-12) and _close(acc[1], (-1.0, 0.0, 0.0), 1e-12)
    soft = ds.accelerations(pos, [1.0, 1.0], softening=1.0, G=1.0)
    assert _close(soft[0][0], 2.0 ** -1.5, 1e-12)
    assert _close(ds.accelerations([(0.0, 0.0, 0.0)], [1.0], 0.1, 1.0)[0], (0.0, 0.0, 0.0))


def test_a_two_body_orbit_closes_with_keplers_period():
    pos = [(-0.5, 0.0, 0.0), (0.5, 0.0, 0.0)]
    v = 0.5 * math.sqrt(2.0)
    vel = [(0.0, 0.0, -v), (0.0, 0.0, v)]
    period = 2.0 * math.pi * math.sqrt(1.0 ** 3 / 2.0)
    steps = 2000
    out = ds.nbody_run(pos, vel, [1.0, 1.0], steps, period / steps, softening=0.0, G=1.0)
    assert _close(out["positions"][0], pos[0], 2e-3) and _close(out["positions"][1], pos[1], 2e-3)
    assert out["steps"] == steps


def test_energy_and_momentum_are_conserved():
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 2.0), (-1.5, 0.3, 0.0)]
    vel = [(0.0, 0.0, 0.0), (0.0, 0.1, 0.6), (-0.4, 0.0, 0.0), (0.0, -0.1, -0.3)]
    masses = [2.0, 0.5, 0.5, 0.3]
    e0 = ds.energy(pos, vel, masses, softening=0.1, G=1.0)
    p0 = ds.momentum(vel, masses)
    out = ds.nbody_run(pos, vel, masses, 1000, 0.005, softening=0.1, G=1.0)
    e1 = ds.energy(out["positions"], out["velocities"], masses, softening=0.1, G=1.0)
    assert abs(e1 - e0) < 1e-3 * abs(e0)
    assert _close(ds.momentum(out["velocities"], masses), p0, 1e-9)


def test_the_run_is_a_function_of_the_step_count():
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 2.0)]
    vel = [(0.0, 0.0, 0.0), (0.0, 0.1, 0.6), (-0.4, 0.0, 0.0)]
    whole = ds.nbody_run(pos, vel, [1.0, 0.5, 0.5], 40, 0.01, 0.1, 1.0)
    first = ds.nbody_run(pos, vel, [1.0, 0.5, 0.5], 20, 0.01, 0.1, 1.0)
    rest = ds.nbody_run(first["positions"], first["velocities"], [1.0, 0.5, 0.5], 20, 0.01, 0.1, 1.0)
    assert whole["positions"] == rest["positions"] and whole["velocities"] == rest["velocities"]
    assert ds.nbody_run(pos, vel, [1.0, 0.5, 0.5], 40, 0.01, 0.1, 1.0) == whole


def test_the_run_is_bounded():
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    vel = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.7)]
    with pytest.raises(ValueError):
        ds.nbody_run(pos, vel, [1.0, 1.0], ds.MAX_STEPS + 1, 0.01, 0.1, 1.0)
    with pytest.raises(ValueError):
        ds.nbody_run([(0.0, 0.0, 0.0)] * (ds.MAX_BODIES + 1), [(0.0, 0.0, 0.0)] * (ds.MAX_BODIES + 1), [1.0] * (ds.MAX_BODIES + 1), 1, 0.01, 0.1, 1.0)
    with pytest.raises(ValueError):
        ds.nbody_run(pos, vel, [1.0], 1, 0.01, 0.1, 1.0)
    with pytest.raises(ValueError):
        ds.nbody_run(pos, vel, [1.0, 1.0], 1, 0.0, 0.1, 1.0)


def test_the_galaxy_bodies_rotate_on_the_curve():
    bodies = ds.galaxy_bodies(SEED, 50, DISK, dict(BULGE, share=0.0), dict(ARMS, amplitude=0.0), HALO, mass=1.0)
    assert len(bodies["positions"]) == 50 == len(bodies["velocities"]) == len(bodies["masses"])
    assert _close(sum(bodies["masses"]), 1.0, 1e-9)
    for p, v in zip(bodies["positions"], bodies["velocities"]):
        r = math.hypot(p[0], p[2])
        speed = math.hypot(v[0], v[2])
        assert _close(speed, ds.rotation_speed(r, DISK, dict(BULGE, share=0.0), HALO, mass=1.0), 1e-9)
        assert abs(p[0] * v[0] + p[2] * v[2]) < 1e-9
        assert v[1] == 0.0


def test_merger_bodies_place_two_galaxies_on_approach():
    a = ds.galaxy_bodies(SEED, 30, DISK, dict(BULGE, share=0.0), dict(ARMS, amplitude=0.0), HALO, mass=1.0)
    b = ds.galaxy_bodies(SEED + 1, 20, DISK, dict(BULGE, share=0.0), dict(ARMS, amplitude=0.0), HALO, mass=0.5)
    m = ds.merger_bodies(a, b, separation=10.0, impact=2.0, speed=0.3)
    assert len(m["positions"]) == 50
    cx = sum(mi * p[0] for mi, p in zip(m["masses"], m["positions"])) / sum(m["masses"])
    assert abs(cx) < 1e-9
    px = sum(mi * v[0] for mi, v in zip(m["masses"], m["velocities"]))
    assert abs(px) < 1e-9
    assert sum(p[0] for p in m["positions"][:30]) < 0.0 < sum(p[0] for p in m["positions"][30:])


# ------------------------------------------------------------------------------------ nebulae

def test_the_emission_lines():
    assert _close(ds.LINES["h-alpha"], 656.28)
    assert _close(ds.LINES["oiii"], 500.7)
    assert set(ds.LINES) == {"h-alpha", "h-beta", "oiii", "sii", "nii"}


def test_wavelengths_map_to_colours():
    red = ds.wavelength_colour(ds.LINES["h-alpha"])
    green = ds.wavelength_colour(ds.LINES["oiii"])
    blue = ds.wavelength_colour(ds.LINES["h-beta"])
    for c in (red, green, blue):
        assert max(c) == 1.0 and min(c) >= 0.0
    assert red[0] == 1.0 and red[1] < 0.3 and red[2] < 0.3
    assert green[1] > green[0] and green[1] > green[2]
    assert blue[2] > blue[0]
    with pytest.raises(ValueError):
        ds.wavelength_colour(100.0)


def test_the_palettes():
    assert ds.palette_colour("natural", "h-alpha") == ds.wavelength_colour(ds.LINES["h-alpha"])
    assert ds.palette_colour("sho", "sii") == (1.0, 0.0, 0.0)
    assert ds.palette_colour("sho", "h-alpha") == (0.0, 1.0, 0.0)
    assert ds.palette_colour("sho", "oiii") == (0.0, 0.0, 1.0)
    assert ds.palette_colour("hoo", "h-alpha") == (1.0, 0.0, 0.0)
    assert ds.palette_colour("hoo", "oiii") == (0.0, 1.0, 1.0)
    assert ds.palette_colour("sho", "nii") == (0.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        ds.palette_colour("rgb", "h-alpha")
    with pytest.raises(ValueError):
        ds.palette_colour("sho", "fe")


def test_nebula_emission_sums_the_lines():
    e = ds.nebula_emission({"h-alpha": 1.0, "oiii": 0.5}, "sho")
    assert _close(e, (0.0, 1.0, 0.5))
    assert ds.nebula_emission({}, "sho") == (0.0, 0.0, 0.0)
    e = ds.nebula_emission({"h-alpha": 2.0}, "natural")
    assert _close(e, tuple(2.0 * c for c in ds.wavelength_colour(ds.LINES["h-alpha"])))
    with pytest.raises(ValueError):
        ds.nebula_emission({"h-alpha": -1.0}, "sho")
    with pytest.raises(ValueError):
        ds.nebula_emission({f"line{i}": 1.0 for i in range(ds.MAX_LINES + 1)}, "sho")


def test_the_nebula_sample_feeds_the_a2_medium():
    sigma, emission = ds.nebula_sample(0.5, {"h-alpha": 1.0, "oiii": 0.5}, "sho", extinction=2.0, emission_scale=3.0)
    assert _close(sigma, 1.0)
    assert _close(emission, (0.0, 1.5, 0.75))
    assert ds.nebula_sample(0.0, {"h-alpha": 1.0}, "sho", 2.0, 1.0) == (0.0, (0.0, 0.0, 0.0))


# ------------------------------------------------------------------------------------ the draft

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
    assert "SR-80" in draft
    for word in ("galaxy", "bulge", "arms", "halo", "dynamics", "nebula", "palette", "Sérsic", "sech", "leapfrog",
                 "V17", "seek check", "deepsky_reference.py", "h-alpha", "sho", "Plummer"):
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
    scope = ds.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert ds._same(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(draft, capsys):
    ds.main()
    out = capsys.readouterr().out.strip().splitlines()
    table = [line for line in draft.splitlines() if ROW.match(line) and not line.startswith("| Test")]
    assert out == table
