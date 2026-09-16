"""``git_log`` must answer in a repository whose ``HEAD`` has no commits (#2502).

A repository between ``git init`` and its first commit is the state every
project starts in, but ``git log`` exits 128 there, so the tool raised a
``RuntimeError`` the model could only retry. An empty history is an answer, not
a failure — and a directory that is not a repository at all must keep failing
loudly instead of being reported as an empty history.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agentos.sandbox.config import SandboxSettings
from agentos.sandbox.integration import configure_runtime, reset_runtime
from agentos.tools.builtin import git
from agentos.tools.types import ToolContext, current_tool_context

NO_COMMITS = "(no commits yet)"


def _git(repo: Path, *args: str) -> None:
    """Run git with the ambient user/system config neutralised.

    A maintainer's global ``commit.gpgsign`` or commit template would otherwise
    decide whether this test can make a commit, and the env is copied rather
    than replaced because git on Windows needs the ambient ``SYSTEMROOT``.
    """
    missing = str(repo.parent / "no-such-gitconfig")
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": missing,
            "GIT_CONFIG_SYSTEM": missing,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


def _commit(repo: Path, message: str) -> None:
    name = f"{message.replace(' ', '-')}.txt"
    (repo / name).write_text("x\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


@contextmanager
def _as_workspace(path: Path) -> Iterator[Path]:
    """Run the tool handlers inline for *path*, the way an ungraded run does.

    The sandbox runtime is configured with ``sandbox=False`` so the
    ``@sandboxed`` gate does not refuse fail-closed, mirroring
    ``test_git_diff_revision``.
    """
    configure_runtime(
        SandboxSettings(sandbox=False, security_grading=False, allow_legacy_mode=True),
        workspace=path,
    )
    token = current_tool_context.set(ToolContext(workspace_dir=str(path)))
    try:
        yield path
    finally:
        current_tool_context.reset(token)
        reset_runtime()


@pytest.fixture
def unborn_repo(tmp_path: Path) -> Iterator[Path]:
    """A repository with no commit yet — ``git log`` has nothing to walk."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    with _as_workspace(repo) as path:
        yield path


@pytest.fixture
def plain_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A workspace that is not a repository at all.

    ``GIT_CEILING_DIRECTORIES`` stops git's upward search for a repository,
    which otherwise adopts whatever encloses the temporary directory: a machine
    whose home directory is itself a checkout puts every ``tmp_path`` under one,
    and ``git log`` there reports that repository's unborn branch instead of
    refusing.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plain = tmp_path / "plain"
    plain.mkdir()
    with _as_workspace(plain) as path:
        yield path


async def test_log_in_a_repository_without_a_commit_reports_an_empty_history(
    unborn_repo: Path,
) -> None:
    """The state ``git init`` leaves behind is an answer, not a traceback."""
    assert await git.git_log() == NO_COMMITS


async def test_log_still_lists_commits_once_they_exist(unborn_repo: Path) -> None:
    """The probe must not replace the log it was added to guard."""
    _commit(unborn_repo, "first commit")

    out = await git.git_log()

    assert "first commit" in out
    assert NO_COMMITS not in out


async def test_log_honours_count_in_a_repository_with_commits(unborn_repo: Path) -> None:
    """``count`` is still passed through, not short-circuited by the probe."""
    _commit(unborn_repo, "commit one")
    _commit(unborn_repo, "commit two")
    _commit(unborn_repo, "commit three")

    lines = [line for line in (await git.git_log(count=1)).splitlines() if line.strip()]

    assert len(lines) == 1
    assert "commit three" in lines[0]


async def test_log_reports_the_same_when_the_workdir_names_the_repository(
    unborn_repo: Path,
) -> None:
    """An explicit ``workdir`` resolves to the same repository, same answer."""
    assert await git.git_log(workdir=str(unborn_repo)) == NO_COMMITS


async def test_log_outside_a_repository_still_raises(plain_directory: Path) -> None:
    """``rev-parse`` fails for both conditions, so the probe must not mask this."""
    with pytest.raises(RuntimeError, match="not a git repository"):
        await git.git_log()


async def test_unborn_head_separates_an_empty_repository_from_no_repository(
    unborn_repo: Path, plain_directory: Path
) -> None:
    """Unit-level pin on the distinction the log branch hangs off."""
    assert await git._unborn_head(str(unborn_repo)) is True
    assert await git._unborn_head(str(plain_directory)) is False

    _commit(unborn_repo, "first commit")

    assert await git._unborn_head(str(unborn_repo)) is False
