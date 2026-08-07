import contextlib
import difflib
import logging
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import PurePath
from unittest import SkipTest, skip
from unittest.mock import patch

from odoo.db import Cursor
from odoo.orm.models.mixins._crud_common import COPY_THRESHOLD
from odoo.tests.benchmark import compute_stats
from odoo.tests.case import TestCase
from odoo.tests.common import (
    _DELEGATING_STATEMENTS,
    _STATEMENT_RECORDERS,
    BaseCase,
    HttpCase,
    RegistryRLock,
    TransactionCase,
    mute_logger,
    users,
    warmup,
)
from odoo.tests.cursor import TestCursor
from odoo.tests.result import OdooTestResult
from odoo.tests.utils import env_int

_logger = logging.getLogger(__name__)


class TestTestSuite(TestCase):
    test_tags = {"standard", "at_install"}
    test_module = "base"

    def test_test_suite(self):

        def get_method_additional_tags(self, method):
            return []


class TestRunnerLoggingCommon(TransactionCase):
    def setUp(self):
        self.expected_logs = None
        self.expected_first_frame_methods = None
        return super().setUp()

    def _addError(self, result, test, exc_info):
        try:
            self.test_result = result

            if exc_info:
                tb = exc_info[2]
                self._check_first_frame(tb)

            log_records = []

            def makeRecord(
                logger,
                name,
                level,
                fn,
                lno,
                msg,
                args,
                exc_info,
                func=None,
                extra=None,
                sinfo=None,
            ):
                log_records.append(
                    {
                        "logger": logger,
                        "name": name,
                        "level": level,
                        "fn": fn,
                        "lno": lno,
                        "msg": msg % args,
                        "exc_info": exc_info,
                        "func": func,
                        "extra": extra,
                        "sinfo": sinfo,
                    }
                )

            def handle(logger, record):
                return

            fake_result = OdooTestResult()
            with (
                patch("logging.Logger.makeRecord", makeRecord),
                patch("logging.Logger.handle", handle),
            ):
                super()._addError(fake_result, test, exc_info)

            self._check_log_records(log_records)

        except Exception:
            _logger.exception("unexpected exception in _feedErrorsToResult")

    def _check_first_frame(self, tb):
        if self.expected_first_frame_methods is None:
            expected_first_frame_method = self._testMethodName
        else:
            expected_first_frame_method = self.expected_first_frame_methods.pop(0)
        if expected_first_frame_method.endswith("_with_decorators"):
            return
        first_frame_method = tb.tb_frame.f_code.co_name
        if first_frame_method != expected_first_frame_method:
            self._log_error(
                f"Checking first tb frame: {first_frame_method} is not equal to {expected_first_frame_method}"
            )

    def _check_log_records(self, log_records):
        for log_record in log_records:
            self._assert_log_equal(log_record, "logger", _logger)
            self._assert_log_equal(
                log_record, "name", "odoo.addons.base.tests.test_test_suite"
            )
            self._assert_log_equal(log_record, "fn", __file__)
            self._assert_log_equal(log_record, "func", self._testMethodName)

        if self.expected_logs is not None:
            for log_record in log_records:
                level, msg = self.expected_logs.pop(0)
                self._assert_log_equal(log_record, "level", level)
                self._assert_log_equal(log_record, "msg", msg)

    def _assert_log_equal(self, log_record, key, expected):
        value = log_record[key]
        if key == "msg":
            value = self._clean_message(value)
        if value != expected:
            if key != "msg":
                self._log_error(
                    f"Key `{key}` => `{value}` is not equal to `{expected}` \n {log_record['msg']}"
                )
            else:
                diff = "\n".join(
                    difflib.ndiff(expected.splitlines(), value.splitlines())
                )
                self._log_error(f"Key `{key}` did not matched expected:\n{diff}")

    def _log_error(self, message):
        self.test_result.addError(self, (AssertionError, AssertionError(message), None))

    def _clean_message(self, message):
        root_path = PurePath(__file__).parents[4]
        python_path = PurePath(contextlib.__file__).parent
        message = re.sub(r"line \d+", "line $line", message)
        message = re.sub(r"py:\d+", "py:$line", message)
        message = re.sub(r"decorator-gen-\d+", "decorator-gen-xxx", message)
        message = re.sub(r"^\s*~*\^+~*\s*\n", "", message, flags=re.MULTILINE)
        message = re.sub(r"\.\.\.<\d+ lines>\.\.\.", "...<$elided>...", message)
        message = message.replace(f'"{root_path}', '"/root_path/odoo')
        message = message.replace(f'"{python_path}', '"/usr/lib/python')
        return message.replace("\\", "/")


