import ast
import itertools
from pathlib import Path

from odoo.tools.misc import file_open

from . import lint_case


class L10nChecker(lint_case.NodeVisitor):
    def matches_tagged(self, node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                return node.func.attr == "tagged"
            if isinstance(node.func, ast.Name):
                return node.func.id == "tagged"
        return False

    def visit_ClassDef(self, node):
        tags = {
            arg.value
            for deco in node.decorator_list
            if self.matches_tagged(deco)
            for arg in deco.args
            if isinstance(arg, ast.Constant)
        }
        if (
            (len({"post_install_l10n", "external_l10n"} & tags) != 1)
            or ("post_install_l10n" in tags and "post_install" not in tags)
            or (("external_l10n" in tags) ^ ("external" in tags))
        ):
            if any(
                stmt.name.startswith("test_")
                for stmt in node.body
                if isinstance(stmt, ast.FunctionDef)
            ):
                return [node]
        return []


class L10nLinter(lint_case.LintCase):
    def test_l10n_test_tags(self):
        checker = L10nChecker()
        rs = []
        for path in self.iter_module_files("**/l10n_*/tests/*.py"):
            if not lint_case.is_core_path(path):
                continue
            with file_open(path, "rb") as f:
                t = ast.parse(f.read(), path)
            rs.extend(
                zip(
                    itertools.repeat(
                        str(Path(path).relative_to(lint_case.core_root()))
                    ),
                    checker.visit(t),
                )
            )

        # Ratcheted like every other gate here, and reported relative to the
        # repository rather than to `Path.cwd()`: the old form printed a
        # different path depending on where the runner happened to be started,
        # which is not something a failure message should depend on.
        self.assert_ratchet(
            sorted(f"{path}:{node.lineno}" for path, node in rs),
            0,
            "l10n test class(es) without the right post_install_l10n tagging",
            "Tag the class `post_install_l10n` (with `post_install`) or "
            "`external_l10n` (with `external`), never both and never neither.",
        )
