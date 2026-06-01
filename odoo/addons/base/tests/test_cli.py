import os
import re
import subprocess as sp
import sys
import unittest
from pathlib import Path

from odoo.cli import upgrade_code
from odoo.cli.command import (
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
        """scaffold --help must not probe templates/ eagerly; if the probe
        were in __init__, a missing directory would crash every invocation
        including --help.
        """
        src = (Path(__file__).parents[3] / "cli/scaffold.py").read_text()
        # Statically assert: __init__ is guarded or deferred.
        init_body = re.search(
            r"def __init__\(self\)[^\n]*:(.*?)def\s",
            src,
            re.DOTALL,
        ).group(1)
        self.assertNotIn(
            "iterdir()",
            init_body.replace("try:", "GUARDED"),
            msg="scaffold __init__ probes templates/ eagerly — wrap in try/except",
        ) if "try:" not in init_body else None

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
        from odoo.cli.deploy import EXCLUDED_DIR_NAMES, EXCLUDED_SUFFIXES

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
        for ext in (".pyc", ".pyo", ".swp", ".bak", ".DS_Store"):
            self.assertIn(ext, EXCLUDED_SUFFIXES)

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
