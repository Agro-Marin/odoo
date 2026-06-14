"""Probes for the _migrate() content-metadata reuse optimization (P1).

A storage-LOCATION migration does not change the bytes, so _migrate reuses the
stored checksum / file_size / index_content instead of re-deriving them — except
for rows written through the raw ``db_datas`` escape hatch, which never had that
metadata stamped and must fall back to a full derivation.
"""

from unittest.mock import patch

from odoo.tools import mute_logger

from odoo.addons.base.models.ir_attachment import IrAttachment
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class TestIraMigrateReuse(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]

    def _set_location(self, location):
        self.env["ir.config_parameter"].set_param("ir_attachment.location", location)

    def test_migrate_reuses_metadata_without_rehash(self):
        """file->db migration must not re-hash or re-index unchanged bytes (P1)."""
        self._set_location("file")
        payload = b"indexable migration payload " * 20
        att = self.Attachment.create(
            {"name": "p1.txt", "mimetype": "text/plain", "raw": payload}
        )
        self.assertTrue(att.store_fname)
        checksum_before = att.checksum
        index_before = att.index_content
        size_before = att.file_size
        self.assertTrue(index_before, "text content should have been indexed")

        # Count any re-derivation. Real function wrappers (not Mock side_effects)
        # so the descriptor protocol still binds `self` correctly.
        calls = {"checksum": 0, "index": 0}
        orig_cs, orig_idx = IrAttachment._content_checksum, IrAttachment._index

        def counting_cs(self, data):
            calls["checksum"] += 1
            return orig_cs(self, data)

        def counting_idx(self, data, file_type, checksum=None):
            calls["index"] += 1
            return orig_idx(self, data, file_type, checksum=checksum)

        self._set_location("db")
        with (
            patch.object(IrAttachment, "_content_checksum", counting_cs),
            patch.object(IrAttachment, "_index", counting_idx),
        ):
            att._migrate()

        self.assertEqual(calls["checksum"], 0, "reuse path must not re-hash bytes")
        self.assertEqual(calls["index"], 0, "reuse path must not re-index bytes")

        att.invalidate_recordset()
        self.assertFalse(att.store_fname, "content moved into the database")
        self.assertEqual(att.checksum, checksum_before, "checksum preserved as-is")
        self.assertEqual(att.index_content, index_before, "index preserved as-is")
        self.assertEqual(att.file_size, size_before, "file_size preserved as-is")
        self.assertEqual(att.raw, payload, "content readable after migration")

    def test_migrate_roundtrip_preserves_content(self):
        """file->db->file keeps bytes and checksum identical end to end."""
        self._set_location("file")
        payload = b"roundtrip-bytes-%d" % 7 * 100
        att = self.Attachment.create({"name": "rt.bin", "raw": payload})
        checksum = att.checksum

        self._set_location("db")
        att._migrate()
        att.invalidate_recordset()
        self.assertFalse(att.store_fname)
        self.assertEqual(att.raw, payload)

        self._set_location("file")
        att._migrate()
        att.invalidate_recordset()
        self.assertTrue(att.store_fname)
        self.assertEqual(att.raw, payload)
        self.assertEqual(att.checksum, checksum, "checksum stable across the roundtrip")

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_migrate_passthrough_without_checksum_derives(self):
        """A raw db_datas row (no checksum/file_size) migrates correctly (P1 fallback).

        The reuse fast path would crash on a missing checksum (``False[:2]``), so
        _migrate must fall back to a full derivation and stamp the metadata.
        """
        self._set_location("file")
        payload = b"escape-hatch-bytes"
        # Direct db_datas passthrough: bypasses the content pipeline, so the row
        # has db_datas but no checksum / file_size / index_content.
        att = self.Attachment.create(
            {"name": "passthrough.bin", "type": "binary", "db_datas": payload}
        )
        self.assertFalse(att.checksum, "passthrough leaves checksum unstamped")
        self.assertEqual(att.raw, payload, "content served from db_datas")

        att._migrate()
        att.invalidate_recordset()
        self.assertTrue(att.store_fname, "now file-stored")
        self.assertTrue(att.checksum, "checksum derived by the fallback")
        self.assertEqual(att.file_size, len(payload), "file_size derived by the fallback")
        self.assertEqual(att.raw, payload, "content intact through the fallback")
