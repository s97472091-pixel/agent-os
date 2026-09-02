"""Regression tests for AST-based destructive pattern detection in code_exec.

Issue #848: the regex-based whitelist could be bypassed with getattr string
concatenation, __import__ / importlib.import_module dynamic imports,
exec/eval wrappers, and `from os import *` wildcard imports. The AST
analyzer must catch these obfuscated spellings just like the obvious
`os.remove()` form.
"""

from __future__ import annotations

from agentos.tools.builtin import code_exec


def _assert_destructive(code: str) -> None:
    result = code_exec._check_code_destructive(code)
    assert result is not None, f"expected destructive flag, got None for: {code!r}"


def _assert_clean(code: str) -> None:
    result = code_exec._check_code_destructive(code)
    assert result is None, f"expected clean, got: {result!r} for: {code!r}"


class TestRegexCompatibility:
    """The original literal forms must still be flagged."""

    def test_os_remove(self) -> None:
        _assert_destructive('os.remove("/tmp/x")')

    def test_os_unlink(self) -> None:
        _assert_destructive('os.unlink("/tmp/x")')

    def test_os_rmdir(self) -> None:
        _assert_destructive('os.rmdir("/tmp/x")')

    def test_os_removedirs(self) -> None:
        _assert_destructive('os.removedirs("/tmp/x")')

    def test_shutil_rmtree(self) -> None:
        _assert_destructive('shutil.rmtree("/tmp/x")')

    def test_path_unlink(self) -> None:
        _assert_destructive('Path("/tmp/x").unlink()')

    def test_pathlib_path_unlink(self) -> None:
        _assert_destructive('pathlib.Path("/tmp/x").unlink()')

    def test_os_system_with_rm(self) -> None:
        _assert_destructive('os.system("rm -rf /tmp/x")')

    def test_subprocess_run_with_rm(self) -> None:
        _assert_destructive('subprocess.run(["rm", "-rf", "/tmp/x"])')


class TestGetattrBypass:
    """getattr with a folded attribute name must be caught."""

    def test_getattr_remove_string_concat(self) -> None:
        _assert_destructive('getattr(os, "rem" + "ove")("/tmp/x")')

    def test_getattr_remove_literal(self) -> None:
        _assert_destructive('getattr(os, "remove")("/tmp/x")')

    def test_getattr_rmtree(self) -> None:
        _assert_destructive('getattr(shutil, "rmtree")("/tmp/x")')

    def test_getattr_on_imported_module(self) -> None:
        _assert_destructive('getattr(__import__("os"), "remove")("/tmp/x")')

    def test_dynamic_attribute_on_os_is_opaque(self) -> None:
        # A non-literal attribute name on a destructive module cannot be
        # proven safe.
        _assert_destructive('getattr(os, name)("/tmp/x")')

    def test_clean_getattr(self) -> None:
        # Benign attribute access on a non-destructive module stays clean.
        _assert_clean('getattr(json, "dumps")({"a": 1})')


class TestDynamicImportBypass:
    """__import__ / importlib.import_module of a destructive module."""

    def test_dunder_import_os_remove(self) -> None:
        _assert_destructive('__import__("os").remove("/tmp/x")')

    def test_importlib_import_module_os_remove(self) -> None:
        _assert_destructive('importlib.import_module("os").remove("/tmp/x")')

    def test_dunder_import_os_alone(self) -> None:
        # Importing a destructive module dynamically is itself a gate signal.
        _assert_destructive('m = __import__("os")')

    def test_importlib_import_module_shutil_alone(self) -> None:
        _assert_destructive('m = importlib.import_module("shutil")')

    def test_dunder_import_benign_module_clean(self) -> None:
        _assert_clean('m = __import__("json")')


class TestExecEvalWrapper:
    """Destructive code hidden inside exec/eval must be caught."""

    def test_exec_os_remove(self) -> None:
        _assert_destructive("exec(\"os.remove('/tmp/x')\")")

    def test_eval_os_remove(self) -> None:
        _assert_destructive("eval(\"os.remove('/tmp/x')\")")

    def test_exec_getattr_concat(self) -> None:
        _assert_destructive("exec(\"getattr(os, 'rem' + 'ove')('/tmp/x')\")")

    def test_exec_clean_code_clean(self) -> None:
        _assert_clean('exec("x = 1 + 1")')


class TestWildcardImportBypass:
    """`from os import *` hides destructive names from per-call analysis."""

    def test_from_os_star(self) -> None:
        _assert_destructive("from os import *; remove('/tmp/x')")

    def test_from_shutil_star(self) -> None:
        _assert_destructive("from shutil import *; rmtree('/tmp/x')")

    def test_from_pathlib_star(self) -> None:
        _assert_destructive("from pathlib import *; Path('/tmp/x').unlink()")


class TestFalsePositiveGuard:
    """Code that merely mentions destructive words must stay clean."""

    def test_plain_string_literal(self) -> None:
        _assert_clean('print("os.remove is dangerous")')

    def test_benign_computation(self) -> None:
        _assert_clean("total = sum(x for x in range(10))")

    def test_list_remove_method_is_clean(self) -> None:
        # `.remove` on a plain list is not a destructive filesystem op.
        _assert_clean("items = [1, 2]; items.remove(1)")

    def test_dotted_name_in_comment_only(self) -> None:
        _assert_clean('# os.remove("/tmp/x")')

    def test_non_destructive_attr_on_unknown_base(self) -> None:
        _assert_clean('thing.cleanup("/tmp/x")')


class TestRecursiveNesting:
    """Bypass spellings can nest — each layer must resolve."""

    def test_getattr_of_dunder_import(self) -> None:
        _assert_destructive('getattr(__import__("os"), "rem" + "ove")("/tmp/x")')

    def test_exec_wrapping_dynamic_import(self) -> None:
        _assert_destructive("exec(\"__import__('os').remove('/tmp/x')\")")

    def test_importlib_dynamic_getattr(self) -> None:
        _assert_destructive('getattr(importlib.import_module("os"), "remove")("/tmp/x")')
