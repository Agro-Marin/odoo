import logging

from odoo.modules import Manifest
from odoo.tests import tagged
from odoo.tools.assets.esm_graph import (
    find_escaping_relative_imports,
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

    def test_every_esm_bundle_compiles(self):
        """A bare specifier can name a module that exists and an export that does not.

        The two checks above ask whether the bundle's *file list* resolves and
        whether its *relative* imports stay inside it. Neither reads a bare
        `@addon/...` specifier's named bindings, so an import of a symbol its
        module no longer exports passes both and then fails in esbuild, which
        is the first thing that actually links them.

        Measured on `bf19a83c9ab`, which renamed `resequenceRecords` to
        `resequence` in `web` and left `enterprise/web_map` importing the old
        name: `web.assets_web`, `web.assets_web_dark` and
        `web.assets_web_print` all stopped compiling, so the backend answered
        500 for every user of any database carrying enterprise. Both sibling
        methods passed throughout, at every scope.

        Compiles rather than trusting `_is_esbuild_fail_closed()`, which is off
        unless `--test-enable` or `dev_mode=assets` is set: a gate that only
        fires when a switch happens to be on is a gate whose absence looks like
        a pass.
        """
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

    # `web/static/src/libs/*` are third-party wrappers a bundle must list
    # explicitly: nothing pulls them in transitively, and a bare specifier that
    # names a module the bundle does not carry resolves to `undefined` rather
    # than failing to load, so the fault only surfaces at the first call site.
    LIB_SPECIFIERS = (
        "@web/libs/bootstrap",
        "@web/libs/popper_compat",
    )

    # Bundles that import a lib wrapper without carrying it because they are
    # only ever loaded onto a document that already carries one. Exempted by
    # name so the gate stands aside knowingly rather than being blind.
    LIB_INHERITING_BUNDLES = {
        # Loaded on the same frontend document as `web.assets_frontend`.
        "web.assets_frontend_minimal",
        # Loaded into the editable iframe, over `web.assets_frontend`.
        "website.assets_inside_builder_iframe",
        # Declares `web.assets_unit_tests_setup` in `import_map_includes`.
        "web.assets_unit_tests",
    }

    def test_every_bundled_module_carries_the_libs_it_imports(self):
        """A bare specifier for a bundled third-party lib must be in the bundle.

        `9251982dca8` retired Bootstrap's JS from the backend. Three builder
        modules kept importing `@web/libs/bootstrap` from bundles that do not
        carry it; the import silently yielded `undefined` and every use threw
        `TypeError: ... reading 'getInstance'`, breaking snippet removal in the
        website builder. Neither existing gate saw it: one checks that the
        target *file* exists, the other checks *relative* imports only -- and
        tells you to spell the import bare, which is the spelling it stops
        checking.
        """
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
        """Every non-relative specifier `module` imports."""
        src = module.raw_content or ""
        lexed = lex_module(src)
        if lexed is None:
            return set()
        specs = {imp["n"] for imp in lexed["imports"] if imp.get("n")}
        specs.update(lexed.get("starFrom") or ())
        return {s for s in specs if s and not s.startswith((".", "/"))}

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
