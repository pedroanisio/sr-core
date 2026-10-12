"""Tests for sr_core.scene.values: value codecs, number formatting and XSD pattern translation."""
from __future__ import annotations

import datetime as dt
import math
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from sr_core.scene.errors import SchemaError, SchemaValueError
from sr_core.scene.values import Codec, codec_for, fmt_decimal, fmt_double, translate_pattern

ROOT = Path(__file__).resolve().parent.parent
XSD = ROOT / "schema" / "scene-render.xsd"
XS = "{http://www.w3.org/2001/XMLSchema}"

Table = dict[str, dict[str, Any]]


def spec(kind: str = "restriction", base: Any = None, enums: tuple[str, ...] = (),
         facets: tuple[tuple[str, str], ...] = (), members: tuple[Any, ...] = (), item: Any = None) -> dict[str, Any]:
    return {"kind": kind, "base": base, "enums": enums, "facets": facets, "members": members, "item": item}


def restrict(base: str, *facets: tuple[str, str], enums: tuple[str, ...] = ()) -> dict[str, Any]:
    return spec(base=base, facets=tuple(facets), enums=enums)


def refused(codec: Codec, value: Any) -> SchemaValueError:
    with pytest.raises(SchemaValueError) as info:
        codec.validate(value)
    assert info.value.xsd_type, "xsd_type must be set"
    assert str(info.value.message)
    return info.value


# ---------------------------------------------------------------------------------------------------- formatting

class TestFmtDecimal:
    @pytest.mark.parametrize("value,expected", [
        (0.0, "0"), (-0.0, "0"), (1.0, "1"), (-2.5, "-2.5"), (0.1 + 0.2, "0.30000000000000004"),
        (1e-7, "0.0000001"), (1.5e-10, "0.00000000015"), (123.456, "123.456"), (1e16, "10000000000000000"),
        (1e21, "1000000000000000000000"), (-1e-5, "-0.00001"), (3, "3"), (-7, "-7"), (0, "0"),
        (2 ** 70, str(2 ** 70)), (Decimal("-12.500"), "-12.5"), (Decimal("100"), "100"), (Decimal("1E+3"), "1000"),
        (Decimal("-0.000"), "0"), (Decimal("0.0000000000000000000000000000001234567890123456789"),
                                   "0.0000000000000000000000000000001234567890123456789"),
    ])
    def test_values(self, value: Any, expected: str) -> None:
        assert fmt_decimal(value) == expected

    def test_shortest_round_trip(self) -> None:
        for v in (0.1, 1 / 3, 2 ** 53 + 1.0, 5e-324, 1.7976931348623157e308):
            s = fmt_decimal(v)
            assert float(s) == v
            assert "e" not in s.lower()

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, Decimal("NaN"), Decimal("Infinity")])
    def test_refuses_non_finite(self, bad: Any) -> None:
        with pytest.raises(SchemaValueError):
            fmt_decimal(bad)


class TestFmtDouble:
    @pytest.mark.parametrize("value,expected", [
        (0.5, "0.5"), (-0.0, "0"), (2, "2"), (1e-7, "0.0000001"), (1e22, "10000000000000000000000"),
        (0.1 + 0.2, "0.30000000000000004"),
    ])
    def test_values(self, value: Any, expected: str) -> None:
        assert fmt_double(value) == expected

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 10 ** 400])
    def test_refuses(self, bad: Any) -> None:
        with pytest.raises(SchemaValueError):
            fmt_double(bad)


# ---------------------------------------------------------------------------------------------------- builtins

class TestDouble:
    c = codec_for("xs:double", {})

    def test_metadata(self) -> None:
        assert self.c.xsd_type == "xs:double"
        assert self.c.literals is None

    @pytest.mark.parametrize("value,expected", [(1, "1"), (0.25, "0.25"), (-0.0, "0"), (1e-9, "0.000000001")])
    def test_validate(self, value: Any, expected: str) -> None:
        assert self.c.validate(value) == expected

    @pytest.mark.parametrize("bad", [True, False, "x", Decimal("1"), None, math.nan, math.inf, -math.inf, [1], 10 ** 400])
    def test_refuses(self, bad: Any) -> None:
        refused(self.c, bad)

    @pytest.mark.parametrize("lex,expected", [
        ("1.5", 1.5), (" 2 ", 2.0), ("-.5", -0.5), ("+3", 3.0), ("1e3", 1000.0), ("1.5E-2", 0.015), ("5.", 5.0),
        ("INF", math.inf), ("-INF", -math.inf), ("0", 0.0),
    ])
    def test_parse(self, lex: str, expected: float) -> None:
        assert self.c.parse(lex) == expected
        assert self.c.is_valid_lexical(lex)

    def test_parse_nan(self) -> None:
        assert math.isnan(self.c.parse("NaN"))
        assert self.c.is_valid_lexical("NaN")

    @pytest.mark.parametrize("lex", ["", "inf", "nan", "+INF", "1_0", "1,5", "0x10", "e5", "1e", "--1", "١٢", "1 2"])
    def test_parse_refuses(self, lex: str) -> None:
        assert not self.c.is_valid_lexical(lex)
        with pytest.raises(SchemaValueError):
            self.c.parse(lex)


class TestDecimal:
    c = codec_for("xs:decimal", {})

    @pytest.mark.parametrize("value,expected", [
        (1, "1"), (0.5, "0.5"), (Decimal("1.250"), "1.25"), ("1.50", "1.50"), (" 7 ", " 7 "), ("-.5", "-.5"), ("+2.", "+2."),
        (-0.0, "0"),
    ])
    def test_validate(self, value: Any, expected: str) -> None:
        assert self.c.validate(value) == expected

    @pytest.mark.parametrize("bad", [True, None, "1e3", "abc", "", "1.2.3", math.nan, math.inf, Decimal("NaN"), [1]])
    def test_refuses(self, bad: Any) -> None:
        refused(self.c, bad)

    def test_parse_is_exact(self) -> None:
        v = self.c.parse("0.10000000000000000000000001")
        assert isinstance(v, Decimal) and v == Decimal("0.10000000000000000000000001")
        long = "0." + "0" * 40 + "1"
        assert self.c.validate(long) == long

    def test_lexical(self) -> None:
        assert self.c.is_valid_lexical("12.5")
        assert not self.c.is_valid_lexical("1e3")
        assert not self.c.is_valid_lexical("NaN")
        assert not self.c.is_valid_lexical("١٢")


