"""Tests for the partner res.partner overrides."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResPartner(TransactionCase):
    def test_get_backend_root_menu_ids_includes_partner_menu(self):
        """res.partner's backend root menu includes partner's own menu."""
        menu_ids = self.env["res.partner"]._get_backend_root_menu_ids()
        self.assertIn(self.env.ref("partner.partner_menu_root").id, menu_ids)
