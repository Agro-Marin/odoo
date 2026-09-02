#!/usr/bin/env python3


from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import re
import sys
from bisect import bisect_right
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "architecture"))
import _ast_cache

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="doc_link_gate")

DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parent / "baselines" / "doc_link_baseline.json"
)

DEFAULT_SCAN_GLOBS = [
    "addons/*/machine_doc_v1/*.md",
    "odoo/**/machine_doc_v1/*.md",
    ".github/workflows/*.yml",
    "CLAUDE.md",
    "addons/*/CLAUDE.md",
    "doc/*.md",
    "doc/architecture/**/*.md",
    "odoo/**/README.md",
    "tooling/**/*.md",
]

DEFAULT_EXCLUDES = [
    "**/node_modules/**",
    "**/venv/**",
    "**/.git/**",
    "**/static/lib/**",
]

REF_PATTERNS = [
    re.compile(r"\[[^\]]+\]\(([^)]+\.md(?:#[^)]*)?)\)"),
    re.compile(r"`([^`\s]+\.md)`"),
    re.compile(r"\[[^\]]+\]\((#[\w-]+)\)"),
]

PLACEHOLDER_MARKERS = (
    "~",
    "<",
    "$",
    "YYYY",
    "tXXXXX",
    "txxxxx",
    "{",
    "*",
)


