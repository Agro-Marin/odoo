import logging

from odoo.modules import Manifest
from odoo.tests import tagged
from odoo.tools.assets.esm_graph import find_escaping_relative_imports

from . import lint_case

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestBundlesAssemble(lint_case.LintCase):
    def test_every_declared_bundle_assembles(self):
        failures = []
        with self.superuser_env() as env:
            bundles = self.served_bundle_names(env)

            self.assertTrue(bundles, "no bundles found — the scan reached nothing")

            ir_asset = env["ir.asset"]
            params = ir_asset._prepare_assets_params()
            for bundle in bundles:
                try:
                    ir_asset._get_asset_paths(bundle, params)
                except Exception as exc:
                    failures.append(f"  {bundle}: {type(exc).__name__}: {exc}")

        self.assertFalse(
            failures,
            f"{len(failures)} of {len(bundles)} declared bundle(s) do not "
            "assemble:\n" + "\n".join(failures),
        )
        _logger.info("%s served bundles assemble", len(bundles))

    def test_every_bundled_module_can_resolve_its_own_imports(self):
        failures = []
        with self.superuser_env() as env:
            bundles = self.served_bundle_names(env)
            self.assertTrue(bundles, "no bundles found — the scan reached nothing")

            qweb = env["ir.qweb"]
            checked = 0
            for bundle in bundles:
                try:
                    asset_bundle = qweb._get_asset_bundle(bundle, css=False, js=True)
                    escapes = find_escaping_relative_imports(
                        asset_bundle.native_modules
                    )
                except Exception as exc:
                    failures.append(f"  {bundle}: {type(exc).__name__}: {exc}")
                    continue
                checked += 1
                for module_path, spec, resolved in escapes:
                    failures.append(
                        f"  {bundle}: {module_path} imports {spec!r} "
                        f"(-> {resolved}), which the bundle does not carry"
                    )

        self.assertFalse(
            failures,
            f"{len(failures)} relative import(s) escape their bundle. Either add "
            f"the missing file to the bundle, drop the module that reaches for "
            f"it, or spell the import as a bare '@addon/...' specifier so it "
            f"resolves through the import map:\n" + "\n".join(failures),
        )
        declared = {
            bundle
            for manifest in Manifest.all_addon_manifests()
            for bundle in (manifest.get("assets") or {})
        }
        _logger.info(
            "%s of %s declared bundle(s) resolve their own relative imports; "
            "the rest belong to modules not installed at this scope and are "
            "checked by nothing",
            checked,
            len(declared),
        )

    def test_pregenerated_js_bundles_can_be_built(self):
        """Every bundle whose JS `_pregenerate_assets_bundles` builds must build.

        The JS set is not the set of bundles anyone serves as JS: any module may
        widen it by overriding `_get_bundles_to_pregenerate`, and one did --
        `test_mass_mailing` added `mass_mailing.assets_iframe_style`, a bundle its
        only caller renders with `t-js="False"` because it carries no servable JS
        at all. It includes `html_editor.assets_media_dialog`, whose files are
        native ESM, so building it as a legacy bundle raised
        ModuleSyntaxInLegacyBundleError out of `_pregenerate_assets_bundles`.

        That call sits in `_run_post_install_tests`, ahead of the post_install
        suites, so the failure took the whole phase with it -- and the run still
        printed the at_install tests it had managed, which is why it read as a
        green result rather than as a suite that never ran.

        This test builds the bundles itself rather than leaning on that call,
        which is what lets it report the fault instead of being erased by it:
        `_run_post_install_tests` only pregenerates when the selected suite
        carries an HttpCase, so a run narrow enough to exclude one never reaches
        the raise, and a run wide enough to include one never reaches this test.

        Nothing else gated it. The `esm` declaration checks in TestEsmBundles
        deliberately skip bundles rendered with `t-js="False"`, on the correct
        reasoning that nothing serves their JS. Pregeneration does not share that
        reasoning: it builds whatever is in the JS set.
        """
        failures = []
        with self.superuser_env() as env:
            qweb = env["ir.qweb"]
            js_bundles, _css_bundles = qweb._get_bundles_to_pregenerate()
            self.assertTrue(
                js_bundles, "no bundle is pregenerated as JS — the scan reached nothing"
            )
            for bundle in sorted(js_bundles):
                try:
                    qweb._get_asset_bundle(bundle, css=False, js=True).js()
                except Exception as exc:
                    failures.append(f"  {bundle}: {type(exc).__name__}: {exc}")

        self.assertFalse(
            failures,
            f"{len(failures)} of {len(js_bundles)} pregenerated JS bundle(s) do "
            f"not build. Either declare the bundle under its module's 'esm' key, "
            f"or -- if nothing serves its JS -- stop adding it to the JS half of "
            f"`_get_bundles_to_pregenerate`:\n" + "\n".join(failures),
        )
        _logger.info("%s pregenerated JS bundle(s) build", len(js_bundles))
