"""Debug-mode import maps must never route specifiers through bridge shims.

Bridge shims read ``odoo.loader.modules``, which only esbuild production
bundles populate before shim evaluation — in ``?debug=assets`` mode the
shims evaluate against an empty map and every export binds ``undefined``.
Regression pin for the include-path defect fixed 2026-06-10 (hoot runner
failed all ~1311 tests because ``IMPORT_MAP_INCLUDES`` bridge entries
shadowed the parent's direct URLs; review doc 2026-06-09, §12).
"""

import json

from odoo.tests.common import TransactionCase


class TestDebugIncludeImportMap(TransactionCase):
    def test_debug_import_map_has_no_shim_entries(self):
        """The setup bundle's debug map resolves every spec to a direct URL."""
        IrQweb = self.env["ir.qweb"]
        pre, _post = IrQweb._get_native_module_nodes(
            "web.assets_unit_tests_setup", debug="assets"
        )
        import_map = {}
        for _tag, attrs in pre:
            if attrs.get("type") == "importmap":
                import_map = json.loads(attrs["text"])["imports"]
        if not import_map:
            self.skipTest("bundle resolved empty (web assets unavailable)")
        shim_valued = {
            spec: url
            for spec, url in import_map.items()
            if url.startswith(("/web/assets/esm/bridges/", "data:"))
        }
        self.assertFalse(
            shim_valued,
            "debug import map routes specs through odoo.loader.modules shims "
            f"(non-functional in debug): {dict(list(shim_valued.items())[:5])}",
        )
