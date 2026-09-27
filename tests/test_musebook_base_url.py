"""Regression tests for #3435: musebook skill uses live .me domain."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUSE_SCRIPT = ROOT / "src/agentos/skills/bundled/musebook/scripts/muse.py"
MUSE_SKILL = ROOT / "src/agentos/skills/bundled/musebook/SKILL.md"
MUSE_TXT = ROOT / "src/agentos/skills/bundled/musebook/references/muse.txt"
PUBLISHERS = ROOT / "src/agentos/skills/publishers.py"


FUNCTIONAL_PATHS = {
    "muse.py": MUSE_SCRIPT,
    "SKILL.md": MUSE_SKILL,
    "publishers.py": PUBLISHERS,
}


def _lines_with(text: str, needle: str) -> list[str]:
    return [line for line in text.splitlines() if needle in line]


def test_no_old_domain_in_functional_files():
    """Executable/config files must not reference the expired .lol domain."""
    for name, path in FUNCTIONAL_PATHS.items():
        content = path.read_text(encoding="utf-8")
        lines = _lines_with(content, "musebook.lol")
        assert not lines, f"{name} still contains 'musebook.lol': {lines[:3]}"


def test_live_domain_present_in_functional_files():
    """The new .me domain must be present in every functional file."""
    for name, path in FUNCTIONAL_PATHS.items():
        content = path.read_text(encoding="utf-8")
        assert "musebook.me" in content, f"{name} missing 'musebook.me'"


def test_muse_txt_uses_live_domain_for_urls():
    """The onboarding copy must use musebook.me for functional URLs/endpoints."""
    content = MUSE_TXT.read_text(encoding="utf-8")
    assert "https://musebook.me/" in content, "muse.txt missing https://musebook.me/ URLs"
    # The live file still mentions the old domain only to explain the migration;
    # no actual endpoint should point there.
    old_urls = [line for line in content.splitlines() if "https://musebook.lol/" in line]
    assert not old_urls, f"muse.txt still uses old URL: {old_urls[:3]}"
