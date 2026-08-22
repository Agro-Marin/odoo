import logging

from odoo import SUPERUSER_ID, api
from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name
from odoo.tools.assets.esm_graph import find_escaping_relative_imports

from . import lint_case

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestBundlesAssemble(lint_case.LintCase):
    def test_every_declared_bundle_assembles(self):
        failures = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
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
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
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
