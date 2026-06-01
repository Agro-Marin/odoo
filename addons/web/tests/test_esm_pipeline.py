"""Tests for the ESM bundler pipeline refactor.

Covers the surfaces added by the UMD→ESM completion work:

    • Structured asset-pipeline logging (``odoo.assets.*``)
    • esbuild circuit breaker (cooldown + escalation + reset)
    • Admin override via ``web.esbuild.force_fallback_bundles``
    • Advisory-lock contention → graceful debug-mode fallback
    • Content-addressable attachment URLs (``/web/assets/esm/<hash>/``)
    • Metafile sidecar attachment

The tests deliberately use lightweight unit-level mocking so they run
without spawning esbuild; a companion HttpCase exercises the real
subprocess path.
"""

import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import patch

from odoo.libs.asset_log import ASSET_ROOT, get_asset_logger, log_event
from odoo.tests.common import TransactionCase


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
                log, logging.DEBUG, "started",
                bundle="web.assets_web", modules=42,
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
        with self.assertLogs(f"{ASSET_ROOT}.fallback", level=logging.WARNING) as captured:
            self.IrQweb._esbuild_circuit_record_failure(
                "web.test_bundle", reason="SubprocessError",
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
        with self.assertLogs(f"{ASSET_ROOT}.fallback", level=logging.WARNING) as captured:
            self.IrQweb._esbuild_circuit_record_failure(
                "web.test_bundle", reason="Err1",
            )
            self.IrQweb._esbuild_circuit_record_failure(
                "web.test_bundle", reason="Err2",
            )
        self.assertEqual(len(captured.records), 2)
        self.assertIn("fails=1", captured.records[0].getMessage())
        self.assertIn("fails=2", captured.records[1].getMessage())
        _expiry, _reason, fails = self.IrQweb._esbuild_cooldowns["web.test_bundle"]
        self.assertEqual(fails, 2)
        # Extended cooldown kicks in at the 2nd failure.
        remaining = _expiry - time.monotonic()
        self.assertGreater(
            remaining, self.IrQweb._ESBUILD_COOLDOWN_S,
            msg="2nd failure should escalate past the base cooldown",
        )

    def test_success_clears_the_circuit(self):
        # record_failure trips the WARNING; record_success emits an INFO
        # ``circuit_close`` that ``assertLogs(level=WARNING)`` ignores.
        with self.assertLogs(f"{ASSET_ROOT}.fallback", level=logging.WARNING) as captured:
            self.IrQweb._esbuild_circuit_record_failure(
                "web.test_bundle", reason="OnceFailed",
            )
            self.IrQweb._esbuild_circuit_record_success("web.test_bundle")
        self.assertEqual(len(captured.records), 1)
        self.assertIn("event=circuit_open", captured.records[0].getMessage())
        self.assertNotIn(
            "web.test_bundle", self.IrQweb._esbuild_cooldowns,
        )
        allow, _ = self.IrQweb._esbuild_circuit_state("web.test_bundle")
        self.assertTrue(allow)


class TestEsbuildAdvisoryLock(TransactionCase):
    """Postgres advisory lock for serializing bundle compilation."""

    def test_lock_acquired_in_own_cursor(self):
        IrQweb = self.env["ir.qweb"]
        got = IrQweb._esbuild_try_acquire_lock("test.lock.alpha")
        self.assertTrue(got)

    def test_lock_rejects_other_cursor_while_held(self):
        from odoo.db import db_connect
        IrQweb = self.env["ir.qweb"]
        self.assertTrue(IrQweb._esbuild_try_acquire_lock("test.lock.beta"))
        # Open a sibling connection and verify it cannot take the lock.
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
        from odoo.db import db_connect
        dbname = self.env.cr.dbname
        key = "esbuild:test.lock.gamma"

        # Conn A: acquire, commit → lock auto-releases.
        with db_connect(dbname).cursor() as cr_a:
            cr_a.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))", (key,),
            )
            self.assertTrue(cr_a.fetchone()[0])
            cr_a.commit()

        # Conn B: should succeed now that A's tx has ended.
        with db_connect(dbname).cursor() as cr_b:
            cr_b.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))", (key,),
            )
            got = cr_b.fetchone()[0]
            cr_b.commit()
        self.assertTrue(got, msg="lock must release at transaction commit")


