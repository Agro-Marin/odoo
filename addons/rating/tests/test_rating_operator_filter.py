"""Pins the index behind the "My Ratings" filter of the rating search view."""

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestRatingOperatorFilter(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.operator = new_test_user(cls.env, login="rating_operator")
        cls.project = cls.env["project.project"].create({"name": "Rating project"})
        cls.task = cls.env["project.task"].create(
            {"name": "Rated task", "project_id": cls.project.id}
        )
        cls.rating = cls.env["rating.rating"].create(
            {
                "res_model_id": cls.env["ir.model"]._get_id("project.task"),
                "res_id": cls.task.id,
                "rated_partner_id": cls.operator.partner_id.id,
                "rating": 5,
                "consumed": True,
            }
        )

    def test_the_my_ratings_filter_finds_the_operators_ratings(self):
        """The domain the search view ships selects the rating (boundary)."""
        found = self.env["rating.rating"].search(
            [("rated_partner_id.user_ids", "in", [self.operator.id])]
        )
        self.assertEqual(found, self.rating)

    def test_the_rated_operator_is_indexed(self):
        """A filter the rating search view offers must not be a sequential scan.

        `rated_partner_id` carries a foreign key, and Postgres does not index
        one on its own. Everything the views group, pivot and filter by that
        column -- `views/rating_rating_views.xml:242` above all -- reads the
        whole table without this index.
        """
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'rating_rating' AND indexdef ILIKE %s",
            ("%(rated_partner_id)%",),
        )
        self.assertTrue(
            self.env.cr.fetchall(),
            "no index covers rated_partner_id, so the operator filters scan "
            "the whole rating table",
        )
