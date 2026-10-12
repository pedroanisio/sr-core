"""layout="indent": the indentation rule of libxml2 (what ``lxml.etree.tostring(pretty_print=True)`` applies).

An element none of whose children is a text node gets one child per line, 2 spaces per level; an element with a text
node (white space included) is written as stored, with everything below it.
"""
from __future__ import annotations

import random

import pytest

from sr_core.scene import Scene, read, to_bytes, write

DECL = b'<?xml version="1.0" encoding="UTF-8"?>\n'


def indent(xml: bytes | str) -> bytes:
    data = xml.encode() if isinstance(xml, str) else xml
    return to_bytes(read(data), layout="indent")


class TestRule:
    def test_elements_without_text_are_indented(self) -> None:
        assert indent("<a><b/><c><d/></c></a>") == DECL + b"<a>\n  <b/>\n  <c>\n    <d/>\n  </c>\n</a>\n"

    def test_text_child_keeps_the_element_and_its_subtree_as_stored(self) -> None:
        assert indent("<a><b><c/></b>x<d><e/></d></a>") == DECL + b"<a><b><c/></b>x<d><e/></d></a>\n"

    def test_siblings_of_a_text_element_are_still_indented(self) -> None:
        assert indent("<a><b/><c><d/>t</c><e> </e></a>") == DECL + b"<a>\n  <b/>\n  <c><d/>t</c>\n  <e> </e>\n</a>\n"

    def test_whitespace_text_counts_as_text(self) -> None:
        assert indent("<a>\n<b><c/></b>\n</a>") == DECL + b"<a>\n<b><c/></b>\n</a>\n"

    def test_comments_and_pis_are_indented_like_elements(self) -> None:
        assert indent("<a><f><!--c--><?p x?></f></a>") == (
            DECL + b"<a>\n  <f>\n    <!--c-->\n    <?p x?>\n  </f>\n</a>\n")

    def test_prolog_and_epilog_one_per_line(self) -> None:
        assert indent("<!--pre--><?pi d?><a><b/></a><!--post-->") == (
            DECL + b"<!--pre-->\n<?pi d?>\n<a>\n  <b/>\n</a>\n<!--post-->\n")

    def test_empty_root(self) -> None:
        assert indent("<a/>") == DECL + b"<a/>\n"
        assert indent("<a></a>") == DECL + b"<a/>\n"

    def test_text_root_is_unchanged(self) -> None:
        assert indent("<a>x</a>") == DECL + b"<a>x</a>\n"

    def test_deeper_than_the_recursion_limit(self) -> None:
        depth = 3000
        out = indent("<a>" * depth + "</a>" * depth)
        assert out.count(b"\n") == 2 * depth

    def test_indent_is_idempotent(self) -> None:
        once = indent("<a><b><c/></b>x<d><e/></d><f><g/></f></a>")
        assert indent(once) == once

    def test_unknown_layout_is_refused(self) -> None:
        with pytest.raises(ValueError, match="indent"):
            to_bytes(Scene(version="auto"), layout="tidy")  # type: ignore[arg-type]


class TestBuilt:
    def test_built_scene_is_indented_and_copied_subtree_is_not(self) -> None:
        scene = Scene(version="1.7")
        scene.add_project(width=10, height=10, fps="30", duration="1")
        kit = read(b"<scene version=\"1.7\">\n  <styles>\n  <s id=\"x\"/>\n</styles>\n</scene>")
        scene.add(kit.find("styles").copy())
        out = to_bytes(scene, layout="indent")
        assert out.startswith(DECL + b'<scene version="1.7">\n  <project ')
        assert out.endswith(b"\n  <styles>\n  <s id=\"x\"/>\n</styles>\n</scene>\n")

    def test_write_to_a_path(self, tmp_path) -> None:
        target = tmp_path / "s.xml"
        scene = Scene(version="1.7")
        write(scene, target, layout="indent")
        assert target.read_bytes() == DECL + b'<scene version="1.7"/>\n'


def random_document(rng: random.Random):
    """A random lxml tree: text, tails, comments, PIs, empty elements, siblings of the root."""
    from lxml import etree

    names = ["a", "b", "c", "d", "e"]

    def fill(parent, level: int) -> None:
        for _ in range(rng.randint(0, 4)):
            kind = rng.random()
            if kind < 0.6 and level < 5:
                child = etree.SubElement(parent, rng.choice(names), {"k": str(rng.randint(0, 9))})
                if rng.random() < 0.2:
                    child.text = rng.choice(["t", " ", "\n  ", "x y"])
                fill(child, level + 1)
                if rng.random() < 0.2:
                    child.tail = rng.choice(["t", " ", "\n"])
            elif kind < 0.8:
                parent.append(etree.Comment(rng.choice(["c", " note "])))
            else:
                parent.append(etree.ProcessingInstruction("p", rng.choice(["x", "a=b"])))

    root = etree.Element("scene", {"version": "1.0"})
    fill(root, 0)
    if rng.random() < 0.3:
        root.text = "r"
    for _ in range(rng.randint(0, 2)):
        root.addprevious(etree.Comment("before"))
    for _ in range(rng.randint(0, 2)):
        root.addnext(etree.ProcessingInstruction("after", "d"))
    return root


class TestDifferential:
    def test_matches_lxml_pretty_print_on_random_trees(self) -> None:
        etree = pytest.importorskip("lxml.etree")
        rng = random.Random(20261012)
        for case in range(400):
            root = random_document(rng)
            tree = root.getroottree()
            compact = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
            expected = etree.tostring(tree, pretty_print=True, xml_declaration=True, encoding="UTF-8")
            expected = expected.replace(b"<?xml version='1.0' encoding='UTF-8'?>", DECL.rstrip(b"\n"), 1)
            assert indent(compact) == expected, (case, compact)

    def test_matches_lxml_on_fixed_cases(self) -> None:
        etree = pytest.importorskip("lxml.etree")
        cases = [
            "<a><b/><c><d/>t</c><e> </e><f><!--c--><?p x?></f></a>",
            "<a>\n<b><c/></b>\n</a>",
            "<a><b><c/></b>x<d><e/></d></a>",
            "<!--pre--><?pi d?><a><b/></a><!--post-->",
            "<a>\n  <b>\n    <c/>\n  </b>\n</a>",
            "<a><b>\n  <c/>\n</b><d><e/></d></a>",
        ]
        for xml in cases:
            expected = etree.tostring(etree.fromstring(xml).getroottree(), pretty_print=True, xml_declaration=True,
                                      encoding="UTF-8")
            expected = expected.replace(b"<?xml version='1.0' encoding='UTF-8'?>", DECL.rstrip(b"\n"), 1)
            if xml.startswith("<!--"):
                tree = etree.ElementTree(etree.fromstring(xml[xml.index("<a>"):xml.index("</a>") + 4]))
                tree.getroot().addprevious(etree.Comment("pre"))
                tree.getroot().addprevious(etree.ProcessingInstruction("pi", "d"))
                tree.getroot().addnext(etree.Comment("post"))
                expected = etree.tostring(tree, pretty_print=True, xml_declaration=True, encoding="UTF-8")
                expected = expected.replace(b"<?xml version='1.0' encoding='UTF-8'?>", DECL.rstrip(b"\n"), 1)
            assert indent(xml) == expected, xml