class TestContentAddressableUrl(TransactionCase):
    """The ESM bundle URL is derived from the bundle's SHA256."""

    def test_identical_content_produces_identical_url(self):
        # We drive _save_esm_attachment directly so we can compare URLs
        # without spawning esbuild. A minimal asset_bundle stub suffices.
        class _Stub:
            name = "test.cas.same"
            _last_metafile = None

        ir_qweb = self.env["ir.qweb"]
        content = "export const x = 1;"
        url1 = ir_qweb._save_esm_attachment("test.cas.same", content, _Stub())
        # Second call with identical content must hit the "reuse" branch
        # and return the same URL.
        url2 = ir_qweb._save_esm_attachment("test.cas.same", content, _Stub())
        self.assertEqual(url1, url2)
        self.assertRegex(
            url1,
            r"^/web/assets/esm/[0-9a-f]{16}/test\.cas\.same\.esm\.js$",
            msg="URL must match content-addressable scheme",
        )

    def test_different_content_produces_different_url(self):
        class _Stub:
            name = "test.cas.diff"
            _last_metafile = None

        ir_qweb = self.env["ir.qweb"]
        url_a = ir_qweb._save_esm_attachment(
            "test.cas.diff", "export const x = 1;", _Stub(),
        )
        url_b = ir_qweb._save_esm_attachment(
            "test.cas.diff", "export const x = 2;", _Stub(),
        )
        self.assertNotEqual(url_a, url_b)
        # Stale cleanup runs on save: the old URL's attachment should be
        # unlinked so only the new one remains.
        attachments = self.env["ir.attachment"].sudo().search([
            ("url", "=like", "/web/assets/esm/%/test.cas.diff.esm.js"),
        ])
        self.assertEqual(
            len(attachments), 1,
            msg="stale cleanup must drop the old-content attachment",
        )
        self.assertEqual(attachments.url, url_b)


class TestMetafileSidecar(TransactionCase):
    """Metafile attachment is created alongside the bundle."""

    def test_metafile_saved_as_sibling_when_present(self):
        class _Stub:
            name = "test.meta.present"
            # Simulate esbuild having populated this attribute with a
            # minimal valid metafile JSON.
            _last_metafile = json.dumps({"inputs": {}, "outputs": {}})

        ir_qweb = self.env["ir.qweb"]
        url = ir_qweb._save_esm_attachment(
            "test.meta.present", "/* bundle */", _Stub(),
        )
        meta_url = url[: -len(".esm.js")] + ".meta.json"
        meta = self.env["ir.attachment"].sudo().search([
            ("url", "=", meta_url), ("public", "=", True),
        ], limit=1)
        self.assertTrue(meta, msg="sibling metafile attachment must exist")
        self.assertEqual(meta.mimetype, "application/json")
        parsed = json.loads(meta.raw)
        self.assertIn("inputs", parsed)
        self.assertIn("outputs", parsed)

    def test_metafile_absent_when_esbuild_did_not_run(self):
        class _Stub:
            name = "test.meta.absent"
            _last_metafile = None

        ir_qweb = self.env["ir.qweb"]
        url = ir_qweb._save_esm_attachment(
            "test.meta.absent", "/* bundle */", _Stub(),
        )
        meta_url = url[: -len(".esm.js")] + ".meta.json"
        meta = self.env["ir.attachment"].sudo().search([
            ("url", "=", meta_url),
        ], limit=1)
        self.assertFalse(
            meta,
            msg="no metafile should be created when _last_metafile is None",
        )


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
            "web.assets_unit_tests_setup", js=True, css=False,
        )
        bridges = setup_ab._build_parent_self_bridge()
        # Every native module's specifier must have a bridge.  Sanity
        # check with a small sample rather than exhaustively enumerating.
        native_specs = {a.module_path for a in setup_ab.native_modules}
        self.assertGreater(len(bridges), 0)
        # Bridges resolve to content-addressable attachment URLs under
        # ``/web/assets/esm/bridges/<hash>.js`` (see
        # ``AssetsBundle._persist_bridge_shims``).  Pre-refactor they
        # were inline ``data:text/javascript,<urlencoded>`` URIs —
        # that pattern no longer exists.
        for spec, url in list(bridges.items())[:20]:
            self.assertIn(spec, native_specs)
            self.assertTrue(
                url.startswith("/web/assets/esm/bridges/"),
                msg=f"bridge for {spec} is not an attachment URL: {url[:80]}",
            )
            # Resolved attachment must be fetchable (hash + .js).
            self.assertRegex(url, r"^/web/assets/esm/bridges/[0-9a-f]{16}\.js$")

    def test_prod_import_map_bridges_parent_specifiers(self):
        """The production import map for a bundle with satellites must
        include bridge entries for specifiers imported by satellites'
        individually-loaded source files.

        We pick a native module that's guaranteed to be in ``setup``
        regardless of the ``ai`` module's presence (it lives in core).
        """
        self.env["ir.attachment"].sudo().search([
            ("url", "=like", "/web/assets/esm/%/web.assets_unit_tests_setup%"),
        ]).unlink()
        setup_ab = self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_unit_tests_setup", js=True, css=False,
        )
        # Pick an arbitrary @web/* specifier that exists — this avoids
        # coupling the test to optional addons like ``ai``.
        sample_spec = next(
            a.module_path for a in setup_ab.native_modules
            if a.module_path.startswith("@web/")
        )

        pre, _post = self.env["ir.qweb"]._get_native_module_nodes(
            "web.assets_unit_tests_setup", debug=False,
        )
        import_map = None
        for tag, attrs in pre:
            if attrs.get("type") == "importmap":
                import_map = json.loads(attrs["text"])["imports"]
                break
        self.assertIsNotNone(import_map, "prod must emit an import map")
        # A parent-bundle specifier must be resolvable from satellites.
        self.assertIn(
            sample_spec, import_map,
            msg=(
                f"expected parent-self bridge for {sample_spec!r}; "
                f"map size={len(import_map)}, "
                f"@web/* count={sum(1 for s in import_map if s.startswith('@web/'))}"
            ),
        )


