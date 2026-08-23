"""What `_load_file_options` swallows, and what it must not.

Reading the rc file and parsing its values were guarded by one `try`, and
`except OSError: pass` sat over both. That is right for the read -- there may be
no rc file, or it may not be readable, and neither is an error -- and wrong for
the parse: `_check_addons_path` calls `Path.iterdir()`, which raises
PermissionError on a directory it cannot read.

The consequence was not a lost option but a lost *file*. The exception broke the
loop, so every option after the offending one went unread, `_file_options` stayed
empty, and nothing was logged. Measured before the split: a three-option file
behind one unreadable addons directory loaded zero options and emitted zero
warnings, and a server started that way came up on the default port with no
database.
"""

import tempfile
import unittest
from pathlib import Path

from odoo.tools.config import configmanager


class _ConfigFileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config = configmanager()

    def write(self, name, text):
        path = self.tmp / name
        path.write_text(text)
        return path

    def load(self, path):
        self.config._load_file_options(str(path))
        return dict(self.config._file_options)


class TestUnreadableInputIsTolerated(_ConfigFileCase):
    """A file that cannot be read is not a configuration error."""

    def test_absent_file(self):
        self.assertEqual(self.load(self.tmp / "nope.conf"), {})

    def test_file_without_an_options_section(self):
        self.assertEqual(self.load(self.write("ns.conf", "[other]\nx = 1\n")), {})

    def test_unreadable_file(self):
        path = self.write("locked.conf", "[options]\nhttp_port = 1\n")
        path.chmod(0o000)
        try:
            self.assertEqual(self.load(path), {})
        finally:
            path.chmod(0o600)


class TestParseFailuresAreLoud(_ConfigFileCase):
    def test_an_ordinary_file_still_loads(self):
        loaded = self.load(
            self.write("good.conf", "[options]\nhttp_port = 9999\ndb_name = probe\n")
        )
        self.assertEqual(loaded["http_port"], 9999)

    def test_a_bad_value_raises_and_names_the_option(self):
        path = self.write("bad.conf", "[options]\nhttp_port = not-a-number\n")
        with self.assertRaises(ValueError) as caught:
            self.load(path)
        self.assertIn("http_port", str(caught.exception))

    def test_an_unreadable_addons_dir_raises_instead_of_emptying_the_file(self):
        """The regression this suite exists for.

        `addons_path` is listed first and the two options after it are plainly
        valid. Before the split, all three were silently dropped.
        """
        locked = self.tmp / "locked"
        locked.mkdir()
        (locked / "child").mkdir()
        locked.chmod(0o000)
        path = self.write(
            "perm.conf",
            f"[options]\naddons_path = {locked}\nhttp_port = 9999\ndb_name = probe\n",
        )
        try:
            with self.assertRaises(ValueError) as caught:
                self.load(path)
        finally:
            locked.chmod(0o700)
        message = str(caught.exception)
        self.assertIn("addons_path", message)
        self.assertIn(str(path), message, "the message must name the file")
        self.assertIsInstance(caught.exception.__cause__, PermissionError)


if __name__ == "__main__":
    unittest.main()
