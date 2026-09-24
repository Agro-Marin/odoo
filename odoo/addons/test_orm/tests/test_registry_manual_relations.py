from odoo.tests import common


class TestNamedSetupAfterRolledBackManualModel(common.TransactionCase):
    def _create_manual_model(self, model):
        return self.env["ir.model"].create(
            {
                "name": model,
                "model": model,
                "field_id": [
                    (0, 0, {"name": "x_name", "ttype": "char"}),
                    (
                        0,
                        0,
                        {
                            "name": "x_partner_id",
                            "ttype": "many2one",
                            "relation": "res.partner",
                        },
                    ),
                ],
            }
        )

    def test_a_base_model_drops_its_one2many_to_a_rolled_back_manual_model(self):
        with self.assertRaises(InterruptedError), self.env.cr.savepoint():
            self._create_manual_model("x_rolled_back")
            self.env["ir.model.fields"].create(
                {
                    "model_id": self.env["ir.model"]._get_id("res.partner"),
                    "name": "x_rolled_back_ids",
                    "ttype": "one2many",
                    "relation": "x_rolled_back",
                    "relation_field": "x_partner_id",
                }
            )
            self.assertIn("x_rolled_back_ids", self.env["res.partner"]._fields)
            raise InterruptedError

        self._create_manual_model("x_created_after")

        self.assertNotIn("x_rolled_back", self.registry)
        self.assertNotIn("x_rolled_back_ids", self.env["res.partner"]._fields)
        self.assertIn("x_created_after", self.registry)
