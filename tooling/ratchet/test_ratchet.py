#!/usr/bin/env python3


from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import ratchet
from ratchet import EXIT_DRIFT, EXIT_OK, EXIT_USAGE, Baseline, evaluate


class EvaluatePureTests(unittest.TestCase):
    BASE = Baseline(count=100, note="x")

    def test_unchanged_passes(self):
        v = evaluate("g", 100, self.BASE, "exact")
        self.assertTrue(v.ok)
        self.assertEqual(v.status, "unchanged")
        self.assertEqual(v.drift, 0)

    def test_increase_always_fails(self):
        for mode in ("exact", "no-increase"):
            v = evaluate("g", 101, self.BASE, mode)
            self.assertFalse(v.ok, mode)
            self.assertEqual(v.status, "regressed")
            self.assertEqual(v.drift, 1)

    def test_decrease_fails_in_exact_mode(self):
        v = evaluate("g", 90, self.BASE, "exact")
        self.assertFalse(v.ok)
        self.assertEqual(v.status, "improved")
        self.assertIn("--update", v.message)

    def test_decrease_passes_in_no_increase_mode(self):
        v = evaluate("g", 90, self.BASE, "no-increase")
        self.assertTrue(v.ok)
        self.assertEqual(v.status, "improved")

    def test_large_regression_reported(self):
        v = evaluate("mypy", 600, Baseline(count=100), "exact")
        self.assertFalse(v.ok)
        self.assertIn("+500", v.message)


class BaselineIOTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._patch = mock.patch.object(ratchet, "BASELINES_DIR", self.dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_missing_baseline_loads_none(self):
        self.assertIsNone(Baseline.load("nope"))

    def test_roundtrip(self):
        Baseline(count=42, note="hello").save("g")
        loaded = Baseline.load("g")
        self.assertEqual(loaded, Baseline(count=42, note="hello"))

    def test_saved_file_is_diff_friendly(self):
        Baseline(count=7).save("g")
        text = (self.dir / "g.json").read_text()
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text)["count"], 7)

    def test_a_baseline_predating_the_stamp_still_loads(self):
        # 104 committed baselines have no measured_at; absent is not orphaned.
        (self.dir / "g.json").write_text('{"count": 5, "note": "old"}\n')
        self.assertEqual(Baseline.load("g"), Baseline(count=5, note="old"))

    def test_rejects_path_traversal_gate_names(self):
        for bad in ("../etc/passwd", "a/b", ".hidden", ""):
            with self.assertRaises(ValueError):
                ratchet.baseline_path(bad)


