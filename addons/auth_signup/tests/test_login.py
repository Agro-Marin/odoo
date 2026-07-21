# rerun TestWebLogin tests with auth_signup installed
from odoo.addons.web.tests.test_login import (
    TestWebLogin,  # noqa: F401  pylint: disable=W0611
)
