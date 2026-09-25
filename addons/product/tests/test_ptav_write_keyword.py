from odoo.tests import tagged

from odoo.addons.product.tests.common import ProductVariantsCommon


@tagged("post_install", "-at_install")
class TestPtavWriteKeyword(ProductVariantsCommon):
    def test_write_takes_the_base_keyword(self):
        ptav = self.product_template_sofa.attribute_line_ids.product_template_value_ids[
            :1
        ]
        ptav.write(vals={"price_extra": 7.0})
        self.assertEqual(ptav.price_extra, 7.0)
