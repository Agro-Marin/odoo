import odoo.tests

from odoo.addons.web.tests.test_js import HOOTCommon


@odoo.tests.tagged("post_install", "-at_install", "web_js")
class PortalSignatureFormSuite(HOOTCommon):

    @odoo.tests.no_retry
    def test_signature_form(self):
        self._run_hoot("@portal/signature_form", preset="desktop", timeout=300)
