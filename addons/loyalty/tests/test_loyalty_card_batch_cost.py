# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyCardBatchCost(TransactionCase):
    """What issuing N cards costs, measured as a marginal cost rather than a total.

    An absolute `assertQueryCount` at N=1 cannot see an N+1 in a batch path at all,
    and one at a single larger N cannot tell a per-record cost from a fixed setup
    cost. Both sizes are measured here so a warm cache cannot make the comparison
    vacuous.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env['loyalty.program'].create({
            'name': "Batch cost", 'reward_ids': [Command.create({})],
        })

    def _queries_to_issue(self, count):
        partners = self.env['res.partner'].create(
            [{'name': f"Holder {index}"} for index in range(count)]
        )
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        self.env['loyalty.card'].with_context(loyalty_no_mail=True).create([
            {'program_id': self.program.id, 'partner_id': partner.id, 'points': 1}
            for partner in partners
        ])
        self.env.flush_all()
        return self.env.cr.sql_log_count - before

    def test_issuing_cards_costs_one_batch(self):
        """Creating cards is batched: 18 more cards must not cost 18 more queries.

        The mail path is excluded on purpose -- an "At Creation" communication plan
        sends one mail per card and costs roughly seven queries each, which is known,
        recorded, and not what this test measures.
        """
        self._queries_to_issue(2)  # warm the registry, the defaults and the company

        small = self._queries_to_issue(2)
        large = self._queries_to_issue(20)

        marginal = (large - small) / 18
        self.assertLess(
            marginal, 1,
            f"issuing a card should cost well under one query each; measured"
            f" {marginal:.2f} ({small} queries for 2, {large} for 20)",
        )
