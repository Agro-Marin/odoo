"""Tests for the ESM bundler pipeline refactor.

Covers the surfaces added by the UMD→ESM completion work:

    • Structured asset-pipeline logging (``odoo.assets.*``)
    • esbuild circuit breaker (cooldown + escalation + reset)
    • Admin override via ``web.esbuild.force_fallback_bundles``
    • Advisory-lock contention → graceful debug-mode fallback
    • Content-addressable attachment URLs (``/web/assets/esm/<hash>/``)
    • Metafile sidecar attachment

Most classes here use lightweight unit-level mocking so they run without
spawning esbuild; ``TestEsbuildIntegration`` and ``TestEsbuildSourceMaps``
are the exception — they invoke the real esbuild subprocess and skip
themselves when the binary isn't installed (``npm install``).
"""

import json
import logging
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from psycopg.errors import ReadOnlySqlTransaction

import odoo
from odoo.db import db_connect
from odoo.libs.asset_log import ASSET_ROOT, get_asset_logger, log_event
from odoo.libs.constants import ODOO_EXTERNAL_LIBS
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.assets.esbuild import EsbuildCompiler, EsbuildResult
from odoo.tools.assets.esm_graph import (
    _BridgeExportResolver,
    _scan_import_specifiers,
    discover_transitive_import_specifiers,
)

from odoo.addons.base.models.assetsbundle import AssetsBundle, _parse_odoo_module_header
from odoo.addons.base.models.ir_qweb_assets import _EsmFallbackError


@tagged("web_unit", "web_assets")
class TestAssetLogHelper(TransactionCase):
    """Structured-logging helper: logger hierarchy + event format."""

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
        # Event name leads, fields follow in insertion order.
        self.assertEqual(msg, "event=started bundle=web.assets_web modules=42")

    def test_log_event_suppressed_below_level(self):
        """``log_event`` must short-circuit when the target level is off.

        We verify the fast-path by patching ``Logger.log`` — if
        ``isEnabledFor`` returns False, the helper should not forward
        to the underlying logger at all (avoiding message formatting).
        """
        log = get_asset_logger("quiet")
        log.setLevel(logging.WARNING)
        with patch.object(log, "log") as mocked_log:
            log_event(log, logging.DEBUG, "skipped", k="v")
        mocked_log.assert_not_called()


