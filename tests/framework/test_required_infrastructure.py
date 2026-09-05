import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("policy", "successful", "errors"),
    [(None, False, 2), ("1", False, 2), ("0", True, 0)],
)
def test_missing_infrastructure_cannot_hide_in_a_mixed_suite(
    policy, successful, errors
):
    environment = dict(os.environ)
    environment.pop("ODOO_REQUIRE_INFRA", None)
    if policy is not None:
        environment["ODOO_REQUIRE_INFRA"] = policy
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
from unittest import SkipTest
from odoo.tests.case import TestCase
from odoo.tests.http import HttpCase
from odoo.tests.result import OdooTestResult
from odoo.tests.suite import TestSuite
from odoo.tests.utils import InfrastructureUnavailable

class Passing(TestCase):
    def test_pass(self):
        pass

class DeliberateSkip(TestCase):
    def test_skip(self):
        raise SkipTest('not applicable')

class MissingHttp(HttpCase):
    @classmethod
    def http_port(cls):
        return None

    def test_http(self):
        raise AssertionError('must not run without HTTP')

class MissingBrowser(TestCase):
    def test_browser(self):
        raise InfrastructureUnavailable('browser executable is unavailable')

result = OdooTestResult()
TestSuite([Passing('test_pass'), DeliberateSkip('test_skip'),
           MissingBrowser('test_browser'), MissingHttp('test_http')]).run(result)
print(json.dumps([result.wasSuccessful(), result.errors_count, result.testsRun,
                  result.infrastructure_skipped, result.skipped]))
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == [successful, errors, 3, 2, 3]
