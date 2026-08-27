import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools.assets.esbuild import EXTERNAL_LIB_ALIASES
from odoo.tools.assets.esm_bridges import BridgeShimManager
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_path

from .common import _Mod, make_cursor_readonly
from odoo.addons.base.models.assetsbundle import AssetsBundle


class TestFallbackBridgeExternals(TransactionCase):
    """The per-file bridge must not evaluate libraries the bundle never uses.

    ``_get_esm_nodes_debug`` renders ``debug=assets`` pages *and* every page
    whose esbuild compile declined -- an unavailable build lock is enough
    (``odoo.assets.fallback: event=lock_unavailable``).  Its bridge turns each
    specifier into a static import, so anything listed here is code the page
    runs, and the esbuild entry is the reference for what that list may hold.
    """

    def test_an_unrelated_bundle_bridges_owl_and_nothing_else(self):
        IrQweb = self.env["ir.qweb"]
        specs = IrQweb._bridge_external_specifiers(
            {"import_map": {"@web/env": "/web/static/src/env.js"}}
        )
        self.assertEqual(specs, {"@odoo/owl"})

    def test_a_bundle_carrying_hoot_bridges_its_aliases(self):
        IrQweb = self.env["ir.qweb"]
        specs = IrQweb._bridge_external_specifiers(
            {
                "import_map": {
                    alias_target: f"/web/static/lib/{alias_target}.js"
                    for alias_target in EXTERNAL_LIB_ALIASES.values()
                }
            }
        )
        self.assertEqual(specs, {"@odoo/owl", *EXTERNAL_LIB_ALIASES})

    def test_the_app_bundles_do_not_bridge_the_test_framework(self):
        IrQweb = self.env["ir.qweb"]
        params = self.env["ir.asset"]._prepare_assets_params()
        for bundle in ("web.assets_web", "web.assets_frontend_lazy"):
            asset_bundle = IrQweb._get_asset_bundle(
                bundle,
                js=True,
                css=False,
                debug_assets=True,
                assets_params=params,
            )
            native_data = asset_bundle.get_native_module_data()
            if not native_data["import_map"]:
                self.skipTest(f"{bundle} resolved empty (web assets unavailable)")
            self.assertEqual(
                IrQweb._bridge_external_specifiers(native_data),
                {"@odoo/owl"},
                f"{bundle} would evaluate the HOOT test framework on every page "
                "served through the per-file fallback",
            )


class BridgeRequestBoundCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch("odoo.http.request", new=SimpleNamespace()))


class TestBridgeShimLiterals(TransactionCase):
    NAMES = {"alpha", "class", "default", "a-b"}

    def test_shim_specifier_is_json_quoted(self):
        shim, is_fallback = AssetsBundle._bridge_shim_source(
            "@web/core/x", set(), {"alpha"}, True
        )
        self.assertIn('odoo.loader.modules.get("@web/core/x");', shim)
        self.assertNotIn("get('@web/core/x')", shim)
        self.assertIn("_e0 = _m.alpha;", shim)
        self.assertIn("_e0 as alpha", shim)
        self.assertNotIn("export default", shim)
        self.assertFalse(is_fallback)

    def test_a_reserved_word_survives_as_an_alias(self):
        shim, _ = AssetsBundle._bridge_shim_source(
            "@web/core/x", set(), self.NAMES, False
        )

        self.assertIn(" as class", shim)
        self.assertNotIn("const class", shim)
        self.assertNotIn("a-b", shim)
        self.assertNotIn("= _m.default;", shim)

    @unittest.skipUnless(shutil.which("node"), "node binary not available")
    def test_the_two_generators_agree(self):
        bridge_js = file_path("web/static/src/core/module_bridge.js")
        names = sorted(self.NAMES)
        script = (
            f"import {{ buildBridgeModuleSource }} from {json.dumps(bridge_js)};\n"
            f"process.stdout.write("
            f"buildBridgeModuleSource({json.dumps('@web/core/x')}, "
            f"{json.dumps(names)}));\n"
        )

        proc = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        python_shim, _ = AssetsBundle._bridge_shim_source(
            "@web/core/x", set(), self.NAMES, False
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, python_shim)


class TestBridgeHashWidth(BridgeRequestBoundCase):
    def test_bridge_url_hash_is_32_hex(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ):
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/test_hash": "export default 1;"}
            )
        basename = urls["@web/test_hash"].rsplit("/", 1)[-1]
        self.assertRegex(basename, r"^[0-9a-f]{32}\.js$")