@tagged("web_unit", "web_assets")
class TestEsbuildCircuitBreaker(TransactionCase):
    """Class-level circuit breaker for esbuild failures."""

    def setUp(self):
        super().setUp()
        self.IrQweb = self.env["ir.qweb"]
        # Isolate per-test state — the dict is a class attribute so a
        # leaked entry would bleed across tests.
        self.addCleanup(
            self.IrQweb._esbuild_cooldowns.clear,
        )

    def test_initial_state_allows(self):
        allow, reason = self.IrQweb._esbuild_circuit_state("web.test_bundle")
        self.assertTrue(allow)
        self.assertEqual(reason, "")

    def test_first_failure_opens_circuit(self):
        # ``_esbuild_circuit_record_failure`` is the production trip path and
        # emits ``WARNING event=circuit_open`` so operators see the breaker
        # fire. The test deliberately calls it, so we consume the warning
        # via ``assertLogs`` — both keeping the test log clean and asserting
        # the structured-logging contract (event name + ``reason`` field).
        with self.assertLogs(
            f"{ASSET_ROOT}.fallback", level=logging.WARNING
        ) as captured:
            self.IrQweb._esbuild_circuit_record_failure(
                "web.test_bundle",
                reason="SubprocessError",
            )
        self.assertEqual(len(captured.records), 1)
        self.assertIn("event=circuit_open", captured.records[0].getMessage())
        self.assertIn("reason=SubprocessError", captured.records[0].getMessage())
        allow, reason = self.IrQweb._esbuild_circuit_state("web.test_bundle")
        self.assertFalse(allow)
        self.assertEqual(reason, "SubprocessError")

    def test_second_consecutive_failure_escalates_cooldown(self):
        # Both record_failure calls emit ``WARNING circuit_open``; wrap both
        # in a single ``assertLogs`` so the test exits with the breaker
        # warnings consumed and the escalation visible in the captured log.
        with self.assertLogs(
            f"{ASSET_ROOT}.fallback", level=logging.WARNING
        ) as captured:
            self.IrQweb._esbuild_circuit_record_failure(
                "web.test_bundle",
                reason="Err1",
            )
            self.IrQweb._esbuild_circuit_record_failure(
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
        # record_failure trips the WARNING; record_success emits an INFO
        # ``circuit_close`` that ``assertLogs(level=WARNING)`` ignores.
        with self.assertLogs(
            f"{ASSET_ROOT}.fallback", level=logging.WARNING
        ) as captured:
            self.IrQweb._esbuild_circuit_record_failure(
                "web.test_bundle",
                reason="OnceFailed",
            )
            self.IrQweb._esbuild_circuit_record_success("web.test_bundle")
        self.assertEqual(len(captured.records), 1)
        self.assertIn("event=circuit_open", captured.records[0].getMessage())
        self.assertNotIn(
            (self.env.cr.dbname, "web.test_bundle"),
            self.IrQweb._esbuild_cooldowns,
        )
        allow, _ = self.IrQweb._esbuild_circuit_state("web.test_bundle")
        self.assertTrue(allow)

    def test_circuit_key_is_database_scoped(self):
        # The cooldown dict is a single process-global class attribute shared
        # by every registry in the worker, so its key MUST include the database
        # name — otherwise an esbuild failure for a bundle in one tenant would
        # open the breaker for the same bundle name in every other tenant.
        with self.assertLogs(f"{ASSET_ROOT}.fallback", level=logging.WARNING):
            self.IrQweb._esbuild_circuit_record_failure(
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
        # A failure recorded by another database (different db_name, same
        # bundle) must NOT open this database's breaker.
        self.IrQweb._esbuild_cooldowns[("some_other_db", "web.test_bundle")] = (
            time.monotonic() + 1e6,
            "OtherDbFail",
            1,
        )
        allow, reason = self.IrQweb._esbuild_circuit_state("web.test_bundle")
        self.assertFalse(
            allow,
            msg="this db's own failure should still gate it",
        )
        self.assertEqual(reason, "ScopeCheck")


@tagged("web_unit", "web_assets")
class TestEsbuildAdvisoryLock(TransactionCase):
    """Postgres advisory lock for serializing bundle compilation."""

    def test_lock_acquired_in_own_cursor(self):
        IrQweb = self.env["ir.qweb"]
        got = IrQweb._esbuild_try_acquire_lock("test.lock.alpha")
        self.assertTrue(got)

    def test_lock_rejects_other_cursor_while_held(self):
        IrQweb = self.env["ir.qweb"]
        self.assertTrue(IrQweb._esbuild_try_acquire_lock("test.lock.beta"))
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
        """``pg_advisory_xact_lock`` must release when the tx ends.

        TransactionCase forbids commits on ``self.env.cr``, so we drive
        the whole scenario through scratch connections: one takes the
        lock + commits, the other observes the lock is free afterwards.
        """
        dbname = self.env.cr.dbname
        key = "esbuild:test.lock.gamma"

        # Conn A: acquire, commit → lock auto-releases.
        with db_connect(dbname).cursor() as cr_a:
            cr_a.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (key,),
            )
            self.assertTrue(cr_a.fetchone()[0])
            cr_a.commit()

        # Conn B: should succeed now that A's tx has ended.
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
    """The ESM bundle URL is derived from the bundle's SHA256."""

    def test_identical_content_produces_identical_url(self):
        # We drive _save_esm_attachment directly so we can compare URLs
        # without spawning esbuild (no metafile/sourcemap siblings).
        ir_qweb = self.env["ir.qweb"]
        content = "export const x = 1;"
        url1 = ir_qweb._save_esm_attachment("test.cas.same", content)
        # Second call with identical content must hit the "reuse" branch
        # and return the same URL.
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
        # Stale-version deletion is DEFERRED (grace window): right after
        # the rebuild BOTH rows must exist so in-flight pages and
        # not-yet-signaled workers keep serving the old URL.
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
        # Once the superseded row ages past the grace window, the
        # autovacuum sweeps it and keeps only the newest version.
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
    """Metafile attachment is created alongside the bundle."""

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
class TestParentSelfBridge(TransactionCase):
    """The parent-self bridge exports an esbuild-compiled bundle's own
    specifiers to satellite bundles that load individual source files.

    Without this, the satellite bundle's files — fetched via relative
    paths — can't resolve bare specifiers (``@ai/foo``) that only exist
    inside the parent's esbuild output.  See
    ``AssetsBundle._build_parent_self_bridge`` for the mechanics.
    """

    def test_parent_self_bridge_covers_native_modules(self):
        setup_ab = self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_unit_tests_setup",
            js=True,
            css=False,
        )
        bridges = setup_ab._bridges._build_parent_self_bridge()
        # Every native module's specifier must have a bridge.  Sanity
        # check with a small sample rather than exhaustively enumerating.
        native_specs = {a.module_path for a in setup_ab.native_modules}
        self.assertGreater(len(bridges), 0)
        # Bridges normally resolve to content-addressable attachment URLs
        # under ``/web/assets/esm/bridges/<hash>.js`` (see
        # ``AssetsBundle._persist_bridge_shims``).  The pre-refactor inline
        # ``data:text/javascript,<urlencoded>`` URI format still exists,
        # but only as that helper's last-resort fallback when no writable
        # cursor is reachable at all.
        for spec, url in list(bridges.items())[:20]:
            self.assertIn(spec, native_specs)
            self.assertTrue(
                url.startswith("/web/assets/esm/bridges/"),
                msg=f"bridge for {spec} is not an attachment URL: {url[:80]}",
            )
            # Resolved attachment must be fetchable (128-bit hash + .js).
            self.assertRegex(url, r"^/web/assets/esm/bridges/[0-9a-f]{32}\.js$")

    def test_prod_import_map_bridges_parent_specifiers(self):
        """The production import map for a bundle with satellites must
        include bridge entries for specifiers imported by satellites'
        individually-loaded source files.

        We pick a native module that's guaranteed to be in ``setup``
        regardless of the ``ai`` module's presence (it lives in core).
        """
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
        # Pick an arbitrary @web/* specifier that exists — this avoids
        # coupling the test to optional addons like ``ai``.
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
    """End-to-end: circuit + admin override route through fallback."""

    def test_admin_override_skips_esbuild(self):
        """When a bundle is in ``force_fallback_bundles``, esbuild
        must not run — the debug-mode fallback handles rendering."""
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
        """When the advisory lock is unavailable, nodes must still
        render via the debug-mode path instead of producing nothing."""
        ir_qweb = self.env["ir.qweb"]
        with patch.object(
            type(ir_qweb),
            "_esbuild_try_acquire_lock",
            return_value=False,
        ):
            # Drop cached attachments so the prod path is actually
            # attempted (otherwise the cache short-circuits the branch).
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
        # Fallback emits individual-file + importmap nodes rather than
        # a single esbuild-bundled module; ensure the output is
        # non-empty and contains an importmap.
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
        """Regression: with an HTTP request bound, the FIRST ESM bundle
        rendered through the uncached ``_esm_debug_nodes`` path (``?debug=assets``
        or the esbuild-declined fallback) must keep its
        ``<script type="importmap">`` — and a SECOND bundle on the same request
        must still be deduped.

        The request-scoped dedup flag (``request._esm_import_map_rendered``) has
        exactly one owner per branch: ``_esm_debug_nodes`` self-dedups and sets
        the flag, so the dispatcher must NOT also run
        ``_dedup_request_import_map`` over its output. The historical bug ran
        both: the second pass saw the flag the first had just set and stripped
        the importmap the first had just emitted, so every request-bound
        ``?debug=assets`` page — and every production page during an esbuild
        incident (circuit open / ``force_fallback_bundles`` / missing binary) —
        was served with no import map, leaving all bare specifiers unresolved.

        The pre-existing ``request=None`` fallback tests could not catch this:
        with no request bound, ``_dedup_request_import_map`` returns early and
        ``_esm_debug_nodes`` never touches the flag, so both dedup owners are
        no-ops. See ``_get_native_module_nodes``.
        """
        from odoo.addons.base.models import ir_qweb_assets

        ir_qweb = self.env["ir.qweb"]

        def importmaps(nodes):
            return [
                attrs
                for tag, attrs in nodes
                if tag == "script" and attrs.get("type") == "importmap"
            ]

        # SimpleNamespace is a truthy attribute-bag stand-in for the werkzeug
        # request proxy: it supports the getattr/setattr the flag logic needs.
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
    """End-to-end: spawn real esbuild on a real bundle and assert output shape.

    Separate from the unit-level tests above because it's the only one
    that actually invokes the ``esbuild`` subprocess; it's skipped when
    the binary is not installed (``npm install`` hasn't been run) so
    that the suite stays green on minimal CI environments.  A single
    bundle (``web.assets_emoji``) is enough to exercise the full path:
    entry-point synthesis, addon-alias resolution, subprocess run,
    output capture, and metafile sidecar read.
    """

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
        """Build the smallest ESM bundle through the real esbuild path."""
        IrQweb = self.env["ir.qweb"]
        assets_params = self.env["ir.asset"]._get_asset_params()
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

        # The esbuild entry point always calls registerNativeModules —
        # the presence of this string is the structural-integrity check.
        self.assertIn(
            "odoo.loader.registerNativeModules",
            result.code,
            msg="bundle output must register modules via the loader API",
        )
        # Minified output still has substance (emoji_data.js is ~36k
        # lines); a suspiciously small output means esbuild silently
        # dropped input — surface that as a test failure, not a warning.
        self.assertGreater(
            len(result.code),
            1000,
            msg=f"bundle output suspiciously small ({len(result.code)} bytes)",
        )
        # Metafile is a side effect we expose to consumers; the real
        # esbuild path MUST populate it.  Skipping this check would
        # mask a regression where we lose the analysis side-channel.
        self.assertIsNotNone(
            result.metafile,
            msg="metafile sidecar must be captured after successful build",
        )

    def test_timeout_parameter_threaded_through(self):
        """Explicit ``timeout_s`` / ``target`` overrides reach ``esbuild_native_bundle``.

        Smoke test only: passes non-default values (60s, ``es2022``)
        through a real build and asserts it still completes normally.
        The real timeout-exceeded path is covered indirectly by the
        circuit breaker tests above (any build failure, including a
        subprocess timeout, is what trips the breaker).
        """
        IrQweb = self.env["ir.qweb"]
        assets_params = self.env["ir.asset"]._get_asset_params()
        # Re-use emoji bundle but exercise the signature change.
        bundle = IrQweb._get_asset_bundle(
            "web.assets_emoji",
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        # Explicit non-default args — smoke test that the overrides are
        # accepted without raising TypeError.
        result = bundle.esbuild_native_bundle(timeout_s=60, target="es2022")
        self.assertIn("odoo.loader.registerNativeModules", result.code)


@tagged("web_unit", "web_assets")
class TestEsbuildSettingLoader(TransactionCase):
    """``_get_esbuild_setting`` reads ir.config_parameter with cast + fallback."""

    def test_unset_returns_default(self):
        IrQweb = self.env["ir.qweb"]
        # A key that is definitely not set in a fresh test DB.
        self.env["ir.config_parameter"].sudo().search(
            [
                ("key", "=", "web.esbuild.cooldown_s"),
            ]
        ).unlink()
        val = IrQweb._get_esbuild_setting(
            "cooldown_s",
            default=60.0,
            cast=float,
        )
        self.assertEqual(val, 60.0)

    def test_valid_param_casts(self):
        IrQweb = self.env["ir.qweb"]
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.cooldown_s",
            "12.5",
        )
        val = IrQweb._get_esbuild_setting(
            "cooldown_s",
            default=60.0,
            cast=float,
        )
        self.assertEqual(val, 12.5)

    def test_unparseable_param_falls_back_to_default(self):
        IrQweb = self.env["ir.qweb"]
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.cooldown_s",
            "not-a-number",
        )
        val = IrQweb._get_esbuild_setting(
            "cooldown_s",
            default=60.0,
            cast=float,
        )
        self.assertEqual(
            val,
            60.0,
            msg="cast failure must silently fall back to the default",
        )

    def test_unknown_key_raises(self):
        IrQweb = self.env["ir.qweb"]
        # Typos in setting names would silently read empty values — catch
        # them at the call site with a fast-failing ValueError.
        with self.assertRaises(ValueError):
            IrQweb._get_esbuild_setting("totally_made_up", default=0)


