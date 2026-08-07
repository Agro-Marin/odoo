"""One parse of the Python corpus, shared by every AST-based lint test.

Before this module there were five full-corpus passes: the four checkers in
``test_ruff`` each re-read and re-``ast.parse``d all 8 509 core files, and
``test_onchange_domains`` did it again over all 18 272. Measured on this
workspace, one read+parse pass is **11.0 s** and the analysis that follows it
is 1.6-11.4 s per checker -- so roughly 33 s of an 84 s suite was spent
re-deriving a syntax tree that had just been thrown away, and
``test_unlink_override`` was ~75 % parsing for a check that walks the tree once
and reports two findings.

Parsing once and dispatching to every checker removes that. The trees are not
cached -- 18 k simultaneous ``ast.Module`` objects is gigabytes -- so the unit
of work is one file: read it, parse it, run everything that applies, discard.
The whole scan is memoised, so the first test to ask pays for it and the rest
read the result.

**Coverage.** The corpus is the addon roots *plus the framework itself*.
``odoo/orm``, ``odoo/tools``, ``odoo/http`` and ``odoo/service`` sit beside
``odoo/addons`` rather than inside it, so a module-driven scan could never see
them -- 531 files, ``odoo/tools/sql.py`` among them. Every checker here was
blind to the half of the repository most likely to build SQL by hand.
"""

