from odoo import Command
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMrpMobile(HttpCase):
    # a phone-sized window: the whole point of the views below is what they do
    # when `env.isSmall` is true.
    browser_size = "375x667"

    def test_components_are_cards_on_a_small_screen(self):
        component = self.env["product.product"].create(
            {"name": "Mobile component", "is_storable": True}
        )
        finished = self.env["product.product"].create(
            {"name": "Mobile finished product", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1.0}),
                ],
            }
        )
        production = self.env["mrp.production"].create({"bom_id": bom.id})
        self.assertTrue(production.move_raw_ids)

        self.start_tour(
            f"/odoo/action-mrp.mrp_production_action/{production.id}",
            "mrp_mo_components_kanban_on_mobile",
            login="admin",
            timeout=100,
        )
