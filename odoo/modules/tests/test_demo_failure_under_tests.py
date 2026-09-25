import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

from odoo.modules import loading
from odoo.tests import result
from odoo.tests.result import OdooTestResult
from odoo.tools import mute_logger


def _loader(report, *, demo_installable=True):
    loader = loading._PackageLoader.__new__(loading._PackageLoader)
    loader.env = MagicMock()
    loader.package = cast(
        "Any",
        SimpleNamespace(
            name="broken_demo",
            id=7,
            demo=False,
            demo_installable=demo_installable,
            manifest={"demo": ["demo/broken.xml"]},
        ),
    )
    loader.operation = "install"
    loader.install_demo = True
    loader.report = report
    return loader


def _install(loader, *, demo_loads):
    with (
        patch.object(loading, "load_data"),
        patch.object(loading, "load_demo", return_value=demo_loads),
        mute_logger("odoo.modules.loading"),
    ):
        loader.load_data_and_demo()


class TestDemoFailureUnderTests(unittest.TestCase):
    def test_a_demo_that_fails_while_tests_run_is_an_error_of_the_run(self):
        report = OdooTestResult()
        _install(_loader(report), demo_loads=False)
        self.assertFalse(report.wasSuccessful())
        self.assertEqual(report.errors_count, 1)
        self.assertEqual(report.demo_failures, ["broken_demo"])
        self.assertIn("broken_demo", str(report))

    def test_a_demo_that_loads_leaves_the_run_successful(self):
        report = OdooTestResult()
        _install(_loader(report), demo_loads=True)
        self.assertTrue(report.wasSuccessful())
        self.assertEqual(report.demo_failures, [])

    def test_a_demo_never_attempted_is_not_a_failure(self):
        report = OdooTestResult()
        loader = _loader(report, demo_installable=False)
        with patch.object(loading, "load_demo") as load_demo:
            _install(loader, demo_loads=False)
        load_demo.assert_not_called()
        self.assertTrue(report.wasSuccessful())

    def test_without_tests_a_demo_failure_stays_a_warning(self):
        loader = _loader(None)
        _install(loader, demo_loads=False)
        self.assertFalse(loader.package.demo)

    def test_the_explicit_opt_out_tolerates_the_failure(self):
        report = OdooTestResult()
        with patch.object(result, "REQUIRE_DEMO", False):
            _install(_loader(report), demo_loads=False)
        self.assertTrue(report.wasSuccessful())
        self.assertEqual(report.demo_failures, [])
