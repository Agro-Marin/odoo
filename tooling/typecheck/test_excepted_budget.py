import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import excepted_budget as eb


class VerdictTest(unittest.TestCase):
    def test_within_budget_is_clean(self):
        self.assertTrue(eb.evaluate({"a.js": 5, "b.js": 0}, {"a.js": 5, "b.js": 0}).ok)

    def test_one_more_error_fails(self):
        v = eb.evaluate({"a.js": 6}, {"a.js": 5})
        self.assertFalse(v.ok)
        self.assertEqual(v.regressed, [("a.js", 5, 6)])

    def test_one_fewer_error_also_fails_until_locked_in(self):
        v = eb.evaluate({"a.js": 4}, {"a.js": 5})
        self.assertFalse(v.ok)
        self.assertEqual(v.improved, [("a.js", 5, 4)])
        self.assertEqual(v.regressed, [])

    def test_newly_excepted_file_without_a_budget_fails(self):
        v = eb.evaluate({"a.js": 5, "new.js": 3}, {"a.js": 5})
        self.assertFalse(v.ok)
        self.assertEqual(v.unbudgeted, ["new.js"])

    def test_budget_for_a_file_no_longer_excepted_fails(self):
        v = eb.evaluate({"a.js": 5}, {"a.js": 5, "gone.js": 2})
        self.assertFalse(v.ok)
        self.assertEqual(v.stale, ["gone.js"])

    def test_a_clean_excepted_file_is_held_at_zero(self):
        self.assertTrue(eb.evaluate({"a.js": 0}, {"a.js": 0}).ok)
        self.assertEqual(
            eb.evaluate({"a.js": 1}, {"a.js": 0}).regressed, [("a.js", 0, 1)]
        )


class MeasureTest(unittest.TestCase):
    def test_counts_only_excepted_files(self):
        log = (
            "addons/web/a.js(1,1): error TS2345: x\n"
            "addons/web/a.js(2,1): error TS2322: y\n"
            "addons/web/unlisted.js(1,1): error TS2345: z\n"
        )
        with mock.patch.object(
            eb.sg, "read_exceptions", return_value=["addons/web/a.js"]
        ):
            self.assertEqual(eb.measure("strict", "web", log), {"addons/web/a.js": 2})

    def test_reports_zero_for_an_excepted_file_with_no_errors(self):
        with mock.patch.object(
            eb.sg, "read_exceptions", return_value=["addons/web/clean.js"]
        ):
            self.assertEqual(
                eb.measure("strict", "web", ""), {"addons/web/clean.js": 0}
            )


class BudgetFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.object(eb, "BUDGETS_DIR", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_round_trips(self):
        eb.write_budget("strict", "web", {"b.js": 2, "a.js": 1}, note="seeded")
        self.assertEqual(eb.read_budget("strict", "web"), {"a.js": 1, "b.js": 2})

    def test_records_the_total(self):
        path = eb.write_budget("strict", "web", {"a.js": 3, "b.js": 4}, note="n")
        self.assertEqual(json.loads(path.read_text())["total"], 7)

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(eb.read_budget("strict", "web"), {})

    def test_path_traversal_in_names_is_rejected(self):
        for bad in ("../etc", "a/b", ".hidden", ""):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                eb.budget_path(bad, "web")


class FailClosedTest(unittest.TestCase):
    def test_empty_measurement_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "empty.log"
            log.write_text("")
            with mock.patch.object(eb.sg, "read_exceptions", return_value=[]):
                self.assertEqual(eb.main(["strict", "--log", str(log)]), 2)

    def test_missing_log_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                eb.main(["strict", "--log", str(Path(tmp) / "nope.log")]), 2
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
