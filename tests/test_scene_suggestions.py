"""Suggestions for a near-miss enumeration value and for a mistyped class name (SREP 91, section 3.12)."""
from __future__ import annotations

import pickle
import time

import pytest

import sr_core.scene as S
from sr_core.scene import DensityTonemap, Layer, Output, SchemaValueError, UnknownNameError


def test_a_near_miss_enumeration_value_says_what_was_meant() -> None:
    layer = Layer(id="l")
    with pytest.raises(SchemaValueError) as info:
        layer.blend = "mutliply"  # type: ignore[assignment]
    err = info.value
    assert err.suggestions == ("multiply",)
    assert "'mutliply' is not one of 'normal'" in str(err)  # the message that was there stays
    assert "did you mean 'multiply'?" in str(err)
    assert str(err).startswith("/layer/@blend: ")
    assert err.attribute == "blend" and err.xsd_type == "blendType"


def test_a_value_in_the_wrong_case_is_suggested_first() -> None:
    with pytest.raises(SchemaValueError) as info:
        Layer(id="l", blend="Multiply")  # type: ignore[arg-type]
    assert info.value.suggestions[0] == "multiply"


def test_no_close_value_gives_no_hint_and_the_old_message() -> None:
    with pytest.raises(SchemaValueError) as info:
        Layer(id="l", blend="zzzzzzzz")  # type: ignore[arg-type]
    assert info.value.suggestions == ()
    assert "did you mean" not in str(info.value)
    assert "'zzzzzzzz' is not one of 'normal'" in str(info.value)


def test_a_list_of_enumeration_values_names_the_item_and_the_suggestion() -> None:
    out = Output(id="o")
    with pytest.raises(SchemaValueError) as info:
        out.audioRoles = ["dialogue", "musik"]  # type: ignore[list-item]
    assert info.value.suggestions == ("music",)
    assert "item 1: 'musik' is not one of 'dialogue'" in str(info.value)
    assert "did you mean 'music'?" in str(info.value)
    with pytest.raises(SchemaValueError) as info2:
        out.audioRoles = "dialogue voiceovr"  # the lexical form is checked the same way
    assert info2.value.suggestions == ("voiceover",)


def test_a_union_with_an_enumeration_member_carries_its_suggestion() -> None:
    node = DensityTonemap(id="d") if "id" in DensityTonemap.__dict__ else DensityTonemap()
    with pytest.raises(SchemaValueError) as info:
        node.reference = "mx"  # type: ignore[assignment]
    assert info.value.suggestions == ("max",)
    assert "fits no member type" in str(info.value)
    assert "did you mean 'max'?" in str(info.value)


def test_non_enumeration_failures_are_unchanged() -> None:
    layer = Layer(id="l")
    with pytest.raises(SchemaValueError) as info:
        layer.opacity = 2  # type: ignore[assignment]
    assert info.value.suggestions == ()
    assert "did you mean" not in str(info.value)
    assert str(info.value).startswith("/layer/@opacity: 2 violates maxInclusive")


def test_the_suggestions_survive_pickle_and_the_unknown_name_error_is_unchanged() -> None:
    with pytest.raises(SchemaValueError) as info:
        Layer(id="l", blend="mutliply")  # type: ignore[arg-type]
    again = pickle.loads(pickle.dumps(info.value))
    assert again.suggestions == ("multiply",) and str(again) == str(info.value)
    with pytest.raises(UnknownNameError) as unknown:
        Layer(id="l", opacty=1)  # type: ignore[call-arg]
    assert str(unknown.value).count("did you mean") == 1


def test_a_valid_set_does_no_suggestion_work(monkeypatch: pytest.MonkeyPatch) -> None:
    import sr_core.scene.errors as errors

    def boom(*a: object, **k: object) -> tuple[str, ...]:
        raise AssertionError("suggest() ran on a valid value")

    monkeypatch.setattr(errors, "suggest", boom)
    layer = Layer(id="l")
    layer.blend = "multiply"
    layer.opacity = 0.5
    Output(id="o").audioRoles = ["music", "dialogue"]


def test_a_valid_enumeration_set_scales_linearly() -> None:
    def cost(n: int) -> float:
        layer = Layer(id="l")
        t = time.perf_counter()
        for _ in range(n):
            layer.blend = "multiply"
        return time.perf_counter() - t

    cost(2000)
    small, big = min(cost(4000) for _ in range(3)), min(cost(40000) for _ in range(3))
    assert big / small < 25  # ten times the work: linear is 10


# ------------------------------------------------------------------------------------------------ class names

def test_a_mistyped_class_name_says_what_was_meant() -> None:
    with pytest.raises(UnknownNameError) as info:
        S.Layr  # noqa: B018
    err = info.value
    assert isinstance(err, AttributeError)
    assert err.kind == "class" and err.name == "Layr"
    assert err.suggestions[0] == "Layer"
    assert "did you mean 'Layer'?" in str(err)
    assert str(err).startswith("module 'sr_core.scene' has no class 'Layr'; did you mean 'Layer'? (allowed: ")


def test_an_element_name_maps_to_its_class() -> None:
    with pytest.raises(UnknownNameError) as info:
        S.textanimator  # noqa: B018
    assert info.value.suggestions[0] == "TextAnimator"
    with pytest.raises(UnknownNameError) as info2:
        S.layer  # noqa: B018
    assert info2.value.suggestions[0] == "Layer"


def test_hasattr_and_getattr_default_still_work() -> None:
    assert not hasattr(S, "Layr")
    assert getattr(S, "Nope", 7) == 7
    assert hasattr(S, "Layer")


def test_from_import_of_a_missing_name_is_still_an_import_error() -> None:
    with pytest.raises(ImportError):
        exec("from sr_core.scene import Nope")
    with pytest.raises(ImportError) as info:
        exec("from sr_core.scene import Layr")
    assert "Layr" in str(info.value)


def test_dunder_probes_stay_plain_attribute_errors() -> None:
    with pytest.raises(AttributeError) as info:
        S.__wrapped__  # noqa: B018
    assert not isinstance(info.value, UnknownNameError)