@tagged("web_unit", "web_assets")
class TestExternalLibsValidator(TransactionCase):
    """Cross-file validator catches drift between ODOO_EXTERNAL_LIBS,
    EXTERNAL_BARE_SPECIFIERS and _LIB_CANDIDATES."""

    def test_valid_configuration_passes(self):
        """The real configuration at import time must pass the validator."""
        IrQweb = self.env["ir.qweb"]
        # Does not raise — proves the live configuration is consistent,
        # including the on-disk existence of every import-map URL.
        AssetsBundle._validate_external_libs(IrQweb._ODOO_EXTERNAL_LIBS)

    def test_missing_alias_raises(self):
        """Import-map spec without a matching alias must be rejected."""
        with self.assertRaises(ValueError) as ctx:
            AssetsBundle._validate_external_libs(
                {"@invented/lib": "/web/static/lib/owl/owl.es.js"},
                bare_specifiers=set(),
            )
        self.assertIn("@invented/lib", str(ctx.exception))
        self.assertIn("no per-lib alias", str(ctx.exception))

    def test_pattern_externals_accepted(self):
        """@odoo/owl etc. are covered by --external:@odoo/* and don't need aliases."""
        # Does not raise even though none are in _LIB_CANDIDATES.
        AssetsBundle._validate_external_libs(
            {
                "@odoo/owl": "/web/static/lib/owl/owl.es.js",
                "@odoo/hoot": "/web/static/lib/hoot/hoot.js",
                "@odoo/hoot-dom": "/web/static/lib/hoot-dom/hoot-dom.js",
                "@odoo/hoot-mock": "/web/static/lib/hoot/hoot-mock.js",
            },
            bare_specifiers=set(),
        )

    def test_bare_specifier_without_import_map_url_raises(self):
        """An esbuild external bare specifier missing its import-map URL
        must fail fast: esbuild would emit the import verbatim and the
        browser would die on "Failed to resolve module specifier"."""
        with self.assertRaises(ValueError) as ctx:
            AssetsBundle._validate_external_libs(
                {"@odoo/owl": "/web/static/lib/owl/owl.es.js"},
                bare_specifiers={"luxon"},
            )
        self.assertIn("luxon", str(ctx.exception))
        self.assertIn("no import-map URL", str(ctx.exception))

    def test_import_map_url_missing_on_disk_raises(self):
        """A typo'd import-map URL (existing addon, nonexistent file) must
        be caught at startup instead of surfacing as a browser 404."""
        with self.assertRaises(ValueError) as ctx:
            AssetsBundle._validate_external_libs(
                {"@odoo/owl": "/web/static/lib/owl/owl_typo.es.js"},
                bare_specifiers=set(),
            )
        self.assertIn("owl_typo", str(ctx.exception))
        self.assertIn("404", str(ctx.exception))

    def test_import_map_url_in_absent_addon_skipped(self):
        """URLs under an addon absent from addons_path are skipped — the
        lib is unreachable but so is any code importing it."""
        # Does not raise.
        AssetsBundle._validate_external_libs(
            {"@odoo/owl": "/nonexistent_addon_xyz/static/lib/foo.js"},
            bare_specifiers=set(),
        )

    def test_lib_candidate_missing_on_disk_raises(self):
        """A ``_LIB_CANDIDATES`` alias whose target file is missing must be
        caught at startup — the esbuild addon scan silently skips it and
        every bundle importing the alias fails to build."""
        with self.assertRaises(ValueError) as ctx:
            AssetsBundle._validate_external_libs(
                {},
                bare_specifiers=set(),
                lib_candidates={
                    "@odoo/typo-lib": ("web", "static", "lib", "owl", "typo.js"),
                },
            )
        self.assertIn("@odoo/typo-lib", str(ctx.exception))
        self.assertIn("silently skip", str(ctx.exception))

    def test_lib_candidate_in_absent_addon_skipped(self):
        """Alias targets under an absent addon are skipped, mirroring the
        import-map URL rule."""
        # Does not raise.
        AssetsBundle._validate_external_libs(
            {},
            bare_specifiers=set(),
            lib_candidates={
                "@odoo/optional": ("nonexistent_addon_xyz", "static", "x.js"),
            },
        )


