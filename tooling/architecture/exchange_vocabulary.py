from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import (
    find_odoo_root,
    find_workspace,
    in_full_workspace,
    sibling_repo_paths,
)

ROOT = find_odoo_root(Path(__file__).resolve(), tool="exchange_vocabulary")
ALLOWLIST = Path(__file__).with_name("exchange_vocabulary_allowlist.json")

CHECKOUT_ROOTS = ("addons", "odoo/addons")

SKIP_DIRS = frozenset({"__pycache__", "node_modules", ".git", "tests", "migrations"})

# A module reaching one of these is talking to a counterparty, whatever its name
# says. The list is deliberately about *protocols and authorities*, not about the
# word "edi" -- that word names three different things,
# and `l10n_co_dian`, `myinvois` and `l10n_id_efaktur_coretax` carry none of it
# while holding the same transmission model as the ones that do.
EXCHANGE_TOKENS = re.compile(
    r"edi|sii|cfdi|dian|tbai|verifactu|oscu|nilvera|peppol|myinvois|nemhandel"
    r"|sinvoice|facturae|fatturapa|efaktur|coretax|saft|clearance|einvoice",
)

CANONICAL = ("draft", "queued", "sent", "accepted", "rejected", "expired")


@dataclass(frozen=True, order=True)
class Finding:
    module: str
    path: str
    line: int
    field: str
    values: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.module}.{self.field}"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.key}  {' | '.join(self.values)}"


def scan_roots() -> list[Path]:
    roots = [ROOT / rel for rel in CHECKOUT_ROOTS]
    if find_workspace(ROOT) is not None:
        roots += sibling_repo_paths(ROOT)
    return [r for r in roots if r.is_dir()]


def _selection_values(node: ast.Call) -> tuple[str, ...] | None:
    listing = next((a for a in node.args if isinstance(a, ast.List)), None)
    for keyword in node.keywords:
        if keyword.arg == "selection" and isinstance(keyword.value, ast.List):
            listing = keyword.value
    if listing is None:
        return None
    return tuple(
        element.elts[0].value
        for element in listing.elts
        if isinstance(element, ast.Tuple)
        and element.elts
        and isinstance(element.elts[0], ast.Constant)
        and isinstance(element.elts[0].value, str)
    )


def _module_of(path: Path, root: Path) -> str:
    return path.relative_to(root).parts[0]


def module_names() -> dict[str, str]:
    found: dict[str, str] = {}
    for root in scan_roots():
        for manifest in root.glob("*/__manifest__.py"):
            found.setdefault(manifest.parent.name, str(root))
    return found


def findings() -> list[Finding]:
    found: list[Finding] = []
    for root in scan_roots():
        for path in root.rglob("*.py"):
            if SKIP_DIRS & set(path.parts):
                continue
            module = _module_of(path, root)
            if not EXCHANGE_TOKENS.search(f"{module}/{path.name}"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                ):
                    continue
                if getattr(node.value.func, "attr", "") != "Selection":
                    continue
                name = getattr(node.targets[0], "id", "")
                if not name.endswith("state"):
                    continue
                values = _selection_values(node.value)
                if not values or set(values) <= set(CANONICAL):
                    continue
                found.append(
                    Finding(
                        module=module,
                        path=str(path.relative_to(root.parent)),
                        line=node.lineno,
                        field=name,
                        values=values,
                    )
                )
    return sorted(found)


def load_allowlist() -> dict[str, str]:
    if not ALLOWLIST.exists():
        return {}
    return json.loads(ALLOWLIST.read_text())["fields"]


def save_allowlist(fields: dict[str, str]) -> None:
    ALLOWLIST.write_text(
        json.dumps(
            {
                "note": (
                    "Selection fields named *state, in a module that talks to a "
                    "counterparty, whose values are not exchange.transmission's. "
                    "Each entry is a lifecycle this workspace spells its own way "
                    "and has not yet moved onto `exchange`. Entries come off as "
                    "modules port; there is no --update, because a flag that "
                    "rewrote this list would let the next one in silently."
                ),
                "fields": dict(sorted(fields.items())),
            },
            indent=2,
        )
        + "\n"
    )


def offenders() -> list[Finding]:
    allowed = load_allowlist()
    return [finding for finding in findings() if finding.key not in allowed]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One exchange lifecycle, not forty-seven.",
    )
    parser.add_argument(
        "--check", action="store_true", help="fail on an unlisted field"
    )
    parser.add_argument("--count", action="store_true", help="print the offender count")
    parser.add_argument("--list", action="store_true", help="print the pinned fields")
    parser.add_argument("--prune", action="store_true", help="drop vanished fields")
    args = parser.parse_args()

    if args.list:
        for key, why in sorted(load_allowlist().items()):
            print(f"  {key:56} {why}")
        return 0

    if args.prune:
        if not in_full_workspace(ROOT):
            print(
                "refusing to prune: the sibling repos are not checked out beside "
                "this one, so a field that is merely out of scope would read as "
                "gone. Run --prune from the full workspace.",
                file=sys.stderr,
            )
            return 1
        allowed = load_allowlist()
        present = {finding.key for finding in findings()}
        kept = {k: v for k, v in allowed.items() if k in present}
        for key in sorted(set(allowed) - set(kept)):
            print(f"pruned {key} (no longer declared)")
        save_allowlist(kept)
        return 0

    present = module_names()
    if not present:
        print(
            "exchange_vocabulary: found no module at all under "
            + ", ".join(str(r) for r in scan_roots() or ["(no readable root)"])
            + ". A gate with no inputs must refuse rather than report success -- "
            "passing here would mean the check silently stopped covering the "
            "tree. An exchange module with nothing left to list is a different "
            "state, and reports zero offenders.",
            file=sys.stderr,
        )
        return 1

    every = findings()
    bad = offenders()

    if args.count:
        print(len(bad))
        return 0

    if not bad:
        if args.check:
            print(
                f"exchange_vocabulary: {len(present)} modules and {len(every)} "
                "state selection(s) scanned, none spells a lifecycle without an "
                "entry saying why"
            )
        return 0

    print(
        f"{len(bad)} state selection(s) spell an exchange lifecycle of "
        "their own.\n"
        "A transmission's phase is exchange.transmission.state -- "
        f"{' | '.join(CANONICAL)} -- and what is\n"
        "being asked for is `intent`, a separate field. A vocabulary that mixes the "
        "two, or\n"
        "renames the phases, is the shape this workspace already had forty-seven "
        "times.\n"
        "Port the module, or add the field to\n"
        f"{ALLOWLIST.relative_to(ROOT)} with the reason it has not moved yet.\n",
        file=sys.stderr,
    )
    for finding in bad:
        print(f"  {finding}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