class TestIntegerFamily:
    @pytest.mark.parametrize("name,good,bad", [
        ("xs:integer", [0, -5, 10 ** 30], ["1.0", 1.0, True]),
        ("xs:positiveInteger", [1, 10 ** 30], [0, -1, "0", True]),
        ("xs:nonNegativeInteger", [0, 7], [-1, 1.5, False]),
        ("xs:int", [-2 ** 31, 2 ** 31 - 1], [-2 ** 31 - 1, 2 ** 31]),
        ("xs:unsignedLong", [0, 2 ** 64 - 1], [-1, 2 ** 64]),
    ])
    def test_validate(self, name: str, good: list[Any], bad: list[Any]) -> None:
        c = codec_for(name, {})
        assert c.xsd_type == name
        for g in good:
            assert c.validate(g) == str(g)
        for b in bad:
            refused(c, b)

    @pytest.mark.parametrize("name,lex,ok", [
        ("xs:integer", "+5", True), ("xs:integer", "05", True), ("xs:integer", " 12 ", True), ("xs:integer", "1.0", False),
        ("xs:integer", "", False), ("xs:integer", "-", False), ("xs:integer", "١", False),
        ("xs:positiveInteger", "0", False), ("xs:positiveInteger", "+1", True), ("xs:positiveInteger", "-0", False),
        ("xs:nonNegativeInteger", "-0", True), ("xs:nonNegativeInteger", "-1", False),
        ("xs:int", "2147483647", True), ("xs:int", "2147483648", False), ("xs:int", "-2147483648", True),
        ("xs:unsignedLong", "18446744073709551615", True), ("xs:unsignedLong", "18446744073709551616", False),
    ])
    def test_lexical(self, name: str, lex: str, ok: bool) -> None:
        c = codec_for(name, {})
        assert c.is_valid_lexical(lex) is ok
        if ok:
            v = c.parse(lex)
            assert isinstance(v, int) and not isinstance(v, bool)
            assert v == int(lex)
        else:
            with pytest.raises(SchemaValueError):
                c.parse(lex)


class TestBoolean:
    c = codec_for("xs:boolean", {})

    def test_validate(self) -> None:
        assert self.c.validate(True) == "true"
        assert self.c.validate(False) == "false"

    @pytest.mark.parametrize("bad", [1, 0, "yes", "True", None, 1.0])
    def test_refuses(self, bad: Any) -> None:
        refused(self.c, bad)

    @pytest.mark.parametrize("lex,expected", [("true", True), ("1", True), ("false", False), ("0", False), (" true ", True)])
    def test_parse(self, lex: str, expected: bool) -> None:
        assert self.c.parse(lex) is expected

    @pytest.mark.parametrize("lex", ["True", "TRUE", "yes", "2", "", "tru"])
    def test_parse_refuses(self, lex: str) -> None:
        assert not self.c.is_valid_lexical(lex)
        with pytest.raises(SchemaValueError):
            self.c.parse(lex)


class TestStringsAndNames:
    def test_string(self) -> None:
        c = codec_for("xs:string", {})
        assert c.validate("  a  b\n") == "  a  b\n"
        assert c.parse(" x ") == " x "
        refused(c, 1)
        refused(c, None)
        refused(c, "bad\x00char")
        refused(c, "bad￾")
        assert c.is_valid_lexical("")
        assert not c.is_valid_lexical("\x01")

    @pytest.mark.parametrize("name", ["xs:NCName", "xs:ID", "xs:IDREF"])
    def test_ncname_family(self, name: str) -> None:
        c = codec_for(name, {})
        for good in ["a", "_x", "layer-1", "a.b", "é1", "A_b-c.d9", "日本"]:
            assert c.validate(good) == good
            assert c.is_valid_lexical(good)
        assert c.validate("  padded ") == "padded"
        for bad in ["", "1a", "-a", ".a", "a:b", "a b", "a#b", "a/b", 5, None, "·a"]:
            if isinstance(bad, str):
                assert not c.is_valid_lexical(bad), bad
            refused(c, bad)
        assert c.parse(" x ") == "x"

    def test_nmtoken(self) -> None:
        c = codec_for("xs:NMTOKEN", {})
        for good in ["a", "1", "-x", ".y", "a:b", "x·y"]:
            assert c.validate(good) == good
        for bad in ["", "a b", "a#", "a/b", 3]:
            refused(c, bad)
        assert c.parse("  tok ") == "tok"

    def test_anyuri(self) -> None:
        c = codec_for("xs:anyURI", {})
        for good in ["a.png", "file:///a/b%20c.png", "https://x.org/a?b=c#d", "../rel/p.png", "assets/a b.png"]:
            assert c.validate(good) == good
        assert c.validate("  x.png ") == "x.png"
        refused(c, 3)
        refused(c, "a\x00b")

    @pytest.mark.parametrize("uri", [
        "", "#", "?", "a%41", "http://[::1]/p", "http://[v1.x]/", "http://u:p@h:80/p?q=1/2?#f", "mailto:x@y",
        "http://127.0.0.1:8080", "a b", "é.png", "日本/x", "a<b>{c}|d\\e^f`g\"h", "a:b:c", "//h/p", "/a//b", "~u/x",
        "http://[2001:db8::7]/", "http://[::ffff:1.2.3.4]/", "a\tb",
    ])
    def test_anyuri_accepts_references(self, uri: str) -> None:
        assert codec_for("xs:anyURI", {}).is_valid_lexical(uri)

    @pytest.mark.parametrize("uri", [
        "%", "a%", "%zz", "%4", "a%2", "%%", "a%d", "#a#b", "a#b#", "[", "]", "[a]", "a[b]", "http://x/[1]",
        "http://[::1/", "http://[:::1]/", "http://[1:2]/", ":::", "1:2", ":a", "http://h:p/", "a?b#c#d", "x]",
        "http://[v.x]/",
    ])
    def test_anyuri_refuses_malformed(self, uri: str) -> None:
        # RFC 3986: pct-encoded needs two hex digits; one "#"; "[" and "]" only in an IP-literal; scheme is ALPHA first.
        assert not codec_for("xs:anyURI", {}).is_valid_lexical(uri)
        with pytest.raises(SchemaValueError):
            codec_for("xs:anyURI", {}).validate(uri)

    def test_idref_accepts_objects_with_id(self) -> None:
        c = codec_for("xs:IDREF", {})

        class Thing:
            def __init__(self, id: Any) -> None:
                self.id = id

        assert c.validate(Thing("title")) == "title"
        refused(c, Thing(None))
        refused(c, Thing(""))
        refused(c, Thing("1bad"))
        refused(c, Thing(5))
        refused(c, object())
        # ID does not take objects: it names, it does not refer
        refused(codec_for("xs:ID", {}), Thing("x"))

    def test_idrefs_and_nmtokens(self) -> None:
        class Thing:
            id = "t2"

        idrefs = codec_for("xs:IDREFS", {})
        assert idrefs.validate(["a", Thing(), "c"]) == "a t2 c"
        assert idrefs.validate("a   b\tc") == "a b c"
        assert idrefs.parse("a b") == ["a", "b"]
        refused(idrefs, [])
        refused(idrefs, ["a", "1x"])
        refused(idrefs, [3])
        assert not idrefs.is_valid_lexical("")
        assert not idrefs.is_valid_lexical("   ")
        nm = codec_for("xs:NMTOKENS", {})
        assert nm.validate(("x", "y-1")) == "x y-1"
        assert nm.parse(" x  y ") == ["x", "y"]
        refused(nm, [])
        refused(nm, ["a b"])


