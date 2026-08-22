import re
from unittest.mock import patch

from odoo.modules import Manifest
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.web.models.ir_asset import UNIT_TEST_URL_SEGMENT

BACKEND_BUNDLE = "web.assets_backend"
RUNNER_BUNDLE = "web.assets_unit_tests_setup"

CLASSIC_BUNDLE_LINK = re.compile(r"/web/assets/[\w/]+/[\w.]+\.min\.(?:js|css)")


def _declared_depends(addon):
    return set((Manifest.for_addon(addon) or {}).get("depends") or ["base"])


def _addon_of(entry):
    return entry.path.strip("/").partition("/")[0]


@tagged("post_install", "-at_install", "asset_scope")
class TestUnitTestAssetScope(TransactionCase):
    def test_closure_follows_manifest_dependencies(self):
        graph = {
            "a": {"depends": ["b"]},
            "b": {"depends": ["c"]},
            "c": {"depends": ["base"]},
            "base": {"depends": []},
        }
        IrAsset = self.env["ir.asset"]

        with (
            patch.object(
                type(IrAsset),
                "_get_addons_installed",
                return_value=frozenset(graph),
            ),
            patch.object(Manifest, "for_addon", staticmethod(graph.get)),
        ):
            closure = IrAsset._get_addons_in_unit_test_scope("a")

        self.assertEqual(closure, frozenset(graph))

    def test_closure_is_transitive_over_installed_addons(self):
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_addons_installed()

        for addon in installed:
            closure = IrAsset._get_addons_in_unit_test_scope(addon)
            self.assertIn(addon, closure, f"{addon}: closure is not reflexive")
            self.assertLessEqual(
                closure, installed, f"{addon}: closure escapes the installed set"
            )
            for member in closure:
                self.assertLessEqual(
                    _declared_depends(member) & installed,
                    closure,
                    f"{addon}: closure stops at {member}'s dependencies instead "
                    "of walking through them",
                )

    def test_closure_excludes_addons_that_merely_depend_on_the_scope(self):
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_addons_installed()
        closure = IrAsset._get_addons_in_unit_test_scope("web")

        self.assertIn("web", closure)
        dependents = {a for a in installed if "web" in _declared_depends(a)} - {"web"}
        self.assertTrue(dependents, "no installed addon depends on web")
        self.assertFalse(dependents & closure)

    def test_uninstalled_scope_yields_no_addons(self):
        self.assertFalse(
            self.env["ir.asset"]._get_addons_in_unit_test_scope("no_such_addon")
        )

    def test_active_addons_are_narrowed_to_the_closure(self):
        IrAsset = self.env["ir.asset"]
        unscoped = set(IrAsset._get_addons_active())

        scoped = set(IrAsset._get_addons_active(unit_test_scope="web"))

        self.assertLessEqual(scoped, unscoped)
        self.assertIn("web", scoped)
        if "mail" in unscoped:
            self.assertNotIn("mail", scoped)

    def test_no_scope_leaves_the_addon_list_untouched(self):
        IrAsset = self.env["ir.asset"]

        self.assertEqual(
            set(IrAsset._get_addons_active()),
            set(IrAsset._get_addons_active(unit_test_scope=None)),
        )

    def test_scope_is_ignored_outside_a_request(self):
        self.assertEqual(self.env["ir.asset"]._get_unit_test_scope(), "")
        self.assertNotIn(
            "unit_test_scope", self.env["ir.asset"]._prepare_assets_params()
        )


