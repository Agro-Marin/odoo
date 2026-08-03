# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""HOOT runner for addons that bundle unit tests but ship no runner of their own.

``_run_hoot`` drives HOOT with ``&id=`` hash filters built from explicit suite
names, so a suite no filter names never runs — silently, since the page still
reports success for the tests it did run. That was 660 test files across 159
addons, 38% of the workspace's HOOT tests, tracked as debt in a hand-maintained
allowlist that only ever grew when someone noticed. ``base_import`` sat there
with 38 tests, two broken, one of them a real UI bug.

This module closes the hole structurally: it generates one test method per
addon that has bundled test files and no runner, so a new addon is covered the
day it lands instead of joining a list. Addons whose suites do not pass yet stay
explicit in :data:`KNOWN_FAILING_ADDONS`, which
``test_js.py::test_every_addon_unit_suite_is_selected_by_a_runner`` asserts is
exact in both directions — it can only shrink.
"""

import odoo.tests

from .test_js import HOOTCommon, uncovered_suites_by_addon

#: Addons whose bundled suites are generated but not yet green. Each entry is a
#: run that fails today, not a suite anyone chose to skip: remove it once the
#: addon passes. Asserted exact, so an addon that starts passing fails the build
#: until it is taken out.
KNOWN_FAILING_ADDONS = frozenset()


@odoo.tests.tagged("post_install", "-at_install", "addon_js", "-web_js")
class AddonSuite(HOOTCommon):
    """One method per addon that bundles HOOT tests and defines no runner.

    ``-web_js`` drops the tag inherited from :class:`HOOTCommon` on purpose:
    ``web_js`` means "web's own JS suites" and is already a 1-2 hour tag, and
    these 158 methods test other addons. They get their own ``addon_js``.
    """


def _make_run(addon, suites):
    @odoo.tests.no_retry
    def run(self):
        if addon not in self.env["ir.asset"]._get_installed_addons_list():
            self.skipTest(f"{addon} is not installed on this database")
        if addon in KNOWN_FAILING_ADDONS:
            self.skipTest(f"{addon} is known-failing; see KNOWN_FAILING_ADDONS")
        self._run_hoot(*suites, preset="desktop", timeout=900)

    run.__name__ = f"test_{addon}"
    run.__doc__ = f"@{addon} — {len(suites)} bundled suite(s) no runner selects."
    return run


UNCOVERED_BY_ADDON = uncovered_suites_by_addon()

#: The addons a method was generated for. Named rather than scraped back off the
#: class, which also carries the test methods inherited from ``HOOTCommon``.
GENERATED_ADDONS = frozenset(UNCOVERED_BY_ADDON)

for _addon, _suites in UNCOVERED_BY_ADDON.items():
    setattr(AddonSuite, f"test_{_addon}", _make_run(_addon, sorted(_suites)))
