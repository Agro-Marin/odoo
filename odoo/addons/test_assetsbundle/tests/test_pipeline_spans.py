import re
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import BaseCase, TransactionCase

from odoo.addons.base.models.assetsbundle import (
    AssetsBundle,
    SassStylesheetAsset,
    ScssStylesheetAsset,
    StylesheetAsset,
    XMLAssetError,
)
from odoo.addons.base.models.assetsbundle import bundle as bundle_module
from odoo.addons.base.models.assetsbundle.common import (
    _SCSS_STATEMENT_SPANS,
    _pipeline_fingerprint,
    _rewrite_css_outside_strings,
)
from odoo.addons.base.models.assetsbundle.css_pipeline import CssPipeline

FORBIDDEN = "../../secret"


def _file(url, content, last_modified=1.0):
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


def _sanitized(source):
    bundle = SimpleNamespace(css_errors=[], name="test.spans", stylesheets=[])
    out = CssPipeline(bundle).compile_css(lambda src: src, source)
    return out, bundle.css_errors


class TestImportSanitizerSpans(BaseCase):
    def test_protocol_relative_url_does_not_hide_later_import(self):
        out, errors = _sanitized(
            f'.a{{background:url(//cdn.x/y.png)}} @import "{FORBIDDEN}";'
        )
        self.assertTrue(errors, "the local import must still be rejected")
        self.assertNotIn(FORBIDDEN, out)
        self.assertIn("url(//cdn.x/y.png)", out, "the href itself is untouched")

    def test_absolute_url_does_not_hide_later_import(self):
        out, errors = _sanitized(
            f'.a{{background:url(https://cdn.x/y.png)}} @import "{FORBIDDEN}";'
        )
        self.assertTrue(errors)
        self.assertNotIn(FORBIDDEN, out)

    def test_real_line_comment_still_ends_at_newline(self):
        out, errors = _sanitized(f'// note\n@import "{FORBIDDEN}";')
        self.assertTrue(errors, "a comment protects its own line, not the next")
        self.assertIn("// note", out)

    def test_import_inside_block_comment_is_untouched(self):
        source = f'/* @import "{FORBIDDEN}"; */ @import "bootstrap";'
        out, errors = _sanitized(source)
        self.assertFalse(errors)
        self.assertEqual(out, source)

    def test_import_inside_string_is_untouched(self):
        source = f'$s: "@import \'{FORBIDDEN}\';";\n@import "bootstrap";'
        out, errors = _sanitized(source)
        self.assertFalse(errors)
        self.assertEqual(out, source)

    def test_media_aware_dedup_survives_the_rewrite(self):
        out, _ = _sanitized('@import "foo" screen;\n@import "foo" screen;')
        self.assertEqual(out, '@import "foo" screen;')
        out, _ = _sanitized('@import "foo" screen;\n@import "foo" print;')
        self.assertEqual(out, '@import "foo" screen;\n@import "foo" print;')


class TestProtectedSpanDispatch(BaseCase):
    def test_url_span_reaches_repl_never(self):
        seen = []

        def repl(match):
            seen.append(match.group(0))
            return "REWRITTEN"

        out = _rewrite_css_outside_strings(
            re.compile(r"(cdn\.x)"),
            repl,
            ".a{background:url(//cdn.x/y.png)}",
            _SCSS_STATEMENT_SPANS,
        )
        self.assertEqual(seen, [], "a url(...) span is opaque, not code")
        self.assertEqual(out, ".a{background:url(//cdn.x/y.png)}")

    def test_code_outside_the_span_is_still_rewritten(self):
        out = _rewrite_css_outside_strings(
            re.compile(r"(cdn\.x)"),
            lambda m: "REWRITTEN",
            ".cdn.x{background:url(//cdn.x/y.png)}",
            _SCSS_STATEMENT_SPANS,
        )
        self.assertEqual(out, ".REWRITTEN{background:url(//cdn.x/y.png)}")

    def test_target_groups_are_readable_by_name(self):
        out = _rewrite_css_outside_strings(
            StylesheetAsset.rx_url,
            lambda m: f"url({m.group('q')}X/{m.group('body')}{m.group('q')})",
            "a{background:url('img/x.png')}",
        )
        self.assertEqual(out, "a{background:url('X/img/x.png'))}")


