import base64
import contextlib
import hashlib
import io
import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from odoo.api import SUPERUSER_ID
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import mute_logger
from odoo.tools.image import image_to_base64

from odoo.addons.base.models.ir_attachment import IrAttachment
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo

HASH_SPLIT = 2  # FIXME: testing an implementation detail is not a good idea


class TestIrAttachment(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.filestore = self.Attachment._filestore()

        # Blob1
        self.blob1 = b"blob1"
        self.blob1_b64 = base64.b64encode(self.blob1)
        self.blob1_hash = hashlib.sha1(self.blob1, usedforsecurity=False).hexdigest()
        self.blob1_fname = self.blob1_hash[:HASH_SPLIT] + "/" + self.blob1_hash

        # Blob2
        self.blob2 = b"blob2"
        self.blob2_b64 = base64.b64encode(self.blob2)

    def assertApproximately(self, value, expectedSize, delta=1):
        # not bin_size: on write the cache holds the data, not the size, so
        # getting the size would need a cache invalidation per write.
        with contextlib.suppress(UnicodeDecodeError):
            value = base64.b64decode(value.decode())
        size = len(value) / 1024  # kb

        self.assertAlmostEqual(size, expectedSize, delta=delta)

    def test_01_store_in_db(self):
        # force storing in database
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")

        a1 = self.Attachment.create({"name": "a1", "raw": self.blob1})
        self.assertEqual(a1.datas, self.blob1_b64)

        self.assertEqual(a1.db_datas, self.blob1)

    def test_02_store_on_disk(self):
        a2 = self.Attachment.create({"name": "a2", "raw": self.blob1})
        self.assertEqual(a2.store_fname, self.blob1_fname)
        self.assertTrue(Path(self.filestore, a2.store_fname).is_file())

    def test_03_no_duplication(self):
        a2 = self.Attachment.create({"name": "a2", "raw": self.blob1})
        a3 = self.Attachment.create({"name": "a3", "raw": self.blob1})
        self.assertEqual(a3.store_fname, a2.store_fname)

    def test_04_keep_file(self):
        a2 = self.Attachment.create({"name": "a2", "raw": self.blob1})
        a3 = self.Attachment.create({"name": "a3", "raw": self.blob1})

        a2_fn = Path(self.filestore, a2.store_fname)

        a3.unlink()
        self.assertTrue(a2_fn.is_file())

    def test_05_change_data_change_file(self):
        a2 = self.Attachment.create({"name": "a2", "raw": self.blob1})
        a2_store_fname1 = a2.store_fname
        a2_fn = Path(self.filestore, a2_store_fname1)

        self.assertTrue(a2_fn.is_file())

        a2.write({"raw": self.blob2})

        a2_store_fname2 = a2.store_fname
        self.assertNotEqual(a2_store_fname1, a2_store_fname2)

        a2_fn = Path(self.filestore, a2_store_fname2)
        self.assertTrue(a2_fn.is_file())

    def test_07_write_mimetype(self):
        """Document mimetypes stay consistent."""

        Attachment = self.Attachment.with_user(self.user_demo.id)
        a2 = Attachment.create(
            {"name": "a2", "datas": self.blob1_b64, "mimetype": "image/png"}
        )
        self.assertEqual(
            a2.mimetype,
            "image/png",
            "the new mimetype should be the one given on write",
        )
        a3 = Attachment.create(
            {
                "name": "a3",
                "datas": self.blob1_b64,
                "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        )
        self.assertEqual(
            a3.mimetype,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "should preserve office mime type",
        )
        a4 = Attachment.create(
            {
                "name": "a4",
                "datas": self.blob1_b64,
                "mimetype": "Application/VND.OpenXMLformats-officedocument.wordprocessingml.document",
            }
        )
        self.assertEqual(
            a4.mimetype,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "should preserve office mime type (lowercase)",
        )

    def test_08_neuter_xml_mimetype(self):
        """Harmful XML mimetypes (XSS vectors) are forced to text."""
        Attachment = self.Attachment.with_user(self.user_demo.id)
        document = Attachment.create({"name": "document", "datas": self.blob1_b64})
        document.write({"datas": self.blob1_b64, "mimetype": "text/xml"})
        self.assertEqual(
            document.mimetype,
            "text/plain",
            "XML mimetype should be forced to text",
        )
        document.write({"datas": self.blob1_b64, "mimetype": "image/svg+xml"})
        self.assertEqual(
            document.mimetype,
            "text/plain",
            "SVG mimetype should be forced to text",
        )
        document.write({"datas": self.blob1_b64, "mimetype": "text/html"})
        self.assertEqual(
            document.mimetype,
            "text/plain",
            "HTML mimetype should be forced to text",
        )
        document.write({"datas": self.blob1_b64, "mimetype": "application/xhtml+xml"})
        self.assertEqual(
            document.mimetype,
            "text/plain",
            "XHTML mimetype should be forced to text",
        )

    def test_09_dont_neuter_xml_mimetype_for_admin(self):
        """Admin users bypass the mimetype filter."""
        document = self.Attachment.create({"name": "document", "datas": self.blob1_b64})
        document.write({"datas": self.blob1_b64, "mimetype": "text/xml"})
        self.assertEqual(
            document.mimetype,
            "text/xml",
            "XML mimetype should not be forced to text, for admin user",
        )

    def test_10_image_autoresize(self):
        Attachment = self.env["ir.attachment"]
        img_bin = io.BytesIO()
        dir_path = Path(__file__).resolve().parent
        with Image.open(str(Path(dir_path, "odoo.jpg")), "r") as logo:
            img = Image.new("RGB", (4000, 2000), "#4169E1")
            img.paste(logo)
            img.save(img_bin, "JPEG")

        img_encoded = image_to_base64(img, "JPEG")
        img_bin = img_bin.getvalue()

        fullsize = 124.99

        # test create/write on 'datas'
        attach = Attachment.with_context(image_no_postprocess=True).create(
            {
                "name": "image",
                "datas": img_encoded,
            }
        )
        self.assertApproximately(attach.datas, fullsize)  # no resize, no compression

        attach = attach.with_context(image_no_postprocess=False)
        attach.datas = img_encoded
        self.assertApproximately(
            attach.datas, 12.06
        )  # default resize + default compression

        # resize + default quality (80)
        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_max_px", "1024x768"
        )
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, 3.71)

        # resize + quality 50
        self.env["ir.config_parameter"].set_param("base.image_autoresize_quality", "50")
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, 3.57)

        # no resize + no quality implicit
        self.env["ir.config_parameter"].set_param("base.image_autoresize_max_px", "0")
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, fullsize)

        # quality is only applied when resizing, so we don't recompress on a
        # plain rewrite. no resize + quality -> no effect
        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_max_px", "10000x10000"
        )
        self.env["ir.config_parameter"].set_param("base.image_autoresize_quality", "50")
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, fullsize)

        # test create/write on 'raw'

        # reset default ~ delete
        self.env["ir.config_parameter"].search(
            [("key", "ilike", "base.image_autoresize%")]
        ).unlink()

        attach = Attachment.with_context(image_no_postprocess=True).create(
            {
                "name": "image",
                "raw": img_bin,
            }
        )
        self.assertApproximately(attach.raw, fullsize)  # no resize, no compression

        attach = attach.with_context(image_no_postprocess=False)
        attach.raw = img_bin
        self.assertApproximately(
            attach.raw, 12.06
        )  # default resize + default compression

        # resize + default quality (80)
        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_max_px", "1024x768"
        )
        attach.raw = img_bin
        self.assertApproximately(attach.raw, 3.71)

        # resize + no quality
        self.env["ir.config_parameter"].set_param("base.image_autoresize_quality", "0")
        attach.raw = img_bin
        self.assertApproximately(attach.raw, 4.09)

        # resize + quality 50
        self.env["ir.config_parameter"].set_param("base.image_autoresize_quality", "50")
        attach.raw = img_bin
        self.assertApproximately(attach.raw, 3.57)

        # no resize + no quality implicit
        self.env["ir.config_parameter"].set_param("base.image_autoresize_max_px", "0")
        attach.raw = img_bin
        self.assertApproximately(attach.raw, fullsize)

        # no resize of gif
        self.env["ir.config_parameter"].set_param("base.image_autoresize_max_px", "0x0")
        gif_bin = b"GIF89a\x01\x00\x01\x00\x00\xff\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x00;"
        attach.raw = gif_bin
        self.assertEqual(attach.raw, gif_bin)

    def test_11_copy(self):
        """Copying an attachment preserves the data."""
        document = self.Attachment.create({"name": "document", "datas": self.blob2_b64})
        document2 = document.copy({"name": "document (copy)"})
        self.assertEqual(document2.name, "document (copy)")
        self.assertEqual(document2.datas, document.datas)
        self.assertEqual(document2.db_datas, document.db_datas)
        self.assertEqual(document2.store_fname, document.store_fname)
        self.assertEqual(document2.checksum, document.checksum)

        document3 = document.copy({"datas": self.blob1_b64})
        self.assertEqual(document3.datas, self.blob1_b64)
        self.assertEqual(document3.raw, self.blob1)
        self.assertTrue(document3.store_fname)  # no data in db but has a store_fname
        self.assertEqual(document3.db_datas, False)
        self.assertEqual(document3.store_fname, self.blob1_fname)
        self.assertEqual(document3.checksum, self.blob1_hash)

    def test_12_gc(self):
        # zero the grace window: this test marks and sweeps immediately
        self.patch(IrAttachment, "_GC_CHECKLIST_GRACE", 0)
        # unique data so no other attachment shares the file, letting the gc collect it
        unique_blob = os.urandom(16)
        a1 = self.Attachment.create({"name": "a1", "raw": unique_blob})
        store_path = Path(self.filestore, a1.store_fname)
        self.assertTrue(store_path.is_file(), "file exists")
        a1.unlink()
        self.Attachment._gc_file_store_unsafe()
        self.assertFalse(store_path.is_file(), "file removed")

    def test_13_rollback(self):
        # zero the grace window: this test marks and sweeps immediately
        self.patch(IrAttachment, "_GC_CHECKLIST_GRACE", 0)
        # unique data so no other attachment shares the file, letting the gc collect it
        unique_blob = os.urandom(16)
        with contextlib.closing(self.cr.savepoint()):
            a1 = self.env["ir.attachment"].create({"name": "a1", "raw": unique_blob})
            store_path = Path(self.filestore, a1.store_fname)
            self.assertTrue(store_path.is_file(), "file exists")
        self.env["ir.attachment"]._gc_file_store_unsafe()
        self.assertFalse(store_path.is_file(), "file removed")

    def test_gc_prewalked_checklist(self):
        """GC accepts a checklist scanned before the lock (IRA-P2-3).

        The collect phase drops orphans yet spares files a live row still
        references (the whitelist query under the lock).
        """
        self.patch(IrAttachment, "_GC_CHECKLIST_GRACE", 0)
        Attachment = self.env["ir.attachment"]
        orphan = Attachment.create({"name": "orphan", "raw": os.urandom(16)})
        kept = Attachment.create({"name": "kept", "raw": os.urandom(16)})
        orphan_fname = orphan.store_fname  # capture before unlink deletes the row
        kept_fname = kept.store_fname
        orphan_path = Path(self.filestore, orphan_fname)
        kept_path = Path(self.filestore, kept_fname)

        orphan.unlink()  # marks the orphan's file for GC
        Attachment._mark_for_gc(kept_fname)  # also mark a still-referenced file
        Attachment.flush_recordset(["store_fname"])

        checklist = Attachment._gc_checklist()
        self.assertIn(orphan_fname, checklist)
        self.assertIn(kept_fname, checklist)

        Attachment._gc_file_store_unsafe(checklist)  # pre-walked path
        self.assertFalse(orphan_path.is_file(), "orphan file must be collected")
        self.assertTrue(kept_path.is_file(), "referenced file must be spared")

    def _checklist_marker(self, fname):
        """Return the checklist marker path for *fname*."""
        return Path(self.filestore, "checklist", fname)

    def _age_marker(self, fname, age_seconds):
        """Backdate *fname*'s checklist marker mtime by *age_seconds*."""
        marker = self._checklist_marker(fname)
        past = marker.stat().st_mtime - age_seconds
        os.utime(marker, (past, past))

    def test_gc_grace_spares_fresh_markers(self):
        """GC must not sweep a checklist entry younger than the grace window
        (IRA-G1).

        create() writes and marks the file BEFORE super().create() flushes the
        INSERT, so an autovacuum racing that window would delete a not-yet-
        committed transaction's content. The age gate in _gc_checklist closes
        the race.
        """
        unique_blob = os.urandom(16)
        a1 = self.Attachment.create({"name": "a1", "raw": unique_blob})
        fname = a1.store_fname
        store_path = Path(self.filestore, fname)
        a1.unlink()

        # Fresh marker (just re-marked by unlink): the default-grace scan
        # must exclude it, and the sweep must leave file AND marker alone.
        checklist = self.Attachment._gc_checklist()
        self.assertNotIn(fname, checklist, "fresh marker must be grace-skipped")
        self.Attachment._gc_file_store_unsafe()
        self.assertTrue(store_path.is_file(), "file within grace must survive")
        self.assertTrue(
            self._checklist_marker(fname).is_file(),
            "marker within grace must stay for a later run",
        )

        # Age the marker past the grace window: now the sweep collects it.
        self._age_marker(fname, IrAttachment._GC_CHECKLIST_GRACE + 60)
        checklist = self.Attachment._gc_checklist()
        self.assertIn(fname, checklist, "aged marker must be sweepable")
        self.Attachment._gc_file_store_unsafe()
        self.assertFalse(store_path.is_file(), "aged orphan must be collected")
        self.assertFalse(self._checklist_marker(fname).is_file())

    def test_gc_grace_remark_refreshes_clock(self):
        """A dedup-hit re-mark must reset the marker's grace clock (IRA-G1).

        Both _file_write and _file_write_stream re-mark on dedup hits: the
        existing file may be an aborted transaction's orphan whose marker
        already outlived the grace window, and without an mtime refresh the GC
        could sweep it before the CURRENT transaction flushes its INSERT.
        """
        unique_blob = os.urandom(16)
        checksum = hashlib.sha1(unique_blob, usedforsecurity=False).hexdigest()

        # First write creates file + marker; backdate the marker so it looks
        # like the leftover of a long-aborted transaction.
        fname = self.Attachment._file_write(unique_blob, checksum)
        self._age_marker(fname, IrAttachment._GC_CHECKLIST_GRACE + 60)
        self.assertIn(fname, self.Attachment._gc_checklist())

        # Buffered dedup hit: the re-mark must refresh the mtime back
        # inside the grace window.
        self.assertEqual(self.Attachment._file_write(unique_blob, checksum), fname)
        self.assertNotIn(
            fname,
            self.Attachment._gc_checklist(),
            "_file_write dedup hit must refresh the marker's grace clock",
        )

        # Streamed dedup hit: same contract.
        self._age_marker(fname, IrAttachment._GC_CHECKLIST_GRACE + 60)
        self.assertIn(fname, self.Attachment._gc_checklist())
        stream_fname, size, stream_checksum = self.Attachment._file_write_stream(
            io.BytesIO(unique_blob)
        )
        self.assertEqual((stream_fname, size, stream_checksum), (fname, 16, checksum))
        self.assertNotIn(
            fname,
            self.Attachment._gc_checklist(),
            "_file_write_stream dedup hit must refresh the marker's grace clock",
        )

    def test_gc_sweep_restats_marker_before_unlink(self):
        """The sweep re-stats the checklist marker under the lock, sparing a
        file whose marker was refreshed after the pre-lock scan (IRA-G1
        residual race).

        _gc_checklist stats marker mtimes before the SHARE lock; between that
        scan and the unlink, a concurrent transaction can re-mark (refreshing
        the grace clock) and rewrite the file, whose still-uncommitted INSERT
        the whitelist query cannot see. Re-stating under the lock closes the gap.
        """
        a1 = self.Attachment.create({"name": "restat", "raw": os.urandom(16)})
        fname = a1.store_fname
        store_path = Path(self.filestore, fname)
        a1.unlink()  # marks the file for GC; the row is gone (not whitelisted)

        # Pre-lock scan: age the marker so it is collectable and enters the
        # checklist (grace stays the non-zero default so the re-stat guard fires).
        self._age_marker(fname, IrAttachment._GC_CHECKLIST_GRACE + 60)
        checklist = self.Attachment._gc_checklist()
        self.assertIn(fname, checklist)

        # A concurrent transaction re-marks the file (refreshing the marker to
        # "now") after the pre-lock stat; its content file is still on disk.
        os.utime(self._checklist_marker(fname), None)
        self.assertTrue(store_path.is_file())

        # Sweeping the pre-scanned checklist must re-stat and spare the file.
        self.Attachment._gc_file_store_unsafe(checklist)
        self.assertTrue(
            store_path.is_file(),
            "a file whose marker was refreshed after the scan must be spared",
        )

    def test_14_invalid_mimetype_with_correct_file_extension_no_post_processing(
        self,
    ):
        # test with fake svg with png mimetype
        unique_blob = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        a1 = self.Attachment.create(
            {"name": "a1", "raw": unique_blob, "mimetype": "image/png"}
        )
        self.assertEqual(a1.raw, unique_blob)
        self.assertEqual(a1.mimetype, "image/png")

    def test_15_read_bin_size_doesnt_read_datas(self):
        self.env.invalidate_all()
        IrAttachment = self.registry["ir.attachment"]
        main_partner = self.env.ref("base.main_partner")
        with patch.object(
            IrAttachment,
            "_file_read",
            side_effect=IrAttachment._file_read,
            autospec=True,
        ) as patch_file_read:
            self.env["res.partner"].with_context(bin_size=True).search_read(
                [("id", "in", main_partner.ids)], ["image_128"]
            )
            self.assertEqual(patch_file_read.call_count, 0)

    def test_create_unique_invalid_base64(self):
        """create_unique raises UserError with chained exception on bad base64."""
        from odoo.exceptions import UserError

        with self.assertRaises(UserError) as cm:
            self.Attachment.create_unique(
                [
                    {
                        "name": "bad.txt",
                        "datas": "NOT_VALID_BASE64!!!",
                        "mimetype": "text/plain",
                    }
                ]
            )
        # Verify the exception chain is preserved (from exc)
        self.assertIsNotNone(
            cm.exception.__cause__, "Exception chain should be preserved"
        )

    def test_create_unique_dedup(self):
        """create_unique deduplicates by checksum/size/mimetype."""
        data = base64.b64encode(b"hello dedup").decode()
        ids = self.Attachment.create_unique(
            [
                {"name": "a.txt", "datas": data, "mimetype": "text/plain"},
                {"name": "b.txt", "datas": data, "mimetype": "text/plain"},
            ]
        )
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[0], ids[1], "Same content should deduplicate")

    def test_create_unique_dedups_against_unreadable_row(self):
        """create_unique dedups against a row the caller cannot read (IRA-C2).

        The dedup search runs sudo(), so identical content owned by someone else
        / in another company is reused (reading it stays ACL-gated downstream).
        A non-sudo dedup would apply the caller's ACL, miss the row, and wrongly
        duplicate.
        """
        company_b = self.env["res.company"].sudo().create({"name": "IRA-C2 B"})
        user_b = (
            self.env["res.users"]
            .sudo()
            .create(
                {
                    "name": "ira-c2",
                    "login": "ira_c2_b",
                    "company_id": company_b.id,
                    "company_ids": [(6, 0, [company_b.id])],
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )
        payload = b"ira-c2-shared-" + os.urandom(8)
        # admin-owned orphan (res_id=False, not public): invisible to user_b via
        # the creator rule in _search, yet content-addressed for dedup.
        seeded = self.Attachment.sudo().create(
            {
                "name": "seed",
                "mimetype": "text/plain",
                "raw": payload,
                "company_id": self.env.company.id,
            }
        )
        self.env.flush_all()
        self.assertFalse(
            self.Attachment.with_user(user_b).search([("id", "=", seeded.id)]),
            "precondition: the seeded row is unreadable by the dedup caller",
        )
        dedup_ids = self.Attachment.with_user(user_b).create_unique(
            [
                {
                    "name": "dup",
                    "mimetype": "text/plain",
                    "raw": payload,
                    "company_id": company_b.id,
                }
            ]
        )
        self.assertEqual(
            dedup_ids,
            [seeded.id],
            "sudo dedup reuses the unreadable cross-company row instead of duplicating",
        )

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_to_http_stream_missing_file(self):
        """_to_http_stream gracefully handles missing filestore file."""
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        att = self.Attachment.create(
            {
                "name": "test.txt",
                "raw": b"test content",
            }
        )
        self.assertTrue(att.store_fname, "Attachment should be stored in filestore")

        # Delete the filestore file to simulate missing file
        full_path = att._full_path(att.store_fname)
        Path(full_path).unlink()

        # Push a fake request onto the LocalStack so `request.db` resolves.
        from types import SimpleNamespace

        from odoo.http.core import _request_stack

        fake_request = SimpleNamespace(db=self.env.cr.dbname)
        _request_stack.push(fake_request)
        try:
            with patch("odoo.addons.base.models.ir_attachment.root"):
                stream = att._to_http_stream()
                self.assertEqual(stream.type, "data")
                self.assertEqual(stream.data, b"")
                self.assertEqual(stream.size, 0)
                # The degraded stream must carry NO caching metadata: built with
                # etag = checksum (the REAL content's digest), a cacheable 200
                # with this empty body would keep answering 304 after the file is
                # restored, pinning the empty body in caches forever.
                self.assertIs(
                    stream.etag, False, "empty fallback must not keep the real ETag"
                )
                self.assertIsNone(stream.last_modified)
                self.assertFalse(
                    stream.conditional, "fallback must not serve conditionally"
                )
                self.assertFalse(stream.public, "fallback must not be proxy-cacheable")
        finally:
            _request_stack.pop()

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_postprocess_bad_max_resolution(self):
        """Bad base.image_autoresize_max_px config skips resize instead of crashing."""
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (2000, 2000), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()

        for bad_val in ("1920", "abc", ""):
            self.env["ir.config_parameter"].set_param(
                "base.image_autoresize_max_px", bad_val
            )
            # Should NOT raise ValueError — just skip the resize
            att = self.Attachment.create(
                {
                    "name": "test.png",
                    "raw": png_data,
                }
            )
            self.assertTrue(att.id)

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_postprocess_bad_quality(self):
        """Bad base.image_autoresize_quality must skip, not crash the upload.

        Mirrors test_postprocess_bad_max_resolution for the quality param: an
        over-bounds JPEG forces the resize+quality path, where int(quality)
        previously raised ValueError and blocked every such upload (P0-5).
        """
        img = Image.new("RGB", (64, 64), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        jpeg_data = buf.getvalue()

        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_max_px", "10x10"
        )  # force the resize branch (64 > 10)
        for bad_val in ("notanint", "", "80%"):
            self.env["ir.config_parameter"].set_param(
                "base.image_autoresize_quality", bad_val
            )
            att = self.Attachment.create(
                {"name": "q.jpg", "raw": jpeg_data, "mimetype": "image/jpeg"}
            )
            self.assertTrue(att.id, f"upload must survive quality={bad_val!r}")

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_to_http_stream_url_without_request(self):
        """url-branch of _to_http_stream must not crash with no request bound.

        P0-1: cron / server-side report rendering reach this path with an empty
        request stack, where ``request.httprequest`` raised.
        """
        from odoo.http.core import _request_stack

        att = self.Attachment.create(
            {"name": "u", "type": "binary", "url": "/web/static/does-not-exist.png"}
        )
        att.db_datas = False  # ensure the url branch is taken
        # Sanity-check the precondition: no request is bound in this context.
        self.assertFalse(_request_stack(), "test must run with no request bound")
        with patch("odoo.addons.base.models.ir_attachment.root") as mock_root:
            mock_root.get_static_file.return_value = None
            stream = att._to_http_stream()
        self.assertEqual(stream.type, "url")
        self.assertEqual(stream.url, att.url)
        # host must degrade to "" rather than dereferencing an unbound proxy
        self.assertEqual(mock_root.get_static_file.call_args.kwargs.get("host"), "")

    def test_compute_res_name_orphaned_res_id(self):
        """_compute_res_name degrades to False for an orphaned res_id (P0-6).

        A res_id pointing at a missing record must not raise MissingError and
        break list views. ORM deletion would cascade-delete this attachment, so
        the real trigger is an orphaned reference (import, raw-SQL deletion,
        cross-model leftover); reproduced here with an id that cannot exist.
        """
        att = self.Attachment.create(
            {
                "name": "orphan",
                "raw": b"x",
                "res_model": "res.partner",
                "res_id": 2147483646,
            }
        )
        att.invalidate_recordset(["res_name"])
        # Must not raise; the orphaned target resolves to False.
        self.assertFalse(att.res_name)

    def test_index_preserves_non_ascii_text(self):
        """_index keeps accented/non-ASCII words whole for text content.

        The old byte-class [\\x20-\\x7E] split every multi-byte UTF-8 char,
        shredding Spanish words and crippling full-text search. The Unicode-aware
        scan keeps them intact while matching the old output for pure ASCII.
        """
        Att = self.env["ir.attachment"]
        spanish = "Configuración del módulo árbol genealógico".encode()
        indexed = Att._index(spanish, "text/plain")
        self.assertIn("Configuración", indexed)
        self.assertIn("módulo", indexed)
        self.assertIn("genealógico", indexed)
        # non-text content is still not indexed
        self.assertIsNone(Att._index(b"\x89PNG\r\n", "image/png"))
        # pure-ASCII output is unchanged: printable runs >=4, split on controls
        ascii_data = b"hello world\nshort\na\nplain ascii text here"
        self.assertEqual(
            Att._index(ascii_data, "text/plain"),
            "hello world\nshort\nplain ascii text here",
        )

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_migrate_preserves_content_on_empty_read(self):
        """_migrate must never blank a non-empty file on an empty read (P0-2).

        Simulates a transient _file_read failure (returns b"") during migration;
        stored content and store_fname must be untouched.
        """
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        att = self.Attachment.create({"name": "precious", "raw": b"precious-bytes"})
        original_fname = att.store_fname
        original_size = att.file_size
        self.assertTrue(original_fname)

        IrAttachment = self.registry["ir.attachment"]
        with patch.object(IrAttachment, "_file_read", return_value=b""):
            att._migrate()

        att.invalidate_recordset()
        self.assertEqual(att.store_fname, original_fname, "store_fname must survive")
        self.assertEqual(att.file_size, original_size, "file_size must survive")
        self.assertTrue(
            Path(self.filestore, original_fname).is_file(), "file must survive"
        )

    def test_create_from_stream_unreadable_readback_skips_index(self):
        """_create_from_stream must not index an empty read-back of stored content.

        _file_read returns b"" on a (possibly transient) read error; indexing
        that would derive the index from the wrong (empty) bytes. Same guard as
        _compute_raw/_migrate.
        """
        payload = b"streamed text payload for indexation"
        # positive control: the streaming path indexes readable text content
        ok = self.Attachment._create_from_stream(
            io.BytesIO(payload), name="ok.txt", mimetype="text/plain"
        )
        self.assertIn("streamed", ok.index_content)

        IrAttachmentCls = self.registry["ir.attachment"]
        with (
            patch.object(IrAttachmentCls, "_file_read", return_value=b""),
            patch.object(
                IrAttachmentCls,
                "_index",
                autospec=True,
                side_effect=IrAttachmentCls._index,
            ) as index_spy,
            self.assertLogs("odoo.addons.base.models.ir_attachment", "WARNING") as log,
        ):
            att = self.Attachment._create_from_stream(
                io.BytesIO(payload), name="s.txt", mimetype="text/plain"
            )
        self.assertEqual(index_spy.call_count, 0, "empty read-back must not be indexed")
        self.assertTrue(any("skipping index extraction" in line for line in log.output))
        self.assertFalse(att.index_content)
        # the stored content and its metadata are untouched by the guard
        self.assertEqual(att.file_size, len(payload))
        att.invalidate_recordset()
        self.assertEqual(att.raw, payload)

    def test_invalid_base64_datas_raises_user_error(self):
        """Every 'datas' entry point surfaces invalid base64 as a UserError.

        b64decode raises binascii.Error (a ValueError subclass) on malformed
        padding/length; all decodes go through _decode_datas, which wraps it as
        a clean UserError instead of a 500.
        """
        bad = b"a"  # 1 char is never a valid base64 quantum, even unpadded
        with self.assertRaises(UserError):
            self.Attachment.create({"name": "bad", "datas": bad})
        att = self.Attachment.create({"name": "ok", "raw": b"x"})
        with self.assertRaises(UserError):
            att.write({"datas": bad})
        with self.assertRaises(UserError):
            self.Attachment.create_unique(
                [{"name": "bad", "mimetype": "text/plain", "datas": bad}]
            )
        with self.assertRaises(UserError):
            self.Attachment._mimetype_from_values({"datas": bad})

    def test_content_derivation_memoized_within_batch(self):
        """Identical payloads in one batch derive their metadata once.

        Both content loops memoize _get_datas_related_values over identical
        bytes (create() keyed on the checksum, write on the payload's identity),
        so _index runs once, not once per record.
        """
        IrAttachmentCls = self.registry["ir.attachment"]
        payload = b"same text payload for every record in the batch"

        # create(): the base64 path decodes a distinct object per row, so the
        # memo must hit on the checksum, not on object identity.
        datas = base64.b64encode(payload)
        with patch.object(
            IrAttachmentCls,
            "_index",
            autospec=True,
            side_effect=IrAttachmentCls._index,
        ) as index_spy:
            atts = self.Attachment.create(
                [
                    {"name": f"c{i}.txt", "datas": datas, "mimetype": "text/plain"}
                    for i in range(3)
                ]
            )
        self.assertEqual(index_spy.call_count, 1, "create must derive the batch once")
        self.assertEqual(len(set(atts.mapped("store_fname"))), 1)
        for att in atts:
            self.assertEqual(att.raw, payload)
            self.assertIn("payload", att.index_content)

        # write path: `write({'raw': X})` hands every record the same cached
        # bytes object, hit by the single-slot identity memo.
        rewritten = b"rewritten text payload shared by the whole batch"
        with patch.object(
            IrAttachmentCls,
            "_index",
            autospec=True,
            side_effect=IrAttachmentCls._index,
        ) as index_spy:
            atts.write({"raw": rewritten})
        self.assertEqual(index_spy.call_count, 1, "write must derive the batch once")
        atts.invalidate_recordset()
        for att in atts:
            self.assertEqual(att.raw, rewritten)
            self.assertIn("rewritten", att.index_content)

    def test_write_res_field_check_grouped_by_model(self):
        """write() checks the res_field ACL once per distinct res_model (IRA-L2).

        The field ACL is deterministic per (res_model, res_field, operation,
        user), so a batch on the same comodel needs one check, not one per
        record — same rationale as _check_access's memoization.
        """
        partner = self.env["res.partner"].create({"name": "grouped-check"})
        atts = self.Attachment.create(
            [
                {
                    "name": f"g{i}",
                    "raw": b"x",
                    "res_model": "res.partner",
                    "res_id": partner.id,
                }
                for i in range(3)
            ]
        )
        IrAttachmentCls = self.registry["ir.attachment"]
        with patch.object(
            IrAttachmentCls,
            "_check_res_field_access",
            autospec=True,
            side_effect=IrAttachmentCls._check_res_field_access,
        ) as spy:
            atts.write({"res_field": "image_1920"})
        self.assertEqual(spy.call_count, 1, "one ACL check per distinct res_model")
        self.assertEqual(set(atts.mapped("res_field")), {"image_1920"})

    def test_migrate_does_not_resize_images(self):
        """_migrate is a storage move, not a content rewrite (P0-3).

        An image stored larger than the current autoresize limit must keep its
        exact bytes across a migration — image_no_postprocess guards the write.
        """
        img = Image.new("RGB", (64, 64), color="green")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        jpeg_data = buf.getvalue()

        # Upload with resize disabled so the stored image stays 64x64...
        self.env["ir.config_parameter"].set_param("base.image_autoresize_max_px", "0")
        att = self.Attachment.create(
            {"name": "big.jpg", "raw": jpeg_data, "mimetype": "image/jpeg"}
        )
        stored = att.raw
        # ...then drop the limit below the image size and migrate.
        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_max_px", "10x10"
        )
        att._migrate()
        att.invalidate_recordset()
        self.assertEqual(att.raw, stored, "migration must not mutate image bytes")

    def test_serving_check_on_content_write(self):
        """Swapping a served binary+url attachment's content re-checks the
        serving group (IRA-P1-1).

        ``write`` only re-runs ``_check_serving_attachments`` on url/type change,
        but the *content* is what ir.http._serve_fallback serves. The check lives
        in ``_set_attachment_data``, which both content paths reach
        (``write({'raw': ...})`` and ``record.raw = ...`` via the inverse).
        """
        att = self.Attachment.create(
            {"name": "asset", "type": "binary", "url": "/web/assets/x.js", "raw": b"v1"}
        )
        with patch.object(
            IrAttachment,
            "_check_serving_attachments",
            side_effect=IrAttachment._check_serving_attachments,
            autospec=True,
        ) as spy:
            att.write({"raw": b"v2"})  # content-only write — used to skip the check
            self.assertGreaterEqual(spy.call_count, 1, "write({'raw'}) must re-check")
            spy.reset_mock()
            att.raw = b"v3"
            att.flush_recordset()
            self.assertGreaterEqual(spy.call_count, 1, "record.raw= must re-check")

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_file_write_atomic_no_poison(self):
        """A failed _file_write must not poison the content-addressed path (P0-4).

        A crash mid-write used to leave a truncated file at the final path,
        failing every future _same_content check with a spurious collision
        UserError. tmp-file + atomic replace prevents that.
        """
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        payload = b"atomic-write-" + os.urandom(16)
        checksum = hashlib.sha1(payload, usedforsecurity=False).hexdigest()
        target = Path(self.filestore, checksum[:2], checksum)
        checklist = Path(self.filestore, "checklist", checksum[:2], checksum)
        self.addCleanup(target.unlink, missing_ok=True)
        self.addCleanup(checklist.unlink, missing_ok=True)

        # Simulate a crash during the atomic rename.
        with patch("pathlib.Path.replace", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.env["ir.attachment"]._file_write(payload, checksum)
        self.assertFalse(
            target.exists(), "no truncated file may remain at the real path"
        )
        # Staging happens in the filestore tmp/ dir so a crash-orphaned temp is
        # reachable by _gc_stale_filestore_temps (a shard-dir temp was swept by
        # no GC). The failure path must still unlink it, and the shard dir must
        # never see a temp.
        tmp_dir = Path(self.filestore, "tmp")
        self.assertEqual(
            list(tmp_dir.glob("write-*")) if tmp_dir.is_dir() else [],
            [],
            "staging temp cleaned up on failure",
        )
        self.assertEqual(
            list(target.parent.glob(f"{checksum}.tmp-*")),
            [],
            "no temp file may be staged in the shard dir",
        )

        # The same content can now be written and round-trips correctly.
        fname = self.env["ir.attachment"]._file_write(payload, checksum)
        self.assertEqual(self.env["ir.attachment"]._file_read(fname), payload)

    def test_file_write_stages_temp_in_tmp_dir(self):
        """_file_write stages its temp in the filestore tmp/ dir, not the shard.

        A shard-dir temp left by a pre-replace crash was reachable by no GC (the
        checklist walk never saw it, the tmp/ sweep only scans tmp/). Staging in
        tmp/ lets _gc_stale_filestore_temps collect it. Pin the location so a
        revert to shard-dir staging is caught.
        """
        payload = b"tmp-staging-" + os.urandom(16)
        checksum = hashlib.sha1(payload, usedforsecurity=False).hexdigest()
        target = Path(self.filestore, checksum[:2], checksum)
        self.addCleanup(target.unlink, missing_ok=True)
        self.addCleanup(
            Path(self.filestore, "checklist", checksum[:2], checksum).unlink,
            missing_ok=True,
        )
        tmp_dir = Path(self.filestore, "tmp")

        captured = {}
        orig_replace = Path.replace

        def capture(self, dst):
            captured["src_parent"] = self.parent
            return orig_replace(self, dst)

        with patch.object(Path, "replace", capture):
            self.env["ir.attachment"]._file_write(payload, checksum)
        self.assertEqual(
            captured.get("src_parent"),
            tmp_dir,
            "the staging temp must be created under the filestore tmp/ dir",
        )
        self.assertEqual(
            list(target.parent.glob(f"{checksum}.tmp-*")),
            [],
            "no temp may be staged in the shard dir",
        )

    def test_file_write_single_get_path(self):
        """A filestore create resolves the path once, not twice (IRA-P2-1).

        Only _file_write calls _get_path now (not _get_datas_related_values).
        Guards against reintroducing the double mkdir + double full-file
        collision read.
        """
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        unique = b"single-path-" + os.urandom(16)
        with patch.object(
            IrAttachment, "_get_path", side_effect=IrAttachment._get_path, autospec=True
        ) as patched:
            att = self.Attachment.create({"name": "sp", "raw": unique})
            self.addCleanup(
                Path(self.filestore, att.store_fname).unlink, missing_ok=True
            )
        self.assertEqual(patched.call_count, 1, "exactly one _get_path per write")

    def test_empty_content_checksum_consistency(self):
        """Empty content gets the same checksum whether created or written (P0-7).

        _content_checksum's contract is "an empty file has a checksum too (for
        caching)". write honoured it; create used to skip it, leaving an empty
        attachment with checksum=False and no ETag in _to_http_stream.
        """
        empty_sha = hashlib.sha1(b"", usedforsecurity=False).hexdigest()
        created = self.Attachment.create({"name": "empty", "raw": b""})
        self.assertEqual(created.checksum, empty_sha, "create must set empty checksum")
        self.assertEqual(created.file_size, 0)
        # consistent with the write path producing the same checksum
        written = self.Attachment.create({"name": "x", "raw": b"data"})
        written.write({"raw": b""})
        self.assertEqual(written.checksum, empty_sha, "write path agrees")

    def test_audit_url_attachments_warns_on_suspicious(self):
        """``_audit_url_attachments`` flags non-public binary attachments with
        ``url`` set.

        Defense-in-depth for ``ir.http._serve_fallback``: any such record is
        publicly servable at ``url``. The autovacuum pass logs a WARNING so ops
        can review before a real exposure occurs.
        """
        # Bypass `_check_serving_attachments` by creating as admin (sudo),
        # mirroring the real concern: a future ``controller.sudo().create(
        # {'url': user_input})`` would slip past the write-time gate.
        suspicious = self.Attachment.sudo().create(
            {
                "name": "probe.bin",
                "type": "binary",
                "url": "/suspicious/probe",
                "raw": b"x",
                "public": False,
            }
        )
        self.assertTrue(suspicious.id)

        with self.assertLogs(
            "odoo.addons.base.models.ir_attachment", level="WARNING"
        ) as logs:
            self.env["ir.attachment"]._audit_url_attachments()

        self.assertTrue(
            any("non-public binary attachment" in msg for msg in logs.output),
            f"expected audit warning, got: {logs.output!r}",
        )

    def test_audit_url_attachments_warns_once_per_row(self):
        """A suspicious row is WARNING-reported once, then INFO while it
        remains unresolved (seen ids persist in ir_attachment.url_audit_seen).
        """
        self.Attachment.sudo().create(
            {
                "name": "probe-once.bin",
                "type": "binary",
                "url": "/suspicious/probe-once",
                "raw": b"x",
                "public": False,
            }
        )
        logger_name = "odoo.addons.base.models.ir_attachment"
        with self.assertLogs(logger_name, level="INFO") as first:
            self.env["ir.attachment"]._audit_url_attachments()
        self.assertTrue(
            any(rec.levelname == "WARNING" for rec in first.records),
            "first sighting must warn",
        )
        with self.assertLogs(logger_name, level="INFO") as second:
            self.env["ir.attachment"]._audit_url_attachments()
        self.assertFalse(
            any(rec.levelname == "WARNING" for rec in second.records),
            "already-reported rows must not re-warn",
        )
        self.assertTrue(
            any("previously reported" in rec.getMessage() for rec in second.records),
            "unresolved rows keep an INFO heartbeat",
        )

    def test_audit_url_attachments_silent_on_clean_fleet(self):
        """No suspicious rows → no WARNING emitted."""
        # Ensure any pre-existing rows are public=True (usual safe case).
        self.env.cr.execute(
            "UPDATE ir_attachment SET public = TRUE "
            "WHERE type = 'binary' AND url IS NOT NULL"
        )
        with self.assertNoLogs(
            "odoo.addons.base.models.ir_attachment", level="WARNING"
        ):
            self.env["ir.attachment"]._audit_url_attachments()


class TestPermissions(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        # replace self.env(uid=1) with an actual user environment so rules apply
        self.env = self.env(user=self.user_demo)
        self.Attachments = self.env["ir.attachment"]

        # create a record with an attachment and a rule allowing Read access
        # but preventing Create, Update, or Delete
        record = self.Attachments.create({"name": "record1"})
        self.vals = {
            "name": "attach",
            "res_id": record.id,
            "res_model": record._name,
        }
        a = self.attachment = self.Attachments.create(self.vals)

        # prevent create, write and unlink accesses on record
        self.rule = (
            self.env["ir.rule"]
            .sudo()
            .create(
                {
                    "name": "remove access to record %d" % record.id,
                    "model_id": self.env["ir.model"]._get_id(record._name),
                    "domain_force": "[('id', '!=', %s)]" % record.id,
                    "perm_read": False,
                }
            )
        )
        self.env.flush_all()
        a.invalidate_recordset()

    def test_read_permission(self):
        """If the record can't be read, the attachment can't be read either
        If the attachment is public, the attachment can be read even if the record can't be read
        If the attachment has no res_model/res_id, it can be read by its author and admins only
        """
        # check that the information can be read out of the box
        _ = self.attachment.datas
        # prevent read access on record
        self.rule.perm_read = True
        self.attachment.invalidate_recordset()
        with self.assertRaises(AccessError):
            _ = self.attachment.datas

        # Make the attachment public
        self.attachment.sudo().public = True
        # Check the information can be read again
        _ = self.attachment.datas
        # Remove the public access
        self.attachment.sudo().public = False
        # Check the record can no longer be accessed
        with self.assertRaises(AccessError):
            _ = self.attachment.datas

        # Create an attachment as user without res_model/res_id
        attachment_user = self.Attachments.create({"name": "foo"})
        # Check the user can access his own attachment
        _ = attachment_user.datas
        # Create an attachment as superuser without res_model/res_id
        attachment_admin = self.Attachments.with_user(SUPERUSER_ID).create(
            {"name": "foo"}
        )
        # Check the record cannot be accessed by a regular user
        with self.assertRaises(AccessError):
            _ = attachment_admin.with_user(self.env.user).datas
        # Check the record can be accessed by an admin (other than superuser)
        admin_user = self.env.ref("base.user_admin")
        # Safety assert that base.user_admin is not the superuser, otherwise the test is useless
        self.assertNotEqual(SUPERUSER_ID, admin_user.id)
        _ = attachment_admin.with_user(admin_user).datas

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_field_read_permission(self):
        """If the record field can't be read,
        e.g. `groups="base.group_system"` on the field,
        the attachment can't be read either.
        """
        # check that the information can be read out of the box
        main_partner = self.env.ref("base.main_partner")
        self.assertTrue(main_partner.image_128)
        attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "res.partner"),
                ("res_id", "=", main_partner.id),
                ("res_field", "=", "image_128"),
            ]
        )
        self.assertTrue(attachment.datas)
        with self.assertQueries(
            [
                # security SQL contains public check or accessible field with
                # res_id IN accessible corecords for a given res_model
                """
            SELECT "ir_attachment"."id"
            FROM "ir_attachment"
            WHERE ("ir_attachment"."res_field" IN (%s) AND "ir_attachment"."res_id" IN (%s) AND "ir_attachment"."res_model" IN (%s) AND (
                "ir_attachment"."public" IS TRUE
                OR (
                    ("ir_attachment"."res_field" IN (%s) OR "ir_attachment"."res_field" IS NULL)
                    AND "ir_attachment"."res_id" IN (
                        SELECT "res_partner"."id"
                        FROM "res_partner"
                        WHERE "res_partner"."id" IN (%s) AND (
                            ("res_partner"."company_id" IN (%s) OR "res_partner"."company_id" IS NULL)
                            OR "res_partner"."partner_share" IS NOT TRUE
                        )
                    )
                    AND "ir_attachment"."res_model" IN (%s)
                )
            ))
            ORDER BY "ir_attachment"."id" DESC
            """
            ]
        ):
            self.env["ir.attachment"].search(
                [
                    ("res_model", "=", "res.partner"),
                    ("res_id", "=", main_partner.id),
                    ("res_field", "=", "image_128"),
                ]
            )

        # Patch the field `res.partner.image_128` to make it unreadable by the demo user
        self.patch(
            self.env.registry["res.partner"]._fields["image_128"],
            "groups",
            "base.group_system",
        )

        # Assert the field can't be read
        with self.assertRaises(AccessError):
            _ = main_partner.image_128
        # Assert the attachment related to the field can't be read
        with self.assertRaises(AccessError):
            _ = attachment.datas

    def test_field_read_permission_uses_comodel_acl(self):
        """The res_field ACL in _check_access must defer to the *comodel's*
        _has_field_access, not ir.attachment's.

        A comodel overriding the method (e.g. res.users self-service fields)
        would otherwise be bypassed, leaking a field it forbids. Unlike a plain
        ``groups=...`` field (covered above, model-independent), only an override
        exposes the wrong-model dispatch this guards against.
        """
        main_partner = self.env.ref("base.main_partner")
        attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "res.partner"),
                ("res_id", "=", main_partner.id),
                ("res_field", "=", "image_128"),
            ]
        )
        self.assertTrue(attachment.datas)  # readable out of the box

        partner_field = self.env.registry["res.partner"]._fields["image_128"]
        attach_called, partner_called = [], []
        attach_orig = self.env.registry["ir.attachment"]._has_field_access
        partner_orig = self.env.registry["res.partner"]._has_field_access

        def attach_spy(this, field, operation, _o=attach_orig):
            if field is partner_field:
                attach_called.append(operation)
            return _o(this, field, operation)

        def partner_deny(this, field, operation, _o=partner_orig):
            if field is partner_field:
                partner_called.append(operation)
                if operation == "read":
                    return False
            return _o(this, field, operation)

        self.patch(self.env.registry["ir.attachment"], "_has_field_access", attach_spy)
        self.patch(self.env.registry["res.partner"], "_has_field_access", partner_deny)

        # The comodel now forbids reading image_128 -> the attachment must too.
        attachment.invalidate_recordset()
        with self.assertRaises(AccessError):
            _ = attachment.datas

        # The field ACL was evaluated on the comodel, not on ir.attachment.
        self.assertIn("read", partner_called, "comodel ACL must be consulted")
        self.assertNotIn(
            "read", attach_called, "field ACL must not be checked on ir.attachment"
        )

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_search_unbounded_model_fallback(self):
        """The unbounded ``_search`` fallback filters inaccessible rows (IRA-T1).

        A broad ``('id', 'in', [...])`` domain has no ``res_model`` constraint,
        so ``_search`` takes the ``sudo()`` batched-fetch + ``_filtered_access``
        post-filter branch instead of the ≤5-model branch; an attachment the
        demo user must not see stays excluded.
        """
        # public attachment: always visible
        public_att = self.Attachments.sudo().create({"name": "public", "public": True})
        # orphan attachment owned by the superuser: a non-system user must
        # not see it (res_id is False and create_uid != demo)
        admin_orphan = self.Attachments.with_user(SUPERUSER_ID).create(
            {"name": "admin-orphan"}
        )
        # demo's own orphan: visible to its creator
        own_orphan = self.Attachments.create({"name": "demo-orphan"})

        probe_ids = (public_att + admin_orphan + own_orphan).ids
        found = self.Attachments.search([("id", "in", probe_ids)])
        self.assertIn(public_att.id, found.ids)
        self.assertIn(own_orphan.id, found.ids)
        self.assertNotIn(
            admin_orphan.id,
            found.ids,
            "the superuser-owned orphan attachment must not leak to the demo user",
        )

    def test_search_unbounded_matches_limited(self):
        """Unbounded (limit=None) _search returns the same accessible set as a
        limited search — the batched fetch must not drop or duplicate rows
        (IRA-P1-3). Guards the memory-bounding rewrite of the limit=None branch.
        """
        atts = self.Attachments.sudo().create(
            [{"name": f"pub{i}", "public": True} for i in range(12)]
        )
        ids = atts.ids
        unbounded = self.Attachments.search([("id", "in", ids)])  # limit=None branch
        limited = self.Attachments.search([("id", "in", ids)], limit=len(ids))
        self.assertEqual(set(unbounded.ids), set(ids), "unbounded must return all")
        self.assertEqual(
            set(unbounded.ids), set(limited.ids), "unbounded must match limited"
        )

    def test_search_keyset_pagination_crosses_batches(self):
        """Multi-batch keyset/OFFSET pagination must equal a single fetch (IRA-B5).

        ``test_search_unbounded_matches_limited`` uses fewer rows than
        ``PREFETCH_MAX`` (1000), leaving the keyset seek predicate in
        ``_fetch_accessible_ids`` (and a forbidden row as batch anchor)
        unexercised. Patching ``PREFETCH_MAX`` to 3 over interleaved rows: the
        batch size must not change which rows ``_search`` returns in ANY mode
        (limit=None keyset, bounded keyset, offset slices, caller order), and
        must never drop, duplicate, or leak an inaccessible row across a boundary.
        """
        # accessible to demo: public, or a demo-owned orphan (create_uid=demo,
        # res_id=False). inaccessible: a superuser-owned orphan.
        all_ids = []
        for i in range(24):
            kind = i % 3
            if kind == 0:
                a = self.Attachments.sudo().create(
                    {"name": f"p{i:02d}", "public": True}
                )
            elif kind == 1:
                a = self.Attachments.create({"name": f"o{i:02d}"})  # demo orphan
            else:
                a = self.Attachments.with_user(SUPERUSER_ID).create(
                    {"name": f"a{i:02d}"}
                )
            all_ids.append(a.id)
        domain = [("id", "in", all_ids)]
        forbidden = set(all_ids[2::3])  # the superuser-owned orphans (kind == 2)

        def run():
            search = self.Attachments.search
            return {
                "limit=None": search(domain).ids,
                "limit=5": search(domain, limit=5).ids,
                "limit=7": search(domain, limit=7).ids,
                "offset=3,limit=4": search(domain, offset=3, limit=4).ids,
                "order=name": search(domain, order="name").ids,
                "order=name,limit=6": search(domain, order="name", limit=6).ids,
                "order=name,offset=5,limit=5": search(
                    domain, order="name", offset=5, limit=5
                ).ids,
            }

        truth = run()  # single fetch at PREFETCH_MAX=1000
        with patch("odoo.addons.base.models.ir_attachment.PREFETCH_MAX", 3):
            batched = run()  # forced into many small batches

        for label, ids in batched.items():
            self.assertEqual(
                ids,
                truth[label],
                f"{label}: multi-batch result diverged from single fetch",
            )
            self.assertEqual(
                len(ids), len(set(ids)), f"{label}: duplicate id across batch boundary"
            )
            self.assertFalse(
                set(ids) & forbidden, f"{label}: leaked an inaccessible row"
            )

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_res_field_write_access(self):
        """A new ``res_field`` must pass the comodel field's ACL (IRA-L2).

        Otherwise a non-system user could re-point an attachment's ``res_field``
        at a field they cannot access, since the ``res_field`` Char has no
        ``groups``.
        """
        partner = self.user_demo.partner_id
        # Restrict a writable partner field to system users only.
        self.patch(
            self.env.registry["res.partner"]._fields["comment"],
            "groups",
            "base.group_system",
        )

        # create: pointing res_field at the inaccessible field is forbidden
        with self.assertRaises(AccessError):
            self.Attachments.create(
                {
                    "name": "field-attach",
                    "res_model": "res.partner",
                    "res_id": partner.id,
                    "res_field": "comment",
                }
            )

        # write: re-pointing an existing attachment's res_field is forbidden
        existing = self.Attachments.create(
            {
                "name": "field-attach",
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        with self.assertRaises(AccessError):
            existing.write({"res_field": "comment"})

    def test_from_request_file_mimetype_modes(self):
        """``_from_request_file`` honours the three mimetype modes (IRA-T2).

        Also pins the XSS-neuter contract: a ``TRUST``-ed ``text/html`` /
        ``image/svg+xml`` upload is forced to ``text/plain`` for a non-view
        writer (the demo user), so the upload path is no stored-XSS vector.
        """

        class _FakeFile:
            def __init__(self, content, content_type, filename):
                self._buf = io.BytesIO(content)
                self.content_type = content_type
                self.filename = filename

            def read(self, size=-1):
                return self._buf.read(size)

            def seek(self, offset, whence=0):
                return self._buf.seek(offset, whence)

        # explicit mimetype mode
        explicit = self.Attachments._from_request_file(
            _FakeFile(b"hello", "application/octet-stream", "note.txt"),
            mimetype="text/plain",
        )
        self.assertEqual(explicit.mimetype, "text/plain")

        # GUESS mode: content sniffed (a real PNG header)
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        guessed = self.Attachments._from_request_file(
            _FakeFile(png, "application/octet-stream", "img"),
            mimetype="GUESS",
        )
        self.assertEqual(guessed.mimetype, "image/png")

        # TRUST mode: a malicious html upload is neutered to text/plain for a
        # non-view writer (XSS regression pin)
        trusted_html = self.Attachments._from_request_file(
            _FakeFile(b"<script>alert(1)</script>", "text/html", "evil.html"),
            mimetype="TRUST",
        )
        self.assertEqual(
            trusted_html.mimetype,
            "text/plain",
            "TRUST-ed text/html must be neutered for a non-view writer",
        )
        trusted_svg = self.Attachments._from_request_file(
            _FakeFile(b"<svg/>", "image/svg+xml", "evil.svg"),
            mimetype="TRUST",
        )
        self.assertEqual(
            trusted_svg.mimetype,
            "text/plain",
            "TRUST-ed image/svg+xml must be neutered for a non-view writer",
        )

    def test_with_write_permissions(self):
        """With write permissions to the linked record, attachment can be
        created, updated, or deleted (or copied).
        """
        # enable write permission on linked record
        self.rule.perm_write = False
        attachment = self.Attachments.create(self.vals)
        attachment.copy()
        attachment.write({"raw": b"test"})
        attachment.unlink()

    def test_basic_modifications(self):
        """Lacking write access to the linked record means create, update, and
        delete on the attachment are forbidden
        """
        with self.assertRaises(AccessError):
            self.Attachments.create(self.vals)
        with self.assertRaises(AccessError):
            self.attachment.write({"raw": b"yay"})
        with self.assertRaises(AccessError):
            self.attachment.unlink()
        with self.assertRaises(AccessError):
            self.attachment.copy()

    def test_cross_record_copies(self):
        """Copying attachments between records (in the same model or not) adds
        wrinkles as the ACLs may diverge a lot more
        """
        # create an other unwritable record in a different model
        unwritable = self.env["res.users.apikeys.description"].create(
            {"name": "Unwritable"}
        )
        with self.assertRaises(AccessError):
            unwritable.write({})  # checks unwritability
        # create a writable record in the same model
        writable = self.Attachments.create({"name": "yes"})
        writable.name = "canwrite"  # checks for writeability

        # can copy from a record with read permissions to one with write permissions
        copied = self.attachment.copy(
            {"res_model": writable._name, "res_id": writable.id}
        )
        # can copy to self given write permission
        copied.copy()
        # can not copy back to record without write permission
        with self.assertRaises(AccessError):
            copied.copy({"res_id": self.vals["res_id"]})

        # can not copy to a record without write permission
        with self.assertRaises(AccessError):
            self.attachment.copy(
                {"res_model": unwritable._name, "res_id": unwritable.id}
            )
        # even from a record with write permissions
        with self.assertRaises(AccessError):
            copied.copy({"res_model": unwritable._name, "res_id": unwritable.id})

    def test_write_error(self):
        # try to write a file in a place where we have no access
        # /proc is not writeable, check if we have an error raised
        self.patch(
            IrAttachment,
            "_get_path",
            lambda self, binary, _checksum: (binary, "/proc/dummy_test"),
        )
        with self.assertRaises(OSError):
            self.env["ir.attachment"]._file_write(b"test", "test")

    def test_write_create_url_binary_attachment(self):
        """A non-serving user cannot create/write a binary+url attachment.

        Assert on the exception type only: the message goes through ``_()`` and
        this dev DB serves ``es_MX``, so matching the English string is flaky.
        ``_check_serving_attachments`` is the only ValidationError these paths
        can raise.
        """
        with self.assertRaises(ValidationError):
            self.Attachments.create(
                {"name": "Py", "url": "/blabla.js", "raw": b"Something"}
            )
        with self.assertRaises(ValidationError):
            self.Attachments.create(
                {"name": "Py", "url": "/blabla.js", "raw": b"Something"}
            )
        with self.assertRaises(ValidationError):
            self.Attachments.with_context(default_url="/blabla.js").create(
                {"name": "Py", "raw": b"Something"}
            )

        existing_attachment = self.Attachments.create({"name": "aaa"})
        with self.assertRaises(ValidationError):
            existing_attachment.url = "/blabla.js"
        existing_attachment.type = "url"
        existing_attachment.url = "/blabla.js"

        with self.assertRaises(ValidationError):
            existing_attachment.type = "binary"
