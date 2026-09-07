"""The read-only tier of every privilege, held to one pattern.

Five apps carry a read-only group beside their privilege's ladder:
`stock.group_stock_readonly`, `sales_team.group_sale_readonly`,
`purchase.group_purchase_readonly`, `mrp.group_mrp_readonly` and
`account.group_account_readonly`. Each is a decision to SEE everything the app
shows and change none of it, so three things must hold for each, and none of
them is derivable from the ladder (measured 2026-09-06: what the rungs write is
mostly wizards and other apps' models; what the tier reads is mostly bridges).
Hence three checks over the declared rows and rules, at the tree level:

* ``grants_write``: a row on a read-only group carries no write bit. A wizard
  that only reads needs ``create`` to be opened at all, so those are named in
  ``READ_ONLY_WIZARDS`` with the tier that may open them.
* ``ruleless``: where a rung of the same privilege narrows a model the tier
  reads by record rule, the tier carries a read rule on that model, or the
  reader's scope depends on which other hats they wear. Record rules OR across
  a user's groups, which is also why the rung that implies the tier is the
  lowest one that already sees every document -- a narrower rung implying it
  would read everything through the tier's rule.
* ``dead_rows``: a read-only row grants nothing when ``base.group_user`` already
  reads the model through a module in the row's own dependency closure. The
  closure matters: ``website_event`` opens events to every employee, which makes
  ``event_sale``'s rows redundant only in an install that carries it.

All three are hard zeros. ``--census`` prints the table the plan restates.
"""

from __future__ import annotations

import argparse
import ast
import csv
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _count_gate

ROOT = find_odoo_root(Path(__file__).resolve(), tool="readonly_tiers")
WORKSPACE = sibling_repos_root(ROOT)
DEFAULT_ADDON = "addons"
SIBLING_SCOPES = ("enterprise", "agromarin")
GOVERNED_ADDONS = (DEFAULT_ADDON, *SIBLING_SCOPES)
BLANKET = "[(1, '=', 1)]"

TIERS: dict[str, tuple[str, frozenset[str]]] = {
    "stock": (
        "stock.group_stock_readonly",
        frozenset({"stock.group_stock_user", "stock.group_stock_manager"}),
    ),
    "sale": (
        "sales_team.group_sale_readonly",
        frozenset(
            {
                "sales_team.group_sale_salesman",
                "sales_team.group_sale_salesman_team",
                "sales_team.group_sale_salesman_all_leads",
                "sales_team.group_sale_manager",
            }
        ),
    ),
    "purchase": (
        "purchase.group_purchase_readonly",
        frozenset(
            {
                "purchase.group_purchase_user",
                "purchase.group_purchase_user_all",
                "purchase.group_purchase_manager",
            }
        ),
    ),
    "mrp": (
        "mrp.group_mrp_readonly",
        frozenset({"mrp.group_mrp_user", "mrp.group_mrp_manager"}),
    ),
    "account": (
        "account.group_account_readonly",
        frozenset(
            {
                "account.group_account_invoice",
                "account.group_account_basic",
                "account.group_account_user",
                "account.group_account_manager",
            }
        ),
    ),
}

# Report wizards a tier may open: they only read, and a wizard cannot be
# instantiated without create.
READ_ONLY_WIZARDS: dict[str, frozenset[str]] = {
    "stock.group_stock_readonly": frozenset(
        {
            "stock.model_stock_quantity_history",
            "stock.model_stock_rules_report",
            "stock.model_stock_traceability_report",
        }
    ),
}

KINDS = ("grants_write", "ruleless", "dead_rows")


@dataclass(frozen=True)
class Finding:
    kind: str
    tier: str
    model: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: {self.tier} {self.kind} {self.model}  {self.detail}"


@dataclass(frozen=True)
class AclRow:
    module: str
    path: Path
    xmlid: str
    model: str
    group: str
    read: bool
    write: bool
    create: bool
    unlink: bool


@dataclass(frozen=True)
class Rule:
    module: str
    path: Path
    xmlid: str
    model: str
    groups: frozenset[str]
    domain: str


