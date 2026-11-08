"""Tests for the temp-layout re-exec prologue of the ``.github/ci`` wrappers (repository-helpers#832)."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_, less_than, not_

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CI_DIR = _REPO_ROOT / ".github" / "ci"
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_ACTION_PIN = "the-hcma/repository-helpers/actions/setup-tmp-layout@bfee0e1f2d682e83c6207a0d6a0f7feefa576fd8"
_WRAPPER_MARKERS = (".github/ci/uv-run", ".github/ci/pnpm-run", ".github/ci/pytest-run", 'with-tmp-layout"')
# Wrapper -> tool chain the layout helper is asked for.
_CHAINS = {
    "pnpm-run": "pnpm",
    "pytest-run": "uv pytest",
    "python-static": "uv",
    "setup-python": "uv",
    "uv-run": "uv",
}


@dataclass(frozen=True)
class _Run:
    returncode: int
    stderr: str
    stdout: str


def _run(
    tmp_path: Path,
    wrapper: str,
    args: list[str],
    *,
    helpers: bool,
    github_actions: bool = False,
    in_layout: bool = False,
) -> _Run:
    """Run a wrapper with stub tools; ``helpers`` installs a stub with-tmp-layout that logs its argv."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("uv", "pnpm"):
        stub = bin_dir / tool
        stub.write_text(f'#!/usr/bin/env bash\necho "{tool} $*"\n')
        stub.chmod(0o755)
    helper_dir = tmp_path / "helpers"
    (helper_dir / "scripts" / "dev").mkdir(parents=True)
    if helpers:
        layout = helper_dir / "scripts" / "dev" / "with-tmp-layout"
        # Log the request, then run the command the way the real helper does (after the `--`).
        layout.write_text('#!/usr/bin/env bash\necho "layout $1" >&2\nshift 2\nexec "$@"\n')
        layout.chmod(0o755)
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPOSITORY_HELPERS_DIR": str(helper_dir),
    }
    if github_actions:
        env["GITHUB_ACTIONS"] = "true"
    if in_layout:
        env["CI_TMP_LAYOUT"] = "1"
    result = subprocess.run(
        ["bash", str(_CI_DIR / wrapper), *args],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return _Run(result.returncode, result.stderr, result.stdout)


@pytest.mark.parametrize("wrapper", sorted(_CHAINS))
def test_wrapper_declares_the_layout_prologue(wrapper: str) -> None:
    """Wrapper declares the layout prologue."""
    text = (_CI_DIR / wrapper).read_text()
    assert_that(text, contains_string("CI_TMP_LAYOUT"))
    assert_that(text, contains_string("with-tmp-layout"))
    assert_that(text, contains_string("setup-tmp-layout action step"))


@pytest.mark.parametrize("wrapper", ["pnpm-run", "pytest-run", "uv-run"])
def test_ci_without_the_layout_helper_fails_with_a_pointer_to_the_action(tmp_path: Path, wrapper: str) -> None:
    """Ci without the layout helper fails with a pointer to the action."""
    run = _run(tmp_path, wrapper, ["pnpm", "--version"], helpers=False, github_actions=True)
    assert_that(run.returncode, is_(1))
    assert_that(run.stderr, contains_string("setup-tmp-layout"))
    assert_that(run.stdout, equal_to(""))


def test_uv_run_without_helpers_outside_ci_runs_the_command_unchanged(tmp_path: Path) -> None:
    """Uv run without helpers outside ci runs the command unchanged."""
    run = _run(tmp_path, "uv-run", ["uv", "sync"], helpers=False)
    assert_that(run.returncode, is_(0))
    assert_that(run.stdout, equal_to("uv sync\n"))


def test_pnpm_run_without_helpers_outside_ci_runs_the_command_unchanged(tmp_path: Path) -> None:
    """Pnpm run without helpers outside ci runs the command unchanged."""
    run = _run(tmp_path, "pnpm-run", ["pnpm", "run", "build"], helpers=False)
    assert_that(run.returncode, is_(0))
    assert_that(run.stdout, equal_to("pnpm run build\n"))


def test_pytest_run_without_helpers_outside_ci_passes_arguments_to_uv_run_pytest(tmp_path: Path) -> None:
    """Pytest run without helpers outside ci passes arguments to uv run pytest."""
    run = _run(tmp_path, "pytest-run", ["--cov=app"], helpers=False)
    assert_that(run.returncode, is_(0))
    assert_that(run.stdout, equal_to("uv run pytest --cov=app\n"))


def test_uv_run_with_helpers_re_execs_through_the_uv_layout(tmp_path: Path) -> None:
    """Uv run with helpers re execs through the uv layout."""
    run = _run(tmp_path, "uv-run", ["uv", "sync"], helpers=True)
    assert_that(run.returncode, is_(0))
    assert_that(run.stderr, contains_string("layout uv"))
    assert_that(run.stdout, equal_to("uv sync\n"))


def test_pnpm_run_with_helpers_re_execs_through_the_pnpm_layout(tmp_path: Path) -> None:
    """Pnpm run with helpers re execs through the pnpm layout."""
    run = _run(tmp_path, "pnpm-run", ["pnpm", "run", "build"], helpers=True)
    assert_that(run.returncode, is_(0))
    assert_that(run.stderr, contains_string("layout pnpm"))
    assert_that(run.stdout, equal_to("pnpm run build\n"))


def test_pytest_run_with_helpers_nests_the_uv_and_pytest_layouts(tmp_path: Path) -> None:
    """Pytest run with helpers nests the uv and pytest layouts."""
    run = _run(tmp_path, "pytest-run", ["-k", "x"], helpers=True)
    assert_that(run.returncode, is_(0))
    assert_that(run.stderr, contains_string("layout uv"))
    assert_that(run.stderr, contains_string("layout pytest"))
    assert_that(run.stdout, equal_to("uv run pytest -k x\n"))


def test_wrapper_already_inside_the_layout_does_not_re_exec(tmp_path: Path) -> None:
    """Wrapper already inside the layout does not re exec."""
    run = _run(tmp_path, "uv-run", ["uv", "sync"], helpers=True, in_layout=True)
    assert_that(run.returncode, is_(0))
    assert_that(run.stderr, not_(contains_string("layout")))


@pytest.mark.parametrize("workflow", ["ci.yml", "cve-check.yml"])
def test_workflow_pins_setup_tmp_layout_by_full_sha_before_the_first_wrapper_use(workflow: str) -> None:
    """Workflow pins setup tmp layout by full sha before the first wrapper use."""
    text = (_WORKFLOWS_DIR / workflow).read_text()
    assert_that(text, contains_string(_ACTION_PIN))
    for job_text in re.split(r"\n  (?=[\w-]+:\n)", text)[1:]:
        uses = [job_text.find(marker) for marker in _WRAPPER_MARKERS if marker in job_text]
        if uses:
            assert_that(job_text, contains_string("setup-tmp-layout"))
            assert_that(job_text.index("setup-tmp-layout"), less_than(min(uses)))
