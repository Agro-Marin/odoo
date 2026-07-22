# Inline string literals in raise statements, bare Exception, blind except
# handlers, and trivial re-raises are all intentional: the exact source lines
# appear in tracebacks, and these tests assert on traceback content.
import contextlib
import difflib
import logging
import re
import threading
from contextlib import contextmanager
from pathlib import PurePath
from unittest import SkipTest, skip
from unittest.mock import patch

from odoo.tests.benchmark import compute_stats
from odoo.tests.case import TestCase
from odoo.tests.common import (
    BaseCase,
    RegistryRLock,
    TransactionCase,
    users,
    warmup,
)
from odoo.tests.cursor import TestCursor
from odoo.tests.result import OdooTestResult

_logger = logging.getLogger(__name__)


# ensures simple tests keep working even when BaseCase would be used; only
# works if doClassCleanup is available on testCase (vendoring of suite.py).
class TestTestSuite(TestCase):
    test_tags = {"standard", "at_install"}
    test_module = "base"

    def test_test_suite(self):
        """Check that OdooSuite handles unittest.TestCase correctly."""

        def get_method_additional_tags(self, method):
            return []


class TestRunnerLoggingCommon(TransactionCase):
    """Metatesting: check that on error the runner logs it with the right file
    reference (guards against errors in tests/common.py or tests/runner.py).
    Tricky because the logs happen outside the test method, after teardown.
    """

    def setUp(self):
        self.expected_logs = None
        self.expected_first_frame_methods = None
        return super().setUp()

    def _addError(self, result, test, exc_info):
        # Hook to catch the logged error. Called post-tearDown; thanks to
        # tests.common._ErrorCatcher the errors are logged directly. This
        # method can be temporarily renamed to test the real failure.
        try:
            self.test_result = result
            # check the first frame of the stack is inside the test method

            if exc_info:
                tb = exc_info[2]
                self._check_first_frame(tb)

            # intercept all ir_logging; log catchers don't work here because
            # makeRecord is too low level
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
                # disable error logging
                return

            fake_result = OdooTestResult()
            with (
                patch("logging.Logger.makeRecord", makeRecord),
                patch("logging.Logger.handle", handle),
            ):
                super()._addError(fake_result, test, exc_info)

            self._check_log_records(log_records)

        except Exception:
            # _feedErrorsToResult() shouldn't raise; be robust to future changes
            _logger.exception("unexpected exception in _feedErrorsToResult")

    def _check_first_frame(self, tb):
        """Check that the first frame of the given traceback is the expected method name."""
        # expected_first_frame_methods holds a list of expected first frames
        # (useful for setup/teardown tests)
        if self.expected_first_frame_methods is None:
            expected_first_frame_method = self._testMethodName
        else:
            expected_first_frame_method = self.expected_first_frame_methods.pop(0)
        if expected_first_frame_method.endswith("_with_decorators"):
            # For decorators the first frame need not match the test name; it
            # already appears in the stack trace. See odoo/odoo#108202.
            return
        first_frame_method = tb.tb_frame.f_code.co_name
        if first_frame_method != expected_first_frame_method:
            self._log_error(
                f"Checking first tb frame: {first_frame_method} is not equal to {expected_first_frame_method}"
            )

    def _check_log_records(self, log_records):
        """Check that what was logged is what was expected."""
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
        """Check the content of a log record."""
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
        """Log an actual error (about a log in a test that doesn't match expectations)"""
        # use test_result (not plain logging) to keep the test counters correct
        self.test_result.addError(self, (AssertionError, AssertionError(message), None))

    def _clean_message(self, message):
        root_path = PurePath(__file__).parents[
            4
        ]  # removes /odoo/addons/base/tests/test_test_suite.py
        python_path = PurePath(
            contextlib.__file__
        ).parent  # /usr/lib/pythonx.x, C:\\python\\Lib, ...
        message = re.sub(r"line \d+", "line $line", message)
        message = re.sub(r"py:\d+", "py:$line", message)
        message = re.sub(r"decorator-gen-\d+", "decorator-gen-xxx", message)
        message = re.sub(r"^\s*~*\^+~*\s*\n", "", message, flags=re.MULTILINE)
        # Python 3.14 elides multi-line source in tracebacks with ...<N lines>...
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
        """With subtest, expect multiple errors, one per subtest."""

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
    """With Test02ClassCleanupsCheck, checks that class cleanups run."""

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
        """Closing a non-top TestCursor must remove *that* cursor, not evict
        the still-open top of the stack."""
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
            tc1.close()  # out of order: tc2 is the top of the stack
        self.assertNotIn(tc1, TestCursor._cursors_stack)
        self.assertIn(tc2, TestCursor._cursors_stack)
        self.assertFalse(tc2._closed)

        tc2.close()  # normal close, no warning
        self.assertNotIn(tc2, TestCursor._cursors_stack)


class TestBenchmarkStats(BaseCase):
    def test_compute_stats_raw_extremes_joint_trim(self):
        """min/max report raw extremes; query/DB samples are trimmed jointly
        with the timing samples (same iterations dropped)."""
        times = [100.0] * 19 + [10000.0]
        db_times = [60.0] * 19 + [9990.0]
        query_counts = [3] * 19 + [50]
        stats = compute_stats("t", times, query_counts, db_times)

        self.assertEqual(stats.iterations, 20)
        self.assertEqual(stats.total_samples, 19)  # outlier iteration trimmed
        self.assertEqual(stats.min_us, 100.0)
        self.assertEqual(stats.max_us, 10000.0)  # raw, not trimmed, extremes
        self.assertAlmostEqual(stats.mean_us, 100.0)
        # the outlier iteration's DB time and query count are dropped with it
        self.assertAlmostEqual(stats.db_time_us, 60.0)
        self.assertAlmostEqual(stats.db_ratio, 0.6)
        self.assertAlmostEqual(stats.query_count_mean, 3.0)
        self.assertEqual(stats.query_count_max, 50)

    def test_compute_stats_ratio_bounded(self):
        """With per-iteration db <= wall samples, db_ratio stays <= 1 because
        both means are computed over the same iteration subset."""
        times = [100.0] * 9 + [1000.0]
        db_times = [99.0] * 9 + [999.0]
        stats = compute_stats("t", times, [1] * 10, db_times)
        self.assertLessEqual(stats.db_ratio, 1.0)
        self.assertGreaterEqual(stats.python_time_us, 0.0)

    def test_compute_stats_small_sample_untrimmed(self):
        stats = compute_stats("t", [1.0, 2.0, 3.0], [1, 1, 1], [0.5, 0.5, 0.5])
        self.assertEqual(stats.total_samples, 3)
        self.assertEqual(stats.max_us, 3.0)