class TestRunnerLogging(TestRunnerLoggingCommon):
    def setUp(self):
        old_level = _logger.level
        _logger.setLevel(logging.INFO)
        self.addCleanup(_logger.setLevel, old_level)
        return super().setUp()

    def test_has_add_error(self):
        self.assertTrue(hasattr(self, "_addError"))

    def test_raise(self):
        raise Exception("This is an error")

    def test_raise_subtest(self):

        def make_message(message):
            return f"""ERROR: Subtest TestRunnerLogging.test_raise_subtest (<subtest>)
Traceback (most recent call last):
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in test_raise_subtest
    raise Exception("{message}")
Exception: {message}
"""

        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, make_message("This is an error")),
        ]
        with self.subTest():
            raise Exception("This is an error")
        self.assertFalse(self.expected_logs, "Error should have been logged immediatly")

        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, make_message("This is an error2")),
        ]

        with self.subTest():
            raise Exception("This is an error2")
        self.assertFalse(self.expected_logs, "Error should have been logged immediatly")

    @users("__system__")
    @warmup
    def test_with_decorators(self):
        message = """ERROR: Subtest TestRunnerLogging.test_with_decorators (login='__system__')
Traceback (most recent call last):
  File "/root_path/odoo/odoo/tests/common.py", line $line, in with_users
    func(self, *args, **kwargs)
  File "/root_path/odoo/odoo/tests/common.py", line $line, in warmup
    func(self, *args, **kwargs)
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in test_with_decorators
    raise Exception("This is an error")
Exception: This is an error
"""
        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, message),
        ]
        raise Exception("This is an error")

    def test_traverse_contextmanager(self):
        @contextmanager
        def assertSomething():
            yield
            raise Exception("This is an error")

        with assertSomething():
            pass

    def test_subtest_sub_call(self):
        def func():
            with self.subTest():
                raise Exception("This is an error")

        func()

    def test_call_stack(self):
        message = """ERROR: TestRunnerLogging.test_call_stack
Traceback (most recent call last):
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in test_call_stack
    alpha()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in alpha
    beta()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in beta
    gamma()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in gamma
    raise Exception("This is an error")
Exception: This is an error
"""
        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, message),
        ]

        def alpha():
            beta()

        def beta():
            gamma()

        def gamma():
            raise Exception("This is an error")

        alpha()

    def test_call_stack_context_manager(self):
        message = """ERROR: TestRunnerLogging.test_call_stack_context_manager
Traceback (most recent call last):
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in test_call_stack_context_manager
    alpha()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in alpha
    beta()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in beta
    gamma()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in gamma
    raise Exception("This is an error")
Exception: This is an error
"""
        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, message),
        ]

        def alpha():
            beta()

        def beta():
            with self.with_user("admin"):
                gamma()
                return 0

        def gamma():
            raise Exception("This is an error")

        alpha()

    def test_call_stack_subtest(self):
        message = """ERROR: Subtest TestRunnerLogging.test_call_stack_subtest (<subtest>)
Traceback (most recent call last):
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in test_call_stack_subtest
    alpha()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in alpha
    beta()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in beta
    gamma()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in gamma
    raise Exception("This is an error")
Exception: This is an error
"""
        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, message),
        ]

        def alpha():
            beta()

        def beta():
            with self.subTest():
                gamma()

        def gamma():
            raise Exception("This is an error")

        alpha()

    def test_assertQueryCount(self):
        message = """FAIL: Subtest TestRunnerLogging.test_assertQueryCount (<subtest>)
Traceback (most recent call last):
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in test_assertQueryCount
    with self.assertQueryCount(system=0):
  File "/usr/lib/python/contextlib.py", line $line, in __exit__
    next(self.gen)
  File "/root_path/odoo/odoo/tests/common.py", line $line, in assertQueryCount
    self.fail(
        "Query count more than expected for user %s: %d > %d in %s at %s:%s"
    ...<$elided>...
        )
    )
AssertionError: Query count more than expected for user __system__: 1 > 0 in test_assertQueryCount at base/tests/test_test_suite.py:$line
"""
        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, message),
        ]
        with self.assertQueryCount(system=0):
            self.env.cr.execute("SELECT 1")

    @users("__system__")
    @warmup
    def test_assertQueryCount_with_decorators(self):
        with self.assertQueryCount(system=0):
            self.env.cr.execute("SELECT 1")

    def test_reraise(self):
        message = """ERROR: TestRunnerLogging.test_reraise
Traceback (most recent call last):
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in test_reraise
    alpha()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in alpha
    beta()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in beta
    raise Exception("This is an error")
Exception: This is an error
"""
        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, message),
        ]

        def alpha():
            try:
                beta()
            except Exception:
                raise

        def beta():
            raise Exception("This is an error")

        alpha()

    def test_handle_error(self):
        message = """ERROR: TestRunnerLogging.test_handle_error
Traceback (most recent call last):
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in alpha
    beta()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in beta
    raise Exception("This is an error")
Exception: This is an error

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in test_handle_error
    alpha()
  File "/root_path/odoo/odoo/addons/base/tests/test_test_suite.py", line $line, in alpha
    raise Exception("This is an error2") from err
Exception: This is an error2
"""
        self.expected_logs = [
            (logging.INFO, "=" * 70),
            (logging.ERROR, message),
        ]

        def alpha():
            try:
                beta()
            except Exception as err:
                raise Exception("This is an error2") from err

        def beta():
            raise Exception("This is an error")

        alpha()


