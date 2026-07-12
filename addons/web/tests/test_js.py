import re
from contextlib import suppress
from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_open, file_path

RE_FORBIDDEN_STATEMENTS = re.compile(r"test.*\.(only|debug)\(")

# Suite name lists shared by the desktop and mobile classes AND by
# test_suite_filters_cover_every_test_file below. HOOT ``&id=`` filters fail
# open (zero matched tests still printed the success signal until the runner
# was hardened), so every static/tests directory MUST appear in one of these
# lists or its tests silently never run in CI — 13 files (~183 tests) were
# lost that way once. Keep new tests-directory names in sync here.
GRAPH_PIVOT_SUITES = (
    "@web/views/graph",
    "@web/views/pivot",
    "@web/views/pivot_view",
    "@web/views/view_components",
    "@web/views/view_compiler",
    "@web/views/view_dialogs",
    "@web/views/widgets",
    "@web/views/layout",
    "@web/views/view_button",
    "@web/views/view_buttons",
    "@web/views/view_button_hook",
    "@web/views/view_service",
    "@web/views/view",
    "@web/views/view_utils",
    "@web/views/module_views",
)
MISC_SUITES = (
    "@web/env",
    "@web/reactivity",
    "@web/t_custom_click",
    "@web/helpers",
    "@web/interactions",
    "@web/l10n",
    "@web/legacy_js",
    "@web/mock_server",
    "@web/modules",
)
# Union of every suite prefix some CI method selects (html_editor lives in
# its own addon and is not part of the web tests tree walk).
ALL_WEB_SUITE_PREFIXES = (
    "@web/core",
    "@web/components",
    "@web/services",
    "@web/ui",
    "@web/views/calendar",
    "@web/views/fields",
    "@web/views/form",
    "@web/views/kanban",
    "@web/views/list",
    *GRAPH_PIVOT_SUITES,
    "@web/search",
    "@web/webclient",
    "@web/public",
    "@web/model",
    *MISC_SUITES,
)


def unit_test_error_checker(message):
    return "[HOOT]" not in message



def _get_filters(test_params):
    filters = []
    for sign, param in test_params:
        parts = param.split(",")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            part_sign = sign
            if part.startswith("-"):
                part = part[1:]
                part_sign = "-" if sign == "+" else "+"
            filters.append((part_sign, part))
    return sorted(filters)


@odoo.tests.tagged("post_install", "-at_install", "web_js")
class HOOTCommon(odoo.tests.HttpCase):
    def setUp(self):
        super().setUp()
        self.hoot_filters = self.get_hoot_filters()

    def _generate_hash(self, test_string):
        hash_val = 0
        for char in test_string:
            hash_val = (hash_val << 5) - hash_val + ord(char)
            hash_val = hash_val & 0xFFFFFFFF
        return f"{hash_val:08x}"

    def get_hoot_filters(self):
        filters = _get_filters(self._test_params)
        id_params = ""
        for sign, f in filters:
            h = self._generate_hash(f)
            if sign == "-":
                h = f"-{h}"
            # The hash doesn't distinguish a test from a suite, so pass it as
            # a generic "job" id filter (HOOT resolves it against either).
            id_params += f"&id={h}"
        return id_params

    def test_generate_hoot_hash(self):
        self.assertEqual(self._generate_hash("@web/core"), "e39ce9ba")
        self.assertEqual(
            self._generate_hash("@web/core/autocomplete"), "69a6561d"
        )  # suite
        self.assertEqual(
            self._generate_hash("@web/core/autocomplete/open dropdown on input"),
            "ee565d54",
        )  # test

    def test_get_hoot_filter(self):
        self._test_params = []
        self.assertEqual(self.get_hoot_filters(), "")
        expected = "&id=e39ce9ba&id=-69a6561d"
        self._test_params = [("+", "@web/core,-@web/core/autocomplete")]
        self.assertEqual(self.get_hoot_filters(), expected)
        self._test_params = [
            ("+", "@web/core"),
            ("-", "@web/core/autocomplete"),
        ]
        self.assertEqual(self.get_hoot_filters(), expected)
        self._test_params = [("+", "-@web/core/autocomplete,-@web/core/autocomplete2")]
        self.assertEqual(self.get_hoot_filters(), "&id=-69a6561d&id=-cb246db5")
        self._test_params = [("-", "-@web/core/autocomplete,-@web/core/autocomplete2")]
        self.assertEqual(self.get_hoot_filters(), "&id=69a6561d&id=cb246db5")

    def _run_hoot(self, *suite_names, preset, timeout=600, tag="", extra=""):
        """Run specific hoot test suites by their module path.

        Each suite_name (e.g. '@web/core') is hashed and passed as ``&id=``
        filter parameters so that only matching suites execute.

        When ``--test-tags`` supplies explicit suite/test paths (e.g.
        ``--test-tags '/web:@web/core/domain'`` for one suite, or a full test
        path for one test), those override the method's default ``suite_names``
        so a single suite or a single test can be driven without editing this
        file. HOOT resolves each ``&id=`` against either a suite or a test, so a
        full test path narrows the run to one test — the key lever for a fast
        edit/run loop (see web/tooling/scripts/hoot for a warm-server runner).
        """
        if self.hoot_filters:
            id_filters = self.hoot_filters
        else:
            id_filters = "".join(f"&id={self._generate_hash(n)}" for n in suite_names)
        tag_param = f"&tag={tag}" if tag else ""
        self.browser_js(
            f"/web/tests?headless&loglevel=2&preset={preset}&timeout=15000{id_filters}{tag_param}{extra}",
            "",
            "",
            login="admin",
            timeout=timeout,
            success_signal="[HOOT] Test suite succeeded",
            error_checker=unit_test_error_checker,
        )


