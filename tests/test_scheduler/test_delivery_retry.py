"""Transient retry policy for channel/webhook delivery (#430).

A successful run whose *delivery* hit a transient error (429/502/503,
timeout, DNS/network hiccup) must be retried with exponential backoff
instead of being reported as ``delivery_failed`` forever. Permanent
errors (auth/config-style signatures) fail immediately without retries.
Both the primary delivery path and ``failure_destination`` alerts route
through the same two methods, so retrying them covers both.
"""

from __future__ import annotations

import sys

import pytest

from agentos.scheduler import delivery as delivery_module
from agentos.scheduler.delivery import (
    _TRANSIENT_MAX_RETRIES,
    DeliveryChain,
)
from agentos.scheduler.types import (
    CronJob,
    DeliveryConfig,
    DeliveryMode,
    FailureDestination,
    SessionTarget,
)


def _no_sleep() -> None:
    """Tests must not wait on real backoff delays."""


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch) -> None:
    monkeypatch.setattr(delivery_module, "_TRANSIENT_BACKOFF_SECONDS", (0.0, 0.0, 0.0))
    monkeypatch.setattr(
        delivery_module,
        "_TRANSIENT_MAX_RETRIES",
        3,
    )


def _webhook_job(url: str, token: str = "") -> CronJob:
    return CronJob(
        id="job-1",
        name="hook",
        cron_expr="*/5 * * * *",
        handler_key="agent_run",
        payload={"kind": "agent_turn", "task": "x", "agent_id": "main"},
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.WEBHOOK,
            webhook_url=url,
            webhook_token=token,
        ),
    )


class _StatusResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _install_fake_httpx(
    monkeypatch,
    *,
    failures: int = 0,
    fail_text: str = "502 Bad Gateway",
) -> type:
    """Install a fake ``httpx`` module whose AsyncClient fails the first
    ``failures`` POSTs with ``fail_text`` then succeeds.
    """

    class _FlakyClient:
        instances: list[_FlakyClient] = []

        def __init__(self, *, timeout=None, **_kw) -> None:
            self.timeout = timeout
            self.posts: list[dict] = []
            _FlakyClient.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            self.posts.append({"url": url, "json": json, "headers": headers or {}})
            if len(self.posts) <= failures:
                raise RuntimeError(fail_text)
            return _StatusResp(200)

    class _FakeHttpx:
        AsyncClient = _FlakyClient

    monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)
    return _FlakyClient


# --- webhook: transient ----------------------------------------------------


async def test_webhook_transient_error_retries_then_delivers(monkeypatch) -> None:
    client_cls = _install_fake_httpx(monkeypatch, failures=2)

    chain = DeliveryChain()
    status = await chain._deliver_webhook(_webhook_job("https://hooks.example/cron"), text="x")

    assert status == "delivered"
    client = client_cls.instances[-1]
    assert len(client.posts) == 3, "transient failure should be retried twice"


async def test_webhook_transient_error_exhausts_retries(monkeypatch) -> None:
    client_cls = _install_fake_httpx(monkeypatch, failures=99, fail_text="Connection timeout")

    chain = DeliveryChain()
    status = await chain._deliver_webhook(_webhook_job("https://hooks.example/cron"), text="x")

    assert status == "delivery_failed"
    client = client_cls.instances[-1]
    assert len(client.posts) == _TRANSIENT_MAX_RETRIES


async def test_webhook_rate_limit_error_is_transient(monkeypatch) -> None:
    client_cls = _install_fake_httpx(monkeypatch, failures=1, fail_text="429 Too Many Requests")

    chain = DeliveryChain()
    status = await chain._deliver_webhook(_webhook_job("https://hooks.example/cron"), text="x")

    assert status == "delivered"
    client = client_cls.instances[-1]
    assert len(client.posts) == 2


# --- webhook: permanent ----------------------------------------------------


async def test_webhook_permanent_error_does_not_retry(monkeypatch) -> None:
    client_cls = _install_fake_httpx(monkeypatch, failures=99, fail_text="401 Unauthorized")

    chain = DeliveryChain()
    status = await chain._deliver_webhook(_webhook_job("https://hooks.example/cron"), text="x")

    assert status == "delivery_failed"
    client = client_cls.instances[-1]
    assert len(client.posts) == 1, "permanent errors must fail fast"


# --- channel ---------------------------------------------------------------


class _FlakyAdapter:
    def __init__(self, failures: int = 0, fail_text: str = "") -> None:
        self.sends = 0
        self.failures = failures
        self.fail_text = fail_text

    async def send(self, msg) -> None:
        self.sends += 1
        if self.sends <= self.failures:
            raise RuntimeError(self.fail_text)


class _FakeChannelManager:
    def __init__(self, adapter) -> None:
        self.adapter = adapter

    def get(self, channel_name: str):
        return self.adapter


def _channel_job(channel_name: str = "telegram", channel_id: str = "C1") -> CronJob:
    return CronJob(
        id="job-2",
        name="chan",
        cron_expr="*/5 * * * *",
        handler_key="agent_run",
        payload={"kind": "agent_turn", "task": "x", "agent_id": "main"},
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name=channel_name,
            channel_id=channel_id,
        ),
    )


async def test_channel_transient_error_retries_then_delivers() -> None:
    adapter = _FlakyAdapter(failures=2, fail_text="429 Too Many Requests")
    chain = DeliveryChain(
        channel_manager_ref=lambda: _FakeChannelManager(adapter),
    )

    status = await chain._post_to_channel(
        job_id="job-2",
        text="x",
        channel_name="telegram",
        channel_id="C1",
        thread_id="",
    )

    assert status == "delivered"
    assert adapter.sends == 3, "transient failure should be retried twice"


async def test_channel_permanent_error_does_not_retry() -> None:
    adapter = _FlakyAdapter(failures=99, fail_text="403 Forbidden")
    chain = DeliveryChain(
        channel_manager_ref=lambda: _FakeChannelManager(adapter),
    )

    status = await chain._post_to_channel(
        job_id="job-2",
        text="x",
        channel_name="telegram",
        channel_id="C1",
        thread_id="",
    )

    assert status == "delivery_failed"
    assert adapter.sends == 1, "permanent errors must fail fast"


# --- failure_destination shares the retry path -----------------------------


async def test_failure_destination_webhook_gets_retried(monkeypatch) -> None:
    client_cls = _install_fake_httpx(monkeypatch, failures=2)

    job = _webhook_job("https://hooks.example/primary")
    job.delivery.failure_destination = FailureDestination(
        mode=DeliveryMode.WEBHOOK,
        webhook_url="https://hooks.example/alerts",
    )

    chain = DeliveryChain()
    status = await chain._deliver_to_failure_destination(
        job, "alert text", job.delivery.failure_destination
    )

    assert status == "delivered"
    client = client_cls.instances[-1]
    assert len(client.posts) == 3
    assert client.posts[0]["url"] == "https://hooks.example/alerts"