@tagged("web_unit", "web_assets")
class TestEsbuildSourceMaps(TransactionCase):
    """``--sourcemap=<mode>`` plumbing through esbuild + sidecar persistence."""

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
        assets_params = self.env["ir.asset"]._get_asset_params()
        return IrQweb._get_asset_bundle(
            "web.assets_emoji",
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )

    def test_off_by_default(self):
        """Default mode is empty string — no source map captured."""
        bundle = self._bundle()
        result = bundle.esbuild_native_bundle()
        self.assertIsNone(
            result.sourcemap,
            msg="default behavior must not capture a source map",
        )

    def test_linked_mode_populates_last_sourcemap_and_links_bundle(self):
        """``source_maps='linked'`` writes a sidecar AND emits the directive.

        This is the mode operators will pick 95% of the time.
        ``external`` writes the map but omits the directive — see
        ``test_external_mode_emits_map_without_directive``.
        """
        bundle = self._bundle()
        result = bundle.esbuild_native_bundle(source_maps="linked")
        self.assertIsNotNone(
            result.sourcemap,
            msg="linked mode must capture the sourcemap sibling",
        )
        # esbuild source maps are JSON; minimal sanity check that we
        # captured the right bytes (not e.g. the metafile).
        parsed = json.loads(result.sourcemap)
        self.assertIn("version", parsed)
        self.assertIn("mappings", parsed)
        self.assertIn("//# sourceMappingURL=", result.code)

    def test_external_mode_emits_map_without_directive(self):
        """``source_maps='external'`` writes the map but omits the
        ``//# sourceMappingURL=`` comment — matches esbuild's own
        semantics for ``--sourcemap=external``.  Useful when the map
        is distributed out-of-band (e.g. uploaded to a crash reporter)
        and we don't want devtools auto-fetching it.
        """
        bundle = self._bundle()
        result = bundle.esbuild_native_bundle(source_maps="external")
        self.assertIsNotNone(
            result.sourcemap,
            msg="external mode still writes the sidecar, just doesn't link it",
        )
        self.assertNotIn("//# sourceMappingURL=", result.code)

    def test_inline_mode_embeds_in_bundle(self):
        """``source_maps='inline'`` embeds a base64 data URL in the bundle."""
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
        """Garbage mode value is logged and ignored — never crashes the build."""
        bundle = self._bundle()
        # The helper logs ``WARNING source_maps_unknown_mode`` on an
        # invalid mode; consume it via ``assertLogs`` so the test log
        # stays clean and the structured event is asserted.
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
        """``_save_esm_attachment`` writes a ``.esm.js.map`` sibling."""
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
        """When no sourcemap is passed, no ``.map`` sidecar is created."""
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
        """``source_maps`` is in ``_ESBUILD_SETTING_KEYS`` for config-param overrides."""
        IrQweb = self.env["ir.qweb"]
        self.assertIn("source_maps", IrQweb._ESBUILD_SETTING_KEYS)
        # Clear any operator-set value so the fallback path is what we
        # actually exercise — otherwise a leftover
        # ``web.esbuild.source_maps=linked`` from a manual e2e probe
        # leaks into the test.
        self.env["ir.config_parameter"].sudo().search(
            [
                ("key", "=", "web.esbuild.source_maps"),
            ]
        ).unlink()
        # And the helper accepts it without raising the unknown-key
        # ValueError that catches operator typos.
        val = IrQweb._get_esbuild_setting("source_maps", default="")
        self.assertEqual(val, "")


def _fake_native_module(url="", raw_content="", module_path="", filename=None):
    """Lightweight stand-in for a JavascriptAsset in helper unit tests.

    Mirrors the attributes the esbuild helpers read off a real native module:
    ``.url``, ``.raw_content``, ``.module_path``, ``._filename`` and
    ``.parsed_header``. The header is derived from ``raw_content`` exactly as
    :meth:`JavascriptAsset.parsed_header` does, so the ``@odoo/*`` alias pass in
    ``_esbuild_flags`` behaves like production — without building a real asset
    (or touching the filestore).
    """
    return SimpleNamespace(
        url=url,
        raw_content=raw_content,
        module_path=module_path,
        _filename=filename,
        parsed_header=_parse_odoo_module_header(raw_content),
    )


