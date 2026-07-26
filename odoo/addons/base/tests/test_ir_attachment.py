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
from odoo.tests.common import skip_if_dev_mode
from odoo.tools import mute_logger
from odoo.tools.hashing import ALGO_TAG
from odoo.tools.image import image_to_base64

from odoo.addons.base.models import ir_attachment as ir_attachment_module
from odoo.addons.base.models.ir_attachment import IrAttachment
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class TestIrAttachment(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.filestore = self.Attachment._filestore()

        # Blob1
        self.blob1 = b"blob1"
        self.blob1_b64 = base64.b64encode(self.blob1)
        self.blob1_hash = self.Attachment._content_checksum(self.blob1)
        self.blob1_fname = self.Attachment._file_store_path(self.blob1_hash)

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
        checksum = self.Attachment._content_checksum(unique_blob)

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

    def test_read_prefix_filestore_and_db(self):
        """_read_prefix reads a bounded head from either content location."""
        on_disk = self.Attachment.create({"name": "a1", "raw": self.blob1})
        self.assertTrue(on_disk.store_fname)
        self.assertEqual(on_disk._read_prefix(3), self.blob1[:3])
        self.assertEqual(on_disk._read_prefix(), self.blob1)

        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        in_db = self.Attachment.create({"name": "a2", "raw": self.blob2})
        self.assertFalse(in_db.store_fname)
        self.assertEqual(in_db._read_prefix(3), self.blob2[:3])
        self.assertEqual(in_db._read_prefix(), self.blob2)

    def test_read_prefix_ignores_bin_size(self):
        """A bin_size context must not turn the read into a size string.

        Under bin_size a stored binary column reads back as
        ``pg_size_pretty(length(...))``, so without neutralizing it the caller
        would receive b"5 bytes" and treat it as content.
        """
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        in_db = self.Attachment.create({"name": "a1", "raw": self.blob1})
        self.env.invalidate_all()
        sized = in_db.with_context(bin_size=True)
        # guard the premise: the plain field read really does yield a size here
        self.assertNotEqual(sized.db_datas, self.blob1)
        self.assertEqual(sized._read_prefix(), self.blob1)
        self.assertEqual(sized._read_prefix(3), self.blob1[:3])

    def test_read_prefix_without_content(self):
        """A content-less row reads as empty rather than raising."""
        bare = self.Attachment.create({"name": "a1", "type": "binary"})
        self.assertEqual(bare._read_prefix(10), b"")

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

    def test_create_unique_contentless_matches_create(self):
        """Content-less values behave exactly as in create() (IRA-R1/IRA-C4).

        create_unique used to re-implement the raw/datas normalization instead
        of sharing `_normalize_content_vals`, and unconditionally set
        ``raw = b""``. A value carrying NO content key therefore got the digest
        of b"" stamped on it, and every such row collapsed onto one id because
        they all shared that digest.
        """
        created = self.Attachment.create({"name": "bare", "mimetype": "text/plain"})
        ids = self.Attachment.create_unique(
            [
                {"name": "bare-a", "mimetype": "text/plain"},
                {"name": "bare-b", "mimetype": "text/plain"},
            ]
        )
        uniques = self.Attachment.browse(ids)
        self.assertEqual(
            uniques.mapped("checksum"),
            [created.checksum, created.checksum],
            "a content-less value must not be stamped with the digest of b''",
        )
        self.assertNotEqual(
            ids[0], ids[1], "content-less values have nothing to deduplicate on"
        )
        self.assertEqual(uniques.mapped("name"), ["bare-a", "bare-b"])

    def test_create_unique_preserves_db_datas_passthrough(self):
        """The db_datas escape hatch survives create_unique, as it does create().

        Forcing ``raw = b""`` for a value with no content key overwrote the
        caller's db_datas with empty bytes — silent content loss on the one
        documented way to write the column directly.
        """
        vals = {"name": "hatch", "mimetype": "text/plain", "db_datas": b"hand-written"}
        created = self.Attachment.create(dict(vals))
        [unique_id] = self.Attachment.create_unique([dict(vals)])
        self.assertEqual(created.raw, b"hand-written")
        self.assertEqual(
            self.Attachment.browse(unique_id).raw,
            b"hand-written",
            "create_unique must not blank a db_datas passthrough",
        )

    def test_create_unique_does_not_mutate_caller_values(self):
        """create_unique copies before normalizing (model_create_multi contract)."""
        values = {
            "name": "keep.txt",
            "mimetype": "text/plain",
            "datas": base64.b64encode(b"payload").decode(),
        }
        self.Attachment.create_unique([values])
        self.assertIn("datas", values, "the caller's dict must not be mutated")

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
        checksum = self.Attachment._content_checksum(payload)
        store_path = self.Attachment._file_store_path(checksum)
        target = Path(self.filestore, store_path)
        checklist = Path(self.filestore, "checklist", store_path)
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
        checksum = self.Attachment._content_checksum(payload)
        store_path = self.Attachment._file_store_path(checksum)
        target = Path(self.filestore, store_path)
        self.addCleanup(target.unlink, missing_ok=True)
        self.addCleanup(
            Path(self.filestore, "checklist", store_path).unlink,
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

    def test_stream_write_resolves_path_through_get_path(self):
        """The streaming writer resolves its path through _get_path too.

        _file_write_stream used to re-derive the store path, the shard mkdir and
        the collision check inline, so a deployment overriding _get_path — the
        documented single resolution point, pinned by the test above — silently
        kept stock behaviour on every streamed upload.
        """
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        payload = b"stream-path-" + os.urandom(16)
        with patch.object(
            IrAttachment, "_get_path", side_effect=IrAttachment._get_path, autospec=True
        ) as patched:
            fname, size, _checksum = self.Attachment._file_write_stream(
                io.BytesIO(payload)
            )
        self.addCleanup(Path(self.filestore, fname).unlink, missing_ok=True)
        self.assertEqual(
            patched.call_count, 1, "exactly one _get_path per stream write"
        )
        self.assertEqual(size, len(payload))
        self.assertEqual(self.Attachment._file_read(fname), payload)

    def test_stream_write_collision_unstages_temp(self):
        """A collision on the streamed path must not leak the staged temp.

        The temp is written before the digest is known, so the collision is only
        detected afterwards; the failure path has to unstage it rather than
        leave it for the age-based sweep.
        """
        self.env["ir.config_parameter"].set_param(
            "ir_attachment.verify_content_collision", "True"
        )
        payload = b"stream-collide-" + os.urandom(16)
        checksum = self.Attachment._content_checksum(payload)
        planted = Path(self.filestore, self.Attachment._file_store_path(checksum))
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_bytes(b"different bytes entirely")
        self.addCleanup(planted.unlink, missing_ok=True)

        tmp_dir = Path(self.Attachment._full_path("tmp"))
        before = set(tmp_dir.iterdir()) if tmp_dir.is_dir() else set()
        with self.assertRaises(UserError):
            self.Attachment._file_write_stream(io.BytesIO(payload))
        after = set(tmp_dir.iterdir()) if tmp_dir.is_dir() else set()
        self.assertEqual(after, before, "the staged temp must be removed on failure")

    def test_empty_content_checksum_consistency(self):
        """Empty content gets the same checksum whether created or written (P0-7).

        _content_checksum's contract is "an empty file has a checksum too (for
        caching)". write honoured it; create used to skip it, leaving an empty
        attachment with checksum=False and no ETag in _to_http_stream.
        """
        empty_sha = self.Attachment._content_checksum(b"")
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


class TestContentDigestKeys(TransactionCaseWithUserDemo):
    """Algorithm-tagged store keys and coexistence with legacy sha1 keys.

    The digest moved from sha1 to ``tools.hashing``'s content family; keys
    written under the new algorithm carry its tag so the two layouts share one
    filestore.  What must hold is compatibility, not any particular algorithm:
    rows written before the switch keep resolving, and every filestore
    primitive stays agnostic to the key's shape.
    """

    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.filestore = self.Attachment._filestore()
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")

    def _legacy_key(self, payload):
        """Write *payload* at an untagged ``<shard>/<sha1>`` key, as pre-BLAKE3
        code did, and return that key."""
        sha = hashlib.sha1(payload, usedforsecurity=False).hexdigest()
        fname = sha[:2] + "/" + sha
        path = Path(self.filestore, fname)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        self.addCleanup(path.unlink, missing_ok=True)
        return fname, sha

    def test_new_keys_carry_the_algorithm_tag(self):
        """A fresh write is stored under ``<algo>/<shard>/<digest>``."""
        att = self.Attachment.create({"name": "tagged", "raw": b"tag-" + os.urandom(8)})
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        expected = self.Attachment._file_store_path(att.checksum)
        self.assertEqual(att.store_fname, expected)
        if ALGO_TAG != "s1":
            self.assertTrue(att.store_fname.startswith(f"{ALGO_TAG}/"))
            # tag, shard, digest — the extra level the GC walk must tolerate
            self.assertEqual(len(att.store_fname.split("/")), 3)
        self.assertEqual(Path(self.filestore, att.store_fname).read_bytes(), att.raw)

    def test_checksum_column_fits_the_digest(self):
        """The stored checksum survives a flush + reread (column is wide enough)."""
        att = self.Attachment.create({"name": "len", "raw": b"len-" + os.urandom(8)})
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        att.flush_recordset()
        att.invalidate_recordset()
        self.assertEqual(att.checksum, self.Attachment._content_checksum(att.raw))
        self.assertLessEqual(len(att.checksum), 64)

    def test_legacy_key_still_reads(self):
        """A row whose store_fname predates the tag keeps serving its bytes."""
        payload = b"legacy-" + os.urandom(16)
        fname, sha = self._legacy_key(payload)
        att = self.Attachment.create({"name": "legacy", "raw": b"placeholder"})
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        # simulate the pre-switch row: untagged key + 40-char sha1 checksum
        att.flush_recordset()
        self.env.cr.execute(
            "UPDATE ir_attachment SET store_fname = %s, checksum = %s, file_size = %s "
            "WHERE id = %s",
            [fname, sha, len(payload), att.id],
        )
        att.invalidate_recordset()
        self.assertEqual(att.raw, payload, "legacy-keyed content must still read")
        self.assertEqual(self.Attachment._file_read(fname), payload)
        self.assertEqual(len(att.checksum), 40)

    def test_legacy_key_is_gc_collectable(self):
        """The GC sweeps an untagged key exactly like a tagged one."""
        payload = b"legacy-gc-" + os.urandom(16)
        fname, _sha = self._legacy_key(payload)
        self.Attachment._mark_for_gc(fname)
        marker = Path(self.filestore, "checklist", fname)
        self.assertTrue(marker.is_file(), "marker created at the legacy depth")
        checklist = self.Attachment._gc_checklist(grace=0)
        self.assertIn(fname, checklist)
        # unreferenced by any row → collected, marker cleaned up. Scan and sweep
        # with grace=0 (the marker is seconds old) and hand the sweep only this
        # key, so the assertions cannot be perturbed by other markers.
        self.Attachment._gc_file_store_unsafe(
            checklist={fname: checklist[fname]}, grace=0
        )
        self.assertFalse(Path(self.filestore, fname).exists())
        self.assertFalse(marker.exists())

    def test_both_layouts_coexist_in_one_filestore(self):
        """Same bytes under both layouts: each key resolves to its own file."""
        payload = b"coexist-" + os.urandom(16)
        legacy_fname, _sha = self._legacy_key(payload)
        att = self.Attachment.create({"name": "coexist", "raw": payload})
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        if ALGO_TAG != "s1":
            self.assertNotEqual(att.store_fname, legacy_fname)
        self.assertEqual(self.Attachment._file_read(legacy_fname), payload)
        self.assertEqual(self.Attachment._file_read(att.store_fname), payload)

    def test_collision_verification_default_follows_the_algorithm(self):
        """The re-read defaults on only for the collision-prone digest."""
        self.assertEqual(
            self.Attachment._verify_content_collision(),
            ALGO_TAG == "s1",
            "sha1 needs the byte-compare; a modern digest does not",
        )

    def test_collision_verification_param_wins(self):
        """An explicit parameter overrides the algorithm-derived default."""
        ICP = self.env["ir.config_parameter"]
        for value, expected in (("True", True), ("False", False)):
            ICP.set_param("ir_attachment.verify_content_collision", value)
            self.assertEqual(self.Attachment._verify_content_collision(), expected)

    # -- sha1-fallback branches -------------------------------------------
    # ``blake3`` is a hard requirement, so the branches taken when it is
    # absent are otherwise dead in every integration run. These two patch the
    # tag that selects them, pinning the *branch* — not a full sha1
    # deployment, which only ``tools/tests/test_hashing.py`` can simulate.

    def test_untagged_layout_under_the_sha1_tag(self):
        """Without the extension, keys keep the historical untagged shape.

        The compatibility promise runs both ways: a node that lost the wheel
        must write where the pre-BLAKE3 code wrote, or it would strand its
        content under a prefix the rest of the fleet never looks at.
        """
        sha = "0" * 40
        with patch.object(ir_attachment_module, "ALGO_TAG", "s1"):
            self.assertEqual(self.Attachment._file_store_path(sha), f"{sha[:2]}/{sha}")

    def test_verification_defaults_on_under_the_sha1_tag(self):
        """The byte-compare comes back on when the digest is the broken one."""
        with patch.object(ir_attachment_module, "ALGO_TAG", "s1"):
            self.assertTrue(self.Attachment._verify_content_collision())

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_forced_verification_still_detects_a_mismatch(self):
        """With verification forced on, wrong bytes at the key are refused.

        Guards the opt-in path: the check must still work when an operator
        turns it back on, whatever the digest in use.
        """
        self.env["ir.config_parameter"].set_param(
            "ir_attachment.verify_content_collision", "True"
        )
        payload = b"verify-" + os.urandom(16)
        checksum = self.Attachment._content_checksum(payload)
        fname = self.Attachment._file_store_path(checksum)
        path = Path(self.filestore, fname)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"different bytes entirely")
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaises(UserError):
            self.Attachment._file_write(payload, checksum)

    def test_stream_and_buffered_writes_agree(self):
        """``_file_write_stream`` produces the same key/digest as ``_file_write``."""
        payload = b"stream-" + os.urandom(4096)
        fname, size, checksum = self.Attachment._file_write_stream(io.BytesIO(payload))
        self.addCleanup(Path(self.filestore, fname).unlink, missing_ok=True)
        self.assertEqual(size, len(payload))
        self.assertEqual(checksum, self.Attachment._content_checksum(payload))
        self.assertEqual(fname, self.Attachment._file_store_path(checksum))
        self.assertEqual(self.Attachment._file_read(fname), payload)

    # -- opt-in convergence of legacy keys ---------------------------------

    def _legacy_row(self, payload):
        """Create a row whose stored content sits at an untagged legacy key."""
        fname, sha = self._legacy_key(payload)
        att = self.Attachment.create({"name": "legacy-row", "raw": b"placeholder"})
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        att.flush_recordset()
        self.env.cr.execute(
            "UPDATE ir_attachment SET store_fname = %s, checksum = %s, file_size = %s "
            "WHERE id = %s",
            [fname, sha, len(payload), att.id],
        )
        att.invalidate_recordset()
        return att, fname

    def _drain_legacy_rows(self):
        """Re-key every pre-existing legacy row so counts are the test's own.

        A dev/CI database carries rows written before the digest switch; without
        this, a count assertion measures the database's history rather than the
        behaviour under test. Rolled back with the test transaction.
        """
        while self.Attachment._gc_rehash_legacy_keys(limit=1000)[0]:
            pass

    def test_rehash_is_disabled_by_default(self):
        """Absent the parameter, the pass must not touch a single row."""
        att, fname = self._legacy_row(b"untouched-" + os.urandom(16))
        self.assertEqual(self.Attachment._gc_rehash_legacy_keys(), (0, 0))
        att.invalidate_recordset()
        self.assertEqual(att.store_fname, fname, "no re-key without the opt-in")

    def test_rehash_rekeys_and_preserves_content(self):
        """An opted-in run moves the row to the current layout, bytes intact."""
        if ALGO_TAG == "s1":
            self.skipTest("no target layout to converge to under the sha1 fallback")
        self._drain_legacy_rows()
        payload = b"converge-" + os.urandom(16)
        att, old_fname = self._legacy_row(payload)
        size_before, index_before = att.file_size, att.index_content

        self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=10), (1, 0))

        att.invalidate_recordset()
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        self.assertTrue(att.store_fname.startswith(f"{ALGO_TAG}/"))
        self.assertEqual(att.raw, payload, "bytes must survive the re-key")
        self.assertEqual(att.checksum, self.Attachment._content_checksum(payload))
        self.assertEqual(
            att.store_fname, self.Attachment._file_store_path(att.checksum)
        )
        # bytes did not change, so the derived metadata must not have either
        self.assertEqual(att.file_size, size_before)
        self.assertEqual(att.index_content, index_before)
        # the superseded key is only MARKED for GC, never unlinked inline
        self.assertTrue(Path(self.filestore, old_fname).exists())
        self.assertTrue(Path(self.filestore, "checklist", old_fname).exists())

    def test_rehash_respects_its_limit_and_is_resumable(self):
        """The batch size caps a run; the next run picks up where it stopped."""
        if ALGO_TAG == "s1":
            self.skipTest("no target layout to converge to under the sha1 fallback")
        self._drain_legacy_rows()
        rows = [
            self._legacy_row(f"batch-{i}".encode() + os.urandom(8))[0] for i in range(3)
        ]
        # (re-keyed, remaining): a truthy remaining is what re-enqueues the
        # pass inside one autovacuum run instead of one batch per daily run
        self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=2), (2, 1))
        self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=2), (1, 0))
        self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=2), (0, 0))
        for att in rows:
            att.invalidate_recordset()
            self.addCleanup(
                Path(self.filestore, att.store_fname).unlink, missing_ok=True
            )
            self.assertTrue(att.store_fname.startswith(f"{ALGO_TAG}/"))

    def test_rehash_leaves_shared_legacy_content_readable(self):
        """Re-keying one of two rows sharing a key must not strand the other.

        The old key is marked for GC, and the sweep whitelists any key a row
        still references — so the sibling keeps resolving.
        """
        if ALGO_TAG == "s1":
            self.skipTest("no target layout to converge to under the sha1 fallback")
        self._drain_legacy_rows()
        payload = b"shared-" + os.urandom(16)
        first, legacy_fname = self._legacy_row(payload)
        second, _ = self._legacy_row(payload)  # same content, same legacy key
        self.assertEqual(second.store_fname, legacy_fname)

        self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=1)[0], 1)
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.addCleanup(Path(self.filestore, first.store_fname).unlink, missing_ok=True)

        checklist = self.Attachment._gc_checklist(grace=0)
        if legacy_fname in checklist:
            self.Attachment._gc_file_store_unsafe(
                checklist={legacy_fname: checklist[legacy_fname]}, grace=0
            )
        self.assertEqual(second.raw, payload, "the sibling row must still read")

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_rehash_reports_no_remaining_when_it_makes_no_progress(self):
        """A batch that re-keys nothing must not re-enqueue itself.

        The read guard skips rows whose content cannot be read. If such a batch
        still reported rows remaining, the autovacuum would re-enqueue it for
        its whole wall-clock budget, re-reading the same broken rows.
        """
        if ALGO_TAG == "s1":
            self.skipTest("no target layout to converge to under the sha1 fallback")
        self._drain_legacy_rows()
        att, _fname = self._legacy_row(b"unreadable-" + os.urandom(16))
        # simulate unreadable content: the guard trips on empty-read vs file_size
        with patch.object(IrAttachment, "_file_read", return_value=b""):
            self.assertEqual(
                self.Attachment._gc_rehash_legacy_keys(limit=10),
                (0, 0),
                "no progress must report nothing remaining",
            )
        att.invalidate_recordset()
        self.assertFalse(att.store_fname.startswith(f"{ALGO_TAG}/"))

    def test_rehash_skips_other_backends_keys(self):
        """A schemed key belongs to another backend and is never re-keyed."""
        if ALGO_TAG == "s1":
            self.skipTest("no target layout to converge to under the sha1 fallback")
        att = self.Attachment.create({"name": "remote", "raw": b"remote-ish"})
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        att.flush_recordset()
        self.env.cr.execute(
            "UPDATE ir_attachment SET store_fname = %s WHERE id = %s",
            ["s3://bucket/deadbeef", att.id],
        )
        att.invalidate_recordset()
        self.Attachment._gc_rehash_legacy_keys(limit=10)
        att.invalidate_recordset()
        self.assertEqual(att.store_fname, "s3://bucket/deadbeef")

    def test_rehash_is_a_noop_under_db_storage(self):
        """Under ``db`` storage a rewrite would move content between backends."""
        att, fname = self._legacy_row(b"dbmode-" + os.urandom(16))
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=10), (0, 0))
        att.invalidate_recordset()
        self.assertEqual(att.store_fname, fname)


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
        skip_if_dev_mode("xml")  # ir.rule domain ormcache
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


