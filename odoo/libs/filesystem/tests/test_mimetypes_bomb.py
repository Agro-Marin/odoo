import io
import resource
import unittest
import zipfile

from odoo.libs.filesystem.mimetypes import _check_open_container_format


def _zip_with_mimetype(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", payload)
    return buf.getvalue()


class TestOpenContainerBomb(unittest.TestCase):
    def test_oversized_mimetype_member_is_not_fully_decompressed(self):
        blob = _zip_with_mimetype(b"A" * (120 * 1024 * 1024))
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result = _check_open_container_format(blob)
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.assertFalse(result)
        self.assertLess((after - before) / 1024, 50)

    def test_valid_odf_mimetype_still_detected(self):
        blob = _zip_with_mimetype(b"application/vnd.oasis.opendocument.text")
        self.assertEqual(
            _check_open_container_format(blob),
            "application/vnd.oasis.opendocument.text",
        )


if __name__ == "__main__":
    unittest.main()
