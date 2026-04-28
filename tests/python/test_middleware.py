"""Tests for RequestLoggingMiddleware."""

import json
import logging
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory
from hamcrest import assert_that, equal_to

TRACE = 5


def _make_json_response(body: dict, status: int = 200):  # type: ignore[no-untyped-def]
    from django.http import HttpResponse
    return HttpResponse(
        json.dumps(body).encode(),
        content_type='application/json',
        status=status,
    )


def _make_plain_response(status: int = 200):  # type: ignore[no-untyped-def]
    from django.http import HttpResponse
    return HttpResponse(status=status)


@pytest.fixture()
def factory() -> RequestFactory:
    return RequestFactory()


@pytest.fixture()
def mock_logger() -> Generator[MagicMock, None, None]:
    with patch('app.middleware.logger') as m:
        yield m


class TestRequestLoggingMiddleware:
    """RequestLoggingMiddleware logs METHOD path -> status, plus JSON bodies when present."""

    # ── basic one-liner ───────────────────────────────────────────────────

    def test_logs_method_path_status(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_plain_response(200))
        mw(factory.get('/api/owntracks/'))
        mock_logger.log.assert_called_once()
        args = mock_logger.log.call_args[0]
        assert_that(args[0], equal_to(logging.DEBUG))
        assert 'GET' in args[1] % args[2:]
        assert '/api/owntracks/' in args[1] % args[2:]
        assert '200' in args[1] % args[2:]

    def test_health_check_logged_at_trace(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_plain_response(200))
        mw(factory.get('/health/'))
        level = mock_logger.log.call_args[0][0]
        assert_that(level, equal_to(TRACE))

    def test_non_health_logged_at_debug(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_plain_response(200))
        mw(factory.get('/some/path/'))
        level = mock_logger.log.call_args[0][0]
        assert_that(level, equal_to(logging.DEBUG))

    def test_post_non_json_status_logged(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_plain_response(201))
        mw(factory.post('/api/owntracks/'))
        args = mock_logger.log.call_args[0]
        msg = args[1] % args[2:]
        assert 'POST' in msg
        assert '201' in msg

    # ── request body ─────────────────────────────────────────────────────

    def test_json_request_body_included(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_plain_response(201))
        payload = {'_type': 'location', 'lat': 51.5}
        mw(factory.post(
            '/api/owntracks/',
            data=json.dumps(payload),
            content_type='application/json',
        ))
        args = mock_logger.log.call_args[0]
        msg = args[1] % args[2:]
        assert 'req:' in msg
        assert '_type' in msg
        assert 'resp:' not in msg

    def test_non_json_request_body_not_included(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_plain_response(200))
        mw(factory.post('/api/owntracks/', data='plain text', content_type='text/plain'))
        args = mock_logger.log.call_args[0]
        assert 'req:' not in args[1] % args[2:]

    # ── response body ─────────────────────────────────────────────────────

    def test_json_response_body_included(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_json_response({'id': 1, 'lat': 51.5}))
        mw(factory.get('/api/locations/'))
        args = mock_logger.log.call_args[0]
        msg = args[1] % args[2:]
        assert 'resp:' in msg
        assert '"id"' in msg
        assert 'req:' not in msg

    def test_non_json_response_body_not_included(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_plain_response(200))
        mw(factory.get('/api/locations/'))
        args = mock_logger.log.call_args[0]
        assert 'resp:' not in args[1] % args[2:]

    # ── both bodies ───────────────────────────────────────────────────────

    def test_both_bodies_included(self, factory: RequestFactory, mock_logger: MagicMock) -> None:
        from app.middleware import RequestLoggingMiddleware
        mw = RequestLoggingMiddleware(lambda r: _make_json_response({'result': 'ok'}, 201))
        mw(factory.post(
            '/api/owntracks/',
            data=json.dumps({'_type': 'location'}),
            content_type='application/json',
        ))
        args = mock_logger.log.call_args[0]
        msg = args[1] % args[2:]
        assert 'req:' in msg
        assert 'resp:' in msg
        assert '_type' in msg
        assert 'result' in msg

    # ── _compact_json helper ──────────────────────────────────────────────

    def test_compact_json_strips_whitespace(self) -> None:
        from app.middleware import _compact_json
        assert _compact_json(b'{"a": 1, "b": 2}') == '{"a":1,"b":2}'

    def test_compact_json_returns_raw_on_invalid(self) -> None:
        from app.middleware import _compact_json
        assert _compact_json(b'not json') == 'not json'
