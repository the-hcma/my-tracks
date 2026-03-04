"""Tests for semantic versioning: get_version utility and release script."""

import importlib.machinery
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from hamcrest import (assert_that, calling, contains_string, equal_to,
                      greater_than, has_length, is_, is_not, matches_regexp,
                      not_none, raises, starts_with)

from my_tracks.utils import get_version

PROJECT_ROOT = Path(__file__).resolve().parent
RELEASE_SCRIPT = PROJECT_ROOT / "release"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

SEMVER_RE = r"^\d+\.\d+\.\d+$"


# ── get_version() utility ──────────────────────────────────────────────────


class TestGetVersion:
    """Tests for the get_version() helper in my_tracks.utils."""

    def test_returns_string(self) -> None:
        assert_that(get_version(), is_(not_none()))

    def test_matches_semver_pattern(self) -> None:
        assert_that(get_version(), matches_regexp(SEMVER_RE))

    def test_matches_pyproject_version(self) -> None:
        text = PYPROJECT.read_text()
        match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', text, re.MULTILINE)
        assert_that(match, is_(not_none()))
        assert_that(get_version(), equal_to(match.group(1)))  # type: ignore[union-attr]

    def test_returns_unknown_when_package_not_found(self) -> None:
        with patch("my_tracks.utils._get_pkg_version", side_effect=Exception("nope")):
            from importlib.metadata import PackageNotFoundError

            with patch(
                "my_tracks.utils._get_pkg_version",
                side_effect=PackageNotFoundError("fake"),
            ):
                assert_that(get_version(), equal_to("unknown"))


# ── pyproject.toml as single source of truth ────────────────────────────────


class TestPyprojectVersion:
    """Verify pyproject.toml contains a valid version."""

    def test_pyproject_exists(self) -> None:
        assert_that(PYPROJECT.exists(), is_(True))

    def test_version_field_present(self) -> None:
        text = PYPROJECT.read_text()
        assert_that(text, contains_string('version = "'))

    def test_version_is_semver(self) -> None:
        text = PYPROJECT.read_text()
        match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', text, re.MULTILINE)
        assert_that(match, is_(not_none()))


# ── Release script structure ────────────────────────────────────────────────


class TestReleaseScriptStructure:
    """Tests for the release script file properties."""

    def test_script_exists(self) -> None:
        assert_that(RELEASE_SCRIPT.exists(), is_(True))

    def test_script_is_executable(self) -> None:
        import os
        import stat

        mode = os.stat(RELEASE_SCRIPT).st_mode
        assert_that(bool(mode & stat.S_IXUSR), is_(True))

    def test_python_shebang(self) -> None:
        first_line = RELEASE_SCRIPT.read_text().splitlines()[0]
        assert_that(first_line, starts_with("#!/usr/bin/env python3"))

    def test_auto_venv_activation(self) -> None:
        text = RELEASE_SCRIPT.read_text()
        assert_that(text, contains_string("_activate_venv"))

    def test_uses_typer(self) -> None:
        text = RELEASE_SCRIPT.read_text()
        assert_that(text, contains_string("import typer"))

    def test_has_dry_run_flag(self) -> None:
        text = RELEASE_SCRIPT.read_text()
        assert_that(text, contains_string("--dry-run"))

    def test_has_skip_push_flag(self) -> None:
        text = RELEASE_SCRIPT.read_text()
        assert_that(text, contains_string("--skip-push"))


# ── Release script functional tests (via subprocess) ────────────────────────


class TestReleaseScriptFunctional:
    """Functional tests for the release script (using --dry-run)."""

    def _run_release(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RELEASE_SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )

    def test_help_flag(self) -> None:
        result = self._run_release("--help")
        assert_that(result.returncode, equal_to(0))
        assert_that(result.stdout, contains_string("Bump the project version"))

    def test_patch_dry_run(self) -> None:
        result = self._run_release("patch", "--dry-run")
        assert_that(result.returncode, equal_to(0))
        assert_that(result.stdout, contains_string("(dry run"))

    def test_minor_dry_run(self) -> None:
        result = self._run_release("minor", "--dry-run")
        assert_that(result.returncode, equal_to(0))
        assert_that(result.stdout, contains_string("minor"))

    def test_major_dry_run(self) -> None:
        result = self._run_release("major", "--dry-run")
        assert_that(result.returncode, equal_to(0))
        assert_that(result.stdout, contains_string("major"))

    def test_no_args_fails(self) -> None:
        result = self._run_release()
        assert_that(result.returncode, is_not(equal_to(0)))

    def test_invalid_part_fails(self) -> None:
        result = self._run_release("bogus")
        assert_that(result.returncode, is_not(equal_to(0)))


# ── Version bump logic (unit-level) ────────────────────────────────────────


def _load_release_module() -> object:
    """Load the release script as a Python module (extensionless file).

    Since tests run inside the venv already, _activate_venv is a no-op.
    """
    loader = importlib.machinery.SourceFileLoader("release_mod", str(RELEASE_SCRIPT))
    spec = importlib.util.spec_from_loader("release_mod", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestBumpLogic:
    """Test the _bump function directly by importing it."""

    def test_bump_patch(self) -> None:
        mod = _load_release_module()
        assert_that(mod._bump("1.2.3", mod.BumpPart.patch), equal_to("1.2.4"))  # type: ignore[attr-defined]

    def test_bump_minor(self) -> None:
        mod = _load_release_module()
        assert_that(mod._bump("1.2.3", mod.BumpPart.minor), equal_to("1.3.0"))  # type: ignore[attr-defined]

    def test_bump_major(self) -> None:
        mod = _load_release_module()
        assert_that(mod._bump("1.2.3", mod.BumpPart.major), equal_to("2.0.0"))  # type: ignore[attr-defined]

    def test_bump_from_zero(self) -> None:
        mod = _load_release_module()
        assert_that(mod._bump("0.0.0", mod.BumpPart.patch), equal_to("0.0.1"))  # type: ignore[attr-defined]
        assert_that(mod._bump("0.0.0", mod.BumpPart.minor), equal_to("0.1.0"))  # type: ignore[attr-defined]
        assert_that(mod._bump("0.0.0", mod.BumpPart.major), equal_to("1.0.0"))  # type: ignore[attr-defined]


# ── About page shows version ───────────────────────────────────────────────


class TestAboutPageVersion:
    """Verify the about template includes a version placeholder."""

    def test_about_template_contains_version_tag(self) -> None:
        template = PROJECT_ROOT / "web_ui" / "templates" / "web_ui" / "about.html"
        assert_that(template.exists(), is_(True))
        text = template.read_text()
        assert_that(text, contains_string("{{ version }}"))

    def test_about_view_passes_version_context(self) -> None:
        source = (PROJECT_ROOT / "web_ui" / "views.py").read_text()
        assert_that(source, contains_string("'version': get_version()"))
