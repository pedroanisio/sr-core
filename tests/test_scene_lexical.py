"""Lexical forms set as str (SREP 0 section 3.5): a valid lexical form of a non-string type is stored verbatim."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from sr_core.scene import Project, Scene, SchemaValueError, read, to_bytes
from sr_core.scene.values import codec_for


def project(**attrs: Any) -> Project:
    scene = Scene(version="auto")
    return scene.add_project(**attrs)


class TestCodecs:
    @pytest.mark.parametrize("spec,text,parsed", [
        ("xs:double", "0.3000", 0.3), ("xs:double", "1e3", 1000.0), ("xs:double", "16.000000", 16.0),
        ("xs:integer", "007", 7), ("xs:positiveInteger", "+12", 12), ("xs:int", "-5", -5),
        ("xs:unsignedLong", "00", 0), ("xs:boolean", "1", True), ("xs:boolean", "false", False),
        ("xs:decimal", "0.5000", Decimal("0.5")),
    ])
    def test_valid_str_is_returned_verbatim(self, spec: str, text: str, parsed: Any) -> None:
        codec = codec_for(spec, {})
        assert codec.validate(text) == text
        assert codec.parse(text) == parsed

    @pytest.mark.parametrize("spec,text", [
        ("xs:double", "abc"), ("xs:double", ""), ("xs:integer", "1.0"), ("xs:positiveInteger", "0"),
        ("xs:int", "2147483648"), ("xs:boolean", "yes"), ("xs:decimal", "1e3"),
    ])
    def test_invalid_str_is_refused(self, spec: str, text: str) -> None:
        with pytest.raises(SchemaValueError):
            codec_for(spec, {}).validate(text)

    def test_facets_are_checked_on_str(self) -> None:
        codec = codec_for({"kind": "restriction", "base": "xs:double", "enums": (), "members": (), "item": None,
                           "facets": (("minInclusive", "0"), ("maxInclusive", "720"))}, {})
        assert codec.validate("360.000") == "360.000"
        for bad in ("721.0", "-0.5"):
            with pytest.raises(SchemaValueError):
                codec.validate(bad)

    def test_native_values_are_unchanged(self) -> None:
        assert codec_for("xs:double", {}).validate(0.3) == "0.3"
        assert codec_for("xs:positiveInteger", {}).validate(7) == "7"
        assert codec_for("xs:boolean", {}).validate(True) == "true"
        with pytest.raises(SchemaValueError):
            codec_for("xs:positiveInteger", {}).validate(7.0)


class TestAttributes:
    def test_double_str_stored_and_written_verbatim(self) -> None:
        p = project(width=10, height=10)
        p.shutterPhase = "0.3000"
        assert p.shutterPhase == 0.3
        assert b'shutterPhase="0.3000"' in to_bytes(p.owner or p)

    def test_getter_matches_a_read_file(self) -> None:
        p = project(width="0010", height=10, motionBlur="1", shutterAngle="180.00")
        data = to_bytes(p.owner)
        again = read(data).find("project")
        for name in ("width", "motionBlur", "shutterAngle"):
            assert getattr(p, name) == getattr(again, name)
            assert p._attrs[name] == again._attrs[name]
        assert p.width == 10 and p.motionBlur is True and p.shutterAngle == 180.0

    def test_attribute_facet_failure_has_context(self) -> None:
        p = project(width=10, height=10)
        with pytest.raises(SchemaValueError) as info:
            p.shutterAngle = "900.0"
        assert info.value.attribute == "shutterAngle"
        assert p.shutterAngle is None

    def test_native_float_still_shortest(self) -> None:
        p = project(width=10, height=10, shutterPhase=0.30)
        assert p._attrs["shutterPhase"] == "0.3"

    def test_string_typed_attribute_is_unchanged(self) -> None:
        p = project(width=10, height=10, quality="final")
        assert p.quality == "final"
        with pytest.raises(SchemaValueError):
            p.quality = "nope"
