"""One typed error for a name the schema does not have, with suggestions (SREP 0, section 9)."""
from __future__ import annotations

import copy
import pickle

import pytest

from sr_core.scene import (Composition, Layer, Scene, Still, UnknownNameError, SchemaValueError, default_of)


def test_the_error_is_both_a_schema_value_error_and_an_attribute_error() -> None:
    assert issubclass(UnknownNameError, SchemaValueError)
    assert issubclass(UnknownNameError, AttributeError)


def test_setting_an_unknown_attribute_suggests_the_right_one() -> None:
    layer = Layer(id="l")
    with pytest.raises(UnknownNameError) as info:
        layer.blendMode = "x"  # type: ignore[attr-defined]
    err = info.value
    assert err.name == "blendMode"
    assert err.element == "layer"
    assert err.suggestions[0] == "blend"
    assert "blend" in err.allowed and "opacity" in err.allowed
    assert str(err).startswith("<layer> has no attribute 'blendMode'; did you mean 'blend'? (allowed: id, name, ")
    assert not str(err).startswith("/")  # no path prefix in front of the message


def test_constructor_keyword_error() -> None:
    with pytest.raises(UnknownNameError) as info:
        Layer(id="l", opacty=0.5)  # type: ignore[call-arg]
    assert info.value.suggestions[0] == "opacity"
    assert "did you mean 'opacity'?" in str(info.value)


def test_no_close_match_gives_no_did_you_mean() -> None:
    with pytest.raises(UnknownNameError) as info:
        Layer(id="l", zzzzzzzz=1)  # type: ignore[call-arg]
    assert info.value.suggestions == ()
    assert "did you mean" not in str(info.value)
    assert "(allowed: " in str(info.value)


def test_case_insensitive_suggestion() -> None:
    with pytest.raises(UnknownNameError) as info:
        Layer(id="l", Opacity=1)  # type: ignore[call-arg]
    assert info.value.suggestions[0] == "opacity"
    with pytest.raises(UnknownNameError) as info:
        Layer(id="l", SCALEX=1)  # type: ignore[call-arg]
    assert info.value.suggestions[0] == "scaleX"


def test_from_maps_to_from_underscore() -> None:
    from sr_core.scene import CLASSES
    from sr_core.scene._runtime import Attr

    host = next(c for c in CLASSES.values() if any(isinstance(v, Attr) and v.name == "from_" for v in vars(c).values()))
    with pytest.raises(UnknownNameError) as info:
        host(**{"from": "x"})
    assert info.value.suggestions[0] == "from_"
    obj = host()
    with pytest.raises(UnknownNameError) as info:
        setattr(obj, "from", "x")
    assert info.value.suggestions[0] == "from_"


def test_hasattr_and_getattr_default_stay_false() -> None:
    layer = Layer(id="l")
    assert hasattr(layer, "nope") is False
    assert getattr(layer, "nope", 7) == 7
    assert hasattr(layer, "opacity") is True
    with pytest.raises(AttributeError):
        layer.nope  # noqa: B018


def test_reading_an_unknown_attribute_raises_the_typed_error() -> None:
    layer = Layer(id="l")
    with pytest.raises(UnknownNameError) as info:
        layer.opacty  # noqa: B018
    assert info.value.suggestions[0] == "opacity"
    assert str(info.value).startswith("<layer> has no attribute 'opacty'; did you mean 'opacity'?")


def test_unknown_add_method_suggests_the_method() -> None:
    comp = Composition()
    with pytest.raises(UnknownNameError) as info:
        comp.add_layr(id="x")  # type: ignore[attr-defined]
    assert info.value.suggestions[0] == "add_layer"
    assert str(info.value).startswith("<composition> has no method 'add_layr'; did you mean 'add_layer'?")
    assert hasattr(comp, "add_layr") is False


def test_read_only_members_keep_their_own_error() -> None:
    layer = Layer(id="l")
    with pytest.raises(AttributeError) as info:
        layer.xml_name = "x"  # type: ignore[misc]
    assert not isinstance(info.value, UnknownNameError)


def test_child_not_allowed_suggests_names() -> None:
    comp = Composition()
    with pytest.raises(UnknownNameError) as info:
        comp.add(Scene())  # a <scene> in a <composition>
    err = info.value
    assert err.name == "scene" and err.element == "composition"
    assert "layer" in err.allowed


def test_add_child_typo_via_the_generic_path() -> None:
    from sr_core.scene import Unknown

    comp = Composition()
    with pytest.raises(UnknownNameError) as info:
        comp._slot_for("layr", None)
    assert info.value.suggestions[0] == "layer"
    assert "<layr> is not allowed in <composition>; did you mean 'layer'?" in str(info.value)
    assert Unknown("layr")  # the Unknown element itself is unaffected


def test_xml_name_choice_of_a_multi_name_class() -> None:
    with pytest.raises(UnknownNameError) as info:
        Still(xml_name="postr")
    assert info.value.suggestions[0] == "poster"
    assert info.value.allowed == ("poster", "thumbnail")


def test_default_of_unknown_name() -> None:
    layer = Layer(id="l")
    with pytest.raises(UnknownNameError) as info:
        default_of(layer, "opacty")
    assert info.value.suggestions[0] == "opacity"


def test_valid_use_is_unchanged_and_copies_and_pickles_work() -> None:
    layer = Layer(id="l", opacity=0.5)
    layer.blend = "multiply"
    assert layer.opacity == 0.5
    clone = copy.deepcopy(layer)
    assert clone.attributes() == layer.attributes() and clone is not layer
    again = pickle.loads(pickle.dumps(layer))
    assert again.attributes() == layer.attributes()


def test_scene_version_auto_still_sets() -> None:
    scene = Scene(version="auto")
    assert scene.attributes()["version"] == "auto"
    scene.version = "1.1"
    with pytest.raises(UnknownNameError):
        scene.vrsion = "1.1"  # type: ignore[attr-defined]


def test_no_measurable_cost_on_valid_sets() -> None:
    import timeit

    layer = Layer(id="l")
    per_set = min(timeit.repeat(lambda: setattr(layer, "opacity", 0.5), number=20000, repeat=5)) / 20000
    assert per_set < 20e-6  # microseconds, a very loose ceiling; the growth-ratio tests guard the rest
