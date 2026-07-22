"""Tests for the /doc index-cache garbage collector."""

import base64

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDocIndexGc(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attachment = cls.env["ir.attachment"]
        cls.sequence = str(cls.env.registry.get_sequences(cls.env.cr)[0])

    def _doc_index(self, sequence, suffix):
        return self.Attachment.create(
            {
                "name": f"odoo-doc-index-{sequence}-{suffix}.json",
                "datas": base64.b64encode(b"{}"),
            }
        )

    def test_gc_removes_stale_index_keeps_current(self):
        """The GC drops indexes from a past registry sequence, keeps current."""
        stale = self._doc_index("0", "en_US")
        fresh = self._doc_index(self.sequence, "en_US")
        self.Attachment._gc_doc_index()
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())

    def test_gc_noop_without_indexes(self):
        """With no cached indexes the GC is a harmless no-op (boundary)."""
        self.Attachment.search([("name", "like", R"odoo-doc-index-%-%.json")]).unlink()
        # Should not raise even when there is nothing to collect.
        self.Attachment._gc_doc_index()
