"""Regression tests for IntentApprovalCache compound-command bypass fix.

PR #546 fixes P1 security issue #512: when ``rm A; rm -rf /`` is checked
against a cache that only approved ``rm A``, the second ``rm`` must be
rejected. The fix uses ``re.finditer`` + shell-separator-aware tokenization
instead of ``re.search``, so each ``rm`` invocation is parsed independently.

See https://github.com/use-agent-os/agent-os/pull/546
"""

from __future__ import annotations

from agentos.application.intent_cache import IntentApprovalCache


class TestCompoundCommandSeparatorBypass:
    """Every shell separator must be caught by the permission cache.

    A single approved ``rm /a`` followed by a second ``rm /b`` via any of the
    six shell separators (``;``, ``&&``, ``||``, ``|``, ``&``, ``\\n``) must
    return ``False`` — the untargeted path was never approved.
    """

    def _check_separator(self, separator: str) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /a")
        assert cache.check("rm /a") is True
        assert cache.check(f"rm /a{separator} rm /b") is False, (
            f"check('rm /a{separator} rm /b') should be False"
        )

    def test_semicolon(self) -> None:
        self._check_separator(";")

    def test_and_and(self) -> None:
        self._check_separator(" && ")

    def test_or_or(self) -> None:
        self._check_separator(" || ")

    def test_pipe(self) -> None:
        self._check_separator(" | ")

    def test_ampersand(self) -> None:
        self._check_separator(" & ")

    def test_newline(self) -> None:
        self._check_separator("\n")


class TestMultiTargetApproval:
    """Multi-target commands must require approval for all targets."""

    def test_all_targets_approved_passes(self) -> None:
        """rm /a /b recorded -> check('rm /a /b') is True."""
        cache = IntentApprovalCache()
        cache.record("rm /a /b")
        assert cache.check("rm /a /b") is True

    def test_extra_target_not_approved_fails(self) -> None:
        """rm /a /b recorded -> check('rm /a /b /c') is False — /c not approved."""
        cache = IntentApprovalCache()
        cache.record("rm /a /b")
        assert cache.check("rm /a /b /c") is False


class TestRecordAndCheck:
    """Basic record/check lifecycle."""

    def test_empty_command_returns_false(self) -> None:
        cache = IntentApprovalCache()
        assert cache.check("") is False

    def test_non_rm_command_returns_false(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /a")
        assert cache.check("echo hello") is False

    def test_record_always_survives_clear_scope(self) -> None:
        cache = IntentApprovalCache()
        cache.record_always("rm /a")
        cache.clear_scope("once")
        assert cache.check("rm /a") is True

    def test_forget_removes_entry(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /a")
        assert cache.check("rm /a") is True
        cache.forget("rm /a")
        assert cache.check("rm /a") is False

    def test_clear_drops_all(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /a")
        cache.record("rm /b")
        cache.clear()
        assert cache.check("rm /a") is False
        assert cache.check("rm /b") is False


class TestFlagEscalationBypass:
    """Approving a plain delete must not unlock flag-escalated variants.

    Issue #849: ``cache.record('rm /tmp/a')`` then ``cache.check('rm -rf
    /tmp/a')`` returned True because only the target path was part of the
    cache key. Escalation flags (-r/-R/--recursive, -f/--force,
    --no-preserve-root, and Python recursion like shutil.rmtree) must be
    part of the approved capability, monotonic in one direction only:
    approving a *stronger* delete still covers the *milder* form, but a
    milder approval never covers a stronger one.
    """

    def test_plain_approval_does_not_cover_recursive_force(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check("rm -rf /tmp/a") is False
        assert cache.check("rm -r /tmp/a") is False
        assert cache.check("rm -f /tmp/a") is False

    def test_plain_approval_still_covers_exact_and_milder(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check("rm /tmp/a") is True
        # A path with a trailing slash normalizes to the same target and
        # carries no escalation flags, so it stays approved.
        assert cache.check("rm /tmp/a/") is True

    def test_strong_approval_covers_milder_but_not_stronger(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm -rf /tmp/a")
        # Recursive+force approval still covers the plain and single-flag
        # variants of the same target (monotonic — capability only grows).
        assert cache.check("rm /tmp/a") is True
        assert cache.check("rm -r /tmp/a") is True
        assert cache.check("rm -f /tmp/a") is True
        assert cache.check("rm -rf /tmp/a") is True
        # But never a different, stronger target.
        assert cache.check("rm -rf /tmp/b") is False

    def test_long_flag_escalation(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        assert cache.check("rm --recursive /tmp/a") is False
        assert cache.check("rm --force /tmp/a") is False

    def test_force_alone_does_not_cover_recursive(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm -f /tmp/a")
        assert cache.check("rm -f /tmp/a") is True
        assert cache.check("rm -rf /tmp/a") is False

    def test_python_rmtree_is_recursive_escalation(self) -> None:
        cache = IntentApprovalCache()
        # os.remove approval must not cover the recursive shutil.rmtree on
        # the same path (rmtree implies the "recursive" capability).
        cache.record("os.remove('/tmp/a')")
        assert cache.check("os.remove('/tmp/a')") is True
        assert cache.check("shutil.rmtree('/tmp/a')") is False
        assert cache.check("os.removedirs('/tmp/a')") is False

    def test_python_rmtree_approval_covers_single_delete(self) -> None:
        cache = IntentApprovalCache()
        cache.record("shutil.rmtree('/tmp/a')")
        assert cache.check("shutil.rmtree('/tmp/a')") is True
        assert cache.check("os.remove('/tmp/a')") is True
        assert cache.check("Path('/tmp/a').unlink()") is True

    def test_record_merges_flags_monotonically(self) -> None:
        cache = IntentApprovalCache()
        cache.record("rm /tmp/a")
        # A later, stronger approval upgrades the same (kind, target) entry.
        cache.record("rm -rf /tmp/a")
        assert cache.check("rm -rf /tmp/a") is True
        assert cache.check("rm /tmp/a") is True
        # And a later milder record does not downgrade the entry.
        cache.record("rm /tmp/a")
        assert cache.check("rm -rf /tmp/a") is True