import ast
import functools
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from . import (
    _checker_batch,
    _checker_gettext,
    _checker_noqa_rationale,
    _checker_onchange,
    _checker_orm_import,
    _checker_sql,
    _checker_unlink,
    lint_case,
)
from ._suppression import is_suppressed

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation, normalised across every checker."""

    path: str
    lineno: int
    rule: str
    message: str = ""

    def __str__(self) -> str:
        tail = f" {self.message}" if self.message else ""
        return f"{self.path}:{self.lineno} [{self.rule}]{tail}"


@dataclass(frozen=True, slots=True)
class Source:
    """A file in the corpus."""

    path: str
    in_module: bool


@dataclass(frozen=True, slots=True)
class Unit:
    """Everything a checker may need about one file, derived exactly once."""

    path: str
    source: str
    tree: ast.Module
    nodes: list[ast.AST]
    in_module: bool
    is_test: bool = False


def is_test_path(path: str) -> bool:
    """Whether *path* holds test code, for every rule that exempts it.

    There were three answers to this question and they disagreed. The SQL
    checker asked whether the *basename* started with ``test_``; gettext asked
    whether ``/test_`` or ``/tests/`` appeared anywhere in the path; the batch
    checker asked for the basename *or* ``/tests/``. So
    ``addons/base/tests/common.py`` -- a test helper by any reading -- was
    scanned for SQL injection and by nothing else, and which rules applied to a
    file depended on which checker happened to be looking.

    One definition, the union of the three: any path component named ``tests``
    or starting with ``test_``. That covers a ``tests`` directory, a
    ``test_*.py`` module, and a whole ``test_*`` addon -- which matters,
    because ``test_mail``'s and ``test_orm``'s models are scaffolding for the
    suite and nothing else. The gettext checker had them by accident, through
    ``"/test_" in filepath``; stating it deliberately is what lets the other
    rules agree.
    """
    return any(part == "tests" or part.startswith("test_") for part in path.split("/"))


def walk_with_parents(tree: ast.AST) -> list[ast.AST]:
    """Depth-first pre-order node list, with ``_parent`` set on every child."""
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        nodes.append(node)
        children = list(ast.iter_child_nodes(node))
        for child in children:
            child._parent = node
        stack.extend(reversed(children))
    return nodes


RULES = frozenset(
    {
        "sql-injection",
        "gettext-variable",
        "gettext-placeholders",
        "gettext-repr",
        "missing-gettext",
        "raise-unlink-override",
        "n-plus-one-query",
        "orm-import",
        "onchange-domain",
        "noqa-rationale",
    }
)

_NOQA_SELF = (
    "/test_lint/tests/_checker_noqa_rationale.py",
    "/test_lint/tests/_suppression.py",
    "/test_lint/tests/_py_scan.py",
    "/test_lint/tests/test_checkers.py",
    "/test_lint/tests/test_python_lint.py",
)


def _sql(unit: Unit) -> Iterator[object]:
    checker = _checker_sql.SqlInjectionChecker(unit.path, is_test=unit.is_test)
    yield from checker.check_nodes(unit.nodes)


_CHECKERS: list[
    tuple[str | None, Callable[[Unit], Iterator], Callable[[Unit], bool]]
] = [
    ("sql-injection", _sql, lambda u: not u.is_test),
    (
        None,
        lambda u: _checker_gettext.check(u.tree, u.nodes),
        lambda u: not u.is_test,
    ),
    (
        "raise-unlink-override",
        lambda u: _checker_unlink.check(u.tree, u.nodes),
        lambda u: True,
    ),
    (
        "n-plus-one-query",
        lambda u: _checker_batch.check(u.tree, u.nodes),
        lambda u: not u.is_test,
    ),
    (
        "noqa-rationale",
        lambda u: _checker_noqa_rationale.find_violations(u.source),
        lambda u: not u.path.endswith(_NOQA_SELF),
    ),
    (
        "orm-import",
        lambda u: _checker_orm_import.check(u.tree, u.nodes),
        lambda u: u.in_module and not u.is_test,
    ),
    (
        "onchange-domain",
        lambda u: _checker_onchange.check(u.tree, u.path, u.nodes),
        lambda u: u.in_module,
    ),
]


@functools.cache
def corpus() -> tuple[Source, ...]:
    """Every Python file this repository owns, addons and framework alike.

    Sibling checkouts (``enterprise``, ``design-themes``, ``agromarin``) are
    excluded: 55 % of this suite's failures came from code the fork must not
    edit, and a gate nobody can act on is a gate nobody reads. Upgrade and
    migration scripts are excluded too -- they are written against the schema of
    a version that is already gone and are never imported by running code.
    """
    seen: set[str] = set()
    sources: list[Source] = []
    for path in lint_case.module_file_paths():
        if not path.endswith(".py") or not lint_case.is_core_path(path):
            continue
        if "/upgrades/" in path or "/migrations/" in path:
            continue
        if path not in seen:
            seen.add(path)
            sources.append(Source(path, in_module=True))
    for path in lint_case.framework_paths():
        if path not in seen:
            seen.add(path)
            sources.append(Source(path, in_module=False))
    return tuple(sorted(sources, key=lambda s: s.path))


def _source_line(text: str, lineno: int, limit: int = 110) -> str:
    """The offending line of source, trimmed, for a checker that reports none."""
    lines = text.split("\n")
    if not 1 <= lineno <= len(lines):
        return ""
    line = lines[lineno - 1].strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


@functools.cache
def findings() -> dict[str, list[Finding]]:
    """Run every Python checker over the corpus in a single parse pass.

    Suppressed findings are dropped here rather than by each caller, so
    ``# noqa`` means the same thing to every rule.
    """
    by_rule: dict[str, list[Finding]] = {}
    parse_errors = 0

    for entry in corpus():
        try:
            raw = Path(entry.path).read_bytes()
            text = raw.decode("utf-8", errors="replace")
            tree = ast.parse(raw, entry.path)
        except OSError, SyntaxError, ValueError:
            parse_errors += 1
            continue
        unit = Unit(
            entry.path,
            text,
            tree,
            walk_with_parents(tree),
            entry.in_module,
            is_test_path(entry.path),
        )

        for rule, runner, in_scope in _CHECKERS:
            if not in_scope(unit):
                continue
            try:
                violations = list(runner(unit))
            except RecursionError:
                _logger.warning(
                    "%s: %s checker hit the recursion limit, file not analysed",
                    entry.path,
                    rule or "gettext",
                )
                continue
            for violation in violations:
                name = rule or violation.rule
                lineno = violation.lineno
                if is_suppressed(text, lineno, name):
                    continue
                message = (
                    getattr(violation, "message", "")
                    or getattr(violation, "raw", "")
                    or _source_line(text, lineno)
                )
                by_rule.setdefault(name, []).append(
                    Finding(entry.path, lineno, name, message.strip())
                )

    if parse_errors:
        _logger.info("%s file(s) could not be parsed and were skipped", parse_errors)
    _logger.info(
        "scanned %s Python files, %s finding(s) across %s rule(s)",
        len(corpus()),
        sum(map(len, by_rule.values())),
        len(by_rule),
    )
    return by_rule


def report(rule: str, header: str) -> str:
    """A sorted, one-per-line report for *rule*, or ``""`` when it is clean."""
    found = sorted(findings().get(rule, []), key=lambda f: (f.path, f.lineno))
    if not found:
        return ""
    return f"{len(found)} {header}:\n  " + "\n  ".join(map(str, found))
