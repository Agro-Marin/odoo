"""Executable proofs for the 2026-06-15 assetsbundle review follow-up.

Three contested behaviors, each pinned without a DB (mirroring
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
"""

from types import SimpleNamespace
from unittest.mock import Mock

from odoo.tests.common import BaseCase

from odoo.addons.base.models.assetsbundle import (
    AssetsBundle,
    PreprocessedCSS,
    ScssStylesheetAsset,
    StylesheetAsset,
)


class TestPreprocessCssErrorContract(BaseCase):
    """``preprocess_css`` hands back ``""`` on a bundle-level compile failure.

    The method is bound to a fake ``self`` (a ``SimpleNamespace`` carrying
    only the attributes it touches), so the contract is provable without a
    bundle, a cursor, or a Sass install.
    """

    def _fake(self, stylesheets):
        return SimpleNamespace(
            stylesheets=stylesheets,
            css_errors=[],
            autoprefix=False,
            rtl=False,
            rx_css_split=AssetsBundle.rx_css_split,
        )

    def test_compile_failure_returns_empty_not_raw_source(self):
        """A Sass failure (compile_css -> "" + recorded error) must yield "",
        not the uncompiled SCSS the split/minify fallback would assemble."""
        scss = Mock(spec=ScssStylesheetAsset)  # isinstance PreprocessedCSS -> True
        scss.get_source.return_value = "$x: 1; a {}"
        scss.minify.return_value = "RAW_UNCOMPILED_SCSS"  # would be served pre-fix
        scss.errors = []
        self.assertIsInstance(scss, PreprocessedCSS)

        fake = self._fake([scss])

        def failing_compile_css(compiler, source):
            fake.css_errors.append("Sass: something broke")
            return ""

        fake.compile_css = failing_compile_css

        result = AssetsBundle.preprocess_css(fake)
        self.assertEqual(result, "")
        self.assertEqual(fake.css_errors, ["Sass: something broke"])

    def test_leaf_asset_error_still_ships_partial_bundle(self):
        """A per-asset fetch error is NOT a bundle-level failure: compilation
        succeeded, so the good assets are validly compiled and the partial
        bundle is returned (css() still banners on the harvested error). Only a
        bundle-level compile/rtl failure short-circuits to ""; this guards the
        narrow boundary against regressing back to "any css_errors -> ''"."""
        plain = Mock(spec=StylesheetAsset)  # not a PreprocessedCSS
        plain.minify.return_value = "body{color:red}"
        plain.errors = ["audit_missing.css does not exist."]
        fake = self._fake([plain])

        result = AssetsBundle.preprocess_css(fake)
        self.assertEqual(result, "body{color:red}")
        self.assertIn("audit_missing.css does not exist.", fake.css_errors)

    def test_clean_compile_returns_bundle(self):
        """No errors -> the assembled, minified bundle is returned verbatim."""
        plain = Mock(spec=StylesheetAsset)
        plain.minify.return_value = "body{color:red}"
        plain.errors = []
        fake = self._fake([plain])

        result = AssetsBundle.preprocess_css(fake)
        self.assertEqual(result, "body{color:red}")
        self.assertEqual(fake.css_errors, [])

    def test_no_stylesheets_short_circuits(self):
        """The empty-bundle guard is unchanged."""
        self.assertEqual(AssetsBundle.preprocess_css(self._fake([])), "")


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
