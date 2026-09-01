import base64

from odoo.tests import common

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YA"
    "AAAASUVORK5CYII="
)


@common.tagged("post_install", "-at_install", "web_unit", "web_qweb_fields")
class TestIrQwebFieldImageRecordToHtml(common.TransactionCase):
    def test_explicit_none_class_option_does_not_crash(self):
        partner = self.env["res.partner"].create(
            {"name": "Img Partner", "image_1920": base64.b64encode(TINY_PNG)}
        )
        field = self.env["ir.qweb.field.image"]
        html = field.record_to_html(
            partner,
            "image_1920",
            {"tagName": "span", "qweb_img_raw_data": True, "class": None},
        )
        self.assertIn("<img", html)
