#!/usr/bin/env python3
"""FA4 → FA7 codemod: migrates FontAwesome 4 class syntax to FA7 native syntax.

Transforms:
  fa fa-icon-name        →  fa-solid  fa-icon-name  (solid, unchanged name)
  fa fa-icon-name-o      →  fa-regular fa-icon-name  (outline → regular, strip -o)
  fa fa-brand-icon       →  fa-brands  fa-brand-icon  (brands, per shims.yml)
  fa-fw (on any element) →  removed (deprecated in FA7, icons fill canvas by default)

Dynamic patterns (f-strings, .format(), % with variables, t-att-class) are flagged
with a # TODO comment for manual review rather than silently transformed.

Usage:
    python fa4_to_fa7.py [--dry-run] [--check] <path>...

    <path>  Files or directories to process (directories are recursed).

    --dry-run  Print unified diff without writing files.
    --check    Exit code 1 if any files would be changed (CI gate).

File types processed: .xml .html .js .ts .py .scss .css .jinja2 .jinja
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHIMS_PATH = (
    Path(__file__).parent.parent
    / "addons/web/static/src/libs/fontawesome7/metadata/shims.yml"
)

# Map FA short prefix → FA7 style class
_PREFIX_TO_STYLE: dict[str, str] = {
    "fas": "fa-solid",
    "far": "fa-regular",
    "fab": "fa-brands",
    "fal": "fa-light",
    "fat": "fa-thin",
    "fad": "fa-duotone",
    "fas": "fa-solid",
}

# FA4 modifier classes that are NOT icon names — keep as-is, do not map through shims
_FA_MODIFIERS: frozenset[str] = frozenset({
    "fa-spin",
    "fa-pulse",
    "fa-fw",       # deprecated in FA7 — will be dropped
    "fa-border",
    "fa-pull-left",
    "fa-pull-right",
    "fa-lg",
    "fa-2x",
    "fa-3x",
    "fa-4x",
    "fa-5x",
    "fa-6x",
    "fa-7x",
    "fa-8x",
    "fa-9x",
    "fa-10x",
    "fa-xs",
    "fa-sm",
    "fa-1x",
    "fa-stack",
    "fa-stack-1x",
    "fa-stack-2x",
    "fa-inverse",
    "fa-rotate-90",
    "fa-rotate-180",
    "fa-rotate-270",
    "fa-flip-horizontal",
    "fa-flip-vertical",
    "fa-flip-both",
    "fa-beat",
    "fa-fade",
    "fa-beat-fade",
    "fa-bounce",
    "fa-shake",
    "fa-li",
    "fa-ul",
    "fa-ol",
    # FA7 animation variants (keep if already present)
    "fa-flip",
    "fa-rotate",
})

# File extensions to process
_EXTENSIONS: frozenset[str] = frozenset({
    ".xml", ".html", ".js", ".ts", ".py",
    ".scss", ".css", ".jinja2", ".jinja",
})

# Directories to skip entirely
_SKIP_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".git", "node_modules", "_vendor",
    "fontawesome",   # old FA4 dir — not source code
    "fontawesome7",  # new FA7 dir — CSS files, not source code
    ".mypy_cache", ".ruff_cache",
})

# ---------------------------------------------------------------------------
# YAML shims parser (no external dependency)
# ---------------------------------------------------------------------------

def _load_shims(path: Path) -> dict[str, dict[str, str]]:
    """Parse shims.yml into {fa4_icon_name: {'prefix': str, 'name': str}}.

    The file format is simple YAML with top-level keys (FA4 icon names) and
    optional ``prefix`` and ``name`` sub-keys:

        area-chart:
          name: chart-area
        arrow-circle-o-down:
          prefix: far
          name: circle-down
        clone:
          prefix: far
    """
    shims: dict[str, dict[str, str]] = {}
    current_key: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(" "):
            # Top-level key (FA4 icon name)
            current_key = line.rstrip(":").strip()
            shims[current_key] = {}
        elif current_key and ":" in line:
            sub_key, _, sub_val = line.strip().partition(":")
            shims[current_key][sub_key.strip()] = sub_val.strip()

    return shims


# ---------------------------------------------------------------------------
# Mapping logic
# ---------------------------------------------------------------------------

def _get_fa7(fa4_name: str, shims: dict[str, dict[str, str]]) -> tuple[str, str]:
    """Return ``(fa7_style_class, fa7_icon_name)`` for an FA4 icon name.

    Icon names are WITHOUT the ``fa-`` prefix (e.g. ``clock-o``, ``trash``).
    """
    if fa4_name in shims:
        entry = shims[fa4_name]
        prefix = entry.get("prefix", "fas")
        name = entry.get("name") or fa4_name
    elif fa4_name.endswith("-o"):
        # FA4 outline convention: strip -o suffix → regular style
        prefix = "far"
        name = fa4_name[:-2]
    else:
        # Unknown icon, assume solid with same name
        prefix = "fas"
        name = fa4_name

    return _PREFIX_TO_STYLE.get(prefix, "fa-solid"), name


# ---------------------------------------------------------------------------
# Class-string transformer
# ---------------------------------------------------------------------------

class _TransformResult(NamedTuple):
    new_string: str
    changed: bool
    icon_renamed: bool      # True when icon name itself changed (for reporting)
    style_changed: bool     # True when style class changed


def _transform_class_string(
    class_str: str,
    shims: dict[str, dict[str, str]],
) -> _TransformResult:
    """Transform a single class-attribute value from FA4 to FA7 syntax.

    Input:  ``'fa fa-clock-o fa-spin'``
    Output: ``'fa-regular fa-clock fa-spin'``

    The input is the raw string value (without surrounding quotes).
    Returns a :class:`_TransformResult`.
    """
    tokens = class_str.split()

    # Must contain the FA4 base class 'fa'
    if "fa" not in tokens:
        return _TransformResult(class_str, False, False, False)

    # Find the icon token: the fa-* class that is NOT a known modifier
    icon_token: str | None = None
    icon_idx: int = -1
    for i, tok in enumerate(tokens):
        if tok.startswith("fa-") and tok not in _FA_MODIFIERS:
            icon_token = tok
            icon_idx = i
            break

    if icon_token is None:
        # Has 'fa' base class but no recognisable icon — leave untouched
        return _TransformResult(class_str, False, False, False)

    fa4_name = icon_token[3:]   # strip leading 'fa-'
    fa7_style, fa7_name = _get_fa7(fa4_name, shims)

    # Build new token list preserving order:
    # - non-FA tokens that precede the 'fa' base class stay in place
    # - 'fa' base class is replaced by fa7_style + 'fa-NEW_NAME'
    # - 'fa-fw' is dropped (deprecated in FA7)
    # - remaining tokens (modifiers, other classes) follow
    pre_base: list[str] = []     # tokens before 'fa' base class
    post_base: list[str] = []    # tokens after 'fa' base class (excl. icon)
    base_found = False

    for i, tok in enumerate(tokens):
        if tok == "fa" and not base_found:
            base_found = True
            continue                   # drop old base class; style class inserted here
        if tok == "fa-fw":
            continue                   # drop deprecated fixed-width class
        if i == icon_idx:
            continue                   # icon replaced by fa7_style + fa-NEW_NAME
        if not base_found:
            pre_base.append(tok)
        else:
            post_base.append(tok)

    # Correct order: [pre-base tokens] fa7_style fa-icon [modifiers/other]
    new_tokens = pre_base + [fa7_style, f"fa-{fa7_name}"] + post_base
    new_str = " ".join(new_tokens)
    changed = new_str != class_str
    icon_renamed = fa7_name != fa4_name
    style_changed = fa7_style != "fa-solid"  # non-solid is notable

    return _TransformResult(new_str, changed, icon_renamed, style_changed)


# ---------------------------------------------------------------------------
# Dynamic-pattern detector
# ---------------------------------------------------------------------------

# Patterns that indicate a string is dynamically constructed — flag for review
_DYNAMIC_PATTERNS = re.compile(
    r"""
    \{[^}]+\}           |   # f-string / format interpolation: {var}
    %\s*[(\w]           |   # %-formatting: % (var) or %s etc.
    \.format\s*\(       |   # str.format()
    \$\{[^}]+\}         |   # JS template literal: ${var}
    \+\s*[a-zA-Z_]     |   # string concatenation: + var
    [a-zA-Z_]\s*\+          # string concatenation: var +
    """,
    re.VERBOSE,
)


def _is_dynamic(text: str) -> bool:
    return bool(_DYNAMIC_PATTERNS.search(text))


# ---------------------------------------------------------------------------
# Per-file transformation
# ---------------------------------------------------------------------------

# Regex to find FA4 usage in quoted strings (single or double quotes).
# Group 1: opening quote
# Group 2: full quoted content
# Group 3: closing quote (same as group 1)
#
# We match any quoted string that contains '\bfa\b' followed somewhere by
# 'fa-something' — the transform function decides whether it's a real match.
_QUOTED_STRING_RE = re.compile(
    r'(["\'])([^"\'\\]*(?:\\.[^"\'\\]*)*)(\1)',
    re.DOTALL,
)

# Alternatively, match just class attribute values for XML/HTML
# (more precise but misses Python dict values etc.)
_CLASS_ATTR_RE = re.compile(
    r'(?<=class=)(["\'])([^"\']*\bfa\b\s+fa-[\w-]+[^"\']*)(\1)',
)

# Broad token-level scan: find 'fa' word followed (possibly with gap) by 'fa-word'
_FA4_PRESENCE = re.compile(r"\bfa\b")


class FileResult(NamedTuple):
    path: Path
    original: str
    transformed: str
    change_count: int
    flag_count: int
    flags: list[tuple[int, str]]   # (line_number, context)


def _transform_file(path: Path, shims: dict[str, dict[str, str]]) -> FileResult:
    """Read *path*, transform FA4 → FA7, return :class:`FileResult`.

    Strategy:
    1. Work line by line to preserve exact line endings.
    2. For each line, find quoted strings containing FA4 patterns.
    3. Check for dynamic patterns → flag instead of transform.
    4. Apply :func:`_transform_class_string` to static strings.
    """
    original = path.read_text(encoding="utf-8")
    lines = original.split("\n")

    new_lines: list[str] = []
    total_changes = 0
    flag_count = 0
    flags: list[tuple[int, str]] = []

    for lineno, line in enumerate(lines, start=1):
        # Fast path: skip lines with no FA4 base class at all
        if not _FA4_PRESENCE.search(line):
            new_lines.append(line)
            continue

        new_line, n_changes, n_flags, line_flags = _transform_line(
            line, lineno, shims
        )
        new_lines.append(new_line)
        total_changes += n_changes
        flag_count += n_flags
        flags.extend(line_flags)

    transformed = "\n".join(new_lines)
    return FileResult(path, original, transformed, total_changes, flag_count, flags)


def _transform_line(
    line: str,
    lineno: int,
    shims: dict[str, dict[str, str]],
) -> tuple[str, int, int, list[tuple[int, str]]]:
    """Transform one line. Returns (new_line, changes, flags, flag_contexts)."""
    changes = 0
    flags = 0
    flag_contexts: list[tuple[int, str]] = []
    result = line

    def _replacer(match: re.Match[str]) -> str:
        nonlocal changes, flags

        q_open = match.group(1)
        content = match.group(2)
        q_close = match.group(3)

        # Must contain 'fa' as a word
        if not _FA4_PRESENCE.search(content):
            return match.group(0)

        # Must have a fa-icon pattern following the 'fa' word
        if not re.search(r'\bfa\b[^"\']*fa-[\w-]+', content):
            return match.group(0)

        # Dynamic pattern → flag for manual review
        if _is_dynamic(content):
            flags += 1
            flag_contexts.append(
                (lineno, f"  Dynamic pattern — manual review: {match.group(0)[:120]}")
            )
            return match.group(0)

        tr = _transform_class_string(content, shims)
        if tr.changed:
            changes += 1
            return f"{q_open}{tr.new_string}{q_close}"
        return match.group(0)

    result = _QUOTED_STRING_RE.sub(_replacer, line)
    return result, changes, flags, flag_contexts


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _iter_files(paths: list[Path]) -> Iterator[Path]:
    """Yield all processable files under *paths*."""
    for p in paths:
        if p.is_file():
            if p.suffix in _EXTENSIONS:
                yield p
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix in _EXTENSIONS:
                    # Skip blacklisted directories anywhere in path
                    if any(part in _SKIP_DIRS for part in child.parts):
                        continue
                    yield child


# ---------------------------------------------------------------------------
# Diff output
# ---------------------------------------------------------------------------

def _unified_diff(path: Path, original: str, transformed: str) -> str:
    import difflib
    orig_lines = original.splitlines(keepends=True)
    new_lines = transformed.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", type=Path, metavar="path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show unified diff without writing files.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit code 1 if any files would be changed (CI mode).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show each processed file.",
    )
    args = parser.parse_args(argv)

    if not SHIMS_PATH.exists():
        print(f"ERROR: shims.yml not found at {SHIMS_PATH}", file=sys.stderr)
        print("Run Phase 1 first to extract FA7 files.", file=sys.stderr)
        return 2

    shims = _load_shims(SHIMS_PATH)
    print(f"Loaded {len(shims)} shim entries from {SHIMS_PATH.name}")

    total_files_changed = 0
    total_changes = 0
    total_flags = 0
    all_flags: list[tuple[Path, int, str]] = []

    for file_path in _iter_files(args.paths):
        try:
            result = _transform_file(file_path, shims)
        except (UnicodeDecodeError, PermissionError) as exc:
            print(f"  SKIP {file_path}: {exc}", file=sys.stderr)
            continue

        if result.change_count or result.flag_count:
            if args.verbose or result.change_count:
                changed_marker = f"+{result.change_count}" if result.change_count else ""
                flag_marker = f" [{result.flag_count} flags]" if result.flag_count else ""
                print(f"  {file_path}  {changed_marker}{flag_marker}")

        if result.change_count:
            total_files_changed += 1
            total_changes += result.change_count

            if args.dry_run:
                diff = _unified_diff(result.path, result.original, result.transformed)
                print(diff, end="")
            else:
                result.path.write_text(result.transformed, encoding="utf-8")

        if result.flag_count:
            total_flags += result.flag_count
            for lineno, ctx in result.flags:
                all_flags.append((result.path, lineno, ctx))

    print(
        f"\nDone: {total_files_changed} files changed, "
        f"{total_changes} substitutions, "
        f"{total_flags} dynamic patterns flagged for manual review."
    )

    if all_flags:
        print(f"\n{'='*70}")
        print("MANUAL REVIEW REQUIRED (dynamic FA4 patterns):")
        print(f"{'='*70}")
        for fp, ln, ctx in all_flags:
            print(f"  {fp}:{ln}")
            print(ctx)

    if args.check and total_files_changed > 0:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
