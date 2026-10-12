"""Value codecs, number formatting and XSD pattern translation for the scene SDK (SREP 91, sections 3.5, 3.6, 4.3).

A :class:`Codec` knows one XSD simple type. It turns a Python value into the lexical form that is stored
(``validate``), reads a lexical form into a Python value (``parse``) and answers whether a lexical form is valid
(``is_valid_lexical``). The XSD 1.0 lexical and value spaces are followed (W3C XML Schema Part 2, Datatypes).

``codec_for(spec, simple_table)`` builds codecs from a builtin name (``"xs:double"``), a named simple type found in
``simple_table``, or an inline spec dict. A spec dict has the keys of the generated ``SIMPLE_TYPES`` entries:

``kind``
    ``"restriction"``, ``"list"`` or ``"union"``.
``base``
    restriction base: a builtin name, a named type, or a nested spec dict.
``enums``
    enumeration literals (plain strings, or ``(literal, documentation)`` pairs).
``facets``
    ``(facet, value)`` pairs: length, minLength, maxLength, pattern, minInclusive, maxInclusive, minExclusive,
    maxExclusive.
``members``
    union member types, in order (names or nested spec dicts).
``item``
    list item type (a name or a nested spec dict).

Python values accepted (SREP 3.5): ``bool`` is never an integer or a double; ``str`` is accepted for ``xs:decimal``
when it is lexically valid; ``xs:double`` takes ``int`` and ``float``; ``xs:IDREF`` takes a string or any object whose
``id`` attribute is a truthy string.

Parsed values: ``xs:double`` gives ``float``, ``xs:decimal`` gives ``decimal.Decimal`` (exact), the integer types
give ``int``, ``xs:boolean`` gives ``bool``, ``xs:dateTime`` gives ``datetime.datetime`` (fractions of a second
beyond microseconds are truncated), strings give ``str``, lists give ``list``.

Names (Name, NCName, NMTOKEN) follow the character classes of XML 1.0 Second Edition Appendix B, which XML Schema
1.0 Second Edition references normatively and libxml2 implements (see ``NAME_START_RANGES``).
"""

from __future__ import annotations

import datetime as _dt
import functools
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from sr_core.scene.errors import SchemaError, SchemaValueError

__all__ = ["Codec", "codec_for", "fmt_decimal", "fmt_double", "translate_pattern"]

_WS = "[ \t\n\r]"
_WS_RUN = re.compile(_WS + "+")


def _collapse(s: str) -> str:
    """XSD whiteSpace=collapse: tab, LF and CR become spaces, runs collapse, ends are trimmed (not NBSP etc.)."""
    return _WS_RUN.sub(" ", s).strip(" ")


def _split(s: str) -> list[str]:
    n = _collapse(s)
    return n.split(" ") if n else []


# ------------------------------------------------------------------------------------------------ number formatting

def _bad_number(message: str, xsd_type: str | None) -> SchemaValueError:
    return SchemaValueError(message, xsd_type=xsd_type)


