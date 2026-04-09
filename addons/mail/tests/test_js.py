import odoo.tests

from odoo.addons.web.tests.test_js import HOOTCommon


@odoo.tests.tagged("post_install", "-at_install", "mail_js")
class MailSuite(HOOTCommon):
    """Hoot JS unit tests for the mail module."""

    @odoo.tests.no_retry
    def test_mail(self):
        """Run all @mail Hoot JS unit tests (desktop)."""
        self._run_hoot("@mail", preset="desktop", timeout=1200)

    @odoo.tests.no_retry
    def test_mail_mobile(self):
        """Run all @mail Hoot JS unit tests (mobile)."""
        self.browser_size = "375x667"
        self.touch_enabled = True
        self._run_hoot("@mail", preset="mobile", tag="-headless", timeout=1200)
