import base64
import errno
import os
import pathlib
import tempfile
import textwrap
import time
import unittest
from collections import Counter
from unittest import skip
from unittest.mock import Mock, patch

import lxml

import odoo.modules
from odoo import api
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger
from odoo.tools.misc import file_path

from odoo.addons.base.models.assetsbundle import (
    ANY_UNIQUE,
    AssetAttachmentStore,
    AssetsBundle,
    JavascriptAsset,
    XMLAssetError,
    _check_rtlcss,
)
from odoo.addons.base.models.ir_asset_paths import AssetPaths, _glob_static_file
from odoo.addons.base.models.ir_attachment import IrAttachment

ORIGINAL_PATH_STAT = pathlib.Path.stat


class TestAddonPaths(TransactionCase):
    def test_operations(self):
        asset_paths = AssetPaths()
        self.assertFalse(asset_paths.list)

        asset_paths.append(
            [
                ("/home/user/odoo/addons/web/a", "/web/a", 1),
                ("/home/user/odoo/addons/web/c", "/web/c", 1),
                ("/home/user/odoo/addons/web/d", "/web/d", 1),
            ],
            "bundle1",
        )
        self.assertEqual(
            asset_paths.list,
            [
                ("/home/user/odoo/addons/web/a", "/web/a", "bundle1", 1),
                ("/home/user/odoo/addons/web/c", "/web/c", "bundle1", 1),
                ("/home/user/odoo/addons/web/d", "/web/d", "bundle1", 1),
            ],
        )

        asset_paths.append(
            [
                ("/home/user/odoo/addons/web/c", "/web/c", 1),
                ("/home/user/odoo/addons/web/f", "/web/f", 1),
            ],
            "bundle2",
        )
        self.assertEqual(
            asset_paths.list,
            [
                ("/home/user/odoo/addons/web/a", "/web/a", "bundle1", 1),
                ("/home/user/odoo/addons/web/c", "/web/c", "bundle1", 1),
                ("/home/user/odoo/addons/web/d", "/web/d", "bundle1", 1),
                ("/home/user/odoo/addons/web/f", "/web/f", "bundle2", 1),
            ],
        )

        asset_paths.insert(
            [
                ("/home/user/odoo/addons/web/c", "/web/c", 1),
                ("/home/user/odoo/addons/web/e", "/web/e", 1),
            ],
            "bundle3",
            3,
        )
        self.assertEqual(
            asset_paths.list,
            [
                ("/home/user/odoo/addons/web/a", "/web/a", "bundle1", 1),
                ("/home/user/odoo/addons/web/c", "/web/c", "bundle1", 1),
                ("/home/user/odoo/addons/web/d", "/web/d", "bundle1", 1),
                ("/home/user/odoo/addons/web/e", "/web/e", "bundle3", 1),
                ("/home/user/odoo/addons/web/f", "/web/f", "bundle2", 1),
            ],
        )

        asset_paths.insert(
            [
                ("/home/user/odoo/addons/web/b", "/web/b", 1),
                ("/home/user/odoo/addons/web/d", "/web/d", 1),
            ],
            "bundle4",
            1,
        )
        self.assertEqual(
            asset_paths.list,
            [
                ("/home/user/odoo/addons/web/a", "/web/a", "bundle1", 1),
                ("/home/user/odoo/addons/web/b", "/web/b", "bundle4", 1),
                ("/home/user/odoo/addons/web/c", "/web/c", "bundle1", 1),
                ("/home/user/odoo/addons/web/d", "/web/d", "bundle1", 1),
                ("/home/user/odoo/addons/web/e", "/web/e", "bundle3", 1),
                ("/home/user/odoo/addons/web/f", "/web/f", "bundle2", 1),
            ],
        )

        asset_paths.remove(
            [
                ("/home/user/odoo/addons/web/c", "/web/c", 1),
                ("/home/user/odoo/addons/web/d", "/web/d", 1),
                ("/home/user/odoo/addons/web/g", "/web/g", 1),
            ],
            "bundle5",
        )
        self.assertEqual(
            asset_paths.list,
            [
                ("/home/user/odoo/addons/web/a", "/web/a", "bundle1", 1),
                ("/home/user/odoo/addons/web/b", "/web/b", "bundle4", 1),
                ("/home/user/odoo/addons/web/e", "/web/e", "bundle3", 1),
                ("/home/user/odoo/addons/web/f", "/web/f", "bundle2", 1),
            ],
        )

    def test_replace_empty_source(self):
        asset_paths = AssetPaths()
        asset_paths.append(
            [
                ("/web/a.js", "/full/a.js", 1),
                ("/web/b.js", "/full/b.js", 1),
                ("/web/c.js", "/full/c.js", 1),
            ],
            "bundle1",
        )
        target_index = asset_paths.index("/web/b.js", "bundle1")
        asset_paths.insert([], "bundle1", target_index)
        asset_paths.remove([("/web/b.js", "/full/b.js", 1)], "bundle1")

        self.assertEqual(len(asset_paths.list), 2)
        self.assertEqual(asset_paths.list[0][0], "/web/a.js")
        self.assertEqual(asset_paths.list[1][0], "/web/c.js")
        self.assertNotIn("/web/b.js", asset_paths.memo)

    def test_glob_static_file_race_condition(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = str(pathlib.Path(tmp).resolve())
            deleted_file = f"{static_dir}/_test_asset_race_condition.js"
            with patch(
                "odoo.addons.base.models.ir_asset_paths.glob",
                return_value=[deleted_file],
            ):
                result = _glob_static_file(f"{static_dir}/*.js", static_dir)
        self.assertEqual(result, [], "Deleted files should be silently skipped")

    def test_glob_static_file_filters_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = str(pathlib.Path(tmp).resolve())
            for name in ("file.js", "file.py", "file.css"):
                pathlib.Path(static_dir, name).write_text("", encoding="utf-8")
            result = _glob_static_file(f"{static_dir}/*", static_dir)
        paths = [r[0] for r in result]
        self.assertIn(f"{static_dir}/file.js", paths)
        self.assertIn(f"{static_dir}/file.css", paths)
        self.assertNotIn(f"{static_dir}/file.py", paths)

    @mute_logger(
        "odoo.addons.base.models.ir_asset",
        "odoo.addons.base.models.ir_asset_paths",
    )
    def test_glob_static_file_memo_is_not_shared_across_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_a = pathlib.Path(tmp, "a", "static")
            root_b = pathlib.Path(tmp, "b", "static")
            (root_a / "src").mkdir(parents=True)
            root_b.mkdir(parents=True)
            (root_a / "src" / "in_a.js").write_text("var a;")
            (root_b / "in_b.js").write_text("var b;")

            memo = {}
            found_a = _glob_static_file(f"{root_a}/**/*.js", str(root_a), memo)
            found_b = _glob_static_file(f"{root_b}/*.js", str(root_b), memo)

        self.assertEqual([pathlib.Path(f).name for f, _mtime in found_a], ["in_a.js"])
        self.assertEqual([pathlib.Path(f).name for f, _mtime in found_b], ["in_b.js"])

    def test_glob_static_file_drops_matches_linking_out_of_static(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp).resolve()
            static_dir = root / "static"
            (static_dir / "src").mkdir(parents=True)
            (static_dir / "src" / "inside.js").write_text("")
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.js").write_text("")
            (static_dir / "escape").symlink_to(outside)

            result = _glob_static_file(f"{static_dir}/*/*.js", str(static_dir))

        self.assertEqual(
            [path for path, _mtime in result], [f"{static_dir}/src/inside.js"]
        )


class TestParseBundleName(TransactionCase):
    def test_no_extension(self):
        IrAsset = self.env["ir.asset"]
        with self.assertRaises(ValueError) as cm:
            IrAsset._parse_bundle_name("nodotfilename", debug_assets=True)
        self.assertIn("no extension", str(cm.exception))
        self.assertIn("nodotfilename", str(cm.exception))

    def test_valid_debug_js(self):
        IrAsset = self.env["ir.asset"]
        name, rtl, asset_type, autoprefix = IrAsset._parse_bundle_name(
            "web.assets_frontend.js", debug_assets=True
        )
        self.assertEqual(name, "web.assets_frontend")
        self.assertEqual(asset_type, "js")
        self.assertFalse(rtl)
        self.assertFalse(autoprefix)

    def test_valid_min_css_rtl_autoprefixed(self):
        IrAsset = self.env["ir.asset"]
        name, rtl, asset_type, autoprefix = IrAsset._parse_bundle_name(
            "web.assets_frontend.rtl.autoprefixed.min.css", debug_assets=False
        )
        self.assertEqual(name, "web.assets_frontend")
        self.assertEqual(asset_type, "css")
        self.assertTrue(rtl)
        self.assertTrue(autoprefix)

    def test_unsupported_extension(self):
        IrAsset = self.env["ir.asset"]
        with self.assertRaises(ValueError) as cm:
            IrAsset._parse_bundle_name("web.assets.xml", debug_assets=True)
        self.assertIn("Only js and css", str(cm.exception))


class Manifests(dict):
    def __init__(self, default):
        self.defaults = default

    def __missing__(self, key):
        return self.defaults(key)


class AddonManifestPatched(TransactionCase):
    def setUp(self):
        super().setUp()

        self.installed_modules = {"base", "test_assetsbundle"}
        self.manifests = Manifests(odoo.modules.Manifest.for_addon)

        self.patch(self.env.registry, "_init_modules", self.installed_modules)
        self.patch(
            odoo.modules.Manifest,
            "for_addon",
            lambda module, **kw: self.manifests[module],
        )


class FileTouchable(AddonManifestPatched):
    def setUp(self):
        super().setUp()
        self.touches = {}

    def _touch(self, filepath, touch_time=None):
        self.touches[filepath] = touch_time or time.time()

        def patched_stat(path_self, *args, **kwargs):
            result = ORIGINAL_PATH_STAT(path_self, *args, **kwargs)
            touched = self.touches.get(str(path_self))
            if touched is not None:
                return os.stat_result(
                    (
                        result.st_mode,
                        result.st_ino,
                        result.st_dev,
                        result.st_nlink,
                        result.st_uid,
                        result.st_gid,
                        result.st_size,
                        result.st_atime,
                        touched,
                        result.st_ctime,
                    )
                )
            return result

        return patch.object(pathlib.Path, "stat", patched_stat)


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
                "the version must should because the bundle has changed.",
            )

            self.assertEqual(
                len(self._any_ira_for_bundle("js")),
                1,
                "there should be one minified attachment associated to this bundle",
            )

    def test_04_content_invalidation(self):
        bundle0 = self._get_asset(self.jsbundle_name)
        bundle0.js()
        files0 = bundle0.files
        version0 = bundle0.get_version("js")

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
        files1 = bundle1.files
        version1 = bundle1.get_version("js")

        self.assertNotEqual(
            files0,
            files1,
            "the list of files should be different because a file has been added to the bundle",
        )
        self.assertNotEqual(
            version0,
            version1,
            "the version should be different because a file has been added to the bundle",
        )

        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified attachment associated to this bundle",
        )

    def test_05_normal_mode(self):
        debug_bundle = self._get_asset(self.jsbundle_name)
        content = debug_bundle.get_links()
        debug_bundle.js()
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

    def test_compile_css_dedups_repeated_library_import(self):
        bundle = self._get_asset(self.cssbundle_name)
        source = (
            '@import "bootstrap/scss/functions";\n'
            ".a { color: red; }\n"
            '@import "bootstrap/scss/functions";'
        )
        out = bundle._css.compile_css(lambda s: s, source)
        self.assertEqual(
            bundle.css_errors,
            [],
            "a repeated library @import must not be flagged as an error",
        )
        self.assertEqual(
            out.count('@import "bootstrap/scss/functions"'),
            1,
            "the duplicate @import should be dropped, keeping the first",
        )

    def test_compile_css_blocks_whitespace_padded_local_import(self):
        bundle = self._get_asset(self.cssbundle_name)
        source = '@import  "./secret.css";'
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            out = bundle._css.compile_css(lambda s: s, source)
        self.assertTrue(
            bundle.css_errors,
            "a whitespace-padded local @import must be rejected",
        )
        self.assertNotIn("secret", out, "the local @import must be stripped")

    def test_stylesheet_url_rewrite_is_os_independent(self):
        from odoo.addons.base.models import assetsbundle
        from odoo.addons.base.models.assetsbundle import StylesheetAsset, WebAsset

        bundle = self._get_asset(self.cssbundle_name)
        sample = (
            '@import "theme.css";\n'
            ".a { background: url(images/logo.png); }\n"
            ".b { background: url(../img/sprite.png); }\n"
        )
        asset = StylesheetAsset(bundle, url="/web/static/src/css/foo.css")

        with (
            patch.object(WebAsset, "_fetch_content", lambda self: sample),
            patch.object(assetsbundle.assets, "Path", pathlib.PureWindowsPath),
        ):
            out = asset._fetch_content()

        self.assertNotIn("\\", out, "rewritten URLs must never contain backslashes")
        self.assertIn(
            '@import "/web/static/src/css/theme.css"',
            out,
            "relative @import must be prefixed with the asset's posix dir",
        )
        self.assertIn(
            "url(/web/static/src/css/images/logo.png)",
            out,
            "relative url() must be prefixed with the asset's posix dir",
        )
        self.assertIn(
            "url(/web/static/src/img/sprite.png)",
            out,
            "a ../ in url() must collapse against the posix dir",
        )

    def test_rtlcss_binary_resolution_shared_between_probe_and_run(self):
        from odoo.addons.base.models import assetsbundle

        self.addCleanup(assetsbundle.css_pipeline._rtlcss_bin.cache_clear)

        assetsbundle.css_pipeline._rtlcss_bin.cache_clear()
        with (
            patch.object(assetsbundle.css_pipeline.os, "name", "nt"),
            patch.object(
                assetsbundle.css_pipeline.misc,
                "find_in_path",
                return_value="C:/npm/rtlcss.cmd",
            ) as find,
        ):
            self.assertEqual(
                assetsbundle.css_pipeline._rtlcss_bin(), "C:/npm/rtlcss.cmd"
            )
            find.assert_called_once_with("rtlcss.cmd")

        assetsbundle.css_pipeline._rtlcss_bin.cache_clear()
        with (
            patch.object(assetsbundle.css_pipeline.os, "name", "posix"),
            patch.object(
                assetsbundle.css_pipeline.misc,
                "find_in_path",
                return_value="/usr/bin/rtlcss",
            ),
        ):
            self.assertEqual(assetsbundle.css_pipeline._rtlcss_bin(), "/usr/bin/rtlcss")

    def test_rtlcss_binary_falls_back_to_node_modules(self):
        from odoo.addons.base.models import assetsbundle

        self.addCleanup(assetsbundle.css_pipeline._rtlcss_bin.cache_clear)
        assetsbundle.css_pipeline._rtlcss_bin.cache_clear()

        node_bin = str(
            pathlib.Path(odoo.__path__[0]).parent / "node_modules" / ".bin" / "rtlcss"
        )
        with (
            patch.object(assetsbundle.css_pipeline.os, "name", "posix"),
            patch.object(
                assetsbundle.css_pipeline.misc,
                "find_in_path",
                side_effect=OSError(errno.ENOENT, "not found"),
            ),
            patch.object(
                assetsbundle.css_pipeline.shutil, "which", return_value=node_bin
            ) as which,
        ):
            self.assertEqual(assetsbundle.css_pipeline._rtlcss_bin(), node_bin)
        self.assertEqual(which.call_args.args, ("rtlcss",))
        self.assertTrue(which.call_args.kwargs["path"].endswith("node_modules/.bin"))

    def test_rtlcss_is_resolvable_in_this_checkout(self):
        from odoo.addons.base.models import assetsbundle

        binary = assetsbundle.css_pipeline._rtlcss_bin()
        self.assertTrue(
            pathlib.Path(binary).is_absolute() and pathlib.Path(binary).exists(),
            f"rtlcss did not resolve to an executable ({binary!r}); RTL "
            f"stylesheets would silently be served as LTR",
        )

    def test_js_header_line_count(self):
        bundle = self._get_asset(self.jsbundle_name)
        asset = JavascriptAsset(bundle, url="/web/static/src/_probe.js", inline="x")
        rendered = asset.with_header("SINGLE_LINE_BODY", minimal=False)
        self.assertEqual(rendered.count("\n"), JavascriptAsset._HEADER_LINE_COUNT)

    def test_bridge_resolver_memoizes_source_exports(self):
        from odoo.tools.assets.esm_graph import _BridgeExportResolver

        resolver = _BridgeExportResolver({}, {}, "test_bundle")
        resolver._cache["@x/y"] = "export const A = 1;\nexport default A;"
        first = resolver.source_exports("@x/y")
        second = resolver.source_exports("@x/y")
        self.assertEqual(first[0], {"A"})
        self.assertTrue(first[1])
        self.assertIs(first, second, "parsed exports must be memoized")

    def test_xml_template_elements_shapes(self):
        from odoo.addons.base.models.assetsbundle import XMLAsset

        bundle = self._get_asset(self.jsbundle_name)
        cases = {
            '<templates><t t-name="a"/><t t-name="b"/></templates>': ["a", "b"],
            '<odoo><t t-name="c"/></odoo>': ["c"],
            '<t t-name="solo"/>': ["solo"],
        }
        for src, expected in cases.items():
            asset = XMLAsset(bundle, inline=src, url="/web/static/src/_probe.xml")
            names = [el.get("t-name") for el in asset.template_elements]
            self.assertEqual(names, expected, f"for {src!r}")
            self.assertIs(asset.template_elements, asset.template_elements)

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

    def test_11_css_content_invalidation(self):
        bundle0 = self._get_asset(self.cssbundle_name)
        bundle0.css()
        files0 = bundle0.files
        version0 = bundle0.get_version("css")

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
        files1 = bundle1.files
        version1 = bundle1.get_version("css")

        self.assertNotEqual(files0, files1)
        self.assertNotEqual(version0, version1)

        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

    def test_12_css_debug(self):
        debug_bundle = self._get_asset(self.cssbundle_name, debug_assets=True)
        links = debug_bundle.get_links()
        self.assertEqual(links[0], "/web/assets/debug/test_assetsbundle.bundle2.css")

        debug_bundle.css()
        self.assertEqual(
            len(self._any_ira_for_bundle("css")),
            1,
            "there should be one css asset created in debug mode",
        )

    def test_14_duplicated_css_assets(self):
        bundle0 = self._get_asset(self.cssbundle_name)
        bundle0.css()
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

        ira0 = self._any_ira_for_bundle("min.css")
        ira1 = ira0.copy()
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 2)
        self.assertEqual(ira0.store_fname, ira1.store_fname)

        content = bundle0.get_links()
        self.assertIn("test_assetsbundle.bundle2.min.css", content[0])

    def test_15_rtl_css_generation(self):
        self.bundle = self._get_asset(self.cssbundle_name, rtl=True)

        self.assertEqual(len(self._any_ira_for_bundle("min.css", rtl=True)), 0)
        self.assertEqual(len(self.bundle.get_attachments("min.css")), 0)

        self.bundle.css()

        self.assertEqual(len(self.bundle.css_errors), 0)

        self.assertEqual(len(self._any_ira_for_bundle("min.css", rtl=True)), 1)
        self.assertEqual(len(self.bundle.get_attachments("min.css")), 1)

    @unittest.skipUnless(_check_rtlcss(), "rtlcss binary not available")
    def test_15_rtl_invalid_css_generation(self):
        self.bundle = self._get_asset("test_assetsbundle.broken_css", rtl=True)
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle.css()
        self.assertEqual(len(self.bundle.css_errors), 1)
        self.assertIn("rtlcss: error processing payload", self.bundle.css_errors[0])

    def test_16_ltr_and_rtl_css_access(self):
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
        self._any_ira_for_bundle("min.css", rtl=True)

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

    def test_17_css_bundle_date_invalidation(self):
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

    def test_18_css_bundle_content_invalidation(self):
        ltr_bundle0 = self._get_asset(self.cssbundle_name)
        ltr_bundle0.css()
        ltr_files0 = ltr_bundle0.files
        ltr_version0 = ltr_bundle0.get_version("css")

        rtl_bundle0 = self._get_asset(self.cssbundle_name, rtl=True)
        rtl_bundle0.css()
        rtl_files0 = rtl_bundle0.files
        rtl_version0 = rtl_bundle0.get_version("css")

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
        ltr_files1 = ltr_bundle1.files
        ltr_version1 = ltr_bundle1.get_version("css")
        ltr_ira1 = self._any_ira_for_bundle("min.css")

        self.assertNotEqual(ltr_files0, ltr_files1)
        self.assertNotEqual(ltr_version0, ltr_version1)

        rtl_bundle1 = self._get_asset(self.cssbundle_name, rtl=True)
        rtl_bundle1.css()
        rtl_files1 = rtl_bundle1.files
        rtl_version1 = rtl_bundle1.get_version("css")
        rtl_ira1 = self._any_ira_for_bundle("min.css", rtl=True)

        self.assertNotEqual(rtl_files0, rtl_files1)
        self.assertNotEqual(rtl_version0, rtl_version1)

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

    def test_19_css_in_debug_assets(self):
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

    def test_20_external_lib_assets(self):
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

    def test_21_external_lib_assets_debug_mode(self):
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


