from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWebsiteSaleStockWishlist(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env.ref("website.default_website")
        cls.partner = cls.env["res.partner"].create({"name": "Wisher"})
        cls.product = cls.env["product.product"].create({"name": "Notifiable good"})

    def _wishlist(self):
        return self.env["product.wishlist"].create(
            {
                "product_id": self.product.id,
                "partner_id": self.partner.id,
                "website_id": self.website.id,
            }
        )

    def test_stock_notification_false_without_subscription(self):
        self.assertFalse(self._wishlist().stock_notification)

    def test_stock_notification_true_when_partner_subscribed(self):
        self.product.stock_notification_partner_ids = [(4, self.partner.id)]
        self.assertTrue(self._wishlist().stock_notification)
