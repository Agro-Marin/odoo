from lxml import etree

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestName(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_name = "Product Test Name"
        cls.product_code = "PTN"
        cls.product = cls.env["product.product"].create(
            {
                "name": cls.product_name,
                "default_code": cls.product_code,
            }
        )

    def test_10_product_name(self):
        display_name = self.product.display_name
        self.assertEqual(
            display_name,
            "[%s] %s" % (self.product_code, self.product_name),
            "Code should be preprended the name as the context is not preventing it.",
        )
        display_name = self.product.with_context(
            display_default_code=False
        ).display_name
        self.assertEqual(
            display_name,
            self.product_name,
            "Code should not be preprended to the name as context should prevent it.",
        )

    def test_default_code_and_negative_operator(self):
        res = self.env["product.template"].name_search(name="PTN", operator="not ilike")
        res_ids = [r[0] for r in res]
        self.assertNotIn(self.product.id, res_ids)

    def test_product_template_search_name_no_product_product(self):
        self.env.user.write(
            {"group_ids": [(4, self.env.ref("product.group_product_variant").id)]}
        )
        color_attr = self.env["product.attribute"].create(
            {"name": "Color", "create_variant": "dynamic"}
        )
        color_attr_value_r = self.env["product.attribute.value"].create(
            {"name": "Red", "attribute_id": color_attr.id}
        )
        color_attr_value_b = self.env["product.attribute.value"].create(
            {"name": "Blue", "attribute_id": color_attr.id}
        )
        template_dyn = self.env["product.template"].create(
            {
                "name": "Test Dynamical",
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": color_attr.id,
                            "value_ids": [
                                (4, color_attr_value_r.id),
                                (4, color_attr_value_b.id),
                            ],
                        },
                    )
                ],
            }
        )
        product = self.env["product.product"].create(
            {
                "name": "Dynamo Lamp",
                "default_code": "Dynamo",
            }
        )
        self.assertTrue(template_dyn.has_dynamic_attributes())
        self.assertEqual(len(template_dyn.product_variant_ids), 0)
        res = self.env["product.template"].name_search(name="Dynam", operator="ilike")
        res_ids = [r[0] for r in res]
        self.assertIn(template_dyn.id, res_ids)
        self.assertIn(product.product_tmpl_id.id, res_ids)

    def test_product_product_name_search(self):
        attribute = self.env["product.attribute"].create(
            {
                "name": "Attribute",
                "value_ids": [Command.create({"name": f"value {i}"}) for i in range(3)],
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "Whatever",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        variant1, _variant2, _variant3 = template.product_variant_ids
        variant1.default_code = "HOHO"
        product_search = (
            self.env["product.product"]
            .with_context(partner_id=33)
            .search(
                [
                    ("display_name", "=", "HOHO"),
                ]
            )
        )
        self.assertEqual(variant1, product_search)

    def _search_as_the_search_bar_does(self, model, view_xmlid, typed):
        """Search the way the search bar does: through the view's own filter_domain.

        The domain is read from the combined arch instead of being hardcoded, so
        the test exercises what a user typing into the search bar actually gets
        rather than restating the change.
        """
        view = self.env.ref(view_xmlid)
        arch = etree.fromstring(self.env[model].get_view(view.id, "search")["arch"])
        nodes = arch.xpath("//field[@name='name'][@filter_domain]")
        self.assertTrue(nodes, "%s has no filter_domain on `name`" % view_xmlid)
        domain = safe_eval(
            nodes[0].get("filter_domain"), {"self": typed, "raw_value": typed}
        )
        return self.env[model].search(domain)

    def test_search_bar_finds_a_product_pasted_as_ref_and_name(self):
        """`[PTN] Product Test Name` is what a label, an export or a PDF shows.

        Pasting it whole into the product search bar has to find the product;
        before this it matched nothing, because the view searched `default_code`,
        `name` and `barcode` separately and the combined string is none of them.
        """
        typed = self.product.display_name
        self.assertEqual(typed, "[PTN] Product Test Name")

        self.assertEqual(
            self._search_as_the_search_bar_does(
                "product.product", "product.view_product_product_search", typed
            ),
            self.product,
        )
        self.assertEqual(
            self._search_as_the_search_bar_does(
                "product.template", "product.view_product_template_search", typed
            ),
            self.product.product_tmpl_id,
        )

    def test_search_bar_still_finds_a_product_by_its_parts(self):
        """The full-string search must not cost us the partial ones."""
        for typed in (self.product_code, self.product_name, "Test Name"):
            with self.subTest(typed=typed):
                self.assertIn(
                    self.product,
                    self._search_as_the_search_bar_does(
                        "product.product", "product.view_product_product_search", typed
                    ),
                )
