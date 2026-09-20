"""repair_tool_pairing prunes unpaired tool blocks instead of dropping mixed messages.

A message carrying an orphan ``ContentBlockToolResult`` (or an orphan
``ContentBlockToolUse``) next to text content used to be discarded whole by the
final filter loop, silently deleting the user's text from the transcript. Only
the unpaired tool blocks are pruned now; the message is dropped only when
nothing but tool blocks remains. See issue #3233.
"""

from __future__ import annotations

from agentos.engine.history import repair_tool_pairing
from agentos.provider import (
    ContentBlockText,
    ContentBlockToolResult,
    ContentBlockToolUse,
    Message,
)


def _use(call_id: str) -> ContentBlockToolUse:
    return ContentBlockToolUse(id=call_id, name="web_fetch", input={"url": "https://example.com"})


def _result(call_id: str) -> ContentBlockToolResult:
    return ContentBlockToolResult(tool_use_id=call_id, content="ok")


def test_mixed_message_with_orphan_result_keeps_its_text() -> None:
    messages = [
        Message(
            role="user",
            content=[
                ContentBlockText(text="Please process the updated data"),
                _result("orphan_id"),
            ],
        )
    ]

    repaired = repair_tool_pairing(messages)

    assert repaired is not messages
    assert len(repaired) == 1
    assert repaired[0].role == "user"
    assert [block.type for block in repaired[0].content] == ["text"]
    assert repaired[0].content[0].text == "Please process the updated data"


def test_mixed_message_with_orphan_call_keeps_its_text() -> None:
    messages = [
        Message(
            role="assistant",
            content=[
                ContentBlockText(text="Let me check that."),
                _use("orphan_call"),
            ],
        )
    ]

    repaired = repair_tool_pairing(messages)

    assert len(repaired) == 1
    assert [block.type for block in repaired[0].content] == ["text"]
    assert repaired[0].content[0].text == "Let me check that."


def test_pure_orphan_result_message_is_still_dropped() -> None:
    messages = [Message(role="user", content=[_result("orphan_id")])]

    assert repair_tool_pairing(messages) == []


def test_pure_orphan_call_message_is_still_dropped() -> None:
    messages = [Message(role="assistant", content=[_use("orphan_call")])]

    assert repair_tool_pairing(messages) == []


def test_valid_pairing_returns_the_original_list() -> None:
    messages = [
        Message(role="assistant", content=[_use("call-1")]),
        Message(role="user", content=[_result("call-1")]),
    ]

    repaired = repair_tool_pairing(messages)

    assert repaired is messages


def test_mixed_message_with_valid_result_is_kept_whole() -> None:
    messages = [
        Message(role="assistant", content=[_use("call-1")]),
        Message(
            role="user",
            content=[
                _result("call-1"),
                ContentBlockText(text="and here is more context"),
            ],
        ),
    ]

    repaired = repair_tool_pairing(messages)

    assert repaired is messages
    assert [block.type for block in repaired[1].content] == ["tool_result", "text"]


def test_pruning_keeps_the_surrounding_messages_in_order() -> None:
    messages = [
        Message(role="user", content=[ContentBlockText(text="hello")]),
        Message(
            role="user",
            content=[ContentBlockText(text="context"), _result("orphan")],
        ),
        Message(role="assistant", content=[ContentBlockText(text="bye")]),
    ]

    repaired = repair_tool_pairing(messages)

    assert len(repaired) == 3
    assert repaired[0].content[0].text == "hello"
    assert [block.type for block in repaired[1].content] == ["text"]
    assert repaired[1].content[0].text == "context"
    assert repaired[2].content[0].text == "bye"