class TestRunnerLoggingSetup(TestRunnerLoggingCommon):
    def setUp(self):
        super().setUp()
        self.expected_first_frame_methods = [
            "setUp",
            "cleanupError2",
            "cleanupError",
        ]

        def cleanupError():
            raise Exception("This is a cleanup error")

        self.addCleanup(cleanupError)

        def cleanupError2():
            raise Exception("This is a second cleanup error")

        self.addCleanup(cleanupError2)

        raise Exception("This is a setup error")

    def test_raises_setup(self):
        _logger.error("This shouldn't be executed")

    def tearDown(self):
        _logger.error("This shouldn't be executed since setup failed")


class TestRunnerLoggingTeardown(TestRunnerLoggingCommon):
    def setUp(self):
        super().setUp()
        self.expected_first_frame_methods = [
            "test_raises_teardown",
            "test_raises_teardown",
            "test_raises_teardown",
            "tearDown",
            "cleanupError2",
            "cleanupError",
        ]

        def cleanupError():
            raise Exception("This is a cleanup error")

        self.addCleanup(cleanupError)

        def cleanupError2():
            raise Exception("This is a second cleanup error")

        self.addCleanup(cleanupError2)

    def tearDown(self):
        raise Exception("This is a tearDown error")

    def test_raises_teardown(self):
        with self.subTest():
            raise Exception("This is a subTest error")
        with self.subTest():
            raise Exception("This is a second subTest error")
        raise Exception("This is a test error")


class TestSubtests(BaseCase):
    def test_nested_subtests(self):
        with self.subTest(a=1, x=2):
            with self.subTest(b=3, x=4):
                self.assertEqual(self._subtest._subDescription(), "(b=3, x=4, a=1)")
            with self.subTest(b=5, x=6):
                self.assertEqual(self._subtest._subDescription(), "(b=5, x=6, a=1)")