class TestDateTime:
    c = codec_for("xs:dateTime", {})

    @pytest.mark.parametrize("lex", [
        "2024-02-29T12:30:45", "2024-02-29T12:30:45Z", "2024-02-29T12:30:45.123+05:30", "0001-01-01T00:00:00",
        "2024-12-31T24:00:00", "-0044-03-15T00:00:00Z", "12345-01-01T00:00:00", "2024-01-01T00:00:00-14:00",
        " 2024-01-01T00:00:00Z ",
    ])
    def test_valid_lexical(self, lex: str) -> None:
        assert self.c.is_valid_lexical(lex)

    @pytest.mark.parametrize("lex", [
        "2023-02-29T00:00:00", "2024-13-01T00:00:00", "2024-00-10T00:00:00", "2024-01-32T00:00:00", "2024-01-01",
        "2024-01-01T25:00:00", "2024-01-01T24:00:01", "2024-01-01T00:60:00", "2024-01-01T00:00:60",
        "2024-01-01 00:00:00", "2024-01-01T00:00", "24-01-01T00:00:00", "0000-01-01T00:00:00", "2024-01-01T00:00:00+15:00",
        "2024-01-01T00:00:00+14:30", "2024-01-01T00:00:00+0530", "2024-01-01T00:00:00.Z", "", "2100-02-29T00:00:00",
        "２０２４-01-01T00:00:00",
    ])
    def test_invalid_lexical(self, lex: str) -> None:
        assert not self.c.is_valid_lexical(lex)
        with pytest.raises(SchemaValueError):
            self.c.parse(lex)

    def test_century_leap_rules(self) -> None:
        assert self.c.is_valid_lexical("2000-02-29T00:00:00")
        assert not self.c.is_valid_lexical("1900-02-29T00:00:00")

    def test_parse(self) -> None:
        v = self.c.parse("2024-02-29T12:30:45.5+05:30")
        assert v == dt.datetime(2024, 2, 29, 12, 30, 45, 500000, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
        assert self.c.parse("2024-02-29T12:30:45") == dt.datetime(2024, 2, 29, 12, 30, 45)
        assert self.c.parse("2024-02-29T12:30:45Z").tzinfo == dt.timezone.utc
        assert self.c.parse("2024-12-31T24:00:00") == dt.datetime(2025, 1, 1)

    def test_parse_outside_python_range_is_valid_lexically_but_unrepresentable(self) -> None:
        assert self.c.is_valid_lexical("12345-01-01T00:00:00")
        with pytest.raises(SchemaValueError):
            self.c.parse("12345-01-01T00:00:00")

    def test_validate(self) -> None:
        assert self.c.validate(dt.datetime(2024, 2, 29, 12, 30, 45)) == "2024-02-29T12:30:45"
        assert self.c.validate(dt.datetime(2024, 2, 29, 12, 30, 45, 120000)) == "2024-02-29T12:30:45.12"
        assert self.c.validate(dt.datetime(2024, 2, 29, tzinfo=dt.timezone.utc)) == "2024-02-29T00:00:00Z"
        tz = dt.timezone(dt.timedelta(hours=-3, minutes=-30))
        assert self.c.validate(dt.datetime(2024, 2, 29, 1, tzinfo=tz)) == "2024-02-29T01:00:00-03:30"
        assert self.c.validate(dt.datetime(5, 1, 1)) == "0005-01-01T00:00:00"
        assert self.c.validate("2024-01-01T00:00:00Z") == "2024-01-01T00:00:00Z"
        assert self.c.validate(" 2024-01-01T00:00:00 ") == " 2024-01-01T00:00:00 "
        refused(self.c, dt.date(2024, 1, 1))
        refused(self.c, "2024-01-01")
        refused(self.c, 5)
        refused(self.c, dt.datetime(2024, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=15))))


# ---------------------------------------------------------------------------------------------------- restrictions

