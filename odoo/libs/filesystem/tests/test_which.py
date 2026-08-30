import os
import pathlib
import stat
import tempfile
import unittest

from odoo.libs.filesystem.which import which_files


class TestWhichFiles(unittest.TestCase):
    def test_pathext_argument_is_not_mutated(self):
        pathext = [".exe"]
        list(which_files("nonexistent_file_xyz", pathext=pathext))
        list(which_files("nonexistent_file_xyz", pathext=pathext))
        self.assertEqual(pathext, [".exe"])

    def test_it_finds_a_real_executable(self):
        # The exists() pre-check was dropped: access() answers on its own, and
        # asking twice was a second syscall plus a TOCTOU gap.
        with tempfile.TemporaryDirectory() as tmp:
            exe = pathlib.Path(tmp) / "runnable"
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            exe.chmod(stat.S_IRWXU)
            self.assertEqual(list(which_files("runnable", path=[tmp])), [str(exe)])

    def test_a_present_but_unexecutable_file_is_not_a_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = pathlib.Path(tmp) / "plain"
            plain.write_text("data\n", encoding="utf-8")
            plain.chmod(stat.S_IRUSR | stat.S_IWUSR)
            self.assertEqual(list(which_files("plain", path=[tmp])), [])
            self.assertEqual(
                list(which_files("plain", mode=os.F_OK, path=[tmp])), [str(plain)]
            )

    def test_a_missing_file_yields_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list(which_files("absent", path=[tmp])), [])


if __name__ == "__main__":
    unittest.main()
