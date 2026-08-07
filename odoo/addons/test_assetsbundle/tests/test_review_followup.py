import re
from types import SimpleNamespace
from unittest.mock import Mock, patch

from odoo.tests.common import BaseCase

from odoo.addons.base.models import assetsbundle as _ab
from odoo.addons.base.models.assetsbundle import (
    AssetsBundle,
    CssPipeline,
    JavascriptAsset,
    PreprocessedCSS,
    ScssStylesheetAsset,
    StylesheetAsset,
    XMLAsset,
    XmlTemplatePipeline,
    _rewrite_css_outside_strings,
)


class TestPreprocessCssErrorContract(BaseCase):
    def _pipeline(self, stylesheets):
        bundle = SimpleNamespace(
            stylesheets=stylesheets,
            css_errors=[],
            autoprefix=False,
            rtl=False,
            name="test.bundle",
            is_debug_assets=False,
        )
        return CssPipeline(bundle), bundle

    def test_compile_failure_returns_empty_not_raw_source(self):
        scss = Mock(spec=ScssStylesheetAsset)
        scss.get_source.return_value = "$x: 1; a {}"
        scss.minify.return_value = "RAW_UNCOMPILED_SCSS"
        scss.errors = []
        self.assertIsInstance(scss, PreprocessedCSS)

        pipeline, bundle = self._pipeline([scss])

        def failing_compile_css(compiler, source):
            bundle.css_errors.append("Sass: something broke")
            return ""

        pipeline.compile_css = failing_compile_css

        result = pipeline.preprocess()
        self.assertEqual(result, "")
        self.assertEqual(bundle.css_errors, ["Sass: something broke"])

    def test_leaf_asset_error_still_ships_partial_bundle(self):
        plain = Mock(spec=StylesheetAsset)
        plain._content = None
        plain.errors = []

        def _minify():
            plain.errors.append("audit_missing.css does not exist.")
            return "body{color:red}"

        plain.minify.side_effect = _minify
        pipeline, bundle = self._pipeline([plain])

        result = pipeline.preprocess()
        self.assertEqual(result, "body{color:red}")
        self.assertIn("audit_missing.css does not exist.", bundle.css_errors)

    def test_clean_compile_returns_bundle(self):
        plain = Mock(spec=StylesheetAsset)
        plain.minify.return_value = "body{color:red}"
        plain.errors = []
        pipeline, bundle = self._pipeline([plain])

        result = pipeline.preprocess()
        self.assertEqual(result, "body{color:red}")
        self.assertEqual(bundle.css_errors, [])

    def test_no_stylesheets_short_circuits(self):
        pipeline, _ = self._pipeline([])
        self.assertEqual(pipeline.preprocess(), "")


class TestMinifyNulGuard(BaseCase):
    def test_nul_digit_no_longer_crashes(self):
        out = StylesheetAsset._minify_css_body("a{}\x000\x00b{}")
        self.assertNotIn("\x00", out)
        self.assertIn("a{}", out)
        self.assertIn("b{}", out)

    def test_strip_does_not_disturb_normal_minification(self):
        self.assertIn('"x   y"', StylesheetAsset._minify_css_body('a{content:"x   y"}'))
        out = StylesheetAsset._minify_css_body(
            "/*! keep */ a{color:red} /* drop */ b{}"
        )
        self.assertIn("/*! keep */", out)
        self.assertNotIn("drop", out)