def fmt_decimal(x: int | float | Decimal, *, xsd_type: str | None = "xs:decimal") -> str:
    """Positional lexical form of ``x`` (SREP 4.3): shortest round trip for floats, exact for ``Decimal``.

    Never uses an exponent; ``-0`` becomes ``0``; NaN and the infinities raise ``SchemaValueError``.
    """
    if isinstance(x, bool) or not isinstance(x, (int, float, Decimal)):
        raise _bad_number(f"expected a number, got {type(x).__name__}", xsd_type)
    if isinstance(x, Decimal):
        if not x.is_finite():
            raise _bad_number(f"{x} is not a finite number", xsd_type)
        s = format(x, "f")
    elif isinstance(x, int):
        s = str(x)
    else:
        if x != x or x in (float("inf"), float("-inf")):
            raise _bad_number(f"{x!r} is not a finite number; NaN and infinities are refused", xsd_type)
        if x == 0:
            return "0"
        s = format(Decimal(repr(x)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fmt_double(x: int | float, *, xsd_type: str | None = "xs:double") -> str:
    """Lexical form of a double: the shortest positional form that reads back as the same float."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise _bad_number(f"expected int or float, got {type(x).__name__}", xsd_type)
    try:
        f = float(x)
    except OverflowError:
        raise _bad_number("the integer is too large for a double", xsd_type) from None
    return fmt_decimal(f, xsd_type=xsd_type)


# ------------------------------------------------------------------------------------------------ XSD regex

_SINGLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t"}
_SINGLE_CHARS = set("\\|.-^?*+{}()[]")
_UNSUPPORTED_ESCAPES = {
    "i": "name-start character class", "I": "name-start character class", "c": "name character class",
    "C": "name character class", "p": "Unicode category or block", "P": "Unicode category or block",
}
_QUANT_RE = re.compile(r"\{([0-9]+)(?:(,)([0-9]*))?\}")
_XSD_SPACE = "\\x20\\t\\n\\r"
_NOT_XSD_SPACE = "\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x21-\\U0010ffff"


def _cp(code: int) -> str:
    return "\\U%08x" % code


def _lit(ch: str) -> str:
    """A literal character as Python regex source, safe in and out of a character class."""
    if ch.isascii() and (ch.isalnum() or ch == "_"):
        return ch
    if ch.isascii() and ch.isprintable():
        return "\\" + ch
    return _cp(ord(ch))


@functools.lru_cache(maxsize=1)
def _word_class_bodies() -> tuple[str, str]:
    """Class bodies for the XSD ``\\w`` (everything except Unicode P, Z and C) and its complement."""
    word: list[str] = []
    nonword: list[str] = []
    for target, wanted in ((word, False), (nonword, True)):
        start = -1
        for code in range(0x110000):
            hit = (unicodedata.category(chr(code))[0] in "PZC") is wanted
            if hit and start < 0:
                start = code
            elif not hit and start >= 0:
                target.append(_cp(start) if start == code - 1 else f"{_cp(start)}-{_cp(code - 1)}")
                start = -1
        if start >= 0:
            target.append(f"{_cp(start)}-{_cp(0x10ffff)}")
    return "".join(word), "".join(nonword)


def _multi_escape(c: str, in_class: bool) -> str:
    """Python source for \\d \\D \\s \\S \\w \\W (XSD definitions), as a class member or as an atom."""
    word, nonword = _word_class_bodies() if c in "wW" else ("", "")
    if c in "dD":
        return "\\" + c
    if in_class:
        return {"s": _XSD_SPACE, "S": _NOT_XSD_SPACE, "w": word, "W": nonword}[c]
    return {"s": f"[{_XSD_SPACE}]", "S": f"[^{_XSD_SPACE}]", "w": f"[{word}]", "W": f"[{nonword}]"}[c]


def translate_pattern(xsd_regex: str) -> str:
    """Translate an XSD regular expression into Python ``re`` source, to be used with ``re.fullmatch``.

    XSD patterns are implicitly anchored, have no anchors (``^`` and ``$`` are literal), a ``.`` that excludes
    only CR and LF, and an ``\\s`` that is exactly space, tab, LF and CR. ``\\d`` is Unicode ``Nd`` and ``\\w`` is
    every character except Unicode punctuation, separators and other. Groups never capture.

    Raises ``SchemaError`` on ``\\i \\c \\I \\C \\p{..} \\P{..}``, character class subtraction, lazy or stacked
    quantifiers and anything else outside the subset shared with Python.
    """
    def fail(message: str) -> SchemaError:
        return SchemaError(f"pattern {xsd_regex!r}: {message}")

    out: list[str] = []
    n = len(xsd_regex)
    i = 0
    depth = 0
    quantifiable = False

    def escape(j: int, in_class: bool) -> tuple[str | None, str, int]:
        """Read the escape at ``j`` (a backslash). Returns (single char or None, python source, next index)."""
        if j + 1 >= n:
            raise fail("trailing backslash")
        c = xsd_regex[j + 1]
        if c in _SINGLE_ESCAPES:
            return _SINGLE_ESCAPES[c], _lit(_SINGLE_ESCAPES[c]), j + 2
        if c in _SINGLE_CHARS:
            return c, _lit(c), j + 2
        if c in "dDsSwW":
            return None, _multi_escape(c, in_class), j + 2
        if c in _UNSUPPORTED_ESCAPES:
            raise fail(f"\\{c} ({_UNSUPPORTED_ESCAPES[c]}) is not supported")
        raise fail(f"unknown escape \\{c}")

    def char_class(j: int) -> tuple[str, int]:
        j += 1
        negate = j < n and xsd_regex[j] == "^"
        if negate:
            j += 1
        body: list[str] = []
        while True:
            if j >= n:
                raise fail("unterminated character class")
            c = xsd_regex[j]
            if c == "]":
                if not body:
                    raise fail("empty character class")
                return "[" + ("^" if negate else "") + "".join(body) + "]", j + 1
            if c == "[":
                raise fail("unescaped '[' in a character class (class subtraction is not supported)")
            if c == "-" and xsd_regex.startswith("-[", j):
                raise fail("character class subtraction is not supported")
            if c == "\\":
                lo, src, j = escape(j, True)
            else:
                lo, src, j = c, _lit(c), j + 1
            if (lo is not None and j + 1 < n and xsd_regex[j] == "-" and xsd_regex[j + 1] not in "]["):
                if xsd_regex[j + 1] == "\\":
                    hi, _, j2 = escape(j + 1, True)
                else:
                    hi, j2 = xsd_regex[j + 1], j + 2
                if hi is None:
                    raise fail("a range cannot end in a character class escape")
                if hi < lo:
                    raise fail(f"range {lo!r}-{hi!r} is reversed")
                body.append(f"{_lit(lo)}-{_lit(hi)}")
                j = j2
            elif lo is None and j < n - 1 and xsd_regex[j] == "-" and xsd_regex[j + 1] not in "][":
                raise fail("a range cannot start with a character class escape")
            else:
                body.append(src)

    while i < n:
        c = xsd_regex[i]
        if c == "(":
            out.append("(?:")
            depth += 1
            quantifiable = False
            i += 1
        elif c == ")":
            if depth == 0:
                raise fail("unbalanced ')'")
            depth -= 1
            out.append(")")
            quantifiable = True
            i += 1
        elif c == "|":
            out.append("|")
            quantifiable = False
            i += 1
        elif c == "[":
            src, i = char_class(i)
            out.append(src)
            quantifiable = True
        elif c == "\\":
            _, src, i = escape(i, False)
            out.append(src)
            quantifiable = True
        elif c == ".":
            out.append("[^\\n\\r]")
            quantifiable = True
            i += 1
        elif c in "?*+":
            if not quantifiable:
                raise fail(f"quantifier {c!r} has nothing to repeat (XSD allows one quantifier per atom)")
            out.append(c)
            quantifiable = False
            i += 1
        elif c == "{":
            m = _QUANT_RE.match(xsd_regex, i)
            if not quantifiable or m is None:
                raise fail("invalid '{' (use \\{ for a literal brace)")
            if m.group(2) and m.group(3) and int(m.group(3)) < int(m.group(1)):
                raise fail("quantifier maximum is below its minimum")
            out.append(m.group(0))
            quantifiable = False
            i = m.end()
        elif c == "}":
            raise fail("unescaped '}'")
        else:
            out.append(_lit(c))
            quantifiable = True
            i += 1
    if depth:
        raise fail("unbalanced '('")
    return "".join(out)


@functools.lru_cache(maxsize=None)
def _compile(xsd_regex: str) -> re.Pattern[str]:
    return re.compile(translate_pattern(xsd_regex))


# ------------------------------------------------------------------------------------------------ lexical spaces

# XML 1.0 (Second Edition) Appendix B character classes, which XML Schema 1.0 Second Edition references normatively
# (https://www.w3.org/TR/xmlschema-2/ sections 3.3.4 to 3.3.9) and which libxml2 implements. Generated from the
# productions [84] Letter, [85] BaseChar, [86] Ideographic, [87] CombiningChar, [88] Digit and [89] Extender of
# https://www.w3.org/TR/2000/REC-xml-20001006#CharClasses, as sorted, merged inclusive ranges.
# NAME_START_RANGES: Letter. NAME_CHAR_RANGES: Letter, Digit, CombiningChar, Extender, '.', '-' and '_'.
# NCName (Namespaces in XML 1999): (Letter | '_') NCNameChar*. Name: (Letter | '_' | ':') (NCNameChar | ':')*.
NAME_START_RANGES: tuple[tuple[int, int], ...] = (
    (0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x00D6), (0x00D8, 0x00F6), (0x00F8, 0x0131), (0x0134, 0x013E),
    (0x0141, 0x0148), (0x014A, 0x017E), (0x0180, 0x01C3), (0x01CD, 0x01F0), (0x01F4, 0x01F5), (0x01FA, 0x0217),
    (0x0250, 0x02A8), (0x02BB, 0x02C1), (0x0386, 0x0386), (0x0388, 0x038A), (0x038C, 0x038C), (0x038E, 0x03A1),
    (0x03A3, 0x03CE), (0x03D0, 0x03D6), (0x03DA, 0x03DA), (0x03DC, 0x03DC), (0x03DE, 0x03DE), (0x03E0, 0x03E0),
    (0x03E2, 0x03F3), (0x0401, 0x040C), (0x040E, 0x044F), (0x0451, 0x045C), (0x045E, 0x0481), (0x0490, 0x04C4),
    (0x04C7, 0x04C8), (0x04CB, 0x04CC), (0x04D0, 0x04EB), (0x04EE, 0x04F5), (0x04F8, 0x04F9), (0x0531, 0x0556),
    (0x0559, 0x0559), (0x0561, 0x0586), (0x05D0, 0x05EA), (0x05F0, 0x05F2), (0x0621, 0x063A), (0x0641, 0x064A),
    (0x0671, 0x06B7), (0x06BA, 0x06BE), (0x06C0, 0x06CE), (0x06D0, 0x06D3), (0x06D5, 0x06D5), (0x06E5, 0x06E6),
    (0x0905, 0x0939), (0x093D, 0x093D), (0x0958, 0x0961), (0x0985, 0x098C), (0x098F, 0x0990), (0x0993, 0x09A8),
    (0x09AA, 0x09B0), (0x09B2, 0x09B2), (0x09B6, 0x09B9), (0x09DC, 0x09DD), (0x09DF, 0x09E1), (0x09F0, 0x09F1),
    (0x0A05, 0x0A0A), (0x0A0F, 0x0A10), (0x0A13, 0x0A28), (0x0A2A, 0x0A30), (0x0A32, 0x0A33), (0x0A35, 0x0A36),
    (0x0A38, 0x0A39), (0x0A59, 0x0A5C), (0x0A5E, 0x0A5E), (0x0A72, 0x0A74), (0x0A85, 0x0A8B), (0x0A8D, 0x0A8D),
    (0x0A8F, 0x0A91), (0x0A93, 0x0AA8), (0x0AAA, 0x0AB0), (0x0AB2, 0x0AB3), (0x0AB5, 0x0AB9), (0x0ABD, 0x0ABD),
    (0x0AE0, 0x0AE0), (0x0B05, 0x0B0C), (0x0B0F, 0x0B10), (0x0B13, 0x0B28), (0x0B2A, 0x0B30), (0x0B32, 0x0B33),
    (0x0B36, 0x0B39), (0x0B3D, 0x0B3D), (0x0B5C, 0x0B5D), (0x0B5F, 0x0B61), (0x0B85, 0x0B8A), (0x0B8E, 0x0B90),
    (0x0B92, 0x0B95), (0x0B99, 0x0B9A), (0x0B9C, 0x0B9C), (0x0B9E, 0x0B9F), (0x0BA3, 0x0BA4), (0x0BA8, 0x0BAA),
    (0x0BAE, 0x0BB5), (0x0BB7, 0x0BB9), (0x0C05, 0x0C0C), (0x0C0E, 0x0C10), (0x0C12, 0x0C28), (0x0C2A, 0x0C33),
    (0x0C35, 0x0C39), (0x0C60, 0x0C61), (0x0C85, 0x0C8C), (0x0C8E, 0x0C90), (0x0C92, 0x0CA8), (0x0CAA, 0x0CB3),
    (0x0CB5, 0x0CB9), (0x0CDE, 0x0CDE), (0x0CE0, 0x0CE1), (0x0D05, 0x0D0C), (0x0D0E, 0x0D10), (0x0D12, 0x0D28),
    (0x0D2A, 0x0D39), (0x0D60, 0x0D61), (0x0E01, 0x0E2E), (0x0E30, 0x0E30), (0x0E32, 0x0E33), (0x0E40, 0x0E45),
    (0x0E81, 0x0E82), (0x0E84, 0x0E84), (0x0E87, 0x0E88), (0x0E8A, 0x0E8A), (0x0E8D, 0x0E8D), (0x0E94, 0x0E97),
    (0x0E99, 0x0E9F), (0x0EA1, 0x0EA3), (0x0EA5, 0x0EA5), (0x0EA7, 0x0EA7), (0x0EAA, 0x0EAB), (0x0EAD, 0x0EAE),
    (0x0EB0, 0x0EB0), (0x0EB2, 0x0EB3), (0x0EBD, 0x0EBD), (0x0EC0, 0x0EC4), (0x0F40, 0x0F47), (0x0F49, 0x0F69),
    (0x10A0, 0x10C5), (0x10D0, 0x10F6), (0x1100, 0x1100), (0x1102, 0x1103), (0x1105, 0x1107), (0x1109, 0x1109),
    (0x110B, 0x110C), (0x110E, 0x1112), (0x113C, 0x113C), (0x113E, 0x113E), (0x1140, 0x1140), (0x114C, 0x114C),
    (0x114E, 0x114E), (0x1150, 0x1150), (0x1154, 0x1155), (0x1159, 0x1159), (0x115F, 0x1161), (0x1163, 0x1163),
    (0x1165, 0x1165), (0x1167, 0x1167), (0x1169, 0x1169), (0x116D, 0x116E), (0x1172, 0x1173), (0x1175, 0x1175),
    (0x119E, 0x119E), (0x11A8, 0x11A8), (0x11AB, 0x11AB), (0x11AE, 0x11AF), (0x11B7, 0x11B8), (0x11BA, 0x11BA),
    (0x11BC, 0x11C2), (0x11EB, 0x11EB), (0x11F0, 0x11F0), (0x11F9, 0x11F9), (0x1E00, 0x1E9B), (0x1EA0, 0x1EF9),
    (0x1F00, 0x1F15), (0x1F18, 0x1F1D), (0x1F20, 0x1F45), (0x1F48, 0x1F4D), (0x1F50, 0x1F57), (0x1F59, 0x1F59),
    (0x1F5B, 0x1F5B), (0x1F5D, 0x1F5D), (0x1F5F, 0x1F7D), (0x1F80, 0x1FB4), (0x1FB6, 0x1FBC), (0x1FBE, 0x1FBE),
    (0x1FC2, 0x1FC4), (0x1FC6, 0x1FCC), (0x1FD0, 0x1FD3), (0x1FD6, 0x1FDB), (0x1FE0, 0x1FEC), (0x1FF2, 0x1FF4),
    (0x1FF6, 0x1FFC), (0x2126, 0x2126), (0x212A, 0x212B), (0x212E, 0x212E), (0x2180, 0x2182), (0x3007, 0x3007),
    (0x3021, 0x3029), (0x3041, 0x3094), (0x30A1, 0x30FA), (0x3105, 0x312C), (0x4E00, 0x9FA5), (0xAC00, 0xD7A3),
)
NAME_CHAR_RANGES: tuple[tuple[int, int], ...] = (
    (0x002D, 0x002E), (0x0030, 0x0039), (0x0041, 0x005A), (0x005F, 0x005F), (0x0061, 0x007A), (0x00B7, 0x00B7),
    (0x00C0, 0x00D6), (0x00D8, 0x00F6), (0x00F8, 0x0131), (0x0134, 0x013E), (0x0141, 0x0148), (0x014A, 0x017E),
    (0x0180, 0x01C3), (0x01CD, 0x01F0), (0x01F4, 0x01F5), (0x01FA, 0x0217), (0x0250, 0x02A8), (0x02BB, 0x02C1),
    (0x02D0, 0x02D1), (0x0300, 0x0345), (0x0360, 0x0361), (0x0386, 0x038A), (0x038C, 0x038C), (0x038E, 0x03A1),
    (0x03A3, 0x03CE), (0x03D0, 0x03D6), (0x03DA, 0x03DA), (0x03DC, 0x03DC), (0x03DE, 0x03DE), (0x03E0, 0x03E0),
    (0x03E2, 0x03F3), (0x0401, 0x040C), (0x040E, 0x044F), (0x0451, 0x045C), (0x045E, 0x0481), (0x0483, 0x0486),
    (0x0490, 0x04C4), (0x04C7, 0x04C8), (0x04CB, 0x04CC), (0x04D0, 0x04EB), (0x04EE, 0x04F5), (0x04F8, 0x04F9),
    (0x0531, 0x0556), (0x0559, 0x0559), (0x0561, 0x0586), (0x0591, 0x05A1), (0x05A3, 0x05B9), (0x05BB, 0x05BD),
    (0x05BF, 0x05BF), (0x05C1, 0x05C2), (0x05C4, 0x05C4), (0x05D0, 0x05EA), (0x05F0, 0x05F2), (0x0621, 0x063A),
    (0x0640, 0x0652), (0x0660, 0x0669), (0x0670, 0x06B7), (0x06BA, 0x06BE), (0x06C0, 0x06CE), (0x06D0, 0x06D3),
    (0x06D5, 0x06E8), (0x06EA, 0x06ED), (0x06F0, 0x06F9), (0x0901, 0x0903), (0x0905, 0x0939), (0x093C, 0x094D),
    (0x0951, 0x0954), (0x0958, 0x0963), (0x0966, 0x096F), (0x0981, 0x0983), (0x0985, 0x098C), (0x098F, 0x0990),
    (0x0993, 0x09A8), (0x09AA, 0x09B0), (0x09B2, 0x09B2), (0x09B6, 0x09B9), (0x09BC, 0x09BC), (0x09BE, 0x09C4),
    (0x09C7, 0x09C8), (0x09CB, 0x09CD), (0x09D7, 0x09D7), (0x09DC, 0x09DD), (0x09DF, 0x09E3), (0x09E6, 0x09F1),
    (0x0A02, 0x0A02), (0x0A05, 0x0A0A), (0x0A0F, 0x0A10), (0x0A13, 0x0A28), (0x0A2A, 0x0A30), (0x0A32, 0x0A33),
    (0x0A35, 0x0A36), (0x0A38, 0x0A39), (0x0A3C, 0x0A3C), (0x0A3E, 0x0A42), (0x0A47, 0x0A48), (0x0A4B, 0x0A4D),
    (0x0A59, 0x0A5C), (0x0A5E, 0x0A5E), (0x0A66, 0x0A74), (0x0A81, 0x0A83), (0x0A85, 0x0A8B), (0x0A8D, 0x0A8D),
    (0x0A8F, 0x0A91), (0x0A93, 0x0AA8), (0x0AAA, 0x0AB0), (0x0AB2, 0x0AB3), (0x0AB5, 0x0AB9), (0x0ABC, 0x0AC5),
    (0x0AC7, 0x0AC9), (0x0ACB, 0x0ACD), (0x0AE0, 0x0AE0), (0x0AE6, 0x0AEF), (0x0B01, 0x0B03), (0x0B05, 0x0B0C),
    (0x0B0F, 0x0B10), (0x0B13, 0x0B28), (0x0B2A, 0x0B30), (0x0B32, 0x0B33), (0x0B36, 0x0B39), (0x0B3C, 0x0B43),
    (0x0B47, 0x0B48), (0x0B4B, 0x0B4D), (0x0B56, 0x0B57), (0x0B5C, 0x0B5D), (0x0B5F, 0x0B61), (0x0B66, 0x0B6F),
    (0x0B82, 0x0B83), (0x0B85, 0x0B8A), (0x0B8E, 0x0B90), (0x0B92, 0x0B95), (0x0B99, 0x0B9A), (0x0B9C, 0x0B9C),
    (0x0B9E, 0x0B9F), (0x0BA3, 0x0BA4), (0x0BA8, 0x0BAA), (0x0BAE, 0x0BB5), (0x0BB7, 0x0BB9), (0x0BBE, 0x0BC2),
    (0x0BC6, 0x0BC8), (0x0BCA, 0x0BCD), (0x0BD7, 0x0BD7), (0x0BE7, 0x0BEF), (0x0C01, 0x0C03), (0x0C05, 0x0C0C),
    (0x0C0E, 0x0C10), (0x0C12, 0x0C28), (0x0C2A, 0x0C33), (0x0C35, 0x0C39), (0x0C3E, 0x0C44), (0x0C46, 0x0C48),
    (0x0C4A, 0x0C4D), (0x0C55, 0x0C56), (0x0C60, 0x0C61), (0x0C66, 0x0C6F), (0x0C82, 0x0C83), (0x0C85, 0x0C8C),
    (0x0C8E, 0x0C90), (0x0C92, 0x0CA8), (0x0CAA, 0x0CB3), (0x0CB5, 0x0CB9), (0x0CBE, 0x0CC4), (0x0CC6, 0x0CC8),
    (0x0CCA, 0x0CCD), (0x0CD5, 0x0CD6), (0x0CDE, 0x0CDE), (0x0CE0, 0x0CE1), (0x0CE6, 0x0CEF), (0x0D02, 0x0D03),
    (0x0D05, 0x0D0C), (0x0D0E, 0x0D10), (0x0D12, 0x0D28), (0x0D2A, 0x0D39), (0x0D3E, 0x0D43), (0x0D46, 0x0D48),
    (0x0D4A, 0x0D4D), (0x0D57, 0x0D57), (0x0D60, 0x0D61), (0x0D66, 0x0D6F), (0x0E01, 0x0E2E), (0x0E30, 0x0E3A),
    (0x0E40, 0x0E4E), (0x0E50, 0x0E59), (0x0E81, 0x0E82), (0x0E84, 0x0E84), (0x0E87, 0x0E88), (0x0E8A, 0x0E8A),
    (0x0E8D, 0x0E8D), (0x0E94, 0x0E97), (0x0E99, 0x0E9F), (0x0EA1, 0x0EA3), (0x0EA5, 0x0EA5), (0x0EA7, 0x0EA7),
    (0x0EAA, 0x0EAB), (0x0EAD, 0x0EAE), (0x0EB0, 0x0EB9), (0x0EBB, 0x0EBD), (0x0EC0, 0x0EC4), (0x0EC6, 0x0EC6),
    (0x0EC8, 0x0ECD), (0x0ED0, 0x0ED9), (0x0F18, 0x0F19), (0x0F20, 0x0F29), (0x0F35, 0x0F35), (0x0F37, 0x0F37),
    (0x0F39, 0x0F39), (0x0F3E, 0x0F47), (0x0F49, 0x0F69), (0x0F71, 0x0F84), (0x0F86, 0x0F8B), (0x0F90, 0x0F95),
    (0x0F97, 0x0F97), (0x0F99, 0x0FAD), (0x0FB1, 0x0FB7), (0x0FB9, 0x0FB9), (0x10A0, 0x10C5), (0x10D0, 0x10F6),
    (0x1100, 0x1100), (0x1102, 0x1103), (0x1105, 0x1107), (0x1109, 0x1109), (0x110B, 0x110C), (0x110E, 0x1112),
    (0x113C, 0x113C), (0x113E, 0x113E), (0x1140, 0x1140), (0x114C, 0x114C), (0x114E, 0x114E), (0x1150, 0x1150),
    (0x1154, 0x1155), (0x1159, 0x1159), (0x115F, 0x1161), (0x1163, 0x1163), (0x1165, 0x1165), (0x1167, 0x1167),
    (0x1169, 0x1169), (0x116D, 0x116E), (0x1172, 0x1173), (0x1175, 0x1175), (0x119E, 0x119E), (0x11A8, 0x11A8),
    (0x11AB, 0x11AB), (0x11AE, 0x11AF), (0x11B7, 0x11B8), (0x11BA, 0x11BA), (0x11BC, 0x11C2), (0x11EB, 0x11EB),
    (0x11F0, 0x11F0), (0x11F9, 0x11F9), (0x1E00, 0x1E9B), (0x1EA0, 0x1EF9), (0x1F00, 0x1F15), (0x1F18, 0x1F1D),
    (0x1F20, 0x1F45), (0x1F48, 0x1F4D), (0x1F50, 0x1F57), (0x1F59, 0x1F59), (0x1F5B, 0x1F5B), (0x1F5D, 0x1F5D),
    (0x1F5F, 0x1F7D), (0x1F80, 0x1FB4), (0x1FB6, 0x1FBC), (0x1FBE, 0x1FBE), (0x1FC2, 0x1FC4), (0x1FC6, 0x1FCC),
    (0x1FD0, 0x1FD3), (0x1FD6, 0x1FDB), (0x1FE0, 0x1FEC), (0x1FF2, 0x1FF4), (0x1FF6, 0x1FFC), (0x20D0, 0x20DC),
    (0x20E1, 0x20E1), (0x2126, 0x2126), (0x212A, 0x212B), (0x212E, 0x212E), (0x2180, 0x2182), (0x3005, 0x3005),
    (0x3007, 0x3007), (0x3021, 0x302F), (0x3031, 0x3035), (0x3041, 0x3094), (0x3099, 0x309A), (0x309D, 0x309E),
    (0x30A1, 0x30FA), (0x30FC, 0x30FE), (0x3105, 0x312C), (0x4E00, 0x9FA5), (0xAC00, 0xD7A3),
)


def _class(ranges: tuple[tuple[int, int], ...], extra: str = "") -> str:
    def esc(c: int) -> str:
        return f"\\U{c:08x}"

    return "[" + "".join(esc(a) if a == b else f"{esc(a)}-{esc(b)}" for a, b in ranges) + extra + "]"


_START = _class(NAME_START_RANGES, "_")
_CHAR = _class(NAME_CHAR_RANGES)
_NCNAME = re.compile(f"{_START}{_CHAR}*")
_NMTOKEN = re.compile(f"(?:{_CHAR}|:)+")
_NAME = re.compile(f"(?:{_START}|:)(?:{_CHAR}|:)*")
_BAD_XML_CHAR = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
_DOUBLE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|INF|-INF|NaN")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_INTEGER = re.compile(r"[+-]?[0-9]+")
_DATETIME = re.compile(r"(-?)([0-9]{4,})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?"
                       r"(Z|[+-][0-9]{2}:[0-9]{2})?")


class _Unrepresentable(SchemaValueError):
    """A lexically valid value that Python cannot hold (dateTime outside years 1 to 9999). Counts as valid."""


# ------------------------------------------------------------------------------------------------ codecs

class Codec:
    """One XSD simple type. See the module docstring for the Python values and parsed values per type."""

    xsd_type: str
    literals: tuple[str, ...] | None = None
    _lengthy = False      # length facets apply (strings and lists)
    _ordered = False      # range facets apply (doubles, decimals, integers)
    _lexical_str = False  # a str is a lexical form, stored verbatim when valid (numbers, booleans, dateTime)

    def __init__(self, xsd_type: str) -> None:
        self.xsd_type = xsd_type

    # -- subclass hooks
    def _normalize(self, s: str) -> str:
        return s

    def _lexical(self, value: Any) -> str:
        raise NotImplementedError

    def _value(self, s: str) -> Any:
        raise NotImplementedError

    # -- helpers
    def _fail(self, message: str, *, suggestions: Iterable[str] | None = None,
              suggest_from: tuple[str, Iterable[str]] | None = None) -> SchemaValueError:
        return SchemaValueError(message, xsd_type=self.xsd_type, suggestions=suggestions, suggest_from=suggest_from)

    def _wrong_type(self, value: Any, expected: str) -> SchemaValueError:
        return self._fail(f"expected {expected}, got {type(value).__name__} {value!r}")

    # -- public API
    def validate(self, value: Any) -> str:
        """Return the lexical form to store for ``value``; raise ``SchemaValueError`` if it is refused.

        For a type that is not string-valued, a ``str`` is a lexical form: when it is valid (every facet checked) it
        is returned unchanged, as ``read`` keeps a lexical form it finds in a file (SREP 91 section 3.5).
        """
        lexical = value if self._lexical_str and isinstance(value, str) else self._lexical(value)
        try:
            self._value(lexical)
        except _Unrepresentable:
            pass
        return lexical

    format = validate

    def parse(self, lexical: str) -> Any:
        """Read a lexical form into its Python value; raise ``SchemaValueError`` if it is not valid."""
        if not isinstance(lexical, str):
            raise self._wrong_type(lexical, "a lexical str")
        return self._value(lexical)

    def is_valid_lexical(self, s: str) -> bool:
        """Full XSD lexical and value space check, including every facet."""
        if not isinstance(s, str):
            return False
        try:
            self._value(s)
        except _Unrepresentable:
            return True
        except SchemaValueError:
            return False
        return True

    def __repr__(self) -> str:
        return f"<Codec {self.xsd_type}>"


class _String(Codec):
    _lengthy = True

    def __init__(self, xsd_type: str, *, collapse: bool = False, lexical_re: re.Pattern[str] | None = None,
                 what: str = "a string") -> None:
        super().__init__(xsd_type)
        self._collapse_ws = collapse
        self._re = lexical_re
        self._what = what

    def _normalize(self, s: str) -> str:
        return _collapse(s) if self._collapse_ws else s

    def _text(self, value: Any) -> str:
        if not isinstance(value, str):
            raise self._wrong_type(value, "str")
        return value

    def _lexical(self, value: Any) -> str:
        return self._normalize(self._text(value))

    def _value(self, s: str) -> str:
        n = self._normalize(s)
        bad = _BAD_XML_CHAR.search(n)
        if bad:
            raise self._fail(f"character U+{ord(bad.group()):04X} is not allowed in XML")
        if self._re is not None and self._re.fullmatch(n) is None:
            raise self._fail(f"{n!r} is not {self._what}")
        return n


class _IdRef(_String):
    """xs:IDREF: an NCName, or any object with a truthy string ``id`` (stores the id)."""

    def _text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        ident = getattr(value, "id", None)
        if ident is None or ident == "":
            raise self._fail(f"{type(value).__name__} has no id to refer to")
        if not isinstance(ident, str):
            raise self._wrong_type(ident, "str id")
        return ident


class _Double(Codec):
    _lexical_str = True
    _ordered = True

    def _normalize(self, s: str) -> str:
        return _collapse(s)

    def _lexical(self, value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._wrong_type(value, "int or float")
        return fmt_double(value, xsd_type=self.xsd_type)

    def _value(self, s: str) -> float:
        n = _collapse(s)
        if _DOUBLE.fullmatch(n) is None:
            raise self._fail(f"{n!r} is not a valid xs:double")
        return float(n.replace("INF", "inf").replace("NaN", "nan"))


class _Decimal(Codec):
    _lexical_str = True
    _ordered = True

    def _normalize(self, s: str) -> str:
        return _collapse(s)

    def _lexical(self, value: Any) -> str:
        if isinstance(value, str):
            n = _collapse(value)
            if _DECIMAL.fullmatch(n) is None:
                raise self._fail(f"{n!r} is not a valid xs:decimal")
            return n
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise self._wrong_type(value, "int, float, Decimal or a decimal str")
        return fmt_decimal(value, xsd_type=self.xsd_type)

    def _value(self, s: str) -> Decimal:
        n = _collapse(s)
        if _DECIMAL.fullmatch(n) is None:
            raise self._fail(f"{n!r} is not a valid xs:decimal")
        return Decimal(n)


class _Integer(Codec):
    _lexical_str = True
    _ordered = True

    def __init__(self, xsd_type: str, lo: int | None = None, hi: int | None = None) -> None:
        super().__init__(xsd_type)
        self._lo = lo
        self._hi = hi

    def _normalize(self, s: str) -> str:
        return _collapse(s)

    def _lexical(self, value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, int):
            raise self._wrong_type(value, "int")
        return str(value)

    def _value(self, s: str) -> int:
        n = _collapse(s)
        if _INTEGER.fullmatch(n) is None:
            raise self._fail(f"{n!r} is not a valid {self.xsd_type}")
        try:
            v = int(n)
        except ValueError:
            raise self._fail(f"{n[:20]!r}... has too many digits") from None
        if (self._lo is not None and v < self._lo) or (self._hi is not None and v > self._hi):
            low = "-inf" if self._lo is None else self._lo
            high = "+inf" if self._hi is None else self._hi
            raise self._fail(f"{v} is outside the range [{low}, {high}] of {self.xsd_type}")
        return v


class _Boolean(Codec):
    _lexical_str = True
    def _normalize(self, s: str) -> str:
        return _collapse(s)

    def _lexical(self, value: Any) -> str:
        if not isinstance(value, bool):
            raise self._wrong_type(value, "bool")
        return "true" if value else "false"

    def _value(self, s: str) -> bool:
        n = _collapse(s)
        if n in ("true", "1"):
            return True
        if n in ("false", "0"):
            return False
        raise self._fail(f"{n!r} is not a valid xs:boolean (true, false, 1 or 0)")


def _leap(year: int) -> bool:
    y = year if year > 0 else year + 1      # XSD 1.0 has no year 0: -0001 is astronomical year 0
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


class _DateTime(Codec):
    _lexical_str = True
    def _normalize(self, s: str) -> str:
        return _collapse(s)

    def _lexical(self, value: Any) -> str:
        if isinstance(value, str):
            return _collapse(value)
        if not isinstance(value, _dt.datetime):
            raise self._wrong_type(value, "datetime or an xs:dateTime str")
        text = (f"{value.year:04d}-{value.month:02d}-{value.day:02d}T{value.hour:02d}:{value.minute:02d}:"
                f"{value.second:02d}")
        if value.microsecond:
            text += "." + f"{value.microsecond:06d}".rstrip("0")
        offset = value.utcoffset()
        if offset is not None:
            minutes, rest = divmod(int(offset.total_seconds()), 60)
            if rest or offset.microseconds or abs(minutes) > 14 * 60:
                raise self._fail(f"UTC offset {offset} is not a whole number of minutes within 14 hours")
            if minutes == 0:
                text += "Z"
            else:
                text += ("-" if minutes < 0 else "+") + f"{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"
        return text

    def _value(self, s: str) -> _dt.datetime:
        n = _collapse(s)
        m = _DATETIME.fullmatch(n)
        if m is None:
            raise self._fail(f"{n!r} is not a valid xs:dateTime (YYYY-MM-DDThh:mm:ss[.s+][Z|(+|-)hh:mm])")
        sign, ys, mo_s, d_s, h_s, mi_s, sec_s, frac, tz = m.groups()
        year = -int(ys) if sign else int(ys)
        month, day, hour, minute, second = int(mo_s), int(d_s), int(h_s), int(mi_s), int(sec_s)
        if len(ys) > 4 and ys[0] == "0":
            raise self._fail(f"{n!r}: the year has superfluous leading zeros")
        if year == 0:
            raise self._fail(f"{n!r}: year 0000 does not exist in XSD 1.0")
        if not 1 <= month <= 12:
            raise self._fail(f"{n!r}: month {month} is out of range")
        if not 1 <= day <= _DAYS[month - 1] + (1 if month == 2 and _leap(year) else 0):
            raise self._fail(f"{n!r}: day {day} does not exist in that month")
        fraction_zero = frac is None or not frac.strip(".0")
        end_of_day = hour == 24
        if hour > 24 or (end_of_day and (minute or second or not fraction_zero)):
            raise self._fail(f"{n!r}: hour {hour} is out of range (24 is allowed only as 24:00:00)")
        if minute > 59 or second > 59:
            raise self._fail(f"{n!r}: minute or second is out of range")
        tzinfo: _dt.tzinfo | None = None
        if tz is not None:
            if tz == "Z":
                tzinfo = _dt.timezone.utc
            else:
                th, tm = int(tz[1:3]), int(tz[4:6])
                if th > 14 or tm > 59 or (th == 14 and tm):
                    raise self._fail(f"{n!r}: time zone offset {tz} is out of range (at most 14:00)")
                delta = _dt.timedelta(hours=th, minutes=tm)
                tzinfo = _dt.timezone(-delta if tz[0] == "-" else delta)
        if not 1 <= year <= 9999:
            raise _Unrepresentable(f"{n!r} is valid but outside the years Python can hold", xsd_type=self.xsd_type)
        micro = int((frac[1:] + "000000")[:6]) if frac else 0
        try:
            base = _dt.datetime(year, month, day, 0 if end_of_day else hour, minute, second, micro, tzinfo)
            return base + _dt.timedelta(days=1) if end_of_day else base
        except OverflowError:
            raise _Unrepresentable(f"{n!r} is valid but outside the years Python can hold",
                                   xsd_type=self.xsd_type) from None


class _List(Codec):
    _lengthy = True

    def __init__(self, xsd_type: str, item: Codec) -> None:
        super().__init__(xsd_type)
        self._item = item

    def _normalize(self, s: str) -> str:
        return _collapse(s)

    def _lexical(self, value: Any) -> str:
        if isinstance(value, str):
            tokens = _split(value)
            for index, token in enumerate(tokens):
                self._check_item(index, token)
            return " ".join(tokens)
        if isinstance(value, (bytes, bytearray)) or not isinstance(value, Sequence):
            raise self._wrong_type(value, "a sequence or a lexical str")
        tokens = []
        for index, item in enumerate(value):
            try:
                token = self._item.validate(item)
            except SchemaValueError as e:
                raise self._fail(f"item {index}: {e.message}", suggestions=e.suggestions) from None
            if _WS_RUN.search(token) or token == "":
                raise self._fail(f"item {index}: {token!r} cannot be written as a list item")
            tokens.append(token)
        return " ".join(tokens)

    def _check_item(self, index: int, token: str) -> Any:
        try:
            return self._item._value(token)
        except _Unrepresentable:
            return None
        except SchemaValueError as e:
            raise self._fail(f"item {index}: {e.message}", suggestions=e.suggestions) from None

    def _value(self, s: str) -> list[Any]:
        return [self._check_item(i, t) for i, t in enumerate(_split(s))]


class _Union(Codec):
    def __init__(self, xsd_type: str, members: Sequence[Codec]) -> None:
        super().__init__(xsd_type)
        self._members = tuple(members)

    def _lexical(self, value: Any) -> str:
        errors: list[SchemaValueError] = []
        for member in self._members:
            try:
                return member.validate(value)
            except SchemaValueError as e:
                errors.append(e)
        raise self._no_member(repr(value), errors)

    def _value(self, s: str) -> Any:
        errors: list[SchemaValueError] = []
        for member in self._members:
            try:
                return member._value(s)
            except _Unrepresentable:
                raise
            except SchemaValueError as e:
                errors.append(e)
        raise self._no_member(repr(s), errors)

    def _no_member(self, shown: str, errors: list[SchemaValueError]) -> SchemaValueError:
        """The error for a value that fits no member; the members' suggestions are read only now, when it is refused."""
        reasons = [f"{m.xsd_type}: {e.message}" for m, e in zip(self._members, errors)]
        found: list[str] = []
        for e in errors:
            found.extend(x for x in e.suggestions if x not in found)
        return self._fail(f"{shown} fits no member type ({'; '.join(reasons)})", suggestions=found[:3])


_LENGTH_FACETS = ("length", "minLength", "maxLength")
_RANGE_FACETS = ("minInclusive", "maxInclusive", "minExclusive", "maxExclusive")
_SINGLE_FACETS = _LENGTH_FACETS + _RANGE_FACETS


class _Restriction(Codec):
    """A base codec narrowed by enumeration and facets. Patterns in one step are alternatives (XSD 4.3.4)."""

    def __init__(self, xsd_type: str, base: Codec, enums: Sequence[str], facets: Sequence[tuple[str, str]]) -> None:
        super().__init__(xsd_type)
        self._base = base
        self._lengthy = base._lengthy
        self._ordered = base._ordered
        self._lexical_str = base._lexical_str
        self.literals = tuple(enums) if enums else base.literals
        self._enum_values: list[Any] | None = None
        if enums:
            values: list[Any] = []
            for lit in enums:
                try:
                    values.append(base._value(lit))
                except SchemaValueError as e:
                    raise SchemaError(f"{xsd_type}: enumeration value {lit!r} is not in the base type: {e.message}") from None
            self._enum_values = values
        self._patterns: list[re.Pattern[str]] = []
        self._lengths: dict[str, int] = {}
        self._bounds: dict[str, Any] = {}
        seen: set[str] = set()
        for facet, value in facets:
            if facet == "pattern":
                self._patterns.append(_compile(value))
            elif facet in _SINGLE_FACETS:
                if facet in seen:
                    raise SchemaError(f"{xsd_type}: facet {facet} given twice")
                seen.add(facet)
                if facet in _LENGTH_FACETS:
                    self._add_length(facet, value)
                else:
                    self._add_bound(facet, value)
            else:
                raise SchemaError(f"{xsd_type}: facet {facet!r} is not supported")

    def _add_length(self, facet: str, value: str) -> None:
        if not self._lengthy:
            raise SchemaError(f"{self.xsd_type}: facet {facet} does not apply to the base type")
        if not re.fullmatch("[0-9]+", value):
            raise SchemaError(f"{self.xsd_type}: facet {facet} needs a non-negative integer, got {value!r}")
        self._lengths[facet] = int(value)

    def _add_bound(self, facet: str, value: str) -> None:
        if not self._ordered:
            raise SchemaError(f"{self.xsd_type}: facet {facet} does not apply to the base type")
        try:
            self._bounds[facet] = self._base._value(value)
        except SchemaValueError as e:
            raise SchemaError(f"{self.xsd_type}: {facet} value {value!r} is not in the base type: {e.message}") from None

    def _normalize(self, s: str) -> str:
        return self._base._normalize(s)

    def _lexical(self, value: Any) -> str:
        return self._base._lexical(value)

    def _value(self, s: str) -> Any:
        v = self._base._value(s)
        n = self._base._normalize(s)
        if self._enum_values is not None and not any(v == e for e in self._enum_values):
            literals = self.literals or ()
            raise self._fail(f"{n!r} is not one of {', '.join(repr(x) for x in literals)}",
                             suggest_from=(n, literals))
        if self._patterns and not any(p.fullmatch(n) for p in self._patterns):
            raise self._fail(f"{n!r} does not match the pattern of {self.xsd_type}")
        if self._lengths:
            size = len(v)
            for facet, limit in self._lengths.items():
                if ((facet == "length" and size != limit) or (facet == "minLength" and size < limit)
                        or (facet == "maxLength" and size > limit)):
                    unit = "items" if isinstance(v, list) else "characters"
                    raise self._fail(f"{size} {unit} violates {facet} {limit}")
        for facet, bound in self._bounds.items():
            if facet == "minInclusive":
                ok = v >= bound
            elif facet == "maxInclusive":
                ok = v <= bound
            elif facet == "minExclusive":
                ok = v > bound
            else:
                ok = v < bound
            if not ok:
                raise self._fail(f"{n} violates {facet} {bound}")
        return v


# ------------------------------------------------------------------------------------------------ construction

_BUILTINS: dict[str, Codec] = {}


# ------------------------------------------------------------------------------------------------ xs:anyURI

def _uri_regex() -> re.Pattern[str]:
    """RFC 3986 section 4.1 URI-reference, compiled from the ABNF of its Appendix A."""
    pct = "%[0-9A-Fa-f]{2}"                                     # pct-encoded (2.1)
    unreserved = "[A-Za-z0-9._~-]"                              # unreserved (2.3)
    sub = "[!$&'()*+,;=]"                                       # sub-delims (2.2)
    pchar = f"(?:{unreserved}|{pct}|{sub}|[:@])"                # pchar (3.3)
    segment, segment_nz = f"{pchar}*", f"{pchar}+"
    segment_nz_nc = f"(?:{unreserved}|{pct}|{sub}|@)+"          # segment-nz-nc (3.3)
    scheme = "[A-Za-z][A-Za-z0-9+.-]*"                          # scheme (3.1)
    userinfo = f"(?:{unreserved}|{pct}|{sub}|:)*"               # userinfo (3.2.1)
    octet = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]|[0-9])"   # dec-octet (3.2.2)
    ipv4 = rf"{octet}(?:\.{octet}){{3}}"                        # IPv4address
    h16 = "[0-9A-Fa-f]{1,4}"
    ls32 = f"(?:{h16}:{h16}|{ipv4})"
    ipv6 = "|".join([                                           # IPv6address (3.2.2), nine alternatives
        f"(?:{h16}:){{6}}{ls32}",
        f"::(?:{h16}:){{5}}{ls32}",
        f"(?:{h16})?::(?:{h16}:){{4}}{ls32}",
        f"(?:(?:{h16}:){{0,1}}{h16})?::(?:{h16}:){{3}}{ls32}",
        f"(?:(?:{h16}:){{0,2}}{h16})?::(?:{h16}:){{2}}{ls32}",
        f"(?:(?:{h16}:){{0,3}}{h16})?::{h16}:{ls32}",
        f"(?:(?:{h16}:){{0,4}}{h16})?::{ls32}",
        f"(?:(?:{h16}:){{0,5}}{h16})?::{h16}",
        f"(?:(?:{h16}:){{0,6}}{h16})?::",
    ])
    ipvfuture = rf"v[0-9A-Fa-f]+\.(?:{unreserved}|{sub}|:)+"      # IPvFuture
    ip_literal = rf"\[(?:{ipv6}|{ipvfuture})\]"                 # IP-literal: the only place [ ] may occur
    host = f"(?:{ip_literal}|{ipv4}|(?:{unreserved}|{pct}|{sub})*)"   # host, reg-name
    authority = f"(?:{userinfo}@)?{host}(?::[0-9]*)?"           # authority (3.2)
    abempty = f"(?:/{segment})*"                                # path-abempty (3.3)
    absolute = f"/(?:{segment_nz}(?:/{segment})*)?"             # path-absolute
    rootless = f"{segment_nz}(?:/{segment})*"                   # path-rootless
    noscheme = f"{segment_nz_nc}(?:/{segment})*"                # path-noscheme
    tail = rf"(?:\?(?:{pchar}|[/?])*)?(?:#(?:{pchar}|[/?])*)?"    # query, fragment (3.4, 3.5): no second "#"
    hier = f"(?://{authority}{abempty}|{absolute}|{rootless}|)"      # hier-part (3.0), path-empty
    rel = f"(?://{authority}{abempty}|{absolute}|{noscheme}|)"       # relative-part (4.2)
    return re.compile(f"(?:{scheme}:{hier}|{rel}){tail}")       # URI | relative-ref (4.1)


