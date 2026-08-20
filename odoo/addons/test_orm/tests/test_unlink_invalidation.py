from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUnlinkInvalidation(TransactionCase):
    def test_deleted_records_leave_no_cached_values(self):
        discussion = self.env["test_orm.discussion"].create(
            {"name": "d", "participants": [(4, self.env.user.id)]}
        )
        message = self.env["test_orm.message"].create(
            {"discussion": discussion.id, "body": "b"}
        )
        self.env.flush_all()
        self.assertEqual(message.body, "b")
        message.unlink()
        self.assertFalse(message.exists())
        self.assertNotIn("body", message._cache)

    def test_a_cascaded_child_is_not_served_from_cache(self):
        discussion = self.env["test_orm.discussion"].create(
            {"name": "d", "participants": [(4, self.env.user.id)]}
        )
        message = self.env["test_orm.message"].create(
            {"discussion": discussion.id, "body": "b"}
        )
        self.env.flush_all()
        self.assertEqual(message.body, "b")
        discussion.unlink()
        self.assertFalse(message.exists())
        self.assertNotIn("body", message._cache)

    def test_a_one2many_drops_the_deleted_child(self):
        discussion = self.env["test_orm.discussion"].create(
            {"name": "d", "participants": [(4, self.env.user.id)]}
        )
        kept, removed = self.env["test_orm.message"].create(
            [
                {"discussion": discussion.id, "body": "kept"},
                {"discussion": discussion.id, "body": "removed"},
            ]
        )
        self.env.flush_all()
        self.assertEqual(discussion.messages, kept + removed)
        removed.unlink()
        self.assertEqual(discussion.messages, kept)

    def test_a_many2one_to_a_deleted_record_reads_as_empty(self):
        discussion = self.env["test_orm.discussion"].create(
            {"name": "d", "participants": [(4, self.env.user.id)]}
        )
        category = self.env["test_orm.category"].create({"name": "c"})
        child = self.env["test_orm.category"].create(
            {"name": "child", "parent": category.id}
        )
        self.env.flush_all()
        self.assertEqual(child.parent, category)
        self.assertTrue(discussion)
        category.unlink()
        self.assertFalse(child.exists())

    def test_an_unrelated_model_keeps_its_cache(self):
        discussion = self.env["test_orm.discussion"].create(
            {"name": "d", "participants": [(4, self.env.user.id)]}
        )
        message = self.env["test_orm.message"].create(
            {"discussion": discussion.id, "body": "b"}
        )
        currency = self.env["res.currency"].search([], limit=1)
        self.env.flush_all()
        self.assertTrue(currency.name)
        self.assertIn("name", currency._cache)
        message.unlink()
        self.assertIn(
            "name",
            currency._cache,
            "unlinking a model unrelated to res.currency must not drop its cache",
        )

    def test_a_many2many_drops_the_deleted_peer(self):
        category = self.env["test_orm.category"].create({"name": "c"})
        discussion = self.env["test_orm.discussion"].create(
            {
                "name": "d",
                "categories": [(6, 0, category.ids)],
                "participants": [(4, self.env.user.id)],
            }
        )
        self.env.flush_all()
        self.assertEqual(discussion.categories, category)
        category.unlink()
        self.assertFalse(discussion.categories)
