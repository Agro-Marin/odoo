from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoyaltyCardUniqueness(TransactionCase):
    """A customer's points on a loyalty program live on one card, or nowhere."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.loyalty_program = cls.env["loyalty.program"].create(
            {"name": "Points", "program_type": "loyalty"}
        )
        cls.coupon_program = cls.env["loyalty.program"].create(
            {
                "name": "Coupons",
                "program_type": "coupons",
                "reward_ids": [Command.create({})],
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Loyal Customer"})

    def _card(self, program=None, partner=None, **values):
        return self.env["loyalty.card"].create(
            {
                "program_id": (program or self.loyalty_program).id,
                "partner_id": (partner or self.partner).id,
                "points": 10,
                **values,
            }
        )

    def test_a_second_card_for_the_same_program_is_refused(self):
        """`sale_loyalty` reads one card per program, so the second holds dead points."""
        self._card()

        with self.assertRaises(ValidationError):
            self._card(points=200)

    def test_two_cards_created_in_one_batch_are_refused(self):
        """The pair never exists one at a time, so a per-record check would miss it."""
        with self.assertRaises(ValidationError):
            self.env["loyalty.card"].create(
                [
                    {
                        "program_id": self.loyalty_program.id,
                        "partner_id": self.partner.id,
                    },
                    {
                        "program_id": self.loyalty_program.id,
                        "partner_id": self.partner.id,
                    },
                ]
            )

    def test_handing_a_card_to_a_customer_who_already_has_one_is_refused(self):
        """The same through `partner_id`, which an import or a merge reaches."""
        self._card()
        other = self._card(partner=self.env["res.partner"].create({"name": "Other"}))

        with self.assertRaises(ValidationError):
            other.partner_id = self.partner

    def test_an_archived_card_leaves_room_for_a_new_one(self):
        """Archiving is how a balance is retired, so it must free the customer."""
        first = self._card()
        first.active = False

        self.assertTrue(self._card(points=200))

    def test_a_card_may_be_archived_next_to_an_active_one(self):
        """Deliberately unlike upstream, whose check ignores the card's own `active`.

        `base.partner.merge` drains the losing cards and archives them while the
        survivor is already active on the destination partner.
        """
        first = self._card()
        second = self._card(partner=self.env["res.partner"].create({"name": "Merged"}))
        second.active = False

        self.assertTrue(second.write({"partner_id": first.partner_id.id}))

    def test_an_anonymous_card_is_not_a_customer_s_card(self):
        """A card with no holder cannot collide with another customer's."""
        self._card(partner_id=False)

        self.assertTrue(self._card(partner_id=False))

    def test_other_program_types_still_allow_several(self):
        """Coupons, gift cards and eWallets are issued many times over."""
        self._card(program=self.coupon_program)

        self.assertTrue(self._card(program=self.coupon_program))