class TestUrlRewriteStringBoundary(BaseCase):
    rx = StylesheetAsset.rx_url

    def _rewrite(self, css):
        def repl(match):
            q = match.group("q")
            return f"url({q}REW/{match.group('body')}{q}"

        return _rewrite_css_outside_strings(self.rx, repl, css)

    def test_real_url_is_rewritten(self):
        self.assertIn("REW/", self._rewrite("a{background:url(x.png)}"))

    def test_quoted_real_url_is_rewritten(self):
        self.assertIn('url("REW/x', self._rewrite('a{background:url("x.png")}'))

    def test_multi_url_src_list_all_rewritten(self):
        out = self._rewrite(
            'src:url("./l/a.eot?#iefix") format("embedded-opentype"),'
            'url("./l/a.woff") format("woff"),'
            "url('./l/a.ttf') format('truetype');"
        )
        self.assertEqual(out.count("REW/"), 3, out)
        self.assertIn('format("woff")', out)
        self.assertIn("format('truetype')", out)

    def test_quoted_url_with_space_is_left_untouched(self):
        out = self._rewrite('a{background:url("x y.png")}')
        self.assertNotIn("REW/", out)
        self.assertIn('url("x y.png")', out)

    def test_consecutive_imports_all_rewritten(self):

        def repl(match):
            q = match.group("q")
            return f"@import {q}REW/{match.group('path')}{q}"

        out = _rewrite_css_outside_strings(
            StylesheetAsset.rx_import,
            repl,
            '@import "a.css"; @import "b.css";',
        )
        self.assertEqual(out.count("REW/"), 2, out)

    def test_url_inside_string_value_is_skipped(self):
        out = self._rewrite('a{content:"hello url(x.png) y"}')
        self.assertNotIn("REW/", out)
        self.assertIn('"hello url(x.png) y"', out)

    def test_raw_regex_remains_permissive(self):
        self.assertEqual(len(self.rx.findall('a{content:"hello url(x.png) y"}')), 1)


class TestPreprocessCssAtRulesIdempotent(BaseCase):
    _COMPILED = '@charset "UTF-8";\n/*! odoo-split:abc123 */\nh1{color:red}'

    def _pipeline(self, rtl=False):
        scss = Mock(spec=ScssStylesheetAsset)
        scss.id = "abc123"
        scss.get_source.return_value = "/*! odoo-split:abc123 */\nh1{}"
        scss.minify.return_value = "h1{color:red}"
        scss.errors = []
        bundle = SimpleNamespace(
            stylesheets=[scss],
            css_errors=[],
            autoprefix=False,
            rtl=rtl,
            name="test.bundle",
            is_debug_assets=False,
        )
        pipeline = CssPipeline(bundle)
        pipeline.compile_css = lambda compiler, source: self._COMPILED
        pipeline.run_rtlcss = lambda source: source
        return pipeline, bundle

    def test_source_list_untouched_atrules_in_render_list(self):
        pipeline, bundle = self._pipeline()
        out1 = pipeline.preprocess()
        self.assertEqual(len(bundle.stylesheets), 1, "source list must not be mutated")
        self.assertEqual(
            len(pipeline._rendered_assets), 2, "@at-rules prepended to the render list"
        )
        self.assertEqual(out1.count("@charset"), 1)

    def test_rerun_does_not_stack_at_rules(self):
        pipeline, bundle = self._pipeline()
        pipeline.preprocess()
        out2 = pipeline.preprocess()
        self.assertEqual(
            len(bundle.stylesheets), 1, "re-run must not mutate the source"
        )
        self.assertEqual(
            len(pipeline._rendered_assets), 2, "render list rebuilt, not stacked"
        )
        self.assertEqual(out2.count("@charset"), 1, "@charset must not be duplicated")

    def test_rerun_idempotent_under_rtl(self):
        pipeline, bundle = self._pipeline(rtl=True)
        pipeline.preprocess()
        pipeline.preprocess()
        out3 = pipeline.preprocess()
        self.assertEqual(len(bundle.stylesheets), 1)
        self.assertEqual(len(pipeline._rendered_assets), 2)
        self.assertEqual(out3.count("@charset"), 1)


class TestCssErrorBannerBackslashEscape(BaseCase):
    def test_backslash_is_escaped_not_interpreted(self):
        banner = AssetsBundle._render_css_error_banner([r"C:\foo broke"], "")
        content_line = next(ln for ln in banner.splitlines() if "C:" in ln)
        self.assertIn(r"C:\\foo", content_line)

    def test_quote_escape_stays_single_backslash(self):
        banner = AssetsBundle._render_css_error_banner(['say "hi"'], "")
        content_line = next(ln for ln in banner.splitlines() if "say" in ln)
        self.assertIn(r"say \"hi\"", content_line)
        self.assertNotIn(r"\\\"", content_line)


