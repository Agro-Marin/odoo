#!/usr/bin/env python3

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import testbaseline
from testbaseline import (
    EXIT_DRIFT,
    EXIT_OK,
    EXIT_USAGE,
    Baseline,
    Scan,
    evaluate,
    qualify,
    scan_log,
)

PREFIX = "2026-08-22 09:48:01,105 980318"


def record(level: str, logger: str, message: str) -> str:
    return f"{PREFIX} {level} uid:- db_name {logger}: {message}\n"


def failure(module: str, description: str, flavour: str = "FAIL") -> str:
    return record(
        "ERROR", f"odoo.addons.{module}.tests.test_x", f"{flavour}: {description}"
    )


def start(module: str, description: str) -> str:
    return record(
        "INFO", f"odoo.addons.{module}.tests.test_x", f"Starting {description} ..."
    )


def summary(failed: int, errors: int, total: int) -> str:
    return record(
        "ERROR",
        "odoo.tests.result",
        f"{failed} failed, {errors} error(s) of {total} tests when loading database 'x'",
    )


class QualifyTests(unittest.TestCase):
    def test_addon_is_taken_from_the_test_module_logger(self):
        self.assertEqual(
            qualify("odoo.addons.quality_control.tests.test_qc", "TestA.test_b"),
            "quality_control/TestA.test_b",
        )

    def test_non_addon_logger_falls_back_to_the_logger_name(self):
        self.assertEqual(
            qualify("odoo.tests.result", "TestA.test_b"),
            "odoo.tests.result/TestA.test_b",
        )

    def test_a_memory_address_in_a_subtest_param_is_folded(self):
        # _SubTest._subDescription interpolates repr() of every param, so an
        # object without a stable repr would rename the subtest every run.
        first = qualify(
            "odoo.addons.base.tests.test_x",
            "Subtest TestCustomFields.test_related_field (rec=<obj at 0x7f9c1a2b3c40>)",
        )
        second = qualify(
            "odoo.addons.base.tests.test_x",
            "Subtest TestCustomFields.test_related_field (rec=<obj at 0x7fa0deadbeef>)",
        )
        self.assertEqual(first, second)
        self.assertIn("0xADDR", first)

    def test_a_stable_subtest_param_is_left_alone(self):
        self.assertEqual(
            qualify("odoo.addons.base.tests.test_x", "Subtest T.t (n=3, s='x')"),
            "base/Subtest T.t (n=3, s='x')",
        )

    def test_same_class_and_method_in_two_addons_do_not_collide(self):
        first = qualify("odoo.addons.mail.tests.test_x", "TestCommon.test_default")
        second = qualify("odoo.addons.hr.tests.test_x", "TestCommon.test_default")
        self.assertNotEqual(first, second)


class ScanLogTests(unittest.TestCase):
    def scan(self, text: str) -> Scan:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.log"
            path.write_text(text, encoding="utf-8")
            return scan_log(path)

    def test_a_structured_failure_is_collected(self):
        scan = self.scan(failure("base", "TestMenuMisc.test_multi_copy"))
        self.assertEqual(scan.failures, {"base/TestMenuMisc.test_multi_copy": "FAIL"})

    def test_postgres_error_text_inside_a_passing_test_is_not_a_failure(self):
        # The shape that made the prose table claim two failures that never
        # existed: psycopg's message is an unprefixed continuation line inside a
        # record belonging to a test that passes.
        text = (
            start("base", "TestConcurrentDdl.test_alter")
            + record("ERROR", "odoo.db.cursor", 'bad COPY: COPY "t" ("x") FROM STDIN')
            + "ERROR: descriptor 'toordinal' for 'datetime.date' objects doesn't apply\n"
        )
        self.assertEqual(self.scan(text).failures, {})

    def test_a_plain_error_record_without_a_flavour_is_not_a_failure(self):
        self.assertEqual(
            self.scan(record("ERROR", "odoo.db.pool", "Closed 1 pool(s)")).failures, {}
        )

    def test_an_error_flavour_is_collected_alongside_fail(self):
        scan = self.scan(failure("l10n_ch", "TestSwissQR.test_iban", flavour="ERROR"))
        self.assertEqual(scan.failures["l10n_ch/TestSwissQR.test_iban"], "ERROR")

    def test_phase_banners_are_not_counted_as_tests(self):
        text = record("INFO", "odoo.service.server", "Starting post tests")
        self.assertEqual(self.scan(text).started_count, 0)

    def test_total_prefers_the_servers_own_tally_over_counted_starts(self):
        # A retried test logs Starting twice and a set collapses the pair.
        text = (
            start("qc", "TestA.test_b")
            + start("qc", "TestA.test_b")
            + summary(0, 0, 41)
        )
        scan = self.scan(text)
        self.assertEqual(scan.started_count, 1)
        self.assertEqual(scan.total, 41)

    def test_total_falls_back_to_counted_starts_without_a_summary(self):
        self.assertEqual(self.scan(start("qc", "TestA.test_b")).total, 1)

    def test_a_log_without_a_summary_is_incomplete(self):
        # The shape a server dying mid-run takes. Without this, every expected
        # failure reads as newly-passing and invites banking a green baseline.
        scan = self.scan(failure("qc", "TestA.test_b"))
        self.assertFalse(scan.complete)
        self.assertFalse(scan.sound)

    def test_a_parse_matching_the_server_is_sound(self):
        text = failure("qc", "TestA.test_b") + summary(1, 0, 41)
        self.assertTrue(self.scan(text).sound)

    def test_a_parse_disagreeing_with_the_server_is_unsound(self):
        text = failure("qc", "TestA.test_b") + summary(3, 0, 41)
        self.assertFalse(self.scan(text).sound)

    def test_errors_and_failures_are_both_counted_against_the_summary(self):
        text = (
            failure("qc", "TestA.test_b")
            + failure("qc", "TestA.test_c", flavour="ERROR")
            + summary(1, 1, 41)
        )
        self.assertTrue(self.scan(text).sound)


