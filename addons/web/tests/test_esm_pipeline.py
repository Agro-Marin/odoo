import json
import logging
import posixpath
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from psycopg.errors import ReadOnlySqlTransaction

import odoo
from odoo.api import SUPERUSER_ID
from odoo.db import db_connect
from odoo.fields import Domain
from odoo.libs.asset_log import ASSET_ROOT, get_asset_logger, log_event
from odoo.libs.hashing import cache_hash
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.assets import esm_bridges
from odoo.tools.assets.esbuild import EsbuildCompiler, EsbuildResult
from odoo.tools.assets.esm_graph import (
    _BridgeExportResolver,
    _scan_import_specifiers,
    discover_transitive_import_specifiers,
)
from odoo.tools.assets.esm_registry import (
    EsmRegistry,
    esm_registry,
    external_libs,
)
from odoo.tools.misc import file_path

from odoo.addons.base.models import ir_qweb_assets
from odoo.addons.base.models.assetsbundle import AssetsBundle, _parse_odoo_module_header
from odoo.addons.base.models.ir_qweb_assets import (
    _BuildDeclined,
    _EsmFallbackError,
    _StandaloneBundleDeclined,
)


@tagged("web_unit", "web_assets")
class TestAssetLogHelper(TransactionCase):
    def test_logger_name_under_asset_root(self):
        log = get_asset_logger("esbuild")
        self.assertEqual(log.name, f"{ASSET_ROOT}.esbuild")
        self.assertEqual(get_asset_logger("").name, ASSET_ROOT)

    def test_log_event_format(self):
        log = get_asset_logger("testcat")
        with self.assertLogs(log.name, level=logging.DEBUG) as captured:
            log_event(
                log,
                logging.DEBUG,
                "started",
                bundle="web.assets_web",
                modules=42,
            )
        self.assertEqual(len(captured.records), 1)
        msg = captured.records[0].getMessage()
        self.assertEqual(msg, "event=started bundle=web.assets_web modules=42")

    def test_log_event_suppressed_below_level(self):
        log = get_asset_logger("quiet")
        log.setLevel(logging.WARNING)
        with patch.object(log, "log") as mocked_log:
            log_event(log, logging.DEBUG, "skipped", k="v")
        mocked_log.assert_not_called()


@tagged("web_unit", "web_assets")
class TestEsbuildCircuitBreaker(TransactionCase):
    def setUp(self):
        super().setUp()
        self.IrQweb = self.env["ir.qweb"]
        self.addCleanup(
            self.IrQweb._esbuild_cooldowns.clear,
        )

    def test_initial_state_allows(self):
        allow, reason = self.IrQweb._get_esbuild_circuit_state("web.test_bundle")
        self.assertTrue(allow)
        self.assertEqual(reason, "")

    def test_first_failure_opens_circuit(self):
        with self.assertLogs(
            f"{ASSET_ROOT}.fallback", level=logging.WARNING
        ) as captured:
            self.IrQweb._open_esbuild_circuit(
                "web.test_bundle",
                reason="SubprocessError",
            )
        self.assertEqual(len(captured.records), 1)
        self.assertIn("event=circuit_open", captured.records[0].getMessage())
        self.assertIn("reason=SubprocessError", captured.records[0].getMessage())
        allow, reason = self.IrQweb._get_esbuild_circuit_state("web.test_bundle")
        self.assertFalse(allow)
        self.assertEqual(reason, "SubprocessError")

    def test_second_consecutive_failure_escalates_cooldown(self):
        with self.assertLogs(
            f"{ASSET_ROOT}.fallback", level=logging.WARNING
        ) as captured:
            self.IrQweb._open_esbuild_circuit(
                "web.test_bundle",
                reason="Err1",
            )
            self.IrQweb._open_esbuild_circuit(
                "web.test_bundle",
                reason="Err2",
            )
        self.assertEqual(len(captured.records), 2)
        self.assertIn("fails=1", captured.records[0].getMessage())
        self.assertIn("fails=2", captured.records[1].getMessage())
        _expiry, _reason, fails = self.IrQweb._esbuild_cooldowns[
            (self.env.cr.dbname, "web.test_bundle")
        ]
        self.assertEqual(fails, 2)
        remaining = _expiry - time.monotonic()
        self.assertGreater(
            remaining,
            self.IrQweb._ESBUILD_COOLDOWN_S,
            msg="2nd failure should escalate past the base cooldown",
        )

    def test_success_clears_the_circuit(self):
        with self.assertLogs(
            f"{ASSET_ROOT}.fallback", level=logging.WARNING
        ) as captured:
            self.IrQweb._open_esbuild_circuit(
                "web.test_bundle",
                reason="OnceFailed",
            )
            self.IrQweb._close_esbuild_circuit("web.test_bundle")
        self.assertEqual(len(captured.records), 1)
        self.assertIn("event=circuit_open", captured.records[0].getMessage())
        self.assertNotIn(
            (self.env.cr.dbname, "web.test_bundle"),
            self.IrQweb._esbuild_cooldowns,
        )
        allow, _ = self.IrQweb._get_esbuild_circuit_state("web.test_bundle")
        self.assertTrue(allow)

    def test_circuit_key_is_database_scoped(self):
        with self.assertLogs(f"{ASSET_ROOT}.fallback", level=logging.WARNING):
            self.IrQweb._open_esbuild_circuit(
                "web.test_bundle",
                reason="ScopeCheck",
            )
        self.assertIn(
            (self.env.cr.dbname, "web.test_bundle"),
            self.IrQweb._esbuild_cooldowns,
            msg="cooldown key must be (db_name, bundle)",
        )
        self.assertNotIn(
            "web.test_bundle",
            self.IrQweb._esbuild_cooldowns,
            msg="bundle-only key would bleed the breaker across databases",
        )
        self.IrQweb._esbuild_cooldowns[("some_other_db", "web.test_bundle")] = (
            time.monotonic() + 1e6,
            "OtherDbFail",
            1,
        )
        allow, reason = self.IrQweb._get_esbuild_circuit_state("web.test_bundle")
        self.assertFalse(
            allow,
            msg="this db's own failure should still gate it",
        )
        self.assertEqual(reason, "ScopeCheck")


@tagged("web_unit", "web_assets")
class TestEsbuildAdvisoryLock(TransactionCase):
    def test_lock_acquired_in_own_cursor(self):
        IrQweb = self.env["ir.qweb"]
        got = IrQweb._acquire_esbuild_lock("test.lock.alpha")
        self.assertTrue(got)

    def test_lock_rejects_other_cursor_while_held(self):
        IrQweb = self.env["ir.qweb"]
        self.assertTrue(IrQweb._acquire_esbuild_lock("test.lock.beta"))
        with db_connect(self.env.cr.dbname).cursor() as cr2:
            cr2.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                ("esbuild:test.lock.beta",),
            )
            got = cr2.fetchone()[0]
        self.assertFalse(
            got,
            msg="sibling cursor must not acquire lock while self.env.cr holds it",
        )

    def test_lock_released_on_commit(self):
        dbname = self.env.cr.dbname
        key = "esbuild:test.lock.gamma"

        with db_connect(dbname).cursor() as cr_a:
            cr_a.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (key,),
            )
            self.assertTrue(cr_a.fetchone()[0])
            cr_a.commit()

        with db_connect(dbname).cursor() as cr_b:
            cr_b.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (key,),
            )
            got = cr_b.fetchone()[0]
            cr_b.commit()
        self.assertTrue(got, msg="lock must release at transaction commit")


@tagged("web_unit", "web_assets")
class TestContentAddressableUrl(TransactionCase):
    def test_identical_content_produces_identical_url(self):
        ir_qweb = self.env["ir.qweb"]
        content = "export const x = 1;"
        url1 = ir_qweb._save_esm_attachment("test.cas.same", content)
        url2 = ir_qweb._save_esm_attachment("test.cas.same", content)
        self.assertEqual(url1, url2)
        self.assertRegex(
            url1,
            r"^/web/assets/esm/[0-9a-f]{16}/test\.cas\.same\.esm\.js$",
            msg="URL must match content-addressable scheme",
        )

    def test_different_content_produces_different_url(self):
        ir_qweb = self.env["ir.qweb"]
        url_a = ir_qweb._save_esm_attachment(
            "test.cas.diff",
            "export const x = 1;",
        )
        url_b = ir_qweb._save_esm_attachment(
            "test.cas.diff",
            "export const x = 2;",
        )
        self.assertNotEqual(url_a, url_b)
        Attachment = self.env["ir.attachment"].sudo()
        attachments = Attachment.search(
            [
                ("url", "=like", "/web/assets/esm/%/test.cas.diff.esm.js"),
            ]
        )
        self.assertEqual(
            len(attachments),
            2,
            msg="superseded version must survive the rebuild (deferred GC)",
        )
        old_row = attachments.filtered(lambda a: a.url == url_a)
        self.env.cr.execute(
            "UPDATE ir_attachment SET write_date = write_date - interval '30 days'"
            " WHERE id = %s",
            [old_row.id],
        )
        old_row.invalidate_recordset()
        Attachment._gc_esm_assets()
        remaining = Attachment.search(
            [
                ("url", "=like", "/web/assets/esm/%/test.cas.diff.esm.js"),
            ]
        )
        self.assertEqual(remaining.mapped("url"), [url_b])


@tagged("web_unit", "web_assets")
class TestMetafileSidecar(TransactionCase):
    def test_metafile_saved_as_sibling_when_present(self):
        ir_qweb = self.env["ir.qweb"]
        url = ir_qweb._save_esm_attachment(
            "test.meta.present",
            "/* bundle */",
            metafile=json.dumps({"inputs": {}, "outputs": {}}),
        )
        meta_url = url[: -len(".esm.js")] + ".meta.json"
        meta = (
            self.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("url", "=", meta_url),
                    ("public", "=", True),
                ],
                limit=1,
            )
        )
        self.assertTrue(meta, msg="sibling metafile attachment must exist")
        self.assertEqual(meta.mimetype, "application/json")
        parsed = json.loads(meta.raw)
        self.assertIn("inputs", parsed)
        self.assertIn("outputs", parsed)

    def test_metafile_absent_when_esbuild_did_not_run(self):
        ir_qweb = self.env["ir.qweb"]
        url = ir_qweb._save_esm_attachment(
            "test.meta.absent",
            "/* bundle */",
        )
        meta_url = url[: -len(".esm.js")] + ".meta.json"
        meta = (
            self.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("url", "=", meta_url),
                ],
                limit=1,
            )
        )
        self.assertFalse(
            meta,
            msg="no metafile should be created when _last_metafile is None",
        )


