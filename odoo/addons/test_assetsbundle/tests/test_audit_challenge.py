"""Adversarial verification of the 2026-06-10 assetsbundle audit claims.

Each test pins one contested behavior with an executable proof:
readonly-flag asymmetry of ``save_attachment``, dead-code status of the
``get_attachments`` copy-fallback in base, the LIKE-escaping of ``_`` in
bundle-URL patterns (cross-bundle attachment deletion and the
multi-record ``.raw`` crash before the fix), silent LTR degradation when
rtlcss is missing, and the epoch-0 mtime sentinel conflation.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.base.models.assetsbundle import AssetsBundle, JavascriptAsset

PLAIN_JS = "(function () {\n    window.auditX = 1;\n})();\n"
PLAIN_CSS = "body { margin-left: 1px; }"


def _file(url, content, last_modified=1.0):
    """Build the files-dict entry shape produced by ir_qweb._get_asset_content."""
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


class TestAuditReadonlyAsymmetry(TransactionCase):
    """``save_attachment`` does not consult ``cr.readonly`` (bridges do)."""

    def _make_cursor_readonly(self):
        cr = self.env.cr
        original = cr._readonly
        cr._readonly = True
        self.addCleanup(setattr, cr, "_readonly", original)

    def test_save_attachment_ignores_readonly_flag(self):
        """The create proceeds with the readonly flag set — no guard, no
        diversion. Harmless today because every reachable caller holds a
        rw cursor (binary controller escalation / default-rw routes); the
        test pins the asymmetry so a future render-path caller trips it."""
        bundle = AssetsBundle(
            "test_assetsbundle.audit_ro",
            [_file("/test_assetsbundle/static/src/js/audit_ro.js", PLAIN_JS)],
            env=self.env,
            css=False,
        )
        self._make_cursor_readonly()
        attachment = bundle.save_attachment("min.js", "/* ro */")
        self.assertTrue(attachment.exists())


class TestAuditFallbackDeadInBase(TransactionCase):
    """The ``get_attachments`` copy-fallback cannot trigger without an
    ``_get_asset_bundle_url`` override (website): in base the
    ``ignore_params=True`` pattern is byte-identical to the primary one,
    so the fallback re-runs the exact query that just returned nothing."""

    def test_ignore_params_pattern_identical_in_base(self):
        bundle = AssetsBundle(
            "test_assetsbundle.audit_fb",
            [_file("/test_assetsbundle/static/src/js/audit_fb.js", PLAIN_JS)],
            env=self.env,
            css=False,
        )
        unique = bundle.get_version("js")
        primary = bundle._store.get_asset_url_pattern(unique=unique, extension="min.js")
        fallback = bundle._store.get_asset_url_pattern(
            unique=unique, extension="min.js", ignore_params=True
        )
        self.assertEqual(primary, fallback)


class TestAuditLikeUnderscoreWildcard(TransactionCase):
    """``_`` in bundle names is LIKE-escaped in URL patterns: a bundle's
    pattern must never match sibling bundles whose name differs only at
    an underscore position (it used to — read AND write side)."""

    FILES = [_file("/test_assetsbundle/static/src/js/audit_like.js", PLAIN_JS)]

    def test_sibling_bundle_not_matched(self):
        sibling = AssetsBundle("test.auditXa", self.FILES, env=self.env, css=False)
        sibling.save_attachment("min.js", "/* sibling */")
        bundle = AssetsBundle("test.audit_a", self.FILES, env=self.env, css=False)
        matched = bundle.get_attachments("min.js", ignore_version=True)
        self.assertNotIn("test.auditXa.min.js", matched.mapped("name"))

    def test_clean_attachments_spares_sibling(self):
        """Write side: saving ``test.audit_b`` runs ``_clean_attachments``;
        its escaped pattern must not match (and delete) the previously
        saved sibling ``test.auditXb`` — it did before the escape fix."""
        sibling_att = AssetsBundle(
            "test.auditXb", self.FILES, env=self.env, css=False
        ).save_attachment("min.js", "/* sibling */")
        self.assertTrue(sibling_att.exists())
        own_att = AssetsBundle(
            "test.audit_b", self.FILES, env=self.env, css=False
        ).save_attachment("min.js", "/* own */")
        self.assertTrue(sibling_att.exists())
        self.assertTrue(own_att.exists())

    def test_ignore_version_returns_only_own(self):
        """Read side: with a coexisting sibling, the ``ignore_version``
        lookup returns exactly one name and the singleton ``raw`` read in
        ``css()``'s degraded-error path works (it used to raise)."""
        bundle = AssetsBundle("test.audit_c", self.FILES, env=self.env, css=False)
        bundle.save_attachment("min.js", "/* own */")
        AssetsBundle(
            "test.auditXc", self.FILES, env=self.env, css=False
        ).save_attachment("min.js", "/* sibling */")
        matched = bundle.get_attachments("min.js", ignore_version=True)
        self.assertEqual(matched.mapped("name"), ["test.audit_c.min.js"])
        self.assertEqual(matched.raw, b"/* own */")

    def test_clean_attachments_still_cleans_own_versions(self):
        """The escape must not break the cleanup's actual job: replacing
        an outdated version of the SAME bundle still deletes it."""
        files_v1 = [_file("/test_assetsbundle/static/src/js/audit_v.js", PLAIN_JS, 1.0)]
        old_att = AssetsBundle(
            "test.audit_v", files_v1, env=self.env, css=False
        ).save_attachment("min.js", "/* v1 */")
        self.assertTrue(old_att.exists())
        files_v2 = [_file("/test_assetsbundle/static/src/js/audit_v.js", PLAIN_JS, 2.0)]
        new_att = AssetsBundle(
            "test.audit_v", files_v2, env=self.env, css=False
        ).save_attachment("min.js", "/* v2 */")
        self.assertFalse(old_att.exists())
        self.assertTrue(new_att.exists())


