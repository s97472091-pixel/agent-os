"""Tests for intent_cache — compound command handling in _extract_rm_targets."""

from __future__ import annotations

from agentos.application.intent_cache import _extract_rm_targets


def test_single_rm_simple() -> None:
    """Single rm still works."""
    assert _extract_rm_targets("rm /tmp/ok") == ["/tmp/ok"]


def test_single_rm_multi_target() -> None:
    """rm with multiple args extracts all."""
    targets = _extract_rm_targets("rm -rf /tmp/a /tmp/b /tmp/c")
    assert "/tmp/a" in targets
    assert "/tmp/b" in targets
    assert "/tmp/c" in targets


def test_compound_rm_semicolon() -> None:
    """Compound command: rm A; rm B — both extracted."""
    targets = _extract_rm_targets("rm /tmp/ok; rm /root/.bash_history")
    assert "/tmp/ok" in targets
    assert "/root/.bash_history" in targets


def test_compound_rm_and() -> None:
    """Compound command: rm A && rm B — both extracted."""
    targets = _extract_rm_targets("rm /tmp/ok && rm -rf /etc")
    assert "/tmp/ok" in targets
    assert "/etc" in targets


def test_compound_rm_or() -> None:
    """Compound command: rm A || rm B — both extracted."""
    targets = _extract_rm_targets("rm -f /tmp/ok || rm /root")
    assert "/tmp/ok" in targets
    assert "/root" in targets


def test_compound_rm_pipe() -> None:
    """Compound command: rm A | rm B — both extracted."""
    targets = _extract_rm_targets("rm /tmp/ok | rm /root/.ssh/id_rsa")
    assert "/tmp/ok" in targets
    assert "/root/.ssh/id_rsa" in targets


def test_compound_rm_triple_multiplex() -> None:
    """Three-segment compound: rm A; rm B; rm C — all three extracted."""
    targets = _extract_rm_targets("rm /tmp/ok; rm /root; rm -rf /etc/passwd")
    assert "/tmp/ok" in targets
    assert "/root" in targets
    assert "/etc/passwd" in targets


def test_compound_rm_with_non_destructive_segment() -> None:
    """Non-destructive segment in compound is ignored by rm extraction."""
    targets = _extract_rm_targets("rm /tmp/trash; cat /root/.bash_history")
    assert "/tmp/trash" in targets
    # cat is not an rm command — not extracted
    assert len(targets) == 1


def test_compound_rm_with_leading_echo() -> None:
    """Leading non-rm segment before rm is fine."""
    targets = _extract_rm_targets("echo starting; rm /root/.bash_history")
    assert "/root/.bash_history" in targets


def test_only_non_rm_segments() -> None:
    """No rm at all — empty result."""
    assert _extract_rm_targets("cat /root/.bash_history") == []
    assert _extract_rm_targets("ls /root") == []


def test_empty_command() -> None:
    """Empty string — empty result."""
    assert _extract_rm_targets("") == []
    assert _extract_rm_targets("   ") == []


def test_compound_rm_sensitive_target_in_command() -> None:
    """Integration: compound rm with sensitive path gets blocked."""
    from agentos.sandbox.sensitive_paths import sensitive_target_in_command

    # compound rm with second rm targeting sensitive path
    assert (
        sensitive_target_in_command("rm /tmp/ok; rm /root/.bash_history", cwd="/workspace")
        is not None
    )

    # single rm targeting sensitive path still works
    assert sensitive_target_in_command("rm /root/.bash_history", cwd="/workspace") is not None

    # no sensitive path — not blocked
    assert sensitive_target_in_command("rm /tmp/ok", cwd="/workspace") is None