@tagged("web_unit", "web_assets")
class TestGeneratedAssetsAreCollectable(TransactionCase):
    def _row_for(self, url, create):
        attachment = create(
            {
                "name": url.rsplit("/", 1)[-1],
                "mimetype": "text/javascript",
                "res_model": "ir.ui.view",
                "res_id": False,
                "type": "binary",
                "public": True,
                "raw": b"export default 1;",
                "url": url,
            }
        )
        Attachment = self.env["ir.attachment"]
        domain = Attachment._generated_asset_domain()
        return attachment, bool(
            Attachment.sudo().search(domain & Domain("id", "=", attachment.id))
        )

    def test_sudo_alone_leaves_an_uncollectable_row(self):
        env = self.env(user=self.env.ref("base.user_admin").id)
        attachment, collectable = self._row_for(
            "/web/assets/esm/bridges/probe_sudo.js",
            env["ir.attachment"].sudo().create,
        )
        self.assertNotEqual(attachment.create_uid.id, SUPERUSER_ID)
        self.assertFalse(collectable)

    def test_with_user_superuser_is_collectable(self):
        env = self.env(user=self.env.ref("base.user_admin").id)
        attachment, collectable = self._row_for(
            "/web/assets/esm/bridges/probe_superuser.js",
            env["ir.attachment"].with_user(SUPERUSER_ID).create,
        )
        self.assertEqual(attachment.create_uid.id, SUPERUSER_ID)
        self.assertTrue(collectable)

    def test_the_bridge_writer_uses_the_collectable_form(self):
        source = Path(esm_bridges.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"ir.attachment"].sudo().create', source)
        self.assertIn('"ir.attachment"].with_user(SUPERUSER_ID).create', source)


@tagged("web_unit", "web_assets")
class TestParentSelfBridge(TransactionCase):
    def test_parent_self_bridge_covers_native_modules(self):
        setup_ab = self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_unit_tests_setup",
            js=True,
            css=False,
        )
        bridges = setup_ab._bridges._build_parent_self_bridge()
        native_specs = {a.module_path for a in setup_ab.native_modules}
        self.assertGreater(len(bridges), 0)
        for spec, url in list(bridges.items())[:20]:
            self.assertIn(spec, native_specs)
            self.assertTrue(
                url.startswith("/web/assets/esm/bridges/"),
                msg=f"bridge for {spec} is not an attachment URL: {url[:80]}",
            )
            self.assertRegex(url, r"^/web/assets/esm/bridges/[0-9a-f]{32}\.js$")

    def test_prod_import_map_bridges_parent_specifiers(self):
        self.env["ir.attachment"].sudo().search(
            [
                ("url", "=like", "/web/assets/esm/%/web.assets_unit_tests_setup%"),
            ]
        ).unlink()
        setup_ab = self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_unit_tests_setup",
            js=True,
            css=False,
        )
        sample_spec = next(
            a.module_path
            for a in setup_ab.native_modules
            if a.module_path.startswith("@web/")
        )

        pre, _post = self.env["ir.qweb"]._get_native_module_nodes(
            "web.assets_unit_tests_setup",
            debug=False,
        )
        import_map = None
        for _tag, attrs in pre:
            if attrs.get("type") == "importmap":
                import_map = json.loads(attrs["text"])["imports"]
                break
        self.assertIsNotNone(import_map, "prod must emit an import map")
        self.assertIn(
            sample_spec,
            import_map,
            msg=(
                f"expected parent-self bridge for {sample_spec!r}; "
                f"map size={len(import_map)}, "
                f"@web/* count={sum(1 for s in import_map if s.startswith('@web/'))}"
            ),
        )


@tagged("web_unit", "web_assets")
class TestPipelineIntegration(TransactionCase):
    def test_admin_override_skips_esbuild(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.force_fallback_bundles",
            "web.assets_web",
        )
        self.addCleanup(
            self.env["ir.config_parameter"].sudo().set_param,
            "web.esbuild.force_fallback_bundles",
            "",
        )

        called = []
        original = AssetsBundle.esbuild_native_bundle

        def _spy(self, *args, **kwargs):
            called.append(self.name)
            return original(self, *args, **kwargs)

        with patch.object(AssetsBundle, "esbuild_native_bundle", _spy):
            self.env["ir.qweb"]._get_asset_nodes(
                "web.assets_web",
                css=False,
                js=True,
            )
        self.assertNotIn(
            "web.assets_web",
            called,
            msg="admin override must bypass the esbuild subprocess",
        )

    def test_contention_falls_through_to_debug_nodes(self):
        ir_qweb = self.env["ir.qweb"]
        with patch.object(
            type(ir_qweb),
            "_acquire_esbuild_lock",
            return_value=False,
        ):
            self.env["ir.attachment"].sudo().search(
                [
                    ("url", "=like", "/web/assets/esm/%/web.assets_web%"),
                ]
            ).unlink()
            nodes = ir_qweb._get_asset_nodes(
                "web.assets_web",
                css=False,
                js=True,
            )
        self.assertTrue(nodes, msg="fallback must still produce nodes")
        tags = {tag for tag, _attrs in nodes}
        self.assertIn("script", tags)
        importmaps = [
            attrs
            for tag, attrs in nodes
            if tag == "script" and attrs.get("type") == "importmap"
        ]
        self.assertTrue(
            importmaps,
            msg="debug-mode fallback must emit an importmap",
        )

    def test_request_bound_debug_bundle_keeps_importmap(self):
        from odoo.addons.base.models import ir_qweb_assets

        ir_qweb = self.env["ir.qweb"]

        def importmaps(nodes):
            return [
                attrs
                for tag, attrs in nodes
                if tag == "script" and attrs.get("type") == "importmap"
            ]

        fake_request = SimpleNamespace()
        with patch.object(ir_qweb_assets, "request", fake_request):
            first = ir_qweb._get_asset_nodes(
                "web.assets_web", css=False, js=True, debug="assets"
            )
            second = ir_qweb._get_asset_nodes(
                "web.assets_web", css=False, js=True, debug="assets"
            )

        self.assertEqual(
            len(importmaps(first)),
            1,
            msg="first request-bound debug bundle must emit exactly one importmap",
        )
        self.assertEqual(
            len(importmaps(second)),
            0,
            msg="second bundle on the same request must be deduped (no importmap)",
        )


