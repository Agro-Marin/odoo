import importlib
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from odoo.modules.db import (
    _AUTO_INSTALL_CANDIDATES_QUERY,
    _AUTO_INSTALL_CLOSURE_QUERY,
    create_categories,
)
from odoo.modules.module import (
    Manifest,
    MissingDependencyError,
    _load_manifest,
    adapt_version,
    check_python_external_dependency,
    check_version,
    get_module_icon,
)
from odoo.release import major_version
from odoo.tests.common import BaseCase, TransactionCase
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


class TestManifestVersionResilience(BaseCase):
    """A malformed version must quarantine the module (installable=False), not
    crash manifest parsing: a raise would propagate through every all-manifests
    consumer (db.initialize, update_list, graph build), so one stray
    third-party addon on the path would prevent bootstrapping any database.
    """

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
        # 'depends': 'base' (forgot the brackets) must not be iterated
        # character by character as module names
        with self.assertRaisesRegex(TypeError, "forget.*brackets"):
            _load_manifest("m", {**self.BASE, "depends": "base"})


class TestCheckVersion(BaseCase):
    """check_version(should_raise=False) must never raise, including for
    structurally malformed versions that adapt_version rejects.
    """

    def test_should_raise_false_never_raises(self):
        self.assertFalse(check_version("garbage", should_raise=False))
        self.assertFalse(check_version("1.2.3.4.5.6", should_raise=False))

    def test_should_raise_true_raises_on_malformed(self):
        with self.assertRaises(ValueError):
            check_version("garbage")

    def test_verdicts(self):
        self.assertTrue(check_version(major_version, should_raise=False))
        self.assertTrue(check_version(f"{major_version}.1.0", should_raise=False))
        # 4-part version of another serie: well-formed but wrong release
        self.assertFalse(check_version("1.2.3.4", should_raise=False))


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


class TestAutoInstallQueries(TransactionCase):
    """Selection logic of the two queries behind db.initialize()'s recursive
    auto-install marking, on fixture rows rolled back with the transaction.

    Guards the uninstallable-dependency rules: a candidate with an
    uninstallable dependency must not be selected, and the closure must never
    mark an uninstallable module 'to install' (doing so overwrote its state).

    The queries scan the real ir_module_module table too (which legitimately
    contains 'to install' rows while at_install tests run), so every
    assertion is scoped to the fixture's '_audit_ai_' names — a prefix no real
    module can have (leading underscore fails MODULE_NAME_RE).
    """

    PREFIX = "_audit_ai_"

    def _add_module(self, name, state, auto_install=False):
        self.cr.execute(
            "INSERT INTO ir_module_module (name, state, auto_install)"
            " VALUES (%s, %s, %s) RETURNING id",
            (self.PREFIX + name, state, auto_install),
        )
        return self.cr.fetchone()[0]

    def _add_dep(self, module_id, dep_name, required):
        self.cr.execute(
            "INSERT INTO ir_module_module_dependency"
            " (module_id, name, auto_install_required) VALUES (%s, %s, %s)",
            (module_id, self.PREFIX + dep_name, required),
        )

    def _fixture_rows(self, rows):
        return {name for (name,) in rows if name.startswith(self.PREFIX)}

    def test_candidate_selection(self):
        self._add_module("marked_dep", "to install")
        self._add_module("unmarked_dep", "uninstalled")
        self._add_module("uninst_dep", "uninstallable")

        ok = self._add_module("cand_ok", "uninstalled", auto_install=True)
        self._add_dep(ok, "marked_dep", required=True)

        blocked_req = self._add_module(
            "cand_blocked_required", "uninstalled", auto_install=True
        )
        self._add_dep(blocked_req, "unmarked_dep", required=True)

        blocked_missing = self._add_module(
            "cand_blocked_missing", "uninstalled", auto_install=True
        )
        self._add_dep(blocked_missing, "marked_dep", required=True)
        self._add_dep(blocked_missing, "no_such_module", required=False)

        blocked_uninst = self._add_module(
            "cand_blocked_uninst", "uninstalled", auto_install=True
        )
        self._add_dep(blocked_uninst, "marked_dep", required=True)
        self._add_dep(blocked_uninst, "uninst_dep", required=False)

        self.cr.execute(_AUTO_INSTALL_CANDIDATES_QUERY)
        selected = self._fixture_rows(self.cr.fetchall())
        self.assertEqual(selected, {self.PREFIX + "cand_ok"})

    def test_closure_selection(self):
        self._add_module("plain_dep", "uninstalled")
        self._add_module("uninst_dep", "uninstallable")
        self._add_module("marked_dep", "to install")
        m1 = self._add_module("installing", "to install")
        self._add_dep(m1, "plain_dep", required=False)
        self._add_dep(m1, "uninst_dep", required=False)
        self._add_dep(m1, "marked_dep", required=False)

        self._add_module("plain_dep2", "uninstalled")
        m2 = self._add_module("candidate", "uninstalled")
        self._add_dep(m2, "plain_dep2", required=False)

        candidates = [self.PREFIX + "candidate"]
        self.cr.execute(_AUTO_INSTALL_CLOSURE_QUERY, [candidates, candidates])
        pulled = self._fixture_rows(self.cr.fetchall())
        # plain deps of the to-install module and of the candidate are pulled;
        # the already-marked dep is not re-marked; the uninstallable dep is
        # never marked (regression: its state used to be overwritten)
        self.assertEqual(
            pulled, {self.PREFIX + "plain_dep", self.PREFIX + "plain_dep2"}
        )


class TestCreateCategoriesCache(TransactionCase):
    """create_categories with a shared cache must resolve repeated category
    paths without touching the database again (initialize() calls it once per
    module for ~1500 modules with few distinct paths).
    """

    def test_warm_cache_short_circuits_queries(self):
        cache = {}
        cat_id = create_categories(self.cr, ["Audit Cat", "Sub"], cache)
        self.assertIsInstance(cat_id, int)
        queries_before = self.cr.sql_log_count
        again = create_categories(self.cr, ["Audit Cat", "Sub"], cache)
        self.assertEqual(again, cat_id)
        self.assertEqual(self.cr.sql_log_count, queries_before, "expected 0 queries")

    def test_without_cache_behaviour_unchanged(self):
        cat_id = create_categories(self.cr, ["Audit Cat", "Sub"])
        self.assertEqual(create_categories(self.cr, ["Audit Cat", "Sub"]), cat_id)


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
