from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path


def _english_list(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) < 3:
        return " and ".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _addon_help(
    default: str, everything: str, siblings: Sequence[str], tail: str
) -> str:
    return (
        f"what to measure: {default} (default) is the odoo/ package, "
        f"{everything} is the whole bundled-addons tree as one number, and "
        f"{_english_list(siblings)} are sibling checkouts{tail}"
    )


def build_parser(
    default_addon: str,
    everything: str,
    siblings: Sequence[str],
    addon_help_tail: str = "",
    addon_help: str | None = None,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=25, help="0 for all")
    parser.add_argument(
        "--addon",
        default=default_addon,
        help=addon_help
        if addon_help is not None
        else _addon_help(default_addon, everything, siblings, addon_help_tail),
    )
    return parser


def run(
    argv: list[str] | None,
    *,
    script: str,
    gate: str,
    headline: str,
    unit: str,
    default_addon: str,
    everything: str,
    siblings: Sequence[str],
    governed: Sequence[str],
    addon_src: Callable[[str], Path],
    measure: Callable[..., list],
    root_name: str,
    summary: Callable[[list], str] | None = None,
    where_for: Callable[[str], str] | None = None,
    addon_help_tail: str = "",
    addon_help: str | None = None,
) -> int:
    args = build_parser(
        default_addon, everything, siblings, addon_help_tail, addon_help
    ).parse_args(argv)

    if args.addon not in governed:
        print(
            f"error: {args.addon!r} is not a governed scope. Onboarding one is a "
            f"row in GOVERNED_ADDONS and its own baseline, not a flag: a floor "
            f"over an unscanned tree checks nothing.\n"
            f"       governed: {', '.join(governed)}",
            file=sys.stderr,
        )
        return 2

    src = addon_src(args.addon)
    if args.addon in siblings and not src.is_dir():
        print(
            f"SKIP: {args.addon} is not checked out beside {root_name}; "
            f"its own architecture.yml pairs the two and runs this there.",
            file=sys.stderr,
        )
        return 0

    try:
        found = measure(src=src)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(item) for item in found], indent=2))
        return 0

    if where_for is not None:
        where = where_for(args.addon)
    else:
        where = {default_addon: "odoo/", everything: "addons/"}.get(
            args.addon, f"{args.addon}/"
        )
    print(headline.format(where=where))
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{len(found)} {unit}   <- the ratcheted number")
    if summary is not None:
        print(summary(found))
    suffix = "" if args.addon == default_addon else f" --addon {args.addon}"
    name = gate if args.addon == default_addon else f"{gate}_{args.addon}"
    print("\nRatchet it:")
    print(f"  python tooling/architecture/{script} --count{suffix} \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0
