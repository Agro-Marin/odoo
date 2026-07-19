import base64
import os
import pathlib
import shutil
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
)
from odoo.addons.base.models.ir_asset import AssetPaths, _glob_static_file
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

        # append with a duplicate of 'c'
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

        # insert with a duplicate of 'c' after 'c'
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

        # insert with a duplicate of 'd' before 'd'
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

        # remove
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
        """REPLACE with empty source should remove target without replacement."""
        asset_paths = AssetPaths()
        asset_paths.append(
            [
                ("/web/a.js", "/full/a.js", 1),
                ("/web/b.js", "/full/b.js", 1),
                ("/web/c.js", "/full/c.js", 1),
            ],
            "bundle1",
        )
        # Simulate REPLACE where source resolved to nothing:
        # insert([], ...) is a no-op, then remove deletes the target.
        target_index = asset_paths.index("/web/b.js", "bundle1")
        asset_paths.insert([], "bundle1", target_index)
        asset_paths.remove([("/web/b.js", "/full/b.js", 1)], "bundle1")

        self.assertEqual(len(asset_paths.list), 2)
        self.assertEqual(asset_paths.list[0][0], "/web/a.js")
        self.assertEqual(asset_paths.list[1][0], "/web/c.js")
        self.assertNotIn("/web/b.js", asset_paths.memo)

    def test_glob_static_file_race_condition(self):
        """Files deleted between glob() and stat() should be skipped."""
        deleted_file = "/tmp/_test_asset_race_condition.js"
        # Patch glob to return a file that doesn't exist on disk
        with patch(
            "odoo.addons.base.models.ir_asset.glob",
            return_value=[deleted_file],
        ):
            result = _glob_static_file("/tmp/*.js")
        self.assertEqual(result, [], "Deleted files should be silently skipped")

    def test_glob_static_file_filters_extensions(self):
        """Only ASSET_EXTENSIONS files should be returned."""
        with patch(
            "odoo.addons.base.models.ir_asset.glob",
            return_value=["/tmp/file.js", "/tmp/file.py", "/tmp/file.css"],
        ), patch(
            "odoo.addons.base.models.ir_asset.Path"
        ) as MockPath:
            MockPath.return_value.stat.return_value.st_mtime = 100.0
            result = _glob_static_file("/tmp/*")
        # .py should be filtered out, .js and .css kept
        paths = [r[0] for r in result]
        self.assertIn("/tmp/file.js", paths)
        self.assertIn("/tmp/file.css", paths)
        self.assertNotIn("/tmp/file.py", paths)


class TestParseBundleName(TransactionCase):
    """Tests for IrAsset._parse_bundle_name error handling."""

    def test_no_extension(self):
        """Dot-less filename should raise ValueError with clear message."""
        IrAsset = self.env["ir.asset"]
        with self.assertRaises(ValueError) as cm:
            IrAsset._parse_bundle_name("nodotfilename", debug_assets=True)
        self.assertIn("no extension", str(cm.exception))
        self.assertIn("nodotfilename", str(cm.exception))

    def test_valid_debug_js(self):
        """Valid JS bundle in debug mode should parse correctly."""
        IrAsset = self.env["ir.asset"]
        name, rtl, asset_type, autoprefix = IrAsset._parse_bundle_name(
            "web.assets_frontend.js", debug_assets=True
        )
        self.assertEqual(name, "web.assets_frontend")
        self.assertEqual(asset_type, "js")
        self.assertFalse(rtl)
        self.assertFalse(autoprefix)

    def test_valid_min_css_rtl_autoprefixed(self):
        """Full CSS bundle with rtl+autoprefix in non-debug should parse."""
        IrAsset = self.env["ir.asset"]
        name, rtl, asset_type, autoprefix = IrAsset._parse_bundle_name(
            "web.assets_frontend.rtl.autoprefixed.min.css", debug_assets=False
        )
        self.assertEqual(name, "web.assets_frontend")
        self.assertEqual(asset_type, "css")
        self.assertTrue(rtl)
        self.assertTrue(autoprefix)

    def test_unsupported_extension(self):
        """Non-js/css extension should raise ValueError."""
        IrAsset = self.env["ir.asset"]
        with self.assertRaises(ValueError) as cm:
            IrAsset._parse_bundle_name("web.assets.xml", debug_assets=True)
        self.assertIn("Only js and css", str(cm.exception))


