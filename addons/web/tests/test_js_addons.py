import odoo.tests

from .test_js import HOOTCommon, uncovered_suites_by_addon

KNOWN_FAILING_ADDONS = frozenset()


@odoo.tests.tagged("post_install", "-at_install", "addon_js", "-web_js")
class AddonSuite(HOOTCommon):
    pass


def _make_run(addon, suites):
    @odoo.tests.no_retry
    def run(self):
        if addon not in self.env["ir.asset"]._get_addons_installed():
            self.skipTest(f"{addon} is not installed on this database")
        if addon in KNOWN_FAILING_ADDONS:
            self.skipTest(f"{addon} is known-failing; see KNOWN_FAILING_ADDONS")
        self._run_hoot(*suites, preset="desktop", timeout=900)

    run.__name__ = f"test_{addon}"
    run.__doc__ = f"@{addon} — {len(suites)} bundled suite(s) no runner selects."
    return run


UNCOVERED_BY_ADDON = uncovered_suites_by_addon()

GENERATED_ADDONS = frozenset(UNCOVERED_BY_ADDON)

for _addon, _suites in UNCOVERED_BY_ADDON.items():
    setattr(AddonSuite, f"test_{_addon}", _make_run(_addon, sorted(_suites)))
