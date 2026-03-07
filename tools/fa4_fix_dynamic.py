#!/usr/bin/env python3
"""Third-pass FA4 → FA7 fixer for dynamic t-attf-class / t-att-class patterns.

Handles patterns the previous passes couldn't auto-transform because they
contain template interpolations.

Categories handled:
  A. `fa fa-ICON {{ dynamic }}` → `fa-solid fa-ICON {{ dynamic }}`
     Safe when icon name is static and clearly solid.
  B. `fa fa-fw {{ ... }}` → `fa-solid fa-fw {{ ... }}`
  C. Brand icons in t-attf-class:
     `fa fa-facebook/twitter/linkedin/whatsapp/pinterest` → `fa-brands fa-X`
  D. `fa fa-fw fa-caret-{{ dir }}` → `fa-solid fa-fw fa-caret-{{ dir }}`

Complex `-o` conditional patterns (e.g. `fa-star#{cond ? '' : '-o'}`) are
handled separately by hand in this script via explicit sed-like substitutions.

Usage:
    python fa4_fix_dynamic.py [--dry-run] <path>...
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Substitution rules: (pattern, replacement)
#
# Applied in order. Each pattern is matched against each LINE of the file.
# Use raw-string regexes with re.sub semantics.
# ---------------------------------------------------------------------------

_RULES: list[tuple[str, str]] = [
    # -------------------------------------------------------------------------
    # Category B+D: fa fa-fw (with caret or other dynamic icon suffix)
    # -------------------------------------------------------------------------
    # "fa fa-fw fa-caret-{{ ... }}"  → "fa-solid fa-fw fa-caret-{{ ... }}"
    # "fa fa-fw {{ ... }}" → "fa-solid fa-fw {{ ... }}"
    # "fa fa-fw #{...}" → "fa-solid fa-fw #{...}"
    (r'\bfa fa-fw\b', 'fa-solid fa-fw'),

    # -------------------------------------------------------------------------
    # Category C: Social media brand icons (dynamic suffix: rounded shadow-sm)
    # -------------------------------------------------------------------------
    (r'\bfa fa-(facebook|twitter|linkedin|whatsapp|pinterest|instagram|youtube|'
     r'github|gitlab|google|amazon|apple|android|windows|linux|btc|bitcoin|'
     r'snapchat|skype|slack|spotify|steam|twitch|vimeo|wordpress)\b',
     r'fa-brands fa-\1'),

    # -------------------------------------------------------------------------
    # Category A: Specific static icons that are unambiguously solid
    # fa fa-ICON {{ dynamic_conditional }} patterns
    # -------------------------------------------------------------------------
    # Navigation/caret icons
    (r'\bfa fa-(caret|chevron|angle|arrow)-(up|down|left|right|circle)\b',
     r'fa-solid fa-\1-\2'),
    (r'\bfa fa-caret-\{\{', 'fa-solid fa-caret-{{'),
    (r'\bfa fa-caret-#\{', 'fa-solid fa-caret-#{'),
    (r'\bfa fa-sort-numeric-\{\{', 'fa-solid fa-sort-numeric-{{'),
    (r'\bfa fa-sign-\{\{', 'fa-solid fa-sign-{{'),
    (r"\bfa fa-sign-'", "fa-solid fa-sign-'"),
    (r'\bfa fa-arrow-#\{', 'fa-solid fa-arrow-#{'),
    (r'\bfa fa-arrow-\{\{', 'fa-solid fa-arrow-{{'),
    (r'\bfa fa-angle-#\{', 'fa-solid fa-angle-#{'),
    (r'\bfa fa-angle-\{\{', 'fa-solid fa-angle-{{'),
    (r'\bfa fa-cloud-upload\b', 'fa-solid fa-cloud-upload'),
    (r'\bfa fa-area-chart\b', 'fa-solid fa-area-chart'),

    # UI icons (solid)
    (r'\bfa fa-sort\b', 'fa-solid fa-sort'),
    (r'\bfa fa-plus\b', 'fa-solid fa-plus'),
    (r'\bfa fa-trash\b', 'fa-solid fa-trash'),
    (r'\bfa fa-list\b', 'fa-solid fa-list'),
    (r'\bfa fa-lock\b', 'fa-solid fa-lock'),
    (r'\bfa fa-info-circle\b', 'fa-solid fa-info-circle'),
    (r'\bfa fa-comment\b', 'fa-solid fa-comment'),
    (r'\bfa fa-envelope\b', 'fa-solid fa-envelope'),
    (r'\bfa fa-user\b', 'fa-solid fa-user'),
    (r'\bfa fa-user-circle\b', 'fa-solid fa-user-circle'),
    (r'\bfa fa-star\b', 'fa-solid fa-star'),
    (r'\bfa fa-flag\b', 'fa-solid fa-flag'),
    (r'\bfa fa-window-close\b', 'fa-solid fa-window-close'),
    (r'\bfa fa-check\b(?!\s*-)', 'fa-solid fa-check'),

    # These appear with {{ dynamic }} suffix
    (r'\bfa fa-\{\{', 'fa-solid fa-{{'),
    (r'\bfa fa-#\{', 'fa-solid fa-#{'),
]

# Brand icon list for t-attf-class complete replacement
_BRAND_RE = re.compile(
    r'\bfa fa-(facebook|twitter|linkedin|whatsapp|pinterest|instagram|youtube|'
    r'github|gitlab|google|amazon|apple|android|windows|linux|btc|bitcoin|'
    r'snapchat|skype|slack|spotify|steam|twitch|vimeo|wordpress)\b'
)

# Compile all rules
_COMPILED_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat), repl) for pat, repl in _RULES
]

_FA4_PRESENCE = re.compile(r"\bfa fa-")


def _transform_line(line: str) -> tuple[str, int]:
    if not _FA4_PRESENCE.search(line):
        return line, 0
    result = line
    changes = 0
    for pattern, replacement in _COMPILED_RULES:
        new = pattern.sub(replacement, result)
        if new != result:
            changes += 1
            result = new
    return result, changes


def _process_file(path: Path, dry_run: bool) -> tuple[int, int]:
    original = path.read_text(encoding="utf-8")
    lines = original.split("\n")
    new_lines: list[str] = []
    total = 0
    for line in lines:
        new_line, n = _transform_line(line)
        new_lines.append(new_line)
        total += n
    if total == 0:
        return 0, 0
    transformed = "\n".join(new_lines)
    if dry_run:
        import difflib
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            transformed.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        sys.stdout.write("".join(diff))
    else:
        path.write_text(transformed, encoding="utf-8")
    return 1, total


_EXTENSIONS = frozenset({".xml", ".html", ".js", ".ts", ".py", ".scss", ".css"})
_SKIP_DIRS = frozenset({
    "__pycache__", ".git", "node_modules", "_vendor",
    "fontawesome", "fontawesome7", ".mypy_cache", ".ruff_cache",
})


def _iter_files(paths: list[Path]):
    for p in paths:
        if p.is_file():
            if p.suffix in _EXTENSIONS:
                yield p
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix in _EXTENSIONS:
                    if any(part in _SKIP_DIRS for part in child.parts):
                        continue
                    yield child


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    total_files = 0
    total_subs = 0
    for path in _iter_files(args.paths):
        f, s = _process_file(path, args.dry_run)
        total_files += f
        total_subs += s

    action = "would change" if args.dry_run else "changed"
    print(
        f"Done: {total_files} files {action}, {total_subs} substitutions.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