class TestSilentNoopDirectives(TransactionCase):
    """Tests asserting that silent-noop directives (REMOVE / AFTER / BEFORE /
    REPLACE pointing at a path that resolves to nothing) emit a WARNING with
    enough context (bundle name + directive + path) for an operator to fix
    the manifest by hand.

    Background: CONVENTIONS.md §3 (web) documents that the ``remove`` and
    ``after`` directives in ``__manifest__.py`` are load-bearing for the
    asset graph.  Before this guardrail, a ``("remove", "moved_file.js")``
    silently became a no-op when the file was renamed — the manifest tuple
    was dead weight that nobody could spot without ``git blame`` archaeology.
    The new warnings turn each silent no-op into a grep-able log line.
    """

    def _make_ir_asset(self):
        return self.env["ir.asset"]

    @property
    def _ir_asset_cls(self):
        """Patch target for class-level method mocking — model recordsets
        are immutable, so we must patch the underlying class."""
        return type(self.env["ir.asset"])

    def test_remove_unresolved_path_warns(self):
        """REMOVE pointing at a path that resolves to nothing emits a WARNING."""
        IrAsset = self._make_ir_asset()
        asset_paths = AssetPaths()
        # Patch _get_paths to simulate a stale path (file moved/deleted).
        with patch.object(self._ir_asset_cls, "_get_paths", return_value=[]), \
             self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING") as cm:
            IrAsset._process_path(
                bundle="some.bundle",
                directive="remove",
                target=None,
                path_def="/some_addon/static/src/moved_or_deleted.js",
                asset_paths=asset_paths,
                seen=[],
                addons=[],
                installed=set(),
                bundle_start_index=0,
            )
        # The asset_paths list is unchanged because the path resolved to nothing.
        self.assertEqual(asset_paths.list, [])
        # The warning carries enough context for the operator to find the manifest.
        joined = " ".join(cm.output)
        self.assertIn("REMOVE", joined)
        self.assertIn("some.bundle", joined)
        self.assertIn("moved_or_deleted.js", joined)

    def test_after_missing_target_warns(self):
        """AFTER with a target that resolves to nothing emits a WARNING."""
        IrAsset = self._make_ir_asset()
        asset_paths = AssetPaths()

        # First _get_paths call (for path_def) returns the source file;
        # second (for target) returns nothing — simulating a renamed anchor.
        side_effects = [
            [("/web/source.scss", "/full/source.scss", 1)],  # source resolves
            [],  # target does NOT
        ]
        with patch.object(self._ir_asset_cls, "_get_paths", side_effect=side_effects), \
             self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING") as cm:
            IrAsset._process_path(
                bundle="some.bundle",
                directive="after",
                target="/web/missing_anchor.scss",
                path_def="/web/source.scss",
                asset_paths=asset_paths,
                seen=[],
                addons=[],
                installed=set(),
                bundle_start_index=0,
            )
        # source.scss was NOT inserted because the target index could not be
        # resolved — the directive is a complete no-op.
        self.assertEqual(asset_paths.list, [])
        joined = " ".join(cm.output)
        self.assertIn("after", joined)
        self.assertIn("some.bundle", joined)
        self.assertIn("missing_anchor.scss", joined)

    def test_before_missing_target_warns(self):
        """BEFORE with a missing target emits a WARNING (same path as AFTER)."""
        IrAsset = self._make_ir_asset()
        asset_paths = AssetPaths()
        with patch.object(
            self._ir_asset_cls,
            "_get_paths",
            side_effect=[[("/web/x.js", "/full/x.js", 1)], []],
        ), self.assertLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ) as cm:
            IrAsset._process_path(
                bundle="b.b",
                directive="before",
                target="/web/missing.js",
                path_def="/web/x.js",
                asset_paths=asset_paths,
                seen=[],
                addons=[],
                installed=set(),
                bundle_start_index=0,
            )
        self.assertEqual(asset_paths.list, [])
        joined = " ".join(cm.output)
        self.assertIn("before", joined)
        self.assertIn("missing.js", joined)

    def test_after_no_target_warns(self):
        """AFTER with target=None emits a WARNING."""
        IrAsset = self._make_ir_asset()
        asset_paths = AssetPaths()
        with patch.object(
            self._ir_asset_cls,
            "_get_paths",
            return_value=[("/web/x.js", "/full/x.js", 1)],
        ), self.assertLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ) as cm:
            IrAsset._process_path(
                bundle="x.y",
                directive="after",
                target=None,
                path_def="/web/x.js",
                asset_paths=asset_paths,
                seen=[],
                addons=[],
                installed=set(),
                bundle_start_index=0,
            )
        self.assertEqual(asset_paths.list, [])
        joined = " ".join(cm.output)
        self.assertIn("no target", joined)
        self.assertIn("x.y", joined)

    def test_append_unresolved_path_does_not_warn(self):
        """APPEND with an empty path resolution is NOT a no-op for the
        operator — it is the normal "glob matched no files yet" case during
        partial module load.  No new warning beyond the existing
        path-resolution log.
        """
        IrAsset = self._make_ir_asset()
        asset_paths = AssetPaths()
        # The existing _get_paths warning at line 526 covers the empty-glob
        # case; assertNoLogs is used to assert that our new warnings did NOT
        # also fire for APPEND.
        with patch.object(self._ir_asset_cls, "_get_paths", return_value=[]):
            with self.assertNoLogs(
                "odoo.addons.base.models.ir_asset", level="WARNING"
            ):
                IrAsset._process_path(
                    bundle="x.y",
                    directive="append",
                    target=None,
                    path_def="/web/x.js",
                    asset_paths=asset_paths,
                    seen=[],
                    addons=[],
                    installed=set(),
                    bundle_start_index=0,
                )
        self.assertEqual(asset_paths.list, [])

    def test_remove_resolved_path_succeeds_silently(self):
        """REMOVE with a path that DOES resolve does its job silently — no
        spurious warning when the manifest is correct.
        """
        IrAsset = self._make_ir_asset()
        asset_paths = AssetPaths()
        asset_paths.append(
            [("/web/x.js", "/full/x.js", 1)],
            "preexisting",
        )
        with patch.object(
            self._ir_asset_cls,
            "_get_paths",
            return_value=[("/web/x.js", "/full/x.js", 1)],
        ), self.assertNoLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ):
            IrAsset._process_path(
                bundle="x.y",
                directive="remove",
                target=None,
                path_def="/web/x.js",
                asset_paths=asset_paths,
                seen=[],
                addons=[],
                installed=set(),
                bundle_start_index=0,
            )
        # The path was successfully removed.
        self.assertEqual(asset_paths.list, [])


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
                # Return a modified stat_result with the faked st_mtime
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
        # this is mainly to avoid tests breaking when executed after pre-generate
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
        """Returns all ir.attachments associated to a bundle, regardless of the version."""
        bundle = (
            self.jsbundle_name if extension in ["js", "min.js"] else self.cssbundle_name
        )
        direction = ".rtl" if rtl else ""
        bundle_name = f"{bundle}{direction}.{extension}"
        url = self.env["ir.asset"]._get_asset_bundle_url(bundle_name, ANY_UNIQUE, {})
        domain = [("url", "=like", url)]
        return self.env["ir.attachment"].search(domain)

    def test_01_generation(self):
        """Checks that a bundle creates an ir.attachment record when its `js` method is called
        for the first time and this ir.attachment is different depending on `is_minified` param.
        """
        self.bundle = self._get_asset(self.jsbundle_name, debug_assets=False)

        # there shouldn't be any minified attachment associated to this bundle
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

        # trigger the first generation and, thus, the first save in database
        self.bundle.js()

        # there should be one minified attachment associated to this bundle
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

        # there shouldn't be any non-minified attachment associated to this bundle
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

        # trigger the first generation and, thus, the first save in database for the non-minified version.
        self.bundle_debug = self._get_asset(self.jsbundle_name, debug_assets=True)
        self.bundle_debug.js()

        # there should be one non-minified attachment associated to this bundle
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
        """Checks that the bundle's cache is working, i.e. that the bundle creates only one
        ir.attachment record when rendered multiple times.
        """
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
        """Checks that a bundle is invalidated when one of its assets' modification date is changed."""
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

            # check if the previous attachment is correctly cleaned
            self.assertEqual(
                len(self._any_ira_for_bundle("js")),
                1,
                "there should be one minified attachment associated to this bundle",
            )

    def test_04_content_invalidation(self):
        """Checks that a bundle is invalidated when its content is modified by adding a file to
        source.
        """
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

        # check if the previous attachment are correctly cleaned
        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified attachment associated to this bundle",
        )

    def test_05_normal_mode(self):
        """Checks that a bundle rendered in normal mode outputs minified assets
        and create a minified ir.attachment.
        """
        debug_bundle = self._get_asset(self.jsbundle_name)
        content = debug_bundle.get_links()
        debug_bundle.js()
        # there should be a minified file
        self.assertIn("test_assetsbundle.bundle1.min.js", content[0])

        # there should be one minified assets created in normal mode
        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            1,
            "there should be one minified assets created in normal mode",
        )

        # there shouldn't be any non-minified assets created in normal mode
        self.assertEqual(
            len(self._any_ira_for_bundle("js")),
            0,
            "there shouldn't be any non-minified assets created in normal mode",
        )

    def test_06_defer_assets_loading(self):
        """The main purpose of this test is to check the defer attribute does
        not end up being added *again* on an asset which is lazy-loaded as
        this is not W3C-valid.
        """
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
        """Checks that a bundle rendered in debug assets mode outputs non-minified assets
        and creates a non-minified ir.attachment.
        """
        debug_bundle = self._get_asset(self.jsbundle_name, debug_assets=True)
        content = debug_bundle.get_links()
        debug_bundle.js()
        # there should be a minified file
        self.assertIn(
            "test_assetsbundle.bundle1.js",
            content[0],
            "there should be one non-minified assets created in debug assets mode",
        )

        # there shouldn't be any minified assets created in debug mode
        self.assertEqual(
            len(self._any_ira_for_bundle("min.js")),
            0,
            "there shouldn't be any minified assets created in debug assets mode",
        )

        # there should be one non-minified assets created in debug mode
        self.assertEqual(
            len(self._any_ira_for_bundle("js")),
            1,
            "there should be one non-minified assets without a version in its url created in debug assets mode",
        )

    def test_08_css_generation3(self):
        # self.cssbundle_xlmid contains 3 rules (not checked below)
        self.bundle = self._get_asset(self.cssbundle_name)
        self.bundle.css()
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)
        self.assertEqual(len(self.bundle.get_attachments("min.css")), 1)

    def test_compile_css_dedups_repeated_library_import(self):
        """A library @import repeated across concatenated files is deduped,
        not reported as a forbidden local import.

        Regression: the sanitizer folded the dedup test into the security
        predicate, so the second occurrence of a legitimate ``@import "lib"``
        fell into the "forbidden for security reasons" branch. That polluted
        ``css_errors`` and tripped the degraded-CSS banner in ``css()`` for an
        entirely benign duplicate.
        """
        bundle = self._get_asset(self.cssbundle_name)
        source = (
            '@import "bootstrap/scss/functions";\n'
            ".a { color: red; }\n"
            '@import "bootstrap/scss/functions";'
        )
        # compile_css takes the compiler as an argument; an identity stub
        # exercises only the @import sanitization, no Sass subprocess.
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
        r"""A local @import padded with extra whitespace is still rejected.

        Regression: ``rx_preprocess_imports`` used ``\s?`` (0-1 whitespace),
        so ``@import  "./x"`` with two spaces slipped past the sanitizer
        unmatched and reached the compiler unsanitized. ``\s*`` closes the gap.
        """
        bundle = self._get_asset(self.cssbundle_name)
        source = '@import  "./secret.css";'  # two spaces — the historic bypass
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            out = bundle._css.compile_css(lambda s: s, source)
        self.assertTrue(
            bundle.css_errors,
            "a whitespace-padded local @import must be rejected",
        )
        self.assertNotIn("secret", out, "the local @import must be stripped")

    def test_stylesheet_url_rewrite_is_os_independent(self):
        r"""``StylesheetAsset`` rewrites ``@import``/``url(...)`` with posix
        semantics regardless of the host OS path flavour.

        Regression: ``web_dir`` used ``str(Path(self.url).parent)``. ``Path``
        is ``WindowsPath`` on Windows, so ``.parent`` yields backslashes; those
        were spliced into a regex replacement TEMPLATE (``rf"@import \1{web_dir}/"``)
        where ``\web`` reparses as the invalid escape ``\w`` and raises
        ``re.PatternError`` — a hard crash that escapes the ``except AssetError``
        handler. ``self.url`` is always a forward-slash web path, so the rewrite
        must use ``posixpath`` and a function replacement.

        Forcing the module ``Path`` to ``PureWindowsPath`` reproduces the
        Windows path flavour on a Linux CI: with the posix fix it is inert; a
        revert to ``Path``-based URL math makes this test crash or emit
        backslashes again.
        """
        from odoo.addons.base.models import assetsbundle
        from odoo.addons.base.models.assetsbundle import StylesheetAsset, WebAsset

        bundle = self._get_asset(self.cssbundle_name)
        sample = (
            '@import "theme.css";\n'
            ".a { background: url(images/logo.png); }\n"
            ".b { background: url(../img/sprite.png); }\n"
        )
        asset = StylesheetAsset(bundle, url="/web/static/src/css/foo.css")

        # Stub the base file/DB read so only the rewrite logic runs, and force
        # the Windows path flavour so a Path-based regression would resurface.
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
        """The rtlcss probe and invocation resolve the SAME executable.

        Regression: ``_check_rtlcss`` probed plain ``rtlcss`` while ``run_rtlcss``
        resolved ``rtlcss.cmd`` on Windows. The probe therefore failed on Windows
        and disabled RTL even when the npm ``.cmd`` shim was installed and usable.
        Both now route through ``_rtlcss_bin``.
        """
        from odoo.addons.base.models import assetsbundle

        # ``_rtlcss_bin`` is @functools.cache'd; clear it around each scenario so
        # a patched result never leaks into other tests' real rtlcss runs.
        self.addCleanup(assetsbundle.css_pipeline._rtlcss_bin.cache_clear)

        assetsbundle.css_pipeline._rtlcss_bin.cache_clear()
        with (
            patch.object(assetsbundle.css_pipeline.os, "name", "nt"),
            patch.object(
                assetsbundle.css_pipeline.misc, "find_in_path", return_value="C:/npm/rtlcss.cmd"
            ) as find,
        ):
            self.assertEqual(assetsbundle.css_pipeline._rtlcss_bin(), "C:/npm/rtlcss.cmd")
            find.assert_called_once_with("rtlcss.cmd")

        assetsbundle.css_pipeline._rtlcss_bin.cache_clear()
        with patch.object(assetsbundle.css_pipeline.os, "name", "posix"):
            self.assertEqual(assetsbundle.css_pipeline._rtlcss_bin(), "rtlcss")

    def test_js_header_line_count(self):
        """The verbose JS header emits exactly ``_HEADER_LINE_COUNT`` lines
        before the body.

        ``js_with_sourcemap`` feeds that constant to the sourcemap generator
        as each source's ``start_offset``; if ``with_header`` gains or loses a
        header line without updating the constant, generated line numbers
        silently drift. This guards the coupling.
        """
        bundle = self._get_asset(self.jsbundle_name)
        asset = JavascriptAsset(bundle, url="/web/static/src/_probe.js", inline="x")
        # A single-line body adds no newlines, so the rendered header+body's
        # newline count equals the number of header lines before the body.
        rendered = asset.with_header("SINGLE_LINE_BODY", minimal=False)
        self.assertEqual(rendered.count("\n"), JavascriptAsset._HEADER_LINE_COUNT)

    def test_bridge_resolver_memoizes_source_exports(self):
        """``_BridgeExportResolver.source_exports`` parses each spec once.

        A re-export hub is reached through many ``export * from`` chains in a
        single build; its parsed surface must be memoized, not recomputed on
        every visit. ``assertIs`` is true only when the result is cached.
        """
        from odoo.tools.assets.esm_graph import _BridgeExportResolver

        resolver = _BridgeExportResolver({}, {}, "test_bundle")
        # Seed the disk-read cache so source_exports resolves without I/O.
        resolver._cache["@x/y"] = "export const A = 1;\nexport default A;"
        first = resolver.source_exports("@x/y")
        second = resolver.source_exports("@x/y")
        self.assertEqual(first[0], {"A"})
        self.assertTrue(first[1])
        self.assertIs(first, second, "parsed exports must be memoized")

    def test_xml_template_elements_shapes(self):
        """XMLAsset.template_elements yields each template for every root shape.

        ``AssetsBundle.xml()`` consumes these directly (one parse per file)
        instead of re-parsing the serialized content; a regression would
        silently change which templates get registered. Covers the three root
        shapes the old wrap+reparse handled: ``<templates>``/``<odoo>``
        wrappers and a bare single-element template.
        """
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
            # Cached: parsed once, same list object on re-access.
            self.assertIs(asset.template_elements, asset.template_elements)

    def test_09_css_access(self):
        """Checks that the bundle's cache is working, i.e. that a bundle creates only enough
        ir.attachment records when rendered multiple times.
        """
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
        """Checks that a bundle is invalidated when its content is modified by adding a file to
        source.
        """
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

        # check if the previous attachment are correctly cleaned
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

    def test_12_css_debug(self):
        """Check that a bundle in debug mode outputs non-minified assets."""
        debug_bundle = self._get_asset(self.cssbundle_name, debug_assets=True)
        links = debug_bundle.get_links()
        # there should be a minified file
        self.assertEqual(links[0], "/web/assets/debug/test_assetsbundle.bundle2.css")

        # there should be one css asset created in debug mode
        debug_bundle.css()
        self.assertEqual(
            len(self._any_ira_for_bundle("css")),
            1,
            "there should be one css asset created in debug mode",
        )

    def test_14_duplicated_css_assets(self):
        """Checks that if the bundle's ir.attachment record is duplicated, the bundle is only sourced once. This could
        happen if multiple transactions try to render the bundle simultaneously.
        """
        bundle0 = self._get_asset(self.cssbundle_name)
        bundle0.css()
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 1)

        # duplicate the asset bundle
        ira0 = self._any_ira_for_bundle("min.css")
        ira1 = ira0.copy()
        self.assertEqual(len(self._any_ira_for_bundle("min.css")), 2)
        self.assertEqual(ira0.store_fname, ira1.store_fname)

        # the ir.attachment records should be deduplicated in the bundle's content
        content = bundle0.get_links()
        self.assertIn("test_assetsbundle.bundle2.min.css", content[0])

    # Language direction specific tests

    def test_15_rtl_css_generation(self):
        """Checks that a bundle creates an ir.attachment record when its `css` method is called
        for the first time for language with different direction and separate bundle is created for rtl direction.
        """
        self.bundle = self._get_asset(self.cssbundle_name, rtl=True)

        # there shouldn't be any attachment associated to this bundle
        self.assertEqual(len(self._any_ira_for_bundle("min.css", rtl=True)), 0)
        self.assertEqual(len(self.bundle.get_attachments("min.css")), 0)

        # trigger the first generation and, thus, the first save in database
        self.bundle.css()

        # there should be no compilation errors
        self.assertEqual(len(self.bundle.css_errors), 0)

        # there should be one attachment associated to this bundle
        self.assertEqual(len(self._any_ira_for_bundle("min.css", rtl=True)), 1)
        self.assertEqual(len(self.bundle.get_attachments("min.css")), 1)

    @unittest.skipUnless(shutil.which("rtlcss"), "rtlcss not installed")
    def test_15_rtl_invalid_css_generation(self):
        """Checks that erroneous css cannot be compiled by rtlcss and that errors are registered"""
        self.bundle = self._get_asset("test_assetsbundle.broken_css", rtl=True)
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle.css()
        self.assertEqual(len(self.bundle.css_errors), 1)
        self.assertIn("rtlcss: error processing payload", self.bundle.css_errors[0])

    def test_16_ltr_and_rtl_css_access(self):
        """Checks that the bundle's cache is working, i.e. that the bundle creates only one
        ir.attachment record when rendered multiple times for rtl direction also check we have two css bundles,
        one for ltr and one for rtl.
        """
        # Assets access for en_US language
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

        # Checks rtl and ltr bundles are different
        self.assertNotEqual(ltr_ira1.id, rtl_ira1.id)

        # Check two bundles are available, one for ltr and one for rtl
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
        """Checks that both css bundles are invalidated when one of its assets' modification date is changed"""
        ltr_bundle0 = self._get_asset(self.cssbundle_name, debug_assets=True)
        ltr_bundle0.css()
        ltr_last_modified0 = ltr_bundle0.get_checksum("css")
        ltr_version0 = ltr_bundle0.get_version("css")

        rtl_bundle0 = self._get_asset(self.cssbundle_name, rtl=True, debug_assets=True)
        rtl_bundle0.css()
        rtl_last_modified0 = rtl_bundle0.get_checksum("css")
        rtl_version0 = rtl_bundle0.get_version("css")

        # Touch test_cssfile1.css
        # Note: No lang specific context given while calling _get_asset so it will load assets for en_US
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

            # Checks rtl and ltr bundles are different
            self.assertNotEqual(ltr_ira1.id, rtl_ira1.id)

            # check if the previous attachment is correctly cleaned
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
        """Checks that a bundle is invalidated when its content is modified by adding a file to
        source.
        """
        # Assets for en_US
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

        # Checks rtl and ltr bundles are different
        self.assertNotEqual(ltr_ira1.id, rtl_ira1.id)

        # check if the previous attachment are correctly cleaned
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
        """Checks that a bundle rendered in debug mode(assets) with right to left language direction stores css files in assets bundle."""
        debug_bundle = self._get_asset(self.cssbundle_name, rtl=True, debug_assets=True)
        content = debug_bundle.get_links()

        # there should be an css assets bundle in /debug/rtl if user's lang direction is rtl and debug=assets
        self.assertEqual(
            f"/web/assets/debug/{self.cssbundle_name}.rtl.css",
            content[0],
            "there should be an css assets bundle in /debug/rtl if user's lang direction is rtl and debug=assets",
        )

        debug_bundle.css()
        # there should be an css assets bundle created in /rtl if user's lang direction is rtl and debug=assets
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
            (f"""<!DOCTYPE html>
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
</html>"""),
        )

    def test_21_external_lib_assets_debug_mode(self):
        html = self.env["ir.ui.view"]._render_template(
            "test_assetsbundle.template2", {"debug": "assets"}
        )
        self.assertEqual(
            str(html.strip()),
            ("""<!DOCTYPE html>
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
</html>"""),
        )


