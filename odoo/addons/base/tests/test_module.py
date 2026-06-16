import tempfile
from pathlib import Path
from unittest.mock import patch

from odoo.modules.module import Manifest, _load_manifest
from odoo.release import major_version
from odoo.tests.common import BaseCase

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
    """Validation of the ``auto_install`` manifest key in _load_manifest.

    These branches guard against silently-misparsed manifests (a string
    becoming a set of characters, a trigger that is not a dependency).
    """

    BASE = {"author": "x", "license": "MIT"}

    def test_auto_install_string_is_rejected(self):
        # 'auto_install': 'sale' (forgot the brackets) must not become {'s','a',...}
        with self.assertRaisesRegex(TypeError, "forget.*brackets"):
            _load_manifest("m", {**self.BASE, "auto_install": "sale", "depends": ["sale"]})

    def test_auto_install_non_bool_non_collection_rejected(self):
        with self.assertRaisesRegex(TypeError, "must be a bool"):
            _load_manifest("m", {**self.BASE, "auto_install": 5, "depends": ["base"]})

    def test_auto_install_trigger_must_be_a_dependency(self):
        with self.assertRaisesRegex(AssertionError, "must be dependencies"):
            _load_manifest("m", {**self.BASE, "auto_install": ["sale"], "depends": ["base"]})

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
