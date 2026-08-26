import base64
import os
import time
import unittest
from collections import Counter
from unittest.mock import Mock, patch

from odoo import api
from odoo.tests import HttpCase
from odoo.tests.common import BaseCase, TransactionCase, tagged
from odoo.tools import mute_logger
from odoo.tools.misc import file_path

from .common import FileTouchable
from odoo.addons.base.models.assetsbundle import (
    ANY_UNIQUE,
    AssetAttachmentStore,
    AssetError,
    AssetNotFoundError,
    AssetsBundle,
    WebAsset,
    XMLAssetError,
)
from odoo.addons.base.models.assetsbundle.common import CompileError
from odoo.addons.base.models.ir_attachment import IrAttachment


class TestJavascriptAssetsBundle(FileTouchable):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.maxDiff = 10000
        cls.env["ir.attachment"].search(
            [("url", "=like", "/web/assets/%test_assetsbundle%")]
        ).unlink()

    def setUp(self):
        super().setUp()
        self.jsbundle_name = "test_assetsbundle.bundle1"
        self.cssbundle_name = "test_assetsbundle.bundle2"

    def _get_asset(self, bundle, rtl=False, debug_assets=False):
        files, _ = self.env["ir.qweb"]._get_asset_content(bundle)
        return AssetsBundle(
            bundle, files, env=self.env, debug_assets=debug_assets, rtl=rtl
        )

    def _assert_bundle_changed(self, bundle0, bundle1, method):
        """Assert that rebuilding a bundle after an ir.asset addition
        changed both its computed file list and its version."""
        self.assertNotEqual(
            bundle0.files,
            bundle1.files,
            "the list of files should be different because a file has been added to the bundle",
        )
        self.assertNotEqual(
            bundle0.get_version(method),
            bundle1.get_version(method),
            "the version should be different because a file has been added to the bundle",
        )

    def _any_ira_for_bundle(self, extension, rtl=False):
        bundle = (
            self.jsbundle_name if extension in ["js", "min.js"] else self.cssbundle_name
        )
        direction = ".rtl" if rtl else ""
        bundle_name = f"{bundle}{direction}.{extension}"
        url = self.env["ir.asset"]._get_asset_bundle_url(bundle_name, ANY_UNIQUE, {})
        domain = [("url", "=like", url)]
        return self.env["ir.attachment"].search(domain)

    def test_01_generation(self):
        self.bundle = self._get_asset(self.jsbundle_name, debug_assets=False)

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            0,
            "there shouldn't be any minified attachment associated to this bundle",
        )
        self.assertEqual(
            len(self.bundle.get_attachments("min.js")),
            0,
            "there shouldn't be any minified attachment associated to this bundle",
        )

        self.bundle.js()

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified attachment associated to this bundle",
        )
        self.assertEqual(
            len(self.bundle.get_attachments("min.js")),
            1,
            "there should be one minified attachment associated to this bundle",
        )

        self.assertEqual(
            len(self._any_ira_for_bundle("js")),
            0,
            "there shouldn't be any non-minified attachment associated to this bundle",
        )
        self.assertEqual(
            len(self.bundle.get_attachments("js")),
            0,
            "there shouldn't be any non-minified attachment associated to this bundle",
        )

        self.bundle_debug = self._get_asset(self.jsbundle_name, debug_assets=True)
        self.bundle_debug.js()

        self.assertEqual(
            len(self._any_ira_for_bundle("js")),
            1,
            "there should be one non-minified attachment associated to this bundle",
        )
        self.assertEqual(
            len(self.bundle.get_attachments("js")),
            1,
            "there should be one non-minified attachment associated to this bundle",
        )

    def test_02_access(self):
        bundle0 = self._get_asset(self.jsbundle_name, debug_assets=False)
        bundle0.js()

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified attachment associated to this bundle",
        )

        version0 = bundle0.get_version("js")
        ira0 = self._any_ira_for_bundle("min.js")
        date0 = ira0.create_date

        bundle1 = self._get_asset(self.jsbundle_name, debug_assets=False)
        bundle1.js()

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified attachment associated to this bundle",
        )

        version1 = bundle1.get_version("js")
        ira1 = self._any_ira_for_bundle("min.js")
        date1 = ira1.create_date

        self.assertEqual(
            version0,
            version1,
            "the version should not be changed because the bundle hasn't changed",
        )
        self.assertEqual(
            date0,
            date1,
            "the date of creation of the ir.attachment should not change because the bundle is unchanged",
        )

    def test_03_date_invalidation(self):
        bundle0 = self._get_asset(self.jsbundle_name, debug_assets=True)
        bundle0.js()
        last_modified0 = bundle0.get_checksum("js")
        version0 = bundle0.get_version("js")

        path = file_path("test_assetsbundle/static/src/js/test_jsfile1.js")
        bundle1 = self._get_asset(self.jsbundle_name, debug_assets=True)

        with self._touch(path):
            bundle1.js()
            last_modified1 = bundle1.get_checksum("js")
            version1 = bundle1.get_version("js")
            self.assertNotEqual(
                last_modified0,
                last_modified1,
                "the creation date of the ir.attachment should change because the bundle has changed.",
            )
            self.assertNotEqual(
                version0,
                version1,
                "the version must change because the bundle has changed.",
            )

            self.assertEqual(
                len(self._any_ira_for_bundle("js")),
                1,
                "there should be one minified attachment associated to this bundle",
            )

    def test_04_content_invalidation(self):
        bundle0 = self._get_asset(self.jsbundle_name)
        bundle0.js()

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified attachment associated to this bundle",
        )

        self.env["ir.asset"].create(
            {
                "name": "test bundle inheritance",
                "bundle": self.jsbundle_name,
                "path": "test_assetsbundle/static/src/js/test_jsfile4.js",
            }
        )

        bundle1 = self._get_asset(self.jsbundle_name)
        bundle1.js()

        self._assert_bundle_changed(bundle0, bundle1, "js")

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified attachment associated to this bundle",
        )

    def test_05_normal_mode(self):
        bundle = self._get_asset(self.jsbundle_name)
        content = bundle.get_links()
        bundle.js()
        self.assertIn("test_assetsbundle.bundle1.min.js", content[0])

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified assets created in normal mode",
        )

        self.assertEqual(
            len(self._any_ira_for_bundle("js")),
            0,
            "there shouldn't be any non-minified assets created in normal mode",
        )

    def test_06_defer_assets_loading(self):
        nodes = self.env["ir.qweb"]._get_asset_nodes(self.jsbundle_name)
        self.assertEqual(len(nodes), 1, "there should be one node generated")
        self.assertEqual(nodes[0][0], "script", "the node should be a script")
        attrs = nodes[0][1]
        self.assertIn("src", attrs, "there should be a src on the script")
        self.assertNotIn(
            "data-src", attrs, "there should not be a fake src on the script"
        )
        self.assertNotIn("defer", attrs, "the script should not have defer loading")

        nodes = self.env["ir.qweb"]._get_asset_nodes(
            self.jsbundle_name, defer_load=True
        )
        self.assertEqual(len(nodes), 1, "there should be one node generated")
        self.assertEqual(nodes[0][0], "script", "the node should be a script")
        attrs = nodes[0][1]
        self.assertIn("src", attrs, "there should be a src on the script")
        self.assertNotIn(
            "data-src", attrs, "there should not be a fake src on the script"
        )
        self.assertIn("defer", attrs, "the script should have defer loading")

        nodes = self.env["ir.qweb"]._get_asset_nodes(self.jsbundle_name, lazy_load=True)
        self.assertEqual(len(nodes), 1, "there should be one node generated")
        self.assertEqual(nodes[0][0], "script", "the node should be a script")
        attrs = nodes[0][1]
        self.assertNotIn("src", attrs, "there should not be a src on the script")
        self.assertIn("data-src", attrs, "there should be a fake src on the script")
        self.assertNotIn(
            "defer",
            attrs,
            "the script should not have defer loading, this is not valid without src",
        )

    def test_07_debug_assets(self):
        debug_bundle = self._get_asset(self.jsbundle_name, debug_assets=True)
        content = debug_bundle.get_links()
        debug_bundle.js()
        self.assertIn(
            "test_assetsbundle.bundle1.js",
            content[0],
            "there should be one non-minified assets created in debug assets mode",
        )

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            0,
            "there shouldn't be any minified assets created in debug assets mode",
        )

        self.assertEqual(
            len(self._any_ira_for_bundle("js")),
            1,
            "there should be one non-minified assets without a version in its url created in debug assets mode",
        )

    def test_08_css_generation3(self):
        self.bundle = self._get_asset(self.cssbundle_name)
        self.bundle.css()
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)
        self.assertEqual(len(self.bundle.get_attachments("min.css")), 1)

    def test_09_css_access(self):
        bundle0 = self._get_asset(self.cssbundle_name)
        bundle0.css()

        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

        version0 = bundle0.get_version("css")
        ira0 = self._any_ira_for_bundle("min.css")
        date0 = ira0.create_date

        bundle1 = self._get_asset(self.cssbundle_name)
        bundle1.css()

        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

        version1 = bundle1.get_version("css")
        ira1 = self._any_ira_for_bundle("min.css")
        date1 = ira1.create_date

        self.assertEqual(version0, version1)
        self.assertEqual(date0, date1)

    def test_10_css_content_invalidation(self):
        bundle0 = self._get_asset(self.cssbundle_name)
        bundle0.css()

        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

        self.env["ir.asset"].create(
            {
                "name": "test bundle inheritance",
                "bundle": self.cssbundle_name,
                "path": "test_assetsbundle/static/src/css/test_cssfile2.css",
            }
        )

        bundle1 = self._get_asset(self.cssbundle_name)
        bundle1.css()

        self._assert_bundle_changed(bundle0, bundle1, "css")

        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

    def test_11_css_debug(self):
        debug_bundle = self._get_asset(self.cssbundle_name, debug_assets=True)
        links = debug_bundle.get_links()
        self.assertEqual(links[0], "/web/assets/debug/test_assetsbundle.bundle2.css")

        debug_bundle.css()
        self.assertEqual(
            len(self._any_ira_for_bundle("css")),
            1,
            "there should be one css asset created in debug mode",
        )

    def test_12_duplicated_css_assets(self):
        bundle0 = self._get_asset(self.cssbundle_name)
        bundle0.css()
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

        ira0 = self._any_ira_for_bundle("min.css")
        ira1 = ira0.copy()
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 2)
        self.assertEqual(ira0.store_fname, ira1.store_fname)

        content = bundle0.get_links()
        self.assertIn("test_assetsbundle.bundle2.min.css", content[0])

    def test_13_rtl_css_generation(self):
        self.bundle = self._get_asset(self.cssbundle_name, rtl=True)

        self.assertEqual(len(self._any_ira_for_bundle("min.css", rtl=True)), 0)
        self.assertEqual(len(self.bundle.get_attachments("min.css")), 0)

        self.bundle.css()

        self.assertEqual(len(self.bundle.css_errors), 0)

        self.assertEqual(len(self._any_ira_for_bundle("min.css", rtl=True)), 1)
        self.assertEqual(len(self.bundle.get_attachments("min.css")), 1)

    def test_14_rtl_invalid_css_generation(self):
        self.bundle = self._get_asset("test_assetsbundle.broken_css", rtl=True)
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle.css()
        self.assertEqual(len(self.bundle.css_errors), 1)
        self.assertIn("rtlcss: error processing payload", self.bundle.css_errors[0])

    def test_15_ltr_and_rtl_css_access(self):
        ltr_bundle0 = self._get_asset(self.cssbundle_name, debug_assets=False)
        ltr_bundle0.css()

        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

        ltr_version0 = ltr_bundle0.get_version("css")
        ltr_ira0 = self._any_ira_for_bundle("min.css")
        self.assertTrue(ltr_ira0)

        ltr_bundle1 = self._get_asset(self.cssbundle_name, debug_assets=False)
        ltr_bundle1.css()

        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

        ltr_version1 = ltr_bundle1.get_version("css")
        ltr_ira1 = self._any_ira_for_bundle("min.css")
        self.assertTrue(ltr_ira1)

        self.assertEqual(ltr_version0, ltr_version1)

        rtl_bundle0 = self._get_asset(self.cssbundle_name, rtl=True, debug_assets=False)
        rtl_bundle0.css()

        self.assertEqual(len(self._any_ira_for_bundle("min.css", rtl=True)), 1)

        rtl_version0 = rtl_bundle0.get_version("css")

        rtl_bundle1 = self._get_asset(self.cssbundle_name, rtl=True, debug_assets=False)
        rtl_bundle1.css()

        self.assertEqual(len(self._any_ira_for_bundle("min.css", rtl=True)), 1)

        rtl_version1 = rtl_bundle1.get_version("css")
        rtl_ira1 = self._any_ira_for_bundle("min.css", rtl=True)

        self.assertEqual(rtl_version0, rtl_version1)

        self.assertNotEqual(ltr_ira1.id, rtl_ira1.id)

        css_bundles = self.env["ir.attachment"].search(
            [
                (
                    "url",
                    "=like",
                    f"/web/assets/%/{self.cssbundle_name}%.min.css",
                ),
            ]
        )
        self.assertEqual(len(css_bundles), 2)

    def test_16_css_bundle_date_invalidation(self):
        ltr_bundle0 = self._get_asset(self.cssbundle_name, debug_assets=True)
        ltr_bundle0.css()
        ltr_last_modified0 = ltr_bundle0.get_checksum("css")
        ltr_version0 = ltr_bundle0.get_version("css")

        rtl_bundle0 = self._get_asset(self.cssbundle_name, rtl=True, debug_assets=True)
        rtl_bundle0.css()
        rtl_last_modified0 = rtl_bundle0.get_checksum("css")
        rtl_version0 = rtl_bundle0.get_version("css")

        path = file_path("test_assetsbundle/static/src/css/test_cssfile1.css")
        ltr_bundle1 = self._get_asset(self.cssbundle_name, debug_assets=True)

        with self._touch(path):
            ltr_bundle1.css()
            ltr_last_modified1 = ltr_bundle1.get_checksum("css")
            ltr_version1 = ltr_bundle1.get_version("css")
            ltr_ira1 = self._any_ira_for_bundle("css")
            self.assertNotEqual(ltr_last_modified0, ltr_last_modified1)
            self.assertNotEqual(ltr_version0, ltr_version1)

            rtl_bundle1 = self._get_asset(
                self.cssbundle_name, rtl=True, debug_assets=True
            )

            rtl_bundle1.css()
            rtl_last_modified1 = rtl_bundle1.get_checksum("css")
            rtl_version1 = rtl_bundle1.get_version("css")
            rtl_ira1 = self._any_ira_for_bundle("css", rtl=True)
            self.assertNotEqual(rtl_last_modified0, rtl_last_modified1)
            self.assertNotEqual(rtl_version0, rtl_version1)

            self.assertNotEqual(ltr_ira1.id, rtl_ira1.id)

            css_bundles = self.env["ir.attachment"].search(
                [
                    (
                        "url",
                        "=like",
                        f"/web/assets/%/{self.cssbundle_name}%.css",
                    ),
                ]
            )
            self.assertEqual(len(css_bundles), 2)

    def test_17_css_bundle_content_invalidation(self):
        ltr_bundle0 = self._get_asset(self.cssbundle_name)
        ltr_bundle0.css()

        rtl_bundle0 = self._get_asset(self.cssbundle_name, rtl=True)
        rtl_bundle0.css()

        css_bundles = self.env["ir.attachment"].search(
            [
                (
                    "url",
                    "=like",
                    f"/web/assets/%/{self.cssbundle_name}%.min.css",
                ),
            ]
        )
        self.assertEqual(len(css_bundles), 2)

        self.env["ir.asset"].create(
            {
                "name": "test bundle inheritance",
                "bundle": self.cssbundle_name,
                "path": "test_assetsbundle/static/src/css/test_cssfile3.css",
            }
        )

        ltr_bundle1 = self._get_asset(self.cssbundle_name)
        ltr_bundle1.css()
        ltr_ira1 = self._any_ira_for_bundle("min.css")

        self._assert_bundle_changed(ltr_bundle0, ltr_bundle1, "css")

        rtl_bundle1 = self._get_asset(self.cssbundle_name, rtl=True)
        rtl_bundle1.css()
        rtl_ira1 = self._any_ira_for_bundle("min.css", rtl=True)

        self._assert_bundle_changed(rtl_bundle0, rtl_bundle1, "css")

        self.assertNotEqual(ltr_ira1.id, rtl_ira1.id)

        css_bundles = self.env["ir.attachment"].search(
            [
                (
                    "url",
                    "=like",
                    f"/web/assets/%/{self.cssbundle_name}%.min.css",
                ),
            ]
        )
        self.assertEqual(len(css_bundles), 2)

    def test_18_css_in_debug_assets(self):
        debug_bundle = self._get_asset(self.cssbundle_name, rtl=True, debug_assets=True)
        content = debug_bundle.get_links()

        self.assertEqual(
            f"/web/assets/debug/{self.cssbundle_name}.rtl.css",
            content[0],
            "there should be an css assets bundle in /debug/rtl if user's lang direction is rtl and debug=assets",
        )

        debug_bundle.css()
        css_bundle = self.env["ir.attachment"].search(
            [
                (
                    "url",
                    "=like",
                    f"/web/assets/%/{self.cssbundle_name}.rtl.css",
                ),
            ]
        )
        self.assertEqual(
            len(css_bundle),
            1,
            "there should be an css assets bundle created in /rtl if user's lang direction is rtl and debug=assets",
        )

    def test_19_external_lib_assets(self):
        html = self.env["ir.ui.view"]._render_template("test_assetsbundle.template2")

        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.bundle4")
        links = bundle.get_links()
        self.assertEqual(len(links), 6)

        self.assertEqual(
            str(html.strip()),
            (
                f"""<!DOCTYPE html>
<html>
    <head>
        <link type="text/css" rel="stylesheet" href="http://test.external.link/style1.css"/>
        <link type="text/css" rel="stylesheet" href="http://test.external.link/style2.css"/>
        <link type="text/css" rel="stylesheet" href="{links[4]}"/>
        <meta/>
        <script type="text/javascript" src="http://test.external.link/javascript1.js"></script>
        <script type="text/javascript" src="http://test.external.link/javascript2.js"></script>
        <script type="text/javascript" src="{links[5]}"></script>
    </head>
    <body>
    </body>
</html>"""
            ),
        )

    def test_20_external_lib_assets_debug_mode(self):
        html = self.env["ir.ui.view"]._render_template(
            "test_assetsbundle.template2", {"debug": "assets"}
        )
        self.assertEqual(
            str(html.strip()),
            (
                """<!DOCTYPE html>
<html>
    <head>
        <link type="text/css" rel="stylesheet" href="http://test.external.link/style1.css"/>
        <link type="text/css" rel="stylesheet" href="http://test.external.link/style2.css"/>
        <link type="text/css" rel="stylesheet" href="/web/assets/debug/test_assetsbundle.bundle4.css"/>
        <meta/>
        <script type="text/javascript" src="http://test.external.link/javascript1.js"></script>
        <script type="text/javascript" src="http://test.external.link/javascript2.js"></script>
        <script type="text/javascript" src="/web/assets/debug/test_assetsbundle.bundle4.js"></script>
    </head>
    <body>
    </body>
</html>"""
            ),
        )


