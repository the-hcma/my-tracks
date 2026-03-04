"""Tests for database configuration via DATABASE_URL."""

from unittest.mock import patch

import dj_database_url
import pytest
from hamcrest import (assert_that, contains_string, equal_to, greater_than,
                      has_entry, has_key, is_, not_none)


class TestDjDatabaseUrlParsing:
    """Verify dj-database-url parses common URL schemes correctly."""

    def test_sqlite_url_uses_sqlite_engine(self) -> None:
        result = dj_database_url.parse("sqlite:///path/to/db.sqlite3")
        assert_that(result["ENGINE"], equal_to("django.db.backends.sqlite3"))

    def test_sqlite_url_extracts_name(self) -> None:
        result = dj_database_url.parse("sqlite:///path/to/db.sqlite3")
        assert_that(result["NAME"], equal_to("path/to/db.sqlite3"))

    def test_postgresql_url_uses_postgresql_engine(self) -> None:
        result = dj_database_url.parse("postgresql://u:p@host:5432/mydb")
        assert_that(result["ENGINE"], equal_to("django.db.backends.postgresql"))

    def test_postgresql_url_extracts_credentials(self) -> None:
        result = dj_database_url.parse("postgresql://myuser:secret@db.example.com:5432/mytracks")
        assert_that(result["USER"], equal_to("myuser"))
        assert_that(result["PASSWORD"], equal_to("secret"))
        assert_that(result["HOST"], equal_to("db.example.com"))
        assert_that(result["PORT"], equal_to(5432))
        assert_that(result["NAME"], equal_to("mytracks"))

    def test_conn_max_age_applied(self) -> None:
        result = dj_database_url.parse("sqlite:///db.sqlite3", conn_max_age=600)
        assert_that(result["CONN_MAX_AGE"], equal_to(600))

    def test_conn_health_checks_applied(self) -> None:
        result = dj_database_url.parse("sqlite:///db.sqlite3", conn_health_checks=True)
        assert_that(result["CONN_HEALTH_CHECKS"], is_(True))


class TestDatabaseSettingsIntegration:
    """Verify config/settings.py wires DATABASE_URL correctly."""

    def test_default_is_sqlite_when_database_url_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("DATABASE_URL", None)
            result = dj_database_url.config(
                default="sqlite:///fallback.sqlite3",
                conn_max_age=600,
                conn_health_checks=True,
            )
        assert_that(result["ENGINE"], equal_to("django.db.backends.sqlite3"))
        assert_that(result["CONN_MAX_AGE"], equal_to(600))
        assert_that(result["CONN_HEALTH_CHECKS"], is_(True))

    def test_postgresql_used_when_database_url_set(self) -> None:
        pg_url = "postgresql://user:pass@pghost:5432/mytracks"
        with patch.dict("os.environ", {"DATABASE_URL": pg_url}):
            result = dj_database_url.config(
                default="sqlite:///fallback.sqlite3",
                conn_max_age=600,
                conn_health_checks=True,
            )
        assert_that(result["ENGINE"], equal_to("django.db.backends.postgresql"))
        assert_that(result["HOST"], equal_to("pghost"))
        assert_that(result["NAME"], equal_to("mytracks"))
        assert_that(result["CONN_MAX_AGE"], equal_to(600))
        assert_that(result["CONN_HEALTH_CHECKS"], is_(True))

    def test_database_url_overrides_default(self) -> None:
        mysql_url = "mysql://user:pass@mysqlhost:3306/mydb"
        with patch.dict("os.environ", {"DATABASE_URL": mysql_url}):
            result = dj_database_url.config(
                default="sqlite:///fallback.sqlite3",
            )
        assert_that(result["ENGINE"], contains_string("mysql"))

    @pytest.mark.django_db
    def test_django_settings_database_is_configured(self) -> None:
        from django.conf import settings
        db_config = settings.DATABASES["default"]
        assert_that(db_config, has_key("ENGINE"))
        assert_that(db_config["ENGINE"], is_(not_none()))
        assert_that(db_config, has_key("CONN_MAX_AGE"))
        assert_that(db_config["CONN_MAX_AGE"], equal_to(600))
        assert_that(db_config, has_key("CONN_HEALTH_CHECKS"))
        assert_that(db_config["CONN_HEALTH_CHECKS"], is_(True))

    def test_sqlite_default_url_contains_db_sqlite3(self) -> None:
        from config.settings import _SQLITE_DEFAULT
        assert_that(_SQLITE_DEFAULT, contains_string("db.sqlite3"))
