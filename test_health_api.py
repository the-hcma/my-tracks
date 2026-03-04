"""Tests for the /api/health/ endpoint and docker-entrypoint script."""

from pathlib import Path

import pytest
from hamcrest import (assert_that, contains_string, equal_to, has_key, is_,
                      not_none)
from rest_framework import status
from rest_framework.test import APIClient


class TestApiHealthEndpoint:
    """The /api/health/ endpoint must work without authentication."""

    @pytest.mark.django_db
    def test_returns_200_ok(self) -> None:
        client = APIClient()
        response = client.get("/api/health/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    @pytest.mark.django_db
    def test_returns_status_ok(self) -> None:
        client = APIClient()
        response = client.get("/api/health/")
        assert_that(response.json()["status"], equal_to("ok"))

    @pytest.mark.django_db
    def test_returns_version(self) -> None:
        client = APIClient()
        response = client.get("/api/health/")
        assert_that(response.json(), has_key("version"))
        assert_that(response.json()["version"], is_(not_none()))

    @pytest.mark.django_db
    def test_no_authentication_required(self) -> None:
        client = APIClient()
        response = client.get("/api/health/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    @pytest.mark.django_db
    def test_trailing_slash_optional(self) -> None:
        client = APIClient()
        response = client.get("/api/health")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


class TestDockerEntrypoint:
    """Validate the docker-entrypoint script structure."""

    def test_entrypoint_exists(self) -> None:
        entrypoint = Path(__file__).resolve().parent / "docker-entrypoint"
        assert_that(entrypoint.exists(), is_(True))

    def test_entrypoint_is_executable(self) -> None:
        import os
        entrypoint = Path(__file__).resolve().parent / "docker-entrypoint"
        assert_that(os.access(entrypoint, os.X_OK), is_(True))

    def test_entrypoint_has_bash_shebang(self) -> None:
        entrypoint = Path(__file__).resolve().parent / "docker-entrypoint"
        first_line = entrypoint.read_text().splitlines()[0]
        assert_that(first_line, contains_string("bash"))

    def test_entrypoint_runs_migrate(self) -> None:
        source = (Path(__file__).resolve().parent / "docker-entrypoint").read_text()
        assert_that(source, contains_string("manage.py migrate"))

    def test_entrypoint_starts_daphne(self) -> None:
        source = (Path(__file__).resolve().parent / "docker-entrypoint").read_text()
        assert_that(source, contains_string("daphne"))
        assert_that(source, contains_string("config.asgi:application"))

    def test_entrypoint_supports_skip_migrate(self) -> None:
        source = (Path(__file__).resolve().parent / "docker-entrypoint").read_text()
        assert_that(source, contains_string("--skip-migrate"))

    def test_entrypoint_validates_log_level(self) -> None:
        source = (Path(__file__).resolve().parent / "docker-entrypoint").read_text()
        assert_that(source, contains_string("Invalid log level"))


class TestDockerfile:
    """Validate the Dockerfile structure."""

    def test_dockerfile_exists(self) -> None:
        dockerfile = Path(__file__).resolve().parent / "Dockerfile"
        assert_that(dockerfile.exists(), is_(True))

    def test_dockerfile_has_three_stages(self) -> None:
        source = (Path(__file__).resolve().parent / "Dockerfile").read_text()
        assert_that(source, contains_string("AS frontend"))
        assert_that(source, contains_string("AS python-build"))
        assert_that(source, contains_string("AS runtime"))

    def test_dockerfile_uses_non_root_user(self) -> None:
        source = (Path(__file__).resolve().parent / "Dockerfile").read_text()
        assert_that(source, contains_string("USER app"))

    def test_dockerfile_has_healthcheck(self) -> None:
        source = (Path(__file__).resolve().parent / "Dockerfile").read_text()
        assert_that(source, contains_string("HEALTHCHECK"))
        assert_that(source, contains_string("/api/health/"))

    def test_dockerfile_exposes_correct_ports(self) -> None:
        source = (Path(__file__).resolve().parent / "Dockerfile").read_text()
        assert_that(source, contains_string("EXPOSE 8080 8883"))

    def test_dockerignore_exists(self) -> None:
        dockerignore = Path(__file__).resolve().parent / ".dockerignore"
        assert_that(dockerignore.exists(), is_(True))

    def test_dockerignore_excludes_venv(self) -> None:
        source = (Path(__file__).resolve().parent / ".dockerignore").read_text()
        assert_that(source, contains_string(".venv"))

    def test_dockerignore_excludes_node_modules(self) -> None:
        source = (Path(__file__).resolve().parent / ".dockerignore").read_text()
        assert_that(source, contains_string("node_modules"))

    def test_dockerignore_excludes_sqlite(self) -> None:
        source = (Path(__file__).resolve().parent / ".dockerignore").read_text()
        assert_that(source, contains_string("db.sqlite3"))
