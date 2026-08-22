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

MIN_MAPPED_DIRECTORIES = 100
MIN_CHECKED_IMPORTS = 1000


def _layer_map():
    rows = _MAP_ROW_RE.findall(DIRECTORY_MAP.read_text(encoding="utf-8"))
    return {
        directory.rstrip("/"): layer
        for directory, layer in rows
        if layer in LAYER_ORDER
    }


def _layer_of(rel_path, layer_map):
    parts = rel_path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        directory = "/".join(parts[:i])
        if directory in layer_map:
            return layer_map[directory]
    return None


def _imported_path(spec, source):
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
