import odoo.tests
from odoo.addons.web.tests.test_js import HOOTCommon


@odoo.tests.tagged("post_install", "-at_install", "-web_js", "html_editor_js")
class HtmlEditorSuite(HOOTCommon):
    """HOOT JS tests for the html_editor module.

    Separated from web's test suite so that ``--test-tags 'web_js'``
    no longer runs the ~4 600 html_editor tests (saving ~280 s).
    Run these with ``--test-tags 'html_editor_js'``.
    """

    @odoo.tests.no_retry
    def test_html_editor(self):
        """@html_editor — rich text editor tests (desktop)."""
        self._run_hoot("@html_editor", preset="desktop", timeout=900)


@odoo.tests.tagged("post_install", "-at_install", "-web_js", "html_editor_js")
class MobileHtmlEditorSuite(HOOTCommon):
    """Mobile variant of html_editor HOOT tests."""

    browser_size = "375x667"
    touch_enabled = True

    @odoo.tests.no_retry
    def test_html_editor(self):
        """@html_editor — rich text editor tests (mobile)."""
        self._run_hoot("@html_editor", preset="mobile", tag="-headless", timeout=900)
