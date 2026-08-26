"""Pure helpers behind `ir.qweb`'s asset rendering.

Everything here decides something about an asset node, a specifier or a chunk
of generated JavaScript, and none of it needs a database, a registry or a
request.  It lived on the `ir.qweb` model, where the module-level
``from odoo import models`` drags the whole ORM through the Tier-1 import stubs
(`odoo/_testing_bootstrap.py`) and no unit test can reach it -- so the branchy
parts, the ones that have actually been wrong, were only ever exercised through
a `TransactionCase`.

The neighbouring `ir_asset_paths.py` sets the precedent: import nothing from
`odoo` but `odoo.tools.assets.constants`, and a plain pytest suite can drive it.
See `odoo/tools/tests/test_asset_nodes.py`.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from odoo.tools.assets.constants import (
    SCRIPT_EXTENSIONS,
    STYLE_EXTENSIONS,
    TEMPLATE_EXTENSIONS,
)

__all__ = [
    "LOADER_SHIM_MARKER",
    "AssetNode",
    "bridge_external_specifiers",
    "combine_bundle_with_templates",
    "count_import_map_urls",
    "has_esm_test_satellites",
    "import_map_specs",
    "inline_module_node",
    "is_debug_assets",
    "is_hoot_test_specifier",
    "is_import_map_node",
    "is_loader_shim_node",
    "link_to_node",
    "prepare_register_native_modules_js",
]

AssetNode = tuple[str, dict[str, Any]]

LOADER_SHIM_MARKER = "data-loader-shim"

BRIDGE_URL_PREFIX = "/web/assets/esm/bridges/"

SOURCE_MAP_DIRECTIVE = "//# sourceMappingURL="


def is_debug_assets(debug: Any) -> bool:
    return isinstance(debug, str) and "assets" in debug


def has_esm_test_satellites(debug: Any, *, test_enable: bool) -> bool:
    # `isinstance` rather than `debug or ""`: the qweb compiler passes
    # `values.get("debug")`, which is `None` when absent, and callers in
    # `point_of_sale` pass `request and request.session.debug`, which is a
    # falsy *request* when there is none.  `"tests" in True` raises.
    return (isinstance(debug, str) and "tests" in debug) or test_enable


def inline_module_node(marker: str, bundle: str, code: str) -> AssetNode:
    return ("script", {"type": "module", marker: bundle, "text": code})


def is_import_map_node(node: AssetNode) -> bool:
    return node[0] == "script" and node[1].get("type") == "importmap"


def is_loader_shim_node(node: AssetNode) -> bool:
    return node[0] == "script" and LOADER_SHIM_MARKER in node[1]


def import_map_specs(nodes: Iterable[AssetNode]) -> frozenset[str]:
    return frozenset(
        spec
        for node in nodes
        if is_import_map_node(node)
        for spec in json.loads(node[1]["text"])["imports"]
    )


def count_import_map_urls(import_map: Mapping[str, str]) -> tuple[int, int, int]:
    """``(real urls, bridge shims, data: uris)`` -- a log-line breakdown."""
    bridges = sum(1 for v in import_map.values() if v.startswith(BRIDGE_URL_PREFIX))
    data = sum(1 for v in import_map.values() if v.startswith("data:"))
    return len(import_map) - bridges - data, bridges, data


def link_to_node(
    path: str,
    *,
    defer_load: bool = False,
    lazy_load: bool = False,
    media: str | None = None,
) -> AssetNode | None:
    """The node a bundle link renders as, or ``None`` for an extension that has
    no rendering (the caller logs and skips)."""
    if not path:
        return None
    ext = path.rsplit(".", maxsplit=1)[-1]

    if ext in SCRIPT_EXTENSIONS:
        attributes = {"type": "text/javascript"}
        if defer_load:
            attributes["defer"] = "defer"
        attributes["data-src" if lazy_load else "src"] = path
        return ("script", attributes)

    if ext in STYLE_EXTENSIONS:
        return (
            "link",
            {
                "type": "text/css",
                "rel": "stylesheet",
                "href": path,
                "media": media,
            },
        )

    if ext in TEMPLATE_EXTENSIONS:
        return (
            "script",
            {
                "type": "text/xml",
                "async": "async",
                "rel": "prefetch",
                "data-src": path,
            },
        )

    return None


def combine_bundle_with_templates(esbuild_code: str, esm_tpl: str) -> str:
    """Append the template registration, keeping any trailing sourcemap
    directive last -- a `//# sourceMappingURL=` line only counts where it is."""
    if not esm_tpl:
        return esbuild_code
    body = esbuild_code
    directive = ""
    tail = esbuild_code.rfind(SOURCE_MAP_DIRECTIVE)
    if tail != -1 and "\n" not in esbuild_code[tail:].rstrip("\n"):
        directive = esbuild_code[tail:].rstrip("\n")
        body = esbuild_code[:tail].rstrip("\n") + "\n"
    return (
        body
        + "/* ── Inlined templates registration ── */\n"
        + esm_tpl
        + ("\n" + directive + "\n" if directive else "")
    )


def is_hoot_test_specifier(specifier: str, *, by_directory: bool = True) -> bool:
    if "/tours/" in specifier:
        return False
    if ".test" in specifier or ".hoot" in specifier:
        return True
    return by_directory and ("/../tests/" in specifier or "/tests/" in specifier)


def prepare_register_native_modules_js(
    entries: Sequence[tuple[str, str]], var_prefix: str
) -> str:
    import_lines = []
    register_entries = []
    for index, (specifier, source) in enumerate(entries):
        var = f"{var_prefix}{index}"
        import_lines.append(f"import * as {var} from {json.dumps(source)};")
        register_entries.append(f"  {json.dumps(specifier)}: {var}")
    return (
        "\n".join(import_lines)
        + "\nodoo.loader.registerNativeModules({\n"
        + ",\n".join(register_entries)
        + "\n});\n"
    )


def bridge_external_specifiers(
    own_specifiers: Iterable[str], aliases: Mapping[str, str]
) -> set[str]:
    """External-lib specifiers the per-file bridge may eagerly import.

    The caller turns every specifier it is handed into a static
    ``import * as __mN from "<spec>"``, so this decides what the page
    *evaluates*, not merely what it can resolve -- resolution is already
    covered by seeding the import map with the whole external table.

    The rule is the one the esbuild entry follows: ``@odoo/owl``
    unconditionally, and an alias only when the bundle carries the file it
    aliases.  Handing over the whole external table instead evaluates the entire
    HOOT framework, plus pdfjs, chart.js and fullcalendar, on any page rendered
    through this branch -- and that branch is not just ``debug=assets``, an
    esbuild lock held by another worker used to fall into it too.
    """
    own = set(own_specifiers)
    return {"@odoo/owl"} | {
        alias for alias, aliased in aliases.items() if aliased in own
    }
