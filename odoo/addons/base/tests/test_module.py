import importlib
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from odoo.modules.module import (
    Manifest,
    MissingDependencyError,
    _load_manifest,
    adapt_version,
    check_python_external_dependency,
    get_module_icon,
)
from odoo.release import major_version
from odoo.tests.common import BaseCase
from odoo.tools import mute_logger

import odoo.addons


class TestModuleManifest(BaseCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.TemporaryDirectory(prefix="odoo_test_addons_")
        cls.addClassCleanup(cls._tmp_dir.cleanup)
        cls.addons_path = cls._tmp_dir.name

        patcher = patch.object(odoo.addons, "__path__", [cls.addons_path])
        cls.startClassPatcher(patcher)

    def setUp(self):
        self.module_root = tempfile.mkdtemp(
            prefix="odoo_test_module_", dir=self.addons_path
        )
        self.module_name = Path(self.module_root).name

    def test_default_manifest(self):
        with Path(str(Path(self.module_root, "__manifest__.py"))).open("w") as file:
            file.write(
                str(
                    {
                        "name": f"Temp {self.module_name}",
                        "license": "MIT",
                        "author": "Fapi",
                    }
                )
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
        module_name = "base"
        new_manifest = Manifest.for_addon(module_name)
        orig_auto_install = new_manifest["auto_install"]
        with self.assertRaisesRegex(TypeError, r"does not support item assignment"):
            new_manifest["auto_install"] = not orig_auto_install
        self.assertIs(Manifest.for_addon(module_name), new_manifest)

    def test_missing_manifest(self):
        with self.assertLogs("odoo.modules.module", "DEBUG") as capture:
            manifest = Manifest.for_addon(self.module_name)
        self.assertIs(manifest, None)
        self.assertIn("manifest not found", capture.output[0])

    def test_missing_license(self):
        with Path(str(Path(self.module_root, "__manifest__.py"))).open("w") as file:
            file.write(str({"name": f"Temp {self.module_name}"}))
        with self.assertLogs("odoo.modules.module", "WARNING") as capture:
            manifest = Manifest.for_addon(self.module_name)
            manifest._force_parse()
        self.assertEqual(manifest["license"], "LGPL-3")
        self.assertEqual(manifest["author"], "")
        self.assertIn("Missing `author` key", capture.output[0])
        self.assertIn("Missing `license` key", capture.output[1])


class TestManifestAutoInstall(BaseCase):
    """Validate ``auto_install`` key handling in _load_manifest (guards against
    silently-misparsed manifests: a string becoming a char set, a non-dependency
    trigger).
    """

    BASE = {"author": "x", "license": "MIT"}

    def test_auto_install_string_is_rejected(self):
        # 'auto_install': 'sale' (forgot the brackets) must not become {'s','a',...}
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
    """The manifest lookup cache must not cache misses (so a module that
    appears later is still found) and must be droppable via clear_caches().
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="odoo_test_cache_")
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(odoo.addons, "__path__", [self._tmp.name])
        p.start()
        self.addCleanup(p.stop)
        # Isolate: snapshot the process-wide cache, start empty, restore on exit
        # so we never evict entries (e.g. 'base') that other test classes rely on.
        saved = dict(Manifest._manifest_cache)
        Manifest.clear_caches()

        def _restore():
            Manifest._manifest_cache.clear()
            Manifest._manifest_cache.update(saved)

        self.addCleanup(_restore)

    def _make(self, name):
        d = Path(self._tmp.name, name)
        d.mkdir()
        (d / "__manifest__.py").write_text(
            "{'name': 'X', 'license': 'LGPL-3', 'author': 'x'}"
        )
        return name

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

    def test_clear_caches_drops_found_entries(self):
        name = self._make("probe_clear")
        first = Manifest.for_addon(name)
        Manifest.clear_caches()
        again = Manifest.for_addon(name)
        self.assertIsNotNone(again)
        self.assertIsNot(again, first)


class TestExternalDependency(BaseCase):
    """check_python_external_dependency must import the requirement *name*, not
    the raw spec string, and MissingDependencyError must carry the dependency.
    """

    @mute_logger("odoo.modules.module")
    def test_specced_importable_module_name_is_accepted(self):
        # Legacy manifest style: an importable module name with NO PyPI metadata
        # but WITH a version specifier.  importlib.import_module("<name>>=1.0")
        # would always fail, so the name must be parsed out first.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        Path(tmp, "odoo_probe_legacy_dep.py").write_text("#\n")
        sys.path.insert(0, tmp)
        self.addCleanup(lambda: tmp in sys.path and sys.path.remove(tmp))
        importlib.invalidate_caches()
        # must not raise
        check_python_external_dependency("odoo_probe_legacy_dep>=1.0")

    def test_genuinely_missing_dependency_raises(self):
        with self.assertRaises(MissingDependencyError):
            check_python_external_dependency("odoo_definitely_absent_pkg_zzz>=1.0")

    def test_error_renders_message_and_keeps_dependency(self):
        # No .format() templating: the message is used verbatim, the structured
        # dependency is exposed for callers (ir.module.module) to reuse.
        err = MissingDependencyError("Unable to find 'foo>=1' in path", "foo>=1")
        self.assertEqual(str(err), "Unable to find 'foo>=1' in path")
        self.assertEqual(err.dependency, "foo>=1")
        self.assertNotIn("{dependency", str(err))


class TestAdaptVersion(BaseCase):
    """adapt_version canonicalisation (guards the removal of the dead
    non-digit-strip branch: behaviour must be unchanged).
    """

    def test_bare_versions_get_serie_prefix(self):
        self.assertEqual(adapt_version("1.0"), f"{major_version}.1.0")
        self.assertEqual(adapt_version("2.5"), f"{major_version}.2.5")
        self.assertEqual(adapt_version("1.2.3"), f"{major_version}.1.2.3")

    def test_serie_prefixed_versions_unchanged(self):
        self.assertEqual(adapt_version(major_version), major_version)
        self.assertEqual(adapt_version(f"{major_version}.1.2"), f"{major_version}.1.2")
        self.assertEqual(
            adapt_version(f"{major_version}.1.2.3"), f"{major_version}.1.2.3"
        )

    def test_four_part_non_serie_version_is_left_unchanged(self):
        self.assertEqual(adapt_version("1.2.3.4"), "1.2.3.4")

    def test_rejects_malformed(self):
        for bad in ("abc", "1", "1.2.3.4.5.6", "1.x"):
            with self.assertRaises(ValueError):
                adapt_version(bad)


class TestModuleIcon(BaseCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="odoo_test_icon_")
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(odoo.addons, "__path__", [self._tmp.name])
        p.start()
        self.addCleanup(p.stop)
        saved = dict(Manifest._manifest_cache)
        Manifest.clear_caches()

        def _restore():
            Manifest._manifest_cache.clear()
            Manifest._manifest_cache.update(saved)

        self.addCleanup(_restore)

    def test_missing_icon_falls_back_to_base_default(self):
        name = "probe_icon"
        d = Path(self._tmp.name, name)
        d.mkdir()
        (d / "__manifest__.py").write_text(
            "{'name': 'X', 'license': 'LGPL-3', 'author': 'x'}"
        )
        # No icon file on disk -> the base default is returned.
        self.assertEqual(get_module_icon(name), "/base/static/description/icon.png")

    def test_icon_for_unknown_module_is_base_default(self):
        self.assertEqual(
            get_module_icon("no_such_module_xyz"), "/base/static/description/icon.png"
        )


class TestManifestMapping(BaseCase):
    """The Mapping facade: computed keys must surface through both __iter__ and
    __getitem__ (they share a single _COMPUTED_KEYS source of truth).
    """

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
            manifest[key]  # must not raise KeyError
