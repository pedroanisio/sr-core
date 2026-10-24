"""Tests of the draft SREP "Add scalar 3D: isosurfaces and transfer-function volumes"
(srep/srep-0000-scalar3d.md) and of its reference module conformance/tools/scalar3d_reference.py:
the tetrahedral decomposition of a cell, the triangles of a tetrahedron, welded isosurface meshes, their
area, volume, orientation and manifoldness, the sphere's O(h^2) area convergence, normals, grid functions,
transfer functions on a medium, and the SREP's numeric table against the module.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "scalar3d_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-scalar3d.md")

spec = importlib.util.spec_from_file_location("scalar3d_reference", MODULE)
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

UNIT = (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
BOX = (-1.25, 1.25, -1.25, 1.25, -1.25, 1.25)


def sphere(x, y, z):
    return x * x + y * y + z * z - 1.0


def plane_x(x, y, z):
    return x - 0.5


def _close(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


# ------------------------------------------------------------------------------------------ the cell

def test_the_six_tetrahedra_share_the_main_diagonal_and_fill_the_cell():
    assert len(sc.TETS) == 6
    for tet in sc.TETS:
        assert tet[0] == 0 and tet[3] == 6
        assert len(set(tet)) == 4
    corners = sc.cell_corners(UNIT)
    assert corners[0] == (0.0, 0.0, 0.0) and corners[6] == (1.0, 1.0, 1.0)
    total = sum(sc.tet_volume(*(corners[i] for i in tet)) for tet in sc.TETS)
    assert _close(total, 1.0)
    for tet in sc.TETS:
        assert sc.tet_volume(*(corners[i] for i in tet)) > 0.0


def test_the_cell_corners_follow_the_bit_order():
    corners = sc.cell_corners((0.0, 2.0, 0.0, 4.0, 0.0, 8.0))
    assert corners == ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 4.0, 0.0), (0.0, 4.0, 0.0),
                       (0.0, 0.0, 8.0), (2.0, 0.0, 8.0), (2.0, 4.0, 8.0), (0.0, 4.0, 8.0))


def test_the_edge_point_interpolates_the_level_and_lands_on_a_corner_at_the_level():
    assert sc.edge_point((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), -1.0, 3.0, 0.0) == (0.5, 0.0, 0.0)
    assert sc.edge_point((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 0.0, 3.0, 0.0) == (0.0, 0.0, 0.0)
    assert sc.edge_point((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), -1.0, 1.0, 0.5) == (1.5, 0.0, 0.0)
    with pytest.raises(ValueError):
        sc.edge_point((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 1.0, 3.0, 0.0)


# -------------------------------------------------------------------------------- one tetrahedron

TET = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def test_a_tetrahedron_with_no_crossing_gives_no_triangle():
    assert sc.tet_triangles(TET, (-1.0, -1.0, -1.0, -1.0), 0.0) == ()
    assert sc.tet_triangles(TET, (1.0, 1.0, 1.0, 1.0), 0.0) == ()
    assert sc.tet_triangles(TET, (0.0, 0.0, 0.0, 0.0), 0.0) == ()


def test_one_or_three_corners_inside_give_one_triangle_two_give_two():
    assert len(sc.tet_triangles(TET, (1.0, -1.0, -1.0, -1.0), 0.0)) == 1
    assert len(sc.tet_triangles(TET, (-1.0, 1.0, 1.0, 1.0), 0.0)) == 1
    assert len(sc.tet_triangles(TET, (1.0, 1.0, -1.0, -1.0), 0.0)) == 2
    assert len(sc.tet_triangles(TET, (-1.0, -1.0, 1.0, 1.0), 0.0)) == 2


def test_the_triangles_face_the_rising_side():
    for values in ((1.0, -1.0, -1.0, -1.0), (-1.0, 1.0, 1.0, 1.0), (1.0, 1.0, -1.0, -1.0), (-1.0, -1.0, 1.0, 1.0)):
        grad = sc.tet_gradient(TET, values)
        for tri in sc.tet_triangles(TET, values, 0.0):
            n = sc.triangle_normal(tri)
            assert sum(a * b for a, b in zip(n, grad)) > 0.0


def test_the_gradient_of_a_linear_function_on_a_tetrahedron_is_exact():
    values = tuple(2.0 * x - 3.0 * y + 0.5 * z + 7.0 for x, y, z in TET)
    assert _close(sc.tet_gradient(TET, values), (2.0, -3.0, 0.5))


def test_the_triangle_of_one_corner_lies_on_the_level():
    tris = sc.tet_triangles(TET, (1.0, -1.0, -1.0, -1.0), 0.0)
    assert _close(sorted(tris[0]), [(0.0, 0.0, 0.5), (0.0, 0.5, 0.0), (0.5, 0.0, 0.0)])


# ------------------------------------------------------------------------------------- the mesh

def test_a_plane_through_the_unit_cell_is_a_unit_square_of_eight_triangles():
    vertices, faces = sc.isosurface(plane_x, UNIT, 1)
    assert len(faces) == 8 and len(vertices) == 9
    assert all(_close(v[0], 0.5) for v in vertices)
    assert _close(sc.mesh_area(vertices, faces), 1.0)
    assert sc.euler(vertices, faces) == 1


def test_the_mesh_is_welded_and_the_same_at_any_resolution_for_a_plane():
    for res in (1, 2, 3):
        vertices, faces = sc.isosurface(plane_x, UNIT, res)
        assert len(set(vertices)) == len(vertices)
        assert _close(sc.mesh_area(vertices, faces), 1.0)


def test_a_surface_on_a_grid_line_is_drawn_once_from_the_cells_below_it():
    vertices, faces = sc.isosurface(plane_x, UNIT, (2, 1, 3))
    assert _close(sc.mesh_area(vertices, faces), 1.0)
    assert len(faces) == 6 and len(vertices) == 8
    assert sc.euler(vertices, faces) == 1


def test_the_resolution_may_differ_per_axis():
    vertices, faces = sc.isosurface(plane_x, UNIT, (3, 1, 2))
    assert _close(sc.mesh_area(vertices, faces), 1.0)
    assert len(faces) == 2 * 8


def test_the_level_shifts_the_surface():
    vertices, faces = sc.isosurface(lambda x, y, z: x, UNIT, 2, level=0.25)
    assert all(_close(v[0], 0.25) for v in vertices)


def test_the_sphere_mesh_is_closed_manifold_and_outward():
    vertices, faces = sc.isosurface(sphere, BOX, 6)
    assert sc.euler(vertices, faces) == 2
    assert sc.is_closed(vertices, faces)
    assert sc.mesh_volume(vertices, faces) > 0.0
    for a, b, c in faces:
        n = sc.triangle_normal((vertices[a], vertices[b], vertices[c]))
        centre = tuple(sum(p[i] for p in (vertices[a], vertices[b], vertices[c])) / 3.0 for i in range(3))
        assert sum(x * y for x, y in zip(n, centre)) > 0.0


def test_the_sphere_area_error_falls_as_h_squared():
    errors = [abs(sc.mesh_area(*sc.sphere_mesh(res)) - 4.0 * math.pi) for res in (6, 12, 24)]
    assert errors[0] > errors[1] > errors[2]
    assert sc.convergence_order(errors[0], errors[1]) >= 1.7
    assert sc.convergence_order(errors[1], errors[2]) >= 1.7


def test_the_sphere_volume_converges_too():
    errors = [abs(sc.mesh_volume(*sc.sphere_mesh(res)) - 4.0 * math.pi / 3.0) for res in (6, 12, 24)]
    assert errors[0] > errors[1] > errors[2]


def test_the_mesh_is_a_function_of_its_inputs():
    assert sc.isosurface(sphere, BOX, 6) == sc.isosurface(sphere, BOX, 6)
    vertices, faces = sc.isosurface(sphere, BOX, 6)
    assert vertices == sc.sphere_mesh(6)[0]


def test_an_animated_level_is_the_same_alone_and_played():
    played = [sc.isosurface(sphere, BOX, 4, level=l) for l in (-0.5, 0.0, 0.5)]
    alone = sc.isosurface(sphere, BOX, 4, level=0.5)
    assert played[2] == alone


def test_degenerate_triangles_are_dropped():
    vertices, faces = sc.isosurface(lambda x, y, z: x + y + z - 1.0, UNIT, 1)
    for a, b, c in faces:
        assert sc.triangle_area((vertices[a], vertices[b], vertices[c])) > 0.0
    assert _close(sc.mesh_area(vertices, faces), math.sqrt(3.0) / 2.0)


def test_the_bounds_are_errors():
    with pytest.raises(ValueError):
        sc.isosurface(sphere, BOX, 0)
    with pytest.raises(ValueError):
        sc.isosurface(sphere, BOX, sc.MAX_RESOLUTION + 1)
    with pytest.raises(ValueError):
        sc.isosurface(sphere, BOX, (1024, 1024, 1024))
    with pytest.raises(ValueError):
        sc.isosurface(sphere, (1.0, 0.0, 0.0, 1.0, 0.0, 1.0), 1)
    with pytest.raises(ValueError):
        sc.isosurface(lambda x, y, z: float("nan"), UNIT, 1)
    with pytest.raises(ValueError):
        sc.isosurface(lambda x, y, z: float("inf"), UNIT, 1)


# ---------------------------------------------------------------------------------------- normals

def test_vertex_normals_are_unit_and_outward_on_the_sphere():
    vertices, faces = sc.sphere_mesh(12)
    normals = sc.vertex_normals(vertices, faces)
    assert len(normals) == len(vertices)
    for v, n in zip(vertices, normals):
        assert _close(math.sqrt(sum(c * c for c in n)), 1.0)
        assert sum(a * b for a, b in zip(v, n)) > 0.9


def test_gradient_normals_point_along_the_gradient():
    n = sc.gradient_normal(sphere, (0.6, 0.0, 0.8), 1e-3)
    assert _close(n, (0.6, 0.0, 0.8), 1e-6)
    with pytest.raises(ValueError):
        sc.gradient_normal(lambda x, y, z: 1.0, (0.0, 0.0, 0.0), 1e-3)


# ---------------------------------------------------------------------------------- grid functions

def test_trilinear_interpolation_of_a_grid():
    dims = (2, 2, 2)
    values = tuple(float(i) for i in range(8))
    f = sc.grid_function(values, dims, UNIT)
    assert f(0.0, 0.0, 0.0) == 0.0
    assert f(1.0, 1.0, 1.0) == 7.0
    assert _close(f(0.5, 0.5, 0.5), 3.5)
    assert _close(f(1.0, 0.0, 0.0), 1.0)
    assert _close(f(0.0, 1.0, 0.0), 2.0)
    assert _close(f(0.0, 0.0, 1.0), 4.0)
    assert _close(f(-1.0, 0.0, 0.0), 0.0)
    assert _close(f(2.0, 2.0, 2.0), 7.0)


def test_a_grid_isosurface_is_a_plane_for_a_ramp():
    dims = (3, 2, 2)
    values = tuple(float(i % 3) / 2.0 for i in range(12))
    f = sc.grid_function(values, dims, UNIT)
    vertices, faces = sc.isosurface(f, UNIT, (2, 1, 1), level=0.25)
    assert all(_close(v[0], 0.25) for v in vertices)
    assert _close(sc.mesh_area(vertices, faces), 1.0)


def test_grid_functions_are_validated():
    with pytest.raises(ValueError):
        sc.grid_function((0.0,) * 7, (2, 2, 2), UNIT)
    with pytest.raises(ValueError):
        sc.grid_function((0.0,) * 4, (1, 2, 2), UNIT)
    with pytest.raises(ValueError):
        sc.grid_function((0.0,) * 7 + (float("nan"),), (2, 2, 2), UNIT)


# ------------------------------------------------------------------------------- transfer functions

RAMP = ((0.0, (0.0, 0.0, 1.0), 0.0), (1.0, (1.0, 0.0, 0.0), 1.0))


def test_a_transfer_function_interpolates_its_stops_and_clamps():
    assert _close(sc.transfer(RAMP, 0.0), ((0.0, 0.0, 1.0), 0.0))
    assert _close(sc.transfer(RAMP, 0.25), ((0.25, 0.0, 0.75), 0.25))
    assert _close(sc.transfer(RAMP, 1.0), ((1.0, 0.0, 0.0), 1.0))
    assert _close(sc.transfer(RAMP, -3.0), ((0.0, 0.0, 1.0), 0.0))
    assert _close(sc.transfer(RAMP, 7.0), ((1.0, 0.0, 0.0), 1.0))


def test_a_transfer_function_is_piecewise_linear():
    stops = ((0.0, (0.0, 0.0, 0.0), 0.0), (0.5, (1.0, 1.0, 1.0), 1.0), (1.0, (0.0, 0.0, 0.0), 0.0))
    assert _close(sc.transfer(stops, 0.25), ((0.5, 0.5, 0.5), 0.5))
    assert _close(sc.transfer(stops, 0.75), ((0.5, 0.5, 0.5), 0.5))
    assert _close(sc.transfer(stops, 0.5), ((1.0, 1.0, 1.0), 1.0))


def test_stops_are_validated():
    with pytest.raises(ValueError):
        sc.validate_stops(RAMP[:1])
    with pytest.raises(ValueError):
        sc.validate_stops((RAMP[1], RAMP[0]))
    with pytest.raises(ValueError):
        sc.validate_stops((RAMP[0], RAMP[0]))
    with pytest.raises(ValueError):
        sc.validate_stops(((0.0, (0.0, 0.0, 0.0), -0.1), RAMP[1]))
    with pytest.raises(ValueError):
        sc.validate_stops(((0.0, (0.0, 0.0, 2.0), 0.0), RAMP[1]))
    with pytest.raises(ValueError):
        sc.validate_stops(tuple((i / 300.0, (0.0, 0.0, 0.0), 0.0) for i in range(sc.MAX_STOPS + 1)))


def test_a_medium_sample_takes_the_opacity_as_density_and_the_colour_as_emission():
    sigma, emission = sc.medium_sample(RAMP, 0.25, extinction=2.0, density_scale=3.0, emission_scale=4.0)
    assert _close(sigma, 0.25 * 3.0 * 2.0)
    assert _close(emission, (0.25 * 0.25 * 3.0 * 4.0, 0.0, 0.75 * 0.25 * 3.0 * 4.0))
    sigma, emission = sc.medium_sample(RAMP, 0.0, extinction=2.0, density_scale=3.0, emission_scale=4.0)
    assert sigma == 0.0 and emission == (0.0, 0.0, 0.0)


def test_transmittance_is_beer_lambert_and_a_march_converges_to_it():
    assert _close(sc.transmittance(0.5, 2.0), math.exp(-1.0))
    stops = ((0.0, (0.0, 0.0, 0.0), 0.0), (1.0, (0.0, 0.0, 0.0), 1.0))
    exact = math.exp(-1.0 / 3.0)
    coarse = sc.march_transmittance(stops, lambda t: t * t, 0.0, 1.0, 4, extinction=1.0)
    fine = sc.march_transmittance(stops, lambda t: t * t, 0.0, 1.0, 64, extinction=1.0)
    assert abs(fine - exact) < abs(coarse - exact)
    assert abs(fine - exact) < 1e-4
    assert _close(sc.march_transmittance(stops, lambda t: 0.5, 0.0, 2.0, 1, extinction=1.0), math.exp(-1.0))


def test_a_march_has_bounds():
    stops = ((0.0, (0.0, 0.0, 0.0), 0.0), (1.0, (0.0, 0.0, 0.0), 1.0))
    with pytest.raises(ValueError):
        sc.march_transmittance(stops, lambda t: t, 0.0, 1.0, 0)
    with pytest.raises(ValueError):
        sc.march_transmittance(stops, lambda t: t, 0.0, 1.0, sc.MAX_STEPS + 1)
    with pytest.raises(ValueError):
        sc.march_transmittance(stops, lambda t: t, 1.0, 0.0, 4)


# ---------------------------------------------------------------------------------------- the draft

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
    assert "SR-77" in draft
    assert "isosurfaceType" in draft
    assert "transfer" in draft and "stop" in draft
    assert "V17" in draft
    assert "marching tetrahedra" in draft
    assert "O(h" in draft
    assert "seek check" in draft
    assert "Beer" in draft
    assert "scalar3d_reference.py" in draft


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
    scope = sc.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert sc._same(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(draft, capsys):
    sc.main()
    out = capsys.readouterr().out.strip().splitlines()
    table = [line for line in draft.splitlines() if ROW.match(line) and not line.startswith("| Test")]
    assert out == table
