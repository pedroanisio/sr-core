"""Tests of the draft SREP "Add wave simulations" (srep/srep-0000-wave-sim.md) and of its reference
implementation conformance/tools/wave_sim_reference.py (OW4 of SREP 12, SRC-54).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "wave_sim_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-wave-sim.md")

_spec = importlib.util.spec_from_file_location("wave_sim_reference", MODULE)
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ------------------------------------------------------------------------------------ the ripple tank


def test_cfl_bounds_and_the_time_step():
    assert _close(ws.COURANT_LIMIT_2D, 1.0 / math.sqrt(2.0), 1e-15)
    assert ws.COURANT_LIMIT_1D == 1.0
    assert _close(ws.cfl_dt(0.01, 2.0, 0.5), 0.5 * 0.01 / 2.0, 1e-18)  # the Courant number is c dt / dx
    assert ws.courant_stable(0.7, 2)
    assert not ws.courant_stable(0.71, 2)
    assert ws.courant_stable(1.0, 1)
    assert not ws.courant_stable(1.01, 1)
    with pytest.raises(ws.WaveSimError):
        ws.cfl_dt(0.0, 1.0, 0.5)
    with pytest.raises(ws.WaveSimError):
        ws.cfl_dt(0.01, 1.0, 0.8)  # above the 2D limit


def test_a_plane_wave_travels_at_the_wave_speed_and_refracts():
    # a periodic-in-y tank is a 1D line: launch a pulse and time its crest
    tank = ws.tank(nx=160, ny=4, dx=1.0, speed=1.0, courant=0.5, boundary="periodic")
    ws.inject_pulse(tank, x=20, width=4.0, amplitude=1.0)
    x0 = ws.crest_x(tank)
    ws.run(tank, steps=100)
    x1 = ws.crest_x(tank)
    speed = (x1 - x0) / (100 * tank["dt"])
    assert _close(speed, 1.0, 0.03)
    # a slower region on the right: the crest moves at half the speed there
    slow = ws.tank(nx=200, ny=4, dx=1.0, speed=1.0, courant=0.5, boundary="periodic")
    ws.set_speed(slow, lambda x, y: 1.0 if x < 100 else 0.5)
    ws.inject_pulse(slow, x=120, width=4.0, amplitude=1.0)
    x0 = ws.crest_x(slow)
    ws.run(slow, steps=100)
    x1 = ws.crest_x(slow)
    assert _close((x1 - x0) / (100 * slow["dt"]), 0.5, 0.03)
    assert slow["dt"] == tank["dt"]  # dt follows the fastest speed


def test_reflecting_walls_conserve_the_discrete_energy_and_sponges_absorb():
    tank = ws.tank(nx=64, ny=64, dx=1.0, speed=1.0, courant=0.5, boundary="reflecting")
    ws.inject_pulse(tank, x=32, y=32, width=3.0, amplitude=1.0)
    e0 = ws.energy(tank)
    ws.run(tank, steps=200)
    assert _close(ws.energy(tank) / e0, 1.0, 0.02)
    absorbing = ws.tank(nx=64, ny=64, dx=1.0, speed=1.0, courant=0.5, boundary="absorbing", sponge=16)
    ws.inject_pulse(absorbing, x=32, y=32, width=3.0, amplitude=1.0)
    e0 = ws.energy(absorbing)
    ws.run(absorbing, steps=200)
    assert ws.energy(absorbing) / e0 < 0.05
    assert ws.max_abs(absorbing) < 0.1  # low-frequency content of a 3-cell pulse sees a 16-cell sponge as abrupt
    assert ws.max_abs(absorbing) < 0.5 * ws.max_abs(tank)
    assert ws.sponge_factor(0, 16) < 1.0 < 1.0 + 1e-15
    assert ws.sponge_factor(16, 16) == 1.0
    assert ws.sponge_factor(0, 16) < ws.sponge_factor(8, 16) < 1.0


def test_walls_block_and_slits_pass():
    tank = ws.tank(nx=96, ny=96, dx=1.0, speed=1.0, courant=0.5, boundary="absorbing", sponge=12)
    ws.add_wall(tank, x=48, slits=[(38, 58)])  # a wall at x = 48 with one slit from y 38 to 58, 2.5 wavelengths
    src = ws.source(kind="point", x=20, y=48, frequency=0.125, amplitude=1.0, waveform="continuous")
    ws.run(tank, steps=160, sources=[src])
    behind_slit = ws.rms_region(tank, (60, 70), (44, 52))
    behind_wall = ws.rms_region(tank, (60, 70), (8, 16))  # 65 degrees off the slit's axis: the geometric shadow
    assert behind_slit > 5.0 * behind_wall
    assert ws.field_at(tank, 48, 10) == 0.0  # the wall itself stays at rest
    # a line source makes a plane wave: equal field along y away from the sponge
    plane = ws.tank(nx=96, ny=48, dx=1.0, speed=1.0, courant=0.5, boundary="periodic")
    line = ws.source(kind="line", x=10, frequency=0.05, amplitude=1.0, waveform="continuous")
    ws.run(plane, steps=120, sources=[line])
    column = [ws.field_at(plane, 50, y) for y in range(48)]
    assert max(column) - min(column) < 1e-9


def test_an_unstable_courant_number_is_refused_and_would_blow_up():
    with pytest.raises(ws.WaveSimError):
        ws.tank(nx=32, ny=32, dx=1.0, speed=1.0, courant=0.9, boundary="reflecting")
    unstable = ws.tank(nx=32, ny=32, dx=1.0, speed=1.0, courant=0.5, boundary="reflecting")
    unstable["dt"] *= 1.5  # courant 0.75: past the 2D bound 0.7071
    ws.inject_pulse(unstable, x=16, y=16, width=2.0, amplitude=1.0)
    ws.run(unstable, steps=120)
    assert ws.max_abs(unstable) > 1e3


def test_two_sources_interfere_with_the_expected_fringe_count():
    tank = ws.tank(nx=120, ny=96, dx=1.0, speed=1.0, courant=0.5, boundary="absorbing", sponge=12)
    lam = 8.0
    f = 1.0 / lam
    d = 24.0
    s1 = ws.source(kind="point", x=20, y=48 - d / 2, frequency=f, amplitude=1.0, waveform="continuous")
    s2 = ws.source(kind="point", x=20, y=48 + d / 2, frequency=f, amplitude=1.0, waveform="continuous")
    ws.run(tank, steps=320, sources=[s1, s2])
    # along the column x = 90 the time-averaged intensity has a maximum on the axis
    profile = ws.rms_column(tank, 90, 16, 80)
    centre = profile[len(profile) // 2]
    assert centre == max(profile)
    maxima = ws.local_maxima(profile)
    assert len(maxima) >= 3
    # the first-order maxima sit near the angle sin(theta) = lambda / d
    y_first = 70.0 * lam / d  # L tan(theta) ~ L lambda / d at L = 70
    nearest = min((abs(m - len(profile) // 2) for m in maxima if abs(m - len(profile) // 2) > 2), default=None)
    assert nearest is not None and abs(nearest - y_first) < 0.25 * y_first


# ------------------------------------------------------------------------------------ strings


def test_string_modes_frequencies_and_nodes():
    L, c = 1.0, 2.0
    assert _close(ws.mode_frequency(1, L, c, "fixed"), c / (2.0 * L), 1e-15)
    assert _close(ws.mode_frequency(3, L, c, "fixed"), 3.0 * c / (2.0 * L), 1e-15)
    assert _close(ws.mode_frequency(1, L, c, "free"), c / (4.0 * L), 1e-15)  # fixed-free: odd quarter waves
    assert _close(ws.mode_frequency(2, L, c, "free"), 3.0 * c / (4.0 * L), 1e-15)
    assert _close(ws.node_positions(3, L), (0.0, L / 3.0, 2.0 * L / 3.0, L), 1e-15)
    assert _close(ws.mode_wavelength(2, L), L, 1e-15)  # nodes at n lambda / 2
    x, t = 0.25, 0.1
    assert _close(ws.standing_wave(x, t, 2, L, c, 1.0),
                  math.sin(2.0 * math.pi * x / L) * math.cos(2.0 * math.pi * ws.mode_frequency(2, L, c, "fixed") * t), 1e-12)
    with pytest.raises(ws.WaveSimError):
        ws.mode_frequency(0, L, c, "fixed")


def test_a_simulated_string_vibrates_at_the_mode_frequency_with_nodes_at_rest():
    L, c = 1.0, 1.0
    s = ws.string(n=200, length=L, speed=c, ends="fixed", courant=0.5)
    ws.set_shape(s, lambda x: math.sin(2.0 * math.pi * x / L))  # the second mode
    mid = s["n"] // 2
    quarter = s["n"] // 4
    history = []
    for _ in range(2400):
        ws.string_step(s)
        history.append(s["u"][quarter])
        assert abs(s["u"][mid]) < 1e-6  # the node at L / 2 stays at rest
    period = ws.period_from_history(history, s["dt"])
    assert _close(1.0 / period, ws.mode_frequency(2, L, c, "fixed"), 0.01)
    # a plucked string's energy is conserved without damping and decays with it
    p = ws.string(n=100, length=L, speed=c, ends="fixed", courant=0.5)
    ws.pluck(p, position=0.3, amplitude=0.01)
    e0 = ws.string_energy(p)
    for _ in range(400):
        ws.string_step(p)
    assert _close(ws.string_energy(p) / e0, 1.0, 0.02)
    damped = ws.string(n=100, length=L, speed=c, ends="fixed", courant=0.5, damping=2.0)
    ws.pluck(damped, position=0.3, amplitude=0.01)
    e0 = ws.string_energy(damped)
    for _ in range(400):
        ws.string_step(damped)
    assert ws.string_energy(damped) / e0 < 0.5
    # a struck string starts from rest with a velocity; a driven end follows the drive
    struck = ws.string(n=100, length=L, speed=c, ends="fixed", courant=0.5)
    ws.strike(struck, position=0.5, width=0.1, velocity=1.0)
    assert max(abs(v) for v in struck["u"]) == 0.0
    ws.string_step(struck)
    assert max(abs(v) for v in struck["u"]) > 0.0
    driven = ws.string(n=100, length=L, speed=c, ends="fixed", courant=0.5)
    for _ in range(50):
        ws.string_step(driven, drive=ws.drive(frequency=1.0, amplitude=0.01))
    assert _close(driven["u"][0], 0.01 * math.sin(2.0 * math.pi * 1.0 * driven["t"]), 1e-12)


# ------------------------------------------------------------------------------------ plates


def test_simply_supported_plate_closed_forms():
    a, b = 2.0, 1.0
    assert _close(ws.plate_mode_ss(1, 1, a, b, a / 2.0, b / 2.0), 1.0, 1e-15)
    assert _close(ws.plate_mode_ss(2, 1, a, b, a / 2.0, b / 2.0), 0.0, 1e-12)
    f11 = ws.plate_frequency_ss(1, 1, a, b, 1.0)
    assert _close(f11, math.pi / 2.0 * ((1.0 / a) ** 2 + (1.0 / b) ** 2), 1e-12)
    assert _close(ws.plate_frequency_ss(2, 1, a, b, 1.0) / f11, (4.0 / a ** 2 + 1.0 / b ** 2) / (1.0 / a ** 2 + 1.0 / b ** 2), 1e-12)
    lines = ws.nodal_lines_ss(3, 2, a, b)
    assert _close(lines["x"], (a / 3.0, 2.0 * a / 3.0), 1e-15)
    assert _close(lines["y"], (b / 2.0,), 1e-15)
    with pytest.raises(ws.WaveSimError):
        ws.plate_mode_ss(0, 1, a, b, 0.5, 0.5)


def test_free_free_beam_functions_are_orthonormal_with_the_right_roots():
    k = ws.beam_roots(4)
    assert _close(k[0], 2.3650204, 1e-6)  # the first even root of tan k + tanh k = 0
    assert _close(k[1], 3.9266023, 1e-6)  # the first odd root of tan k - tanh k = 0
    assert _close(k[2], 5.4978039, 1e-6)
    assert _close(k[3], 7.0685827, 1e-6)
    fns = ws.beam_functions(6)
    assert len(fns) == 6
    for i in range(6):
        for j in range(6):
            inner = ws.integrate(lambda x: fns[i](x) * fns[j](x))
            assert _close(inner, 1.0 if i == j else 0.0, 1e-6), (i, j)
    # the first two are the rigid modes, the rest bend
    assert _close(ws.integrate(lambda x: ws.beam_second_derivative(0)(x) ** 2), 0.0, 1e-12)
    assert ws.integrate(lambda x: ws.beam_second_derivative(2)(x) ** 2) > 1.0
    # the free-end conditions: zero curvature at x = 1
    assert _close(ws.beam_second_derivative(2)(1.0), 0.0, 1e-6)
    assert _close(ws.beam_second_derivative(3)(1.0), 0.0, 1e-6)


def test_ritz_plate_has_three_rigid_modes_and_symmetric_flexible_modes():
    res = ws.ritz_plate(basis=4, poisson=0.225)
    lams = res["eigenvalues"]
    assert len(lams) == 16
    assert all(lams[i] <= lams[i + 1] + 1e-9 for i in range(15))
    assert all(abs(v) < 1e-8 for v in lams[:3])  # translation and two rotations
    assert lams[3] > 1.0
    # the lowest flexible mode is the twist mode: it vanishes on both medians and its single-term Rayleigh
    # quotient 18 (1 - nu) bounds it from above
    mode = ws.plate_mode_free(res, 3)
    for s in (0.3, -0.7, 0.95):
        assert abs(mode(0.0, s)) < 1e-9 and abs(mode(s, 0.0)) < 1e-9
    assert abs(mode(0.5, 0.5)) > 1e-3
    assert lams[3] <= 18.0 * (1.0 - 0.225) + 1e-9
    assert ws.mode_symmetry(res, 3) == ("odd", "odd")
    # the saddle mode (even, even, antisymmetric in the swap) vanishes on the diagonals
    idx = ws.first_mode_with_symmetry(res, ("even", "even"), swap="anti")
    saddle = ws.plate_mode_free(res, idx)
    for s in (0.3, -0.7, 0.95):
        assert abs(saddle(s, s)) < 1e-9 and abs(saddle(s, -s)) < 1e-9
    # more basis functions lower the Ritz eigenvalues (an upper-bound method) and converge
    bigger = ws.ritz_plate(basis=6, poisson=0.225)["eigenvalues"]
    assert bigger[3] <= lams[3] + 1e-9
    assert _close(bigger[3], lams[3], 0.05 * lams[3])
    with pytest.raises(ws.WaveSimError):
        ws.ritz_plate(basis=1, poisson=0.225)


def test_nodal_lines_and_sand():
    res = ws.ritz_plate(basis=4, poisson=0.225)
    mode = ws.plate_mode_free(res, 3)
    zero = ws.nodal_points(mode, grid=41)
    assert zero
    assert all(abs(x) < 0.06 or abs(y) < 0.06 for x, y in zero)  # the twist mode's nodes are the medians
    particles = [(-0.8 + 1.6 * i / 9.0, -0.8 + 1.6 * j / 9.0) for i in range(10) for j in range(10)]
    settled = ws.chladni_sand(mode, particles, steps=200, step_size=0.01)
    assert len(settled) == 100
    amp = max(abs(mode(x, y)) for x, y in particles)
    assert all(abs(mode(x, y)) < 0.05 * amp for x, y in settled)
    assert all(-1.0 <= x <= 1.0 and -1.0 <= y <= 1.0 for x, y in settled)


# ------------------------------------------------------------------------------------ animation and the seek check


def test_frames_are_pure_functions_of_the_frame_and_the_seek_check_holds():
    spec = {"nx": 48, "ny": 32, "dx": 1.0, "speed": 1.0, "courant": 0.5, "boundary": "absorbing", "sponge": 8,
            "stepsPerFrame": 4, "sources": [ws.source(kind="point", x=16, y=16, frequency=0.05, amplitude=1.0,
                                                      waveform="pulse", cycles=2)]}
    a = ws.frame_state(spec, 12)
    b = ws.frame_state(spec, 12)
    assert a["u"] == b["u"]
    assert ws.frame_state(spec, 13)["u"] != a["u"]
    assert ws.seek_test() is True
    with pytest.raises(ws.WaveSimError):
        ws.frame_state(spec, -1)
    with pytest.raises(ws.WaveSimError):
        ws.frame_state({**spec, "stepsPerFrame": 65}, 1)


# ------------------------------------------------------------------------------------ sampled hits


def test_hits_follow_the_profile_and_the_stream():
    hits = ws.sample_hits([1.0, 2.0, 1.0], 4000, seed=7)
    assert len(hits) == 4000
    assert all(0.0 <= h < 3.0 for h in hits)
    counts = ws.hit_histogram(hits, 3)
    assert abs(counts[1] / 4000 - 0.5) < 0.03
    assert abs(counts[0] / 4000 - 0.25) < 0.03
    assert hits == ws.sample_hits([1.0, 2.0, 1.0], 4000, seed=7)
    assert hits[10:13] == ws.sample_hits([1.0, 2.0, 1.0], 3, seed=7, first=10)
    assert hits != ws.sample_hits([1.0, 2.0, 1.0], 4000, seed=8)
    assert ws.sample_hits([0.0, 0.0, 5.0], 20, seed=1) == [h for h in ws.sample_hits([0.0, 0.0, 5.0], 20, seed=1) if 2.0 <= h < 3.0]
    assert 0.0 <= ws.hit_unit(7, 0) < 1.0
    assert ws.hit_unit(7, 0) == ws.U(7, ws.CHANNEL_HIT, 0)
    for bad in (([], 1), ([1.0, -1.0], 1), ([0.0, 0.0], 1), ([1.0], ws.MAX_HITS + 1), ([1.0], -1)):
        with pytest.raises(ws.WaveSimError):
            ws.sample_hits(bad[0], bad[1], seed=0)
    with pytest.raises(ws.WaveSimError):
        ws.hit_unit(1 << 64, 0)


# ------------------------------------------------------------------------------------ validation


def test_validation_rules():
    ws.validate_tank({"nx": 100, "ny": 100, "dx": 0.01, "speed": 1.0, "courant": 0.5, "boundary": "absorbing",
                      "sponge": 20, "stepsPerFrame": 4})
    for bad in ({"nx": 5000, "ny": 100, "dx": 0.01, "speed": 1.0, "courant": 0.5, "boundary": "absorbing"},
                {"nx": 100, "ny": 100, "dx": 0.01, "speed": 1.0, "courant": 0.8, "boundary": "absorbing"},
                {"nx": 100, "ny": 100, "dx": 0.01, "speed": 0.0, "courant": 0.5, "boundary": "absorbing"},
                {"nx": 100, "ny": 100, "dx": 0.01, "speed": 1.0, "courant": 0.5, "boundary": "mirror"},
                {"nx": 100, "ny": 100, "dx": 0.01, "speed": 1.0, "courant": 0.5, "boundary": "absorbing", "sponge": -1},
                {"nx": 100, "ny": 100, "dx": 0.01, "speed": 1.0, "courant": 0.5, "boundary": "absorbing",
                 "stepsPerFrame": 0}):
        with pytest.raises(ws.WaveSimError):
            ws.validate_tank(bad)
    ws.validate_string({"segments": 100, "length": 1.0, "speed": 1.0, "ends": "fixed", "courant": 1.0, "damping": 0.0})
    for bad in ({"segments": 2, "length": 1.0, "speed": 1.0, "ends": "fixed", "courant": 0.5},
                {"segments": 100, "length": 1.0, "speed": 1.0, "ends": "loose", "courant": 0.5},
                {"segments": 100, "length": 1.0, "speed": 1.0, "ends": "fixed", "courant": 1.1},
                {"segments": 100, "length": 1.0, "speed": 1.0, "ends": "fixed", "courant": 0.5, "damping": -1.0}):
        with pytest.raises(ws.WaveSimError):
            ws.validate_string(bad)
    ws.validate_plate({"support": "free", "basis": 6, "poisson": 0.225, "mode": 4})
    ws.validate_plate({"support": "simplySupported", "m": 2, "n": 3})
    for bad in ({"support": "clamped", "basis": 6, "poisson": 0.225, "mode": 4},
                {"support": "free", "basis": 1, "poisson": 0.225, "mode": 4},
                {"support": "free", "basis": 6, "poisson": 0.5, "mode": 4},
                {"support": "free", "basis": 4, "poisson": 0.225, "mode": 16},
                {"support": "simplySupported", "m": 0, "n": 3}):
        with pytest.raises(ws.WaveSimError):
            ws.validate_plate(bad)
    ws.validate_source(ws.source(kind="point", x=1, y=1, frequency=1.0, amplitude=1.0, waveform="pulse", cycles=3))
    for bad in ({"kind": "blob", "x": 1, "y": 1, "frequency": 1.0, "amplitude": 1.0, "waveform": "continuous"},
                {"kind": "point", "x": 1, "y": 1, "frequency": 0.0, "amplitude": 1.0, "waveform": "continuous"},
                {"kind": "point", "x": 1, "y": 1, "frequency": 1.0, "amplitude": 1.0, "waveform": "square"},
                {"kind": "point", "x": 1, "y": 1, "frequency": 1.0, "amplitude": 1.0, "waveform": "pulse", "cycles": 0}):
        with pytest.raises(ws.WaveSimError):
            ws.validate_source(bad)


def test_constants():
    assert ws.BOUNDARIES == ("absorbing", "reflecting", "periodic")
    assert ws.SOURCE_KINDS == ("point", "line")
    assert ws.WAVEFORMS == ("continuous", "pulse")
    assert ws.END_KINDS == ("fixed", "free")
    assert ws.PLATE_SUPPORTS == ("simplySupported", "free")
    assert ws.MAX_GRID == 4096
    assert ws.MAX_STEPS_PER_FRAME == 64
    assert ws.MAX_BASIS == 12


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
    for word in ("SR-96", "SREP 92", "hits", "rippleTank", "string", "chladniPlate", "courant", "boundary", "absorbing", "reflecting",
                 "periodic", "sponge", "stepsPerFrame", "source", "wall", "slit", "speedRegion", "ends", "pluck",
                 "strike", "drive", "damping", "support", "simplySupported", "free", "basis", "poisson", "sand",
                 "CFL", "Courant", "Ritz", "Gander", "Wanner", "beam functions", "Chladni", "nodal", "WS1", "WS2",
                 "WS3", "WS4", "V17", "seek check", "SREP 14", "wave_sim_reference.py", "Leissa", "Strikwerda"):
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
    s = ws.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or ws._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    ws.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