class TestXMLAssetsBundle(FileTouchable):
    def _get_asset(self, bundle, rtl=False, debug_assets=False):
        files, _ = self.env["ir.qweb"]._get_asset_content(bundle)
        return AssetsBundle(
            bundle, files, env=self.env, debug_assets=debug_assets, rtl=rtl
        )

    def test_01_broken_xml(self):
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.broken_xml")

            with self.assertRaisesRegex(
                XMLAssetError,
                "Invalid XML template: Opening and ending tag mismatch: SomeComponent line 4 and t, line 5, column 7' in file '/test_assetsbundle/static/invalid_src/xml/invalid_xml.xml",
            ):
                self.bundle.xml()

    def test_02_multiple_broken_xml(self):
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.multiple_broken_xml")

            with self.assertRaisesRegex(
                XMLAssetError,
                "Invalid XML template: Opening and ending tag mismatch: SomeComponent line 4 and t, line 5, column 7' in file '/test_assetsbundle/static/invalid_src/xml/invalid_xml.xml",
            ):
                self.bundle.xml()

    def test_04_template_wo_name(self):
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.wo_name")

            with self.assertRaisesRegex(
                XMLAssetError,
                "'Template name is missing.' in file '/test_assetsbundle/static/invalid_src/xml/template_wo_name.xml'",
            ):
                self.bundle.xml()

    def test_05_file_not_found(self):
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.file_not_found")

            with self.assertRaisesRegex(
                XMLAssetError,
                "Could not find test_assetsbundle/static/invalid_src/xml/file_not_found.xml",
            ):
                self.bundle.xml()


