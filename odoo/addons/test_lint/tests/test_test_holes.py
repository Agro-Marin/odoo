import ast
import logging
import os
import pathlib
import unittest.mock
from collections import Counter

from odoo.modules import Manifest

from odoo.addons.test_lint.tests.lint_case import LintCase

_logger = logging.getLogger(__name__)


class InitChecker(ast.NodeVisitor):
    def __init__(self):
        self.path = None
        self.names = Counter()
        self.prefix = ""

    def visit_Import(self, node):
        raise AssertionError(
            f"Init files should not have top-level imports, found {ast.dump(node)}"
        )

    def visit_ImportFrom(self, node):
        assert node.level == 1, f"{ast.dump(node)} should be a `from . import ...`"

        if node.module:
            assert "." not in node.module, "only supports one level of relative import"
            [alias] = node.names
            assert (alias.name, alias.asname) == (
                "*",
                None,
            ), (
                f"only star-imports can be used to import test sub-modules, got {ast.dump(node)}"
            )
            with unittest.mock.patch.object(
                self, "prefix", f"{self.prefix}{node.module}/"
            ):
                init = self.path / self.prefix / "__init__.py"
                self.visit(ast.parse(init.read_bytes(), init))
        else:
            for alias in node.names:
                if alias.name.startswith("test_"):
                    self.names[f"{self.prefix}{alias.name}.py"] += 1


class TestTestHoles(LintCase):
    def test_check_tests(self):
        checker = InitChecker()

        errors = []
        checked = 0
        for manifest in Manifest.all_addon_manifests():
            checker.names.clear()
            p = checker.path = pathlib.Path(manifest.path, "tests")
            if not p.exists():
                continue

            init = p / "__init__.py"
            if not init.exists():
                # Collected, not raised. A bare `assert` here aborted the whole
                # scan on the first offender: it fired on `cloud_storage`, the
                # 119th of 986 modules with a tests directory, so the remaining
                # 866 were never examined at all -- and only two modules in the
                # tree actually have this problem.
                errors.append(f"Python test directory without an __init__: {p}")
                continue

            checked += 1
            try:
                checker.visit(ast.parse(init.read_bytes(), init))
            except (AssertionError, SyntaxError, OSError) as exc:
                # Likewise: one unparseable or non-trivial init must not hide
                # every module after it.
                errors.append(f"{init}: {exc}")
                continue

            for f in p.rglob("test_*.py"):
                if f.match("odoo/addons/base/tests/test_uninstall.py"):
                    continue
                checker.names[os.fspath(f.relative_to(p))] -= 1

            for test_path, count in checker.names.items():
                match count:
                    case -1:
                        errors.append(f"Test file {test_path} never imported in {init}")
                    case 0:
                        pass
                    case _:
                        errors.append(
                            f"Test file {test_path} imported multiple times in {init}"
                        )

        _logger.info("checked the test init of %s modules", checked)
        self.assertTrue(checked, "the scan reached no test directories at all")
        if errors:
            raise AssertionError(
                f"Found {len(errors)} test error(s):"
                + "".join(f"\n- {e}" for e in sorted(errors))
            )
