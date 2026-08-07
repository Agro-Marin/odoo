import unittest

from odoo.libs.filesystem.which import which_files


class TestWhichFiles(unittest.TestCase):
    def test_pathext_argument_is_not_mutated(self):
        pathext = [".exe"]
        list(which_files("nonexistent_file_xyz", pathext=pathext))
        list(which_files("nonexistent_file_xyz", pathext=pathext))
        self.assertEqual(pathext, [".exe"])


if __name__ == "__main__":
    unittest.main()