class TestClassSetup(BaseCase):
    @classmethod
    def setUpClass(cls):
        raise SkipTest("Skip this class")

    def test_method(self):
        pass


class TestClassTeardown(BaseCase):
    @classmethod
    def tearDownClass(cls):
        raise SkipTest("Skip this class")

    def test_method(self):
        pass


class Test01ClassCleanups(BaseCase):
    executed = False
    cleanup = False

    @classmethod
    def setUpClass(cls):
        cls.executed = True

        def doCleanup():
            cls.cleanup = True

        cls.addClassCleanup(doCleanup)

    def test_dummy(self):
        pass


class Test02ClassCleanupsCheck(BaseCase):
    def test_classcleanups(self):
        self.assertTrue(
            Test01ClassCleanups.executed,
            "This test only makes sence when executed after Test01ClassCleanups",
        )
        self.assertTrue(
            Test01ClassCleanups.cleanup,
            "TestClassCleanup shoudl have been cleanuped",
        )


@skip
class TestSkipClass(BaseCase):
    def test_classcleanups(self):
        raise Exception("This should be skipped")


class TestSkipMethof(BaseCase):
    @skip
    def test_skip_method(self):
        raise Exception("This should be skipped")


class TestRegistryRLock(BaseCase):
    def test_registry_rlock_count(self):
        lock = RegistryRLock()
        for i in range(5):
            self.assertEqual(lock.count, i)
            lock.acquire()
        for i in range(5):
            self.assertEqual(lock.count, 5 - i)
            lock.release()


class TestCursorStack(TransactionCase):
    def test_out_of_order_close(self):
        lock = threading.RLock()
        cr1 = self.registry.cursor()
        cr2 = self.registry.cursor()
        tc1 = TestCursor(cr1, lock, readonly=False)
        tc2 = TestCursor(cr2, lock, readonly=False)

        def cleanup():
            for tc in (tc1, tc2):
                if not tc._closed:
                    tc.close()
            cr1.close()
            cr2.close()

        self.addCleanup(cleanup)

        with self.assertLogs("odoo.db.cursor", level="WARNING"):
            tc1.close()
        self.assertNotIn(tc1, TestCursor._cursors_stack)
        self.assertIn(tc2, TestCursor._cursors_stack)
        self.assertFalse(tc2._closed)

        tc2.close()
        self.assertNotIn(tc2, TestCursor._cursors_stack)

    def test_readonly_nesting_enforced_lazily(self):
        lock = threading.RLock()
        cr_ro = self.registry.cursor()
        cr_rw = self.registry.cursor()
        tc_ro = TestCursor(cr_ro, lock, readonly=True)

        def cleanup():
            if not tc_ro._closed:
                tc_ro.close()
            cr_ro.close()
            cr_rw.close()

        self.addCleanup(cleanup)

        tc_rw = TestCursor(cr_rw, lock, readonly=False)
        tc_rw.close()

        tc_ro.execute("SELECT 1")
        with self.assertRaisesRegex(Exception, "read/write test cursor"):
            TestCursor(cr_rw, lock, readonly=False)
        self.assertEqual([tc_ro], TestCursor._cursors_stack)


class TestBenchmarkStats(BaseCase):
    def test_compute_stats_raw_extremes_joint_trim(self):
        times = [100.0] * 19 + [10000.0]
        db_times = [60.0] * 19 + [9990.0]
        query_counts = [3] * 19 + [50]
        stats = compute_stats("t", times, query_counts, db_times)

        self.assertEqual(stats.iterations, 20)
        self.assertEqual(stats.total_samples, 19)
        self.assertEqual(stats.min_us, 100.0)
        self.assertEqual(stats.max_us, 10000.0)
        self.assertAlmostEqual(stats.mean_us, 100.0)
        self.assertAlmostEqual(stats.db_time_us, 60.0)
        self.assertAlmostEqual(stats.db_ratio, 0.6)
        self.assertAlmostEqual(stats.query_count_mean, 3.0)
        self.assertEqual(stats.query_count_max, 50)

    def test_compute_stats_ratio_bounded(self):
        times = [100.0] * 9 + [1000.0]
        db_times = [99.0] * 9 + [999.0]
        stats = compute_stats("t", times, [1] * 10, db_times)
        self.assertLessEqual(stats.db_ratio, 1.0)
        self.assertGreaterEqual(stats.python_time_us, 0.0)

    def test_compute_stats_small_sample_untrimmed(self):
        stats = compute_stats("t", [1.0, 2.0, 3.0], [1, 1, 1], [0.5, 0.5, 0.5])
        self.assertEqual(stats.total_samples, 3)
        self.assertEqual(stats.max_us, 3.0)


