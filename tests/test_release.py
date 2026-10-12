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


# ------------------------------------------------------------------ scene SDK (SREP 0, D1, D2, D7)
import shutil  # noqa: E402

SDK_FILES = ["schema/scene-render.xsd", "schema/scene-render.sch", "schema/SHA256SUMS",
             "sr_core/scene/_generated.py", "sr_core/scene/schema/scene-render.xsd",
             "sr_core/scene/schema/scene-render.sch", "sr_core/scene/schema/SHA256SUMS"]


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    """A scratch copy of the files the SDK controls; release.ROOT points at it."""
    for rel in SDK_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), tmp_path / rel)
    monkeypatch.setattr(release, "ROOT", str(tmp_path))
    return tmp_path


def test_fresh_sdk_has_no_problems(tmp_root):
    assert release.sdk_problems() == []


def test_stale_sdk_is_a_problem(tmp_root):
    gen = tmp_root / release.SDK_GENERATED
    gen.write_bytes(gen.read_bytes() + b"# edited\n")
    assert release.sdk_problems() == ["sr_core/scene is stale; run python3 -m sr_core.scene.generate"]


def test_missing_sdk_is_stale(tmp_root):
    (tmp_root / release.SDK_GENERATED).unlink()
    assert release.SDK_STALE in release.sdk_problems()


def test_schema_change_without_regeneration_is_stale_and_mismatched(tmp_root):
    xsd = tmp_root / "schema/scene-render.xsd"
    xsd.write_bytes(xsd.read_bytes().replace(b"<!--", b"<!-- ", 1))
    problems = release.sdk_problems()
    assert release.SDK_STALE in problems
    assert any("sr_core/scene/schema/scene-render.xsd is not byte-equal to schema/scene-render.xsd" in p for p in problems)
    assert any("XSD_SHA256" in p for p in problems)


@pytest.mark.parametrize("name", ["scene-render.sch", "SHA256SUMS"])
def test_schema_copy_mismatch(tmp_root, name):
    copy = tmp_root / "sr_core/scene/schema" / name
    copy.write_bytes(copy.read_bytes() + b"\n")
    assert release.sdk_problems() == [f"sr_core/scene/schema/{name} is not byte-equal to schema/{name}; "
                                      "run python3 -m sr_core.scene.generate"]


@pytest.mark.parametrize("const", ["XSD_SHA256", "SCH_SHA256"])
def test_header_hash_mismatch(tmp_root, const):
    gen = tmp_root / release.SDK_GENERATED
    text = gen.read_text(encoding="utf-8")
    old = next(l for l in text.splitlines() if l.startswith(f"{const} = "))
    gen.write_text(text.replace(old, f'{const} = "{"0" * 64}"'), encoding="utf-8")
    problems = release.sdk_problems()
    assert any(const in p and "differs from the hash" in p for p in problems)


def test_check_reports_the_sdk_problems(monkeypatch):
    monkeypatch.setattr(release, "sdk_problems", lambda: ["sdk problem"])
    assert "sdk problem" in release.check()


def test_refresh_schema_regenerates_the_sdk(tmp_root, monkeypatch):
    from sr_core.schemadoc import cli
    monkeypatch.setattr(cli, "main", lambda argv: 0)
    xsd = tmp_root / "schema/scene-render.xsd"
    xsd.write_bytes(xsd.read_bytes().replace(b"<!--", b"<!-- ", 1))
    release.refresh_schema()
    assert release.sdk_problems() == []
    assert (tmp_root / "sr_core/scene/schema/scene-render.xsd").read_bytes() == xsd.read_bytes()
    assert (tmp_root / "schema/SHA256SUMS").read_text() == release.sums_text()


TOOLS_LOG = "# Changelog\n\n## Unreleased\n\n### Breaking\n\n### Added\n\n### Fixed\n\n## 1.7.0 — 2026-10-12\n\n### Added\n\n- x\n"


@pytest.mark.parametrize("schema_classes,section,expected_ok", [
    ({"fixed": ["f"]}, "Added", True),
    ({"added": ["a"]}, "Added", True),
    ({"changed": ["c"], "added": ["a"]}, "Added", True),
    ({"breaking": ["b"]}, "Breaking", True),
    ({"removed": ["r"], "added": ["a"]}, "Breaking", True),
    ({"fixed": ["f"]}, "Fixed", False),
    ({"fixed": ["f"]}, "Breaking", False),
    ({"breaking": ["b"]}, "Added", False),
    ({"removed": ["r"]}, "Added", False),
])
def test_sdk_entry_class_follows_the_schema_change(schema_classes, section, expected_ok):
    text = TOOLS_LOG.replace(f"### {section}\n\n", f"### {section}\n\n- Regenerates `sr_core.scene`.\n\n", 1)
    problem = release.sdk_entry_problem(schema_classes, text)
    assert (problem is None) is expected_ok
    if not expected_ok:
        assert "sr_core.scene" in problem


def test_sdk_entry_must_mention_the_sdk():
    text = TOOLS_LOG.replace("### Added\n\n", "### Added\n\n- something else\n\n", 1)
    assert "no Unreleased entry that mentions sr_core.scene under Added" in release.sdk_entry_problem({"fixed": ["f"]}, text)


@pytest.fixture
def release_root(tmp_root, monkeypatch):
    (tmp_root / "sr_core").mkdir(exist_ok=True)
    (tmp_root / "sr_core/__init__.py").write_text('__version__ = "1.7.0"\n')
    schema_log = LOG.replace("1.4.2", "1.7.0")
    (tmp_root / "schema/CHANGELOG.md").write_text(schema_log)
    (tmp_root / "CHANGELOG.md").write_text(TOOLS_LOG)
    calls = []
    monkeypatch.setattr(release, "refresh_schema", lambda: calls.append("refresh"))
    return tmp_root, calls


def run_release(capsys):
    rc = release.main(["release", "schema", "--date", "2026-10-13"])
    return rc, capsys.readouterr().err


def test_release_schema_refused_without_an_sdk_entry(release_root, capsys):
    root, calls = release_root
    rc, err = run_release(capsys)
    assert rc == 2 and "mentions sr_core.scene" in err
    assert calls == [] and "## Unreleased" in (root / "schema/CHANGELOG.md").read_text()
    assert "1.7.1" not in (root / "schema/CHANGELOG.md").read_text()


def test_release_schema_refused_with_the_wrong_class(release_root, capsys):
    root, calls = release_root
    (root / "CHANGELOG.md").write_text(TOOLS_LOG.replace("### Fixed\n\n", "### Fixed\n\n- `sr_core.scene` regenerated\n\n", 1))
    rc, err = run_release(capsys)
    assert rc == 2 and "under Added" in err and "found under fixed" in err
    assert "1.7.1" not in (root / "schema/CHANGELOG.md").read_text()


def test_release_schema_allowed_with_the_right_class(release_root, capsys):
    root, calls = release_root
    (root / "CHANGELOG.md").write_text(TOOLS_LOG.replace("### Added\n\n", "### Added\n\n- `sr_core.scene` regenerated\n\n", 1))
    rc, err = run_release(capsys)
    assert rc == 0 and err == ""
    assert "## 1.7.1 — 2026-10-13" in (root / "schema/CHANGELOG.md").read_text()
    assert calls == ["refresh"]


def test_release_tools_needs_no_sdk_entry(release_root, capsys):
    root, _ = release_root
    (root / "CHANGELOG.md").write_text(TOOLS_LOG.replace("### Fixed\n\n", "### Fixed\n\n- a fix\n\n", 1))
    assert release.main(["release", "tools", "--date", "2026-10-13"]) == 0