@tagged("web_unit", "web_assets")
class TestEsbuildIntegration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        odoo_root = Path(odoo.__path__[0]).parent
        cls.esbuild = shutil.which("esbuild") or shutil.which(
            "esbuild",
            path=str(odoo_root / "node_modules" / ".bin"),
        )

    def setUp(self):
        super().setUp()
        if not self.esbuild:
            self.skipTest(
                "esbuild binary not found. Run 'npm install' in the Odoo root "
                "to enable this integration test.",
            )

    def test_emoji_bundle_compiles(self):
        IrQweb = self.env["ir.qweb"]
        assets_params = self.env["ir.asset"]._prepare_assets_params()
        bundle = IrQweb._get_asset_bundle(
            "web.assets_emoji",
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        self.assertTrue(
            bundle._is_esm_bundle,
            msg="web.assets_emoji must be classified as an ESM bundle",
        )
        self.assertGreater(
            len(bundle.native_modules),
            0,
            msg=(
                "bundle must have at least one native module "
                "(did ir.asset population run?)"
            ),
        )

        result = bundle.esbuild_native_bundle()

        self.assertIn(
            "odoo.loader.registerNativeModules",
            result.code,
            msg="bundle output must register modules via the loader API",
        )
        self.assertGreater(
            len(result.code),
            1000,
            msg=f"bundle output suspiciously small ({len(result.code)} bytes)",
        )
        self.assertIsNotNone(
            result.metafile,
            msg="metafile sidecar must be captured after successful build",
        )

    def test_timeout_parameter_threaded_through(self):
        IrQweb = self.env["ir.qweb"]
        assets_params = self.env["ir.asset"]._prepare_assets_params()
        bundle = IrQweb._get_asset_bundle(
            "web.assets_emoji",
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        result = bundle.esbuild_native_bundle(timeout_s=60, target="es2022")
        self.assertIn("odoo.loader.registerNativeModules", result.code)


@tagged("web_unit", "web_assets")
class TestEsbuildSettings(TransactionCase):
    """`ir.qweb` used to re-derive read/cast/warn/default over
    `ir.config_parameter`; it now uses the typed readers that model already
    exposes.  What matters is that the two agree, which is precisely what the
    re-derivation stopped doing."""

    def setUp(self):
        super().setUp()
        self.ICP = self.env["ir.config_parameter"].sudo()

    def _set(self, key, value):
        self.ICP.set_param(key, value)
        self.env.registry.clear_cache("stable")

    def test_unset_returns_default(self):
        self.ICP.search([("key", "=", "web.esbuild.cooldown_s")]).unlink()
        self.env.registry.clear_cache("stable")
        self.assertEqual(self.ICP.get_param_float("web.esbuild.cooldown_s", 60.0), 60.0)

    def test_valid_param_casts(self):
        self._set("web.esbuild.cooldown_s", "12.5")
        self.assertEqual(self.ICP.get_param_float("web.esbuild.cooldown_s", 60.0), 12.5)

    def test_unparseable_param_falls_back_to_default(self):
        self._set("web.esbuild.cooldown_s", "not-a-number")
        self.assertEqual(
            self.ICP.get_param_float("web.esbuild.cooldown_s", 60.0),
            60.0,
            msg="a bad cast must fall back to the default",
        )

    def test_fail_closed_agrees_with_every_other_boolean_parameter(self):
        """`no`, `off` and `none` used to mean True here and False everywhere
        else, so an operator disabling fail-closed the obvious way turned an
        esbuild error into a 500 instead of a fallback."""
        IrQweb = self.env["ir.qweb"]
        for raw in ("0", "false", "no", "off", "none", ""):
            with self.subTest(raw=raw):
                self._set("web.esbuild.fail_closed", raw)
                self.assertFalse(
                    IrQweb._is_esbuild_fail_closed(),
                    msg=f"{raw!r} is falsy for ir.config_parameter",
                )
        for raw in ("1", "true", "yes"):
            with self.subTest(raw=raw):
                self._set("web.esbuild.fail_closed", raw)
                self.assertTrue(IrQweb._is_esbuild_fail_closed())

    def test_fail_closed_unset_follows_the_run_mode(self):
        self.ICP.search([("key", "=", "web.esbuild.fail_closed")]).unlink()
        self.env.registry.clear_cache("stable")
        self.assertTrue(
            self.env["ir.qweb"]._is_esbuild_fail_closed(),
            msg="under --test-enable the default is fail-closed",
        )


@tagged("web_unit", "web_assets")
class TestEsbuildSourceMaps(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        odoo_root = Path(odoo.__path__[0]).parent
        cls.esbuild = shutil.which("esbuild") or shutil.which(
            "esbuild",
            path=str(odoo_root / "node_modules" / ".bin"),
        )

    def setUp(self):
        super().setUp()
        if not self.esbuild:
            self.skipTest(
                "esbuild binary not found. Run 'npm install' in the Odoo root "
                "to enable this integration test.",
            )

    def _bundle(self, **kwargs):
        IrQweb = self.env["ir.qweb"]
        assets_params = self.env["ir.asset"]._prepare_assets_params()
        return IrQweb._get_asset_bundle(
            "web.assets_emoji",
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )

    def test_off_by_default(self):
        bundle = self._bundle()
        result = bundle.esbuild_native_bundle()
        self.assertIsNone(
            result.sourcemap,
            msg="default behavior must not capture a source map",
        )

    def test_linked_mode_populates_last_sourcemap_and_links_bundle(self):
        bundle = self._bundle()
        result = bundle.esbuild_native_bundle(source_maps="linked")
        self.assertIsNotNone(
            result.sourcemap,
            msg="linked mode must capture the sourcemap sibling",
        )
        parsed = json.loads(result.sourcemap)
        self.assertIn("version", parsed)
        self.assertIn("mappings", parsed)
        self.assertIn("//# sourceMappingURL=", result.code)

    def test_external_mode_emits_map_without_directive(self):
        bundle = self._bundle()
        result = bundle.esbuild_native_bundle(source_maps="external")
        self.assertIsNotNone(
            result.sourcemap,
            msg="external mode still writes the sidecar, just doesn't link it",
        )
        self.assertNotIn("//# sourceMappingURL=", result.code)

    def test_inline_mode_embeds_in_bundle(self):
        bundle = self._bundle()
        result = bundle.esbuild_native_bundle(source_maps="inline")
        self.assertIsNone(
            result.sourcemap,
            msg="inline mode embeds in bundle, no sidecar to capture",
        )
        self.assertIn(
            "//# sourceMappingURL=data:application/json;base64,",
            result.code,
        )

    def test_unknown_mode_silently_falls_back(self):
        bundle = self._bundle()
        with self.assertLogs(
            f"{ASSET_ROOT}.esbuild", level=logging.WARNING
        ) as captured:
            result = bundle.esbuild_native_bundle(source_maps="yes please")
        self.assertTrue(
            any(
                "event=source_maps_unknown_mode" in r.getMessage()
                and "mode=yes please" in r.getMessage()
                for r in captured.records
            ),
            msg="invalid source_maps mode must emit a structured warning",
        )
        self.assertIsNone(result.sourcemap)
        self.assertIn("odoo.loader.registerNativeModules", result.code)

    def test_external_mode_persists_sidecar_attachment(self):
        ir_qweb = self.env["ir.qweb"]
        url = ir_qweb._save_esm_attachment(
            "test.sm.sidecar",
            "/* bundle */",
            sourcemap='{"version":3,"sources":[],"mappings":""}',
        )
        sm_url = url + ".map"
        sm = (
            self.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("url", "=", sm_url),
                    ("public", "=", True),
                ],
                limit=1,
            )
        )
        self.assertTrue(sm, msg="external-mode sidecar attachment must exist")
        self.assertEqual(sm.mimetype, "application/json")

    def test_no_sourcemap_no_sidecar(self):
        ir_qweb = self.env["ir.qweb"]
        url = ir_qweb._save_esm_attachment(
            "test.sm.absent",
            "/* bundle */",
        )
        sm_url = url + ".map"
        sm = (
            self.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("url", "=", sm_url),
                ],
                limit=1,
            )
        )
        self.assertFalse(
            sm,
            msg="no source map must create no .map sidecar",
        )

    def test_setting_key_recognized(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.search([("key", "=", "web.esbuild.source_maps")]).unlink()
        self.env.registry.clear_cache("stable")
        self.assertEqual(ICP.get_param("web.esbuild.source_maps", ""), "")
        ICP.set_param("web.esbuild.source_maps", "external")
        self.env.registry.clear_cache("stable")
        self.assertEqual(ICP.get_param("web.esbuild.source_maps", ""), "external")


def _fake_native_module(url="", raw_content="", module_path="", filename=None):
    return SimpleNamespace(
        url=url,
        raw_content=raw_content,
        module_path=module_path,
        _filename=filename,
        parsed_header=_parse_odoo_module_header(raw_content),
    )


@tagged("web_unit", "web_assets")
class TestEsbuildHelpers(TransactionCase):
    def _compiler(self, name="web.assets_emoji", native_modules=(), provider=None):
        return EsbuildCompiler(
            name,
            list(native_modules),
            addon_flags_provider=provider,
        )

    def _odoo_root(self):
        return Path(odoo.__path__[0]).parent

    def test_resolve_opts_applies_defaults(self):
        c = self._compiler()
        timeout_s, target, source_maps = c._esbuild_resolve_opts(None, None, None)
        self.assertEqual(timeout_s, EsbuildCompiler._ESBUILD_TIMEOUT_S)
        self.assertEqual(target, EsbuildCompiler._ESBUILD_TARGET)
        self.assertEqual(source_maps, EsbuildCompiler._ESBUILD_SOURCE_MAPS)

    def test_resolve_opts_passes_through_valid(self):
        c = self._compiler()
        self.assertEqual(
            c._esbuild_resolve_opts(10, "es2022", "linked"),
            (10, "es2022", "linked"),
        )

    def test_resolve_opts_unknown_source_map_falls_back(self):
        c = self._compiler()
        with self.assertLogs(f"{ASSET_ROOT}.esbuild", level=logging.WARNING):
            _, _, source_maps = c._esbuild_resolve_opts(5, "es2023", "bogus")
        self.assertEqual(source_maps, "")

    def test_entry_lines_register_block(self):
        c = self._compiler(
            native_modules=[
                _fake_native_module(
                    url="/web/static/src/foo.js", module_path="@web/foo"
                ),
            ]
        )
        lines = c._esbuild_entry_lines(self._odoo_root())
        self.assertIn('import * as __owl from "@odoo/owl";', lines)
        self.assertIn('import * as __m0 from "./addons/web/static/src/foo.js";', lines)
        self.assertIn("odoo.loader.registerNativeModules({", lines)
        joined = "\n".join(lines)
        self.assertIn('"@odoo/owl": __owl', joined)
        self.assertIn('"@web/foo": __m0', joined)

    def test_flags_drops_own_test_externals(self):
        fake = (
            [],
            [
                "--external:@web/../tests/*",
                "--external:./web/static/tests/*",
                "--external:@other/../tests/*",
            ],
        )
        c = self._compiler(
            native_modules=[_fake_native_module(url="/web/static/tests/t.js")],
            provider=lambda root: fake,
        )
        _, external_flags = c._esbuild_flags(self._odoo_root(), None)
        self.assertNotIn("--external:@web/../tests/*", external_flags)
        self.assertNotIn("--external:./web/static/tests/*", external_flags)
        self.assertIn("--external:@other/../tests/*", external_flags)

    def test_flags_adds_dynamic_child_externals(self):
        c = self._compiler(provider=lambda root: ([], []))
        _, external_flags = c._esbuild_flags(
            self._odoo_root(), frozenset({"@lazy/child"})
        )
        self.assertIn("--external:@lazy/child", external_flags)

    def test_postprocess_rewrites_directive_and_captures_sidecars(self):
        c = self._compiler("web.assets_emoji")
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            out = tmp / "x.out.js"
            meta = tmp / "x.meta.json"
            smap = tmp / "x.out.js.map"
            out.write_text(
                "console.log(1);\n//# sourceMappingURL=tmpXYZ.js.out.js.map\n",
                encoding="utf-8",
            )
            meta.write_text('{"inputs":{}}', encoding="utf-8")
            smap.write_text('{"version":3,"mappings":""}', encoding="utf-8")
            result = c._postprocess_esbuild_output(
                out, meta, smap, "linked", entry_bytes=10, _t0=time.monotonic()
            )
        self.assertIn("//# sourceMappingURL=web.assets_emoji.esm.js.map", result)
        self.assertNotIn("tmpXYZ", result)
        self.assertEqual(c._last_metafile, '{"inputs":{}}')
        self.assertEqual(c._last_sourcemap, '{"version":3,"mappings":""}')

    def test_postprocess_no_sourcemap_leaves_last_none(self):
        c = self._compiler()
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            out = tmp / "x.out.js"
            meta = tmp / "x.meta.json"
            out.write_text("console.log(2);", encoding="utf-8")
            meta.write_text("{}", encoding="utf-8")
            result = c._postprocess_esbuild_output(
                out, meta, tmp / "x.map", "", 5, time.monotonic()
            )
        self.assertEqual(result, "console.log(2);")
        self.assertIsNone(c._last_sourcemap)

    def test_postprocess_missing_output_raises(self):
        c = self._compiler()
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            with self.assertRaises(RuntimeError) as ctx:
                c._postprocess_esbuild_output(
                    tmp / "nope.js",
                    tmp / "nope.meta",
                    tmp / "nope.map",
                    "",
                    0,
                    time.monotonic(),
                )
        self.assertIn("output file missing", str(ctx.exception))


@tagged("web_unit", "web_assets")
class TestBridgeHelpers(TransactionCase):
    def test_resolver_resolves_external_lib(self):
        r = _BridgeExportResolver(
            {"luxon": "/web/static/lib/luxon/luxon.js"}, {}, "test"
        )
        self.assertEqual(r.resolve_url("luxon"), "/web/static/lib/luxon/luxon.js")

    def test_resolver_resolves_lib_candidate(self):
        r = _BridgeExportResolver({}, {"@odoo/x": ("a", "b", "c.js")}, "test")
        self.assertEqual(r.resolve_url("@odoo/x"), "/a/b/c.js")

    def test_resolver_resolves_addon_paths(self):
        r = _BridgeExportResolver({}, {}, "test")
        self.assertEqual(
            r.resolve_url("@web/core/registry"),
            "/web/static/src/core/registry.js",
        )
        self.assertEqual(
            r.resolve_url("@web/../lib/foo/bar"), "/web/static/lib/foo/bar.js"
        )
        self.assertEqual(r.resolve_url("@web/../tests/baz"), "/web/static/tests/baz.js")

    def test_resolver_unmappable_specifiers(self):
        r = _BridgeExportResolver({}, {}, "test")
        self.assertIsNone(r.resolve_url("luxon"))
        self.assertIsNone(r.resolve_url("@noslash"))

    def test_resolver_caches_and_get_protocol(self):
        r = _BridgeExportResolver({}, {}, "test")
        self.assertIsNone(r.read_source("nope"))
        self.assertIn("nope", r._cache)
        self.assertIsNone(r._cache["nope"])
        self.assertIsNone(r.get("nope"))
        self.assertEqual(r.get("nope", "DEFAULT"), "DEFAULT")

    def test_discover_classifies_import_kinds(self):
        b = AssetsBundle("test.discover", [], env=self.env)
        b.native_modules = [
            _fake_native_module(
                raw_content=(
                    'import {a} from "@web/named";\n'
                    'import D from "@web/deflt";\n'
                    'import * as N from "@web/star";\n'
                )
            ),
        ]
        discovered, ext_seen = b._bridges._discover_bridge_specifiers(set(), set())
        self.assertEqual(discovered.get("@web/named"), set())
        self.assertEqual(discovered.get("@web/deflt"), {"__default__"})
        self.assertEqual(discovered.get("@web/star"), {"__star__"})
        self.assertEqual(ext_seen, set())

    def test_discover_excludes_ignored(self):
        b = AssetsBundle("test.discover2", [], env=self.env)
        b.native_modules = [
            _fake_native_module(
                raw_content=(
                    'import X from "@web/own";\n'
                    'import Y from "@odoo/owl";\n'
                    'import Z from "@web/extlib";\n'
                    'import W from "@web/keep";\n'
                )
            ),
        ]
        discovered, ext_seen = b._bridges._discover_bridge_specifiers(
            {"@web/own"}, {"@web/extlib"}
        )
        self.assertNotIn("@web/own", discovered)
        self.assertNotIn("@odoo/owl", discovered)
        self.assertNotIn("@web/extlib", discovered)
        self.assertIn("@web/keep", discovered)
        self.assertEqual(ext_seen, {"@web/extlib"})

    def test_shim_source_default_and_named(self):
        shim, star = AssetsBundle._bridge_shim_source(
            "@web/foo", set(), {"b", "a"}, True
        )
        self.assertFalse(star)
        self.assertIn('const _m = odoo.loader.modules.get("@web/foo");', shim)
        self.assertIn("_d = _m.default ?? _m;", shim)
        self.assertIn("_d as default", shim)
        self.assertIn("_e0 = _m.a;", shim)
        self.assertIn("_e1 = _m.b;", shim)
        self.assertIn("export { _d as default, _e0 as a, _e1 as b };", shim)

    def test_shim_source_star_fallback(self):
        shim, star = AssetsBundle._bridge_shim_source("@web/bar", set(), set(), False)
        self.assertTrue(star)
        self.assertIn("_d = _m.default ?? _m;", shim)
        self.assertIn("_d as default", shim)
        self.assertEqual(shim.count("export {"), 1)
        self.assertNotIn("_e0", shim)

    def test_shim_source_named_only_still_exports_default(self):
        shim, star = AssetsBundle._bridge_shim_source("@web/baz", set(), {"x"}, False)
        self.assertFalse(star)
        self.assertIn("_e0 = _m.x;", shim)
        self.assertIn("_e0 as x", shim)
        self.assertIn("_d as default", shim)

    def test_shim_source_star_kind_no_duplicate_default(self):
        shim, star = AssetsBundle._bridge_shim_source(
            "@web/qux", {"__star__"}, set(), False
        )
        self.assertTrue(star)
        self.assertEqual(shim.count("export {"), 1)
        self.assertEqual(shim.count(" as default"), 1)
        self.assertNotIn("export default", shim)

    def test_shim_source_default_kind_triggers_export(self):
        shim, star = AssetsBundle._bridge_shim_source(
            "@web/q", {"__default__"}, set(), False
        )
        self.assertFalse(star)
        self.assertIn("_d as default", shim)


@tagged("web_unit", "web_assets")
class TestTransitiveImportClosure(TransactionCase):
    @staticmethod
    def _read_static_url(url):
        if not url.startswith("/") or "/static/" not in url:
            return None
        try:
            return Path(file_path(url.lstrip("/"))).read_text(encoding="utf-8")
        except OSError, ValueError:
            return None

    def test_walk_finds_two_hop_specifier(self):
        res = discover_transitive_import_specifiers(
            [
                "@web/../lib/bootstrap/bootstrap.esm.js",
                "@web/core/utils/dom/scrolling",
            ],
            {"@web/libs/bootstrap"},
            external_libs(),
            EsbuildCompiler._LIB_CANDIDATES,
            "test.report.closure",
        )
        self.assertIn("@web/core/browser/browser", res)
        self.assertNotIn("@popperjs/core", res)
        self.assertNotIn("@web/libs/bootstrap", res)

    def test_scan_covers_reexport_and_relative_shapes(self):
        specs = _scan_import_specifiers(
            'import { a } from "@web/named";\n'
            'import "@web/side_effect";\n'
            'import "./relative";\n'
            'export { b } from "@web/list_from";\n'
            'export * from "@web/star_from";\n'
            'export * as ns from "@web/ns_from";\n'
            'const url = import("@web/dynamic_only");\n'
        )
        self.assertLessEqual(
            {
                "@web/named",
                "@web/side_effect",
                "./relative",
                "@web/list_from",
                "@web/star_from",
                "@web/ns_from",
            },
            specs,
        )
        self.assertNotIn("@web/dynamic_only", specs)

    def test_report_bundle_debug_importmap_is_transitively_complete(self):
        nodes, _post = self.env["ir.qweb"]._get_native_module_nodes(
            "web.report_assets_common",
            debug="assets",
        )
        importmaps = [
            attrs
            for tag, attrs in nodes
            if tag == "script" and attrs.get("type") == "importmap"
        ]
        self.assertEqual(len(importmaps), 1)
        imports = json.loads(importmaps[0]["text"])["imports"]
        for spec in (
            "@web/libs/bootstrap",
            "@web/../lib/bootstrap/bootstrap.esm.js",
            "@popperjs/core",
        ):
            self.assertIn(spec, imports, msg=f"{spec} missing from import map")

        seed = "@web/libs/bootstrap"
        queue = [(seed, imports.get(seed))]
        seen_urls = set()
        unmapped = []
        while queue:
            spec, url = queue.pop()
            if url is None:
                unmapped.append(spec)
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            source = self._read_static_url(url)
            if source is None:
                continue
            for imported in _scan_import_specifiers(source):
                if imported.startswith("."):
                    queue.append(
                        (
                            imported,
                            posixpath.normpath(f"{posixpath.dirname(url)}/{imported}"),
                        ),
                    )
                else:
                    queue.append((imported, imports.get(imported)))
        self.assertFalse(
            unmapped,
            "Specifiers reachable from the report bundle but absent from its "
            "debug import map (the browser cannot resolve them):"
            "\n- " + "\n- ".join(sorted(unmapped)),
        )


@tagged("web_unit", "web_assets")
class TestEsmLexer(TransactionCase):
    SRC = (
        'import { q } from "@web/other";\n'
        "export const alpha = 1;\n"
        "export function beta() {}\n"
        "export default class Gamma {}\n"
        'export * as ns from "@web/ns_target";\n'
        "/* export const block_commented = 2; */\n"
        "const tpl = `export const in_template = 3;`;\n"
    )

    def test_worker_available(self):
        from odoo.tools.assets.esm_lexer import lex_module

        result = lex_module("export const x = 1;")
        self.assertIsNotNone(
            result,
            msg="es-module-lexer worker unavailable — run `npm install` "
            "in the Odoo root (same prerequisite as esbuild)",
        )
        self.assertEqual(result["names"], ["x"])
        self.assertFalse(result["hasDefault"])

    def test_lexer_and_regex_paths_agree(self):
        from odoo.tools.assets import esm_graph

        expected = ({"alpha", "beta", "ns"}, True)
        self.assertEqual(esm_graph._extract_esm_exports(self.SRC), expected)
        with patch.object(esm_graph, "lex_module", return_value=None):
            self.assertEqual(esm_graph._extract_esm_exports(self.SRC), expected)

    def test_lexer_line_comment_immunity(self):
        from odoo.tools.assets import esm_graph

        names, has_default = esm_graph._extract_esm_exports(
            "// export const ghost = 1;\nexport const real = 2;\n"
        )
        self.assertEqual(names, {"real"})
        self.assertFalse(has_default)

    def test_star_expansion_shared_by_both_paths(self):
        from odoo.tools.assets import esm_graph

        source_map = {
            "@web/barrel": 'export * from "@web/leaf";\nexport const own = 1;',
            "@web/leaf": "export const leaf_a = 1;\nexport const leaf_b = 2;",
        }
        expected = ({"own", "leaf_a", "leaf_b"}, False)
        result = esm_graph._extract_esm_exports(
            source_map["@web/barrel"],
            source_map=source_map,
            importing_specifier="@web/barrel",
        )
        self.assertEqual(result, expected)
        with patch.object(esm_graph, "lex_module", return_value=None):
            result = esm_graph._extract_esm_exports(
                source_map["@web/barrel"],
                source_map=source_map,
                importing_specifier="@web/barrel",
            )
        self.assertEqual(result, expected)

    def test_unlexable_source_falls_back_to_regex(self):
        from odoo.tools.assets import esm_graph

        broken = "export const good = 1;\nfunction ( { invalid syntax\n"
        names, _ = esm_graph._extract_esm_exports(broken)
        self.assertIn("good", names)

    def test_discovery_catches_mixed_default_named_import(self):
        from odoo.tools.assets.esm_bridges import BridgeShimManager

        asset = SimpleNamespace(
            module_path="@web/consumer",
            raw_content='import Def, { named } from "@other/mixed";\n',
        )
        manager = BridgeShimManager(self.env, "test.bundle", [asset])
        discovered, _ext = manager._discover_bridge_specifiers(set(), set())
        self.assertIn("@other/mixed", discovered)
        self.assertIn("__default__", discovered["@other/mixed"])


@tagged("web_unit", "web_assets")
class TestQwebAssetHelpers(TransactionCase):
    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    def test_specifier_convention_resolves(self):
        cases = {
            "@web/core/registry": "/web/static/src/core/registry.js",
            "@web/../lib/hoot/hoot": "/web/static/lib/hoot/hoot.js",
            "@web/../tests/foo": "/web/static/tests/foo.js",
            "@account/models/move": "/account/static/src/models/move.js",
        }
        for spec, url in cases.items():
            self.assertEqual(self._qweb._specifier_to_static_url(spec), url, spec)

    def test_specifier_odoo_namespace_is_reserved(self):
        externals = self._qweb._external_libs()
        for spec in [k for k in externals if k.startswith("@odoo/")]:
            self.assertIsNone(
                self._qweb._specifier_to_static_url(spec),
                f"{spec} must not resolve via the addon convention",
            )
            self.assertTrue(externals[spec])
        self.assertIsNone(self._qweb._specifier_to_static_url("@odoo/nope"))

    def test_specifier_non_convention_returns_none(self):
        for spec in ["luxon", "@web", "@/foo", ""]:
            self.assertIsNone(self._qweb._specifier_to_static_url(spec), spec)

    def test_is_debug_assets_string_semantics(self):
        q = self._qweb
        self.assertTrue(q._is_debug_assets("assets"))
        self.assertTrue(q._is_debug_assets("1,assets"))
        self.assertFalse(q._is_debug_assets("1"))
        self.assertFalse(q._is_debug_assets(""))

    def test_is_debug_assets_never_raises_on_non_str(self):
        q = self._qweb
        for value in (True, False, None, 0, 1):
            self.assertFalse(q._is_debug_assets(value), repr(value))

    def test_get_asset_links_survives_bool_debug(self):
        self.assertEqual(
            self._qweb._get_asset_links(
                "web.assets_web", css=False, js=False, debug=True
            ),
            [],
        )

    def test_link_to_node_stylesheet_is_text_css(self):
        for path in ["/x/a.css", "/x/a.scss", "/x/a.sass"]:
            tag, attrs = self._qweb._link_to_node(path)
            self.assertEqual(tag, "link", path)
            self.assertEqual(attrs["type"], "text/css", path)
            self.assertEqual(attrs["rel"], "stylesheet", path)

    def test_link_to_node_script_and_xml(self):
        tag, attrs = self._qweb._link_to_node("/x/a.js")
        self.assertEqual(
            (tag, attrs["type"], attrs.get("src")),
            ("script", "text/javascript", "/x/a.js"),
        )
        tag, attrs = self._qweb._link_to_node("/x/a.xml")
        self.assertEqual(
            (tag, attrs["type"], attrs.get("data-src")),
            ("script", "text/xml", "/x/a.xml"),
        )

    def test_import_map_url_breakdown(self):
        im = {
            "a": "/web/static/src/a.js",
            "b": "/web/assets/esm/bridges/deadbeef.js",
            "c": "data:text/javascript,1",
            "d": "/account/static/src/d.js",
        }
        self.assertEqual(self._qweb._get_import_map_url_counts(im), (2, 1, 1))
        self.assertEqual(self._qweb._get_import_map_url_counts({}), (0, 0, 0))

    def test_combine_no_templates_is_identity(self):
        self.assertEqual(
            self._qweb._combine_bundle_with_templates("CODE;", ""), "CODE;"
        )

    def test_combine_appends_templates(self):
        out = self._qweb._combine_bundle_with_templates("CODE;", "TPL;")
        self.assertIn("CODE;", out)
        self.assertIn("TPL;", out)
        self.assertNotIn("sourceMappingURL", out)

    def test_combine_keeps_sourcemap_directive_last(self):
        src = "CODE;\n//# sourceMappingURL=b.esm.js.map"
        out = self._qweb._combine_bundle_with_templates(src, "TPL;")
        last = out.rstrip("\n").splitlines()[-1]
        self.assertEqual(last, "//# sourceMappingURL=b.esm.js.map")
        self.assertEqual(out.count("sourceMappingURL"), 1)
        self.assertIn("TPL;", out)


@tagged("web_unit", "web_assets")
class TestNativeNodesDispatch(TransactionCase):
    BUNDLE = "web.assets_web"
    PRE = [("script", {"type": "importmap", "data-bundle": "t", "text": "{}"})]
    POST = [("script", {"type": "module", "text": "t"})]

    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    def _run(self, *, debug="", readonly=False, cached=None, impl=None):
        ir_qweb = self._qweb
        patches = [
            patch.object(
                type(ir_qweb),
                "_get_native_module_nodes_cached",
                **(cached or {"return_value": (self.PRE, self.POST)}),
            ),
            patch.object(
                type(ir_qweb),
                "_get_native_module_nodes_uncached",
                **(impl or {"return_value": (self.PRE, self.POST)}),
            ),
        ]
        if readonly:
            patches.append(patch.object(self.env.cr, "_readonly", True))
        with patches[0] as cached_mock, patches[1] as impl_mock:
            if readonly:
                with patches[2]:
                    result = ir_qweb._get_native_module_nodes(self.BUNDLE, debug=debug)
            else:
                result = ir_qweb._get_native_module_nodes(self.BUNDLE, debug=debug)
        return result, cached_mock, impl_mock

    def test_readwrite_prod_uses_cache(self):
        result, cached_mock, impl_mock = self._run()
        self.assertEqual(result, (self.PRE, self.POST))
        cached_mock.assert_called_once()
        impl_mock.assert_not_called()

    def test_readonly_prod_uses_cache(self):
        result, cached_mock, impl_mock = self._run(readonly=True)
        self.assertEqual(result, (self.PRE, self.POST))
        cached_mock.assert_called_once()
        impl_mock.assert_not_called()

    def test_debug_assets_bypasses_cache(self):
        for readonly in (False, True):
            with self.subTest(readonly=readonly):
                result, cached_mock, impl_mock = self._run(
                    debug="assets", readonly=readonly
                )
                self.assertEqual(result, (self.PRE, self.POST))
                cached_mock.assert_not_called()
                impl_mock.assert_called_once()

    def test_forced_fallback_is_cached_under_its_own_key(self):
        """It used to bypass the ormcache, so every request rebuilt the whole
        per-file answer -- measured at 0.053 s and 19 `AssetsBundle`
        constructions against 0.000 s and 0 for a cache hit, for as long as the
        override (or the circuit-breaker cooldown, up to 600 s) lasted.  The
        degraded render is now a cache entry of its own, keyed `esbuild_ok`."""
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.force_fallback_bundles", self.BUNDLE
        )
        self.addCleanup(
            self.env["ir.config_parameter"].sudo().set_param,
            "web.esbuild.force_fallback_bundles",
            "",
        )
        self.env.registry.clear_cache("stable")
        for readonly in (False, True):
            with self.subTest(readonly=readonly):
                result, cached_mock, impl_mock = self._run(readonly=readonly)
                self.assertEqual(result, (self.PRE, self.POST))
                cached_mock.assert_called_once()
                self.assertFalse(
                    cached_mock.call_args.kwargs["esbuild_ok"],
                    msg="the fallback must be cached under esbuild_ok=False",
                )
                impl_mock.assert_not_called()

    def test_decline_falls_back_uncached(self):
        for readonly in (False, True):
            with self.subTest(readonly=readonly):
                result, cached_mock, impl_mock = self._run(
                    readonly=readonly,
                    cached={"side_effect": _EsmFallbackError},
                )
                self.assertEqual(result, (self.PRE, self.POST))
                cached_mock.assert_called_once()
                impl_mock.assert_called_once()


