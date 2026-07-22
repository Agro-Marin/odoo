import logging
import time
from unittest.mock import patch

import odoo
import odoo.tests
from odoo.modules.module import get_manifest
from odoo.tests.common import HttpCase
from odoo.tools import mute_logger
from odoo.tools.sass_embedded import SassCompileError, close_sass_compiler

_logger = logging.getLogger(__name__)


class TestAssetsGenerateTimeCommon(odoo.tests.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure the dart:sass singleton is shut down after this class so the
        # test framework's child-process check does not warn about it.
        cls.addClassCleanup(close_sass_compiler)

    def generate_bundles(self, unlink=True):
        if unlink:
            self.env["ir.attachment"].search(
                [("url", "=like", "/web/assets/%")]
            ).unlink()
        installed_module_names = (
            self.env["ir.module.module"]
            .search([("state", "=", "installed")])
            .mapped("name")
        )
        bundles = {
            key
            for module in installed_module_names
            for key in get_manifest(module).get("assets", [])
            # Skip private sub-bundles (documented convention: segment after '.'
            # starts with '_'). These are composition-only bundles never meant
            # to compile standalone; e.g. web._assets_helpers, web._assets_bootstrap.
            if not any(seg.startswith("_") for seg in key.split("."))
        }

        for bundle_name in bundles:
            # Two loggers can fire here: the legacy classic pipeline logs under
            # "odoo.addons.base.models.assetsbundle", while the asset event bus
            # (``get_asset_logger``) logs under "odoo.assets.bundle" — the latter
            # emits one ERROR per module-syntax file when an ESM-only bundle
            # (e.g. web.assets_backend, served only via its ESM parent
            # web.assets_web) is force-generated standalone here. This test only
            # measures timing, so both must be muted; naming just the first let
            # ~1880 spurious ERRORs leak per run.
            with mute_logger(
                "odoo.addons.base.models.assetsbundle", "odoo.assets.bundle"
            ):
                for assets_type in "css", "js":
                    try:
                        start_t = time.time()
                        css = assets_type == "css"
                        js = assets_type == "js"
                        bundle = self.env["ir.qweb"]._get_asset_bundle(
                            bundle_name, css=css, js=js
                        )
                        if assets_type == "css" and bundle.stylesheets:
                            bundle.css()
                        if assets_type == "js" and bundle.javascripts:
                            bundle.js()
                        yield (
                            f"{bundle_name}.{assets_type}",
                            time.time() - start_t,
                        )
                    except ValueError, SassCompileError:
                        _logger.info(
                            "Error detected while generating bundle %r %s",
                            bundle_name,
                            assets_type,
                        )


@odoo.tests.tagged(
    "post_install", "-at_install", "assets_bundle", "web_unit", "web_assets"
)
class TestLogsAssetsGenerateTime(TestAssetsGenerateTimeCommon):
    def test_logs_assets_generate_time(self):
        """Monitor bundle generation time from cold (existing attachments unlinked first).

        generate_bundles() swallows generation errors (try/except + mute_logger)
        since this test measures timing, not correctness.
        """
        for bundle, duration in list(self.generate_bundles()):
            _logger.info("Bundle %r generated in %.2fs", bundle, duration)

    def test_logs_assets_check_time(self):
        """Monitor bundle check time when attachments already exist (no unlink).

        generate_bundles() swallows generation errors (try/except + mute_logger)
        since this test measures timing, not correctness.
        """
        start = time.time()
        for bundle, duration in self.generate_bundles(False):
            _logger.info("Bundle %r checked in %.2fs", bundle, duration)
        duration = time.time() - start
        _logger.info("All bundle checked in %.2fs", duration)


@odoo.tests.tagged(
    "post_install",
    "-at_install",
    "-standard",
    "test_assets",
    "web_http",
    "web_assets",
)
class TestPregenerateTime(HttpCase):
    def test_logs_pregenerate_time(self):
        self.env["ir.qweb"]._pregenerate_assets_bundles()
        start = time.time()
        self.env.registry.clear_cache()
        self.env.cache.invalidate()
        with self.profile(
            collectors=[
                "sql",
                odoo.tools.profiler.PeriodicCollector(interval=0.01),
            ],
            disable_gc=True,
        ):
            self.env["ir.qweb"]._pregenerate_assets_bundles()
        duration = time.time() - start
        _logger.info("All bundle checked in %.2fs", duration)


@odoo.tests.tagged(
    "post_install",
    "-at_install",
    "-standard",
    "assets_bundle",
    "web_unit",
    "web_assets",
)
class TestAssetsGenerateTime(TestAssetsGenerateTimeCommon):
    """Run nightly to ensure bundle generation does not exceed a low threshold."""

    def test_assets_generate_time(self):
        thresholds = {
            "project.webclient.js": 2.5,
            "point_of_sale.pos_assets_backend.js": 2.5,
            "web.assets_backend.js": 2.5,
        }
        for bundle, duration in self.generate_bundles():
            threshold = thresholds.get(bundle, 2)
            self.assertLess(
                duration,
                threshold,
                f"Bundle {bundle!r} took more than {threshold} sec",
            )


@odoo.tests.tagged("post_install", "-at_install", "web_http", "web_assets")
class TestLoad(HttpCase):
    def test_assets_already_exists(self):
        self.authenticate("admin", "admin")
        # TODO xdo adapt this test. url open won't generate attachment anymore even if not pregenerated
        _save_attachment = (
            odoo.addons.base.models.assetsbundle.AssetsBundle.save_attachment
        )

        def save_attachment(bundle, extension, content):
            attachment = _save_attachment(bundle, extension, content)
            message = f"Trying to save an attachment for {bundle.name} when it should already exist: {attachment.url}"
            _logger.error(message)
            return attachment

        with patch(
            "odoo.addons.base.models.assetsbundle.AssetsBundle.save_attachment",
            save_attachment,
        ):
            self.url_open("/odoo").raise_for_status()
            self.url_open("/").raise_for_status()


@odoo.tests.tagged("post_install", "-at_install", "web_http", "web_assets")
class TestWebAssetsCursors(HttpCase):
    """Tests the cursor usage of the /web/assets route.

    The route is almost always read-only, except when the bundle is missing/outdated.
    To avoid opening a read/write cursor on every request, it checks with a read-only
    cursor first and only opens a new one to generate the bundle when needed.

    This is only safe because the route's flow is simple (check, generate, return)
    with no other database operation in between: if the check itself needed a
    read/write cursor (no replica available), reusing it avoids opening a second one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bundle_name = "web.assets_frontend"
        cls.bundle_version = (
            cls.env["ir.qweb"]._get_asset_bundle(cls.bundle_name).get_version("css")
        )

    def setUp(self):
        super().setUp()
        self.env["ir.attachment"].search([("url", "=like", "/web/assets/%")]).unlink()
        self.bundle_name = "web.assets_frontend"

    def _get_generate_cursors_readwriteness(self):
        """Return the read/write state of each cursor opened while generating the bundle.

        :return: [('ro'|'rw', '(ro_requested)'|'(rw_requested)'), ...]
        """
        cursors = []
        original_cursor = self.env.registry.cursor

        def cursor(readonly=False):
            cursor = original_cursor(readonly=readonly)
            cursors.append(
                (
                    "ro" if cursor.readonly else "rw",
                    "(ro_requested)" if readonly else "(rw_requested)",
                )
            )
            return cursor

        with patch.object(self.env.registry, "cursor", cursor):
            response = self.url_open(
                f"/web/assets/{self.bundle_version}/{self.bundle_name}.min.css",
                allow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        return cursors

    def test_web_binary_keep_cursor_ro(self):
        """With a replica, generation needs a ro then a rw cursor when cold, and a single ro cursor when warm."""
        self.assertEqual(
            self._get_generate_cursors_readwriteness(),
            [
                ("ro", "(ro_requested)"),
                ("rw", "(rw_requested)"),
            ],
            "A ro and rw cursor should be used to generate assets with replica when cold",
        )

        self.assertEqual(
            self._get_generate_cursors_readwriteness(),
            [
                ("ro", "(ro_requested)"),
            ],
            "Only one readonly cursor should be used to generate assets with replica when warm",
        )

    def test_web_binary_keep_cursor_rw(self):
        self.set_registry_readonly_mode(False)
        self.assertEqual(
            self._get_generate_cursors_readwriteness(),
            [
                ("rw", "(ro_requested)"),
            ],
            "Only one readwrite cursor should be used to generate assets without replica",
        )
