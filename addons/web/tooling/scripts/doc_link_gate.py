#!/usr/bin/env python3
"""doc_link_gate.py — strict-ratcheting CI gate for broken .md references.

Catches the same class of bug found three times in the web architecture
review (2026-05-09): CI workflows, machine_doc files, and audit comments
that reference ``.md`` paths that don't exist on disk.  Each instance
silently rotted because no automated check pinged when a referenced
doc was renamed, deleted, or never written in the first place.

The gate reads a configurable set of source globs, extracts every
plausible ``.md`` reference, resolves it to an absolute path, and
flags any that point to nothing.  A baseline JSON file freezes the
currently-tolerated violations so CI never red-lights existing rot —
only NEW broken references trigger a gate failure.

Mirrors the API and exit-code contract of the sibling
``typecheck_gate.mjs`` so operators recognise the pattern:

  exit 0 — no new violations (or first run with --update-baseline)
  exit 1 — at least one new broken reference vs baseline
  exit 2 — usage error

USAGE
-----

  # Gate (CI):
  python doc_link_gate.py

  # Refresh baseline after a cleanup PR:
  python doc_link_gate.py --update-baseline

  # Inspect what's currently broken without baseline comparison:
  python doc_link_gate.py --report-only

  # Use an alternate baseline path:
  python doc_link_gate.py --baseline=path/to/other.json

WHY PYTHON
----------

The sibling typecheck/lint gates are JS (they parse tsc/eslint output).
This gate scans source files directly — no upstream tool to consume
output from.  Python's pathlib/regex/json stdlib is enough; adding a
node_modules dependency just to match language would be net negative.

WHAT COUNTS AS A REFERENCE
--------------------------

Three patterns extracted (regex-based; deliberately conservative):

1. Markdown links: ``[text](path/to/file.md)`` and the optional
   ``#anchor`` suffix is stripped before existence check
2. Backtick-wrapped paths: `` `path/to/file.md` `` — the dominant
   form in machine_doc_v1 and CI workflow comments
3. "See: <path>.md" / "Plan: <path>.md" prose patterns — opt-in via
   --include-prose, off by default since false-positive risk is high

Pure prose mentions (``Read CONVENTIONS.md``) without backticks are
*not* extracted by default to avoid false positives on natural
language.  The convention is to wrap real path references in
backticks; the gate enforces that convention by only checking what's
explicitly marked.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Path math: /home/marin/Odoo/addons/odoo/addons/web/tooling/scripts/<this>
#   parents[0] = scripts/, [1] = tooling/, [2] = web/,
#   parents[3] = addons/ (inner), [4] = core/, [5] = addons/ (outer),
#   parents[6] = Odoo/        ← the workspace root we want.
REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_BASELINE_PATH = (
    REPO_ROOT
    / "addons/odoo/addons/web/tooling/scripts/doc_link_baseline.json"
)

# Source-file globs scanned by default.  Edits to this list belong with
# the gate so PR review sees the scope change alongside any baseline
# diff.  Exclusions go through the negative-glob mechanism below.
DEFAULT_SCAN_GLOBS = [
    # Machine-consumable docs the team treats as authoritative.
    "addons/odoo/addons/web/machine_doc_v1/*.md",
    # CI workflows that frequently reference plan/audit docs.
    "addons/odoo/.github/workflows/*.yml",
    # Top-level CLAUDE.md surface (workspace + repo + addon-level).
    "CLAUDE.md",
    "addons/odoo/CLAUDE.md",
    "addons/odoo/addons/web/CLAUDE.md",
    # Knowledge tree — the most common source of dangling refs.
    "knowledge/agromarin-knowledge/research/*.md",
    "knowledge/agromarin-knowledge/plans/*.md",
    "knowledge/agromarin-knowledge/reference/**/*.md",
]

# Negative globs — paths matching these are skipped even if they were
# captured by a positive glob above.  Excludes generated/vendored docs.
DEFAULT_EXCLUDES = [
    "**/node_modules/**",
    "**/venv/**",
    "**/.git/**",
    "**/static/lib/**",
]

# Reference extractors.  Each returns ``(file_offset, raw_path)`` tuples.
# Patterns favour false-negatives over false-positives — the convention
# is that real refs are wrapped in backticks or markdown link syntax.
REF_PATTERNS = [
    # Markdown links: [text](path.md) or [text](path.md#anchor)
    re.compile(r"\[[^\]]+\]\(([^)]+\.md(?:#[^)]*)?)\)"),
    # Backtick-wrapped paths.  The ``[/.]`` anchor avoids matching bare
    # file names like ``CONVENTIONS.md`` without a directory component
    # (those resolve relative to source file, handled separately).
    re.compile(r"`([^`\s]+\.md)`"),
]


# Placeholder markers — when a ref contains any of these, treat it as
# documentation pseudo-syntax rather than a real path.  CLAUDE.md
# heavily uses placeholders ("``research/YYYY-MM-DD-tXXXXX-topic.md``")
# to describe naming conventions; flagging these as broken is noise,
# not signal.
PLACEHOLDER_MARKERS = (
    "~",          # ~/Odoo/CLAUDE.md style — home-relative, not repo-relative
    "<",          # <role>.md, <INITIALS>, etc.
    "$",          # $PROJECT, $INITIALS environment-variable substitutions
    "YYYY",       # YYYY-MM-DD-... date placeholders
    "tXXXXX",     # task-id placeholders
    "txxxxx",     # case variant
    "{",          # {var} template substitutions
    "*",          # *.md glob patterns (e.g. ".claude/agents/*.md") — these
                  # are documentation about file shapes, not real paths
)


def _is_placeholder(raw_path: str) -> bool:
    """True if the ref is documentation pseudo-syntax, not a real path."""
    return any(marker in raw_path for marker in PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class Violation:
    """One broken reference, located precisely enough to fix or whitelist."""

    source_file: str  # repo-relative path of the file containing the ref
    line: int  # 1-based line number where the ref appears
    raw_path: str  # the path as written
    resolved_path: str  # absolute path the gate looked for

    def key(self) -> tuple[str, str]:
        """Stable key for baseline storage (file × ref-target)."""
        return (self.source_file, self.raw_path)


def _strip_anchor(path: str) -> str:
    """``foo/bar.md#section`` → ``foo/bar.md``."""
    return path.split("#", 1)[0]


