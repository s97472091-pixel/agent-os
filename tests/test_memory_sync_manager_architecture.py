from __future__ import annotations

import pytest

from agentos.memory.sync_manager import MemorySyncManager


class NoopStore:
    def __init__(self) -> None:
        self.indexed: list[str] = []
        self.removed: list[str] = []

    async def index_file(self, *, path: str, content: str, source: object) -> int:
        self.indexed.append(path)
        return 1

    async def remove_file(self, path: str) -> None:
        self.removed.append(path)
        return None


def test_sync_manager_scans_archive_as_curated_memory_subdir(tmp_path):
    workspace = tmp_path / "workspace"
    memory = workspace / "memory"
    archive = memory / "archive"
    hidden = memory / ".private"
    archive.mkdir(parents=True)
    hidden.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("root\n", encoding="utf-8")
    (memory / "a.md").write_text("a\n", encoding="utf-8")
    (memory / ".hidden.md").write_text("hidden file\n", encoding="utf-8")
    (archive / "x.md").write_text("archive is curated if user-created\n", encoding="utf-8")
    (hidden / "x.md").write_text("hidden\n", encoding="utf-8")

    manager = MemorySyncManager(
        store=NoopStore(),
        workspace_dir=workspace,
        memory_dir=memory,
    )

    assert sorted(manager._scan_files()) == [
        "MEMORY.md",
        "memory/a.md",
        "memory/archive/x.md",
    ]


@pytest.mark.asyncio
async def test_sync_force_rescans_unchanged_memory_sources(tmp_path):
    workspace = tmp_path / "workspace"
    memory = workspace / "memory"
    memory.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("root\n", encoding="utf-8")
    (memory / "a.md").write_text("a\n", encoding="utf-8")
    store = NoopStore()
    manager = MemorySyncManager(store=store, workspace_dir=workspace, memory_dir=memory)

    await manager.sync(reason="manual")
    first_indexed = list(store.indexed)
    await manager.sync(reason="manual")
    second_indexed = store.indexed[len(first_indexed) :]
    await manager.sync(reason="manual", force=True)
    forced_indexed = store.indexed[len(first_indexed) + len(second_indexed) :]

    assert sorted(first_indexed) == ["MEMORY.md", "memory/a.md"]
    assert second_indexed == []
    assert sorted(forced_indexed) == ["MEMORY.md", "memory/a.md"]


@pytest.mark.asyncio
async def test_sync_force_overrides_search_clean_fast_path(tmp_path):
    workspace = tmp_path / "workspace"
    memory = workspace / "memory"
    memory.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("root\n", encoding="utf-8")
    store = NoopStore()
    manager = MemorySyncManager(store=store, workspace_dir=workspace, memory_dir=memory)

    await manager.sync(reason="manual")
    first_count = len(store.indexed)
    sync_calls: list[dict[str, object]] = []

    async def fake_do_file_sync(**kwargs: object) -> tuple[set[str], set[str]]:
        sync_calls.append(kwargs)
        return set(), set()

    manager._do_file_sync = fake_do_file_sync  # type: ignore[method-assign]
    await manager.sync(reason="search")
    await manager.sync(reason="search:tool")
    await manager.sync(reason="search:control")
    search_count = len(store.indexed)
    await manager.sync(reason="search:tool", force=True)

    assert first_count == 1
    assert search_count == first_count
    assert sync_calls == [{"force": True}]


class FlakyStore(NoopStore):
    """``index_file`` fails for the configured paths until ``fail_times``."""

    def __init__(self, fail_paths: set[str], fail_times: int = 1) -> None:
        super().__init__()
        self._fail_paths = fail_paths
        self._fail_times = fail_times
        self._index_calls: dict[str, int] = {}

    async def index_file(self, *, path: str, content: str, source: object) -> int:
        self._index_calls[path] = self._index_calls.get(path, 0) + 1
        if path in self._fail_paths and self._index_calls[path] <= self._fail_times:
            raise OSError("transient index failure")
        return await super().index_file(path=path, content=content, source=source)


