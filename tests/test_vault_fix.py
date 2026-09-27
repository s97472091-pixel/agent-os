"""Regression test for #3430: Vault.change_password FileNotFoundError on missing keystore."""
from pathlib import Path

import pytest

from agentos.trading.vault import Vault


def test_change_password_skips_missing_keystore(tmp_path: Path) -> None:
    """When a wallet keystore is deleted, change_password must not crash."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    # Initialize vault and add two wallets
    vault = Vault(vault_dir)
    vault.setup(password="oldpassword", unlock_mode="auto")

    addr1 = vault.create("w1").address
    addr2 = vault.create("w2").address

    vault.lock()
    vault.unlock(password="oldpassword")

    # Verify both keystores exist
    assert vault.keystore_path(addr1).is_file()
    assert vault.keystore_path(addr2).is_file()

    # Delete one keystore to simulate the bug scenario
    vault.keystore_path(addr2).unlink()
    vault.change_password(password="oldpassword", new_password="newpassword")
    vault.lock()

    # Verify the remaining wallet can be unlocked with the new password
    vault.unlock(password="newpassword")
    assert vault.list()
    vault.lock()

    print("PASS: change_password handled missing keystore gracefully")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "-s"]))