class TestAssetsBundleWithIRAMock(FileTouchable):
    def setUp(self):
        super().setUp()
        self.stylebundle_name = "test_assetsbundle.bundle3"
        self.counter = counter = Counter()

        origin_create = IrAttachment.create
        origin_unlink = AssetAttachmentStore._unlink_attachments

        @api.model_create_multi
        def create(self, vals_list):
            counter.update(["create"] * len(vals_list))
            return origin_create(self, vals_list)

        def unlink(self, attachments):
            counter.update(["unlink"])
            return origin_unlink(self, attachments)

        self.patch(IrAttachment, "create", create)
        self.patch(AssetAttachmentStore, "_unlink_attachments", unlink)

    def _get_asset(self, debug_assets=True):
        with patch.object(
            type(self.env["ir.asset"]),
            "_get_addons_installed",
            Mock(return_value=self.installed_modules),
        ):
            return self.env["ir.qweb"]._get_asset_bundle(
                self.stylebundle_name, debug_assets=debug_assets
            )

    def _bundle(self, bundle, should_create, should_unlink, reason=""):
        self.counter.clear()
        bundle.css()
        if should_create:
            self.assertEqual(
                self.counter["create"],
                2,
                f"An attachment should have been created {reason}",
            )
        else:
            self.assertEqual(
                self.counter["create"],
                0,
                f"No attachment should have been created {reason}",
            )

        if should_unlink:
            self.assertEqual(
                self.counter["unlink"],
                2,
                f"An attachment should have been unlink {reason}",
            )
        else:
            self.assertEqual(
                self.counter["unlink"],
                0,
                f"No attachment should have been unlink {reason}",
            )

    def test_01_debug_mode_assets(self):
        self._bundle(self._get_asset(), True, False, "(First access)")

        self._bundle(self._get_asset(), False, False, "(Second access, no change)")

        path = file_path("test_assetsbundle/static/src/scss/test_file1.scss")
        t = time.time() + 5
        asset = self._get_asset()
        with self._touch(path, t):
            self._bundle(asset, True, True)

            self._bump_last_attachment_write_date(10)

            self._bundle(self._get_asset(), False, False)