class TestEnvInt(BaseCase):
    def test_env_int(self):
        var = "ODOO_TEST_ENV_INT_PROBE"
        self.assertEqual(env_int(var, 3), 3)
        for raw, expected in [("", 3), (" ", 3), ("0", 0), ("42", 42), ("-1", -1)]:
            with self.subTest(raw=raw), patch.dict(os.environ, {var: raw}):
                self.assertEqual(env_int(var, 3), expected)
        with patch.dict(os.environ, {var: "nope"}), self.assertRaises(ValueError):
            env_int(var, 3)


class TestRetryAccounting(BaseCase):
    class _Case(BaseCase):
        test_tags = {"standard"}
        test_module = "base"
        attempts = 0
        failures_wanted = 0

        def test_probe(self):
            type(self).attempts += 1
            if self.attempts <= self.failures_wanted:
                raise AssertionError("deliberate")

    def _run(self, retries, failures_wanted=0):
        case = type("Probe", (self._Case,), {})
        case.failures_wanted = failures_wanted
        case._tests_run_count = retries + 1
        result = OdooTestResult()
        with mute_logger(__name__):
            case("test_probe").run(result)
        return case.attempts, result

    def test_passing_test_is_counted_once_with_retries(self):
        for retries in (0, 1, 3):
            with self.subTest(retries=retries):
                attempts, result = self._run(retries)
                self.assertEqual(attempts, 1)
                self.assertEqual(result.testsRun, 1)
                self.assertTrue(result.wasSuccessful())

    def test_flaky_test_is_counted_once(self):
        attempts, result = self._run(retries=2, failures_wanted=2)
        self.assertEqual(attempts, 3, "should have retried twice")
        self.assertEqual(result.testsRun, 1)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.failures_count, 0, "soft failures must not count")

    def test_always_failing_test_is_counted_once_and_fails(self):
        attempts, result = self._run(retries=1, failures_wanted=99)
        self.assertEqual(attempts, 2)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.failures_count, 1)


