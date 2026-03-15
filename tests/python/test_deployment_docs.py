"""Tests for DEPLOYMENT.md documentation completeness and accuracy."""

from pathlib import Path

from hamcrest import assert_that, contains_string, greater_than, is_, not_none

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOYMENT_MD = PROJECT_ROOT / "docs" / "DEPLOYMENT.md"


class TestDeploymentDocExists:
    """Basic file-level checks."""

    def test_file_exists(self) -> None:
        assert_that(DEPLOYMENT_MD.exists(), is_(True))

    def test_file_is_not_empty(self) -> None:
        assert_that(len(DEPLOYMENT_MD.read_text()), greater_than(1000))


class TestArchitectureSection:
    """The doc should describe the container architecture."""

    def test_has_architecture_heading(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("## Architecture"))

    def test_describes_nginx(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("nginx"))

    def test_describes_postgres(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("postgres"))

    def test_describes_my_tracks_container(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("ghcr.io/the-hcma/my-tracks"))

    def test_describes_port_443(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("443"))

    def test_describes_port_8883(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("8883"))


class TestPrerequisites:
    """Must document what's needed before deployment."""

    def test_mentions_docker(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Docker"))

    def test_mentions_compose(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Compose"))


class TestQuickStart:
    """Must have a quick start section with the deploy command."""

    def test_has_quick_start_heading(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("## Quick Start"))

    def test_mentions_deploy_command(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("scripts/deploy"))


class TestConfigurationReference:
    """Must document all environment variables."""

    def test_has_configuration_heading(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("## Configuration Reference"))

    def test_documents_secret_key(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("SECRET_KEY"))

    def test_documents_allowed_hosts(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("ALLOWED_HOSTS"))

    def test_documents_csrf_trusted_origins(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("CSRF_TRUSTED_ORIGINS"))

    def test_documents_postgres_password(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("POSTGRES_PASSWORD"))

    def test_documents_debug(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("DEBUG"))

    def test_documents_certs_dir(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("CERTS_DIR"))

    def test_documents_command_api_key(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("COMMAND_API_KEY"))


class TestTlsCertificates:
    """Must document TLS certificate options."""

    def test_has_tls_section(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("## TLS Certificates (HTTPS)"))

    def test_documents_self_signed(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Self-Signed"))

    def test_documents_lets_encrypt(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Let's Encrypt"))

    def test_documents_bring_your_own(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Bring Your Own"))

    def test_mentions_fullchain_pem(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("fullchain.pem"))

    def test_mentions_privkey_pem(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("privkey.pem"))

    def test_certbot_command(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("certbot certonly"))

    def test_distinguishes_https_from_mqtt_tls(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("**not** related to MQTT over TLS"))


class TestOperations:
    """Must document day-to-day operations."""

    def test_documents_update(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("--update"))

    def test_documents_backup(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("--backup"))

    def test_documents_restore(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Restore from Backup"))

    def test_documents_logs(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("--logs"))

    def test_documents_status(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("--status"))

    def test_documents_stop(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("--stop"))


class TestSemverSection:
    """Must document the release workflow."""

    def test_has_releasing_section(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Releasing New Versions"))

    def test_documents_release_script(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("scripts/release"))

    def test_documents_dry_run(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("--dry-run"))

    def test_documents_version_bump_types(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("patch"))
        assert_that(text, contains_string("minor"))
        assert_that(text, contains_string("major"))


class TestNetworkAndFirewall:
    """Must include firewall guidance."""

    def test_has_firewall_section(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("## Network & Firewall"))

    def test_documents_centos_firewalld(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("firewall-cmd"))

    def test_documents_ubuntu_ufw(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("ufw"))


class TestHealthCheck:
    """Must document the health endpoint."""

    def test_has_health_check_section(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("## Health Check"))

    def test_documents_health_endpoint(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("/api/health/"))


class TestOwnTracksConfig:
    """Must document OwnTracks client configuration."""

    def test_has_owntracks_section(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("OwnTracks Client"))

    def test_documents_mqtt_mode(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("MQTT Mode"))

    def test_documents_http_mode(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("HTTP Mode"))

    def test_documents_protocol_level(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("mqttProtocolLevel"))


class TestTroubleshooting:
    """Must have troubleshooting guidance."""

    def test_has_troubleshooting_section(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("## Troubleshooting"))

    def test_covers_container_startup(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Container Won't Start"))

    def test_covers_502_error(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("502 Bad Gateway"))

    def test_covers_mqtt_issues(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("MQTT Clients Can't Connect"))

    def test_covers_database_issues(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Database Connection Errors"))

    def test_covers_certificate_issues(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Certificate Issues"))


class TestBareMetal:
    """Should mention bare metal as an alternative."""

    def test_has_bare_metal_section(self) -> None:
        text = DEPLOYMENT_MD.read_text()
        assert_that(text, contains_string("Bare Metal"))
