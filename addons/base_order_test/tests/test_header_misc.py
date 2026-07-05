from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestHeaderMisc(BaseOrderTestCase):
    def test_has_archived_products(self):
        order = self._make_order()
        self._make_line(order=order)
        self.assertFalse(order.has_archived_products)

        self.product.active = False
        order.invalidate_recordset(["has_archived_products"])

        self.assertTrue(order.has_archived_products)

    def test_action_view_business_doc(self):
        order = self._make_order()

        action = order.action_view_business_doc()

        self.assertEqual(action["res_model"], "base.order.test")
        self.assertEqual(action["res_id"], order.id)

    def test_display_name_plain_without_context(self):
        order = self._make_order()

        self.assertEqual(order.display_name, order.name)

    def test_display_name_suffix_with_context(self):
        order = self._make_order()

        named = order.with_context(sale_show_partner_name=True)

        self.assertIn(self.partner.name, named.display_name)

    def test_rec_names_search_toggles_partner(self):
        Model = self.env["base.order.test"]

        self.assertEqual(Model._rec_names_search, ["name"])
        self.assertIn(
            "partner_id.name",
            Model.with_context(sale_show_partner_name=True)._rec_names_search,
        )

    def test_import_templates_shape(self):
        templates = self.env["base.order.test"].get_import_templates()

        self.assertTrue(templates)
        self.assertIn("label", templates[0])
        self.assertIn("template", templates[0])

    def test_is_late_search(self):
        now = fields.Datetime.now()
        late = self._make_order(date_planned=now - timedelta(days=1))
        on_time = self._make_order(date_planned=now + timedelta(days=1))
        undated = self._make_order()
        (late + on_time + undated).write({"state": "done"})
        draft_past = self._make_order(date_planned=now - timedelta(days=1))

        Model = self.env["base.order.test"]
        made = late + on_time + undated + draft_past

        late_found = Model.search([("is_late", "=", True), ("id", "in", made.ids)])
        self.assertEqual(late_found, late)

        # The negation must also cover orders without a planned date.
        not_late = Model.search([("is_late", "=", False), ("id", "in", made.ids)])
        self.assertEqual(not_late, on_time + undated + draft_past)

    def test_is_late_search_rejects_bad_operator(self):
        with self.assertRaises(Exception):
            self.env["base.order.test"].search([("is_late", ">", True)])
