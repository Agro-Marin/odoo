# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyProgramFields(TransactionCase):
    """Program-level fields whose value a write must not decide by accident."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_a, cls.product_b = cls.env['product.product'].create([
            {'name': "Trigger A", 'type': 'consu'},
            {'name': "Trigger B", 'type': 'consu'},
        ])

    def test_program_without_a_company_gets_a_currency(self):
        """A program left "Visible to all" still has the required currency.

        `company_id` is optional and the form offers a blank one; `currency_id` is
        required, and computing it from the empty company used to write a null.
        """
        program = self.env['loyalty.program'].create({
            'name': "No company",
            'company_id': False,
            'reward_ids': [Command.create({})],
        })
        self.env.flush_all()

        self.assertFalse(program.company_id)
        self.assertEqual(program.currency_id, self.env.company.currency_id)

    def test_trigger_products_are_ignored_off_the_payment_forms(self):
        """Writing `trigger_product_ids` elsewhere must not rewrite the rule's products.

        It is related to `rule_ids.product_ids`, and only the gift card and eWallet
        forms show it. `create` already dropped it; `write` let it through and
        replaced the products of every rule of the program.
        """
        program = self.env['loyalty.program'].create({
            'name': "Promotion",
            'program_type': 'promotion',
            'rule_ids': [Command.create({'product_ids': [Command.set(self.product_a.ids)]})],
        })

        program.write({'trigger_product_ids': [Command.set(self.product_b.ids)]})

        self.assertEqual(program.rule_ids.product_ids, self.product_a)

    def test_trigger_products_still_apply_to_a_gift_card(self):
        """The gift card form keeps writing through to its rule."""
        program = self.env['loyalty.program'].create({'name': "Gift"})
        program.write({'program_type': 'gift_card'})
        self.env.flush_all()
        self.assertTrue(program.rule_ids, "the gift card type builds a trigger rule")

        program.write({'trigger_product_ids': [Command.set(self.product_b.ids)]})

        self.assertEqual(program.rule_ids.product_ids, self.product_b)

    def test_trigger_products_over_a_mixed_batch(self):
        """A batch of both kinds writes it only where it belongs."""
        gift = self.env['loyalty.program'].create({'name': "Gift batch"})
        gift.write({'program_type': 'gift_card'})
        promo = self.env['loyalty.program'].create({
            'name': "Promo batch",
            'program_type': 'promotion',
            'rule_ids': [Command.create({'product_ids': [Command.set(self.product_a.ids)]})],
            'reward_ids': [Command.create({})],
        })
        self.env.flush_all()

        (gift + promo).write({'trigger_product_ids': [Command.set(self.product_b.ids)]})

        self.assertEqual(gift.rule_ids.product_ids, self.product_b)
        self.assertEqual(promo.rule_ids.product_ids, self.product_a)

    def test_create_does_not_edit_the_caller_s_values(self):
        """`create` drops `trigger_product_ids` without mutating the caller's dict."""
        vals_list = [{
            'name': "Caller owned",
            'program_type': 'promotion',
            'trigger_product_ids': [Command.set(self.product_a.ids)],
            'reward_ids': [Command.create({})],
        }]

        self.env['loyalty.program'].create(vals_list)

        self.assertIn('trigger_product_ids', vals_list[0])

    def test_constraints_raise_validation_errors(self):
        """The program's `@api.constrains` report as validation, not as a user error.

        A `UserError` here is not caught by the ORM's constraint handling and is not
        what any caller of a constrained write expects.
        """
        with self.assertRaises(ValidationError):
            self.env['loyalty.program'].create({
                'name': "Backwards",
                'date_from': '2030-01-02',
                'date_to': '2030-01-01',
                'reward_ids': [Command.create({})],
            })

    def test_coupon_count_label_names_the_items(self):
        """One source names the cards: the stat button, the list and the action."""
        program = self.env['loyalty.program'].create({
            'name': "Named", 'program_type': 'gift_card',
        })
        items_name = self.env['loyalty.program']._program_items_name()['gift_card']

        self.assertEqual(program.coupon_count_label, items_name)
        self.assertEqual(program.coupon_count_display, f"0 {items_name}")
        self.assertEqual(program.action_open_loyalty_cards()['name'], items_name)