@odoo.tests.tagged("post_install", "-at_install", "web_js")
class WebSuite(HOOTCommon):
    @odoo.tests.no_retry
    def test_core(self):
        """@web/core — domain, registry, network, py_js, utils, l10n."""
        self._run_hoot("@web/core", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_components(self):
        """@web/components — reusable UI components (dropdown, dialog, etc.)."""
        self._run_hoot("@web/components", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_services(self):
        """@web/services — ORM, hotkeys, commands, field service, etc."""
        self._run_hoot("@web/services", preset="desktop")

    @odoo.tests.no_retry
    def test_ui(self):
        """@web/ui — dialog, notification, popover, tooltip, overlay."""
        self._run_hoot("@web/ui", preset="desktop")

    @odoo.tests.no_retry
    def test_calendar(self):
        """@web/views/calendar — calendar view tests."""
        self._run_hoot("@web/views/calendar", preset="desktop")

    @odoo.tests.no_retry
    def test_fields(self):
        """@web/views/fields — all field widget tests."""
        self._run_hoot("@web/views/fields", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_form(self):
        """@web/views/form — form view tests."""
        self._run_hoot("@web/views/form", preset="desktop")

    @odoo.tests.no_retry
    def test_kanban(self):
        """@web/views/kanban — kanban view tests."""
        self._run_hoot("@web/views/kanban", preset="desktop")

    @odoo.tests.no_retry
    def test_list(self):
        """@web/views/list — list view tests."""
        self._run_hoot("@web/views/list", preset="desktop")

    @odoo.tests.no_retry
    def test_graph_pivot(self):
        """Graph, pivot, view components/dialogs/widgets, and root view files."""
        self._run_hoot(*GRAPH_PIVOT_SUITES, preset="desktop")

    @odoo.tests.no_retry
    def test_search(self):
        """@web/search — search bar, filters, groupby, favorites, etc."""
        self._run_hoot("@web/search", preset="desktop")

    @odoo.tests.no_retry
    def test_webclient(self):
        """@web/webclient — action manager, navbar, settings, etc."""
        self._run_hoot("@web/webclient", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_public(self):
        """@web/public — public page components."""
        self._run_hoot("@web/public", preset="desktop")

    @odoo.tests.no_retry
    def test_html_editor(self):
        """@html_editor — rich text editor tests."""
        self._run_hoot("@html_editor", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_model(self):
        """@web/model — relational model, record utils, command builder."""
        self._run_hoot("@web/model", preset="desktop")

    @odoo.tests.no_retry
    def test_misc(self):
        """Root-level test files (env, reactivity, t_custom_click) plus the
        infrastructure suites: mock server meta-tests, module loader, l10n
        utils, legacy Class/publicWidget ports, test helpers, interactions."""
        self._run_hoot(*MISC_SUITES, preset="desktop")

    @odoo.tests.no_retry
    def test_hoot(self):
        """Run HOOT's own internal test suite (the test framework's tests,
        not the @web/... suites covered by the other test_* methods)."""
        self.browser_js(
            f"/web/static/lib/hoot/tests/index.html?headless&loglevel=2{self.hoot_filters}",
            "",
            "",
            login="admin",
            timeout=1800,
            success_signal="[HOOT] Test suite succeeded",
            error_checker=unit_test_error_checker,
        )

    def test_check_suite(self):
        """Check that no HOOT test uses only() or debug()."""
        self._check_forbidden_statements("web.assets_unit_tests")

    def test_suite_filters_cover_every_test_file(self):
        """Every ``static/tests/**/*.test.js`` must be selected by at least
        one CI suite filter in ALL_WEB_SUITE_PREFIXES.

        HOOT ``&id=`` hash filters resolve against suite names, so a tests
        directory that no method names simply never runs — and, before the
        runner was hardened to fail on zero matched tests, reported success.
        13 files (~183 tests: mock_server, l10n, legacy_js, modules,
        interactions, helpers, view_compiler) were silently lost that way.
        This walk fails the build the moment a tests directory is added or
        renamed without updating the suite lists at the top of this file.
        """
        tests_root = Path(file_path("web/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            if rel.startswith(("_framework/", "tours/")):
                # _framework is the mock-server implementation; tours run
                # through web.assets_tests, not the HOOT unit runner.
                continue
            suite = "@web/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_WEB_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "Test files selected by no CI suite filter (they will never run):"
            "\n- " + "\n- ".join(uncovered),
        )

    def _check_forbidden_statements(self, bundle):
        # As we currently are not in a request context, we cannot render `web.layout`.
        # We then re-define it as a minimal proxy template.
        self.env.ref("web.layout").write(
            {
                "arch_db": '<t t-name="web.layout"><html><head><meta charset="utf-8"/><link/><script id="web.layout.odooscript"/><meta/><t t-esc="head"/></head><body><t t-out="0"/></body></html></t>'
            }
        )

        assets = self.env["ir.qweb"]._get_asset_content(bundle)[0]
        if len(assets) == 0:
            self.fail("No assets found in the given test bundle")

        for asset in assets:
            filename = asset["filename"]
            if not filename.endswith(".test.js"):
                continue
            with suppress(FileNotFoundError):
                with file_open(filename, "rb", filter_ext=(".js",)) as fp:
                    if RE_FORBIDDEN_STATEMENTS.search(fp.read().decode("utf-8")):
                        self.fail(
                            "`only()` or `debug()` used in file %r" % asset["url"]
                        )


@odoo.tests.tagged("post_install", "-at_install", "web_js")
class MobileWebSuite(HOOTCommon):
    browser_size = "375x667"
    touch_enabled = True

    @odoo.tests.no_retry
    def test_core(self):
        """@web/core — domain, registry, network, py_js, utils, l10n."""
        self._run_hoot("@web/core", preset="mobile", tag="-headless", timeout=900)

    @odoo.tests.no_retry
    def test_components(self):
        """@web/components — reusable UI components (dropdown, dialog, etc.)."""
        self._run_hoot("@web/components", preset="mobile", tag="-headless", timeout=900)

    @odoo.tests.no_retry
    def test_services(self):
        """@web/services — ORM, hotkeys, commands, field service, etc."""
        self._run_hoot("@web/services", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_ui(self):
        """@web/ui — dialog, notification, popover, tooltip, overlay."""
        self._run_hoot("@web/ui", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_calendar(self):
        """@web/views/calendar — calendar view tests."""
        self._run_hoot("@web/views/calendar", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_fields(self):
        """@web/views/fields — all field widget tests."""
        self._run_hoot(
            "@web/views/fields", preset="mobile", tag="-headless", timeout=900
        )

    @odoo.tests.no_retry
    def test_form(self):
        """@web/views/form — form view tests."""
        self._run_hoot("@web/views/form", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_kanban(self):
        """@web/views/kanban — kanban view tests."""
        self._run_hoot("@web/views/kanban", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_list(self):
        """@web/views/list — list view tests."""
        self._run_hoot("@web/views/list", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_graph_pivot(self):
        """Graph, pivot, view components/dialogs/widgets, and root view files."""
        self._run_hoot(*GRAPH_PIVOT_SUITES, preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_search(self):
        """@web/search — search bar, filters, groupby, favorites, etc."""
        self._run_hoot("@web/search", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_webclient(self):
        """@web/webclient — action manager, navbar, settings, etc."""
        self._run_hoot("@web/webclient", preset="mobile", tag="-headless", timeout=900)

    @odoo.tests.no_retry
    def test_public(self):
        """@web/public — public page components."""
        self._run_hoot("@web/public", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_html_editor(self):
        """@html_editor — rich text editor tests."""
        self._run_hoot("@html_editor", preset="mobile", tag="-headless", timeout=900)

    @odoo.tests.no_retry
    def test_model(self):
        """@web/model — relational model, record utils, command builder."""
        self._run_hoot("@web/model", preset="mobile", tag="-headless")

    @odoo.tests.no_retry
    def test_misc(self):
        """Root-level test files plus infrastructure suites (see WebSuite)."""
        self._run_hoot(*MISC_SUITES, preset="mobile", tag="-headless")
