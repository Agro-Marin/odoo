"""Regression tests for the 2026-06-15 ir_attachment audit findings.

Each test pins one behavior that was empirically shown broken before the fix:

- A1: image autoresize must not crash the upload with a PIL-native exception.
  ``_postprocess_contents`` only caught ``UserError``, but ``resize()`` /
  ``image_quality()`` raise ``OSError`` / ``DecompressionBombError`` (proven
  flag-independent), which escaped and 500'd a large-image upload.
- A2: ``create_unique`` dedups an autoresized image across SEPARATE calls.
  The dedup key was computed on the pre-pipeline bytes, so create()'s
  autoresize changed the stored checksum and a second call created a duplicate
  row (both pointing at the same content-addressed file).
- A3: ``create_unique`` must not silently drop content passed as ``raw=``.
  It only read ``datas``; a ``raw`` payload was overwritten with ``b""``.
"""

import base64
import io
from unittest.mock import patch

from PIL import Image

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_IRA_LOG = "odoo.addons.base.models.ir_attachment"


class TestIraAuditFixes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attachment = cls.env["ir.attachment"]
        icp = cls.env["ir.config_parameter"].sudo()
        icp.set_param("base.image_autoresize_extensions", "png,jpeg,bmp,tiff")
        icp.set_param("base.image_autoresize_max_px", "1920x1920")
        icp.set_param("base.image_autoresize_quality", "80")

    def _solid_jpeg(self, w, h, color=(123, 50, 200)):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), color).save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    # -- A1 ---------------------------------------------------------------
    @mute_logger(_IRA_LOG)
    def test_a1_autoresize_survives_decompression_bomb(self):
        """A PIL decompression-bomb error during resize must not 500 the upload.

        Simulated by lowering PIL's pixel ceiling so a normal oversized image
        trips the SAME guard a real >178Mpx upload hits (autoresize decodes
        with verify_resolution=False, so PIL's guard is the only check).
        """
        payload = self._solid_jpeg(3000, 3000)  # > 1920 -> resize path taken
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1000):
            # must NOT raise; degrades to storing the original bytes unresized
            att = self.Attachment.create(
                {
                    "name": "bomb.jpg",
                    "mimetype": "image/jpeg",
                    "raw": payload,
                    "res_field": False,
                }
            )
        self.assertTrue(att.id)
        self.assertEqual(
            att.file_size,
            len(payload),
            "bomb upload should keep the original bytes, not crash",
        )

    @mute_logger(_IRA_LOG)
    def test_a1_valid_oversized_image_still_resizes(self):
        """The fix must not disable normal autoresize."""
        payload = self._solid_jpeg(3000, 3000)
        att = self.Attachment.create(
            {
                "name": "big.jpg",
                "mimetype": "image/jpeg",
                "raw": payload,
                "res_field": False,
            }
        )
        w, h = Image.open(io.BytesIO(att.raw)).size
        self.assertLessEqual(max(w, h), 1920, "oversized image must be resized down")

    # -- A2 ---------------------------------------------------------------
    @mute_logger(_IRA_LOG)
    def test_a2_create_unique_dedups_autoresized_image_across_calls(self):
        payload = self._solid_jpeg(3000, 3000)
        b64 = base64.b64encode(payload).decode()
        ids1 = self.Attachment.create_unique(
            [{"name": "u.jpg", "mimetype": "image/jpeg", "datas": b64}]
        )
        ids2 = self.Attachment.create_unique(
            [{"name": "u.jpg", "mimetype": "image/jpeg", "datas": b64}]
        )
        self.assertEqual(
            ids1[0], ids2[0], "same oversized image must dedup to one row across calls"
        )

    @mute_logger(_IRA_LOG)
    def test_a2_text_dedup_still_works(self):
        """Control: non-image dedup behavior is unchanged."""
        b64 = base64.b64encode(b"dedup control content").decode()
        ids1 = self.Attachment.create_unique(
            [{"name": "c.txt", "mimetype": "text/plain", "datas": b64}]
        )
        ids2 = self.Attachment.create_unique(
            [{"name": "c.txt", "mimetype": "text/plain", "datas": b64}]
        )
        self.assertEqual(ids1[0], ids2[0])

    # -- A3 ---------------------------------------------------------------
    @mute_logger(_IRA_LOG)
    def test_a3_create_unique_preserves_raw_content(self):
        ids = self.Attachment.create_unique(
            [{"name": "r.txt", "mimetype": "text/plain", "raw": b"IMPORTANT DATA"}]
        )
        rec = self.Attachment.browse(ids[0])
        self.assertEqual(
            rec.raw, b"IMPORTANT DATA", "raw= content must not be silently dropped"
        )
        self.assertEqual(rec.file_size, len(b"IMPORTANT DATA"))

    @mute_logger(_IRA_LOG)
    def test_a3_create_unique_str_raw_is_encoded(self):
        ids = self.Attachment.create_unique(
            [{"name": "s.txt", "mimetype": "text/plain", "raw": "héllo"}]
        )
        rec = self.Attachment.browse(ids[0])
        self.assertEqual(rec.raw, "héllo".encode())

    # -- create_unique rewrite hardening ----------------------------------
    @mute_logger(_IRA_LOG)
    def test_cu_in_batch_dedup_of_oversized_images(self):
        """Two identical oversized images in ONE call collapse to one row."""
        b64 = base64.b64encode(self._solid_jpeg(3000, 3000)).decode()
        ids = self.Attachment.create_unique(
            [
                {"name": "a.jpg", "mimetype": "image/jpeg", "datas": b64},
                {"name": "b.jpg", "mimetype": "image/jpeg", "datas": b64},
            ]
        )
        self.assertEqual(ids[0], ids[1])

    @mute_logger(_IRA_LOG)
    def test_cu_xml_neutralized_mimetype_dedups(self):
        """Bonus fix from the rewrite: keying dedup on the POST-pipeline
        mimetype means an XML payload neutralized to text/plain dedups across
        calls. The old pre-pipeline key (application/xml) never matched the
        stored text/plain row, so every call created a new row.
        """
        Att = self.Attachment.with_context(attachments_mime_plainxml=True)
        b64 = base64.b64encode(b"<xml>payload</xml>").decode()
        vals = {"name": "x.xml", "mimetype": "application/xml", "datas": b64}
        ids1 = Att.create_unique([dict(vals)])
        ids2 = Att.create_unique([dict(vals)])
        self.assertEqual(ids1[0], ids2[0], "neutralized mimetype must dedup")
        self.assertEqual(self.Attachment.browse(ids1[0]).mimetype, "text/plain")

    @mute_logger(_IRA_LOG)
    def test_cu_mixed_raw_and_datas_batch(self):
        """raw and datas inputs may be mixed in one call; both are stored."""
        ids = self.Attachment.create_unique(
            [
                {"name": "r.txt", "mimetype": "text/plain", "raw": b"alpha"},
                {
                    "name": "d.txt",
                    "mimetype": "text/plain",
                    "datas": base64.b64encode(b"beta").decode(),
                },
            ]
        )
        self.assertEqual(self.Attachment.browse(ids[0]).raw, b"alpha")
        self.assertEqual(self.Attachment.browse(ids[1]).raw, b"beta")

    @mute_logger(_IRA_LOG)
    def test_cu_returns_ids_in_input_order_with_dedup(self):
        """Returned ids follow input order, with duplicates resolved."""
        a = base64.b64encode(b"content-A").decode()
        b = base64.b64encode(b"content-B").decode()
        ids = self.Attachment.create_unique(
            [
                {"name": "1", "mimetype": "text/plain", "datas": a},
                {"name": "2", "mimetype": "text/plain", "datas": b},
                {"name": "3", "mimetype": "text/plain", "datas": a},
            ]
        )
        self.assertEqual(ids[0], ids[2], "1st and 3rd share content -> same row")
        self.assertNotEqual(ids[0], ids[1])
