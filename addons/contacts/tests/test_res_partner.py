"""Tests for the contacts res.partner overrides."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResPartner(TransactionCase):
    def test_get_backend_root_menu_ids_includes_contacts_menu(self):
        """res.partner's backend root menu includes contacts's own menu."""
        menu_ids = self.env["res.partner"]._get_backend_root_menu_ids()
        self.assertIn(self.env.ref("contacts.menu_contacts").id, menu_ids)