@pytest.mark.asyncio
async def test_transient_index_failure_is_requeued_and_retried(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    memory = workspace / "memory"
    memory.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("root\n", encoding="utf-8")
    (memory / "a.md").write_text("a\n", encoding="utf-8")
    store = FlakyStore(fail_paths={"memory/a.md"}, fail_times=1)
    manager = MemorySyncManager(store=store, workspace_dir=workspace, memory_dir=memory)

    # First sync: a.md fails once, MEMORY.md succeeds.
    await manager.sync(reason="manual")
    assert sorted(store.indexed) == ["MEMORY.md"]
    assert "memory/a.md" in manager._pending_changes
    assert manager._dirty is True

    # Watcher tick without an mtime change retries the failed path.
    await manager.sync(reason="watch")
    assert sorted(store.indexed) == ["MEMORY.md", "memory/a.md"]
    assert manager._pending_changes == set()
    assert manager._dirty is False


@pytest.mark.asyncio
async def test_persistent_index_failure_stays_pending_and_dirty(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    memory = workspace / "memory"
    memory.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("root\n", encoding="utf-8")
    (memory / "a.md").write_text("a\n", encoding="utf-8")
    store = FlakyStore(fail_paths={"memory/a.md"}, fail_times=100)
    manager = MemorySyncManager(store=store, workspace_dir=workspace, memory_dir=memory)

    await manager.sync(reason="manual")
    assert store._index_calls["memory/a.md"] == 1

    # Still failing after several watcher ticks: stays pending + dirty.
    await manager.sync(reason="watch")
    await manager.sync(reason="watch")
    await manager.sync(reason="watch")
    assert store._index_calls["memory/a.md"] == 4
    assert "memory/a.md" in manager._pending_changes
    assert manager._dirty is True


@pytest.mark.asyncio
async def test_clean_sync_after_retry_does_not_duplicate(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    memory = workspace / "memory"
    memory.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("root\n", encoding="utf-8")
    (memory / "a.md").write_text("a\n", encoding="utf-8")
    store = FlakyStore(fail_paths={"memory/a.md"}, fail_times=1)
    manager = MemorySyncManager(store=store, workspace_dir=workspace, memory_dir=memory)

    await manager.sync(reason="manual")  # a.md fails
    await manager.sync(reason="watch")  # a.md retried and succeeds
    assert store._index_calls["memory/a.md"] == 2

    # A clean subsequent sync must not re-index anything.
    await manager.sync(reason="watch")
    assert store._index_calls["memory/a.md"] == 2
    assert store.indexed == ["MEMORY.md", "memory/a.md"]


@pytest.mark.asyncio
async def test_delete_failure_retry_is_preserved(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    memory = workspace / "memory"
    memory.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("root\n", encoding="utf-8")
    (memory / "a.md").write_text("a\n", encoding="utf-8")

    class FlakyDeleteStore(NoopStore):
        def __init__(self) -> None:
            super().__init__()
            self.remove_attempts = 0

        async def remove_file(self, path: str) -> None:
            self.remove_attempts += 1
            if self.remove_attempts == 1:
                raise OSError("transient sqlite lock")
            return await super().remove_file(path)

    store = FlakyDeleteStore()
    manager = MemorySyncManager(store=store, workspace_dir=workspace, memory_dir=memory)

    # Index everything first, then delete the file.
    await manager.sync(reason="manual")
    (memory / "a.md").unlink()

    # First watch: remove_file fails -> requeued into _pending_deletes.
    await manager.sync(reason="watch")
    assert "memory/a.md" in manager._pending_deletes
    assert manager._dirty is True

    # Second watch: retried and succeeds.
    await manager.sync(reason="watch")
    assert store.removed == ["memory/a.md"]
    assert manager._pending_deletes == set()
    assert manager._dirty is False
