import logging
import sys
from typing import Any
from unittest import BaseTestSuite, TestCase, util

import odoo

from . import case
from .http import HttpCase
from .result import OdooTestResult, stats_logger

__unittest = True


class TestSuite(BaseTestSuite):
    def run(self, result: OdooTestResult, debug: bool = False) -> OdooTestResult:
        for test in self:
            if result.shouldStop:
                break
            assert isinstance(test, TestCase)
            odoo.modules.module.current_test = test
            self._tearDownPreviousClass(test, result)
            self._handleClassSetUp(test, result)
            result._previousTestClass = test.__class__

            if not test.__class__._classSetupFailed:
                test(result)

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
            result.addSkip(error, str(exception))
        elif not info:
            result.addError(error, sys.exc_info())
        else:
            result.addError(error, info)

    def _tearDownPreviousClass(
        self, test: TestCase | None, result: OdooTestResult
    ) -> None:
        previousClass = result._previousTestClass
        currentClass = test.__class__
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
    def _handleClassSetUp(self, test: TestCase, result: OdooTestResult) -> None:
        previous_test_class = result._previousTestClass
        if not (
            previous_test_class is not type(test)
            and hasattr(result, "stats")
            and stats_logger.isEnabledFor(logging.INFO)
        ):
            super()._handleClassSetUp(test, result)
            return

        test_class = type(test)
        test_id = f"{test_class.__module__}.{test_class.__qualname__}.setUpClass"
        with result.collectStats(test_id):
            super()._handleClassSetUp(test, result)

    def _tearDownPreviousClass(
        self, test: TestCase | None, result: OdooTestResult
    ) -> None:
        previous_test_class = result._previousTestClass
        if not (
            previous_test_class
            and previous_test_class is not type(test)
            and hasattr(result, "stats")
            and stats_logger.isEnabledFor(logging.INFO)
        ):
            super()._tearDownPreviousClass(test, result)
            return

        test_id = f"{previous_test_class.__module__}.{previous_test_class.__qualname__}.tearDownClass"
        with result.collectStats(test_id):
            super()._tearDownPreviousClass(test, result)

    def has_http_case(self) -> bool:
        return any(isinstance(test_case, HttpCase) for test_case in self)
