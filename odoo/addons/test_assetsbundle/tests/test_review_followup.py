"""Executable proofs for the 2026-06-15 assetsbundle review follow-up.

Four contested behaviors, each pinned without a DB (mirroring
``TestAssetAttachmentStoreUnit``: the logic under test is pure or
mock-bindable, so a live bundle/cursor is unnecessary):

* ``preprocess_css`` returns ``""`` on a *bundle-level* compile/rtl failure
  (where the assembled string would be raw, uncompiled source) rather than
  leaning on the caller's ``css_errors`` check to discard it. A leaf-only
  asset fetch error is NOT a bundle-level failure: the good assets compiled
  fine, so the partial bundle is still returned (mirroring the team's
  ``test_bundle_harvests_asset_errors``).
* ``_minify_css_body`` no longer crashes on a NUL byte in the source
  (a NUL-delimited mask placeholder collision -> IndexError before the fix).
* ``StylesheetAsset.rx_url`` rewrites ``url(...)`` string-unaware: the
  quote-adjacent case is guarded, but a mid-string occurrence is rewritten
  (characterized here as a known boundary).
* ``preprocess_css`` is idempotent across re-runs: the Sass-hoisted
  ``@at-rules`` fragment it injects into ``self.stylesheets`` is tracked and
  dropped before recomputing, so a second call neither duplicates the block
  nor (under RTL) leaks the stale fragment back into the compile input.

Plus the 2026-06-15 compounding follow-ups, pinned the same DB-free way:

* ``_render_css_error_banner`` escapes a literal backslash FIRST, so a path or
  regex in the error cannot become a CSS escape.
* ``JavascriptAsset.minify`` escalates to esbuild only for NESTED template
  literals (backtick AND ``${``); ``${``-free backtick files stay on rjsmin.
* ``has_js_content`` / ``_has_legacy_templates`` are the single predicate shared
  by ``get_links`` and ``js`` so the two cannot drift.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from odoo.tests.common import BaseCase

from odoo.addons.base.models.assetsbundle import (
    AssetsBundle,
    CssPipeline,
    JavascriptAsset,
    PreprocessedCSS,
    ScssStylesheetAsset,
    StylesheetAsset,
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
            # Mirrors AssetsBundle.__init__: preprocess reads this to drop a
            # prior at-rules fragment on re-run (idempotency guard).
            _at_rules_asset=None,
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
        plain.minify.return_value = "body{color:red}"
        plain.errors = ["audit_missing.css does not exist."]
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
        out = StylesheetAsset._minify_css_body("/*! keep */ a{color:red} /* drop */ b{}")
        self.assertIn("/*! keep */", out)
        self.assertNotIn("drop", out)


class TestUrlRewriteStringBoundary(BaseCase):
    """Characterize ``StylesheetAsset.rx_url``'s string-(un)awareness.

    The rewriter in ``_fetch_content`` runs this regex over the whole file,
    so it is the regex that decides what gets a ``web_dir/`` prefix. This
    pins the boundary so a future change to the pattern is deliberate.
    """

    rx = StylesheetAsset.rx_url

    def test_real_url_matches(self):
        self.assertEqual(len(self.rx.findall("a{background:url(x.png)}")), 1)

    def test_quote_adjacent_url_in_string_is_guarded(self):
        """``"url(...)"`` right after a quote is skipped by the (?<!") lookbehind."""
        self.assertEqual(self.rx.findall('a{content:"url(x.png)"}'), [])

    def test_midstring_url_is_rewritten_known_limitation(self):
        """A ``url(...)`` mid-string (whitespace-preceded) is NOT guarded and
        WOULD be rewritten — a known limitation, not yet fixed, documented so
        the boundary is intentional rather than incidental."""
        self.assertEqual(len(self.rx.findall('a{content:"hello url(x.png) y"}')), 1)


class TestPreprocessCssAtRulesIdempotent(BaseCase):
    """``CssPipeline.preprocess`` re-runs without stacking a second @at-rules block.

    Dart Sass hoists ``@at-rules`` (e.g. ``@charset``) above the per-file split
    markers; ``preprocess`` peels that leading fragment off and injects it into
    the bundle's ``stylesheets`` so the debug sourcemap path can assemble it.
    That insert was additive: a second call stacked another fragment
    (``stylesheets`` 1->2->3, ``@charset`` duplicated) and, under RTL, the stale
    fragment re-entered the compile input via ``plain_css_assets``. The pipeline
    now tracks the fragment it injected (``bundle._at_rules_asset``) and drops it
    before recomputing.

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
            _at_rules_asset=None,
        )
        pipeline = CssPipeline(bundle)
        pipeline.compile_css = lambda compiler, source: self._COMPILED
        pipeline.run_rtlcss = lambda source: source
        return pipeline, bundle

    def test_rerun_does_not_stack_at_rules(self):
        """Second call keeps the injected fragment count at one (was 1->2->3)."""
        pipeline, bundle = self._pipeline()
        pipeline.preprocess()
        self.assertEqual(len(bundle.stylesheets), 2, "at-rules fragment injected once")
        out2 = pipeline.preprocess()
        self.assertEqual(
            len(bundle.stylesheets), 2, "re-run must not stack a second fragment"
        )
        self.assertEqual(out2.count("@charset"), 1, "@charset must not be duplicated")

    def test_rerun_idempotent_under_rtl(self):
        """The stale fragment must not leak back into the RTL compile input."""
        pipeline, bundle = self._pipeline(rtl=True)
        pipeline.preprocess()
        pipeline.preprocess()
        out3 = pipeline.preprocess()
        self.assertEqual(len(bundle.stylesheets), 2)
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

    _TARGET = "odoo.addons.base.models.assetsbundle.minify_js"

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
