import base64
import io

from PIL import Image

from odoo.tests import TransactionCase, tagged


def _png(width=6, height=4):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue())


@tagged("post_install", "-at_install")
class TestAttachmentMediaUrls(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attachment = cls.env["ir.attachment"]

    def test_binary_image_src_carries_a_cachebuster(self):
        attachment = self.Attachment.create(
            {
                "name": "pic.png",
                "datas": _png(),
                "mimetype": "image/png",
            }
        )
        unique = attachment.checksum[:8]
        self.assertEqual(
            attachment.image_src,
            f"/web/image/{attachment.id}-{unique}/pic.png",
        )

    def test_local_url_falls_back_to_the_image_route(self):
        attachment = self.Attachment.create(
            {
                "name": "pic.png",
                "datas": _png(),
                "mimetype": "image/png",
            }
        )
        self.assertEqual(
            attachment.local_url,
            f"/web/image/{attachment.id}?unique={attachment.checksum}",
        )

    def test_unsupported_mimetype_has_no_image_src(self):
        attachment = self.Attachment.create(
            {
                "name": "blob.bin",
                "datas": base64.b64encode(b"zzz"),
                "mimetype": "application/octet-stream",
            }
        )
        self.assertFalse(attachment.image_src)

    def test_local_url_attachment_is_served_as_is(self):
        attachment = self.Attachment.create(
            {
                "name": "local.png",
                "type": "url",
                "url": "/web/static/img/a.png",
                "mimetype": "image/png",
            }
        )
        self.assertEqual(attachment.image_src, "/web/static/img/a.png")
        self.assertEqual(attachment.local_url, "/web/static/img/a.png")

    def test_external_url_attachment_goes_through_the_redirect(self):
        attachment = self.Attachment.create(
            {
                "name": "ext img.png",
                "type": "url",
                "url": "https://example.com/a.png",
                "mimetype": "image/png",
            }
        )
        self.assertEqual(
            attachment.image_src,
            f"/web/image/{attachment.id}-redirect/ext%20img.png",
        )

    def test_url_with_query_gets_an_ampersand_separator(self):
        attachment = self.Attachment.create(
            {
                "name": "q.png",
                "datas": _png(),
                "mimetype": "image/png",
                "url": "/x/y?v=1",
            }
        )
        self.assertEqual(
            attachment.image_src,
            f"/x/y?v=1&unique={attachment.checksum[:8]}",
        )

    def test_image_dimensions_are_read_from_the_data(self):
        attachment = self.Attachment.create(
            {
                "name": "pic.png",
                "datas": _png(width=6, height=4),
                "mimetype": "image/png",
            }
        )
        self.assertEqual(attachment.image_width, 6)
        self.assertEqual(attachment.image_height, 4)

    def test_undecodable_data_reports_zero_dimensions(self):
        attachment = self.Attachment.create(
            {
                "name": "blob.bin",
                "datas": base64.b64encode(b"not an image"),
                "mimetype": "application/octet-stream",
            }
        )
        self.assertEqual(attachment.image_width, 0)
        self.assertEqual(attachment.image_height, 0)

    def test_media_info_exposes_the_dialog_payload(self):
        attachment = self.Attachment.create(
            {
                "name": "pic.png",
                "datas": _png(),
                "mimetype": "image/png",
            }
        )
        info = attachment._get_media_info()
        for key in (
            "id",
            "name",
            "mimetype",
            "image_src",
            "image_width",
            "image_height",
        ):
            self.assertIn(key, info)
        self.assertEqual(info["name"], "pic.png")

    def test_rights_bypass_is_closed_by_default(self):
        self.assertFalse(self.Attachment._can_bypass_rights_on_media_dialog())