class TestXMLAssetsBundle(FileTouchable):

    def _get_asset(self, bundle, rtl=False, debug_assets=False):
        files, _ = self.env["ir.qweb"]._get_asset_content(bundle)
        return AssetsBundle(
            bundle, files, env=self.env, debug_assets=debug_assets, rtl=rtl
        )

    def test_01_broken_xml(self):
        """Checks that a bundle don't try hard to parse broken xml, and returns a comprehensive
        error message.
        """
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.broken_xml")

            # there shouldn't be any test_assetsbundle.invalid_xml template.
            # there should be an parsing_error template with the parsing error message.
            with self.assertRaisesRegex(
                XMLAssetError,
                "Invalid XML template: Opening and ending tag mismatch: SomeComponent line 4 and t, line 5, column 7' in file '/test_assetsbundle/static/invalid_src/xml/invalid_xml.xml",
            ):
                self.bundle.xml()

    def test_02_multiple_broken_xml(self):
        """Checks that a bundle with multiple broken xml returns a comprehensive error message."""
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.multiple_broken_xml")

            # there shouldn't be any test_assetsbundle.invalid_xml template or test_assetsbundle.second_invalid_xml template.
            # there should be one parsing_error templates with the parsing error message for the first file.
            with self.assertRaisesRegex(
                XMLAssetError,
                "Invalid XML template: Opening and ending tag mismatch: SomeComponent line 4 and t, line 5, column 7' in file '/test_assetsbundle/static/invalid_src/xml/invalid_xml.xml",
            ):
                self.bundle.xml()

    def test_04_template_wo_name(self):
        """Checks that a bundle with template without name returns a comprehensive error message."""
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.wo_name")

            # there shouldn't be raise a ValueError, there should a parsing_error template with
            # the error message.
            with self.assertRaisesRegex(
                XMLAssetError,
                "'Template name is missing.' in file '/test_assetsbundle/static/invalid_src/xml/template_wo_name.xml'",
            ):
                self.bundle.xml()

    def test_05_file_not_found(self):
        """Checks that a bundle with a file in error (file not found, encoding error, or other) returns a comprehensive error message."""
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.bundle = self._get_asset("test_assetsbundle.file_not_found")

            # there shouldn't be raise a ValueError, there should a parsing_error template with
            # the error message.
            # ``AssetNotFoundError`` reaches the XML error path unwrapped, so
            # the message is the precise "Could not find" — not the generic
            # "Could not get content for" re-wrap it used to degrade into.
            with self.assertRaisesRegex(
                XMLAssetError,
                "Could not find test_assetsbundle/static/invalid_src/xml/file_not_found.xml",
            ):
                self.bundle.xml()