class TestBacktickMinifyGate(BaseCase):
    _TARGET = "odoo.addons.base.models.assetsbundle.assets.minify_js"

    def _routes_to_esbuild(self, code):
        asset = JavascriptAsset(SimpleNamespace(name="b"), inline=code)
        with patch(self._TARGET, return_value="ESB") as minify_js:
            asset.minify()
        return minify_js.called

    def test_no_backtick_uses_rjsmin(self):
        self.assertFalse(self._routes_to_esbuild("var x = 1;\n"))

    def test_backtick_without_interpolation_uses_rjsmin(self):
        self.assertFalse(self._routes_to_esbuild("var x = `a   b`;\n"))

    def test_nested_interpolation_uses_esbuild(self):
        self.assertTrue(self._routes_to_esbuild("var x = `${`a   b`}`;\n"))

    def test_rjsmin_path_preserves_top_level_literal(self):
        asset = JavascriptAsset(SimpleNamespace(name="b"), inline="var x = `a   b`;\n")
        self.assertIn("a   b", asset.minify())


class TestJsContentPredicates(BaseCase):
    def _has_legacy_templates(self, templates, esm):
        fake = SimpleNamespace(templates=templates, _is_esm_bundle=esm)
        return AssetsBundle._has_legacy_templates.fget(fake)

    def _has_js_content(self, javascripts, legacy_templates):
        fake = SimpleNamespace(
            javascripts=javascripts, _has_legacy_templates=legacy_templates
        )
        return AssetsBundle.has_js_content.fget(fake)

    def test_legacy_templates_only_for_non_esm(self):
        self.assertTrue(self._has_legacy_templates(["t"], esm=False))
        self.assertFalse(self._has_legacy_templates(["t"], esm=True))
        self.assertFalse(self._has_legacy_templates([], esm=False))

    def test_has_js_content_combines_js_and_templates(self):
        self.assertTrue(self._has_js_content(["j"], False))
        self.assertTrue(self._has_js_content([], True))
        self.assertFalse(self._has_js_content([], False))


class _MissRecordset:
    def __bool__(self):
        return False

    def __len__(self):
        return 0

    def ensure_one(self):
        raise ValueError("empty recordset")


class _MissAttachModel:
    def sudo(self):
        return self

    def _get_serve_attachment(self, url):
        return _MissRecordset()


class TestPreprocessLeafErrorRebuilt(BaseCase):
    _MISSING = "/web/static/src/audit_missing.scss"

    def _bundle_with_missing_scss(self, autoprefix=False, rtl=False):
        bundle = SimpleNamespace(
            stylesheets=[],
            css_errors=[],
            autoprefix=autoprefix,
            rtl=rtl,
            name="test.bundle",
            is_debug_assets=False,
            env={"ir.attachment": _MissAttachModel()},
        )
        asset = ScssStylesheetAsset(bundle, url=self._MISSING)
        bundle.stylesheets.append(asset)
        return bundle, asset

    def test_single_call_compile_failure_reports_leaf_once(self):
        bundle, _asset = self._bundle_with_missing_scss()
        pipeline = CssPipeline(bundle)

        def failing_compile(compiler, source):
            bundle.css_errors.append("Sass: build broke")
            return ""

        pipeline.compile_css = failing_compile

        self.assertEqual(pipeline.preprocess(), "")
        leaf_msg = f"Could not find {self._MISSING}"
        self.assertEqual(bundle.css_errors.count(leaf_msg), 1)
        self.assertIn("Sass: build broke", bundle.css_errors)

    def test_rerun_does_not_accumulate_leaf_errors(self):
        bundle, asset = self._bundle_with_missing_scss()
        pipeline = CssPipeline(bundle)
        pipeline.compile_css = lambda compiler, source: source

        leaf_msg = f"Could not find {self._MISSING}"
        for _ in range(3):
            pipeline.preprocess()
            self.assertEqual(bundle.css_errors.count(leaf_msg), 1)
        self.assertEqual(asset.errors.count(leaf_msg), 1)


