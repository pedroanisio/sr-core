"""Tests of the draft SREP "Add reactive values" (srep/srep-0000-reactive-values.md) and of its reference module
conformance/tools/reactive_values_reference.py: trackers, time folds stepped from their start, index folds,
seeded draws, the seek check of SREP 14, the Fourier centre of mass of shot 9 and the Einstein solid of shot 5,
and the SREP's numeric table against the module.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "reactive_values_reference.py")
STREAMS = os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-reactive-values.md")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rv = _load("reactive_values_reference", MODULE)
rs = _load("random_streams_reference", STREAMS)


# ------------------------------------------------------------------------------------------------ keys and steps

def test_keys_hold_before_the_first_and_after_the_last():
    keys = ((1.0, 2.0), (3.0, 6.0))
    assert rv.keys_at(keys, 0.0) == 2.0
    assert rv.keys_at(keys, 9.0) == 6.0


def test_keys_interpolate_linearly_between():
    assert rv.keys_at(((1.0, 2.0), (3.0, 6.0)), 2.0) == 4.0


def test_a_constant_is_a_single_key():
    assert rv.keys_at(5.0, 123.0) == 5.0


def test_keys_need_at_least_one_key_in_time_order():
    with pytest.raises(ValueError):
        rv.keys_at((), 0.0)
    with pytest.raises(ValueError):
        rv.keys_at(((2.0, 0.0), (1.0, 1.0)), 0.0)


def test_the_step_count_is_the_last_step_at_or_before_t():
    assert rv.steps_at(0.0, 0.1, 1.0) == 10
    assert rv.steps_at(0.0, 0.1, 0.3) == 3          # 0.3 / 0.1 is 2.9999999999999996 in binary64
    assert rv.steps_at(0.0, 0.1, 0.29) == 2


def test_no_step_before_the_start():
    assert rv.steps_at(1.0, 0.5, 0.5) == 0
    assert rv.steps_at(1.0, 0.5, 1.0) == 0


def test_the_step_count_is_bounded():
    assert rv.steps_at(0.0, 1e-6, 1.0) == rv.MAX_STEPS
    with pytest.raises(ValueError):
        rv.steps_at(0.0, 1e-7, 1.0)


def test_the_step_must_be_positive():
    with pytest.raises(ValueError):
        rv.steps_at(0.0, 0.0, 1.0)
    with pytest.raises(ValueError):
        rv.steps_at(0.0, -1.0, 1.0)


# ------------------------------------------------------------------------------------------------ time folds

def _integrator(rate, step=0.25, **kw):
    return rv.Fold("x", 0.0, lambda c: c.value + rate * c.dt, step=step, **kw)


def test_a_fold_needs_exactly_one_of_step_and_count():
    with pytest.raises(ValueError):
        rv.Fold("x", 0.0, lambda c: c.value)
    with pytest.raises(ValueError):
        rv.Fold("x", 0.0, lambda c: c.value, step=1.0, count=3)


def test_between_is_hold_or_linear_and_only_for_time_folds():
    with pytest.raises(ValueError):
        rv.Fold("x", 0.0, lambda c: c.value, step=1.0, between="cubic")
    with pytest.raises(ValueError):
        rv.Fold("x", 0.0, lambda c: c.value, count=2, between="linear")


def test_a_constant_rate_integrates_to_rate_times_time():
    assert rv.fold_value(_integrator(2.0), 1.0) == 2.0


def test_the_value_holds_between_steps_by_default():
    f = rv.Fold("x", 0.0, lambda c: c.value + 1.0, step=1.0)
    assert rv.fold_value(f, 2.5) == 2.0


def test_linear_between_steps_reaches_the_next_state():
    f = rv.Fold("x", 0.0, lambda c: c.value + 1.0, step=1.0, between="linear")
    assert rv.fold_value(f, 2.5) == 2.5
    assert rv.fold_value(f, 3.0) == 3.0


def test_before_the_start_the_value_is_the_initial_state():
    f = rv.Fold("x", 5.0, lambda c: c.value + 1.0, start=2.0, step=1.0)
    assert rv.fold_value(f, 1.0) == 5.0
    assert rv.fold_value(f, 2.0) == 5.0
    assert rv.fold_value(f, 3.0) == 6.0


def test_the_initial_state_is_the_keys_at_the_start():
    f = rv.Fold("x", ((0.0, 0.0), (2.0, 4.0)), lambda c: c.value + 1.0, start=1.0, step=1.0)
    assert rv.fold_value(f, 1.0) == 2.0
    assert rv.fold_value(f, 2.0) == 3.0


def test_the_update_sees_index_count_time_and_dt():
    seen = []

    def update(c):
        seen.append((c.index, c.count, c.time, c.dt))
        return c.value

    rv.fold_value(rv.Fold("x", 0.0, update, start=1.0, step=0.5), 2.0)
    assert seen == [(0, 1, 1.5, 0.5), (1, 2, 2.0, 0.5)]   # count is the step number: the state cannot know t


def test_the_euler_integrator_of_cos_is_within_a_step_of_sin():
    f = rv.Fold("x", 0.0, lambda c: c.value + math.cos(c.time - c.dt) * c.dt, step=0.001)
    assert abs(rv.fold_value(f, 1.0) - math.sin(1.0)) < 0.001


def test_a_frame_alone_equals_the_played_frame():
    f = rv.Fold("x", 0.0, lambda c: c.value + c.index, step=0.1)
    assert rv.played((f,), (0.0, 0.5, 1.0)) == (0.0, 10.0, 45.0)
    assert rv.alone((f,), (0.0, 0.5, 1.0)) == (0.0, 10.0, 45.0)
    assert rv.seek_check((f,), (0.0, 0.55, 0.3, 1.0, 0.3))


def test_the_played_pass_steps_incrementally_and_out_of_order_times_restart():
    calls = []
    f = rv.Fold("x", 0.0, lambda c: calls.append(c.index) or c.value + 1.0, step=1.0)
    assert rv.played((f,), (2.0, 3.0, 1.0)) == (2.0, 3.0, 1.0)
    assert calls == [0, 1, 2, 0]


def test_folds_that_read_each_other_see_the_previous_step():
    a = rv.Fold("a", 1.0, lambda c: c.read("b"), step=1.0)
    b = rv.Fold("b", 2.0, lambda c: c.read("a"), step=1.0)
    assert rv.time_fold_at((a, b), 1.0) == {"a": 2.0, "b": 1.0}
    assert rv.time_fold_at((a, b), 2.0) == {"a": 1.0, "b": 2.0}


def test_folds_of_a_system_share_step_and_start():
    a = rv.Fold("a", 0.0, lambda c: c.value, step=1.0)
    b = rv.Fold("b", 0.0, lambda c: c.value, step=0.5)
    with pytest.raises(ValueError):
        rv.time_fold_at((a, b), 1.0)
    c = rv.Fold("c", 0.0, lambda c: c.value, step=1.0, start=1.0)
    with pytest.raises(ValueError):
        rv.time_fold_at((a, c), 1.0)


def test_an_unknown_read_and_a_duplicate_id_are_errors():
    a = rv.Fold("a", 0.0, lambda c: c.read("zz"), step=1.0)
    with pytest.raises(ValueError):
        rv.time_fold_at((a,), 1.0)
    with pytest.raises(ValueError):
        rv.time_fold_at((a, rv.Fold("a", 0.0, lambda c: c.value, step=1.0)), 1.0)


def test_an_index_fold_is_not_a_time_fold():
    with pytest.raises(ValueError):
        rv.time_fold_at((rv.Fold("a", 0.0, lambda c: c.value, count=3),), 1.0)


def test_a_non_finite_state_is_an_error():
    f = rv.Fold("x", 1.0, lambda c: c.value / 0.0 if False else math.inf, step=1.0)
    with pytest.raises(ValueError):
        rv.fold_value(f, 1.0)


# ------------------------------------------------------------------------------------------------ draws

def test_the_hash_is_the_one_of_the_random_streams_module():
    for seed, channel, index in ((0, 0, 0), (1, 2, 3), (2**64 - 1, 7, -5)):
        assert rv.H(seed, channel, index) == rs.H(seed, channel, index)
        assert rv.U(seed, channel, index) == rs.U(seed, channel, index)
    assert rv.pack(3, 1, 0) == rs.pack(3, 1, 0)


def test_a_draw_is_the_unit_draw_of_the_packed_step_and_index():
    assert rv.draw(7, 0, 3, 1) == rs.U(7, 0, rs.pack(3, 1, 0))
    assert 0.0 <= rv.draw(1, 2, 3, 4) < 1.0
    assert rv.draw(1, 2, 3, 4) != rv.draw(1, 2, 4, 4)
    assert rv.draw(1, 2, 3, 4) != rv.draw(2, 2, 3, 4)


def test_random_in_an_update_uses_the_step_index_in_place_of_the_frame():
    assert rv.rand(1, 5, 0) == rs.U(1, 5, 0)
    assert rv.rand(1, 5, 2, 3) == rs.U(1, 5, 2 + (3 << 32))


def test_the_update_draws_through_the_context():
    f = rv.Fold("x", 0.0, lambda c: c.draw(0, 0) + c.random(0), step=1.0, seed=9)
    assert rv.fold_value(f, 1.0) == rv.draw(9, 0, 0, 0) + rv.rand(9, 0, 0)
    assert rv.fold_value(f, 2.0) == rv.draw(9, 0, 1, 0) + rv.rand(9, 1, 0)


# ------------------------------------------------------------------------------------------------ index folds

def test_an_index_fold_sums_in_increasing_index():
    order = []
    assert rv.index_fold(0.0, 10, lambda c: order.append(c.index) or c.value + c.index) == 45.0
    assert order == list(range(10))


def test_an_index_fold_sees_count_and_the_frame_time():
    assert rv.index_fold(0.0, 4, lambda c: c.value + 1.0 / c.count) == 1.0
    assert rv.index_fold(0.0, 3, lambda c: c.time, t=2.5) == 2.5
    assert rv.index_fold(0.0, 3, lambda c: c.dt) == 0.0


def test_the_count_is_bounded():
    assert rv.index_fold(0.0, rv.MAX_COUNT, lambda c: c.value) == 0.0
    with pytest.raises(ValueError):
        rv.index_fold(0.0, rv.MAX_COUNT + 1, lambda c: c.value)
    with pytest.raises(ValueError):
        rv.index_fold(0.0, 0, lambda c: c.value)


def test_an_index_fold_starts_from_the_keys_at_the_frame_time():
    assert rv.index_fold(((0.0, 0.0), (2.0, 4.0)), 2, lambda c: c.value + 1.0, t=1.0) == 4.0


# ------------------------------------------------------------------------------------------------ the shots

def test_the_fourier_centre_of_mass_sits_at_half_the_amplitude_at_the_signal_frequency():
    g = lambda tau: math.cos(math.tau * 3.0 * tau)   # noqa: E731
    x, y = rv.fourier_centre(g, 3.0, 400, 4.0)
    assert abs(x - 0.5) < 1e-9 and abs(y) < 1e-9


def test_the_fourier_centre_of_mass_is_at_the_origin_off_frequency():
    g = lambda tau: math.cos(math.tau * 3.0 * tau)   # noqa: E731
    x, y = rv.fourier_centre(g, 2.0, 400, 4.0)
    assert abs(x) < 1e-9 and abs(y) < 1e-9


def test_the_einstein_solid_conserves_its_packets_and_reproduces_by_seed():
    a = rv.einstein_solid((3.0, 0.0, 0.0, 0.0), 500, 1)
    assert sum(a) == 3.0 and all(e >= 0.0 for e in a) and len(a) == 4
    assert a == rv.einstein_solid((3.0, 0.0, 0.0, 0.0), 500, 1)
    assert a != rv.einstein_solid((3.0, 0.0, 0.0, 0.0), 500, 2) or \
        rv.einstein_solid((3.0, 0.0, 0.0, 0.0), 20, 1) != rv.einstein_solid((3.0, 0.0, 0.0, 0.0), 20, 2)


def test_the_einstein_solid_hops_one_packet_at_a_time_from_a_cell_that_has_one():
    before = rv.einstein_solid((3.0, 0.0, 0.0, 0.0), 0, 1)
    assert before == (3.0, 0.0, 0.0, 0.0)
    for k in range(1, 30):
        a = rv.einstein_solid((3.0, 0.0, 0.0, 0.0), k - 1, 1)
        b = rv.einstein_solid((3.0, 0.0, 0.0, 0.0), k, 1)
        moved = [i for i in range(4) if a[i] != b[i]]
        assert moved == [] or (len(moved) == 2 and sorted(b[i] - a[i] for i in moved) == [-1.0, 1.0])


def test_the_einstein_solid_passes_the_seek_check():
    folds = rv.einstein_folds((3.0, 0.0, 0.0, 0.0), 1)
    assert len(folds) == 4
    assert rv.seek_check(folds, (0.5, 0.2, 1.0, 0.2))


# ------------------------------------------------------------------------------------------------ the draft

def _numeric_rows():
    text = open(DRAFT, encoding="utf-8").read()
    body = text.split("### Numeric tests", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in body.splitlines():
        m = re.match(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", line)
        if m and m.group(1) not in ("Test", "---"):
            rows.append((m.group(1), m.group(2), m.group(3)))
    return rows


def test_the_draft_exists_with_its_sections_and_a_table():
    text = open(DRAFT, encoding="utf-8").read()
    for section in ("## Abstract", "## Motivation", "### Syntax", "### Semantics", "## Rationale",
                    "## Rejected alternatives", "## Backwards compatibility", "## Engine impact", "### Numeric tests",
                    "### Kit cases", "## Open issues", "## References", "## History"):
        assert section in text, section
    assert len(_numeric_rows()) >= 30
    assert "Status:          Draft" in text and "SREP:            0" in text
    assert "SR-66" in text


def test_the_draft_rules_that_included_values_fold_in_composition_time():
    # SRC-25, from the engine's SR-66 review: an include merges assets and carries no clock, so a fold of an
    # included document steps on the host's composition time; a looped or remapped reader restarts nothing.
    text = open(DRAFT, encoding="utf-8").read()
    rule = text.split("1. **A value is a property without a node.**", 1)[1].split("\n2. ", 1)[0]
    rule = re.sub(r"\n +", " ", rule)   # the draft wraps at 110 columns
    assert "An `include` merges the included document's values" in rule
    assert "carries no clock" in rule
    assert "n(t) of rule 2 counts the host's composition time" in rule
    assert "restarts no fold" in rule
    assert "2026-10-25: rule 1 states that included values fold in the host's composition time" in text


def _close(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


@pytest.mark.parametrize("name, expr, expected", _numeric_rows() if os.path.exists(DRAFT) else [])
def test_numeric_table_row(name, expr, expected):
    scope = {k: getattr(rv, k) for k in dir(rv) if not k.startswith("_")}
    scope["math"] = math
    scope["__builtins__"] = {"tuple": tuple, "round": round, "len": len, "abs": abs, "sum": sum, "all": all,
                             "max": max, "min": min}
    got = eval(expr, scope)   # one scope: a lambda in a row looks its names up in the globals
    want = eval(expected, {"__builtins__": {}, "inf": math.inf, "nan": math.nan}, {})
    assert _close(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(capsys):
    rv.main()
    out = capsys.readouterr().out
    printed = re.findall(r"^\| ([^|]+?) \| `([^`]+)` \| `([^`]+)` \|$", out, re.M)
    assert printed == _numeric_rows()