class TestEnumeration:
    def test_literals_and_membership(self) -> None:
        c = codec_for(restrict("xs:string", enums=("a", "b-c", "d")), {})
        assert c.literals == ("a", "b-c", "d")
        assert c.validate("b-c") == "b-c"
        refused(c, "B-C")
        refused(c, "e")
        refused(c, " a")
        refused(c, 1)
        assert c.is_valid_lexical("d")
        assert not c.is_valid_lexical("z")
        assert c.parse("a") == "a"

    def test_error_names_the_literals(self) -> None:
        c = codec_for(restrict("xs:string", enums=("a", "b")), {})
        err = refused(c, "z")
        assert "'a'" in err.message and "'z'" in err.message

    def test_numeric_enumeration_compares_in_value_space(self) -> None:
        c = codec_for(restrict("xs:integer", enums=("1", "02", "3")), {})
        assert c.literals == ("1", "02", "3")
        assert c.validate(2) == "2"
        assert c.is_valid_lexical("+1")
        assert not c.is_valid_lexical("4")
        refused(c, 4)

    def test_named_type_literals(self) -> None:
        table: Table = {"mode": restrict("xs:string", enums=("x", "y"))}
        c = codec_for("mode", table)
        assert c.literals == ("x", "y")
        assert c.xsd_type == "mode"
        assert c.validate("y") == "y"

    def test_enumeration_entries_may_carry_documentation(self) -> None:
        c = codec_for(spec(base="xs:string", enums=(("a", "doc a"), ("b", ""))), {})  # type: ignore[arg-type]
        assert c.literals == ("a", "b")


class TestLengthFacets:
    def test_string_length(self) -> None:
        c = codec_for(restrict("xs:string", ("length", "3")), {})
        assert c.validate("abc") == "abc"
        refused(c, "ab")
        refused(c, "abcd")
        assert c.validate("日本語") == "日本語"

    def test_min_max_length(self) -> None:
        c = codec_for(restrict("xs:string", ("minLength", "2"), ("maxLength", "4")), {})
        for ok in ["ab", "abcd"]:
            assert c.validate(ok) == ok
        refused(c, "a")
        refused(c, "abcde")
        assert not c.is_valid_lexical("a")
        assert c.is_valid_lexical("abc")

    def test_collapse_applies_before_length(self) -> None:
        c = codec_for(restrict("xs:NMTOKEN", ("maxLength", "3")), {})
        assert c.validate("  abc ") == "abc"
        refused(c, "abcd")

    def test_length_on_numeric_base_is_a_schema_error(self) -> None:
        with pytest.raises(SchemaError):
            codec_for(restrict("xs:integer", ("length", "3")), {})


class TestRangeFacets:
    def test_double_inclusive(self) -> None:
        c = codec_for(restrict("xs:double", ("minInclusive", "0"), ("maxInclusive", "1")), {})
        for ok in [0, 1, 0.5, 0.0]:
            c.validate(ok)
        for bad in [-0.0001, 1.0000001, 2]:
            refused(c, bad)
        assert c.parse("1") == 1.0
        assert not c.is_valid_lexical("1.1")
        assert not c.is_valid_lexical("NaN")
        assert not c.is_valid_lexical("INF")

    def test_double_exclusive(self) -> None:
        c = codec_for(restrict("xs:double", ("minExclusive", "0"), ("maxExclusive", "10")), {})
        c.validate(1e-300)
        c.validate(9.999999)
        refused(c, 0)
        refused(c, 10)

    def test_decimal_bounds_are_exact(self) -> None:
        c = codec_for(restrict("xs:decimal", ("maxInclusive", "0.1")), {})
        assert c.validate("0.1") == "0.1"
        assert c.validate(Decimal("0.1")) == "0.1"
        refused(c, "0.1000000000000000000000001")
        c2 = codec_for(restrict("xs:decimal", ("minExclusive", "0")), {})
        refused(c2, "0.0")
        assert c2.validate("0.0000000000000000000000000001") == "0.0000000000000000000000000001"

    def test_integer_bounds(self) -> None:
        c = codec_for(restrict("xs:integer", ("minInclusive", "-3"), ("maxExclusive", "5")), {})
        for ok in [-3, 0, 4]:
            c.validate(ok)
        for bad in [-4, 5]:
            refused(c, bad)

    def test_positive_integer_with_max(self) -> None:
        c = codec_for(restrict("xs:positiveInteger", ("maxInclusive", "9")), {})
        c.validate(9)
        refused(c, 0)
        refused(c, 10)

    def test_range_on_string_is_a_schema_error(self) -> None:
        with pytest.raises(SchemaError):
            codec_for(restrict("xs:string", ("minInclusive", "0")), {})

    def test_range_on_datetime_is_a_schema_error(self) -> None:
        with pytest.raises(SchemaError):
            codec_for(restrict("xs:dateTime", ("minInclusive", "2000-01-01T00:00:00")), {})

    def test_bound_outside_base_value_space_is_a_schema_error(self) -> None:
        with pytest.raises(SchemaError):
            codec_for(restrict("xs:integer", ("minInclusive", "x")), {})
        with pytest.raises(SchemaError):
            codec_for(restrict("xs:positiveInteger", ("minInclusive", "0")), {})

    def test_unknown_facet_is_a_schema_error(self) -> None:
        with pytest.raises(SchemaError):
            codec_for(restrict("xs:string", ("totalDigits", "3")), {})
        with pytest.raises(SchemaError):
            codec_for(restrict("xs:string", ("whiteSpace", "collapse")), {})