class TestAuditRtlSilentDegradation(TransactionCase):
    """Missing rtlcss serves LTR styles to RTL users with no css_errors
    entry — only a once-per-process server log."""

    def test_missing_rtlcss_returns_ltr_silently(self):
        bundle = AssetsBundle(
            "test_assetsbundle.audit_rtl",
            [_file("/test_assetsbundle/static/src/css/audit_rtl.css", PLAIN_CSS)],
            env=self.env,
            js=False,
            rtl=True,
        )
        with patch(
            "odoo.addons.base.models.assetsbundle._check_rtlcss",
            return_value=False,
        ):
            out = bundle.run_rtlcss(PLAIN_CSS)
        self.assertEqual(out, PLAIN_CSS)
        self.assertFalse(bundle.css_errors)


class TestAuditEpochMtime(TransactionCase):
    """``last_modified`` keeps a legitimate epoch-0 mtime distinct from
    the missing-file ``-1`` sentinel (``is None`` check, 2026-06-11)."""

    def _tmp_js(self, mtime):
        fd, path = tempfile.mkstemp(suffix=".js")
        with os.fdopen(fd, "w") as handle:
            handle.write(PLAIN_JS)
        self.addCleanup(os.unlink, path)
        os.utime(path, (mtime, mtime))
        return path

    def _asset(self, filename):
        bundle = AssetsBundle("test_assetsbundle.audit_mtime", [], env=self.env)
        return JavascriptAsset(bundle, url="/test/audit_mtime.js", filename=filename)

    def test_epoch_zero_is_preserved(self):
        asset = self._asset(self._tmp_js(0))
        self.assertEqual(asset.last_modified, 0.0)

    def test_nonzero_mtime_passes_through(self):
        path = self._tmp_js(1234)
        asset = self._asset(path)
        self.assertEqual(asset.last_modified, Path(path).stat().st_mtime)
