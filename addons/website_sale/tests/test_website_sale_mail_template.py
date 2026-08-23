# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestWebsiteSaleOrderEmailTemplate(SaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env["website"].create(
            {
                "name": "Test Website for Email Template",
            }
        )
        cls.sale_order.website_id = cls.website.id

    def _create_confirmation_template(self):
        return self.env["mail.template"].create(
            {
                "name": "Website Custom Confirmation Template",
                "model_id": self.env.ref("sale.model_sale_order").id,
                "subject": "Website Confirmation",
                "body_html": "<p>Hello</p>",
            }
        )

    def test_website_specific_confirmation_template_is_used(self):
        """Ensure _get_confirmation_template returns the website-specific template when set."""
        template = self._create_confirmation_template()
        self.website.confirmation_email_template_id = template

        self.assertEqual(self.sale_order._get_confirmation_template(), template)

    def test_confirmation_template_falls_back_when_website_sets_none(self):
        """A website without its own template must not shadow `sale`'s default."""
        self.website.confirmation_email_template_id = False

        self.assertEqual(
            self.sale_order._get_confirmation_template(),
            self.env.ref("sale.mail_template_sale_confirmation"),
            "The override must defer to sale's default when the website sets no template",
        )

    def test_confirmation_template_is_not_used_off_website(self):
        """The override keys on the order's website, not on the template existing."""
        self.website.confirmation_email_template_id = (
            self._create_confirmation_template()
        )
        self.sale_order.website_id = False

        self.assertNotEqual(
            self.sale_order._get_confirmation_template(),
            self.website.confirmation_email_template_id,
        )