def _qualify(ref: str, module: str) -> str:
    return ref if "." in ref else f"{module}.{ref}"


def _addon_roots(scope: str) -> list[Path]:
    if scope == DEFAULT_ADDON:
        return [ROOT / "addons", ROOT / "odoo" / "addons"]
    return [WORKSPACE / scope]


def _all_addon_roots() -> list[Path]:
    return [ROOT / "addons", ROOT / "odoo" / "addons"] + [
        WORKSPACE / s for s in SIBLING_SCOPES if (WORKSPACE / s).is_dir()
    ]


def _module_dirs(roots: Iterable[Path]) -> list[Path]:
    return sorted(
        d
        for root in roots
        for d in root.iterdir()
        if d.is_dir() and (d / "__manifest__.py").is_file()
    )


def _read_acl(module_dir: Path) -> list[AclRow]:
    path = module_dir / "security" / "ir.model.access.csv"
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            model = row.get("model_id:id") or row.get("model_id/id") or ""
            if not model:
                continue
            group = row.get("group_id:id") or row.get("group_id/id") or ""
            rows.append(
                AclRow(
                    module=module_dir.name,
                    path=path,
                    xmlid=f"{module_dir.name}.{row.get('id', '')}",
                    model=_qualify(model, module_dir.name),
                    group=_qualify(group, module_dir.name) if group else "",
                    read=row.get("perm_read", "0").strip() == "1",
                    write=row.get("perm_write", "0").strip() == "1",
                    create=row.get("perm_create", "0").strip() == "1",
                    unlink=row.get("perm_unlink", "0").strip() == "1",
                )
            )
    return rows


def _read_rules(module_dir: Path) -> list[Rule]:
    rules = []
    for path in sorted((module_dir / "security").glob("*.xml")):
        try:
            root = etree.parse(str(path)).getroot()
        except etree.XMLSyntaxError:
            continue
        for record in root.iter("record"):
            if record.get("model") != "ir.rule":
                continue
            model = None
            groups: set[str] = set()
            domain = ""
            for field in record.findall("field"):
                name = field.get("name")
                if name == "model_id":
                    model = field.get("ref")
                elif name == "domain_force":
                    domain = " ".join((field.text or "").split())
                elif name in ("group_ids", "groups"):
                    groups.update(
                        _qualify(ref, module_dir.name)
                        for ref in re.findall(
                            r"ref\('([^']+)'\)", field.get("eval", "")
                        )
                    )
            if model:
                rules.append(
                    Rule(
                        module=module_dir.name,
                        path=path,
                        xmlid=f"{module_dir.name}.{record.get('id')}",
                        model=_qualify(model, module_dir.name),
                        groups=frozenset(groups),
                        domain=domain,
                    )
                )
    return rules


def _depends(module_dir: Path) -> list[str]:
    try:
        manifest = ast.literal_eval((module_dir / "__manifest__.py").read_text())
    except SyntaxError, ValueError:
        return []
    return list(manifest.get("depends", []))


def _closure(module: str, depends: dict[str, list[str]]) -> frozenset[str]:
    seen = {module}
    stack = [module]
    while stack:
        for dep in depends.get(stack.pop(), []):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return frozenset(seen)


class Tree:
    def __init__(self) -> None:
        dirs = _module_dirs(_all_addon_roots())
        self.acl = [row for d in dirs for row in _read_acl(d)]
        self.rules = [rule for d in dirs for rule in _read_rules(d)]
        self.depends = {d.name: _depends(d) for d in dirs}

    def group_user_readers(self, model: str) -> set[str]:
        return {
            row.module
            for row in self.acl
            if row.model == model and row.group == "base.group_user" and row.read
        }


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(WORKSPACE))
    except ValueError:
        return str(path)


def _in_scope(path: Path, src: Path) -> bool:
    if src == ROOT:
        return path.is_relative_to(ROOT)
    return path.is_relative_to(src)


