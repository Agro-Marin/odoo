import logging

from odoo.modules import Manifest
from odoo.tests import tagged
from odoo.tools.assets.esm_graph import (
    get_escaping_relative_imports,
    lex_module,
)

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
                    escapes = get_escaping_relative_imports(asset_bundle.native_modules)
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

    def test_every_esm_bundle_compiles(self):
        failures = []
        with self.superuser_env() as env:
            qweb = env["ir.qweb"]
            bundles = self.served_bundle_names(env)
            self.assertTrue(bundles, "no bundles found -- the scan reached nothing")

            compiled = 0
            for bundle in bundles:
                if not qweb._can_compile_with_esbuild(bundle):
                    continue
                try:
                    asset_bundle = qweb._get_asset_bundle(bundle, css=False, js=True)
                    asset_bundle.esbuild_native_bundle()
                except Exception as exc:
                    failures.append(f"  {bundle}: {type(exc).__name__}: {exc}")
                    continue
                compiled += 1

        self.assertFalse(
            failures,
            f"{len(failures)} bundle(s) do not compile. esbuild names the "
            f"importing file and line; the usual cause is a bare specifier "
            f"whose module was refactored and whose importer was not:\n"
            + "\n".join(failures),
        )
        _logger.info("%s esm bundle(s) compile", compiled)

    LIB_SPECIFIERS = (
        "@web/libs/bootstrap",
        "@web/libs/popper_compat",
    )

    LIB_INHERITING_BUNDLES = {
        "web.assets_frontend_minimal",
        "website.assets_inside_builder_iframe",
        "web.assets_unit_tests",
    }

    def test_every_bundled_module_carries_the_libs_it_imports(self):
        failures = []
        with self.superuser_env() as env:
            bundles = self.served_bundle_names(env)
            self.assertTrue(bundles, "no bundles found -- the scan reached nothing")

            qweb = env["ir.qweb"]
            checked = 0
            for bundle in bundles:
                if bundle in self.LIB_INHERITING_BUNDLES:
                    continue
                try:
                    asset_bundle = qweb._get_asset_bundle(bundle, css=False, js=True)
                    modules = list(asset_bundle.native_modules)
                except Exception as exc:
                    failures.append(f"  {bundle}: {type(exc).__name__}: {exc}")
                    continue
                if not modules:
                    continue
                checked += 1
                carried = {module.module_path for module in modules}
                failures.extend(
                    f"  {bundle}: {module.module_path} imports {spec!r}, "
                    f"which the bundle does not carry"
                    for module in modules
                    for spec in sorted(self._bare_specifiers(module))
                    if spec in self.LIB_SPECIFIERS and spec not in carried
                )

        self.assertFalse(
            failures,
            f"{len(failures)} bundled module(s) import a third-party lib their "
            f"bundle does not carry. The specifier resolves to `undefined` at "
            f"runtime, so this surfaces as a TypeError at the first call site, "
            f"not as a load error. Either add the lib to the bundle, drop the "
            f"import, or -- if the module drives elements in another document "
            f"-- reach for that document's own copy "
            f"(`@html_builder/core/bootstrap_realm`):\n" + "\n".join(failures),
        )
        _logger.info("%s bundle(s) carry every lib they import", checked)

    @staticmethod
    def _bare_specifiers(module) -> set:
        src = module.raw_content or ""
        lexed = lex_module(src)
        if lexed is None:
            return set()
        specs = {imp["n"] for imp in lexed["imports"] if imp.get("n")}
        specs.update(lexed.get("starFrom") or ())
        return {s for s in specs if s and not s.startswith((".", "/"))}

    def test_pregenerated_js_bundles_can_be_built(self):
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