@tagged("post_install", "-at_install", "asset_scope")
class TestUnitTestAssetScopeResolution(TransactionCase):
    def setUp(self):
        super().setUp()
        IrAsset = self.env["ir.asset"]
        self.closure = IrAsset._get_addons_in_unit_test_scope("web")
        self.unscoped = IrAsset._get_asset_paths(BACKEND_BUNDLE, {})
        self.scoped = IrAsset._get_asset_paths(
            BACKEND_BUNDLE, {"unit_test_scope": "web"}
        )
        self.foreign_unscoped = [
            entry for entry in self.unscoped if _addon_of(entry) not in self.closure
        ]

    def test_manifest_declared_foreign_files_are_dropped(self):
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")
        record_paths = {
            asset.path.strip("/")
            for asset in self.env["ir.asset"]
            .sudo()
            .with_context(active_test=False)
            .search([])
        }
        surviving = {
            entry.path
            for entry in self.scoped
            if _addon_of(entry) not in self.closure
            and entry.path.strip("/") not in record_paths
        }

        self.assertFalse(
            surviving,
            f"scoped bundle still carries manifest-declared files {sorted(surviving)}",
        )

    def test_scope_removes_the_bulk_of_the_bundle(self):
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")

        self.assertLess(len(self.scoped), len(self.unscoped))

    def test_an_ir_asset_record_cannot_escape_the_scope(self):
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")
        smuggled = self.foreign_unscoped[0]
        self.assertNotIn(smuggled, self.scoped)

        self.env["ir.asset"].create(
            {
                "name": "scope leak probe",
                "bundle": BACKEND_BUNDLE,
                "path": smuggled.path,
            }
        )
        rescoped = self.env["ir.asset"]._get_asset_paths(
            BACKEND_BUNDLE, {"unit_test_scope": "web"}
        )

        self.assertNotIn(smuggled.path, [entry.path for entry in rescoped])

    def test_a_glob_record_cannot_expand_into_a_foreign_addon(self):
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")
        foreign_addon = _addon_of(self.foreign_unscoped[0])

        self.env["ir.asset"].create(
            {
                "name": "scope glob leak probe",
                "bundle": BACKEND_BUNDLE,
                "path": f"{foreign_addon}/static/src/**/*.js",
            }
        )
        rescoped = self.env["ir.asset"]._get_asset_paths(
            BACKEND_BUNDLE, {"unit_test_scope": "web"}
        )

        self.assertFalse(
            [e.path for e in rescoped if _addon_of(e) == foreign_addon],
        )

    def test_the_scoped_url_names_the_scope_that_built_it(self):
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")
        IrAsset = self.env["ir.asset"]
        scoped_params = {"unit_test_scope": "web"}
        unique = (
            self.env["ir.qweb"]
            ._get_asset_bundle(BACKEND_BUNDLE, assets_params=scoped_params)
            .get_version("js")
        )

        scoped_url = IrAsset._get_asset_bundle_url(
            f"{BACKEND_BUNDLE}.min.js", unique, scoped_params
        )
        plain_url = IrAsset._get_asset_bundle_url(
            f"{BACKEND_BUNDLE}.min.js", unique, {}
        )

        self.assertEqual(
            scoped_url,
            f"/web/assets/scope/web/{unique}/{BACKEND_BUNDLE}.min.js",
        )
        self.assertNotEqual(scoped_url, plain_url)

    def test_every_asset_param_contributes_a_url_segment(self):
        IrAsset = self.env["ir.asset"]
        params = dict.fromkeys(IrAsset._prepare_assets_params(), "probe")
        params["unit_test_scope"] = "web"

        segments = IrAsset._get_asset_bundle_url_segments(params)

        for key, value in params.items():
            self.assertIn(
                value,
                segments,
                f"{key} changes the resolution but not the URL that serves it",
            )


@tagged("post_install", "-at_install", "asset_scope")
class TestUnitTestAssetScopeRoutes(HttpCase):
    def setUp(self):
        super().setUp()
        self.authenticate("admin", "admin")

    def test_the_linked_bundle_is_served_at_its_own_url(self):
        page = self.url_open("/web/tests?module_scope=web")
        page.raise_for_status()
        links = set(CLASSIC_BUNDLE_LINK.findall(page.text))
        if not links:
            self.skipTest("scoped runner page links no classic bundle")

        served = {
            link: self.url_open(link, allow_redirects=False) for link in sorted(links)
        }

        for link, response in served.items():
            self.assertEqual(response.status_code, 200, f"{link} was not served")
        self.assertTrue(
            any("/scope/web/" in link for link in links),
            f"no link carries the scope: {sorted(links)}",
        )

    def test_lazily_loaded_bundles_inherit_the_scope(self):
        unscoped = self.url_open(f"/web/bundle/{RUNNER_BUNDLE}")
        scoped = self.url_open(f"/web/bundle/{RUNNER_BUNDLE}?module_scope=web")
        unscoped.raise_for_status()
        scoped.raise_for_status()

        self.assertNotEqual(scoped.json(), unscoped.json())

    def test_the_runner_page_publishes_the_scope_to_loadbundle(self):
        page = self.url_open("/web/tests?module_scope=web")
        page.raise_for_status()

        self.assertIn('"module_scope": "web"', page.text)

    def test_the_route_and_the_url_builder_spell_the_scope_alike(self):
        rule = next(
            rule
            for rule in self.env["ir.http"].routing_map().iter_rules()
            if rule.endpoint.routing["routes"][0].startswith("/web/assets/")
            and "scope" in rule.arguments
        )

        self.assertIn(f"/web/assets/{UNIT_TEST_URL_SEGMENT}/", str(rule))

    def test_an_unknown_scope_is_not_served(self):
        response = self.url_open(
            f"/web/assets/scope/__no_such_addon__/any/{RUNNER_BUNDLE}.min.js",
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 404)
