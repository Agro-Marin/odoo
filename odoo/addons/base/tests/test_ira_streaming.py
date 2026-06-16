"""Tests for ir.attachment streaming uploads (C4).

Uploads of non-transformed binaries are streamed to the filestore in bounded
chunks instead of buffered whole via ``file.read()``. These tests pin:

- the filestore streaming primitive (`_file_write_stream`): round-trip,
  chunked reads (never one unbounded read), content-addressed dedup, empty;
- the stream/buffer decision (`_should_stream_upload`);
- `_from_request_file` end to end: non-image binaries and text stream;
  autoresize-eligible images still buffer and resize; `image_no_postprocess`
  images stream untouched; db storage buffers; identical content dedups.
"""

import hashlib
import io
import os
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import FileStorage

from odoo.tests.common import TransactionCase

from odoo.addons.base.models.ir_attachment import IrAttachment


class _ReadSpy:
    """Minimal binary file-like that records the size of each read()."""

    def __init__(self, data):
        self._buf = io.BytesIO(data)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self._buf.read(size)

    def seek(self, *args):
        return self._buf.seek(*args)


class TestIraStreaming(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attachment = cls.env["ir.attachment"]
        icp = cls.env["ir.config_parameter"].sudo()
        icp.set_param("base.image_autoresize_extensions", "png,jpeg,bmp,tiff")
        icp.set_param("base.image_autoresize_max_px", "1920x1920")

    def _solid_jpeg(self, w, h, color=(10, 90, 200)):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), color).save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    def _upload(self, data, filename, content_type, mimetype="TRUST", **vals):
        fs = FileStorage(
            stream=io.BytesIO(data), filename=filename, content_type=content_type
        )
        return self.Attachment._from_request_file(fs, mimetype=mimetype, **vals)

    # -- primitive --------------------------------------------------------
    def test_primitive_roundtrip(self):
        data = os.urandom(5000)
        fname, size, checksum = self.Attachment._file_write_stream(io.BytesIO(data))
        self.assertEqual(size, len(data))
        self.assertEqual(checksum, hashlib.sha1(data).hexdigest())
        self.assertEqual(self.Attachment._file_read(fname), data)

    def test_primitive_reads_in_bounded_chunks(self):
        data = os.urandom(5000)
        spy = _ReadSpy(data)
        _fname, size, _checksum = self.Attachment._file_write_stream(
            spy, chunk_size=1024
        )
        self.assertEqual(size, len(data))
        # never an unbounded read; the whole file was consumed in >1 chunk
        self.assertTrue(all(s == 1024 for s in spy.read_sizes), spy.read_sizes)
        self.assertGreaterEqual(len(spy.read_sizes), 5)

    def test_primitive_dedups_by_content(self):
        data = b"dedup-me" * 2000
        f1, _s1, c1 = self.Attachment._file_write_stream(io.BytesIO(data))
        f2, _s2, c2 = self.Attachment._file_write_stream(io.BytesIO(data))
        self.assertEqual(f1, f2)
        self.assertEqual(c1, c2)
        self.assertEqual(self.Attachment._file_read(f1), data)

    def test_primitive_empty_stays_inline(self):
        fname, size, checksum = self.Attachment._file_write_stream(io.BytesIO(b""))
        self.assertEqual((fname, size), ("", 0))
        self.assertEqual(checksum, hashlib.sha1(b"").hexdigest())

    # -- decision ---------------------------------------------------------
    def test_should_stream_upload_decision(self):
        Att = self.Attachment
        self.assertTrue(Att._should_stream_upload("application/pdf"))
        self.assertTrue(Att._should_stream_upload("text/plain"))
        self.assertTrue(Att._should_stream_upload("image/gif"))  # not autoresized
        self.assertFalse(Att._should_stream_upload("image/jpeg"))  # may be resized
        self.assertTrue(
            Att.with_context(image_no_postprocess=True)._should_stream_upload(
                "image/jpeg"
            )
        )

    # -- _from_request_file end to end ------------------------------------
    def test_from_request_file_streams_binary(self):
        data = os.urandom(300000)
        att = self._upload(data, "f.bin", "application/octet-stream")
        self.assertTrue(att.store_fname, "non-image binary must be file-backed")
        self.assertEqual(att.raw, data)
        self.assertEqual(att.file_size, len(data))
        self.assertEqual(att.checksum, hashlib.sha1(data).hexdigest())

    def test_from_request_file_streams_text_and_indexes(self):
        text = b"streamable searchable words here " * 200
        att = self._upload(text, "t.txt", "text/plain")
        self.assertEqual(att.raw, text)
        self.assertIn("searchable", att.index_content or "")

    def test_from_request_file_image_buffers_and_resizes(self):
        payload = self._solid_jpeg(3000, 3000)
        att = self._upload(payload, "big.jpg", "image/jpeg")
        w, h = Image.open(io.BytesIO(att.raw)).size
        self.assertLessEqual(max(w, h), 1920, "buffered path must autoresize")

    def test_from_request_file_image_no_postprocess_streams_untouched(self):
        payload = self._solid_jpeg(3000, 3000)
        att = self.Attachment.with_context(image_no_postprocess=True)
        fs = FileStorage(
            stream=io.BytesIO(payload), filename="big.jpg", content_type="image/jpeg"
        )
        rec = att._from_request_file(fs, mimetype="TRUST")
        self.assertEqual(rec.raw, payload, "streamed image must keep original bytes")
        self.assertEqual(Image.open(io.BytesIO(rec.raw)).size, (3000, 3000))

    def test_from_request_file_dedups_identical_content(self):
        data = os.urandom(50000)
        a1 = self._upload(data, "a.bin", "application/octet-stream")
        a2 = self._upload(data, "b.bin", "application/octet-stream")
        self.assertNotEqual(a1.id, a2.id)
        self.assertEqual(a1.store_fname, a2.store_fname)

    def test_from_request_file_routes_to_streaming_primitive(self):
        """Isolation: prove the path taken, not just the resulting bytes.

        An image_no_postprocess upload must go through _file_write_stream; an
        autoresize-eligible image (no such context) must NOT — it buffers so PIL
        can resize. Same payload both times, so only the route differs.
        """
        payload = self._solid_jpeg(3000, 3000)
        calls = []
        real = IrAttachment._file_write_stream

        def spy(model, fileobj, **kwargs):
            calls.append(1)
            return real(model, fileobj, **kwargs)

        with patch.object(IrAttachment, "_file_write_stream", spy):
            fs = FileStorage(
                stream=io.BytesIO(payload), filename="a.jpg", content_type="image/jpeg"
            )
            self.Attachment.with_context(image_no_postprocess=True)._from_request_file(
                fs, mimetype="TRUST"
            )
            self.assertEqual(len(calls), 1, "image_no_postprocess must stream")

            fs2 = FileStorage(
                stream=io.BytesIO(payload), filename="b.jpg", content_type="image/jpeg"
            )
            self.Attachment._from_request_file(fs2, mimetype="TRUST")
            self.assertEqual(
                len(calls), 1, "autoresize image must NOT use the streaming primitive"
            )

    def test_from_request_file_db_location_buffers(self):
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("ir_attachment.location", "db")
        try:
            data = os.urandom(40000)
            att = self._upload(data, "d.bin", "application/octet-stream")
            self.assertFalse(att.store_fname, "db storage stays inline")
            self.assertEqual(att.raw, data)
            self.assertEqual(att.file_size, len(data))
        finally:
            icp.set_param("ir_attachment.location", "file")
