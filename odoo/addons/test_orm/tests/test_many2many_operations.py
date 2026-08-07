from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestMany2manyCommands(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "M2M Alpha"})
        cls.cat_b = Category.create({"name": "M2M Beta"})
        cls.cat_c = Category.create({"name": "M2M Gamma"})

    def _make_discussion(self, **kwargs):
        vals = {"name": "Test M2M Discussion"}
        vals.update(kwargs)
        return self.env["test_orm.discussion"].create(vals)

    def test_link_command(self):
        disc = self._make_discussion(categories=[Command.link(self.cat_a.id)])
        self.assertEqual(disc.categories, self.cat_a)

        disc.write({"categories": [Command.link(self.cat_b.id)]})
        self.assertEqual(disc.categories, self.cat_a | self.cat_b)

    def test_link_duplicate(self):
        disc = self._make_discussion(categories=[Command.link(self.cat_a.id)])
        disc.write({"categories": [Command.link(self.cat_a.id)]})
        self.assertEqual(len(disc.categories), 1)
        self.assertEqual(disc.categories, self.cat_a)

    def test_link_multiple(self):
        disc = self._make_discussion(
            categories=[
                Command.link(self.cat_a.id),
                Command.link(self.cat_b.id),
                Command.link(self.cat_c.id),
            ]
        )
        self.assertEqual(len(disc.categories), 3)

    def test_unlink_command(self):
        disc = self._make_discussion(
            categories=[
                Command.link(self.cat_a.id),
                Command.link(self.cat_b.id),
            ]
        )
        disc.write({"categories": [Command.unlink(self.cat_a.id)]})
        self.assertEqual(disc.categories, self.cat_b)

    def test_unlink_nonexistent(self):
        disc = self._make_discussion(categories=[Command.link(self.cat_a.id)])
        disc.write({"categories": [Command.unlink(self.cat_c.id)]})
        self.assertEqual(disc.categories, self.cat_a)

    def test_clear_command(self):
        disc = self._make_discussion(
            categories=[
                Command.link(self.cat_a.id),
                Command.link(self.cat_b.id),
                Command.link(self.cat_c.id),
            ]
        )
        disc.write({"categories": [Command.clear()]})
        self.assertFalse(disc.categories)

    def test_clear_empty(self):
        disc = self._make_discussion()
        disc.write({"categories": [Command.clear()]})
        self.assertFalse(disc.categories)

    def test_set_command(self):
        disc = self._make_discussion(categories=[Command.link(self.cat_a.id)])
        disc.write({"categories": [Command.set([self.cat_b.id, self.cat_c.id])]})
        self.assertEqual(disc.categories, self.cat_b | self.cat_c)
        self.assertNotIn(self.cat_a, disc.categories)

    def test_set_empty(self):
        disc = self._make_discussion(
            categories=[
                Command.link(self.cat_a.id),
                Command.link(self.cat_b.id),
            ]
        )
        disc.write({"categories": [Command.set([])]})
        self.assertFalse(disc.categories)

    def test_set_idempotent(self):
        disc = self._make_discussion(
            categories=[
                Command.link(self.cat_a.id),
                Command.link(self.cat_b.id),
            ]
        )
        disc.write({"categories": [Command.set([self.cat_a.id, self.cat_b.id])]})
        self.assertEqual(disc.categories, self.cat_a | self.cat_b)

    def test_create_command(self):
        disc = self._make_discussion(
            categories=[
                Command.create({"name": "Created Cat"}),
            ]
        )
        self.assertEqual(len(disc.categories), 1)
        self.assertEqual(disc.categories.name, "Created Cat")

    def test_create_multiple(self):
        disc = self._make_discussion(
            categories=[
                Command.create({"name": "Cat X"}),
                Command.create({"name": "Cat Y"}),
            ]
        )
        self.assertEqual(len(disc.categories), 2)
        self.assertEqual(set(disc.categories.mapped("name")), {"Cat X", "Cat Y"})

    def test_delete_command(self):
        cat_temp = self.env["test_orm.category"].create({"name": "Temporary"})
        disc = self._make_discussion(categories=[Command.link(cat_temp.id)])
        disc.write({"categories": [Command.delete(cat_temp.id)]})
        self.assertFalse(disc.categories)
        self.assertFalse(cat_temp.exists())

    def test_combined_commands(self):
        disc = self._make_discussion(
            categories=[
                Command.link(self.cat_a.id),
                Command.link(self.cat_b.id),
            ]
        )
        disc.write(
            {
                "categories": [
                    Command.unlink(self.cat_a.id),
                    Command.link(self.cat_c.id),
                ]
            }
        )
        self.assertEqual(disc.categories, self.cat_b | self.cat_c)

    def test_create_with_m2m(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Created with M2M",
                "categories": [Command.set([self.cat_a.id, self.cat_b.id])],
            }
        )
        self.assertEqual(len(disc.categories), 2)

    def test_create_multiple_with_m2m(self):
        records = self.env["test_orm.discussion"].create(
            [
                {
                    "name": "Batch 1",
                    "categories": [Command.link(self.cat_a.id)],
                },
                {
                    "name": "Batch 2",
                    "categories": [Command.link(self.cat_b.id)],
                },
            ]
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].categories, self.cat_a)
        self.assertEqual(records[1].categories, self.cat_b)


