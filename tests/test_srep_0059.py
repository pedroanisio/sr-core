"""SREP 59: ID references are checked by every validator: R53 (an IDREFS list names at least one id) and R54 (an
audiogram's source names an audioTrack of audioMix), pattern p77. lxml's XSD processor skips the IDREF table and the
IDREFS minLength (the reason for the SREP), so these documents reach the Schematron.
"""
import os

import pytest

from test_schema_rules import ROOT, verdict

HEAD = '<scene version="1.2"><project width="64" height="64" fps="24" duration="1"/>'


def audiogram(source):
    return (HEAD + f'<assets><audio id="a" src="a.wav"/><audiogram id="g" source="{source}" width="32" height="16"/>'
            '</assets><composition><shape id="s" shape="rect" width="10" height="10"/></composition>'
            '<audioMix><audioTrack id="t" asset="a"/></audioMix></scene>').encode()


def test_an_empty_idrefs_list_fails_r53():
    doc = (HEAD + '<composition><shape id="s" shape="rect" width="10" height="10" effects=" "/></composition></scene>')
    assert verdict(doc.encode()) == "sch:R53"


@pytest.mark.parametrize("attr", ["audioBuses", "audioTracks", "captions", "colliders", "duckUnder", "effects", "fit",
                                  "forceFields", "lights", "looks", "splash"])
def test_r53_covers_every_idrefs_attribute_name(attr):
    sch = open(os.path.join(ROOT, "schema", "scene-render.sch")).read()
    assert f"@{attr}" in sch.split('id="p77"')[1].split("</sch:pattern>")[0]


def test_r54_audiogram_source():
    assert verdict(audiogram("t")) == "ok"
    assert verdict(audiogram("s")) == "sch:R54"
    assert verdict(audiogram("nowhere")) == "sch:R54"


@pytest.mark.parametrize("name,codes", [("srep-0059-empty-idrefs", "sch:R53"), ("srep-0059-audiogram-source", "sch:R54"),
                                        ("srep-0059-identity", "ok")])
def test_cases(name, codes):
    # the identity case is an XSD identity error that lxml does not check: it validates here and fails in validators
    # that make the check (the Rust reference: S10)
    path = os.path.join(ROOT, "conformance", "cases", name + ".xml")
    assert verdict(open(path, "rb").read()) == codes
