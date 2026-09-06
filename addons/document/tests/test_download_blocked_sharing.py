"""The `document.sharing` dialog side of the "view but not download" setting.

The setting itself is community (`document.document.is_download_blocked`); the
dialog that exposes it is this module's, so its coverage lives here.
"""

from odoo.tests.common import TransactionCase


class TestDownloadBlockedSharingDialog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document = cls.env["document.document"].create(
            {
                "name": "confidential.txt",
                "type": "binary",
                "raw": b"secret",
                "is_download_blocked": True,
            }
        )

    def _open_sharing(self, documents):
        action = self.env["document.sharing"].action_open(documents.ids)
        return self.env["document.sharing"].browse(action["res_id"])

    def test_the_sharing_dialog_reflects_and_applies_the_setting(self):
        """The setting is reachable where sharing is decided, not only by API."""
        wizard = self._open_sharing(self.document)
        self.assertEqual(wizard.viewer_download_mode, "blocked")

        open_document = self.env["document.document"].create(
            {"name": "downloadable.txt", "type": "binary", "raw": b"open"}
        )
        wizard = self._open_sharing(open_document)
        self.assertEqual(wizard.viewer_download_mode, "allowed")
        self.assertFalse(wizard.is_access_modified, "untouched is not a change")

        # Same `write_` convention the other access selections use: choosing a
        # `write_` value is what marks it as edited.
        wizard.viewer_download_mode = "write_blocked"
        self.assertTrue(wizard.is_access_modified)
        wizard.action_update_rights()
        open_document.invalidate_recordset()

        self.assertTrue(open_document.is_download_blocked)

    def test_the_sharing_dialog_reports_a_mixed_selection(self):
        open_document = self.env["document.document"].create(
            {"name": "mixed.txt", "type": "binary", "raw": b"open"}
        )
        wizard = self._open_sharing(self.document | open_document)
        self.assertEqual(
            wizard.viewer_download_mode,
            "mixed",
            "a selection that disagrees must not silently pick one",
        )