class TestUrlFragmentReferences(BaseCase):
    WEB_DIR = "/mod/static/src/css"

    def _rewritten(self, css):
        import posixpath

        def repl(match):
            q, body = match.group("q"), match.group("body")
            if not body:
                return f"url({q}{self.WEB_DIR}/{q}"
            return f"url({q}{posixpath.normpath(f'{self.WEB_DIR}/{body}')}{q}"

        return _rewrite_css_outside_strings(
            StylesheetAsset.rx_url, repl, css, StylesheetAsset._SOURCE_TOKEN_RE
        )

    def test_fragment_reference_is_left_alone(self):
        for css in (
            ".a{mask:url(#alttext-manager-mask)}",
            ".a{clip-path:url(#clip)}",
            ".a{behavior:url(#default#VML)}",
        ):
            self.assertEqual(self._rewritten(css), css, css)

    def test_interpolated_leading_segment_is_still_rewritten(self):
        self.assertEqual(
            self._rewritten('@font-face{src:url("#{$lato-font-path}/Lato-Reg.eot")}'),
            '@font-face{src:url("/mod/static/src/css/#{$lato-font-path}/Lato-Reg.eot")}',
        )
        self.assertEqual(
            self._rewritten('.a{background:url("#{$p}/#{$f}/#{$f}.woff")}'),
            '.a{background:url("/mod/static/src/css/#{$p}/#{$f}/#{$f}.woff")}',
        )

    def test_str_function_interpolation_is_left_alone(self):
        for css in (
            "a{background:url(\"#{str-slice(o-website-value('body-image'), 2)}\")}",
            "a{background:url(\"#{str-replace(str-slice($s, 1, -2), 'a', 'b')}\")}",
        ):
            self.assertEqual(self._rewritten(css), css, css)

    def test_relative_paths_are_still_rewritten(self):
        self.assertEqual(
            self._rewritten(".a{background:url(img/x.png)}"),
            ".a{background:url(/mod/static/src/css/img/x.png)}",
        )
        self.assertEqual(
            self._rewritten('.a{background:url("img/x.png")}'),
            '.a{background:url("/mod/static/src/css/img/x.png")}',
        )

    def test_absolute_and_data_urls_are_still_skipped(self):
        for css in (
            ".a{background:url(https://x/y.png)}",
            ".a{background:url(/abs/y.png)}",
            ".a{background:url(data:image/gif;base64,AA)}",
        ):
            self.assertEqual(self._rewritten(css), css, css)


class TestAssetExtensionTable(TransactionCase):
    def test_extension_tables_match_the_constants(self):
        from odoo.libs.constants import (
            SCRIPT_EXTENSIONS,
            STYLE_EXTENSIONS,
            TEMPLATE_EXTENSIONS,
        )

        self.assertEqual(set(STYLE_EXTENSIONS), set(AssetsBundle._STYLESHEET_TYPES))
        self.assertEqual(set(SCRIPT_EXTENSIONS), set(AssetsBundle._SCRIPT_TYPES))
        self.assertEqual(set(TEMPLATE_EXTENSIONS), set(AssetsBundle._TEMPLATE_TYPES))

    def test_query_string_does_not_hide_the_extension(self):
        bundle = AssetsBundle(
            "test.query_ext",
            [
                _file("/m/static/src/a.css?v=2", "a{}"),
                _file("/m/static/src/b.js#frag", "//b"),
            ],
            env=self.env,
        )
        self.assertEqual(len(bundle.stylesheets), 1)
        self.assertEqual(len(bundle.javascripts) + len(bundle.native_modules), 1)

    def test_sass_file_builds_a_sass_asset(self):
        bundle = AssetsBundle(
            "test.sass_ext",
            [_file("/mod/static/src/a.sass", ".x\n  color: red\n")],
            env=self.env,
        )
        self.assertEqual(len(bundle.stylesheets), 1)
        self.assertIsInstance(bundle.stylesheets[0], SassStylesheetAsset)

    def test_sass_cli_selects_the_indented_syntax(self):
        scss = ScssStylesheetAsset(None, inline="// x")
        sass = SassStylesheetAsset(None, inline="// x")
        self.assertEqual(scss._sass_syntax, "scss")
        self.assertEqual(sass._sass_syntax, "indented")
        self.assertIn("--no-indented", scss.get_command())
        self.assertIn("--indented", sass.get_command())
        self.assertNotIn("--no-indented", sass.get_command())

    def test_sass_bundle_compiles_end_to_end(self):
        bundle = AssetsBundle(
            "test.sass_compile",
            [_file("/mod/static/src/a.sass", ".audit-sass\n  color: red\n")],
            env=self.env,
        )
        css = bundle.preprocess_css()
        self.assertFalse(bundle.css_errors, bundle.css_errors)
        self.assertIn(".audit-sass", css)
        self.assertIn("color:red", css.replace(" ", ""))

    def test_sass_compiles_the_same_on_the_cli_fallback(self):
        from odoo.tools import sass_embedded

        source = ".audit-sass\n  color: red\n  &:hover\n    color: blue\n"
        spec = [_file("/mod/static/src/a.sass", source)]

        embedded = AssetsBundle("test.sass_emb", spec, env=self.env).preprocess_css()
        with patch.object(
            sass_embedded, "get_sass_compiler", side_effect=RuntimeError("forced")
        ):
            cli = AssetsBundle("test.sass_cli", spec, env=self.env).preprocess_css()

        self.assertIn(".audit-sass:hover", embedded)
        self.assertEqual(embedded.strip(), cli.strip())

    def test_mixed_dialects_degrade_instead_of_raising(self):
        bundle = AssetsBundle(
            "test.sass_mixed",
            [
                _file("/mod/static/src/a.sass", ".x\n  color: red\n"),
                _file("/mod/static/src/b.scss", ".y{color:blue}"),
            ],
            env=self.env,
        )
        self.assertEqual(bundle.preprocess_css(), "")
        self.assertTrue(bundle.css_errors)
        self.assertIn("dialects", bundle.css_errors[0])