class TestBridgeReadonlyEscalation(BridgeRequestBoundCase):
    def _make_cursor_readonly(self):
        make_cursor_readonly(self)

    def test_escalation_success_returns_canonical_urls(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        self._make_cursor_readonly()
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ) as escalate:
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/ro_test": "export default 1;"}
            )
        escalate.assert_called_once()
        (to_create,) = escalate.call_args.args
        self.assertEqual(len(to_create), 1)
        self.assertTrue(urls["@web/ro_test"].startswith("/web/assets/esm/bridges/"))

    def test_escalation_failure_falls_back_to_data_uris(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        self._make_cursor_readonly()
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=False
        ) as escalate:
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/ro_test2": "export default 2;"}
            )
        escalate.assert_called_once()
        self.assertTrue(urls["@web/ro_test2"].startswith("data:text/javascript"))


class TestBridgePersistenceDecoupled(BridgeRequestBoundCase):
    def test_writable_cursor_routes_through_rw_cursor(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        self.assertFalse(
            self.env.cr.readonly, "precondition: the request cursor is writable"
        )
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ) as escalate:
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/decoupled": "export const decoupled = 1;"}
            )
        escalate.assert_called_once()
        url = urls["@web/decoupled"]
        self.assertTrue(
            url.startswith("/web/assets/esm/bridges/"),
            "a successful out-of-band persist yields a canonical URL",
        )
        self.assertFalse(
            url.startswith("data:"), "the writable path must not inline data: URIs"
        )

    def test_unwritable_primary_falls_back_to_data_uris(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=False
        ):
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/degraded": "export const degraded = 2;"}
            )
        self.assertTrue(
            urls["@web/degraded"].startswith("data:text/javascript"),
            "data: URIs are reserved for a genuinely unwritable primary",
        )


class TestBridgeNoRequestPersistence(TransactionCase):
    def test_no_request_persists_on_current_cursor(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor"
        ) as escalate:
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/no_request": "export const no_request = 3;"}
            )
        escalate.assert_not_called()
        url = urls["@web/no_request"]
        self.assertTrue(
            url.startswith("/web/assets/esm/bridges/"),
            "current-cursor persistence still yields canonical URLs",
        )
        attachment = self.env["ir.attachment"].sudo().search([("url", "=", url)])
        self.assertTrue(
            attachment,
            "the bridge row must be visible on the current cursor",
        )


class TestBridgeShimSources(TransactionCase):
    def _manager(self):
        return AssetsBundle("web.assets_web", [], env=self.env)._bridges

    def test_a_shim_re_exports_the_real_module_names(self):
        shims = self._manager().build_shim_sources({"@web/core/registry"})
        shim = shims["@web/core/registry"]
        self.assertIn('odoo.loader.modules.get("@web/core/registry")', shim)
        self.assertRegex(
            shim,
            r"(_e\d+) = _m\.registry;",
            "the shim must bind each name to a local before re-exporting it",
        )
        self.assertRegex(shim, r"_e\d+ as registry\b")

    def test_no_specifiers_means_no_work(self):
        self.assertEqual(self._manager().build_shim_sources(set()), {})

    def test_discovery_reads_the_import_kind_not_just_the_specifier(self):
        modules = [
            _Mod("@a/one", 'import def from "@web/core/a";\n'),
            _Mod("@a/two", 'import * as ns from "@web/core/b";\n'),
            _Mod("@a/three", 'import { named } from "@web/core/c";\n'),
        ]
        discovered, ext_seen = self._manager()._discover_bridge_specifiers(
            set(), set(), modules=modules
        )
        self.assertEqual(discovered["@web/core/a"], {"__default__"})
        self.assertEqual(discovered["@web/core/b"], {"__star__"})
        self.assertEqual(discovered["@web/core/c"], set())
        self.assertEqual(ext_seen, set())

    def test_a_bundle_member_is_not_bridged_to_itself(self):
        modules = [_Mod("@a/one", 'import { x } from "@a/two";\n')]
        discovered, _ext = self._manager()._discover_bridge_specifiers(
            {"@a/two"}, set(), modules=modules
        )
        self.assertNotIn("@a/two", discovered)

    def test_an_external_library_is_recorded_but_not_bridged(self):
        modules = [_Mod("@a/one", 'import { App } from "@odoo/owl";\n')]
        discovered, ext_seen = self._manager()._discover_bridge_specifiers(
            set(), {"@odoo/owl"}, modules=modules
        )
        self.assertNotIn("@odoo/owl", discovered)
        self.assertEqual(ext_seen, {"@odoo/owl"})