_URI = _uri_regex()
# XLink 5.4 (used by XSD 1.0 Part 2, 3.2.17): these are percent-escaped, as UTF-8, before the URI check.
_XLINK_ESCAPE = re.compile(r"[^\x21-\x7e]|[\"<>\\^`{|}]")


def _xlink_escape(s: str) -> str:
    return _XLINK_ESCAPE.sub(lambda m: "".join(f"%{b:02X}" for b in m.group().encode("utf-8", "surrogatepass")), s)


class _AnyURI(_String):
    """xs:anyURI: after the XLink escaping, a URI reference of RFC 3986 section 4.1."""

    def _value(self, s: str) -> str:
        n = super()._value(s)
        if _URI.fullmatch(_xlink_escape(n)) is None:
            raise self._fail(f"{n!r} is not a URI reference (RFC 3986)")
        return n


def _make_builtin(name: str) -> Codec:
    def string(**kw: Any) -> Codec:
        return _String(name, **kw)

    if name == "xs:string":
        return string()
    if name == "xs:anyURI":
        return _AnyURI(name, collapse=True, what="a URI reference")
    if name in ("xs:NCName", "xs:ID"):
        return string(collapse=True, lexical_re=_NCNAME, what="a valid NCName")
    if name == "xs:IDREF":
        return _IdRef(name, collapse=True, lexical_re=_NCNAME, what="a valid NCName")
    if name == "xs:NMTOKEN":
        return string(collapse=True, lexical_re=_NMTOKEN, what="a valid NMTOKEN")
    if name == "xs:double":
        return _Double(name)
    if name == "xs:decimal":
        return _Decimal(name)
    if name == "xs:integer":
        return _Integer(name)
    if name == "xs:positiveInteger":
        return _Integer(name, lo=1)
    if name == "xs:nonNegativeInteger":
        return _Integer(name, lo=0)
    if name == "xs:int":
        return _Integer(name, lo=-2 ** 31, hi=2 ** 31 - 1)
    if name == "xs:unsignedLong":
        return _Integer(name, lo=0, hi=2 ** 64 - 1)
    if name == "xs:boolean":
        return _Boolean(name)
    if name == "xs:dateTime":
        return _DateTime(name)
    if name in ("xs:IDREFS", "xs:NMTOKENS"):
        item = _builtin(name[:-1])
        return _Restriction(name, _List(f"list of {item.xsd_type}", item), (), (("minLength", "1"),))
    raise SchemaError(f"unsupported builtin type {name!r}")


