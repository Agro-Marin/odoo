#!/usr/bin/env python3
"""Second-pass FA4 → FA7 fixer for static class attributes missed by fa4_to_fa7.py.

Root cause: fa4_to_fa7.py uses _QUOTED_STRING_RE which stops at any quote
character. In XML lines with mixed quotes (e.g. t-if="...'online'..." class="fa fa-circle"),
the regex matches '" class="' as a token, leaving the icon string unquoted.

This script uses a class-attribute-anchored regex (_CLASS_ATTR_RE) which is
immune to surrounding attribute values containing opposite-type quotes.

Also handles:
  - class="fa fa-fw" bare OWL merge prefix  → class="fa-solid fa-fw"
  - t-att-class dict values in ir_actions_views.xml
  - Static JS patterns (class="fa fa-X" in JSX strings)

Usage:
    python fa4_fix_statics.py [--dry-run] <path>...
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Reuse transform logic from fa4_to_fa7.py
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SHIMS_PATH = REPO_ROOT / "addons/web/static/src/libs/fontawesome7/metadata/shims.yml"

_PREFIX_TO_STYLE: dict[str, str] = {
    "fas": "fa-solid",
    "far": "fa-regular",
    "fab": "fa-brands",
    "fal": "fa-light",
    "fat": "fa-thin",
    "fad": "fa-duotone",
}

_FA_MODIFIERS: frozenset[str] = frozenset({
    "fa-spin", "fa-pulse", "fa-fw", "fa-border",
    "fa-pull-left", "fa-pull-right",
    "fa-lg", "fa-2x", "fa-3x", "fa-4x", "fa-5x",
    "fa-6x", "fa-7x", "fa-8x", "fa-9x", "fa-10x",
    "fa-xs", "fa-sm", "fa-1x",
    "fa-stack", "fa-stack-1x", "fa-stack-2x", "fa-inverse",
    "fa-rotate-90", "fa-rotate-180", "fa-rotate-270",
    "fa-flip-horizontal", "fa-flip-vertical", "fa-flip-both",
    "fa-beat", "fa-fade", "fa-beat-fade", "fa-bounce", "fa-shake",
    "fa-li", "fa-ul", "fa-ol", "fa-flip", "fa-rotate",
})


def _load_shims(path: Path) -> dict[str, dict[str, str]]:
    """Parse shims.yml into {fa4_icon_name: {'prefix': str, 'name': str}}."""
    shims: dict[str, dict[str, str]] = {}
    current_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(" "):
            current_key = line.rstrip(":").strip()
            shims[current_key] = {}
        elif current_key and ":" in line:
            sub_key, _, sub_val = line.strip().partition(":")
            shims[current_key][sub_key.strip()] = sub_val.strip()
    return shims


def _get_fa7(fa4_name: str, shims: dict[str, dict[str, str]]) -> tuple[str, str]:
    """Return (fa7_style_class, fa7_icon_name) for an FA4 icon name (no 'fa-' prefix)."""
    if fa4_name in shims:
        entry = shims[fa4_name]
        prefix = entry.get("prefix", "fas")
        name = entry.get("name") or fa4_name
    elif fa4_name.endswith("-o"):
        prefix = "far"
        name = fa4_name[:-2]
    else:
        prefix = "fas"
        name = fa4_name
    return _PREFIX_TO_STYLE.get(prefix, "fa-solid"), name


def _transform_class_string(
    class_str: str,
    shims: dict[str, dict[str, str]],
) -> str | None:
    """Transform a class attribute value from FA4 to FA7 syntax.

    Returns the transformed string, or None if no change needed.
    Keeps fa-fw (unlike the original codemod which drops it — here we keep it
    because many OWL elements rely on it for layout, and FA7 Pro retains it).
    """
    tokens = class_str.split()
    if "fa" not in tokens:
        return None

    # Find the icon token
    icon_token: str | None = None
    icon_idx: int = -1
    for i, tok in enumerate(tokens):
        if tok.startswith("fa-") and tok not in _FA_MODIFIERS:
            icon_token = tok
            icon_idx = i
            break

    if icon_token is None:
        # Has 'fa' but no icon — special case: bare "fa fa-fw" OWL merge prefix
        if "fa-fw" in tokens:
            # Replace bare 'fa' with 'fa-solid' for OWL merge patterns
            new_tokens = ["fa-solid" if t == "fa" else t for t in tokens]
            result = " ".join(new_tokens)
            return result if result != class_str else None
        return None

    fa4_name = icon_token[3:]  # strip 'fa-'
    fa7_style, fa7_name = _get_fa7(fa4_name, shims)

    pre_base: list[str] = []
    post_base: list[str] = []
    base_found = False

    for i, tok in enumerate(tokens):
        if tok == "fa" and not base_found:
            base_found = True
            continue  # drop old base class
        if i == icon_idx:
            continue  # replaced below
        if not base_found:
            pre_base.append(tok)
        else:
            post_base.append(tok)

    new_tokens = pre_base + [fa7_style, f"fa-{fa7_name}"] + post_base
    result = " ".join(new_tokens)
    return result if result != class_str else None


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Anchored on class= to avoid mixed-quote confusion
_CLASS_ATTR_RE = re.compile(
    r'(?<=class=)(["\'])([^"\']*\bfa\b[^"\'"]*)(\1)'
)

# Fast skip: lines with no FA4 base class
_FA4_PRESENCE = re.compile(r"\bfa\b")

# Already-converted: skip lines that are pure FA7
_ALREADY_FA7 = re.compile(r"\bfa-(solid|regular|brands|light|thin|duotone)\b")


def _transform_line(line: str, shims: dict[str, dict[str, str]]) -> tuple[str, int]:
    """Return (new_line, num_changes)."""
    if not _FA4_PRESENCE.search(line):
        return line, 0

    changes = 0

    def _replacer(match: re.Match[str]) -> str:
        nonlocal changes
        q = match.group(1)
        content = match.group(2)

        # Must contain 'fa fa-' pattern (word boundary)
        if not re.search(r'\bfa\b\s+fa-[\w-]+', content):
            return match.group(0)

        result = _transform_class_string(content, shims)
        if result is not None:
            changes += 1
            return f"{q}{result}{q}"
        return match.group(0)

    new_line = _CLASS_ATTR_RE.sub(_replacer, line)
    return new_line, changes


def _process_file(
    path: Path,
    shims: dict[str, dict[str, str]],
    dry_run: bool,
) -> tuple[int, int]:
    """Process one file. Returns (files_changed, substitutions)."""
    original = path.read_text(encoding="utf-8")
    lines = original.split("\n")
    new_lines: list[str] = []
    total_changes = 0

    for line in lines:
        new_line, n = _transform_line(line, shims)
        new_lines.append(new_line)
        total_changes += n

    if total_changes == 0:
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

    return 1, total_changes


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

    shims = _load_shims(SHIMS_PATH)

    total_files = 0
    total_subs = 0
    for path in _iter_files(args.paths):
        f, s = _process_file(path, shims, args.dry_run)
        total_files += f
        total_subs += s

    action = "would change" if args.dry_run else "changed"
    print(
        f"Done: {total_files} files {action}, {total_subs} substitutions.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
