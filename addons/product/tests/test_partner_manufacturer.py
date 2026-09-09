from odoo.tests.common import TransactionCase


class TestResPartnerManufacturer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.manufacturer = cls.env["res.partner"].create(
            {"name": "Manufacturer With Products", "is_manufacturer": True}
        )
        cls.other_partner = cls.env["res.partner"].create(
            {"name": "Plain Partner", "is_manufacturer": False}
        )
        cls.template_a = cls.env["product.template"].create(
            {"name": "Template A", "manufacturer_id": cls.manufacturer.id}
        )
        cls.template_b = cls.env["product.template"].create(
            {"name": "Template B", "manufacturer_id": cls.manufacturer.id}
        )

    def test_the_count_matches_live_templates(self):
        self.assertEqual(self.manufacturer.count_manufactured_products, 2)

    def test_the_count_drops_when_a_template_is_archived(self):
        self.template_a.active = False
        self.manufacturer.invalidate_recordset(["count_manufactured_products"])
        self.assertEqual(self.manufacturer.count_manufactured_products, 1)

    def test_the_count_refreshes_after_an_archive_in_the_same_cursor(self):
        # reading the count first is what makes this a test of the dependency:
        # with a cold cache the post-archive read is correct even when nothing
        # watches `active`.
        self.assertEqual(self.manufacturer.count_manufactured_products, 2)
        self.template_a.action_archive()
        self.assertEqual(self.manufacturer.count_manufactured_products, 1)

    def test_the_count_is_keyed_by_active_test(self):
        self.template_a.active = False
        self.env.invalidate_all()
        self.assertEqual(self.manufacturer.count_manufactured_products, 1)
        self.assertEqual(
            self.manufacturer.with_context(
                active_test=False
            ).count_manufactured_products,
            2,
        )

    def test_the_count_is_zero_without_products(self):
        self.assertEqual(self.other_partner.count_manufactured_products, 0)

    def test_manufactured_product_ids_holds_the_templates(self):
        self.assertEqual(
            self.manufacturer.manufactured_product_ids,
            self.template_a + self.template_b,
        )

    def test_action_returns_the_manufacturer_templates(self):
        action = self.manufacturer.action_view_manufacturer_products()
        self.assertEqual(action["res_model"], "product.template")
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(
            action["context"]["search_default_manufacturer_id"],
            self.manufacturer.id,
        )
        self.assertEqual(
            action["context"]["default_manufacturer_id"],
            self.manufacturer.id,
        )

    def test_manufacturer_action_resolves_the_module_views(self):
        action = self.env.ref("product.action_partner_manufacturers")
        resolved = self.env["res.partner"].get_views(action.views)["views"]
        expected = {
            "kanban": self.env.ref("product.view_partner_manufacturer_kanban").id,
            "list": self.env.ref("product.view_partner_manufacturer_list").id,
            "form": self.env.ref("product.view_partner_manufacturer_form").id,
        }
        self.assertEqual(
            {mode: resolved[mode]["id"] for mode in expected},
            expected,
        )
