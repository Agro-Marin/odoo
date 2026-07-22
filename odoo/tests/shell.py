__all__ = ["run_tests"]

import logging
import re
import sys
from typing import Any

from psycopg.pq import TransactionStatus

import odoo
from odoo.modules.registry import Registry

from .loader import make_suite, run_suite
from .result import OdooTestResult

_logger = logging.getLogger(__name__)

TEST_MODULE_NAME_PATTERN = re.compile(r"^odoo\.addons\.\w+\.tests")


def run_tests(
    env: Any,
    test_tags: str,
    modules: list[str] | None = None,
    reload_tests: bool = False,
) -> OdooTestResult | None:
    """Run tests for the given modules and test tags."""

    if odoo.cli.COMMAND != "shell":
        _logger.error("run_tests should be used only in odoo shell")
        return None

    if odoo.tools.config["workers"] != 0:
        _logger.error("run_tests should be used only in threaded mode")
        return None

    from odoo.service.lifecycle import server

    if not server.httpd:
        # some tests need the http daemon to be available...
        server.http_spawn()

    if env.cr.connection.info.transaction_status != TransactionStatus.IDLE:
        # rollback the cr in case it holds a database lock which may cause deadlock while running tests
        _logger.warning("Rolling back the transaction before testing")
        env.cr.rollback()

    if not modules:
        modules = sorted(env.registry._init_modules)

    if reload_tests:
        _clear_loaded_test_modules()

    # restore in a finally: leaving test_enable set after a failed run would
    # leave the whole shell session in test mode (test cursors, test dispatch)
    old_test_tags = odoo.tools.config["test_tags"]
    old_test_enable = odoo.tools.config["test_enable"]
    odoo.tools.config["test_tags"] = test_tags
    odoo.tools.config["test_enable"] = True
    try:
        report = _run_tests(env.cr.dbname, modules)
    finally:
        odoo.tools.config["test_enable"] = old_test_enable
        odoo.tools.config["test_tags"] = old_test_tags

    _log_test_report(report)

    return report


def _run_tests(db_name: str, modules: list[str]) -> OdooTestResult:
    """Run at_install and post_install test suites for the given modules."""
    report = OdooTestResult()

    # Run at_install tests
    with Registry._lock:
        registry = Registry(db_name)
        try:
            # best effort to restore the test environment
            registry.loaded = False
            registry.ready = False
            at_install_suite = make_suite(modules, "at_install")
            if at_install_suite.countTestCases():
                _logger.info("Starting at_install tests")
                report.update(run_suite(at_install_suite, report))
        finally:
            registry.loaded = True
            registry.ready = True

    # Run post_install tests
    post_install_suite = make_suite(modules, "post_install")
    if post_install_suite.countTestCases():
        _logger.info("Starting post_install tests")
        report.update(run_suite(post_install_suite, report))

    return report


def _clear_loaded_test_modules() -> None:
    """Clear loaded test modules that may have been modified."""
    for module_key in list(sys.modules):
        if TEST_MODULE_NAME_PATTERN.match(module_key):
            _logger.debug("Removing module from sys.modules for reload: %s", module_key)
            del sys.modules[module_key]


def _log_test_report(report: OdooTestResult) -> None:
    """Log a summary of the test report at the appropriate log level."""
    if not report.wasSuccessful():
        _logger.error("Tests failed: %s", report)
    elif not report.testsRun:
        _logger.warning("No tests executed: %s", report)
    else:
        _logger.info("Tests passed: %s", report)
