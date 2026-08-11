from datetime import date

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGiftCardStatus(TransactionCase):
    """Whether a scanned gift-card code may be used at the register.

    The cashier scans a code and this decides what happens next, so both
    answers cost money: accepting a spent or already-owned card gives goods
    away, refusing a good one turns a paying customer away.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Card = cls.env["loyalty.card"]
        cls.config = cls.env["pos.config"].search([], limit=1)
        cls.gift_card_program = cls.env["loyalty.program"].create(
            {
                "name": "Gift cards",
                "program_type": "gift_card",
                "trigger": "auto",
                "applies_on": "current",
                "rule_ids": [Command.create({"mode": "with_code"})],
            }
        )
        cls.loyalty_program = cls.env["loyalty.program"].create(
            {
                "name": "Points",
                "program_type": "loyalty",
                "trigger": "auto",
                "applies_on": "both",
                "rule_ids": [
                    Command.create({"reward_point_mode": "unit", "minimum_qty": 1})
                ],
            }
        )

    def _card(self, code, program=None, **values):
        return self.Card.create(
            {
                "program_id": (program or self.gift_card_program).id,
                "code": code,
                "points": 50.0,
                **values,
            }
        )

    def _usable(self, code):
        return self.Card.get_gift_card_status(code, self.config)["status"]

    def test_a_funded_card_may_be_used(self):
        """A gift card with a balance and no owner is accepted."""
        self._card("GC-FUNDED")
        self.assertTrue(self._usable("GC-FUNDED"))

    def test_an_expired_card_is_refused(self):
        """Past its expiry date a card is no longer money (negative)."""
        self._card("GC-EXPIRED", expiration_date=date(2020, 1, 1))
        self.assertFalse(self._usable("GC-EXPIRED"))

    def test_a_spent_card_is_refused(self):
        """A card with nothing left on it buys nothing (negative)."""
        self._card("GC-SPENT", points=0.0)
        self.assertFalse(self._usable("GC-SPENT"))

    def test_a_card_already_belonging_to_someone_is_refused(self):
        """An assigned card is that customer's, not the bearer's (negative)."""
        owner = self.env["res.partner"].create({"name": "Card owner"})
        self._card("GC-OWNED", partner_id=owner.id)
        self.assertFalse(self._usable("GC-OWNED"))

    def test_a_loyalty_card_is_not_a_gift_card(self):
        """A points card carries no balance to spend (negative)."""
        self._card("LOYALTY-1", program=self.loyalty_program)
        self.assertFalse(self._usable("LOYALTY-1"))

    def test_an_unknown_code_is_reported_as_free_to_issue(self):
        """A code nobody holds answers yes, because it can still be issued.

        The question asked is whether the register may go ahead with this
        code, and an unissued one is available -- this is deliberate, not a
        missing existence check.
        """
        self.assertFalse(self.Card.search([("code", "=", "NEVER-ISSUED")]))
        self.assertTrue(self._usable("NEVER-ISSUED"))

    def test_the_answer_carries_the_card_it_found(self):
        """The register is handed the card's data along with the verdict."""
        card = self._card("GC-PAYLOAD")
        result = self.Card.get_gift_card_status("GC-PAYLOAD", self.config)
        self.assertEqual(result["data"]["loyalty.card"][0]["id"], card.id)

    def test_an_unknown_code_carries_no_card(self):
        """Nothing is invented to go with a code that was never issued."""
        result = self.Card.get_gift_card_status("NEVER-ISSUED", self.config)
        self.assertFalse(result["data"]["loyalty.card"])
