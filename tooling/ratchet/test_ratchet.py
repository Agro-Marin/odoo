#!/usr/bin/env python3
"""Stdlib-only tests for the drift-zero ratchet. Run: python -m pytest, or

    python tooling/ratchet/test_ratchet.py

No Odoo, no database, no third-party deps — mirrors the self-test guarantee that
``tooling/architecture/test_layer_check.py`` gives the layering checker.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import ratchet
from ratchet import Baseline, EXIT_DRIFT, EXIT_OK, EXIT_USAGE, evaluate


class EvaluatePureTests(unittest.TestCase):
    """The comparison logic — the load-bearing part — as a pure function."""

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
        # The compounding rule: an improvement you don't commit is a failure,
        # so the lower floor gets locked in.
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

    def test_rejects_path_traversal_gate_names(self):
        for bad in ("../etc/passwd", "a/b", ".hidden", ""):
            with self.assertRaises(ValueError):
                ratchet.baseline_path(bad)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._patch = mock.patch.object(ratchet, "BASELINES_DIR", Path(self._tmp.name))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ratchet.run(argv)
        return code, out.getvalue(), err.getvalue()

    def test_first_check_without_baseline_is_usage_error(self):
        code, _, err = self._run(["mypy", "--count", "10"])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("no baseline", err)

    def test_update_then_check_cycle(self):
        code, out, _ = self._run(["mypy", "--count", "1969", "--update", "--note", "n"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("created", out)

        # Same count → passes.
        code, _, _ = self._run(["mypy", "--count", "1969"])
        self.assertEqual(code, EXIT_OK)

        # One more error → blocks the merge.
        code, _, _ = self._run(["mypy", "--count", "1970"])
        self.assertEqual(code, EXIT_DRIFT)

        # Improvement without committing the baseline → also blocks (exact mode).
        code, _, _ = self._run(["mypy", "--count", "1900"])
        self.assertEqual(code, EXIT_DRIFT)

        # ...until you lock it in; then the floor is 1900 and 1969 regresses.
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
