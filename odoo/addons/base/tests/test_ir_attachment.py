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
from odoo.fields import Domain
from odoo.libs.constants import PREFETCH_MAX
from odoo.libs.hashing import ALGO_TAG
from odoo.tests.common import skip_if_dev_mode
from odoo.tools import OrderedSet, human_size, mute_logger
from odoo.tools.image import image_to_base64

from odoo.addons.base.models import ir_attachment as ir_attachment_module
from odoo.addons.base.models.ir_attachment import SECURITY_FIELDS, IrAttachment
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class TestIrAttachment(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.filestore = self.Attachment._filestore()

        self.blob1 = b"blob1"
        self.blob1_b64 = base64.b64encode(self.blob1)
        self.blob1_hash = self.Attachment._content_checksum(self.blob1)
        self.blob1_fname = self.Attachment._file_store_path(self.blob1_hash)

        self.blob2 = b"blob2"
        self.blob2_b64 = base64.b64encode(self.blob2)

    def assertApproximately(self, value, expectedSize, delta=1):
        with contextlib.suppress(UnicodeDecodeError):
            value = base64.b64decode(value.decode())
        size = len(value) / 1024

        self.assertAlmostEqual(size, expectedSize, delta=delta)

    def test_01_store_in_db(self):
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

    def _zip_bytes(self, entry):
        """Return a zip archive carrying no format marker of its own.

        Sniffing can only call it ``application/zip``; the filename is the only
        thing that can type it as the OOXML document it stands in for (a real
        one whose ``[Content_Types].xml`` the sniffer cannot reach — encrypted,
        or written with a non-standard entry order).
        """
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr(entry, entry)
        return buf.getvalue()

    def test_write_mimetype_matches_create_of_the_same_file(self):
        """Rewriting the content must type the file as ``create`` would.

        ``_mimetype_from_values`` only ever saw the write's own keys, so it
        never saw the row's filename and fell through to sniffing the bytes:
        ``sheet.xlsx`` came back as ``application/zip`` (served to the browser
        as a zip), and ``report.csv`` flipped between ``text/csv`` and
        ``text/plain`` with the column count.
        """
        cases = [
            ("sheet.xlsx", self._zip_bytes("first"), self._zip_bytes("second")),
            ("report.csv", b"a,b,c\n1,2,3\n", b"c,d\n3,4\n"),
            ("notes.txt", b"hello there", b"goodbye there"),
        ]
        for name, first, second in cases:
            with self.subTest(name=name):
                attachment = self.Attachment.create({"name": name, "raw": first})
                expected = self.Attachment.create(
                    {"name": name, "raw": second}
                ).mimetype
                attachment.write({"raw": second})
                self.assertEqual(
                    attachment.mimetype,
                    expected,
                    "a content write typed the file differently from a create",
                )

    def test_write_mimetype_explicit_and_heterogeneous(self):
        """An explicit ``mimetype`` wins, and mixed names fall back to sniffing.

        One ``write`` stores one mimetype, so a recordset whose rows disagree on
        their filename has no single name to derive it from.
        """
        forced = self.Attachment.create({"name": "a.txt", "raw": b"hello"})
        forced.write({"raw": b"other", "mimetype": "application/vnd.custom"})
        self.assertEqual(forced.mimetype, "application/vnd.custom")

        pair = self.Attachment.create(
            [
                {"name": "one.csv", "raw": b"a,b\n"},
                {"name": "two.xlsx", "raw": b"a,b\n"},
            ]
        )
        pair.write({"raw": b"x,y,z\n4,5,6\n"})
        self.assertEqual(
            set(pair.mapped("mimetype")),
            {self.Attachment._mimetype_from_values({"raw": b"x,y,z\n4,5,6\n"})},
            "rows disagreeing on their name must fall back to sniffing",
        )

    def test_bin_size_reports_file_size_without_reading_content(self):
        """``bin_size`` must answer from ``file_size``, not from the payload.

        Neutralizing the computed value instead read the whole file back to
        measure it, and sized ``raw`` as if it were base64 — so a 5000-byte
        file reported ``3.66 Kb`` (a quarter short) while a 4999-byte one, whose
        length is not a multiple of four, reported the correct ``4.88 Kb``.
        """
        even = self.Attachment.create({"name": "even.bin", "raw": b"x" * 5000})
        odd = self.Attachment.create({"name": "odd.bin", "raw": b"y" * 4999})
        self.env.flush_all()
        self.env.invalidate_all()

        with patch.object(
            self.registry["ir.attachment"],
            "_file_read",
            side_effect=IrAttachment._file_read,
            autospec=True,
        ) as file_read:
            sized = self.Attachment.with_context(bin_size=True).browse((even + odd).ids)
            reported = [(record.datas, record.raw) for record in sized]
            self.assertEqual(
                file_read.call_count, 0, "bin_size read the content it exists to skip"
            )

        for (datas, raw), record in zip(reported, even + odd, strict=True):
            expected = human_size(record.file_size).encode()
            self.assertEqual(datas, expected)
            self.assertEqual(raw, expected, "raw was sized as base64")

    def test_db_datas_create_goes_through_the_content_pipeline(self):
        """``db_datas`` on create is content, not a column write (IRA-R2).

        It used to reach ``super()`` untouched, producing a row with content but
        no ``file_size``, no ``checksum`` and no ``index_content``, held inline
        whatever ``ir_attachment.location`` says. The size reported to clients,
        the ETag ``_to_http_stream`` serves and the full-text index were all
        missing from a row that reads back perfectly well.
        """
        payload = b"inline,payload\n1,2\n"
        attachment = self.Attachment.create(
            {"name": "inline.csv", "db_datas": payload, "mimetype": "text/csv"}
        )
        attachment.flush_recordset()
        self.addCleanup(
            Path(self.filestore, attachment.store_fname).unlink, missing_ok=True
        )
        self.assertEqual(attachment.raw, payload)
        self.assertEqual(attachment.file_size, len(payload))
        self.assertEqual(
            attachment.checksum, self.Attachment._content_checksum(payload)
        )
        self.assertTrue(attachment.index_content)
        self.assertTrue(
            attachment.store_fname,
            "db_datas must honour ir_attachment.location, not force the column",
        )
        self.assertFalse(attachment.db_datas)
        self.assertEqual(attachment._to_http_stream().etag, attachment.checksum)

    def test_db_datas_write_replaces_the_content(self):
        """A ``db_datas`` write must replace content, not be silently dropped.

        ``store_fname`` wins in every reader, so writing the column on a
        filestore-backed row left the OLD bytes being served while Postgres
        gained a second, unreachable copy of the new ones — and
        ``file_size``/``checksum`` went on describing the old ones. The write
        returned success.
        """
        attachment = self.Attachment.create(
            {"name": "r.txt", "raw": b"original", "mimetype": "text/plain"}
        )
        attachment.flush_recordset()
        first_fname = attachment.store_fname
        self.addCleanup(Path(self.filestore, first_fname).unlink, missing_ok=True)

        attachment.write({"db_datas": b"replacement"})
        attachment.flush_recordset()
        self.addCleanup(
            Path(self.filestore, attachment.store_fname).unlink, missing_ok=True
        )
        self.env.invalidate_all()
        attachment = self.Attachment.browse(attachment.id)

        self.assertEqual(attachment.raw, b"replacement")
        self.assertEqual(attachment.file_size, len(b"replacement"))
        self.assertEqual(
            attachment.checksum, self.Attachment._content_checksum(b"replacement")
        )
        self.env.cr.execute(
            "SELECT db_datas FROM ir_attachment WHERE id = %s", [attachment.id]
        )
        self.assertFalse(
            self.env.cr.fetchone()[0],
            "the replaced content must not survive as a dead inline copy",
        )

    def test_copying_a_keyed_row_carries_no_inline_column(self):
        """A keyed row's copy takes its content from the key, never the column.

        ``db_datas`` describes where content lives, not that there is none, so
        neither the falsy value a filestore-backed row carries nor the dead
        bytes a legacy dual row carries may be read as the copy's content.
        """
        attachment = self.Attachment.create({"name": "src.bin", "raw": self.blob1})
        attachment.flush_recordset()
        self.addCleanup(
            Path(self.filestore, attachment.store_fname).unlink, missing_ok=True
        )
        self.assertNotIn("db_datas", attachment.copy_data()[0])
        self.assertFalse(
            self.Attachment._normalize_content_vals({"db_datas": False}),
            "a falsy db_datas from any source must not read as empty content",
        )
        self.assertEqual(attachment.copy().raw, self.blob1)

    def test_copy_reapplies_the_derived_columns_it_never_carries(self):
        """The four derived columns are `copy=False`, and `copy` restores them.

        `copy_data` used to carry values `create` immediately discarded
        (`_normalize_content_vals` pops all four), so the only thing the copy
        flag changed was the work done to reach the same row. It is safe
        because neither half of the copy path reads them out of the vals:
        `copy_data` triages on `attachment.store_fname`/`checksum`, and `copy`
        writes them onto the copies from `origin`.
        """
        attachment = self.Attachment.create({"name": "src.bin", "raw": self.blob1})
        attachment.flush_recordset()
        self.addCleanup(
            Path(self.filestore, attachment.store_fname).unlink, missing_ok=True
        )

        vals = attachment.copy_data()[0]
        for field in ("store_fname", "checksum", "file_size", "index_content"):
            self.assertNotIn(field, vals)

        copied = attachment.copy()
        self.assertEqual(copied.store_fname, attachment.store_fname)
        self.assertEqual(copied.checksum, attachment.checksum)
        self.assertEqual(copied.file_size, attachment.file_size)
        self.assertEqual(copied.index_content, attachment.index_content)
        self.assertEqual(copied.raw, self.blob1)

    def test_copying_a_legacy_dual_row_writes_no_new_content(self):
        """A row holding both a key and stale inline bytes must copy for free.

        ``copy`` points the copy at the origin's key, so carrying the inline
        column through made the copy hash those dead bytes and write them to
        the filestore — a content file, and a GC marker, for something nothing
        ever references.
        """
        attachment = self.Attachment.create({"name": "dual.bin", "raw": self.blob1})
        attachment.flush_recordset()
        self.addCleanup(
            Path(self.filestore, attachment.store_fname).unlink, missing_ok=True
        )
        self.env.cr.execute(
            "UPDATE ir_attachment SET db_datas = %s WHERE id = %s",
            [b"stale-inline-bytes", attachment.id],
        )
        attachment.invalidate_recordset()
        self.assertTrue(attachment.db_datas)

        stale_key = self.Attachment._file_store_path(
            self.Attachment._content_checksum(b"stale-inline-bytes")
        )
        copied = attachment.copy()
        self.env.flush_all()

        self.assertEqual(copied.raw, self.blob1)
        self.assertEqual(copied.store_fname, attachment.store_fname)
        self.assertFalse(
            Path(self.filestore, stale_key).is_file(),
            "the copy wrote the origin's dead inline bytes to the filestore",
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

        attach = Attachment.with_context(image_no_postprocess=True).create(
            {
                "name": "image",
                "datas": img_encoded,
            }
        )
        self.assertApproximately(attach.datas, fullsize)

        attach = attach.with_context(image_no_postprocess=False)
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, 12.06)

        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_max_px", "1024x768"
        )
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, 3.71)

        self.env["ir.config_parameter"].set_param("base.image_autoresize_quality", "50")
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, 3.57)

        self.env["ir.config_parameter"].set_param("base.image_autoresize_max_px", "0")
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, fullsize)

        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_max_px", "10000x10000"
        )
        self.env["ir.config_parameter"].set_param("base.image_autoresize_quality", "50")
        attach.datas = img_encoded
        self.assertApproximately(attach.datas, fullsize)

        self.env["ir.config_parameter"].search(
            [("key", "ilike", "base.image_autoresize%")]
        ).unlink()

        attach = Attachment.with_context(image_no_postprocess=True).create(
            {
                "name": "image",
                "raw": img_bin,
            }
        )
        self.assertApproximately(attach.raw, fullsize)

        attach = attach.with_context(image_no_postprocess=False)
        attach.raw = img_bin
        self.assertApproximately(attach.raw, 12.06)

        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_max_px", "1024x768"
        )
        attach.raw = img_bin
        self.assertApproximately(attach.raw, 3.71)

        self.env["ir.config_parameter"].set_param("base.image_autoresize_quality", "0")
        attach.raw = img_bin
        self.assertApproximately(attach.raw, 4.09)

        self.env["ir.config_parameter"].set_param("base.image_autoresize_quality", "50")
        attach.raw = img_bin
        self.assertApproximately(attach.raw, 3.57)

        self.env["ir.config_parameter"].set_param("base.image_autoresize_max_px", "0")
        attach.raw = img_bin
        self.assertApproximately(attach.raw, fullsize)

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
        self.assertTrue(document3.store_fname)
        self.assertEqual(document3.db_datas, False)
        self.assertEqual(document3.store_fname, self.blob1_fname)
        self.assertEqual(document3.checksum, self.blob1_hash)

    def test_12_gc(self):
        self.patch(IrAttachment, "_GC_CHECKLIST_GRACE", 0)
        unique_blob = os.urandom(16)
        a1 = self.Attachment.create({"name": "a1", "raw": unique_blob})
        store_path = Path(self.filestore, a1.store_fname)
        self.assertTrue(store_path.is_file(), "file exists")
        a1.unlink()
        self.Attachment._gc_file_store_unsafe()
        self.assertFalse(store_path.is_file(), "file removed")

    def test_13_rollback(self):
        self.patch(IrAttachment, "_GC_CHECKLIST_GRACE", 0)
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
        orphan_fname = orphan.store_fname
        kept_fname = kept.store_fname
        orphan_path = Path(self.filestore, orphan_fname)
        kept_path = Path(self.filestore, kept_fname)

        orphan.unlink()
        Attachment._mark_for_gc(kept_fname)
        Attachment.flush_recordset(["store_fname"])

        checklist = Attachment._gc_checklist()
        self.assertIn(orphan_fname, checklist)
        self.assertIn(kept_fname, checklist)

        Attachment._gc_file_store_unsafe(checklist)
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

        checklist = self.Attachment._gc_checklist()
        self.assertNotIn(fname, checklist, "fresh marker must be grace-skipped")
        self.Attachment._gc_file_store_unsafe()
        self.assertTrue(store_path.is_file(), "file within grace must survive")
        self.assertTrue(
            self._checklist_marker(fname).is_file(),
            "marker within grace must stay for a later run",
        )

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

        fname = self.Attachment._file_write(unique_blob, checksum)
        self._age_marker(fname, IrAttachment._GC_CHECKLIST_GRACE + 60)
        self.assertIn(fname, self.Attachment._gc_checklist())

        self.assertEqual(self.Attachment._file_write(unique_blob, checksum), fname)
        self.assertNotIn(
            fname,
            self.Attachment._gc_checklist(),
            "_file_write dedup hit must refresh the marker's grace clock",
        )

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
        a1.unlink()

        self._age_marker(fname, IrAttachment._GC_CHECKLIST_GRACE + 60)
        checklist = self.Attachment._gc_checklist()
        self.assertIn(fname, checklist)

        os.utime(self._checklist_marker(fname), None)
        self.assertTrue(store_path.is_file())

        self.Attachment._gc_file_store_unsafe(checklist)
        self.assertTrue(
            store_path.is_file(),
            "a file whose marker was refreshed after the scan must be spared",
        )

    def test_force_storage_migrates_rows_its_caller_cannot_read(self):
        """`force_storage` moves EVERY row, not every readable row (IRA-D2).

        The migration itself has always written as superuser, so the caller's
        ACL only decided which rows the sweep found -- and it dropped the rest
        without an error or a log line. An attachment whose ``res_model`` names
        a model that is no longer installed is unreadable by every non-superuser
        including an administrator, so it stayed on the old backend and no
        number of re-runs moved it.
        """
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        readable = self.Attachment.create({"name": "readable.txt", "raw": b"readable"})
        orphaned = self.Attachment.create(
            {
                "name": "orphaned.txt",
                "raw": b"orphaned",
                "res_model": "x.module.was.uninstalled",
                "res_id": 1,
            }
        )
        self.env.flush_all()
        self.assertFalse(readable.store_fname)
        self.assertFalse(orphaned.store_fname)

        admin = self.env.ref("base.user_admin")
        self.assertFalse(
            self.Attachment.with_user(admin)
            .with_context(skip_res_field_check=True)
            .search([("id", "=", orphaned.id)]),
            "precondition: the row is invisible to the administrator running the sweep",
        )

        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        self.Attachment.with_user(admin).force_storage()
        (readable | orphaned).invalidate_recordset()
        for att in (readable, orphaned):
            self.addCleanup(
                Path(self.filestore, att.store_fname).unlink, missing_ok=True
            )

        self.assertTrue(readable.store_fname)
        self.assertTrue(
            orphaned.store_fname, "unreadable row was silently left un-migrated"
        )
        self.assertEqual(orphaned.raw, b"orphaned")
        self.assertFalse(
            self.Attachment.sudo()
            .with_context(skip_res_field_check=True)
            .search_count(
                Domain.AND(
                    [self.Attachment._get_storage_domain(), [("type", "=", "binary")]]
                )
            ),
            "force_storage left rows matching its own migration domain behind",
        )

    def test_to_http_stream_ignores_bin_size(self):
        """The stream must carry content, never a human-readable size (IRA-D3).

        `_stored_content` and `_read_prefix` both neutralize ``bin_size``,
        because under it a stored binary column reads back as its own size.
        `_to_http_stream` runs the same triage a third time and did not, so a
        db-stored attachment streamed ``b"4.88 Kb"`` as its response body.
        """
        payload = b"X" * 5000
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        in_db = self.Attachment.create({"name": "d.bin", "raw": payload})
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        on_disk = self.Attachment.create({"name": "f.bin", "raw": payload})
        self.env.flush_all()
        self.addCleanup(
            Path(self.filestore, on_disk.store_fname).unlink, missing_ok=True
        )
        self.assertFalse(in_db.store_fname)
        self.assertTrue(on_disk.store_fname)

        sized_stream = in_db.with_context(bin_size=True)._to_http_stream()
        self.assertEqual(sized_stream.data, payload)
        self.assertEqual(sized_stream.size, len(payload))

        self.assertEqual(
            on_disk.with_context(bin_size=True)._to_http_stream().size, len(payload)
        )
        self.assertEqual(
            in_db.with_context(bin_size=True).file_size,
            len(payload),
            "bin_size still reports the size where it is asked for it",
        )

    def test_both_search_paths_agree_on_a_non_binary_res_field(self):
        """`search` must not depend on how many models the domain names (IRA-D5).

        The per-comodel field clause listed only binary fields and relations to
        ``ir.attachment``; `_check_access` -- the authority both paths are
        documented to follow -- accepts any field the user can read. So a row
        whose ``res_field`` names an ordinary readable field was returned by the
        `_fetch_accessible_ids` path (used past `_SEARCH_MODEL_DOMAIN_LIMIT`
        models) and dropped by the per-model domain path, for the same user over
        the same rows.
        """
        partner = self.env["res.partner"].sudo().create({"name": "IRA-D5"})
        att = self.Attachment.sudo().create(
            {
                "name": "odd-res-field",
                "raw": b"x",
                "mimetype": "text/plain",
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        att.flush_recordset()
        # such a row can no longer be created (`_check_res_field_valid`), but
        # databases written before that check still hold them
        self.env.cr.execute(
            "UPDATE ir_attachment SET res_field = 'comment' WHERE id = %s", [att.id]
        )
        att.invalidate_recordset()
        self.env.flush_all()

        Att = self.Attachment.with_user(self.user_demo).with_context(
            skip_res_field_check=True
        )
        wide = [
            "res.partner",
            "res.currency",
            "res.company",
            "res.country",
            "res.users",
            "res.bank",
        ]
        self.assertGreater(
            len(wide),
            self.Attachment._SEARCH_MODEL_DOMAIN_LIMIT,
            "precondition: the wide domain must take the batched access path",
        )
        one_model = Att.search([("res_model", "=", "res.partner")])
        many_models = Att.search([("res_model", "in", wide)])
        allowed = bool(Att.browse(att.id)._filtered_access("read"))

        self.assertEqual(
            att.id in one_model.ids,
            allowed,
            "per-model domain path disagrees with _check_access",
        )
        self.assertEqual(
            att.id in many_models.ids,
            allowed,
            "batched access path disagrees with _check_access",
        )

    def test_res_field_must_name_an_attachment_backed_field(self):
        """`res_field` claims "this row IS field X"; only some fields can be.

        Every writer in the codebase passes a Binary field or a relation to
        ir.attachment, and every reader assumes it -- but nothing enforced it,
        so the readers could be handed a state they each interpreted
        differently. Enforced for the superuser too: it is a data-model
        invariant, not a permission.
        """
        partner = self.env["res.partner"].sudo().create({"name": "IRA-D7"})
        base = {
            "name": "backed",
            "raw": b"x",
            "mimetype": "text/plain",
            "res_model": "res.partner",
            "res_id": partner.id,
        }
        for field_name in ("comment", "name", "active"):
            with self.subTest(field=field_name), self.assertRaises(ValidationError):
                self.Attachment.sudo().create(base | {"res_field": field_name})

        for field_name in ("image_1920", "avatar_128"):
            with self.subTest(field=field_name):
                att = self.Attachment.sudo().create(base | {"res_field": field_name})
                att.flush_recordset()
                self.addCleanup(
                    Path(self.filestore, att.store_fname).unlink, missing_ok=True
                )
                self.assertEqual(att.res_field, field_name)

        ok = self.Attachment.sudo().create(base)
        ok.flush_recordset()
        self.addCleanup(Path(self.filestore, ok.store_fname).unlink, missing_ok=True)
        with self.assertRaises(ValidationError):
            ok.write({"res_field": "comment"})

        unknown = self.Attachment.sudo().create(
            base | {"res_model": "x.gone", "res_field": "whatever"}
        )
        unknown.flush_recordset()
        self.addCleanup(
            Path(self.filestore, unknown.store_fname).unlink, missing_ok=True
        )
        self.assertEqual(
            unknown.res_field,
            "whatever",
            "an unresolvable model must stay writable for uninstall paths",
        )

    def test_full_path_confines_every_input_to_the_filestore(self):
        """No input escapes the filestore, and a leaky sanitizer is refused."""
        root = Path(self.filestore).resolve()
        for path in (
            "../../etc/passwd",
            "/etc/passwd",
            "..",
            "....//....//etc",
            "a/../../b",
            "tmp",
            "checklist",
            self.blob1_fname,
        ):
            resolved = Path(self.Attachment._full_path(path))
            self.assertTrue(
                resolved == root or root in resolved.parents,
                f"{path!r} escaped the filestore as {resolved}",
            )

        self.patch(IrAttachment, "_sanitize_store_path", lambda self, path: path)
        with self.assertRaises(ValueError):
            self.Attachment._full_path("../../etc/passwd")
        with self.assertRaises(ValueError):
            self.Attachment._full_path("/etc/passwd")

    def test_full_path_refuses_a_symlink_out_of_the_filestore(self):
        """A store key that is a symlink to elsewhere must not be readable.

        This is the whole reason `_full_path` resolves symlinks per call instead
        of joining the path lexically -- which is ~3x faster and equally proof
        against an escape spelled INTO the path. Nothing in Odoo can create such
        a link (restore writes regular files, duplicate dereferences), so it
        takes filesystem write access to plant one; the check is what keeps that
        from turning into "serve any file the server can read". It had no test,
        which is how it nearly got optimized away.
        """
        outside = Path(self.filestore).parent / f"outside-{os.urandom(6).hex()}.txt"
        outside.write_bytes(b"outside the filestore")
        self.addCleanup(outside.unlink, missing_ok=True)

        shard = Path(self.filestore, "zz")
        shard.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shard.rmdir)
        link = shard / ("f" * 40)
        link.unlink(missing_ok=True)
        link.symlink_to(outside)
        self.addCleanup(link.unlink, missing_ok=True)

        key = f"zz/{'f' * 40}"
        with self.assertRaises(ValueError):
            self.Attachment._full_path(key)
        with mute_logger("odoo.addons.base.models.ir_attachment"):
            self.assertEqual(
                self.Attachment._file_read(key),
                b"",
                "content outside the filestore was served through a symlinked key",
            )

    def test_fixed_subdirs_resolve_to_the_same_place_as_full_path(self):
        """The cached constant-dir helper must not drift from `_full_path`."""
        for name in ("tmp", "checklist"):
            self.assertEqual(
                str(self.Attachment._filestore_dir(name)),
                self.Attachment._full_path(name),
            )

    def test_14_invalid_mimetype_with_correct_file_extension_no_post_processing(
        self,
    ):
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

    def test_create_unique_treats_db_datas_as_content(self):
        """``db_datas`` is content on every entry point, create_unique included.

        It used to reach ``super()`` untouched, so a row written through it kept
        its content but had no ``checksum`` — and the dedup key IS the checksum,
        so two such rows never matched each other and create_unique degraded to
        create for them.
        """
        vals = {"name": "hatch", "mimetype": "text/plain", "db_datas": b"hand-written"}
        created = self.Attachment.create(dict(vals))
        [unique_id] = self.Attachment.create_unique([dict(vals)])
        self.assertEqual(created.raw, b"hand-written")
        self.assertEqual(
            created.checksum, self.Attachment._content_checksum(b"hand-written")
        )
        self.assertEqual(created.file_size, len(b"hand-written"))
        self.assertEqual(
            unique_id,
            created.id,
            "create_unique must dedup a db_datas value against an identical row",
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
    def test_create_unique_does_not_dedup_across_a_digest_collision(self):
        """A dedup hit must not hand back a row serving different bytes.

        `_verify_content_collision` exists because a digest with practical
        collisions otherwise lets one upload serve another's content, and
        `_get_path` honours it before sharing a filestore key. `create_unique`
        deduplicates a whole ROW on ``(checksum, file_size, mimetype)`` and
        never reached that check, so with the mitigation *enabled* an upload
        colliding with a stored file returned the stored file's id and dropped
        the caller's payload unread.
        """
        self.env["ir.config_parameter"].set_param(
            "ir_attachment.verify_content_collision", "True"
        )
        alpha = b"CONTENT-ALPHA" * 8
        bravo = b"CONTENT-BRAVO" * 8
        self.assertEqual(len(alpha), len(bravo), "a collision pair shares its length")

        real = type(self.Attachment)._content_checksum
        digest = "c0" * 20

        def colliding(model, data):
            return digest if data in (alpha, bravo) else real(model, data)

        with patch.object(type(self.Attachment), "_content_checksum", colliding):
            first = self.Attachment.create_unique(
                [
                    {
                        "name": "a.bin",
                        "mimetype": "application/octet-stream",
                        "raw": alpha,
                    }
                ]
            )
            self.env.flush_all()
            stored = self.Attachment.browse(first[0])
            self.addCleanup(
                Path(self.filestore, stored.store_fname).unlink, missing_ok=True
            )
            with self.assertRaises(UserError):
                self.Attachment.create_unique(
                    [
                        {
                            "name": "b.bin",
                            "mimetype": "application/octet-stream",
                            "raw": bravo,
                        }
                    ]
                )
        self.assertEqual(stored.raw, alpha, "the stored row must keep its own content")

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

        full_path = att._full_path(att.store_fname)
        Path(full_path).unlink()

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
        )
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
        att.db_datas = False
        self.assertFalse(_request_stack(), "test must run with no request bound")
        with patch("odoo.addons.base.models.ir_attachment.root") as mock_root:
            mock_root.get_static_file.return_value = None
            stream = att._to_http_stream()
        self.assertEqual(stream.type, "url")
        self.assertEqual(stream.url, att.url)
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
        self.assertIsNone(Att._index(b"\x89PNG\r\n", "image/png"))
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
        self.assertEqual(att.file_size, len(payload))
        att.invalidate_recordset()
        self.assertEqual(att.raw, payload)

    def test_invalid_base64_datas_raises_user_error(self):
        """Every 'datas' entry point surfaces invalid base64 as a UserError.

        b64decode raises binascii.Error (a ValueError subclass) on malformed
        padding/length; all decodes go through _decode_datas, which wraps it as
        a clean UserError instead of a 500.
        """
        bad = b"a"
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

        self.env["ir.config_parameter"].set_param("base.image_autoresize_max_px", "0")
        att = self.Attachment.create(
            {"name": "big.jpg", "raw": jpeg_data, "mimetype": "image/jpeg"}
        )
        stored = att.raw
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
            att.write({"raw": b"v2"})
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

        with patch("pathlib.Path.replace", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.env["ir.attachment"]._file_write(payload, checksum)
        self.assertFalse(
            target.exists(), "no truncated file may remain at the real path"
        )
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

    The digest moved from sha1 to ``libs.hashing``'s content family; keys
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

    @contextlib.contextmanager
    def _tagged_digest_build(self):
        """Run the body as a deployment whose digest is tagged and 64 wide.

        Which digest is installed is a property of the WHEEL, not of the code:
        without ``blake3``, ``ALGO_TAG`` is ``"s1"``, the current layout IS the
        untagged sha1 one, and every test about converging onto a tagged layout
        had nothing to converge to. They all called ``skipTest`` -- so on the
        build this workspace actually runs, the convergence pass, the shape
        matching and the digest-provenance guard had no coverage at all, which
        is how a `_migrate` bug reachable only under BLAKE3 survived.

        Substituting a deterministic 64-wide digest exercises the mechanism on
        any build. The real installed digest is still covered by the tests that
        do not enter this block.
        """
        with (
            patch.object(ir_attachment_module, "ALGO_TAG", "b3"),
            patch.object(ir_attachment_module, "CONTENT_DIGEST_LEN", 64),
            patch.object(
                ir_attachment_module,
                "content_hash",
                lambda data: hashlib.sha256(data or b"").hexdigest(),
            ),
        ):
            yield

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
        """A fresh write is stored under ``<algo>/<shard>/<digest>``.

        The tagged shape is asserted under a simulated tagged build so it is
        checked on every build, not only where the wheel happens to be present
        -- the ``if ALGO_TAG != "s1"`` it replaces asserted nothing here.
        """
        att = self.Attachment.create({"name": "tagged", "raw": b"tag-" + os.urandom(8)})
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)
        self.assertEqual(
            att.store_fname, self.Attachment._file_store_path(att.checksum)
        )
        self.assertEqual(Path(self.filestore, att.store_fname).read_bytes(), att.raw)

        with self._tagged_digest_build():
            tagged = self.Attachment.create(
                {"name": "tagged2", "raw": b"tag2-" + os.urandom(8)}
            )
            tagged.flush_recordset()
            self.addCleanup(
                Path(self.filestore, tagged.store_fname).unlink, missing_ok=True
            )
            self.assertTrue(tagged.store_fname.startswith("b3/"))
            self.assertEqual(len(tagged.store_fname.split("/")), 3)
            self.assertEqual(
                tagged.store_fname,
                self.Attachment._file_store_path(tagged.checksum),
            )

    def test_migration_never_tags_a_key_with_a_foreign_digest(self):
        """`_migrate` must re-derive a checksum it did not produce (IRA-D1).

        Only ``store_fname`` records which algorithm made a digest; the
        ``checksum`` column does not. `_migrate` reused that column as the store
        key whenever it merely looked plausible, so a row checksummed under an
        earlier algorithm was filed under the CURRENT tag carrying the OLD
        digest -- ``b3/88/<40-char sha1>``. Three things follow, none of them
        visible: `_gc_rehash_legacy_keys` skips the row forever (it matches
        ``b3/%``), the content no longer dedups against its own re-upload, and
        the key inherits the collision resistance the tag advertises while
        holding a digest that does not have it -- which is exactly what
        `_verify_content_collision` stops byte-comparing on.

        Stated without naming an algorithm: whatever ends up in the key must be
        `_content_checksum` of the bytes.
        """
        payload = b"pre-rollout-" + os.urandom(16)
        foreign = (
            hashlib.sha256(payload).hexdigest()
            if len(self.Attachment._content_checksum(payload)) != 64
            else hashlib.sha1(payload, usedforsecurity=False).hexdigest()
        )

        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        att = self.Attachment.create({"name": "vintage.bin", "raw": payload})
        att.flush_recordset()
        self.assertFalse(att.store_fname, "precondition: row is stored in db")
        self.env.cr.execute(
            "UPDATE ir_attachment SET checksum = %s WHERE id = %s", [foreign, att.id]
        )
        att.invalidate_recordset()

        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        self.Attachment.force_storage()
        att.invalidate_recordset()
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)

        expected = self.Attachment._file_store_path(
            self.Attachment._content_checksum(payload)
        )
        self.assertEqual(
            att.store_fname,
            expected,
            "migration filed the row under a key holding a foreign digest",
        )
        self.assertEqual(att.checksum, self.Attachment._content_checksum(payload))
        self.assertEqual(att.raw, payload)

        twin = self.Attachment.create({"name": "twin.bin", "raw": payload})
        twin.flush_recordset()
        self.assertEqual(
            twin.store_fname,
            att.store_fname,
            "identical content stored twice: dedup broken by the mislabeled key",
        )

    def test_migration_rekeys_without_reindexing(self):
        """Re-keying a stale digest must not re-derive the other columns.

        `_migrate` moves bytes between backends; it never changes them. So a row
        whose stored metadata is sound has exactly one column that can be
        unusable -- the checksum, when it came from another algorithm. Sending
        such a row through the full derivation to fix that would re-run `_index`
        too, which `attachment_indexation` turns into a whole PDF/OOXML parse,
        for content that did not change. On a sha1-to-BLAKE3 upgrade that is
        every row of the filestore.
        """
        payload = b"rekey-" + os.urandom(24)
        foreign = (
            hashlib.sha256(payload).hexdigest()
            if len(self.Attachment._content_checksum(payload)) != 64
            else hashlib.sha1(payload, usedforsecurity=False).hexdigest()
        )
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        att = self.Attachment.create({"name": "doc.bin", "raw": payload})
        att.flush_recordset()
        self.env.cr.execute(
            "UPDATE ir_attachment SET checksum = %s, index_content = %s WHERE id = %s",
            [foreign, "EXPENSIVE-OVERRIDE-OUTPUT", att.id],
        )
        att.invalidate_recordset()

        calls = []
        real_index = type(self.Attachment)._index

        def spy(model, bin_data, file_type, checksum=None):
            calls.append(file_type)
            return real_index(model, bin_data, file_type, checksum)

        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        with patch.object(type(self.Attachment), "_index", spy):
            self.Attachment.force_storage()
        att.invalidate_recordset()
        self.addCleanup(Path(self.filestore, att.store_fname).unlink, missing_ok=True)

        self.assertEqual(calls, [], "_index was re-run for unchanged bytes")
        self.assertEqual(
            att.index_content,
            "EXPENSIVE-OVERRIDE-OUTPUT",
            "the derived index was thrown away while re-keying",
        )
        self.assertEqual(att.checksum, self.Attachment._content_checksum(payload))
        self.assertEqual(
            att.store_fname,
            self.Attachment._file_store_path(
                self.Attachment._content_checksum(payload)
            ),
        )
        self.assertEqual(att.raw, payload)

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
        self.Attachment._gc_file_store_unsafe(
            checklist={fname: checklist[fname]}, grace=0
        )
        self.assertFalse(Path(self.filestore, fname).exists())
        self.assertFalse(marker.exists())

    def test_both_layouts_coexist_in_one_filestore(self):
        """Same bytes under both layouts: each key resolves to its own file."""
        payload = b"coexist-" + os.urandom(16)
        legacy_fname, _sha = self._legacy_key(payload)

        with self._tagged_digest_build():
            att = self.Attachment.create({"name": "coexist", "raw": payload})
            att.flush_recordset()
            self.addCleanup(
                Path(self.filestore, att.store_fname).unlink, missing_ok=True
            )
            self.assertNotEqual(
                att.store_fname, legacy_fname, "the two layouts must not collide"
            )
            self.assertEqual(self.Attachment._file_read(legacy_fname), payload)
            self.assertEqual(self.Attachment._file_read(att.store_fname), payload)

        self.assertEqual(
            self.Attachment._file_read(att.store_fname),
            payload,
            "a key written under one layout keeps reading under the other",
        )

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

    def test_legacy_key_domain_matches_shape_not_prefix(self):
        """Convergence is owed to malformed keys too, not just untagged ones.

        Selecting the rehash batch on the ``<algo>/`` prefix alone declared a
        key converged as soon as it carried the tag -- including one whose
        digest came from another algorithm, which is precisely the key that
        needs re-keying most. Matching the whole shape catches both.
        """
        payload = b"shape-" + os.urandom(16)
        good = self.Attachment.create({"name": "well-formed", "raw": payload})
        good.flush_recordset()
        self.addCleanup(Path(self.filestore, good.store_fname).unlink, missing_ok=True)
        self.assertEqual(
            good.store_fname,
            self.Attachment._file_store_path(
                self.Attachment._content_checksum(payload)
            ),
        )

        malformed = good.store_fname.rsplit("/", 1)[0] + "/" + "0" * 8
        bad = self.Attachment.create({"name": "malformed", "raw": b"other-" + payload})
        bad.flush_recordset()
        self.addCleanup(Path(self.filestore, bad.store_fname).unlink, missing_ok=True)
        self.env.cr.execute(
            "UPDATE ir_attachment SET store_fname = %s WHERE id = %s",
            [malformed, bad.id],
        )
        bad.invalidate_recordset()

        selected = (
            self.Attachment.sudo()
            .with_context(skip_res_field_check=True)
            .search(
                self.Attachment._legacy_key_domain()
                & Domain("id", "in", (good | bad).ids)
            )
        )
        self.assertEqual(
            selected.ids,
            bad.ids,
            "the domain must select the malformed key and spare the well-formed one",
        )

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
        with self._tagged_digest_build():
            self._drain_legacy_rows()
            payload = b"converge-" + os.urandom(16)
            att, old_fname = self._legacy_row(payload)
            size_before, index_before = att.file_size, att.index_content

            self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=10), (1, 0))

            att.invalidate_recordset()
            self.addCleanup(
                Path(self.filestore, att.store_fname).unlink, missing_ok=True
            )
            self.assertTrue(att.store_fname.startswith("b3/"))
            self.assertEqual(att.raw, payload, "bytes must survive the re-key")
            self.assertEqual(att.checksum, self.Attachment._content_checksum(payload))
            self.assertEqual(
                att.store_fname, self.Attachment._file_store_path(att.checksum)
            )
            self.assertEqual(att.file_size, size_before)
            self.assertEqual(att.index_content, index_before)
            self.assertTrue(Path(self.filestore, old_fname).exists())
            self.assertTrue(Path(self.filestore, "checklist", old_fname).exists())

    def test_rehash_respects_its_limit_and_is_resumable(self):
        """The batch size caps a run; the next run picks up where it stopped."""
        with self._tagged_digest_build():
            self._drain_legacy_rows()
            rows = [
                self._legacy_row(f"batch-{i}".encode() + os.urandom(8))[0]
                for i in range(3)
            ]
            self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=2), (2, 1))
            self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=2), (1, 0))
            self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=2), (0, 0))
            for att in rows:
                att.invalidate_recordset()
                self.addCleanup(
                    Path(self.filestore, att.store_fname).unlink, missing_ok=True
                )
                self.assertTrue(att.store_fname.startswith("b3/"))
                self.assertEqual(
                    att.store_fname,
                    self.Attachment._file_store_path(att.checksum),
                )

    def test_rehash_leaves_shared_legacy_content_readable(self):
        """Re-keying one of two rows sharing a key must not strand the other.

        The old key is marked for GC, and the sweep whitelists any key a row
        still references — so the sibling keeps resolving.
        """
        with self._tagged_digest_build():
            self._drain_legacy_rows()
            payload = b"shared-" + os.urandom(16)
            first, legacy_fname = self._legacy_row(payload)
            second, _ = self._legacy_row(payload)
            self.assertEqual(second.store_fname, legacy_fname)

            self.assertEqual(self.Attachment._gc_rehash_legacy_keys(limit=1)[0], 1)
            first.invalidate_recordset()
            second.invalidate_recordset()
            self.addCleanup(
                Path(self.filestore, first.store_fname).unlink, missing_ok=True
            )

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
        with self._tagged_digest_build():
            self._drain_legacy_rows()
            att, _fname = self._legacy_row(b"unreadable-" + os.urandom(16))
            with patch.object(IrAttachment, "_file_read", return_value=b""):
                self.assertEqual(
                    self.Attachment._gc_rehash_legacy_keys(limit=10),
                    (0, 0),
                    "no progress must report nothing remaining",
                )
            att.invalidate_recordset()
            self.assertFalse(att.store_fname.startswith("b3/"))

    def test_rehash_skips_other_backends_keys(self):
        """A schemed key belongs to another backend and is never re-keyed."""
        with self._tagged_digest_build():
            att = self.Attachment.create({"name": "remote", "raw": b"remote-ish"})
            self.addCleanup(
                Path(self.filestore, att.store_fname).unlink, missing_ok=True
            )
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
        self.env = self.env(user=self.user_demo)
        self.Attachments = self.env["ir.attachment"]

        record = self.Attachments.create({"name": "record1"})
        self.vals = {
            "name": "attach",
            "res_id": record.id,
            "res_model": record._name,
        }
        a = self.attachment = self.Attachments.create(self.vals)

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
        _ = self.attachment.datas
        self.rule.perm_read = True
        self.attachment.invalidate_recordset()
        with self.assertRaises(AccessError):
            _ = self.attachment.datas

        self.attachment.sudo().public = True
        _ = self.attachment.datas
        self.attachment.sudo().public = False
        with self.assertRaises(AccessError):
            _ = self.attachment.datas

        attachment_user = self.Attachments.create({"name": "foo"})
        _ = attachment_user.datas
        attachment_admin = self.Attachments.with_user(SUPERUSER_ID).create(
            {"name": "foo"}
        )
        with self.assertRaises(AccessError):
            _ = attachment_admin.with_user(self.env.user).datas
        admin_user = self.env.ref("base.user_admin")
        self.assertNotEqual(SUPERUSER_ID, admin_user.id)
        _ = attachment_admin.with_user(admin_user).datas

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_field_read_permission(self):
        """If the record field can't be read,
        e.g. `groups="base.group_system"` on the field,
        the attachment can't be read either.
        """
        skip_if_dev_mode("xml")
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

        self.patch(
            self.env.registry["res.partner"]._fields["image_128"],
            "groups",
            "base.group_system",
        )

        with self.assertRaises(AccessError):
            _ = main_partner.image_128
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
        self.assertTrue(attachment.datas)

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

        attachment.invalidate_recordset()
        with self.assertRaises(AccessError):
            _ = attachment.datas

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
        public_att = self.Attachments.sudo().create({"name": "public", "public": True})
        admin_orphan = self.Attachments.with_user(SUPERUSER_ID).create(
            {"name": "admin-orphan"}
        )
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
        unbounded = self.Attachments.search([("id", "in", ids)])
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
        all_ids = []
        for i in range(24):
            kind = i % 3
            if kind == 0:
                a = self.Attachments.sudo().create(
                    {"name": f"p{i:02d}", "public": True}
                )
            elif kind == 1:
                a = self.Attachments.create({"name": f"o{i:02d}"})
            else:
                a = self.Attachments.with_user(SUPERUSER_ID).create(
                    {"name": f"a{i:02d}"}
                )
            all_ids.append(a.id)
        domain = [("id", "in", all_ids)]
        forbidden = set(all_ids[2::3])

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

        truth = run()
        with patch("odoo.addons.base.models.ir_attachment.PREFETCH_MAX", 3):
            batched = run()

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

    def test_batch_seek_keysets_the_order_search_actually_passes(self):
        """An ``id``-led order must yield a keyset, not OFFSET (IRA-B5).

        ``search_fetch`` substitutes ``_order`` for a missing order, so
        ``_search`` sees ``'id desc'`` on every ordinary ``search()`` and the
        keyset branch — which would have chosen that very order for itself —
        was reachable only from ``search_count`` and subqueries. Every page
        then paid OFFSET's re-scan of the rows it skipped.
        """
        model = self.Attachments
        anchor = model.create({"name": "anchor"})

        for order in (model._order, "id desc", "id", "id ASC", "id desc, name"):
            with self.subTest(order=order):
                effective, keyset = model._accessible_batch_seek(order, None)
                self.assertEqual(effective, order, "an id-led order is already total")
                self.assertIsNotNone(keyset, "no keyset derived for an id-led order")
                seek = keyset(anchor)
                expected = "<" if "desc" in order else ">"
                self.assertEqual(
                    [
                        (c.field_expr, c.operator, c.value)
                        for c in seek.iter_conditions()
                    ],
                    [("id", expected, anchor.id)],
                )

        effective, keyset = model._accessible_batch_seek("name", None)
        self.assertEqual(effective, "name, id", "a caller order must be made total")
        self.assertIsNone(keyset, "an unvetted leading term must stay on OFFSET")

        for bound in (None, 50):
            _order, keyset = model._accessible_batch_seek(None, bound)
            self.assertIsNotNone(keyset, "the order-less scan must keep its keyset")

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_write_access_is_enforced_without_the_duplicate_check(self):
        """``super().write`` is the single gate on writing the attachments.

        ``write`` used to check that itself as well, re-running the whole
        comodel resolution of ``_check_access`` on every write. The checks it
        keeps cover only what that gate cannot see: the NEW ``res_model`` /
        ``res_id`` target and the NEW ``res_field``.
        """
        outsider = (
            self.env["res.users"]
            .sudo()
            .create(
                {
                    "name": "Write Outsider",
                    "login": "attachment_write_outsider",
                    "group_ids": [(6, 0, self.env.ref("base.group_user").ids)],
                }
            )
        )
        mine = self.Attachments.create({"name": "mine", "raw": b"mine"})
        self.env.flush_all()

        theirs = mine.with_user(outsider)
        theirs.invalidate_recordset()
        for vals in (
            {"name": "renamed"},
            {"raw": b"replaced"},
            {"res_model": "res.partner", "res_id": self.env.user.partner_id.id},
            {"public": True},
        ):
            with self.subTest(vals=list(vals)), self.assertRaises(AccessError):
                theirs.write(vals)
        self.assertEqual(mine.name, "mine")
        self.assertEqual(mine.raw, b"mine")

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_res_field_write_access(self):
        """A new ``res_field`` must pass the comodel field's ACL (IRA-L2).

        Otherwise a non-system user could re-point an attachment's ``res_field``
        at a field they cannot access, since the ``res_field`` Char has no
        ``groups``. The field has to be one an attachment can actually back
        (see `_check_res_field_valid`), so the vehicle is a restricted Image
        field rather than an arbitrary one.
        """
        partner = self.user_demo.partner_id
        self.patch(
            self.env.registry["res.partner"]._fields["image_1920"],
            "groups",
            "base.group_system",
        )

        with self.assertRaises(AccessError):
            self.Attachments.create(
                {
                    "name": "field-attach",
                    "res_model": "res.partner",
                    "res_id": partner.id,
                    "res_field": "image_1920",
                }
            )

        existing = self.Attachments.create(
            {
                "name": "field-attach",
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        with self.assertRaises(AccessError):
            existing.write({"res_field": "image_1920"})

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_res_model_write_retargets_res_field_and_is_gated(self):
        """Moving ``res_model`` re-targets ``res_field`` and passes its ACL.

        ``res_field`` means nothing alone: the pair says "this row IS field X of
        model Y", and a write naming only ``res_model`` moves it just as surely
        as one naming ``res_field``. Only the second was gated, so the first
        skipped the comodel field ACL entirely — a user allowed to write a
        record could hand it the content of a binary field they are NOT allowed
        to write, by re-pointing a row they had legitimately created against a
        model where the same field is open (IRA-L2).
        """
        partner = self.user_demo.partner_id
        attachment = self.Attachments.create(
            {
                "name": "avatar",
                "res_model": "res.partner",
                "res_id": partner.id,
                "res_field": "image_1920",
                "raw": b"x",
            }
        )
        self.patch(
            self.env.registry["res.users"]._fields["image_1920"],
            "groups",
            "base.group_system",
        )
        with self.assertRaises(AccessError):
            attachment.write({"res_model": "res.users", "res_id": self.env.uid})
        self.assertEqual(attachment.res_model, "res.partner")

    def _revoke_model_read(self, model_name):
        """Make *model_name* unreadable at the ACL level for the demo user."""
        self.env["ir.model.access"].sudo().search(
            [("model_id.model", "=", model_name), ("perm_read", "=", True)]
        ).write({"perm_read": False})
        self.env.flush_all()
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        self.assertFalse(
            self.env[model_name].with_user(self.user_demo).has_access("read"),
            f"{model_name} was expected to become unreadable",
        )

    def _unprefiltered(self, func):
        """Run *func* with the scan prefilter reduced to what it replaced."""
        with patch.object(
            IrAttachment,
            "_scan_prefilter",
            lambda self, sec_domain: sec_domain | Domain("res_model", "!=", False),
        ):
            return func()

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_scan_prefilter_agrees_with_the_unprefiltered_scan(self):
        """Narrowing the scan in SQL must not change one row of its answer.

        The prefilter only decides how many rows ``_check_access`` is handed;
        the post-filter stays the authority. So the whole contract is that the
        two agree, and it is asserted against the condition the prefilter
        replaced rather than against a hand-written expectation.
        """
        view = self.env["ir.ui.view"].sudo().search([], limit=1)
        self.Attachments.sudo().create(
            [
                {
                    "name": f"scan-{i}.txt",
                    "raw": f"c{i}".encode(),
                    "res_model": "ir.ui.view",
                    "res_id": view.id,
                    "public": bool(i % 3 == 0),
                }
                for i in range(9)
            ]
        )
        self.env.flush_all()
        self._revoke_model_read("ir.ui.view")

        for domain in ([], [("name", "like", "scan-")], [("public", "=", False)]):
            with self.subTest(domain=domain):
                self.assertEqual(
                    self.Attachments.search(domain).ids,
                    self._unprefiltered(
                        lambda d=domain: self.Attachments.search(d).ids
                    ),
                )
                self.assertEqual(
                    self.Attachments.search_count(domain),
                    self._unprefiltered(
                        lambda d=domain: self.Attachments.search_count(d)
                    ),
                )

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_scan_prefilter_keeps_public_rows_of_an_unreadable_model(self):
        """A public row survives its comodel being unreadable (IRA-B7).

        ``public`` short-circuits :meth:`_check_access` before the comodel is
        ever consulted, so pruning by model alone would drop rows the authority
        allows — the one way this prefilter could be too restrictive.
        """
        view = self.env["ir.ui.view"].sudo().search([], limit=1)
        public, private = self.Attachments.sudo().create(
            [
                {
                    "name": "public-on-hidden-model.txt",
                    "raw": b"visible",
                    "res_model": "ir.ui.view",
                    "res_id": view.id,
                    "public": True,
                },
                {
                    "name": "private-on-hidden-model.txt",
                    "raw": b"hidden",
                    "res_model": "ir.ui.view",
                    "res_id": view.id,
                },
            ]
        )
        self.env.flush_all()
        self._revoke_model_read("ir.ui.view")

        found = self.Attachments.search([("name", "like", "-on-hidden-model.txt")])
        self.assertEqual(found, public)
        self.assertNotIn(private, found)
        self.assertEqual(public.raw, b"visible")

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_scan_prefilter_keeps_rows_with_no_res_model(self):
        """``res_model NOT IN (...)`` must not drop the rows where it is NULL.

        SQL says ``NULL NOT IN ('x')`` is NULL, i.e. not true, so a literal
        ``NOT IN`` would silently drop every unlinked row from every scan — and
        those are precisely the rows :meth:`_check_access` hands to their
        creator. ``Domain`` compiles the ``OR res_model IS NULL`` that makes it
        safe; this pins that, since the prefilter is built on it.
        """
        mine = self.Attachments.create({"name": "mine-unlinked.txt", "raw": b"mine"})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ir_attachment SET res_model = NULL, res_id = NULL WHERE id = %s",
            [mine.id],
        )
        mine.invalidate_recordset()
        view = self.env["ir.ui.view"].sudo().search([], limit=1)
        self.Attachments.sudo().create(
            {
                "name": "on-hidden.txt",
                "raw": b"x",
                "res_model": "ir.ui.view",
                "res_id": view.id,
            }
        )
        self.env.flush_all()
        self._revoke_model_read("ir.ui.view")
        self.assertIn(
            "ir.ui.view",
            self.Attachments._attached_model_names()[0],
            "this test needs the unreadable model to be discovered",
        )

        found = self.Attachments.search([("name", "like", "-unlinked.txt")])
        self.assertEqual(found, mine)
        self.assertEqual(
            found.ids,
            self._unprefiltered(
                lambda: self.Attachments.search([("name", "like", "-unlinked.txt")]).ids
            ),
        )

    def test_scan_prefilter_declines_past_the_discovery_cap(self):
        """Too many distinct models and nothing is narrowed at all."""
        sec_domain = Domain("public", "=", True)
        with patch.object(
            IrAttachment,
            "_attached_model_names",
            lambda self: (["res.partner"], True),
        ):
            self.assertEqual(
                self.Attachments._scan_prefilter(sec_domain),
                sec_domain | Domain("res_model", "!=", False),
            )

    def test_res_field_cannot_outlive_its_res_model(self):
        """Clearing ``res_model`` while ``res_field`` stays is refused, clearly.

        The pair carries the meaning; a ``res_field`` alone names a field of
        nothing, and no reader can resolve the row. Refused for the superuser
        too — it is the data-model invariant, not a permission — and as a
        ``ValidationError``, since "this pair makes no sense" is not an access
        answer.
        """
        backed = self.Attachments.create(
            {
                "name": "avatar",
                "res_model": "res.partner",
                "res_id": self.user_demo.partner_id.id,
                "res_field": "image_1920",
                "raw": b"x",
            }
        )
        for records in (backed, backed.sudo()):
            with self.subTest(su=records.env.su), self.assertRaises(ValidationError):
                records.write({"res_model": False})
        self.assertEqual(backed.res_model, "res.partner")

        with self.assertRaises(ValidationError):
            self.Attachments.sudo().create(
                {"name": "orphan", "res_field": "image_1920", "raw": b"x"}
            )

        backed.write({"res_model": False, "res_field": False})
        self.assertFalse(backed.res_model)
        self.assertFalse(backed.res_field)

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_a_non_string_res_model_is_refused_not_crashed_on(self):
        """A client-supplied ``res_model`` must never 500 out of an access gate.

        The value reaches ``create``/``write`` unconverted and is used as a dict
        key and a registry lookup, so a list raised ``TypeError: cannot use
        'list' as a dict key`` from inside the comodel access check — a 500
        where the answer is "that is not a model".
        """
        partner = self.user_demo.partner_id
        for res_model in ([], ["res.partner"], {"a": 1}, 42, 0.5):
            with self.subTest(res_model=res_model):
                try:
                    self.Attachments.create(
                        {"name": "odd", "res_model": res_model, "res_id": partner.id}
                    )
                except (AccessError, ValidationError, ValueError, TypeError) as exc:
                    self.assertNotIsInstance(
                        exc, TypeError, "the access check crashed on client input"
                    )

        row = self.Attachments.create({"name": "plain", "raw": b"x"})
        for res_model in ([], ["res.partner"], 42):
            with (
                self.subTest(write=res_model),
                contextlib.suppress(AccessError, ValidationError, ValueError),
            ):
                row.write({"res_model": res_model})

    def test_res_field_targets_cover_every_way_the_pair_moves(self):
        """Every write that moves either half of the pair is checked, once each.

        The enumeration is what the gate sees, so it is pinned directly: the
        ``res_model``-only case is the one that used to yield nothing at all,
        and both halves of :meth:`_check_res_field_access` — the data-model
        invariant and the field ACL — were skipped with it. Rows with no
        ``res_field`` still yield a falsy pair, which the check returns on, so
        an ordinary re-parenting write stays free.
        """
        partner = self.user_demo.partner_id
        backed = self.Attachments.create(
            {
                "name": "avatar",
                "res_model": "res.partner",
                "res_id": partner.id,
                "res_field": "image_1920",
                "raw": b"x",
            }
        )
        self.assertEqual(
            set(backed._res_field_targets({"res_model": "res.users"})),
            {("res.users", "image_1920")},
        )
        self.assertEqual(
            set(backed._res_field_targets({"res_field": "avatar_128"})),
            {("res.partner", "avatar_128")},
        )
        self.assertEqual(
            set(
                backed._res_field_targets(
                    {"res_model": "res.users", "res_field": "avatar_128"}
                )
            ),
            {("res.users", "avatar_128")},
        )
        self.assertEqual(backed._res_field_targets({"name": "x"}), OrderedSet())
        self.assertEqual(
            set(self.attachment._res_field_targets({"res_model": "res.users"})),
            {("res.users", False)},
            "a row with no res_field must yield a pair the check returns on",
        )

    def test_derive_mode_reproduces_the_buffered_create(self):
        """The streaming upload path must produce the row ``create`` produced.

        ``/mail/attachment/upload`` and ``/web/binary/upload_attachment`` used
        to hold the whole file in the worker (``create({"raw": ufile.read()})``)
        because none of ``_from_request_file``'s modes typed a row the way
        ``create`` does: ``TRUST`` believes the client's Content-Type and
        ``GUESS`` renames the file. ``DERIVE`` is that missing mode, so the
        switch is a memory change and nothing else — asserted field by field,
        including the ones that are only right if the same bytes were stored.
        """

        class _FakeFile:
            def __init__(self, content, filename):
                self._buf = io.BytesIO(content)
                self.filename = filename
                self.content_type = "application/octet-stream"

            def read(self, size=-1):
                return self._buf.read(size)

            def seek(self, offset, whence=0):
                return self._buf.seek(offset, whence)

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        for filename, content in (
            ("report.csv", b"a,b,c\n1,2,3\n"),
            ("sheet.xlsx", b"PK\x03\x04" + b"\x00" * 60),
            ("noext", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + b"x" * 100),
            ("photo.png", png),
            ("plain.txt", b"hello world"),
        ):
            with self.subTest(filename=filename):
                buffered = self.Attachments.create({"name": filename, "raw": content})
                streamed = self.Attachments._from_request_file(
                    _FakeFile(content, filename)
                )
                for field in ("name", "mimetype", "file_size", "checksum", "raw"):
                    self.assertEqual(
                        streamed[field],
                        buffered[field],
                        f"{field} differs between the two upload paths",
                    )

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

        explicit = self.Attachments._from_request_file(
            _FakeFile(b"hello", "application/octet-stream", "note.txt"),
            mimetype="text/plain",
        )
        self.assertEqual(explicit.mimetype, "text/plain")

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        guessed = self.Attachments._from_request_file(
            _FakeFile(png, "application/octet-stream", "img"),
            mimetype="GUESS",
        )
        self.assertEqual(guessed.mimetype, "image/png")

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
        unwritable = self.env["res.users.apikeys.description"].create(
            {"name": "Unwritable"}
        )
        with self.assertRaises(AccessError):
            unwritable.write({})
        writable = self.Attachments.create({"name": "yes"})
        writable.name = "canwrite"

        copied = self.attachment.copy(
            {"res_model": writable._name, "res_id": writable.id}
        )
        copied.copy()
        with self.assertRaises(AccessError):
            copied.copy({"res_id": self.vals["res_id"]})

        with self.assertRaises(AccessError):
            self.attachment.copy(
                {"res_model": unwritable._name, "res_id": unwritable.id}
            )
        with self.assertRaises(AccessError):
            copied.copy({"res_model": unwritable._name, "res_id": unwritable.id})

    def test_write_error(self):
        """An unwritable target propagates its OSError out of ``_file_write``.

        The stub returns what the real ``_get_path`` returns — a ``str`` store
        key and its absolute path. It used to hand back the payload ``bytes``
        as the key, which only went unnoticed because nothing touched the key
        before the write failed; ``_file_write`` now marks it for collection
        first (IRA-G2), and a bytes key raises a ``TypeError`` there instead.
        """
        key = "te/test_write_error"
        self.patch(
            IrAttachment,
            "_get_path",
            lambda self, _binary, _checksum: (key, "/proc/dummy_test"),
        )
        self.addCleanup(
            (self.Attachments._filestore_dir("checklist") / key).unlink, True
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

    def test_res_id_without_res_model_stays_owner_only(self):
        """An attachment carrying ``res_id`` but no ``res_model`` is unlinked.

        ``_check_access`` used to read that state as "linked to a record" and
        skip the creator check, while ``res_model and res_id`` then skipped the
        comodel check too — so the row fell through every branch and any
        internal user could read, write and delete it. ``res_id`` is
        caller-supplied at create time, so the state is trivially reachable.
        """
        other_user = (
            self.env["res.users"]
            .sudo()
            .create(
                {
                    "name": "Attachment Outsider",
                    "login": "attachment_outsider",
                    "group_ids": [(6, 0, self.env.ref("base.group_user").ids)],
                }
            )
        )
        orphan = self.Attachments.create(
            {"name": "orphan", "raw": b"owner-only", "res_id": 1}
        )
        self.env.flush_all()
        self.assertFalse(orphan.sudo().res_model)

        outsider_view = orphan.with_user(other_user)
        outsider_view.invalidate_recordset()
        with self.assertRaises(AccessError):
            _ = outsider_view.raw
        with self.assertRaises(AccessError):
            outsider_view.write({"name": "taken over"})
        with self.assertRaises(AccessError):
            outsider_view.unlink()

        self.assertEqual(orphan.raw, b"owner-only", "the creator kept access")
        self.assertIn(
            orphan,
            self.Attachments.search([("name", "=", "orphan")]),
            "_search and _check_access disagree on what counts as unlinked",
        )
        self.assertNotIn(
            orphan,
            self.Attachments.with_user(other_user).search([("name", "=", "orphan")]),
            "an outsider found the attachment through search",
        )

    def _rule_free_comodel(self):
        """Return a model whose ``_search`` produces no WHERE for this user.

        That is the shape the per-comodel subdomain used to treat as
        unrestricted, and it is the common one: master data usually carries no
        record rule at all.
        """
        for name in ("res.country", "res.country.state", "res.groups"):
            comodel = self.env.get(name)
            if comodel is not None and not comodel._search(Domain.TRUE).where_clause:
                return comodel
        self.skipTest("no rule-free readable comodel available")
        return None

    def test_search_by_model_excludes_unlinked_rows_of_others(self):
        """The ≤5-model search path must not out-run ``_check_access`` (IRA-B6).

        With no record rule and no ``res_id`` condition, the comodel subquery
        restricts nothing, and the ``res_id IN (subquery)`` clause used to be
        dropped as a tautology. It is not one: it also excludes NULL and ``0``,
        and those rows are the unlinked ones ``_check_access`` reserves for
        their creator. Dropping it let any user read another's
        ``res_model``-set, ``res_id``-less attachment — content included — on
        the path that has no post-filter to catch it.
        """
        comodel = self._rule_free_comodel()
        real_id = comodel.search([], limit=1).id
        rows = {
            label: self.Attachments.with_user(SUPERUSER_ID).create(
                {
                    "name": f"secret-{label}",
                    "res_model": comodel._name,
                    "res_id": res_id,
                    "raw": f"payload {label}".encode(),
                }
            )
            for label, res_id in (
                ("false", False),
                ("zero", 0),
                ("real", real_id),
            )
        }
        self.env.flush_all()

        by_model = self.Attachments.search([("res_model", "=", comodel._name)])
        broad = self.Attachments.search([("id", "in", [r.id for r in rows.values()])])
        for label, row in rows.items():
            reachable = row.with_user(self.env.user).has_access("read")
            self.assertEqual(
                row.id in by_model.ids,
                reachable,
                f"{label}: the per-model search path disagrees with _check_access",
            )
            self.assertEqual(
                row.id in broad.ids,
                reachable,
                f"{label}: the two search paths disagree with each other",
            )
        self.assertFalse(
            rows["false"].with_user(self.env.user).has_access("read"),
            "the unlinked row must stay owner-only, or this test proves nothing",
        )

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_search_by_unreadable_model_is_empty_not_an_error(self):
        """An unreachable comodel contributes nothing; it does not raise.

        ``comodel._search`` raises for a model the user cannot read, so
        searching one's own attachments by ``res_model`` failed with an
        ``AccessError`` naming an unrelated model — while the same search
        spanning six models quietly returned nothing for it, and
        ``_check_access`` simply treats those attachments as forbidden.
        """
        forbidden = next(
            (
                name
                for name in ("ir.model", "decimal.precision", "ir.config_parameter")
                if not self.env[name].browse().has_access("read")
            ),
            None,
        )
        if forbidden is None:
            self.skipTest("no readable-model-free candidate available")

        self.assertEqual(
            self.Attachments.search([("res_model", "=", forbidden)]).ids, []
        )
        self.assertEqual(
            self.Attachments.search_count([("res_model", "=", forbidden)]), 0
        )

        mine = self.Attachments.create(
            {"name": "mine", "res_model": forbidden, "res_id": False}
        )
        self.env.flush_all()
        self.assertIn(
            mine.id,
            self.Attachments.search([("res_model", "=", forbidden)]).ids,
            "an own unlinked row stays reachable even under an unreadable model",
        )


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
        self.assertEqual(attachment.raw, b"")
        self.assertTrue(attachment.file_size)

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

    def test_content_comparison_helpers_agree(self):
        payload = b"compare-me" * 9
        checksum = self.Attachment._content_checksum(payload)
        path = self.Attachment._full_path(
            self.Attachment._file_write(payload, checksum)
        )

        self.assertTrue(self.Attachment._same_content(payload, path))
        self.assertFalse(self.Attachment._same_content(payload + b"!", path))
        self.assertFalse(self.Attachment._same_content(b"Z" * len(payload), path))
        self.assertTrue(self.Attachment._same_content_files(path, path))

        other = b"different" * 9
        other_path = self.Attachment._full_path(
            self.Attachment._file_write(other, self.Attachment._content_checksum(other))
        )
        self.assertFalse(self.Attachment._same_content_files(path, other_path))

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

        Rows holding a store key AND inline bytes exist — a half-finished
        migration, a restore, or any of the writes that produced them back when
        ``db_datas`` reached the column untouched. If one reader preferred the
        inline copy it would serve different content than the other two —
        silently, and only for such rows.

        The decoy goes in by SQL because the API no longer writes that state:
        ``db_datas`` is content now, so assigning it REPLACES the keyed copy
        rather than shadowing it (IRA-R2). The shape under test outlives the way
        it used to be produced.
        """
        payload = b"the-real-content" * 5
        attachment = self.Attachment.create({"name": "both.bin", "raw": payload})
        self.env.flush_all()
        self.assertTrue(attachment.store_fname)

        self.env.cr.execute(
            "UPDATE ir_attachment SET db_datas = %s WHERE id = %s",
            [b"decoy-inline-content", attachment.id],
        )
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


class TestBinSizeIsNeverContent(TransactionCaseWithUserDemo):
    """``bin_size`` is a presentation mode; no content path may observe it.

    Under it every binary field reads back as a human size string
    (``b"4.90 Kb"``) instead of its payload, and nothing downstream can tell
    that from a legitimately tiny file. Each test here drives one content path
    from a ``bin_size`` context and asserts the bytes survive (IRA-Z1).
    """

    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.payload = b"REAL-CONTENT-" + b"z" * 5000

    def _sized(self, records):
        return records.with_context(bin_size=True)

    def _reread(self, record):
        self.env.flush_all()
        self.env.invalidate_all()
        return self.Attachment.browse(record.id)

    def test_bin_size_really_hides_the_payload(self):
        """The premise: without neutralization a binary field is a size string."""
        attachment = self.Attachment.create({"name": "p.bin", "raw": self.payload})
        attachment = self._reread(attachment)
        self.assertEqual(
            self._sized(attachment).raw,
            human_size(len(self.payload)).encode(),
            "bin_size no longer substitutes the size; these tests need a new premise",
        )

    def test_content_write_under_bin_size_keeps_the_bytes(self):
        """A content ``write`` used to BLANK the row.

        The inverse reads ``raw`` back to store it, and the ORM caches the
        assigned value with ``bin_size`` stripped — so reading it in the
        caller's ``bin_size`` env missed the cache entirely and the row was
        rewritten with ``b""``: no ``store_fname``, ``file_size = 0``, and the
        previous content left for the GC.
        """
        for key, value in (
            ("raw", self.payload),
            ("datas", base64.b64encode(self.payload)),
        ):
            with self.subTest(key=key):
                attachment = self.Attachment.create(
                    {"name": f"w-{key}.bin", "raw": b"initial"}
                )
                attachment = self._reread(attachment)
                self._sized(attachment).write({key: value})
                attachment = self._reread(attachment)
                self.assertEqual(attachment.raw, self.payload)
                self.assertEqual(attachment.file_size, len(self.payload))

    def test_copy_under_bin_size_keeps_the_bytes(self):
        """``copy`` stored ``b"4.90 Kb"`` as the copy's content.

        Only db-stored rows were hit: a filestore-backed copy shares its
        origin's key and never round-trips the payload.
        """
        for location in ("db", "file"):
            with self.subTest(location=location):
                self.env["ir.config_parameter"].set_param(
                    "ir_attachment.location", location
                )
                origin = self.Attachment.create(
                    {"name": f"c-{location}.bin", "raw": self.payload}
                )
                origin = self._reread(origin)
                copied = self._reread(self._sized(origin).copy())
                self.assertEqual(copied.raw, self.payload)
                self.assertEqual(copied.file_size, len(self.payload))

    def test_force_storage_under_bin_size_keeps_the_bytes(self):
        """The worst case: a whole-table sweep rewriting every row it moves.

        ``_migrate``'s own guard cannot catch it — it compares ``file_size``
        against the content it just read, disagrees, and "repairs" the row by
        re-deriving every column from the size string.
        """
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        attachment = self.Attachment.create({"name": "m.bin", "raw": self.payload})
        attachment = self._reread(attachment)
        self.assertFalse(attachment.store_fname)

        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        self.Attachment.with_context(bin_size=True).force_storage()

        attachment = self._reread(attachment)
        self.assertTrue(attachment.store_fname)
        self.assertEqual(attachment.raw, self.payload)
        self.assertEqual(attachment.file_size, len(self.payload))

    def test_pdf_raw_under_bin_size_keeps_the_bytes(self):
        """``_get_pdf_raw`` fed the size string to every PDF consumer."""
        pdf = b"%PDF-1.4\n" + b"x" * 3000
        attachment = self.Attachment.create(
            {"name": "d.pdf", "raw": pdf, "mimetype": "application/pdf"}
        )
        attachment = self._reread(attachment)
        self.assertEqual(self._sized(attachment)._get_pdf_raw(), pdf)

    def test_per_field_bin_size_is_neutralized_too(self):
        """``bin_size_raw`` is a second, independent axis and must also be cleared.

        ``Binary.compute_value`` reads it straight from the context, so a reader
        that clears only the global ``bin_size`` still gets the size string.
        """
        attachment = self.Attachment.create({"name": "pf.bin", "raw": self.payload})
        attachment = self._reread(attachment)
        scoped = attachment.with_context(bin_size_raw=True, bin_size_db_datas=True)
        self.assertEqual(scoped._stored_content(), self.payload)
        self.assertEqual(scoped._read_prefix(), self.payload)
        self.assertEqual(scoped._unsized().raw, self.payload)

        scoped.write({"raw": b"replacement-payload"})
        self.assertEqual(self._reread(attachment).raw, b"replacement-payload")

    def test_per_field_bin_size_does_not_poison_plain_readers(self):
        """A ``bin_size_<field>`` read must not answer a caller who asked for none.

        ``Binary`` honours ``bin_size_<name>`` in ``read``/``compute_value`` but
        declared only the global ``bin_size`` in its cache key, so both contexts
        shared ONE entry: a single read under ``bin_size_raw`` wrote
        ``b"1.96 Kb"`` into the entry every plain reader uses, and
        ``record.raw`` then returned it to a caller with no ``bin_size`` in
        context at all. Fixed in ``Binary.get_depends``; this pins it from the
        model whose content the confusion corrupted.
        """
        attachment = self.Attachment.create({"name": "poison.bin", "raw": self.payload})
        attachment = self._reread(attachment)

        sized = attachment.with_context(bin_size_raw=True).raw
        self.assertEqual(sized, human_size(len(self.payload)).encode())
        self.assertEqual(
            self.Attachment.browse(attachment.id).raw,
            self.payload,
            "a bin_size_<field> read answered a caller that never asked for it",
        )

    def test_per_field_flags_shorten_only_their_own_field(self):
        """``bin_size_raw`` must shorten ``raw`` and nothing else.

        ``datas`` is computed FROM ``raw``, and its own ``bin_size`` short
        circuit does not fire for a flag naming a different field — so
        ``bin_size_raw`` alone reached ``_compute_datas``, which encoded the
        size string: ``datas`` came back as the base64 of ``b"1.97 Kb"``. That
        decodes cleanly, so a caller gets a well-formed 7-byte file rather than
        an error.
        """
        attachment = self.Attachment.create({"name": "ind.bin", "raw": self.payload})
        attachment = self._reread(attachment)
        size = human_size(len(self.payload)).encode()

        raw_only = attachment.with_context(bin_size_raw=True)
        self.assertEqual(raw_only.raw, size)
        self.assertEqual(
            base64.b64decode(raw_only.datas),
            self.payload,
            "bin_size_raw shortened datas as well",
        )

        self.env.invalidate_all()
        datas_only = self.Attachment.browse(attachment.id).with_context(
            bin_size_datas=True
        )
        self.assertEqual(datas_only.datas, size)
        self.assertEqual(
            datas_only.raw, self.payload, "bin_size_datas shortened raw as well"
        )

    def test_attachment_backed_host_field_ignores_the_storage_flags(self):
        """``bin_size_datas`` names ir.attachment's field, not the host's.

        An attachment-backed binary field is read out of ``ir.attachment``
        rows, and ``Binary.read`` used to read them under whatever context the
        host carried. ``bin_size_datas`` — scoped to a field on a model the
        caller never mentioned — therefore made ``res.partner.image_1920``
        return ``b"70.00 bytes"``, and that value lands in the entry keyed by
        ``bin_size``/``bin_size_image_1920``, neither of which is set: every
        later plain reader in the transaction is served the size string too.
        Same cross-field poisoning ``Binary.get_depends`` fixed for one field,
        arriving through the storage model instead.
        """
        image = image_to_base64(Image.new("RGB", (4, 4)), "PNG")
        partner = self.env["res.partner"].create({"name": "host", "image_1920": image})
        self.env.flush_all()

        for flag in ("bin_size_datas", "bin_size_raw", "bin_size_db_datas"):
            with self.subTest(flag=flag):
                self.env.invalidate_all()
                scoped = self.env["res.partner"].browse(partner.id)
                self.assertTrue(
                    scoped.with_context(**{flag: True}).image_1920.startswith(b"iVBOR"),
                    f"{flag} shortened a field it does not name",
                )
                self.assertTrue(
                    self.env["res.partner"]
                    .browse(partner.id)
                    .image_1920.startswith(b"iVBOR"),
                    f"a {flag} read answered a caller that never asked for it",
                )

    def test_attachment_backed_host_field_honours_its_own_flag(self):
        """``bin_size_<name>`` must shorten the field it names, wherever it lives.

        ``_fetch_query`` honours it for a column-stored binary field and
        ``Binary.compute_value`` for a computed one; ``Binary.read`` — the
        attachment-backed leg — ignored it, so the same flag shortened two of
        the three storage shapes and silently did nothing to the third, while
        ``get_depends`` still spent a separate cache entry on it.
        """
        image = image_to_base64(Image.new("RGB", (4, 4)), "PNG")
        partner = self.env["res.partner"].create({"name": "host", "image_1920": image})
        self.env.flush_all()
        self.env.invalidate_all()

        scoped = self.env["res.partner"].browse(partner.id)
        self.assertEqual(
            scoped.with_context(bin_size_image_1920=True).image_1920,
            scoped.with_context(bin_size=True).image_1920,
        )
        self.assertTrue(
            self.env["res.partner"].browse(partner.id).image_1920.startswith(b"iVBOR")
        )

    def test_unsized_is_a_no_op_without_bin_size(self):
        """The common path must not allocate a new environment per call."""
        attachment = self.Attachment.create({"name": "n.bin", "raw": b"x"})
        self.assertIs(attachment._unsized(), attachment)
        self.assertIsNot(self._sized(attachment)._unsized(), self._sized(attachment))


class TestDedupOwnership(TransactionCaseWithUserDemo):
    """``create_unique`` may only reuse rows that stand on their own (IRA-C4)."""

    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.payload = b"SHARED-DEDUP-PAYLOAD"
        self.partner = self.env["res.partner"].create({"name": "dedup host"})

    def _field_row(self):
        row = self.Attachment.sudo().create(
            {
                "name": "image_1920",
                "res_model": "res.partner",
                "res_field": "image_1920",
                "res_id": self.partner.id,
                "type": "binary",
                "raw": self.payload,
                "mimetype": "image/png",
            }
        )
        self.env.flush_all()
        return row

    def _create_unique(self):
        return self.Attachment.create_unique(
            [
                {
                    "name": "mine.png",
                    "datas": base64.b64encode(self.payload),
                    "mimetype": "image/png",
                }
            ]
        )

    def test_create_unique_never_reuses_a_field_backing_row(self):
        """A ``res_field`` row is field X of record Y, not a shareable blob.

        Reusing one handed the caller a reference the ORM rewrites on the next
        write of that field and deletes with its host record.
        """
        field_row = self._field_row()
        [reused] = self._create_unique()
        self.assertNotEqual(
            reused,
            field_row.id,
            "create_unique reused an attachment owned by another record's field",
        )
        self.assertFalse(self.Attachment.browse(reused).res_field)
        self.assertEqual(self.Attachment.browse(reused).raw, self.payload)

    def test_a_res_field_value_never_reuses_anything(self):
        """Asking for "field X of record Y" must produce that row, not a match.

        The exclusion ran on the match SET only, so a value carrying
        ``res_field`` still matched a free-standing row and was handed its id:
        the caller asked to back a field and got an unrelated attachment, the
        field stayed unbacked, and nothing said so.
        """
        free = self.Attachment.create(
            {"name": "free.png", "raw": self.payload, "mimetype": "image/png"}
        )
        self.env.flush_all()

        [created] = self.Attachment.sudo().create_unique(
            [
                {
                    "name": "image_1920",
                    "raw": self.payload,
                    "mimetype": "image/png",
                    "res_model": "res.partner",
                    "res_field": "image_1920",
                    "res_id": self.partner.id,
                }
            ]
        )
        self.assertNotEqual(created, free.id, "a res_field value reused another row")
        backing = self.Attachment.with_context(skip_res_field_check=True).browse(
            created
        )
        self.assertEqual(backing.res_field, "image_1920")
        self.assertEqual(backing.res_id, self.partner.id)

    def test_a_res_field_value_is_never_reused_within_its_own_batch(self):
        """The same guard from the other end: it must not seed the batch's keys.

        A ``res_field`` value registering the content key first handed the NEXT,
        free-standing value a field-backing id — the exact reference IRA-C4
        forbids, produced inside one call rather than found in the table.
        """
        [backed, standalone] = self.Attachment.sudo().create_unique(
            [
                {
                    "name": "image_1920",
                    "raw": self.payload,
                    "mimetype": "image/png",
                    "res_model": "res.partner",
                    "res_field": "image_1920",
                    "res_id": self.partner.id,
                },
                {
                    "name": "standalone.png",
                    "raw": self.payload,
                    "mimetype": "image/png",
                },
            ]
        )
        self.assertNotEqual(backed, standalone)
        self.assertFalse(self.Attachment.browse(standalone).res_field)
        self.assertEqual(self.Attachment.browse(standalone).raw, self.payload)

    def test_reused_row_survives_its_lookalike_host(self):
        """The consequence the exclusion prevents: content swap and deletion."""
        field_row = self._field_row()
        [reused] = self._create_unique()
        self.env.flush_all()

        self.partner.unlink()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertFalse(
            field_row.sudo().with_context(skip_res_field_check=True).exists(),
            "the host record must still own its field attachment",
        )
        self.assertTrue(
            self.Attachment.browse(reused).exists(),
            "deleting an unrelated record deleted the caller's attachment",
        )
        self.assertEqual(self.Attachment.browse(reused).raw, self.payload)

    def test_create_unique_still_dedups_free_standing_rows(self):
        """The exclusion must not disable dedup for ordinary rows."""
        free = self.Attachment.create(
            {"name": "free.png", "raw": self.payload, "mimetype": "image/png"}
        )
        self.env.flush_all()
        self.assertEqual(self._create_unique(), [free.id])


class TestGcChecklistAddressing(TransactionCaseWithUserDemo):
    """The GC must unlink the file it asked the database about (IRA-G2, IRA-G3)."""

    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.checklist = self.Attachment._filestore_dir("checklist")

    def test_a_stray_marker_never_unlinks_an_unrelated_file(self):
        """A checklist name the sanitizer rewrites addresses two files.

        The whitelist query used the name as found, the unlink used its
        sanitized form — so a stray ``ab/cd.ef`` marker (an editor swap file, an
        NFS silly-rename) made the sweep delete ``ab/cdef``, which no marker
        ever named and which may be live content.
        """
        live = self.Attachment.create({"name": "live.bin", "raw": b"live-content"})
        self.env.flush_all()
        victim = Path(self.Attachment._full_path(live.store_fname))
        self.assertTrue(victim.is_file())

        shard, _, digest = live.store_fname.rpartition("/")
        stray = self.checklist / shard / f"{digest[:-2]}.{digest[-2:]}"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(b"")
        self.addCleanup(stray.unlink, True)
        self.assertNotEqual(
            self.Attachment._sanitize_store_path(
                str(stray.relative_to(self.checklist))
            ),
            str(stray.relative_to(self.checklist)),
            "this test needs a name the sanitizer rewrites",
        )

        self.Attachment._gc_file_store_unsafe(
            self.Attachment._gc_checklist(grace=0), grace=0
        )

        self.assertTrue(
            victim.is_file(),
            "the sweep unlinked a file no checklist entry named",
        )
        self.assertEqual(live.raw, b"live-content")

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_a_refused_store_key_does_not_stop_the_sweep(self):
        """One un-addressable marker must not disable the GC for good.

        ``_full_path`` refuses a key whose shard resolves out of the filestore —
        that refusal is the point of the ``resolve()`` there. Raising it out of
        the sweep turned the confinement check into a denial of the GC: the run
        aborts, every later marker in the walk is left, the autovacuum rolls
        back, and the next run stops in the same place. The marker is dropped
        instead: a key the filestore refuses addresses neither a file nor a live
        ``store_fname``, so keeping it reclaims nothing and pins it against
        ``_GC_MAX_ENTRIES`` forever.
        """
        live = self.Attachment.create({"name": "live.bin", "raw": b"survivor"})
        self.env.flush_all()
        victim = Path(self.Attachment._full_path(live.store_fname))
        self.assertTrue(victim.is_file())

        filestore = Path(self.Attachment._filestore())
        outside = filestore.parent / "ira_outside_the_filestore"
        outside.mkdir(parents=True, exist_ok=True)
        self.addCleanup(outside.rmdir)
        escaping_shard = filestore / "zz"
        escaping_shard.symlink_to(outside)
        self.addCleanup(escaping_shard.unlink)

        refused = "zz/" + "a" * 40
        with self.assertRaises(ValueError):
            self.Attachment._full_path(refused)
        marker = self.checklist / refused
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(b"")
        self.addCleanup(marker.unlink, True)

        collectable = self.Attachment.create({"name": "gone.bin", "raw": b"collect-me"})
        self.env.flush_all()
        orphan = Path(self.Attachment._full_path(collectable.store_fname))
        orphan_key = collectable.store_fname
        collectable.unlink()
        self.env.flush_all()

        # explicit order: the refused entry has to be swept BEFORE the
        # collectable one for the abort to be observable at all
        self.Attachment._gc_file_store_unsafe(
            {refused: marker, orphan_key: self.checklist / orphan_key}, grace=0
        )

        self.assertFalse(marker.is_file(), "the refused marker was left to recur")
        self.assertFalse(
            orphan.is_file(),
            "a refused entry stopped the sweep before the collectable ones",
        )
        self.assertFalse((self.checklist / orphan_key).is_file())
        self.assertTrue(victim.is_file())
        self.assertEqual(live.raw, b"survivor")

    def test_content_is_marked_before_it_is_published(self):
        """A crash between publishing and marking leaks content forever.

        The sweep walks the checklist, not the filestore, so an unmarked file
        whose row rolled back is unreachable to every later GC run.
        """
        payload = b"marked-before-published"
        checksum = self.Attachment._content_checksum(payload)
        fname = self.Attachment._file_store_path(checksum)
        marker = self.checklist / fname
        marker.unlink(missing_ok=True)
        Path(self.Attachment._full_path(fname)).unlink(missing_ok=True)

        published = []
        original = Path.replace

        def spy(self, target):
            published.append(marker.exists())
            return original(self, target)

        self.patch(Path, "replace", spy)
        self.Attachment._file_write(payload, checksum)

        self.assertEqual(
            published,
            [True],
            "the content was published before its GC marker existed",
        )

    def test_streamed_content_is_marked_before_it_is_published(self):
        """Same ordering for the streaming writer."""
        payload = b"streamed-marked-before-published"
        checksum = self.Attachment._content_checksum(payload)
        fname = self.Attachment._file_store_path(checksum)
        marker = self.checklist / fname
        marker.unlink(missing_ok=True)
        Path(self.Attachment._full_path(fname)).unlink(missing_ok=True)

        published = []
        original = Path.replace

        def spy(self, target):
            published.append(marker.exists())
            return original(self, target)

        self.patch(Path, "replace", spy)
        self.Attachment._file_write_stream(io.BytesIO(payload))

        self.assertEqual(published, [True])


class TestAccessibleIdScanFootprint(TransactionCaseWithUserDemo):
    """The batched access scan must cost O(batch) memory, not O(table) (P2-9)."""

    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.user = (
            self.env["res.users"]
            .sudo()
            .create(
                {
                    "name": "Scan User",
                    "login": "scan_user",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )
        partner = self.env["res.partner"].create({"name": "scan host"})
        rows = 3 * PREFETCH_MAX + 17
        self.env.cr.execute(
            """
            INSERT INTO ir_attachment
                (name, type, res_model, res_id, public, create_uid, write_uid,
                 create_date, write_date, file_size, company_id)
            SELECT 'scan-' || g, 'binary', 'res.partner', %s, false, 1, 1,
                   now(), now(), 0, %s
            FROM generate_series(1, %s) g
            """,
            [partner.id, self.env.company.id, rows],
        )
        self.env.invalidate_all()
        self.expected = rows

    def _cached_security_rows(self):
        model = self.Attachment.with_user(self.user)
        return max(
            len(self.env.cache.get_records(model, model._fields[name]))
            for name in SECURITY_FIELDS
        )

    def test_unbounded_scan_keeps_only_one_batch_cached(self):
        """``search_count`` is the caller that never passes a bound.

        Batching bounded the query but not the cache, so every row ever
        examined stayed resident: 23 MB of ``SECURITY_FIELDS`` to produce one
        integer over 50k rows.
        """
        scanned = self.Attachment.with_user(self.user)
        self.assertGreaterEqual(scanned.search_count([]), self.expected)
        self.assertLessEqual(
            self._cached_security_rows(),
            PREFETCH_MAX,
            "the access scan kept more than one batch of security fields cached",
        )

    def test_scan_still_agrees_with_the_authority(self):
        """Invalidating a batch must not change which ids it reported."""
        scanned = self.Attachment.with_user(self.user)
        found = scanned.search([("name", "=like", "scan-%")], order="id")
        self.env.invalidate_all()
        expected = (
            self.Attachment.sudo()
            .search([("name", "=like", "scan-%")], order="id")
            .with_user(self.user)
            ._filtered_access("read")
        )
        self.assertEqual(found.ids, expected.ids)

    def test_deep_paging_agrees_with_a_full_ordered_scan(self):
        """Keyset batches must not skip or repeat a row across a boundary."""
        scanned = self.Attachment.with_user(self.user)
        domain = [("name", "=like", "scan-%")]
        for order in ("id", "id desc"):
            with self.subTest(order=order):
                whole = scanned.search(domain, order=order).ids
                paged = []
                page = PREFETCH_MAX + 3
                for offset in range(0, len(whole), page):
                    paged.extend(
                        scanned.search(
                            domain, order=order, limit=page, offset=offset
                        ).ids
                    )
                self.assertEqual(paged, whole)
