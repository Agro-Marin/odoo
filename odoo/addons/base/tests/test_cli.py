import os
import re
import subprocess as sp
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odoo.cli import upgrade_code
from odoo.cli.command import (
    build_bootstrap_parser,
    commands,
    load_addons_commands,
    load_internal_commands,
)
from odoo.tests import BaseCase
from odoo.tools import config, file_path


class TestCommand(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.odoo_bin = Path(__file__).parents[4].resolve() / "odoo-bin"
        addons_path = config.format("addons_path", config["addons_path"])
        cls.run_args = (
            sys.executable,
            cls.odoo_bin,
            f"--addons-path={addons_path}",
        )

    def run_command(self, *args, check=True, capture_output=True, text=True, **kwargs):
        return sp.run(
            [*self.run_args, *args],
            capture_output=capture_output,
            check=check,
            text=text,
            **kwargs,
        )

    def popen_command(self, *args, capture_output=True, text=True, **kwargs):
        if capture_output:
            kwargs["stdout"] = kwargs["stderr"] = sp.PIPE
        return sp.Popen([*self.run_args, *args], text=text, **kwargs)

    def test_docstring(self):
        load_internal_commands()
        load_addons_commands()
        for name, cmd in commands.items():
            self.assertTrue(
                cmd.__doc__,
                msg=f"Command {name} needs a docstring to be displayed with 'odoo-bin help'",
            )
            self.assertFalse(
                "\n" in cmd.__doc__ or len(cmd.__doc__) > 120,
                msg=f"Command {name}'s docstring format is invalid for 'odoo-bin help'",
            )

    def test_unknown_command(self):
        for name in ("bonbon", "café"):
            with self.subTest(name):
                command_output = self.run_command(name, check=False).stderr.strip()
                self.assertEqual(
                    command_output,
                    f"Unknown command '{name}'.\nUse 'odoo-bin --help' to see the list of available commands.",
                )

    def test_help(self):
        expected = {
            "cloc",
            "db",
            "deploy",
            "help",
            "i18n",
            "module",
            "neutralize",
            "obfuscate",
            "populate",
            "scaffold",
            "server",
            "shell",
            "start",
            "upgrade_code",
        }
        for option in ("help", "-h", "--help"):
            with self.subTest(option=option):
                actual = set()
                for line in self.run_command(option).stdout.splitlines():
                    if line.startswith("   ") and (
                        result := re.search(r"    (\w+)\s+(\w.*)$", line)
                    ):
                        actual.add(result.groups()[0])
                self.assertGreaterEqual(
                    actual,
                    expected,
                    msg="Help is not showing required commands",
                )

    def test_help_covers_all_cli_modules(self):
        """Guard against the test_help expected set drifting behind cli/.

        Every ``cli/*.py`` module that declares a ``class X(Command)`` must be
        exposed by ``odoo-bin help``.
        """
        from pathlib import Path

        cli_dir = Path(__file__).parents[3] / "cli"
        declared = set()
        for py in cli_dir.glob("*.py"):
            if py.stem.startswith("_"):
                continue
            if re.search(r"class\s+\w+\(Command\)", py.read_text()):
                declared.add(py.stem)

        actual = set()
        for line in self.run_command("--help").stdout.splitlines():
            if line.startswith("   ") and (
                result := re.search(r"    (\w+)\s+(\w.*)$", line)
            ):
                actual.add(result.groups()[0])
        missing = declared - actual
        self.assertFalse(
            missing,
            msg=f"cli/ modules missing from `odoo-bin help`: {sorted(missing)}",
        )

    def test_help_subcommand(self):
        """Just execute the help for each internal sub-command"""
        load_internal_commands()
        for name in commands:
            with self.subTest(command=name):
                self.run_command(name, "--help", timeout=10)

    def test_upgrade_code_example(self):
        proc = self.run_command(
            "upgrade_code", "--script", "17.5-00-example", "--dry-run"
        )
        self.assertFalse(
            proc.stdout,
            "there should be no file modified by the example script",
        )
        self.assertFalse(proc.stderr)

    def test_upgrade_code_help(self):
        proc = self.run_command("upgrade_code", "--help")
        self.assertIn("usage: ", proc.stdout)
        self.assertIn("Rewrite the entire source code", proc.stdout)
        self.assertFalse(proc.stderr)

    def test_upgrade_code_standalone(self):
        proc = sp.run(
            [sys.executable, upgrade_code.__file__, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("usage: ", proc.stdout)
        self.assertIn("Rewrite the entire source code", proc.stdout)
        # Regression: the stub Command.parser used to rebuild a fresh
        # ArgumentParser on every access, so none of the real flags were
        # registered on the parser that parse_args() eventually used.
        # Asserting flag visibility in --help catches that class of bug.
        for flag in (
            "--script",
            "--from",
            "--to",
            "--glob",
            "--dry-run",
            "--addons-path",
        ):
            self.assertIn(
                flag,
                proc.stdout,
                msg=f"standalone --help missing {flag}",
            )
        self.assertFalse(proc.stderr)

    def test_upgrade_code_standalone_runs(self):
        """Standalone upgrade_code.py must run a real script, not just --help."""
        proc = sp.run(
            [
                sys.executable,
                upgrade_code.__file__,
                "--script",
                "17.5-00-example",
                "--dry-run",
                "--addons-path",
                str(Path(__file__).parents[4] / "odoo/addons"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"standalone --script failed: stderr={proc.stderr[:200]!r}",
        )

    def test_upgrade_code_rejects_inverted_range(self):
        proc = self.run_command(
            "upgrade_code",
            "--from",
            "19.0",
            "--to",
            "17.0",
            "--glob",
            "no/such/*.py",
            "--dry-run",
            check=False,
        )
        self.assertNotEqual(
            proc.returncode,
            0,
            msg="upgrade_code should reject --to < --from",
        )

    def test_i18n_loadlang_requires_language(self):
        """loadlang without -l must be rejected by argparse, not silently
        no-op (Domain coerces None → False, so an empty recordset would
        iterate zero times and the command would report success)."""
        proc = self.run_command(
            "i18n",
            "loadlang",
            "-d",
            "no_such_db",
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        # argparse errors should include 'required' or the flag name in stderr
        msg = proc.stderr.lower()
        self.assertTrue(
            "required" in msg or "-l" in msg or "--languages" in msg,
            msg=f"stderr did not mention the missing -l flag: {proc.stderr!r}",
        )

    def test_scaffold_help_tolerant_of_missing_templates(self):
        """scaffold --help must survive a missing templates/ directory.

        Behavioral, not source-grep: two eager probes used to kill --help —
        the iterdir() in __init__ (epilog) and the ``default=Template(...)``
        constructed at add_argument time. The default is now a plain string
        that argparse converts only after --help has been handled.
        """
        import contextlib
        import io

        from odoo.cli import scaffold as scaffold_mod

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no_such_templates"
            cwd = Path.cwd()
            os.chdir(tmp)  # no ./default dir to fall back on
            buf = io.StringIO()
            try:
                with mock.patch.object(
                    scaffold_mod,
                    "_builtins_dir",
                    missing.joinpath,
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        with contextlib.redirect_stdout(buf):
                            scaffold_mod.Scaffold().run(["--help"])
            finally:
                os.chdir(cwd)
        self.assertIn(ctx.exception.code, (0, None), msg="--help must exit 0")
        self.assertIn("usage:", buf.getvalue())

    def test_scaffold_invalid_template_is_usage_error(self):
        """`scaffold -t bogus` must be a standard argparse usage error
        (usage line, exit 2), not a bare sys.exit(1) message — Template is
        an argparse `type` callable and must raise ArgumentTypeError."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_command(
                "scaffold", "-t", "bogus_template", "mymod", tmp, check=False
            )
        self.assertEqual(proc.returncode, 2, msg=proc.stderr)
        self.assertIn("usage:", proc.stderr)
        self.assertIn("not a valid module template", proc.stderr)

    def test_db_load_validates_before_drop(self):
        """`db load --force` must NOT drop the target before the dump is
        fetched and recognised as a zip — a 404 or a stray .sql file used
        to destroy the existing database and then abort."""
        from odoo.cli import db as dbmod

        calls = []
        with tempfile.NamedTemporaryFile(suffix=".sql") as tmp:
            tmp.write(b"not a zip")
            tmp.flush()
            ns = mock.Mock(
                database="mydb", dump_file=tmp.name, force=True, neutralize=False
            )
            with (
                mock.patch.object(dbmod, "exp_db_exist", lambda db: True),
                mock.patch.object(
                    dbmod, "_drop_database", lambda db: calls.append("drop") or True
                ),
                mock.patch.object(
                    dbmod, "restore_db", lambda **kw: calls.append("restore")
                ),
            ):
                with self.assertRaises(SystemExit):
                    dbmod.Db().load(ns)
        self.assertEqual(calls, [], msg=f"target dropped before validation: {calls}")

    def test_db_load_force_drops_after_validation(self):
        """The happy path must still work: valid zip -> drop -> restore.

        ``_drop_if_exists`` calls ``_drop_database`` directly, not ``exp_drop``
        (t23746/EO7.9.11, A3 HIGH) — the CLI is local trusted tooling and must
        not be silently blocked by ``exp_drop``'s exposed-databases allowlist
        gate, which exists to protect the RPC entry point instead. Mock the
        function actually called, not the RPC-facing one."""
        import zipfile as zipfile_mod

        from odoo.cli import db as dbmod

        calls = []
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            with zipfile_mod.ZipFile(tmp, "w") as z:
                z.writestr("dump.sql", "fake")
            tmp.flush()
            ns = mock.Mock(
                database="mydb", dump_file=tmp.name, force=True, neutralize=False
            )
            with (
                mock.patch.object(dbmod, "exp_db_exist", lambda db: True),
                mock.patch.object(
                    dbmod, "_drop_database", lambda db: calls.append("drop") or True
                ),
                mock.patch.object(
                    dbmod, "restore_db", lambda **kw: calls.append("restore")
                ),
            ):
                dbmod.Db().load(ns)
        self.assertEqual(calls, ["drop", "restore"])

    def test_db_duplicate_checks_source_before_drop(self):
        """`db duplicate missing_src tgt --force` must abort before the
        target is dropped — the source check used to happen inside
        _duplicate_database, after the drop."""
        from odoo.cli import db as dbmod

        calls = []
        ns = mock.Mock(source="missing_src", target="tgt", force=True, neutralize=False)
        with (
            mock.patch.object(dbmod, "exp_db_exist", lambda db: db != "missing_src"),
            mock.patch.object(
                dbmod, "_drop_database", lambda db: calls.append("drop") or True
            ),
            mock.patch.object(
                dbmod,
                "_duplicate_database",
                lambda *a, **k: calls.append("duplicate"),
            ),
        ):
            with self.assertRaises(SystemExit) as ctx:
                dbmod.Db().duplicate(ns)
        self.assertEqual(calls, [])
        self.assertIn("missing_src", str(ctx.exception.code))

    def test_db_drop_calls_drop_database_not_exp_drop(self):
        """`db drop <name>` must call `_drop_database` (local trusted CLI),
        not `exp_drop` (RPC-gated, refuses anything outside the exposed
        allowlist) — the two must stay consistent with `load/duplicate/rename
        --force`, which already route through `_drop_database`."""
        from odoo.cli import db as dbmod

        with mock.patch.object(dbmod, "_drop_database", return_value=True) as drop_mock:
            dbmod.Db().drop(mock.Mock(database="mydb"))
        drop_mock.assert_called_once_with("mydb")

    def test_db_drop_reports_missing_database(self):
        """The happy-path exit message must still fire when the database is
        genuinely absent (`_drop_database` returns False)."""
        from odoo.cli import db as dbmod

        with mock.patch.object(dbmod, "_drop_database", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                dbmod.Db().drop(mock.Mock(database="missing"))
        self.assertIn("missing", str(ctx.exception.code))

    def test_db_connection_flag_map_covers_all_flags(self):
        """The dest->flag map is derived from _CONNECTION_FLAGS; every
        declared flag must round-trip into config_args. The previous
        prefix-based filter (db_*/pg_* + a passthrough tuple) only matched
        the current flags by coincidence."""
        from odoo.cli import db as dbmod

        dest_flags = dbmod.Db._connection_dest_flags()
        for flags in dbmod.Db._CONNECTION_FLAGS:
            long_flag = flags[-1]
            dest = long_flag.lstrip("-").replace("-", "_")
            self.assertIn(dest, dest_flags)
            self.assertEqual(dest_flags[dest], long_flag)

    def test_obfuscate_select_fields(self):
        """The --fields/--file/--exclude/--no-default-fields/--allfields
        interplay, unit-tested without a database."""
        import argparse

        from odoo.cli.obfuscate import DEFAULT_FIELDS, _select_fields

        base = {
            "fields": None,
            "file": None,
            "exclude": None,
            "allfields": False,
            "no_default_fields": False,
        }
        ns = lambda **kw: argparse.Namespace(**{**base, **kw})  # noqa: E731

        self.assertEqual(_select_fields(ns()), list(DEFAULT_FIELDS))
        self.assertEqual(
            _select_fields(ns(fields="t.c")),
            list(DEFAULT_FIELDS) + [("t", "c")],
            msg="--fields appends to the built-in list",
        )
        self.assertEqual(
            _select_fields(ns(fields="t.c", no_default_fields=True)),
            [("t", "c")],
            msg="--no-default-fields restricts to the manual selection",
        )
        excluded = _select_fields(ns(exclude="res_partner.name"))
        self.assertNotIn(("res_partner", "name"), excluded)
        self.assertEqual(len(excluded), len(DEFAULT_FIELDS) - 1)
        self.assertEqual(
            _select_fields(ns(fields="t.c", allfields=True)),
            list(DEFAULT_FIELDS),
            msg="--allfields ignores manual selection (expanded later)",
        )
        with self.assertRaises(ValueError):
            _select_fields(ns(fields="no_dot_here"))

    def test_populate_model_factors(self):
        """Factor/model mapping: propagation, surplus tolerance, int check."""
        from odoo.cli.populate import _parse_model_factors

        errors = []
        self.assertEqual(
            _parse_model_factors("1,2,3,4", "a,b", errors.append),
            {"a": 1, "b": 2},
        )
        self.assertEqual(
            _parse_model_factors("7", "a,b,c", errors.append),
            {"a": 7, "b": 7, "c": 7},
        )
        self.assertFalse(errors)
        _parse_model_factors("x", "a", errors.append)
        self.assertTrue(errors and "--factors" in errors[0])

    def test_deploy_requests_have_timeouts(self):
        """requests has no default timeout — a stuck server would hang the
        deploy forever. Both the login GET and the upload POST must pass an
        explicit timeout."""
        from odoo.cli.deploy import Deploy

        deploy = Deploy()
        deploy.session = mock.MagicMock()
        deploy.session.post.return_value = mock.MagicMock(status_code=200, text="ok")
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            deploy.login_upload_module(
                module_file=tmp.name,
                url="http://localhost:8069",
                login="admin",
                password="admin",
                db="",
            )
        self.assertIsNotNone(deploy.session.get.call_args.kwargs.get("timeout"))
        self.assertIsNotNone(deploy.session.post.call_args.kwargs.get("timeout"))

    def test_deploy_zip_compressed_and_pruned(self):
        """The deploy zip must deflate its entries (ZIP_STORED uploads are
        several-fold larger) and never include excluded trees, which are
        pruned during the walk rather than filtered file-by-file."""
        import zipfile as zipfile_mod

        from odoo.cli.deploy import Deploy

        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "mymod"
            (mod / "node_modules" / "pkg").mkdir(parents=True)
            (mod / "node_modules" / "pkg" / "index.js").write_text("x" * 4096)
            (mod / "__manifest__.py").write_text("{'name': 'mymod'}\n" * 64)
            zpath = Deploy().zip_module(mod)
            try:
                with zipfile_mod.ZipFile(zpath) as z:
                    infos = {i.filename: i for i in z.infolist()}
            finally:
                Path(zpath).unlink()
        self.assertFalse(
            [n for n in infos if "node_modules" in n],
            msg=f"excluded tree leaked into zip: {list(infos)}",
        )
        manifest = next(i for n, i in infos.items() if n.endswith("__manifest__.py"))
        self.assertEqual(manifest.compress_type, zipfile_mod.ZIP_DEFLATED)

    def test_deploy_zip_keeps_file_named_like_excluded_dir(self):
        """A regular module file whose basename equals an excluded *directory*
        name (e.g. ``build``, ``dist``) must still ship. _should_skip tests
        only the parent path components, never the file's own basename — the
        earlier form dropped such files silently."""
        import zipfile as zipfile_mod

        from odoo.cli.deploy import Deploy

        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "mymod"
            mod.mkdir()
            (mod / "__manifest__.py").write_text("{'name': 'mymod'}\n")
            (mod / "build").write_text("legit content")  # file, not a dir
            (mod / "node_modules").mkdir()
            (mod / "node_modules" / "junk.js").write_text("junk")
            zpath = Deploy().zip_module(mod)
            try:
                with zipfile_mod.ZipFile(zpath) as z:
                    names = {n.split("/", 1)[1] for n in z.namelist()}
            finally:
                Path(zpath).unlink()
        self.assertIn("build", names, msg="file named like an excluded dir was dropped")
        self.assertNotIn(
            "node_modules/junk.js", names, msg="excluded dir tree leaked into zip"
        )

    def test_start_explicit_path_wins_over_venv(self):
        """`start -p .` must use the cwd even inside a virtualenv: the
        $VIRTUAL_ENV fallback applies only when -p was omitted (the old
        default='.' made the explicit form indistinguishable)."""
        from odoo.cli import start as start_mod

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            (proj / "mymodule").mkdir(parents=True)
            (proj / "mymodule" / "__manifest__.py").write_text("{'name': 'x'}\n")
            captured = {}
            cwd = Path.cwd()
            os.chdir(proj)
            try:
                with (
                    mock.patch.object(
                        start_mod,
                        "main",
                        lambda cmdargs: captured.update(args=list(cmdargs)),
                    ),
                    mock.patch.object(
                        start_mod,
                        "_create_empty_database",
                        mock.Mock(side_effect=start_mod.DatabaseExists()),
                    ),
                    mock.patch.dict(os.environ, {"VIRTUAL_ENV": tmp}),
                ):
                    start_mod.Start().run(["-p", ".", "-d", "mydb"])
            finally:
                os.chdir(cwd)
            flags = [a for a in captured["args"] if a.startswith("--addons-path=")]
            self.assertEqual(len(flags), 1, msg=f"args: {captured['args']}")
            paths = flags[0].removeprefix("--addons-path=").split(",")
            self.assertIn(str(proj.resolve()), paths)
            self.assertNotIn(tmp, paths, msg="venv path overrode explicit -p .")

    def test_db_init_accepts_config_after_subcommand(self):
        """`db init mydb -c cfg` must work, matching `module install` UX."""
        proc = self.run_command(
            "db",
            "init",
            "nonexistent_db",
            "-c",
            "/nonexistent/path.conf",
            check=False,
        )
        # The command may still fail (config missing), but argparse must not
        # complain about 'unrecognized arguments' for -c.
        self.assertNotIn("unrecognized arguments", proc.stderr)

    def test_db_connection_flags_before_subcommand_survive(self):
        """`db -c cfg --db_host h drop mydb` must NOT drop the connection flags.

        argparse copies the subparser namespace back onto the parent, so a
        subparser flag with an ordinary None default used to clobber a value
        supplied before the subcommand. With default=SUPPRESS on the
        subparser copies, the before-form value must survive into config_args
        (otherwise `db -c prod.conf drop x` would silently target the local
        default server). Drives the real Db.run, stubbing only the side
        effects.
        """
        from odoo.cli import db as dbmod

        captured = {}

        def fake_parse_config(args, **kwargs):
            captured["config_args"] = list(args)

        with (
            mock.patch.object(dbmod.config, "parse_config", fake_parse_config),
            mock.patch.object(dbmod, "report_configuration", lambda: None),
            mock.patch.object(dbmod.Db, "drop", lambda self, args: None),
        ):
            dbmod.Db().run(
                ["-c", "/tmp/before.conf", "--db_host", "prodhost", "drop", "mydb"]
            )

        config_args = captured.get("config_args", [])
        self.assertIn("/tmp/before.conf", config_args, msg=f"-c lost: {config_args}")
        self.assertIn("prodhost", config_args, msg=f"--db_host lost: {config_args}")

    def test_deploy_db_omitted_does_not_crash(self):
        """`deploy <path>` with no --db must not crash on quote(None).

        The encode step ran before any network call, so quote(None) raised
        TypeError and the generic handler turned it into a cryptic message.
        Now --db defaults to "" and the encode is None-tolerant.
        """
        from odoo.cli.deploy import Deploy

        deploy = Deploy()
        # Stub the HTTP session so we exercise only the db-encoding path.
        deploy.session = mock.MagicMock()
        deploy.session.post.return_value = mock.MagicMock(status_code=200, text="ok")
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            # db=None is the worst case (worse than the new "" default); it must
            # not raise TypeError from urllib.parse.quote.
            try:
                deploy.login_upload_module(
                    module_file=tmp.name,
                    url="http://localhost:8069",
                    login="admin",
                    password="admin",
                    db=None,
                )
            except TypeError as exc:  # pragma: no cover - regression guard
                self.fail(f"login_upload_module crashed on db=None: {exc}")
        self.assertTrue(deploy.session.get.called)

    def test_bootstrap_parser_rejects_abbreviation(self):
        """The pre-dispatch parser must not abbreviate --addons-path.

        With allow_abbrev (the argparse default) `--addons=/y` was silently
        swallowed as the addons path; the real flag must still parse.
        """
        parser = build_bootstrap_parser()
        ns, rest = parser.parse_known_args(["server", "--addons=/y"])
        self.assertIsNone(ns.addons_path)
        self.assertIn("--addons=/y", rest)
        ns2, _ = parser.parse_known_args(["server", "--addons-path=/y"])
        self.assertEqual(ns2.addons_path, "/y")

    def test_upgrade_code_rejects_out_of_tree_script(self):
        """`--script ../evil` must be rejected when it resolves outside UPGRADE.

        Path.relative_to is lexical and does not raise for `..`; the guard now
        resolves both sides. Point UPGRADE at a temp dir and plant a sibling
        file reachable via `../`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upgrade_dir = root / "upgrade_code"
            upgrade_dir.mkdir()
            evil = root / "evil.py"
            evil.write_text("def upgrade(fm):\n    pass\n")
            with mock.patch.object(upgrade_code, "UPGRADE", upgrade_dir):
                with self.assertRaises(FileNotFoundError) as ctx:
                    upgrade_code.migrate(
                        addons_path=[tmp], glob="*.py", script="../evil"
                    )
            self.assertIn("outside", str(ctx.exception))

    def test_discovery_survives_broken_addon_cli(self):
        """A SyntaxError in one addon's cli/*.py must not break discovery.

        `odoo-bin help` loads every addon's cli file; one bad file previously
        propagated and killed the whole listing.
        """
        from odoo.cli import command as cmd

        import odoo.addons

        with tempfile.TemporaryDirectory() as tmp:
            cli_dir = Path(tmp) / "brokenmod" / "cli"
            cli_dir.mkdir(parents=True)
            # Missing colon -> SyntaxError at import (not an ImportError).
            (cli_dir / "brokencmd.py").write_text(
                "from odoo.cli import Command\n"
                "class Brokencmd(Command)\n"
                "    def run(self, args): pass\n"
            )
            # Patch the addons search path to just our temp dir (a plain list,
            # so no _NamespacePath mutation) and neuter initialize_sys_path so
            # it does not rebuild the path from config.
            with (
                mock.patch.object(odoo.addons, "__path__", [tmp]),
                mock.patch.object(cmd, "initialize_sys_path", lambda: None),
            ):
                try:
                    load_addons_commands()  # the all-discovery path help uses
                except SyntaxError:  # pragma: no cover - regression guard
                    self.fail("a broken addon cli file broke command discovery")
            self.assertNotIn("brokencmd", commands)

    def test_deploy_local_host_detection(self):
        """deploy.py must distinguish localhost forms from look-alike hosts."""
        from odoo.cli.deploy import _LOCAL_HOSTS

        self.assertIn("localhost", _LOCAL_HOSTS)
        self.assertIn("127.0.0.1", _LOCAL_HOSTS)
        self.assertIn("0.0.0.0", _LOCAL_HOSTS)
        self.assertIn("::1", _LOCAL_HOSTS)
        # The substring trap that the previous startswith() implementation
        # fell into:
        self.assertNotIn("localhost.evil.com", _LOCAL_HOSTS)
        self.assertNotIn("127.0.0.1.evil.com", _LOCAL_HOSTS)

    def test_deploy_excluded_paths(self):
        """The deploy zip must skip VCS, IDE, and build noise."""
        from odoo.cli.deploy import (
            EXCLUDED_DIR_NAMES,
            EXCLUDED_FILE_NAMES,
            EXCLUDED_SUFFIXES,
        )

        for name in (
            ".git",
            ".hg",
            "__pycache__",
            "node_modules",
            ".idea",
            ".vscode",
            "dist",
            "build",
        ):
            self.assertIn(name, EXCLUDED_DIR_NAMES)
        for ext in (".pyc", ".pyo", ".swp", ".bak"):
            self.assertIn(ext, EXCLUDED_SUFFIXES)
        # By NAME, not suffix: Path('.DS_Store').suffix == '' (dotfile), so a
        # suffix-based exclusion never fired and the junk file shipped.
        self.assertIn(".DS_Store", EXCLUDED_FILE_NAMES)

    def test_start_db_filter_escapes_regex(self):
        """start.py must escape regex meta-characters in db_name when
        building --db-filter, otherwise an unrelated db like 'myXprod-db'
        would match a filter built from 'my.prod-db'."""
        src = (Path(__file__).parents[3] / "cli/start.py").read_text()
        self.assertIn(
            "re.escape(args.db_name)",
            src,
            msg="--db-filter built without re.escape — regex meta-chars in "
            "db names would let unrelated databases through.",
        )

    def test_db_filter_database_constrains_permissive_dbfilter(self):
        """`--database` must further constrain a `--db-filter`, not be overridden.

        With a permissive dbfilter (``.*``) and several databases on the host, a
        `-d X` run must still resolve to exactly X — otherwise db_monodb is
        ambiguous and every db-bound route 404s (this broke HttpCase tests).
        """
        from odoo.http import db_filter

        dbs = ["alpha", "beta", "prod", "test_db"]
        with mock.patch.dict(
            config.options, {"dbfilter": ".*", "db_name": ["test_db"]}
        ):
            self.assertEqual(db_filter(dbs, host="localhost"), ["test_db"])
        # dbfilter alone still filters by pattern only
        with mock.patch.dict(config.options, {"dbfilter": "^al", "db_name": []}):
            self.assertEqual(db_filter(dbs, host="localhost"), ["alpha"])
        # db_name alone still intersects (sorted)
        with mock.patch.dict(
            config.options, {"dbfilter": "", "db_name": ["beta", "alpha"]}
        ):
            self.assertEqual(db_filter(dbs, host="localhost"), ["alpha", "beta"])
        # both set: intersection of the two
        with mock.patch.dict(
            config.options, {"dbfilter": "^(alpha|prod)$", "db_name": ["prod", "beta"]}
        ):
            self.assertEqual(db_filter(dbs, host="localhost"), ["prod"])

    def test_obfuscate_excludes_ir_tables_via_starts_with(self):
        """Source-level guard: get_all_fields must filter ir_* tables via
        starts_with, not LIKE — the latter treats '_' as a wildcard and
        would also exclude tables like 'irrelevant' or 'iru_custom'."""
        src = (Path(__file__).parents[3] / "cli/obfuscate.py").read_text()
        # Strip Python comments so docstrings/explanations don't trip the
        # 'LIKE' check.
        non_comment = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
        self.assertIn("starts_with(table_name, 'ir_')", non_comment)
        self.assertNotIn("LIKE 'ir_%'", non_comment)

    def test_dotted_command_name_no_traceback(self):
        """A dotted typo like `odoo-bin db.init` must produce the standard
        Unknown-command message, not a ModuleNotFoundError traceback.

        find_command's suppress guard compares e.name to the expected module
        name; for 'x.y' the import machinery reports the *parent* module
        ('odoo.cli.x'), so the guard re-raised. Names are now validated
        before any import attempt."""
        for name in ("db.init", "x.y", ".", ".."):
            with self.subTest(name=name):
                proc = self.run_command(name, check=False)
                self.assertIn("Unknown command", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)

    def test_start_merges_bootstrap_addons_path(self):
        """`odoo-bin start --addons-path=X` must not lose X.

        The dispatcher's bootstrap parser strips --addons-path from any argv
        position, so start.py never sees it in cmdargs and used to append
        the bare auto-detected project path — which the second config parse
        then took as a *replacement* for X. start.py must merge the
        bootstrap value (exposed as odoo.cli.BOOTSTRAP_ADDONS_PATH) with the
        project path, user paths first."""
        import odoo.cli
        from odoo.cli import start as start_mod

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            (proj / "mymodule").mkdir(parents=True)
            (proj / "mymodule" / "__manifest__.py").write_text("{'name': 'x'}\n")
            captured = {}
            with (
                mock.patch.object(
                    start_mod,
                    "main",
                    lambda cmdargs: captured.update(args=list(cmdargs)),
                ),
                mock.patch.object(
                    start_mod,
                    "_create_empty_database",
                    mock.Mock(side_effect=start_mod.DatabaseExists()),
                ),
                mock.patch.object(odoo.cli, "BOOTSTRAP_ADDONS_PATH", "/custom/addons"),
            ):
                start_mod.Start().run(["--path", str(proj), "-d", "mydb"])
            flags = [a for a in captured["args"] if a.startswith("--addons-path=")]
            self.assertEqual(len(flags), 1, msg=f"args: {captured['args']}")
            paths = flags[0].removeprefix("--addons-path=").split(",")
            self.assertEqual(
                paths[0], "/custom/addons", msg="user-supplied paths must come first"
            )
            self.assertIn(str(proj.resolve()), paths)

    def test_start_filters_concatenated_path_flag(self):
        """`start -pX` (argparse's concatenated short form) must be removed
        from the args forwarded to the server: the server parser maps -p to
        --http-port, so a leaked -pX is misparsed (a numeric X would even
        silently change the listening port)."""
        from odoo.cli import start as start_mod

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            (proj / "mymodule").mkdir(parents=True)
            (proj / "mymodule" / "__manifest__.py").write_text("{'name': 'x'}\n")
            captured = {}
            with (
                mock.patch.object(
                    start_mod,
                    "main",
                    lambda cmdargs: captured.update(args=list(cmdargs)),
                ),
                mock.patch.object(
                    start_mod,
                    "_create_empty_database",
                    mock.Mock(side_effect=start_mod.DatabaseExists()),
                ),
            ):
                start_mod.Start().run([f"-p{proj}", "-d", "mydb"])
            leaked = [
                a
                for a in captured["args"]
                if a.startswith("-p") and not a.startswith("--")
            ]
            self.assertFalse(leaked, msg=f"args: {captured['args']}")

    def test_deploy_zip_skips_symlinks(self):
        """The deploy zip must not embed the content of symlinked files —
        a link pointing outside the module would leak the target's bytes
        into the upload."""
        import zipfile

        from odoo.cli.deploy import Deploy

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "secret.txt").write_text("TOPSECRET")
            mod = tmp_path / "mymod"
            mod.mkdir()
            (mod / "__manifest__.py").write_text("{'name': 'mymod'}\n")
            (mod / "leak.txt").symlink_to(tmp_path / "secret.txt")
            zpath = Deploy().zip_module(mod)
            try:
                with zipfile.ZipFile(zpath) as z:
                    names = z.namelist()
            finally:
                Path(zpath).unlink()
            self.assertTrue(any(n.endswith("__manifest__.py") for n in names))
            self.assertFalse(
                any(n.endswith("leak.txt") for n in names),
                msg=f"symlink leaked into zip: {names}",
            )

    def test_command_register_optout(self):
        """`class Base(Command, register=False)` must be allowed as an
        abstract helper base: not registered, exempt from the name/module
        and run-override checks. Concrete subclasses are still validated."""
        from odoo.cli.command import Command, commands

        before = dict(commands)
        helper = type("HelperBase", (Command,), {}, register=False)
        self.assertEqual(commands, before, msg="opt-out base must not register")
        self.assertIsNone(helper.name)
        # a concrete subclass goes through the usual validation (here it
        # fails the module-name check, proving validation still applies)
        with self.assertRaises(ValueError):
            type("Concrete", (helper,), {"run": lambda self, args: None})
        self.assertEqual(commands, before)

    def test_db_helpers_live_on_databasecommand_not_base(self):
        """The -c/-d plumbing belongs to DatabaseCommand, not the universal
        Command base. Every caller of add_config_arguments/require_single_database
        is a DatabaseCommand; db-free commands (deploy/scaffold/help) must not
        inherit database helpers they never use. Pins the separation so the
        helpers are not re-hoisted onto the base."""
        from odoo.cli.command import Command, DatabaseCommand

        for meth in (
            "add_config_arguments",
            "bootstrap_config",
            "require_single_database",
        ):
            self.assertIn(
                meth,
                vars(DatabaseCommand),
                msg=f"{meth} must be defined on DatabaseCommand",
            )
            self.assertNotIn(
                meth,
                vars(Command),
                msg=f"{meth} must not be defined on the base Command",
            )

    def test_obfuscate_update_has_where_guard(self):
        """convert_table must guard its UPDATE with a WHERE clause: an
        unguarded UPDATE physically rewrites every tuple even when the
        idempotency CASE returns the value unchanged (full-table I/O and
        bloat on re-runs)."""
        from odoo.cli.obfuscate import Obfuscate

        for unobfuscate, marker in (
            (False, "IS NOT NULL AND NOT starts_with"),
            (True, "WHERE starts_with"),
        ):
            with self.subTest(unobfuscate=unobfuscate):
                ob = Obfuscate()
                ob.cr = mock.MagicMock()
                ob.cr.rowcount = 1
                ob.cr.fetchone.return_value = ("varchar",)
                ob.convert_table(
                    "res_partner", ["name"], "pwd", unobfuscate=unobfuscate
                )
                update_sql = ob.cr.execute.call_args[0][0].code
                self.assertIn("UPDATE", update_sql)
                self.assertIn("WHERE", update_sql)
                self.assertIn(marker, update_sql)

    def test_obfuscate_prefetches_field_kinds(self):
        """After _prefetch_field_kinds, check_field is a dict lookup with no
        per-field information_schema round-trip, and returns exactly what the
        per-field probe would (string/json for supported types, None for
        unsupported or absent columns). Guards the explicit --fields path from
        regressing to one catalog query per field, charged twice (the
        validation pass in run() plus convert_table)."""
        from odoo.cli.obfuscate import Obfuscate

        ob = Obfuscate()
        executed = []

        class FakeCur:
            def execute(self, query, params=None):
                executed.append(params)

            def fetchall(self):
                # text/varchar/jsonb are kept; an unsupported type is dropped.
                return [
                    ("res_partner", "name", "varchar"),
                    ("res_partner", "email", "varchar"),
                    ("res_partner", "extra", "jsonb"),
                    ("res_partner", "active", "bool"),
                ]

        ob.cr = FakeCur()
        ob._prefetch_field_kinds({"res_partner"})
        self.assertEqual(len(executed), 1, msg="prefetch must be a single query")
        self.assertEqual(
            executed[0], [["res_partner"]], msg="tables passed via ANY(%s)"
        )

        before = len(executed)
        self.assertEqual(ob.check_field("res_partner", "name"), "string")
        self.assertEqual(ob.check_field("res_partner", "extra"), "json")
        self.assertIsNone(ob.check_field("res_partner", "active"), msg="non-text type")
        self.assertIsNone(ob.check_field("res_partner", "ghost"), msg="absent column")
        self.assertEqual(
            len(executed),
            before,
            msg="check_field issued a catalog query despite the prefetch",
        )

    @unittest.skipIf(os.name != "posix", "`os.openpty` only available on POSIX systems")
    def test_shell(self):

        main, child = os.openpty()

        shell = self.popen_command(
            "shell",
            "--shell-interface=python",
            "--shell-file",
            file_path("base/tests/shell_file.txt"),
            stdin=main,
            close_fds=True,
        )
        os.close(main)
        with os.fdopen(child, "w", encoding="utf-8") as stdin_file:
            stdin_file.write("print(message)\nexit()\n")
        with shell:
            self.assertFalse(shell.wait(), "exited with a non 0 code")

            # we skip local variables as they differ based on configuration (e.g.: if a database is specified or not)
            lines = [
                line
                for line in shell.stdout.read().splitlines()
                if line.startswith(">>>")
            ]
            self.assertEqual(lines, [">>> Hello from Python!", ">>> "])

    def test_databasecommand_preserves_bootstrap_addons_path(self):
        """`module install --addons-path=X` must not silently lose X.

        command.main strips --addons-path and feeds it to config in a FIRST
        parse; DatabaseCommand.bootstrap_config then runs a SECOND parse
        forwarding only -c/-d. Modules are found only because config specially
        preserves addons_path across that second parse; dropping that
        preservation would make commands resolve zero modules with no error.
        Pinned on an isolated configmanager so the global singleton is untouched.
        """
        from odoo.tools.config import configmanager

        with tempfile.TemporaryDirectory() as ad, tempfile.TemporaryDirectory() as dd:
            module = Path(ad) / "mymodule"
            module.mkdir()
            (module / "__init__.py").write_text("")
            (module / "__manifest__.py").write_text("{'name': 'mymodule'}\n")

            cfg = configmanager()
            # FIRST parse: what command.main does with the bootstrap
            # --addons-path (plus a normal --data-dir, used below as a control).
            cfg._parse_config([f"--addons-path={ad}", f"--data-dir={dd}"])
            first_addons = list(cfg["addons_path"])
            first_data_dir = cfg["data_dir"]
            self.assertIn(ad, first_addons)

            # SECOND parse: what DatabaseCommand.bootstrap_config does — only
            # -d, NO --addons-path.
            cfg._parse_config(["-d", "somedb"])
            second_addons = list(cfg["addons_path"])
            second_data_dir = cfg["data_dir"]

            self.assertIn(
                ad,
                second_addons,
                msg="addons_path lost on the second config parse: "
                "`module install --addons-path=X` would find no modules",
            )
            # Control: a non-preserved option (data_dir) is NOT carried over,
            # proving addons_path's survival is a deliberate special case and
            # not a generic 'CLI options persist' behaviour.
            self.assertNotEqual(
                second_data_dir,
                first_data_dir,
                msg="data_dir unexpectedly persisted; the control no longer "
                "isolates addons_path's special preservation",
            )

    def test_build_config_args_forwards_only_connection_flags(self):
        """build_config_args carries only --no-http/-c/-d, never the global
        --addons-path.

        This is the CLI half of the contract pinned by
        test_databasecommand_preserves_bootstrap_addons_path: because the
        second parse omits --addons-path, config MUST preserve it. The
        assertion also bounds the abstraction — commands needing arbitrary
        server options (shell, cloc) cannot route through build_config_args
        and so parse the config themselves.
        """
        from odoo.cli.command import build_config_args

        self.assertEqual(
            build_config_args("cfg", "db"),
            ["--no-http", "-c", "cfg", "-d", "db"],
        )
        self.assertNotIn("--addons-path", build_config_args("cfg", "db"))
        # extra_args is the only channel for anything beyond -c/-d/--no-http:
        self.assertIn(
            "--workers=4",
            build_config_args(None, None, extra_args=["--workers=4"]),
        )

    def test_db_refuses_system_databases(self):
        """Destructive `db` subcommands must refuse the PG system databases
        and the configured creation template. PostgreSQL itself refuses to
        drop template0/1 (with a raw traceback), but happily drops `postgres`
        — the maintenance DB every client tool connects to by default."""
        from odoo.cli import db as dbmod

        cmd = dbmod.Db()
        protected = ["postgres", "template0", "template1", config["db_template"]]
        # exp_db_exist=True + force=True: without the guard, every subcommand
        # would sail through its free/exists checks and reach a (mocked)
        # destructive call — so each assertion below discriminates the guard,
        # and no code path touches the real cluster.
        with (
            mock.patch.object(dbmod, "exp_db_exist", return_value=True),
            mock.patch.object(dbmod, "_drop_database") as drop_mock,
            mock.patch.object(dbmod, "exp_create_database") as create_mock,
            mock.patch.object(dbmod, "_rename_database") as rename_mock,
            mock.patch.object(dbmod, "_duplicate_database") as duplicate_mock,
        ):
            for name in protected:
                with self.assertRaises(SystemExit, msg=f"drop {name} not refused"):
                    cmd.drop(mock.Mock(database=name))
                with self.assertRaises(SystemExit, msg=f"init {name} not refused"):
                    cmd.init(mock.Mock(database=name, force=True))
                with self.assertRaises(SystemExit, msg=f"rename from {name}"):
                    cmd.rename(mock.Mock(source=name, target="tgt", force=True))
                with self.assertRaises(SystemExit, msg=f"duplicate onto {name}"):
                    cmd.duplicate(mock.Mock(source="src", target=name, force=True))
        drop_mock.assert_not_called()
        create_mock.assert_not_called()
        rename_mock.assert_not_called()
        duplicate_mock.assert_not_called()

    def test_start_refuses_system_database_names(self):
        """`start` derives the database name from a directory name; a project
        checked out as e.g. `postgres/` must not create over (or serve from)
        a PG system database."""
        from odoo.cli import start as startmod

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "postgres"
            proj.mkdir()
            with (
                mock.patch.object(startmod, "_create_empty_database") as create_mock,
                self.assertRaises(SystemExit) as ctx,
            ):
                startmod.Start().run(["-p", str(proj)])
        create_mock.assert_not_called()
        self.assertIn("system database", str(ctx.exception.code))

    def test_db_list_prints_databases(self):
        """`db list` prints each visible database on its own line."""
        import contextlib
        import io

        from odoo.cli import db as dbmod

        out = io.StringIO()
        with (
            mock.patch.object(dbmod, "list_dbs", return_value=["alpha", "beta"]) as m,
            contextlib.redirect_stdout(out),
        ):
            dbmod.Db().list(mock.Mock())
        m.assert_called_once_with(force=True)
        self.assertEqual(out.getvalue(), "alpha\nbeta\n")

    def test_db_connection_flags_have_help(self):
        """Every connection flag must carry help text (rendered in `db --help`
        and each subcommand's help), and the help map must not drift from the
        declared flags. Assert on the parser actions, not the formatted output
        — argparse wraps help at terminal width, so string matching against
        print_help() would be flaky in narrow terminals."""
        import argparse

        from odoo.cli import db as dbmod

        declared = {flags[-1] for flags in dbmod.Db._CONNECTION_FLAGS}
        self.assertEqual(set(dbmod.Db._CONNECTION_HELP), declared)
        parser = argparse.ArgumentParser(prog="db")
        dbmod.Db._add_connection_flags(parser)
        # option_strings keeps declaration order; the long form is last,
        # matching the _CONNECTION_FLAGS convention.
        registered = {
            a.option_strings[-1]: a.help
            for a in parser._actions
            if a.option_strings and a.dest != "help"
        }
        for long_flag in declared:
            self.assertEqual(
                registered.get(long_flag),
                dbmod.Db._CONNECTION_HELP[long_flag],
                msg=f"{long_flag} registered without its help text",
            )

    def test_deploy_zip_skips_junk_file_names(self):
        """`.DS_Store` has no Path.suffix (dotfile), so the old suffix-based
        exclusion shipped it in every deploy zip; it must be excluded by
        file name."""
        import zipfile as zipfile_mod

        from odoo.cli.deploy import Deploy

        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "mymod"
            mod.mkdir()
            (mod / "__manifest__.py").write_text("{'name': 'mymod'}\n")
            (mod / ".DS_Store").write_bytes(b"\x00junk")
            (mod / "Thumbs.db").write_bytes(b"\x00junk")
            zpath = Deploy().zip_module(mod)
            try:
                with zipfile_mod.ZipFile(zpath) as z:
                    names = {n.split("/", 1)[1] for n in z.namelist()}
            finally:
                Path(zpath).unlink()
        self.assertNotIn(".DS_Store", names)
        self.assertNotIn("Thumbs.db", names)
        self.assertIn("__manifest__.py", names)

    def test_populate_rejects_nonpositive_factors(self):
        """A factor of 0 or less would silently populate nothing while the
        command still reports success."""
        from odoo.cli.populate import _parse_model_factors

        for factors in ("0", "-1", "3,0"):
            errors = []
            _parse_model_factors(factors, "a,b", errors.append)
            self.assertTrue(
                errors and ">= 1" in errors[0],
                msg=f"factors {factors!r} not rejected: {errors}",
            )

    def test_help_falls_back_to_description(self):
        """An (addon) command without a docstring must still show its
        `description` in the `help` table instead of a blank cell."""
        import contextlib
        import io

        from odoo.cli import help as helpmod

        class NoDocstring:
            __doc__ = None
            description = "From description\nsecond line ignored"

        out = io.StringIO()
        with (
            mock.patch.object(helpmod, "load_internal_commands"),
            mock.patch.object(helpmod, "load_addons_commands"),
            mock.patch.dict(helpmod.commands, {"nodoc": NoDocstring}, clear=True),
            contextlib.redirect_stdout(out),
        ):
            helpmod.Help().run([])
        self.assertIn("From description", out.getvalue())
        self.assertNotIn("second line", out.getvalue())

    def test_shell_repl_availability_probe(self):
        """REPL availability is probed with find_spec, so an installed-but-
        broken REPL surfaces a warning instead of silently vanishing from the
        fallback chain."""
        import importlib.util

        from odoo.cli.shell import Shell

        # The stdlib console is always available.
        self.assertTrue(Shell._repl_available("python"))
        # Every non-stdlib supported shell must have a probe mapping.
        self.assertEqual(
            set(Shell._REPL_MODULES),
            set(Shell.supported_shells) - {"python"},
        )
        with mock.patch.object(importlib.util, "find_spec", return_value=None):
            self.assertFalse(Shell._repl_available("ipython"))

    def test_cloc_counts_path(self):
        """`cloc -p <dir>` runs config-free and reports counted lines; the
        database-mode connection flags must be visible in --help (they used
        to work only via silent unknown-arg forwarding)."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "thing.py").write_text("x = 1\ny = 2\n")
            proc = self.run_command("cloc", "-v", "-p", tmp)
        self.assertIn(Path(tmp).name, proc.stdout)
        self.assertIn("thing.py", proc.stdout)
        help_proc = self.run_command("cloc", "--help")
        self.assertIn("--config", help_proc.stdout)
        self.assertIn("--data-dir", help_proc.stdout)

    def test_get_single_database_refuses_system_databases(self):
        """The single-database funnel (shell, cloc, every DatabaseCommand)
        must refuse PG system databases and the configured creation template:
        opening a registry on one would bootstrap Odoo tables inside it."""
        from odoo.cli.command import get_single_database

        for name in ("postgres", "template0", "template1", config["db_template"]):
            errors = []
            self.assertIsNone(get_single_database([name], error_handler=errors.append))
            self.assertTrue(
                errors and "system or template" in errors[0],
                msg=f"{name!r} not refused: {errors}",
            )
        errors = []
        self.assertEqual(
            get_single_database(["mydb"], error_handler=errors.append), "mydb"
        )
        self.assertFalse(errors)

    def test_server_refuses_system_database(self):
        """`odoo-bin -d postgres` must refuse to serve: registry preload
        bootstraps Odoo tables into any uninitialized database it is pointed
        at, corrupting the maintenance DB."""
        proc = self.run_command(
            "server",
            "-d",
            "postgres",
            "--no-http",
            "--stop-after-init",
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("system or template database", proc.stderr)

    def test_db_dump_removes_partial_file_on_failure(self):
        """A dump that fails mid-write must not leave a truncated file that
        is indistinguishable from a valid dump by name."""
        from odoo.cli import db as dbmod

        with tempfile.TemporaryDirectory() as tmp:
            dump_path = Path(tmp) / "out.zip"
            ns = mock.Mock(
                database="mydb",
                dump_path=str(dump_path),
                dump_format="zip",
                filestore=True,
            )
            with (
                mock.patch.object(dbmod, "exp_db_exist", return_value=True),
                mock.patch.object(
                    dbmod, "dump_db", side_effect=RuntimeError("disk full")
                ),
                self.assertRaises(RuntimeError),
            ):
                dbmod.Db().dump(ns)
            self.assertFalse(dump_path.exists(), msg="partial dump file left behind")

    def test_module_zip_path_requires_real_zip(self):
        """A file merely *named* .zip must not be treated as an importable
        data module — the 'not a readable .zip' warning has to be true."""
        import zipfile as zipfile_mod

        from odoo.cli.module import Module

        cmd = Module()
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake.zip"
            fake.write_text("not a zip at all")
            real = Path(tmp) / "real.zip"
            with zipfile_mod.ZipFile(real, "w") as z:
                z.writestr("mod/__manifest__.py", "{}")
            self.assertIsNone(cmd._get_zip_path(str(fake)))
            self.assertEqual(cmd._get_zip_path(str(real)), real.resolve())

    def test_upgrade_code_clears_progress_line(self):
        """The last progress render ends with `\\r`; clear_progress must erase
        it so it isn't left under later stdout output."""
        import contextlib
        import io

        fm = upgrade_code.FileManager([], "**/*")
        fm._show_progress = True
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            fm.clear_progress()
        self.assertEqual(stderr.getvalue(), "\033[K")
        fm._show_progress = False
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            fm.clear_progress()
        self.assertEqual(stderr.getvalue(), "", msg="must be silent off-tty")
