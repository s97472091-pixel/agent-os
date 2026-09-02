"""Session-scoped cache of approved action intents.

The per-approval queue treats every tool invocation as a fresh request. That
means approving ``rm /tmp/x`` does nothing for a subsequent
``os.remove("/tmp/x")`` or ``Path("/tmp/x").unlink()`` — the model can paraphrase
its way past approval prompts and the user has to press y repeatedly. This
module normalizes destructive actions to a semantic key (intent kind + target)
and remembers approvals for a short window, so paraphrased retries of the same
intent proceed without another prompt.

Scope: only *delete* intents for now, since that is the bulk of user-observed
pain. Extend ``_extract_intent`` if other classes (write-outside-workspace,
network egress) need intent-level memory.
"""

from __future__ import annotations

import os
import re
import shlex
import threading
import time
from pathlib import Path

_DEFAULT_TTL_SECONDS = 30 * 60
_ALWAYS_TTL_SECONDS = 365 * 24 * 3600  # effectively never expires within a session


def _norm_path(raw: str, *, base_dir: str | Path | None = None) -> str:
    """Best-effort absolute-path normalization.

    Leaves non-path tokens alone (so ``*`` or variable references don't get
    expanded into something wrong).
    """
    if not raw or raw.startswith(("$", "`")) or raw in {"*", "-"}:
        return raw
    try:
        path = Path(raw).expanduser()
        if base_dir is not None and not path.is_absolute():
            path = Path(base_dir).expanduser() / path
        return str(path.resolve(strict=False))
    except (OSError, ValueError):
        return raw


# Regex-based single-capture extractors for Python-flavoured deletes. Each
# regex uses ``finditer`` so ``shutil.rmtree("a"); os.remove("b")`` yields
# both paths. Each pattern carries the escalation flags its operation
# implies (e.g. ``shutil.rmtree`` is inherently recursive) so the approval
# cache can tell ``os.remove`` apart from a recursive delete.
_PY_DELETE_PATTERNS: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (
        re.compile(r"\bos\.(?:remove|unlink|rmdir)\s*\(\s*[\"']([^\"']+)[\"']"),
        frozenset(),
    ),
    (
        re.compile(r"\bos\.removedirs\s*\(\s*[\"']([^\"']+)[\"']"),
        frozenset({"recursive"}),
    ),
    (
        re.compile(r"\bshutil\.rmtree\s*\(\s*[\"']([^\"']+)[\"']"),
        frozenset({"recursive"}),
    ),
    (
        re.compile(
            r"\b(?:pathlib\.)?Path\s*\(\s*[\"']([^\"']+)[\"']\s*\)\s*\.(?:unlink|rmdir)\s*\("
        ),
        frozenset(),
    ),
)

# Shell command separators that terminate a single ``rm`` invocation.
_SHELL_SEPARATORS = (";", "&&", "||", "|", "&")


def _rm_escalation_flags(tokens: list[str]) -> frozenset[str]:
    """Map an ``rm`` invocation's flags to escalation-relevant capabilities.

    Only flags that make the delete *more* destructive are tracked so an
    approval for ``rm /a`` can never be replayed as ``rm -rf /a`` while a
    ``rm -rf /a`` approval still covers the milder ``rm /a`` (monotonic:
    approval only ever grows stronger, never weaker). ``-i``/``-v`` and
    other benign flags are ignored.
    """
    flags: set[str] = set()
    for token in tokens:
        if not token.startswith("-"):
            continue
        if token.startswith("--"):
            if token == "--recursive":
                flags.add("recursive")
            elif token == "--force":
                flags.add("force")
            elif token == "--no-preserve-root":
                flags.add("no-preserve-root")
            continue
        for char in token[1:]:
            if char in "rR":
                flags.add("recursive")
            elif char == "f":
                flags.add("force")
    return frozenset(flags)


def _extract_rm_targets(command: str) -> list[tuple[str, frozenset[str]]]:
    """Pull every (target, escalation-flags) pair out of every ``rm`` invocation.

    Handles ``rm a b c``, ``rm -rf /a /b``, quoted paths, and stops at shell
    separators. Uses ``finditer`` so ``rm foo; rm -rf /bar`` yields pairs
    from both invocations independently. Does not try to be a full shell
    parser — falls back to whitespace split on shlex errors (unbalanced quotes).
    """
    # Match each ``rm`` invocation, stopping at shell separators.
    # ``[^;\n&|]*`` captures everything from ``rm`` up to the next separator
    # or end-of-expression, so each ``rm`` is tokenized independently.
    pattern = re.compile(r"\brm\b([^;\n&|]*)")
    matches = list(pattern.finditer(command))
    if not matches:
        return []

    targets: list[tuple[str, frozenset[str]]] = []
    seen: set[tuple[str, frozenset[str]]] = set()

    for match in matches:
        tail = match.group(1).strip()
        if not tail:
            continue

        token_sets: list[list[str]] = []
        try:
            token_sets.append(shlex.split(tail))
        except ValueError:
            token_sets.append(tail.split())
        if "\\" in tail and (os.name == "nt" or re.search(r"(?:^|\s)\\[^\s]", tail)):
            try:
                token_sets.append(shlex.split(tail, posix=False))
            except ValueError:
                token_sets.append(tail.split())

        for tokens in token_sets:
            flags = _rm_escalation_flags(tokens)
            for token in tokens:
                if not token or token.startswith("-") or (token, flags) in seen:
                    continue
                seen.add((token, flags))
                targets.append((token, flags))

    return targets


