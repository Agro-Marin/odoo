from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged("post_install", "-at_install")
class TestPosBarcodeVariants(TestPointOfSaleHttpCommon):
    def test_barcode_scan_preselect_always_variant(self):
        """Scanning a barcode that identifies one variant must open the
        configurator with the variant-creating attribute already picked, and ask
        only for the attributes the barcode cannot decide.

        The first scan of the tour passes even without the fix, because the
        configurator falls back to the first value of each attribute and Red is
        first. The second scan is the one that catches it.
        """
        color_attribute = self.env["product.attribute"].create(
            {
                "name": "Color",
                "create_variant": "always",
                "display_type": "radio",
                "value_ids": [
                    Command.create({"name": "Red", "sequence": 1}),
                    Command.create({"name": "Blue", "sequence": 2}),
                ],
            }
        )
        size_attribute = self.env["product.attribute"].create(
            {
                "name": "Size",
                "create_variant": "no_variant",
                "display_type": "radio",
                "value_ids": [
                    Command.create({"name": "Small", "sequence": 1}),
                    Command.create({"name": "Large", "sequence": 2}),
                ],
            }
        )
        product = self.env["product.template"].create(
            {
                "name": "Variant Barcode Product",
                "available_in_pos": True,
                "list_price": 10,
                "taxes_id": False,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": color_attribute.id,
                            "value_ids": [Command.set(color_attribute.value_ids.ids)],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": size_attribute.id,
                            "value_ids": [Command.set(size_attribute.value_ids.ids)],
                        }
                    ),
                ],
            }
        )
        red_variant, blue_variant = product.product_variant_ids
        red_variant.barcode = "VAR_RED_001"
        blue_variant.barcode = "VAR_BLUE_001"

        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.start_pos_tour("test_barcode_scan_preselect_always_variant")
