# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectMrp(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({"name": "Assembly line"})
        cls.product = cls.env["product.product"].create(
            {"name": "Finished good", "is_storable": True}
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.product.product_tmpl_id.id,
                "product_qty": 1.0,
                "project_id": cls.project.id,
            }
        )

    def _production(self):
        return self.env["mrp.production"].create(
            {"product_id": self.product.id, "product_qty": 1.0, "bom_id": self.bom.id}
        )

    def test_bom_count_reflects_linked_boms(self):
        """The project counts the bills of materials linked to it."""
        self.assertEqual(self.project.bom_count, 1)

    def test_action_view_mrp_bom_is_scoped_to_project(self):
        """The BoM smart button filters and defaults to the project."""
        action = self.project.action_view_mrp_bom()
        self.assertEqual(action["res_model"], "mrp.bom")
        self.assertEqual(action["domain"], [("project_id", "=", self.project.id)])
        self.assertEqual(action["context"]["default_project_id"], self.project.id)

    def test_production_inherits_project_from_bom(self):
        """A manufacturing order derives its project from its bill of materials."""
        production = self._production()
        self.assertEqual(production.project_id, self.project)
        self.assertEqual(self.project.production_count, 1)

    def test_action_open_project_targets_the_project(self):
        """The MO open-project action points at the linked project."""
        production = self._production()
        action = production.action_open_project()
        self.assertEqual(action["res_model"], "project.project")
        self.assertEqual(action["res_id"], self.project.id)

    def test_action_view_mrp_production_is_scoped_to_project(self):
        """The MO smart button filters and defaults to the project."""
        action = self.project.action_view_mrp_production()
        self.assertEqual(action["res_model"], "mrp.production")
        self.assertEqual(action["domain"], [("project_id", "=", self.project.id)])
        self.assertEqual(action["context"]["default_project_id"], self.project.id)
        self.assertTrue(action["context"]["from_project_action"])

    def test_stat_buttons_include_mrp_entries(self):
        """A project exposes BoM and manufacturing-order stat buttons."""
        buttons = {
            b["action"]: b for b in self.project._get_stat_buttons() if "action" in b
        }
        self.assertIn("action_view_mrp_bom", buttons)
        self.assertIn("action_view_mrp_production", buttons)
        self.assertEqual(
            buttons["action_view_mrp_bom"]["number"], self.project.bom_count
        )
