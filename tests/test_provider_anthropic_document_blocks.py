"""The document-block gate excludes SKUs that reject native document blocks.

Anthropic added document (PDF) block support with Claude 3.5 Sonnet; the
original Claude 3 Opus/Sonnet SKUs reject a ``document`` block with a 400.
``_supports_document_blocks`` must say False for them so the payload builder
substitutes the documented text fallback instead of the API rejecting the
whole request. See issue #3245.
"""

from __future__ import annotations

import pytest

from agentos.provider import ContentBlockDocument, Message
from agentos.provider.anthropic import (
    _build_message_payload,
    _supports_document_blocks,
)


@pytest.mark.parametrize(
    "model",
    [
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
        "claude-3-5-haiku-20241022",
        "claude-haiku-4-5",
    ],
)
def test_gate_excludes_unsupported_skus(model: str) -> None:
    assert _supports_document_blocks(model) is False


@pytest.mark.parametrize(
    "model",
    [
        "claude-3-5-sonnet-20241022",
        "claude-3-7-sonnet-20250219",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
    ],
)
def test_gate_allows_document_capable_skus(model: str) -> None:
    assert _supports_document_blocks(model) is True


def test_payload_falls_back_to_text_for_claude_3_opus() -> None:
    msg = Message(
        role="user",
        content=[
            ContentBlockDocument(media_type="application/pdf", data="QUJD", title="spec.pdf"),
        ],
    )

    payload = _build_message_payload(msg, model="claude-3-opus-20240229")

    assert payload["content"][0]["type"] == "text"
    assert "spec.pdf" in payload["content"][0]["text"]


def test_payload_keeps_native_document_for_supported_model() -> None:
    msg = Message(
        role="user",
        content=[
            ContentBlockDocument(media_type="application/pdf", data="QUJD", title="spec.pdf"),
        ],
    )

    payload = _build_message_payload(msg, model="claude-sonnet-4-6")

    assert payload["content"][0]["type"] == "document"
    assert payload["content"][0]["source"]["media_type"] == "application/pdf"
