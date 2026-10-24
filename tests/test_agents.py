"""Tests of the draft SREP "Add agent behaviours" (srep/srep-0000-agents.md) and of its reference module
conformance/tools/agents_reference.py: seeded populations on a rim, daily pellets, nearest-pellet claims by
arrival time over rounds, sharing and payoffs (hawk and dove), fates (survive, reproduce) from food and
draws, mutation, the day step in gather form, the seek check, live counts, the within-day path, and the
SREP's numeric table against the module.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "agents_reference.py")
STREAMS = os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-agents.md")

spec = importlib.util.spec_from_file_location("agents_reference", MODULE)
ag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ag)

spec_rs = importlib.util.spec_from_file_location("random_streams_reference", STREAMS)
rs = importlib.util.module_from_spec(spec_rs)
spec_rs.loader.exec_module(rs)

HAWK_DOVE = ((("hawk", "dove"), (1.5, 0.5)), (("hawk", "hawk"), (0.0, 0.0)), (("dove", "dove"), (1.0, 1.0)))


def _close(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], tol) for k in a)
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


def selection_spec(**kw):
    base = dict(count=6, seed=1, width=100.0, height=100.0, speed=10.0, pellets=4, units=1.0, share=1, meals=2,
                kinds=(("blob", 1.0),), mutation=0.0)
    base.update(kw)
    return ag.Spec(**base)


def aggression_spec(**kw):
    base = dict(count=6, seed=2, width=100.0, height=100.0, speed=10.0, pellets=3, units=2.0, share=2, meals=1,
                kinds=(("hawk", 0.5), ("dove", 0.5)), payoffs=HAWK_DOVE)
    base.update(kw)
    return ag.Spec(**base)


# ------------------------------------------------------------------------------------------------ the spec

def test_the_spec_validates_its_fields():
    assert ag.raises(lambda: selection_spec(count=0))
    assert ag.raises(lambda: selection_spec(count=ag.MAX_AGENTS + 1))
    assert ag.raises(lambda: selection_spec(pellets=0))
    assert ag.raises(lambda: selection_spec(share=3))
    assert ag.raises(lambda: selection_spec(meals=0))
    assert ag.raises(lambda: selection_spec(units=0.0))
    assert ag.raises(lambda: selection_spec(speed=0.0))
    assert ag.raises(lambda: selection_spec(width=0.0))
    assert ag.raises(lambda: selection_spec(kinds=(("a", 0.5), ("b", 0.4))))        # shares sum to 1
    assert ag.raises(lambda: selection_spec(kinds=(("a", 0.5), ("a", 0.5))))        # unique names
    assert ag.raises(lambda: selection_spec(kinds=()))
    assert ag.raises(lambda: selection_spec(mutation=-0.1))
    assert ag.raises(lambda: selection_spec(min_speed=20.0, max_speed=10.0))
    assert ag.raises(lambda: aggression_spec(payoffs=((("hawk", "owl"), (1.0, 1.0)),)))   # unknown kind
    assert ag.raises(lambda: aggression_spec(payoffs=((("hawk", "dove"), (-1.0, 1.0)),)))  # negative food
    assert selection_spec().count == 6


def test_the_element_seed_is_the_d24_element_seed_of_the_agents_purpose():
    s = selection_spec(project=7, id="pop", seed=3)
    assert ag.element_seed(s) == rs.E(7, "pop", 3, "agents")
    assert ag.element_seed(selection_spec(seed=None)) == rs.E(0, "agents", None, "agents")


def test_kinds_are_assigned_by_cumulative_share_in_index_order():
    kinds = (("hawk", 0.5), ("dove", 0.5))
    assert [ag.kind_of(i, 6, kinds) for i in range(6)] == ["hawk"] * 3 + ["dove"] * 3
    kinds = (("a", 0.25), ("b", 0.75))
    assert [ag.kind_of(i, 4, kinds) for i in range(4)] == ["a", "b", "b", "b"]
    assert ag.kind_of(0, 1, (("only", 1.0),)) == "only"
    assert ag.raises(lambda: ag.kind_of(4, 4, kinds))


def test_rim_points_walk_the_perimeter_clockwise_from_the_origin():
    assert ag.rim_point(0.0, 100.0, 100.0) == (0.0, 0.0)
    assert ag.rim_point(0.25, 100.0, 100.0) == (100.0, 0.0)
    assert ag.rim_point(0.5, 100.0, 100.0) == (100.0, 100.0)
    assert ag.rim_point(0.75, 100.0, 100.0) == (0.0, 100.0)
    assert ag.rim_point(0.125, 100.0, 100.0) == (50.0, 0.0)
    assert ag.rim_point(0.9, 100.0, 100.0) == (0.0, 40.0)
    assert ag.rim_point(0.5, 200.0, 100.0) == (200.0, 100.0)
    assert ag.raises(lambda: ag.rim_point(1.0, 100.0, 100.0))


def test_the_initial_population_sits_on_the_rim_with_the_cruise_speed():
    s = selection_spec()
    agents = ag.init(s)
    assert len(agents) == 6
    e = ag.element_seed(s)
    for i, a in enumerate(agents):
        assert a.kind == "blob" and a.speed == 10.0
        assert (a.x, a.y) == ag.rim_point(rs.S(e, ag.P_HOME, 0, i), 100.0, 100.0)
    hd = ag.init(aggression_spec())
    assert [a.kind for a in hd] == ["hawk"] * 3 + ["dove"] * 3


def test_pellets_are_uniform_in_the_arena_from_the_food_stream_of_the_day():
    s = selection_spec()
    e = ag.element_seed(s)
    p = ag.pellets(s, 3)
    assert len(p) == 4
    for j, (x, y) in enumerate(p):
        assert x == rs.S(e, ag.P_FOOD, 3, 2 * j) * 100.0
        assert y == rs.S(e, ag.P_FOOD, 3, 2 * j + 1) * 100.0
    assert ag.pellets(s, 3) != ag.pellets(s, 4)


# ------------------------------------------------------------------------------------------------ claims

def test_claims_go_to_the_earliest_arrival_and_losers_try_again_next_round():
    positions = ((0.0, 0.0), (10.0, 0.0))
    speeds = (1.0, 1.0)
    pellets = ((4.0, 0.0), (20.0, 0.0))
    per_agent, per_pellet = ag.claims(positions, speeds, pellets, share=1, meals=2)
    assert per_agent == ((0,), (1,))
    assert per_pellet == ((0,), (1,))


def test_a_winner_continues_from_the_pellet_and_its_arrival_times_accumulate():
    # agent 0 wins pellet 0 at t = 4 and would reach pellet 1 at t = 20; agent 1 reaches it at t = 10
    positions = ((0.0, 0.0), (10.0, 0.0))
    pellets = ((4.0, 0.0), (20.0, 0.0))
    per_agent, per_pellet = ag.claims(positions, (1.0, 1.0), pellets, share=1, meals=2)
    assert per_agent[1] == (1,)
    # a much faster agent 0 takes both
    per_agent, per_pellet = ag.claims(positions, (10.0, 1.0), pellets, share=1, meals=2)
    assert per_agent == ((0, 1), ())
    assert per_pellet == ((0,), (0,))


def test_ties_in_arrival_go_to_the_lower_agent_index_and_pellet_index():
    per_agent, per_pellet = ag.claims(((0.0, 0.0), (8.0, 0.0)), (1.0, 1.0), ((4.0, 0.0),), share=1, meals=1)
    assert per_agent == ((0,), ())
    per_agent, per_pellet = ag.claims(((0.0, 0.0),), (1.0,), ((4.0, 0.0), (-4.0, 0.0)), share=1, meals=1)
    assert per_agent == ((0,),)


def test_sharing_lets_two_claimants_take_one_pellet():
    positions = ((0.0, 0.0), (10.0, 0.0), (50.0, 50.0))
    per_agent, per_pellet = ag.claims(positions, (1.0, 1.0, 1.0), ((5.0, 0.0),), share=2, meals=1)
    assert per_agent == ((0,), (0,), ())
    assert per_pellet == ((0, 1),)


def test_one_meal_each_and_the_loser_turns_from_where_it_is():
    positions = ((0.0, 0.0), (10.0, 0.0))
    pellets = ((4.0, 0.0), (20.0, 0.0), (40.0, 0.0))
    per_agent, per_pellet = ag.claims(positions, (1.0, 1.0), pellets, share=1, meals=1)
    assert per_agent == ((0,), (1,))
    assert per_pellet == ((0,), (1,), ())
    # agent 1 loses pellet 0 at t = 4 from (6, 0), reaches pellet 1 at 18 before agent 0 (20), and from
    # there pellet 2 at 38 before agent 0, which had turned at (18, 0) and would arrive at 40
    per_agent, per_pellet = ag.claims(positions, (1.0, 1.0), pellets, share=1, meals=5)
    assert per_agent == ((0,), (1, 2))
    assert per_pellet == ((0,), (1,), (1,))
    assert ag._toward((10.0, 0.0), (4.0, 0.0), 4.0) == (6.0, 0.0)
    assert ag._toward((10.0, 0.0), (4.0, 0.0), 9.0) == (4.0, 0.0)


def test_claims_validation_and_empty_cases():
    assert ag.claims((), (), ((1.0, 1.0),), 1, 2) == ((), ((),))
    assert ag.claims(((0.0, 0.0),), (1.0,), (), 1, 2) == (((),), ())
    assert ag.raises(lambda: ag.claims(((0.0, 0.0),), (0.0,), ((1.0, 1.0),), 1, 2))
    assert ag.raises(lambda: ag.claims(((0.0, 0.0),), (1.0, 1.0), ((1.0, 1.0),), 1, 2))


# ------------------------------------------------------------------------------------------------ food and fate

def test_a_sole_claimant_eats_the_pellet_and_two_split_it_equally_by_default():
    s = selection_spec(units=1.0)
    assert ag.food(s, ("blob", "blob"), per_pellet=((0,),)) == (1.0, 0.0)
    s = aggression_spec(payoffs=())
    assert ag.food(s, ("hawk", "dove"), per_pellet=((0, 1),)) == (1.0, 1.0)
    assert ag.food(s, ("hawk", "dove"), per_pellet=((1,),)) == (0.0, 2.0)
    assert ag.food(selection_spec(), ("blob", "blob"), per_pellet=((0,), (0,), ())) == (2.0, 0.0)


def test_payoffs_are_symmetric_in_the_order_of_the_kinds():
    s = aggression_spec()
    assert ag.payoff(s, "hawk", "dove") == (1.5, 0.5)
    assert ag.payoff(s, "dove", "hawk") == (0.5, 1.5)
    assert ag.payoff(s, "hawk", "hawk") == (0.0, 0.0)
    assert ag.payoff(s, "dove", "dove") == (1.0, 1.0)
    assert ag.payoff(aggression_spec(payoffs=()), "hawk", "dove") == (1.0, 1.0)
    assert ag.raises(lambda: ag.payoff(s, "hawk", "owl"))


def test_food_with_payoffs():
    s = aggression_spec()
    assert ag.food(s, ("hawk", "dove", "hawk", "hawk"), per_pellet=((0, 1), (2, 3), ())) == (1.5, 0.5, 0.0, 0.0)


def test_fate_from_food_and_the_two_draws():
    assert ag.fate(0.0, 0.0, 0.0) == (False, 0)
    assert ag.fate(1.0, 0.99, 0.99) == (True, 0)
    assert ag.fate(2.0, 0.99, 0.99) == (True, 1)
    assert ag.fate(3.0, 0.99, 0.99) == (True, 2)
    assert ag.fate(0.5, 0.4, 0.0) == (True, 0)
    assert ag.fate(0.5, 0.6, 0.0) == (False, 0)
    assert ag.fate(1.5, 0.0, 0.4) == (True, 1)
    assert ag.fate(1.5, 0.0, 0.6) == (True, 0)
    assert ag.fate(0.5, 0.5, 0.0) == (False, 0)            # the draw must be below the food
    assert ag.raises(lambda: ag.fate(-1.0, 0.0, 0.0))


def test_mutated_speed_is_the_parent_speed_scaled_by_a_signed_draw_within_bounds():
    e = 12345
    assert ag.mutated_speed(10.0, 0.0, 1.0, 100.0, e, 3, 0) == 10.0
    want = 10.0 * (1.0 + 0.2 * rs.S_signed(e, ag.P_MUTATE, 3, 0))
    assert _close(ag.mutated_speed(10.0, 0.2, 1.0, 100.0, e, 3, 0), want)
    assert ag.mutated_speed(10.0, 1.0, 9.9, 10.1, e, 3, 0) in (9.9, 10.1) or 9.9 <= ag.mutated_speed(10.0, 1.0, 9.9, 10.1, e, 3, 0) <= 10.1


# ------------------------------------------------------------------------------------------------ the day

def test_the_day_report_accounts_for_every_agent():
    s = selection_spec()
    agents = ag.init(s)
    rep = ag.day_report(s, agents, 0)
    assert len(rep["food"]) == 6 and len(rep["fate"]) == 6
    assert len(rep["pellets"]) == 4
    assert sum(len(c) for c in rep["claims"]) <= 4
    survivors = sum(1 for alive, _ in rep["fate"] if alive)
    children = sum(c for _, c in rep["fate"])
    assert len(rep["next"]) == survivors + children
    for f, (alive, c) in zip(rep["food"], rep["fate"]):
        assert alive == (f >= 1.0)                           # whole units: no draw decides
        assert c == max(0, int(f) - 1)


def test_the_next_day_starts_on_the_rim_with_inherited_kinds_and_speeds():
    s = aggression_spec()
    agents = ag.init(s)
    rep = ag.day_report(s, agents, 0)
    e = ag.element_seed(s)
    for i, a in enumerate(rep["next"]):
        assert (a.x, a.y) == ag.rim_point(rs.S(e, ag.P_HOME, 1, i), 100.0, 100.0)
        assert a.kind in ("hawk", "dove") and a.speed == 10.0
    survivors = [a for a, (alive, _) in zip(agents, rep["fate"]) if alive]
    assert [a.kind for a in rep["next"][:len(survivors)]] == [a.kind for a in survivors]


def test_children_follow_their_parents_in_parent_order():
    s = selection_spec(count=2, pellets=6, meals=4, speed=50.0)
    agents = ag.init(s)
    rep = ag.day_report(s, agents, 0)
    kids = [c for _, c in rep["fate"]]
    assert sum(kids) >= 1
    expected = [a.kind for a, (alive, _) in zip(agents, rep["fate"]) if alive]
    for a, (alive, c) in zip(agents, rep["fate"]):
        expected += [a.kind] * c
    assert [a.kind for a in rep["next"]] == expected


def test_the_day_is_a_pure_function_of_the_state_and_the_step():
    s = selection_spec()
    agents = ag.init(s)
    assert ag.day(s, agents, 0) == ag.day(s, agents, 0)
    assert ag.day(s, agents, 0) != ag.day(s, agents, 1)
    assert ag.day(s, (), 0) == ()


def test_seeded_populations_reproduce_exactly():
    s = selection_spec()
    assert ag.run(s, 10) == ag.run(s, 10)
    assert ag.run(s, 10) != ag.run(selection_spec(seed=9), 10)
    assert ag.counts(ag.run(s, 10)) == ag.counts(ag.run(s, 10))


def test_the_frame_alone_equals_the_frame_played():
    s = aggression_spec()
    played = ag.init(s)
    for k in range(5):
        played = ag.day(s, played, k)
    assert ag.run(s, 5) == played
    assert ag.run(s, 5) == ag.day(s, ag.run(s, 4), 4)
    assert ag.run(s, 0) == ag.init(s)


def test_run_bounds_the_days_and_the_population():
    assert ag.raises(lambda: ag.run(selection_spec(), ag.MAX_DAYS + 1))
    assert ag.raises(lambda: ag.run(selection_spec(), -1))
    s = selection_spec(count=ag.MAX_AGENTS, pellets=ag.MAX_PELLETS)
    assert ag.raises(lambda: ag.grow_check(ag.MAX_AGENTS + 1))
    assert ag.grow_check(ag.MAX_AGENTS) is None


def test_counts_and_means_are_live_values():
    s = aggression_spec()
    agents = ag.init(s)
    assert ag.counts(agents) == {"hawk": 3, "dove": 3}
    assert ag.counts(()) == {}
    assert ag.mean_speed(agents) == 10.0
    assert ag.mean_speed(()) == 0.0
    assert ag.count(agents) == 6
    assert ag.count(agents, "dove") == 3
    assert ag.count(agents, "owl") == 0


def test_a_starving_population_dies_out_and_stays_dead():
    s = selection_spec(count=4, pellets=1, meals=1)
    agents = ag.init(s)
    rep = ag.day_report(s, agents, 0)
    assert sum(1 for alive, _ in rep["fate"] if alive) == 1
    later = ag.run(selection_spec(count=1, pellets=1, meals=1, width=1000.0, height=1000.0, speed=0.001), 3)
    assert ag.count(later) <= 1


# ------------------------------------------------------------------------------------------------ the path

def test_the_day_path_visits_the_claimed_pellets_and_returns_home():
    assert ag.day_path((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0))) == ((0.0, 0.0), (3.0, 0.0), (3.0, 4.0), (0.0, 0.0))
    assert ag.day_path((5.0, 5.0), ()) == ((5.0, 5.0),)
    assert ag.path_length(ag.day_path((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0)))) == 12.0


def test_along_a_path_by_distance_and_the_position_within_the_day():
    path = ag.day_path((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0)))
    assert ag.along(path, 0.0) == (0.0, 0.0)
    assert ag.along(path, 1.5) == (1.5, 0.0)
    assert ag.along(path, 5.0) == (3.0, 2.0)
    assert _close(ag.along(path, 9.5), (1.5, 2.0))
    assert ag.along(path, 12.0) == (0.0, 0.0)
    assert ag.along(path, 50.0) == (0.0, 0.0)
    assert ag.position_at((0.0, 0.0), ((3.0, 0.0), (3.0, 4.0)), 2.0, 2.5) == (3.0, 2.0)
    assert ag.position_at((5.0, 5.0), (), 2.0, 2.5) == (5.0, 5.0)
    assert ag.raises(lambda: ag.along(path, -1.0))


# ------------------------------------------------------------------------------------------------ the draft

@pytest.fixture(scope="module")
def draft():
    with open(DRAFT, encoding="utf-8") as fh:
        return fh.read()


def test_the_draft_has_the_srep_sections(draft):
    for section in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics", "## Rationale",
                    "## Rejected alternatives", "## Backwards compatibility", "## Engine impact", "## Conformance",
                    "### Numeric tests", "### Kit cases", "## Open issues", "## References", "## History"):
        assert section in draft, section
    assert "SREP:            0" in draft
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    assert "SR-76" in draft
    for word in ("agentsType", "payoff", 'prop("', "V17", "seek check", "gather form"):
        assert word in draft, word


def _rows(draft):
    start = draft.index("### Numeric tests")
    end = draft.index("### Kit cases")
    rows = re.findall(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", draft[start:end])
    return [(n, e, x) for n, e, x in rows if n != "Test" and not set(n) <= {"-"}]


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as fh:
        return _rows(fh.read())


def test_the_numeric_table_has_its_rows(draft):
    assert len(_rows(draft)) >= 30


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = ag.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert _close(got, want, 1e-9), name


def test_the_table_is_what_the_module_prints(draft, capsys):
    ag.main()
    printed = capsys.readouterr().out.strip().splitlines()
    rows = _rows(draft)
    assert len(printed) == len(rows)
    for line, (name, expr, expected) in zip(printed, rows):
        assert line == f"| {name} | `{expr}` | `{expected}` |", name