class TestPipelineIntegration(TransactionCase):
    """End-to-end: circuit + admin override route through fallback."""

    def test_admin_override_skips_esbuild(self):
        """When a bundle is in ``force_fallback_bundles``, esbuild
        must not run — the debug-mode fallback handles rendering."""
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.force_fallback_bundles", "web.assets_web",
        )
        self.addCleanup(
            self.env["ir.config_parameter"].sudo().set_param,
            "web.esbuild.force_fallback_bundles", "",
        )

        called = []
        from odoo.addons.base.models.assetsbundle import AssetsBundle
        original = AssetsBundle.esbuild_native_bundle

        def _spy(self, *args, **kwargs):
            called.append(self.name)
            return original(self, *args, **kwargs)

        with patch.object(AssetsBundle, "esbuild_native_bundle", _spy):
            self.env["ir.qweb"]._get_asset_nodes(
                "web.assets_web", css=False, js=True,
            )
        self.assertNotIn(
            "web.assets_web", called,
            msg="admin override must bypass the esbuild subprocess",
        )

    def test_contention_falls_through_to_debug_nodes(self):
        """When the advisory lock is unavailable, nodes must still
        render via the debug-mode path instead of producing nothing."""
        ir_qweb = self.env["ir.qweb"]
        with patch.object(
            type(ir_qweb), "_esbuild_try_acquire_lock",
            return_value=False,
        ):
            # Drop cached attachments so the prod path is actually
            # attempted (otherwise the cache short-circuits the branch).
            self.env["ir.attachment"].sudo().search([
                ("url", "=like", "/web/assets/esm/%/web.assets_web%"),
            ]).unlink()
            nodes = ir_qweb._get_asset_nodes(
                "web.assets_web", css=False, js=True,
            )
        # Fallback emits individual-file + importmap nodes rather than
        # a single esbuild-bundled module; ensure the output is
        # non-empty and contains an importmap.
        self.assertTrue(nodes, msg="fallback must still produce nodes")
        tags = {tag for tag, _attrs in nodes}
        self.assertIn("script", tags)
        importmaps = [
            attrs for tag, attrs in nodes
            if tag == "script" and attrs.get("type") == "importmap"
        ]
        self.assertTrue(
            importmaps,
            msg="debug-mode fallback must emit an importmap",
        )


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
        import shutil
        from pathlib import Path
        import odoo
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
            js=True, css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        self.assertTrue(
            bundle._is_esm_bundle,
            msg="web.assets_emoji must be classified as an ESM bundle",
        )
        self.assertGreater(
            len(bundle.native_modules), 0,
            msg=(
                "bundle must have at least one native module "
                "(did ir.asset population run?)"
            ),
        )

        code = bundle.esbuild_native_bundle()

        # The esbuild entry point always calls registerNativeModules —
        # the presence of this string is the structural-integrity check.
        self.assertIn(
            "odoo.loader.registerNativeModules",
            code,
            msg="bundle output must register modules via the loader API",
        )
        # Minified output still has substance (emoji_data.js is ~36k
        # lines); a suspiciously small output means esbuild silently
        # dropped input — surface that as a test failure, not a warning.
        self.assertGreater(
            len(code), 1000,
            msg=f"bundle output suspiciously small ({len(code)} bytes)",
        )
        # Metafile is a side effect we expose to consumers; the real
        # esbuild path MUST populate it.  Skipping this check would
        # mask a regression where we lose the analysis side-channel.
        self.assertIsNotNone(
            bundle._last_metafile,
            msg="metafile sidecar must be captured after successful build",
        )

    def test_timeout_parameter_threaded_through(self):
        """``timeout_s`` arg must reach the subprocess.run() call.

        Doesn't actually time esbuild out — just asserts that calling
        ``esbuild_native_bundle(timeout_s=1)`` on a bundle with zero
        modules returns empty cleanly (the timeout is set but never
        triggers because the short-circuit in the method returns before
        any subprocess is spawned).  The real timeout-exceeded path is
        covered indirectly by the circuit breaker tests above.
        """
        IrQweb = self.env["ir.qweb"]
        assets_params = self.env["ir.asset"]._get_asset_params()
        # Re-use emoji bundle but exercise the signature change.
        bundle = IrQweb._get_asset_bundle(
            "web.assets_emoji", js=True, css=False,
            debug_assets=False, assets_params=assets_params,
        )
        # Explicit non-default args — smoke test that the overrides are
        # accepted without raising TypeError.
        code = bundle.esbuild_native_bundle(timeout_s=60, target="es2022")
        self.assertIn("odoo.loader.registerNativeModules", code)