@tagged("web_unit", "web_assets")
class TestEsbuildLockCursor(TransactionCase):
    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    def test_readwrite_yields_a_dedicated_cursor(self):
        """It used to hand back `self.env.cr`.  `pg_try_advisory_xact_lock`
        releases at transaction end, so the lock then outlived the compile by
        the whole rest of the request, and every worker that wanted the same
        bundle meanwhile fell into the per-file branch -- a different page, not
        just a slower one."""
        self.assertFalse(self.env.cr.readonly)
        with self._qweb._get_esbuild_lock_cursor("b.x") as lock_cr:
            self.assertIsNotNone(lock_cr)
            self.assertIsNot(
                lock_cr,
                self.env.cr,
                msg="the lock must not be taken on the request transaction",
            )
            lock_cr.execute("SELECT pg_backend_pid()")
            self.assertNotEqual(
                lock_cr.fetchone()[0],
                self._backend_pid(),
                msg="a dedicated cursor means a separate backend",
            )

    def _backend_pid(self):
        self.env.cr.execute("SELECT pg_backend_pid()")
        return self.env.cr.fetchone()[0]

    def test_the_lock_is_released_when_the_block_exits(self):
        held = "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
        self.env.cr.execute(held)
        before = self.env.cr.fetchone()[0]
        with self._qweb._get_esbuild_lock_cursor("b.x") as lock_cr:
            self.assertTrue(self._qweb._acquire_esbuild_lock("b.x", cr=lock_cr))
        self.env.cr.execute(held)
        self.assertEqual(
            self.env.cr.fetchone()[0],
            before,
            msg="the advisory lock must not outlive the compile",
        )

    def test_readonly_test_cursor_yields_none(self):
        with patch.object(self.env.cr, "_readonly", True):
            with self._qweb._get_esbuild_lock_cursor("b.x") as lock_cr:
                self.assertIsNone(lock_cr)

    def test_acquire_lock_runs_on_the_given_cursor(self):
        executed = []

        fake_cr = SimpleNamespace(
            execute=lambda sql, params=None: executed.append(sql),
            fetchone=lambda: (True,),
        )
        got = self._qweb._acquire_esbuild_lock("b.x", cr=fake_cr)
        self.assertTrue(got)
        self.assertEqual(len(executed), 1)
        self.assertIn("pg_try_advisory_xact_lock", executed[0])

    def test_readonly_run_esbuild_skips_lock_and_build(self):
        ir_qweb = self._qweb
        with (
            patch.object(self.env.cr, "_readonly", True),
            patch.object(
                type(ir_qweb),
                "_acquire_esbuild_lock",
                side_effect=AssertionError("lock must not be attempted"),
            ),
            patch.object(
                AssetsBundle,
                "esbuild_native_bundle",
                side_effect=AssertionError("esbuild must not run"),
            ),
        ):
            result, child_bundles = ir_qweb._compile_with_esbuild_locked(
                "web.assets_web", SimpleNamespace(), None
            )
        self.assertEqual(result.code, "")
        self.assertEqual(child_bundles, [])


