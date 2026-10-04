"""Certificate validity choices are clamped to the active CA's remaining lifetime."""

import re
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
import time_machine
from django.contrib.auth.models import User
from django.test import Client
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    greater_than,
    has_entries,
    is_,
    is_not,
    less_than,
    not_none,
)
from rest_framework import status
from rest_framework.test import APIClient

from app.pki import VALIDITY_PRESETS, ValidityChoice, validity_choices

ONE_YEAR_PRESET = 365
SHORT_CA_VALIDITY_DAYS = 500


def _create_ca(client: Client, validity_days: int) -> None:
    client.post(
        "/admin-panel/",
        {
            "form_type": "generate_ca",
            "ca_common_name": "Clamp Test CA",
            "ca_validity_days": str(validity_days),
            "ca_key_size": "2048",
        },
    )


def _validity_options(content: str, select_id: str) -> list[ValidityChoice]:
    """Parse the validity <select> with the given id into ValidityChoice values."""
    select = re.search(rf'<select name="[a-z_]+" id="{select_id}">(.*?)</select>', content, re.S)
    assert_that(select, is_(not_none()))
    return [
        ValidityChoice(
            days=int(match.group(1)),
            label=match.group(4),
            disabled=match.group(2) is not None,
            selected=match.group(3) is not None,
        )
        for match in re.finditer(
            r'<option value="(\d+)"( disabled)?( selected)?>(.*?)</option>', cast(re.Match[str], select).group(1)
        )
    ]


class TestValidityChoices:
    def test_every_preset_enabled_and_default_selected_when_ca_is_long_lived(self) -> None:
        choices = validity_choices(3650)

        assert_that([c.disabled for c in choices], equal_to([False] * len(VALIDITY_PRESETS)))
        assert_that([c.days for c in choices if c.selected], equal_to([1825]))

    def test_presets_beyond_maximum_are_disabled_and_default_is_clamped(self) -> None:
        choices = validity_choices(1000)

        assert_that([c.days for c in choices if c.disabled], equal_to([1095, 1460, 1825]))
        assert_that([c.days for c in choices if c.selected], equal_to([730]))

    def test_maximum_exactly_at_a_preset_keeps_that_preset_enabled(self) -> None:
        choices = validity_choices(1095)

        assert_that([c.days for c in choices if c.disabled], equal_to([1460, 1825]))
        assert_that([c.days for c in choices if c.selected], equal_to([1095]))

    @pytest.mark.parametrize("max_days", [0, 364])
    def test_nothing_selectable_below_smallest_preset(self, max_days: int) -> None:
        choices = validity_choices(max_days)

        assert_that(all(c.disabled for c in choices), is_(True))
        assert_that(any(c.selected for c in choices), is_(False))


@pytest.mark.django_db
class TestAdminPanelValidityClamp:
    def test_long_lived_ca_keeps_all_presets_and_five_year_default(self, admin_logged_in_client: Client) -> None:
        _create_ca(admin_logged_in_client, 3650)

        content = admin_logged_in_client.get("/admin-panel/").content.decode()

        for select_id in ("id_sc_validity_days", "id_cc_validity_days"):
            choices = _validity_options(content, select_id)
            assert_that(any(c.disabled for c in choices), is_(False))
            assert_that([c.days for c in choices if c.selected], equal_to([1825]))
        assert_that(content, is_not(contains_string("Renew the CA below")))
        assert_that(content, is_not(contains_string('class="submit-btn" disabled')))

    def test_short_lived_ca_disables_longer_presets_in_both_forms(self, admin_logged_in_client: Client) -> None:
        _create_ca(admin_logged_in_client, SHORT_CA_VALIDITY_DAYS)

        content = admin_logged_in_client.get("/admin-panel/").content.decode()

        for select_id in ("id_sc_validity_days", "id_cc_validity_days"):
            choices = _validity_options(content, select_id)
            assert_that([c.days for c in choices if not c.disabled], equal_to([ONE_YEAR_PRESET]))
            assert_that([c.days for c in choices if c.selected], equal_to([ONE_YEAR_PRESET]))
        assert_that(content, contains_string('data-testid="sc-validity-hint"'))
        assert_that(content, contains_string("expires in 49"))
        assert_that(content, is_not(contains_string("Renew the CA below")))

    def test_expired_ca_disables_everything_and_prompts_renewal(
        self, admin_logged_in_client: Client, admin_user: User
    ) -> None:
        _create_ca(admin_logged_in_client, SHORT_CA_VALIDITY_DAYS)
        expired_at = datetime.now(UTC) + timedelta(days=SHORT_CA_VALIDITY_DAYS + 30)

        with time_machine.travel(expired_at, tick=False):
            admin_logged_in_client.force_login(admin_user)
            content = admin_logged_in_client.get("/admin-panel/").content.decode()

        for select_id in ("id_sc_validity_days", "id_cc_validity_days"):
            choices = _validity_options(content, select_id)
            assert_that(all(c.disabled for c in choices), is_(True))
            assert_that(any(c.selected for c in choices), is_(False))
        assert_that(content, contains_string("at most 0 days"))
        assert_that(content, contains_string("Renew the CA below before issuing server certificates"))
        assert_that(content, contains_string("Renew the CA before issuing client certificates"))
        assert_that(
            re.search(r'<button type="submit" class="submit-btn" disabled[^>]*>Generate Server Certificate', content),
            is_(not_none()),
        )
        assert_that(
            re.search(r'<button type="submit" class="submit-btn" disabled>Issue Client Certificate', content),
            is_(not_none()),
        )


@pytest.mark.django_db
class TestCertificateAuthorityApiMaxValidity:
    def test_active_ca_reports_per_kind_maximum(self, admin_api_client: APIClient) -> None:
        admin_api_client.post(
            "/api/admin/pki/ca/", {"common_name": "API CA", "validity_days": 3650, "key_size": 2048}, format="json"
        )

        response = admin_api_client.get("/api/admin/pki/ca/")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.data[0]["max_validity_days"], has_entries(server=greater_than(1825), client=greater_than(1825))
        )

    def test_expired_ca_reports_zero(self, admin_api_client: APIClient, admin_user: User) -> None:
        admin_api_client.post(
            "/api/admin/pki/ca/", {"common_name": "API CA", "validity_days": 30, "key_size": 2048}, format="json"
        )
        expired_at = datetime.now(UTC) + timedelta(days=60)

        with time_machine.travel(expired_at, tick=False):
            admin_api_client.force_authenticate(admin_user)
            response = admin_api_client.get("/api/admin/pki/ca/")

        assert_that(response.data[0]["max_validity_days"], equal_to({"server": 0, "client": 0}))

    def test_short_lived_ca_maximum_is_below_its_lifetime(self, admin_api_client: APIClient) -> None:
        admin_api_client.post(
            "/api/admin/pki/ca/", {"common_name": "API CA", "validity_days": 100, "key_size": 2048}, format="json"
        )

        response = admin_api_client.get("/api/admin/pki/ca/")

        maximum = response.data[0]["max_validity_days"]
        assert_that(maximum["server"], less_than(101))
        assert_that(maximum["client"], greater_than(0))