@tagged("web_unit", "web_assets")
class TestEsbuildHelpers(TransactionCase):
    """Unit tests for the esbuild subprocess-layer helpers.

    None of these spawn esbuild — they exercise option resolution, entry-script
    assembly, flag computation and output post-processing in isolation, on
    ``EsbuildCompiler`` directly (the ``AssetsBundle`` delegators were deleted
    once this class stopped needing them).  The real subprocess path stays
    covered by ``TestEsbuildSourceMaps`` / ``TestEsbuildIntegration``.
    """

    def _compiler(self, name="web.assets_emoji", native_modules=(), provider=None):
        return EsbuildCompiler(
            name,
            list(native_modules),
            addon_flags_provider=provider,
        )

    def _odoo_root(self):
        return Path(odoo.__path__[0]).parent

    def test_resolve_opts_applies_defaults(self):
        """``None`` arguments resolve to the class-constant defaults."""
        c = self._compiler()
        timeout_s, target, source_maps = c._esbuild_resolve_opts(None, None, None)
        self.assertEqual(timeout_s, EsbuildCompiler._ESBUILD_TIMEOUT_S)
        self.assertEqual(target, EsbuildCompiler._ESBUILD_TARGET)
        self.assertEqual(source_maps, EsbuildCompiler._ESBUILD_SOURCE_MAPS)

    def test_resolve_opts_passes_through_valid(self):
        """Explicit valid values are returned unchanged."""
        c = self._compiler()
        self.assertEqual(
            c._esbuild_resolve_opts(10, "es2022", "linked"),
            (10, "es2022", "linked"),
        )

    def test_resolve_opts_unknown_source_map_falls_back(self):
        """An unknown source-map mode degrades to ``""`` (never crashes esbuild)."""
        c = self._compiler()
        with self.assertLogs(f"{ASSET_ROOT}.esbuild", level=logging.WARNING):
            _, _, source_maps = c._esbuild_resolve_opts(5, "es2023", "bogus")
        self.assertEqual(source_maps, "")

    def test_entry_lines_register_block(self):
        """The entry lines register every native module plus ``@odoo/owl``."""
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
        """A bundle that ships test files keeps them: its own ``tests/*``
        externals are filtered out while other addons' survive.
        """
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
        """``dynamic_child_specs`` become ``--external:<spec>`` flags."""
        c = self._compiler(provider=lambda root: ([], []))
        _, external_flags = c._esbuild_flags(
            self._odoo_root(), frozenset({"@lazy/child"})
        )
        self.assertIn("--external:@lazy/child", external_flags)

    def test_postprocess_rewrites_directive_and_captures_sidecars(self):
        """``linked`` mode rewrites ``sourceMappingURL`` to the final attachment
        name and captures the metafile + source-map bytes.
        """
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
        """``""`` mode reads the bundle verbatim and captures no source map."""
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
        """A vanished output file becomes a clear ``RuntimeError``."""
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
    """Unit tests for the helpers extracted from ``_build_native_to_legacy_bridge``."""

    def test_resolver_resolves_external_lib(self):
        """A specifier in ``ext_libs`` returns its canonical URL directly."""
        r = _BridgeExportResolver(
            {"luxon": "/web/static/lib/luxon/luxon.js"}, {}, "test"
        )
        self.assertEqual(r.resolve_url("luxon"), "/web/static/lib/luxon/luxon.js")

    def test_resolver_resolves_lib_candidate(self):
        """A vendored ``_LIB_CANDIDATES`` entry maps to a ``/``-joined URL."""
        r = _BridgeExportResolver({}, {"@odoo/x": ("a", "b", "c.js")}, "test")
        self.assertEqual(r.resolve_url("@odoo/x"), "/a/b/c.js")

    def test_resolver_resolves_addon_paths(self):
        """``@addon`` specifiers map to ``src`` / ``lib`` / ``tests`` URLs."""
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
        """Bare or malformed specifiers resolve to ``None``."""
        r = _BridgeExportResolver({}, {}, "test")
        self.assertIsNone(r.resolve_url("luxon"))
        self.assertIsNone(r.resolve_url("@noslash"))

    def test_resolver_caches_and_get_protocol(self):
        """``read_source`` caches misses; ``get`` honors the source_map default."""
        r = _BridgeExportResolver({}, {}, "test")
        self.assertIsNone(r.read_source("nope"))  # unmappable -> None, cached
        self.assertIn("nope", r._cache)
        self.assertIsNone(r._cache["nope"])
        self.assertIsNone(r.get("nope"))
        self.assertEqual(r.get("nope", "DEFAULT"), "DEFAULT")

    def test_discover_classifies_import_kinds(self):
        """Named / default / namespace imports are classified per specifier."""
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
        """Own / owl / external-lib specifiers are excluded; ext libs recorded."""
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
        """A default + named surface emits ``export default`` and sorted names."""
        shim, star = AssetsBundle._bridge_shim_source(
            "@web/foo", set(), {"b", "a"}, True
        )
        self.assertFalse(star)
        # Specifier literals are emitted with script-safe json.dumps (double
        # quotes), matching the esbuild entry codegen.
        self.assertIn('const _m = odoo.loader.modules.get("@web/foo");', shim)
        self.assertIn("const _d = _m?.default ?? _m;", shim)
        self.assertIn("export default _d;", shim)
        self.assertIn("export const a = _m?.a;", shim)
        self.assertIn("export const b = _m?.b;", shim)
        self.assertLess(shim.index("export const a"), shim.index("export const b"))

    def test_shim_source_star_fallback(self):
        """No names and no default -> flagged, but same interop default shape."""
        shim, star = AssetsBundle._bridge_shim_source("@web/bar", set(), set(), False)
        self.assertTrue(star)
        self.assertIn("const _d = _m?.default ?? _m;", shim)
        self.assertIn("export default _d;", shim)
        self.assertNotIn("export const", shim)

    def test_shim_source_named_only_still_exports_default(self):
        """Named-only surfaces still emit the interop default block.

        The runtime bridge builder (``@web/core/module_bridge``) always
        emits it — the two generators must stay field-for-field identical
        for server attachments and ``data:`` bridges to be interchangeable.
        """
        shim, star = AssetsBundle._bridge_shim_source("@web/baz", set(), {"x"}, False)
        self.assertFalse(star)
        self.assertIn("export const x = _m?.x;", shim)
        self.assertIn("export default _d;", shim)

    def test_shim_source_star_kind_no_duplicate_default(self):
        """``__star__`` consumers of an unreadable source get ONE default.

        The old conditional emission appended a second ``export default``
        (a SyntaxError in the shim) when ``__star__`` was in the consumer
        kinds but the export surface was empty.
        """
        shim, star = AssetsBundle._bridge_shim_source(
            "@web/qux", {"__star__"}, set(), False
        )
        self.assertTrue(star)
        self.assertEqual(shim.count("export default"), 1)

    def test_shim_source_default_kind_triggers_export(self):
        """A ``__default__`` consumer kind forces a default export even when the
        source surface is empty.
        """
        shim, star = AssetsBundle._bridge_shim_source(
            "@web/q", {"__default__"}, set(), False
        )
        self.assertFalse(star)
        self.assertIn("export default _d;", shim)


@tagged("web_unit", "web_assets")
class TestTransitiveImportClosure(TransactionCase):
    """Debug-mode import maps must cover the TRANSITIVE out-of-bundle graph.

    Every specifier the debug/fallback path resolves to a direct URL is
    fetched as RAW source, so its own bare imports must resolve through the
    import map too.  The one-level ``_discover_bridge_specifiers`` scan only
    covers the bundle's own modules; ``discover_transitive_import_specifiers``
    walks the rest.  Regression anchor: ``web.report_assets_common`` ships
    ONE native module (``@web/libs/bootstrap``) whose chain reaches
    ``@web/core/browser/browser`` two hops out of the bundle — unmapped, every
    ``/report/html`` page rendered through the fallback path (readonly test
    cursor, esbuild circuit open, ``?debug=assets``) failed pre-boot with
    ``Failed to resolve module specifier "@web/core/browser/browser"``
    (caught by ``TestStockReportTour.test_stock_route_diagram_report``).
    """

    def test_walk_finds_two_hop_specifier(self):
        """The real bootstrap chain yields the two-hop browser specifier."""
        res = discover_transitive_import_specifiers(
            # The two direct out-of-bundle imports of @web/libs/bootstrap.
            [
                "@web/../lib/bootstrap/bootstrap.esm.js",
                "@web/core/utils/dom/scrolling",
            ],
            {"@web/libs/bootstrap"},
            ODOO_EXTERNAL_LIBS,
            EsbuildCompiler._LIB_CANDIDATES,
            "test.report.closure",
        )
        self.assertIn("@web/core/browser/browser", res)
        # @popperjs/core (imported by bootstrap.esm.js) is an external lib —
        # already mapped, must NOT be re-discovered.
        self.assertNotIn("@popperjs/core", res)
        # Known specifiers are never re-added.
        self.assertNotIn("@web/libs/bootstrap", res)

    def test_scan_covers_reexport_and_relative_shapes(self):
        """The per-file scan sees import, side-effect, and re-export forms."""
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
        # Dynamic import() is resolved at runtime through the map the page
        # already has; the static walk must not chase it.
        self.assertNotIn("@web/dynamic_only", specs)

    def test_report_bundle_debug_importmap_is_transitively_complete(self):
        """The report bundle's debug nodes map the whole reachable graph."""
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
            "@web/core/utils/dom/scrolling",
            "@web/core/browser/browser",  # the two-hop regression specifier
            "@popperjs/core",
        ):
            self.assertIn(spec, imports, msg=f"{spec} missing from import map")


