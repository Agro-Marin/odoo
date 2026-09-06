"""Pins that a new rating reaches the parent document that already read its own."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRatingParentLink(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({"name": "Rating project"})
        cls.task = cls.env["project.task"].create(
            {"name": "Rated task", "project_id": cls.project.id}
        )

    def _rate_the_task(self):
        return self.env["rating.rating"].create(
            {
                "res_model_id": self.env["ir.model"]._get_id("project.task"),
                "res_id": self.task.id,
                "parent_res_model_id": self.env["ir.model"]._get_id("project.project"),
                "parent_res_id": self.project.id,
                "rating": 5,
                "consumed": True,
            }
        )

    def test_parent_that_already_read_its_children_sees_a_new_one(self):
        """A rating created after the parent read `rating_child_ids` shows up there.

        `rating_child_ids` is a One2many over `parent_res_id`. The ORM keeps a
        cached recordset per parent and refreshes it on write through the
        inverse -- but it only registers that direction when the inverse field
        is a `Many2one` or a `Many2oneReference`
        (`odoo/orm/fields/relational/one2many.py:83`). Over a plain `Integer`
        nothing pushes the new child in, so a parent that read the relation
        earlier in the transaction keeps answering with the list it read then.
        """
        self.assertEqual(
            self.project.rating_child_ids.ids,
            [],
            "the parent starts with no child ratings (boundary)",
        )

        rating = self._rate_the_task()

        self.assertEqual(self.project.rating_child_ids.ids, rating.ids)
