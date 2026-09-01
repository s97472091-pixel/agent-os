"""Transient-HTTP retries on the Slack adapter's outbound calls.

``retry_request`` (``agentos.channels._util``) already backs every Discord
call site; these tests pin the same behaviour for Slack — 429/5xx/read
timeouts are retried, and a fatal 4xx is returned on the first attempt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agentos.channels._util import _parse_retry_after, retry_request
from agentos.channels.slack import SlackChannel
from agentos.channels.types import OutgoingMessage

_REQUEST = httpx.Request("POST", "https://slack.test/api")


def _resp(
    status_code: int = 200,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body if body is not None else {"ok": True, "ts": "1.0"},
        headers=headers,
        request=_REQUEST,
    )


def _channel() -> SlackChannel:
    return SlackChannel(token="xoxb-test", slack_channel_id="C123")


def _attach(channel: SlackChannel, *responses: Any) -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock(side_effect=list(responses))
    channel._client = client
    return client.post


@pytest.fixture
def no_sleep():
    """Collapse ``retry_request``'s backoff so the assertions stay fast."""
    with patch("agentos.channels._util.asyncio.sleep", new=AsyncMock()) as sleep:
        yield sleep


async def test_send_retries_server_error_then_succeeds(no_sleep) -> None:
    channel = _channel()
    post = _attach(channel, _resp(503), _resp(200))

    await channel.send(OutgoingMessage(content="hi", reply_to="C123"))

    assert post.await_count == 2


async def test_send_retries_rate_limit_honouring_retry_after(no_sleep) -> None:
    channel = _channel()
    post = _attach(channel, _resp(429, headers={"Retry-After": "2"}), _resp(200))

    await channel.send(OutgoingMessage(content="hi", reply_to="C123"))

    assert post.await_count == 2
    no_sleep.assert_awaited_once_with(2.0)


async def test_send_does_not_retry_fatal_client_error(no_sleep) -> None:
    channel = _channel()
    post = _attach(channel, _resp(401, {"ok": False, "error": "invalid_auth"}))

    with pytest.raises(httpx.HTTPStatusError):
        await channel.send(OutgoingMessage(content="hi", reply_to="C123"))

    assert post.await_count == 1
    no_sleep.assert_not_awaited()


async def test_send_retries_read_timeout_then_succeeds(no_sleep) -> None:
    """Read timeouts are retried, accepting the duplicate-post risk Discord takes."""
    channel = _channel()
    post = _attach(channel, httpx.ReadTimeout("slow"), _resp(200))

    await channel.send(OutgoingMessage(content="hi", reply_to="C123"))

    assert post.await_count == 2


async def test_send_raises_after_retries_are_exhausted(no_sleep) -> None:
    channel = _channel()
    post = _attach(channel, *[httpx.ConnectError("down")] * 4)

    with pytest.raises(httpx.ConnectError):
        await channel.send(OutgoingMessage(content="hi", reply_to="C123"))

    assert post.await_count == 4  # initial attempt + max_retries=3


async def test_edit_retries_transient_error(no_sleep) -> None:
    channel = _channel()
    post = _attach(channel, _resp(502), _resp(200))

    await channel.edit("1.0", "updated")

    assert post.await_count == 2


async def test_delete_retries_transient_error(no_sleep) -> None:
    channel = _channel()
    post = _attach(channel, _resp(500), _resp(200))

    await channel.delete("1.0")

    assert post.await_count == 2


async def test_send_streaming_retries_post_and_edit(no_sleep) -> None:
    """Both the opening chat.postMessage and each chat.update ride the retry."""
    channel = _channel()
    seen: list[str] = []

    async def _post(url: str, **kwargs: Any) -> httpx.Response:
        seen.append(url)
        # First call to each endpoint fails transiently, then succeeds.
        if seen.count(url) == 1:
            return _resp(503)
        return _resp(200, {"ok": True, "ts": "1.0"})

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_post)
    channel._client = client

    async def _chunks():
        yield "a"
        yield "b"

    ts = await channel.send_streaming(_chunks(), channel="C123", update_interval_ms=0)

    assert ts == "1.0"
    assert seen.count("/chat.postMessage") == 2  # one retry
    assert seen.count("/chat.update") >= 2  # at least one update, retried once


