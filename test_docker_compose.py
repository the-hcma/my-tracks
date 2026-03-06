"""Tests for Docker Compose stack and nginx configuration."""

from pathlib import Path

from hamcrest import (assert_that, contains_string, equal_to, has_item,
                      has_key, is_, is_not)

_ROOT = Path(__file__).resolve().parent


def _read(name: str) -> str:
    return (_ROOT / name).read_text()


class TestDockerCompose:
    """Validate docker-compose.yml structure (base file, no postgres)."""

    def test_compose_file_exists(self) -> None:
        assert_that((_ROOT / "docker-compose.yml").exists(), is_(True))

    def test_defines_my_tracks_service(self) -> None:
        assert_that(_read("docker-compose.yml"), contains_string("my-tracks:"))

    def test_defines_nginx_service(self) -> None:
        assert_that(_read("docker-compose.yml"), contains_string("nginx:"))

    def test_defines_certbot_service(self) -> None:
        assert_that(_read("docker-compose.yml"), contains_string("certbot:"))

    def test_certbot_is_optional_profile(self) -> None:
        source = _read("docker-compose.yml")
        assert_that(source, contains_string("profiles:"))
        assert_that(source, contains_string("- certbot"))

    def test_no_postgres_in_base(self) -> None:
        source = _read("docker-compose.yml")
        assert_that(source, is_not(contains_string("postgres:")))
        assert_that(source, is_not(contains_string("postgres-data:")))

    def test_no_database_url_in_base(self) -> None:
        assert_that(
            _read("docker-compose.yml"), is_not(contains_string("DATABASE_URL"))
        )

    def test_nginx_exposes_443(self) -> None:
        assert_that(_read("docker-compose.yml"), contains_string("443"))

    def test_nginx_exposes_8883(self) -> None:
        assert_that(_read("docker-compose.yml"), contains_string("8883"))

    def test_certs_volume_mounted(self) -> None:
        assert_that(_read("docker-compose.yml"), contains_string("/etc/nginx/certs"))

    def test_env_production_referenced(self) -> None:
        assert_that(_read("docker-compose.yml"), contains_string(".env.production"))


class TestDockerComposePostgres:
    """Validate docker-compose.postgres.yml (optional internal DB)."""

    def test_postgres_compose_file_exists(self) -> None:
        assert_that((_ROOT / "docker-compose.postgres.yml").exists(), is_(True))

    def test_defines_postgres_service(self) -> None:
        assert_that(
            _read("docker-compose.postgres.yml"), contains_string("postgres:")
        )

    def test_postgres_has_healthcheck(self) -> None:
        assert_that(
            _read("docker-compose.postgres.yml"), contains_string("pg_isready")
        )

    def test_my_tracks_depends_on_postgres(self) -> None:
        assert_that(
            _read("docker-compose.postgres.yml"), contains_string("service_healthy")
        )

    def test_postgres_data_volume_defined(self) -> None:
        assert_that(
            _read("docker-compose.postgres.yml"), contains_string("postgres-data:")
        )

    def test_database_url_uses_postgres(self) -> None:
        assert_that(
            _read("docker-compose.postgres.yml"), contains_string("postgresql://")
        )


class TestNginxConfig:
    """Validate nginx configuration."""

    def test_nginx_conf_exists(self) -> None:
        assert_that((_ROOT / "nginx" / "nginx.conf").exists(), is_(True))

    def test_proxy_params_exists(self) -> None:
        assert_that((_ROOT / "nginx" / "proxy_params").exists(), is_(True))

    def test_https_server_block(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("listen 443 ssl"))

    def test_http_to_https_redirect(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("return 301 https://"))

    def test_websocket_upgrade_headers(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("proxy_set_header Upgrade"))
        assert_that(source, contains_string("proxy_set_header Connection"))

    def test_mqtt_tls_stream_passthrough(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("stream {"))
        assert_that(source, contains_string("listen 8883"))
        assert_that(source, contains_string("proxy_pass my-tracks:8883"))

    def test_ssl_certificate_paths(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("/etc/nginx/certs/fullchain.pem"))
        assert_that(source, contains_string("/etc/nginx/certs/privkey.pem"))

    def test_login_rate_limiting(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("limit_req_zone"))
        assert_that(source, contains_string("limit_req zone=login"))

    def test_acme_challenge_location(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string(".well-known/acme-challenge"))

    def test_security_headers(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("X-Content-Type-Options"))
        assert_that(source, contains_string("X-Frame-Options"))
        assert_that(source, contains_string("Strict-Transport-Security"))

    def test_forwarded_proto_header(self) -> None:
        source = _read("nginx/proxy_params")
        assert_that(source, contains_string("X-Forwarded-Proto"))

    def test_tls_protocols(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("TLSv1.2"))
        assert_that(source, contains_string("TLSv1.3"))

    def test_mqtt_stream_rate_limiting(self) -> None:
        source = _read("nginx/nginx.conf")
        assert_that(source, contains_string("limit_conn_zone"))
        assert_that(source, contains_string("limit_conn mqtt"))


class TestEnvProductionExample:
    """Validate the production environment template."""

    def test_env_production_example_exists(self) -> None:
        assert_that((_ROOT / ".env.production.example").exists(), is_(True))

    def test_contains_secret_key(self) -> None:
        assert_that(_read(".env.production.example"), contains_string("SECRET_KEY="))

    def test_contains_debug_false(self) -> None:
        assert_that(_read(".env.production.example"), contains_string("DEBUG=False"))

    def test_contains_database_url(self) -> None:
        assert_that(_read(".env.production.example"), contains_string("DATABASE_URL="))

    def test_contains_postgres_password(self) -> None:
        assert_that(_read(".env.production.example"), contains_string("POSTGRES_PASSWORD="))

    def test_contains_allowed_hosts(self) -> None:
        assert_that(_read(".env.production.example"), contains_string("ALLOWED_HOSTS="))

    def test_contains_csrf_trusted_origins(self) -> None:
        assert_that(_read(".env.production.example"), contains_string("CSRF_TRUSTED_ORIGINS="))

    def test_contains_certs_dir(self) -> None:
        assert_that(_read(".env.production.example"), contains_string("CERTS_DIR"))
