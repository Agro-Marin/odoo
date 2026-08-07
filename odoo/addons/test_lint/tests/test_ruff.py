import ast
import logging
import re
from pathlib import Path

from odoo import tools
from odoo.tools.misc import file_open

from . import _checker_batch, _checker_gettext, _checker_sql, _checker_unlink, lint_case

_logger = logging.getLogger(__name__)

_PYLINT_DISABLE_RE = re.compile(r"#\s*pylint:\s*disable=([^\n]+)")

_RULE_ALIASES: dict[str, frozenset[str]] = {
    "sql-injection": frozenset({"sql-injection", "E8501"}),
    "gettext-variable": frozenset({"gettext-variable", "E8502"}),
    "gettext-placeholders": frozenset({"gettext-placeholders", "E8503"}),
    "gettext-repr": frozenset({"gettext-repr", "E8504"}),
    "missing-gettext": frozenset({"missing-gettext", "E8505"}),
    "raise-unlink-override": frozenset({"raise-unlink-override", "E8506"}),
    "n-plus-one-query": frozenset({"n-plus-one-query", "E8507"}),
}


def _is_core_path(path: str) -> bool:
    root = tools.config.root_path
    core_dir = str(Path(root).parent)
    return path.startswith(core_dir)


def _is_suppressed(source: bytes | str, lineno: int, rule: str) -> bool:
    lines = (source if isinstance(source, bytes) else source.encode()).split(b"\n")
    if lineno < 1 or lineno > len(lines):
        return False
    line = lines[lineno - 1].decode(errors="replace")

    if m := _PYLINT_DISABLE_RE.search(line):
        disabled = {tok.strip() for tok in m.group(1).split(",")}
        aliases = _RULE_ALIASES.get(rule, frozenset({rule}))
        if disabled & aliases:
            return True

    if "# noqa" in line:
        noqa_idx = line.index("# noqa")
        rest = line[noqa_idx + 6 :].strip()
        if not rest or rest.startswith("  "):
            return True
        if rest.startswith(":"):
            codes = {c.strip() for c in rest[1:].split(",")}
            aliases = _RULE_ALIASES.get(rule, frozenset({rule}))
            if codes & aliases:
                return True

    return False


class TestRuff(lint_case.LintCase):
    def _iter_core_python_files(self):
        for path in self.iter_module_files("*.py"):
            if not _is_core_path(path):
                continue
            if "/upgrades/" in path or "/migrations/" in path:
                continue
            yield path

    def test_sql_injection(self):
        violations = []
        for path in self._iter_core_python_files():
            try:
                with file_open(path, "rb") as f:
                    source = f.read()
                tree = ast.parse(source, path)
            except SyntaxError:
                continue
            _checker_sql.annotate_parents(tree)
            checker = _checker_sql.SqlInjectionChecker(path)
            violations.extend(
                (path, v)
                for v in checker.check(tree)
                if not _is_suppressed(source, v.lineno, "sql-injection")
            )

        if violations:
            violations.sort(key=lambda t: t[0])
            msg = "SQL injection risks detected:\n" + "\n".join(
                f"- {path}:{v.lineno}" for path, v in violations
            )
            self.fail(msg)

    def test_gettext(self):
        violations = []
        for path in self._iter_core_python_files():
            try:
                with file_open(path, "rb") as f:
                    source = f.read()
                tree = ast.parse(source, path)
            except SyntaxError:
                continue
            violations.extend(
                (path, v)
                for v in _checker_gettext.check(tree, path)
                if not _is_suppressed(source, v.lineno, v.rule)
            )

        if violations:
            violations.sort(key=lambda t: t[0])
            msg = "gettext violations detected:\n" + "\n".join(
                f"- {path}:{v.lineno} [{v.rule}] {v.message}" for path, v in violations
            )
            self.fail(msg)

    def test_unlink_override(self):
        violations = []
        for path in self._iter_core_python_files():
            try:
                with file_open(path, "rb") as f:
                    source = f.read()
                tree = ast.parse(source, path)
            except SyntaxError:
                continue
            violations.extend(
                (path, v)
                for v in _checker_unlink.check(tree)
                if not _is_suppressed(source, v.lineno, "raise-unlink-override")
            )

        if violations:
            violations.sort(key=lambda t: t[0])
            msg = "raise inside unlink override:\n" + "\n".join(
                f"- {path}:{v.lineno}" for path, v in violations
            )
            self.fail(msg)

    def test_batch_queries(self):
        violations = []
        for path in self._iter_core_python_files():
            try:
                with file_open(path, "rb") as f:
                    source = f.read()
                tree = ast.parse(source, path)
            except SyntaxError:
                continue
            violations.extend(
                (path, v)
                for v in _checker_batch.check(tree, path)
                if not _is_suppressed(source, v.lineno, "n-plus-one-query")
            )

        if violations:
            violations.sort(key=lambda t: t[0])
            msg = "N+1 query patterns detected (%d):\n%s" % (
                len(violations),
                "\n".join(f"- {path}:{v.lineno} {v.message}" for path, v in violations),
            )
            _logger.warning(msg)
