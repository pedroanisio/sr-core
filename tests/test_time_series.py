"""Tests for the draft SREP "Add time-series layers to the map" (M3 of SREP 12) and its reference module."""
import datetime
import importlib.util
import math
import os
import re

import pytest

np = pytest.importorskip("numpy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "time_series_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-time-series.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ts = _load(MODULE, "time_series_reference")

UTC = datetime.timezone.utc


def _epoch(*args, **kw):
    return datetime.datetime(*args, tzinfo=UTC, **kw).timestamp()


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list, np.ndarray)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# -------------------------------------------------------------------------------------------------------- data time


def test_times_are_numbers_or_iso_8601_date_times():
    assert ts.parse_time(5) == 5.0 and ts.parse_time(-2.5) == -2.5
    assert ts.parse_time("2024-03-01T12:00:00Z") == _epoch(2024, 3, 1, 12)
    assert ts.parse_time("1970-01-01T00:00:00Z") == 0.0
    assert ts.parse_time("2024-03-01T12:00:00+02:00") == _epoch(2024, 3, 1, 10)
    assert ts.parse_time("2024-03-01T12:00:00-03:30") == _epoch(2024, 3, 1, 15, 30)
    assert ts.parse_time("2024-03-01T12:00:00.250Z") == _epoch(2024, 3, 1, 12) + 0.25
    assert ts.parse_time("1969-12-31T23:59:59Z") == -1.0
    assert ts.parse_time(" 42 ") == 42.0


def test_malformed_times_are_refused():
    for bad in ("yesterday", "2024-03-01", "2024-03-01T12:00Z", "2024-13-01T00:00:00Z", "2024-02-30T00:00:00Z",
                "2024-03-01T24:00:00Z", "2024-03-01T12:00:00", "", None, True, [1], float("nan")):
        with pytest.raises(ts.TimeSeriesError):
            ts.parse_time(bad)


def test_data_time_is_the_origin_plus_the_offset():
    assert ts.data_time(0, 10.0) == 10.0
    assert ts.data_time("2024-01-01T00:00:00Z", 3600.0) == _epoch(2024, 1, 1, 1)
    assert ts.data_time(100, -20.0) == 80.0


def test_animated_attributes_interpolate_their_keys_linearly_and_clamp():
    assert ts.animated(7.0, 3.0) == 7.0
    keys = {"keys": [[0.0, 0.0], [10.0, 100.0]]}
    assert ts.animated(keys, 5.0) == 50.0
    assert ts.animated(keys, -1.0) == 0.0 and ts.animated(keys, 20.0) == 100.0
    three = {"keys": [[0.0, 0.0], [4.0, 8.0], [10.0, 8.0]]}
    assert ts.animated(three, 2.0) == 4.0 and ts.animated(three, 7.0) == 8.0
    with pytest.raises(ts.TimeSeriesError):
        ts.animated({"keys": []}, 0.0)
    with pytest.raises(ts.TimeSeriesError):
        ts.animated({"keys": [[1.0, 0.0], [0.0, 1.0]]}, 0.0)


# -------------------------------------------------------------------------------------------------- feature filters


def test_a_feature_shows_from_its_time_on():
    t0 = _epoch(2024, 1, 1)
    props = {"time": "2024-01-01T01:00:00Z"}
    assert ts.feature_alpha(props, t0 + 3600.0, "time", None, 0.0, False) == 1.0
    assert ts.feature_alpha(props, t0 + 3599.0, "time", None, 0.0, False) is None
    assert ts.feature_alpha(props, t0 + 1e9, "time", None, 0.0, False) == 1.0
    assert ts.feature_alpha({"time": 5}, 5.0, "time", None, 0.0, False) == 1.0


def test_a_trail_hides_old_features_and_fades_them():
    tau = 1000.0
    props = {"time": tau}
    assert ts.feature_alpha(props, tau + 50.0, "time", None, 100.0, True) == 0.5
    assert ts.feature_alpha(props, tau + 100.0, "time", None, 100.0, True) is None
    assert ts.feature_alpha(props, tau + 100.0, "time", None, 100.0, False) == 1.0
    assert ts.feature_alpha(props, tau + 101.0, "time", None, 100.0, False) is None
    assert ts.feature_alpha(props, tau, "time", None, 100.0, True) == 1.0
    assert _close(ts.feature_alpha(props, tau + 25.0, "time", None, 100.0, True), 0.75)


