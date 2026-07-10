from unittest import SkipTest

from odoo.tests.common import standalone
from odoo.tests.module_operations import install
from odoo.tools import mute_logger
from odoo.tools.convert import ParseError


@standalone("test_isolated_install")
def test_isolated_install(env):
    """Check that a module failing to install leaves preceding modules installed."""
    MODULE_NAMES = [
        "test_install_base",
        "test_install_auto",
        "test_install_fail",
    ]
    modules = {
        module.name: module
        for module in env["ir.module.module"].search([("name", "in", MODULE_NAMES)])
    }
    if len(modules) < 3:
        raise SkipTest(f"Failed to find the required modules {MODULE_NAMES}")
    if not all(module.state == "uninstalled" for module in modules.values()):
        raise SkipTest(f"The modules {MODULE_NAMES} should not be installed")

    # test_install_fail depends on base and auto, so both install just before it
    try:
        with mute_logger("odoo.modules.registry"):
            install(
                env.cr.dbname,
                modules["test_install_fail"].id,
                "test_install_fail",
            )
    except ParseError:
        pass

    env.cr.rollback()
    env.transaction.reset()

    cron = env["ir.cron"].search([("cron_name", "=", "test_install_auto_cron")])
    assert cron, "The cron 'test_install_auto_cron' has not been created"

    assert modules["test_install_base"].state == "installed", (
        "Module 'test_install_base' not installed"
    )
    assert modules["test_install_auto"].state == "installed", (
        "Module 'test_install_auto' not installed"
    )
    assert modules["test_install_fail"].state == "uninstalled", (
        "Module 'test_install_fail' should be uninstalled"
    )

    assert env["res.currency"]._test_install_auto_cron() is True, (
        "Cron code not working"
    )
