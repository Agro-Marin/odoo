# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyRewardDomain(TransactionCase):
    """The two representations of a reward's discounted products."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Set once, here: `set_param` invalidates the cache, and these tests are
        # about what the ORM invalidates on its own.
        cls.env['ir.config_parameter'].sudo().set_param(
            'loyalty.compute_all_discount_product_ids', 'disabled'
        )
        cls.program = cls.env['loyalty.program'].create({
            'name': "Domain program", 'reward_ids': [Command.create({})],
        })
        cls.reward = cls.program.reward_ids
        cls.reward.discount_applicability = 'specific'
        cls.product = cls.env['product.product'].create({'name': "Discounted", 'type': 'consu'})

    def _serialized_domain(self):
        """Read the domain the PoS would be handed, invalidating nothing.

        Deliberately no `invalidate_recordset`: `reward_product_domain` is a
        non-stored compute, so invalidating it recomputes it whatever its
        `@api.depends` says — which is how the first version of these tests passed
        against the very bug they were written for.
        """
        return json.loads(self.reward.reward_product_domain)

    def test_domain_follows_the_products(self):
        """Setting the reward's products changes the domain the PoS evaluates.

        `reward_product_domain` depended on `discount_product_domain` alone, so it
        kept answering "every product" after the reward was narrowed.
        """
        before = self._serialized_domain()
        self.reward.discount_product_ids = [Command.set(self.product.ids)]
        after = self._serialized_domain()

        self.assertNotEqual(before, after)
        self.assertIn(str(self.product.id), json.dumps(after))

    def test_domain_follows_the_category(self):
        """The same for the reward's product category."""
        category = self.env['product.category'].create({'name': "Discounted category"})
        before = self._serialized_domain()
        self.reward.discount_product_category_id = category
        after = self._serialized_domain()

        self.assertNotEqual(before, after)

    def test_domain_follows_the_tag(self):
        """The same for the reward's product tag."""
        tag = self.env['product.tag'].create({'name': "Discounted tag"})
        before = self._serialized_domain()
        self.reward.discount_product_tag_id = tag
        after = self._serialized_domain()

        self.assertNotEqual(before, after)

    def test_the_domain_stays_evaluable_in_the_browser(self):
        """No hierarchical operator may reach the serialised domain.

        `@web/core/domain` compiles `child_of` and `parent_of` to `() => true`, so a
        PoS discount stated that way would apply to the whole catalogue. This is why
        the category is expanded here and not on `loyalty.rule`, which is read by the
        server alone.
        """
        parent = self.env['product.category'].create({'name': "Parent"})
        self.env['product.category'].create({'name': "Child", 'parent_id': parent.id})
        self.reward.discount_product_category_id = parent

        serialized = json.dumps(self._serialized_domain())

        self.assertNotIn('child_of', serialized)
        self.assertNotIn('parent_of', serialized)

    def test_the_expanded_category_covers_every_descendant(self):
        """Expanding the category must reach the whole subtree, not one level."""
        root = self.env['product.category'].create({'name': "Root"})
        mid = self.env['product.category'].create({'name': "Mid", 'parent_id': root.id})
        leaf = self.env['product.category'].create({'name': "Leaf", 'parent_id': mid.id})
        deep_product = self.env['product.product'].create(
            {'name': "Deep", 'type': 'consu', 'categ_id': leaf.id}
        )
        self.reward.discount_product_category_id = root

        matched = self.env['product.product'].search(self.reward._get_discount_product_domain())

        self.assertIn(deep_product, matched)

    def test_only_one_representation_is_filled_in(self):
        """The two are alternatives: the id list or the domain, never both.

        This one invalidates on purpose — the config parameter is not a field, so
        nothing tracks it; the invalidation is the parameter change, not the test
        papering over a missing dependency.
        """
        Param = self.env['ir.config_parameter'].sudo()
        self.reward.discount_product_ids = [Command.set(self.product.ids)]

        Param.set_param('loyalty.compute_all_discount_product_ids', 'enabled')
        self.reward.invalidate_recordset(['all_discount_product_ids', 'reward_product_domain'])
        self.assertEqual(self.reward.all_discount_product_ids, self.product)
        self.assertEqual(self.reward.reward_product_domain, "null")

        Param.set_param('loyalty.compute_all_discount_product_ids', 'disabled')
        self.reward.invalidate_recordset(['all_discount_product_ids', 'reward_product_domain'])
        self.assertFalse(self.reward.all_discount_product_ids)
        self.assertNotEqual(self.reward.reward_product_domain, "null")

    def test_a_stale_domain_would_be_observable(self):
        """Guard on `_serialized_domain`: it must be able to return a stale value.

        The three dependency tests above are only worth anything if reading the
        domain caches it and writing a dependency is what drops it again. The first
        version of them invalidated the field by hand and so passed against the very
        bug they were written for; this fails if that ever comes back.
        """
        field = self.reward._fields['reward_product_domain']

        self._serialized_domain()
        self.assertTrue(
            self.env.cache.contains(self.reward, field),
            "reading the domain must cache it, or a stale read is impossible to see",
        )

        self.reward.discount_product_ids = [Command.set(self.product.ids)]
        self.assertFalse(
            self.env.cache.contains(self.reward, field),
            "writing a dependency must drop the cached domain",
        )

    def test_reward_product_uom_follows_the_reward_type(self):
        """A reward that stops being a free product stops carrying a unit.

        The unit depended on the product and the tag but read `reward_product_ids`,
        which is empty for anything but a product reward.
        """
        product_reward = self.env['loyalty.reward'].create({
            'program_id': self.program.id,
            'reward_type': 'product',
            'reward_product_id': self.product.id,
        })
        self.assertTrue(product_reward.reward_product_uom_id)

        product_reward.reward_type = 'discount'

        self.assertFalse(product_reward.reward_product_ids)
        self.assertFalse(product_reward.reward_product_uom_id)
