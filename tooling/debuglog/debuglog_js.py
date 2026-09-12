#!/usr/bin/env python3
"""Inventory, validate and strip the `@web/core/debug/debug_logger` call sites.

The JS twin of `debuglog.py`. The client-side debug loggers are the same
medium-term instrument: removal is mechanical only while every site keeps one
of a fixed set of shapes, and this tool answers the same three questions:

    --list    how many sites, per addon and per channel
    --check   does every site have a strippable shape (exit 1 otherwise)
    --strip   remove every site and print the files it rewrote

The strippable shapes, and only these:

    import { makeLogger } from "@web/core/debug/debug_logger";
    import { useLifecycleLog } from "@web/core/debug/logger_hooks";
                                                   one specifier per import
    const log = makeLogger("<ns>");                module level; `log` or
                                                   `debugLog`, or `const log =
                                                   debugLog.log;` behind a
                                                   `makeGeoLogger` facade
    useLifecycleLog(log);                          an expression statement
    log.logic(...); log.pipeline(...); log.lifecycle(...);
                                                   an expression statement,
                                                   possibly multi-line
    const endX = log.perf(...);                    a declaration whose name
                                                   starts with `end`
    endX(...);                                     an expression statement

`log.measure(...)` and `log.perf(...)` used as an expression are refused: the
first wraps real work and the second returns a function somebody else calls,
so neither can be deleted as a statement. A site that is the only statement of
its block is refused too, because stripping it would leave the block empty.
Files under `static/tests/` and the helper's own directory are not scanned.
Run prettier over the rewritten files after `--strip`; the tool does not.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

REPO = find_odoo_root(Path(__file__).resolve(), tool="debuglog_js")
DEFAULT_ROOTS = ("addons",)
CHANNELS = ("logic", "perf", "pipeline", "lifecycle")
LINE_CHANNELS = ("logic", "pipeline", "lifecycle")
LOGGER_NAMES = ("log", "debugLog")
HELPER_DIR = "addons/web/static/src/core/debug"
SKIPPED = (
    "/static/tests/",
    "/static/lib/",
    "/node_modules/",
    "/tooling/",
    "/geo_debug.js",
)
IMPORT_RE = re.compile(
    r"^import \{\s*(makeLogger|useLifecycleLog)\s*\} from "
    r'"(?:@web/core/debug/|\./debug/|\.\./debug/|\./)(debug_logger|logger_hooks)(?:\.js)?";$'
)
DECL_RE = re.compile(
    r'^const (log|debugLog) = (?:makeLogger\("[^"]+"\)|debugLog\.log);$'
)
HOOK_RE = re.compile(r"^(\s*)useLifecycleLog\((log|debugLog)\);$")
CALL_RE = re.compile(r"^(\s*)(log|debugLog)\.(logic|pipeline|lifecycle)\(")
PERF_RE = re.compile(r"^(\s*)const (end[A-Z]\w*) = (log|debugLog)\.perf\(")
END_RE = re.compile(r"^(\s*)(end[A-Z]\w*)\(")
ANY_USE_RE = re.compile(
    r"\b(?:makeLogger|useLifecycleLog|(?:log|debugLog)\.(?:logic|pipeline|lifecycle|perf|measure|child|isEnabled|enabled|ns))\b"
)
BLOCK_OPEN_RE = re.compile(r"(\{|=>)\s*$")


@dataclass
class Site:
    path: Path
    line: int
    end: int
    kind: str
    channel: str | None = None


@dataclass
class Violation:
    path: Path
    line: int
    message: str


@dataclass
class FileReport:
    path: Path
    sites: list[Site] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)


def iter_files(roots: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        base = Path(root) if Path(root).is_absolute() else REPO / root
        for path in sorted(base.rglob("*.js")):
            rel = path.as_posix()
            if any(part in rel for part in SKIPPED):
                continue
            if HELPER_DIR in rel:
                continue
            if "/static/src/" not in rel:
                continue
            files.append(path)
    return files


def _statement_end(lines: list[str], start: int) -> int:
    depth = 0
    in_template = False
    for index in range(start, len(lines)):
        text = lines[index]
        for char in text:
            if char == "`":
                in_template = not in_template
            if in_template:
                continue
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
        if depth <= 0 and text.rstrip().endswith(";"):
            return index
    return -1


def _only_statement_of_block(lines: list[str], start: int, end: int) -> bool:
    before = start - 1
    while before >= 0 and not lines[before].strip():
        before -= 1
    after = end + 1
    while after < len(lines) and not lines[after].strip():
        after += 1
    opens = before >= 0 and BLOCK_OPEN_RE.search(lines[before]) is not None
    closes = after < len(lines) and lines[after].strip().startswith("}")
    return opens and closes


def scan_file(path: Path) -> FileReport:
    report = FileReport(path)
    lines = path.read_text(encoding="utf-8").split("\n")
    consumed: set[int] = set()
    perf_names: set[str] = set()
    index = 0
    while index < len(lines):
        text = lines[index]
        if IMPORT_RE.match(text):
            report.sites.append(Site(path, index + 1, index + 1, "import"))
            consumed.add(index)
            index += 1
            continue
        if DECL_RE.match(text):
            report.sites.append(Site(path, index + 1, index + 1, "declaration"))
            consumed.add(index)
            index += 1
            continue
        if HOOK_RE.match(text):
            report.sites.append(Site(path, index + 1, index + 1, "hook", "lifecycle"))
            consumed.add(index)
            index += 1
            continue
        call = CALL_RE.match(text)
        perf = PERF_RE.match(text)
        end_call = END_RE.match(text)
        if call or perf or (end_call and end_call.group(2) in perf_names):
            end = _statement_end(lines, index)
            if end < 0:
                report.violations.append(
                    Violation(path, index + 1, "statement does not end with ';'")
                )
                index += 1
                continue
            if _only_statement_of_block(lines, index, end):
                report.violations.append(
                    Violation(
                        path, index + 1, "log call is the only statement of its block"
                    )
                )
            if call:
                kind, channel = "call", call.group(3)
            elif perf:
                kind, channel = "perf", "perf"
                perf_names.add(perf.group(2))
            else:
                kind, channel = "perf-end", "perf"
            report.sites.append(Site(path, index + 1, end + 1, kind, channel))
            consumed.update(range(index, end + 1))
            index = end + 1
            continue
        index += 1
    if not any(site.kind == "declaration" for site in report.sites):
        return report
    end_use = (
        re.compile(r"\b(" + "|".join(sorted(perf_names)) + r")\b")
        if perf_names
        else None
    )
    for number, text in enumerate(lines):
        if number in consumed or text.lstrip().startswith(("//", "*", "/*")):
            continue
        if ANY_USE_RE.search(text) or (end_use and end_use.search(text)):
            report.violations.append(
                Violation(path, number + 1, f"unstrippable use: {text.strip()[:80]}")
            )
    return report


def strip_file(path: Path, report: FileReport) -> bool:
    lines = path.read_text(encoding="utf-8").split("\n")
    drop: set[int] = set()
    for site in report.sites:
        drop.update(range(site.line - 1, site.end))
    if not drop:
        return False
    kept: list[str] = []
    for number, text in enumerate(lines):
        if number in drop:
            continue
        if (
            not text.strip()
            and number - 1 in drop
            and (not kept or not kept[-1].strip())
        ):
            continue
        kept.append(text)
    collapsed: list[str] = []
    for text in kept:
        if not text.strip() and collapsed and not collapsed[-1].strip():
            continue
        collapsed.append(text)
    path.write_text("\n".join(collapsed), encoding="utf-8")
    return True


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def addon_of(path: Path) -> str:
    parts = path.parts
    try:
        return parts[parts.index("static") - 1]
    except ValueError, IndexError:
        return path.parent.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--strip", action="store_true")
    parser.add_argument("--roots", nargs="+", default=list(DEFAULT_ROOTS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    reports = [scan_file(path) for path in iter_files(tuple(args.roots))]
    reports = [report for report in reports if report.sites or report.violations]

    if args.list:
        per_addon: Counter[str] = Counter()
        per_channel: Counter[str] = Counter()
        for report in reports:
            for site in report.sites:
                if site.kind in ("import", "declaration"):
                    continue
                per_addon[addon_of(report.path)] += 1
                if site.channel:
                    per_channel[site.channel] += 1
        total = sum(per_addon.values())
        for addon, count in sorted(per_addon.items(), key=lambda item: -item[1]):
            print(f"{count:6d}  {addon}")
        print(f"{total:6d}  total sites in {len(reports)} file(s)")
        for channel in CHANNELS:
            print(f"        {channel:10s} {per_channel[channel]}")
        return 0

    violations = [violation for report in reports for violation in report.violations]
    if args.check:
        for violation in violations:
            print(f"{_rel(violation.path)}:{violation.line}: {violation.message}")
        print(f"{len(violations)} violation(s) in {len(reports)} file(s)")
        return 1 if violations else 0

    if violations:
        for violation in violations:
            print(f"{_rel(violation.path)}:{violation.line}: {violation.message}")
        print("refusing to strip while sites have unstrippable shapes")
        return 1
    rewritten = 0
    for report in reports:
        if args.dry_run:
            print(f"would rewrite {_rel(report.path)} ({len(report.sites)} site(s))")
            rewritten += 1
        elif strip_file(report.path, report):
            print(f"rewrote {_rel(report.path)}")
            rewritten += 1
    print(f"{rewritten} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