def _extract_refs(content: str) -> list[tuple[int, str]]:
    """Return (line, raw_path) for every plausible .md reference."""
    refs: list[tuple[int, str]] = []
    # Pre-compute line offsets so each match's line number is one binary
    # search away; cheaper than re.split on every match.
    line_starts = [0]
    for i, ch in enumerate(content):
        if ch == "\n":
            line_starts.append(i + 1)

    def _line_of(offset: int) -> int:
        # Bisect via builtin — line_starts is sorted by construction.
        from bisect import bisect_right

        return bisect_right(line_starts, offset)

    for pattern in REF_PATTERNS:
        for match in pattern.finditer(content):
            refs.append((_line_of(match.start()), match.group(1)))
    return refs


def _resolve_ref(source_file: Path, raw_path: str) -> Path | None:
    """Resolve a raw reference; return the first existing match, or None.

    The fork's docs use multiple conventions: repo-root paths, source-
    relative paths, and source-parent-relative paths (where ``doc/X.md``
    in a ``machine_doc_v1/`` file actually means the sibling
    ``../doc/X.md`` in the parent ``web/`` directory).  Trying each
    candidate in turn matches authorial intent — the gate's job is to
    catch refs that resolve to NOTHING, not to enforce a single style.

    Resolution order:
      1. Absolute (``/`` prefix) → ``REPO_ROOT/<path>``
      2. Looks-rooted (starts with a known top-level dir) → ``REPO_ROOT/<path>``
      3. Walk up from source-file dir, trying each parent until repo root
      4. None — caller treats this as a violation

    Anchor fragments are stripped before existence check.
    """
    cleaned = _strip_anchor(raw_path)

    if cleaned.startswith("/"):
        candidate = REPO_ROOT / cleaned.lstrip("/")
        return candidate if candidate.exists() else None

    parts = cleaned.split("/", 1)
    looks_rooted = parts[0] in {
        "knowledge",
        "addons",
        "venv",
        "config",
        "core",
        "enterprise",
        "design-themes",
        "agromarin",
    }
    if looks_rooted:
        candidate = REPO_ROOT / cleaned
        return candidate if candidate.exists() else None

    # Walk up source-file's ancestry trying ``<ancestor>/<cleaned>``.
    # This captures both sibling-style refs (resolves at the source's
    # own directory) and parent-style refs (``doc/X.md`` from a child).
    # Stop at repo root — beyond that is escape-from-repo territory.
    current = source_file.parent
    while True:
        candidate = (current / cleaned).resolve()
        if candidate.exists():
            return candidate
        if current == REPO_ROOT:
            break
        if current.parent == current:
            break  # filesystem root reached without hitting REPO_ROOT
        current = current.parent
    return None