@tagged("-at_install", "post_install")
class AssetsNodeOrmCacheUsage(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env.registry.clear_cache("assets")
        self.addCleanup(self.env.registry.clear_cache, "assets")

    def cache_keys(self):
        lrus = self.env.registry.ormcache_lrus
        keys = [key for store in ("assets", "assets.links") for key in lrus[store]]

        asset_keys = [
            key
            for key in keys
            if key[0] == "ir.asset" and "_get_asset_paths" in str(key[1])
        ]
        qweb_keys = [key for key in keys if key[0] == "ir.qweb"]
        return asset_keys, qweb_keys

    def test_assets_node_orm_cache_usage_debug(self):
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 0)
        self.assertEqual(len(qweb_keys), 0)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend")

        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", debug="tests")
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", debug="1")
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", debug="assets")
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

    def test_assets_node_orm_cache_usage_file_type(self):
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 0)
        self.assertEqual(len(qweb_keys), 0)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", js=True, css=False)
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", js=False, css=True)
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 4)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", js=True, css=True)
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 5)

    def test_assets_node_orm_cache_usage_lang(self):
        self.env["res.lang"]._activate_lang("ar_SY")
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["res.lang"]._activate_lang("en_US")

        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 0)
        self.assertEqual(len(qweb_keys), 0)

        self.env["ir.qweb"].with_context(lang="fr_FR")._get_asset_nodes(
            "web.assets_backend"
        )
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"].with_context(lang="en_US")._get_asset_nodes(
            "web.assets_backend"
        )
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"].with_context(lang="ar_SY")._get_asset_nodes(
            "web.assets_backend"
        )
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 4)

    def test_assets_node_orm_cache_usage_website(self):
        if "website" not in self.env:
            self.skipTest("website is not installed; website_id cannot key the cache")

        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 0)
        self.assertEqual(len(qweb_keys), 0)

        self.env["ir.qweb"].with_context(website_id=None)._get_asset_nodes(
            "web.assets_backend"
        )
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"].with_context(website_id=1)._get_asset_nodes(
            "web.assets_backend"
        )
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 2)
        self.assertEqual(len(qweb_keys), 6)

    def test_assets_node_orm_cache_usage_node_flags(self):
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 0)
        self.assertEqual(len(qweb_keys), 0)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend")
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", media="print")
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1, "media shouldn't create another entry")
        self.assertEqual(len(qweb_keys), 3, "media shouldn't create another entry")

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", defer_load=True)
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(
            len(asset_keys), 1, "defer_load shouldn't create another entry"
        )
        self.assertEqual(len(qweb_keys), 3, "defer_load shouldn't create another entry")

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", lazy_load=True)
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1, "lazy_load shouldn't create another entry")
        self.assertEqual(len(qweb_keys), 3, "lazy_load shouldn't create another entry")


