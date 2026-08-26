from odoo.exceptions import ValidationError

from odoo.addons.product.tests.common import ProductCommon


class TestPricelistItemTargeting(ProductCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.attribute = cls.env["product.attribute"].create(
            {
                "name": "Targeting Colour",
                "create_variant": "always",
                "display_type": "radio",
            }
        )
        cls.red_value, cls.blue_value = cls.env["product.attribute.value"].create(
            [
                {"name": "Targeting Red", "attribute_id": cls.attribute.id},
                {"name": "Targeting Blue", "attribute_id": cls.attribute.id},
            ]
        )

    def _two_variant_template(self, name):
        template = self.env["product.template"].create(
            {
                "name": name,
                "list_price": 100.0,
                "uom_id": self.uom_unit.id,
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": self.attribute.id,
                            "value_ids": [
                                (6, 0, (self.red_value + self.blue_value).ids)
                            ],
                        },
                    )
                ],
            }
        )
        return (
            template,
            template.product_variant_ids[0],
            template.product_variant_ids[1],
        )

    def test_write_product_id_deduces_applied_on(self):
        template, red, _blue = self._two_variant_template("Targeting Deduce")
        item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "product_tmpl_id": template.id,
                "compute_price": "fixed",
                "fixed_price": 10.0,
            }
        )
        self.assertEqual(item.applied_on, "1_product")

        item.write({"product_id": red.id})

        self.assertEqual(item.applied_on, "0_product_variant")
        self.assertEqual(item.product_tmpl_id, template)

    def test_write_clearing_variant_falls_back_to_template(self):
        _template, red, blue = self._two_variant_template("Targeting Widen")
        item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "product_id": red.id,
                "compute_price": "fixed",
                "fixed_price": 10.0,
            }
        )
        self.assertEqual(item.applied_on, "0_product_variant")

        item.write({"product_id": False})

        self.assertEqual(item.applied_on, "1_product")
        self.assertEqual(self.pricelist._get_product_price(blue, 1.0), 10.0)

    def test_write_categ_id_deduces_category_level(self):
        item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "compute_price": "fixed",
                "fixed_price": 10.0,
            }
        )
        self.assertEqual(item.applied_on, "3_global")

        item.write({"categ_id": self.product_category.id})

        self.assertEqual(item.applied_on, "2_product_category")
        self.assertEqual(
            self.pricelist._get_product_price(self.product, 1.0),
            10.0,
        )

    def test_write_explicit_applied_on_is_respected(self):
        _template, red, _blue = self._two_variant_template("Targeting Explicit")
        item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "product_id": red.id,
                "compute_price": "fixed",
                "fixed_price": 10.0,
            }
        )
        write_vals = {"applied_on": "3_global"}
        item.write(write_vals)

        self.assertEqual(item.applied_on, "3_global")
        self.assertFalse(item.product_id)
        self.assertFalse(item.product_tmpl_id)
        self.assertEqual(write_vals, {"applied_on": "3_global"})

    def test_write_deduces_per_record_in_a_batch(self):
        _template, red, _blue = self._two_variant_template("Targeting Batch")
        variant_item, global_item = self.env["product.pricelist.item"].create(
            [
                {
                    "pricelist_id": self.pricelist.id,
                    "product_id": red.id,
                    "compute_price": "fixed",
                    "fixed_price": 10.0,
                },
                {
                    "pricelist_id": self.pricelist.id,
                    "compute_price": "fixed",
                    "fixed_price": 20.0,
                },
            ]
        )
        (variant_item + global_item).write({"categ_id": self.product_category.id})

        self.assertEqual(variant_item.applied_on, "0_product_variant")
        self.assertEqual(global_item.applied_on, "2_product_category")

    def test_narrowed_rule_outranks_a_later_template_rule(self):
        template, red, _blue = self._two_variant_template("Targeting Priority")
        override = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "product_tmpl_id": template.id,
                "compute_price": "fixed",
                "fixed_price": 10.0,
            }
        )
        override.write({"product_id": red.id})
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "product_tmpl_id": template.id,
                "compute_price": "fixed",
                "fixed_price": 99.0,
            }
        )

        self.assertEqual(self.pricelist._get_product_price(red, 1.0), 10.0)

    def test_variant_of_another_template_is_rejected(self):
        _template_a, red_a, _blue_a = self._two_variant_template("Targeting Cons A")
        template_b, _red_b, _blue_b = self._two_variant_template("Targeting Cons B")
        item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "product_id": red_a.id,
                "compute_price": "fixed",
                "fixed_price": 42.0,
            }
        )
        with self.assertRaises(ValidationError):
            item.write({"product_tmpl_id": template_b.id})
            self.env.flush_all()

    def test_variant_of_another_template_is_rejected_on_create(self):
        _template_a, red_a, _blue_a = self._two_variant_template("Targeting Cons C")
        template_b, _red_b, _blue_b = self._two_variant_template("Targeting Cons D")
        with self.assertRaises(ValidationError):
            self.env["product.pricelist.item"].create(
                {
                    "pricelist_id": self.pricelist.id,
                    "applied_on": "0_product_variant",
                    "product_id": red_a.id,
                    "product_tmpl_id": template_b.id,
                    "compute_price": "fixed",
                    "fixed_price": 42.0,
                }
            )
            self.env.flush_all()

    def test_retargeting_a_rule_to_another_template_keeps_it_reachable(self):
        _template_a, red_a, _blue_a = self._two_variant_template("Targeting Move A")
        template_b, red_b, blue_b = self._two_variant_template("Targeting Move B")
        item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "product_id": red_a.id,
                "compute_price": "fixed",
                "fixed_price": 42.0,
            }
        )
        item.write({"product_id": red_b.id})

        self.assertEqual(item.product_tmpl_id, template_b)
        self.assertEqual(self.pricelist._get_product_price(red_b, 1.0), 42.0)
        self.assertEqual(self.pricelist._get_product_price(blue_b, 1.0), 100.0)