@tagged("web_unit", "web_assets")
class TestProdNodesDeclineNotCached(TransactionCase):
    BUNDLE = "g4.decline.bundle"

    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    def _fake_bundle(self):
        return SimpleNamespace(
            name=self.BUNDLE,
            generate_esm_template_bundle=lambda use_import: "",
        )

    def test_decline_raises_instead_of_inlining(self):
        ir_qweb = self._qweb
        with patch.object(
            type(ir_qweb),
            "_save_esm_attachment",
            side_effect=ReadOnlySqlTransaction("no writable cursor"),
        ):
            with (
                self.assertLogs(
                    f"{ASSET_ROOT}.attach", level=logging.WARNING
                ) as caught,
                self.assertRaises(_EsmFallbackError),
            ):
                ir_qweb._get_esm_nodes_prod(
                    self.BUNDLE,
                    self._fake_bundle(),
                    EsbuildResult("CODE;", None, None),
                    None,
                    [],
                    raise_on_decline=True,
                )
        self.assertIn("declined=True", caught.output[0])

    def test_uncached_rerun_still_inlines(self):
        ir_qweb = self._qweb
        with patch.object(
            type(ir_qweb),
            "_save_esm_attachment",
            side_effect=ReadOnlySqlTransaction("no writable cursor"),
        ):
            with self.assertLogs(
                f"{ASSET_ROOT}.attach", level=logging.WARNING
            ) as caught:
                _pre, post = ir_qweb._get_esm_nodes_prod(
                    self.BUNDLE,
                    self._fake_bundle(),
                    EsbuildResult("CODE;", None, None),
                    None,
                    [],
                )
        self.assertIn("declined=False", caught.output[0])
        module_nodes = [
            attrs
            for tag, attrs in post
            if tag == "script" and attrs.get("type") == "module"
        ]
        self.assertEqual(len(module_nodes), 1)
        self.assertEqual(module_nodes[0].get("text"), "CODE;")
        self.assertNotIn("src", module_nodes[0])


