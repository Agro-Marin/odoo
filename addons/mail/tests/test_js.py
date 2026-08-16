from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

THREAD_SUITES = ("@mail/thread", "@mail/message", "@mail/composer")
MISC_SUITES = (
    "@mail/activity",
    "@mail/chat_bubble",
    "@mail/chat_window",
    "@mail/crosstab",
    "@mail/emoji",
    "@mail/gif_picker",
    "@mail/html_editor",
    "@mail/inline",
    "@mail/messaging",
    "@mail/messaging_menu",
    "@mail/mobile",
    "@mail/mock_server",
    "@mail/patch_235_regression",
    "@mail/quick_reaction_menu",
    "@mail/scheduled_message",
    "@mail/suggestion",
    "@mail/translation",
    "@mail/utils",
    "@mail/views",
    "@mail/widgets",
    "@mail/composer_send_icon",
    "@mail/mail_utils",
    "@mail/search",
    "@mail/service_worker_utils",
)
ALL_MAIL_SUITE_PREFIXES = (
    "@mail/discuss",
    "@mail/discuss_app",
    "@mail/core",
    "@mail/web",
    "@mail/chatter",
    *THREAD_SUITES,
    *MISC_SUITES,
)


@odoo.tests.tagged("post_install", "-at_install", "mail_js")
class MailSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_discuss(self):
        self._run_hoot("@mail/discuss", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_discuss_app(self):
        self._run_hoot("@mail/discuss_app", preset="desktop")

    @odoo.tests.no_retry
    def test_core(self):
        self._run_hoot("@mail/core", preset="desktop")

    @odoo.tests.no_retry
    def test_web(self):
        self._run_hoot("@mail/web", preset="desktop")

    @odoo.tests.no_retry
    def test_chatter(self):
        self._run_hoot("@mail/chatter", preset="desktop")

    @odoo.tests.no_retry
    def test_thread(self):
        self._run_hoot(*THREAD_SUITES, preset="desktop")

    @odoo.tests.no_retry
    def test_misc(self):
        self._run_hoot(*MISC_SUITES, preset="desktop", timeout=900)

    def test_suite_filters_cover_every_test_file(self):
        tests_root = Path(file_path("mail/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@mail/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_MAIL_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "Mail test files selected by no CI suite filter (they will never "
            "run):\n- " + "\n- ".join(uncovered),
        )


@odoo.tests.tagged("post_install", "-at_install", "mail_js")
class MobileMailSuite(web_test_js.HOOTCommon):
    browser_size = "375x667"
    touch_enabled = True

    @odoo.tests.no_retry
    def test_discuss(self):
        self._run_hoot("@mail/discuss", preset="mobile", tag="-headless", timeout=900)

    @odoo.tests.no_retry
    def test_rest(self):
        self._run_hoot(
            "@mail/discuss_app",
            "@mail/core",
            "@mail/web",
            "@mail/chatter",
            *THREAD_SUITES,
            *MISC_SUITES,
            preset="mobile",
            tag="-headless",
            timeout=900,
        )
