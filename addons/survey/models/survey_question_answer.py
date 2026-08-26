from textwrap import shorten
from typing import Any

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SurveyQuestionAnswer(models.Model):
    _name = "survey.question.answer"
    _rec_name = "value"
    _rec_names_search = ["question_id.title", "value"]
    _order = "question_id, sequence, id"
    _description = "Survey Label"

    MAX_ANSWER_NAME_LENGTH = 90

    question_id = fields.Many2one(
        "survey.question",
        string="Question",
        ondelete="cascade",
        index="btree_not_null",
    )
    matrix_question_id = fields.Many2one(
        "survey.question",
        string="Question (as matrix row)",
        ondelete="cascade",
        index="btree_not_null",
    )
    sequence = fields.Integer("Label Sequence order", default=10)
    question_type = fields.Selection(related="question_id.question_type")
    scoring_type = fields.Selection(related="question_id.scoring_type")
    value = fields.Char("Suggested value", translate=True)
    value_image = fields.Image("Image", max_width=1024, max_height=1024)
    value_image_filename = fields.Char("Image Filename")
    value_label = fields.Char(
        "Value Label",
        compute="_compute_value_label",
        help="Answer label as either the value itself if not empty "
        "or a letter representing the index of the answer otherwise.",
    )
    is_correct = fields.Boolean("Correct")
    answer_score = fields.Float(
        "Score",
        help="A positive score indicates a correct choice; a negative or null score indicates a wrong answer",
    )
    comment = fields.Text(
        "Comment",
        translate=True,
        help="Feedback shown to the learner when this answer is selected.",
    )
    skip_action = fields.Selection(
        [
            ("next", "Continue normally"),
            ("skip_to", "Skip to question/page"),
            ("end_survey", "End survey"),
            ("redirect", "Redirect to URL"),
        ],
        string="Skip Action",
        default="next",
        help="Action to perform when this answer is selected and the page is submitted.",
    )
    skip_target_id = fields.Many2one(
        "survey.question",
        string="Skip To",
        ondelete="set null",
        help="Question or page to skip to when 'Skip to question/page' is selected.",
    )
    skip_redirect_url = fields.Char(
        "Redirect URL",
        help="External URL to redirect to when 'Redirect to URL' action is selected.",
    )

    # `value` is translate=True, so the column is jsonb: a CHECK for NOT NULL passes
    # on {"en_US": ""}, which is exactly the case it was written to reject.
    @api.constrains("value", "value_image_filename")
    def _check_value_not_empty(self) -> None:
        for label in self:
            if not (label.value or "").strip() and not label.value_image_filename:
                raise ValidationError(
                    _(
                        "Suggested answer value must not be empty (a text and/or an "
                        "image must be provided)."
                    )
                )

    @api.constrains("question_id", "matrix_question_id")
    def _check_question_not_empty(self) -> None:
        for label in self:
            if bool(label.question_id) == bool(label.matrix_question_id):
                raise ValidationError(
                    _("A label must be attached to only one question.")
                )

    @api.depends(
        "value_label",
        "question_id.question_type",
        "question_id.title",
        "matrix_question_id",
    )
    def _compute_display_name(self) -> None:
        for answer in self:
            answer_label = answer.value_label
            if not answer.question_id or answer.question_id.question_type in (
                "matrix",
                "likert",
            ):
                answer.display_name = answer_label
                continue
            title = answer.question_id.title or _("[Question Title]")
            n_extra_characters = (
                len(title) + len(answer_label) + 3 - self.MAX_ANSWER_NAME_LENGTH
            )
            if n_extra_characters <= 0:
                answer.display_name = f"{title} : {answer_label}"
            else:
                answer.display_name = shorten(
                    f"{shorten(title, max(30, len(title) - n_extra_characters), placeholder='...')} : {answer_label}",
                    self.MAX_ANSWER_NAME_LENGTH,
                    placeholder="...",
                )

    @api.depends("question_id.suggested_answer_ids", "sequence", "value")
    def _compute_value_label(self) -> None:
        for answer in self:
            if not answer.value and answer.question_id and answer.id:
                answer_idx = answer.question_id.suggested_answer_ids.ids.index(
                    answer.id
                )
                answer.value_label = chr(65 + answer_idx) if answer_idx < 26 else ""
            else:
                answer.value_label = answer.value or ""

    def _get_answer_matching_domain(
        self, row_id: int | bool = False
    ) -> list[str | tuple[str, str, Any]]:
        self.ensure_one()
        if self.question_type in ("matrix", "likert"):
            return [
                "&",
                "&",
                ("question_id", "=", self.question_id.id),
                ("matrix_row_id", "=", row_id),
                ("suggested_answer_id", "=", self.id),
            ]
        elif self.question_type in ("multiple_choice", "simple_choice", "dropdown"):
            return [
                "&",
                ("question_id", "=", self.question_id.id),
                ("suggested_answer_id", "=", self.id),
            ]
        return []