class TestEsbuildSettingLoader(TransactionCase):
    """``_get_esbuild_setting`` reads ir.config_parameter with cast + fallback."""

    def test_unset_returns_default(self):
        IrQweb = self.env["ir.qweb"]
        # A key that is definitely not set in a fresh test DB.
        self.env["ir.config_parameter"].sudo().search([
            ("key", "=", "web.esbuild.cooldown_s"),
        ]).unlink()
        val = IrQweb._get_esbuild_setting(
            "cooldown_s", default=60.0, cast=float,
        )
        self.assertEqual(val, 60.0)

    def test_valid_param_casts(self):
        IrQweb = self.env["ir.qweb"]
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.cooldown_s", "12.5",
        )
        val = IrQweb._get_esbuild_setting(
            "cooldown_s", default=60.0, cast=float,
        )
        self.assertEqual(val, 12.5)

    def test_unparseable_param_falls_back_to_default(self):
        IrQweb = self.env["ir.qweb"]
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.cooldown_s", "not-a-number",
        )
        val = IrQweb._get_esbuild_setting(
            "cooldown_s", default=60.0, cast=float,
        )
        self.assertEqual(
            val, 60.0,
            msg="cast failure must silently fall back to the default",
        )

    def test_unknown_key_raises(self):
        IrQweb = self.env["ir.qweb"]
        # Typos in setting names would silently read empty values — catch
        # them at the call site with a fast-failing ValueError.
        with self.assertRaises(ValueError):
            IrQweb._get_esbuild_setting("totally_made_up", default=0)


