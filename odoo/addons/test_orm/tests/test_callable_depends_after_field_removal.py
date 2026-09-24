from odoo.tests import common


class TestCallableDependsAfterManualFieldRemoval(common.TransactionCase):
    def test_a_callable_depends_forgets_a_removed_manual_one2many(self):
        holder_model = self.env["ir.model"]._get("test_orm.manual_lines_holder")
        self.env["ir.model"].create(
            {
                "name": "x_holder_line",
                "model": "x_holder_line",
                "field_id": [
                    (
                        0,
                        0,
                        {
                            "name": "x_holder_id",
                            "ttype": "many2one",
                            "relation": "test_orm.manual_lines_holder",
                        },
                    )
                ],
            }
        )
        one2many = self.env["ir.model.fields"].create(
            {
                "model_id": holder_model.id,
                "name": "x_line_ids",
                "ttype": "one2many",
                "relation": "x_holder_line",
                "relation_field": "x_holder_id",
            }
        )
        holder = self.env["test_orm.manual_lines_holder"].create({"name": "h"})
        self.env["x_holder_line"].create({"x_holder_id": holder.id})
        self.assertEqual(holder.line_count, 1)

        one2many.unlink()

        self.assertNotIn("x_line_ids", self.env["test_orm.manual_lines_holder"]._fields)
        holder = self.env["test_orm.manual_lines_holder"].create({"name": "after"})
        self.env.flush_all()
        self.assertEqual(holder.line_count, 0)
