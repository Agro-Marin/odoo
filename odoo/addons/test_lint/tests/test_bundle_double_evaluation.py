import logging

from odoo.modules import Manifest
from odoo.tests import tagged
from odoo.tools.assets.esbuild import EsbuildCompiler
from odoo.tools.assets.esm_graph import (
    discover_transitive_import_specifiers,
    url_to_module_path,
)
from odoo.tools.assets.esm_registry import external_libs

from . import lint_case

_logger = logging.getLogger(__name__)


def _removed_paths_by_bundle(installed):
    removed = {}
    for name in installed:
        manifest = Manifest.for_addon(name, display_warning=False)
        if not manifest:
            continue
        for bundle, entries in (manifest.get("assets") or {}).items():
            for entry in entries:
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) == 2
                    and entry[0] == "remove"
                    and isinstance(entry[1], str)
                    and entry[1].endswith(".js")
                ):
                    removed.setdefault(bundle, set()).add(entry[1])
    return removed


@tagged("post_install", "-at_install")
class TestBundleDoubleEvaluation(lint_case.LintCase):
    def test_a_removed_file_does_not_come_back_as_an_import(self):
        findings = []
        with self.superuser_env() as env:
            installed = (
                env["ir.module.module"]
                .search([("state", "=", "installed")])
                .mapped("name")
            )
            removed_by_bundle = _removed_paths_by_bundle(installed)
            if not removed_by_bundle:
                self.skipTest("no bundle declares a remove directive")

            ir_asset = env["ir.asset"]
            qweb = env["ir.qweb"]
            params = ir_asset._prepare_assets_params()
            ext = external_libs()
            libs = EsbuildCompiler._LIB_CANDIDATES

            for bundle, removed_paths in sorted(removed_by_bundle.items()):
                try:
                    paths = ir_asset._get_asset_paths(bundle, params)
                except Exception:
                    _logger.debug("bundle %s does not assemble", bundle, exc_info=True)
                    continue
                seeds = set()
                for entry in paths:
                    url = entry[0] if isinstance(entry, (list, tuple)) else entry
                    if isinstance(url, str) and url.endswith(".js"):
                        if spec := url_to_module_path(url):
                            seeds.add(spec)
                closure = seeds | set(
                    discover_transitive_import_specifiers(
                        seeds, seeds, ext, libs, bundle
                    )
                )
                stubbed = set(qweb._get_secondary_shared_specs(bundle, params))
                for path in sorted(removed_paths):
                    spec = url_to_module_path("/" + path.lstrip("/"))
                    if spec and spec in closure and spec not in stubbed:
                        findings.append(f"{bundle}: {spec} (removed, still inlined)")

        self.assert_ratchet(
            findings,
            "bundle_double_eval",
            "module(s) removed from a bundle and re-inlined by an import",
            "Declare the providing bundle a secondary parent of this one under "
            "`esm.secondary_import_map_includes`, so the import is stubbed to "
            "the shared loader instead of inlined; or give the module a "
            "specifier esbuild leaves external. Detail: agromarin-knowledge/"
            "research/2026-08-27-frontend-bundle-double-evaluation.md.",
            exact=False,
        )
        _logger.info(
            "%s removed-but-reinlined module(s) across %s bundle(s) with removes",
            len(findings),
            len(removed_by_bundle),
        )
