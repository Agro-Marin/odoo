import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from odoo.modules.module import (
    Manifest,
    MissingDependencyError,
    _load_manifest,
    check_python_external_dependency,
    get_module_icon,
)
from odoo.release import major_version
from odoo.tools import mute_logger

import odoo.addons

BaseCase = unittest.TestCase


class TestModuleManifest(BaseCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.TemporaryDirectory(prefix="odoo_test_addons_")
        cls.addClassCleanup(cls._tmp_dir.cleanup)
        cls.addons_path = cls._tmp_dir.name

        patcher = patch.object(odoo.addons, "__path__", [cls.addons_path])
        cls.enterClassContext(patcher)

    def setUp(self):
        self.module_root = tempfile.mkdtemp(
            prefix="odoo_test_module_", dir=self.addons_path
        )
        self.module_name = Path(self.module_root).name

    def test_default_manifest(self):
        Path(str(Path(self.module_root, "__manifest__.py"))).write_text(
            str(
                {
                    "name": f"Temp {self.module_name}",
                    "license": "MIT",
                    "author": "Fapi",
                }
            ),
            encoding="utf-8",
        )

        with self.assertNoLogs("odoo.modules.module", "WARNING"):
            manifest = dict(Manifest.for_addon(self.module_name))

        self.maxDiff = None
        self.assertDictEqual(
            manifest,
            {
                "addons_path": self.addons_path,
                "application": False,
                "assets": {},
                "author": "Fapi",
                "auto_install": False,
                "bootstrap": False,
                "category": "Uncategorized",
                "cloc_exclude": [],
                "configurator_snippets": {},
                "configurator_snippets_addons": {},
                "countries": [],
                "data": [],
                "demo": [],
                "demo_xml": [],
                "depends": ["base"],
                "description": "",
                "esm": {},
                "external_dependencies": {},
                "icon": "/base/static/description/icon.png",
                "init_xml": [],
                "installable": True,
                "images": [],
                "images_preview_theme": {},
                "license": "MIT",
                "live_test_url": "",
                "name": f"Temp {self.module_name}",
                "new_page_templates": {},
                "post_init_hook": "",
                "post_load": "",
                "pre_init_hook": "",
                "sequence": 100,
                "static_path": None,
                "summary": "",
                "test": [],
                "theme_customizations": {},
                "update_xml": [],
                "uninstall_hook": "",
                "version": f"{major_version}.1.0",
                "web": False,
                "website": "",
            },
        )

    def test_change_manifest(self):
        # Deliberately a module this test creates, not "base": reading a module
        # the patched addons path does not contain used to succeed anyway,
        # served from a cache nothing invalidated, so the patch above was inert
        # and the assertions ran against the real `base`.
        Path(self.module_root, "__manifest__.py").write_text(
            str({"name": "X", "license": "MIT", "author": "x"}), encoding="utf-8"
        )
        manifest = Manifest.for_addon(self.module_name)
        orig_auto_install = manifest["auto_install"]
        with self.assertRaisesRegex(TypeError, r"does not support item assignment"):
            manifest["auto_install"] = not orig_auto_install
        self.assertIs(Manifest.for_addon(self.module_name), manifest)

    def test_missing_manifest(self):
        with self.assertLogs("odoo.modules.module", "DEBUG") as capture:
            manifest = Manifest.for_addon(self.module_name)
        self.assertIs(manifest, None)
        self.assertIn("manifest not found", capture.output[0])

    def test_missing_license(self):
        Path(str(Path(self.module_root, "__manifest__.py"))).write_text(
            str({"name": f"Temp {self.module_name}"}), encoding="utf-8"
        )
        with self.assertLogs("odoo.modules.module", "WARNING") as capture:
            manifest = Manifest.for_addon(self.module_name)
            manifest._force_parse()
        self.assertEqual(manifest["license"], "LGPL-3")
        self.assertEqual(manifest["author"], "")
        self.assertIn("Missing `author` key", capture.output[0])
        self.assertIn("Missing `license` key", capture.output[1])


class TestManifestAutoInstall(BaseCase):
    BASE = {"author": "x", "license": "MIT"}

    def test_auto_install_string_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "forget.*brackets"):
            _load_manifest(
                "m", {**self.BASE, "auto_install": "sale", "depends": ["sale"]}
            )

    def test_auto_install_non_bool_non_collection_rejected(self):
        with self.assertRaisesRegex(TypeError, "must be a bool"):
            _load_manifest("m", {**self.BASE, "auto_install": 5, "depends": ["base"]})

    def test_auto_install_trigger_must_be_a_dependency(self):
        with self.assertRaisesRegex(AssertionError, "must be dependencies"):
            _load_manifest(
                "m", {**self.BASE, "auto_install": ["sale"], "depends": ["base"]}
            )

    def test_auto_install_true_expands_to_all_depends(self):
        manifest = _load_manifest(
            "m", {**self.BASE, "auto_install": True, "depends": ["base", "sale"]}
        )
        self.assertEqual(manifest["auto_install"], {"base", "sale"})

    def test_auto_install_list_subset_of_depends_is_kept(self):
        manifest = _load_manifest(
            "m", {**self.BASE, "auto_install": ["base"], "depends": ["base", "sale"]}
        )
        self.assertEqual(manifest["auto_install"], {"base"})

    def test_base_depends_forced_empty(self):
        self.assertEqual(_load_manifest("base", dict(self.BASE))["depends"], [])

    def test_non_base_empty_depends_forced_to_base(self):
        self.assertEqual(_load_manifest("m", dict(self.BASE))["depends"], ["base"])


