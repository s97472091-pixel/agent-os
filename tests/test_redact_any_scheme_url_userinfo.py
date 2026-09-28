"""Issue #3432: redaction of URL userinfo must not be gated on a scheme list.

``_URL_USERINFO_RE`` previously matched ``https?://`` only. ``_DB_CONNSTR_RE``
lists five database schemes. Every other scheme handed its password to the model
verbatim -- ``ws``/``wss`` (a gateway URL with basic auth), ``ftp``, ``sftp``,
``ssh``, ``smtp``, ``ldap``, ``clickhouse``, ``mariadb`` and any future scheme.

A password in a URL's userinfo is a credential whatever the scheme in front of
it is, so the redaction-only pattern now matches the *structure* instead of a
scheme list. The scheme start is anchored with a negative lookbehind so a long
alphanumeric run cannot cause a quadratic scan.
"""

from __future__ import annotations

import time

import pytest

from agentos.redact import redact_sensitive_text

SECRET = "s3cr3t-pw"


@pytest.mark.parametrize(
    "url",
    [
        "wss://user:{pw}@gateway.host/ws",
        "ws://user:{pw}@gateway.host/ws",
        "ftp://user:{pw}@files.host/x",
        "sftp://user:{pw}@host/x",
        "ssh://user:{pw}@host",
        "smtp://user:{pw}@mail.host:587",
        "ldap://user:{pw}@directory.host",
        "clickhouse://user:{pw}@db:9000",
        "mariadb://user:{pw}@db",
        "mongodb+srv://user:{pw}@cluster.example.com/admin",
    ],
)
def test_a_password_is_masked_whatever_the_scheme(url: str) -> None:
    """The issue's repro, across the schemes the allowlist never named."""
    redacted = redact_sensitive_text(url.format(pw=SECRET), force=True)
    assert SECRET not in redacted
    assert "***" in redacted


@pytest.mark.parametrize(
    "url",
    [
        "redis://:{pw}@cache:6379/0",
        "amqp://:{pw}@broker:5672",
        "postgres://:{pw}@db:5432/app",
        "rediss://:{pw}@cache:6379",
        "wss://:{pw}@gateway.host/ws",
        "https://:{pw}@example.com/x",
    ],
)
def test_an_empty_username_still_masks_the_password(url: str) -> None:
    """Userinfo may carry no username, e.g. the canonical Redis URL."""
    assert SECRET not in redact_sensitive_text(url.format(pw=SECRET), force=True)


@pytest.mark.parametrize(
    "url",
    ["https://user:{pw}@host/x", "http://user:{pw}@host", "postgres://u:{pw}@db/app"],
)
def test_the_schemes_that_already_worked_still_do(url: str) -> None:
    redacted = redact_sensitive_text(url.format(pw=SECRET), force=True)
    assert SECRET not in redacted
    assert "***" in redacted


def test_the_host_and_scheme_survive_so_the_line_stays_readable() -> None:
    """Masking the secret must not cost the operator the diagnostic."""
    redacted = redact_sensitive_text(f"wss://user:{SECRET}@gateway.host:443/ws", force=True)
    assert redacted == "wss://user:***@gateway.host:443/ws"


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com:8080/path",  # a port, not a credential
        "http://host/a@b",  # an @ in the path
        "see http://plain.host/x for docs",
        "mailto:user@host",  # no ://
        "git+ssh://git@github.com/owner/repo.git",  # user, no password
        "key: value",
        "ratio 3:1 @ noon",
        "see https://example.com/docs, bob@example.com",
        "http://[::1]:8080/path",  # IPv6 host
        "ssh://user@[2001:db8::1]:22",  # IPv6 host with user, no password
    ],
)
def test_ordinary_text_is_not_touched(text: str) -> None:
    """A structural match is wider than a scheme list, so the boundary matters."""
    assert redact_sensitive_text(text, force=True) == text


def test_a_scheme_with_a_plus_or_dot_is_still_matched() -> None:
    """RFC 3986 scheme characters, so ``mongodb+srv`` and the like keep working."""
    redacted = redact_sensitive_text(f"mongodb+srv://user:{SECRET}@cluster/admin", force=True)
    assert SECRET not in redacted
    assert "mongodb+srv://" in redacted


def test_large_alphanumeric_run_does_not_quadratically_slow_redaction() -> None:
    """Regression for the anchored scheme start: an 80k run of hex-like chars
    plus one URL must stay fast. Without the anchor the scan is quadratic."""
    text = "a" * 80_000 + " http://user:secret@example.com/path"
    start = time.perf_counter()
    for _ in range(10):
        redact_sensitive_text(text, force=True)
    elapsed = (time.perf_counter() - start) / 10
    assert elapsed < 1.0  # generous; with anchor it is ~1 ms