def measure_grants_write(tree: Tree, src: Path) -> list[Finding]:
    found = []
    for tier, (readonly, _rungs) in TIERS.items():
        allowed = READ_ONLY_WIZARDS.get(readonly, frozenset())
        for row in tree.acl:
            if row.group != readonly or not _in_scope(row.path, src):
                continue
            if row.unlink or ((row.write or row.create) and row.model not in allowed):
                found.append(
                    Finding(
                        "grants_write",
                        tier,
                        row.model,
                        _relative(row.path),
                        f"{row.xmlid} carries a write bit",
                    )
                )
    return found


def measure_ruleless(tree: Tree, src: Path) -> list[Finding]:
    found = []
    for tier, (readonly, rungs) in TIERS.items():
        read = {row.model for row in tree.acl if row.group == readonly and row.read}
        tier_ruled = {rule.model for rule in tree.rules if readonly in rule.groups}
        for rule in tree.rules:
            if (
                rule.model in read
                and rule.groups & rungs
                and rule.domain != BLANKET
                and rule.model not in tier_ruled
                and _in_scope(rule.path, src)
            ):
                found.append(
                    Finding(
                        "ruleless",
                        tier,
                        rule.model,
                        _relative(rule.path),
                        f"{rule.xmlid} narrows a rung and the tier has no read rule",
                    )
                )
                tier_ruled.add(rule.model)
    return found


def measure_dead_rows(tree: Tree, src: Path) -> list[Finding]:
    found = []
    readonly_groups = {readonly: tier for tier, (readonly, _r) in TIERS.items()}
    for row in tree.acl:
        tier = readonly_groups.get(row.group)
        if tier is None or not _in_scope(row.path, src):
            continue
        granting = tree.group_user_readers(row.model) & _closure(
            row.module, tree.depends
        )
        if granting:
            found.append(
                Finding(
                    "dead_rows",
                    tier,
                    row.model,
                    _relative(row.path),
                    f"{row.xmlid} duplicates base.group_user's read from "
                    f"{', '.join(sorted(granting))}",
                )
            )
    return found


MEASURES = {
    "grants_write": measure_grants_write,
    "ruleless": measure_ruleless,
    "dead_rows": measure_dead_rows,
}


def census(tree: Tree) -> str:
    base_reads = {row.model for row in tree.acl if row.group == "base.group_user"}
    header = (
        f"{'tier':9} {'rungs write':>11} {'derived':>8} {'tier reads':>10} "
        f"{'both':>5} {'tier-only':>9} {'derived-only':>12}"
    )
    lines = [header]
    for tier, (readonly, rungs) in TIERS.items():
        writable = {
            row.model
            for row in tree.acl
            if row.group in rungs and (row.write or row.create or row.unlink)
        }
        reads = {row.model for row in tree.acl if row.group == readonly and row.read}
        derived = writable - base_reads
        lines.append(
            f"{tier:9} {len(writable):>11} {len(derived):>8} {len(reads):>10} "
            f"{len(reads & derived):>5} {len(reads - derived):>9} "
            f"{len(derived - reads):>12}"
        )
    return "\n".join(lines)


def _addon_src(scope: str) -> Path:
    return ROOT if scope == DEFAULT_ADDON else WORKSPACE / scope


def main(argv: list[str] | None = None) -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--kind", choices=KINDS, default="grants_write")
    pre.add_argument("--census", action="store_true")
    known, rest = pre.parse_known_args(argv)
    tree = Tree()
    if known.census:
        print(census(tree))
        return 0
    measure = MEASURES[known.kind]
    return _count_gate.run(
        rest,
        script="readonly_tiers.py",
        gate=f"readonly_tier_{known.kind}",
        headline=f"read-only tier {known.kind} findings in {{where}}",
        unit=f"{known.kind} finding(s)",
        default_addon=DEFAULT_ADDON,
        everything=DEFAULT_ADDON,
        siblings=SIBLING_SCOPES,
        governed=GOVERNED_ADDONS,
        addon_src=_addon_src,
        measure=lambda src: sorted(
            measure(tree, src), key=lambda f: (f.tier, f.model, f.where)
        ),
        root_name="odoo",
        description=__doc__,
    )


if __name__ == "__main__":
    sys.exit(main())
