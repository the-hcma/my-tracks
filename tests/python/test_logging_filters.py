"""Tests for custom logging filters in config.settings."""

import logging

import pytest
from hamcrest import assert_that, equal_to, is_


def _make_record(
    msg: str,
    args: tuple[object, ...] = (),
    level: int = logging.WARNING,
    status_code: int | None = None,
) -> logging.LogRecord:
    """Create a minimal LogRecord for filter testing."""
    record = logging.LogRecord(
        name='django.request',
        level=level,
        pathname='',
        lineno=0,
        msg=msg,
        args=args,
        exc_info=None,
    )
    if status_code is not None:
        record.status_code = status_code
    return record


class TestWebSocketNotFoundFilter:
    """WebSocketNotFoundFilter downgrades HTTP 404s on /ws/ paths to INFO."""

    @pytest.fixture()
    def f(self):  # type: ignore[no-untyped-def]
        from config.settings import WebSocketNotFoundFilter
        return WebSocketNotFoundFilter()

    # ── passes through unrelated records ──────────────────────────────────

    def test_non_404_record_unchanged(self, f) -> None:  # type: ignore[no-untyped-def]
        """Non-404 records are not modified."""
        record = _make_record('%s: %s', ('Internal Server Error', '/ws/locations/'), status_code=500)
        result = f.filter(record)
        assert_that(result, is_(True))
        assert_that(record.levelno, equal_to(logging.WARNING))

    def test_non_ws_404_unchanged(self, f) -> None:  # type: ignore[no-untyped-def]
        """404 for a non-WebSocket path is not modified."""
        record = _make_record('%s: %s', ('Not Found', '/api/missing/'), status_code=404)
        result = f.filter(record)
        assert_that(result, is_(True))
        assert_that(record.levelno, equal_to(logging.WARNING))
        assert_that(record.msg, equal_to('%s: %s'))

    def test_record_without_status_code_unchanged(self, f) -> None:  # type: ignore[no-untyped-def]
        """Records without a status_code attribute are not modified."""
        record = _make_record('%s: %s', ('Not Found', '/ws/locations/'))
        result = f.filter(record)
        assert_that(result, is_(True))
        assert_that(record.levelno, equal_to(logging.WARNING))

    # ── downgrades /ws/ 404s ───────────────────────────────────────────────

    def test_ws_locations_404_downgraded_to_info(self, f) -> None:  # type: ignore[no-untyped-def]
        """404 on /ws/locations/ is downgraded from WARNING to INFO."""
        record = _make_record('%s: %s', ('Not Found', '/ws/locations/'), status_code=404)
        result = f.filter(record)
        assert_that(result, is_(True))
        assert_that(record.levelno, equal_to(logging.INFO))
        assert_that(record.levelname, equal_to('INFO'))

    def test_ws_404_message_updated(self, f) -> None:  # type: ignore[no-untyped-def]
        """Message is updated to explain the WebSocket-only endpoint."""
        record = _make_record('%s: %s', ('Not Found', '/ws/locations/'), status_code=404)
        f.filter(record)
        assert_that(record.args, equal_to(('/ws/locations/',)))
        assert_that('WebSocket' in record.msg, is_(True))
        assert_that('HTTP' in record.msg, is_(True))

    def test_ws_subpath_404_downgraded(self, f) -> None:  # type: ignore[no-untyped-def]
        """Any path starting with /ws/ is covered, not just /ws/locations/."""
        record = _make_record('%s: %s', ('Not Found', '/ws/other/'), status_code=404)
        result = f.filter(record)
        assert_that(result, is_(True))
        assert_that(record.levelno, equal_to(logging.INFO))

    def test_filter_always_returns_true(self, f) -> None:  # type: ignore[no-untyped-def]
        """The filter never suppresses records — it only rewrites them."""
        for path, code in [
            ('/ws/locations/', 404),
            ('/api/missing/', 404),
            ('/ws/locations/', 500),
        ]:
            record = _make_record('%s: %s', ('Not Found', path), status_code=code)
            assert_that(f.filter(record), is_(True))