@tagged("web_unit", "web_assets")
class TestImportMapMergeHelpers(TransactionCase):
    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    BUNDLE = "web.assets_unit_tests_setup"
    COLLIDING = "@odoo/hoot"
    DECOY = "/web/static/lib/hoot/decoy_that_is_not_served.js"

    def _rendered_import_map(self, debug):
        pre, _post = self._qweb._get_native_module_nodes(self.BUNDLE, debug=debug)
        for tag, attrs in pre:
            if tag == "script" and attrs.get("type") == "importmap":
                return json.loads(attrs["text"])["imports"]
        return {}

    def test_the_page_entry_outranks_the_external_table(self):
        own = self._qweb._get_native_module_data_cached(
            self.BUNDLE,
            assets_params=self.env["ir.asset"]._prepare_assets_params(),
        )["import_map"]
        self.assertIn(
            self.COLLIDING,
            own,
            f"{self.BUNDLE} no longer claims {self.COLLIDING}; pick another "
            "colliding specifier or drop this test",
        )
        externals = dict(self._qweb._external_libs())
        externals[self.COLLIDING] = self.DECOY
        with patch.object(
            type(self._qweb), "_external_libs", staticmethod(lambda: externals)
        ):
            self.env.registry.clear_cache("assets")
            rendered = self._rendered_import_map("assets")
        self.env.registry.clear_cache("assets")
        self.assertEqual(
            rendered.get(self.COLLIDING),
            own[self.COLLIDING],
            "the external table overrode where the page actually serves the module",
        )

    def test_the_external_table_is_the_floor(self):
        externals = dict(self._qweb._external_libs())
        self.assertIn("luxon", externals)
        rendered = self._rendered_import_map("assets")
        self.assertEqual(rendered.get("luxon"), externals["luxon"])

    @staticmethod
    def _fake_registry(**overrides):
        reg = SimpleNamespace(
            dynamic_children={},
            dynamic_bundle_names=set(),
            import_map_includes={},
            secondary_import_map_includes={},
            runtime_bundle_names=set(),
        )
        for key, value in overrides.items():
            setattr(reg, key, value)
        children = {child for kids in reg.dynamic_children.values() for child in kids}
        reg.dynamic_bundle_names = set(reg.dynamic_bundle_names) | children
        reg.runtime_bundle_names = set(reg.runtime_bundle_names) | children
        return reg

    def test_the_fake_registry_carries_every_real_field(self):
        missing = set(EsmRegistry._fields) - set(vars(self._fake_registry()))
        self.assertEqual(
            sorted(
                missing
                - {
                    "bundles",
                    "standalone_bundles",
                    "external_libs",
                    "import_map_included_bundles",
                    "secondary_parents",
                    "secondary_bundle_names",
                }
            ),
            [],
            "the fake registry lacks a field the production code may read",
        )

    @staticmethod
    def _fake_ab(name, import_map, bridge_import_map=None, discovered=()):
        def get_native_module_data(with_bridges=True):
            data = {"import_map": dict(import_map)}
            if bridge_import_map is not None:
                data["bridge_import_map"] = dict(bridge_import_map)
            return data

        return SimpleNamespace(
            name=name,
            get_native_module_data=get_native_module_data,
            _bridges=SimpleNamespace(
                _discover_bridge_specifiers=lambda specs, ext, modules=None: (
                    list(discovered),
                    set(),
                ),
            ),
        )

    def _patch_registry(self, reg):
        return patch(
            "odoo.addons.base.models.ir_qweb_assets.esm_registry",
            return_value=reg,
        )

    def test_dynamic_child_construction_policy(self):
        reg = self._fake_registry(
            dynamic_children={"parent": ("child.dyn", "child.plain")},
        )
        built = []

        def fake_get_asset_bundle(bundle, js, css, debug_assets, assets_params):
            built.append((bundle, debug_assets))
            return SimpleNamespace(name=bundle)

        ir_qweb = self._qweb
        with (
            self._patch_registry(reg),
            patch.object(
                type(ir_qweb),
                "_get_asset_bundle",
                side_effect=fake_get_asset_bundle,
            ),
        ):
            ir_qweb._get_dynamic_child_bundles("parent", None, debug_assets=False)
            self.assertEqual(built, [("child.dyn", True), ("child.plain", True)])
            built.clear()
            ir_qweb._get_dynamic_child_bundles("parent", None, debug_assets=True)
            self.assertEqual(built, [("child.dyn", True), ("child.plain", True)])

    def _child_pair(self):
        dyn = self._fake_ab("child.dyn", {"@a/x": "/a/static/src/x.js"})
        plain = self._fake_ab(
            "child.plain",
            {"@b/y": "/b/static/src/y.js", "@a/x": "/b/override.js"},
        )
        return dyn, plain

    def test_merge_child_import_maps(self):
        reg = self._fake_registry(dynamic_bundle_names={"child.dyn"})
        dyn, plain = self._child_pair()
        import_map = {}
        with self._patch_registry(reg):
            dynamic, specs = self._qweb._merge_child_import_maps(
                import_map, [dyn, plain]
            )
        self.assertEqual(dynamic, [dyn])
        self.assertEqual(
            import_map,
            {"@a/x": "/b/override.js", "@b/y": "/b/static/src/y.js"},
        )
        self.assertEqual(specs, {"@a/x", "@b/y"})

    def test_child_specifiers_are_collected_without_being_mapped(self):
        reg = self._fake_registry(dynamic_bundle_names={"child.dyn"})
        dyn, plain = self._child_pair()
        import_map = {"@keep/me": "/keep/static/src/me.js"}
        with self._patch_registry(reg):
            dynamic, specs = self._qweb._merge_child_import_maps(
                import_map, [dyn, plain], map_specifiers=False
            )
        self.assertEqual(dynamic, [dyn])
        self.assertEqual(specs, {"@a/x", "@b/y"})
        self.assertEqual(
            import_map,
            {"@keep/me": "/keep/static/src/me.js"},
            "a dynamic child's specifiers were mapped on the parent page",
        )

    def test_merge_includes_production_policy(self):
        reg = self._fake_registry(import_map_includes={"parent": ("inc.a",)})
        ir_qweb = self._qweb
        with (
            self._patch_registry(reg),
            patch.object(
                type(ir_qweb),
                "_get_native_module_data_cached",
                return_value={
                    "import_map": {"@inc/mod": "/inc/static/src/mod.js"},
                    "bridge_import_map": {
                        "@parent/kept": "/web/assets/esm/bridges/aa.js",
                        "@child/direct": "/web/assets/esm/bridges/bb.js",
                    },
                },
            ) as cached_mock,
        ):
            import_map = {"@child/direct": "/child/static/src/direct.js"}
            include_names = ir_qweb._merge_include_import_maps(
                "parent",
                import_map,
                None,
                debug_assets=False,
                resolve_bridges=False,
            )
        self.assertEqual(include_names, ("inc.a",))
        cached_mock.assert_called_once()
        self.assertEqual(import_map["@inc/mod"], "/inc/static/src/mod.js")
        self.assertEqual(import_map["@parent/kept"], "/web/assets/esm/bridges/aa.js")
        self.assertEqual(import_map["@child/direct"], "/child/static/src/direct.js")

    def test_merge_includes_debug_policy_resolves_bridges(self):
        reg = self._fake_registry(import_map_includes={"parent": ("inc.a",)})
        include_ab = self._fake_ab(
            "inc.a",
            {"@inc/mod": "/inc/static/src/mod.js"},
            discovered=["@web/core/registry", "unresolvable-bare"],
        )
        ir_qweb = self._qweb
        with (
            self._patch_registry(reg),
            patch.object(
                type(ir_qweb),
                "_get_asset_bundle",
                return_value=include_ab,
            ),
        ):
            import_map = {
                "unresolvable-bare": "data:text/javascript,shim",
            }
            ir_qweb._merge_include_import_maps(
                "parent",
                import_map,
                None,
                debug_assets=True,
                resolve_bridges=True,
            )
        self.assertEqual(import_map["@inc/mod"], "/inc/static/src/mod.js")
        self.assertEqual(
            import_map["@web/core/registry"], "/web/static/src/core/registry.js"
        )
        self.assertNotIn("unresolvable-bare", import_map)

    def test_merge_secondary_is_first_wins(self):
        reg = self._fake_registry(secondary_import_map_includes={"parent": ("sec.a",)})
        sec_ab = self._fake_ab(
            "sec.a",
            {
                "@parent/mod": "/web/assets/esm/bridges/shim.js",
                "@sec/new": "/sec/static/src/new.js",
            },
        )
        ir_qweb = self._qweb
        with (
            self._patch_registry(reg),
            patch.object(type(ir_qweb), "_get_asset_bundle", return_value=sec_ab),
        ):
            import_map = {"@parent/mod": "/parent/static/src/mod.js"}
            ir_qweb._merge_secondary_import_maps(
                "parent", import_map, None, debug_assets=False
            )
        self.assertEqual(
            import_map,
            {
                "@parent/mod": "/parent/static/src/mod.js",
                "@sec/new": "/sec/static/src/new.js",
            },
        )

    def test_resolve_bridge_specifiers_matrix(self):
        qweb = self._qweb
        base_map = {
            "@a/direct": "/a/static/src/direct.js",
            "@b/shimmed": "/web/assets/esm/bridges/cc.js",
            "@c/data": "data:text/javascript,x",
            "bare-unresolvable": "/web/assets/esm/bridges/dd.js",
        }

        import_map = dict(base_map)
        with self.assertLogs(f"{ASSET_ROOT}.bridge", level=logging.WARNING) as captured:
            resolved = qweb._add_import_map_bridge_urls(
                import_map,
                ["@a/direct", "@b/shimmed", "@c/data", "bare-unresolvable", "@d/new"],
                drop_unresolved=True,
            )
        self.assertEqual(len(captured.output), 3)
        self.assertEqual(import_map["@a/direct"], "/a/static/src/direct.js")
        self.assertNotIn("@a/direct", resolved)
        self.assertEqual(import_map["@b/shimmed"], "/b/static/src/shimmed.js")
        self.assertEqual(import_map["@c/data"], "/c/static/src/data.js")
        self.assertEqual(import_map["@d/new"], "/d/static/src/new.js")
        self.assertNotIn("bare-unresolvable", import_map)

        import_map = dict(base_map)
        qweb._add_import_map_bridge_urls(
            import_map,
            ["bare-unresolvable"],
            drop_unresolved=False,
        )
        self.assertEqual(
            import_map["bare-unresolvable"], "/web/assets/esm/bridges/dd.js"
        )