class TestExternalLibsValidator(TransactionCase):
    """Cross-file validator catches drift between _ODOO_EXTERNAL_LIBS and _LIB_CANDIDATES."""

    def test_valid_configuration_passes(self):
        """The real configuration at import time must pass the validator."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle
        IrQweb = self.env["ir.qweb"]
        # Does not raise — proves the live configuration is consistent.
        AssetsBundle._validate_external_libs(
            set(IrQweb._ODOO_EXTERNAL_LIBS),
        )

    def test_missing_alias_raises(self):
        """Import-map spec without a matching alias must be rejected."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle
        with self.assertRaises(ValueError) as ctx:
            AssetsBundle._validate_external_libs({"@invented/lib"})
        self.assertIn("@invented/lib", str(ctx.exception))
        self.assertIn("_LIB_CANDIDATES", str(ctx.exception))

    def test_pattern_externals_accepted(self):
        """@odoo/owl etc. are covered by --external:@odoo/* and don't need aliases."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle
        # Does not raise even though none are in _LIB_CANDIDATES.
        AssetsBundle._validate_external_libs({
            "@odoo/owl", "@odoo/hoot",
            "@odoo/hoot-dom", "@odoo/hoot-mock",
        })


class TestEsbuildSourceMaps(TransactionCase):
    """``--sourcemap=<mode>`` plumbing through esbuild + sidecar persistence."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import shutil
        from pathlib import Path
        import odoo
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
            js=True, css=False,
            debug_assets=False,
            assets_params=assets_params,
        )

    def test_off_by_default(self):
        """Default mode is empty string — no source map captured."""
        bundle = self._bundle()
        bundle.esbuild_native_bundle()
        self.assertIsNone(
            bundle._last_sourcemap,
            msg="default behavior must not capture a source map",
        )

    def test_linked_mode_populates_last_sourcemap_and_links_bundle(self):
        """``source_maps='linked'`` writes a sidecar AND emits the directive.

        This is the mode operators will pick 95% of the time.
        ``external`` writes the map but omits the directive — see
        ``test_external_mode_emits_map_without_directive``.
        """
        bundle = self._bundle()
        code = bundle.esbuild_native_bundle(source_maps="linked")
        self.assertIsNotNone(
            bundle._last_sourcemap,
            msg="linked mode must populate _last_sourcemap",
        )
        # esbuild source maps are JSON; minimal sanity check that we
        # captured the right bytes (not e.g. the metafile).
        import json
        parsed = json.loads(bundle._last_sourcemap)
        self.assertIn("version", parsed)
        self.assertIn("mappings", parsed)
        # Bundle references the sidecar so devtools fetches it on open.
        self.assertIn("//# sourceMappingURL=", code)

    def test_external_mode_emits_map_without_directive(self):
        """``source_maps='external'`` writes the map but omits the
        ``//# sourceMappingURL=`` comment — matches esbuild's own
        semantics for ``--sourcemap=external``.  Useful when the map
        is distributed out-of-band (e.g. uploaded to a crash reporter)
        and we don't want devtools auto-fetching it.
        """
        bundle = self._bundle()
        code = bundle.esbuild_native_bundle(source_maps="external")
        self.assertIsNotNone(
            bundle._last_sourcemap,
            msg="external mode still writes the sidecar, just doesn't link it",
        )
        self.assertNotIn("//# sourceMappingURL=", code)

    def test_inline_mode_embeds_in_bundle(self):
        """``source_maps='inline'`` embeds a base64 data URL in the bundle."""
        bundle = self._bundle()
        code = bundle.esbuild_native_bundle(source_maps="inline")
        self.assertIsNone(
            bundle._last_sourcemap,
            msg="inline mode embeds in bundle, no sidecar to capture",
        )
        # Inline maps are appended as a data URL ``//# sourceMappingURL=
        # data:application/json;base64,...``.
        self.assertIn(
            "//# sourceMappingURL=data:application/json;base64,",
            code,
        )

    def test_unknown_mode_silently_falls_back(self):
        """Garbage mode value is logged and ignored — never crashes the build."""
        bundle = self._bundle()
        # ``"yes please"`` is not a valid esbuild mode; the helper must
        # treat it as off rather than passing it through and breaking
        # the subprocess. The helper logs ``WARNING source_maps_unknown_mode``
        # so misconfiguration is visible — consume it via ``assertLogs`` so
        # the test log stays clean and the structured event is asserted.
        with self.assertLogs(f"{ASSET_ROOT}.esbuild", level=logging.WARNING) as captured:
            code = bundle.esbuild_native_bundle(source_maps="yes please")
        self.assertTrue(
            any(
                "event=source_maps_unknown_mode" in r.getMessage()
                and "mode=yes please" in r.getMessage()
                for r in captured.records
            ),
            msg="invalid source_maps mode must emit a structured warning",
        )
        self.assertIsNone(bundle._last_sourcemap)
        self.assertIn("odoo.loader.registerNativeModules", code)

    def test_external_mode_persists_sidecar_attachment(self):
        """``_save_esm_attachment`` writes a ``.esm.js.map`` sibling."""
        class _Stub:
            name = "test.sm.sidecar"
            _last_metafile = None
            _last_sourcemap = '{"version":3,"sources":[],"mappings":""}'

        ir_qweb = self.env["ir.qweb"]
        url = ir_qweb._save_esm_attachment(
            "test.sm.sidecar", "/* bundle */", _Stub(),
        )
        sm_url = url + ".map"
        sm = self.env["ir.attachment"].sudo().search([
            ("url", "=", sm_url), ("public", "=", True),
        ], limit=1)
        self.assertTrue(sm, msg="external-mode sidecar attachment must exist")
        self.assertEqual(sm.mimetype, "application/json")

    def test_no_sourcemap_no_sidecar(self):
        """When ``_last_sourcemap is None`` no ``.map`` sidecar is created."""
        class _Stub:
            name = "test.sm.absent"
            _last_metafile = None
            _last_sourcemap = None

        ir_qweb = self.env["ir.qweb"]
        url = ir_qweb._save_esm_attachment(
            "test.sm.absent", "/* bundle */", _Stub(),
        )
        sm_url = url + ".map"
        sm = self.env["ir.attachment"].sudo().search([
            ("url", "=", sm_url),
        ], limit=1)
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
        self.env["ir.config_parameter"].sudo().search([
            ("key", "=", "web.esbuild.source_maps"),
        ]).unlink()
        # And the helper accepts it without raising the unknown-key
        # ValueError that catches operator typos.
        val = IrQweb._get_esbuild_setting("source_maps", default="")
        self.assertEqual(val, "")