@tagged("-at_install", "post_install")
class TestAssetsBundleInBrowser(HttpCase):
    def test_01_js_interpretation(self):
        """Checks that the javascript of a bundle is correctly interpreted."""
        self.browser_js(
            "/test_assetsbundle/js",
            "a + b + c === 6 ? console.log('test successful') : console.log('error')",
            login="admin",
        )

    @skip("Feature Regression")
    def test_02_js_interpretation_inline(self):
        """Checks that the javascript of a bundle is correctly interpreted when mixed with inline."""
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

    # LPE Fixme
    # Review point @al: is this really what we want people to do ?
    def test_03_js_interpretation_recommended_new_method(self):
        """Checks the feature of test_02 is still produceable, but in another way
        '/web/content/<int:id>/<string: filename.js>',
        """
        code = b"const d = 4;"
        attach = self.env["ir.attachment"].create(
            {
                "name": "CustomJscode.js",
                "mimetype": "text/javascript",
                "datas": base64.b64encode(code),
            }
        )
        # Use this route (filename is necessary)
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

        # patch methods 'create' and 'unlink' of model 'ir.attachment'.
        # ``_unlink_attachments`` moved to AssetAttachmentStore; ``save_attachment``
        # (also on the store) calls it on the store instance, so patch it there —
        # patching the AssetsBundle delegator would not intercept that internal call.
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
        """Checks that the ir.attachments records created for compiled assets in debug mode
        are correctly invalidated.
        """
        # Compile for the first time
        self._bundle(self._get_asset(), True, False, "(First access)")

        # Compile a second time, without changes
        self._bundle(self._get_asset(), False, False, "(Second access, no change)")

        # Touch the file and compile a third time
        path = file_path("test_assetsbundle/static/src/scss/test_file1.scss")
        t = time.time() + 5
        asset = self._get_asset()
        with self._touch(path, t):
            self._bundle(asset, True, True)

            # Because we are in the same transaction since the beginning of the test, the first asset
            # created and the second one have the same write_date, but the file's last modified date
            # has really been modified. If we do not update the write_date to a posterior date, we are
            # not able to reproduce the case where we compile this bundle again without changing
            # anything.
            self.env["ir.attachment"].flush_model(["checksum", "write_date"])
            self.cr.execute(
                "update ir_attachment set write_date=clock_timestamp() + interval '10 seconds' where id = (select max(id) from ir_attachment)"
            )
            self.env["ir.attachment"].invalidate_model(["write_date"])

            # Compile a fourth time, without changes
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
        # asset is now: js_file4 ; js_file3
        self.env["ir.asset"].create(
            {
                "name": "test_jsfile4",
                "bundle": "test_assetsbundle.manifest4",
                "directive": "replace",
                "path": "test_assetsbundle/static/src/js/test_jsfile[12].js",
                "target": "test_assetsbundle/static/src/js/test_jsfile[45].js",
            }
        )
        # asset is now: js_file1 ; js_file2 ; js_file3
        # because js_file is replaced by 1 and 2
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
        # indeed everything in the bundle matches the glob, so there is no attachment
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

    #
    # LPE Fixme: Warning, this matches a change in behavior
    # Before this, each node within an asset could have a "media" and/or a "direction"
    # attribute to tell the browser to take preferably the css resource
    # in the relevant viewport or text direction
    #
    # with the new ir_assert mechanism, these attributes are only evaluated at the t-call-asset
    # step, that is, a step earlier than before, implicating a more restrictive usage
    #
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
        # Regression: ``!important`` must be replicated onto the prefixed copies
        # (previously dropped, so a WebKit form-control reset lost its weight).
        self.assertRegex(
            content,
            r"\.appearance-none-important\{-webkit-appearance:none !important;"
            r"-moz-appearance:none !important;appearance:none !important\}",
        )
        # Regression: a hyphenated value must reach the prefixed copies intact
        # (``\w+`` truncated ``menulist-button`` to ``menulist``).
        self.assertRegex(
            content,
            r"\.appearance-menulist-button\{-webkit-appearance:menulist-button;"
            r"-moz-appearance:menulist-button;appearance:menulist-button\}",
        )

        # Flex properties are not vendor-prefixed (autoprefix_css only handles appearance)
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
        """A bare ``/*! <hex> */`` loud comment must not alias the per-file
        split marker.

        Dart Sass preserves loud comments verbatim, so a source comment whose
        body is a single hex token (e.g. a build-hash stamp) reaches
        ``rx_css_split`` looking exactly like a fragment boundary.  Before the
        marker was namespaced (``odoo-split:``) this raised RuntimeError and
        took the entire bundle's CSS compile down; now the comment is left as
        inert content.
        """
        self.env["ir.asset"].create(
            {
                "name": "1",
                "bundle": "test_assetsbundle.irasset_split",
                "path": "test_assetsbundle/static/src/scss/test_split_marker.scss",
            }
        )
        bundle = self.env["ir.qweb"]._get_asset_bundle(
            "test_assetsbundle.irasset_split", js=False
        )
        # Must not raise; the rule compiles and the inert hex comment survives.
        content = bundle.css().raw.decode()
        self.assertRegex(content, r"\.split-marker-regression\{color:red\}")
        self.assertIn("/*! a1b2c3d */", content)

    def test_21_js_before_css(self):
        """Non existing target node: ignore the manifest line"""
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
        """Non existing target node: ignore the manifest line"""
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

    @mute_logger("odoo.addons.base.models.ir_asset")
    def test_31(self):
        path_to_dummy = "../../tests/dummy.js"
        me = pathlib.Path(__file__).parent.absolute()
        file_path = me.joinpath(
            "..", path_to_dummy
        )  # assuming me = test_assetsbundle/tests
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

    @mute_logger("odoo.addons.base.models.ir_asset")
    def test_32_a_relative_path_in_addon(self):
        path_to_dummy = "../../tests/dummy.xml"
        me = pathlib.Path(__file__).parent.absolute()
        file_path = me.joinpath(
            "..", path_to_dummy
        )  # assuming me = test_assetsbundle/tests
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
            [
                (
                    "/test_assetsbundle/../../tests/dummy.xml",
                    None,
                    "test_assetsbundle.irassetsec",
                    None,
                )
            ],
        )
        # TODO, validate this behaviour
        # the idea is that if the second element is False (not None) it will be added to the assetbundle, but considered in any case as an attachment url)

    @mute_logger("odoo.addons.base.models.ir_asset")
    def test_32_b_relative_path_outsied_addon(self):
        path_to_dummy = "../../tests/dummy.xml"
        me = pathlib.Path(__file__).parent.absolute()
        file_path = me.joinpath(
            "..", path_to_dummy
        )  # assuming me = test_assetsbundle/tests
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
            [
                (
                    "../../tests/dummy.xml",
                    None,
                    "test_assetsbundle.irassetsec",
                    None,
                )
            ],
        )

    def test_33(self):
        """Assets from known-but-uninstalled addons are silently skipped."""
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
        # No exception: uninstalled addon assets are gracefully excluded
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

    @mute_logger("odoo.addons.base.models.ir_asset")
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

    @mute_logger("odoo.addons.base.models.ir_asset")
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
            [
                (
                    "/test_assetsbundle/data/ir_asset.xml",
                    None,
                    "test_assetsbundle.irassetsec",
                    None,
                )
            ],
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
            [
                (
                    "/test_assetsbundle/static/accessible.xml",
                    f"{base_path}/static/accessible.xml",
                    "test_assetsbundle.irassetsec",
                    modified,
                )
            ],
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
        # The scss should be compiled
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
        keys = list(self.env.registry._Registry__caches["assets"])

        asset_keys = [
            key
            for key in keys
            if key[0] == "ir.asset" and "_get_asset_paths" in str(key[1])
        ]  # ignore topological sort entry
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
        # link + native-data + native-nodes: the ESM build-caching change
        # added _get_native_module_nodes_cached as a third assets entry
        # per (bundle, assets_params).
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", debug="tests")
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", debug="1")
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)

        # in debug=assets, the ormcache is not used for _generate_asset_links_cache
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
        self.assertEqual(len(qweb_keys), 3)  # link(js) + native-data + native-nodes

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", js=False, css=True)
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 4)  # + link(css); css-only skips native caches

        # NOTE: this result is not really desired but this is the current behaviour. In practice, we usually only generate one of them.
        # This could be enforced or avoided
        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend", js=True, css=True)
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 5)  # + link(js+css)

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
        self.assertEqual(len(qweb_keys), 3)  # link + native-data + native-nodes

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
        # + a second link entry for rtl; the native caches are shared
        # (lang is not part of their key)
        self.assertEqual(len(qweb_keys), 4)

    def test_assets_node_orm_cache_usage_website(self):
        if self.env["ir.module.module"].search(
            [("name", "=", "website"), ("state", "=", "uninstalled")]
        ):
            return  # only makes sense if website is installed
        self.env.registry.clear_cache("assets")

        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 0)
        self.assertEqual(len(qweb_keys), 0)

        self.env["ir.qweb"].with_context(website_id=None)._get_asset_nodes(
            "web.assets_backend"
        )
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)  # link + native-data + native-nodes

        self.env["ir.qweb"].with_context(website_id=1)._get_asset_nodes(
            "web.assets_backend"
        )
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(
            len(asset_keys), 2
        )  # the content may be different for different websites, even if it is not always the case
        # 2 link + 2 native-data + 2 native-nodes (assets_params per website)
        self.assertEqual(len(qweb_keys), 6)

    def test_assets_node_orm_cache_usage_node_flags(self):
        self.env.registry.clear_cache("assets")

        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 0)
        self.assertEqual(len(qweb_keys), 0)

        self.env["ir.qweb"]._get_asset_nodes("web.assets_backend")
        asset_keys, qweb_keys = self.cache_keys()
        self.assertEqual(len(asset_keys), 1)
        self.assertEqual(len(qweb_keys), 3)  # link + native-data + native-nodes

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
        ).css()  # force pregeneration so that we have the base style
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
        ).css()  # force pregeneration so that we have the base style
        self.env["ir.asset"].create(
            {
                "name": "Css error",
                "bundle": "web.assets_frontend",
                "path": "test_assetsbundle/static/src/css/test_error.scss",
            }
        )
        with mute_logger("odoo.addons.base.models.assetsbundle"):
            self.start_tour("/", "css_error_tour_frontend")