class ProvenanceTests(unittest.TestCase):
    """A floor records the commit it was measured against.

    Five floors were once banked from a detached pre-rebase worktree and were
    wrong the moment they landed; proving that took measuring the gate in an
    archive tree at eight commits. The stamp turns the same question into one
    `git merge-base --is-ancestor`.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._patch = mock.patch.object(ratchet, "BASELINES_DIR", self.dir)
        self._patch.start()
        self._clean = mock.patch.object(ratchet, "_dirty_paths", return_value=[])
        self._clean.start()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._patch.stop)
        self.addCleanup(self._clean.stop)

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ratchet.run(argv)
        return code, out.getvalue(), err.getvalue()

    def test_update_refuses_a_dirty_tree(self):
        with mock.patch.object(
            ratchet, "_dirty_paths", return_value=["odoo/orm/fields/base.py"]
        ):
            code, _, err = self._run(
                ["mypy", "--count", "10", "--update", "--note", "n"]
            )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("dirty odoo tree", err)
        self.assertIn("odoo/orm/fields/base.py", err)
        self.assertFalse((self.dir / "mypy.json").exists())

    def test_update_proceeds_when_git_cannot_say_whether_the_tree_is_dirty(self):
        with (
            mock.patch.object(ratchet, "_dirty_paths", return_value=None),
            mock.patch.object(ratchet, "_head_commit", return_value=""),
        ):
            code, _, _ = self._run(["mypy", "--count", "10", "--update", "--note", "n"])
        self.assertEqual(code, EXIT_OK)

    def test_a_check_against_an_orphaned_floor_is_refused_in_both_modes(self):
        (self.dir / "mypy.json").write_text(
            '{"count": 5, "note": "n", "measured_at": "deadbeef"}\n'
        )
        for mode in ("exact", "no-increase"):
            with mock.patch.object(ratchet, "_is_ancestor_of_head", return_value=False):
                code, out, err = self._run(["mypy", "--count", "5", "--mode", mode])
            self.assertEqual(code, EXIT_USAGE, mode)
            self.assertIn("ORPHANED-BASE", err)
            self.assertIn("Re-measure", err)
            self.assertEqual(out, "")

    def test_an_unanswerable_stamp_is_still_compared(self):
        (self.dir / "mypy.json").write_text(
            '{"count": 5, "note": "n", "measured_at": "deadbeef"}\n'
        )
        with mock.patch.object(ratchet, "_is_ancestor_of_head", return_value=None):
            code, out, _ = self._run(["mypy", "--count", "5"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("== baseline", out)

    def test_a_sibling_gate_refuses_update_without_a_root(self):
        code, _, err = self._run(
            ["naming_enterprise", "--count", "3", "--update", "--note", "n"]
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("--root enterprise", err)
        self.assertFalse((self.dir / "naming_enterprise.json").exists())

    def test_a_sibling_root_is_the_tree_checked_and_the_history_stamped(self):
        with (
            mock.patch.object(ratchet, "_dirty_paths", return_value=[]) as dirty,
            mock.patch.object(ratchet, "_head_commit", return_value="ent1234") as head,
        ):
            code, _, _ = self._run(
                [
                    "naming_enterprise",
                    "--count",
                    "3",
                    "--update",
                    "--note",
                    "n",
                    "--root",
                    "enterprise",
                ]
            )
        self.assertEqual(code, EXIT_OK)
        dirty.assert_called_once_with("enterprise")
        head.assert_called_once_with("enterprise")
        data = json.loads((self.dir / "naming_enterprise.json").read_text())
        self.assertEqual(data["measured_root"], "enterprise")
        self.assertEqual(data["measured_at"], "ent1234")

    def test_a_check_resolves_the_stamp_in_the_recorded_root(self):
        (self.dir / "naming_enterprise.json").write_text(
            '{"count": 3, "note": "n", "measured_at": "ent1234", '
            '"measured_root": "enterprise"}\n'
        )
        with mock.patch.object(
            ratchet, "_is_ancestor_of_head", return_value=True
        ) as ancestor:
            code, _, _ = self._run(["naming_enterprise", "--count", "3"])
        self.assertEqual(code, EXIT_OK)
        ancestor.assert_called_once_with("ent1234", "enterprise")

    def test_a_sibling_stamp_without_a_root_is_not_rendered_as_clean(self):
        (self.dir / "naming_enterprise.json").write_text(
            '{"count": 3, "note": "n", "measured_at": "odoo1234"}\n'
        )
        with mock.patch.object(ratchet, "_is_ancestor_of_head", return_value=True):
            code, out, _ = self._run(["--list"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("STAMP-PREDATES-ROOT", out)
        self.assertIn("wrong repository", out)
        self.assertNotIn("ORPHANED-BASE", out)

    def test_update_stamps_the_commit_it_was_measured_against(self):
        with mock.patch.object(ratchet, "_head_commit", return_value="cafe1234"):
            self._run(["mypy", "--count", "10", "--update", "--note", "n"])
        self.assertEqual(
            json.loads((self.dir / "mypy.json").read_text())["measured_at"], "cafe1234"
        )

    def test_a_stamp_outside_head_history_is_flagged(self):
        (self.dir / "mypy.json").write_text(
            '{"count": 5, "note": "n", "measured_at": "deadbeef"}\n'
        )
        with mock.patch.object(ratchet, "_is_ancestor_of_head", return_value=False):
            code, out, _ = self._run(["--list"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("ORPHANED-BASE", out)
        self.assertIn("may never have been true", out)

    def test_a_stamp_inside_head_history_is_not_flagged(self):
        (self.dir / "mypy.json").write_text(
            '{"count": 5, "note": "n", "measured_at": "deadbeef"}\n'
        )
        with mock.patch.object(ratchet, "_is_ancestor_of_head", return_value=True):
            _code, out, _ = self._run(["--list"])
        self.assertNotIn("ORPHANED-BASE", out)

    def test_an_unanswerable_stamp_is_not_flagged(self):
        # No git, or the object is gone: unknowable is not the same as wrong.
        (self.dir / "mypy.json").write_text('{"count": 5, "measured_at": "x"}\n')
        with mock.patch.object(ratchet, "_is_ancestor_of_head", return_value=None):
            _code, out, _ = self._run(["--list"])
        self.assertNotIn("ORPHANED-BASE", out)

    def test_an_unanswerable_stamp_is_rendered_as_unchecked(self):
        """Unknowable is not wrong, but it is not verified either.

        Rendering it blank made a floor stamped on a commit git can no longer
        resolve look exactly like one whose base was confirmed to be in HEAD's
        history.
        """
        (self.dir / "mypy.json").write_text('{"count": 5, "measured_at": "x"}\n')
        with mock.patch.object(ratchet, "_is_ancestor_of_head", return_value=None):
            _code, out, _ = self._run(["--list"])
        self.assertIn("UNCHECKED", out)
        self.assertIn("could not resolve", out)

    def test_a_baseline_with_no_stamp_at_all_is_not_unchecked(self):
        """104 committed baselines carry no measured_at; absent is not doubtful."""
        (self.dir / "mypy.json").write_text('{"count": 5, "note": "n"}\n')
        _code, out, _ = self._run(["--list"])
        self.assertNotIn("UNCHECKED", out)
        self.assertNotIn("ORPHANED-BASE", out)

    def test_a_verified_stamp_is_neither_flagged_nor_unchecked(self):
        (self.dir / "mypy.json").write_text('{"count": 5, "measured_at": "deadbeef"}\n')
        with mock.patch.object(ratchet, "_is_ancestor_of_head", return_value=True):
            _code, out, _ = self._run(["--list"])
        self.assertNotIn("UNCHECKED", out)
        self.assertNotIn("ORPHANED-BASE", out)

    def test_an_empty_stamp_asks_git_nothing(self):
        self.assertIsNone(ratchet._is_ancestor_of_head(""))

    def test_head_commit_survives_a_missing_git(self):
        with mock.patch.object(
            ratchet.subprocess, "run", side_effect=OSError("no git")
        ):
            self.assertEqual(ratchet._head_commit(), "")
            self.assertIsNone(ratchet._is_ancestor_of_head("abc"))


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._patch = mock.patch.object(ratchet, "BASELINES_DIR", Path(self._tmp.name))
        self._patch.start()
        self._clean = mock.patch.object(ratchet, "_dirty_paths", return_value=[])
        self._clean.start()

    def tearDown(self):
        self._clean.stop()
        self._patch.stop()
        self._tmp.cleanup()

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ratchet.run(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_gate_with_no_baseline_is_held_at_zero(self):
        for mode in ("exact", "no-increase"):
            code, out, _ = self._run(["mypy", "--count", "0", "--mode", mode])
            self.assertEqual(code, EXIT_OK, mode)
            self.assertIn("== baseline", out)

    def test_a_count_above_zero_with_no_baseline_fails_and_names_the_missing_file(
        self,
    ):
        for mode in ("exact", "no-increase"):
            code, out, _ = self._run(["mypy", "--count", "1", "--mode", mode])
            self.assertEqual(code, EXIT_DRIFT, mode)
            self.assertIn("mypy.json", out)
            self.assertIn("contract, not debt", out)
            self.assertIn("--update", out)
        self.assertFalse((ratchet.BASELINES_DIR / "mypy.json").exists())

    def test_a_missing_baseline_is_zero_in_json_output_too(self):
        code, out, _ = self._run(["mypy", "--count", "3", "--json"])
        self.assertEqual(code, EXIT_DRIFT)
        payload = json.loads(out)
        self.assertEqual(payload["baseline"], 0)
        self.assertEqual(payload["status"], "regressed")
        self.assertIn("mypy.json", payload["message"])

    def test_update_still_opens_a_floor_where_there_was_none(self):
        code, out, _ = self._run(["mypy", "--count", "3", "--update", "--note", "n"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("created", out)
        self.assertEqual(Baseline.load("mypy").count, 3)
        code, _, _ = self._run(["mypy", "--count", "3"])
        self.assertEqual(code, EXIT_OK)

    def test_update_then_check_cycle(self):
        code, out, _ = self._run(["mypy", "--count", "1969", "--update", "--note", "n"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("created", out)

        code, _, _ = self._run(["mypy", "--count", "1969"])
        self.assertEqual(code, EXIT_OK)

        code, _, _ = self._run(["mypy", "--count", "1970"])
        self.assertEqual(code, EXIT_DRIFT)

        code, _, _ = self._run(["mypy", "--count", "1900"])
        self.assertEqual(code, EXIT_DRIFT)

        self._run(["mypy", "--count", "1900", "--update"])
        code, _, _ = self._run(["mypy", "--count", "1969"])
        self.assertEqual(code, EXIT_DRIFT)

    def test_no_increase_mode_tolerates_improvement(self):
        self._run(["lint", "--count", "50", "--update"])
        code, _, _ = self._run(["lint", "--count", "30", "--mode", "no-increase"])
        self.assertEqual(code, EXIT_OK)

    def test_update_preserves_note_when_not_given(self):
        self._run(["g", "--count", "5", "--update", "--note", "keep me"])
        self._run(["g", "--count", "4", "--update"])
        self.assertEqual(Baseline.load("g").note, "keep me")

    def test_json_output_is_valid(self):
        self._run(["g", "--count", "5", "--update"])
        code, out, _ = self._run(["g", "--count", "5", "--json"])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "unchanged")

    def test_list(self):
        self._run(["a", "--count", "1", "--update"])
        self._run(["b", "--count", "2", "--update"])
        code, out, _ = self._run(["--list"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("a", out)
        self.assertIn("b", out)

    def test_list_is_one_line_per_floor(self):
        self._run(["a", "--count", "1", "--update", "--note", "one\ntwo\nthree"])
        self._run(["b", "--count", "2", "--update", "--note", "x" * 400])
        code, out, _ = self._run(["--list"])
        self.assertEqual(code, EXIT_OK)
        rows = [line for line in out.splitlines() if line and not line.startswith(" ")]
        self.assertEqual(
            len(rows),
            3,
            f"--list must stay a list: two floors and a total, got {rows}. "
            f"Notes are prose -- 94 of 95 committed ones exceed 80 characters "
            f"and the longest runs 64 lines, so rendering them inline turned a "
            f"95-row table into 1001 lines of output.",
        )
        for line in out.splitlines():
            self.assertLessEqual(len(line), 100, f"line too wide: {line!r}")

    def test_notes_are_still_reachable(self):
        self._run(["a", "--count", "1", "--update", "--note", "one\ntwo"])
        code, out, _ = self._run(["--list", "--notes"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("one", out)
        self.assertIn("two", out)

    def test_list_reports_a_malformed_baseline_instead_of_crashing(self):
        self._run(["good", "--count", "1", "--update"])
        (ratchet.BASELINES_DIR / "broken.json").write_text("{not json")
        (ratchet.BASELINES_DIR / "nocount.json").write_text('{"note": "oops"}')
        code, out, err = self._run(["--list"])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("good", out)
        self.assertIn("broken", err)
        self.assertIn("nocount", err)

    def test_the_count_path_reports_a_malformed_baseline_too(self):

        for name, body in (
            ("nulls", '{"count": null}'),
            ("dicts", '{"count": {}}'),
            ("lists", '{"count": []}'),
            ("broken", "{not json"),
            ("nocount", '{"note": "oops"}'),
        ):
            with self.subTest(baseline=name):
                (ratchet.BASELINES_DIR / f"{name}.json").write_text(body)
                code, _out, err = self._run([name, "--count", "5"])
                self.assertEqual(code, EXIT_USAGE)
                self.assertIn("bad baseline", err)

    def test_list_json_separates_good_from_broken(self):
        self._run(["good", "--count", "3", "--update"])
        (ratchet.BASELINES_DIR / "broken.json").write_text("{not json")
        code, out, _ = self._run(["--list", "--json"])
        self.assertEqual(code, EXIT_USAGE)
        payload = json.loads(out)
        self.assertEqual([r["gate"] for r in payload["baselines"]], ["good"])
        self.assertEqual([r["gate"] for r in payload["broken"]], ["broken"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