class TestAutoprefixImportStringBoundary(BaseCase):
    def test_autoprefix_rewrites_real_declaration(self):
        out = CssPipeline._autoprefix_css("a{appearance:none}")
        self.assertIn("-webkit-appearance:none", out)
        self.assertIn("-moz-appearance:none", out)

    def test_autoprefix_skips_string_literal(self):
        out = CssPipeline._autoprefix_css('.x{content:" appearance: auto"}')
        self.assertNotIn("-webkit-appearance", out)
        self.assertIn('" appearance: auto"', out)

    def test_import_hoist_matches_real_rule(self):
        self.assertEqual(
            CssPipeline.rx_css_import.findall('@import "a.css";\nbody{}'),
            ['@import "a.css";'],
        )

    def test_import_hoist_skips_string_literal(self):
        collected = []

        def take(match):
            collected.append(match.group(0))
            return ""

        out = _rewrite_css_outside_strings(
            CssPipeline.rx_css_import, take, '.x{content:"@import url(evil);"}'
        )
        self.assertEqual(collected, [])
        self.assertEqual(out, '.x{content:"@import url(evil);"}')

    def test_hoist_import_rules_extracts_only_real_rules(self):
        pipeline = CssPipeline.__new__(CssPipeline)
        rules, remainder = pipeline.hoist_import_rules(
            '@import "a.css";\n.x{content:"@import url(evil);"}\nbody{}'
        )
        self.assertEqual(rules, ['@import "a.css";'])
        self.assertIn('content:"@import url(evil);"', remainder)
        self.assertNotIn('@import "a.css"', remainder)


class TestRewriteScannerDotallScope(BaseCase):
    def test_dot_in_target_does_not_span_newlines(self):
        hits = []
        _rewrite_css_outside_strings(
            re.compile(r"X.Y"), lambda m: hits.append(m.group(0)) or "H", "X\nY"
        )
        self.assertEqual(hits, [], "target's '.' must not gain DOTALL")

    def test_target_with_explicit_dotall_is_respected(self):
        hits = []
        _rewrite_css_outside_strings(
            re.compile(r"X.Y", re.DOTALL),
            lambda m: hits.append(m.group(0)) or "H",
            "X\nY",
        )
        self.assertEqual(hits, ["X\nY"])

    def test_multiline_comment_still_protected(self):
        out = _rewrite_css_outside_strings(
            StylesheetAsset.rx_url, lambda m: "U", "a/*\n c \n*/ url(z)"
        )
        self.assertIn("/*\n c \n*/", out)
        self.assertIn("U", out)


class TestMinifySourceMapStringAware(BaseCase):
    @staticmethod
    def _min(css):
        return StylesheetAsset._minify_css_body(css)

    def test_real_sourcemap_link_is_stripped(self):
        out = self._min("a{color:red}\n/*# sourceMappingURL=app.css.map */")
        self.assertNotIn("sourceMappingURL", out)
        self.assertIn("a{color:red}", out)

    def test_sourcemap_text_inside_string_is_preserved(self):
        out = self._min('a::before{content:"/*# sourceMappingURL=x */ keep"}')
        self.assertIn('"/*# sourceMappingURL=x */ keep"', out)


class TestRunRtlcssEmptyOutputGuard(BaseCase):
    def _run(self, source, fake_out):
        bundle = SimpleNamespace(css_errors=[], name="t.b", stylesheets=[])
        pipe = CssPipeline(bundle)
        CssPipeline._compiled_cache.clear()
        with (
            patch.object(_ab.css_pipeline, "_check_rtlcss", return_value=True),
            patch.object(_ab.css_pipeline, "_rtlcss_bin", return_value="rtlcss"),
            patch.object(
                _ab.css_pipeline, "_rtlcss_config_path", return_value="/x.json"
            ),
            patch.object(_ab.css_pipeline, "_run_cli_pipe", return_value=fake_out),
        ):
            result = pipe.run_rtlcss(source)
        return result, bundle.css_errors

    def test_whitespace_only_output_surfaces_error(self):
        result, errors = self._run("body{color:red}", "  \n")
        self.assertEqual(result, "")
        self.assertTrue(errors, "a swallowed-to-whitespace payload must banner")

    def test_empty_output_surfaces_error(self):
        result, errors = self._run("body{color:red}", "")
        self.assertEqual(result, "")
        self.assertTrue(errors)

    def test_normal_output_passes_through(self):
        result, errors = self._run("body{color:red}", "body{color:red}")
        self.assertEqual(result, "body{color:red}")
        self.assertFalse(errors)

    def test_whitespace_only_source_is_not_a_false_positive(self):
        _result, errors = self._run("   \n  ", "")
        self.assertFalse(errors, "empty output for an empty payload is fine")


