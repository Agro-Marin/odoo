from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestProductionListLayout(HttpCase):
    def test_priority_column_is_star_sized(self):
        product = self.env["product.product"].create(
            {
                "name": "Widget",
                "is_storable": True,
            }
        )
        self.env["mrp.production"].create(
            {
                "product_id": product.id,
                "product_qty": 1.0,
                "product_uom_id": product.uom_id.id,
            }
        )
        self.start_tour(
            "/odoo/action-mrp.mrp_production_action",
            "test_mrp_production_priority_column_width",
            login="admin",
        )


@tagged("post_install", "-at_install")
class TestProductionCancelConfirmation(HttpCase):
    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create(
            {
                "name": "Widget",
                "is_storable": True,
            }
        )
        self.production = self.env["mrp.production"].create(
            {
                "product_id": product.id,
                "product_qty": 1.0,
                "product_uom_id": product.uom_id.id,
            }
        )
        self.production.action_confirm()

    def test_form_cancel_dialog_names_the_action(self):
        self.start_tour(
            f"/odoo/action-mrp.mrp_production_action/{self.production.id}",
            "test_mrp_production_cancel_confirmation_form",
            login="admin",
        )
        self.assertEqual(self.production.state, "confirmed")

    def test_list_cancel_dialog_names_the_action(self):
        self.start_tour(
            "/odoo/action-mrp.mrp_production_action",
            "test_mrp_production_cancel_confirmation_list",
            login="admin",
        )
        self.assertEqual(self.production.state, "confirmed")