class TestPatchExecuteStatementApi(TransactionCase):
    def test_every_marked_entry_point_is_recorded(self):
        marked = {
            name
            for name in dir(Cursor)
            if callable(getattr(Cursor, name, None))
            and getattr(getattr(Cursor, name), "__code__", None) is not None
            and "_before_statement" in getattr(Cursor, name).__code__.co_names
        }
        self.assertTrue(marked, "Cursor marks no statement entry points at all")
        self.assertEqual(
            sorted(marked),
            sorted(set(_STATEMENT_RECORDERS) | _DELEGATING_STATEMENTS),
            "every statement entry point must either be recorded or be known "
            "to reach the server through execute()",
        )

    def _capture(self, func):
        self.warm = False
        with self.assertQueries([], flush=False) as caught:
            func()
        self.warm = True
        return list(caught)

    def test_executemany_is_recorded_once(self):
        caught = self._capture(
            lambda: self.cr.executemany("SELECT %s::int", [(1,), (2,), (3,)])
        )
        self.assertEqual(caught, ["SELECT %s::int"])

    def test_execute_values_is_recorded_once_via_execute(self):
        self.cr.execute("CREATE TEMP TABLE _probe_ev (n int)")
        caught = self._capture(
            lambda: self.cr.execute_values(
                "INSERT INTO _probe_ev (n) VALUES %s", [(1,), (2,)]
            )
        )
        self.assertEqual(caught, ["INSERT INTO _probe_ev (n) VALUES (%s), (%s)"])

    def test_copy_from_is_recorded_as_a_copy(self):
        self.cr.execute("CREATE TEMP TABLE _probe_cp (a int, b text)")
        caught = self._capture(
            lambda: self.cr.copy_from("_probe_cp", ["a", "b"], [(1, "x"), (2, "y")])
        )
        self.assertEqual(caught, ['COPY "_probe_cp" ("a", "b") FROM STDIN'])

    def _bulk_create(self):
        self.env["res.partner"].create(
            [{"name": f"probe {i}"} for i in range(COPY_THRESHOLD + 2)]
        )
        self.env.flush_all()

    def test_bulk_create_write_is_visible(self):
        caught = self._capture(self._bulk_create)
        self.assertTrue(
            any(q.startswith('COPY "res_partner"') for q in caught),
            f"the COPY that inserted the rows is missing from {caught}",
        )

    def test_captured_queries_are_always_strings(self):
        caught = self._capture(self._bulk_create)
        self.assertTrue(caught)
        for query in caught:
            self.assertIsInstance(query, str)
        self._normalize_query(caught[0])
        "\n".join(caught)


class TestReadonlyModeIsTestScoped(TransactionCase):
    def test_a_disables_readonly(self):
        self.registry_enter_test_mode(register_cleanup=True)
        self.set_registry_readonly_mode(False)
        self.assertFalse(type(self)._registry_readonly_enabled)

    def test_b_sees_the_default_again(self):
        self.assertTrue(
            type(self)._registry_readonly_enabled,
            "readonly enforcement leaked out of the previous test",
        )


class Test03LeakPatchers(BaseCase):
    class Target:
        a = 1
        b = 2
        c = 3

    def test_leak_three_patchers(self):
        for name, value in (("a", 10), ("b", 20), ("c", 30)):
            patch.object(self.Target, name, value).start()


class Test04LeakedPatchersCheck(BaseCase):
    def test_every_leaked_patcher_was_stopped(self):
        target = Test03LeakPatchers.Target
        self.addCleanup(setattr, target, "a", 1)
        self.addCleanup(setattr, target, "b", 2)
        self.addCleanup(setattr, target, "c", 3)
        self.assertEqual(
            (target.a, target.b, target.c),
            (1, 2, 3),
            "patchers leaked by the previous class survived its cleanup",
        )


class TestCompleteTraceback(BaseCase):
    def test_detached_traceback_falls_back_to_the_full_stack(self):
        from odoo.tests.case import _Outcome

        captured = {}

        def in_another_thread():
            try:
                raise RuntimeError("detached")
            except RuntimeError:
                captured["tb"] = sys.exc_info()[2]

        thread = threading.Thread(target=in_another_thread)
        thread.start()
        thread.join()

        outcome = _Outcome(self, OdooTestResult())
        with self.assertLogs("odoo.tests.case", "WARNING"):
            result = outcome._complete_traceback(captured["tb"])
        self.assertIs(result, captured["tb"])


class TestBaseCaseDefaults(BaseCase):
    def test_subclass_outside_addons_is_constructible(self):
        outside = type(
            "Outside",
            (BaseCase,),
            {"__module__": "some.third.party", "test_x": lambda self: None},
        )
        self.assertIsNone(outside.test_tags, "the class keeps the sentinel")
        case = outside("test_x")
        self.assertEqual(case.test_tags, set(), "the instance gets a usable set")
        self.assertEqual(case.test_module, "")

    def test_framework_bases_keep_the_untagged_sentinel(self):
        for base in (BaseCase, TransactionCase, HttpCase):
            with self.subTest(base=base.__name__):
                self.assertIsNone(
                    base.test_tags,
                    "consuming the sentinel drops every addon subclass "
                    "of this base out of test selection",
                )