class TestEsmTemplateBundleForms(BaseCase):
    _TPL = '<templates><t t-name="my.module.Widget">hi</t></templates>'

    def _bundle(self):
        bundle = SimpleNamespace(name="my.bundle", env=None)
        bundle.templates = [XMLAsset(bundle, inline=self._TPL)]
        return XmlTemplatePipeline(bundle)

    def test_debug_form_uses_native_import(self):
        out = self._bundle().generate_esm_template_bundle(use_import=True)
        self.assertIn("import {", out)
        self.assertIn('from "@web/core/templates";', out)
        self.assertIn('registerTemplate("my.module.Widget"', out)

    def test_production_form_uses_loader_get(self):
        out = self._bundle().generate_esm_template_bundle(use_import=False)
        self.assertIn('odoo.loader.modules.get("@web/core/templates")', out)
        self.assertNotIn("import {", out)
        self.assertIn('registerTemplate("my.module.Widget"', out)

    def test_empty_templates_yield_empty_string(self):
        bundle = SimpleNamespace(name="my.bundle", env=None, templates=[])
        self.assertEqual(XmlTemplatePipeline(bundle).generate_esm_template_bundle(), "")


class TestEsbuildCompilerAddonFlagsSeam(BaseCase):
    def test_provider_is_threaded_into_compiler(self):
        def sentinel(root):
            return (["--alias:x=y"], [])

        fake = SimpleNamespace(
            name="some.bundle",
            native_modules=[],
            javascripts=[],
            _get_esbuild_addon_flags=sentinel,
        )
        compiler = AssetsBundle._make_esbuild_compiler(fake)
        self.assertIs(compiler._addon_flags_provider, sentinel)


class TestImportMapSpecCollision(BaseCase):
    _LOG = "odoo.assets.bundle"

    @staticmethod
    def _mod(module_path, url, alias=None):
        header = {"alias": alias} if alias else None
        return SimpleNamespace(module_path=module_path, url=url, parsed_header=header)

    def _data(self, modules):
        fake = SimpleNamespace(native_modules=modules, name="my.bundle")
        return AssetsBundle._native_module_data(fake, with_bridges=False)

    def test_colliding_specs_warn_and_keep_last_wins(self):
        mods = [
            self._mod("@web/foo", "/web/static/src/foo.js"),
            self._mod("@web/foo", "/web/static/src/foo/index.js"),
        ]
        with self.assertLogs(self._LOG, level="WARNING") as cm:
            data = self._data(mods)
        self.assertIn("import_map_spec_collision", "\n".join(cm.output))
        self.assertEqual(data["import_map"]["@web/foo"], "/web/static/src/foo/index.js")

    def test_colliding_alias_warns(self):
        mods = [
            self._mod("@web/a", "/web/static/src/a.js", alias="shared"),
            self._mod("@web/b", "/web/static/src/b.js", alias="shared"),
        ]
        with self.assertLogs(self._LOG, level="WARNING") as cm:
            self._data(mods)
        self.assertIn("kind=alias", "\n".join(cm.output))

    def test_single_module_spec_and_index_longform_do_not_warn(self):
        mods = [self._mod("@web/foo", "/web/static/src/foo/index.js")]
        with self.assertNoLogs(self._LOG, level="WARNING"):
            data = self._data(mods)
        self.assertEqual(data["import_map"]["@web/foo"], "/web/static/src/foo/index.js")
        self.assertEqual(
            data["import_map"]["@web/foo/index"], "/web/static/src/foo/index.js"
        )
