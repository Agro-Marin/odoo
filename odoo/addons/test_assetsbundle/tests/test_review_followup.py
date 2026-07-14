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
    """``CssPipeline.preprocess`` hands back ``""`` on a bundle-level failure.

    The pipeline is bound to a fake bundle (a ``SimpleNamespace`` carrying only
    the attributes ``preprocess`` touches), so the contract is provable without
    a real bundle, a cursor, or a Sass install.
    """

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
        """A Sass failure (compile_css -> "" + recorded error) must yield "",
        not the uncompiled SCSS the split/minify fallback would assemble."""
        scss = Mock(spec=ScssStylesheetAsset)  # isinstance PreprocessedCSS -> True
        scss.get_source.return_value = "$x: 1; a {}"
        scss.minify.return_value = "RAW_UNCOMPILED_SCSS"  # would be served pre-fix
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
        """A per-asset fetch error is NOT a bundle-level failure: compilation
        succeeded, so the good assets are validly compiled and the partial
        bundle is returned (css() still banners on the harvested error). Only a
        bundle-level compile/rtl failure short-circuits to ""; this guards the
        narrow boundary against regressing back to "any css_errors -> ''"."""
        plain = Mock(spec=StylesheetAsset)  # not a PreprocessedCSS
        plain._content = None
        plain.errors = []

        # A real StylesheetAsset records its fetch/rewrite error WHILE minify()
        # pulls content; preprocess clears asset.errors first and rebuilds it
        # this run, so model the error as recorded during minify() rather than
        # pre-seeded (a pre-seeded list is now reset before the run).
        def _minify():
            plain.errors.append("audit_missing.css does not exist.")
            return "body{color:red}"

        plain.minify.side_effect = _minify
        pipeline, bundle = self._pipeline([plain])

        result = pipeline.preprocess()
        self.assertEqual(result, "body{color:red}")
        self.assertIn("audit_missing.css does not exist.", bundle.css_errors)

    def test_clean_compile_returns_bundle(self):
        """No errors -> the assembled, minified bundle is returned verbatim."""
        plain = Mock(spec=StylesheetAsset)
        plain.minify.return_value = "body{color:red}"
        plain.errors = []
        pipeline, bundle = self._pipeline([plain])

        result = pipeline.preprocess()
        self.assertEqual(result, "body{color:red}")
        self.assertEqual(bundle.css_errors, [])

    def test_no_stylesheets_short_circuits(self):
        """The empty-bundle guard is unchanged."""
        pipeline, _ = self._pipeline([])
        self.assertEqual(pipeline.preprocess(), "")


class TestMinifyNulGuard(BaseCase):
    """``_minify_css_body`` tolerates a NUL byte in the source.

    A bare ``\\x00<digits>\\x00`` in ordinary CSS text used to be caught by
    the placeholder-restore regex and index into an empty ``protected``
    list -> IndexError, aborting the whole bundle's CSS compile.
    """

    def test_nul_digit_no_longer_crashes(self):
        out = StylesheetAsset._minify_css_body("a{}\x000\x00b{}")
        self.assertNotIn("\x00", out)
        # the surrounding rules survive the strip
        self.assertIn("a{}", out)
        self.assertIn("b{}", out)

    def test_strip_does_not_disturb_normal_minification(self):
        """Regression guard: the NUL strip leaves string/comment handling intact."""
        # whitespace inside a string literal is preserved
        self.assertIn('"x   y"', StylesheetAsset._minify_css_body('a{content:"x   y"}'))
        # /*! legal comment kept, ordinary comment dropped
        out = StylesheetAsset._minify_css_body(
            "/*! keep */ a{color:red} /* drop */ b{}"
        )
        self.assertIn("/*! keep */", out)
        self.assertNotIn("drop", out)