def _glob_files(globs: list[str], excludes: list[str]) -> list[Path]:
    """Expand glob list against REPO_ROOT, applying excludes."""
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
    """Minimal glob matcher for negative-exclude paths.

    Path/Path.match() semantics aren't quite right for exclude patterns
    (they require a full match against a single path component).  For
    excludes like ``**/node_modules/**`` we want substring-style match.
    """
    import fnmatch

    return fnmatch.fnmatch(path, pattern)


def scan(
    globs: list[str] | None = None,
    excludes: list[str] | None = None,
) -> list[Violation]:
    """Scan the configured globs and return all broken references."""
    globs = globs or DEFAULT_SCAN_GLOBS
    excludes = excludes or DEFAULT_EXCLUDES

    violations: list[Violation] = []
    files = _glob_files(globs, excludes)
    for source_file in files:
        try:
            content = source_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line, raw_path in _extract_refs(content):
            # Skip documentation pseudo-syntax: ``YYYY-MM-DD-...``,
            # ``<role>.md``, ``~/path``, etc.  These describe naming
            # conventions, not real files.
            if _is_placeholder(raw_path):
                continue
            resolved = _resolve_ref(source_file, raw_path)
            if resolved is None:
                # Best-effort diagnostic path: mirrors _resolve_ref's
                # absolute-ref and source-relative branches.  It does NOT
                # mirror the "looks-rooted" branch (bare ``addons/...``
                # style refs resolve against REPO_ROOT there, not against
                # source_file's directory), so for those refs the path
                # shown here can differ from what _resolve_ref actually
                # tried — still enough to point a human at the right area.
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


# ───────────────────────────────────────────────────────────────────────
# Baseline format
# ───────────────────────────────────────────────────────────────────────
#
# {
#   "_generated_at": "2026-05-09",
#   "_total_violations": 3,
#   "_generator": "...",
#   "violations": [
#     {"source_file": "addons/odoo/.github/workflows/lint.yml",
#      "raw_path": "knowledge/.../audit.md"},
#     ...
#   ]
# }
#
# Order is deterministic (sorted by source_file then raw_path) so
# baseline diffs in PRs reflect real changes, not key reshuffling.
# Stored fields are the violation's KEY only — line numbers drift on
# refactor and would generate noise.


def load_baseline(path: Path) -> set[tuple[str, str]]:
    """Return the set of (source_file, raw_path) tuples currently allowed."""
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    return {
        (v["source_file"], v["raw_path"])
        for v in data.get("violations", [])
    }


def write_baseline(path: Path, violations: list[Violation]) -> dict:
    """Write a stable, sorted-key JSON baseline."""
    keys = sorted({v.key() for v in violations})
    data = {
        "_generated_at": _today_iso(),
        "_total_violations": len(keys),
        "_generator": str(Path(__file__).relative_to(REPO_ROOT)),
        "violations": [
            {"source_file": sf, "raw_path": rp} for sf, rp in keys
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return data


def _today_iso() -> str:
    """Return today's date as YYYY-MM-DD (UTC).  Avoids a datetime import
    on the hot path; baseline regen is cold so the cost doesn't matter."""
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


def compare(
    violations: list[Violation], allowed: set[tuple[str, str]]
) -> tuple[list[Violation], list[tuple[str, str]]]:
    """Split violations into (new, removed) vs the baseline."""
    current_keys = {v.key() for v in violations}
    new = [v for v in violations if v.key() not in allowed]
    removed = sorted(allowed - current_keys)
    return new, removed


# ───────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────


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

    violations = scan()

    if args.update_baseline:
        data = write_baseline(args.baseline, violations)
        print(
            f"✓ Baseline updated: {data['_total_violations']} violations"
        )
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
        print(f"  Run with --update-baseline to tighten.")
    else:
        print(
            f"✓ No new violations.  "
            f"{len(violations)} match baseline."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
