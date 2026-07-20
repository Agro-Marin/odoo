"""Test case implementation"""

import contextlib
import inspect
import logging
import sys
from pathlib import PurePath
from typing import TYPE_CHECKING, Any
from unittest import SkipTest
from unittest import TestCase as _TestCase

if TYPE_CHECKING:
    import types
    from collections.abc import Generator

_logger = logging.getLogger(__name__)


__unittest = True

_subtest_msg_sentinel = object()


class _Outcome:
    def __init__(self, test: TestCase, result: Any) -> None:
        self.result = result
        self.success = True
        self.test = test

    @contextlib.contextmanager
    def testPartExecutor(
        self, test_case: TestCase, isTest: bool = False
    ) -> Generator[None]:
        try:
            yield
        except KeyboardInterrupt:
            raise
        except SkipTest as e:
            self.success = False
            self.result.addSkip(test_case, str(e))
        except BaseException:  # record any failure; KeyboardInterrupt is re-raised above
            exc_info = sys.exc_info()
            self.success = False

            if exc_info is not None:
                exception_type, exception, tb = exc_info
                tb = self._complete_traceback(tb)
                exc_info = (exception_type, exception, tb)
            self.test._addError(self.result, test_case, exc_info)

            # explicitly break a reference cycle:
            # exc_info -> frame -> exc_info
            exc_info = None

    def _complete_traceback(
        self, initial_tb: types.TracebackType
    ) -> types.TracebackType:
        Traceback = type(initial_tb)

        # make the set of frames in the traceback
        tb_frames = set()
        tb = initial_tb
        while tb:
            tb_frames.add(tb.tb_frame)
            tb = tb.tb_next
        tb = initial_tb

        # find the common frame by searching the last frame of the current_stack present in the traceback.
        current_frame = inspect.currentframe()
        common_frame = None
        while current_frame:
            if current_frame in tb_frames:
                common_frame = current_frame  # we want to find the last frame in common
            current_frame = current_frame.f_back

        if not common_frame:  # not really useful but safer
            _logger.warning(
                "No common frame found with current stack, displaying full stack"
            )
            tb = initial_tb
        else:
            # remove the tb_frames until the common_frame is reached (keep the current_frame tb since the line is more accurate)
            while tb and tb.tb_frame != common_frame:
                tb = tb.tb_next

        # add all current frame elements under the common_frame to tb
        current_frame = common_frame.f_back
        while current_frame:
            tb = Traceback(
                tb, current_frame, current_frame.f_lasti, current_frame.f_lineno
            )
            current_frame = current_frame.f_back

        # remove traceback root part (odoo_bin, main, loading, ...), as
        # everything above the testCase is not useful. Cut at '_callTestMethod',
        # '_callSetUp', '_callTearDown' or '_callCleanup' rather than the test
        # method, since the error may not come from the test method itself.
        while tb:
            code = tb.tb_frame.f_code
            if PurePath(code.co_filename).name == "case.py" and code.co_name in (
                "_callTestMethod",
                "_callSetUp",
                "_callTearDown",
                "_callCleanup",
            ):
                return tb.tb_next
            tb = tb.tb_next

        _logger.warning("No root frame found, displaying full stacks")
        return initial_tb  # this shouldn't be reached