class TestParentSelfBridge(TransactionCase):
    def _manager(self, *modules):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        manager = bundle._bridges
        manager.native_modules = list(modules)
        return manager

    def test_every_owned_specifier_gets_a_shim(self):
        manager = self._manager(
            _Mod("@a/one", "export const ONE = 1;\n"),
            _Mod("@a/two", "export const TWO = 2;\n"),
        )
        with self.assertLogs("odoo.assets.bridge", level="DEBUG"):
            bridges = manager._build_parent_self_bridge()

        self.assertEqual(sorted(bridges), ["@a/one", "@a/two"])
        self.assertTrue(
            all(
                url.startswith(("data:", "/web/assets/esm/bridges/"))
                for url in bridges.values()
            )
        )

    def test_a_star_reexport_is_resolved_from_the_bundle_not_from_disk(self):
        manager = self._manager(
            _Mod("@a/base", "export const A = 1;\nexport const B = 2;\n"),
            _Mod("@a/face", "export * from './base';\nexport const C = 3;\n"),
        )
        captured = {}
        with (
            patch.object(
                type(manager),
                "_persist_bridge_shims",
                lambda _self, shims: captured.update(shims) or {},
            ),
            self.assertLogs("odoo.assets.bridge", level="DEBUG"),
        ):
            manager._build_parent_self_bridge()

        shim = captured["@a/face"]
        for name in ("A", "B", "C"):
            self.assertRegex(shim, rf"_e\d+ as {name}\b", f"{name} missing")

    def test_a_relative_specifier_is_not_bridged(self):
        manager = self._manager(
            _Mod("@a/one", "export const ONE = 1;\n"),
            _Mod("../legacy/thing", "export const X = 1;\n"),
        )
        with self.assertLogs("odoo.assets.bridge", level="DEBUG"):
            bridges = manager._build_parent_self_bridge()

        self.assertEqual(list(bridges), ["@a/one"])

    def test_no_native_modules_means_no_bridges(self):
        manager = self._manager()
        self.assertEqual(manager._build_parent_self_bridge(), {})


class TestBridgeRwCursorEscalation(TransactionCase):
    URL_PREFIX = "/web/assets/esm/bridges/rwprobe"

    def setUp(self):
        super().setUp()
        # _persist_bridges_via_rw_cursor commits on a second cursor
        # outside this TransactionCase's rollback, so a crash between
        # that commit and addCleanup(self._cleanup_rows) in some earlier
        # run can leave stray rows behind (addCleanup isn't crash-safe
        # either). Sweep before the test too, not just after, so any
        # given successful run self-heals regardless of when a previous
        # process died.
        self._cleanup_rows()

    def _cleanup_rows(self):
        from odoo.modules.registry import Registry
        from odoo.tests.common import get_db_name

        with Registry(get_db_name()).cursor() as cr:
            cr.execute(
                "DELETE FROM ir_attachment WHERE url LIKE %s", (self.URL_PREFIX + "%",)
            )
            cr.commit()

    def _to_create(self, name):
        return [
            {
                "name": name,
                "url": f"{self.URL_PREFIX}_{name}",
                "type": "binary",
                "public": True,
                "res_model": "ir.ui.view",
                "res_id": False,
                "raw": b"export default 1;",
                "mimetype": "text/javascript",
            }
        ]

    def test_the_rows_really_land_on_the_other_cursor(self):
        from odoo.modules.registry import Registry
        from odoo.tests.common import get_db_name

        self.addCleanup(self._cleanup_rows)
        manager = AssetsBundle("web.assets_web", [], env=self.env)._bridges

        self.assertTrue(manager._persist_bridges_via_rw_cursor(self._to_create("ok")))

        with Registry(get_db_name()).cursor() as cr:
            cr.execute(
                "SELECT count(*) FROM ir_attachment WHERE url = %s",
                (f"{self.URL_PREFIX}_ok",),
            )
            self.assertEqual(cr.fetchone()[0], 1)

    def test_a_failed_escalation_reports_false_rather_than_raising(self):
        manager = AssetsBundle("web.assets_web", [], env=self.env)._bridges
        bad = self._to_create("bad")
        bad[0]["no_such_field_on_ir_attachment"] = 1

        with self.assertLogs("odoo.tools.assets.esm_bridges", level="DEBUG") as logged:
            self.assertFalse(manager._persist_bridges_via_rw_cursor(bad))
        self.assertIn("escalation to a read-write cursor", "\n".join(logged.output))
