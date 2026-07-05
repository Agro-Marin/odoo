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
