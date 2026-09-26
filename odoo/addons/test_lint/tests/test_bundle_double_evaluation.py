import logging

from odoo.modules import Manifest
from odoo.tests import tagged
from odoo.tools.assets.esm_graph import (
    discover_transitive_import_specifiers,
    url_to_module_path,
)
from odoo.tools.assets.esm_registry import esm_registry, external_libs

from . import lint_case

_logger = logging.getLogger(__name__)


def _js_specs(ir_asset, bundle, params):
    specs = set()
    for entry in ir_asset._get_asset_paths(bundle, params):
        url = entry[0] if isinstance(entry, (list, tuple)) else entry
        if isinstance(url, str) and url.endswith(".js"):
            if spec := url_to_module_path(url):
                specs.add(spec)
    return specs


def _includes_by_bundle(installed):
    includes = {}
    for name in installed:
        manifest = Manifest.for_addon(name, display_warning=False)
        if not manifest:
            continue
        for bundle, entries in (manifest.get("assets") or {}).items():
            for entry in entries:
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) == 2
                    and entry[0] == "include"
                ):
                    includes.setdefault(bundle, set()).add(entry[1])
    return includes


def _included_closure(bundle, includes):
    seen = set()
    stack = list(includes.get(bundle, ()))
    while stack:
        current = stack.pop()
        if current not in seen:
            seen.add(current)
            stack.extend(includes.get(current, ()))
    return seen


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


def _reinlined(removed_paths, seeds, closure, stubbed):
    for path in sorted(removed_paths):
        spec = url_to_module_path("/" + path.lstrip("/"))
        if spec and spec in closure and spec not in seeds | stubbed:
            yield path.lstrip("/").split("/", 1)[0], spec


@tagged("post_install", "-at_install")
class TestBundleDoubleEvaluation(lint_case.LintCase):
    def test_a_removed_file_does_not_come_back_as_an_import(self):
        findings = {}
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
            # served module by module through the page's import map, so an
            # import resolves to whatever the map names and nothing is inlined
            by_import_map = esm_registry().import_map_included_bundles

            for bundle, removed_paths in sorted(removed_by_bundle.items()):
                if bundle in by_import_map:
                    continue
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
                    discover_transitive_import_specifiers(seeds, seeds, ext, bundle)
                )
                stubbed = set(qweb._get_secondary_shared_specs(bundle, params))
                for owner, spec in _reinlined(removed_paths, seeds, closure, stubbed):
                    findings.setdefault(owner, []).append(
                        f"{bundle}: {spec} (removed, still inlined)"
                    )

        # keyed by the addon the module lives in, so each floor is graded
        # wherever that addon is installed and no install can lend another
        # addon's debt as slack
        owners = set(findings) | {
            name
            for name in installed
            if lint_case.baseline_floor(f"bundle_double_eval_{name}")
        }
        for owner in sorted(owners):
            with self.subTest(addon=owner):
                self.assert_ratchet(
                    findings.get(owner, []),
                    f"bundle_double_eval_{owner}",
                    f"module(s) of {owner} removed from a bundle and re-inlined "
                    f"by an import",
                    "Declare the providing bundle a secondary parent of this one "
                    "under `esm.secondary_import_map_includes`, so the import is "
                    "stubbed to the shared loader instead of inlined; or give the "
                    "module a specifier esbuild leaves external. Why the floors "
                    "exist and how they are keyed: web/machine_doc_v1/"
                    "ESM_BUNDLING.md, section 'A split page evaluates each "
                    "module once'.",
                )
        _logger.info(
            "%s removed-but-reinlined module(s) across %s bundle(s) with removes",
            sum(map(len, findings.values())),
            len(removed_by_bundle),
        )

    def test_a_secondary_child_reaches_a_split_parent_s_removed_half(self):
        # A bundle that removes files from the one it includes (web.assets_
        # frontend_lazy is web.assets_frontend minus web.assets_frontend_minimal)
        # is rendered beside the bundle holding those files. A secondary child
        # of it that imports one of them must also name that bundle as a
        # parent; naming the full bundle does not count, because it is never on
        # the page beside the split one. Unnamed, the child inlines its own
        # copy and the page runs two (a "singleton split" on the loader).
        findings = []
        with self.superuser_env() as env:
            installed = (
                env["ir.module.module"]
                .search([("state", "=", "installed")])
                .mapped("name")
            )
            removed_by_bundle = _removed_paths_by_bundle(installed)
            includes = _includes_by_bundle(installed)
            ir_asset = env["ir.asset"]
            params = ir_asset._prepare_assets_params()
            ext = external_libs()
            specs_cache = {}

            def specs_of(bundle):
                if bundle not in specs_cache:
                    try:
                        specs_cache[bundle] = _js_specs(ir_asset, bundle, params)
                    except Exception:
                        _logger.debug("bundle %s does not assemble", bundle)
                        specs_cache[bundle] = set()
                return specs_cache[bundle]

            for child, parents in sorted(esm_registry().secondary_parents.items()):
                for parent in parents:
                    removed = removed_by_bundle.get(parent)
                    if not removed:
                        continue
                    seeds = specs_of(child)
                    closure = seeds | set(
                        discover_transitive_import_specifiers(seeds, seeds, ext, child)
                    )
                    # the halves it was cut from: what it includes, minus the
                    # bundle it includes whole (which also holds its own files)
                    parent_specs = specs_of(parent)
                    halves = {
                        half
                        for half in _included_closure(parent, includes)
                        if not parent_specs <= specs_of(half)
                    }
                    for path in sorted(removed):
                        spec = url_to_module_path("/" + path.lstrip("/"))
                        if not spec or spec not in closure or spec in seeds:
                            continue
                        holders = {half for half in halves if spec in specs_of(half)}
                        if holders and not holders & set(parents):
                            findings.append(
                                f"{child} under {parent}: {spec} lives in "
                                f"{', '.join(sorted(holders))}, not a parent"
                            )

        self.assert_ratchet(
            findings,
            "bundle_split_parent",
            "secondary child(ren) importing what a split parent removed",
            "Name the bundle that holds the removed files (for web.assets_frontend_"
            "lazy, web.assets_frontend_minimal) as a parent of the child under "
            "`esm.secondary_import_map_includes`, beside the split one.",
        )

    def test_a_removed_file_back_in_the_bundle_is_not_reinlined(self):
        self.assertEqual(
            list(
                _reinlined(
                    {"website/static/src/interactions/multirange_input.js"},
                    seeds={"@website/interactions/multirange_input"},
                    closure={"@website/interactions/multirange_input"},
                    stubbed=set(),
                )
            ),
            [],
        )

    def test_a_reinlined_module_is_owned_by_the_addon_it_lives_in(self):
        self.assertEqual(
            list(
                _reinlined(
                    {
                        "web/static/src/session.js",
                        "website/static/src/utils/misc.js",
                        "web/static/src/core/browser/cookie.js",
                    },
                    seeds={"@web/core/utils/urls"},
                    closure={
                        "@web/core/utils/urls",
                        "@web/session",
                        "@website/utils/misc",
                    },
                    stubbed={"@web/core/browser/cookie"},
                )
            ),
            [("web", "@web/session"), ("website", "@website/utils/misc")],
        )