class TestMany2manySearch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "Search A"})
        cls.cat_b = Category.create({"name": "Search B"})

        Discussion = cls.env["test_orm.discussion"]
        cls.disc_with_a = Discussion.create(
            {
                "name": "Has A",
                "categories": [Command.link(cls.cat_a.id)],
            }
        )
        cls.disc_with_b = Discussion.create(
            {
                "name": "Has B",
                "categories": [Command.link(cls.cat_b.id)],
            }
        )
        cls.disc_with_both = Discussion.create(
            {
                "name": "Has Both",
                "categories": [Command.set([cls.cat_a.id, cls.cat_b.id])],
            }
        )
        cls.disc_empty = Discussion.create({"name": "Has None"})

    def test_search_in(self):
        result = self.env["test_orm.discussion"].search(
            [
                ("categories", "in", self.cat_a.ids),
            ]
        )
        self.assertIn(self.disc_with_a, result)
        self.assertIn(self.disc_with_both, result)
        self.assertNotIn(self.disc_with_b, result)
        self.assertNotIn(self.disc_empty, result)

    def test_search_not_in(self):
        result = self.env["test_orm.discussion"].search(
            [
                ("categories", "not in", self.cat_a.ids),
            ]
        )
        self.assertNotIn(self.disc_with_a, result)
        self.assertNotIn(self.disc_with_both, result)

    def test_search_equal_false(self):
        result = self.env["test_orm.discussion"].search(
            [
                ("categories", "=", False),
            ]
        )
        self.assertIn(self.disc_empty, result)
        self.assertNotIn(self.disc_with_a, result)

    def test_search_not_equal_false(self):
        result = self.env["test_orm.discussion"].search(
            [
                ("categories", "!=", False),
            ]
        )
        self.assertIn(self.disc_with_a, result)
        self.assertIn(self.disc_with_b, result)
        self.assertIn(self.disc_with_both, result)
        self.assertNotIn(self.disc_empty, result)


class TestMany2manyCache(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat_a = Category.create({"name": "Cache A"})
        cls.cat_b = Category.create({"name": "Cache B"})
        cls.cat_c = Category.create({"name": "Cache C"})

    def test_cache_after_link(self):
        disc = self.env["test_orm.discussion"].create({"name": "Cache Test"})
        self.assertFalse(disc.categories)

        disc.write({"categories": [Command.link(self.cat_a.id)]})
        self.assertEqual(disc.categories, self.cat_a)

    def test_cache_after_clear(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Cache Clear",
                "categories": [Command.set([self.cat_a.id, self.cat_b.id])],
            }
        )
        self.assertEqual(len(disc.categories), 2)

        disc.write({"categories": [Command.clear()]})
        self.assertFalse(disc.categories)

    def test_cache_after_set(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Cache Set",
                "categories": [Command.link(self.cat_a.id)],
            }
        )
        disc.write({"categories": [Command.set([self.cat_b.id, self.cat_c.id])]})
        self.assertEqual(disc.categories, self.cat_b | self.cat_c)

    def test_cache_invalidation_after_flush(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Flush Test",
                "categories": [Command.link(self.cat_a.id)],
            }
        )
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertEqual(disc.categories, self.cat_a)

    def test_cache_consistency_multiple_writes(self):
        disc = self.env["test_orm.discussion"].create({"name": "Multi Write"})

        disc.write({"categories": [Command.link(self.cat_a.id)]})
        self.assertEqual(disc.categories, self.cat_a)

        disc.write({"categories": [Command.link(self.cat_b.id)]})
        self.assertEqual(disc.categories, self.cat_a | self.cat_b)

        disc.write({"categories": [Command.unlink(self.cat_a.id)]})
        self.assertEqual(disc.categories, self.cat_b)

        disc.write({"categories": [Command.set([self.cat_c.id])]})
        self.assertEqual(disc.categories, self.cat_c)