class TestCase(_TestCase):
    _class_cleanups = []
    __unittest_skip__ = False
    __unittest_skip_why__ = ""
    _moduleSetUpFailed = False

    # pylint: disable=super-init-not-called
    def __init__(self, methodName: str = "runTest") -> None:
        """Create an instance of the class that will use the named test
        method when executed. Raises a ValueError if the instance does
        not have a method with the specified name.
        """
        self._testMethodName = methodName
        self._outcome = None
        if methodName != "runTest" and not hasattr(self, methodName):
            # we allow instantiation with no explicit method name
            # but not an *incorrect* or missing method name
            raise ValueError(f"no such test method in {self.__class__}: {methodName}")
        self._cleanups = []
        self._subtest = None

        # Map types to custom assertEqual functions that will compare
        # instances of said type in more detail to generate a more useful
        # error message.
        self._type_equality_funcs = {}
        self.addTypeEqualityFunc(dict, "assertDictEqual")
        self.addTypeEqualityFunc(list, "assertListEqual")
        self.addTypeEqualityFunc(tuple, "assertTupleEqual")
        self.addTypeEqualityFunc(set, "assertSetEqual")
        self.addTypeEqualityFunc(frozenset, "assertSetEqual")
        self.addTypeEqualityFunc(str, "assertMultiLineEqual")

    def addCleanup(self, function: Any, *args: Any, **kwargs: Any) -> None:
        """Add a function, with arguments, to be called when the test is
        completed. Functions added are called on a LIFO basis and are
        called after tearDown on test failure or success.

        Cleanup items are called even if setUp fails (unlike tearDown)."""
        self._cleanups.append((function, args, kwargs))

    @classmethod
    def addClassCleanup(cls, function: Any, *args: Any, **kwargs: Any) -> None:
        """Same as addCleanup, except the cleanup items are called even if
        setUpClass fails (unlike tearDownClass)."""
        cls._class_cleanups.append((function, args, kwargs))

    def shortDescription(self) -> None:
        return None

    @contextlib.contextmanager
    def subTest(
        self, msg: Any = _subtest_msg_sentinel, **params: Any
    ) -> Generator[None]:
        """Return a context manager that will return the enclosed block
        of code in a subtest identified by the optional message and
        keyword parameters.  A failure in the subtest marks the test
        case as failed but resumes execution at the end of the enclosed
        block, allowing further test code to be executed.
        """
        parent = self._subtest
        if parent:
            params = {
                **params,
                **{k: v for k, v in parent.params.items() if k not in params},
            }
        self._subtest = _SubTest(self, msg, params)
        try:
            with self._outcome.testPartExecutor(self._subtest, isTest=True):
                yield
        finally:
            self._subtest = parent

    def _addError(self, result: Any, test: TestCase, exc_info: tuple | None) -> None:
        """Route a single error/failure to the result.

        Handles subtest errors the 3.7-3.10 way; kept on the test case so
        test_test_suite can override it.
        """
        if isinstance(test, _SubTest):
            result.addSubTest(test.test_case, test, exc_info)
        elif exc_info is not None:
            if issubclass(exc_info[0], self.failureException):
                result.addFailure(test, exc_info)
            else:
                result.addError(test, exc_info)

    def _callSetUp(self) -> None:
        self.setUp()

    def _callTestMethod(self, method: Any) -> None:
        method()

    def _callTearDown(self) -> None:
        self.tearDown()

    def _callCleanup(self, function: Any, *args: Any, **kwargs: Any) -> None:
        function(*args, **kwargs)

    def run(self, result: Any) -> Any:
        result.startTest(self)

        testMethod = getattr(self, self._testMethodName)

        skip = False
        skip_why = ""
        try:
            skip = self.__class__.__unittest_skip__ or testMethod.__unittest_skip__
            skip_why = (
                self.__class__.__unittest_skip_why__
                or testMethod.__unittest_skip_why__
                or ""
            )
        except (
            AttributeError
        ):  # testMethod may not have a __unittest_skip__ or __unittest_skip_why__
            pass
        if skip:
            result.addSkip(self, skip_why)
            result.stopTest(self)
            return None

        outcome = _Outcome(self, result)
        try:
            self._outcome = outcome
            with outcome.testPartExecutor(self):
                self._callSetUp()
            if outcome.success:
                with outcome.testPartExecutor(self, isTest=True):
                    self._callTestMethod(testMethod)
                with outcome.testPartExecutor(self):
                    self._callTearDown()

            self.doCleanups()
            if outcome.success:
                result.addSuccess(self)
            return result
        finally:
            result.stopTest(self)

            # clear the outcome, no more needed
            self._outcome = None

    def doCleanups(self) -> None:
        """Execute all cleanup functions. Normally called for you after
        tearDown."""

        while self._cleanups:
            function, args, kwargs = self._cleanups.pop()
            with self._outcome.testPartExecutor(self):
                self._callCleanup(function, *args, **kwargs)

    @classmethod
    def doClassCleanups(cls) -> None:
        """Execute all class cleanup functions. Normally called for you after
        tearDownClass."""
        cls.tearDown_exceptions = []
        while cls._class_cleanups:
            function, args, kwargs = cls._class_cleanups.pop()
            try:
                function(*args, **kwargs)
            except Exception:
                cls.tearDown_exceptions.append(sys.exc_info())

    @property
    def canonical_tag(self):
        module = self.__module__
        for prefix in ("odoo.addons.", "odoo.upgrade."):
            module = module.removeprefix(prefix)

        module = module.replace(".", "/")
        return f"/{module}.py:{self.__class__.__name__}.{self._testMethodName}"

    def get_log_metadata(self) -> dict[str, str]:
        """Return metadata dict for log records emitted by this test."""
        return {
            "canonical_tag": self.canonical_tag,
        }


class _SubTest(TestCase):
    def __init__(
        self, test_case: TestCase, message: Any, params: dict[str, Any]
    ) -> None:
        super().__init__()
        self._message = message
        self.test_case = test_case
        self.params = params
        self.failureException = test_case.failureException

    def runTest(self) -> None:
        raise NotImplementedError("subtests cannot be run directly")

    def _subDescription(self) -> str:
        parts = []
        if self._message is not _subtest_msg_sentinel:
            parts.append(f"[{self._message}]")
        if self.params:
            params_desc = ", ".join(f"{k}={v!r}" for (k, v) in self.params.items())
            parts.append(f"({params_desc})")
        return " ".join(parts) or "(<subtest>)"

    def id(self) -> str:
        return f"{self.test_case.id()} {self._subDescription()}"

    def __str__(self) -> str:
        return f"{self.test_case} {self._subDescription()}"
