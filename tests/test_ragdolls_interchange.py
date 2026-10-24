"""Tests of the draft SREP "Add ragdolls and physics interchange to 3D rigid bodies"
(srep/srep-0000-ragdolls-interchange.md) and of its reference implementation
conformance/tools/ragdoll_reference.py (S4 of SREP 12, SRC-40).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import copy
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "ragdoll_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-ragdolls-interchange.md")

_spec = importlib.util.spec_from_file_location("ragdoll_reference", MODULE)
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)

DT = 1.0 / 240.0


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _bar(n, w=1, h=1):
    return [(x, y, z) for z in range(h) for y in range(w) for x in range(n)]


# ------------------------------------------------------------------------------------ rule 1: the partition


def test_splitmix64_matches_the_engine_constants():
    # the first outputs of splitmix64 from state 0 and 1 (Steele, Lea and Flood 2014; pieces.rs mix())
    assert rr.splitmix64(0) == 0
    assert rr.splitmix64(0x9E3779B97F4A7C15) == 0xE220A8397B1DCDAF
    assert rr.splitmix64(2 * 0x9E3779B97F4A7C15 % 2**64) == 0x6E789E6AA1B965F4


def test_seeds_are_drawn_in_the_doubled_box_from_seed_and_index_alone():
    cells = _bar(4, 3, 2)
    lo, hi = rr.doubled((0, 0, 0)), rr.doubled((3, 2, 1))
    seeds = rr.seeds_in(3, 7, lo, hi)
    assert len(seeds) == 3
    for s in seeds:
        assert all(lo[a] <= s[a] <= hi[a] for a in range(3))
    assert rr.seeds_in(3, 7, lo, hi) == seeds
    assert rr.seeds_in(2, 7, lo, hi) == seeds[:2]          # seed s depends on (seed, s) only
    assert rr.seeds_in(3, 8, lo, hi) != seeds
    assert rr.seeds_in(1, 7, lo, hi)[0] == tuple(lo[a] + rr.splitmix64((7 + (a + 1) * rr.GOLDEN) % 2**64)
                                                % (hi[a] - lo[a] + 1) for a in range(3))
    assert rr.doubled((2, -1, 0)) == (5, -1, 1)
    with pytest.raises(rr.PartitionError):
        rr.seeds_in(rr.MAX_SEEDS + 1, 0, lo, hi)
    with pytest.raises(rr.PartitionError):
        rr.seeds_in(1, 0, (1, 0, 0), (0, 0, 0))


def test_every_cell_goes_to_the_nearest_seed_and_ties_go_to_the_lowest_index():
    seeds = ((1, 1, 1), (9, 1, 1), (5, 1, 1))
    assert rr.nearest(seeds, (1, 1, 1)) == 0
    assert rr.nearest(seeds, (7, 1, 1)) == 1         # 2 from seed 1, 2 from seed 2: the lowest index wins
    assert rr.nearest(seeds, (8, 1, 1)) == 1
    assert rr.nearest(seeds, (3, 1, 1)) == 0         # 2 from 0 and 2 from 2: index 0
    labels = rr.voronoi(_bar(6), 2, 0)
    assert len(labels) == 6 and set(labels) <= {0, 1}


def test_the_pieces_are_the_face_connected_parts_of_each_label_in_scan_order():
    cells = _bar(5)
    labels = [0, 1, 0, 0, 1]
    pieces = rr.partition(cells, labels)
    assert pieces == (((0, 0, 0),), ((1, 0, 0),), ((2, 0, 0), (3, 0, 0)), ((4, 0, 0),))
    # scan order is z, then y, then x: (1, 0, 0) comes before (0, 1, 0), and a piece lists its cells in that order
    cells = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
    pieces = rr.partition(cells, [0, 1, 1, 1])
    assert pieces == (((0, 0, 0),), ((1, 0, 0), (0, 1, 0), (1, 1, 0)))
    assert rr.piece_of(pieces, (1, 1, 0)) == 1
    pieces = rr.partition(cells, [0, 1, 1, 0])          # two labels, four pieces: the diagonals are not face-connected
    assert pieces == (((0, 0, 0),), ((1, 0, 0),), ((0, 1, 0),), ((1, 1, 0),))
    assert rr.piece_of(pieces, (1, 1, 0)) == 3 and rr.piece_of(pieces, (5, 5, 5)) is None
    with pytest.raises(rr.PartitionError):
        rr.partition([], [])
    with pytest.raises(rr.PartitionError):
        rr.partition(cells, [0, 1])


def test_fragment_volumes_sum_to_the_whole():
    cells = [(x, y, z) for x in range(6) for y in range(4) for z in range(3)]
    for seed in range(5):
        for count in (1, 2, 5, 8):
            pieces = rr.partition(cells, rr.voronoi(cells, count, seed))
            assert sum(len(p) for p in pieces) == len(cells)
            assert sorted(c for p in pieces for c in p) == sorted(cells)
            assert all(rr.connected(p) for p in pieces)
            assert _close(sum(rr.volume(p, (0.5, 0.25, 0.2)) for p in pieces), rr.volume(cells, (0.5, 0.25, 0.2)))
    assert rr.volume_sum_test() == (True, True, True)


def test_the_pieces_momenta_sum_to_the_whole_body_momentum():
    cells = [(x, y, z) for x in range(4) for y in range(3) for z in range(2)]
    pieces = rr.partition(cells, rr.voronoi(cells, 4, 3))
    size = (0.1, 0.1, 0.1)
    v, omega = (1.0, -2.0, 0.5), (0.3, 1.1, -0.7)
    dp, dl = rr.momentum_test(cells, pieces, size, 1500.0, v, omega)
    assert dp < 1e-12 and dl < 1e-12
    m = rr.moments(cells, size, 1500.0)
    assert _close(m["mass"], 24 * 0.001 * 1500.0)
    assert _close(m["centre"], (0.2, 0.15, 0.1))
    # a unit cube's inertia about its centre is m a^2 / 6 on each axis
    one = rr.moments([(0, 0, 0)], (1.0, 1.0, 1.0), 6.0)
    assert _close(one["inertia"], ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))


# ------------------------------------------------------------------------------------ rule 2: the glue


def test_the_joints_between_pieces_are_their_shared_faces():
    cells = _bar(3, 2, 1)
    pieces = rr.partition(cells, [0, 0, 1, 0, 0, 1])
    js = rr.joints(pieces)
    assert list(js.keys()) == [(0, 1)]
    faces = js[(0, 1)]
    assert len(faces) == 2 and all(f[2] == 0 for f in faces)      # two faces normal to x
    sec = rr.section(faces, (0.5, 0.5, 0.5))
    assert _close(sec["area"], 0.5)
    assert _close(sec["centroid"], (1.0, 0.5, 0.25))
    assert _close(sec["normal"], (1.0, 0.0, 0.0))
    # second moments about the centroid: two 0.5 x 0.5 faces side by side along y
    assert _close(sec["second"][2][2], 2 * 0.25 * 0.5 ** 2 / 12)
    assert _close(sec["second"][1][1], 2 * (0.25 * 0.5 ** 2 / 12 + 0.25 * 0.25 ** 2))
    assert sec["second"][0][0] == 0.0
    assert _close(sec["lo"], (1.0, 0.0, 0.0)) and _close(sec["hi"], (1.0, 1.0, 0.5))


def test_a_pull_is_normal_stress_a_push_is_nothing_and_a_shear_is_a_shear():
    sec = rr.section([((0, 0, 0), (1, 0, 0), 0)], (1.0, 1.0, 1.0))
    pull = rr.cut_stress([sec], [True], {"force": (2.0, 0.0, 0.0), "moment": (0.0, 0.0, 0.0), "point": (1.0, 0.5, 0.5)})[0]
    assert _close(pull["normal"], 2.0) and _close(pull["principal"], 2.0) and pull["bending"] == 0.0
    push = rr.cut_stress([sec], [True], {"force": (-2.0, 0.0, 0.0), "moment": (0.0, 0.0, 0.0), "point": (1.0, 0.5, 0.5)})[0]
    assert _close(push["normal"], -2.0) and push["principal"] == 0.0
    shear = rr.cut_stress([sec], [True], {"force": (0.0, 3.0, 0.0), "moment": (0.0, 0.0, 0.0), "point": (1.0, 0.5, 0.5)})[0]
    assert _close(shear["shear"], 3.0) and _close(shear["principal"], 3.0)
    # a bending moment M about z on a unit square: 6 M / a^3 at the far fibre
    bend = rr.cut_stress([sec], [True], {"force": (0.0, 0.0, 0.0), "moment": (0.0, 0.0, 0.5), "point": (1.0, 0.5, 0.5)})[0]
    assert _close(bend["bending"], 3.0)
    twist = rr.cut_stress([sec], [True], {"force": (0.0, 0.0, 0.0), "moment": (1.0, 0.0, 0.0), "point": (1.0, 0.5, 0.5)})[0]
    assert _close(twist["torsion"], math.sqrt(0.5) / (1.0 / 6.0))
    assert _close(rr.principal_tension(2.0, 1.5), 1.0 + math.sqrt(1.0 + 2.25))
    assert rr.principal_tension(-4.0, 0.0) == 0.0


def test_a_glued_cantilever_carries_the_classic_root_stress():
    n, a, rho, g = 9, 0.1, 2000.0, 9.81
    stresses = rr.cantilever(n, a, rho, g)
    assert len(stresses) == n - 1
    L = (n - 1) * a
    assert _close(stresses[0]["bending"], 3 * rho * g * L * L / a, 1e-9 * rho * g)
    assert _close(stresses[0]["shear"], rho * g * L, 1e-9 * rho * g)
    assert _close(stresses[0]["bending"], rr.cantilever_root(n, a, rho, g)[0], 1e-9 * rho * g)
    assert _close(stresses[0]["normal"], 0.0)
    assert all(stresses[i]["principal"] > stresses[i + 1]["principal"] for i in range(n - 2))


def test_no_glue_breaks_below_its_threshold_and_the_root_breaks_first():
    stresses = rr.cantilever(9, 0.1, 2000.0, 9.81)
    worst = max(s["principal"] for s in stresses)
    assert rr.broken(stresses, worst * 1.001) == ()
    assert rr.broken(stresses, worst * 0.999) == (0,)
    assert rr.broken(stresses, stresses[3]["principal"]) == (0, 1, 2, 3)      # breaks at the threshold itself
    assert rr.glue_test() == (True, True, 4)
    with pytest.raises(rr.PartitionError):
        rr.broken(stresses, 0.0)


# ------------------------------------------------------------------------------------ rules 3 to 9: the ragdoll


def test_a_limb_is_a_capsule_with_closed_form_mass_and_inertia():
    assert _close(rr.capsule_volume(0.5, 2.0), math.pi * 0.25 * 2.0 + 4.0 / 3.0 * math.pi * 0.125)
    axial, transverse = rr.capsule_inertia(1.0, 0.5, 0.0)       # a sphere: 2/5 m r^2 on every axis
    assert _close(axial, 0.1) and _close(transverse, 0.1)
    axial, transverse = rr.capsule_inertia(1.0, 1e-9, 2.0)      # a rod: m L^2 / 12 across, nothing along
    assert _close(transverse, 1.0 / 3.0, 1e-6) and axial < 1e-12
    limb = rr.limb(2.0)
    assert _close(limb["radius"], 0.4) and _close(limb["d"], 1.0)
    assert _close(limb["mass"], 1000.0 * rr.capsule_volume(0.4, 2.0))
    assert limb["kind"] == "hinge" and limb["min"] is None
    assert rr.limb(1.0, mass=3.0)["mass"] == 3.0
    with pytest.raises(rr.RagdollError):
        rr.limb(0.0)
    with pytest.raises(rr.RagdollError):
        rr.limb(1.0, min_angle=10.0, max_angle=-10.0)
    with pytest.raises(rr.RagdollError):
        rr.limb(1.0, kind="wheel")


def test_the_chain_mass_matrix_is_the_lagrangian_one():
    # one link: I_c + m d^2 about the pivot
    c = rr.chain([rr.limb(1.0, mass=2.0, radius=0.1)])
    M = rr.mass_matrix(c, [0.3])
    assert _close(M[0][0], c["limbs"][0]["I"] + 2.0 * 0.25)
    # two equal rods hanging straight: the classic (m L^2 (4/3), m L^2 / 2; m L^2 / 2, m L^2 / 3) for point-free rods
    rod = rr.limb(1.0, mass=1.0, radius=1e-9)
    c = rr.chain([rod, rod])
    M = rr.mass_matrix(c, [math.pi / 2, math.pi / 2])
    assert _close(M[0][0], 4.0 / 3.0, 1e-6) and _close(M[0][1], 0.5, 1e-6)
    assert _close(M[1][0], 0.5, 1e-6) and _close(M[1][1], 1.0 / 3.0, 1e-6)
    assert M[0][1] == M[1][0]
    with pytest.raises(rr.RagdollError):
        rr.chain([])
    with pytest.raises(rr.RagdollError):
        rr.chain([rod] * (rr.MAX_LIMBS + 1))


def test_at_blend_zero_the_chain_is_the_animation():
    c = rr.chain([rr.limb(1.0), rr.limb(0.7)], dt=DT)
    anim = rr.swing_animation((0.2, -0.4), (1.5, 2.0))
    st = rr.run(c, 50, 0.0, anim)
    assert _close(st["phi"], rr.absolute(anim(50 * DT)))
    assert rr.drawn(st, anim(50 * DT), 0.0) == tuple(anim(50 * DT))
    assert _close(st["omega"], rr.absolute([(a - b) / DT for a, b in zip(anim(50 * DT), anim(49 * DT))]))


def test_at_blend_one_the_pendulum_swings_with_its_period():
    limb = rr.limb(1.0, mass=1.0, radius=0.05)
    assert _close(rr.pendulum_period(limb), 2 * math.pi * math.sqrt((limb["I"] + limb["mass"] * 0.25) / (limb["mass"] * 9.81 * 0.5)))
    measured = rr.measured_period(limb, 0.02, DT)
    assert abs(measured / rr.pendulum_period(limb) - 1.0) < 1e-3
    assert rr.period_test() < 1e-3


def test_the_free_double_pendulum_keeps_its_energy():
    assert rr.energy_test() < 1e-3
    c = rr.chain([rr.limb(1.0, mass=1.0), rr.limb(0.8, mass=0.5)], dt=DT, damping=0.0)
    st0 = rr.state(c, [1.0, 2.0])
    e0 = rr.energy(c, st0)
    st = rr.run(c, 1600, 1.0, None, st0)
    assert abs(rr.energy(c, st) - e0) / rr.energy_scale(c) < 1e-3
    assert st["phi"] != st0["phi"]


def test_the_drive_is_proportional_to_one_minus_the_blend():
    assert _close(rr.drive_torque(10.0, 2.0, 0.0, 0.5, 0.2, 0.0, 1.0), 10.0 * 0.3 - 2.0)
    assert _close(rr.drive_torque(10.0, 2.0, 0.5, 0.5, 0.2, 0.0, 1.0), 0.5 * (10.0 * 0.3 - 2.0))
    assert rr.drive_torque(10.0, 2.0, 1.0, 0.5, 0.2, 0.0, 1.0) == 0.0
    assert _close(rr.blend_angle(0.5, 1.5, 0.25), 0.75)
    with pytest.raises(rr.RagdollError):
        rr.drive_torque(10.0, 2.0, 1.5, 0.0, 0.0, 0.0, 0.0)


def test_a_driven_pendulum_settles_where_the_drive_balances_the_weight():
    limb = rr.limb(1.0, mass=1.0, radius=0.05)
    k, w, target = 20.0, 0.5, 1.0
    theta = rr.settled_angle(limb, k, w, target)
    assert _close(k * (1 - w) * (target - theta), limb["mass"] * 9.81 * limb["d"] * math.sin(theta), 1e-9)
    assert 0.0 < theta < target
    assert rr.settle_test() < 1e-5
    assert rr.settled_angle(limb, k, 1.0, target) == 0.0      # no drive: hangs straight down


def test_a_hinge_limit_holds_and_stops_the_limb_inelastically():
    limb = rr.limb(1.0, mass=1.0, radius=0.05, min_angle=-30.0, max_angle=30.0)
    c = rr.chain([limb], dt=DT, damping=0.0)
    st = rr.run(c, 300, 1.0, None, rr.state(c, [1.0]))
    assert rr.relative(c, st["phi"])[0] <= math.radians(30.0) + 1e-12
    assert rr.relative(c, st["phi"])[0] >= math.radians(-30.0) - 1e-12
    assert rr.limit_test() == (True, True)


def test_the_chain_is_a_function_of_the_step_count():
    assert rr.seek_test() == (True, True)
    c = rr.chain([rr.limb(1.0), rr.limb(0.7)], dt=DT)
    anim = rr.swing_animation((0.2, -0.4), (1.5, 2.0))
    a = rr.run(c, 120, 0.5, anim)
    b = rr.run(c, 60, 0.5, anim, rr.run(c, 60, 0.5, anim))
    assert a == b
    with pytest.raises(rr.RagdollError):
        rr.run(c, rr.MAX_STEPS + 1, 0.5, anim)


# ------------------------------------------------------------------------------------ rules 10 to 14: interchange


def _world():
    bodies = [
        rr.body("crate", shape="box", size=(100.0, 50.0, 20.0), mass=2.0, friction=0.4, restitution=0.2,
                velocity=(10.0, -5.0, 2.0), angular_velocity=(0.0, 90.0, 0.0), pos=(300.0, 200.0, -50.0),
                rot=(0.0, math.sin(0.3), 0.0, math.cos(0.3)), group=1, collides_with=(0, 2)),
        rr.body("ball", shape="sphere", size=(40.0, 40.0, 40.0), mass=0.5, pos=(100.0, 100.0, 0.0),
                sensor=True, bullet=True, activate_at=0.5, linear_damping=0.1),
        rr.body("post", kind="static", shape="capsule", size=(20.0, 120.0, 20.0), pos=(0.0, 0.0, 0.0)),
        rr.body("lid", kind="kinematic", shape="cylinder", size=(30.0, 10.0, 30.0), pos=(50.0, 10.0, 0.0),
                fixed_rotation=True),
        rr.body("cone", shape="cone", size=(30.0, 40.0, 30.0), density=700.0, pos=(0.0, 300.0, 0.0)),
    ]
    constraints = [
        rr.constraint("h", "hinge", "crate", "post", anchor=(300.0, 200.0, 0.0), axis=(0.0, 0.0, 1.0),
                      min_angle=-45.0, max_angle=45.0, break_force=100.0),
        rr.constraint("m", "motor", "lid", "post", axis=(0.0, 1.0, 0.0), motor_speed=180.0, max_force=5.0),
        rr.constraint("s", "slider", "ball", "crate", axis=(1.0, 0.0, 0.0), min_angle=-10.0, max_angle=20.0),
        rr.constraint("w", "weld", "cone", "crate"),
        rr.constraint("b", "ball", "ball", "lid", anchor=(10.0, 20.0, 30.0)),
        rr.constraint("d", "distance", "crate", "ball", rest_length=50.0),
        rr.constraint("r", "rope", "crate", "cone", rest_length=80.0),
        rr.constraint("k", "spring", "ball", "cone", stiffness=30.0, damping=2.0, rest_length=10.0),
        rr.constraint("p", "pin", "crate", anchor=(300.0, 200.0, 0.0)),
    ]
    return rr.world(bodies, constraints, ppm=100.0, gravity=(0.0, -9.80665, 0.0), fixed_step=1 / 120, iterations=8,
                    start=0.0, bounds="floor", frame=(1920.0, 1080.0))


def test_scene_vectors_and_quaternions_map_to_the_y_up_frame():
    assert _close(rr.to_metres((100.0, 50.0, -25.0), 100.0), (1.0, -0.5, 0.25))
    assert _close(rr.to_pixels((1.0, -0.5, 0.25), 100.0), (100.0, 50.0, -25.0))
    assert rr.flip_quat((0.1, 0.2, 0.3, 0.9)) == (0.1, -0.2, -0.3, 0.9)
    assert rr.flip_quat(rr.flip_quat((0.1, 0.2, 0.3, 0.9))) == (0.1, 0.2, 0.3, 0.9)
    assert _close(rr.shape_volume("box", (1.0, 2.0, 3.0)), 6.0)
    assert _close(rr.shape_volume("sphere", (2.0, 2.0, 2.0)), 4.0 / 3.0 * math.pi)
    assert _close(rr.shape_volume("capsule", (0.4, 1.2, 0.4)), rr.capsule_volume(0.2, 0.8))
    assert _close(rr.shape_volume("cylinder", (0.4, 1.0, 0.4)), math.pi * 0.04)
    assert _close(rr.shape_volume("cone", (0.4, 3.0, 0.4)), math.pi * 0.04)
    with pytest.raises(rr.InterchangeError):
        rr.shape_volume("trimesh", (1.0, 1.0, 1.0))


def test_a_world_writes_to_usd_physics_in_metres_with_y_up():
    stage = rr.to_usd(_world())
    assert stage["/"]["metersPerUnit"] == 1.0 and stage["/"]["upAxis"] == "Y"
    scene = stage["/World/PhysicsScene"]
    assert scene["type"] == "PhysicsScene"
    assert _close(scene["physics:gravityDirection"], (0.0, -1.0, 0.0))
    assert _close(scene["physics:gravityMagnitude"], 9.80665)
    crate = stage["/World/crate"]
    assert crate["type"] == "Cube" and crate["size"] == 1.0
    assert _close(crate["xformOp:scale"], (1.0, 0.5, 0.2))
    assert _close(crate["xformOp:translate"], (3.0, -2.0, 0.5))
    assert _close(crate["xformOp:orient"], (math.cos(0.3), 0.0, -math.sin(0.3), 0.0))   # USD quaternions are (w, x, y, z)
    assert crate["apiSchemas"] == ("PhysicsRigidBodyAPI", "PhysicsMassAPI", "PhysicsCollisionAPI")
    material = stage["/World/Materials/crate"]
    assert material["type"] == "Material" and material["apiSchemas"] == ("PhysicsMaterialAPI",)
    assert crate["material:binding:physics"] == "/World/Materials/crate"
    assert _close(crate["physics:mass"], 2.0)
    assert _close(crate["physics:velocity"], (0.1, 0.05, -0.02))
    assert _close(crate["physics:angularVelocity"], (0.0, -90.0, 0.0))       # degrees per second, flipped
    assert _close(material["physics:staticFriction"], 0.4) and _close(material["physics:dynamicFriction"], 0.4)
    assert _close(material["physics:restitution"], 0.2)
    assert crate["physics:rigidBodyEnabled"] is True and crate["physics:kinematicEnabled"] is False
    assert stage["/World/post"]["physics:rigidBodyEnabled"] is False           # static: a collider only
    assert stage["/World/lid"]["physics:kinematicEnabled"] is True
    assert stage["/World/cone"]["physics:density"] == 700.0 and "physics:mass" not in stage["/World/cone"]
    assert stage["/World/post"]["type"] == "Capsule" and _close(stage["/World/post"]["radius"], 0.1)
    assert _close(stage["/World/post"]["height"], 1.0)                          # the cylinder part of the capsule
    assert stage["/World/cone"]["type"] == "Cone" and _close(stage["/World/cone"]["height"], 0.4)
    assert stage["/World/ball"]["customData"]["sr:sensor"] is True
    assert stage["/World/ball"]["customData"]["sr:bullet"] is True
    assert stage["/World/ball"]["customData"]["sr:activateAt"] == 0.5
    assert stage["/World/lid"]["customData"]["sr:fixedRotation"] is True
    assert stage["/World/Groups/g1"]["type"] == "PhysicsCollisionGroup"
    assert stage["/World/Groups/g1"]["physics:filteredGroups"] == ("/World/Groups/g1",)
    assert stage["/World/Groups/g1"]["collection:colliders:includes"] == ("/World/crate",)
    assert "physics:filteredGroups" not in stage["/World/Groups/g0"]
    assert stage["/World/crate"]["physics:collisionGroup"] == "/World/Groups/g1"
    assert stage["/World/crate"]["customData"] == {"sr:collidesWith": (0, 2)}
    assert stage["/World/Ground"]["type"] == "Cube" and _close(stage["/World/Ground"]["xformOp:translate"], (9.6, -10.8 - 2.5, 0.0))
    assert stage["/World/PhysicsScene"]["customData"] == {"sr:pixelsPerMeter": 100.0, "sr:fixedStep": 1 / 120,
                                                           "sr:solverIterations": 8, "sr:start": 0.0, "sr:bounds": "floor",
                                                           "sr:frame": (1920.0, 1080.0)}


def test_the_joints_write_to_the_usd_joint_prims():
    stage = rr.to_usd(_world())
    h = stage["/World/Joints/h"]
    assert h["type"] == "PhysicsRevoluteJoint"
    assert h["physics:body0"] == "/World/crate" and h["physics:body1"] == "/World/post"
    assert h["physics:axis"] == "Z"
    assert _close(h["physics:lowerLimit"], -45.0) and _close(h["physics:upperLimit"], 45.0)
    assert _close(h["physics:breakForce"], 100.0)
    q = rr.flip_quat((0.0, math.sin(0.3), 0.0, math.cos(0.3)))
    assert _close(h["physics:localPos0"], rr.rotate(rr.quat_conj(q), (0.0, 0.0, -0.5)))  # the anchor in crate's frame, metres, y-up
    assert _close(h["physics:localPos1"], (3.0, -2.0, 0.0))                              # in post's frame (post at the origin)
    assert h["physics:localRot1"] == (0.0, 1.0, 0.0, 0.0)                                # 180 degrees about x: the frame's Z is the scene's z
    m = stage["/World/Joints/m"]
    assert m["type"] == "PhysicsRevoluteJoint" and m["physics:axis"] == "Y"
    assert "PhysicsDriveAPI:angular" in m["apiSchemas"]
    assert _close(m["drive:angular:physics:targetVelocity"], 180.0)
    assert _close(m["drive:angular:physics:maxForce"], 5.0)
    assert m["drive:angular:physics:type"] == "acceleration"
    s = stage["/World/Joints/s"]
    assert s["type"] == "PhysicsPrismaticJoint" and s["physics:axis"] == "X"
    assert _close(s["physics:lowerLimit"], -0.1) and _close(s["physics:upperLimit"], 0.2)
    assert stage["/World/Joints/w"]["type"] == "PhysicsFixedJoint"
    assert stage["/World/Joints/b"]["type"] == "PhysicsSphericalJoint"
    d = stage["/World/Joints/d"]
    assert d["type"] == "PhysicsDistanceJoint" and _close(d["physics:minDistance"], 0.5) and _close(d["physics:maxDistance"], 0.5)
    r = stage["/World/Joints/r"]
    assert r["type"] == "PhysicsDistanceJoint" and _close(r["physics:maxDistance"], 0.8) and "physics:minDistance" not in r
    k = stage["/World/Joints/k"]
    assert k["type"] == "PhysicsDistanceJoint" and k["customData"]["sr:type"] == "spring"
    assert k["customData"]["sr:stiffness"] == 30.0 and k["customData"]["sr:damping"] == 2.0
    assert _close(k["physics:minDistance"], 0.1) and _close(k["physics:maxDistance"], 0.1)
    p = stage["/World/Joints/p"]
    assert p["type"] == "PhysicsSphericalJoint" and p["physics:body0"] == "/World/crate" and "physics:body1" not in p
    assert p["customData"]["sr:type"] == "pin" and "sr:unset" not in p["customData"]
    assert _close(p["physics:localPos1"], (3.0, -2.0, 0.0))                              # the world anchor
    assert m["customData"]["sr:unset"] == ("anchor",)


def test_the_usd_round_trip_is_the_identity():
    w = _world()
    stage = rr.to_usd(w)
    back = rr.from_usd(stage)
    assert back == w
    assert rr.to_usd(back) == stage
    assert rr.round_trip_test() == (True, True)


def test_a_foreign_usd_body_with_density_gets_the_mass_of_its_shape():
    stage = rr.to_usd(rr.world([rr.body("slab", shape="box", size=(200.0, 100.0, 100.0), density=500.0)], []))
    w = rr.from_usd(stage)
    assert w["bodies"][0]["density"] == 500.0 and w["bodies"][0]["mass"] is None
    assert _close(rr.body_mass(w["bodies"][0], 100.0), 500.0 * 2.0)
    # a stage from outside: no customData, density and no mass, a Sphere
    foreign = {"/": {"metersPerUnit": 1.0, "upAxis": "Y"},
               "/World/PhysicsScene": {"type": "PhysicsScene", "physics:gravityDirection": (0.0, -1.0, 0.0),
                                        "physics:gravityMagnitude": 9.8},
               "/World/rock": {"type": "Sphere", "radius": 0.5, "apiSchemas": ("PhysicsRigidBodyAPI", "PhysicsCollisionAPI"),
                               "xformOp:translate": (1.0, 2.0, 3.0)}}
    w = rr.from_usd(foreign)
    assert w["ppm"] == 100.0 and w["gravity"] == (0.0, -9.8, 0.0)
    rock = w["bodies"][0]
    assert rock["id"] == "rock" and rock["shape"] == "sphere" and _close(rock["size"], (100.0, 100.0, 100.0))
    assert _close(rock["pos"], (100.0, -200.0, -300.0))
    assert rock["mass"] is None and rock["density"] == 1000.0            # UsdPhysics's default density
    assert _close(rr.body_mass(rock, 100.0), 1000.0 * 4.0 / 3.0 * math.pi * 0.125)
    assert rock["friction"] == 0.5 and rock["restitution"] == 0.0


def test_a_usd_stage_with_centimetres_scales_to_metres():
    foreign = {"/": {"metersPerUnit": 0.01, "upAxis": "Y"},
               "/World/rock": {"type": "Sphere", "radius": 50.0, "apiSchemas": ("PhysicsRigidBodyAPI", "PhysicsCollisionAPI"),
                               "xformOp:translate": (100.0, 0.0, 0.0), "physics:velocity": (100.0, 0.0, 0.0), "physics:mass": 2.0}}
    w = rr.from_usd(foreign)
    assert _close(w["bodies"][0]["size"], (100.0, 100.0, 100.0))
    assert _close(w["bodies"][0]["pos"], (100.0, 0.0, 0.0)) and _close(w["bodies"][0]["velocity"], (100.0, 0.0, 0.0))
    assert w["gravity"] == (0.0, -9.80665, 0.0)


def test_what_the_format_cannot_express_is_a_typed_error_never_a_silent_drop():
    base = {"/": {"metersPerUnit": 1.0, "upAxis": "Y"}}
    with pytest.raises(rr.InterchangeError):
        rr.from_usd({**base, "/World/j": {"type": "PhysicsJoint", "physics:body0": "/World/a", "physics:body1": "/World/b"}})
    with pytest.raises(rr.InterchangeError):
        rr.from_usd({**base, "/": {"metersPerUnit": 1.0, "upAxis": "Z"}})
    with pytest.raises(rr.InterchangeError):
        rr.from_usd({**base, "/World/m": {"type": "Mesh", "apiSchemas": ("PhysicsRigidBodyAPI", "PhysicsCollisionAPI")}})
    with pytest.raises(rr.InterchangeError):
        rr.from_usd({**base, "/World/r": {"type": "Sphere", "radius": 1.0, "apiSchemas": ("PhysicsRigidBodyAPI",),
                                          "physics:velocity": (0.0, 0.0, 0.0), "physics:unknownThing": 1.0}})
    with pytest.raises(rr.InterchangeError):
        rr.from_usd({**base, "/World/h": {"type": "PhysicsRevoluteJoint", "physics:body0": "/World/a", "physics:body1": "/World/b",
                                          "physics:axis": "X", "physics:lowerLimit": 10.0}})      # one limit without the other
    assert rr.unsupported_test() == (True, True, True)
    with pytest.raises(rr.InterchangeError):
        rr.to_usd(rr.world([rr.body("m", shape="trimesh", size=(1.0, 1.0, 1.0))], []))
    with pytest.raises(rr.InterchangeError):
        rr.world([rr.body("a")], [rr.constraint("c", "hinge", "a", "nobody")])
    with pytest.raises(rr.InterchangeError):
        rr.world([rr.body("a")] * (rr.MAX_BODIES + 1), [])


def test_a_world_writes_to_gltf_physics_in_metres_with_y_up_and_radians():
    g = rr.to_gltf(_world())
    assert "KHR_physics_rigid_bodies" in g["extensionsUsed"] and "KHR_implicit_shapes" in g["extensionsUsed"]
    nodes = {n["name"]: n for n in g["nodes"]}
    crate = nodes["crate"]["extensions"]["KHR_physics_rigid_bodies"]
    assert _close(crate["motion"]["mass"], 2.0)
    assert _close(crate["motion"]["linearVelocity"], (0.1, 0.05, -0.02))
    assert _close(crate["motion"]["angularVelocity"], (0.0, -math.pi / 2, 0.0))
    assert "isKinematic" not in crate["motion"]
    assert nodes["lid"]["extensions"]["KHR_physics_rigid_bodies"]["motion"]["isKinematic"] is True
    assert "motion" not in nodes["post"]["extensions"]["KHR_physics_rigid_bodies"]
    shapes = g["extensions"]["KHR_implicit_shapes"]["shapes"]
    assert shapes[crate["collider"]["geometry"]["shape"]] == {"type": "box", "box": {"size": [1.0, 0.5, 0.2]}}
    post = nodes["post"]["extensions"]["KHR_physics_rigid_bodies"]
    assert rr._same(shapes[post["collider"]["geometry"]["shape"]], {"type": "capsule", "capsule": {"height": 1.0, "radiusBottom": 0.1, "radiusTop": 0.1}})
    cone = nodes["cone"]["extensions"]["KHR_physics_rigid_bodies"]
    assert shapes[cone["collider"]["geometry"]["shape"]] == {"type": "cylinder", "cylinder": {"height": 0.4, "radiusBottom": 0.15, "radiusTop": 0.0}}
    assert "mass" not in cone["motion"] and nodes["cone"]["extras"]["sr:density"] == 700.0
    materials = g["extensions"]["KHR_physics_rigid_bodies"]["physicsMaterials"]
    assert materials[crate["collider"]["physicsMaterial"]] == {"staticFriction": 0.4, "dynamicFriction": 0.4, "restitution": 0.2}
    ball = nodes["ball"]["extensions"]["KHR_physics_rigid_bodies"]
    assert "trigger" in ball and "collider" not in ball
    assert nodes["ball"]["extras"] == {"sr:bullet": True, "sr:activateAt": 0.5, "sr:linearDamping": 0.1}
    assert "extras" not in nodes["crate"]
    assert _close(nodes["crate"]["translation"], (3.0, -2.0, 0.5))
    assert _close(nodes["crate"]["rotation"], (0.0, -math.sin(0.3), 0.0, math.cos(0.3)))
    filters = g["extensions"]["KHR_physics_rigid_bodies"]["collisionFilters"]
    assert filters[crate["collider"]["collisionFilter"]] == {"collisionSystems": ["g1"], "collideWithSystems": ["g0", "g2"]}
    assert g["extras"]["sr:gravity"] == [0.0, -9.80665, 0.0]
    joints = g["extensions"]["KHR_physics_rigid_bodies"]["physicsJoints"]
    hinge_node = nodes["h"]
    assert hinge_node["extensions"]["KHR_physics_rigid_bodies"]["joint"]["connectedNode"] == g["nodes"].index(nodes["h.b"])
    h = joints[hinge_node["extensions"]["KHR_physics_rigid_bodies"]["joint"]["joint"]]
    assert {"linearAxes": [0, 1, 2], "min": 0.0, "max": 0.0} in h["limits"]
    assert {"angularAxes": [0, 1], "min": 0.0, "max": 0.0} in h["limits"]
    swing = [l for l in h["limits"] if l.get("angularAxes") == [2]]
    assert len(swing) == 1 and _close(swing[0]["min"], -math.pi / 4) and _close(swing[0]["max"], math.pi / 4)
    assert hinge_node["extras"]["sr:breakForce"] == 100.0 and hinge_node["extras"]["sr:type"] == "hinge"
    m = joints[nodes["m"]["extensions"]["KHR_physics_rigid_bodies"]["joint"]["joint"]]
    assert rr._same(m["drives"], [{"type": "angular", "mode": "acceleration", "axis": 1, "velocityTarget": math.pi, "maxForce": 5.0}])


def test_the_gltf_round_trip_is_the_identity():
    w = _world()
    g = rr.to_gltf(w)
    assert rr.from_gltf(g) == w
    assert rr.to_gltf(rr.from_gltf(g)) == g
    g2 = copy.deepcopy(g)
    g2["nodes"][0]["extensions"]["KHR_physics_rigid_bodies"]["motion"]["gravityFactor"] = 0.5
    with pytest.raises(rr.InterchangeError):
        rr.from_gltf(g2)


def test_the_usda_text_is_deterministic_and_names_the_schemas():
    text = rr.usda(rr.to_usd(_world()))
    assert text.startswith("#usda 1.0\n")
    assert 'def PhysicsScene "PhysicsScene"' in text
    assert "float physics:mass = 2" in text
    assert 'prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI", "PhysicsCollisionAPI"]' in text
    assert 'prepend apiSchemas = ["PhysicsMaterialAPI"]' in text
    assert 'rel physics:body0 = </World/crate>' in text
    assert "metersPerUnit = 1" in text and 'upAxis = "Y"' in text
    assert text == rr.usda(rr.to_usd(_world()))
    assert rr.usda_test() == (True, True, True)


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
    assert "SR-84" in draft
    for word in ("ragdoll", "limb", "blend", "driveStiffness", "driveDamping", "swing", "twist", "UsdPhysics",
                 "KHR_physics_rigid_bodies", "KHR_implicit_shapes", "metersPerUnit", "PhysicsRevoluteJoint",
                 "PhysicsDriveAPI", "customData", "extras", "sr:", "Voronoi", "glue", "strength", "principal tension",
                 "cantilever", "fragment volumes", "V17", "seek check", "ragdoll_reference.py", "splitmix64",
                 "Featherstone", "Rankine", "ratified", "kinematic", "slerp", "srcFormat"):
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
    s = rr.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or rr._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    rr.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())