def test_an_end_property_hides_the_feature_from_then_on():
    props = {"time": 0, "end": 10}
    assert ts.feature_alpha(props, 9.99, "time", "end", 0.0, False) == 1.0
    assert ts.feature_alpha(props, 10.0, "time", "end", 0.0, False) is None
    # a feature without an end stays
    assert ts.feature_alpha({"time": 0}, 10.0, "time", "end", 0.0, False) == 1.0


def test_features_without_a_readable_time_are_hidden():
    assert ts.feature_alpha({}, 10.0, "time", None, 0.0, False) is None
    assert ts.feature_alpha({"time": "soon"}, 10.0, "time", None, 0.0, False) is None
    assert ts.feature_alpha({"time": 0, "end": "never"}, 1.0, "time", "end", 0.0, False) is None
    assert ts.feature_alpha({"time": None}, 10.0, "time", None, 0.0, False) is None


def test_the_time_check_reports_why_a_feature_is_hidden():
    assert ts.feature_state({}, 10.0, "time", None, 0.0, False) == "unreadable"
    assert ts.feature_state({"time": 20}, 10.0, "time", None, 0.0, False) == "pending"
    assert ts.feature_state({"time": 0}, 10.0, "time", None, 5.0, False) == "expired"
    assert ts.feature_state({"time": 0, "end": 5}, 10.0, "time", "end", 0.0, False) == "ended"
    assert ts.feature_state({"time": 0}, 10.0, "time", None, 0.0, False) == "visible"


# ------------------------------------------------------------------------------------------------------------ trips


PATH = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
STAMPS = [0.0, 10.0, 30.0]


def test_the_head_is_the_interpolated_position_at_the_data_time():
    assert _close(ts.interpolate(PATH, STAMPS, 5.0), (5.0, 0.0))
    assert _close(ts.interpolate(PATH, STAMPS, 20.0), (10.0, 5.0))
    assert _close(ts.interpolate(PATH, STAMPS, 10.0), (10.0, 0.0))
    assert _close(ts.interpolate(PATH, STAMPS, -5.0), (0.0, 0.0))
    assert _close(ts.interpolate(PATH, STAMPS, 99.0), (10.0, 10.0))
    # equal stamps: the position jumps to the later vertex
    assert _close(ts.interpolate([(0.0, 0.0), (4.0, 0.0), (8.0, 0.0)], [0.0, 0.0, 8.0], 0.0), (4.0, 0.0))
    assert _close(ts.interpolate([(0.0, 0.0), (4.0, 0.0), (8.0, 0.0)], [0.0, 0.0, 8.0], 4.0), (6.0, 0.0))


def test_a_trip_before_its_start_is_pending_and_a_trip_past_its_trail_is_gone():
    assert ts.trip_window(PATH, STAMPS, -1.0, 120.0, True) is None
    assert ts.trip_state(PATH, STAMPS, -1.0, 120.0) == "pending"
    assert ts.trip_window(PATH, STAMPS, 200.0, 120.0, True) is None
    assert ts.trip_state(PATH, STAMPS, 200.0, 120.0) == "gone"
    assert ts.trip_state(PATH, STAMPS, 150.0, 120.0) == "complete"
    assert ts.trip_state(PATH, STAMPS, 20.0, 120.0) == "running"
    # without a trail a trip never goes
    assert ts.trip_window(PATH, STAMPS, 1e6, 0.0, False) is not None
    assert ts.trip_state(PATH, STAMPS, 1e6, 0.0) == "complete"


def test_the_window_runs_from_the_trail_start_to_the_head_with_fading_alphas():
    w = ts.trip_window(PATH, STAMPS, 5.0, 120.0, True)
    assert _close(w["points"], [(0.0, 0.0), (5.0, 0.0)])
    assert _close(w["alphas"], [1.0 - 5.0 / 120.0, 1.0])
    assert _close(w["head"], (5.0, 0.0))
    w = ts.trip_window(PATH, STAMPS, 20.0, 120.0, True)
    assert _close(w["points"], [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)])
    assert _close(w["alphas"], [1.0 - 20.0 / 120.0, 1.0 - 10.0 / 120.0, 1.0])
    assert _close(w["head"], (10.0, 5.0))
    w = ts.trip_window(PATH, STAMPS, 40.0, 120.0, True)
    assert _close(w["points"], PATH)
    assert _close(w["alphas"], [1.0 - 40.0 / 120.0, 1.0 - 30.0 / 120.0, 1.0 - 10.0 / 120.0])
    assert _close(w["head"], (10.0, 10.0))


