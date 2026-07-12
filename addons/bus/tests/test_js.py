"""CI entry point for the ``bus`` addon's HOOT (JS unit) suites.

Historically the ``bus`` JS test files (``static/tests/**/*.test.js``) were
bundled into ``web.assets_unit_tests`` but **no** ``test_js.py`` ever selected
them, so ``@bus/...`` suites never ran as a gated CI check — regressions there
went unnoticed. This class wires them in, mirroring
``web/tests/test_js.py::WebSuite`` but selecting the ``@bus`` suite tree.

The runner machinery (hash, ``&id=`` filter, ``_run_hoot`` warm-navigation) is
reused verbatim from ``web`` via the ``HOOTCommon`` base. It is imported through
the module object (``web_test_js.HOOTCommon``) rather than ``from ... import
HOOTCommon`` on purpose: binding the name into this module's namespace would make
Odoo's unittest loader collect ``web``'s base meta-tests a second time under the
``bus`` module.

Every ``bus`` test file registers its suite under the ``@bus/...`` path, so the
single ``@bus`` id filter resolves to the parent suite and runs **all**
descendants — a new ``static/tests`` file is covered automatically, with no
per-directory suite list to keep in sync (unlike ``web``, which fans out across
many prefixes and needs ``test_suite_filters_cover_every_test_file``).

Fast local runs use the warm-server runner instead:
``addons/web/tooling/scripts/hoot --db hoot_bus '@bus'`` (see its README).
"""

import odoo.tests

import odoo.addons.web.tests.test_js as web_test_js


@odoo.tests.tagged("post_install", "-at_install", "bus_js")
class BusSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_bus_desktop(self):
        """@bus — every bus JS (HOOT) suite, desktop preset."""
        self._run_hoot("@bus", preset="desktop", timeout=900)

    # A mobile preset pass (see web/tests/test_js.py::MobileWebSuite) can be
    # added once @bus is confirmed green under the mobile preset; desktop is
    # the validated baseline.
