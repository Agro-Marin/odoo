from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEngineShape(TransactionCase):
    def test_the_engine_ships_no_application(self):
        engine = self.env["ir.module.module"].search([("name", "=", "approval")])
        self.assertFalse(engine.application)
        shipped = self.env["ir.model.data"].search([("module", "=", "approval")])
        menus = self.env["ir.ui.menu"].browse(
            shipped.filtered(lambda row: row.model == "ir.ui.menu").mapped("res_id")
        )
        self.assertFalse(menus.filtered(lambda menu: not menu.parent_id))
        self.assertEqual(
            self.env.ref("approval.menu_approval_technical").parent_id,
            self.env.ref("base.menu_custom"),
        )
        self.assertEqual(
            menus - self.env.ref("approval.menu_approval_technical"),
            menus.filtered(
                lambda menu: (
                    menu.parent_id == self.env.ref("approval.menu_approval_technical")
                )
            ),
        )
        self.assertFalse(shipped.filtered(lambda row: row.model == "approval.category"))
