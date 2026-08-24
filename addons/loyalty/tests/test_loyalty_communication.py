# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyCommunication(TransactionCase):
    """The mails a program sends, and what sending them costs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env['mail.template'].create({
            'name': "Coupon mail",
            'model_id': cls.env.ref('loyalty.model_loyalty_card').id,
            'subject': "Your coupon",
            'body_html': "<p>Here it is</p>",
            'auto_delete': False,
        })

    def _program(self, **plan_values):
        return self.env['loyalty.program'].create({
            'name': "Communication",
            'reward_ids': [Command.create({})],
            'communication_plan_ids': [Command.create(
                {'mail_template_id': self.template.id, **plan_values}
            )],
        })

    def _holders(self, count, prefix):
        return self.env['res.partner'].create([
            {'name': f"{prefix} {index}", 'email': f"{prefix}{index}@example.com"}
            for index in range(count)
        ])

    def _issue(self, program, holders):
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        cards = self.env['loyalty.card'].create([
            {'program_id': program.id, 'partner_id': holder.id, 'points': 1}
            for holder in holders
        ])
        self.env.flush_all()
        return self.env.cr.sql_log_count - before, cards

    def _mails_for(self, cards):
        return self.env['mail.mail'].sudo().search([
            ('model', '=', 'loyalty.card'), ('res_id', 'in', cards.ids),
        ])

    def test_one_creation_mail_per_coupon(self):
        """Batching must not cost anyone their mail."""
        program = self._program(trigger='create')
        holders = self._holders(5, "Creation")

        _queries, cards = self._issue(program, holders)

        self.assertEqual(len(self._mails_for(cards)), 5)

    def test_creation_mail_is_sent_in_batches(self):
        """It used to be one `send_mail` per coupon, at about seven queries each."""
        program = self._program(trigger='create')
        self._issue(program, self._holders(2, "Warm"))

        small, _ = self._issue(program, self._holders(2, "Small"))
        large, _ = self._issue(program, self._holders(20, "Large"))

        marginal = (large - small) / 18
        self.assertLess(
            marginal, 2,
            f"a coupon's creation mail should cost well under two queries; measured"
            f" {marginal:.2f} ({small} for 2, {large} for 20)",
        )

    def test_a_coupon_with_no_customer_gets_no_mail(self):
        """Grouping by sender must not sweep in an unheld coupon."""
        program = self._program(trigger='create')
        cards = self.env['loyalty.card'].create([
            {'program_id': program.id, 'points': 1} for _ in range(3)
        ])
        self.env.flush_all()

        self.assertFalse(self._mails_for(cards))

    def test_only_the_highest_milestone_reached_is_sent(self):
        """A card that jumps past two milestones gets one mail, for the higher."""
        second_template = self.template.copy({'name': "Second milestone"})
        program = self.env['loyalty.program'].create({
            'name': "Milestones",
            'reward_ids': [Command.create({})],
            'communication_plan_ids': [
                Command.create({
                    'trigger': 'points_reach', 'points': 50,
                    'mail_template_id': self.template.id,
                }),
                Command.create({
                    'trigger': 'points_reach', 'points': 100,
                    'mail_template_id': second_template.id,
                }),
            ],
        })
        holder = self._holders(1, "Milestone")
        card = self.env['loyalty.card'].with_context(loyalty_no_mail=True).create(
            {'program_id': program.id, 'partner_id': holder.id, 'points': 0}
        )
        self.env.flush_all()

        self.env['loyalty.card'].browse(card.id).write({'points': 150})
        self.env.flush_all()

        mails = self._mails_for(card)
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.subject, second_template.subject)

    def test_milestone_mail_is_sent_in_batches(self):
        """The same batching for the 'When Reaching' plans."""
        program = self._program(trigger='points_reach', points=50)

        def cross(count, prefix):
            holders = self._holders(count, prefix)
            cards = self.env['loyalty.card'].with_context(loyalty_no_mail=True).create([
                {'program_id': program.id, 'partner_id': holder.id, 'points': 0}
                for holder in holders
            ])
            self.env.flush_all()
            self.env.invalidate_all()
            live = self.env['loyalty.card'].browse(cards.ids)
            before = self.env.cr.sql_log_count
            live.write({'points': 60})
            self.env.flush_all()
            return self.env.cr.sql_log_count - before, cards

        cross(2, "MWarm")
        small, _ = cross(2, "MSmall")
        large, crossed = cross(20, "MLarge")

        self.assertLess((large - small) / 18, 2, f"{small} for 2, {large} for 20")
        self.assertEqual(len(self._mails_for(crossed)), 20)

    def test_loyalty_no_mail_still_silences_both(self):
        """The escape hatch the sale and PoS flows rely on."""
        program = self._program(trigger='create')
        holders = self._holders(3, "Silent")
        cards = self.env['loyalty.card'].with_context(loyalty_no_mail=True).create([
            {'program_id': program.id, 'partner_id': holder.id, 'points': 1}
            for holder in holders
        ])
        self.env.flush_all()

        self.assertFalse(self._mails_for(cards))
