# Part of Odoo. See LICENSE file for full copyright and licensing details.

import odoo.tests

from odoo.addons.web.tests.test_js import HOOTCommon


@odoo.tests.tagged("post_install", "-at_install", "web_js")
class PortalSignatureFormSuite(HOOTCommon):
    """Run the portal SignatureForm hoot suite.

    Portal ships no hoot tests by default, so its suite is not registered in
    web/tests/test_js.py's suite lists. This class drives the single portal
    suite explicitly, the same way WebSuite drives the @web/* ones.
    """

    @odoo.tests.no_retry
    def test_signature_form(self):
        self._run_hoot("@portal/signature_form", preset="desktop", timeout=300)