class EvaluateTests(unittest.TestCase):
    BASE = Baseline(
        suite="/quality_control",
        expected={
            "quality_control/TestQualityCheck.test_backorder": "FAIL",
            "quality_control/TestQualityCheck.test_removal": "FAIL",
        },
        tests_total=38,
    )

    def scan_of(self, names: dict[str, str], total: int) -> Scan:
        return Scan(
            failures=names,
            started=frozenset(),
            reported_failed=len(names),
            reported_total=total,
        )

    def test_the_recorded_set_reported_again_is_green(self):
        verdict = evaluate(
            "/quality_control", self.scan_of(dict(self.BASE.expected), 38), self.BASE
        )
        self.assertEqual(verdict.exit_code, EXIT_OK)
        self.assertEqual(verdict.new, ())
        self.assertEqual(verdict.fixed, ())

    def test_an_equal_count_with_a_swapped_name_is_not_green(self):
        # The measured quality_control case: 2 failed before, 2 failed after,
        # one name replaced. A count comparison calls this "both known".
        swapped = {
            "quality_control/TestQualityCheck.test_removal": "FAIL",
            "quality_control/TestSpreadsheet.test_create": "FAIL",
        }
        verdict = evaluate("/quality_control", self.scan_of(swapped, 41), self.BASE)
        self.assertEqual(verdict.exit_code, EXIT_DRIFT)
        self.assertEqual(verdict.new, ("quality_control/TestSpreadsheet.test_create",))
        self.assertEqual(
            verdict.fixed, ("quality_control/TestQualityCheck.test_backorder",)
        )

    def test_a_newly_passing_test_must_be_banked(self):
        one = {"quality_control/TestQualityCheck.test_removal": "FAIL"}
        verdict = evaluate("/quality_control", self.scan_of(one, 38), self.BASE)
        self.assertEqual(verdict.exit_code, EXIT_DRIFT)
        self.assertEqual(len(verdict.fixed), 1)
        self.assertTrue(any("--update" in line for line in verdict.lines))

    def test_suite_growth_is_reported_as_unbaselined(self):
        verdict = evaluate(
            "/quality_control", self.scan_of(dict(self.BASE.expected), 41), self.BASE
        )
        self.assertEqual(verdict.size_drift, 3)
        self.assertTrue(any("unbaselined" in line for line in verdict.lines))

    def test_no_baseline_refuses_a_verdict(self):
        verdict = evaluate("/whatever", self.scan_of({"a/B.c": "FAIL"}, 10), None)
        self.assertEqual(verdict.exit_code, EXIT_USAGE)
        self.assertTrue(verdict.lines[0].startswith("/whatever: NO BASELINE"))

    def test_an_unfinished_run_refuses_a_verdict(self):
        scan = Scan(failures={}, started=frozenset(), reported_failed=None)
        verdict = evaluate("/quality_control", scan, self.BASE)
        self.assertEqual(verdict.exit_code, EXIT_USAGE)
        self.assertIn("never finished", verdict.lines[0])
        self.assertEqual(verdict.fixed, ())

    def test_an_unsound_parse_refuses_a_verdict(self):
        scan = Scan(
            failures={"a/B.c": "FAIL"},
            started=frozenset(),
            reported_failed=7,
            reported_total=10,
        )
        verdict = evaluate("/base", scan, self.BASE)
        self.assertEqual(verdict.exit_code, EXIT_USAGE)
        self.assertIn("no verdict", verdict.lines[0])


