from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSettingsView(TransactionCase):
    def test_setting_and_block_hold_no_bare_text(self):
        views = self.env["ir.ui.view"].browse(
            self.env["ir.model.data"]
            .search([("module", "=", "pos_self_order"), ("model", "=", "ir.ui.view")])
            .mapped("res_id")
        )
        stray = [
            (view.xml_id, node.get("id") or node.get("string"), text.strip())
            for view in views
            for node in etree.fromstring(view.arch_db).iter("setting", "block")
            for text in [node.text or "", *(child.tail or "" for child in node)]
            if text.strip()
        ]
        self.assertEqual(stray, [])
