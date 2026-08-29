import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from odoo.modules.module import ResourceLocation, get_resource_from_path

import odoo.addons

BaseCase = unittest.TestCase


class TestResourceLocation(BaseCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="odoo_test_resource_")
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(odoo.addons, "__path__", [self._tmp.name])
        p.start()
        self.addCleanup(p.stop)
        self.root = Path(self._tmp.name)

    def _located(self, path: str) -> ResourceLocation:
        found = get_resource_from_path(path)
        if found is None:
            self.fail(f"{path!r} resolved to no addon")
        return found

    def test_a_file_inside_a_module_is_located(self):
        found = self._located(str(self.root / "probe" / "views" / "a.xml"))
        self.assertEqual(found, ResourceLocation("probe", "views/a.xml"))
        self.assertEqual(found.module, "probe")
        self.assertEqual(found.relative_path, "views/a.xml")

    def test_addons_path_is_what_the_callers_used_to_rebuild(self):
        found = self._located(str(self.root / "probe" / "views" / "a.xml"))
        self.assertEqual(found.addons_path, "probe/views/a.xml")
        self.assertEqual(found.addons_path, "/".join(found[0:2]))

    def test_a_path_outside_every_addons_path_is_not_located(self):
        self.assertIsNone(get_resource_from_path("/definitely/not/an/addon/a.xml"))

    def test_the_module_directory_itself_locates_to_an_empty_relative_path(self):
        found = self._located(str(self.root / "probe"))
        self.assertEqual(found, ResourceLocation("probe", ""))

    def test_the_longest_matching_addons_path_wins(self):
        nested = self.root / "nested" / "addons"
        nested.mkdir(parents=True)
        with patch.object(odoo.addons, "__path__", [str(self.root), str(nested)]):
            found = get_resource_from_path(str(nested / "probe" / "a.xml"))
        self.assertEqual(found, ResourceLocation("probe", "a.xml"))
