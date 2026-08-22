#!/usr/bin/env python3
"""Derive ``compilerOptions.paths``'s addon-alias block from the addon layout.

Every addon ``X`` that ships ``static/src/`` publishes ``@X/*``. That was always
the rule -- ``tsconfig.json`` says so in prose -- but the block was maintained by
hand, so it drifted: 599 addons on disk ship ``static/src`` against 238 entries,
and the gate only notices the gap when some JS actually imports one of the missing
aliases. It went red on ``@website_mail`` and ``@website_profile`` that way. A list
that is derived by definition and edited by hand will keep rotting; this derives it.

**Scope tolerance is the whole design.** CI checks ``odoo`` out alone, a developer
has ``enterprise/``, ``agromarin/`` and ``design-themes/`` beside it, and the same
file has to be correct in both. So, on the same principle the sibling
``architecture.yml`` lanes use, this tool *grows* what it can see and refuses to
shrink what it cannot:

* an addon on disk with no entry                              -> added
* an entry whose checkout is absent here                      -> kept, untouched
* an entry whose checkout IS present but whose addon is gone  -> removed
* an entry that is not an addon alias (``@odoo/hoot`` -> a file) -> outside the
  markers entirely, so never seen

Run from the repo root::

    python tooling/typecheck/tsconfig_paths.py --check     # what CI asks
    python tooling/typecheck/tsconfig_paths.py --update    # rewrite the block
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="tsconfig_paths")
TSCONFIG = ROOT / "tsconfig.json"

BEGIN = "// >>> derived: addon aliases"
END = "// <<< derived: addon aliases"

INDENT = " " * 12

HEADER = f"""{INDENT}{BEGIN} -- do not hand-edit.
{INDENT}// Every addon shipping `static/src/` publishes `@X/*`. Rewrite with
{INDENT}//     python tooling/typecheck/tsconfig_paths.py --update
{INDENT}// The generator only adds addons it can see and never deletes an entry
{INDENT}// belonging to a checkout that is absent, so running it in CI (odoo
{INDENT}// alone) does not drop the enterprise/agromarin/design-themes aliases."""

CHECKOUTS = (
    (ROOT / "addons", "addons"),
    (ROOT.parent / "enterprise", "../enterprise"),
    (ROOT.parent / "agromarin", "../agromarin"),
    (ROOT.parent / "design-themes", "../design-themes"),
)


def addons_on_disk() -> dict[str, str]:
    """``{addon: target}`` for every addon shipping ``static/src``; first checkout wins."""
    found: dict[str, str] = {}
    for base, prefix in CHECKOUTS:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if (entry / "static" / "src").is_dir():
                found.setdefault(entry.name, f"{prefix}/{entry.name}/static/src/*")
    return found


def present_prefixes() -> set[str]:
    return {prefix for base, prefix in CHECKOUTS if base.is_dir()}


def _split(text: str) -> tuple[str, str, str]:
    """``(before, block, after)`` around the derived region, whole lines."""
    try:
        start = text.index(BEGIN)
        stop = text.index(END)
    except ValueError:
        raise SystemExit(
            f"{TSCONFIG} has no {BEGIN!r} / {END!r} markers; add them around the "
            f"addon-alias entries first (see this module's docstring)"
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
        if _checkout_prefix(target) not in present:
            kept[alias] = target  # another checkout's alias: not ours to judge
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