@tagged("web_unit", "web_assets")
class TestGeneratedAssetDomains(TransactionCase):
    def _make(self, name, url):
        return (
            self.env["ir.attachment"]
            .sudo()
            .create(
                {
                    "name": name,
                    "url": url,
                    "type": "binary",
                    "res_model": "ir.ui.view",
                    "res_id": 0,
                    "public": True,
                    "raw": b"g4-domain-test",
                }
            )
        )

    def test_reuse_only_accepts_a_row_the_controller_would_serve(self):
        """The reuse check in `_save_esm_attachment` used to match on `url` and
        `public` alone, while `/web/assets/esm/<unique>/<filename>` also
        requires `res_model`, `res_id` and `create_uid`.  A row differing in
        `create_uid` -- a `group_system` user duplicating the attachment, a
        restore, a migration -- therefore satisfied reuse and not serving: the
        build was skipped, no row was written, and the `<script src>` the page
        emitted answered 404, cached in the `assets` ormcache and invisible to
        the GC, which filters on `create_uid` too."""
        IrQweb = self.env["ir.qweb"]
        Attachment = self.env["ir.attachment"].sudo()
        content = "export const reuse_probe = 1;\n"
        url = f"/web/assets/esm/{cache_hash(content.encode())[:16]}/g4.reuse.esm.js"
        Attachment.search([("url", "=", url)]).unlink()

        # Correct in every respect but the author.
        admin = self.env.ref("base.user_admin")
        self.env["ir.attachment"].with_user(admin).create(
            {
                "name": "g4.reuse.esm.js",
                "url": url,
                "type": "binary",
                "res_model": "ir.ui.view",
                "res_id": 0,
                "public": True,
                "raw": content.encode(),
                "mimetype": "text/javascript",
            }
        )
        self.env.flush_all()

        self.assertEqual(IrQweb._save_esm_attachment("g4.reuse", content), url)
        servable = Attachment.search(Attachment._generated_asset_domain(url))
        self.assertTrue(
            servable,
            "reuse returned a URL the serving controller would answer 404 for",
        )

    def test_the_single_row_form_is_the_serving_predicate(self):
        row = self._make("g4.one.esm.js", "/web/assets/esm/feedface/g4.one.esm.js")
        Attachment = self.env["ir.attachment"].sudo()
        self.assertEqual(
            Attachment.search(Attachment._generated_asset_domain(row.url)),
            row,
        )
        row.create_uid = self.env.ref("base.user_admin").id
        self.env.flush_all()
        self.assertFalse(
            Attachment.search(Attachment._generated_asset_domain(row.url)),
            "a row this framework did not author is not a generated asset",
        )

    def test_esm_domain_narrows_generated_domain(self):
        Attachment = self.env["ir.attachment"]
        esm = self._make(
            "g4.bundle.esm.js", "/web/assets/esm/deadbeef/g4.bundle.esm.js"
        )
        sourcemap = self._make(
            "g4.bundle.esm.js.map", "/web/assets/esm/deadbeef/g4.bundle.esm.js.map"
        )
        meta = self._make(
            "g4.bundle.meta.json", "/web/assets/esm/deadbeef/g4.bundle.meta.json"
        )
        bridge = self._make("g4-shim.js", "/web/assets/esm/bridges/cafebabe.js")
        classic = self._make(
            "web.assets_g4.min.js", "/web/assets/1/web.assets_g4.min.js"
        )
        everything = esm | sourcemap | meta | bridge | classic

        generated = Attachment.sudo().search(Attachment._generated_asset_domain())
        self.assertEqual(
            everything & generated,
            everything,
            "the broad domain must match every generated row, classic included",
        )

        esm_only = Attachment.sudo().search(Attachment._esm_generated_asset_domain())
        self.assertEqual(everything & esm_only, esm | sourcemap | meta | bridge)
        self.assertNotIn(
            classic,
            esm_only,
            "classic .min.js bundles have their own rotation and must never "
            "match the ESM-narrowed domain",
        )


@tagged("web_unit", "web_assets")
class TestSecondaryBundleSingletons(TransactionCase):
    def _shared(self):
        return self.env["ir.qweb"]._get_secondary_shared_specs("web.assets_tests", None)

    def test_safe_set_contains_core_singletons(self):
        shared = self._shared()
        for spec in ("@web/core/browser/browser", "@web/env"):
            self.assertIn(
                spec,
                shared,
                msg=f"{spec} must be shared with the parent app bundle, not inlined",
            )

    def test_safe_set_subset_of_every_installed_parent(self):
        from odoo.tools.assets.esm_registry import esm_registry

        IrQweb = self.env["ir.qweb"]
        shared = self._shared()
        self.assertTrue(shared, "expected a non-empty shared set for web.assets_tests")
        parents = esm_registry().secondary_parents.get("web.assets_tests", ())
        checked = 0
        for parent in parents:
            ab = IrQweb._get_asset_bundle(
                parent, js=True, css=False, debug_assets=False, assets_params=None
            )
            specs = set(ab.get_native_module_data(with_bridges=False)["import_map"])
            if not specs:
                continue
            checked += 1
            self.assertLessEqual(
                shared,
                specs,
                msg=(
                    f"shared specs not all registered by {parent!r}: "
                    f"{sorted(shared - specs)} — that page would get an "
                    "unresolvable alias"
                ),
            )
        self.assertGreater(checked, 0, "no installed parent bundle to check against")

    def test_non_secondary_bundle_has_no_shared_specs(self):
        self.assertEqual(
            self.env["ir.qweb"]._get_secondary_shared_specs("web.assets_web", None),
            frozenset(),
        )

    def test_stub_sources_read_the_loader(self):
        stubs = self.env["ir.qweb"]._get_secondary_parent_stubs(
            "web.assets_tests", None
        )
        self.assertIn("@web/core/browser/browser", stubs)
        browser_stub = stubs["@web/core/browser/browser"]
        self.assertIn(
            'odoo.loader.modules.get("@web/core/browser/browser")',
            browser_stub,
        )
        self.assertIn("_m === undefined", browser_stub)
        self.assertIn("= _m.browser;", browser_stub)
        self.assertIn(" as browser", browser_stub)