class TestPatternFacet:
    def test_pattern_matches_whole_value(self) -> None:
        c = codec_for(restrict("xs:string", ("pattern", "[a-f]{2}")), {})
        assert c.validate("ab") == "ab"
        refused(c, "abc")
        refused(c, "xab")
        refused(c, "ab\n")
        assert not c.is_valid_lexical("zz")

    def test_two_patterns_in_one_step_are_alternatives(self) -> None:
        c = codec_for(restrict("xs:string", ("pattern", "a+"), ("pattern", "b+")), {})
        c.validate("aaa")
        c.validate("bb")
        refused(c, "ab")

    def test_patterns_across_derivation_steps_are_conjunctive(self) -> None:
        table: Table = {"base": restrict("xs:string", ("pattern", "[a-z]+"))}
        c = codec_for(restrict("base", ("pattern", ".{3}")), table)
        c.validate("abc")
        refused(c, "ab")
        refused(c, "ab1")

    def test_untranslatable_pattern_is_a_schema_error(self) -> None:
        with pytest.raises(SchemaError):
            codec_for(restrict("xs:string", ("pattern", r"\p{L}+")), {})

    def test_pattern_on_numeric_applies_to_lexical_form(self) -> None:
        c = codec_for(restrict("xs:integer", ("pattern", "[0-9]{2}")), {})
        assert c.validate(42) == "42"
        refused(c, 421)
        refused(c, -4)


# ---------------------------------------------------------------------------------------------------- list and union

class TestList:
    def test_python_sequence_in_joined_out(self) -> None:
        c = codec_for(spec(kind="list", item="xs:double"), {})
        assert c.validate([1, 0.5, -2]) == "1 0.5 -2"
        assert c.validate((1.5,)) == "1.5"
        assert c.validate([]) == ""
        assert c.parse("1 0.5\t-2\n") == [1.0, 0.5, -2.0]
        assert c.parse("") == []
        assert c.is_valid_lexical("1 2 3")
        assert not c.is_valid_lexical("1 x")
        refused(c, [1, "x"])
        refused(c, [True])
        refused(c, 3)
        refused(c, None)

    def test_string_is_taken_as_lexical_form(self) -> None:
        c = codec_for(spec(kind="list", item="xs:double"), {})
        assert c.validate("1   2") == "1 2"
        refused(c, "1 two")

    def test_item_with_space_is_refused(self) -> None:
        c = codec_for(spec(kind="list", item="xs:string"), {})
        refused(c, ["a b"])
        assert c.validate(["a", "b"]) == "a b"

    def test_length_facets_count_items(self) -> None:
        c = codec_for(spec(kind="list", item="xs:double", facets=(("length", "3"),)), {})
        assert c.validate([1, 2, 3]) == "1 2 3"
        refused(c, [1, 2])
        refused(c, [1, 2, 3, 4])
        assert not c.is_valid_lexical("1 2")
        c2 = codec_for(spec(kind="list", item="xs:integer", facets=(("minLength", "1"), ("maxLength", "2"))), {})
        c2.validate([1])
        refused(c2, [])
        refused(c2, [1, 2, 3])

    def test_item_facets_apply_to_each_item(self) -> None:
        table: Table = {"unit": restrict("xs:double", ("minInclusive", "0"), ("maxInclusive", "1"))}
        c = codec_for(spec(kind="list", item="unit"), table)
        assert c.validate([0, 0.5, 1]) == "0 0.5 1"
        refused(c, [0, 1.5])

    def test_restriction_of_inline_list_base(self) -> None:
        table: Table = {"unit": restrict("xs:double", ("minInclusive", "0"), ("maxInclusive", "1"))}
        triple = spec(base=spec(kind="list", item="unit"), facets=(("length", "3"),))
        c = codec_for(triple, table)
        assert c.validate([0.1, 0.2, 0.3]) == "0.1 0.2 0.3"
        refused(c, [0.1, 0.2])
        refused(c, [0.1, 0.2, 2])

    def test_named_list_and_xsd_type(self) -> None:
        table: Table = {"nums": spec(kind="list", item="xs:double")}
        c = codec_for("nums", table)
        assert c.xsd_type == "nums"
        refused(c, ["z"])

    def test_list_of_enumeration_has_no_literals_but_validates_items(self) -> None:
        table: Table = {"role": restrict("xs:string", enums=("a", "b"))}
        c = codec_for(spec(kind="list", item="role"), table)
        assert c.validate(["a", "b"]) == "a b"
        refused(c, ["a", "c"])


class TestUnion:
    table: Table = {
        "rel": restrict("xs:string", ("pattern", "-?[0-9]+%")),
        "posdec": restrict("xs:decimal", ("minExclusive", "0")),
    }

    def test_first_accepting_member_wins(self) -> None:
        c = codec_for(spec(kind="union", members=("xs:double", "rel")), self.table)
        assert c.validate(1.5) == "1.5"
        assert c.validate("50%") == "50%"
        refused(c, "nope")
        refused(c, True)
        assert c.parse("2") == 2.0
        assert c.parse("50%") == "50%"
        assert c.is_valid_lexical("3e2")
        assert c.is_valid_lexical("-5%")
        assert not c.is_valid_lexical("5px")

    def test_member_order_decides(self) -> None:
        a = codec_for(spec(kind="union", members=("xs:string", "xs:integer")), {})
        assert a.parse("5") == "5"
        b = codec_for(spec(kind="union", members=("xs:integer", "xs:string")), {})
        assert b.parse("5") == 5
        assert b.parse("five") == "five"

    def test_inline_member_specs(self) -> None:
        enum = restrict("xs:string", enums=("max",))
        c = codec_for(spec(kind="union", members=("posdec", enum)), self.table)
        assert c.validate("max") == "max"
        assert c.validate(2) == "2"
        refused(c, 0)
        refused(c, "min")

    def test_union_error_names_type(self) -> None:
        c = codec_for(spec(kind="union", members=("xs:double", "rel")), self.table)
        err = refused(c, "bad")
        assert err.xsd_type

    def test_union_of_lists(self) -> None:
        c = codec_for(spec(kind="union", members=(spec(kind="list", item="xs:integer"), "xs:string")), {})
        assert c.validate([1, 2]) == "1 2"
        assert c.validate("a b") == "a b"


# ---------------------------------------------------------------------------------------------------- codec_for