class TestExternalAssetFilter(TransactionCase):
    def test_query_string_and_fragment_survive(self):
        bundle = AssetsBundle(
            "test_assetsbundle.ext",
            [],
            external_assets=[
                "https://cdn.example.com/lib.css?v=2",
                "https://cdn.example.com/lib.js#frag",
            ],
            env=self.env,
        )
        self.assertEqual(len(bundle.external_assets), 2)

    def test_unknown_extension_warns(self):
        with self.assertLogs("odoo.assets.bundle", level="WARNING") as cm:
            bundle = AssetsBundle(
                "test_assetsbundle.ext_bad",
                [],
                external_assets=["https://cdn.example.com/font.woff2"],
                env=self.env,
            )
        self.assertEqual(bundle.external_assets, [])
        self.assertIn("external_asset_skipped", "\n".join(cm.output))


class TestAssetErrorTaxonomy(BaseCase):
    def test_asset_error_is_the_common_base(self):
        self.assertTrue(issubclass(AssetNotFoundError, AssetError))
        self.assertTrue(issubclass(XMLAssetError, AssetError))

    def test_compile_error_is_a_separate_family(self):
        self.assertFalse(issubclass(CompileError, AssetError))
        self.assertTrue(issubclass(CompileError, RuntimeError))


class TestAuditRegressionFixes(TransactionCase):
    def _bundle(self, name="test_assetsbundle.audit_fix"):
        return AssetsBundle(name, [], env=self.env)

    def test_get_content_preserves_not_found_subclass(self):
        asset = WebAsset(self._bundle(), url="/test_assetsbundle/missing.js")
        with self.assertRaises(AssetNotFoundError) as cm:
            asset._get_content()
        self.assertIs(type(cm.exception), AssetNotFoundError)


