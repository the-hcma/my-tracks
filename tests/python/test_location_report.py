"""Tests for report vs fix time helpers."""

from datetime import UTC, datetime
from decimal import Decimal

from hamcrest import assert_that, contains_string, equal_to, is_
from pytest import mark

from app.location_report import (
    location_fix_age_seconds,
    location_is_newer_report,
    location_report_log_fragment,
    location_report_log_fragment_from_location,
    location_report_log_fragment_from_mapping,
    location_reported_at,
    location_reported_at_unix,
)
from app.models import Device, Location


@mark.django_db
def test_location_reported_at_prefers_owntracks_created_at() -> None:
    device = Device.objects.create(device_id="phone")
    fix = datetime(2026, 6, 30, 12, 9, 0, tzinfo=UTC)
    reported = datetime(2026, 6, 30, 14, 1, 0, tzinfo=UTC)
    location = Location.objects.create(
        device=device,
        latitude=Decimal("51.0"),
        longitude=Decimal("-0.1"),
        timestamp=fix,
        owntracks_created_at=reported,
        received_via="mqtt",
    )
    assert_that(location_reported_at(location), equal_to(reported))
    assert_that(location_reported_at_unix(location), equal_to(int(reported.timestamp())))


@mark.django_db
def test_location_reported_at_falls_back_to_received_at() -> None:
    device = Device.objects.create(device_id="phone")
    fix = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
    received = datetime(2026, 6, 30, 14, 0, 0, tzinfo=UTC)
    location = Location.objects.create(
        device=device,
        latitude=Decimal("51.0"),
        longitude=Decimal("-0.1"),
        timestamp=fix,
        received_via="mqtt",
    )
    Location.objects.filter(pk=location.pk).update(received_at=received)
    location.refresh_from_db()
    assert_that(location.owntracks_created_at, is_(None))
    assert_that(location_reported_at(location), equal_to(received))


@mark.django_db
def test_location_fix_age_seconds() -> None:
    device = Device.objects.create(device_id="phone")
    fix = datetime(2026, 6, 30, 12, 9, 0, tzinfo=UTC)
    reported = datetime(2026, 6, 30, 14, 1, 0, tzinfo=UTC)
    location = Location.objects.create(
        device=device,
        latitude=Decimal("51.0"),
        longitude=Decimal("-0.1"),
        timestamp=fix,
        owntracks_created_at=reported,
        received_via="mqtt",
    )
    assert_that(location_fix_age_seconds(location), equal_to(6720))


@mark.django_db
def test_location_is_newer_report_ignores_higher_tst_when_report_is_older() -> None:
    device = Device.objects.create(device_id="phone")
    older_fix = datetime(2026, 6, 30, 10, 0, 0, tzinfo=UTC)
    newer_fix = datetime(2026, 6, 30, 12, 9, 0, tzinfo=UTC)
    report_old_fix = datetime(2026, 6, 30, 14, 1, 0, tzinfo=UTC)
    high_tst = Location.objects.create(
        device=device,
        latitude=Decimal("51.0"),
        longitude=Decimal("-0.1"),
        timestamp=newer_fix,
        owntracks_created_at=newer_fix,
        received_via="mqtt",
    )
    ping = Location.objects.create(
        device=device,
        latitude=Decimal("51.0"),
        longitude=Decimal("-0.1"),
        timestamp=older_fix,
        owntracks_created_at=report_old_fix,
        trigger="p",
        received_via="mqtt",
    )
    assert_that(location_is_newer_report(ping, high_tst), is_(True))
    assert_that(location_is_newer_report(high_tst, ping), is_(False))


@mark.django_db
def test_location_report_log_fragment_from_location() -> None:
    device = Device.objects.create(device_id="phone")
    fix = datetime(2026, 6, 30, 12, 9, 0, tzinfo=UTC)
    reported = datetime(2026, 6, 30, 14, 1, 0, tzinfo=UTC)
    location = Location.objects.create(
        device=device,
        latitude=Decimal("51.0"),
        longitude=Decimal("-0.1"),
        timestamp=fix,
        owntracks_created_at=reported,
        received_via="mqtt",
    )
    fragment = location_report_log_fragment_from_location(location)
    assert_that(fragment, contains_string("report_at="))
    assert_that(fragment, contains_string("fix_at="))


@mark.django_db
def test_location_report_log_fragment_from_mapping() -> None:
    fragment = location_report_log_fragment_from_mapping(
        {
            "timestamp_unix": int(datetime(2026, 6, 30, 12, 9, 0, tzinfo=UTC).timestamp()),
            "reported_at_unix": int(datetime(2026, 6, 30, 14, 1, 0, tzinfo=UTC).timestamp()),
        }
    )
    assert_that(fragment, contains_string("report_at="))
    assert_that(fragment, contains_string("fix_at="))
