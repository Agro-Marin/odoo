import ast
import itertools
from pathlib import Path

from odoo.tools.misc import file_open

from . import lint_case


class OnchangeChecker(lint_case.NodeVisitor):
    def matches_onchange(self, node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                return node.func.attr == "onchange"
            if isinstance(node.func, ast.Name):
                return node.func.id == "onchange"
        return False

    def visit_FunctionDef(self, node):
        walker = (
            ast.walk(node)
            if any(map(self.matches_onchange, node.decorator_list))
            else []
        )
        return itertools.islice(
            (n for n in walker if isinstance(n, ast.Constant) and n.value == "domain"),
            1,
        )


class TestOnchangeDomains(lint_case.LintCase):
    def test_forbid_domains_in_onchanges(self):
        checker = OnchangeChecker()
        rs = []
        for path in self.iter_module_files("*.py"):
            with file_open(path, "rb") as f:
                t = ast.parse(f.read(), path)
            rs.extend(
                zip(
                    itertools.repeat(
                        str(Path(path).relative_to(Path.cwd(), walk_up=True))
                    ),
                    checker.visit(t),
                )
            )

        rs.sort(key=lambda t: t[0])
        assert not rs, "probable domains in onchanges at\n" + "\n".join(
            "- %s:%d" % (path, node.lineno) for path, node in rs
        )
