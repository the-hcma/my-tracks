"""Tests for the deploy script."""

import subprocess
from pathlib import Path

from hamcrest import (assert_that, contains_string, equal_to, is_, is_not,
                      not_none)

_ROOT = Path(__file__).resolve().parent
_DEPLOY = _ROOT / "deploy"


def _read_deploy() -> str:
    return _DEPLOY.read_text()


class TestDeployScriptStructure:
    """Validate deploy script file properties."""

    def test_exists(self) -> None:
        assert_that(_DEPLOY.exists(), is_(True))

    def test_is_executable(self) -> None:
        import os
        assert_that(os.access(_DEPLOY, os.X_OK), is_(True))

    def test_has_bash_shebang(self) -> None:
        first_line = _read_deploy().splitlines()[0]
        assert_that(first_line, contains_string("bash"))

    def test_uses_strict_mode(self) -> None:
        assert_that(_read_deploy(), contains_string("set -euo pipefail"))

    def test_passes_shellcheck(self) -> None:
        result = subprocess.run(
            ["shellcheck", str(_DEPLOY)],
            capture_output=True, text=True,
        )
        assert_that(result.returncode, equal_to(0))


class TestDeployCommands:
    """Validate deploy script supports expected commands."""

    def test_supports_help_flag(self) -> None:
        assert_that(_read_deploy(), contains_string("--help"))

    def test_supports_update(self) -> None:
        assert_that(_read_deploy(), contains_string("--update"))

    def test_supports_backup(self) -> None:
        assert_that(_read_deploy(), contains_string("--backup"))

    def test_supports_status(self) -> None:
        assert_that(_read_deploy(), contains_string("--status"))

    def test_supports_stop(self) -> None:
        assert_that(_read_deploy(), contains_string("--stop"))

    def test_supports_logs(self) -> None:
        assert_that(_read_deploy(), contains_string("--logs"))

    def test_help_shows_usage(self) -> None:
        result = subprocess.run(
            [str(_DEPLOY), "--help"],
            capture_output=True, text=True,
        )
        assert_that(result.returncode, equal_to(0))
        assert_that(result.stdout, contains_string("Usage"))

    def test_unknown_flag_exits_nonzero(self) -> None:
        result = subprocess.run(
            [str(_DEPLOY), "--bogus"],
            capture_output=True, text=True,
        )
        assert_that(result.returncode, is_not(equal_to(0)))


class TestDeploySetupFeatures:
    """Validate setup logic is present."""

    def test_generates_secret_key(self) -> None:
        assert_that(_read_deploy(), contains_string("generate_secret"))
        assert_that(_read_deploy(), contains_string("SECRET_KEY"))

    def test_generates_postgres_password(self) -> None:
        assert_that(_read_deploy(), contains_string("POSTGRES_PASSWORD"))

    def test_creates_env_production(self) -> None:
        assert_that(_read_deploy(), contains_string(".env.production"))

    def test_creates_self_signed_cert(self) -> None:
        assert_that(_read_deploy(), contains_string("openssl req -x509"))

    def test_supports_bring_your_own_certs(self) -> None:
        assert_that(_read_deploy(), contains_string("fullchain.pem"))
        assert_that(_read_deploy(), contains_string("privkey.pem"))

    def test_runs_docker_compose_up(self) -> None:
        assert_that(_read_deploy(), contains_string("up -d"))

    def test_creates_admin_user(self) -> None:
        assert_that(_read_deploy(), contains_string("createsuperuser"))

    def test_checks_docker_prerequisite(self) -> None:
        assert_that(_read_deploy(), contains_string("check_prerequisites"))
        assert_that(_read_deploy(), contains_string("Docker is not installed"))

    def test_checks_docker_daemon_reachability(self) -> None:
        content = _read_deploy()
        assert_that(content, contains_string("docker info"))
        assert_that(content, contains_string("Docker daemon is not reachable"))

    def test_suggests_colima_on_macos(self) -> None:
        content = _read_deploy()
        assert_that(content, contains_string("colima start"))
        assert_that(content, contains_string("open -a Docker"))

    def test_suggests_systemctl_on_linux(self) -> None:
        content = _read_deploy()
        assert_that(content, contains_string("sudo systemctl start docker"))


class TestDeployBackup:
    """Validate backup functionality."""

    def test_uses_pg_dump(self) -> None:
        assert_that(_read_deploy(), contains_string("pg_dump"))

    def test_compresses_backup(self) -> None:
        assert_that(_read_deploy(), contains_string("gzip"))

    def test_timestamped_filename(self) -> None:
        assert_that(_read_deploy(), contains_string("mytracks-$timestamp"))


class TestDeployUpdate:
    """Validate update functionality."""

    def test_pulls_latest_images(self) -> None:
        assert_that(_read_deploy(), contains_string("pull"))

    def test_runs_migrations(self) -> None:
        assert_that(_read_deploy(), contains_string("migrate"))
