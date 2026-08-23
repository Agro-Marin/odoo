#!/usr/bin/env python3
"""Every name imported from a façade module must exist in it.

``odoo/tools`` re-exports on purpose: ``odoo.tools.misc`` is imported by
hundreds of files and forwards names that live in ``odoo.libs``. That makes it a
contract with no enforcement -- ``__all__`` states one surface, the module
exposes another, and an addon importing a name that is in neither fails at
*module import time*, which means at install, in one addon, on whoever installs
it next.

That is not hypothetical. An AST sweep of the four repositories found exactly
one such import, and nothing in CI could see it:

    enterprise/l10n_au_hr_payroll_api/models/l10n_au_superstream.py
        from odoo.tools.misc import groupby, itemgetter   # misc has no itemgetter

This gate resolves every ``from <facade> import name`` statically -- no import
of the addon, so an addon with unrelated breakage elsewhere is still checked --
and reports two things:

* **missing** -- the name is imported and does not exist. This fails the gate.
* **undeclared** -- the name exists and is absent from ``__all__``. Reported,
  never failed: the façades deliberately forward more than they declare, and
  turning that into an error would be a large mechanical change dressed up as a
  bug report. The count is printed so the drift stays visible.

Run over sibling repositories with ``--roots``, the way
``naming_vocabulary.py`` does, since a sibling's CI checks out this repo beside
itself (``.github/workflows/architecture.yml``, "Architecture Boundaries").
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0004"

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="facade_surface_check")

#: The modules whose surface is a contract with the rest of the codebase.
FACADES: tuple[str, ...] = (
    "odoo.tools",
    "odoo.tools.misc",
    "odoo.tools.mail",
    "odoo.tools.date_utils",
    "odoo.tools.safe_eval",
    "odoo.tools.xml_utils",
    "odoo.tools.translate",
    "odoo.tools.image",
    "odoo.tools.json",
)

#: Below this, the scan found nothing and must say so rather than pass.
_MIN_SCANNED = 100

SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", "static"}
)


@dataclass(frozen=True)
class Finding:
    path: str
    lineno: int
    facade: str
    name: str


@dataclass
class Report:
    scanned: int = 0
    facades: int = 0
    missing: tuple[Finding, ...] = ()
    undeclared: tuple[Finding, ...] = ()

    #: Set when the scan found nothing to measure.
    vacuous: str = ""

    @property
    def ok(self) -> bool:
        return not self.missing and not self.vacuous


def _module_path(dotted: str) -> Path | None:
    relative = Path(*dotted.split("."))
    for candidate in (
        REPO_ROOT / relative.with_suffix(".py"),
        REPO_ROOT / relative / "__init__.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def _submodule_names(dotted: str) -> set[str]:
    """Submodules of a package façade.

    ``from odoo.tools import date_utils`` binds a *module*, which never appears
    in the package's ``__init__`` and is a perfectly ordinary import. Treating
    those as missing was this gate's first false-positive class -- 91 of them,
    all legal.
    """
    package = REPO_ROOT / Path(*dotted.split(".")) / "__init__.py"
    if not package.is_file():
        return set()
    return {
        child.stem if child.suffix == ".py" else child.name
        for child in package.parent.iterdir()
        if (child.suffix == ".py" and child.stem != "__init__")
        or (child.is_dir() and (child / "__init__.py").is_file())
    }


def _bound_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """The names a module binds at top level, and its ``__all__``.

    Read statically. Importing the façade would drag in the whole ORM, and a
    gate that needs a working runtime to check a contract is a gate that stops
    working exactly when the contract is broken.
    """
    bound: set[str] = set()
    declared: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            bound.update(a.asname or a.name for a in node.names if a.name != "*")
        elif isinstance(node, ast.Import):
            bound.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                bound.add(target.id)
                if target.id == "__all__" and isinstance(
                    node.value, (ast.List, ast.Tuple, ast.Set)
                ):
                    declared.update(
                        e.value
                        for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)
        elif isinstance(node, (ast.If, ast.Try)):
            # `if TYPE_CHECKING:` and `try: import x except ImportError:` both
            # bind names a caller can legitimately import.
            for inner in ast.walk(node):
                if isinstance(inner, ast.ImportFrom):
                    bound.update(
                        a.asname or a.name for a in inner.names if a.name != "*"
                    )
                elif isinstance(inner, ast.Import):
                    bound.update(a.asname or a.name.split(".")[0] for a in inner.names)
                elif isinstance(inner, ast.Assign):
                    bound.update(t.id for t in inner.targets if isinstance(t, ast.Name))
                elif isinstance(
                    inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    bound.add(inner.name)
    return bound, declared


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if SKIP_DIRS.isdisjoint(path.parts):
            yield path


def check(roots: tuple[Path, ...] = (REPO_ROOT,)) -> Report:
    surfaces: dict[str, tuple[set[str], set[str]]] = {}
    for facade in FACADES:
        path = _module_path(facade)
        if path is None:
            continue
        bound, declared = _bound_names(ast.parse(path.read_text(encoding="utf-8")))
        surfaces[facade] = (bound | _submodule_names(facade), declared)

    missing: list[Finding] = []
    undeclared: list[Finding] = []
    scanned = 0
    for root in roots:
        for path in _iter_python_files(root):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            scanned += 1
            relative = path.relative_to(root.parent if root.name else root)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level:
                    continue
                surface = surfaces.get(node.module or "")
                if surface is None:
                    continue
                bound, declared = surface
                # The façade module checking itself proves nothing.
                if (node.module or "").replace(".", "/") in str(path):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    finding = Finding(
                        str(relative), node.lineno, node.module or "", alias.name
                    )
                    if alias.name not in bound:
                        missing.append(finding)
                    elif declared and alias.name not in declared:
                        undeclared.append(finding)

    # A gate that measured nothing reports a clean zero, which is
    # indistinguishable from a gate that measured everything and found nothing.
    # Refuse instead: an emptied tree is a broken probe, not a passing repo.
    vacuous = ""
    if not surfaces:
        vacuous = "no façade module was found; the checkout is not intact"
    elif scanned < _MIN_SCANNED:
        vacuous = (
            f"only {scanned} Python files scanned (expected at least "
            f"{_MIN_SCANNED}); the scan roots are empty or wrong"
        )

    return Report(
        scanned=scanned,
        facades=len(surfaces),
        missing=tuple(missing),
        undeclared=tuple(undeclared),
        vacuous=vacuous,
    )


def _render(report: Report) -> str:
    lines = [
        "Façade surface",
        "=" * 60,
        f"  façades checked : {report.facades}",
        f"  files scanned   : {report.scanned}",
        f"  missing names   : {len(report.missing)}",
        f"  undeclared      : {len(report.undeclared)} (reported, not failed)",
        "",
    ]
    lines.extend(
        f"  MISSING {finding.path}:{finding.lineno}: "
        f"{finding.facade} does not export {finding.name!r}"
        for finding in report.missing
    )
    if report.vacuous:
        lines.append("")
        lines.append(f"FAILED: {report.vacuous}")
    elif report.missing:
        lines.append("")
        lines.append(
            "FAILED: an import names something the façade does not export. "
            "That addon raises ImportError at install."
        )
    else:
        lines.append("Every name imported from a façade exists in it. ✓")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=None,
        help="trees to scan (default: this repository)",
    )
    parser.add_argument(
        "--show-undeclared",
        action="store_true",
        help="list names imported from a façade but absent from its __all__",
    )
    args = parser.parse_args(argv)

    roots = tuple(Path(r).resolve() for r in args.roots) if args.roots else (REPO_ROOT,)
    report = check(roots)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "vacuous": report.vacuous,
                    "scanned": report.scanned,
                    "missing": [
                        {
                            "path": f.path,
                            "line": f.lineno,
                            "facade": f.facade,
                            "name": f.name,
                        }
                        for f in report.missing
                    ],
                    "undeclared": len(report.undeclared),
                },
                indent=2,
            )
        )
    else:
        print(_render(report))
        if args.show_undeclared:
            print()
            for finding in report.undeclared:
                print(
                    f"  undeclared {finding.path}:{finding.lineno}: "
                    f"{finding.facade}.{finding.name} is not in __all__"
                )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