class TestFilestoreDedup(TransactionCaseWithUserDemo):
    """Regression tests for the deduplicated filestore read/write/delete paths.

    Each pins an invariant that two implementations used to encode separately,
    so re-splitting them (or letting one drift) fails here rather than in
    production on one path only.
    """

    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.tmp_dir = Path(self.Attachment._full_path("tmp"))

    def _temps(self):
        if not self.tmp_dir.is_dir():
            return set()
        return {path.name for path in self.tmp_dir.iterdir()}

    # -- deletion: one override point for both paths ---------------------

    def test_unlink_and_content_replacement_share_the_delete_hook(self):
        """`_file_delete_multi` is THE local-filestore deletion override point.

        `unlink()` used to reach `_mark_for_gc_multi` directly, so a deployment
        overriding the per-key hook saw content *replacements* and silently
        never saw *deletions*.
        """
        seen = []
        real = IrAttachment._file_delete_multi

        def spy(records, fnames):
            seen.append(tuple(fnames))
            return real(records, fnames)

        self.patch(IrAttachment, "_file_delete_multi", spy)

        attachment = self.Attachment.create(
            {"name": "gone.bin", "raw": b"unlink-me" * 8}
        )
        self.env.flush_all()
        store_fname = attachment.store_fname
        attachment.unlink()
        self.assertTrue(
            any(store_fname in call for call in seen),
            "unlink() must schedule the old key through _file_delete_multi",
        )

        seen.clear()
        attachment = self.Attachment.create(
            {"name": "replaced.bin", "raw": b"first-content" * 8}
        )
        self.env.flush_all()
        old_fname = attachment.store_fname
        attachment.write({"raw": b"second-content" * 8})
        self.env.flush_all()
        self.assertTrue(
            any(old_fname in call for call in seen),
            "content replacement must use the same hook",
        )

    # -- reading: one triage for raw and _read_prefix ---------------------

    def test_raw_and_read_prefix_agree_on_stored_content(self):
        for location in ("file", "db"):
            with self.subTest(location=location):
                self.env["ir.config_parameter"].sudo().set_param(
                    "ir_attachment.location", location
                )
                payload = f"triage-{location}".encode() * 6
                attachment = self.Attachment.create(
                    {"name": f"{location}.bin", "raw": payload}
                )
                self.env.flush_all()
                attachment.invalidate_recordset()
                self.assertEqual(attachment.raw, payload)
                self.assertEqual(attachment._read_prefix(), payload)
                self.assertEqual(attachment._read_prefix(4), payload[:4])
        self.env["ir.config_parameter"].sudo().set_param(
            "ir_attachment.location", "file"
        )

    def test_read_prefix_keeps_the_static_url_leg_raw_does_not(self):
        """The one place the two readers deliberately differ.

        `_read_prefix` resolves a url naming an addon file; `raw` does not, and
        collapsing them would start serving those bytes through the field.
        """
        attachment = self.Attachment.create(
            {
                "name": "logo.png",
                "type": "url",
                "url": "/web/static/img/logo.png",
                "mimetype": "image/png",
            }
        )
        self.assertTrue(attachment._read_prefix())
        self.assertFalse(attachment.raw)

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_unreadable_content_is_reported_not_silently_empty(self):
        attachment = self.Attachment.create(
            {"name": "vanishing.bin", "raw": b"here-then-gone" * 8}
        )
        self.env.flush_all()
        Path(self.Attachment._full_path(attachment.store_fname)).unlink()
        attachment.invalidate_recordset()
        # Serving still degrades to empty rather than raising...
        self.assertEqual(attachment.raw, b"")
        # ...but the row keeps claiming its real size, which is what makes the
        # rewrite guard skip it instead of blanking it.
        self.assertTrue(attachment.file_size)

    # -- writing: one staging protocol ------------------------------------

    def test_both_writers_stage_and_leave_no_temp(self):
        before = self._temps()

        payload = b"buffered-payload" * 8
        payload_checksum = self.Attachment._content_checksum(payload)
        buffered_fname = self.Attachment._file_write(payload, payload_checksum)
        self.assertEqual(
            Path(self.Attachment._full_path(buffered_fname)).read_bytes(), payload
        )
        self.assertEqual(self._temps(), before, "buffered write left a temp behind")

        streamed = b"streamed-payload" * 8
        stream_fname, size, checksum = self.Attachment._file_write_stream(
            io.BytesIO(streamed)
        )
        self.assertEqual(
            Path(self.Attachment._full_path(stream_fname)).read_bytes(), streamed
        )
        self.assertEqual(size, len(streamed))
        self.assertEqual(checksum, self.Attachment._content_checksum(streamed))
        self.assertEqual(self._temps(), before, "stream write left a temp behind")

        # dedup hits return the same key and stage nothing
        self.assertEqual(
            self.Attachment._file_write(payload, payload_checksum), buffered_fname
        )
        self.assertEqual(
            self.Attachment._file_write_stream(io.BytesIO(streamed))[0], stream_fname
        )
        self.assertEqual(self._temps(), before, "a dedup hit left a temp behind")

    def test_empty_stream_stays_inline_and_stages_nothing(self):
        before = self._temps()
        fname, size, checksum = self.Attachment._file_write_stream(io.BytesIO(b""))
        self.assertEqual(fname, "")
        self.assertEqual(size, 0)
        self.assertEqual(checksum, self.Attachment._content_checksum(b""))
        self.assertEqual(self._temps(), before)

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_a_failed_stage_never_leaks_its_temp(self):
        """Whatever goes wrong mid-write, tmp/ is left as it was found."""
        before = self._temps()
        boom = OSError("disk on fire")

        def exploding_replace(self, target):
            raise boom

        self.patch(Path, "replace", exploding_replace)
        with self.assertRaises(OSError):
            self.Attachment._file_write(b"never-lands" * 8, "deadbeef" * 8)
        self.assertEqual(self._temps(), before, "buffered writer leaked a temp")

        with self.assertRaises(OSError):
            self.Attachment._file_write_stream(io.BytesIO(b"never-lands" * 8))
        self.assertEqual(self._temps(), before, "streaming writer leaked a temp")

    # -- comparison helpers ------------------------------------------------

    def test_content_comparison_helpers_agree(self):
        payload = b"compare-me" * 9
        checksum = self.Attachment._content_checksum(payload)
        path = self.Attachment._full_path(
            self.Attachment._file_write(payload, checksum)
        )

        self.assertTrue(self.Attachment._same_content(payload, path))
        self.assertFalse(self.Attachment._same_content(payload + b"!", path))
        # same length, different bytes: the size fast-reject must not pass it
        self.assertFalse(self.Attachment._same_content(b"Z" * len(payload), path))
        self.assertTrue(self.Attachment._same_content_files(path, path))

        other = b"different" * 9
        other_path = self.Attachment._full_path(
            self.Attachment._file_write(other, self.Attachment._content_checksum(other))
        )
        self.assertFalse(self.Attachment._same_content_files(path, other_path))

    # -- rewrite preamble --------------------------------------------------

    def test_migrate_round_trips_without_touching_the_bytes(self):
        payloads = [b"migrate-a" * 7, b"migrate-b" * 7]
        attachments = self.Attachment.create(
            [
                {"name": f"m{i}.bin", "raw": payload}
                for i, payload in enumerate(payloads)
            ]
        )
        self.env.flush_all()

        self.env["ir.config_parameter"].sudo().set_param("ir_attachment.location", "db")
        attachments._migrate()
        self.env.flush_all()
        attachments.invalidate_recordset()
        self.assertFalse(any(attachments.mapped("store_fname")))
        self.assertEqual(attachments.mapped("raw"), payloads)

        self.env["ir.config_parameter"].sudo().set_param(
            "ir_attachment.location", "file"
        )
        attachments._migrate()
        self.env.flush_all()
        attachments.invalidate_recordset()
        self.assertTrue(all(attachments.mapped("store_fname")))
        self.assertEqual(attachments.mapped("raw"), payloads)

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_rewrite_skips_a_row_whose_content_vanished(self):
        """A read that comes back empty must never be written back.

        Writing it would blank the row AND make the GC reclaim its only copy;
        both whole-filestore rewrites share this guard.
        """
        attachment = self.Attachment.create(
            {"name": "lost.bin", "raw": b"about-to-vanish" * 7}
        )
        self.env.flush_all()
        Path(self.Attachment._full_path(attachment.store_fname)).unlink()
        attachment.invalidate_recordset()
        key_before, size_before = attachment.store_fname, attachment.file_size

        self.env["ir.config_parameter"].sudo().set_param("ir_attachment.location", "db")
        attachment._migrate()
        self.env.flush_all()
        attachment.invalidate_recordset()
        self.env["ir.config_parameter"].sudo().set_param(
            "ir_attachment.location", "file"
        )

        self.assertEqual(attachment.store_fname, key_before, "row was rewritten anyway")
        self.assertEqual(attachment.file_size, size_before)

    # -- the three readers must agree on WHICH location wins ---------------

    def test_all_readers_resolve_the_same_content_location(self):
        """`raw`, `_read_prefix` and `_to_http_stream` share one precedence.

        The triage (keyed backend → inline db_datas → addon-static url → empty)
        is spelled out three times: twice in bytes (`_stored_content`, which
        `raw` and `_read_prefix` share) and once in streams (`_to_http_stream`),
        because a Stream cannot be expressed as a bytes read. Forcing those two
        shapes into one abstraction would be contrived — what must not drift is
        the *order*, so that is what this pins.
        """
        payload = b"precedence" * 7

        on_disk = self.Attachment.create({"name": "disk.bin", "raw": payload})
        self.env.flush_all()
        self.assertTrue(on_disk.store_fname)
        self.assertEqual(on_disk.raw, payload)
        self.assertEqual(on_disk._read_prefix(), payload)
        self.assertEqual(on_disk._to_http_stream().type, "path")

        self.env["ir.config_parameter"].sudo().set_param("ir_attachment.location", "db")
        in_db = self.Attachment.create({"name": "db.bin", "raw": payload})
        self.env.flush_all()
        self.env["ir.config_parameter"].sudo().set_param(
            "ir_attachment.location", "file"
        )
        self.assertFalse(in_db.store_fname)
        self.assertEqual(in_db.raw, payload)
        self.assertEqual(in_db._read_prefix(), payload)
        db_stream = in_db._to_http_stream()
        self.assertEqual(db_stream.type, "data")
        self.assertEqual(db_stream.data, payload)

        remote = self.Attachment.create(
            {"name": "remote", "type": "url", "url": "https://example.com/x.png"}
        )
        self.assertFalse(remote.raw)
        self.assertEqual(remote._read_prefix(), b"")
        self.assertEqual(remote._to_http_stream().type, "url")

        empty = self.Attachment.create({"name": "empty.bin"})
        self.assertFalse(empty.raw)
        self.assertEqual(empty._read_prefix(), b"")
        empty_stream = empty._to_http_stream()
        self.assertEqual(empty_stream.type, "data")
        self.assertEqual(empty_stream.size, 0)

    def test_store_key_wins_over_inline_data_for_every_reader(self):
        """A row carrying both must resolve to the keyed content, three ways.

        `db_datas` is a documented raw-column escape hatch, so a row can hold
        both a store key and inline bytes. If one reader preferred the inline
        copy it would serve different content than the other two — silently, and
        only for such rows.
        """
        payload = b"the-real-content" * 5
        attachment = self.Attachment.create({"name": "both.bin", "raw": payload})
        self.env.flush_all()
        self.assertTrue(attachment.store_fname)

        # raw-column write: deliberately bypasses the content pipeline
        attachment.db_datas = b"decoy-inline-content"
        self.env.flush_all()
        attachment.invalidate_recordset()

        self.assertEqual(attachment.raw, payload, "raw took the decoy")
        self.assertEqual(
            attachment._read_prefix(), payload, "_read_prefix took the decoy"
        )
        self.assertEqual(
            attachment._to_http_stream().type,
            "path",
            "_to_http_stream took the decoy",
        )