class TestCodecFor:
    def test_builtins_have_matching_xsd_type(self) -> None:
        names = ["xs:double", "xs:string", "xs:positiveInteger", "xs:boolean", "xs:IDREF", "xs:ID", "xs:anyURI",
                 "xs:nonNegativeInteger", "xs:IDREFS", "xs:unsignedLong", "xs:NMTOKEN", "xs:NCName", "xs:integer",
                 "xs:decimal", "xs:int", "xs:dateTime", "xs:NMTOKENS"]
        for n in names:
            c = codec_for(n, {})
            assert c.xsd_type == n
            assert c.literals is None

    def test_unknown_builtin_and_unknown_name(self) -> None:
        with pytest.raises(SchemaError):
            codec_for("xs:float", {})
        with pytest.raises(SchemaError):
            codec_for("missing", {})
        with pytest.raises(SchemaError):
            codec_for(spec(kind="mystery"), {})

    def test_cache_returns_same_object(self) -> None:
        table: Table = {"t": restrict("xs:double", ("minInclusive", "0"))}
        assert codec_for("t", table) is codec_for("t", table)
        assert codec_for("xs:double", table) is codec_for("xs:double", {})
        inline = restrict("xs:integer", ("minInclusive", "0"))
        assert codec_for(inline, table) is codec_for(inline, table)

    def test_named_type_chain(self) -> None:
        table: Table = {"a": restrict("xs:double", ("minInclusive", "0")), "b": restrict("a", ("maxInclusive", "1"))}
        c = codec_for("b", table)
        c.validate(1)
        refused(c, 2)
        refused(c, -1)
        assert c.xsd_type == "b"

    def test_cycle_is_a_schema_error(self) -> None:
        table: Table = {"a": restrict("b"), "b": restrict("a")}
        with pytest.raises(SchemaError):
            codec_for("a", table)

    def test_missing_keys_are_a_schema_error(self) -> None:
        with pytest.raises(SchemaError):
            codec_for({"kind": "restriction"}, {})  # type: ignore[arg-type]

    def test_error_fields_for_callers(self) -> None:
        err = refused(codec_for("xs:integer", {}), "x")
        assert err.path is None and err.attribute is None
        assert err.xsd_type == "xs:integer"


# ---------------------------------------------------------------------------------------------------- patterns

def full(xsd_regex: str, text: str) -> bool:
    return re.fullmatch(translate_pattern(xsd_regex), text) is not None


class TestTranslatePattern:
    def test_anchors_are_literal(self) -> None:
        assert full("^a$", "^a$")
        assert not full("^a$", "a")
        assert full("a^b", "a^b")
        assert full("[a$^]+", "$a^")

    def test_dot_excludes_cr_and_lf(self) -> None:
        assert full(".+", "abc")
        assert not full(".", "\n")
        assert not full(".", "\r")
        assert full(".", "é")

    def test_single_char_escapes(self) -> None:
        assert full(r"\n\r\t", "\n\r\t")
        for ch in "\\|.-^?*+{}()[]":
            assert full("\\" + ch, ch), ch
            assert not full("\\" + ch, "x"), ch

    def test_unknown_escape_is_an_error(self) -> None:
        for bad in [r"\q", r"\/", r"\a", "a\\", r"\1", r"[\q]"]:
            with pytest.raises(SchemaError):
                translate_pattern(bad)

    def test_digit_escapes_are_unicode_aware(self) -> None:
        assert full(r"\d+", "123")
        assert full(r"\d+", "١٢٣")
        assert full(r"\D+", "abc")
        assert not full(r"\D", "5")

    def test_space_escape_is_xsd_whitespace_only(self) -> None:
        assert full(r"\s+", " \t\r\n")
        assert not full(r"\s", "\x0b")
        assert not full(r"\s", " ")
        assert full(r"\S", " ")
        assert not full(r"\S", " ")

    def test_word_escape_follows_xsd_definition(self) -> None:
        # XSD \w is everything except punctuation, separators and other (control, unassigned)
        assert full(r"\w+", "abc123é日本")
        assert full(r"\w", "+")        # Sm is not punctuation
        assert full(r"\w", "$")        # Sc
        assert not full(r"\w", "_")    # Pc
        assert not full(r"\w", "-")
        assert not full(r"\w", " ")
        assert not full(r"\w", "\n")
        assert full(r"\W", "_")
        assert not full(r"\W", "a")

    def test_classes(self) -> None:
        assert full("[a-c]+", "abcba")
        assert not full("[a-c]", "d")
        assert full("[^a-c]", "d")
        assert not full("[^a-c]", "b")
        assert full(r"[\-+]", "-")
        assert full("[-+]", "-")
        assert full("[+-]", "-")
        assert full("[a-]", "-")
        assert full(r"[\d.]+", "1.5")
        assert full(r"[\s,]+", " , ")
        assert full(r"[\w.]+", "ab.c")
        assert not full(r"[\w.]", "_")
        assert full(r"[\S]", "a")
        assert not full(r"[\S]", " ")
        assert full(r"[\W]", "_")
        assert full(r"[\]\[]", "[")
        assert full(r"[\\]", "\\")
        assert full(r"[a^]", "^")
        assert full("[&&~~||]+", "&~|")
        assert full(r"[^\n\r]", "x")
        assert not full(r"[^\n\r]", "\n")

    def test_class_errors(self) -> None:
        for bad in ["[]", "[^]", "[abc", "[a-z-[aeiou]]", "[a-[b]]", "[z-a]", "[a[b]", r"[\d-z]", r"[a-\d]"]:
            with pytest.raises(SchemaError):
                translate_pattern(bad)

    def test_quantifiers(self) -> None:
        assert full("a?", "")
        assert full("a?", "a")
        assert not full("a?", "aa")
        assert full("a*", "aaaa")
        assert full("a+", "a")
        assert not full("a+", "")
        assert full("a{3}", "aaa")
        assert not full("a{3}", "aa")
        assert full("a{2,3}", "aa")
        assert not full("a{2,3}", "aaaa")
        assert full("a{2,}", "aaaaa")
        assert not full("a{2,}", "a")
        assert full("(ab){2}", "abab")
        assert full("a{0}", "")

    def test_quantifier_errors(self) -> None:
        # XSD has one quantifier per atom: "a*?" is not lazy matching, it is invalid
        for bad in ["*a", "+", "?", "a*?", "a+*", "a??", "(*)", "|*", "a{", "a{x}", "a{,3}", "a{3,2}", "a{1", "}"]:
            with pytest.raises(SchemaError):
                translate_pattern(bad)

    def test_groups_and_alternation(self) -> None:
        assert full("a|bc", "a")
        assert full("a|bc", "bc")
        assert not full("a|bc", "ab")
        assert full("(a|b)c", "bc")
        assert full("((a)(b))+", "abab")
        assert full("a||b", "")
        assert full("()", "")
        assert full("a|ab", "ab")

    def test_groups_do_not_capture(self) -> None:
        assert re.compile(translate_pattern("(a)(b)")).groups == 0

    def test_group_errors(self) -> None:
        for bad in ["(a", "a)", "(?:a)", "(?i)a"]:
            with pytest.raises(SchemaError):
                translate_pattern(bad)

    @pytest.mark.parametrize("bad", [r"\i", r"\c", r"\I", r"\C", r"\p{L}", r"\P{Nd}", r"[\i]", r"[\p{L}]", r"\i\c*"])
    def test_unsupported_xsd_features_raise(self, bad: str) -> None:
        with pytest.raises(SchemaError):
            translate_pattern(bad)

    def test_astral_and_literal_text(self) -> None:
        assert full("日本", "日本")
        assert full("😀+", "😀😀")
        assert full(" a ", " a ")
        assert full("a b", "a b")
        assert full("#", "#")
        assert full("%", "%")
        assert full(r"url\(#x\)", "url(#x)")

    def test_result_is_a_compilable_str(self) -> None:
        p = translate_pattern("[0-9]+")
        assert isinstance(p, str)
        re.compile(p)


