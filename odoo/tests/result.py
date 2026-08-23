import collections
import contextlib
import inspect
import logging
import re
import sys
import time
import traceback
from typing import TYPE_CHECKING, Any, NamedTuple

from .. import db
from . import case
from .utils import env_int

if TYPE_CHECKING:
    import types
    from collections.abc import Generator

__unittest = True

_max_failed = env_int("ODOO_TEST_MAX_FAILED_TESTS", 0)
ODOO_TEST_MAX_FAILED_TESTS = _max_failed if _max_failed > 0 else sys.maxsize

REQUIRE_INFRA = bool(env_int("ODOO_REQUIRE_INFRA", 0))
"""Promote InfrastructureUnavailable to a hard error (CI opt-in)."""

stats_logger = logging.getLogger("odoo.tests.stats")


class Stat(NamedTuple):
    time: float = 0.0
    queries: int = 0

    def __add__(self, other: Stat) -> Stat:
        if not isinstance(other, Stat):
            return NotImplemented

        return Stat(
            self.time + other.time,
            self.queries + other.queries,
        )


_logger = logging.getLogger(__name__)
_TEST_ID = re.compile(
    r"""
^
odoo\.addons\.
(?P<module>[^.]+)
\.tests\.
(?P<class>.+)
\.
(?P<method>[^.]+)
$
""",
    re.VERBOSE,
)


