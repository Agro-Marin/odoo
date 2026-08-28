"""Default-deny gate over module names carrying "edi".

ADR-0048: the word names three unrelated things in this tree -- fiscal clearance,
partner interchange, document import -- and only the middle one is interchange.
The word cost three wrong conclusions in one afternoon, including a refactor
proposal that would have made fifteen modules, `purchase` among them, depend on an
EDI-document queue they do not use.

Gated at module level because that is where the vocabulary propagates: a module's
models and fields inherit its prefix, and a module name is the identifier other
repositories write down. Model and field names are deliberately not gated -- the
194 `l10n_mx_edi_*` fields carry the prefix and nothing else, and their own names
are accurate.

`l10n_*` is exempt by rule: those names are Odoo ecosystem identifiers, and
ADR-0048 records why renaming `l10n_mx_edi` was considered and rejected.

Usage:
    edi_vocabulary.py --check          # the gate; non-zero on an unlisted module
    edi_vocabulary.py --list           # what is pinned, and why each one is allowed
    edi_vocabulary.py --prune          # drop entries whose module no longer exists
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import (
    find_odoo_root,
    find_workspace,
    in_workspace,
    sibling_repo_paths,
)

ADR = "0048"

ROOT = find_odoo_root(Path(__file__).resolve())
ALLOWLIST = Path(__file__).with_name("edi_vocabulary_allowlist.json")

CHECKOUT_ROOTS = ("addons", "odoo/addons")


def scan_roots() -> list[Path]:
    roots = [ROOT / rel for rel in CHECKOUT_ROOTS]
    workspace = find_workspace(ROOT)
    if workspace is not None:
        roots += sibling_repo_paths(ROOT)
    return [r for r in roots if r.is_dir()]


def module_names() -> dict[str, str]:
    found: dict[str, str] = {}
    for root in scan_roots():
        for manifest in root.glob("*/__manifest__.py"):
            found.setdefault(manifest.parent.name, str(root))
    return found


def carries_edi(name: str) -> bool:
    return "edi" in name.split("_")


def load_allowlist() -> dict[str, str]:
    if not ALLOWLIST.exists():
        return {}
    return json.loads(ALLOWLIST.read_text())["modules"]


def save_allowlist(modules: dict[str, str]) -> None:
    ALLOWLIST.write_text(
        json.dumps(
            {
                "adr": ADR,
                "note": (
                    "Modules whose name carries 'edi' as a component. `l10n_*` is "
                    "exempt by rule and is not listed. Add an entry only with the "
                    "category that justifies it; there is no --update."
                ),
                "modules": dict(sorted(modules.items())),
            },
            indent=2,
        )
        + "\n"
    )


def offenders() -> list[str]:
    allowed = load_allowlist()
    return sorted(
        name
        for name in module_names()
        if carries_edi(name) and not name.startswith("l10n_") and name not in allowed
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail on an unlisted module"
    )
    parser.add_argument("--list", action="store_true", help="print the pinned modules")
    parser.add_argument("--prune", action="store_true", help="drop vanished modules")
    args = parser.parse_args()

    if args.list:
        for name, why in sorted(load_allowlist().items()):
            print(f"  {name:28} {why}")
        return 0

    if args.prune:
        if not in_workspace(ROOT):
            print(
                "refusing to prune: the sibling repos are not checked out beside "
                "this one. Run --prune from the full workspace, where every "
                "scanned root exists.",
                file=sys.stderr,
            )
            return 1
        allowed = load_allowlist()
        present = module_names()
        kept = {k: v for k, v in allowed.items() if k in present}
        dropped = sorted(set(allowed) - set(kept))
        save_allowlist(kept)
        for name in dropped:
            print(f"pruned {name} (module no longer present)")
        return 0

    present = module_names()
    if not present:
        print(
            "edi_vocabulary: found no module at all under "
            + ", ".join(str(r) for r in scan_roots() or ["(no readable root)"])
            + ". A gate with no inputs must refuse rather than report success -- "
            "passing here would mean the check silently stopped covering the tree.",
            file=sys.stderr,
        )
        return 1

    bad = offenders()
    if not bad:
        if args.check:
            print(
                f"edi_vocabulary: {len(present)} modules scanned, "
                "none carries 'edi' without an entry saying why"
            )
        return 0

    print(
        f"ADR-{ADR}: {len(bad)} module name(s) carry 'edi' without an entry saying why.\n"
        "'EDI' names three things here and only partner interchange is one of them.\n"
        "A module whose counterparty is a tax authority is named for the document or\n"
        "the regime (_cfdi, _fiscal), not _edi. If this one really does exchange\n"
        "documents with another business, add it to\n"
        f"{ALLOWLIST.relative_to(ROOT)} with its category.\n",
        file=sys.stderr,
    )
    for name in bad:
        print(f"  {name}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