def _real_patterns() -> list[tuple[str, str]]:
    root = ET.parse(XSD).getroot()
    parents = {c: p for p in root.iter() for c in p}
    found: list[tuple[str, str]] = []
    for p in root.iter(XS + "pattern"):
        node: ET.Element | None = p
        while node is not None and node.get("name") is None:
            node = parents.get(node)
        found.append((node.get("name") if node is not None else "?", p.get("value") or ""))
    return found


# type name -> (examples that must match, examples that must not)
REAL_EXAMPLES: dict[str, tuple[list[str], list[str]]] = {
    "fpsType": (["24", "30000/1001", "60", "1/1"], ["", "0", "24/", "/1", "24/0", "24.5", "-24", "24 ", "a"]),
    "aspectType": (["16:9", "4:3", "1:1", "21:9"], ["16", "16:", ":9", "0:1", "16:09x", "16/9", "16:0", "-1:1", " 16:9"]),
    "sha256Type": (["0" * 64, "abcdef0123456789" * 4], ["0" * 63, "0" * 65, "A" * 64, "g" * 64, ""]),
    "timecodeType": (["00:00:00:00", "01:02:59;29", "10:59:59:99"], ["0:00:00:00", "00:60:00:00", "00:00:60:00", "00:00:00:0",
                                                                      "00:00:00.00", "00:00:00", "aa:00:00:00"]),
    "languageTagType": (["en", "pt-BR", "zh-Hant-TW", "sr-Latn-RS", "en-US-x-twain"],
                        ["e", "english1", "en_US", "en-", "-en", "en--US", "pt-BRAZILIAN9", "en US", "x-private1"]),
    "pointType": (["1,2", "-1.5,2.5", ".5,-.5", "1e3,2E-2", "0,0"],
                  ["1", "1,", ",2", "1;2", "1 ,2", "1,2,3", "--1,2", "a,b", "1e,2", "3.,4"]),
    "relativeLength": (["50%", "-12.5vw", "100vh", "0vmin", ".5vmax", "5.%"], ["50", "%", "50px", "5 %", "--5%", "1e2%", "5VW"]),
    "positiveRelativeLength": (["50%", "0.5vw", "10vh", "100vmin", ".01vmax", "007%", "1.vw"],
                               ["0%", "0.0vw", "00vh", "-5%", ".%", "50", "0.vw"]),
    "colorType": (["#ff00aa", "#FF00AA80", "#abcdef", "1,0.5,0", "0,0,0,1", ".5,.5,.5", "1.00,0,0", "var(--brand-1)",
                   "var(--A_b)"],
                  ["#fff", "#ffff", "#ff00a", "#ff00aaa", "#gggggg", "1,2,3", "0.5,0.5", "1,1,1,1,1", "2,0,0", "var(brand)",
                   "var(--)", "var(--a b)", "red", "1.5,0,0", "0,0,0,"]),
    "paintRefType": (["url(#grad1)", "url(#_a.b-c)", "url(#G)"], ["url(grad)", "url(#1a)", "url(#)", "url(#a b)", "url(#a", "#a"]),
    "geoPointsType": (["1,2 3,4", "  -10.5,20 30,-40e1 5,6  ", "0,0\t1,1\n2,2", "+1,+2 +3,+4"],
                      ["1,2", "1,2 3", "1 2 3 4", "a,b c,d", "1,2;3,4", "", "1,2 3,4,5", "x"]),
    "name": (["a", "A-b_c9", "0", "-", "_"], ["", "a b", "a.b", "a/b", "é", "a:b"]),
    "volumeChannelType": (["a", "R.0", "chan-1_x", "x" * 64], ["", "x" * 65, "a b", "a/b", "é", "a:b"]),
    "volumeSequencePatternType": (["frame_%04d.png", "dir/f%d.exr", "img#.png", "a##b", "%d", "#", "x%3d"],
                                  ["frame.png", "frame_%04.png", "frame_%x.png", "", "a\nb%d", "%d\n"]),
}