@lru_cache(maxsize=1)
def _repo_top_level_dirs() -> frozenset[str]:

    try:
        return frozenset(
            p.name
            for p in REPO_ROOT.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
    except OSError:  # pragma: no cover
        return frozenset()


def _is_placeholder(raw_path: str) -> bool:
    return any(marker in raw_path for marker in PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class Violation:
    source_file: str
    line: int
    raw_path: str
    resolved_path: str

    def key(self) -> tuple[str, str]:
        return (self.source_file, self.raw_path)


def _strip_anchor(path: str) -> str:
    return path.split("#", 1)[0]


def _anchor_of(path: str) -> str:
    return path.split("#", 1)[1] if "#" in path else ""


_HEADING = re.compile(r"^#{1,6}[ \t]+(.*)$", re.MULTILINE)
_ATTR_ANCHOR = re.compile(r"\{#([\w-]+)\}\s*$")
_FENCE = re.compile(r"^(?:```|~~~)", re.MULTILINE)


def _slug(heading: str) -> str:
    text = re.sub(r"`|\*\*|\*|~~", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


@cache
def heading_slugs(path: Path) -> frozenset[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return frozenset()
    outside, fenced = [], False
    for line in content.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            outside.append(line)
    slugs: set[str] = set()
    for heading in _HEADING.findall("\n".join(outside)):
        attribute = _ATTR_ANCHOR.search(heading.strip())
        if attribute:
            slugs.add(attribute.group(1))
            heading = _ATTR_ANCHOR.sub("", heading).strip()
        slugs.add(_slug(heading))
    return frozenset(slugs)


def _inside_repo(candidate: Path) -> bool:

    return candidate == REPO_ROOT or REPO_ROOT in candidate.parents


def _extract_refs(content: str) -> list[tuple[int, str]]:
    refs: list[tuple[int, str]] = []
    line_starts = [0]
    for i, ch in enumerate(content):
        if ch == "\n":
            line_starts.append(i + 1)

    def _line_of(offset: int) -> int:
        return bisect_right(line_starts, offset)

    for pattern in REF_PATTERNS:
        refs.extend(
            (_line_of(match.start()), match.group(1))
            for match in pattern.finditer(content)
        )
    return refs


def _resolve_ref(source_file: Path, raw_path: str) -> Path | None:

    cleaned = _strip_anchor(raw_path)

    def _accept(candidate: Path) -> Path | None:
        resolved = candidate.resolve()
        return resolved if _inside_repo(resolved) and resolved.exists() else None

    if cleaned.startswith("/"):
        return _accept(REPO_ROOT / cleaned.lstrip("/"))

    if cleaned.split("/", 1)[0] in _repo_top_level_dirs():
        if found := _accept(REPO_ROOT / cleaned):
            return found

    current = source_file.parent
    while True:
        if found := _accept(current / cleaned):
            return found
        if current == REPO_ROOT:
            break
        if current.parent == current:
            break
        current = current.parent
    return None


def _glob_files(globs: list[str], excludes: list[str]) -> list[Path]:
    matched: set[Path] = set()
    for glob in globs:
        for path in REPO_ROOT.glob(glob):
            if path.is_file():
                matched.add(path)

    if not excludes:
        return sorted(matched)

    filtered: list[Path] = []
    for path in matched:
        rel = str(path.relative_to(REPO_ROOT))
        if any(_glob_match(rel, pat) for pat in excludes):
            continue
        filtered.append(path)
    return sorted(filtered)


def _glob_match(path: str, pattern: str) -> bool:

    if pattern.startswith("**/") and pattern.endswith("/**"):
        return pattern[3:-3] in PurePosixPath(path).parts
    return fnmatch.fnmatch(path, pattern)


def scan(
    globs: list[str] | None = None,
    excludes: list[str] | None = None,
) -> list[Violation]:
    globs = globs or DEFAULT_SCAN_GLOBS
    excludes = excludes or DEFAULT_EXCLUDES

    violations: list[Violation] = []
    files = _glob_files(globs, excludes)
    for source_file in files:
        content = _ast_cache.read_source(source_file)
        for line, raw_path in _extract_refs(content):
            if _is_placeholder(raw_path):
                continue
            anchor = _anchor_of(raw_path)
            resolved = (
                source_file
                if raw_path.startswith("#")
                else _resolve_ref(source_file, raw_path)
            )
            if (
                resolved is not None
                and anchor
                and resolved.suffix == ".md"
                and anchor not in heading_slugs(resolved)
            ):
                violations.append(
                    Violation(
                        source_file=str(source_file.relative_to(REPO_ROOT)),
                        line=line,
                        raw_path=raw_path,
                        resolved_path=f"{resolved}#{anchor} (no such heading)",
                    )
                )
                continue
            if resolved is None:
                cleaned = _strip_anchor(raw_path)
                attempted = (
                    str(REPO_ROOT / cleaned.lstrip("/"))
                    if cleaned.startswith("/")
                    else str((source_file.parent / cleaned).resolve())
                )
                violations.append(
                    Violation(
                        source_file=str(source_file.relative_to(REPO_ROOT)),
                        line=line,
                        raw_path=raw_path,
                        resolved_path=attempted,
                    )
                )
    return violations


def load_baseline(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {(v["source_file"], v["raw_path"]) for v in data.get("violations", [])}


def write_baseline(path: Path, violations: list[Violation]) -> dict:
    keys = sorted({v.key() for v in violations})
    data = {
        "_generated_at": _today_iso(),
        "_total_violations": len(keys),
        "_generator": str(Path(__file__).relative_to(REPO_ROOT)),
        "violations": [{"source_file": sf, "raw_path": rp} for sf, rp in keys],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def _today_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


def compare(
    violations: list[Violation], allowed: set[tuple[str, str]]
) -> tuple[list[Violation], list[tuple[str, str]]]:
    current_keys = {v.key() for v in violations}
    new = [v for v in violations if v.key() not in allowed]
    removed = sorted(allowed - current_keys)
    return new, removed


VIOLATION_PRINT_LIMIT = 50


def _print_violations(violations: list[Violation], header: str) -> None:
    print(header)
    for v in violations[:VIOLATION_PRINT_LIMIT]:
        print(
            f"  {v.source_file}:{v.line}: "
            f"references missing `{v.raw_path}` → {v.resolved_path}"
        )
    if len(violations) > VIOLATION_PRINT_LIMIT:
        print(f"  ...and {len(violations) - VIOLATION_PRINT_LIMIT} more")


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict-ratcheting CI gate for broken .md references."
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help=f"Baseline JSON path (default: {DEFAULT_BASELINE_PATH}).",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Regenerate baseline from current state.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print all violations; do not compare against baseline.",
    )
    args = parser.parse_args()

    scanned = _glob_files(DEFAULT_SCAN_GLOBS, DEFAULT_EXCLUDES)
    if not scanned:
        print(
            f"doc_link_gate: matched {len(scanned)} document(s) "
            f"— refusing to report a pass. "
            f"A scan that reaches nothing produces no violations, and this "
            f"gate's baseline is a hard zero, so silence is indistinguishable "
            f"from success. Check the globs against the tree they name.",
            file=sys.stderr,
        )
        return 2

    violations = scan()

    if args.update_baseline:
        data = write_baseline(args.baseline, violations)
        print(f"✓ Baseline updated: {data['_total_violations']} violations")
        print(f"  Written to {args.baseline.relative_to(REPO_ROOT)}")
        return 0

    if args.report_only:
        if violations:
            _print_violations(
                violations,
                f"⚠ {len(violations)} broken .md reference(s) found:",
            )
        else:
            print("✓ No broken .md references found.")
        return 0

    allowed = load_baseline(args.baseline)
    new, removed = compare(violations, allowed)

    if new:
        _print_violations(
            new,
            f"✗ {len(new)} new broken .md reference(s) vs baseline:",
        )
        print(
            f"\n  baseline: {len(allowed)} tolerated violations"
            f"\n  current:  {len(violations)} total"
        )
        return 1

    if removed:
        print(
            f"✓ No new violations.  {len(removed)} reference(s) "
            f"resolved since baseline:"
        )
        for sf, rp in removed[:10]:
            print(f"  {sf}: `{rp}`")
        if len(removed) > 10:
            print(f"  ...and {len(removed) - 10} more")
        print("  Run with --update-baseline to tighten.")
    else:
        print(f"✓ No new violations.  {len(violations)} match baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
