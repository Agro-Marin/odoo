import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.base.models.assetsbundle import AssetsBundle, JavascriptAsset

PLAIN_JS = "(function () {\n    window.auditX = 1;\n})();\n"
PLAIN_CSS = "body { margin-left: 1px; }"


def _file(url, content, last_modified=1.0):
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


class TestAuditReadonlyAsymmetry(TransactionCase):
    def _make_cursor_readonly(self):
        cr = self.env.cr
        original = cr._readonly
        cr._readonly = True
        self.addCleanup(setattr, cr, "_readonly", original)

    def test_save_attachment_ignores_readonly_flag(self):
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

    def test_fallback_query_skipped_when_pattern_identical(self):
        bundle = AssetsBundle(
            "test_assetsbundle.audit_fb_skip",
            [_file("/test_assetsbundle/static/src/js/audit_fb_skip.js", PLAIN_JS)],
            env=self.env,
            css=False,
        )
        store = bundle._store
        self.assertFalse(store.get_attachments("min.js"))
        with patch.object(store.env.cr, "execute", wraps=store.env.cr.execute) as spy:
            self.assertFalse(store.get_attachments("min.js"))
        self.assertEqual(
            spy.call_count,
            1,
            "base must run only the primary query, not the redundant fallback",
        )


class TestAuditLikeUnderscoreWildcard(TransactionCase):
    FILES = [_file("/test_assetsbundle/static/src/js/audit_like.js", PLAIN_JS)]

    def test_sibling_bundle_not_matched(self):
        sibling = AssetsBundle("test.auditXa", self.FILES, env=self.env, css=False)
        sibling.save_attachment("min.js", "/* sibling */")
        bundle = AssetsBundle("test.audit_a", self.FILES, env=self.env, css=False)
        matched = bundle.get_attachments("min.js", ignore_version=True)
        self.assertNotIn("test.auditXa.min.js", matched.mapped("name"))

    def test_clean_attachments_spares_sibling(self):
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
        bundle = AssetsBundle("test.audit_c", self.FILES, env=self.env, css=False)
        bundle.save_attachment("min.js", "/* own */")
        AssetsBundle(
            "test.auditXc", self.FILES, env=self.env, css=False
        ).save_attachment("min.js", "/* sibling */")
        matched = bundle.get_attachments("min.js", ignore_version=True)
        self.assertEqual(matched.mapped("name"), ["test.audit_c.min.js"])
        self.assertEqual(matched.raw, b"/* own */")

    def test_clean_attachments_still_cleans_own_versions(self):
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
    def test_missing_rtlcss_returns_ltr_silently(self):
        bundle = AssetsBundle(
            "test_assetsbundle.audit_rtl",
            [_file("/test_assetsbundle/static/src/css/audit_rtl.css", PLAIN_CSS)],
            env=self.env,
            js=False,
            rtl=True,
        )
        with patch(
            "odoo.addons.base.models.assetsbundle.css_pipeline._check_rtlcss",
            return_value=False,
        ):
            out = bundle._css.run_rtlcss(PLAIN_CSS)
        self.assertEqual(out, PLAIN_CSS)
        self.assertFalse(bundle.css_errors)


class TestAuditEpochMtime(TransactionCase):
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