class BaselinePathTests(unittest.TestCase):
    def test_a_leading_slash_is_stripped(self):
        with mock.patch.object(testbaseline, "BASELINES_DIR", Path("/tmp/b")):
            self.assertEqual(testbaseline.baseline_path("/base").name, "base.json")

    def test_a_nested_or_relative_name_is_refused(self):
        for bad in ("/a/b", "..", ".hidden", "/", "a\\b"):
            with self.assertRaises(ValueError, msg=bad):
                testbaseline.baseline_path(bad)


class RoundTripTests(unittest.TestCase):
    def test_a_saved_baseline_loads_back_identical(self):
        with TemporaryDirectory() as tmp:
            with mock.patch.object(testbaseline, "BASELINES_DIR", Path(tmp)):
                original = Baseline(
                    suite="/base",
                    expected={"base/TestA.test_b": "FAIL"},
                    run_spec="-i base --test-tags /base",
                    verified_at="ca4ee2ddd79",
                    tests_total=3284,
                    note="measured",
                )
                original.save()
                self.assertEqual(Baseline.load("/base"), original)

    def test_a_missing_baseline_loads_as_none(self):
        with TemporaryDirectory() as tmp:
            with mock.patch.object(testbaseline, "BASELINES_DIR", Path(tmp)):
                self.assertIsNone(Baseline.load("/absent"))

    def test_the_stored_expected_set_is_sorted(self):
        with TemporaryDirectory() as tmp:
            with mock.patch.object(testbaseline, "BASELINES_DIR", Path(tmp)):
                Baseline(
                    suite="/base", expected={"b/Z.z": "FAIL", "a/A.a": "FAIL"}
                ).save()
                stored = json.loads(
                    (Path(tmp) / "base.json").read_text(encoding="utf-8")
                )
                self.assertEqual(list(stored["expected"]), ["a/A.a", "b/Z.z"])


class MainTests(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = testbaseline.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_update_then_check_is_green(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            log.write_text(
                failure("base", "TestA.test_b") + summary(1, 0, 3284), encoding="utf-8"
            )
            with mock.patch.object(testbaseline, "BASELINES_DIR", Path(tmp)):
                code, out, _ = self.run_main(["/base", str(log), "--update"])
                self.assertEqual(code, EXIT_OK)
                self.assertIn("1 expected of 3284", out)
                code, out, _ = self.run_main(["/base", str(log)])
                self.assertEqual(code, EXIT_OK)
                self.assertIn("GREEN", out)

    def test_update_refuses_an_unfinished_run(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            log.write_text(failure("base", "TestA.test_b"), encoding="utf-8")
            with mock.patch.object(testbaseline, "BASELINES_DIR", Path(tmp)):
                code, _, err = self.run_main(["/base", str(log), "--update"])
                self.assertEqual(code, EXIT_USAGE)
                self.assertIn("unfinished", err)

    def test_update_refuses_an_unsound_parse(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            log.write_text(
                failure("base", "TestA.test_b") + summary(9, 0, 3284), encoding="utf-8"
            )
            with mock.patch.object(testbaseline, "BASELINES_DIR", Path(tmp)):
                code, _, err = self.run_main(["/base", str(log), "--update"])
                self.assertEqual(code, EXIT_USAGE)
                self.assertIn("refusing", err)

    def test_a_bare_invocation_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_main([])
        self.assertEqual(raised.exception.code, EXIT_USAGE)

    def test_a_missing_log_is_a_usage_error(self):
        code, _, err = self.run_main(["/base", "/nonexistent/run.log"])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("no such log", err)

    def test_list_reports_every_recorded_baseline(self):
        with TemporaryDirectory() as tmp:
            with mock.patch.object(testbaseline, "BASELINES_DIR", Path(tmp)):
                Baseline(
                    suite="/base", expected={"base/A.a": "FAIL"}, tests_total=3284
                ).save()
                code, out, _ = self.run_main(["--list"])
                self.assertEqual(code, EXIT_OK)
                self.assertIn("/base", out)
                self.assertIn("3284", out)


if __name__ == "__main__":
    unittest.main()
