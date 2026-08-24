# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyDescription(TransactionCase):
    """`loyalty.reward.description` is generated *and* translated.

    Writing a translated field under the session's language also writes the source
    term when the record has no source yet, so building the string with `_()` under
    a Spanish session stored Spanish as `en_US` — making every reward's English
    description Spanish, and every language without its own translation fall back
    to it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.spanish = cls.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', 'es_ES')]
        )
        if cls.spanish:
            cls.spanish.active = True
            cls.env['ir.module.module'].search(
                [('name', '=', 'loyalty')]
            )._update_translations(['es_ES'])
            cls.env.flush_all()

    def _stored(self, reward):
        """Return the raw jsonb behind `description`, not one language's view of it."""
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT description FROM loyalty_reward WHERE id = %s", (reward.id,)
        )
        return self.env.cr.fetchone()[0]

    def _reward(self, env=None):
        return (env or self.env)['loyalty.program'].create({
            'name': "Described", 'reward_ids': [Command.create({'discount': 10})],
        }).reward_ids

    def test_the_source_term_is_the_source_language(self):
        """Creating a reward in Spanish must not make its English text Spanish."""
        if not self.spanish:
            self.skipTest("es_ES is not available in this database")

        reward = self._reward(self.env['loyalty.program'].with_context(lang='es_ES').env)

        self.assertEqual(self._stored(reward)['en_US'], "10% on your order")

    def test_each_language_gets_its_own_text_on_recompute(self):
        """And a recompute fills every installed language, not just the session's."""
        if not self.spanish:
            self.skipTest("es_ES is not available in this database")
        reward = self._reward()

        reward.with_context(lang='es_ES').discount = 55

        stored = self._stored(reward)
        self.assertEqual(stored['en_US'], "55% on your order")
        self.assertNotEqual(
            stored['es_ES'], stored['en_US'],
            "the Spanish text should be Spanish, not a copy of the source",
        )
        self.assertEqual(reward.with_context(lang='en_US').description, stored['en_US'])
        self.assertEqual(reward.with_context(lang='es_ES').description, stored['es_ES'])

    def test_a_single_language_database_is_unaffected(self):
        """The common case still writes one term and nothing else."""
        reward = self._reward()

        reward.discount = 20

        self.assertEqual(reward.description, "20% on your order")
        self.assertEqual(self._stored(reward)['en_US'], "20% on your order")

    def test_the_description_names_one_specific_product(self):
        """The content the batched product lookup feeds."""
        product = self.env['product.product'].create({'name': "Only one", 'type': 'consu'})
        reward = self._reward()

        reward.write({
            'discount_applicability': 'specific',
            'discount_product_ids': [Command.set(product.ids)],
        })

        self.assertEqual(reward.description, "10% on Only one")
