#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import SIBLING_REPOS, find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="tsconfig_paths")
TSCONFIG = ROOT / "tsconfig.json"

BEGIN = "// >>> derived: addon aliases"
END = "// <<< derived: addon aliases"

INDENT = " " * 12

HEADER = f"""{INDENT}{BEGIN} -- do not hand-edit.
{INDENT}// Rewrite with: python tooling/typecheck/tsconfig_paths.py --update"""

CHECKOUTS = (
    (ROOT / "addons", "addons"),
    *((ROOT.parent / name, f"../{name}") for name in SIBLING_REPOS),
)

# Every prefix a target may legally carry, whether or not that checkout is on
# disk. Read from the layout rather than from CHECKOUTS, which a caller may
# narrow to simulate an absent sibling.
KNOWN_PREFIXES = {"addons", *(f"../{name}" for name in SIBLING_REPOS)}


def addons_on_disk() -> dict[str, str]:
    found: dict[str, str] = {}
    for base, prefix in CHECKOUTS:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            # A manifest as well as a static/src: this walks the filesystem, and
            # a deleted module leaves its directory behind in any long-lived
            # checkout that still holds gitignored bytecode under it. Three such
            # husks minted `@web_enterprise/*`, `@approvals/*` and
            # `@approvals_purchase/*` into the committed tsconfig on 2026-09-03,
            # a day after `09bc9e3e2de` removed the modules from git.
            if (entry / "static" / "src").is_dir() and (
                entry / "__manifest__.py"
            ).is_file():
                found.setdefault(entry.name, f"{prefix}/{entry.name}/static/src/*")
    return found


def present_prefixes() -> set[str]:
    return {prefix for base, prefix in CHECKOUTS if base.is_dir()}


def _split(text: str) -> tuple[str, str, str]:
    try:
        start = text.index(BEGIN)
        stop = text.index(END)
    except ValueError:
        raise SystemExit(
            f"{TSCONFIG} has no {BEGIN!r} / {END!r} markers; add them around the "
            f"addon-alias entries first"
        ) from None
    line_start = text.rindex("\n", 0, start) + 1
    line_stop = text.index("\n", stop) + 1
    return text[:line_start], text[line_start:line_stop], text[line_stop:]


def _existing_entries(block: str) -> dict[str, str]:
    return dict(re.findall(r'"(@[^"]+)":\s*\["([^"]+)"\]', block))


def _checkout_prefix(target: str) -> str:
    parts = target.split("/")
    return "/".join(parts[:2]) if parts[0] == ".." else parts[0]


def desired_entries(existing: dict[str, str]) -> dict[str, str]:
    on_disk = addons_on_disk()
    present = present_prefixes()
    kept: dict[str, str] = {}
    for alias, target in existing.items():
        addon = alias.removeprefix("@").removesuffix("/*")
        prefix = _checkout_prefix(target)
        if prefix not in KNOWN_PREFIXES:
            # An entry naming no checkout at all is malformed, not a sibling
            # that happens to be absent. Keeping it, which is what the next
            # branch does for every prefix it does not recognise, would
            # preserve it through every regeneration that could correct it.
            continue
        if prefix not in present:
            kept[alias] = target
        elif addon in on_disk:
            kept[alias] = on_disk[addon]
    for addon, target in on_disk.items():
        kept.setdefault(f"@{addon}/*", target)
    return dict(sorted(kept.items()))


def render(entries: dict[str, str]) -> str:
    body = ",\n".join(
        f'{INDENT}"{alias}": ["{target}"]' for alias, target in entries.items()
    )
    return f"{HEADER}\n{body}\n{INDENT}{END}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if it drifted")
    parser.add_argument("--update", action="store_true", help="rewrite the block")
    args = parser.parse_args(argv)

    text = TSCONFIG.read_text(encoding="utf8")
    before, block, after = _split(text)
    existing = _existing_entries(block)
    wanted = desired_entries(existing)
    new_block = render(wanted)

    if args.update:
        if new_block == block:
            print("tsconfig.json: already derived")
            return 0
        TSCONFIG.write_text(before + new_block + after, encoding="utf8")
        print(f"tsconfig.json: {len(wanted)} addon aliases written")
        return 0

    added = sorted(set(wanted) - set(existing))
    removed = sorted(set(existing) - set(wanted))
    if new_block == block:
        print(f"tsconfig.json: {len(wanted)} addon aliases, derived")
        return 0
    print("tsconfig.json addon aliases have drifted from the addon layout:")
    for alias in added[:20]:
        print(f"  + {alias}")
    for alias in removed[:20]:
        print(f"  - {alias}")
    if len(added) + len(removed) > 40:
        print(f"  ... {len(added) + len(removed) - 40} more")
    print("  run: python tooling/typecheck/tsconfig_paths.py --update")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
