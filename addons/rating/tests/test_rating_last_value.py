"""Pins that a rating written on a record reaches `rating_last_value`."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRatingLastValue(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({"name": "Rating project"})
        cls.task = cls.env["project.task"].create(
            {"name": "Rated task", "project_id": cls.project.id}
        )

    def test_last_value_sees_a_freshly_created_rating(self):
        """Creating a consumed rating fills `rating_last_value`, column included.

        `_compute_rating_last_value` filters `rating_rating` with raw SQL, so
        every column that SQL touches has to be on disk before it runs.
        `res_model` is the one that gets missed: it is a stored related on
        `res_model_id.model`, which makes it the only dirty field right after
        the create, so a `flush_model` naming just `consumed` and `rating`
        finds nothing dirty and skips the write. The SQL then reads a row
        whose `res_model` is still NULL and matches nothing.
        """
        self.env["rating.rating"].create(
            {
                "res_model_id": self.env["ir.model"]._get_id("project.task"),
                "res_id": self.task.id,
                "rating": 5,
                "consumed": True,
            }
        )
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(self.task.rating_last_value, 5)
        self.env.cr.execute(
            "SELECT rating_last_value FROM project_task WHERE id = %s",
            [self.task.id],
        )
        self.assertEqual(
            self.env.cr.fetchone()[0],
            5,
            "the stored column keeps the stale value, not just the cache",
        )
