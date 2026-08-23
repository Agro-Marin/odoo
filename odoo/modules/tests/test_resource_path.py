"""`get_resource_from_path` returned a third element nobody read.

It was `(module, "/".join(parts), str(Path(*parts)))` -- the third a
POSIX-identical duplicate of the second. All ten call sites in this repo took
`[0]` or `[0:2]`, none in `enterprise`, `agromarin` or `design-themes` called it
at all, and the three that unpacked three names discarded the last. Four of the
five real consumers then rebuilt `module + "/" + relative` with
`"/".join(path_info[0:2])`, which is now `.addons_path`.
"""

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

    def test_a_file_inside_a_module_is_located(self):
        found = get_resource_from_path(str(self.root / "probe" / "views" / "a.xml"))
        self.assertEqual(found, ResourceLocation("probe", "views/a.xml"))
        self.assertEqual(found.module, "probe")
        self.assertEqual(found.relative_path, "views/a.xml")

    def test_addons_path_is_what_the_callers_used_to_rebuild(self):
        found = get_resource_from_path(str(self.root / "probe" / "views" / "a.xml"))
        self.assertEqual(found.addons_path, "probe/views/a.xml")
        self.assertEqual(found.addons_path, "/".join(found[0:2]))

    def test_a_path_outside_every_addons_path_is_not_located(self):
        self.assertIsNone(get_resource_from_path("/definitely/not/an/addon/a.xml"))

    def test_the_module_directory_itself_locates_to_an_empty_relative_path(self):
        found = get_resource_from_path(str(self.root / "probe"))
        self.assertEqual(found, ResourceLocation("probe", ""))

    def test_the_longest_matching_addons_path_wins(self):
        # sorted(__path__, key=len, reverse=True): a nested addons path must
        # win over the one that contains it, or every module under it would be
        # reported as living in the outer path's first directory component.
        nested = self.root / "nested" / "addons"
        nested.mkdir(parents=True)
        with patch.object(odoo.addons, "__path__", [str(self.root), str(nested)]):
            found = get_resource_from_path(str(nested / "probe" / "a.xml"))
        self.assertEqual(found, ResourceLocation("probe", "a.xml"))
