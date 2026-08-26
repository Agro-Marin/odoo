"""Installable modules whose declared dependencies are marked uninstallable.

Marking a module ``installable: False`` is not a local edit. Every module that
depends on it becomes unreachable, and Odoo does not report that as an error --
the module graph drops the dependent with one WARNING and carries on::

    module l10n_in_reports: some depends are not loaded
    (account_invoice_extract), skipped

The dependent is then left committed in state ``to install`` and ``odoo-bin``
exits 0. Nothing downstream distinguishes that from a module nobody asked for:
no test fails, no lane goes red, and the module simply never runs again. Indian
GST reporting sat in that state from the day ``account_invoice_extract`` was
disabled until 2026-08-24, discovered by reading manifests rather than by any
gate.

**Why this fork accumulates the shape.** Replacing an upstream module is a
standing practice here -- ``document_extract_account`` replaced
``account_invoice_extract``, and marking the replaced module uninstallable
rather than merely uninstalling it is what makes the choice hold against the
next module update (`CLAUDE.md` §3). Every such replacement puts the dependents
of the disabled module one edit away from silent death, and the edit that would
save them is in a different module from the one being changed.

**What is checked.** For every module whose manifest does not say
``installable: False``, every name in its ``depends`` that resolves to a module
*within the scanned roots* must not itself be marked ``installable: False``. A
dependency that resolves to nothing in scope is **not** an offence: the scanned
roots are rarely the whole addons path, a sibling repo run sees only its own
tree plus what it is given, and `tools.config.addons_data_dir` can supply a
module at runtime that no checkout contains. Reporting those would make the gate
argue with its user about scope rather than about the rule, and a gate that
over-counts is one people learn to argue with instead of fix.

That narrowness is the point: both modules are on disk, one says outright that
it cannot be installed, and the other says it needs it. There is no reading of
that pair which is correct.

**A contract, not a ratchet.** The count is zero and the fix for any occurrence
is small -- drop the dependency, port what was used, or mark the dependent
uninstallable too. A floor would bank the next silent breakage for as long as
someone left it.

**Scope.** Defaults to the ``odoo`` checkout because that is what CI checks out.
The defect this was written for was entirely inside ``enterprise``, one sibling
depending on another, which the default scope cannot see -- so the sibling repos
run it with ``--roots`` from their own cross-repo lane, the same arrangement
`CLAUDE.md` §9.4 describes for the naming gate.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _repo_root import find_odoo_root

ADR = "0062"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="module_depends_installable")

MANIFEST = "__manifest__.py"


@dataclass(frozen=True)
class Module:
    name: str
    path: str
    installable: bool
    depends: tuple[str, ...]


@dataclass(frozen=True)
class Offence:
    module: str
    module_path: str
    dependency: str
    dependency_path: str

    def __str__(self) -> str:
        return (
            f"{self.module_path}  depends on `{self.dependency}`, "
            f"which is marked uninstallable ({self.dependency_path})"
        )


def _read_manifest(path: Path) -> dict | None:
    try:
        value = ast.literal_eval(path.read_text(encoding="utf-8"))
    except SyntaxError, ValueError, UnicodeDecodeError:
        return None
    return value if isinstance(value, dict) else None


def collect_modules(roots: list[Path]) -> dict[str, Module]:
    """Every module under ``roots``, last root winning on a name collision.

    Collisions are real: ``addons_path`` order decides which of two modules with
    one name is served, and this mirrors it rather than reporting a conflict the
    server resolves silently.
    """
    modules: dict[str, Module] = {}
    for root in roots:
        for manifest in sorted(root.glob(f"*/{MANIFEST}")):
            data = _read_manifest(manifest)
            if data is None:
                continue
            directory = manifest.parent
            depends = data.get("depends") or []
            modules[directory.name] = Module(
                name=directory.name,
                path=str(directory),
                installable=bool(data.get("installable", True)),
                depends=tuple(d for d in depends if isinstance(d, str)),
            )
    return modules


def default_roots() -> list[Path]:
    return [ROOT / "addons", ROOT / "odoo" / "addons"]


def measure(roots: list[Path] | None = None) -> list[Offence]:
    roots = roots or default_roots()
    missing = [root for root in roots if not root.is_dir()]
    if missing:
        raise RuntimeError(
            "no such directory: " + ", ".join(str(root) for root in missing)
        )

    modules = collect_modules(roots)
    if not modules:
        # Zero offences over a tree with no manifests is the number a clean tree
        # reports, and neither the gate nor a reader can tell them apart.
        raise RuntimeError(
            "no `__manifest__.py` under "
            + ", ".join(str(root) for root in roots)
            + " — refusing to report a result measured over nothing"
        )

    offences = [
        Offence(
            module=module.name,
            module_path=module.path,
            dependency=dependency,
            dependency_path=modules[dependency].path,
        )
        for module in modules.values()
        if module.installable
        for dependency in module.depends
        if dependency in modules and not modules[dependency].installable
    ]
    return sorted(offences, key=lambda o: (o.module_path, o.dependency))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero if any offence is found"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of the odoo checkout"
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
        print(json.dumps([asdict(o) for o in found], indent=2))
        return 0

    print("Installable modules depending on an uninstallable one")
    print("=" * 72)
    for offence in found:
        print(f"  {offence}")
    if not found:
        print("  none")
    print("-" * 72)
    print(f"\n{len(found)} unreachable module(s)")
    if found:
        print(
            "\nEach of these is skipped by the module graph with a WARNING and "
            "left in\nstate `to install`, while odoo-bin exits 0. Resolve each by "
            "what it uses:\ndrop the dependency, port what it needed, or mark it "
            "uninstallable too."
        )

    if args.check and found:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