class OdooTestResult:
    _previousTestClass = None
    _moduleSetUpFailed = False

    def __init__(
        self,
        stream: Any = None,
        descriptions: Any = None,
        verbosity: Any = None,
        global_report: OdooTestResult | None = None,
    ) -> None:
        self.failures_count = 0
        self.errors_count = 0
        self.testsRun = 0
        self.skipped = 0
        self.infrastructure_skipped = 0
        self.tb_locals = False
        self.time_start = None
        self.queries_start = None
        self._soft_fail = False
        self._is_retry = False
        self.had_failure = False
        self.stats = collections.defaultdict(Stat)
        self.global_report = global_report
        self.shouldStop = (
            self.global_report and self.global_report.shouldStop
        ) or False

    def total_errors_count(self) -> int:
        result = self.errors_count + self.failures_count
        if self.global_report:
            result += self.global_report.total_errors_count()
        return result

    def _checkShouldStop(self) -> None:
        if self.total_errors_count() >= ODOO_TEST_MAX_FAILED_TESTS:
            global_report = self.global_report or self
            if not global_report.shouldStop:
                _logger.error(
                    "Test suite halted: max failed tests already reached (%s). "
                    "Remaining tests will be skipped.",
                    ODOO_TEST_MAX_FAILED_TESTS,
                )
                global_report.shouldStop = True
            self.shouldStop = True

    def printErrors(self) -> None:
        pass

    def startTest(self, test: case.TestCase) -> None:
        if not self._is_retry:
            self.testsRun += 1
        self.log(
            logging.INFO,
            "Starting %s ...",
            self.getDescription(test),
            test=test,
        )
        self.time_start = time.monotonic()
        self.queries_start = db.sql_counter

    def stopTest(self, test: case.TestCase) -> None:
        if stats_logger.isEnabledFor(logging.INFO):
            self.stats[test.id()] = Stat(
                time=time.monotonic() - self.time_start,
                queries=db.sql_counter - self.queries_start,
            )

    def addError(self, test: case.TestCase, err: tuple) -> None:
        if self._soft_fail:
            self.had_failure = True
        else:
            self.errors_count += 1
        self.logError("ERROR", test, err)
        self._checkShouldStop()

    def addFailure(self, test: case.TestCase, err: tuple) -> None:
        if self._soft_fail:
            self.had_failure = True
        else:
            self.failures_count += 1
        self.logError("FAIL", test, err)
        self._checkShouldStop()

    def addSubTest(
        self, test: case.TestCase, subtest: case.TestCase, err: tuple | None
    ) -> None:
        if err is not None:
            if issubclass(err[0], test.failureException):
                self.addFailure(subtest, err)
            else:
                self.addError(subtest, err)

    def addSuccess(self, test: case.TestCase) -> None:
        pass

    def addSkip(
        self, test: case.TestCase, reason: str, infrastructure: bool = False
    ) -> None:
        self.skipped += 1
        if not infrastructure:
            self.log(
                logging.INFO,
                "skipped %s : %s",
                self.getDescription(test),
                reason,
                test=test,
            )
            return

        # The environment could not run this, which is not the same as deciding
        # it should not run. Counted apart so the summary can say so, and an
        # error under ODOO_REQUIRE_INFRA so a host with no browser cannot report
        # a clean pass over a suite that never executed.
        self.infrastructure_skipped += 1
        if REQUIRE_INFRA:
            self.errors_count += 1
            self.log(
                logging.ERROR,
                "INFRASTRUCTURE UNAVAILABLE %s : %s (ODOO_REQUIRE_INFRA=1)",
                self.getDescription(test),
                reason,
                test=test,
            )
            self._checkShouldStop()
        else:
            self.log(
                logging.WARNING,
                "skipped %s : %s (environment cannot run it; "
                "set ODOO_REQUIRE_INFRA=1 to make this an error)",
                self.getDescription(test),
                reason,
                test=test,
            )

    def wasSuccessful(self) -> bool:
        return self.failures_count == self.errors_count == 0

    def _exc_info_to_string(self, err: tuple, test: case.TestCase) -> str:
        exctype, value, tb = err
        while tb and self._is_relevant_tb_level(tb):
            tb = tb.tb_next

        if exctype is test.failureException:
            length = self._count_relevant_tb_levels(tb)
        else:
            length = None
        tb_e = traceback.TracebackException(
            exctype, value, tb, limit=length, capture_locals=self.tb_locals
        )
        msgLines = list(tb_e.format())

        return "".join(msgLines)

    def _is_relevant_tb_level(self, tb: types.TracebackType) -> bool:
        return "__unittest" in tb.tb_frame.f_globals

    def _count_relevant_tb_levels(self, tb: types.TracebackType | None) -> int:
        length = 0
        while tb and not self._is_relevant_tb_level(tb):
            length += 1
            tb = tb.tb_next
        return length

    def __repr__(self):
        return f"<{self.__class__.__module__}.{self.__class__.__qualname__} run={self.testsRun} errors={self.errors_count} failures={self.failures_count}>"

    def __str__(self):
        summary = (
            f"{self.failures_count} failed, {self.errors_count} error(s) "
            f"of {self.testsRun} tests"
        )
        if self.infrastructure_skipped:
            # Never silent: a suite that could not run is not a suite that passed.
            summary += (
                f" ({self.infrastructure_skipped} skipped because the "
                f"environment could not run them)"
            )
        return summary

    @contextlib.contextmanager
    def retry(self) -> Generator[None]:
        previous = self._is_retry
        self._is_retry = True
        try:
            yield
        finally:
            self._is_retry = previous

    @contextlib.contextmanager
    def soft_fail(self) -> Generator[None]:
        self.had_failure = False
        self._soft_fail = True
        try:
            yield
        finally:
            self._soft_fail = False

    def update(self, other: OdooTestResult) -> None:
        self.failures_count += other.failures_count
        self.errors_count += other.errors_count
        self.testsRun += other.testsRun
        self.skipped += other.skipped
        self.infrastructure_skipped += other.infrastructure_skipped
        for test_id, stat in other.stats.items():
            # Sum, don't overwrite: collectStats accumulates with += and
            # setUpClass ids collide when one class runs in both positions.
            self.stats[test_id] += stat

    def log(
        self,
        level: int,
        msg: str,
        *args: Any,
        test: case.TestCase | None = None,
        exc_info: Any = None,
        extra: dict | None = None,
        stack_info: bool = False,
        caller_infos: tuple | None = None,
    ) -> None:
        test = test or self
        while isinstance(test, case._SubTest) and test.test_case:
            test = test.test_case
        logger = logging.getLogger(test.__module__)
        try:
            caller_infos = caller_infos or logger.findCaller(stack_info)
        except ValueError:
            caller_infos = "(unknown file)", 0, "(unknown function)", None
        fn, lno, func, sinfo = caller_infos
        if logger.isEnabledFor(level):
            record = logger.makeRecord(
                logger.name,
                level,
                fn,
                lno,
                msg,
                args,
                exc_info,
                func,
                extra,
                sinfo,
            )
            logger.handle(record)

    def log_stats(self) -> None:
        if not stats_logger.isEnabledFor(logging.INFO):
            return

        details = stats_logger.isEnabledFor(logging.DEBUG)
        stats_tree = collections.defaultdict(Stat)
        counts = collections.Counter()
        for test, stat in self.stats.items():
            r = _TEST_ID.match(test)
            if not r:
                continue

            stats_tree[r["module"]] += stat
            counts[r["module"]] += 1
            if details:
                stats_tree[f"{r['module']}.{r['class']}"] += stat
                stats_tree[f"{r['module']}.{r['class']}.{r['method']}"] += stat

        if details:
            stats_logger.debug(
                "Detailed Tests Report:\n%s",
                "".join(
                    f"\t{test}: {stats.time:.2f}s {stats.queries} queries\n"
                    for test, stats in sorted(stats_tree.items())
                ),
            )
        else:
            for module, stat in sorted(stats_tree.items()):
                stats_logger.info(
                    "%s: %d tests %.2fs %d queries",
                    module,
                    counts[module],
                    stat.time,
                    stat.queries,
                )

    def getDescription(self, test: case.TestCase) -> str:
        if isinstance(test, case._SubTest):
            tc = test.test_case
            return (
                f"Subtest {tc.__class__.__qualname__}"
                f".{tc._testMethodName} {test._subDescription()}"
            )
        if isinstance(test, case.TestCase):
            return f"{test.__class__.__qualname__}.{test._testMethodName}"
        return str(test)

    @contextlib.contextmanager
    def collectStats(self, test_id: str) -> Generator[None]:
        queries_before = db.sql_counter
        time_start = time.monotonic()

        try:
            yield
        finally:
            self.stats[test_id] += Stat(
                time=time.monotonic() - time_start,
                queries=db.sql_counter - queries_before,
            )

    def logError(self, flavour: str, test: case.TestCase, error: tuple) -> None:
        err = self._exc_info_to_string(error, test)
        caller_infos = self.getErrorCallerInfo(error, test)
        self.log(logging.INFO, "=" * 70, test=test, caller_infos=caller_infos)
        self.log(
            logging.ERROR,
            "%s: %s\n%s",
            flavour,
            self.getDescription(test),
            err,
            test=test,
            caller_infos=caller_infos,
        )

    def getErrorCallerInfo(
        self, error: tuple, test: case.TestCase
    ) -> tuple[str, int, str, None] | None:

        if not isinstance(test, case.TestCase):
            return None

        _, _, error_traceback = error

        while isinstance(test, case._SubTest) and test.test_case:
            test = test.test_case

        method_tb = None
        file_tb = None
        filename = inspect.getfile(type(test))

        while error_traceback:
            code = error_traceback.tb_frame.f_code
            if code.co_name in (test._testMethodName, "setUp", "tearDown"):
                method_tb = error_traceback
            if code.co_filename == filename:
                file_tb = error_traceback
            error_traceback = error_traceback.tb_next

        infos_tb = method_tb or file_tb
        if infos_tb:
            code = infos_tb.tb_frame.f_code
            lineno = infos_tb.tb_lineno
            filename = code.co_filename
            method = test._testMethodName
            return (filename, lineno, method, None)
        return None