def _builtin(name: str) -> Codec:
    codec = _BUILTINS.get(name)
    if codec is None:
        codec = _BUILTINS[name] = _make_builtin(name)
    return codec


_CACHE: dict[tuple[int, Any], tuple[Mapping[str, Any], Any, Codec]] = {}


def _enum_literals(raw: Sequence[Any]) -> tuple[str, ...]:
    return tuple(e[0] if isinstance(e, (tuple, list)) else e for e in raw)


def _resolve(ref: Any, table: Mapping[str, Mapping[str, Any]], stack: tuple[str, ...]) -> Codec:
    if isinstance(ref, str):
        return _named(ref, table, stack)
    if isinstance(ref, Mapping):
        return _build(ref, table, None, stack)
    raise SchemaError(f"a type reference must be a name or a spec dict, got {type(ref).__name__}")


def _named(name: str, table: Mapping[str, Mapping[str, Any]], stack: tuple[str, ...]) -> Codec:
    if name.startswith("xs:"):
        return _builtin(name)
    key = (id(table), name)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] is table:
        return hit[2]
    if name not in table:
        raise SchemaError(f"unknown simple type {name!r}")
    if name in stack:
        raise SchemaError(f"simple type {name!r} refers to itself: {' -> '.join(stack + (name,))}")
    codec = _build(table[name], table, name, stack + (name,))
    _CACHE[key] = (table, name, codec)
    return codec


