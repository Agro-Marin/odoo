"""config.save() file mode and round-trip, and the "None" unset sentinel.

Three defects these pin, all found by audit rather than by a gate:

* save() created the file under the umask and chmod'd it afterwards.  chmod does
  not revoke an already-open descriptor, so a reader winning that race read
  admin_passwd and db_password out of the finished file.  An fd was captured in
  10 of 20 runs before the fix.
* save() only re-read the existing file when `keys` narrowed the write, so a
  full --save wrote a parser that had never seen it and dropped every section
  outside [options].
* "None" meant "unset" through the config file and the environment but not on
  the command line, where optparse calls the type checker directly.  `pg_path =
  None` unset the option while `--pg_path None` resolved to a path under the
  cwd, and the CLI had no spelling for "unset" at all.
"""

import contextlib
import io
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path

from odoo.tools.config import configmanager


def _parse(argv=(), env=None, filetext="[options]\n"):
    """A fresh configmanager over a throwaway rcfile."""
    cfg = configmanager()
    rcfile = Path(tempfile.mkdtemp(), "test.conf")
    rcfile.write_text(filetext, encoding="utf-8")
    previous = dict(os.environ)
    if env:
        os.environ.update(env)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            cfg._parse_config(["-c", str(rcfile), *argv])
    finally:
        os.environ.clear()
        os.environ.update(previous)
    return cfg


class TestSaveFileMode(unittest.TestCase):
    def test_the_config_file_is_never_group_or_world_readable(self):
        cfg = configmanager()
        rcfile = Path(tempfile.mkdtemp(), "secret.conf")
        cfg._override_options["config"] = str(rcfile)
        cfg._override_options["admin_passwd"] = "s3cret-admin"
        cfg._override_options["db_password"] = "s3cret-db"

        observed: list[int] = []
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                with contextlib.suppress(FileNotFoundError):
                    observed.append(stat.S_IMODE(rcfile.stat().st_mode))

        watcher = threading.Thread(target=watch)
        watcher.start()
        try:
            cfg.save()
        finally:
            stop.set()
            watcher.join()

        self.assertEqual(
            sorted(set(observed) | {0o600}),
            [0o600],
            "the config file holds admin_passwd and db_password; it must never "
            "exist at a mode other than 0600, not even between open() and chmod()",
        )
        self.assertEqual(stat.S_IMODE(rcfile.stat().st_mode), 0o600)

    def test_resaving_tightens_a_file_that_was_already_loose(self):
        # The opener's mode applies only on creation; a conf left at 0644 by an
        # earlier odoo, or by hand, is tightened by the fchmod.
        cfg = configmanager()
        rcfile = Path(tempfile.mkdtemp(), "loose.conf")
        rcfile.write_text("[options]\n", encoding="utf-8")
        rcfile.chmod(0o644)
        cfg._override_options["config"] = str(rcfile)
        cfg.save()
        self.assertEqual(stat.S_IMODE(rcfile.stat().st_mode), 0o600)

    def test_a_reader_cannot_capture_a_descriptor_mid_write(self):
        cfg = configmanager()
        rcfile = Path(tempfile.mkdtemp(), "secret.conf")
        cfg._override_options["config"] = str(rcfile)
        cfg._override_options["admin_passwd"] = "s3cret-admin"

        stolen: list[int] = []
        stop = threading.Event()

        def attacker():
            while not stop.is_set():
                try:
                    if stat.S_IMODE(rcfile.stat().st_mode) & 0o044:
                        stolen.append(os.open(rcfile, os.O_RDONLY))
                        return
                except FileNotFoundError:
                    pass

        thread = threading.Thread(target=attacker)
        thread.start()
        try:
            cfg.save()
        finally:
            stop.set()
            thread.join()
        for fd in stolen:
            os.close(fd)
        self.assertEqual(stolen, [], "config file was readable by others mid-write")


class TestSaveRoundTrip(unittest.TestCase):
    def test_a_full_save_keeps_sections_it_does_not_own(self):
        cfg = _parse(
            filetext="[options]\nhttp_port = 8099\n\n[queue_job]\nchannels = root:2\n"
        )
        cfg.save()
        written = Path(cfg["config"]).read_text(encoding="utf-8")
        self.assertIn("[queue_job]", written)
        self.assertIn("channels = root:2", written)

    def test_a_full_save_changes_no_option_it_read(self):
        text = "[options]\nhttp_port = 8099\ndb_maxconn = 8\n"
        cfg = _parse(filetext=text)
        cfg.save()
        cfg2 = _parse(filetext=Path(cfg["config"]).read_text(encoding="utf-8"))
        self.assertEqual(cfg2["http_port"], 8099)
        self.assertEqual(cfg2["db_maxconn"], 8)


class TestNoneSentinel(unittest.TestCase):
    def test_none_unsets_an_option_from_every_source(self):
        for label, kwargs in (
            ("command line", {"argv": ["--pg_path", "None"]}),
            ("command line, =", {"argv": ["--pg_path=None"]}),
            ("config file", {"filetext": "[options]\npg_path = None\n"}),
            ("environment", {"env": {"PGPATH": "None"}}),
        ):
            with self.subTest(source=label):
                self.assertIsNone(_parse(**kwargs)["pg_path"])

    def test_a_real_path_still_resolves(self):
        cfg = _parse(argv=["--pg_path", "/usr/bin"])
        self.assertEqual(cfg["pg_path"], "/usr/bin")

    def test_without_demo_keeps_its_own_meaning_of_none(self):
        # "None" is this type's spelling of "demo data is not restricted", which
        # predates the unset sentinel; it must not become None.
        cfg = _parse(filetext="[options]\nwithout_demo = None\n")
        self.assertIs(cfg["with_demo"], True)


if __name__ == "__main__":
    unittest.main()
