from odoo import fields, models


class SurveyCategory(models.Model):
    """Categories for grouping surveys (e.g. Satisfaction, Feedback, Assessment)."""

    _name = "survey.category"
    _description = "Survey Category"
    # `name` (translated, unique on the source term), `active`, `color` and
    # `code` come from the mixin, which already carried the uniqueness rule this
    # model was importing on its own. Flat: categories do not nest. `_order` is
    # restated because this catalog is sequenced and the mixin's is not.
    _inherit = ["mixin.tag"]
    _order = "sequence, name"

    name = fields.Char("Category Name")
    sequence = fields.Integer("Sequence", default=10)
    survey_count = fields.Integer("Surveys", compute="_compute_survey_count")

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
