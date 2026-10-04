"""Tests for SMTP backend construction and message delivery in app.notifications."""

import warnings
from unittest.mock import MagicMock

from django.core.mail import InvalidMailer
from django.utils.deprecation import RemovedInDjango70Warning
from hamcrest import assert_that, calling, equal_to, has_length, is_, not_none, raises

from app.notifications import SMTP_MAILER_ALIAS, build_smtp_backend, send_test_email_via_backend


def test_build_smtp_backend_uses_explicit_options_without_deprecation_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", RemovedInDjango70Warning)
        backend = build_smtp_backend(
            host="smtp.example.com",
            port=587,
            username="user",
            password="secret",
            use_tls=True,
            use_ssl=False,
        )

    assert_that(backend.alias, equal_to(SMTP_MAILER_ALIAS))
    assert_that(backend.host, equal_to("smtp.example.com"))
    assert_that(backend.port, equal_to(587))
    assert_that(backend.username, equal_to("user"))
    assert_that(backend.password, equal_to("secret"))
    assert_that(backend.use_tls, is_(True))
    assert_that(backend.use_ssl, is_(False))
    assert_that(backend.timeout, equal_to(10))


def test_build_smtp_backend_rejects_tls_and_ssl_together() -> None:
    assert_that(
        calling(build_smtp_backend).with_args(
            host="smtp.example.com", port=587, username="", password="", use_tls=True, use_ssl=True
        ),
        raises(InvalidMailer),
    )


def test_send_test_email_via_backend_sends_through_backend_without_deprecation_warning() -> None:
    backend = MagicMock()

    with warnings.catch_warnings():
        warnings.simplefilter("error", RemovedInDjango70Warning)
        send_test_email_via_backend("out@example.com", backend, "noreply@my-tracks")

    backend.send_messages.assert_called_once()
    (messages,) = backend.send_messages.call_args.args
    assert_that(messages, has_length(1))
    assert_that(messages[0].to, equal_to(["out@example.com"]))
    assert_that(messages[0].from_email, equal_to("noreply@my-tracks"))
    assert_that(messages[0], is_(not_none()))
