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
    #: False for the framework (``odoo/orm``, ``odoo/tools``, ...), which is
    #: core code but belongs to no addon.
    in_module: bool


@dataclass(frozen=True, slots=True)
class Unit:
    """Everything a checker may need about one file, derived exactly once."""

    path: str
    source: str
    tree: ast.Module
    #: ``ast.walk(tree)`` materialised. Traversing the tree, not analysing it,
    #: was most of what the checkers cost: unlink 4.2 s, onchange 4.7 s, batch
    #: 2.5 s, gettext 2.2 s, orm-import 2.2 s over the corpus, and each of those
    #: figures is dominated by its own private ``ast.walk``. One walk, shared.
    nodes: list[ast.AST]
    in_module: bool


#: Every rule name a checker here can emit. Stated rather than derived, because
#: the gettext checker chooses among four of them per finding: a rule that stops
#: firing must not silently vanish from the gate.
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

#: The rationale check is line-based, so a file that *writes about* ``# noqa``
#: -- the checker, the suppression logic, and their tests -- reports its own
#: examples. Excluding them is not a waiver: none of these lines suppresses
#: anything.
_NOQA_SELF = (
    "/test_lint/tests/_checker_noqa_rationale.py",
    "/test_lint/tests/_suppression.py",
    "/test_lint/tests/_py_scan.py",
    "/test_lint/tests/test_checkers.py",
    "/test_lint/tests/test_python_lint.py",
)


def _sql(unit: Unit) -> Iterator[object]:
    # Not driven by `unit.nodes`: this checker carries per-node state and
    # resolves names against an enclosing scope, so it owns its traversal.
    _checker_sql.annotate_parents(unit.tree)
    yield from _checker_sql.SqlInjectionChecker(unit.path).check(unit.tree)


#: ``(rule, runner, scope)``. *rule* is the reported name -- or ``None`` when
#: the checker sets its own, as the gettext one does. *scope* answers whether a
#: given file is this rule's business.
_CHECKERS: list[
    tuple[str | None, Callable[[Unit], Iterator], Callable[[Unit], bool]]
] = [
    ("sql-injection", _sql, lambda u: True),
    (
        None,
        lambda u: _checker_gettext.check(u.tree, u.path, u.nodes),
        lambda u: True,
    ),
    (
        "raise-unlink-override",
        lambda u: _checker_unlink.check(u.tree, u.nodes),
        lambda u: True,
    ),
    (
        "n-plus-one-query",
        lambda u: _checker_batch.check(u.tree, u.path, u.nodes),
        lambda u: True,
    ),
    (
        "noqa-rationale",
        lambda u: _checker_noqa_rationale.find_violations(u.source),
        lambda u: not u.path.endswith(_NOQA_SELF),
    ),
    # An addon rule: the framework may of course import its own internals, and
    # `odoo/orm/*.py` importing `odoo.orm` is not a finding.
    (
        "orm-import",
        lambda u: _checker_orm_import.check(u.tree, u.path, u.nodes),
        lambda u: u.in_module,
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
        unit = Unit(entry.path, text, tree, list(ast.walk(tree)), entry.in_module)

        for rule, runner, in_scope in _CHECKERS:
            if not in_scope(unit):
                continue
            try:
                violations = list(runner(unit))
            except RecursionError:
                # A pathologically nested expression; the file is not skipped
                # silently, because "no findings" and "never analysed" must not
                # look the same.
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
                # `raw` is the noqa checker's spelling; it carries the offending
                # source line, which is the only useful thing to print for it.
                message = getattr(violation, "message", "") or getattr(
                    violation, "raw", ""
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