@tagged("-at_install", "post_install")
class TestAssetsBundleInBrowser(HttpCase):
    def test_01_js_interpretation(self):
        self.browser_js(
            "/test_assetsbundle/js",
            "a + b + c === 6 ? console.log('test successful') : console.log('error')",
            login="admin",
        )

    @skip("Feature Regression")
    def test_02_js_interpretation_inline(self):
        view_arch = """
        <data>
            <xpath expr="." position="inside">
                <script type="text/javascript">
                    var d = 4;
                </script>
            </xpath>
        </data>
        """
        self.env["ir.ui.view"].create(
            {
                "name": "test bundle inheritance inline js",
                "type": "qweb",
                "arch": view_arch,
                "inherit_id": self.browse_ref("test_assetsbundle.bundle1").id,
            }
        )
        self.env.flush_all()

        self.browser_js(
            "/test_assetsbundle/js",
            "a + b + c + d === 10 ? console.log('test successful') : console.log('error')",
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
            "_get_installed_addons_list",
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

            self.env["ir.attachment"].flush_model(["checksum", "write_date"])
            self.cr.execute(
                "update ir_attachment set write_date=clock_timestamp() + interval '10 seconds' where id = (select max(id) from ir_attachment)"
            )
            self.env["ir.attachment"].invalidate_model(["write_date"])

            self._bundle(self._get_asset(), False, False)


@tagged("assets_manifest")
class TestAssetsManifest(AddonManifestPatched):
    def make_asset_view(self, asset_key, t_call_assets_attrs=None):
        default_attrs = {
            "t-js": "true",
            "t-css": "false",
        }
        if t_call_assets_attrs:
            default_attrs.update(t_call_assets_attrs)

        attrs = " ".join(['%s="%s"' % (k, v) for k, v in default_attrs.items()])
        arch = """
            <div>
                <t t-call-assets="%(asset_key)s" %(attrs)s />
            </div>
        """ % {"asset_key": asset_key, "attrs": attrs}

        return self.env["ir.ui.view"].create(
            {
                "name": "test asset",
                "arch": arch,
                "type": "qweb",
            }
        )

    def assertStringEqual(self, reference, tested):
        tested = textwrap.dedent(tested).strip()
        reference = reference.strip()
        self.assertEqual(tested, reference)

    def test_01_globmanifest(self):
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest1")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;
            """,
        )

    def test_02_globmanifest_no_duplicates(self):
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest2")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;
            """,
        )

    def test_03_globmanifest_file_before(self):
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest3")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;;

            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;
            """,
        )

    def test_04_globmanifest_with_irasset(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.manifest4",
                "path": "test_assetsbundle/static/src/js/test_jsfile1.js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;;

            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;
            """,
        )

    def test_05_only_irasset(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.irasset1",
                "path": "test_assetsbundle/static/src/js/test_jsfile1.js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.irasset1")
        attach = bundle.js()

        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;
            """,
        )

    def test_06_1_replace(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.manifest1",
                "directive": "replace",
                "target": "test_assetsbundle/static/src/js/test_jsfile1.js",
                "path": "http://external.link/external.js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest1")
        scripts = [link for link in bundle.get_links() if link.endswith("js")]
        self.assertEqual(len(scripts), 2)
        self.assertEqual(scripts[0], "http://external.link/external.js")
        attach = bundle.js()
        self.assertEqual(scripts[1], attach.url)
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;
            """,
        )

    def test_06_2_replace(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.manifest4",
                "directive": "replace",
                "path": "test_assetsbundle/static/src/js/test_jsfile1.js",
                "target": "test_assetsbundle/static/src/js/test_jsfile3.js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        attach = self.env["ir.attachment"].search(
            [("name", "ilike", "test_assetsbundle.manifest4")],
            order="create_date DESC",
            limit=1,
        )
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;
            """,
        )

    def test_06_3_replace_globs(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "prepend",
                "bundle": "test_assetsbundle.manifest4",
                "path": "test_assetsbundle/static/src/js/test_jsfile4.js",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.manifest4",
                "directive": "replace",
                "path": "test_assetsbundle/static/src/js/test_jsfile[12].js",
                "target": "test_assetsbundle/static/src/js/test_jsfile[45].js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_07_remove(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.manifest5",
                "directive": "remove",
                "path": "test_assetsbundle/static/src/js/test_jsfile2.js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest5")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;
            """,
        )

    def test_08_remove_inexistent_file(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.remove_error",
                "path": "/test_assetsbundle/static/src/js/test_jsfile1.js",
            }
        )

        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.remove_error",
                "directive": "remove",
                "path": "test_assetsbundle/static/src/js/test_doesntexist.js",
            }
        )
        with self.assertRaises(Exception) as cm:
            bundle = self.env["ir.qweb"]._get_asset_bundle(
                "test_assetsbundle.remove_error"
            )
            bundle.js()
        self.assertTrue(
            "['test_assetsbundle/static/src/js/test_doesntexist.js'] not found"
            in str(cm.exception)
        )

    def test_09_remove_wholeglob(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.manifest2",
                "directive": "remove",
                "path": "test_assetsbundle/static/src/*/**",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest2")
        self.assertFalse(bundle.javascripts)
        self.assertFalse(bundle.get_links())

    def test_10_prepend(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "prepend",
                "bundle": "test_assetsbundle.manifest4",
                "path": "test_assetsbundle/static/src/js/test_jsfile1.js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_11_include(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "include",
                "bundle": "test_assetsbundle.irasset_include1",
                "path": "test_assetsbundle.manifest6",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "test_assetsbundle.irasset_include1"
        )
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_12_include2(self):
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest6")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_13_include_circular(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "include",
                "bundle": "test_assetsbundle.irasset_include1",
                "path": "test_assetsbundle.irasset_include2",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "include",
                "bundle": "test_assetsbundle.irasset_include2",
                "path": "test_assetsbundle.irasset_include1",
            }
        )

        with self.assertRaises(Exception) as cm:
            bundle = self.env["ir.qweb"]._get_asset_bundle(
                "test_assetsbundle.irasset_include1"
            )
            bundle.js()
        error = str(cm.exception)
        self.assertTrue(error)
        self.assertFalse(isinstance(error, RecursionError))
        self.assertIn("Circular assets bundle declaration:", error)

    def test_13_2_include_recursive_sibling(self):
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "include",
                "bundle": "test_assetsbundle.irasset_include1",
                "path": "test_assetsbundle.irasset_include2",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "include",
                "bundle": "test_assetsbundle.irasset_include2",
                "path": "test_assetsbundle.irasset_include3",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "include",
                "bundle": "test_assetsbundle.irasset_include2",
                "path": "test_assetsbundle.irasset_include4",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "directive": "include",
                "bundle": "test_assetsbundle.irasset_include4",
                "path": "test_assetsbundle.irasset_include3",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.irasset_include3",
                "path": "test_assetsbundle/static/src/js/test_jsfile1.js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "test_assetsbundle.irasset_include1"
        )
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;
            """,
        )

    def test_14_other_module(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_other.mockmanifest1": [
                    ("include", "test_assetsbundle.manifest4"),
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_other.mockmanifest1")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_15_other_module_append(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_assetsbundle.manifest4": [
                    "test_assetsbundle/static/src/js/test_jsfile1.js",
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;;

            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;
            """,
        )

    def test_16_other_module_prepend(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_assetsbundle.manifest4": [
                    (
                        "prepend",
                        "test_assetsbundle/static/src/js/test_jsfile1.js",
                    ),
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_17_other_module_replace(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_assetsbundle.manifest4": [
                    (
                        "replace",
                        "test_assetsbundle/static/src/js/test_jsfile3.js",
                        "test_assetsbundle/static/src/js/test_jsfile1.js",
                    ),
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;
            """,
        )

    def test_17_other_module_remove(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_assetsbundle.manifest4": [
                    (
                        "remove",
                        "test_assetsbundle/static/src/js/test_jsfile3.js",
                    ),
                    (
                        "append",
                        "test_assetsbundle/static/src/js/test_jsfile1.js",
                    ),
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;
            """,
        )

    def test_18_other_module_external(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_assetsbundle.manifest4": [
                    "http://external.link/external.js",
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        scripts = [link for link in bundle.get_links() if link.endswith("js")]
        self.assertEqual(len(scripts), 2)
        self.assertEqual(scripts[0], "http://external.link/external.js")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_19_css_specific_attrs_in_tcallassets(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irasset2",
                "path": "http://external.css/externalstyle.css",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "2",
                "bundle": "test_assetsbundle.irasset2",
                "path": "test_assetsbundle/static/src/css/test_cssfile1.css",
            }
        )
        view = self.make_asset_view(
            "test_assetsbundle.irasset2",
            {
                "t-js": "false",
                "t-css": "true",
                "media": "print",
            },
        )

        rendered = self.env["ir.qweb"]._render(view.id)
        html_tree = lxml.etree.fromstring(rendered)
        stylesheets = html_tree.findall("link")
        self.assertEqual(len(stylesheets), 2)
        self.assertEqual(
            stylesheets[0].get("href"), "http://external.css/externalstyle.css"
        )
        self.assertEqual(stylesheets[0].get("media"), "print")

    def test_20_css_base(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irasset2",
                "path": "http://external.css/externalstyle.css",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "2",
                "bundle": "test_assetsbundle.irasset2",
                "path": "test_assetsbundle/static/src/scss/test_file1.scss",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.irasset2")
        stylesheets = [link for link in bundle.get_links() if link.endswith("css")]
        self.assertEqual(len(stylesheets), 2)
        attach = bundle.css()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/scss/test_file1.scss */
            .rule1{color:#000}
            """,
        )

    def test_20_css_compatibility_prefix(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irasset2",
                "path": "test_assetsbundle/static/src/scss/test_prefix.scss",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "test_assetsbundle.irasset2", js=False, autoprefix=True
        )
        content = bundle.css().raw.decode()
        self.assertRegex(
            content,
            r"\.appearance-none\{-webkit-appearance:none;-moz-appearance:none;appearance:none\}",
        )
        self.assertRegex(
            content,
            r"\.appearance-auto\{-webkit-appearance:auto;-moz-appearance:auto;appearance:auto\}",
        )
        self.assertRegex(
            content, r"\.appearance-none-prefixed\{-webkit-appearance:none\}"
        )
        self.assertRegex(
            content,
            r"\.appearance-none-important\{-webkit-appearance:none !important;"
            r"-moz-appearance:none !important;appearance:none !important\}",
        )
        self.assertRegex(
            content,
            r"\.appearance-menulist-button\{-webkit-appearance:menulist-button;"
            r"-moz-appearance:menulist-button;appearance:menulist-button\}",
        )

        self.assertRegex(content, r"\.display-flex\{display:flex\}")
        self.assertRegex(content, r"\.display-inline-flex\{display:inline-flex\}")
        self.assertRegex(content, r"\.display-inline\{display:inline\}")
        self.assertRegex(content, r"\.display-var-flex\{--dummy-display: flex\}")
        self.assertRegex(
            content,
            r"\.display-var-inline-flex\{--dummy-display: inline-flex\}",
        )
        self.assertRegex(content, r"\.display-var-inline\{--dummy-display: inline\}")

        self.assertRegex(content, r"\.flex-flow-row-nowrap\{flex-flow:row nowrap\}")
        self.assertRegex(content, r"\.flex-flow-column-wrap\{flex-flow:column wrap\}")
        self.assertRegex(
            content,
            r"\.flex-flow-column-reverse-wrap-reverse\{flex-flow:column-reverse wrap-reverse\}",
        )
        self.assertRegex(content, r"\.flex-flow-row\{flex-flow:row\}")

        self.assertRegex(content, r"\.flex-direction-column\{flex-direction:column\}")
        self.assertRegex(
            content,
            r"\.flex-direction-column-reverse\{flex-direction:column-reverse\}",
        )
        self.assertRegex(content, r"\.flex-direction-row\{flex-direction:row\}")

        self.assertRegex(content, r"\.flex-wrap-wrap\{flex-wrap:wrap\}")
        self.assertRegex(content, r"\.flex-wrap-nowrap\{flex-wrap:nowrap\}")
        self.assertRegex(content, r"\.flex-wrap-wrap-reverse\{flex-wrap:wrap-reverse\}")

        self.assertRegex(content, r"\.flex-0-0-auto\{flex:0 0 auto\}")
        self.assertRegex(content, r"\.flex-0-1-auto\{flex:0 1 auto\}")
        self.assertRegex(content, r"\.flex-1-1-100\{flex:1 1 100\}")
        self.assertRegex(content, r"\.flex-1-1-100percent\{flex:1 1 100%\}")
        self.assertRegex(content, r"\.flex-auto\{flex:auto\}")
        self.assertRegex(content, r"\.flex-1-30px\{flex:1 30px\}")

    def test_20bis_css_loud_comment_not_mistaken_for_split_marker(self):
        fixture = "test_assetsbundle/static/src/scss/test_split_marker.scss"
        # The loud comment is what this test is about, so a fixture that lost it
        # passes the interesting assertion vacuously. It has been lost once
        # already -- a repo-wide comment strip took it for prose -- and the bare
        # assertIn below then failed without saying which side was wrong.
        self.assertIn(
            "/*! a1b2c3d */",
            pathlib.Path(file_path(fixture)).read_text(encoding="utf-8"),
            f"{fixture} lost its loud comment; it is the payload, not a comment",
        )
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irasset_split",
                "path": fixture,
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "test_assetsbundle.irasset_split", js=False
        )
        content = bundle.css().raw.decode()
        self.assertRegex(content, r"\.split-marker-regression\{color:red\}")
        self.assertIn("/*! a1b2c3d */", content)

    def test_21_js_before_css(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_other.bundle4": [
                    (
                        "before",
                        "test_assetsbundle/static/src/css/test_cssfile1.css",
                        "/test_assetsbundle/static/src/js/test_jsfile4.js",
                    )
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.bundle4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_22_js_before_js(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_assetsbundle.bundle4": [
                    (
                        "before",
                        "/test_assetsbundle/static/src/js/test_jsfile3.js",
                        "/test_assetsbundle/static/src/js/test_jsfile4.js",
                    )
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.bundle4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_23_js_after_css(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_other.bundle4": [
                    (
                        "after",
                        "test_assetsbundle/static/src/css/test_cssfile1.css",
                        "/test_assetsbundle/static/src/js/test_jsfile4.js",
                    )
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.bundle4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_24_js_after_js(self):
        self.installed_modules.add("test_other")
        self.manifests["test_other"] = {
            "name": "test_other",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
            "assets": {
                "test_assetsbundle.bundle4": [
                    (
                        "after",
                        "/test_assetsbundle/static/src/js/test_jsfile2.js",
                        "/test_assetsbundle/static/src/js/test_jsfile4.js",
                    )
                ]
            },
        }
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.bundle4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_25_js_before_js_in_irasset(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.bundle4",
                "path": "/test_assetsbundle/static/src/js/test_jsfile4.js",
                "target": "/test_assetsbundle/static/src/js/test_jsfile3.js",
                "directive": "before",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.bundle4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_26_js_after_js_in_irasset(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.bundle4",
                "path": "/test_assetsbundle/static/src/js/test_jsfile4.js",
                "target": "/test_assetsbundle/static/src/js/test_jsfile2.js",
                "directive": "after",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.bundle4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    def test_27_mixing_after_before_js_css_in_irasset(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.bundle4",
                "path": "/test_assetsbundle/static/src/js/test_jsfile4.js",
                "target": "/test_assetsbundle/static/src/css/test_cssfile1.css",
                "directive": "after",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.bundle4",
                "path": "/test_assetsbundle/static/src/css/test_cssfile3.css",
                "target": "/test_assetsbundle/static/src/js/test_jsfile2.js",
                "directive": "before",
            }
        )
        self.make_asset_view(
            "test_assetsbundle.bundle4",
            {
                "t-js": "true",
                "t-css": "true",
            },
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.bundle4")
        attach_css = bundle.css()
        attach_js = bundle.js()

        js_content = attach_js.raw.decode()
        self.assertStringEqual(
            js_content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

        css_content = attach_css.raw.decode()
        self.assertStringEqual(
            css_content,
            """
            /* /test_assetsbundle/static/src/css/test_cssfile3.css */
            .rule4{color: green;}

            /* /test_assetsbundle/static/src/css/test_cssfile1.css */
            .rule1{color: black;}.rule2{color: yellow;}.rule3{color: red;}

            /* /test_assetsbundle/static/src/css/test_cssfile2.css */
            .rule4{color: blue;}
            """,
        )

    def test_28_js_after_js_in_irasset_wrong_path(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.wrong_path",
                "path": "/test_assetsbundle/static/src/js/test_jsfile4.js",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.wrong_path",
                "path": "/test_assetsbundle/static/src/js/test_jsfile1.js",
                "target": "/test_assetsbundle/static/src/js/doesnt_exist.js",
                "directive": "after",
            }
        )
        with self.assertRaises(Exception) as cm:
            bundle = self.env["ir.qweb"]._get_asset_bundle(
                "test_assetsbundle.wrong_path"
            )
            bundle.js()
        self.assertTrue(
            "test_assetsbundle/static/src/js/doesnt_exist.js not found"
            in str(cm.exception)
        )

    def test_29_js_after_js_in_irasset_glob(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.manifest4",
                "path": "/test_assetsbundle/static/src/*/**",
                "target": "/test_assetsbundle/static/src/js/test_jsfile3.js",
                "directive": "after",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;;

            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;
            """,
        )

    def test_30_js_before_js_in_irasset_glob(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.manifest4",
                "path": "/test_assetsbundle/static/src/js/test_jsfile[124].js",
                "target": "/test_assetsbundle/static/src/js/test_jsfile3.js",
                "directive": "before",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.manifest4")
        attach = bundle.js()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* /test_assetsbundle/static/src/js/test_jsfile1.js */
            var a=1;;

            /* /test_assetsbundle/static/src/js/test_jsfile2.js */
            var b=2;;

            /* /test_assetsbundle/static/src/js/test_jsfile4.js */
            var d=4;;

            /* /test_assetsbundle/static/src/js/test_jsfile3.js */
            var c=3;
            """,
        )

    @mute_logger(
        "odoo.addons.base.models.ir_asset",
        "odoo.addons.base.models.ir_asset_paths",
    )
    def test_31(self):
        path_to_dummy = "../../tests/dummy.js"
        me = pathlib.Path(__file__).parent.absolute()
        file_path = me.joinpath("..", path_to_dummy)
        self.assertTrue(file_path.is_file())

        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irassetsec",
                "path": "/test_assetsbundle/%s" % path_to_dummy,
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.irassetsec")
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            attach = bundle.js()
            self.assertIn(
                b"Could not find /test_assetsbundle/../../tests/dummy.js",
                attach.exists().raw,
            )

    @mute_logger(
        "odoo.addons.base.models.ir_asset",
        "odoo.addons.base.models.ir_asset_paths",
    )
    def test_32_a_relative_path_in_addon(self):
        path_to_dummy = "../../tests/dummy.xml"
        me = pathlib.Path(__file__).parent.absolute()
        file_path = me.joinpath("..", path_to_dummy)
        self.assertTrue(file_path.is_file())

        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irassetsec",
                "path": "/test_assetsbundle/%s" % path_to_dummy,
            }
        )

        files = self.env["ir.asset"]._get_asset_paths(
            "test_assetsbundle.irassetsec", {}
        )
        self.assertEqual(
            files,
            (
                (
                    "/test_assetsbundle/../../tests/dummy.xml",
                    None,
                    "test_assetsbundle.irassetsec",
                    None,
                ),
            ),
        )

    @mute_logger(
        "odoo.addons.base.models.ir_asset",
        "odoo.addons.base.models.ir_asset_paths",
    )
    def test_32_b_relative_path_outsied_addon(self):
        path_to_dummy = "../../tests/dummy.xml"
        me = pathlib.Path(__file__).parent.absolute()
        file_path = me.joinpath("..", path_to_dummy)
        self.assertTrue(file_path.is_file())

        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irassetsec",
                "path": "%s" % path_to_dummy,
            }
        )
        files = self.env["ir.asset"]._get_asset_paths(
            "test_assetsbundle.irassetsec", {}
        )
        self.assertEqual(
            files,
            (
                (
                    "../../tests/dummy.xml",
                    None,
                    "test_assetsbundle.irassetsec",
                    None,
                ),
            ),
        )

    def test_33(self):
        self.manifests["notinstalled_module"] = {
            "name": "notinstalled_module",
            "depends": ["test_assetsbundle"],
            "addons_path": pathlib.Path(__file__).resolve().parent,
        }
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irassetsec",
                "path": "/notinstalled_module/somejsfile.js",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.irassetsec")
        content = bundle.js()
        self.assertNotIn("notinstalled_module", content)

    def test_33bis_notinstalled_not_in_manifests(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irassetsec",
                "path": "/notinstalled_module/somejsfile.js",
            }
        )
        self.make_asset_view("test_assetsbundle.irassetsec")
        attach = self.env["ir.attachment"].search(
            [("name", "ilike", "test_assetsbundle.irassetsec")],
            order="create_date DESC",
            limit=1,
        )
        self.assertFalse(attach.exists())

    @mute_logger(
        "odoo.addons.base.models.ir_asset",
        "odoo.addons.base.models.ir_asset_paths",
    )
    def test_34(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irassetsec",
                "path": "/test_assetsbundle/__manifest__.py",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle("test_assetsbundle.irassetsec")
        links = bundle.get_links()
        self.assertFalse(links)

    @mute_logger(
        "odoo.addons.base.models.ir_asset",
        "odoo.addons.base.models.ir_asset_paths",
    )
    def test_35(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irassetsec",
                "path": "/test_assetsbundle/data/ir_asset.xml",
            }
        )
        files = self.env["ir.asset"]._get_asset_paths(
            "test_assetsbundle.irassetsec", {}
        )
        self.assertEqual(
            files,
            (
                (
                    "/test_assetsbundle/data/ir_asset.xml",
                    None,
                    "test_assetsbundle.irassetsec",
                    None,
                ),
            ),
        )

    def test_36(self):
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irassetsec",
                "path": "/test_assetsbundle/static/accessible.xml",
            }
        )
        files = self.env["ir.asset"]._get_asset_paths(
            "test_assetsbundle.irassetsec", {}
        )
        modified = files[0][3]

        base_path = __file__.replace("/tests/test_assetsbundle.py", "")

        self.assertEqual(
            files,
            (
                (
                    "/test_assetsbundle/static/accessible.xml",
                    f"{base_path}/static/accessible.xml",
                    "test_assetsbundle.irassetsec",
                    modified,
                ),
            ),
        )

    def test_37_path_can_be_an_attachment(self):
        scss_code = base64.b64encode(b"""
            .my_div {
                &.subdiv {
                    color: blue;
                }
            }
        """)
        self.env["ir.attachment"].create(
            {
                "name": "my custom scss",
                "mimetype": "text/scss",
                "type": "binary",
                "url": "test_assetsbundle/my_style_attach.scss",
                "datas": scss_code,
            }
        )

        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irasset_custom_attach",
                "path": "test_assetsbundle/my_style_attach.scss",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "test_assetsbundle.irasset_custom_attach"
        )
        attach = bundle.css()
        content = attach.raw.decode()
        self.assertStringEqual(
            content,
            """
            /* test_assetsbundle/my_style_attach.scss */
            .my_div.subdiv{color:blue}
            """,
        )


@tagged("-at_install", "post_install")
class AssetsNodeOrmCacheUsage(TransactionCase):
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
        self.env.registry.clear_cache("assets")

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
        self.env.registry.clear_cache("assets")

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
        self.env.registry.clear_cache("assets")
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
        if self.env["ir.module.module"].search(
            [("name", "=", "website"), ("state", "=", "uninstalled")]
        ):
            return
        self.env.registry.clear_cache("assets")

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
        self.env.registry.clear_cache("assets")

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
                "path": "test_assetsbundle/static/src/css/test_error.scss",
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
                "path": "test_assetsbundle/static/src/css/test_error.scss",
            }
        )
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.start_tour("/?debug=1", "css_error_tour_frontend")
