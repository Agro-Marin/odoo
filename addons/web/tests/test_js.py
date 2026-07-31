import ast
import re
from contextlib import suppress
from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_open, file_path

import odoo.addons

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
    "@web/libs",
    "@web/mock_server",
    "@web/modules",
)
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

#: Addons that bundle ``*.test.js`` into ``web.assets_unit_tests`` while no
#: runner selects those suites, so they never execute. Asserted to be exact by
#: ``test_every_addon_unit_suite_is_selected_by_a_runner``: it may only shrink,
#: and a new addon in this situation fails the build instead of joining it.
#:
#: Two entries are not "no runner at all" but a runner that misses files:
#: ``point_of_sale`` selects ``@point_of_sale/unit`` and bundles files outside
#: it, and ``im_livechat`` drives an unfiltered ``/web/tests/livechat`` route
#: rather than ``_run_hoot``, so its bundled suites match no prefix.
KNOWN_UNCOVERED_ADDONS = frozenset(
    {
        "account",
        "account_accountant",
        "account_online_synchronization",
        "account_payment",
        "account_reports",
        "ai",
        "ai_app",
        "ai_documents",
        "ai_fields",
        "analytic",
        "analytic_enterprise",
        "appointment",
        "approval",
        "approvals",
        "base_automation",
        "board",
        "calendar",
        "crm",
        "crm_enterprise",
        "crm_livechat",
        "data_cleaning",
        "documents_spreadsheet",
        "documents_spreadsheet_survey",
        "esg",
        "gamification",
        "geoengine",
        "google_address_autocomplete",
        "google_calendar",
        "helpdesk",
        "helpdesk_timesheet",
        "hr",
        "hr_attendance",
        "hr_attendance_gantt",
        "hr_gantt",
        "hr_holidays",
        "hr_holidays_homeworking",
        "hr_homeworking",
        "hr_homeworking_calendar",
        "hr_mobile",
        "hr_org_chart",
        "hr_payroll",
        "hr_recruitment",
        "hr_skills",
        "hr_timesheet",
        "hr_work_entry",
        "hr_work_entry_enterprise",
        "html_builder",
        "iap_extract",
        "im_livechat",
        "industry_fsm",
        "industry_fsm_sale",
        "industry_fsm_stock",
        "iot",
        "knowledge",
        "l10n_at_pos",
        "l10n_de_pos_cert",
        "l10n_fr_fec_import",
        "l10n_fr_pos_cert",
        "l10n_it_pos",
        "l10n_sa_pos",
        "l10n_uk_reports",
        "lunch",
        "mail_enterprise",
        "mass_mailing",
        "microsoft_calendar",
        "mrp",
        "mrp_workorder",
        "partner_autocomplete",
        "payment",
        "planning",
        "planning_holidays",
        "point_of_sale",
        "portal",
        "pos_appointment",
        "pos_event",
        "pos_glory_cash",
        "pos_hr",
        "pos_iot",
        "pos_iot_six",
        "pos_online_payment_self_order",
        "pos_restaurant_appointment",
        "pos_sale",
        "pos_self_order",
        "pos_settle_due",
        "pos_urban_piper",
        "pos_urban_piper_enhancements",
        "product",
        "project_enterprise",
        "project_forecast",
        "project_todo",
        "purchase_stock",
        "quality_control",
        "resource",
        "resource_mail",
        "room",
        "sale",
        "sale_management",
        "sale_planning",
        "sale_project",
        "sale_timesheet",
        "sale_timesheet_enterprise",
        "sales_team",
        "sign",
        "sign_itsme",
        "sms",
        "snailmail",
        "social_facebook",
        "social_test_full",
        "spreadsheet",
        "spreadsheet_account",
        "spreadsheet_dashboard",
        "spreadsheet_dashboard_documents",
        "spreadsheet_dashboard_edition",
        "spreadsheet_edition",
        "spreadsheet_sale_management",
        "stock",
        "stock_barcode",
        "stock_barcode_product_expiry",
        "survey",
        "test_assetsbundle",
        "test_discuss_full_enterprise",
        "test_mail_enterprise",
        "test_mail_full",
        "test_spreadsheet_edition",
        "timer",
        "timesheet_grid",
        "uom",
        "voip",
        "voip_crm",
        "voip_onsip",
        "web_cohort",
        "web_enterprise",
        "web_gantt",
        "web_grid",
        "web_hierarchy",
        "web_map",
        "web_mobile",
        "web_studio",
        "web_studio_ai_fields",
        "web_threed",
        "web_tour",
        "web_unsplash",
        "web_widget_model_viewer",
        "website_appointment",
        "website_blog",
        "website_cf_turnstile",
        "website_event",
        "website_forum",
        "website_helpdesk_livechat",
        "website_knowledge",
        "website_livechat",
        "website_mass_mailing",
        "website_payment",
        "website_sale",
        "website_slides",
        "website_studio",
        "whatsapp",
        "worksheet",
    }
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
            id_params += f"&id={h}"
        return id_params

    def test_generate_hoot_hash(self):
        self.assertEqual(self._generate_hash("@web/core"), "e39ce9ba")
        self.assertEqual(
            self._generate_hash("@web/core/autocomplete"), "69a6561d"
        )
        self.assertEqual(
            self._generate_hash("@web/core/autocomplete/open dropdown on input"),
            "ee565d54",
        )

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

    @staticmethod
    def _get_module_scope_param(suite_names):
        """Return the ``&module_scope=`` param for a run, or ``""``.

        Every suite name starts with the addon that owns it (``@mail/discuss``
        → ``mail``), which is the addon whose ``src`` the run is allowed to
        load; ``ir.asset._get_active_addons_list`` narrows the bundle to that
        addon's dependency closure. Suites spanning several addons carry no
        single closure, so they stay unscoped rather than silently dropping
        one side's ``src``.

        Deliberately not derived when ``hoot_filters`` overrides the run: an
        explicit ``--test-tags`` path may select suites from another addon,
        and scoping to this class's declared suites would then load none of
        the addons those tests need.
        """
        addons = {name.partition("/")[0].removeprefix("@") for name in suite_names}
        if len(addons) != 1:
            return ""
        addon = addons.pop()
        return f"&module_scope={addon}" if addon else ""

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
            scope_param = ""
        else:
            id_filters = "".join(f"&id={self._generate_hash(n)}" for n in suite_names)
            scope_param = self._get_module_scope_param(suite_names)
        tag_param = f"&tag={tag}" if tag else ""
        self.browser_js(
            f"/web/tests?headless&loglevel=2&preset={preset}&timeout=15000{id_filters}{tag_param}{scope_param}{extra}",
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
        utils, test helpers, interactions, and the vendored-library patches
        under ``@web/libs`` (Bootstrap, Font Awesome)."""
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
        13 files (~183 tests: mock_server, l10n, modules,
        interactions, helpers, view_compiler) were silently lost that way.
        This walk fails the build the moment a tests directory is added or
        renamed without updating the suite lists at the top of this file.
        """
        tests_root = Path(file_path("web/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            if rel.startswith(("_framework/", "tours/")):
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

    def test_every_addon_unit_suite_is_selected_by_a_runner(self):
        """Repo-wide: every ``*.test.js`` bundled into ``web.assets_unit_tests``
        must be selected by some runner's ``_run_hoot`` prefix.

        The per-addon walks above only police their own addon, so an addon that
        bundles test files and ships no ``tests/test_js.py`` at all was policed
        by nothing: ``_run_hoot`` drives HOOT with ``&id=`` hash filters built
        from explicit suite names, and a suite no filter names simply never
        runs. ``base_import`` sat that way with 38 tests, two of which were
        broken -- one of them a real UI bug -- and ``barcodes`` with 9.

        Coverage is read from what the runners actually execute rather than from
        a naming convention, so cross-addon coverage counts (``web`` runs
        ``@html_editor``) and a runner whose prefixes miss some of its own files
        is still reported.

        :attr:`KNOWN_UNCOVERED_ADDONS` is the remaining debt, and is asserted to
        be exact in both directions: an addon that gains coverage must be
        removed from it, so the list can only shrink.
        """
        uncovered = self._uncovered_unit_suites()
        unexpected = sorted(
            suite
            for suite in uncovered
            if self._suite_addon(suite) not in KNOWN_UNCOVERED_ADDONS
        )
        self.assertFalse(
            unexpected,
            "Unit test files selected by no runner (they will never run). Add a "
            "tests/test_js.py for the addon, or a prefix to an existing runner:"
            "\n- " + "\n- ".join(unexpected),
        )
        stale = KNOWN_UNCOVERED_ADDONS - {self._suite_addon(s) for s in uncovered}
        self.assertFalse(
            stale,
            "These addons are now covered by a runner; remove them from "
            f"KNOWN_UNCOVERED_ADDONS: {sorted(stale)}",
        )

    @staticmethod
    def _suite_addon(suite):
        return suite.split("/", 1)[0].lstrip("@")

    @staticmethod
    def _runner_suite_prefixes(path):
        """Return the suite prefixes ``path`` actually passes to ``_run_hoot``.

        Module-level tuple/list constants are resolved first so a ``*SUITES``
        splat inside the call expands, which is how most runners spell their
        lists.
        """
        tree = ast.parse(Path(path).read_text())
        constants = {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Tuple | ast.List)
            ):
                values = []
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        values.append(elt.value)
                    elif isinstance(elt, ast.Starred) and isinstance(
                        elt.value, ast.Name
                    ):
                        values.extend(constants.get(elt.value.id, ()))
                constants[node.targets[0].id] = tuple(values)
        prefixes = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_run_hoot"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        prefixes.add(arg.value)
                    elif isinstance(arg, ast.Starred) and isinstance(
                        arg.value, ast.Name
                    ):
                        prefixes.update(constants.get(arg.value.id, ()))
        return prefixes

    def _uncovered_unit_suites(self):
        """Return the suite names bundled for HOOT that no runner selects."""
        roots = [Path(p) for p in odoo.addons.__path__]
        prefixes = set()
        for root in roots:
            for runner in root.glob("*/tests/test_js.py"):
                prefixes |= self._runner_suite_prefixes(runner)

        uncovered = []
        for root in roots:
            for manifest in root.glob("*/__manifest__.py"):
                addon = manifest.parent
                if "assets_unit_tests" not in manifest.read_text():
                    continue
                tests_root = addon / "static" / "tests"
                for test_file in sorted(tests_root.rglob("*.test.js")):
                    rel = test_file.relative_to(tests_root).as_posix()
                    suite = f"@{addon.name}/" + rel[: -len(".test.js")]
                    if not any(
                        suite == prefix or suite.startswith(prefix + "/")
                        for prefix in prefixes
                    ):
                        uncovered.append(suite)
        return uncovered

    def _check_forbidden_statements(self, bundle):
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
