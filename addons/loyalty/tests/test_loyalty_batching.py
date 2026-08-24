# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyBatching(TransactionCase):
    """Work that used to cost one query per record.

    Every case is measured as a marginal cost at two sizes: an absolute count at
    one size cannot tell a per-record cost from a fixed setup cost, and cannot see
    an N+1 at all.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'loyalty.compute_all_discount_product_ids', 'enabled'
        )
        cls.program = cls.env['loyalty.program'].create({'name': "Batching"})
        cls.products = cls.env['product.product'].create(
            [{'name': f"Batched {index}", 'type': 'consu'} for index in range(3)]
        )

    def _rewards(self, count):
        return self.env['loyalty.reward'].create([
            {
                'program_id': self.program.id,
                'discount_applicability': 'specific',
                'discount_product_ids': [Command.set(self.products.ids[:1])],
            }
            for _ in range(count)
        ])

    def _queries(self, operation):
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        operation()
        self.env.flush_all()
        return self.env.cr.sql_log_count - before

    def test_resolving_discounted_products_costs_one_search(self):
        """`all_discount_product_ids` used to search once per reward."""
        small, large = self._rewards(2), self._rewards(20)
        self._queries(lambda: small.mapped('all_discount_product_ids'))

        cheap = self._queries(lambda: small.mapped('all_discount_product_ids'))
        dear = self._queries(lambda: large.mapped('all_discount_product_ids'))

        self.assertLess(
            (dear - cheap) / 18, 0.5,
            f"18 more rewards should not cost 18 more searches ({cheap} for 2,"
            f" {dear} for 20)",
        )

    def test_the_batched_products_are_the_ones_a_search_would_find(self):
        """Cheaper is worthless if it answers differently.

        The batch searches the union of the rewards' domains and applies each
        reward's own domain in memory, so it has to agree with a per-reward search
        for every shape a reward can carry.
        """
        category = self.env['product.category'].create({'name': "Batched cat"})
        child = self.env['product.category'].create(
            {'name': "Batched child", 'parent_id': category.id}
        )
        tag = self.env['product.tag'].create({'name': "Batched tag"})
        deep = self.env['product.product'].create(
            {'name': "Deep", 'type': 'consu', 'categ_id': child.id}
        )
        self.products[1].product_tag_ids = tag

        rewards = self.env['loyalty.reward'].create([
            {'program_id': self.program.id, 'discount_applicability': 'specific',
             'discount_product_ids': [Command.set(self.products.ids[:1])]},
            {'program_id': self.program.id, 'discount_applicability': 'specific',
             'discount_product_category_id': category.id},
            {'program_id': self.program.id, 'discount_applicability': 'specific',
             'discount_product_tag_id': tag.id},
            {'program_id': self.program.id, 'discount_applicability': 'specific',
             'discount_product_domain': "[('name', 'like', 'Batched')]"},
            {'program_id': self.program.id, 'discount_applicability': 'specific'},
        ])

        batched = rewards._get_discount_products()

        for reward in rewards:
            with self.subTest(reward=reward.id):
                searched = self.env['product.product'].search(
                    reward._get_discount_product_domain()
                )
                self.assertEqual(batched[reward], searched)
        self.assertIn(deep, batched[rewards[1]], "the category reaches its subtree")

    def _product_searches(self, operation):
        """Count the statements that read `product_product` while `operation` runs."""
        self.env.flush_all()
        self.env.invalidate_all()
        cursor = self.env.cr
        executed = []
        original = cursor.execute

        def spy(query, params=None, *args, **kwargs):
            executed.append(str(query))
            return original(query, params, *args, **kwargs)

        cursor.execute = spy
        try:
            operation()
            self.env.flush_all()
        finally:
            cursor.execute = original
        return sum('FROM "product_product"' in query for query in executed)

    def test_describing_rewards_reads_the_products_once(self):
        """Naming the single product a reward discounts used to search per reward.

        Counted as reads of `product_product` rather than as a total: recomputing
        `description` still costs one UPDATE per reward, because the field is
        `translate=True` and stored, and that is a separate question from the search
        this batches.
        """
        small, large = self._rewards(2), self._rewards(20)
        self._product_searches(lambda: small.write({'discount': 3}))

        cheap = self._product_searches(lambda: small.write({'discount': 4}))
        dear = self._product_searches(lambda: large.write({'discount': 4}))

        self.assertEqual(
            cheap, dear,
            f"reading the discounted products must not grow with the number of"
            f" rewards ({cheap} reads for 2, {dear} for 20)",
        )
        self.assertEqual(large[0].description, "4% on Batched 0")

    def test_recomputing_descriptions_stays_linear_in_writes_only(self):
        """What is left after the search is batched: one UPDATE per reward.

        Recorded rather than fixed. `description` is a stored `translate=True` field
        whose value this module computes, so each row's jsonb is written on its own.
        """
        small, large = self._rewards(2), self._rewards(20)
        self._queries(lambda: small.write({'discount': 5}))

        cheap = self._queries(lambda: small.write({'discount': 6}))
        dear = self._queries(lambda: large.write({'discount': 6}))

        self.assertLessEqual(
            (dear - cheap) / 18, 1.1,
            f"one write per reward and no more ({cheap} for 2, {dear} for 20)",
        )

    def test_the_discount_product_switch_reads_one_vocabulary(self):
        """The parameter is an on/off flag, and its shipped value means off."""
        Param = self.env['ir.config_parameter'].sudo()
        reward = self._rewards(1)

        for value, expanded in (
            ('enabled', True), ('True', True), ('1', True),
            ('False', False), ('', False), ('disabled', False),
        ):
            with self.subTest(value=value):
                Param.set_param('loyalty.compute_all_discount_product_ids', value)
                self.assertEqual(reward._expands_discount_products(), expanded)