def test_a_short_trail_cuts_the_tail_at_its_interpolated_point():
    w = ts.trip_window(PATH, STAMPS, 20.0, 15.0, True)
    assert _close(w["points"], [(5.0, 0.0), (10.0, 0.0), (10.0, 5.0)])
    assert _close(w["alphas"], [0.0, 1.0 - 10.0 / 15.0, 1.0])
    w = ts.trip_window(PATH, STAMPS, 20.0, 15.0, False)
    assert _close(w["alphas"], [1.0, 1.0, 1.0])
    # a trip exactly at its start is its head alone
    w = ts.trip_window(PATH, STAMPS, 0.0, 120.0, True)
    assert _close(w["points"], [(0.0, 0.0)]) and _close(w["head"], (0.0, 0.0)) and w["alphas"] == [1.0]


def test_timestamps_must_be_a_non_decreasing_number_per_vertex():
    assert ts.check_timestamps(PATH, STAMPS) == [0.0, 10.0, 30.0]
    assert ts.check_timestamps(PATH, ["1970-01-01T00:00:00Z", "1970-01-01T00:00:10Z", 30]) == [0.0, 10.0, 30.0]
    for bad in ([0.0, 10.0], [0.0, 20.0, 10.0], "0 10 30", [0.0, "soon", 30.0], None):
        with pytest.raises(ts.TimeSeriesError):
            ts.check_timestamps(PATH, bad)


# -------------------------------------------------------------------------------------------------------- drawing


def test_stroke_pixels_cover_centres_within_half_the_width_with_round_ends():
    px = ts.stroke_pixels([(2.0, 5.0), (8.0, 5.0)], [1.0, 1.0], 2.0, "#FF0000", 1.0, 10, 10)
    assert px.shape == (10, 10, 4)
    covered = px[..., 3] > 0
    assert covered.sum() == 16
    assert covered[4, 1] and covered[5, 8] and not covered[3, 5] and not covered[4, 0] and not covered[4, 9]
    assert np.allclose(px[4, 4], (1.0, 0.0, 0.0, 1.0))
    half = ts.stroke_pixels([(2.0, 5.0), (8.0, 5.0)], [1.0, 1.0], 2.0, "#FF000080", 0.5, 10, 10)
    assert np.allclose(half[4, 4], np.array((1.0, 0.0, 0.0, 1.0)) * (128 / 255) * 0.5)


def test_stroke_alpha_follows_the_nearest_point_of_the_path():
    px = ts.stroke_pixels([(2.0, 5.0), (8.0, 5.0)], [0.0, 1.0], 2.0, "#FFFFFF", 1.0, 10, 10)
    assert _close(px[4, 2][3], 0.5 / 6.0, 1e-9)
    assert _close(px[4, 7][3], 5.5 / 6.0, 1e-9)
    assert _close(px[4, 1][3], 0.0, 1e-9)
    assert _close(px[4, 8][3], 1.0, 1e-9)
    # a corner: the nearest segment wins
    px = ts.stroke_pixels([(2.0, 2.0), (8.0, 2.0), (8.0, 8.0)], [0.0, 0.5, 1.0], 1.0, "#FFFFFF", 1.0, 10, 10)
    assert _close(px[1, 2][3], 0.5 / 6.0 * 0.5, 1e-9)
    assert _close(px[7, 7][3], 0.5 + 0.5 * 5.5 / 6.0, 1e-9)


def test_head_pixels_are_a_disc():
    px = ts.head_pixels((5.0, 5.0), 2.0, "#00FF00", 1.0, 10, 10)
    assert (px[..., 3] > 0).sum() == 12
    assert np.allclose(px[4, 4], (0.0, 1.0, 0.0, 1.0))
    assert ts.head_pixels((5.0, 5.0), 0.0, "#00FF00", 1.0, 10, 10).sum() == 0.0