class TestUrlRewriteStringBoundary(BaseCase):
    """``url()`` rewriting is string-aware via ``_rewrite_css_outside_strings``.

    The raw ``rx_url`` regex stays permissive (it matches ``url(`` anywhere); the
    string-awareness comes from applying it through the shared scanner, which
    skips matches that start inside a string literal or comment. Both layers are
    pinned so a regression in either is caught. (Was a "known limitation" —
    a mid-string ``url(...)`` used to be rewritten; now it is guarded.)
    """

    rx = StylesheetAsset.rx_url

    def _rewrite(self, css):
        # Mirror _fetch_content's url rewrite with an observable marker. Like
        # the real replacement, re-emit the closing quote the regex consumes.
        def repl(match):
            q = match.group("q")
            return f"url({q}REW/{match.group('body')}{q}"

        return _rewrite_css_outside_strings(self.rx, repl, css)

    def test_real_url_is_rewritten(self):
        self.assertIn("REW/", self._rewrite("a{background:url(x.png)}"))

    def test_quoted_real_url_is_rewritten(self):
        # url("x") — the match starts at the url( token (code); the inner "x" is
        # the only protected span and the rewrite never needs to enter it.
        self.assertIn('url("REW/x', self._rewrite('a{background:url("x.png")}'))

    def test_multi_url_src_list_all_rewritten(self):
        """Every url() of a @font-face src list is rewritten, not just the first.

        Regression: the regex used to consume the opening quote but not the
        closing one, desynchronizing the scanner's quote pairing — ``") format("``
        then read as a string literal and swallowed every subsequent ``url(``
        token, so bundle web fonts 404'd in browsers and WeasyPrint PDFs alike.
        """
        out = self._rewrite(
            'src:url("./l/a.eot?#iefix") format("embedded-opentype"),'
            'url("./l/a.woff") format("woff"),'
            "url('./l/a.ttf') format('truetype');"
        )
        self.assertEqual(out.count("REW/"), 3, out)
        # The format() hints are strings and must survive verbatim.
        self.assertIn('format("woff")', out)
        self.assertIn("format('truetype')", out)

    def test_quoted_url_with_space_is_left_untouched(self):
        # A quoted body containing a stopper char can't be matched to its
        # closing quote; it must pass through whole, never half-rewritten
        # (the old regex truncated the body at the space and mangled the url).
        out = self._rewrite('a{background:url("x y.png")}')
        self.assertNotIn("REW/", out)
        self.assertIn('url("x y.png")', out)

    def test_consecutive_imports_all_rewritten(self):
        """Both quoted @imports are rewritten — same quote-pairing regression."""

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
        """A ``url(...)`` mid-string is no longer rewritten (the fix)."""
        out = self._rewrite('a{content:"hello url(x.png) y"}')
        self.assertNotIn("REW/", out)
        self.assertIn('"hello url(x.png) y"', out)

    def test_raw_regex_remains_permissive(self):
        # The guard lives in the scanner, not the regex: the bare regex still
        # matches a url() inside a string. Documents where the protection is.
        self.assertEqual(len(self.rx.findall('a{content:"hello url(x.png) y"}')), 1)


class TestPreprocessCssAtRulesIdempotent(BaseCase):
    """``CssPipeline.preprocess`` assembles @at-rules WITHOUT mutating the source list.

    Dart Sass hoists ``@at-rules`` (e.g. ``@charset``) above the per-file split
    markers; ``preprocess`` peels that leading fragment off and prepends it — as
    a synthetic asset — to the pipeline's own ``_rendered_assets``, NOT to the
    bundle's ``stylesheets``. Because the source list is never mutated, re-runs
    are idempotent by construction: there is no injected fragment to stack
    (``stylesheets`` used to grow 1->2->3, duplicating ``@charset``) and — under
    RTL — none can re-enter the compile input via ``plain_css_assets``. The old
    ``_at_rules_asset`` idempotency guard is gone.

    Bound to a fake bundle — ``preprocess`` touches only a handful of attributes
    — so the contract is proven without a real bundle or a Sass install,
    mirroring ``TestPreprocessCssErrorContract``.
    """

    # @charset hoisted above the per-file split marker, as Dart Sass emits it.
    _COMPILED = '@charset "UTF-8";\n/*! odoo-split:abc123 */\nh1{color:red}'

    def _pipeline(self, rtl=False):
        scss = Mock(spec=ScssStylesheetAsset)  # isinstance PreprocessedCSS -> True
        scss.id = "abc123"  # must match [a-f0-9-]+ for CssPipeline.rx_css_split
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
        """A second call rebuilds ONE render list (stylesheets used to go 1->2->3)."""
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
        """No stale fragment can leak back into the RTL compile input."""
        pipeline, bundle = self._pipeline(rtl=True)
        pipeline.preprocess()
        pipeline.preprocess()
        out3 = pipeline.preprocess()
        self.assertEqual(len(bundle.stylesheets), 1)
        self.assertEqual(len(pipeline._rendered_assets), 2)
        self.assertEqual(out3.count("@charset"), 1)


