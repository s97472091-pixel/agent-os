"""Regression tests for directory arguments reaching media tools (#2153)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.tools.builtin import media
from agentos.tools.envelope import build_tool_failure_envelope
from agentos.tools.types import ToolContext, current_tool_context


@pytest.mark.asyncio
async def test_image_tool_rejects_directory_argument(tmp_path: Path) -> None:
    directory = tmp_path / "photo.png"
    directory.mkdir()

    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    try:
        with pytest.raises(IsADirectoryError, match="Path is a directory"):
            await media.image("photo.png", "describe this image")
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_pdf_tool_rejects_directory_argument(tmp_path: Path) -> None:
    directory = tmp_path / "report.pdf"
    directory.mkdir()

    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    try:
        with pytest.raises(IsADirectoryError, match="Path is a directory"):
            await media.pdf("report.pdf")
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_audio_file_resolution_rejects_directory_argument(tmp_path: Path) -> None:
    directory = tmp_path / "sample.wav"
    directory.mkdir()

    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    try:
        with pytest.raises(IsADirectoryError, match="Path is a directory"):
            await media._resolve_supported_audio_file_for_tool(
                tool_name="voice_clone", path=str(directory)
            )
    finally:
        current_tool_context.reset(token)


def test_directory_argument_renders_actionable_failure_envelope() -> None:
    envelope = build_tool_failure_envelope(
        IsADirectoryError("Path is a directory: photo.png"),
        "image",
    )

    assert envelope["status"] == "error"
    assert envelope["error_class"] == "IsADirectoryError"
    assert envelope["user_message"] == "The tool expected a file but received a directory."
    assert envelope["retry_allowed"] is False
