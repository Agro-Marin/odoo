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
``tooling/typecheck/scope_gate.py`` so operators recognise the pattern:

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
import datetime
import fnmatch
import json
import re
import sys
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# This repo, always. The gate used to climb to the workspace and scan sibling
# checkouts by name, which made a framework fork depend on the layout — and
# the existence — of repositories that have nothing to do with it. Anything
# outside this checkout is somebody else's gate to run.
REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="doc_link_gate")

DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parent / "baselines" / "doc_link_baseline.json"
)

# Every fork-authored documentation surface in this checkout.
#
# It used to be four globs covering 24 files: web's machine_doc, the workflows
# and two CLAUDE.md. The gate was green, but that was a statement about those
# four globs and not about the tree — seven `machine_doc_v1/` directories
# exist and it watched one, so four genuinely broken references (in mail's and
# website's machine_doc, in an ADR, and in this tooling's own README) sat
# unseen. Narrowing the gate to THIS REPO is what let it become blocking, and
# that stays; what widens here is coverage inside the repo, from 24 files to
# ~93, with the baseline still empty.
#
# `doc/cla/` is upstream Odoo's and carries upstream's own rot (`sign-cla.md`
# cites a corporate CLA that was never added); baselining another project's
# broken links teaches nobody anything. So `doc/` is enumerated a directory at
# a time rather than scanned as `doc/**`.
#
# It was enumerated as `doc/*.md` alone until 2026-08-07, which reads like a
# deliberate one-level narrowing and matched **zero files**: `doc/` holds
# `adr/`, `architecture/`, `cla/` and a single `.rst`, and no `.md` at its top
# level at all. The architecture set — the front door, the five views, and the
# gate/quality/risk/measurement pages — is held together by ~30 relative links,
# and every one of them was checked by nothing. Widening surfaced 15 broken
# references on the first run, all of the same shape: a backticked bare
# filename that resolves from the directory the citing page used to live in.
# The core package READMEs are in scope for the same reason — the architecture
# pages cite `odoo/db/README.md` and `odoo/http/README.md`, and both cite back.
#
# There is deliberately no `odoo/*.md` entry: it existed only for the front
# door, and once that moved to `doc/architecture/` the glob matched nothing.
# A glob kept past the file it was written for is how `doc/*.md` became a
# no-op that read like coverage.
DEFAULT_SCAN_GLOBS = [
    "addons/*/machine_doc_v1/*.md",
    "odoo/**/machine_doc_v1/*.md",
    ".github/workflows/*.yml",
    "CLAUDE.md",
    "addons/*/CLAUDE.md",
    "doc/*.md",
    "doc/adr/*.md",
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
]

# --- ADR citations -----------------------------------------------------------
#
# The patterns above only understand a `.md` PATH, which is not how this repo
# cites its architecture decisions. ``ARCHITECTURE.md`` names the *directory*
# ``doc/adr/`` (no `.md` suffix) and everything else writes the bare
# ``ADR-NNNN`` form — a citation, not a path. (Spelled with letters here on
# purpose: a real number in this file would be a live citation by this gate's
# own grammar, so illustrating the rule would create work for it.)
#
# So the most-cited doc artifact in the tree sat entirely outside this gate's
# grammar, and when ``doc/adr/`` was deleted it reported clean while 39
# citations dangled. (One test,
# ``test_architecture_doc.py::test_adrs_exist``, did catch it — but only for
# the front door; the other 25 citations, including the 12 in
# ``layer_check.py`` that justify each enforced contract, were checked by
# nothing.)
#
# Scanned SEPARATELY from the `.md` refs, with a wider file set, and
# deliberately so: broadening DEFAULT_SCAN_GLOBS to `.py`/`.rst` would also
# subject those files to the `.md` patterns above, which surfaces 28 unrelated
# broken references — real rot worth fixing, but a different job, and one that
# would either turn this gate red or need a 28-entry baseline it has never had.
RE_ADR = re.compile(r"\bADR[-‑](\d{4})\b")