class TestCssErrorBannerBackslashEscape(BaseCase):
    """``_render_css_error_banner`` escapes a literal backslash FIRST.

    A ``\\`` in a compiler error (a Windows load path, a regex echoed by Sass)
    must become ``\\\\`` in the CSS ``content:`` string — not be read as a CSS
    escape (``\\f`` -> form feed) and not double the backslashes the ``\\"`` /
    ``\\A`` / ``\\*`` passes introduce after it.
    """

    def test_backslash_is_escaped_not_interpreted(self):
        banner = AssetsBundle._render_css_error_banner([r"C:\foo broke"], "")
        content_line = next(ln for ln in banner.splitlines() if "C:" in ln)
        self.assertIn(r"C:\\foo", content_line)

    def test_quote_escape_stays_single_backslash(self):
        # the backslash pass must not double the backslash the quote escape adds
        banner = AssetsBundle._render_css_error_banner(['say "hi"'], "")
        content_line = next(ln for ln in banner.splitlines() if "say" in ln)
        self.assertIn(r"say \"hi\"", content_line)
        self.assertNotIn(r"\\\"", content_line)


class TestBacktickMinifyGate(BaseCase):
    """``JavascriptAsset.minify`` escalates to esbuild only for NESTED literals.

    rjsmin (1.2.5) corrupts a template literal nested inside a ``${ }``
    interpolation but handles every other case, including top-level literals and
    ``${``-free backtick strings. Nesting requires a ``${``, so the gate routes a
    file to the esbuild subprocess only when BOTH a backtick and ``${`` are
    present — sparing the common ``${``-free backtick file an esbuild call.

    ``minify_js`` is the esbuild seam; patching it to a sentinel and asserting
    whether it was called proves which branch ran, no subprocess needed.
    """

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
        """The newly-fast path must not corrupt the literal it now handles."""
        asset = JavascriptAsset(SimpleNamespace(name="b"), inline="var x = `a   b`;\n")
        self.assertIn("a   b", asset.minify())


class TestJsContentPredicates(BaseCase):
    """``has_js_content`` / ``_has_legacy_templates`` are one shared predicate.

    ``get_links`` (link emission) and ``js`` (template wrapping) both consult
    them, so the "does this bundle ship legacy JS?" decision lives in one place.
    """

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
    """Empty ``ir.attachment`` recordset: falsy, and ``ensure_one()`` raises.

    Mirrors how ``ir.attachment._get_serve_attachment`` reports a miss (an empty
    recordset whose ``ensure_one()`` raises ``ValueError``), so a url-only asset
    fails to resolve exactly as it would against a real cursor — no DB needed.
    The falsy-ness matters: a failed resolve leaves ``WebAsset._ir_attach`` set
    to this empty set, and the guard in ``_resolve_attachment`` retries while it
    is falsy, which is what makes the fetch (and its error) repeat per call.
    """

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
    """A leaf asset's fetch error is reported exactly ONCE per ``preprocess()``.

    Unlike ``TestPreprocessCssErrorContract`` / ``TestPreprocessCssAtRulesIdempotent``
    (Mock-bound by design), this drives a REAL ``ScssStylesheetAsset`` so the
    actual ``get_source()`` -> ``_fetch_content()`` path runs — the one that
    bypasses the ``content`` cache and appends to ``asset.errors`` on every call.
    A Mock (fixed ``errors``/``get_source``) cannot surface the duplication, so
    the regression needs a real asset plus the falsy-miss env above.

    Before the fix ``preprocess`` cleared the bundle's ``css_errors`` but not the
    per-leaf ``errors`` lists it then harvests, so:
      * a re-run doubled (then tripled) every leaf error, and
      * a bundle-level compile failure re-fetched leaves whose ``_content`` the
        empty compiled output left unset, double-reporting them in ONE call.
    """

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
        """Compile failure + a missing leaf: the leaf error appears once, and
        the discarded minify() reassembly is skipped (so it cannot re-fetch)."""
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
        """Re-running preprocess rebuilds css_errors from scratch: the leaf
        error count stays at one rather than growing 1 -> 2 -> 3."""
        bundle, asset = self._bundle_with_missing_scss()
        pipeline = CssPipeline(bundle)
        # Identity compile keeps the split markers, so compilation "succeeds"
        # (a missing leaf returns "" but does not fail the whole bundle).
        pipeline.compile_css = lambda compiler, source: source

        leaf_msg = f"Could not find {self._MISSING}"
        for _ in range(3):
            pipeline.preprocess()
            self.assertEqual(bundle.css_errors.count(leaf_msg), 1)
        # the leaf's own list is rebuilt each run, not appended to forever
        self.assertEqual(asset.errors.count(leaf_msg), 1)