@tagged("web_unit", "web_assets")
class TestEsmLexer(TransactionCase):
    """The es-module-lexer worker and its wiring into export extraction.

    The worker requires node + ``npm install`` (same prerequisites as
    esbuild).  ``test_worker_available`` pins that expectation for dev/CI
    environments; the extraction tests exercise BOTH paths explicitly so
    a regression in either cannot hide behind the other.
    """

    SRC = (
        'import { q } from "@web/other";\n'
        "export const alpha = 1;\n"
        "export function beta() {}\n"
        "export default class Gamma {}\n"
        'export * as ns from "@web/ns_target";\n'
        # NOTE: no line-commented export here — that is the one shape the
        # two paths legitimately DIVERGE on (the regex extractor keeps
        # line comments; the lexer ignores them by construction).  The
        # lexer-only behavior is pinned by
        # ``test_lexer_line_comment_immunity``.
        "/* export const block_commented = 2; */\n"
        "const tpl = `export const in_template = 3;`;\n"
    )

    def test_worker_available(self):
        """The lexer worker must be functional where esbuild is (dev/CI)."""
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
        """Both extraction paths return the same surface on lexable source.

        The lexer is immune to comment/template false positives by
        construction; the regex path via ``_JS_OPAQUE_RE`` stripping.
        """
        from odoo.tools.assets import esm_graph

        expected = ({"alpha", "beta", "ns"}, True)
        # Lexer path (primary).
        self.assertEqual(esm_graph._extract_esm_exports(self.SRC), expected)
        # Regex path (fallback), forced by stubbing the worker out.
        with patch.object(esm_graph, "lex_module", return_value=None):
            self.assertEqual(esm_graph._extract_esm_exports(self.SRC), expected)

    def test_lexer_line_comment_immunity(self):
        """A ``// export const x`` line comment fools neither path into a
        spurious name — the lexer by construction; this documents the one
        false-positive class (line comments) the regex path still has,
        which the lexer now shields in practice."""
        from odoo.tools.assets import esm_graph

        names, has_default = esm_graph._extract_esm_exports(
            "// export const ghost = 1;\nexport const real = 2;\n"
        )
        self.assertEqual(names, {"real"})
        self.assertFalse(has_default)

    def test_star_expansion_shared_by_both_paths(self):
        """``export * from`` recursion works identically via lexer and regex."""
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
        """A syntax error in the source degrades to the regex path, not to
        an empty surface."""
        from odoo.tools.assets import esm_graph

        broken = "export const good = 1;\nfunction ( { invalid syntax\n"
        names, _ = esm_graph._extract_esm_exports(broken)
        self.assertIn("good", names)

    def test_discovery_catches_mixed_default_named_import(self):
        """``import X, { y } from "@a/b"`` is discovered by the lexer path.

        The regex ``_IMPORT_ANY_RE`` misses this shape entirely (latent
        gap: no bridge was built, the satellite bundle failed to resolve
        the specifier at runtime).
        """
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
    """Unit tests for the pure ``ir.qweb`` asset helpers.

    None of these spawn esbuild or touch the DB — they pin the node/URL
    contracts that the render paths depend on, several of which were
    silent latent traps before being hardened.
    """

    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    # ── _specifier_to_static_url (the reserved @odoo namespace) ──
    def test_specifier_convention_resolves(self):
        """``@addon/path`` specifiers map to their served static URL."""
        cases = {
            "@web/core/registry": "/web/static/src/core/registry.js",
            "@web/../lib/hoot/hoot": "/web/static/lib/hoot/hoot.js",
            "@web/../tests/foo": "/web/static/tests/foo.js",
            "@account/models/move": "/account/static/src/models/move.js",
        }
        for spec, url in cases.items():
            self.assertEqual(self._qweb._specifier_to_static_url(spec), url, spec)

    def test_specifier_odoo_namespace_is_reserved(self):
        """``@odoo/*`` are vendored externals, NOT ``/odoo/static/src`` paths.

        Regression: the convention derived a bogus ``/odoo/static/src/owl.js``
        (a hard 404) for ``@odoo/owl``, contradicting the docstring's promise
        of ``None``.  Every such specifier is covered by ``_ODOO_EXTERNAL_LIBS``,
        so returning ``None`` here lets the caller's ``externals or ...`` land on
        the correct vendored URL (or yield a clean *module not found*).
        """
        externals = self._qweb._ODOO_EXTERNAL_LIBS
        for spec in [k for k in externals if k.startswith("@odoo/")]:
            self.assertIsNone(
                self._qweb._specifier_to_static_url(spec),
                f"{spec} must not resolve via the addon convention",
            )
            # …and the external map still has the real, non-empty URL.
            self.assertTrue(externals[spec])
        # a bare @odoo/<x> not in the map also declines (clean not-found)
        self.assertIsNone(self._qweb._specifier_to_static_url("@odoo/nope"))

    def test_specifier_non_convention_returns_none(self):
        for spec in ["luxon", "@web", "@/foo", ""]:
            self.assertIsNone(self._qweb._specifier_to_static_url(spec), spec)

    # ── _is_debug_assets (crash-proof debug flag) ──
    def test_is_debug_assets_string_semantics(self):
        q = self._qweb
        self.assertTrue(q._is_debug_assets("assets"))
        self.assertTrue(q._is_debug_assets("1,assets"))
        self.assertFalse(q._is_debug_assets("1"))
        self.assertFalse(q._is_debug_assets(""))

    def test_is_debug_assets_never_raises_on_non_str(self):
        """A bare ``bool``/``None`` degrades to non-debug instead of the
        historical ``"assets" in True`` -> ``TypeError``."""
        q = self._qweb
        for value in (True, False, None, 0, 1):
            self.assertFalse(q._is_debug_assets(value), repr(value))

    def test_get_asset_links_survives_bool_debug(self):
        """The public entry point no longer crashes when handed ``debug=True``."""
        # Should not raise (empty css+js just returns []).
        self.assertEqual(
            self._qweb._get_asset_links(
                "web.assets_web", css=False, js=False, debug=True
            ),
            [],
        )

    # ── _link_to_node (stylesheet type) ──
    def test_link_to_node_stylesheet_is_text_css(self):
        """A stylesheet link is always ``text/css`` — never ``text/{ext}``."""
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

    # ── _import_map_url_breakdown ──
    def test_import_map_url_breakdown(self):
        im = {
            "a": "/web/static/src/a.js",
            "b": "/web/assets/esm/bridges/deadbeef.js",
            "c": "data:text/javascript,1",
            "d": "/account/static/src/d.js",
        }
        self.assertEqual(self._qweb._import_map_url_breakdown(im), (2, 1, 1))
        self.assertEqual(self._qweb._import_map_url_breakdown({}), (0, 0, 0))

    # ── _combine_bundle_with_templates ──
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
        """The trailing ``//# sourceMappingURL=`` directive must stay the LAST
        line after templates are appended, or devtools drops source maps."""
        src = "CODE;\n//# sourceMappingURL=b.esm.js.map"
        out = self._qweb._combine_bundle_with_templates(src, "TPL;")
        last = out.rstrip("\n").splitlines()[-1]
        self.assertEqual(last, "//# sourceMappingURL=b.esm.js.map")
        self.assertEqual(out.count("sourceMappingURL"), 1)
        self.assertIn("TPL;", out)


