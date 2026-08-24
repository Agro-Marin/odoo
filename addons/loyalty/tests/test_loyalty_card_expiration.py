# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyCardExpiration(TransactionCase):
    """A loyalty card carries no expiration date, however it is written."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.loyalty_program = cls.env['loyalty.program'].create(
            {'name': "Points", 'program_type': 'loyalty'}
        )
        cls.coupon_program = cls.env['loyalty.program'].create(
            {'name': "Coupons", 'program_type': 'coupons', 'reward_ids': [Command.create({})]}
        )

    def test_expiration_on_a_loyalty_card_is_refused_at_create(self):
        """The rule was an onchange, so it only ever guarded the form."""
        with self.assertRaises(ValidationError):
            self.env['loyalty.card'].create({
                'program_id': self.loyalty_program.id,
                'points': 1,
                'expiration_date': '2030-01-01',
            })

    def test_expiration_on_a_loyalty_card_is_refused_at_write(self):
        """The same through a write, which an import or another module reaches."""
        card = self.env['loyalty.card'].create(
            {'program_id': self.loyalty_program.id, 'points': 1}
        )

        with self.assertRaises(ValidationError):
            card.write({'expiration_date': '2030-01-01'})

    def test_moving_a_dated_card_onto_a_loyalty_program_is_refused(self):
        """The program is part of the rule, so changing it re-checks it."""
        card = self.env['loyalty.card'].create({
            'program_id': self.coupon_program.id,
            'points': 1,
            'expiration_date': '2030-01-01',
        })

        with self.assertRaises(ValidationError):
            card.write({'program_id': self.loyalty_program.id})

    def test_other_program_types_still_expire(self):
        """Coupons, gift cards and eWallets keep their expiration date."""
        card = self.env['loyalty.card'].create({
            'program_id': self.coupon_program.id,
            'points': 1,
            'expiration_date': '2030-01-01',
        })

        self.assertEqual(str(card.expiration_date), '2030-01-01')

    def test_points_display_follows_the_program_currency(self):
        """A card priced in its program's currency reformats when that changes.

        Not a fix -- this passes at HEAD. It pins the chain that makes the extra
        dependency unnecessary: `currency_id` -> `portal_point_name` (a stored
        compute) -> the card's related `point_name` -> `points_display`. Written
        after adding `program_id.currency_id` to that compute's `@api.depends` and
        finding it changed nothing; the dependency was removed again.
        """
        wallet = self.env['loyalty.program'].create(
            {'name': "Wallet", 'program_type': 'ewallet'}
        )
        card = self.env['loyalty.card'].create({'program_id': wallet.id, 'points': 10})
        before = card.points_display

        other = self.env['res.currency'].search([('id', '!=', wallet.currency_id.id)], limit=1)
        wallet.write({'currency_id': other.id})

        self.assertNotEqual(card.points_display, before)