class TestAutoprefixImportStringBoundary(BaseCase):
    """The two whole-text CSS rewrites (``_autoprefix_css`` and the ``@import``
    hoist) are now string-aware, like ``StylesheetAsset.rx_url`` (see
    ``TestUrlRewriteStringBoundary``): both run through
    ``_rewrite_css_outside_strings``, so an ``appearance:`` / ``@import`` written
    inside a string literal is left untouched. Was characterized as a "known
    limitation"; now fixed and pinned.
    """

    def test_autoprefix_rewrites_real_declaration(self):
        out = CssPipeline._autoprefix_css("a{appearance:none}")
        self.assertIn("-webkit-appearance:none", out)
        self.assertIn("-moz-appearance:none", out)

    def test_autoprefix_skips_string_literal(self):
        """``appearance:`` inside a ``content:`` string is left untouched — the
        rewrite runs through the string/comment-aware scanner (the fix)."""
        out = CssPipeline._autoprefix_css('.x{content:" appearance: auto"}')
        self.assertNotIn("-webkit-appearance", out)
        self.assertIn('" appearance: auto"', out)

    def test_import_hoist_matches_real_rule(self):
        # The raw regex stays permissive; string-awareness is applied at the
        # call site via _rewrite_css_outside_strings (see below).
        self.assertEqual(
            AssetsBundle.rx_css_import.findall('@import "a.css";\nbody{}'),
            ['@import "a.css";'],
        )

    def test_import_hoist_skips_string_literal(self):
        """An ``@import`` written inside a string literal is no longer hoisted
        or commented out — the call sites apply rx_css_import through the
        scanner, which skips matches starting inside a string."""
        collected = []

        def take(match):
            collected.append(match.group(0))
            return ""

        out = _rewrite_css_outside_strings(
            AssetsBundle.rx_css_import, take, '.x{content:"@import url(evil);"}'
        )
        self.assertEqual(collected, [])
        self.assertEqual(out, '.x{content:"@import url(evil);"}')


class TestRewriteScannerDotallScope(BaseCase):
    """``_rewrite_css_outside_strings`` confines ``re.DOTALL`` to its own arm.

    The scanner is built from the string/comment tokenizer OR the caller's
    ``target``. DOTALL is needed only by the tokenizer (block comments and
    ``\\.`` continuations span lines). It used to be OR'd onto the whole
    combined pattern (``target.flags | re.DOTALL``), which silently changed the
    meaning of any ``.`` the caller's ``target`` carried. The flag is now scoped
    with ``(?s:...)`` so the caller's pattern keeps exactly its own flags.
    """

    def test_dot_in_target_does_not_span_newlines(self):
        # A target using '.' (compiled WITHOUT DOTALL) must not match across a
        # newline when run through the helper.
        hits = []
        _rewrite_css_outside_strings(
            re.compile(r"X.Y"), lambda m: hits.append(m.group(0)) or "H", "X\nY"
        )
        self.assertEqual(hits, [], "target's '.' must not gain DOTALL")

    def test_target_with_explicit_dotall_is_respected(self):
        # If the caller WANTS DOTALL it compiles it into the target; the helper
        # must honour that (its own flags survive — they are not stripped).
        hits = []
        _rewrite_css_outside_strings(
            re.compile(r"X.Y", re.DOTALL),
            lambda m: hits.append(m.group(0)) or "H",
            "X\nY",
        )
        self.assertEqual(hits, ["X\nY"])

    def test_multiline_comment_still_protected(self):
        # The string/comment arm keeps DOTALL: a url() after a multi-line block
        # comment is still rewritten, and the comment passes through verbatim.
        out = _rewrite_css_outside_strings(
            StylesheetAsset.rx_url, lambda m: "U", "a/*\n c \n*/ url(z)"
        )
        self.assertIn("/*\n c \n*/", out)
        self.assertIn("U", out)