def test_a_single_point_window_draws_its_head_only():
    px = ts.trip_pixels({"points": [(5.0, 5.0)], "alphas": [1.0], "head": (5.0, 5.0)},
                        {"stroke": "#FFFFFF", "strokeWidth": 2.0, "opacity": 1.0, "headRadius": 0.0, "headFill": None},
                        10, 10)
    assert (px[..., 3] > 0).sum() == 4  # the round cap of a zero-length path: a disc of radius 1
    px = ts.trip_pixels({"points": [(5.0, 5.0)], "alphas": [1.0], "head": (5.0, 5.0)},
                        {"stroke": "#FFFFFF", "strokeWidth": 2.0, "opacity": 1.0, "headRadius": 2.0, "headFill": "#FF0000"},
                        10, 10)
    assert (px[..., 3] > 0).sum() == 12 and np.allclose(px[4, 4], (1.0, 0.0, 0.0, 1.0))


# ------------------------------------------------------------------------------------------- style filters by time


def test_global_state_time_feeds_style_filters():
    state = {"time": 10.0}
    assert ts.evaluate(["global-state", "time"], {}, state) == 10.0
    assert ts.evaluate(["<=", ["get", "time"], ["global-state", "time"]], {"time": 5}, state) is True
    assert ts.evaluate(["<=", ["get", "time"], ["global-state", "time"]], {"time": 15}, state) is False
    assert ts.evaluate(["all", [">=", ["global-state", "time"], ["get", "start"]],
                        ["<", ["global-state", "time"], ["get", "end"]]], {"start": 0, "end": 20}, state) is True
    assert ts.evaluate(["global-state", "other"], {}, state) is None
    assert ts.keep_feature(["<=", ["get", "time"], ["global-state", "time"]], {"time": 5}, state) is True
    # a failing filter rejects the feature (SREP 9)
    assert ts.keep_feature(["<=", ["get", "time"], ["global-state", "time"]], {}, state) is False
    assert ts.keep_feature(None, {}, state) is True


def test_expressions_follow_srep_9s_subset():
    assert ts.evaluate(["+", 1, 2], {}, {}) == 3.0
    assert ts.evaluate(["case", ["has", "x"], 1, 2], {"x": 0}, {}) == 1
    assert ts.evaluate(["coalesce", ["get", "x"], 7], {}, {}) == 7
    assert ts.evaluate(["to-number", "12"], {}, {}) == 12.0
    assert ts.evaluate("{name} rocks", {"name": "Rome"}, {}) == "Rome rocks"
    with pytest.raises(ts.TimeSeriesError):
        ts.evaluate(["nope", 1], {}, {})
    with pytest.raises(ts.TimeSeriesError):
        ts.evaluate(["get", "missing"], {}, {})


# ----------------------------------------------------------------------------------------------------- the document


def test_world_pixel():
    assert _close(ts.world_pixel(0.0, 0.0, 0), (128.0, 128.0), 1e-9)
    assert _close(ts.world_pixel(-180.0, 0.0, 1), (0.0, 256.0), 1e-9)


def test_the_example_document_runs_frame_by_frame():
    doc = ts.example_document()
    out = ts.run(doc, 6.0)
    assert out["T"] == {"base": 240.0, "events": _epoch(2024, 1, 1, 3), "trips": 240.0}
    assert out["basemap"] == {"kept": 3, "dropped": 2}
    assert out["events"]["visible"] == 2 and out["events"]["hidden"] == 5
    assert _close(out["events"]["alphas"], [0.5, 1.0])
    assert out["trips"]["drawn"] == 1 and out["trips"]["pending"] == 1 and out["trips"]["gone"] == 0
    head = ts.world_pixel(-0.4, 0.0, 3.0)
    assert _close(out["trips"]["heads"][0], (head[0] - (1024.0 - 80.0), head[1] - (1024.0 - 60.0)), 1e-6)
    assert out["warnings"] == ["W-TS1", "W-TS2"]
    assert all(re.fullmatch(r"[0-9a-f]{12}", d) for d in out["digests"])


