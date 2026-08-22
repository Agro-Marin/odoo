import ast
import functools
import logging
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import (
    _checker_batch,
    _checker_config_patch,
    _checker_gettext,
    _checker_noqa_rationale,
    _checker_onchange,
    _checker_orm_import,
    _checker_sql,
    _checker_unlink,
    lint_case,
)
from ._suppression import Suppressions, comment_lines

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    lineno: int
    rule: str
    message: str = ""

    def __str__(self) -> str:
        tail = f" {self.message}" if self.message else ""
        return f"{self.path}:{self.lineno} [{self.rule}]{tail}"


@dataclass(frozen=True, slots=True)
class Source:
    path: str
    in_module: bool


@dataclass(frozen=True, slots=True)
class Unit:
    path: str
    source: str
    tree: ast.Module
    nodes: list[ast.AST]
    in_module: bool
    is_test: bool = False
    comments: dict[int, str] | None = None


def is_test_path(path: str) -> bool:
    return any(part == "tests" or part.startswith("test_") for part in path.split("/"))


def walk_with_parents(tree: ast.AST) -> list[ast.AST]:
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
        "gettext-developer-error",
        "raise-unlink-override",
        "n-plus-one-query",
        "orm-import",
        "onchange-domain",
        "noqa-rationale",
        "config-chainmap-patch",
    }
)


def _sql(unit: Unit) -> Iterator[object]:
    return _checker_sql.SqlInjectionChecker(unit.path).check_nodes(unit.nodes)


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
        lambda u: _checker_noqa_rationale.find_violations(u.comments),
        lambda u: True,
    ),
    (
        "orm-import",
        lambda u: _checker_orm_import.check(u.tree, u.nodes),
        lambda u: u.in_module and not u.is_test,
    ),
    (
        "onchange-domain",
        lambda u: _checker_onchange.check(u.tree, u.nodes),
        lambda u: u.in_module,
    ),
    (
        "config-chainmap-patch",
        lambda u: _checker_config_patch.check(u.tree, u.nodes),
        lambda u: True,
    ),
]


@functools.cache
def corpus() -> tuple[Source, ...]:
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
    lines = text.split("\n")
    if not 1 <= lineno <= len(lines):
        return ""
    line = lines[lineno - 1].strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


def scan_one(path: str, in_module: bool) -> list[tuple[str, str, int, str]]:
    try:
        raw = Path(path).read_bytes()
        text = raw.decode("utf-8", errors="replace")
        tree = ast.parse(raw, path)
    except OSError, SyntaxError, ValueError:
        return []

    unit = Unit(
        path,
        text,
        tree,
        walk_with_parents(tree),
        in_module,
        is_test_path(path),
        comment_lines(text),
    )
    suppressions = Suppressions.from_comments(unit.comments)

    out: list[tuple[str, str, int, str]] = []
    for rule, runner, in_scope in _CHECKERS:
        if not in_scope(unit):
            continue
        try:
            violations = list(runner(unit))
        except RecursionError:
            continue
        for violation in violations:
            name = rule or violation.rule
            lineno = violation.lineno
            if suppressions.suppresses(lineno, name):
                continue
            message = (
                getattr(violation, "message", "")
                or getattr(violation, "raw", "")
                or _source_line(text, lineno)
            )
            out.append((name, path, lineno, message.strip()))
    return out


def scan_many(entries: list[tuple[str, bool]]) -> list[tuple[str, str, int, str]]:
    return [f for path, in_module in entries for f in scan_one(path, in_module)]


def _job_count(work: int) -> int:
    override = os.environ.get("TEST_LINT_JOBS")
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            _logger.warning(
                "TEST_LINT_JOBS=%r is not a number, scanning serially", override
            )
            return 1
    if work < 500:
        return 1
    return max(1, min(16, (os.process_cpu_count() or 1) - 2))


def _stop_multiprocessing_helpers() -> None:
    import multiprocessing.forkserver
    import multiprocessing.resource_tracker

    for holder in (
        getattr(multiprocessing.forkserver, "_forkserver", None),
        getattr(multiprocessing.resource_tracker, "_resource_tracker", None),
    ):
        stop = getattr(holder, "_stop", None)
        if stop is None:
            continue
        try:
            stop()
        except Exception:
            _logger.debug("could not stop a multiprocessing helper", exc_info=True)


def _run_parallel(entries: list[tuple[str, bool]], jobs: int):
    chunks = [entries[index :: jobs * 4] for index in range(jobs * 4)]
    try:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            return [row for part in pool.map(scan_many, chunks) for row in part]
    finally:
        _stop_multiprocessing_helpers()


@functools.cache
def findings() -> dict[str, list[Finding]]:
    entries = [(source.path, source.in_module) for source in corpus()]

    jobs = _job_count(len(entries))
    rows = None
    if jobs > 1:
        try:
            rows = _run_parallel(entries, jobs)
        except Exception:
            _logger.warning(
                "parallel scan unavailable, falling back to a serial one",
                exc_info=True,
            )
            rows = None
    if rows is None:
        jobs = 1
        rows = scan_many(entries)

    by_rule: dict[str, list[Finding]] = {}
    for rule, path, lineno, message in rows:
        by_rule.setdefault(rule, []).append(Finding(path, lineno, rule, message))

    _logger.info(
        "scanned %s Python files in %s process(es), %s finding(s) across %s rule(s)",
        len(entries),
        jobs,
        sum(map(len, by_rule.values())),
        len(by_rule),
    )
    return by_rule


def report(rule: str, header: str) -> str:
    found = sorted(findings().get(rule, []), key=lambda f: (f.path, f.lineno))
    if not found:
        return ""
    return f"{len(found)} {header}:\n  " + "\n  ".join(map(str, found))