class TestMany2manyBidirectional(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user1 = cls.env["test_orm.user"].create({"name": "User 1"})
        cls.user2 = cls.env["test_orm.user"].create({"name": "User 2"})
        cls.group1 = cls.env["test_orm.group"].create({"name": "Group 1"})
        cls.group2 = cls.env["test_orm.group"].create({"name": "Group 2"})

    def test_link_from_one_side(self):
        self.user1.write({"group_ids": [Command.link(self.group1.id)]})
        self.assertIn(self.user1, self.group1.user_ids)

    def test_link_from_other_side(self):
        self.group1.write({"user_ids": [Command.link(self.user1.id)]})
        self.assertIn(self.group1, self.user1.group_ids)

    def test_bidirectional_consistency(self):
        self.user1.write({"group_ids": [Command.set([self.group1.id, self.group2.id])]})
        self.assertIn(self.user1, self.group1.user_ids)
        self.assertIn(self.user1, self.group2.user_ids)

        self.user1.write({"group_ids": [Command.unlink(self.group1.id)]})
        self.assertNotIn(self.user1, self.group1.user_ids)
        self.assertIn(self.user1, self.group2.user_ids)

    def test_bidirectional_clear(self):
        self.user1.write({"group_ids": [Command.set([self.group1.id, self.group2.id])]})
        self.user1.write({"group_ids": [Command.clear()]})
        self.assertFalse(self.user1.group_ids)
        self.assertNotIn(self.user1, self.group1.user_ids)
        self.assertNotIn(self.user1, self.group2.user_ids)

    def test_computed_from_m2m(self):
        self.assertEqual(self.user1.group_count, 0)
        self.user1.write({"group_ids": [Command.set([self.group1.id, self.group2.id])]})
        self.assertEqual(self.user1.group_count, 2)
        self.user1.write({"group_ids": [Command.unlink(self.group1.id)]})
        self.assertEqual(self.user1.group_count, 1)


class TestMany2manyRelated(TransactionCase):
    def test_shared_relation_table(self):
        ship = self.env["test_orm.ship"].create({"name": "Black Pearl"})
        pirate = self.env["test_orm.pirate"].create(
            {
                "name": "Jack Sparrow",
                "ship_ids": [Command.link(ship.id)],
            }
        )
        prisoner = self.env["test_orm.prisoner"].create(
            {
                "name": "Will Turner",
                "ship_ids": [Command.link(ship.id)],
            }
        )

        self.assertIn(pirate, ship.pirate_ids)
        self.assertIn(prisoner, ship.prisoner_ids)
        self.assertIn(ship, pirate.ship_ids)
        self.assertIn(ship, prisoner.ship_ids)

    def test_m2m_with_domain(self):
        tag_a = self.env["test_orm.multi.tag"].create({"name": "alpha"})
        tag_b = self.env["test_orm.multi.tag"].create({"name": "xyz"})
        multi = self.env["test_orm.multi"].create(
            {
                "partner": self.env.ref("base.partner_root").id,
                "tags": [Command.set([tag_a.id, tag_b.id])],
            }
        )
        self.assertTrue(multi.tags)

    def test_copy_m2m(self):
        cat = self.env["test_orm.category"].create({"name": "Copy Cat"})
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Original",
                "categories": [Command.link(cat.id)],
            }
        )
        disc_copy = disc.copy()
        self.assertEqual(disc_copy.categories, cat)
        self.assertNotEqual(disc_copy.id, disc.id)

    def test_unlink_cleans_junction(self):
        cat = self.env["test_orm.category"].create({"name": "Delete Me"})
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Has Cat",
                "categories": [Command.link(cat.id)],
            }
        )
        self.assertEqual(disc.categories, cat)

        cat.unlink()
        disc.invalidate_recordset()
        self.assertFalse(disc.categories)

    def test_m2m_read(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Read M2M",
                "categories": [
                    Command.set(
                        [
                            self.env["test_orm.category"].create({"name": f"RC{i}"}).id
                            for i in range(3)
                        ]
                    )
                ],
            }
        )
        data = disc.read(["categories"])[0]
        self.assertIsInstance(data["categories"], list)
        self.assertEqual(len(data["categories"]), 3)

    def test_m2m_mapped(self):
        cat1 = self.env["test_orm.category"].create({"name": "Map1"})
        cat2 = self.env["test_orm.category"].create({"name": "Map2"})
        disc1 = self.env["test_orm.discussion"].create(
            {
                "name": "Mapped 1",
                "categories": [Command.link(cat1.id)],
            }
        )
        disc2 = self.env["test_orm.discussion"].create(
            {
                "name": "Mapped 2",
                "categories": [Command.link(cat2.id)],
            }
        )
        discussions = disc1 | disc2
        all_cats = discussions.mapped("categories")
        self.assertEqual(all_cats, cat1 | cat2)

    def test_m2m_empty_recordset(self):
        disc = self.env["test_orm.discussion"].create({"name": "Empty M2M"})
        self.assertFalse(disc.categories)
        self.assertEqual(len(disc.categories), 0)
        self.assertEqual(disc.categories.mapped("name"), [])
        self.assertEqual(list(disc.categories), [])


class TestMany2manyQueryCount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cats = Category.create([{"name": f"QC{i}"} for i in range(5)])

    def test_read_m2m_prefetch(self):
        discussions = self.env["test_orm.discussion"].create(
            [
                {"name": f"PF{i}", "categories": [Command.set(self.cats.ids)]}
                for i in range(3)
            ]
        )
        self.env.flush_all()
        discussions.invalidate_recordset()
        for disc in discussions:
            self.assertEqual(sorted(disc.categories.ids), sorted(self.cats.ids))
