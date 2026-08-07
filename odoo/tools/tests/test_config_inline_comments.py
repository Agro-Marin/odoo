import tempfile
import textwrap
import unittest
from pathlib import Path

from odoo.tools.config import configmanager

# configparser disables inline comments by default, so `key = value ; note`
# used to parse as the literal `"value ; note"`. The comment character was a
# comment only at the start of a line, which meant a trailing note either
# corrupted a string option silently (`db_host = /tmp ; socket dir`) or made an
# int option fail to parse. Both prefixes configparser already honours at line
# start -- `#` and `;` -- now also introduce a comment after whitespace.


class TestInlineComments(unittest.TestCase):
    def _load(self, body: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            rcfile = Path(tmp) / "odoo.conf"
            rcfile.write_text(textwrap.dedent(body).lstrip())
            config = configmanager()
            config._load_file_options(str(rcfile))
            return dict(config._file_options)

    def test_semicolon_comment_is_stripped_from_a_string_option(self):
        options = self._load("""
            [options]
            db_host = /var/run/postgresql ; the socket directory
        """)
        self.assertEqual(options["db_host"], "/var/run/postgresql")

    def test_hash_comment_is_stripped_from_a_string_option(self):
        options = self._load("""
            [options]
            db_host = /var/run/postgresql # the socket directory
        """)
        self.assertEqual(options["db_host"], "/var/run/postgresql")

    def test_trailing_comment_no_longer_breaks_a_typed_option(self):
        # This is the failure that is not silent: the int parse used to see
        # "5432 ; the default" and raise.
        options = self._load("""
            [options]
            db_port = 5432 ; the default
        """)
        self.assertEqual(options["db_port"], 5432)

    def test_prefix_without_leading_whitespace_stays_part_of_the_value(self):
        # configparser only treats the prefix as a comment when whitespace
        # precedes it, so values that legitimately contain one survive.
        options = self._load("""
            [options]
            db_host = left;right#middle
        """)
        self.assertEqual(options["db_host"], "left;right#middle")

    def test_whole_line_comments_still_work(self):
        options = self._load("""
            [options]
            ; a semicolon line
            # a hash line
            db_host = localhost
        """)
        self.assertEqual(options["db_host"], "localhost")

    def test_comment_only_value_reads_as_empty(self):
        options = self._load("""
            [options]
            db_host = ; unset, use the unix socket
        """)
        self.assertEqual(options["db_host"], "")


if __name__ == "__main__":
    unittest.main()