async def test_send_file_retries_and_reopens_the_upload_body(tmp_path: Path, no_sleep) -> None:
    """A retried upload must re-read the file, not send an exhausted handle."""
    sample = tmp_path / "note.txt"
    sample.write_bytes(b"hello world")

    channel = _channel()
    bodies: list[bytes] = []
    calls: list[str] = []

    async def _post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append(url)
        if url == "/files.getUploadURLExternal":
            if calls.count(url) == 1:
                return _resp(503)
            return _resp(200, {"ok": True, "upload_url": "https://up.slack/x", "file_id": "F1"})
        if url == "https://up.slack/x":
            bodies.append(kwargs["files"]["file"][1].read())
            if len(bodies) == 1:
                return _resp(503)
            return _resp(200, {"ok": True})
        return _resp(200, {"ok": True})

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_post)
    channel._client = client

    result = await channel.send_file("C123", str(sample), content="here")

    assert result.provider_file_id == "F1"
    # Both upload attempts carried the full body — the handle was reopened.
    assert bodies == [b"hello world", b"hello world"]
    assert calls.count("/files.completeUploadExternal") == 1


async def test_send_does_not_retry_slack_level_error(no_sleep) -> None:
    """``ok: false`` on an HTTP 200 is a Slack verdict — surfaced, not retried."""
    channel = _channel()
    post = _attach(channel, _resp(200, {"ok": False, "error": "channel_not_found"}))

    with pytest.raises(RuntimeError, match="channel_not_found"):
        await channel.send(OutgoingMessage(content="hi", reply_to="C123"))

    assert post.await_count == 1


# ── retry_request: exhausted 429 + Retry-After parsing (#718) ───────────────


def test_parse_retry_after_formats() -> None:
    """Numeric seconds and RFC 7231 HTTP-dates both parse; garbage falls back."""
    # Integer / float seconds.
    assert _parse_retry_after("10", 1.0) == 10.0
    assert _parse_retry_after("2.5", 1.0) == 2.5

    # Missing / empty / unparseable → default_delay.
    assert _parse_retry_after(None, 5.0) == 5.0
    assert _parse_retry_after("", 5.0) == 5.0
    assert _parse_retry_after("   ", 5.0) == 5.0
    assert _parse_retry_after("not-a-number", 5.0) == 5.0

    # Past HTTP-date clamps to 0.0.
    from datetime import timedelta

    past = (datetime.now(UTC) - timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert _parse_retry_after(past, 1.0) == 0.0

    # A far-future HTTP-date is capped at max_delay (5 minutes).
    far_future = (datetime.now(UTC) + timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert _parse_retry_after(far_future, 1.0) == 300.0

    # A huge numeric Retry-After is also capped.
    assert _parse_retry_after("86400", 1.0) == 300.0


async def test_retry_request_returns_429_response_on_final_attempt(no_sleep) -> None:
    """An exhausted 429 returns the Response, not a bare RuntimeError.

    Mirrors the 5xx branch: on the final attempt ``retry_request`` must not
    sleep again or fall through to ``RuntimeError("retry_request exhausted")``
    — it returns the 429 so the caller sees the true status, ``Retry-After``
    header, and response body (e.g. Slack's ``{"ok": false}`` payload).
    """

    async def always_429() -> httpx.Response:
        return _resp(429, {"ok": False, "error": "rate_limited"}, headers={"Retry-After": "2"})

    resp = await retry_request(always_429, max_retries=1, base_delay=0.1)

    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "2"
    assert resp.json() == {"ok": False, "error": "rate_limited"}
    # Slept exactly once (attempt 0 → 1), not after the final attempt.
    assert no_sleep.await_count == 1


async def test_retry_request_parses_http_date_retry_after(no_sleep) -> None:
    """An RFC 7231 HTTP-date Retry-After drives the backoff instead of crashing."""

    def _http_date_soon() -> str:
        from datetime import timedelta

        return (datetime.now(UTC) + timedelta(seconds=15)).strftime("%a, %d %b %Y %H:%M:%S GMT")

    responses = [
        _resp(429, headers={"Retry-After": _http_date_soon()}),
        _resp(200),
    ]

    async def _endpoint() -> httpx.Response:
        return responses.pop(0)

    resp = await retry_request(_endpoint, max_retries=1, base_delay=0.1)

    assert resp.status_code == 200
    slept_time = no_sleep.call_args[0][0]
    # ~15s into the future, generous 5s tolerance for test execution.
    assert 10.0 <= slept_time <= 20.0


async def test_retry_request_429_on_final_attempt_does_not_sleep_again(no_sleep) -> None:
    """Once retries are exhausted, a 429 must be returned without another sleep."""
    responses = [_resp(429, headers={"Retry-After": "5"})] * 2

    async def _endpoint() -> httpx.Response:
        return responses.pop(0)

    resp = await retry_request(_endpoint, max_retries=1, base_delay=0.1)

    assert resp.status_code == 429
    # One sleep for the retry, none after the final attempt.
    assert no_sleep.await_count == 1