class TestXmlParseFailureIsCached(TransactionCase):
    def _broken_bundle(self):
        return AssetsBundle(
            "test.badxml",
            [_file("/m/static/src/a.xml", "<templates><t t-name='x'></templates>")],
            env=self.env,
        )

    def test_parse_is_attempted_once(self):
        asset = self._broken_bundle().templates[0]
        with patch.object(
            type(asset), "_raw_source", wraps=asset._raw_source
        ) as raw_source:
            for _ in range(4):
                with self.assertRaises(XMLAssetError):
                    _ = asset.template_elements
        self.assertEqual(raw_source.call_count, 1)

    def test_the_error_still_surfaces_every_time(self):
        asset = self._broken_bundle().templates[0]
        errors = []
        for _ in range(3):
            with self.assertRaises(XMLAssetError) as caught:
                _ = asset.template_elements
            errors.append(str(caught.exception))
        self.assertEqual(len(set(errors)), 1)
        self.assertIn("Invalid XML template", errors[0])


class TestChecksumSeparator(TransactionCase):
    def test_pipeline_change_invalidates_the_version(self):
        spec = [_file("/a.css", "a{}", 1.0)]
        before = AssetsBundle("test.fp", spec, env=self.env).get_version("css")
        with patch.object(
            bundle_module, "_pipeline_fingerprint", return_value="pretend-new-code"
        ):
            after = AssetsBundle("test.fp", spec, env=self.env).get_version("css")
        self.assertNotEqual(before, after)

    def test_the_superseded_attachment_is_not_left_behind(self):
        name = "test.supersede"
        spec = [_file("/mod/static/src/a.css", "a{color:red}")]

        def urls():
            return set(
                self.env["ir.attachment"]
                .sudo()
                .search([("name", "=like", f"{name}%")])
                .mapped("url")
            )

        with patch.object(
            bundle_module, "_pipeline_fingerprint", return_value="previous-code"
        ):
            AssetsBundle(name, spec, env=self.env).css()
        before = urls()
        self.assertEqual(len(before), 1)

        served = AssetsBundle(name, spec, env=self.env).css()
        after = urls()

        self.assertEqual(len(after), 1, "exactly one version survives")
        self.assertEqual(after, {served.url})
        self.assertFalse(before & after, "the superseded row was deleted")

    def test_fingerprint_is_stable_within_a_release(self):
        _pipeline_fingerprint.cache_clear()
        first = _pipeline_fingerprint()
        _pipeline_fingerprint.cache_clear()
        self.assertEqual(first, _pipeline_fingerprint())
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_ambiguous_split_is_not_a_collision(self):
        two = AssetsBundle(
            "test.sep",
            [_file("/a.js", "//a", 1.0), _file("/b.js", "//b", 2.0)],
            env=self.env,
        )
        one = AssetsBundle(
            "test.sep",
            [_file("/a.js,1.0/b.js", "//ab", 2.0)],
            env=self.env,
        )
        self.assertEqual(
            "".join(a.unique_descriptor for a in two.javascripts),
            "".join(a.unique_descriptor for a in one.javascripts),
            "precondition: the descriptors concatenate to the same string",
        )
        self.assertNotEqual(two.get_version("js"), one.get_version("js"))
