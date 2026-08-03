"""Enforces the Feature-Sliced Design layering of ``addons/web/static/src/``.

``machine_doc_v1/DIRECTORY_MAP.md`` assigns every source directory one of the
layers ``shared -> entities -> features -> widgets -> pages``.  The point of
that ordering is that it is one-way: a directory may import from its own layer
or a lower one, never from a higher one.  An upward import is what turns the
tree into a cycle -- ``core/`` reaching into ``views/`` makes the shared layer
unusable without the whole view stack, and every consumer of ``core/`` pays for
it.

This invariant used to be checked by ``static/tests/modules/dependencies.test.js``,
which read ``odoo.loader.factories[module].deps``.  That map was populated by
the AMD ``define()`` path; post-ESM only ``odoo.loader.modules`` is maintained,
so the test crashed on its first iteration and was left skipped -- the layering
was documented and unenforced.  Nothing about the rule needs the loader: the
imports are in the files.  Reading them here also drops the browser round-trip,
so the check runs in the unit lane.
"""

import re
from pathlib import Path

from odoo.tests.common import BaseCase, tagged

WEB_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = WEB_ROOT / "static" / "src"
DIRECTORY_MAP = WEB_ROOT / "machine_doc_v1" / "DIRECTORY_MAP.md"

LAYER_ORDER = {
    "shared": 0,
    "entities": 1,
    "features": 2,
    "widgets": 3,
    "pages": 4,
}

_MAP_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(\w+)\s*\|", re.MULTILINE)

_IMPORT_RE = re.compile(
    r"""(?:^|\s)(?:from|import)\s*\(?\s*["']([^"']+)["']""",
    re.MULTILINE,
)

#: Below these the walk is not measuring the codebase any more, it is measuring
#: a broken parse -- a renamed table column or a moved ``src`` reads as "no
#: violations" otherwise.
MIN_MAPPED_DIRECTORIES = 100
MIN_CHECKED_IMPORTS = 1000


def _layer_map():
    """``{directory: layer}`` for every row of DIRECTORY_MAP.md's table."""
    rows = _MAP_ROW_RE.findall(DIRECTORY_MAP.read_text(encoding="utf-8"))
    return {
        directory.rstrip("/"): layer
        for directory, layer in rows
        if layer in LAYER_ORDER
    }


def _layer_of(rel_path, layer_map):
    """The layer owning ``rel_path``, walking up to the nearest mapped parent."""
    parts = rel_path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        directory = "/".join(parts[:i])
        if directory in layer_map:
            return layer_map[directory]
    return None


def _imported_path(spec, source):
    """``spec`` as a path relative to ``static/src``, or ``None`` if outside it."""
    if spec.startswith("@web/"):
        return spec[len("@web/") :].removesuffix(".js")
    if spec.startswith("."):
        try:
            resolved = (source.parent / spec).resolve().relative_to(SRC_ROOT)
        except ValueError, OSError:
            return None
        return resolved.as_posix().removesuffix(".js")
    return None


@tagged("web_unit", "web_layering")
class TestModuleLayering(BaseCase):
    def test_no_upward_layer_imports(self):
        layer_map = _layer_map()
        self.assertGreaterEqual(
            len(layer_map),
            MIN_MAPPED_DIRECTORIES,
            f"only {len(layer_map)} directories carry a layer in "
            f"{DIRECTORY_MAP.name}; the table format probably changed",
        )

        checked = 0
        violations = []
        for source in sorted(SRC_ROOT.rglob("*.js")):
            rel = source.relative_to(SRC_ROOT).as_posix()
            importer_layer = _layer_of(rel, layer_map)
            if importer_layer is None:
                continue
            for spec in _IMPORT_RE.findall(source.read_text(encoding="utf-8")):
                target = _imported_path(spec, source)
                if target is None:
                    continue
                imported_layer = _layer_of(target, layer_map)
                if imported_layer is None:
                    continue
                checked += 1
                if LAYER_ORDER[imported_layer] > LAYER_ORDER[importer_layer]:
                    violations.append(
                        f"{rel} [{importer_layer}] imports {spec} [{imported_layer}]"
                    )

        self.assertGreaterEqual(
            checked,
            MIN_CHECKED_IMPORTS,
            f"only {checked} imports resolved into static/src; the walk is not "
            "reaching the sources it is meant to check",
        )
        self.assertFalse(
            violations,
            "Imports pointing up the Feature-Sliced layer order "
            "(shared -> entities -> features -> widgets -> pages):\n- "
            + "\n- ".join(violations),
        )