@tagged("web_unit", "web_assets")
class TestSecondaryBundleSingletonsBuild(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        odoo_root = Path(odoo.__path__[0]).parent
        cls.esbuild = shutil.which("esbuild") or shutil.which(
            "esbuild", path=str(odoo_root / "node_modules" / ".bin")
        )

    def setUp(self):
        super().setUp()
        if not self.esbuild:
            self.skipTest("esbuild binary not found (run 'npm install').")

    def test_browser_is_aliased_not_inlined(self):
        IrQweb = self.env["ir.qweb"]
        ab = IrQweb._get_asset_bundle(
            "web.assets_tests",
            js=True,
            css=False,
            debug_assets=False,
            assets_params=None,
        )
        stubs = IrQweb._get_secondary_parent_stubs("web.assets_tests", None)
        self.assertTrue(stubs, "web.assets_tests should have shared-specifier stubs")

        inlined = ab.esbuild_native_bundle().code
        aliased = ab.esbuild_native_bundle(secondary_parent_stubs=stubs).code

        sig = "window.fetch.bind(window)"
        self.assertIn(sig, inlined, "control: the unaliased build inlines browser.js")
        self.assertNotIn(
            sig,
            aliased,
            "aliased build must NOT inline a second copy of browser.js",
        )
        self.assertIn(
            'odoo.loader.modules.get("@web/core/browser/browser")',
            aliased,
            "aliased build must reach browser via the loader singleton",
        )


@tagged("web_unit", "web_assets")
class TestLazyBundleRelativeImports(TransactionCase):
    @staticmethod
    def _module(module_path, raw_content, url=""):
        return SimpleNamespace(
            module_path=module_path,
            raw_content=raw_content,
            url=url or module_path.replace("@", "/", 1) + ".js",
        )

    def test_in_bundle_relative_import_passes(self):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        modules = [
            self._module(
                "@mod/dir/a",
                'import { b } from "./b.js";\nimport { c } from "../c";\n',
            ),
            self._module("@mod/dir/b", "export const b = 1;\n"),
            self._module("@mod/c", "export const c = 1;\n"),
        ]
        self.assertEqual(find_escaping_relative_imports(modules), [])

    def test_escaping_relative_import_is_reported(self):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        modules = [
            self._module(
                "@mod/dir/a",
                'import { svc } from "../../service.js";\n',
            ),
        ]
        self.assertEqual(
            find_escaping_relative_imports(modules),
            [("@mod/dir/a", "../../service.js", "@mod/service")],
        )

    def test_index_long_form_is_a_member(self):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        modules = [
            self._module(
                "@mod/a",
                'import { x } from "./widget/index.js";\n',
            ),
            self._module(
                "@mod/widget",
                "export const x = 1;\n",
                url="/mod/static/src/widget/index.js",
            ),
        ]
        self.assertEqual(find_escaping_relative_imports(modules), [])

    def test_bare_specifiers_are_ignored(self):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        modules = [
            self._module(
                "@mod/a",
                'import { registry } from "@web/core/registry";\n',
            ),
        ]
        self.assertEqual(find_escaping_relative_imports(modules), [])

    def test_relative_import_from_an_index_module_is_a_member(self):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        modules = [
            self._module(
                "@mod/chart",
                'import "./plugins/core.js";\nexport * from "./menu/link.js";\n',
                url="/mod/static/src/chart/index.js",
            ),
            self._module(
                "@mod/chart/plugins/core",
                "export const core = 1;\n",
                url="/mod/static/src/chart/plugins/core.js",
            ),
            self._module(
                "@mod/chart/menu/link",
                "export const link = 1;\n",
                url="/mod/static/src/chart/menu/link.js",
            ),
        ]
        self.assertEqual(find_escaping_relative_imports(modules), [])

    def test_relative_import_into_static_lib_is_a_member(self):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        modules = [
            self._module(
                "@mod/passkey_lib",
                'import { start } from "../lib/vendored.js";\n'
                "export const lib = { start };\n",
                url="/mod/static/src/passkey_lib.js",
            ),
            self._module(
                "@mod/../lib/vendored",
                "export function start() {}\n",
                url="/mod/static/lib/vendored.js",
            ),
        ]
        self.assertEqual(find_escaping_relative_imports(modules), [])

    def test_index_module_escaping_its_directory_is_still_reported(self):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        modules = [
            self._module(
                "@mod/chart",
                'import { svc } from "../service.js";\n',
                url="/mod/static/src/chart/index.js",
            ),
        ]
        self.assertEqual(
            find_escaping_relative_imports(modules),
            [("@mod/chart", "../service.js", "@mod/service")],
        )

    def test_payload_guard_raises_with_details(self):
        from odoo.addons.base.models.ir_qweb_assets import EsbuildBundleError

        fake_bundle = SimpleNamespace(
            name="mod.lazy_bundle",
            native_modules=[
                self._module(
                    "@mod/dir/a",
                    'import { svc } from "../../service.js";\n',
                ),
            ],
        )
        with self.assertRaises(EsbuildBundleError) as caught:
            self.env["ir.qweb"]._check_lazy_bundle_relative_imports(fake_bundle)
        message = str(caught.exception)
        self.assertIn("mod.lazy_bundle", message)
        self.assertIn("@mod/dir/a", message)
        self.assertIn("../../service.js", message)
        self.assertIn("@mod/service", message)


@tagged("post_install", "-at_install", "web_assets")
class TestDynamicBundleIntegrity(TransactionCase):
    def _dynamic_bundle_names(self):
        from odoo.tools.assets.esm_registry import esm_registry

        registry = esm_registry()
        names = sorted(registry.runtime_bundle_names)
        self.assertTrue(
            names,
            "the ESM registry declares no runtime bundle at all — the "
            "sweep would pass having checked nothing",
        )
        self.assertEqual(
            sorted(registry.dynamic_bundle_names - registry.runtime_bundle_names),
            [],
            "a dynamic child outside the runtime set: the route would decline "
            "to serve it as ESM while this sweep verified it",
        )
        return names

    def _assert_sweep_saw_assets(self, populated, names):
        self.assertGreater(
            populated,
            1,
            f"only {populated} of {len(names)} dynamic bundles resolved to "
            "any file. Either no module owning one is installed, or this "
            "ran before their assets were queryable — - either way the "
            "sweep proves nothing. Widen INSTALL in asset_lint.yml, or "
            "check that this class still runs post_install.",
        )

    FRONTEND_REACH_EXEMPT = set()

    def test_a_frontend_loadable_bundle_reaches_nothing_backend_only(self):
        registry = esm_registry()
        IrQweb = self.env["ir.qweb"]
        parent_name = "web.assets_frontend"
        parent = IrQweb._get_asset_bundle(
            parent_name, js=True, css=False, debug_assets=True, assets_params=None
        )
        available = {a.module_path for a in parent.native_modules} | set(
            external_libs()
        )
        self.assertTrue(available, f"{parent_name} resolved to nothing")

        children = [
            child
            for parent_bundle, kids in registry.dynamic_children.items()
            for child in kids
            if parent_bundle == parent_name
        ]
        self.assertTrue(children, f"no dynamic child declared on {parent_name}")

        unreachable = []
        for child_name in sorted(children):
            child = IrQweb._get_asset_bundle(
                child_name, js=True, css=False, debug_assets=True, assets_params=None
            )
            if not child.native_modules:
                continue
            own = {a.module_path for a in child.native_modules}
            discovered, _ext = child._bridges._discover_bridge_specifiers(
                own, set(external_libs())
            )
            unreachable.extend(
                f"{child_name} -> {spec}"
                for spec in sorted(set(discovered) - available)
                if (child_name, spec) not in self.FRONTEND_REACH_EXEMPT
            )
        self.assertFalse(
            unreachable,
            f"lazy children of {parent_name} needing modules that page never "
            f"registers; their bridges resolve to undefined:\n  "
            + "\n  ".join(unreachable),
        )

    def test_every_installed_dynamic_bundle_is_self_contained(self):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        IrQweb = self.env["ir.qweb"]
        names = self._dynamic_bundle_names()
        escapes = []
        populated = 0
        for bundle_name in names:
            asset_bundle = IrQweb._get_asset_bundle(
                bundle_name,
                js=True,
                css=False,
                debug_assets=True,
                assets_params=None,
            )
            populated += bool(asset_bundle.native_modules)
            escapes.extend(
                (bundle_name, *escape)
                for escape in find_escaping_relative_imports(
                    asset_bundle.native_modules
                )
            )
        self._assert_sweep_saw_assets(populated, names)
        self.assertFalse(
            escapes,
            "Per-file-served bundles with relative imports escaping the "
            f"bundle (use the bare '@addon/...' specifier instead): {escapes}",
        )

    def test_every_installed_dynamic_bundle_serves_a_payload(self):
        IrQweb = self.env["ir.qweb"]
        names = self._dynamic_bundle_names()
        failures = []
        populated = 0
        for bundle_name in names:
            try:
                payload = IrQweb._get_esm_bundle_payload(
                    bundle_name, debug_assets=False
                )
            except Exception as exc:
                failures.append(f"{bundle_name}: {type(exc).__name__}: {exc}")
                continue
            populated += bool(payload["specifiers"])
        self.assertFalse(
            failures,
            "Dynamic child bundles whose /web/bundle payload does not "
            f"build; each is an HTTP 500 on the route: {failures}",
        )
        self._assert_sweep_saw_assets(populated, names)


@tagged("web_unit", "web_assets")
class TestTestSatelliteGating(TransactionCase):
    BUNDLE = "web.assets_frontend"

    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    def _rendered_import_map(self, debug=""):
        self.env.registry.clear_cache("assets")
        pre, _post = self._qweb._get_native_module_nodes(self.BUNDLE, debug=debug)
        self.env.registry.clear_cache("assets")
        for tag, attrs in pre:
            if tag == "script" and attrs.get("type") == "importmap":
                return json.loads(attrs["text"])["imports"]
        return {}

    @staticmethod
    def _test_specifiers(import_map):
        return sorted(s for s in import_map if "/../tests/" in s)

    def test_condition_matches_the_template(self):
        rendered = self._qweb._has_esm_test_satellites
        with odoo.tools.config.patch(test_enable=False):
            for debug in ("", None, False, "1", "assets", "assets,qweb"):
                self.assertFalse(rendered(debug), f"debug={debug!r}")
            for debug in ("tests", "assets,tests", "1,tests"):
                self.assertTrue(rendered(debug), f"debug={debug!r}")
        with odoo.tools.config.patch(test_enable=True):
            self.assertTrue(rendered(""))

    def test_prod_page_carries_no_test_specifiers(self):
        secondaries = esm_registry().secondary_import_map_includes
        self.assertIn(
            self.BUNDLE,
            secondaries,
            f"{self.BUNDLE} no longer declares secondary_import_map_includes; "
            "pick another parent or drop this test",
        )
        with odoo.tools.config.patch(test_enable=False):
            import_map = self._rendered_import_map(debug="")
        self.assertTrue(import_map, "the bundle rendered no import map at all")
        self.assertEqual(
            self._test_specifiers(import_map),
            [],
            "test-bundle specifiers reached a production page's import map",
        )

    def test_test_mode_still_carries_them(self):
        with odoo.tools.config.patch(test_enable=False):
            without = self._rendered_import_map(debug="")
        with odoo.tools.config.patch(test_enable=True):
            with_them = self._rendered_import_map(debug="")
        self.assertTrue(
            self._test_specifiers(with_them),
            "test mode no longer merges the satellites; the guard over-fired",
        )
        self.assertLess(
            len(without),
            len(with_them),
            "gating the merge changed nothing — the guard is not wired",
        )


@tagged("web_unit", "web_assets")
class TestEsmPersistenceDegradation(TransactionCase):
    """A persistence failure must degrade to an inline `<script>`, never take
    the page render down."""

    def _node(self, exc, raise_on_decline=False):
        IrQweb = self.env["ir.qweb"]
        with patch.object(type(IrQweb), "_save_esm_attachment", side_effect=exc):
            return IrQweb._prepare_esm_script_node(
                "b.x", "export const x = 1;", {}, raise_on_decline=raise_on_decline
            )

    def test_a_readonly_cursor_inlines_the_code(self):
        tag, attrs = self._node(ReadOnlySqlTransaction("readonly"))
        self.assertEqual(tag, "script")
        self.assertEqual(attrs["text"], "export const x = 1;")
        self.assertNotIn("src", attrs)

    def test_any_other_persistence_failure_also_inlines(self):
        """This caught `ReadOnlySqlTransaction` alone, while
        `_save_esm_attachment_rows`' last-resort `create` runs on the request
        cursor outside its own `try` and can raise anything -- so a filestore
        or integrity error took down the whole page render, for a bundle whose
        code was in hand and inlineable."""
        for exc in (ValueError("filestore write failed"), OSError("ENOSPC")):
            with self.subTest(exc=type(exc).__name__):
                tag, attrs = self._node(exc)
                self.assertEqual(tag, "script")
                self.assertEqual(attrs["text"], "export const x = 1;")

    def test_a_declining_caller_still_gets_the_fallback_signal(self):
        for exc in (ReadOnlySqlTransaction("ro"), ValueError("boom")):
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(_EsmFallbackError):
                    self._node(exc, raise_on_decline=True)

    def test_both_decline_signals_share_one_contract(self):
        self.assertTrue(issubclass(_EsmFallbackError, _BuildDeclined))
        self.assertTrue(issubclass(_StandaloneBundleDeclined, _BuildDeclined))


@tagged("web_unit", "web_assets")
class TestEsmAttachmentRowsAreNotDuplicated(TransactionCase):
    def test_the_writing_cursor_re_checks_the_urls(self):
        """The reuse search runs on the request cursor and the rows are
        committed out of band, and every cursor here is `repeatable read` -- so
        a row another transaction committed after the snapshot is invisible to
        the check that decides whether to write it.  Re-reading on the cursor
        that writes closes the window to that transaction."""
        IrQweb = self.env["ir.qweb"]
        url = "/web/assets/esm/dup0/g4.dup.esm.js"
        self.env["ir.attachment"].sudo().search([("url", "=", url)]).unlink()
        vals = [{"url": url, "name": "g4.dup.esm.js"}, {"url": "/other", "name": "o"}]

        self.assertEqual(
            IrQweb._drop_rows_already_present(self.env.cr, vals),
            vals,
            "nothing is present yet, so nothing is dropped",
        )

        self.env["ir.attachment"].sudo().create(
            {
                "name": "g4.dup.esm.js",
                "url": url,
                "type": "binary",
                "res_model": "ir.ui.view",
                "res_id": 0,
                "public": True,
                "raw": b"x",
            }
        )
        self.env.flush_all()
        self.assertEqual(
            IrQweb._drop_rows_already_present(self.env.cr, vals),
            [vals[1]],
            "a URL already on the writing cursor must not be inserted again",
        )


@tagged("web_unit", "web_assets")
class TestPageScopedScriptsAreRenderedOnce(TransactionCase):
    """The import map and the loader shim are page-scoped, not bundle-scoped.
    Only the debug branch used to know that; the prod branch emitted both for
    every bundle, so a page with two prod bundles carried two copies of the
    shim (5,554 bytes each, the second inert)."""

    def _pre(self, bundle, specs):
        IrQweb = self.env["ir.qweb"]
        return [
            (
                "script",
                {
                    "type": "importmap",
                    "data-bundle": bundle,
                    "text": json.dumps({"imports": {s: f"/{s}" for s in specs}}),
                },
            ),
            IrQweb._prepare_loader_shim_node(bundle),
            ("script", {"type": "module", "src": "/x.js"}),
        ]

    def _kinds(self, nodes):
        IrQweb = self.env["ir.qweb"]
        return [
            "importmap"
            if IrQweb._is_import_map_node(n)
            else "shim"
            if IrQweb._is_loader_shim_node(n)
            else "other"
            for n in nodes
        ]

    def test_the_second_bundle_keeps_neither_the_map_nor_the_shim(self):
        IrQweb = self.env["ir.qweb"]
        req = SimpleNamespace()
        with patch.object(ir_qweb_assets, "request", req):
            first = IrQweb._dedup_request_page_scripts("a", self._pre("a", ["@a/one"]))
            second = IrQweb._dedup_request_page_scripts("b", self._pre("b", ["@a/one"]))
            self.assertTrue(getattr(req, "_esm_import_map_rendered", False))
        self.assertEqual(self._kinds(first), ["importmap", "shim", "other"])
        self.assertEqual(self._kinds(second), ["other"])

    def test_dropping_a_specifier_the_page_lacks_is_reported(self):
        """Dropping a later bundle's whole map is only sound if the map already
        rendered resolves everything this one needs, and nothing checked it."""
        IrQweb = self.env["ir.qweb"]
        logger = get_asset_logger("esm")
        with patch.object(ir_qweb_assets, "request", SimpleNamespace()):
            IrQweb._dedup_request_page_scripts("a", self._pre("a", ["@a/one"]))
            with self.assertLogs(logger.name, level="WARNING") as caught:
                IrQweb._dedup_request_page_scripts(
                    "b", self._pre("b", ["@a/one", "@b/only"])
                )
        self.assertIn("unresolvable=1", caught.output[0])
        self.assertIn("@b/only", caught.output[0])

    def test_a_superset_page_logs_no_warning(self):
        IrQweb = self.env["ir.qweb"]
        logger = get_asset_logger("esm")
        with patch.object(ir_qweb_assets, "request", SimpleNamespace()):
            IrQweb._dedup_request_page_scripts("a", self._pre("a", ["@a/one", "@b/x"]))
            with self.assertNoLogs(logger.name, level="WARNING"):
                IrQweb._dedup_request_page_scripts("b", self._pre("b", ["@a/one"]))