class TestRealSchemaPatterns:
    def test_fourteen_patterns_present(self) -> None:
        assert len(_real_patterns()) == 14

    def test_every_pattern_translates_and_compiles(self) -> None:
        for name, rx in _real_patterns():
            re.compile(translate_pattern(rx))

    def test_each_has_examples(self) -> None:
        names = {n for n, _ in _real_patterns()}
        assert names <= set(REAL_EXAMPLES), names - set(REAL_EXAMPLES)

    @pytest.mark.parametrize("name,rx", _real_patterns())
    def test_examples(self, name: str, rx: str) -> None:
        good, bad = REAL_EXAMPLES[name]
        for g in good:
            assert full(rx, g), (name, g)
        for b in bad:
            assert not full(rx, b), (name, b)

    def test_documented_examples(self) -> None:
        by = dict(_real_patterns())
        # xs:documentation of colorType: "1,0.5,0,1"
        assert full(by["colorType"], "1,0.5,0,1")
        # pointType: "x,y" pair
        assert full(by["pointType"], "10,20")
        # geoPointsType: "lon,lat lon,lat ..." at least two points
        assert full(by["geoPointsType"], "-46.6,-23.5 -43.2,-22.9")
        assert not full(by["geoPointsType"], "-46.6,-23.5")


# ---------------------------------------------------------------------------------------------------- real schema

def _spec_of(t: Any) -> dict[str, Any]:
    """Convert a schemadoc SimpleType into the generated spec-dict shape (C5)."""
    if t.kind == "restriction":
        base = t.base if t.base else _spec_of(t.inline[0])
        return spec(base=base, enums=tuple(v for v, _ in t.enums), facets=tuple(t.facets))
    if t.kind == "list":
        item = t.base if t.base else _spec_of(t.inline[0])
        return spec(kind="list", item=item, facets=tuple(t.facets))
    members = tuple(t.members) + tuple(_spec_of(i) for i in t.inline)
    return spec(kind="union", members=members, facets=tuple(t.facets))


@pytest.fixture(scope="module")
def schema() -> Any:
    from sr_core.schemadoc.model import read
    return read(XSD.read_bytes(), None)


@pytest.fixture(scope="module")
def table(schema: Any) -> Table:
    return {name: _spec_of(t) for name, t in schema.simple.items()}


def _non_member(codec: Codec) -> str:
    assert codec.literals
    used = set(codec.literals)
    candidate = "zz-not-a-member"
    try:
        numbers = [int(x) for x in codec.literals]
        candidate = str(max(numbers) + 101)
    except ValueError:
        pass
    assert candidate not in used
    return candidate


class TestRealSchema:
    def test_all_67_simple_types_get_a_codec(self, schema: Any, table: Table) -> None:
        assert len(schema.simple) == 67
        for name in schema.simple:
            c = codec_for(name, table)
            assert c.xsd_type == name
            assert codec_for(name, table) is c

    def test_enumeration_literals_validate_and_non_members_are_refused(self, table: Table) -> None:
        enum_types = 0
        for name, s in table.items():
            if not s["enums"]:
                continue
            enum_types += 1
            c = codec_for(name, table)
            assert c.literals == tuple(s["enums"]), name
            for lit in c.literals:
                assert c.is_valid_lexical(lit), (name, lit)
                v = c.parse(lit)
                assert c.validate(v) == lit, (name, lit)
            bad = _non_member(c)
            assert not c.is_valid_lexical(bad), (name, bad)
            with pytest.raises(SchemaValueError):
                c.parse(bad)
        assert enum_types == 23

    def test_attribute_types_all_resolve(self, schema: Any, table: Table) -> None:
        inline = 0
        seen_builtins: set[str] = set()
        for ct in schema.complex.values():
            for a in ct.attributes:
                if a.inline is not None:
                    inline += 1
                    c = codec_for(_spec_of(a.inline), table)
                    for lit in c.literals or ():
                        assert c.is_valid_lexical(lit), (ct.key, a.name, lit)
                        assert c.validate(c.parse(lit)) == lit
                    if c.literals:
                        assert not c.is_valid_lexical(_non_member(c))
                else:
                    assert a.type
                    c = codec_for(a.type, table)
                    if a.type.startswith("xs:"):
                        seen_builtins.add(a.type)
                    # default and fixed values are lexical forms that the codec must accept
                    for lex in (a.default, a.fixed):
                        if lex is not None:
                            assert c.is_valid_lexical(lex), (ct.key, a.name, lex)
        assert inline == 350
        assert {"xs:double", "xs:string", "xs:positiveInteger", "xs:boolean", "xs:IDREF", "xs:ID", "xs:anyURI",
                "xs:nonNegativeInteger", "xs:IDREFS", "xs:unsignedLong", "xs:NMTOKEN", "xs:NCName", "xs:integer",
                "xs:decimal", "xs:int", "xs:dateTime", "xs:NMTOKENS"} == seen_builtins

    def test_inline_attribute_defaults_and_fixed_values_are_valid(self, schema: Any, table: Table) -> None:
        for ct in schema.complex.values():
            for a in ct.attributes:
                if a.inline is None:
                    continue
                c = codec_for(_spec_of(a.inline), table)
                for lex in (a.default, a.fixed):
                    if lex is not None:
                        assert c.is_valid_lexical(lex), (ct.key, a.name, lex)

    def test_spot_checks(self, table: Table) -> None:
        unit = codec_for("unitDecimal", table)
        assert unit.validate(0.25) == "0.25"
        refused(unit, 1.5)
        triple = codec_for("unitTripleType", table)
        assert triple.validate([0, 0.5, 1]) == "0 0.5 1"
        refused(triple, [0, 0.5])
        length = codec_for("lengthType", table)
        assert length.validate(12) == "12"
        assert length.validate("50%") == "50%"
        refused(length, "50px")
        color = codec_for("colorType", table)
        assert color.validate("#ff00aa") == "#ff00aa"
        refused(color, "#fff")
        pts = codec_for("pointListType", table)
        assert pts.validate(["0,0", "1,2.5"]) == "0,0 1,2.5"
        refused(pts, ["0,0", "x"])
