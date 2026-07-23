# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64

from lxml import etree

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestWebUnsplash(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.attachment_model = cls.env["ir.attachment"]
        cls.qweb_image = cls.env["ir.qweb.field.image"]

    # ── res.users._can_manage_unsplash_settings ──────────────────────

    def test_erp_manager_can_manage_unsplash(self):
        """An ERP manager is allowed to manage the Unsplash settings."""
        manager = new_test_user(
            self.env, login="unsplash_mgr", groups="base.group_erp_manager"
        )
        self.assertTrue(manager._can_manage_unsplash_settings())

    def test_basic_user_cannot_manage_unsplash(self):
        """A plain internal user cannot manage the Unsplash settings."""
        user = new_test_user(self.env, login="unsplash_basic", groups="base.group_user")
        self.assertFalse(user._can_manage_unsplash_settings())

    # ── ir.attachment._can_bypass_rights_on_media_dialog ─────────────

    def test_bypass_rights_for_unsplash_binary_url(self):
        """An unsplash binary+url attachment bypasses the usual restriction."""
        self.assertTrue(
            self.attachment_model._can_bypass_rights_on_media_dialog(
                url="/unsplash/photo-1", type="binary"
            )
        )

    def test_no_bypass_for_non_unsplash_url(self):
        """A non-unsplash binary+url attachment defers to the base rule (False)."""
        self.assertFalse(
            self.attachment_model._can_bypass_rights_on_media_dialog(
                url="/web/image/1", type="binary"
            )
        )

    def test_no_bypass_without_url(self):
        """An attachment without a url defers to the base rule (False)."""
        self.assertFalse(
            self.attachment_model._can_bypass_rights_on_media_dialog(type="binary")
        )

    # ── ir.qweb.field.image.from_html ────────────────────────────────

    def test_from_html_without_img_returns_false(self):
        """An element without an image yields no attachment data."""
        element = etree.fromstring("<div>no image here</div>")
        self.assertFalse(
            self.qweb_image.from_html(self.env["res.partner"], None, element)
        )

    def test_from_html_returns_unsplash_attachment_data(self):
        """An unsplash image element resolves to its public attachment data."""
        partner = self.env["res.partner"].create({"name": "Author"})
        payload = base64.b64encode(b"unsplash-bytes")
        self.env["ir.attachment"].create(
            {
                "name": "unsplash.jpg",
                "res_model": "res.partner",
                "res_id": partner.id,
                "public": True,
                "url": "/unsplash/photo-1",
                "datas": payload,
            }
        )
        element = etree.fromstring(
            f'<span data-oe-id="{partner.id}"><img src="/unsplash/photo-1"/></span>'
        )
        result = self.qweb_image.from_html(partner, None, element)
        self.assertEqual(result, payload)
