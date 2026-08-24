# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyProgramTypeChildren(TransactionCase):
    """What a program is given when it is created with a `program_type`.

    `default_get` supplies the rules, rewards and communication plans of a type --
    but it is only asked for `program_type` when the caller left it out, so
    `create` with an explicit type used to produce a program with none of the
    three, and the "at least one reward" constraint did not fire because
    `reward_ids` was never in the values.
    """

    def test_an_explicit_type_still_gets_its_children(self):
        """The defect: a type named in `create` produced an empty program."""
        program = self.env['loyalty.program'].create({
            'name': "Gift", 'program_type': 'gift_card',
        })
        self.env.flush_all()

        self.assertEqual(len(program.rule_ids), 1)
        self.assertEqual(len(program.reward_ids), 1)
        self.assertEqual(len(program.communication_plan_ids), 1)
        self.assertEqual(
            program.rule_ids.product_ids, self.env.ref('loyalty.gift_card_product_50')
        )

    def test_an_omitted_type_is_unchanged(self):
        """The path `default_get` already covered answers the same as before."""
        program = self.env['loyalty.program'].create({'name': "Default"})
        self.env.flush_all()

        self.assertEqual(program.program_type, 'promotion')
        self.assertEqual(len(program.rule_ids), 1)
        self.assertEqual(len(program.reward_ids), 1)
        self.assertFalse(program.communication_plan_ids)

    def test_each_child_is_defaulted_on_its_own(self):
        """Supplying one child does not suppress the others."""
        product = self.env['product.product'].create({'name': "Own", 'type': 'consu'})
        program = self.env['loyalty.program'].create({
            'name': "Half own",
            'program_type': 'gift_card',
            'rule_ids': [Command.create({'product_ids': [Command.set(product.ids)]})],
        })
        self.env.flush_all()

        self.assertEqual(program.rule_ids.product_ids, product, "the caller's rule wins")
        self.assertEqual(len(program.reward_ids), 1, "and the reward is still defaulted")

    def test_a_type_that_contributes_no_rule_gets_none(self):
        """`coupons` deliberately has no rule; it must not be given one."""
        program = self.env['loyalty.program'].create({
            'name': "Coupons", 'program_type': 'coupons',
        })
        self.env.flush_all()

        self.assertFalse(program.rule_ids)
        self.assertEqual(len(program.reward_ids), 1)
        self.assertEqual(len(program.communication_plan_ids), 1)

    def test_every_type_creates_a_valid_program(self):
        """No program type may produce a program its own constraint forbids."""
        types = dict(self.env['loyalty.program']._fields['program_type'].selection)
        for program_type in types:
            with self.subTest(program_type=program_type):
                program = self.env['loyalty.program'].create({
                    'name': f"Every {program_type}", 'program_type': program_type,
                })
                self.env.flush_all()
                self.assertTrue(
                    program.reward_ids,
                    "a program must have at least one reward, and its own defaults"
                    " have to satisfy that",
                )

    def test_the_shipped_gift_card_program_has_one_of_each(self):
        """The data file must not re-declare what the defaults already build.

        A second reward on the gift card program is what `pos_loyalty` refuses to
        open a session with.
        """
        program = self.env.ref('loyalty.gift_card_program')

        self.assertEqual(len(program.rule_ids), 1)
        self.assertEqual(len(program.reward_ids), 1)
        self.assertEqual(len(program.communication_plan_ids), 1)

    def test_clearing_the_children_explicitly_is_still_refused(self):
        """Asking for no reward is an error, not something `create` papers over."""
        with self.assertRaises(ValidationError):
            self.env['loyalty.program'].create({
                'name': "Empty", 'program_type': 'promotion',
                'reward_ids': [Command.clear()],
            })
            self.env.flush_all()

    def test_the_defaults_split_answers_per_type(self):
        """`_program_type_default_values` is assembled from one method per type."""
        Program = self.env['loyalty.program']
        assembled = Program._program_type_default_values()
        product = self.env['product.product'].search([('sale_ok', '=', True)], limit=1)

        for program_type in assembled:
            with self.subTest(program_type=program_type):
                own = getattr(Program, f'_{program_type}_default_values')(product)
                self.assertEqual(set(own), set(assembled[program_type]))