@tagged("web_unit", "web_assets")
class TestNativeNodesDispatch(TransactionCase):
    """Dispatch matrix of ``_get_native_module_nodes``: readonly x debug x
    forced-fallback (audit finding — readonly renders must use the cache).

    Production renders go through the "assets" ormcache on READ-ONLY cursors
    too: the historical ``not cr.readonly`` gate forced every replica-routed
    render through the full uncached assembly (bundle construction, the
    esbuild subprocess, the template XML parse) per request — and executed
    ``pg_try_advisory_xact_lock`` on the standby cursor, which PostgreSQL
    forbids during recovery (SQLSTATE 55000, not retried by http: hard 500).
    The gate's rationale was stale: attachment persistence moved to a
    dedicated RW registry cursor (``_persist_esm_attachment_rows``) and the
    advisory lock now goes through ``_esbuild_lock_cursor``.
    """

    BUNDLE = "web.assets_web"
    PRE = [("script", {"type": "importmap", "data-bundle": "t", "text": "{}"})]
    POST = [("script", {"type": "module", "text": "t"})]

    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    def _run(self, *, debug="", readonly=False, cached=None, impl=None):
        """Call the dispatcher with both branches patched; return the mocks."""
        ir_qweb = self._qweb
        patches = [
            patch.object(
                type(ir_qweb),
                "_get_native_module_nodes_cached",
                **(cached or {"return_value": (self.PRE, self.POST)}),
            ),
            patch.object(
                type(ir_qweb),
                "_get_native_module_nodes_impl",
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
        """The core fix: a readonly render must hit the ormcached branch."""
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

    def test_forced_fallback_bypasses_cache(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.force_fallback_bundles", self.BUNDLE
        )
        self.addCleanup(
            self.env["ir.config_parameter"].sudo().set_param,
            "web.esbuild.force_fallback_bundles",
            "",
        )
        for readonly in (False, True):
            with self.subTest(readonly=readonly):
                result, cached_mock, impl_mock = self._run(readonly=readonly)
                self.assertEqual(result, (self.PRE, self.POST))
                cached_mock.assert_not_called()
                impl_mock.assert_called_once()

    def test_decline_falls_back_uncached(self):
        """A declined cached attempt re-renders uncached — readonly included."""
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
    """``_esbuild_lock_cursor`` / the advisory lock's legal-cursor contract.

    ``pg_try_advisory_xact_lock`` is forbidden during recovery, so a readonly
    request cursor must NEVER execute it; the lock either moves to a
    read-write registry cursor or (readonly test cursors, primary down)
    esbuild is skipped entirely.
    """

    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    def test_readwrite_yields_request_cursor(self):
        with self._qweb._esbuild_lock_cursor("b.x") as lock_cr:
            self.assertIs(lock_cr, self.env.cr)

    def test_readonly_test_cursor_yields_none(self):
        with patch.object(self.env.cr, "_readonly", True):
            with self._qweb._esbuild_lock_cursor("b.x") as lock_cr:
                self.assertIsNone(lock_cr)

    def test_acquire_lock_runs_on_the_given_cursor(self):
        executed = []

        fake_cr = SimpleNamespace(
            execute=lambda sql, params=None: executed.append(sql),
            fetchone=lambda: (True,),
        )
        got = self._qweb._esbuild_try_acquire_lock("b.x", cr=fake_cr)
        self.assertTrue(got)
        self.assertEqual(len(executed), 1)
        self.assertIn("pg_try_advisory_xact_lock", executed[0])

    def test_readonly_run_esbuild_skips_lock_and_build(self):
        """On a readonly test cursor the whole esbuild stage is skipped:
        no advisory-lock SQL on the request cursor, no subprocess, empty
        result → the caller degrades to the debug-mode nodes."""
        ir_qweb = self._qweb
        with (
            patch.object(self.env.cr, "_readonly", True),
            patch.object(
                type(ir_qweb),
                "_esbuild_try_acquire_lock",
                side_effect=AssertionError("lock must not be attempted"),
            ),
            patch.object(
                AssetsBundle,
                "esbuild_native_bundle",
                side_effect=AssertionError("esbuild must not run"),
            ),
        ):
            result, child_bundles = ir_qweb._esm_run_esbuild(
                "web.assets_web", SimpleNamespace(), None
            )
        self.assertEqual(result.code, "")
        self.assertEqual(child_bundles, [])


@tagged("web_unit", "web_assets")
class TestProdNodesDeclineNotCached(TransactionCase):
    """``_esm_prod_nodes(raise_on_decline=True)`` must raise instead of
    inlining when no writable cursor is reachable for the attachment persist:
    ormcache never stores exceptions, so the multi-MB inline degradation can
    never enter the process cache (where it would be served to every later
    request long after the primary is back)."""

    BUNDLE = "g4.decline.bundle"  # no children/includes registered

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
            with self.assertRaises(_EsmFallbackError):
                ir_qweb._esm_prod_nodes(
                    self.BUNDLE,
                    self._fake_bundle(),
                    EsbuildResult("CODE;", None, None),
                    None,
                    [],
                    raise_on_decline=True,
                )

    def test_uncached_rerun_still_inlines(self):
        """Without the flag (the uncached re-run) the inline degradation
        stays available — functionally identical, just heavier."""
        ir_qweb = self._qweb
        with patch.object(
            type(ir_qweb),
            "_save_esm_attachment",
            side_effect=ReadOnlySqlTransaction("no writable cursor"),
        ):
            _pre, post = ir_qweb._esm_prod_nodes(
                self.BUNDLE,
                self._fake_bundle(),
                EsbuildResult("CODE;", None, None),
                None,
                [],
            )
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
    """Direct unit tests for the shared import-map assembly helpers extracted
    from the prod/debug node builders (previously three diverging inline
    copies)."""

    @property
    def _qweb(self):
        return self.env["ir.qweb"]

    @staticmethod
    def _fake_registry(**overrides):
        reg = SimpleNamespace(
            dynamic_children={},
            dynamic_bundle_names=set(),
            import_map_includes={},
            secondary_import_map_includes={},
        )
        for key, value in overrides.items():
            setattr(reg, key, value)
        return reg

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
        """Debug builds every child per-file; production per-file only for
        the truly dynamic (runtime ``loadBundle``) children."""
        reg = self._fake_registry(
            dynamic_children={"parent": ("child.dyn", "child.plain")},
            dynamic_bundle_names={"child.dyn"},
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
            self.assertEqual(built, [("child.dyn", True), ("child.plain", False)])
            built.clear()
            ir_qweb._get_dynamic_child_bundles("parent", None, debug_assets=True)
            self.assertEqual(built, [("child.dyn", True), ("child.plain", True)])

    def test_merge_child_import_maps(self):
        """Children's maps merge in order; the dynamic subset is returned."""
        reg = self._fake_registry(dynamic_bundle_names={"child.dyn"})
        dyn = self._fake_ab("child.dyn", {"@a/x": "/a/static/src/x.js"})
        plain = self._fake_ab(
            "child.plain",
            {"@b/y": "/b/static/src/y.js", "@a/x": "/b/override.js"},
        )
        import_map = {}
        with self._patch_registry(reg):
            dynamic = self._qweb._merge_child_import_maps(import_map, [dyn, plain])
        self.assertEqual(dynamic, [dyn])
        # last child wins on conflicts (plain dict update, in child order)
        self.assertEqual(
            import_map,
            {"@a/x": "/b/override.js", "@b/y": "/b/static/src/y.js"},
        )

    def test_merge_includes_production_policy(self):
        """Production: cached include data, bridge shims are first-wins."""
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
        # a NEW bridge shim is added...
        self.assertEqual(import_map["@parent/kept"], "/web/assets/esm/bridges/aa.js")
        # ...but an existing direct URL (dynamic-child spec) is never
        # overridden by the include's shim (first-wins).
        self.assertEqual(import_map["@child/direct"], "/child/static/src/direct.js")

    def test_merge_includes_debug_policy_resolves_bridges(self):
        """Debug: discovered bridge specifiers become direct URLs (shims
        read ``odoo.loader.modules``, which nothing populates in debug)."""
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
        # unresolvable shim entries are DROPPED for a clean "module not found"
        self.assertNotIn("unresolvable-bare", import_map)

    def test_merge_secondary_is_first_wins(self):
        reg = self._fake_registry(secondary_import_map_includes={"parent": ("sec.a",)})
        sec_ab = self._fake_ab(
            "sec.a",
            {
                "@parent/mod": "/web/assets/esm/bridges/shim.js",  # must lose
                "@sec/new": "/sec/static/src/new.js",  # must be added
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
        resolved = qweb._resolve_bridge_specifiers_to_urls(
            import_map,
            ["@a/direct", "@b/shimmed", "@c/data", "bare-unresolvable", "@d/new"],
            drop_unresolved=True,
        )
        # direct URL kept as-is, not re-resolved
        self.assertEqual(import_map["@a/direct"], "/a/static/src/direct.js")
        self.assertNotIn("@a/direct", resolved)
        # bridge shim and data: URI replaced by convention-derived URLs
        self.assertEqual(import_map["@b/shimmed"], "/b/static/src/shimmed.js")
        self.assertEqual(import_map["@c/data"], "/c/static/src/data.js")
        # discovered-but-absent specifier resolved and added
        self.assertEqual(import_map["@d/new"], "/d/static/src/new.js")
        # unresolvable shim dropped when drop_unresolved=True
        self.assertNotIn("bare-unresolvable", import_map)

        import_map = dict(base_map)
        qweb._resolve_bridge_specifiers_to_urls(
            import_map,
            ["bare-unresolvable"],
            drop_unresolved=False,
        )
        # ...and left alone when drop_unresolved=False (historical behavior
        # of the main debug pass)
        self.assertEqual(
            import_map["bare-unresolvable"], "/web/assets/esm/bridges/dd.js"
        )


@tagged("web_unit", "web_assets")
class TestGeneratedAssetDomains(TransactionCase):
    """``_generated_asset_domain`` matches ALL server-generated
    ``/web/assets/`` rows (classic ``.min.js`` included) while
    ``_esm_generated_asset_domain`` narrows to ESM-pipeline artifacts.
    The old single name (``_esm_asset_domain``) claimed ESM-only while
    matching everything — an invitation for over-deletion by future
    callers."""

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
    """A secondary (test) bundle must SHARE core singletons with its parent app
    bundle, not inline private copies.

    Regression guard for the ESM singleton split: ``web.assets_tests`` is
    esbuild-compiled self-contained, so a core module it imports transitively
    (``@web/core/browser/browser``, ``@web/env``, ``@web/core/registry``) used
    to be inlined as a second, UNregistered copy — a test patching it
    (``patchWithCleanup(browser, …)``, offline simulation) never reached the
    running app. The fix aliases those specifiers to shims reading
    ``odoo.loader.modules`` (``ir.qweb._secondary_parent_stubs`` →
    ``BridgeShimManager.build_shim_sources`` → a module-exact esbuild
    ``--alias``).
    """

    def _shared(self):
        return self.env["ir.qweb"]._secondary_shared_specs("web.assets_tests", None)

    def test_safe_set_contains_core_singletons(self):
        """The shared set includes singletons the app registers and tests patch.

        ``@web/core/browser/browser`` and ``@web/env`` are imported directly by
        ``web/static/tests/helpers/utils.js`` (always present — ``web`` is
        always installed), so they must always be shared, never inlined.
        """
        shared = self._shared()
        for spec in ("@web/core/browser/browser", "@web/env"):
            self.assertIn(
                spec,
                shared,
                msg=f"{spec} must be shared with the parent app bundle, not inlined",
            )

    def test_safe_set_subset_of_every_installed_parent(self):
        """Safety invariant: every shared specifier is registered by EVERY
        declared+installed parent, so no page ever gets an unresolvable alias.

        This is what keeps the module-exact alias safe across heterogeneous
        parents (backend ``assets_web``, ``/pos/ui`` ``assets_prod``, a frontend
        bundle, enterprise app bundles): a specifier only SOME parents own must
        stay inlined, never aliased.
        """
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
                continue  # uninstalled parent — its page never renders here
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
        """A normal app bundle is not a secondary → nothing to alias out."""
        self.assertEqual(
            self.env["ir.qweb"]._secondary_shared_specs("web.assets_web", None),
            frozenset(),
        )

    def test_stub_sources_read_the_loader(self):
        """Each stub re-exports from ``odoo.loader.modules.get(spec)``."""
        stubs = self.env["ir.qweb"]._secondary_parent_stubs("web.assets_tests", None)
        self.assertIn("@web/core/browser/browser", stubs)
        browser_stub = stubs["@web/core/browser/browser"]
        self.assertIn(
            'odoo.loader.modules.get("@web/core/browser/browser")',
            browser_stub,
        )
        self.assertIn("export const browser", browser_stub)


@tagged("web_unit", "web_assets")
class TestSecondaryBundleSingletonsBuild(TransactionCase):
    """esbuild integration: the built secondary bundle must NOT inline the
    shared core, and must reach it through the loader shim instead.
    """

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
        """Building with the stubs replaces the inlined browser.js with a shim."""
        IrQweb = self.env["ir.qweb"]
        ab = IrQweb._get_asset_bundle(
            "web.assets_tests",
            js=True,
            css=False,
            debug_assets=False,
            assets_params=None,
        )
        stubs = IrQweb._secondary_parent_stubs("web.assets_tests", None)
        self.assertTrue(stubs, "web.assets_tests should have shared-specifier stubs")

        inlined = ab.esbuild_native_bundle().code
        aliased = ab.esbuild_native_bundle(secondary_parent_stubs=stubs).code

        # browser.js captures ``window.fetch.bind(window)`` at eval — that
        # signature is the fingerprint of an INLINED copy of the module.
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
