import io
import unittest
import zipfile

from odoo.libs.filesystem.mimetypes import _check_ooxml

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ooxml(dirname: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(f"{dirname}main.xml", "<x/>")
    return buf.getvalue()


class TestCheckOoxml(unittest.TestCase):
    def test_pptx_detected(self):
        self.assertEqual(_check_ooxml(_ooxml("ppt/")), PPTX)

    def test_docx_detected(self):
        self.assertEqual(_check_ooxml(_ooxml("word/")), DOCX)

    def test_xlsx_detected(self):
        self.assertEqual(_check_ooxml(_ooxml("xl/")), XLSX)

    def test_non_ooxml_zip_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("random.txt", "hello")
        self.assertFalse(_check_ooxml(buf.getvalue()))


if __name__ == "__main__":
    unittest.main()
