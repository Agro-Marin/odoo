# Part of Odoo. See LICENSE file for full copyright and licensing details.

import random

from odoo import fields

from odoo.addons.product.tests.common import ProductCommon


class TestPricelistRuleSelection(ProductCommon):
    """`_compute_price_rule` hands each product only the rules that can name it.

    That narrowing must be invisible: the rule selected from the narrowed
    candidates has to be the very one a full ordered scan would have picked.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = cls.env["product.category"].create({"name": "Sel root"})
        cls.middle = cls.env["product.category"].create(
            {"name": "Sel middle", "parent_id": cls.root.id}
        )
        cls.leaf = cls.env["product.category"].create(
            {"name": "Sel leaf", "parent_id": cls.middle.id}
        )
        cls.sibling = cls.env["product.category"].create({"name": "Sel sibling"})
        cls.now = fields.Datetime.now()

    def _pricelist(self, name):
        return self.env["product.pricelist"].create(
            {"name": name, "currency_id": self.env.company.currency_id.id}
        )

    def _template(self, name, categ=None, variants=False):
        vals = {
            "name": name,
            "uom_id": self.uom_unit.id,
            "list_price": 100.0,
            "categ_id": categ.id if categ else False,
        }
        if variants:
            attribute = self.env["product.attribute"].create(
                {
                    "name": f"{name} attribute",
                    "create_variant": "always",
                    "value_ids": [(0, 0, {"name": "a"}), (0, 0, {"name": "b"})],
                }
            )
            vals["attribute_line_ids"] = [
                (
                    0,
                    0,
                    {
                        "attribute_id": attribute.id,
                        "value_ids": [(6, 0, attribute.value_ids.ids)],
                    },
                )
            ]
        return self.env["product.template"].create(vals)

    def test_category_rule_reaches_descendant_products(self):
        """A rule on an ancestor category still reaches a leaf-category product."""
        pricelist = self._pricelist("Sel categ")
        template = self._template("Sel deep", categ=self.leaf)
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "2_product_category",
                "categ_id": self.root.id,
                "compute_price": "fixed",
                "fixed_price": 42.0,
            }
        )
        self.assertEqual(
            pricelist._get_product_price(template.product_variant_id, 1.0), 42.0
        )

    def test_category_rule_does_not_reach_a_sibling_branch(self):
        pricelist = self._pricelist("Sel sibling")
        template = self._template("Sel elsewhere", categ=self.sibling)
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "2_product_category",
                "categ_id": self.root.id,
                "compute_price": "fixed",
                "fixed_price": 42.0,
            }
        )
        self.assertEqual(
            pricelist._get_product_price(template.product_variant_id, 1.0), 100.0
        )

    def test_variant_rule_reaches_a_single_variant_template(self):
        """A template with one variant is priced by that variant's rule."""
        pricelist = self._pricelist("Sel single")
        template = self._template("Sel single tmpl", categ=self.leaf)
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "0_product_variant",
                "product_id": template.product_variant_id.id,
                "compute_price": "fixed",
                "fixed_price": 42.0,
            }
        )
        self.assertEqual(pricelist._get_product_price(template, 1.0), 42.0)

    def test_variant_rule_does_not_reach_a_multi_variant_template(self):
        """A template with several variants is not priced by one variant's rule."""
        pricelist = self._pricelist("Sel multi")
        template = self._template("Sel multi tmpl", categ=self.leaf, variants=True)
        self.assertGreater(template.product_variant_count, 1)
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "0_product_variant",
                "product_id": template.product_variant_ids[0].id,
                "compute_price": "fixed",
                "fixed_price": 42.0,
            }
        )
        self.assertEqual(pricelist._get_product_price(template, 1.0), 100.0)
        self.assertEqual(
            pricelist._get_product_price(template.product_variant_ids[0], 1.0), 42.0
        )

    def test_product_without_category_ignores_category_rules(self):
        pricelist = self._pricelist("Sel nocateg")
        template = self._template("Sel nocateg tmpl", categ=None)
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "2_product_category",
                "categ_id": self.root.id,
                "compute_price": "fixed",
                "fixed_price": 42.0,
            }
        )
        self.assertEqual(
            pricelist._get_product_price(template.product_variant_id, 1.0), 100.0
        )

    def test_narrowed_candidates_match_a_full_ordered_scan(self):
        """The differential that guards the optimisation itself.

        Every rule level, overlapping categories, quantity thresholds and both
        product models -- the narrowed candidate list must select exactly what
        scanning the whole ordered recordset selects.
        """
        rng = random.Random(20260807)
        categories = self.root + self.middle + self.leaf + self.sibling
        templates = self.env["product.template"].concat(
            *[
                self._template(
                    f"Sel diff {i}",
                    categ=categories[i % len(categories)],
                    variants=bool(i % 3 == 0),
                )
                for i in range(12)
            ]
        )
        variants = templates.product_variant_ids
        pricelist = self._pricelist("Sel diff")

        rule_vals = []
        for i in range(120):
            vals = {
                "pricelist_id": pricelist.id,
                "compute_price": "fixed",
                "fixed_price": float(i),
                "min_quantity": rng.choice([0, 0, 5, 50]),
            }
            kind = rng.choice(["global", "categ", "tmpl", "variant"])
            if kind == "categ":
                vals.update(
                    applied_on="2_product_category",
                    categ_id=rng.choice(categories).id,
                )
            elif kind == "tmpl":
                vals.update(
                    applied_on="1_product", product_tmpl_id=rng.choice(templates).id
                )
            elif kind == "variant":
                variant = rng.choice(variants)
                vals.update(
                    applied_on="0_product_variant",
                    product_id=variant.id,
                    product_tmpl_id=variant.product_tmpl_id.id,
                )
            else:
                vals["applied_on"] = "3_global"
            rule_vals.append(vals)
        self.env["product.pricelist.item"].create(rule_vals)
        self.env.flush_all()

        for subject in (variants, templates):
            rules = pricelist._get_applicable_rules(subject, self.now)
            index = pricelist._index_rules_by_target(rules)
            for quantity in (1.0, 5.0, 60.0):
                for product in subject:
                    expected = pricelist._get_suitable_rule(rules, product, quantity)
                    narrowed = pricelist._get_suitable_rule(
                        pricelist._candidate_rules(rules, index, product),
                        product,
                        quantity,
                    )
                    self.assertEqual(
                        narrowed,
                        expected,
                        f"narrowing changed the rule for {product.display_name!r}"
                        f" at qty {quantity}",
                    )