class TestMinifySourceMapStringAware(BaseCase):
    """``_minify_css_body`` drops a sourcemap link via the (string-aware) mask.

    A ``/*# sourceMappingURL=… */`` link is an ordinary block comment, so the
    masking step drops it like any other comment — no separate whole-text pass.
    The old leading ``rx_sourceMap.sub`` ran string-unaware and corrupted a
    ``sourceMappingURL`` written inside a ``content: "…"`` value.
    """

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
    """``CssPipeline.run_rtlcss`` flags a swallowed payload on the STRIPPED output.

    rtlcss can exit 0 yet emit nothing usable for a real payload. The guard now
    compares the stripped result (the value actually returned), so a
    whitespace-only response (``"\\n"``) raises the banner instead of shipping
    ``""`` silently — while a whitespace-only *source* (legitimately empty
    output) is not a false positive.
    """

    def _run(self, source, fake_out):
        bundle = SimpleNamespace(css_errors=[], name="t.b", stylesheets=[])
        pipe = CssPipeline(bundle)
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
    """``generate_esm_template_bundle`` emits both header forms (was untested).

    Debug uses a native ``import`` from ``@web/core/templates`` (resolved via
    import map); production esbuild accesses the SAME module through
    ``odoo.loader.modules.get`` to avoid a second copy of the registry. Both
    forms must destructure the identical registrar set and carry the template
    registration body.
    """

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
    """``_make_esbuild_compiler`` threads ``_get_esbuild_addon_flags`` through.

    ``_get_esbuild_addon_flags`` is the documented per-bundle override seam (a
    classmethod tests can patch to inject fabricated addon flags). This pins
    that the factory hands that very callable to the compiler, so a patch at the
    seam reaches production bundling.
    """

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
    """``get_native_module_data`` warns instead of silently dropping a mapping.

    Two native modules can resolve to the same specifier — ``foo.js`` and
    ``foo/index.js`` both yield ``@addon/foo``. The browser import map holds one
    url per specifier, so one mapping is dropped. Behaviour stays last-wins, but
    the drop is now loud (``import_map_spec_collision``), matching the
    "no silent drops" tripwire the constructor uses for skipped files.
    """

    _LOG = "odoo.assets.bundle"

    @staticmethod
    def _mod(module_path, url, alias=None):
        header = {"alias": alias} if alias else None
        return SimpleNamespace(module_path=module_path, url=url, parsed_header=header)

    def _data(self, modules):
        fake = SimpleNamespace(native_modules=modules, name="my.bundle")
        return AssetsBundle.get_native_module_data(fake, with_bridges=False)

    def test_colliding_specs_warn_and_keep_last_wins(self):
        mods = [
            self._mod("@web/foo", "/web/static/src/foo.js"),
            self._mod("@web/foo", "/web/static/src/foo/index.js"),
        ]
        with self.assertLogs(self._LOG, level="WARNING") as cm:
            data = self._data(mods)
        self.assertIn("import_map_spec_collision", "\n".join(cm.output))
        # last-wins is preserved (purely additive change)
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
        # foo/index.js adds @web/foo AND @web/foo/index, both the SAME url —
        # that is not a collision and must stay silent.
        mods = [self._mod("@web/foo", "/web/static/src/foo/index.js")]
        with self.assertNoLogs(self._LOG, level="WARNING"):
            data = self._data(mods)
        self.assertEqual(data["import_map"]["@web/foo"], "/web/static/src/foo/index.js")
        self.assertEqual(
            data["import_map"]["@web/foo/index"], "/web/static/src/foo/index.js"
        )