#: Where ADR citations actually live: the docs, the gates that cite them as
#: rationale, and the coding guidelines.
ADR_SCAN_GLOBS = [
    "doc/**/*.md",
    "doc/*.rst",
    "odoo/**/*.py",
    "tooling/**/*.py",
    "tooling/**/*.md",
    ".github/workflows/*.yml",
]

ADR_DIR = REPO_ROOT / "doc" / "adr"


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
    """Top-level directory names of this checkout.

    Derived, not listed. The hardcoded list this replaces named sibling
    checkouts that do not exist in this repo at all, so it encoded one
    particular workspace layout into a gate that only ever reads its own tree.
    """
    try:
        return frozenset(
            p.name
            for p in REPO_ROOT.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
    except OSError:  # pragma: no cover
        return frozenset()


def _is_placeholder(raw_path: str) -> bool:
    """True if the ref is documentation pseudo-syntax, not a real path."""
    return any(marker in raw_path for marker in PLACEHOLDER_MARKERS)


# There used to be an ``_is_unverifiable`` hook here: an allowlist of
# sibling-checkout names whose refs were skipped as "may exist in the
# workspace". That is what let a doc here cite an external tree indefinitely —
# unverifiable by construction, so never reported, so never removed. A
# framework fork that stands alone can only point at itself, and a reference it
# cannot resolve is a reference to fix, so the hook was emptied to `return
# False` and is now gone entirely rather than left as a no-op in the scan loop.


@dataclass(frozen=True)
class Violation:
    """One broken reference, located precisely enough to fix or whitelist."""

    source_file: str
    line: int
    raw_path: str
    resolved_path: str

    def key(self) -> tuple[str, str]:
        """Stable key for baseline storage (file × ref-target)."""
        return (self.source_file, self.raw_path)


def _strip_anchor(path: str) -> str:
    """``foo/bar.md#section`` → ``foo/bar.md``."""
    return path.split("#", 1)[0]


def _inside_repo(candidate: Path) -> bool:
    """Whether a resolved candidate is part of THIS checkout.

    The gate's stated scope is this repo and nothing else (see ``REPO_ROOT``),
    and the ``_is_unverifiable`` hook that used to wave sibling checkouts
    through was deleted for that reason. But the resolution walk below could
    still reach them: it calls ``.resolve()``, so a ``../../`` ref climbs out of
    the checkout, and at the top of the walk ``REPO_ROOT / "../../x.md"``
    resolves into the workspace. Measured: ``../../agromarin/CLAUDE.md`` cited
    from ``doc/adr/`` reported "No broken .md references found" because a
    DIFFERENT git repository happened to be checked out next door.

    That is worse than tolerating the reference, because the verdict then
    depends on what is outside the tree: green on a workstation with sibling
    checkouts, red in CI where the repo stands alone. A gate whose answer
    changes with the machine teaches people to ignore it.
    """
    return candidate == REPO_ROOT or REPO_ROOT in candidate.parents


def _extract_refs(content: str) -> list[tuple[int, str]]:
    """Return (line, raw_path) for every plausible .md reference."""
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
    """Resolve a raw reference; return the first existing match, or None.

    The fork's docs use multiple conventions: repo-root paths, source-
    relative paths, and source-parent-relative paths (where ``doc/X.md``
    in a ``machine_doc_v1/`` file actually means the sibling
    ``../doc/X.md`` in the parent ``web/`` directory).  Trying each
    candidate in turn matches authorial intent — the gate's job is to
    catch refs that resolve to NOTHING, not to enforce a single style.

    Resolution order — each step FALLS THROUGH to the next on failure:
      1. Absolute (``/`` prefix) → ``REPO_ROOT/<path>``
      2. Looks-rooted (starts with a known top-level dir) → ``REPO_ROOT/<path>``
      3. Walk up from source-file dir, trying each parent until repo root
      4. None — caller treats this as a violation

    Step 2 used to ``return None`` rather than fall through, which made the
    order a first-match-wins dispatch and produced false positives: a path
    beginning with a rooted-looking segment that is in fact source-relative was
    reported broken even though it resolved. ``addons/odoo/CLAUDE.md`` citing
    ``addons/web/machine_doc_v1/TEST_TAGS.md`` is exactly that shape — the file
    exists, and the gate even PRINTED the path that exists while calling it
    missing, because the message is built by the source-relative rule the check
    never reached. A false positive is the worst failure for a gate: it teaches
    people to ignore it.

    Anchor fragments are stripped before existence check.
    """
    cleaned = _strip_anchor(raw_path)

    def _accept(candidate: Path) -> Path | None:
        # ``.resolve()`` before the containment test, not after: an unresolved
        # path still carries its ``..`` segments, so ``REPO_ROOT/"../x.md"``
        # would pass a naive ``is_relative_to`` check and then ``exists()``
        # outside the tree anyway.
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

    ``Path.match()`` semantics aren't right for exclude patterns (they require
    a full match against a single path component), and neither is bare
    ``fnmatch``: under it ``**/node_modules/**`` needs a literal ``/`` before
    the name, so it excluded ``a/node_modules/x.md`` and NOT the top-level
    ``node_modules/x.md``. Every exclude here names a directory that is
    usually at the root, so all four were inert against the very trees they
    name — invisible while the scan globs stayed narrow, and a flood of 107
    third-party violations the moment they widen.

    A ``**/<name>/**`` pattern is therefore matched against path *segments*;
    anything else falls back to ``fnmatch``.
    """
    if pattern.startswith("**/") and pattern.endswith("/**"):
        return pattern[3:-3] in PurePosixPath(path).parts
    return fnmatch.fnmatch(path, pattern)


def adr_exists(number: str) -> bool:
    """Whether ``doc/adr/`` holds an accepted ADR with this number.

    Globbed rather than joined: the filename carries a slug
    (``0001-layered-orm.md``) that no citation repeats, and requiring citations
    to spell it would make every ADR rename a tree-wide edit.
    """
    return bool(list(ADR_DIR.glob(f"{number}-*.md")))


def scan_adr_citations(
    globs: list[str] | None = None,
    excludes: list[str] | None = None,
) -> list[Violation]:
    """Every ``ADR-NNNN`` citation that resolves to no ADR."""
    files = _glob_files(globs or ADR_SCAN_GLOBS, excludes or DEFAULT_EXCLUDES)
    violations: list[Violation] = []
    for source_file in files:
        try:
            content = source_file.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        if "ADR" not in content:  # cheap reject; most files never cite one
            continue
        line_starts = [0]
        for i, ch in enumerate(content):
            if ch == "\n":
                line_starts.append(i + 1)
        for match in RE_ADR.finditer(content):
            number = match.group(1)
            if adr_exists(number):
                continue
            violations.append(
                Violation(
                    source_file=str(source_file.relative_to(REPO_ROOT)),
                    line=bisect_right(line_starts, match.start()),
                    raw_path=f"ADR-{number}",
                    resolved_path=str(ADR_DIR / f"{number}-*.md"),
                )
            )
    return violations


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
        except OSError, UnicodeDecodeError:
            continue
        for line, raw_path in _extract_refs(content):
            if _is_placeholder(raw_path):
                continue
            resolved = _resolve_ref(source_file, raw_path)
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
    """Return the set of (source_file, raw_path) tuples currently allowed."""
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {(v["source_file"], v["raw_path"]) for v in data.get("violations", [])}


def write_baseline(path: Path, violations: list[Violation]) -> dict:
    """Write a stable, sorted-key JSON baseline."""
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
    """Return today's date as YYYY-MM-DD (UTC)."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


def compare(
    violations: list[Violation], allowed: set[tuple[str, str]]
) -> tuple[list[Violation], list[tuple[str, str]]]:
    """Split violations into (new, removed) vs the baseline."""
    current_keys = {v.key() for v in violations}
    new = [v for v in violations if v.key() not in allowed]
    removed = sorted(allowed - current_keys)
    return new, removed


# CLI


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

    # Both classes of dangling reference, in one baseline: a citation that
    # resolves to nothing is the same defect whether it was spelled as a path
    # or as an ADR number.
    violations = scan() + scan_adr_citations()

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
