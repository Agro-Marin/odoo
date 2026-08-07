"""Tests for the rating aggregation stats on rated records."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRatingStats(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({"name": "Rating project"})
        cls.task = cls.env["project.task"].create(
            {"name": "Rated task", "project_id": cls.project.id}
        )
        cls.partner = cls.env["res.partner"].create({"name": "Rater"})

    def _rate(self, value):
        return self.env["rating.rating"].create(
            {
                "res_model_id": self.env["ir.model"]._get_id("project.task"),
                "res_id": self.task.id,
                "partner_id": self.partner.id,
                "rating": value,
                "consumed": True,
            }
        )

    def test_no_ratings_yields_zero_stats(self):
        """Without ratings the counters stay at zero (boundary)."""
        self.assertEqual(self.task.rating_count, 0)
        self.assertEqual(self.task.rating_avg, 0)

    def test_avg_and_count_aggregate(self):
        """Consumed ratings feed the average and the counter."""
        self._rate(5)
        self._rate(3)
        self.task.invalidate_recordset(["rating_avg", "rating_count"])
        self.assertEqual(self.task.rating_count, 2)
        self.assertEqual(self.task.rating_avg, 4.0)

    def test_satisfaction_percentage_counts_great_only(self):
        """Satisfaction is the share of 'great' grades (5 - great, 3 - okay)."""
        self._rate(5)
        self._rate(5)
        self._rate(3)
        self._rate(1)
        self.task.invalidate_recordset(["rating_percentage_satisfaction"])
        self.assertEqual(self.task.rating_percentage_satisfaction, 50)

    def test_satisfaction_without_ratings_is_sentinel(self):
        """No ratings yield the -1 sentinel, not a fake 0% (boundary)."""
        self.task.invalidate_recordset(["rating_percentage_satisfaction"])
        self.assertEqual(self.task.rating_percentage_satisfaction, -1)

    def test_stats_per_record_distribution(self):
        """Per-record stats expose total, average and percent distribution."""
        self._rate(5)
        self._rate(5)
        self._rate(1)
        stats = self.task._rating_get_stats_per_record()[self.task.id]
        self.assertEqual(stats["total"], 3)
        self.assertAlmostEqual(stats["avg"], 11 / 3, places=2)
        self.assertAlmostEqual(stats["percent"][5], 200 / 3, places=2)
        self.assertAlmostEqual(stats["percent"][1], 100 / 3, places=2)
        self.assertEqual(stats["percent"][2], 0.0)

    def test_grades_map_rating_values(self):
        """Ratings split into great (>=4), okay (>=3) and bad grades."""
        self._rate(5)
        self._rate(4)
        self._rate(3)
        self._rate(1)
        grades = self.task.rating_get_grades()
        self.assertEqual(grades, {"great": 2, "okay": 1, "bad": 1})

    def test_stats_expose_percent_avg_and_total(self):
        """Aggregated stats carry the percent split, average and total."""
        self._rate(5)
        self._rate(5)
        self._rate(1)
        stats = self.task.rating_get_stats()
        self.assertEqual(stats["total"], 3)
        self.assertAlmostEqual(stats["avg"], 11 / 3, places=2)
        self.assertAlmostEqual(stats["percent"][5], 200 / 3, places=2)
        self.assertEqual(stats["percent"][3], 0)

    def test_parent_project_aggregates_task_ratings(self):
        """The project aggregates its tasks' ratings via the parent mixin."""
        self._rate(5)
        self._rate(5)
        self._rate(1)
        self.project.invalidate_recordset(
            ["rating_count", "rating_avg", "rating_percentage_satisfaction"],
        )
        self.assertEqual(self.project.rating_count, 3)
        self.assertAlmostEqual(self.project.rating_avg, 11 / 3, places=2)
        # integer field: 200/3 truncates to 66
        self.assertEqual(self.project.rating_percentage_satisfaction, 66)
        self.assertAlmostEqual(
            self.project.rating_avg_percentage, 11 / 15, places=2,
        )

    def test_parent_without_ratings_uses_sentinel(self):
        """A project without ratings reports the -1 sentinel (boundary)."""
        self.project.invalidate_recordset(["rating_percentage_satisfaction"])
        self.assertEqual(self.project.rating_percentage_satisfaction, -1)

    def test_search_projects_by_average_rating(self):
        """Projects are searchable by their aggregated average rating."""
        self._rate(5)
        self._rate(4)
        matches = self.env["project.project"].search([("rating_avg", ">=", 4)])
        self.assertIn(self.project, matches)
        empty = self.env["project.project"].search([("rating_avg", ">=", 4.6)])
        self.assertNotIn(self.project, empty)