def test_the_example_at_its_start_and_end():
    doc = ts.example_document()
    start = ts.run(doc, 0.0)
    assert start["basemap"] == {"kept": 1, "dropped": 4}
    assert start["events"]["visible"] == 1 and start["events"]["alphas"] == [1.0]
    assert start["trips"]["drawn"] == 1 and start["trips"]["pending"] == 1
    end = ts.run(doc, 12.0)
    assert end["basemap"] == {"kept": 5, "dropped": 0}
    assert end["events"]["visible"] == 1
    assert end["trips"] == {"drawn": 0, "pending": 0, "gone": 2, "heads": []}


def test_any_frame_alone_equals_the_played_frame():
    doc = ts.example_document()
    alone = ts.run(doc, 6.0)
    for t in (0.0, 3.0, 9.0, 12.0):
        ts.run(doc, t)
    assert ts.run(doc, 6.0) == alone


def test_the_example_document_is_valid_and_the_bad_one_lists_every_code():
    assert ts.validate_document(ts.example_document()) == []
    codes = [c for c, _ in ts.validate_document(ts.bad_document())]
    assert codes == ["TS1", "TS2", "TS3", "TS4", "V19"]


def test_validation_one_at_a_time():
    def only(index, **patch):
        doc = ts.example_document()
        doc["map"]["children"][index].update(patch)
        return [c for c, _ in ts.validate_document(doc)]

    assert only(1, timeOrigin="yesterday") == ["TS1"]
    assert only(0, timeOrigin="2024-01-01") == ["TS1"]
    assert only(1, trail=-1.0) == ["TS2"]
    assert only(1, trail=0.0, fade=True) == ["TS2"]
    assert only(2, trail=0.0) == ["TS2"]
    doc = ts.example_document()
    del doc["map"]["children"][1]["timeBy"]
    assert [c for c, _ in ts.validate_document(doc)] == ["TS3"]
    doc = ts.example_document()
    doc["map"]["children"][2]["points"] = [(0.0, 0.0), (1.0, 1.0)]
    del doc["map"]["children"][2]["geo"]
    assert [c for c, _ in ts.validate_document(doc)] == ["TS3"]
    assert only(1, timeEndBy="time") == ["TS4"]
    assert only(2, timeScale=2) == ["V19"]
    assert only(0, time={"keys": [[0.0, 0.0], [12.0, 480.0]]}) == []


def test_constants_and_defaults():
    assert ts.GEO_TIME_DEFAULTS == {"timeBy": None, "timeEndBy": None, "timeOrigin": 0.0, "time": 0.0, "trail": 0.0,
                                    "fade": False}
    assert ts.ROUTE_TRIP_DEFAULTS["trail"] == 120.0 and ts.ROUTE_TRIP_DEFAULTS["fade"] is True
    assert ts.ROUTE_TRIP_DEFAULTS["timeBy"] is None and ts.ROUTE_TRIP_DEFAULTS["strokeWidth"] == 3.0
    assert ts.ROUTE_TRIP_DEFAULTS["stroke"] == "#FFFFFF" and ts.ROUTE_TRIP_DEFAULTS["headRadius"] == 0.0
    assert ts.BASEMAP_TIME_DEFAULTS == {"timeOrigin": 0.0, "time": 0.0}
    assert ts.R == 6378137.0 and ts.TILE == 256
    assert ts.STATES == ("visible", "pending", "expired", "ended", "unreadable")
    assert ts.TRIP_STATES == ("pending", "running", "complete", "gone")


# ---------------------------------------------------------------------------------------------------------- the draft


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
    for word in ("SR-114", "SREP 9", "SREP 12", "SREP 14", "`geoLayer`", "`route`", "`basemap`", "`timeBy`",
                 "`timeEndBy`", "`timeOrigin`", "`time`", "`trail`", "`fade`", "`progress`", "`headRadius`",
                 "`headFill`", "`stroke`", "`strokeWidth`", "`opacity`", "global-state", "ISO 8601", "1970",
                 "deck.gl", "TripsLayer", "MIT", "interpolated", "trail", "linear", "non-decreasing", "round",
                 "premultiplied", "seek check", "any frame alone", "TS1", "TS2", "TS3", "TS4", "W-TS1", "W-TS2",
                 "V19", "time_series_reference.py", "numpy", "6378137", "pending", "running", "complete", "gone",
                 "expired", "unreadable", "kepler.gl", "filter"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 20
    assert len(ts.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in ts.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = ts.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert ts._same(value, want), (name, value, want)
