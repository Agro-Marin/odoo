import base64
import io

from odoo import Command
from odoo.tests import tagged

from .common import ProductCommon, ProductVariantsCommon


def _png(color="#112233", size=(64, 64)):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue())


@tagged("post_install", "-at_install")
class TestVariantUnlinkUnderBinSize(ProductVariantsCommon):

    def test_unlink_moves_the_image_under_a_bin_size_context(self):
        template = self.product_template_sofa
        variant = template.product_variant_ids[0]
        self.assertGreater(len(template.product_variant_ids), 1)
        self.assertFalse(template.image_1920)
        variant.image_variant_1920 = _png()
        self.env.flush_all()
        self.env.invalidate_all()

        variant.with_context(bin_size=True).unlink()

        image = template.with_context(bin_size=False).image_1920
        self.assertTrue(image)
        self.assertTrue(base64.b64decode(image).startswith(b"\x89PNG"))


@tagged("post_install", "-at_install")
class TestUpdateAttributeValueWizardCount(ProductVariantsCommon):

    def test_count_follows_the_attribute_value(self):
        wizard = self.env["update.product.attribute.value"].create(
            {
                "attribute_value_id": self.color_attribute_red.id,
                "mode": "update_extra_price",
            }
        )
        red_count = wizard.product_count

        wizard.attribute_value_id = self.size_attribute_s
        reported = wizard.product_count

        self.env.invalidate_all()
        self.assertEqual(
            reported,
            wizard.product_count,
            "the reported count must be the one a fresh read gives",
        )
        self.assertNotEqual(
            reported,
            red_count,
            "the two values are not carried by the same products; a count that"
            " did not move is the stale one",
        )


@tagged("post_install", "-at_install")
class TestOwnAttributeExclusions(ProductVariantsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.product_template_sofa
        ptavs = cls.template.valid_product_template_attribute_line_ids.product_template_value_ids
        cls.red = ptavs.filtered(
            lambda ptav: ptav.product_attribute_value_id == cls.color_attribute_red
        )
        cls.blue = ptavs.filtered(
            lambda ptav: ptav.product_attribute_value_id == cls.color_attribute_blue
        )

    def test_reports_the_exclusions_of_this_template_only(self):
        other = self.env["product.template"].create(
            {
                "name": "Other sofa",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.color_attribute.id,
                            "value_ids": [
                                Command.set(
                                    [
                                        self.color_attribute_red.id,
                                        self.color_attribute_blue.id,
                                    ]
                                )
                            ],
                        }
                    )
                ],
            }
        )
        other_blue = other.valid_product_template_attribute_line_ids.product_template_value_ids.filtered(
            lambda ptav: ptav.product_attribute_value_id == self.color_attribute_blue
        )
        self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": self.template.id,
                "product_template_attribute_value_id": self.red.id,
                "value_ids": [Command.set(self.blue.ids)],
            }
        )
        self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": other.id,
                "product_template_attribute_value_id": self.red.id,
                "value_ids": [Command.set(other_blue.ids)],
            }
        )

        exclusions = self.template._get_own_attribute_exclusions()
        self.assertEqual(exclusions[self.red.id], self.blue.ids)
        self.assertEqual(exclusions[self.blue.id], [])

    def test_archived_values_are_reported_only_when_asked_for(self):
        self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": self.template.id,
                "product_template_attribute_value_id": self.red.id,
                "value_ids": [Command.set(self.blue.ids)],
            }
        )
        self.blue.ptav_active = False

        self.assertNotIn(self.blue.id, self.template._get_own_attribute_exclusions())
        self.assertEqual(
            self.template._get_own_attribute_exclusions()[self.red.id],
            [],
            "an archived value excludes nothing",
        )
        with_combination = self.template._get_own_attribute_exclusions(
            combination_ids=self.blue.ids
        )
        self.assertIn(self.blue.id, with_combination)

    def test_repeated_calls_do_not_repeat_the_query(self):
        self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": self.template.id,
                "product_template_attribute_value_id": self.red.id,
                "value_ids": [Command.set(self.blue.ids)],
            }
        )
        self.env.flush_all()
        self.env.invalidate_all()

        first = self.template._get_own_attribute_exclusions()
        with self.assertQueryCount(0):
            for _call in range(5):
                self.assertEqual(
                    self.template._get_own_attribute_exclusions(),
                    first,
                )


@tagged("post_install", "-at_install")
class TestCategoryRulePrecedence(ProductCommon):

    def test_child_category_rule_wins_over_parent(self):
        child = self.env["product.category"].create({"name": "Prec child"})
        parent = self.env["product.category"].create({"name": "Prec parent"})
        child.parent_id = parent
        self.assertLess(child.id, parent.id)

        product = self.env["product.template"].create(
            {"name": "Prec widget", "list_price": 100.0, "categ_id": child.id}
        )
        pricelist = self.env["product.pricelist"].create(
            {"name": "Prec pricelist", "currency_id": self.env.company.currency_id.id}
        )
        for category, price in ((parent, 50.0), (child, 10.0)):
            self.env["product.pricelist.item"].create(
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "2_product_category",
                    "categ_id": category.id,
                    "compute_price": "fixed",
                    "fixed_price": price,
                }
            )
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(pricelist._get_product_price(product, 1.0), 10.0)
