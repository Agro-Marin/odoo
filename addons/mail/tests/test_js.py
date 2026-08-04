"""CI entry point for the ``mail`` addon's HOOT (JS unit) suites.

Mirrors ``web/tests/test_js.py``: the ``static/tests`` tree is fanned out across
several ``test_*`` methods (so a single failing area is isolated and the run can
be sharded) and a coverage walk fails the build the moment a new
``static/tests`` directory is added without being selected by a method. The
runner machinery (hash, ``&id=`` filter, ``_run_hoot`` warm navigation) comes
from ``web``'s ``HOOTCommon``.

Both presets are wired: ``MailSuite`` (desktop) and ``MobileMailSuite`` (375x667
touch viewport), mirroring ``web``'s ``WebSuite`` / ``MobileWebSuite`` pair.
HOOT skips ``desktop``-tagged tests under the mobile preset, so the mobile pass
runs the ``mobile``-tagged files plus every preset-agnostic test against the
small-screen layout.

Fast local runs use the warm-server runner instead:
``tooling/hoot/hoot --db hoot_bus_mail '@mail/discuss'`` (any
suite path; see its README).
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

# Grouped so each method is a bounded run and the fan-out stays shardable.
# Every top-level segment under mail/static/tests MUST appear in exactly one
# group (the coverage walk enforces it). ``discuss`` is by far the largest tree
# so it gets its own method.
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
    # root-level test files (mail/static/tests/*.test.js)
    "@mail/composer_send_icon",
    "@mail/mail_utils",
    "@mail/search",
    "@mail/service_worker_utils",
)
# Union of every prefix some method selects — kept in sync with the methods
# below and checked exhaustively by test_suite_filters_cover_every_test_file.
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
        """@mail/discuss — Discuss client (channels, threads, calls, …)."""
        self._run_hoot("@mail/discuss", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_discuss_app(self):
        """@mail/discuss_app — Discuss app shell (sidebar, notifications, …)."""
        self._run_hoot("@mail/discuss_app", preset="desktop")

    @odoo.tests.no_retry
    def test_core(self):
        """@mail/core — store, messaging models, common core."""
        self._run_hoot("@mail/core", preset="desktop")

    @odoo.tests.no_retry
    def test_web(self):
        """@mail/web — backend view integrations (fields, form/list glue)."""
        self._run_hoot("@mail/web", preset="desktop")

    @odoo.tests.no_retry
    def test_chatter(self):
        """@mail/chatter — chatter, followers, activities on records."""
        self._run_hoot("@mail/chatter", preset="desktop")

    @odoo.tests.no_retry
    def test_thread(self):
        """@mail/thread, message, composer — message rendering & posting."""
        self._run_hoot(*THREAD_SUITES, preset="desktop")

    @odoo.tests.no_retry
    def test_misc(self):
        """Everything else: activity, emoji, chat window/bubble, suggestion,
        translation, widgets, root-level files, etc."""
        self._run_hoot(*MISC_SUITES, preset="desktop", timeout=900)

    def test_suite_filters_cover_every_test_file(self):
        """Every ``static/tests/**/*.test.js`` must be selected by at least one
        method's suite prefix. HOOT ``&id=`` hash filters resolve against suite
        names, so a tests directory no method names simply never runs; this walk
        fails the build the moment one is added or renamed without updating the
        suite lists at the top of this file."""
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
    """The ``mobile`` preset of the mail hoot suites — the counterpart to
    ``web``'s ``MobileWebSuite``. HOOT skips ``desktop``-tagged tests under the
    mobile preset, so this runs the ``mobile``-tagged files and every
    preset-agnostic test against a 375x667 touch viewport. ``-headless``
    excludes the DB-free headless suites (they don't depend on the viewport),
    and the prefixes are the ones the desktop coverage walk already guarantees.
    """

    browser_size = "375x667"
    touch_enabled = True

    @odoo.tests.no_retry
    def test_discuss(self):
        """@mail/discuss under the mobile preset (chat windows, calls, …)."""
        self._run_hoot("@mail/discuss", preset="mobile", tag="-headless", timeout=900)

    @odoo.tests.no_retry
    def test_rest(self):
        """Every other mail suite under the mobile preset."""
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
