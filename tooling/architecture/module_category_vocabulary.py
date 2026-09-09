"""Module categories are a closed vocabulary, and a manifest names one path in it.

`ir.module.module.category` is not a choice from a list. `get_or_create_category_id`
splits the string on "/" and turns every prefix into an `ir.module.category` row keyed
by an xml id built from that prefix -- lowercased, "&" to "and", spaces to underscores.
A manifest therefore CREATES whatever it names, silently, and a typo is indistinguishable
from a decision. That is how one workspace came to hold `Fleet` beside
`Human Resources/Fleet`, `Inventory/Inventory` beside `Supply Chain/Inventory`, `Technical`
beside `Hidden` (whose row is displayed "Technical"), and a category whose name was a
summary sentence.

Two rules, and both are about the ROOT of the path:

ROOT DECLARED  the first segment must resolve to a category some data file declares.
    Deeper segments stay free -- `Accounting/Localizations/Reporting` should not need a
    record, and Odoo has always let a module name its own leaf. The root is the part that
    has consequences, because `ir.ui.menu._get_app_categories` walks to it and hands it to
    the app launcher as a group heading. A root nobody declared is a heading nobody chose.

PATH IMPLIES PARENT  a declared record whose xml id path names a parent that also exists
    must declare that parent. `module_category_services_helpdesk` with no `parent_id` reads
    as a top-level application called Helpdesk, and on a database where the row is created
    by the data file before any manifest asks for the path, that is exactly what it becomes.

Neither rule is a ratchet. Both measure zero and are meant to stay there.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _ast_cache
from _ast_cache import SourceUnreadable
from _repo_root import find_odoo_root, find_workspace, sibling_repo_paths

ROOT = find_odoo_root(Path(__file__).resolve())

CHECKOUT_ROOTS = ("addons", "odoo/addons")


def scan_roots() -> list[Path]:
    roots = [ROOT / rel for rel in CHECKOUT_ROOTS]
    if find_workspace(ROOT) is not None:
        roots += sibling_repo_paths(ROOT)
    return [r for r in roots if r.is_dir()]


def category_xmlid(segments: list[str]) -> str:
    joined = "_".join(segment.lower() for segment in segments)
    return "module_category_" + joined.replace("&", "and").replace(" ", "_")


@dataclass(frozen=True)
class Violation:
    rule: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: {self.detail}"


def _manifests(roots: list[Path]) -> Iterator[tuple[Path, dict]]:
    """Every module manifest under `roots`, read through the one door.

    `_ast_cache.literal_file` raises `SourceUnreadable` naming the path. A gate
    that swallows a manifest it could not read reports one fewer module than the
    tree holds and calls that a clean scan.
    """
    for root in roots:
        for manifest in sorted(root.glob("*/__manifest__.py")):
            declared = _ast_cache.literal_file(manifest)
            if isinstance(declared, dict):
                yield manifest, declared


def declared_data_files(roots: list[Path]) -> list[Path]:
    """The XML a manifest actually loads, which is the only XML that declares anything.

    Not `rglob("*.xml")`. A category record in a file no manifest names is loaded
    by nothing and declares nothing, so reading the whole tree would let an
    unreferenced file satisfy this gate. It would also walk the `tests/`
    fixtures, and those hold XML that is broken ON PURPOSE -- measured over the
    four repos, 5 of 10,219 XML files do not parse and every one is a fixture
    (a malformed Italian e-invoice, four empty Uruguayan responses), against
    0 of the 9,427 a manifest declares.

    A manifest naming a file it does not ship is skipped rather than raised on.
    That is an install failure and a different gate's subject, and the silence is
    bounded in the safe direction here: a missed declaration can only make this
    gate report MORE violations, never fewer.
    """
    found: list[Path] = []
    for manifest, declared in _manifests(roots):
        listed = list(declared.get("data") or []) + list(declared.get("demo") or [])
        for relative in listed:
            if not isinstance(relative, str) or not relative.endswith(".xml"):
                continue
            data_file = manifest.parent / relative
            if data_file.is_file():
                found.append(data_file)
    return found


def declared_categories(roots: list[Path]) -> dict[str, str | None]:
    """xml id -> the xml id of its declared parent, for every category a data file loads.

    The `base.` prefix is stripped: a record may be declared fully qualified inside
    base's own data file (`base.module_category_human_resources_referrals` is), and an
    id-keyed scan that does not normalise reports it as a different record.
    """
    declared: dict[str, str | None] = {}
    for data_file in declared_data_files(roots):
        try:
            tree = etree.parse(str(data_file))
        except etree.XMLSyntaxError as exc:
            raise SourceUnreadable(data_file, exc) from exc
        for record in tree.getroot().iter("record"):
            if record.get("model") != "ir.module.category":
                continue
            xmlid = (record.get("id") or "").split(".")[-1]
            if not xmlid:
                continue
            parent = record.find("./field[@name='parent_id']")
            ref = parent.get("ref") if parent is not None else None
            declared[xmlid] = ref.split(".")[-1] if ref else None
    return declared


def manifest_categories(roots: list[Path]) -> dict[str, tuple[str, Path]]:
    found: dict[str, tuple[str, Path]] = {}
    for manifest, declared in _manifests(roots):
        if declared.get("category"):
            found.setdefault(manifest.parent.name, (declared["category"], manifest))
    return found


def measure(roots: list[Path] | None = None) -> list[Violation]:
    roots = roots or scan_roots()
    if not roots:
        raise RuntimeError("no scannable root found")
    declared = declared_categories(roots)
    manifests = manifest_categories(roots)
    if not manifests:
        raise RuntimeError("no manifest declaring a category was found")
    if not declared:
        raise RuntimeError("no data file declaring an ir.module.category was found")
    violations: list[Violation] = []

    for module, (category, _manifest) in sorted(manifests.items()):
        root_segment = category.split("/")[0]
        xmlid = category_xmlid([root_segment])
        if xmlid not in declared:
            violations.append(
                Violation(
                    "root-declared",
                    module,
                    f"category {category!r} makes {root_segment!r} a top-level "
                    f"application; no data file declares {xmlid}",
                )
            )

    for xmlid, parent in sorted(declared.items()):
        if parent is not None:
            continue
        segments = xmlid.removeprefix("module_category_").split("_")
        for cut in range(len(segments) - 1, 0, -1):
            candidate = "module_category_" + "_".join(segments[:cut])
            if candidate in declared:
                violations.append(
                    Violation(
                        "path-implies-parent",
                        xmlid,
                        f"its path names {candidate}, which exists, but it declares "
                        f"no parent_id and so is a top-level application",
                    )
                )
                break
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when anything is reported"
    )
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of the whole workspace"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Module category vocabulary")
    print("=" * 72)
    for violation in found:
        print(f"  [{violation.rule}] {violation}")
    print("-" * 72)
    print(f"{len(found)} violation(s)")
    return 1 if (args.check and found) else 0


if __name__ == "__main__":
    raise SystemExit(main())
