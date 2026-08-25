"""How the Python scan runs: corpus, parallelism, caching.

What it looks for is `_rules`. This module owns nothing about any individual
rule; adding one is an entry in `_rules.CHECKERS` and nothing here.
"""

import ast
import functools
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import _checker_translated_unique, lint_case
from ._rules import (  # re-exported: the vocabulary of a scan
    ALIASES,
    CHECKERS,
    CROSS_UNIT_RULES,
    RULES,
    UNSUPPRESSABLE,
    Finding,
    Source,
    Unit,
    is_test_path,
    statement_spans,
    walk_with_parents,
)
from ._suppression import Suppressions, Untokenisable, comment_lines

_logger = logging.getLogger(__name__)

__all__ = [
    "ALIASES",
    "CHECKERS",
    "CROSS_UNIT_RULES",
    "RULES",
    "UNSUPPRESSABLE",
    "Finding",
    "Source",
    "Unit",
    "corpus",
    "findings",
    "is_test_path",
    "report",
    "scan_many",
    "scan_one",
    "statement_spans",
    "walk_with_parents",
]

#: Third-party code that happens to sit inside the tree. Linting it reports
#: findings nobody here may fix, and the fix upstream would be reverted by the
#: next vendoring.
_NOT_OURS = ("/_vendor/", "/upgrades/", "/migrations/")


@functools.cache
def corpus() -> tuple[Source, ...]:
    seen: set[str] = set()
    sources: list[Source] = []
    for path in lint_case.module_file_paths():
        if not path.endswith(".py") or not lint_case.is_core_path(path):
            continue
        if any(part in path for part in _NOT_OURS):
            continue
        if path not in seen:
            seen.add(path)
            sources.append(Source(path, in_module=True))
    for path in lint_case.framework_paths():
        if any(part in path for part in _NOT_OURS):
            continue
        if path not in seen:
            seen.add(path)
            sources.append(Source(path, in_module=False))
    return tuple(sorted(sources, key=lambda s: s.path))


def _source_line(lines: list[str], lineno: int, limit: int = 110) -> str:
    if not 1 <= lineno <= len(lines):
        return ""
    line = lines[lineno - 1].strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


#: (rule, path, lineno, col_offset, message)
type Row = tuple[str, str, int, int, str]


def scan_one(path: str, in_module: bool) -> tuple[list[Row], list]:
    """Every finding in one file, plus what the cross-unit rules need from it."""
    try:
        raw = Path(path).read_bytes()
        text = raw.decode("utf-8", errors="replace")
        tree = ast.parse(raw, path)
    except (OSError, SyntaxError, ValueError) as exc:
        return [("unreadable-source", path, 1, 0, f"{type(exc).__name__}: {exc}")], []

    try:
        comments = comment_lines(text)
    except Untokenisable as exc:
        return [("unreadable-source", path, 1, 0, str(exc))], []

    unit = Unit(
        path,
        text,
        tree,
        walk_with_parents(tree),
        in_module,
        is_test_path(path),
        comments,
    )
    suppressions = Suppressions(comments, ALIASES, UNSUPPRESSABLE)
    spans = statement_spans(unit.nodes)
    lines = text.split("\n")

    out: list[Row] = []
    for checker in CHECKERS:
        if not checker.applies_to(unit):
            continue
        try:
            violations = list(checker.run(unit))
        except RecursionError:
            out.append(
                (
                    "unreadable-source",
                    path,
                    1,
                    0,
                    f"RecursionError in a checker for {sorted(checker.rules)}",
                )
            )
            continue
        for violation in violations:
            name = checker.rule or violation.rule
            lineno = violation.lineno
            if suppressions.suppresses(lineno, name, spans.get(lineno)):
                continue
            message = (
                getattr(violation, "message", "")
                or getattr(violation, "raw", "")
                or _source_line(lines, lineno)
            )
            out.append(
                (
                    name,
                    path,
                    lineno,
                    getattr(violation, "col_offset", 0),
                    message.strip(),
                )
            )
    return out, _checker_translated_unique.collect(tree)


def scan_many(entries: list[tuple[str, bool]]) -> tuple[list[Row], list]:
    rows: list[Row] = []
    units: list = []
    for path, in_module in entries:
        file_rows, infos = scan_one(path, in_module)
        rows.extend(file_rows)
        if infos:
            units.append((path, infos))
    return rows, units


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
            rows: list[Row] = []
            units: list = []
            for part_rows, part_units in pool.map(scan_many, chunks):
                rows.extend(part_rows)
                units.extend(part_units)
            return rows, units
    finally:
        _stop_multiprocessing_helpers()


@functools.cache
def _scan() -> tuple[list[Row], list, int]:
    """One pass over the corpus. Everything downstream reads this, once."""
    entries = [(source.path, source.in_module) for source in corpus()]

    jobs = _job_count(len(entries))
    result = None
    if jobs > 1:
        try:
            result = _run_parallel(entries, jobs)
        except Exception:
            _logger.warning(
                "parallel scan unavailable, falling back to a serial one",
                exc_info=True,
            )
            result = None
    if result is None:
        jobs = 1
        result = scan_many(entries)
    rows, units = result
    return rows, units, jobs


@functools.cache
def findings() -> dict[str, list[Finding]]:
    rows, units, jobs = _scan()

    by_rule: dict[str, list[Finding]] = {}
    for rule, path, lineno, col, message in rows:
        by_rule.setdefault(rule, []).append(Finding(path, lineno, rule, message, col))

    # `unique-over-translated-column` cannot be decided from one file: a model's
    # translated fields may be declared in a class the constraint's file never
    # imports, so the answer needs every unit at once. The per-file half of the
    # work rode along with the parse above.
    for violation in _checker_translated_unique.violations(units):
        if is_test_path(violation.path):
            continue
        by_rule.setdefault(violation.rule, []).append(
            Finding(violation.path, violation.lineno, violation.rule, str(violation))
        )

    _logger.info(
        "scanned %s Python files in %s process(es), %s finding(s) across %s rule(s)",
        len(corpus()),
        jobs,
        sum(map(len, by_rule.values())),
        len(by_rule),
    )
    return by_rule


def translated_unique_scale() -> tuple[int, int]:
    """(model classes, uniqueness rules) the scan considered.

    The canary for `unique-over-translated-column`: the rule reports nothing on a
    clean tree, so without this a scan that reached no models at all would look
    exactly like a scan that found no defects.
    """
    _rows, units, _jobs = _scan()
    return (
        sum(len(infos) for _path, infos in units),
        sum(len(info.rules) for _path, infos in units for info in infos),
    )


def report(rule: str, header: str) -> str:
    found = sorted(findings().get(rule, []), key=lambda f: f.sort_key)
    if not found:
        return ""
    return f"{len(found)} {header}:\n  " + "\n  ".join(map(str, found))