@tagged("-at_install", "post_install")
class TestAssetsBundleInBrowser(HttpCase):
    def test_01_js_interpretation(self):
        self.browser_js(
            "/test_assetsbundle/js",
            "a + b + c === 6 ? console.log('test successful') : console.log('error')",
            login="admin",
        )

    def test_03_js_interpretation_recommended_new_method(self):
        code = b"const d = 4;"
        attach = self.env["ir.attachment"].create(
            {
                "name": "CustomJscode.js",
                "mimetype": "text/javascript",
                "datas": base64.b64encode(code),
            }
        )
        custom_url = "/web/content/%s/%s" % (attach.id, attach.name)
        attach.url = custom_url

        self.env["ir.asset"].create(
            {
                "name": "lol",
                "bundle": "test_assetsbundle.bundle1",
                "path": custom_url,
            }
        )
        self.browser_js(
            "/test_assetsbundle/js",
            "a + b + c + d === 10 ? console.log('test successful') : console.log('error')",
            login="admin",
        )


@tagged("-at_install", "post_install")
@unittest.skipIf(
    os.getenv("ODOO_FAKETIME_TEST_MODE"), "This test cannot work with faketime"
)
class TestErrorManagement(HttpCase):
    def test_assets_bundle_css_error_backend(self):
        self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_backend", assets_params={}
        ).css()
        self.env["ir.asset"].create(
            {
                "name": "Css error",
                "bundle": "web.assets_backend",
                "path": "test_assetsbundle/static/invalid_src/scss/test_error.scss",
            }
        )

        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.start_tour("/odoo", "css_error_tour", login="admin")

    def test_assets_bundle_css_error_frontend(self):
        whatever = (
            {"website_id": website.search([], limit=1).id}
            if (website := self.env.get("website"))
            else {}
        )
        self.env["ir.qweb"]._get_asset_bundle(
            "web.assets_frontend", assets_params=whatever
        ).css()
        self.env["ir.asset"].create(
            {
                "name": "Css error",
                "bundle": "web.assets_frontend",
                "path": "test_assetsbundle/static/invalid_src/scss/test_error.scss",
            }
        )
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.start_tour("/?debug=1", "css_error_tour_frontend")
