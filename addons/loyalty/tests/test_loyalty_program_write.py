# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyProgramWrite(TransactionCase):
    """`loyalty.program.write` over more than one program at a time."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.programs = cls.env['loyalty.program'].create([
            {'name': "Batch A", 'reward_ids': [Command.create({})]},
            {'name': "Batch B", 'reward_ids': [Command.create({})]},
        ])

    def test_program_type_change_on_a_batch(self):
        """Changing the type of several programs at once recreates each one's rewards.

        `_compute_from_program_type` groups the programs by type and writes the
        defaults to the whole group, so a batch reaches `write` with `reward_ids` in
        the values; deciding whether they leave a reward used to need a singleton.
        """
        self.env.flush_all()
        self.programs.write({'program_type': 'coupons'})
        self.env.flush_all()

        self.assertEqual(set(self.programs.mapped('program_type')), {'coupons'})
        for program in self.programs:
            self.assertTrue(program.reward_ids, "each program keeps a reward")

    def test_deferred_program_type_recompute_on_a_batch(self):
        """The same, reached through a deferred recompute rather than a direct write."""
        self.env.flush_all()
        self.programs.program_type = 'promo_code'
        self.env.flush_all()

        self.assertEqual(set(self.programs.mapped('program_type')), {'promo_code'})

    def test_a_batch_of_code_programs_gets_a_code_each(self):
        """Two programs of a coded type do not take the same trigger code.

        `_program_type_default_values` is one dict written to the whole group, so a
        code baked into it was the same code for every program in that group -- and
        the second one hit `loyalty.rule`'s uniqueness constraint.
        """
        # Created without a type and switched afterwards: `create` with an explicit
        # `program_type` builds no rule at all -- see `_compute_from_program_type`.
        programs = self.env['loyalty.program'].create([
            {'name': "Coded A"},
            {'name': "Coded B"},
        ])
        self.env.flush_all()
        programs.write({'program_type': 'promo_code'})
        self.env.flush_all()

        codes = programs.rule_ids.mapped('code')
        self.assertEqual(len(codes), 2)
        self.assertTrue(all(codes), "each rule carries a code")
        self.assertEqual(len(set(codes)), 2, "and the two differ")

    def test_switching_a_batch_to_a_coded_type(self):
        """The same reached by changing the type of several programs at once."""
        self.env.flush_all()
        self.programs.write({'program_type': 'promo_code'})
        self.env.flush_all()

        codes = self.programs.rule_ids.mapped('code')
        self.assertEqual(len(set(codes)), 2)

    def test_a_rule_switched_to_with_code_gets_one(self):
        """A rule the user switches to "With a promotion code" is given one."""
        program = self.env['loyalty.program'].create({'name': "Auto rule"})
        self.env.flush_all()
        self.assertEqual(program.program_type, 'promotion')
        self.assertFalse(program.rule_ids.code)

        program.rule_ids.mode = 'with_code'

        self.assertTrue(program.rule_ids.code)

    def test_an_explicit_code_is_kept(self):
        """Generating one never overwrites a code the caller gave."""
        program = self.env['loyalty.program'].create({
            'name': "Explicit",
            'program_type': 'promo_code',
            'rule_ids': [Command.create({'code': "KEEPME", 'minimum_amount': 0})],
            'reward_ids': [Command.create({})],
        })
        self.env.flush_all()

        self.assertEqual(program.rule_ids.code, "KEEPME")

    def test_writing_reward_ids_on_a_batch(self):
        """`reward_ids` commands written to several programs at once."""
        self.programs.write({'reward_ids': [Command.create({'discount': 5})]})

        for program in self.programs:
            self.assertEqual(len(program.reward_ids), 2)

    def test_clearing_the_rewards_of_a_batch_is_still_refused(self):
        """Leaving a program with no reward is refused, batch or not.

        The skip that makes the type change possible must not swallow this.
        """
        with self.assertRaises(ValidationError):
            self.programs.write({'reward_ids': [Command.clear()]})
            self.env.flush_all()

    def test_commands_leave_a_reward(self):
        """The command reading behind the skip, over each shape it must answer."""
        leaves = self.env['loyalty.program']._commands_leave_a_reward
        self.assertTrue(leaves([Command.clear(), Command.create({})]), "cleared then recreated")
        self.assertTrue(leaves([Command.set([1, 2])]), "set to two rewards")
        self.assertTrue(leaves([Command.link(1)]))
        self.assertTrue(leaves([{'discount': 5}]), "a bare dict of values")
        self.assertFalse(leaves([Command.clear()]), "cleared and not refilled")
        self.assertFalse(leaves([Command.set([])]), "set to nothing")
        self.assertFalse(leaves([Command.clear(), Command.create({}), Command.unlink(1)]))
        self.assertFalse(leaves([]), "no command at all")
        self.assertFalse(
            leaves([Command.unlink(1)]),
            "an unknown starting count answers False, so the constraint runs",
        )
        self.assertFalse(
            leaves([Command.update(1, {'discount': 5})]),
            "an update creates no reward, so the constraint runs",
        )
