# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoyaltyProductTemplate(TransactionCase):
    """product.template gift-card placeholder image on creation."""

    def test_gift_card_product_gets_placeholder_image(self):
        """Creating a gift-card product stamps the placeholder image."""
        template = (
            self.env["product.template"]
            .with_context(loyalty_is_gift_card_product=True)
            .create({"name": "Gift Card", "type": "consu"})
        )
        self.assertTrue(template.image_1920)

    def test_regular_product_has_no_placeholder(self):
        """A normal product is created without the gift-card image (boundary)."""
        template = self.env["product.template"].create(
            {"name": "Regular", "type": "consu"}
        )
        self.assertFalse(template.image_1920)
