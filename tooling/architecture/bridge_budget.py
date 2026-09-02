#!/usr/bin/env python3
"""Bridge modules that do not pay for their directory.

A bridge is a module whose manifest sets `auto_install` (True, or a list of
the dependencies that trigger it) and names two or more `depends`: it exists
so that installing its parents also installs the glue between them. That is a
legitimate shape when the glue is real. When the glue is a handful of lines,
the bridge is a directory, a manifest, a security file and a registry row for
nothing -- every one of its parents is already in every install closure the
bridge appears in, so the same lines folded into whichever parent already
depends on the others cost no dependency the graph did not already carry.

This gate counts bridges whose Python is under the budget. One is counted when
all three hold:

  1. `installable` is not False, and `auto_install` is True or a non-empty
     list -- True makes every entry of `depends` a trigger, a list names the
     triggers itself;
  2. there are two or more triggers. A module one parent triggers on its own
     (`"auto_install": ["account"]` with `countries`, the country-pack shape)
     is a plugin of that parent and not a bridge: there is no second parent
     to fold it towards, and folding a country pack into `account` is not a
     fold anyone wants;
  3. its pyLOC is below MAX_PYLOC (60).

pyLOC is measured exactly as follows: every `*.py` under the module directory
is read, except `__manifest__.py` (the declaration, not the module's code),
any file under a `tests/` or `migrations/` directory or named `test_*.py`, and
anything under `__pycache__` or `node_modules`; of those files' lines, one is
counted when it is not blank and its first non-whitespace character is not
`#`. Docstrings count -- they are lines the module ships and a bridge under
budget with a long docstring is still under budget for what it does.
Data files, views, assets and the security CSV are deliberately not counted:
they are what a fold moves, and their size does not change whether the bridge
carries any logic that had nowhere else to live.

The number is per addons tree. The default scope is this repository's two
bundled trees, `odoo/addons` and `addons`, as one number; a sibling checkout
measures its own tree. A fold is a decision per module, taken by reading the
list this gate prints bare, never by the count alone: a bridge that is small
because it is a stub for a feature still landing, or that exists to keep an
OPL-1 dependency out of an LGPL-3 parent, stays a bridge, and the floor is
where that judgement is recorded when it is made.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _count_gate
import _sources
from _repo_root import find_odoo_root, sibling_repos_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="bridge_budget")

DEFAULT_ADDON = "addons"

SIBLING_SCOPES = ("enterprise", "agromarin")

GOVERNED_ADDONS = (DEFAULT_ADDON, *SIBLING_SCOPES)

MANIFEST = "__manifest__.py"

MAX_PYLOC = 60

MIN_TRIGGERS = 2

UNCOUNTED_DIRS = frozenset({"migrations"})


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return ROOT
    return sibling_repos_root(ROOT) / addon


def addon_trees(src: Path) -> list[Path]:
    if (src / "odoo-bin").is_file():
        return [
            tree for tree in (src / "odoo" / "addons", src / "addons") if tree.is_dir()
        ]
    return [src] if src.is_dir() else []


@dataclass(frozen=True)
class Bridge:
    tree: str
    module: str
    pyloc: int
    auto_install: str
    depends: tuple[str, ...]

    def __str__(self) -> str:
        return (
            f"  {self.pyloc:3d} pyLOC  {self.tree}/{self.module}"
            f"  auto_install={self.auto_install}"
            f"  depends={', '.join(self.depends)}"
        )


def _read_manifest(path: Path) -> dict | None:
    try:
        value = ast.literal_eval(path.read_text(encoding="utf-8"))
    except SyntaxError, ValueError, UnicodeDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _is_counted_file(path: Path, module_dir: Path) -> bool:
    if path.name == MANIFEST:
        return False
    relative = path.relative_to(module_dir)
    if _sources.SKIP_DIRS & set(relative.parts):
        return False
    if UNCOUNTED_DIRS & set(relative.parts):
        return False
    return not _sources.is_test_path(relative)


def _count_lines(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(
        1
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    )


def pyloc(module_dir: Path) -> int:
    return sum(
        _count_lines(path)
        for path in module_dir.rglob("*.py")
        if _is_counted_file(path, module_dir)
    )


def _depends(manifest: dict) -> tuple[str, ...]:
    return tuple(d for d in manifest.get("depends") or [] if isinstance(d, str))


def _triggers(manifest: dict) -> tuple[str, ...]:
    auto_install = manifest.get("auto_install", False)
    if isinstance(auto_install, (list, tuple)):
        return tuple(t for t in auto_install if isinstance(t, str))
    return _depends(manifest) if auto_install is True else ()


def _is_bridge_manifest(manifest: dict) -> bool:
    if manifest.get("installable", True) is False:
        return False
    return len(_triggers(manifest)) >= MIN_TRIGGERS


def _auto_install_display(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


def measure(src: Path | None = None) -> list[Bridge]:
    src = ROOT if src is None else src
    trees = addon_trees(src)
    manifests = [
        (tree, path) for tree in trees for path in sorted(tree.glob(f"*/{MANIFEST}"))
    ]
    if not manifests:
        raise RuntimeError(
            f"no `{MANIFEST}` under {src} -- the scan found no module at all, "
            f"which is not the same as finding no bridge"
        )
    bundled = src == ROOT
    found: list[Bridge] = []
    for tree, path in manifests:
        manifest = _read_manifest(path)
        if manifest is None or not _is_bridge_manifest(manifest):
            continue
        module_dir = path.parent
        lines = pyloc(module_dir)
        if lines >= MAX_PYLOC:
            continue
        found.append(
            Bridge(
                tree=tree.relative_to(ROOT).as_posix() if bundled else tree.name,
                module=module_dir.name,
                pyloc=lines,
                auto_install=_auto_install_display(manifest["auto_install"]),
                depends=_depends(manifest),
            )
        )
    found.sort(key=lambda b: (b.tree, b.module))
    return found


def _summary(found: list[Bridge]) -> str:
    per_tree: dict[str, int] = {}
    for bridge in found:
        per_tree[bridge.tree] = per_tree.get(bridge.tree, 0) + 1
    trees = "   ".join(f"{tree}: {n}" for tree, n in sorted(per_tree.items()))
    zero = sum(1 for b in found if b.pyloc == 0)
    return f"  per tree: {trees}\n  with no Python at all: {zero}"


def main(argv: list[str] | None = None) -> int:
    return _count_gate.run(
        argv,
        script="bridge_budget.py",
        gate="bridge_budget",
        headline=(
            f"Auto-installed bridges with {MIN_TRIGGERS}+ triggers and under "
            f"{MAX_PYLOC} pyLOC ({{where}})"
        ),
        unit="bridge(s) under budget",
        default_addon=DEFAULT_ADDON,
        everything=DEFAULT_ADDON,
        siblings=SIBLING_SCOPES,
        governed=GOVERNED_ADDONS,
        addon_src=addon_src,
        measure=measure,
        root_name=ROOT.name,
        summary=_summary,
        where_for=lambda addon: (
            "odoo/addons/ and addons/ as one number"
            if addon == DEFAULT_ADDON
            else f"{addon}/"
        ),
        description=__doc__,
        addon_help=(
            f"what to measure: {DEFAULT_ADDON} (default) is this repository's two "
            f"bundled trees, odoo/addons and addons, as one number, and "
            f"{' and '.join(SIBLING_SCOPES)} are sibling checkouts"
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
