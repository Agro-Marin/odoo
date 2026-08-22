import odoo.tests

import odoo.addons.web.tests.test_js as web_test_js


@odoo.tests.tagged("post_install", "-at_install", "bus_js")
class BusSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_bus_desktop(self):
        self._run_hoot("@bus", preset="desktop", timeout=900)
