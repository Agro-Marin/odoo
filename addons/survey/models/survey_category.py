from random import randint

from odoo import fields, models


class SurveyCategory(models.Model):
    """Categories for grouping surveys (e.g. Satisfaction, Feedback, Assessment)."""

    _name = "survey.category"
    _description = "Survey Category"
    _order = "sequence, name"

    def _get_default_color(self) -> int:
        return randint(1, 11)

    name = fields.Char("Category Name", required=True, translate=True)
    sequence = fields.Integer("Sequence", default=10)
    color = fields.Integer("Color", default=_get_default_color)
    survey_count = fields.Integer("Surveys", compute="_compute_survey_count")

    _name_uniq = models.Constraint(
        "unique (name)",
        "Category name already exists!",
    )

    def _compute_survey_count(self) -> None:
        """Count the number of surveys per category."""
        read_group_res = self.env["survey.survey"]._read_group(
            [("category_id", "in", self.ids)],
            ["category_id"],
            ["__count"],
        )
        data = {category.id: count for category, count in read_group_res}
        for category in self:
            category.survey_count = data.get(category.id, 0)
