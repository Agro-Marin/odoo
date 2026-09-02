#!/usr/bin/env python3
"""Addon files that import werkzeug directly, as a ratchet.

`odoo.http` is the HTTP vocabulary addon code is written against: it exports
the request, the response, the route decorator and, since the exception
re-exports landed in `odoo/http/exceptions.py`, the HTTP exceptions a
controller raises -- `NotFound`, `Forbidden`, `BadRequest`, `Unauthorized`,
`HTTPException`, `abort` and the rest. Before that, 129 non-test addon files
(measured at c358454af87, the commit before the re-exports) imported werkzeug
themselves, mostly for those same names, so the framework's one
dependency on a WSGI toolkit was restated in every controller, and a name the
framework wanted to wrap (`HTTPException.get_response` is overridden in
`odoo/http/wrappers.py` for exactly that reason) could be bypassed by importing
the toolkit's own.

The unit is FILES, not statements: a file is either written in the framework's
vocabulary or in the toolkit's, and one statement converted out of three leaves
it in the toolkit's. Every `import werkzeug...` at any scope counts, including
`werkzeug.routing` and `werkzeug.datastructures` -- `ir.http` overrides that
build converters and a routing map legitimately keep those, which is why this
is a ratchet and not a hard zero. Test files are out of scope: a test that
builds a werkzeug environ is testing the toolkit's contract on purpose.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _count_gate
import _sources
from _repo_root import find_odoo_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ROOT = find_odoo_root(Path(__file__).resolve(), tool="werkzeug_in_addons")

BUNDLED_TREES = ("addons", "odoo/addons")

DEFAULT_ADDON = "addons"

GOVERNED_ADDONS = (DEFAULT_ADDON,)

TOOLKIT = "werkzeug"


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    return ROOT


@dataclass(frozen=True)
class ToolkitImport:
    file: str
    names: tuple[str, ...]

    def __str__(self) -> str:
        return f"  {self.file}  {', '.join(self.names)}"


def iter_source_files(src: Path | None = None) -> list[Path]:
    root = ROOT if src is None else src
    files: list[Path] = []
    for tree in BUNDLED_TREES:
        files.extend(_sources.iter_python_files(root / tree, include_polyglots=False))
    return sorted(files)


def _toolkit_names(tree: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(
                alias.name
                for alias in node.names
                if alias.name.split(".", 1)[0] == TOOLKIT
            )
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if module.split(".", 1)[0] == TOOLKIT:
                names.extend(f"{module}.{alias.name}" for alias in node.names)
    return tuple(dict.fromkeys(names))


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[ToolkitImport]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            root = ROOT if src is None else src
            raise RuntimeError(
                f"no Python sources under {' or '.join(str(root / t) for t in BUNDLED_TREES)}"
                f" -- the scan found nothing, which is not the same as finding "
                f"nothing wrong"
            )
    found: list[ToolkitImport] = []
    for path in files:
        tree = _ast_cache.parse_file(path)
        names = _toolkit_names(tree)
        if names:
            found.append(ToolkitImport(_sources.display(path, ROOT), names))
    found.sort(key=lambda item: item.file)
    return found


def _summary(found: list[ToolkitImport]) -> str:
    tally = Counter(name for item in found for name in item.names)
    top = ", ".join(f"{name} {count}" for name, count in tally.most_common(8))
    return f"  by name: {top}"


def main(argv: list[str] | None = None) -> int:
    return _count_gate.run(
        argv,
        script="werkzeug_in_addons.py",
        gate="werkzeug_in_addons",
        headline="Addon files importing werkzeug instead of odoo.http ({where})",
        unit="file(s)",
        default_addon=DEFAULT_ADDON,
        everything=DEFAULT_ADDON,
        siblings=(),
        governed=GOVERNED_ADDONS,
        addon_src=addon_src,
        measure=measure,
        root_name=ROOT.name,
        summary=_summary,
        where_for=lambda addon: "addons/ and odoo/addons/",
        addon_help=(
            f"what to measure: {DEFAULT_ADDON} (default, and the only scope) is "
            f"the two bundled trees, addons/ and odoo/addons/, as one number"
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
