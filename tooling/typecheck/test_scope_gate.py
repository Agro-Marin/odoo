#!/usr/bin/env python3
"""Stdlib-only tests for the default-deny type-check gate. Run: python -m pytest, or

    python tooling/typecheck/test_scope_gate.py

No Odoo, no database, no node, no third-party deps — mirrors the self-test
guarantee ``tooling/ratchet/test_ratchet.py`` gives the ratchet, so CI can
verify the gate before trusting its verdict.
"""

from __future__ import annotations

import io
import json
import pathlib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import scope_gate
from scope_gate import (
    EXIT_DRIFT,
    EXIT_OK,
    EXIT_USAGE,
    evaluate_module,
    module_of,
    parse_log,
)

WEB_SRC = "addons/web/static/src/"
WEB_TESTS = "addons/web/static/tests/"
MAIL_SRC = "addons/mail/static/src/"


def err(path: str, code: str = "TS2532", line: int = 1) -> str:
    return f"{path}({line},1): error {code}: Object is possibly 'undefined'."


class ModuleOfTests(unittest.TestCase):
    """Path -> module mapping. Patched to a two-module scope so the mapping is
    tested independently of which modules SCOPED_MODULES happens to gate."""

    def setUp(self):
        patcher = mock.patch.object(scope_gate, "SCOPED_MODULES", ("web", "mail"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_gated_modules_resolve(self):
        self.assertEqual(module_of(f"{WEB_SRC}core/utils/macro.js"), "web")
        self.assertEqual(module_of(f"{WEB_TESTS}views/list_view.test.js"), "web")
        self.assertEqual(module_of(f"{MAIL_SRC}core/common/thread.js"), "mail")

    def test_ungated_module_is_out_of_scope(self):
        # A module nobody locked yet is the count ratchet's business, not ours.
        self.assertIsNone(module_of("addons/stock/static/src/widget.js"))

    def test_non_scope_subdirs_rejected(self):
        # static/lib is vendored third-party code plus the hoot harness.
        self.assertIsNone(module_of("addons/web/static/lib/hoot/hoot.js"))
        self.assertIsNone(module_of("addons/web/static/fonts/x.js"))

    def test_paths_outside_addons_rejected(self):
        self.assertIsNone(module_of("tooling/typecheck/scope_gate.py"))
        self.assertIsNone(module_of("odoo/addons/base/static/src/x.js"))

    def test_declaration_files_rejected(self):
        # skipLibCheck means .d.ts never produces errors; locking them would
        # inflate the coverage number with files nothing checks.
        self.assertIsNone(module_of(f"{WEB_SRC}@types/registry.d.ts"))
        self.assertEqual(module_of(f"{WEB_SRC}@types/models/_runtime.ts"), "web")

    def test_non_source_extensions_rejected(self):
        self.assertIsNone(module_of(f"{WEB_SRC}ui/dialog/dialog.xml"))
        self.assertIsNone(module_of(f"{WEB_SRC}ui/dialog/dialog.scss"))


class CommittedScopeTests(unittest.TestCase):
    """The scope as actually committed — guards against an accidental widening
    that would lock thousands of unaudited files, and against an empty tuple
    that would silently gate nothing at all."""

    def test_web_is_gated(self):
        self.assertIn("web", scope_gate.SCOPED_MODULES)

    def test_scope_is_not_empty(self):
        self.assertTrue(scope_gate.SCOPED_MODULES)

    def test_every_gated_module_has_both_lists(self):
        # A gated module with no list makes the gate exit 2, not pass, but that
        # is a CI failure discovered late; catch it here instead.
        for gate in ("strict", "noimplicitany"):
            for module in scope_gate.SCOPED_MODULES:
                path = scope_gate.exceptions_path(gate, module)
                self.assertTrue(path.exists(), f"missing {path}")


class ParseLogTests(unittest.TestCase):
    def test_tallies_per_file_and_code(self):
        log = "\n".join(
            [
                err(f"{WEB_SRC}a.js", "TS2532"),
                err(f"{WEB_SRC}a.js", "TS2532", line=9),
                err(f"{WEB_SRC}a.js", "TS18047"),
                err(f"{WEB_SRC}b.js", "TS2345"),
            ]
        )
        self.assertEqual(
            parse_log(log),
            {
                f"{WEB_SRC}a.js": {"TS2532": 2, "TS18047": 1},
                f"{WEB_SRC}b.js": {"TS2345": 1},
            },
        )

    def test_ignores_continuation_and_summary_lines(self):
        log = "\n".join(
            [
                err(f"{WEB_SRC}a.js"),
                "  The expected type comes from property 'x'.",
                "",
                "Found 1 error in 1 file.",
            ]
        )
        self.assertEqual(list(parse_log(log)), [f"{WEB_SRC}a.js"])

    def test_path_inside_a_message_is_not_attributed(self):
        # The regression this anchoring prevents: an unanchored search sees the
        # quoted path and blames a file that is actually clean.
        log = (
            f"{WEB_SRC}a.js(1,1): error TS2307: Cannot find module "
            f"'{WEB_SRC}core/registry.js' or its declarations."
        )
        self.assertEqual(list(parse_log(log)), [f"{WEB_SRC}a.js"])

    def test_absolute_paths_normalised_to_repo_relative(self):
        absolute = (scope_gate.ROOT / f"{WEB_SRC}a.js").as_posix()
        self.assertEqual(list(parse_log(err(absolute))), [f"{WEB_SRC}a.js"])

    def test_dot_slash_prefix_stripped(self):
        self.assertEqual(list(parse_log(err(f"./{WEB_SRC}a.js"))), [f"{WEB_SRC}a.js"])


class EvaluateModuleTests(unittest.TestCase):
    """The verdict logic as a pure function, with the filesystem stubbed."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(scope_gate, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def touch(self, rel: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def test_clean_scope_passes(self):
        self.touch(f"{WEB_SRC}a.js")
        v = evaluate_module("web", {}, [], [f"{WEB_SRC}a.js"], "exact")
        self.assertTrue(v.ok)
        self.assertEqual((v.locked, v.excepted), (1, 0))
        self.assertEqual(v.coverage, 100.0)

    def test_unexcepted_error_regresses(self):
        self.touch(f"{WEB_SRC}a.js")
        v = evaluate_module(
            "web", parse_log(err(f"{WEB_SRC}a.js")), [], [f"{WEB_SRC}a.js"], "exact"
        )
        self.assertFalse(v.ok)
        self.assertEqual(v.regressed, [f"{WEB_SRC}a.js"])

    def test_excepted_error_tolerated(self):
        self.touch(f"{WEB_SRC}a.js")
        tally = parse_log(err(f"{WEB_SRC}a.js"))
        v = evaluate_module(
            "web", tally, [f"{WEB_SRC}a.js"], [f"{WEB_SRC}a.js"], "exact"
        )
        self.assertTrue(v.ok)
        self.assertEqual((v.locked, v.excepted), (0, 1))

    def test_new_file_is_gated_without_being_listed(self):
        # The core win over an allowlist: a file nobody mentioned is enforced.
        self.touch(f"{WEB_SRC}brand_new.js")
        self.touch(f"{WEB_SRC}old.js")
        tally = parse_log(
            "\n".join([err(f"{WEB_SRC}brand_new.js"), err(f"{WEB_SRC}old.js")])
        )
        v = evaluate_module(
            "web",
            tally,
            [f"{WEB_SRC}old.js"],
            [f"{WEB_SRC}brand_new.js", f"{WEB_SRC}old.js"],
            "exact",
        )
        self.assertFalse(v.ok)
        self.assertEqual(v.regressed, [f"{WEB_SRC}brand_new.js"])

    def test_renamed_exception_is_stale_not_resolved(self):
        # ui/block/ui_service.js -> ui/ui_service.js lost its lock this way and
        # no gate noticed. A moved file must read as a lost lock.
        v = evaluate_module(
            "web", parse_log(err(f"{WEB_SRC}b.js")), [f"{WEB_SRC}gone.js"], [], "exact"
        )
        self.assertFalse(v.ok)
        self.assertEqual(v.stale, [f"{WEB_SRC}gone.js"])
        self.assertEqual(v.resolved, [])

    def test_foreign_module_entry_is_out_of_scope(self):
        # A mail path filed in web's list enforces nothing: mail reads its own
        # list, so without this check the lock is absent from both.
        self.touch(f"{MAIL_SRC}x.js")
        v = evaluate_module(
            "web", parse_log(err(f"{WEB_SRC}a.js")), [f"{MAIL_SRC}x.js"], [], "exact"
        )
        self.assertFalse(v.ok)
        self.assertEqual(v.out_of_scope, [f"{MAIL_SRC}x.js"])

    def test_ungated_path_entry_is_out_of_scope(self):
        v = evaluate_module(
            "web",
            parse_log(err(f"{WEB_SRC}a.js")),
            ["addons/web/static/lib/hoot/hoot.js"],
            [],
            "exact",
        )
        self.assertFalse(v.ok)
        self.assertEqual(v.out_of_scope, ["addons/web/static/lib/hoot/hoot.js"])

    def test_resolved_fails_in_exact_mode_only(self):
        self.touch(f"{WEB_SRC}fixed.js")
        self.touch(f"{WEB_SRC}dirty.js")
        tally = parse_log(err(f"{WEB_SRC}dirty.js"))
        exceptions = [f"{WEB_SRC}fixed.js", f"{WEB_SRC}dirty.js"]
        files = [f"{WEB_SRC}fixed.js", f"{WEB_SRC}dirty.js"]

        strict = evaluate_module("web", tally, exceptions, files, "exact")
        self.assertFalse(strict.ok)
        self.assertEqual(strict.resolved, [f"{WEB_SRC}fixed.js"])

        soft = evaluate_module("web", tally, exceptions, files, "no-increase")
        self.assertTrue(soft.ok)
        self.assertEqual(soft.resolved, [f"{WEB_SRC}fixed.js"])

    def test_regression_fails_in_both_modes(self):
        self.touch(f"{WEB_SRC}a.js")
        tally = parse_log(err(f"{WEB_SRC}a.js"))
        for mode in ("exact", "no-increase"):
            v = evaluate_module("web", tally, [], [f"{WEB_SRC}a.js"], mode)
            self.assertFalse(v.ok, mode)

    def test_another_modules_error_is_ignored(self):
        # web's verdict must not be polluted by mail's errors, and vice versa.
        self.touch(f"{WEB_SRC}a.js")
        tally = parse_log(err(f"{MAIL_SRC}x.js"))
        self.assertTrue(
            evaluate_module("web", tally, [], [f"{WEB_SRC}a.js"], "exact").ok
        )

    def test_ungated_module_error_is_ignored(self):
        self.touch(f"{WEB_SRC}a.js")
        tally = parse_log(err("addons/stock/static/src/widget.js"))
        self.assertTrue(
            evaluate_module("web", tally, [], [f"{WEB_SRC}a.js"], "exact").ok
        )

    def test_coverage_excludes_stale_and_out_of_scope_from_excepted(self):
        self.touch(f"{WEB_SRC}dirty.js")
        tally = parse_log(err(f"{WEB_SRC}dirty.js"))
        v = evaluate_module(
            "web",
            tally,
            [f"{WEB_SRC}dirty.js", f"{WEB_SRC}gone.js", f"{MAIL_SRC}x.js"],
            [f"{WEB_SRC}dirty.js", f"{WEB_SRC}clean.js"],
            "exact",
        )
        self.assertEqual(v.excepted, 1)
        self.assertEqual(v.locked, 1)


class ProgramMembershipTests(unittest.TestCase):
    """A file tsc never compiled must not be counted, or credited, as clean."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(scope_gate, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def touch(self, rel: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def test_uncompiled_file_is_unchecked_not_locked(self):
        # The exclude: ["**/l10n*"] regression in miniature: no errors, no
        # exception entry, and yet nothing ever looked at the file.
        files = [f"{WEB_SRC}a.js", f"{WEB_TESTS}core/l10n/dates.test.js"]
        v = evaluate_module("web", {}, [], files, "exact", program={files[0]})
        self.assertFalse(v.ok)
        self.assertEqual(v.unchecked, [files[1]])
        self.assertEqual(v.locked, 1)

    def test_dotfiles_are_out_of_scope_entirely(self):
        # tsconfig's include: ["**/*.js"] does not match a dot-prefixed path, so
        # a dotfile is never in the program tsc builds. Counting it as in-scope
        # therefore reports it UNCHECKED forever — and since `.gitignore` line 1
        # is `.*`, CI (a fresh checkout) never sees the file at all. The gate
        # failed only in working trees carrying an editor dropping, which is the
        # one place a lock must not be noisier than the thing it protects.
        self.touch(f"{WEB_SRC}real.js")
        self.touch(f"{WEB_SRC}.__e.js")
        self.touch(f"{WEB_SRC}model/.__e.js")
        self.touch(f"{WEB_SRC}.hidden_dir/inner.js")
        self.assertEqual(scope_gate.module_files("web"), [f"{WEB_SRC}real.js"])

    def test_dotfile_exclusion_does_not_reach_normal_paths(self):
        # The rule is per-segment and anchored at the start of a segment: a dot
        # inside a name (`file.test.js`, `a.b.js`) must stay in scope, or the
        # fix would silently unlock most of the tests tree.
        self.touch(f"{WEB_TESTS}core/domain.test.js")
        self.touch(f"{WEB_SRC}a.b.js")
        self.assertEqual(
            scope_gate.module_files("web"),
            [f"{WEB_SRC}a.b.js", f"{WEB_TESTS}core/domain.test.js"],
        )

    def test_a_path_with_a_space_stays_in_the_program(self):
        # `--listFiles` lines were rejected outright if they contained a space,
        # as a way of telling a path from prose. A real file named with a space
        # then vanished from the program, was reported UNCHECKED, and failed
        # the gate with a message blaming the tsconfig's include/exclude —
        # a true failure with an untrue cause. Existence settles it.
        self.touch(f"{WEB_SRC}with space.js")
        self.touch(f"{WEB_SRC}plain.js")
        log = f"{self.root}/{WEB_SRC}plain.js\n{self.root}/{WEB_SRC}with space.js\n"
        program = scope_gate.parse_program_files(log)
        self.assertEqual(program, {f"{WEB_SRC}plain.js", f"{WEB_SRC}with space.js"})
        v = evaluate_module("web", {}, [], sorted(program), "exact", program=program)
        self.assertTrue(v.ok)
        self.assertEqual(v.locked, 2)

    def test_prose_that_merely_ends_in_a_suffix_is_still_rejected(self):
        # The other half: a sentence ending in `.ts` must not become a program
        # entry just because the space rule loosened.
        log = "error: could not read tsconfig.json\nSome prose about a file.ts\n"
        self.assertEqual(scope_gate.parse_program_files(log), set())

    def test_buckets_partition_the_scope(self):
        # locked + excepted + unchecked must equal the file count: an excepted
        # file that is also uncompiled belongs to one bucket, not two, or the
        # coverage denominator inflates.
        self.touch(f"{WEB_SRC}dirty.js")
        files = [f"{WEB_SRC}dirty.js", f"{WEB_SRC}skipped.js", f"{WEB_SRC}ok.js"]
        v = evaluate_module(
            "web",
            parse_log(err(f"{WEB_SRC}dirty.js")),
            [f"{WEB_SRC}dirty.js"],
            files,
            "exact",
            program={f"{WEB_SRC}dirty.js", f"{WEB_SRC}ok.js"},
        )
        self.assertEqual(v.locked + v.excepted + len(v.unchecked), len(files))
        self.assertEqual(v.unchecked, [f"{WEB_SRC}skipped.js"])

    def test_excepted_and_uncompiled_is_not_double_counted(self):
        self.touch(f"{WEB_SRC}dropped.js")
        v = evaluate_module(
            "web",
            {},
            [f"{WEB_SRC}dropped.js"],
            [f"{WEB_SRC}dropped.js"],
            "no-increase",
            program=set(),
        )
        self.assertEqual(v.excepted, 1)
        self.assertEqual(v.unchecked, [])
        self.assertEqual(v.locked, 0)

    def test_uncompiled_exception_is_not_reported_resolved(self):
        # Silence from a file nothing compiled must not retire its lock: in
        # exact mode "resolved" tells you to delete the entry, which would drop
        # a lock the gate never verified.
        self.touch(f"{WEB_SRC}dropped.js")
        v = evaluate_module(
            "web",
            {},
            [f"{WEB_SRC}dropped.js"],
            [f"{WEB_SRC}dropped.js"],
            "exact",
            program=set(),
        )
        self.assertEqual(v.resolved, [])
        self.assertTrue(v.ok)

    def test_compiled_and_clean_exception_still_resolves(self):
        self.touch(f"{WEB_SRC}fixed.js")
        v = evaluate_module(
            "web",
            {},
            [f"{WEB_SRC}fixed.js"],
            [f"{WEB_SRC}fixed.js"],
            "exact",
            program={f"{WEB_SRC}fixed.js"},
        )
        self.assertEqual(v.resolved, [f"{WEB_SRC}fixed.js"])
        self.assertFalse(v.ok)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for patched, value in (
            ("ROOT", self.root),
            ("EXCEPTIONS_DIR", self.root / "tooling/typecheck/exceptions"),
            ("SCOPED_MODULES", ("web", "mail")),
        ):
            patcher = mock.patch.object(scope_gate, patched, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.touched: list[str] = []

    def touch(self, rel: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        self.touched.append(rel)

    def write_log(self, text: str, *, omit_from_program: tuple[str, ...] = ()) -> str:
        """A log in the shape the gate requires: diagnostics + --listFiles.

        Every touched file is listed as compiled unless named in
        ``omit_from_program``, which is how an ``unchecked`` file is simulated.
        """
        listed = [r for r in self.touched if r not in omit_from_program]
        program = "\n".join((self.root / r).as_posix() for r in listed)
        path = self.root / "tsc.log"
        path.write_text(f"{text}\n{program}\n", encoding="utf-8")
        return str(path)

    def _run(self, argv):
        out, errbuf = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(errbuf):
            code = scope_gate.run(argv)
        return code, out.getvalue(), errbuf.getvalue()

    def test_update_then_gate_is_green(self):
        # The property that lets the inversion land without any cleanup.
        self.touch(f"{WEB_SRC}dirty.js")
        self.touch(f"{WEB_SRC}clean.js")
        self.touch(f"{MAIL_SRC}dirty.js")
        log = self.write_log(
            "\n".join([err(f"{WEB_SRC}dirty.js"), err(f"{MAIL_SRC}dirty.js")])
        )

        code, out, _ = self._run(["g", "--log", log, "--update"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("exceptions/g/web.txt", out)
        self.assertIn("exceptions/g/mail.txt", out)

        code, out, _ = self._run(["g", "--log", log])
        self.assertEqual(code, EXIT_OK, out)
        # web: dirty + clean, mail: dirty -> 1 locked of 3, 2 excepted.
        self.assertIn("1 of 3 in-scope files", out)
        self.assertIn("2 excepted", out)

    def test_every_module_gets_a_list_even_when_clean(self):
        # A missing file must mean "never generated", not "module is clean".
        self.touch(f"{WEB_SRC}dirty.js")
        log = self.write_log(err(f"{WEB_SRC}dirty.js"))
        self._run(["g", "--log", log, "--update"])
        self.assertTrue(
            (self.root / "tooling/typecheck/exceptions/g/mail.txt").exists()
        )

    def test_gate_fails_on_new_error(self):
        self.touch(f"{WEB_SRC}dirty.js")
        self.touch(f"{WEB_SRC}clean.js")
        self._run(["g", "--log", self.write_log(err(f"{WEB_SRC}dirty.js")), "--update"])
        worse = self.write_log(
            "\n".join([err(f"{WEB_SRC}dirty.js"), err(f"{WEB_SRC}clean.js")])
        )
        code, out, _ = self._run(["g", "--log", worse])
        self.assertEqual(code, EXIT_DRIFT)
        self.assertIn("REGRESSED", out)
        self.assertIn(f"{WEB_SRC}clean.js", out)

    def test_one_modules_regression_fails_the_whole_gate(self):
        self.touch(f"{WEB_SRC}a.js")
        self.touch(f"{MAIL_SRC}x.js")
        self._run(["g", "--log", self.write_log(err(f"{WEB_SRC}a.js")), "--update"])
        worse = self.write_log(
            "\n".join([err(f"{WEB_SRC}a.js"), err(f"{MAIL_SRC}x.js")])
        )
        code, out, _ = self._run(["g", "--log", worse])
        self.assertEqual(code, EXIT_DRIFT)
        self.assertIn("mail:", out)

    def test_module_flag_restricts_the_verdict(self):
        self.touch(f"{WEB_SRC}a.js")
        self.touch(f"{MAIL_SRC}x.js")
        self._run(["g", "--log", self.write_log(err(f"{WEB_SRC}a.js")), "--update"])
        worse = self.write_log(
            "\n".join([err(f"{WEB_SRC}a.js"), err(f"{MAIL_SRC}x.js")])
        )
        # mail regressed, but gating only web must still pass.
        code, _, _ = self._run(["g", "--log", worse, "--module", "web"])
        self.assertEqual(code, EXIT_OK)
        code, _, _ = self._run(["g", "--log", worse, "--module", "mail"])
        self.assertEqual(code, EXIT_DRIFT)

    def test_unknown_module_is_usage_error(self):
        code, _, errtext = self._run(
            ["g", "--log", self.write_log(err(f"{WEB_SRC}a.js")), "--module", "nope"]
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("not a gated module", errtext)

    def test_log_without_program_list_refuses(self):
        # A broken tsc step must not green-light every locked file. The file list
        # is the proof the compile happened, so its absence is fatal.
        path = self.root / "bare.log"
        path.write_text(err(f"{WEB_SRC}a.js"), encoding="utf-8")
        code, _, errtext = self._run(["g", "--log", str(path)])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("no program file list", errtext)

    def test_clean_program_passes(self):
        # With --listFiles proving the compile ran, zero diagnostics is a real
        # clean result and must pass rather than be refused as suspicious.
        self.touch(f"{WEB_SRC}clean.js")
        log = self.write_log("")
        self._run(["g", "--log", log, "--update"])
        code, out, _ = self._run(["g", "--log", log])
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("1 of 1 in-scope files", out)

    def test_scoped_file_absent_from_the_program_is_unchecked(self):
        # tsc's `exclude` silently removed files from the program; counting them
        # as locked at zero inflates coverage with files nothing compiles.
        self.touch(f"{WEB_SRC}compiled.js")
        self.touch(f"{WEB_SRC}excluded.js")
        log = self.write_log("", omit_from_program=(f"{WEB_SRC}excluded.js",))
        self._run(["g", "--log", log, "--update"])
        code, out, _ = self._run(["g", "--log", log])
        self.assertEqual(code, EXIT_DRIFT)
        self.assertIn(f"{WEB_SRC}excluded.js", out)

    def test_missing_log_is_usage_error(self):
        code, _, errtext = self._run(["g", "--log", str(self.root / "nope.log")])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("no such log", errtext)

    def test_missing_exception_list_is_usage_error(self):
        self.touch(f"{WEB_SRC}a.js")
        code, _, errtext = self._run(
            ["g", "--log", self.write_log(err(f"{WEB_SRC}a.js"))]
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("no exception list", errtext)

    def test_bad_gate_name_rejected(self):
        code, _, errtext = self._run(["../escape", "--log", "x"])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("invalid name", errtext)

    def test_json_verdict_shape(self):
        self.touch(f"{WEB_SRC}dirty.js")
        log = self.write_log(err(f"{WEB_SRC}dirty.js"))
        self._run(["g", "--log", log, "--update"])
        code, out, _ = self._run(["g", "--log", log, "--json"])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["excepted"], 1)
        self.assertIn("coverage", payload)
        by_module = {m["module"]: m for m in payload["modules"]}
        self.assertEqual(by_module["web"]["regressed"], [])
        self.assertIn("coverage", by_module["web"])

    def test_report_ranks_by_leverage(self):
        self.touch(f"{WEB_SRC}easy.js")
        self.touch(f"{WEB_SRC}hard.js")
        log = self.write_log(
            "\n".join(
                [err(f"{WEB_SRC}easy.js", "TS2532", i) for i in range(1, 4)]
                + [err(f"{WEB_SRC}hard.js", "TS2339", i) for i in range(1, 4)]
            )
        )
        self._run(["g", "--log", log, "--update"])
        code, out, _ = self._run(["g", "--log", log, "--report"])
        self.assertEqual(code, EXIT_OK)
        self.assertLess(out.index(f"{WEB_SRC}easy.js"), out.index(f"{WEB_SRC}hard.js"))

    def test_report_lists_regressed_files_before_exceptions(self):
        # --report exists to answer "what do I fix next". Ranking only the
        # EXCEPTION list omitted every blocking file by construction — a
        # regression is, by definition, not excepted — so on the real tree it
        # showed 448 excepted files and none of the 14 failing the gate.
        self.touch(f"{WEB_SRC}excepted.js")
        self.touch(f"{WEB_SRC}regressed.js")
        base = self.write_log(err(f"{WEB_SRC}excepted.js", "TS2532"))
        self._run(["g", "--log", base, "--update"])  # excepted.js only

        both = self.write_log(
            "\n".join(
                [err(f"{WEB_SRC}excepted.js", "TS2532")]
                + [err(f"{WEB_SRC}regressed.js", "TS18048", i) for i in range(1, 4)]
            )
        )
        code, out, _ = self._run(["g", "--log", both, "--report"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("REGRESSED", out)
        self.assertIn(f"{WEB_SRC}regressed.js", out)
        # Blocking work is listed ahead of the merely-excepted work.
        self.assertLess(
            out.index(f"{WEB_SRC}regressed.js"), out.index(f"{WEB_SRC}excepted.js")
        )

    def test_report_without_regressions_still_ranks_exceptions(self):
        self.touch(f"{WEB_SRC}excepted.js")
        log = self.write_log(err(f"{WEB_SRC}excepted.js", "TS2532"))
        self._run(["g", "--log", log, "--update"])
        code, out, _ = self._run(["g", "--log", log, "--report"])
        self.assertEqual(code, EXIT_OK)
        self.assertNotIn("REGRESSED", out)
        self.assertIn(f"{WEB_SRC}excepted.js", out)

    def test_stdin_log_accepted(self):
        self.touch(f"{WEB_SRC}dirty.js")
        log = self.write_log(err(f"{WEB_SRC}dirty.js"))
        self._run(["g", "--log", log, "--update"])
        piped = pathlib.Path(log).read_text(encoding="utf-8")
        with mock.patch("sys.stdin", io.StringIO(piped)):
            code, out, _ = self._run(["g", "--log", "-"])
        self.assertEqual(code, EXIT_OK, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