class TestManifestCache(BaseCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="odoo_test_cache_")
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(odoo.addons, "__path__", [self._tmp.name])
        p.start()
        self.addCleanup(p.stop)
        saved = dict(Manifest._parse_cache)
        saved_resolution = dict(Manifest._resolution_cache)
        Manifest.clear_caches()

        def _restore():
            Manifest._parse_cache.clear()
            Manifest._parse_cache.update(saved)
            Manifest._resolution_cache.clear()
            Manifest._resolution_cache.update(saved_resolution)

        self.addCleanup(_restore)

    def _make(self, name, **extra):
        d = Path(self._tmp.name, name)
        d.mkdir(exist_ok=True)
        self._write(name, {"name": "X", "license": "LGPL-3", "author": "x", **extra})
        return name

    def _write(self, name, content):
        path = Path(self._tmp.name, name, "__manifest__.py")
        path.write_text(str(content), encoding="utf-8")
        # st_mtime_ns has filesystem-dependent granularity and these writes are
        # microseconds apart; stamp it so the test measures the invalidation
        # rule rather than the clock.
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    def test_miss_is_not_cached_so_a_later_module_is_found(self):
        name = "probe_appears_later"
        self.assertIsNone(Manifest.for_addon(name, display_warning=False))
        self._make(name)
        found = Manifest.for_addon(name, display_warning=False)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, name)

    def test_found_manifest_is_cached(self):
        name = self._make("probe_cached")
        first = Manifest.for_addon(name)
        self.assertIs(Manifest.for_addon(name), first)

    def test_a_manifest_edited_on_disk_is_seen_by_the_next_lookup(self):
        # ir.module.module.update_list exists to notice exactly this, so no
        # cache in front of it may answer with the pre-edit content.
        name = self._make("probe_edited", version="1.0")
        self.assertEqual(Manifest.for_addon(name)["version"], f"{major_version}.1.0")
        self._write(
            name,
            {"name": "X", "license": "LGPL-3", "author": "x", "version": "9.9"},
        )
        self.assertEqual(Manifest.for_addon(name)["version"], f"{major_version}.9.9")

    def test_a_manifest_edited_on_disk_is_seen_by_the_full_scan(self):
        name = self._make("probe_scanned", version="1.0")
        found = {m.name: m for m in Manifest.all_addon_manifests()}
        self.assertEqual(found[name]["version"], f"{major_version}.1.0")
        self._write(
            name,
            {"name": "X", "license": "LGPL-3", "author": "x", "version": "9.9"},
        )
        found = {m.name: m for m in Manifest.all_addon_manifests()}
        self.assertEqual(found[name]["version"], f"{major_version}.9.9")

    def test_a_manifest_removed_from_disk_stops_resolving(self):
        name = self._make("probe_removed")
        self.assertIsNotNone(Manifest.for_addon(name))
        Path(self._tmp.name, name, "__manifest__.py").unlink()
        self.assertIsNone(Manifest.for_addon(name, display_warning=False))

    def test_an_unchanged_manifest_is_not_reparsed(self):
        name = self._make("probe_stable")
        first = Manifest.for_addon(name)
        with patch.object(
            Manifest, "_parse_from_path", side_effect=AssertionError("reparsed")
        ):
            self.assertIs(Manifest.for_addon(name), first)
            self.assertIs(
                next(m for m in Manifest.all_addon_manifests() if m.name == name),
                first,
            )

    def test_clear_caches_drops_found_entries(self):
        name = self._make("probe_clear")
        first = Manifest.for_addon(name)
        Manifest.clear_caches()
        again = Manifest.for_addon(name)
        self.assertIsNotNone(again)
        self.assertIsNot(again, first)


