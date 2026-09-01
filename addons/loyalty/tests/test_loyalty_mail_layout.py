from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

LIGHT_LAYOUT = "mail.mail_notification_light"


@tagged("post_install", "-at_install")
class TestLoyaltyMailLayout(TransactionCase):
    """The notification layout the shipped coupon mails go out wrapped in."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env["loyalty.program"].create(
            {
                "name": "Coupons",
                "program_type": "coupons",
                "reward_ids": [Command.create({})],
            }
        )
        cls.card = cls.env["loyalty.card"].create(
            {"program_id": cls.program.id, "points": 10}
        )

    def _composer(self, template, **context):
        """The composer as a chatter or a server action would build it."""
        return (
            self.env["mail.compose.message"]
            .with_context(**context)
            .create(
                {
                    "model": "loyalty.card",
                    "res_ids": self.card.ids,
                    "composition_mode": "comment",
                    "template_id": template.id if template else False,
                }
            )
        )

    def test_the_shipped_templates_carry_the_layout_themselves(self):
        """Loaded anywhere, not only from the card's Send button, they stay branded."""
        for xml_id in ("mail_template_gift_card", "mail_template_loyalty_card"):
            with self.subTest(template=xml_id):
                template = self.env.ref(f"loyalty.{xml_id}")

                self.assertEqual(template.email_layout_xmlid, LIGHT_LAYOUT)
                self.assertEqual(
                    self._composer(template).email_layout_xmlid, LIGHT_LAYOUT
                )

    def test_the_send_button_still_brands_a_mail_with_no_template(self):
        """Not a fix -- this passes at HEAD, and must go on passing.

        A template that was never loaded cannot carry a layout, and `loyalty`
        alone resolves none for a program without a creation plan. That is why
        `action_coupon_send` keeps injecting the layout where upstream dropped it.
        `sale_loyalty` supplies a fallback template, so this builds the empty case
        explicitly rather than relying on what happens to be installed.
        """
        action = self.card.action_coupon_send()
        self.assertEqual(action["context"]["default_email_layout_xmlid"], LIGHT_LAYOUT)

        composer = self._composer(None, **action["context"])

        self.assertEqual(composer.email_layout_xmlid, LIGHT_LAYOUT)
