import ast
import importlib
import importlib.machinery
import importlib.util
import re
import sys
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

# Despite the name, this is the catch-all for every ``@web/views/*`` suite that
# does not warrant a test method of its own — graph and pivot are 2 of the 16.
# ``test_graph_pivot`` runs the whole tuple on both presets, so a new
# ``static/tests/views/<x>/`` directory belongs HERE (the name is kept because
# the method it feeds is referenced by tooling/hoot's docs and --test-tags
# recipes). ``@web/views/settings`` was added after
# ``test_suite_filters_cover_every_test_file`` caught it running nowhere.
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
    "@web/views/settings",
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


def suite_addon(suite):
    return suite.split("/", 1)[0].lstrip("@")


def runner_suite_prefixes(path):
    """Return the suite prefixes ``path`` actually passes to ``_run_hoot``.

    Module-level tuple/list constants are resolved first so a ``*SUITES`` splat
    inside the call expands, which is how most runners spell their lists.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
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
                elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name):
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
                elif isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
                    prefixes.update(constants.get(arg.value.id, ()))
    return prefixes


#: ``test(...)`` and ``test.tags(...)(...)`` register a runnable test;
#: ``test.skip`` / ``test.todo`` do not.
RE_RUNNABLE_TEST = re.compile(r"\btest\s*\(|\btest\.tags\s*\(")


def has_runnable_tests(test_file):
    """Whether ``test_file`` registers a test a run can actually select.

    A file whose tests are ALL ``test.skip`` / ``test.todo`` still exists on
    disk, but its ``&id=`` hash matches no job — and the runner is hardened to
    fail rather than fall back to running everything, so generating a suite for
    it produces ``HootError: no suite or test matches id "..."`` and a red
    build. That is what ``AddonSuite.test_web_gantt`` was: ``gantt_view_manual``
    is a hand-run benchmark (10k-record renders) carrying
    ``describe.current.tags("manual testing")`` with all three tests skipped.

    Only *per-file* suites are exposed to this. A directory suite such as
    ``@web/modules`` resolves through its siblings, which is why
    ``web/static/tests/modules/dependencies.test.js`` (also fully skipped)
    never broke anything.
    """
    with suppress(OSError):
        return bool(RE_RUNNABLE_TEST.search(test_file.read_text(encoding="utf-8")))
    return False


def addons_bundling_unit_tests():
    """``{addon: [suite, ...]}`` for every addon that bundles ``*.test.js``."""
    bundled = {}
    for root in (Path(p) for p in odoo.addons.__path__):
        for manifest in root.glob("*/__manifest__.py"):
            addon = manifest.parent
            if "assets_unit_tests" not in manifest.read_text(encoding="utf-8"):
                continue
            tests_root = addon / "static" / "tests"
            suites = [
                f"@{addon.name}/"
                + test_file.relative_to(tests_root).as_posix()[: -len(".test.js")]
                for test_file in sorted(tests_root.rglob("*.test.js"))
                if has_runnable_tests(test_file)
            ]
            if suites:
                bundled.setdefault(addon.name, []).extend(suites)
    return bundled


def uncovered_unit_suites():
    """Suite names bundled for HOOT that no addon's own runner selects.

    These are what :mod:`test_js_addons` picks up: a suite no ``_run_hoot``
    filter names simply never runs, and before the catch-all existed that was
    660 test files across 159 addons — 38% of the workspace's HOOT tests.
    """
    prefixes = set()
    for root in (Path(p) for p in odoo.addons.__path__):
        for runner in root.glob("*/tests/test_js.py"):
            prefixes |= runner_suite_prefixes(runner)
    return [
        suite
        for suites in addons_bundling_unit_tests().values()
        for suite in suites
        if not any(suite == p or suite.startswith(p + "/") for p in prefixes)
    ]


def uncovered_suites_by_addon():
    """``{addon: [suite, ...]}`` for :mod:`test_js_addons` to generate from.

    Keyed on the *suites* an addon leaves uncovered rather than on the addon,
    because coverage is not all-or-nothing: ``point_of_sale`` selects
    ``@point_of_sale/unit`` and bundles files outside it, so a generated method
    running the whole addon would re-run what its own runner already does.
    """
    by_addon = {}
    for suite in uncovered_unit_suites():
        by_addon.setdefault(suite_addon(suite), []).append(suite)
    return by_addon


RE_MOBILE_TAG = re.compile(r"""\.tags\([^)]*["']mobile["']""")


def _suite_test_files(suite):
    """The ``*.test.js`` files a ``&id=`` filter for ``suite`` can select."""
    addon, _, rel = suite.lstrip("@").partition("/")
    with suppress(FileNotFoundError):
        tests_root = Path(file_path(f"{addon}/static/tests"))
        target = tests_root / rel if rel else tests_root
        if target.is_dir():
            return sorted(target.rglob("*.test.js"))
        leaf = target.with_name(target.name + ".test.js")
        if leaf.is_file():
            return [leaf]
    return []


def _mobile_suites_under(prefixes):
    """The file suites under ``prefixes`` that carry at least one mobile test.

    The mobile preset excludes only ``desktop``-tagged tests, so an untagged
    test — 49% of ``@web`` and 97% of ``@html_editor`` — runs a second time at
    375x667. Measured, that second pass is 9409 tests and ~875 s of serial
    runtime against 198 tests that actually carry a ``mobile`` tag, and across
    ~23600 executions its failure set was a strict subset of the desktop pass's
    (the same 7 cross-suite pollution failures, nothing else). Selecting the
    files that own a mobile test keeps every mobile test, keeps the untagged
    tests sitting next to them, and stops re-running the other 96%.
    """
    suites = []
    for prefix in prefixes:
        addon = prefix.lstrip("@").partition("/")[0]
        tests_root = Path(file_path(f"{addon}/static/tests"))
        for test_file in _suite_test_files(prefix):
            with suppress(OSError):
                if RE_MOBILE_TAG.search(test_file.read_text(encoding="utf-8")):
                    rel = test_file.relative_to(tests_root).as_posix()
                    suites.append(f"@{addon}/" + rel[: -len(".test.js")])
    return suites


@odoo.tests.tagged("post_install", "-at_install", "web_js")
class HOOTCommon(odoo.tests.HttpCase):
    def setUp(self):
        super().setUp()
        self.hoot_filters = self.get_hoot_filters()

    def _generate_hash(self, test_string):
        # Iterate UTF-16 CODE UNITS: `hoot_utils.js::generateHash` uses
        # `charCodeAt`, and the browser recomputes the id and keeps only the
        # jobs that match, so a disagreement selects NOTHING rather than
        # selecting the wrong thing. `ord()` returns one value above 0xFFFF
        # where JS returns a surrogate pair, so every astral character
        # diverged — and two suites really carry one ("hotkeys evil 👹",
        # "commands evilness 👹"), which were therefore unselectable by id.
        hash_val = 0
        units = test_string.encode("utf-16-le")
        for i in range(0, len(units), 2):
            hash_val = (hash_val << 5) - hash_val + (units[i] | units[i + 1] << 8)
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
        # An astral character, which JS hashes as a surrogate PAIR. Vector
        # taken from the real suite `@web/services/hotkey_service` and checked
        # against `hoot_utils.js::generateHash` under node. Before the UTF-16
        # iteration this returned d7eaaa1d and the browser matched no job.
        self.assertEqual(
            self._generate_hash("@web/services/hotkey_service/hotkeys evil \U0001f479"),
            "25490ab8",
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
        edit/run loop (see tooling/hoot/hoot for a warm-server runner).
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

    def test_shard_runner_covers_ci(self):
        """``tooling/hoot/hoot-shard`` must run every test file CI runs.

        It presents itself as the full web suite, so a suite missing from it
        reads as "the whole thing is green". Its list used to be a hand-kept
        copy of the one above, marked "KEEP IN SYNC", and it had lost
        ``@html_editor`` (4766 tests, 494 s — more than a third of the desktop
        pass) and ``@web/libs``: the "full" run covered 66% of the tests.

        Asserted over the *resolved plan* — after ``refine()`` has split heavy
        suites into child ids — and in files rather than suite names, so it
        also catches a refinement that drops one. Comparing the two suite lists
        would prove nothing: both are read from this file.
        """
        hoot_lib, hoot_shard = self._load_shard_runner()
        weights = hoot_shard.load_weights()
        declared = hoot_shard.default_web_suites()
        scheduled = hoot_shard.refine(declared, 4, weights)

        def files(suites):
            return {p for s in suites for p in hoot_lib.suite_test_files(s)}

        expected = files(self._runner_suite_prefixes(Path(__file__)))
        self.assertTrue(expected, "no test files resolved for the CI suites")
        self.assertFalse(
            expected - files(scheduled),
            "hoot-shard's plan does not cover every test file WebSuite runs:"
            "\n- " + "\n- ".join(sorted(str(p) for p in expected - files(scheduled))),
        )

    @staticmethod
    def _load_shard_runner():
        """Import ``hoot_lib`` and the extension-less ``hoot-shard`` CLI.

        The runner lives in the repo-root ``tooling/`` tree, outside any addons
        path, so ``file_path`` cannot reach it — walk up for ``odoo-bin``, the
        same anchor the runner itself uses.
        """
        root = next(
            p for p in Path(__file__).resolve().parents if (p / "odoo-bin").is_file()
        )
        scripts = root / "tooling" / "hoot"
        sys.path.insert(0, str(scripts))
        try:
            hoot_lib = importlib.import_module("hoot_lib")
            loader = importlib.machinery.SourceFileLoader(
                "hoot_shard", str(scripts / "hoot-shard")
            )
            spec = importlib.util.spec_from_loader("hoot_shard", loader)
            hoot_shard = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hoot_shard)
        finally:
            sys.path.remove(str(scripts))
        return hoot_lib, hoot_shard

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
        """Repo-wide: every bundled ``*.test.js`` must be selected by a runner.

        ``_run_hoot`` drives HOOT with ``&id=`` hash filters built from explicit
        suite names, and a suite no filter names simply never runs.
        ``base_import`` sat that way with 38 tests, two of which were broken --
        one of them a real UI bug -- and ``barcodes`` with 9.

        An addon with no runner of its own is now picked up by
        :class:`~odoo.addons.web.tests.test_js_addons.AddonSuite`, which
        generates one method per such addon from this same walk. So the walk no
        longer asks "did someone write a runner" — it asks whether the two
        halves still meet: every suite is either named by an explicit runner or
        owned by a generated method, and nothing falls between them.

        :data:`~odoo.addons.web.tests.test_js_addons.KNOWN_FAILING_ADDONS` is
        the remaining debt — addons whose generated method skips because the
        suites do not pass yet — and is asserted exact in both directions, so it
        can only shrink.
        """
        from .test_js_addons import GENERATED_ADDONS, KNOWN_FAILING_ADDONS

        uncovered = uncovered_unit_suites()
        generated = GENERATED_ADDONS
        unowned = sorted(
            suite for suite in uncovered if suite_addon(suite) not in generated
        )
        self.assertFalse(
            unowned,
            "Unit test files selected by no runner and by no generated method "
            "(they will never run):\n- " + "\n- ".join(unowned),
        )

        covered_addons = set(addons_bundling_unit_tests()) - {
            suite_addon(s) for s in uncovered
        }
        self.assertFalse(
            generated & covered_addons,
            "These addons have their own runner; AddonSuite must not also "
            f"generate a method for them: {sorted(generated & covered_addons)}",
        )
        self.assertFalse(
            KNOWN_FAILING_ADDONS - generated,
            "These addons no longer bundle uncovered suites; remove them from "
            f"KNOWN_FAILING_ADDONS: {sorted(KNOWN_FAILING_ADDONS - generated)}",
        )

    @staticmethod
    def _suite_addon(suite):
        return suite_addon(suite)

    @staticmethod
    def _runner_suite_prefixes(path):
        return runner_suite_prefixes(path)

    def _uncovered_unit_suites(self):
        return uncovered_unit_suites()

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

    def _run_hoot(self, *suite_names, **kwargs):
        """Narrow each category to the files that own a mobile test.

        See :func:`_mobile_suites_under`. Not applied when ``--test-tags``
        supplies explicit suites: that path is someone asking for exactly what
        they typed.
        """
        if not self.hoot_filters:
            suite_names = _mobile_suites_under(suite_names)
            if not suite_names:
                self.skipTest("no mobile-tagged test under these suites")
        super()._run_hoot(*suite_names, **kwargs)

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