class TestExternalDependency(BaseCase):
    @mute_logger("odoo.modules.module")
    def test_specced_importable_module_name_is_accepted(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        Path(tmp, "odoo_probe_legacy_dep.py").write_text("#\n", encoding="utf-8")
        sys.path.insert(0, tmp)
        self.addCleanup(lambda: tmp in sys.path and sys.path.remove(tmp))
        importlib.invalidate_caches()
        check_python_external_dependency("odoo_probe_legacy_dep>=1.0")

    def test_genuinely_missing_dependency_raises(self):
        with self.assertRaises(MissingDependencyError):
            check_python_external_dependency("odoo_definitely_absent_pkg_zzz>=1.0")

    def test_error_renders_message_and_keeps_dependency(self):
        err = MissingDependencyError("Unable to find 'foo>=1' in path", "foo>=1")
        self.assertEqual(str(err), "Unable to find 'foo>=1' in path")
        self.assertEqual(err.dependency, "foo>=1")
        self.assertNotIn("{dependency", str(err))


class TestManifestVersionResilience(BaseCase):
    BASE = {"author": "x", "license": "MIT", "name": "X"}

    def test_malformed_version_demotes_to_uninstallable(self):
        with self.assertLogs("odoo.modules.module", "WARNING") as capture:
            manifest = _load_manifest("m", {**self.BASE, "version": "1.0-beta"})
        self.assertFalse(manifest["installable"])
        self.assertIn("invalid version", capture.output[0])

    def test_malformed_version_on_uninstallable_module_is_tolerated(self):
        manifest = _load_manifest(
            "m", {**self.BASE, "version": "1.0-beta", "installable": False}
        )
        self.assertFalse(manifest["installable"])

    def test_string_depends_rejected(self):
        with self.assertRaisesRegex(TypeError, "forget.*brackets"):
            _load_manifest("m", {**self.BASE, "depends": "base"})


class TestModuleIcon(BaseCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="odoo_test_icon_")
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(odoo.addons, "__path__", [self._tmp.name])
        p.start()
        self.addCleanup(p.stop)
        saved = dict(Manifest._parse_cache)
        saved_resolution = dict(Manifest._resolution_cache)
        Manifest.clear_caches()

        def _restore():
            Manifest._parse_cache.clear()
            Manifest._parse_cache.update(saved)
            Manifest._resolution_cache.clear()
            Manifest._resolution_cache.update(saved_resolution)

        self.addCleanup(_restore)

    def _make(self, name, **extra):
        d = Path(self._tmp.name, name)
        d.mkdir()
        (d / "__manifest__.py").write_text(
            str({"name": "X", "license": "LGPL-3", "author": "x", **extra})
        )
        return name

    def test_missing_icon_falls_back_to_base_default(self):
        name = self._make("probe_icon")
        self.assertEqual(get_module_icon(name), "/base/static/description/icon.png")

    def test_icon_for_unknown_module_is_base_default(self):
        self.assertEqual(
            get_module_icon("no_such_module_xyz"), "/base/static/description/icon.png"
        )

    def test_the_manifest_resolves_its_own_icon_without_looking_itself_up(self):
        # Manifest.icon used to call get_module_icon(self.name), which called
        # Manifest.for_addon(self.name) to reach the manifest it was already a
        # method of -- a second parse of the same file per module, and the
        # dominant cost of modules.db.initialize.
        name = self._make("probe_no_self_lookup")
        manifest = Manifest.for_addon(name)
        with patch.object(
            Manifest, "for_addon", side_effect=AssertionError("looked itself up")
        ):
            self.assertEqual(manifest["icon"], "/base/static/description/icon.png")

    def test_a_declared_icon_agrees_between_both_entry_points(self):
        name = self._make(
            "probe_declared_icon", icon="/base/static/description/icon.png"
        )
        self.assertEqual(
            Manifest.for_addon(name)["icon"], "/base/static/description/icon.png"
        )
        self.assertEqual(get_module_icon(name), Manifest.for_addon(name)["icon"])


class TestManifestMapping(BaseCase):
    def _manifest(self):
        return Manifest(
            path="/tmp/odoo_probe_map",
            manifest_content={"name": "P", "license": "LGPL-3", "author": "x"},
        )

    def test_computed_keys_present_in_iter(self):
        keys = set(self._manifest())
        for key in Manifest._COMPUTED_KEYS:
            self.assertIn(key, keys)

    def test_len_matches_iteration(self):
        manifest = self._manifest()
        self.assertEqual(len(manifest), len(list(iter(manifest))))

    def test_computed_keys_reachable_via_getitem(self):
        manifest = self._manifest()
        for key in Manifest._COMPUTED_KEYS:
            manifest[key]