def _build(spec: Mapping[str, Any], table: Mapping[str, Mapping[str, Any]], name: str | None,
           stack: tuple[str, ...]) -> Codec:
    kind = spec.get("kind")
    enums = _enum_literals(spec.get("enums") or ())
    facets = tuple((f, v) for f, v in (spec.get("facets") or ()))
    if kind == "restriction":
        if spec.get("base") is None:
            raise SchemaError(f"{name or 'inline restriction'}: a restriction needs a base")
        base = _resolve(spec["base"], table, stack)
        return _Restriction(name or f"restriction of {base.xsd_type}", base, enums, facets)
    if kind == "list":
        if spec.get("item") is None:
            raise SchemaError(f"{name or 'inline list'}: a list needs an item type")
        item = _resolve(spec["item"], table, stack)
        structural: Codec = _List(name or f"list of {item.xsd_type}", item)
    elif kind == "union":
        members = [_resolve(m, table, stack) for m in (spec.get("members") or ())]
        if not members:
            raise SchemaError(f"{name or 'inline union'}: a union needs member types")
        structural = _Union(name or "union of " + ", ".join(m.xsd_type for m in members), members)
    else:
        raise SchemaError(f"{name or 'inline type'}: unknown kind {kind!r}")
    if enums or facets:
        structural.xsd_type = f"{structural.xsd_type} (base)" if name else structural.xsd_type
        return _Restriction(name or f"restricted {structural.xsd_type}", structural, enums, facets)
    return structural


def codec_for(spec: str | Mapping[str, Any], simple_table: Mapping[str, Mapping[str, Any]]) -> Codec:
    """The codec for a builtin name, a named simple type of ``simple_table``, or an inline spec dict.

    Codecs are cached per table. Raises ``SchemaError`` for anything the SDK does not handle.
    """
    if isinstance(spec, str):
        return _named(spec, simple_table, ())
    if not isinstance(spec, Mapping):
        raise SchemaError(f"a type reference must be a name or a spec dict, got {type(spec).__name__}")
    key = (id(simple_table), id(spec))
    hit = _CACHE.get(key)
    if hit is not None and hit[0] is simple_table and hit[1] is spec:
        return hit[2]
    codec = _build(spec, simple_table, None, ())
    _CACHE[key] = (simple_table, spec, codec)
    return codec
