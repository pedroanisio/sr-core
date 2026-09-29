"""tools/release.py: bumps from changelog classes, cutting a release, and the repository's own versions (SREP 4)."""
import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("release", os.path.join(ROOT, "tools", "release.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

LOG = """# Changelog

## Unreleased

### Breaking

### Added

### Fixed

- a typo
  spanning two lines

## 1.4.2 — 2026-01-01

### Fixed

- older
"""


def with_entries(**classes):
    text = LOG
    for name, entries in classes.items():
        text = text.replace(f"### {name}\n\n", f"### {name}\n\n" + "".join(f"- {e}\n" for e in entries) + "\n", 1)
    return text


def test_parse():
    classes, released, _ = release.parse(LOG)
    assert classes == {"fixed": ["a typo spanning two lines"]}
    assert released == ["1.4.2"]


@pytest.mark.parametrize("classes,expected", [
    ({}, None),
    ({"fixed": ["x"]}, "1.4.3"),
    ({"docs": ["x"], "changed": ["y"]}, "1.4.3"),
    ({"added": ["x"], "fixed": ["y"]}, "1.5.0"),
    ({"deprecated": ["x"]}, "1.5.0"),
    ({"breaking": ["x"], "added": ["y"]}, "2.0.0"),
    ({"removed": ["x"]}, "2.0.0"),
])
def test_next_version_takes_the_largest_bump(classes, expected):
    assert release.next_version("1.4.2", classes) == expected


def test_many_changes_share_one_bump():
    text = with_entries(Added=["one", "two", "three"])
    classes, _, _ = release.parse(text)
    assert release.next_version("1.4.2", classes) == "1.5.0"


def test_cut_moves_entries_and_leaves_an_empty_unreleased():
    text = with_entries(Added=["feature"])
    out = release.cut(text, "1.5.0", "2026-10-01")
    classes, released, _ = release.parse(out)
    assert classes == {} and released == ["1.5.0", "1.4.2"]
    section = out.split("## 1.5.0 — 2026-10-01\n", 1)[1].split("## 1.4.2", 1)[0]
    assert "- feature" in section and "- a typo spanning two lines" in section and "### Breaking" not in section


def test_entry_outside_a_class_is_an_error():
    with pytest.raises(release.ReleaseError):
        release.parse("## Unreleased\n\n- loose\n")


def test_repository_versions_agree():
    """Every version matches its changelog, the schema hashes and reference are current (release.py check)."""
    assert release.check() == []


def test_one_distribution_version():
    import sr_core
    from sr_core import schemadoc, vpkg
    assert vpkg.__version__ == schemadoc.__version__ == sr_core.__version__ == release.tools_version()
