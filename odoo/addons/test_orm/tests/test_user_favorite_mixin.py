from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase


class TestUserFavoriteMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Favorite = cls.env["test_orm.user.favorite"]
        internal = [Command.link(cls.env.ref("base.group_user").id)]
        cls.alice, cls.bob = cls.env["res.users"].create(
            [
                {"name": "Alice", "login": "favorite_alice", "group_ids": internal},
                {"name": "Bob", "login": "favorite_bob", "group_ids": internal},
            ]
        )
        cls.records = cls.Favorite.create([{"name": "a"}, {"name": "b"}, {"name": "c"}])

    def test_relation_table_is_derived_from_the_adopter(self):
        field = self.Favorite._fields["favorite_user_ids"]
        self.assertEqual(field.relation, "res_users_test_orm_user_favorite_rel")
        self.assertEqual(field.column1, "test_orm_user_favorite_id")
        self.assertEqual(field.column2, "res_users_id")

    def test_compute_answers_per_user(self):
        record = self.records[0]
        record.favorite_user_ids = [Command.link(self.alice.id)]

        self.assertTrue(record.with_user(self.alice).is_user_favorite)
        self.assertFalse(record.with_user(self.bob).is_user_favorite)

    def test_compute_is_invalidated_by_the_relation(self):
        record = self.records[0].with_user(self.alice)
        self.assertFalse(record.is_user_favorite)

        record.sudo().favorite_user_ids = [Command.link(self.alice.id)]
        self.assertTrue(record.is_user_favorite)

    def test_writing_true_twice_keeps_it_true(self):
        record = self.records[0].with_user(self.alice)
        record.is_user_favorite = True
        record.is_user_favorite = True

        self.assertTrue(record.is_user_favorite)
        self.assertEqual(record.sudo().favorite_user_ids, self.alice)

    def test_writing_false_removes_only_the_current_user(self):
        record = self.records[0]
        record.favorite_user_ids = [
            Command.link(self.alice.id),
            Command.link(self.bob.id),
        ]

        record.with_user(self.alice).is_user_favorite = False

        self.assertEqual(record.favorite_user_ids, self.bob)

    def test_favoriting_needs_read_access_not_write(self):
        as_reader = self.records[0].with_user(self.alice)
        with self.assertRaises(AccessError):
            as_reader.write({"name": "renamed"})

        as_reader.write({"is_user_favorite": True})
        self.assertTrue(as_reader.is_user_favorite)

        as_reader.action_toggle_user_favorite()
        self.assertFalse(as_reader.is_user_favorite)

    def test_toggle_flips_each_record_independently(self):
        favorited, plain = self.records[0], self.records[1]
        favorited.favorite_user_ids = [Command.link(self.alice.id)]

        (favorited | plain).with_user(self.alice).action_toggle_user_favorite()

        self.assertFalse(favorited.with_user(self.alice).is_user_favorite)
        self.assertTrue(plain.with_user(self.alice).is_user_favorite)

    def test_search_matches_the_current_user_only(self):
        first, second = self.records[0], self.records[1]
        first.favorite_user_ids = [Command.link(self.alice.id)]
        second.favorite_user_ids = [Command.link(self.bob.id)]

        as_alice = self.Favorite.with_user(self.alice)
        self.assertEqual(as_alice.search([("is_user_favorite", "=", True)]), first)
        self.assertNotIn(first, as_alice.search([("is_user_favorite", "=", False)]))
        self.assertIn(second, as_alice.search([("is_user_favorite", "=", False)]))

    def test_order_puts_the_current_user_favorites_first(self):
        last = self.records[-1]
        last.favorite_user_ids = [Command.link(self.alice.id)]

        ordered = self.Favorite.with_user(self.alice).search([])

        self.assertEqual(ordered[0], last)

    def test_order_survives_a_grouped_query_through_a_many2one(self):
        last = self.records[-1]
        last.favorite_user_ids = [Command.link(self.alice.id)]
        Line = self.env["test_orm.user.favorite.line"]
        Line.create([{"favorite_id": record.id} for record in self.records])

        grouped = Line.with_user(self.alice)._read_group(
            [], ["favorite_id"], ["__count"], order="favorite_id"
        )

        self.assertEqual(grouped[0][0], last)
