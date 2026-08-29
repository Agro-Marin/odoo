import contextlib
import logging
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from unittest import BaseTestSuite, util

import odoo

from . import case
from .case import TestCase
from .http import HttpCase
from .result import OdooTestResult, stats_logger
from .utils import InfrastructureUnavailable

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

__unittest = True


class TestSuite(BaseTestSuite):
    _cleanup: bool
    _removeTestAtIndex: Callable[[int], None]

    def run(  # type: ignore[override]  # this runner requires an OdooTestResult
        self, result: OdooTestResult, debug: bool = False
    ) -> OdooTestResult:
        for index, test in enumerate(self):
            if result.shouldStop:
                break
            assert isinstance(test, TestCase)
            odoo.modules.module.current_test = test
            self._tearDownPreviousClass(test, result)
            self._handleClassSetUp(test, result)
            result._previousTestClass = test.__class__

            if not test.__class__._classSetupFailed:
                test.run(result)

            if self._cleanup:
                self._removeTestAtIndex(index)

        self._tearDownPreviousClass(None, result)
        return result

    def _handleClassSetUp(self, test: TestCase, result: OdooTestResult) -> None:
        previousClass = result._previousTestClass
        currentClass = test.__class__
        if currentClass == previousClass:
            return
        if result._moduleSetUpFailed:
            return
        if currentClass.__unittest_skip__:
            return

        currentClass._classSetupFailed = False

        try:
            currentClass.setUpClass()
        except Exception as e:
            currentClass._classSetupFailed = True
            className = util.strclass(currentClass)
            self._createClassOrModuleLevelException(result, e, "setUpClass", className)
        finally:
            if currentClass._classSetupFailed is True:
                currentClass.doClassCleanups()
                if currentClass.tearDown_exceptions:
                    for exc in currentClass.tearDown_exceptions:
                        self._createClassOrModuleLevelException(
                            result, exc[1], "setUpClass", className, info=exc
                        )

    def _createClassOrModuleLevelException(
        self,
        result: OdooTestResult,
        exception: BaseException,
        method_name: str,
        parent: str,
        info: Any = None,
    ) -> None:
        errorName = f"{method_name} ({parent})"
        error = _ErrorHolder(errorName)
        if isinstance(exception, case.SkipTest):
            result.addSkip(
                error,
                str(exception),
                infrastructure=isinstance(exception, InfrastructureUnavailable),
            )
        elif not info:
            result.addError(error, sys.exc_info())
        else:
            result.addError(error, info)

    def _tearDownPreviousClass(
        self, test: TestCase | None, result: OdooTestResult
    ) -> None:
        previousClass = result._previousTestClass
        currentClass = type(test) if test is not None else None
        if currentClass == previousClass:
            return
        if not previousClass:
            return
        if previousClass._classSetupFailed:
            return
        if previousClass.__unittest_skip__:
            return
        try:
            previousClass.tearDownClass()
        except Exception as e:
            className = util.strclass(previousClass)
            self._createClassOrModuleLevelException(
                result, e, "tearDownClass", className
            )
        finally:
            previousClass.doClassCleanups()
            if previousClass.tearDown_exceptions:
                for exc in previousClass.tearDown_exceptions:
                    className = util.strclass(previousClass)
                    self._createClassOrModuleLevelException(
                        result, exc[1], "tearDownClass", className, info=exc
                    )


class _ErrorHolder:
    failureException = None

    def __init__(self, description: str) -> None:
        self.description = description

    def id(self) -> str:
        return self.description

    def shortDescription(self) -> None:
        return

    def __repr__(self) -> str:
        return f"<ErrorHolder description={self.description!r}>"

    def __str__(self) -> str:
        return self.id()

    def run(self, result: OdooTestResult) -> None:
        pass

    def __call__(self, result: OdooTestResult) -> None:
        return self.run(result)

    def countTestCases(self) -> int:
        return 0


class OdooSuite(TestSuite):
    @staticmethod
    def _timing(
        result: OdooTestResult, measured: type | None, hook: str
    ) -> AbstractContextManager:
        if (
            measured is None
            or not hasattr(result, "stats")
            or not stats_logger.isEnabledFor(logging.INFO)
        ):
            return contextlib.nullcontext()
        return result.collectStats(
            f"{measured.__module__}.{measured.__qualname__}.{hook}"
        )

    def _handleClassSetUp(self, test: TestCase, result: OdooTestResult) -> None:
        entering = type(test) if result._previousTestClass is not type(test) else None
        with self._timing(result, entering, "setUpClass"):
            super()._handleClassSetUp(test, result)

    def _tearDownPreviousClass(
        self, test: TestCase | None, result: OdooTestResult
    ) -> None:
        leaving = result._previousTestClass
        if leaving is type(test):
            leaving = None
        with self._timing(result, leaving, "tearDownClass"):
            super()._tearDownPreviousClass(test, result)

    def has_http_case(self) -> bool:
        return any(isinstance(test_case, HttpCase) for test_case in self)