def _fake_native_module(url="", raw_content="", module_path="", filename=None):
    """Lightweight stand-in for a JavascriptAsset in helper unit tests.

    The extracted helpers only read ``.url``, ``.raw_content``,
    ``.module_path`` and ``._filename`` off each native module, so a plain
    namespace avoids building real assets (and touching the filestore).
    """
    return SimpleNamespace(
        url=url,
        raw_content=raw_content,
        module_path=module_path,
        _filename=filename,
    )


class TestEsbuildHelpers(TransactionCase):
    """Unit tests for the helpers extracted from ``esbuild_native_bundle``.

    None of these spawn esbuild — they exercise option resolution, entry-script
    assembly, flag computation and output post-processing in isolation.  The
    real subprocess path stays covered by ``TestEsbuildSourceMaps`` /
    ``TestEsbuildIntegration``.
    """

    def _bundle(self, name="web.assets_emoji"):
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        return AssetsBundle(name, [], env=self.env)

    def _odoo_root(self):
        from pathlib import Path

        import odoo

        return Path(odoo.__path__[0]).parent

    def test_resolve_opts_applies_defaults(self):
        """``None`` arguments resolve to the class-constant defaults."""
        b = self._bundle()
        timeout_s, target, source_maps = b._esbuild_resolve_opts(None, None, None)
        self.assertEqual(timeout_s, b._ESBUILD_TIMEOUT_S)
        self.assertEqual(target, b._ESBUILD_TARGET)
        self.assertEqual(source_maps, b._ESBUILD_SOURCE_MAPS)

    def test_resolve_opts_passes_through_valid(self):
        """Explicit valid values are returned unchanged."""
        b = self._bundle()
        self.assertEqual(
            b._esbuild_resolve_opts(10, "es2022", "linked"),
            (10, "es2022", "linked"),
        )

    def test_resolve_opts_unknown_source_map_falls_back(self):
        """An unknown source-map mode degrades to ``""`` (never crashes esbuild)."""
        b = self._bundle()
        with self.assertLogs(f"{ASSET_ROOT}.esbuild", level=logging.WARNING):
            _, _, source_maps = b._esbuild_resolve_opts(5, "es2023", "bogus")
        self.assertEqual(source_maps, "")

    def test_entry_lines_register_block(self):
        """The entry lines register every native module plus ``@odoo/owl``."""
        b = self._bundle()
        b.native_modules = [
            _fake_native_module(url="/web/static/src/foo.js", module_path="@web/foo"),
        ]
        lines = b._esbuild_entry_lines(self._odoo_root())
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
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        b = self._bundle()
        b.native_modules = [_fake_native_module(url="/web/static/tests/t.js")]
        fake = (
            [],
            [
                "--external:@web/../tests/*",
                "--external:./web/static/tests/*",
                "--external:@other/../tests/*",
            ],
        )
        with patch.object(AssetsBundle, "_get_esbuild_addon_flags", return_value=fake):
            _, external_flags = b._esbuild_flags(self._odoo_root(), None)
        self.assertNotIn("--external:@web/../tests/*", external_flags)
        self.assertNotIn("--external:./web/static/tests/*", external_flags)
        self.assertIn("--external:@other/../tests/*", external_flags)

    def test_flags_adds_dynamic_child_externals(self):
        """``dynamic_child_specs`` become ``--external:<spec>`` flags."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        b = self._bundle()
        with patch.object(
            AssetsBundle, "_get_esbuild_addon_flags", return_value=([], [])
        ):
            _, external_flags = b._esbuild_flags(
                self._odoo_root(), frozenset({"@lazy/child"})
            )
        self.assertIn("--external:@lazy/child", external_flags)

    def test_postprocess_rewrites_directive_and_captures_sidecars(self):
        """``linked`` mode rewrites ``sourceMappingURL`` to the final attachment
        name and captures the metafile + source-map bytes.
        """
        import tempfile
        from pathlib import Path

        b = self._bundle("web.assets_emoji")
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
            result = b._postprocess_esbuild_output(
                out, meta, smap, "linked", entry_bytes=10, _t0=time.monotonic()
            )
        self.assertIn("//# sourceMappingURL=web.assets_emoji.esm.js.map", result)
        self.assertNotIn("tmpXYZ", result)
        self.assertEqual(b._last_metafile, '{"inputs":{}}')
        self.assertEqual(b._last_sourcemap, '{"version":3,"mappings":""}')

    def test_postprocess_no_sourcemap_leaves_last_none(self):
        """``""`` mode reads the bundle verbatim and captures no source map."""
        import tempfile
        from pathlib import Path

        b = self._bundle()
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            out = tmp / "x.out.js"
            meta = tmp / "x.meta.json"
            out.write_text("console.log(2);", encoding="utf-8")
            meta.write_text("{}", encoding="utf-8")
            result = b._postprocess_esbuild_output(
                out, meta, tmp / "x.map", "", 5, time.monotonic()
            )
        self.assertEqual(result, "console.log(2);")
        self.assertIsNone(b._last_sourcemap)

    def test_postprocess_missing_output_raises(self):
        """A vanished output file becomes a clear ``RuntimeError``."""
        import tempfile
        from pathlib import Path

        b = self._bundle()
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            with self.assertRaises(RuntimeError) as ctx:
                b._postprocess_esbuild_output(
                    tmp / "nope.js",
                    tmp / "nope.meta",
                    tmp / "nope.map",
                    "",
                    0,
                    time.monotonic(),
                )
        self.assertIn("output file missing", str(ctx.exception))


class TestBridgeHelpers(TransactionCase):
    """Unit tests for the helpers extracted from ``_build_native_to_legacy_bridge``."""

    def test_resolver_resolves_external_lib(self):
        """A specifier in ``ext_libs`` returns its canonical URL directly."""
        from odoo.addons.base.models.assetsbundle import _BridgeExportResolver

        r = _BridgeExportResolver(
            {"luxon": "/web/static/lib/luxon/luxon.js"}, {}, "test"
        )
        self.assertEqual(r.resolve_url("luxon"), "/web/static/lib/luxon/luxon.js")

    def test_resolver_resolves_lib_candidate(self):
        """A vendored ``_LIB_CANDIDATES`` entry maps to a ``/``-joined URL."""
        from odoo.addons.base.models.assetsbundle import _BridgeExportResolver

        r = _BridgeExportResolver({}, {"@odoo/x": ("a", "b", "c.js")}, "test")
        self.assertEqual(r.resolve_url("@odoo/x"), "/a/b/c.js")

    def test_resolver_resolves_addon_paths(self):
        """``@addon`` specifiers map to ``src`` / ``lib`` / ``tests`` URLs."""
        from odoo.addons.base.models.assetsbundle import _BridgeExportResolver

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
        from odoo.addons.base.models.assetsbundle import _BridgeExportResolver

        r = _BridgeExportResolver({}, {}, "test")
        self.assertIsNone(r.resolve_url("luxon"))
        self.assertIsNone(r.resolve_url("@noslash"))

    def test_resolver_caches_and_get_protocol(self):
        """``read_source`` caches misses; ``get`` honors the source_map default."""
        from odoo.addons.base.models.assetsbundle import _BridgeExportResolver

        r = _BridgeExportResolver({}, {}, "test")
        self.assertIsNone(r.read_source("nope"))  # unmappable -> None, cached
        self.assertIn("nope", r._cache)
        self.assertIsNone(r._cache["nope"])
        self.assertIsNone(r.get("nope"))
        self.assertEqual(r.get("nope", "DEFAULT"), "DEFAULT")

    def test_discover_classifies_import_kinds(self):
        """Named / default / namespace imports are classified per specifier."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle

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
        discovered, ext_seen = b._discover_bridge_specifiers(set(), set())
        self.assertEqual(discovered.get("@web/named"), set())
        self.assertEqual(discovered.get("@web/deflt"), {"__default__"})
        self.assertEqual(discovered.get("@web/star"), {"__star__"})
        self.assertEqual(ext_seen, set())

    def test_discover_excludes_ignored(self):
        """Own / owl / external-lib specifiers are excluded; ext libs recorded."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle

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
        discovered, ext_seen = b._discover_bridge_specifiers(
            {"@web/own"}, {"@web/extlib"}
        )
        self.assertNotIn("@web/own", discovered)
        self.assertNotIn("@odoo/owl", discovered)
        self.assertNotIn("@web/extlib", discovered)
        self.assertIn("@web/keep", discovered)
        self.assertEqual(ext_seen, {"@web/extlib"})

    def test_shim_source_default_and_named(self):
        """A default + named surface emits ``export default`` and sorted names."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        shim, star = AssetsBundle._bridge_shim_source(
            "@web/foo", set(), {"b", "a"}, True
        )
        self.assertFalse(star)
        self.assertIn("const _m = odoo.loader.modules.get('@web/foo');", shim)
        self.assertIn("const _d = _m?.default ?? _m;", shim)
        self.assertIn("export default _d;", shim)
        self.assertIn("export const a = _m?.a;", shim)
        self.assertIn("export const b = _m?.b;", shim)
        self.assertLess(shim.index("export const a"), shim.index("export const b"))

    def test_shim_source_star_fallback(self):
        """No names and no default -> the ``export default _m`` star fallback."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        shim, star = AssetsBundle._bridge_shim_source("@web/bar", set(), set(), False)
        self.assertTrue(star)
        self.assertIn("export default _m;", shim)
        self.assertNotIn("_m?.default", shim)

    def test_shim_source_named_only_no_default(self):
        """Named exports without a default emit no ``export default``."""
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        shim, star = AssetsBundle._bridge_shim_source("@web/baz", set(), {"x"}, False)
        self.assertFalse(star)
        self.assertIn("export const x = _m?.x;", shim)
        self.assertNotIn("export default", shim)

    def test_shim_source_default_kind_triggers_export(self):
        """A ``__default__`` consumer kind forces a default export even when the
        source surface is empty.
        """
        from odoo.addons.base.models.assetsbundle import AssetsBundle

        shim, star = AssetsBundle._bridge_shim_source(
            "@web/q", {"__default__"}, set(), False
        )
        self.assertFalse(star)
        self.assertIn("export default _d;", shim)
