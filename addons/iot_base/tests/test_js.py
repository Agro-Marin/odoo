import odoo.tests

import odoo.addons.web.tests.test_js as web_test_js


@odoo.tests.tagged("post_install", "-at_install", "iot_base_js")
class IotBaseSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_iot_base_desktop(self):
        self._run_hoot("@iot_base", preset="desktop")