def _extract_intents(
    command: str,
    *,
    base_dir: str | Path | None = None,
) -> list[tuple[str, str, frozenset[str]]]:
    """Return every recognized destructive intent, deduped and normalized.

    ``rm /a /b /c`` -> three tuples; ``shutil.rmtree('a'); os.remove('b')`` ->
    two tuples; a plain echo returns an empty list. Each tuple is
    ``(kind, target, escalation_flags)`` so the cache can distinguish
    ``rm /a`` from ``rm -rf /a`` on the same path.
    """
    if not command:
        return []

    result: list[tuple[str, str, frozenset[str]]] = []
    seen: set[tuple[str, str, frozenset[str]]] = set()
    for raw, flags in _extract_rm_targets(command):
        intent = ("delete", _norm_path(raw, base_dir=base_dir), flags)
        if intent in seen:
            continue
        seen.add(intent)
        result.append(intent)
    for pattern, flags in _PY_DELETE_PATTERNS:
        for match in pattern.finditer(command):
            intent = ("delete", _norm_path(match.group(1), base_dir=base_dir), flags)
            if intent in seen:
                continue
            seen.add(intent)
            result.append(intent)
    return result


def _extract_intent(command: str) -> tuple[str, str, frozenset[str]] | None:
    """First extracted intent, or None. Convenience for single-target callers."""
    intents = _extract_intents(command)
    return intents[0] if intents else None


class IntentApprovalCache:
    """In-memory cache keyed by ``(kind, target)`` with scope-aware expiry.

    Two scopes exist so the approval prompt's ``once`` and ``always`` mean
    what they say:

    * ``once``  — covers only paraphrased retries within the same user turn
                  (rm → os.remove within one model response). Cleared at the
                  start of every new user message via :meth:`clear_scope`.
    * ``always`` — persists for the full session TTL; re-prompts won't appear
                  for the same intent until the process restarts.
    """

    def __init__(self, default_ttl: float = _DEFAULT_TTL_SECONDS) -> None:
        self._default_ttl = default_ttl
        # intent -> (expires_monotonic, scope, approved_flags)
        self._entries: dict[tuple[str, str], tuple[float, str, frozenset[str]]] = {}
        self._lock = threading.Lock()

    def record(
        self, command: str, ttl: float | None = None, *, scope: str = "once"
    ) -> list[tuple[str, str, frozenset[str]]]:
        """Mark every intent extracted from *command* as approved.

        Handles multi-target commands like ``rm a b c`` — each path becomes its
        own cache entry. Returns the list of recorded intents (empty if none
        could be extracted).
        """
        intents = _extract_intents(command)
        if not intents:
            return []
        expires = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        with self._lock:
            for kind, target, flags in intents:
                key = (kind, target)
                existing = self._entries.get(key)
                if existing is not None:
                    # Keep the later expiry; union flags so approved
                    # capability only grows, never shrinks.
                    new_expiry = max(existing[0], expires)
                    new_scope = existing[1] if existing[0] >= expires else scope
                    self._entries[key] = (new_expiry, new_scope, existing[2] | flags)
                else:
                    self._entries[key] = (expires, scope, flags)
        return intents

    def record_always(self, command: str) -> list[tuple[str, str, frozenset[str]]]:
        """Remember every intent in *command* for the session lifetime."""
        return self.record(command, ttl=_ALWAYS_TTL_SECONDS, scope="always")

    def check(self, command: str) -> bool:
        """Return True only when **every** extracted intent is still approved.

        Multi-target commands must have approval for *all* targets — one
        missing path means the whole command needs fresh approval.  The
        approved escalation flags must be a superset of the requested flags
        so ``rm -rf /a`` can never replay on a ``rm /a`` approval.
        """
        intents = _extract_intents(command)
        if not intents:
            return False
        now = time.monotonic()
        with self._lock:
            for kind, target, flags in intents:
                key = (kind, target)
                entry = self._entries.get(key)
                if entry is None:
                    return False
                expires, _scope, approved_flags = entry
                if expires < now:
                    self._entries.pop(key, None)
                    return False
                if not flags <= approved_flags:
                    return False
        return True

    def forget(self, command: str) -> None:
        intents = _extract_intents(command)
        if not intents:
            return
        with self._lock:
            for kind, target, _flags in intents:
                self._entries.pop((kind, target), None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def clear_scope(self, scope: str) -> None:
        """Drop every entry whose scope matches, leaving other scopes intact."""
        with self._lock:
            self._entries = {
                intent: data for intent, data in self._entries.items() if data[1] != scope
            }


_cache: IntentApprovalCache | None = None


def get_intent_cache() -> IntentApprovalCache:
    global _cache
    if _cache is None:
        _cache = IntentApprovalCache()
    return _cache


def reset_intent_cache() -> None:
    """Test hook — drop the singleton."""
    global _cache
    _cache = None
