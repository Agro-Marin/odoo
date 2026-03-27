import contextlib
import random
from typing import Any, Self

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError


class SurveyQuestion(models.Model):
    """Questions that will be asked in a survey.

    Each question can have one of more suggested answers (eg. in case of
    multi-answer checkboxes, radio buttons...).

    Technical note:

    survey.question is also the model used for the survey's pages (with the "is_page" field set to True).

    A page corresponds to a "section" in the interface, and the fact that it separates the survey in
    actual pages in the interface depends on the "questions_layout" parameter on the survey.survey model.
    Pages are also used when randomizing questions. The randomization can happen within a "page".

    Using the same model for questions and pages allows to put all the pages and questions together in a o2m field
    (see survey.survey.question_and_page_ids) on the view side and easily reorganize your survey by dragging the
    items around.

    It also removes on level of encoding by directly having 'Add a page' and 'Add a question'
    links on the list view of questions, enabling a faster encoding.

    However, this has the downside of making the code reading a little bit more complicated.
    Efforts were made at the model level to create computed fields so that the use of these models
    still seems somewhat logical. That means:
    - A survey still has "page_ids" (question_and_page_ids filtered on is_page = True)
    - These "page_ids" still have question_ids (questions located between this page and the next)
    - These "question_ids" still have a "page_id"

    That makes the use and display of these information at view and controller levels easier to understand.
    """

    _name = "survey.question"
    _inherit = ["survey.question.statistics"]
    _description = "Survey Question"
    _rec_name = "title"
    _order = "sequence,id"

    @api.model
    def default_get(self, fields: list[str]) -> dict[str, Any]:
        res = super().default_get(fields)
        if default_survey_id := self.env.context.get("default_survey_id"):
            survey = self.env["survey.survey"].browse(default_survey_id)
            if "is_time_limited" in fields and "is_time_limited" not in res:
                res["is_time_limited"] = survey.session_speed_rating
            if "time_limit" in fields and "time_limit" not in res:
                res["time_limit"] = survey.session_speed_rating_time_limit
        return res

    survey_id = fields.Many2one(
        "survey.survey",
        string="Survey",
        ondelete="cascade",
        index="btree_not_null",
    )
    scoring_type = fields.Selection(
        related="survey_id.scoring_type",
        string="Scoring Type",
        readonly=True,
    )
    session_available = fields.Boolean(
        related="survey_id.session_available",
        string="Live Session available",
        readonly=True,
    )
    survey_session_speed_rating = fields.Boolean(
        related="survey_id.session_speed_rating"
    )
    survey_session_speed_rating_time_limit = fields.Integer(
        related="survey_id.session_speed_rating_time_limit",
        string="General Time limit (seconds)",
    )
    title = fields.Char("Title", required=True, translate=True)
    sequence = fields.Integer("Sequence", default=10)
    description = fields.Html(
        "Description",
        translate=True,
        sanitize=True,
        sanitize_overridable=True,
        help="Use this field to add additional explanations about your question or to illustrate it with pictures or a video",
    )
    question_placeholder = fields.Char(
        "Placeholder",
        translate=True,
        compute="_compute_question_placeholder",
        store=True,
        readonly=False,
    )
    background_image = fields.Image(
        "Background Image",
        compute="_compute_background_image",
        store=True,
        readonly=False,
    )
    background_image_url = fields.Char(
        "Background Url",
        compute="_compute_background_image_url",
    )

    # page specific
    is_page = fields.Boolean("Is a page?")
    question_ids = fields.One2many(
        "survey.question",
        string="Questions",
        compute="_compute_question_ids",
    )
    questions_selection = fields.Selection(
        related="survey_id.questions_selection",
        readonly=True,
        help="If randomized is selected, add the number of random questions next to the section.",
    )
    random_questions_count = fields.Integer(
        "# Questions Randomly Picked",
        default=1,
        help="Used on randomized sections to take X random questions from all the questions of that section.",
    )

    # question specific
    page_id = fields.Many2one(
        "survey.question",
        string="Page",
        compute="_compute_page_id",
        store=True,
    )
    question_type = fields.Selection(
        [
            ("simple_choice", "Multiple choice: only one answer"),
            ("dropdown", "Dropdown"),
            ("multiple_choice", "Multiple choice: multiple answers allowed"),
            ("text_box", "Multiple Lines Text Box"),
            ("char_box", "Single Line Text Box"),
            ("numerical_box", "Numerical Value"),
            ("scale", "Scale"),
            ("nps", "Net Promoter Score"),
            ("slider", "Slider"),
            ("rating", "Rating"),
            ("ranking", "Ranking"),
            ("constant_sum", "Constant Sum"),
            ("file_upload", "File Upload"),
            ("date", "Date"),
            ("datetime", "Datetime"),
            ("matrix", "Matrix"),
            ("likert", "Likert Scale"),
            ("calculated", "Calculated / Hidden Field"),
            ("statement", "Statement / Info Screen"),
        ],
        string="Question Type",
        compute="_compute_question_type",
        readonly=False,
        store=True,
    )
    is_scored_question = fields.Boolean(
        "Scored",
        compute="_compute_is_scored_question",
        readonly=False,
        store=True,
        copy=True,
        help="Include this question as part of quiz scoring. Requires an answer and answer score to be taken into account.",
    )
    has_image_only_suggested_answer = fields.Boolean(
        "Has image only suggested answer",
        compute="_compute_has_image_only_suggested_answer",
    )
    # -- scoreable/answerable simple answer_types: numerical_box / date / datetime
    answer_numerical_box = fields.Float(
        "Correct numerical answer", help="Correct number answer for this question.",
    )
    answer_date = fields.Date(
        "Correct date answer", help="Correct date answer for this question.",
    )
    answer_datetime = fields.Datetime(
        "Correct datetime answer",
        help="Correct date and time answer for this question.",
    )
    answer_score = fields.Float(
        "Score", help="Score value for a correct answer to this question."
    )
    # -- char_box
    save_as_email = fields.Boolean(
        "Save as user email",
        compute="_compute_save_as_email",
        readonly=False,
        store=True,
        copy=True,
        help="If checked, this option will save the user's answer as its email address.",
    )
    save_as_nickname = fields.Boolean(
        "Save as user nickname",
        compute="_compute_save_as_nickname",
        readonly=False,
        store=True,
        copy=True,
        help="If checked, this option will save the user's answer as its nickname.",
    )
    # -- simple choice / multiple choice / matrix
    suggested_answer_ids = fields.One2many(
        "survey.question.answer",
        "question_id",
        string="Types of answers",
        copy=True,
        help="Labels used for proposed choices: simple choice, multiple choice and columns of matrix",
    )
    # -- matrix
    matrix_subtype = fields.Selection(
        [("simple", "One choice per row"), ("multiple", "Multiple choices per row")],
        string="Matrix Type",
        default="simple",
    )
    matrix_row_ids = fields.One2many(
        "survey.question.answer",
        "matrix_question_id",
        string="Matrix Rows",
        copy=True,
        help="Labels used for proposed choices: rows of matrix or Likert statements",
    )
    # -- likert preset
    likert_preset = fields.Selection(
        [
            ("agreement_5", "Agreement (5-point)"),
            ("agreement_7", "Agreement (7-point)"),
            ("frequency_5", "Frequency (5-point)"),
            ("satisfaction_5", "Satisfaction (5-point)"),
            ("importance_5", "Importance (5-point)"),
        ],
        string="Likert Preset",
        help="Predefined scale labels. Select a preset then add your statements as matrix rows.",
    )
    # -- scale
    scale_min = fields.Integer("Scale Minimum Value", default=0)
    scale_max = fields.Integer("Scale Maximum Value", default=10)
    scale_min_label = fields.Char("Scale Minimum Label", translate=True)
    scale_mid_label = fields.Char("Scale Middle Label", translate=True)
    scale_max_label = fields.Char("Scale Maximum Label", translate=True)
    # -- slider
    slider_min = fields.Float("Slider Minimum", default=0)
    slider_max = fields.Float("Slider Maximum", default=100)
    slider_step = fields.Float("Slider Step", default=1)
    slider_unit = fields.Char(
        "Slider Unit",
        help="Unit label displayed next to the value (e.g., '%', 'kg', '$').",
    )
    # -- rating
    rating_max = fields.Integer(
        "Rating Maximum", default=5, help="Number of rating icons (1 to 10)."
    )
    rating_icon = fields.Selection(
        [("star", "Stars"), ("heart", "Hearts"), ("thumb", "Thumbs Up")],
        string="Rating Icon",
        default="star",
    )
    # -- constant sum
    constant_sum_total = fields.Integer(
        "Total Points",
        default=100,
        help="The total that all distributed values must sum to.",
    )
    # -- file upload
    file_upload_types = fields.Char(
        "Allowed File Types",
        default=".pdf,.doc,.docx,.jpg,.png",
        help="Comma-separated list of allowed file extensions.",
    )
    file_upload_max_size = fields.Integer(
        "Max File Size (MB)",
        default=10,
        help="Maximum file size in megabytes.",
    )
    # -- calculated / hidden field
    calculated_expression = fields.Char(
        "Formula",
        help="Arithmetic expression using question references. Use Q<id> to reference "
        "other questions' numerical answers. Supports +, -, *, /, parentheses, and "
        "the functions: min(), max(), abs(), round().\n"
        "Example: Q42 * 0.3 + Q43 * 0.7",
    )
    # -- display & timing options
    is_time_limited = fields.Boolean(
        "The question is limited in time",
        help="Currently only supported for live sessions.",
    )
    is_time_customized = fields.Boolean("Customized speed rewards")
    time_limit = fields.Integer("Time limit (seconds)")
    # -- answer display options
    shuffle_answers = fields.Boolean(
        "Shuffle Answers",
        help="Randomize the display order of suggested answers for each respondent. "
        "The order is deterministic per respondent (seeded by their access token).",
    )
    # -- comments (simple choice, multiple choice, matrix (without count as an answer))
    comments_allowed = fields.Boolean("Show Comments Field")
    comments_message = fields.Char("Comment Message", translate=True)
    comment_count_as_answer = fields.Boolean("Comment is an answer")
    # question validation
    validation_required = fields.Boolean(
        "Validate entry",
        compute="_compute_validation_required",
        readonly=False,
        store=True,
    )
    validation_email = fields.Boolean("Input must be an email")
    validation_length_min = fields.Integer("Minimum Text Length", default=0)
    validation_length_max = fields.Integer("Maximum Text Length", default=0)
    validation_min_float_value = fields.Float("Minimum value", default=0.0)
    validation_max_float_value = fields.Float("Maximum value", default=0.0)
    validation_min_date = fields.Date("Minimum Date")
    validation_max_date = fields.Date("Maximum Date")
    validation_min_datetime = fields.Datetime("Minimum Datetime")
    validation_max_datetime = fields.Datetime("Maximum Datetime")
    validation_error_msg = fields.Char("Validation Error", translate=True)
    constr_mandatory = fields.Boolean("Mandatory Answer")
    constr_error_msg = fields.Char("Error message", translate=True)
    # answers
    user_input_line_ids = fields.One2many(
        "survey.user_input.line",
        "question_id",
        string="Answers",
        domain=[("skipped", "=", False)],
        groups="survey.group_survey_user",
    )

    # Not stored, convenient for trigger display computation.
    triggering_question_ids = fields.Many2many(
        "survey.question",
        string="Triggering Questions",
        compute="_compute_triggering_question_ids",
        store=False,
        help="Questions containing the triggering answer(s) to display the current question.",
    )

    allowed_triggering_question_ids = fields.Many2many(
        "survey.question",
        string="Allowed Triggering Questions",
        copy=False,
        compute="_compute_allowed_triggering_question_ids",
    )
    is_placed_before_trigger = fields.Boolean(
        string="Is misplaced?",
        compute="_compute_allowed_triggering_question_ids",
        help="Is this question placed before any of its trigger questions?",
    )
    triggering_answer_ids = fields.Many2many(
        "survey.question.answer",
        string="Triggering Answers",
        copy=False,
        readonly=False,
        domain="""[
            ('question_id.survey_id', '=', survey_id),
            '&', ('question_id.question_type', 'in', ['simple_choice', 'dropdown', 'multiple_choice']),
                 '|',
                     ('question_id.sequence', '<', sequence),
                     '&', ('question_id.sequence', '=', sequence), ('question_id.id', '<', id)
        ]""",
        help="Picking any of these answers will trigger this question.\n"
        "Leave the field empty if the question should always be displayed.",
    )
    # -- value-based conditional triggers (for non-choice question types)
    triggering_question_id = fields.Many2one(
        "survey.question",
        string="Triggering Question (value-based)",
        ondelete="set null",
        domain="""[
            ('survey_id', '=', survey_id),
            ('is_page', '=', False),
            ('question_type', 'not in', ['simple_choice', 'dropdown', 'multiple_choice', 'matrix', 'statement']),
            '|', ('sequence', '<', sequence),
                 '&', ('sequence', '=', sequence), ('id', '<', id)
        ]""",
        help="Show this question only when the selected question's answer meets the operator condition.\n"
        "Use this for non-choice questions (numerical, text, date, scale, etc.).",
    )
    triggering_operator = fields.Selection(
        [
            ("is_answered", "Is answered"),
            ("is_not_answered", "Is not answered"),
            ("eq", "Equals"),
            ("neq", "Does not equal"),
            ("gt", "Greater than"),
            ("gte", "Greater than or equal"),
            ("lt", "Less than"),
            ("lte", "Less than or equal"),
            ("contains", "Contains"),
        ],
        string="Trigger Operator",
        default="is_answered",
        help="Comparison operator for value-based conditional trigger.",
    )
    triggering_value = fields.Char(
        "Trigger Value",
        help="The value to compare against. For numerical questions use a number, "
        "for date questions use YYYY-MM-DD format.",
    )

    _positive_len_min = models.Constraint(
        "CHECK (validation_length_min >= 0)",
        "A length must be positive!",
    )
    _positive_len_max = models.Constraint(
        "CHECK (validation_length_max >= 0)",
        "A length must be positive!",
    )
    _validation_length = models.Constraint(
        "CHECK (validation_length_min <= validation_length_max)",
        "Max length cannot be smaller than min length!",
    )
    _validation_float = models.Constraint(
        "CHECK (validation_min_float_value <= validation_max_float_value)",
        "Max value cannot be smaller than min value!",
    )
    _validation_date = models.Constraint(
        "CHECK (validation_min_date <= validation_max_date)",
        "Max date cannot be smaller than min date!",
    )
    _validation_datetime = models.Constraint(
        "CHECK (validation_min_datetime <= validation_max_datetime)",
        "Max datetime cannot be smaller than min datetime!",
    )
    _positive_answer_score = models.Constraint(
        "CHECK (answer_score >= 0)",
        "An answer score for a non-multiple choice question cannot be negative!",
    )
    _scored_datetime_have_answers = models.Constraint(
        "CHECK (is_scored_question != True OR question_type != 'datetime' OR answer_datetime is not null)",
        'All "Is a scored question = True" and "Question Type: Datetime" questions need an answer',
    )
    _scored_date_have_answers = models.Constraint(
        "CHECK (is_scored_question != True OR question_type != 'date' OR answer_date is not null)",
        'All "Is a scored question = True" and "Question Type: Date" questions need an answer',
    )
    _scale = models.Constraint(
        "CHECK (question_type != 'scale' OR (scale_min >= 0 AND scale_max <= 100 AND scale_min < scale_max AND (scale_max - scale_min) <= 20))",
        "The scale must be a growing non-empty range with min >= 0, max <= 100, and at most 20 steps",
    )
    _slider = models.Constraint(
        "CHECK (question_type != 'slider' OR (slider_min < slider_max AND slider_step > 0))",
        "Slider must have min < max and a positive step",
    )
    _rating = models.Constraint(
        "CHECK (question_type != 'rating' OR (rating_max >= 1 AND rating_max <= 10))",
        "Rating max must be between 1 and 10",
    )
    _constant_sum = models.Constraint(
        "CHECK (question_type != 'constant_sum' OR constant_sum_total > 0)",
        "Constant sum total must be positive",
    )
    _is_time_limited_have_time_limit = models.Constraint(
        "CHECK (is_time_limited != TRUE OR time_limit IS NOT NULL AND time_limit > 0)",
        "All time-limited questions need a positive time limit",
    )

    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------

    @api.constrains("is_page")
    def _check_question_type_for_pages(self) -> None:
        """Ensure pages have no question_type set."""
        invalid_pages = self.filtered(
            lambda question: question.is_page and question.question_type
        )
        if invalid_pages:
            raise ValidationError(
                _(
                    "Question type should be empty for these pages: %s",
                    ", ".join(invalid_pages.mapped("title")),
                )
            )

    @api.constrains("triggering_answer_ids")
    def _check_no_conditional_cycle(self) -> None:
        """Prevent circular dependencies in conditional question chains.

        A cycle (A triggers B, B triggers A) would cause infinite loops in
        ``_get_pages_and_questions_to_show`` and confuse navigation logic.
        We walk the trigger graph for each question and raise if we revisit
        a question already in the current path.
        """
        # Build adjacency: question → set of questions it triggers
        all_conditional = self.search(
            [
                ("survey_id", "in", self.survey_id.ids),
                ("triggering_answer_ids", "!=", False),
            ]
        )
        # triggered_by[q_id] = set of question ids whose answers trigger q_id
        triggered_by = {}
        for q in all_conditional:
            triggered_by[q.id] = set(q.triggering_answer_ids.mapped("question_id").ids)

        def _has_cycle(start_id: int, visited: set[int] | None = None) -> bool:
            """DFS to detect cycles in the trigger dependency graph."""
            if visited is None:
                visited = set()
            if start_id in visited:
                return True
            visited.add(start_id)
            for dep_id in triggered_by.get(start_id, ()):
                if _has_cycle(dep_id, visited):
                    return True
            visited.discard(start_id)
            return False

        for question in self.filtered("triggering_answer_ids"):
            if _has_cycle(question.id):
                raise ValidationError(
                    _(
                        "Circular dependency detected in conditional questions. "
                        "Question '%(title)s' is part of a trigger cycle.",
                        title=question.title,
                    )
                )

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list: list[dict[str, Any]]) -> Self:
        """Create questions and flag time customization diverging from survey defaults."""
        questions = super().create(vals_list)
        questions.filtered(
            lambda q: (
                q.survey_id
                and (
                    q.survey_id.session_speed_rating != q.is_time_limited
                    or (
                        q.is_time_limited
                        and q.survey_id.session_speed_rating_time_limit != q.time_limit
                    )
                )
            )
        ).is_time_customized = True
        return questions

    def copy(self, default: dict[str, Any] | None = None) -> Self:
        """Duplicate questions while preserving conditional trigger relationships."""
        new_questions = super().copy(default)
        for old_question, new_question in zip(self, new_questions, strict=False):
            if old_question.triggering_answer_ids:
                new_question.triggering_answer_ids = old_question.triggering_answer_ids
        return new_questions

    @api.ondelete(at_uninstall=False)
    def _unlink_except_live_sessions_in_progress(self) -> None:
        """Prevent deletion of questions belonging to surveys with active live sessions."""
        running_surveys = self.survey_id.filtered(
            lambda survey: survey.session_state == "in_progress"
        )
        if running_surveys:
            raise UserError(
                _(
                    'You cannot delete questions from surveys "%(survey_names)s" while live sessions are in progress.',
                    survey_names=", ".join(running_surveys.mapped("title")),
                )
            )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends("suggested_answer_ids", "suggested_answer_ids.value")
    def _compute_has_image_only_suggested_answer(self) -> None:
        """Detect questions with at least one answer that has no text value (image-only)."""
        questions_with_image_only_answer = self.env["survey.question"].search(
            [("id", "in", self.ids), ("suggested_answer_ids.value", "in", [False, ""])]
        )
        questions_with_image_only_answer.has_image_only_suggested_answer = True
        (self - questions_with_image_only_answer).has_image_only_suggested_answer = (
            False
        )

    @api.depends("question_type")
    def _compute_question_placeholder(self) -> None:
        """Reset placeholder for question types that don't support it (choices, matrix)."""
        for question in self:
            if (
                question.question_type
                in (
                    "simple_choice",
                    "dropdown",
                    "multiple_choice",
                    "matrix",
                    "likert",
                    "calculated",
                    "statement",
                )
                or not question.question_placeholder
            ):  # avoid CacheMiss errors
                question.question_placeholder = False

    @api.depends("is_page")
    def _compute_background_image(self) -> None:
        """Background image is only available on sections."""
        for question in self.filtered(lambda q: not q.is_page):
            question.background_image = False

    @api.depends(
        "survey_id.access_token",
        "background_image",
        "page_id",
        "survey_id.background_image_url",
    )
    def _compute_background_image_url(self) -> None:
        """How the background url is computed:
        - For a question: it depends on the related section (see below)
        - For a section:
            - if a section has a background, then we create the background URL using this section's ID
            - if not, then we fallback on the survey background url"""
        for question in self:
            if question.is_page:
                background_section_id = (
                    question.id if question.background_image else False
                )
            else:
                background_section_id = (
                    question.page_id.id if question.page_id.background_image else False
                )

            if background_section_id:
                survey_token = question.survey_id.access_token
                question.background_image_url = f"/survey/{survey_token}/{background_section_id}/get_background_image"
            else:
                question.background_image_url = question.survey_id.background_image_url

    @api.depends("is_page")
    def _compute_question_type(self) -> None:
        """Reset question_type for pages; default non-page questions to 'simple_choice'."""
        pages = self.filtered(lambda question: question.is_page)
        pages.question_type = False
        (self - pages).filtered(
            lambda question: not question.question_type
        ).question_type = "simple_choice"

    @api.depends(
        "survey_id.question_and_page_ids.is_page",
        "survey_id.question_and_page_ids.sequence",
    )
    def _compute_question_ids(self) -> None:
        """Compute the questions belonging to each page (section), sorted by index."""
        for question in self:
            if question.is_page:
                question.question_ids = question.survey_id.question_ids.filtered(
                    lambda q, page=question: q.page_id == page
                ).sorted(lambda q: q._index())
            else:
                question.question_ids = self.env["survey.question"]

    @api.depends(
        "survey_id.question_and_page_ids.is_page",
        "survey_id.question_and_page_ids.sequence",
    )
    def _compute_page_id(self) -> None:
        """Will find the page to which this question belongs to by looking inside the corresponding survey"""
        for question in self:
            if question.is_page:
                question.page_id = None
            else:
                page = None
                for q in question.survey_id.question_and_page_ids.sorted():
                    if q == question:
                        break
                    if q.is_page:
                        page = q
                question.page_id = page

    @api.depends("question_type", "validation_email")
    def _compute_save_as_email(self) -> None:
        """Reset save_as_email when question type is not char_box or email validation is off."""
        for question in self:
            if question.question_type != "char_box" or not question.validation_email:
                question.save_as_email = False

    @api.depends("question_type")
    def _compute_save_as_nickname(self) -> None:
        """Reset save_as_nickname when question type is not char_box."""
        for question in self:
            if question.question_type != "char_box":
                question.save_as_nickname = False

    @api.depends("question_type")
    def _compute_validation_required(self) -> None:
        """Reset validation_required for question types that don't support validation."""
        for question in self:
            if not question.validation_required or question.question_type not in [
                "char_box",
                "numerical_box",
                "date",
                "datetime",
            ]:
                question.validation_required = False

    @api.depends("survey_id", "survey_id.question_ids", "triggering_answer_ids")
    def _compute_allowed_triggering_question_ids(self) -> None:
        """Although the question (and possible trigger questions) sequence
        is used here, we do not add these fields to the dependency list to
        avoid cascading rpc calls when reordering questions via the webclient.
        """
        possible_trigger_questions = self.search(
            [
                ("is_page", "=", False),
                (
                    "question_type",
                    "in",
                    ["simple_choice", "dropdown", "multiple_choice"],
                ),
                ("suggested_answer_ids", "!=", False),
                ("survey_id", "in", self.survey_id.ids),
            ]
        )
        # Using the sequence stored in db is necessary for existing questions that are passed as
        # NewIds because the sequence provided by the JS client can be incorrect.
        (self | possible_trigger_questions).flush_recordset()
        self.env.cr.execute(
            "SELECT id, sequence FROM survey_question WHERE id =ANY(%s)", [self.ids]
        )
        conditional_questions_sequences = dict(
            self.env.cr.fetchall()
        )  # id: sequence mapping

        for question in self:
            question_id = question._origin.id
            if not question_id:  # New question
                question.allowed_triggering_question_ids = (
                    possible_trigger_questions.filtered(
                        lambda q, survey_origin=question.survey_id._origin.id: (
                            q.survey_id.id == survey_origin
                        )
                    )
                )
                question.is_placed_before_trigger = False
                continue

            question_sequence = conditional_questions_sequences[question_id]

            question.allowed_triggering_question_ids = possible_trigger_questions.filtered(
                lambda q, survey_origin=question.survey_id._origin.id, seq=question_sequence, qid=question_id: (
                    q.survey_id.id == survey_origin
                    and (q.sequence < seq or (q.sequence == seq and q.id < qid))
                )
            )
            question.is_placed_before_trigger = bool(
                set(question.triggering_answer_ids.question_id.ids)
                - set(
                    question.allowed_triggering_question_ids.ids
                )  # .ids necessary to match ids with newIds
            )

    @api.depends("triggering_answer_ids")
    def _compute_triggering_question_ids(self) -> None:
        """Derive the triggering questions from the triggering answer records."""
        for question in self:
            question.triggering_question_ids = (
                question.triggering_answer_ids.question_id
            )

    @api.depends(
        "question_type",
        "scoring_type",
        "answer_date",
        "answer_datetime",
        "answer_numerical_box",
        "suggested_answer_ids.is_correct",
    )
    def _compute_is_scored_question(self) -> None:
        """Computes whether a question "is scored" or not. Handles following cases:
        - inconsistent Boolean=None edge case that breaks tests => False
        - survey is not scored => False
        - 'date'/'datetime' question types w/correct answer => True
        - 'numerical_box': scored when answer_score > 0 (handles correct answer of 0.0)
        - 'simple_choice / multiple_choice': True if any suggested answers are marked as correct
        - question_type isn't scoreable => False
        """
        for question in self:
            if (
                question.is_scored_question is None
                or question.scoring_type == "no_scoring"
            ):
                question.is_scored_question = False
            elif question.question_type == "date":
                question.is_scored_question = bool(question.answer_date)
            elif question.question_type == "datetime":
                question.is_scored_question = bool(question.answer_datetime)
            elif question.question_type == "numerical_box":
                question.is_scored_question = question.answer_score > 0
            elif question.question_type in [
                "simple_choice",
                "dropdown",
                "multiple_choice",
            ]:
                question.is_scored_question = any(
                    question.suggested_answer_ids.mapped("is_correct")
                )
            else:
                question.is_scored_question = False

    @api.onchange("question_type")
    def _onchange_validation_parameters(self) -> None:
        """Reset validation parameters when the question type changes.

        Different question types use different validation fields (date uses
        min/max date, char uses min/max length, numerical uses min/max float).
        Clearing them all on type change prevents stale values from a previous
        type from being silently saved.
        """
        self.validation_email = False
        self.validation_length_min = 0
        self.validation_length_max = 0
        self.validation_min_date = False
        self.validation_max_date = False
        self.validation_min_datetime = False
        self.validation_max_datetime = False
        self.validation_min_float_value = 0
        self.validation_max_float_value = 0

    # ------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------

    def validate_question(
        self, answer: Any, comment: str | None = None
    ) -> dict[int, str]:
        """Validate question, depending on question type and parameters
        for simple choice, text, date and number, answer is simply the answer of the question.
        For other multiple choices questions, answer is a list of answers (the selected choices
        or a list of selected answers per question -for matrix type-):

        - Simple answer : ``answer = 'example'`` or ``2`` or ``question_answer_id`` or ``2019/10/10``
        - Multiple choice : ``answer = [question_answer_id1, question_answer_id2, question_answer_id3]``
        - Matrix: ``answer = { 'rowId1' : [colId1, colId2,...], 'rowId2' : [colId1, colId3, ...] }``

        :returns: A dict ``{question.id: error}``, or an empty dict if no validation error.
        :rtype: dict[int, str]
        """
        self.ensure_one()
        if isinstance(answer, str):
            answer = answer.strip()
        # Statement and calculated questions collect no direct answer
        if self.question_type in ("statement", "calculated"):
            return {}
        # Empty answer to mandatory question
        # because in choices question types, comment can count as answer
        if not answer and self.question_type not in [
            "simple_choice",
            "dropdown",
            "multiple_choice",
        ]:
            if self.constr_mandatory and not self.survey_id.users_can_go_back:
                return {
                    self.id: self.constr_error_msg
                    or _("This question requires an answer.")
                }
        elif self.question_type == "char_box":
            return self._validate_char_box(answer)
        elif self.question_type == "numerical_box":
            return self._validate_numerical_box(answer)
        elif self.question_type in ["date", "datetime"]:
            return self._validate_date(answer)
        elif self.question_type in ["simple_choice", "dropdown", "multiple_choice"]:
            return self._validate_choice(answer, comment)
        elif self.question_type in ("matrix", "likert"):
            return self._validate_matrix(answer)
        elif self.question_type in ("scale", "nps"):
            return self._validate_scale(answer)
        elif self.question_type == "slider":
            return self._validate_slider(answer)
        elif self.question_type == "rating":
            return self._validate_rating(answer)
        elif self.question_type == "ranking":
            return self._validate_ranking(answer)
        elif self.question_type == "constant_sum":
            return self._validate_constant_sum(answer)
        elif self.question_type == "file_upload":
            return self._validate_file_upload(answer)
        return {}

    def _validate_char_box(self, answer: str) -> dict[int, str]:
        """Validate char_box answer against email format and length constraints."""
        # Email format validation
        # all the strings of the form "<something>@<anything>.<extension>" will be accepted
        if self.validation_email:
            if not tools.email_normalize(answer):
                return {self.id: _("This answer must be an email address")}

        # Answer validation (if properly defined)
        # Length of the answer must be in a range
        if self.validation_required:
            if not (
                self.validation_length_min <= len(answer) <= self.validation_length_max
            ):
                return {
                    self.id: self.validation_error_msg
                    or _("The answer you entered is not valid.")
                }
        return {}

    def _validate_numerical_box(self, answer: Any) -> dict[int, str]:
        """Validate numerical_box answer is a number within configured range."""
        try:
            floatanswer = float(answer)
        except ValueError:
            return {self.id: _("This is not a number")}

        if self.validation_required:
            # Answer is not in the right range
            with contextlib.suppress(TypeError, ValueError):
                if not (
                    self.validation_min_float_value
                    <= floatanswer
                    <= self.validation_max_float_value
                ):
                    return {
                        self.id: self.validation_error_msg
                        or _("The answer you entered is not valid.")
                    }
        return {}

    def _validate_date(self, answer: str) -> dict[int, str]:
        """Validate that the answer is a valid date/datetime and within configured bounds."""
        is_datetime = self.question_type == "datetime"
        field_class = fields.Datetime if is_datetime else fields.Date
        try:
            dateanswer = field_class.from_string(answer)
        except ValueError:
            return {self.id: _("This is not a date")}
        if self.validation_required:
            if is_datetime:
                min_date = fields.Datetime.from_string(self.validation_min_datetime)
                max_date = fields.Datetime.from_string(self.validation_max_datetime)
            else:
                min_date = fields.Date.from_string(self.validation_min_date)
                max_date = fields.Date.from_string(self.validation_max_date)

            if (
                (min_date and max_date and not (min_date <= dateanswer <= max_date))
                or (min_date and not min_date <= dateanswer)
                or (max_date and not dateanswer <= max_date)
            ):
                return {
                    self.id: self.validation_error_msg
                    or _("The answer you entered is not valid.")
                }
        return {}

    def _validate_choice(self, answer: Any, comment: str | None) -> dict[int, str]:
        """Validates choice-based questions.
        - Checks that mandatory questions have at least one answer.
        - For 'simple_choice', ensures that exactly one answer is provided.
        """
        answers = answer if isinstance(answer, list) else ([answer] if answer else [])

        valid_answers_count = len(answers)
        if comment and self.comment_count_as_answer:
            valid_answers_count += 1

        if (
            valid_answers_count == 0
            and self.constr_mandatory
            and not self.survey_id.users_can_go_back
        ):
            return {
                self.id: self.constr_error_msg or _("This question requires an answer.")
            }

        if valid_answers_count > 1 and self.question_type in (
            "simple_choice",
            "dropdown",
        ):
            return {self.id: _("For this question, you can only select one answer.")}

        return {}

    def _validate_matrix(self, answers: dict[str, list[int]]) -> dict[int, str]:
        """Validate that all matrix rows have been answered when mandatory."""
        # Validate that each line has been answered
        if (
            not self.survey_id.users_can_go_back
            and self.constr_mandatory
            and len(self.matrix_row_ids) != len(answers)
        ):
            return {
                self.id: self.constr_error_msg or _("This question requires an answer.")
            }
        return {}

    def _validate_scale(self, answer: Any) -> dict[int, str]:
        """Validate scale/NPS answer is provided when mandatory."""
        if (
            not self.survey_id.users_can_go_back
            and self.constr_mandatory
            and not answer
        ):
            return {
                self.id: self.constr_error_msg or _("This question requires an answer.")
            }
        return {}

    def _validate_slider(self, answer: Any) -> dict[int, str]:
        """Validate slider answer is within configured bounds."""
        if not answer and answer != 0:
            if self.constr_mandatory and not self.survey_id.users_can_go_back:
                return {
                    self.id: self.constr_error_msg
                    or _("This question requires an answer.")
                }
            return {}
        try:
            val = float(answer)
        except ValueError, TypeError:
            return {self.id: _("Invalid numerical value.")}
        if val < self.slider_min or val > self.slider_max:
            return {
                self.id: _(
                    "Value must be between %s and %s.", self.slider_min, self.slider_max
                )
            }
        return {}

    def _validate_rating(self, answer: Any) -> dict[int, str]:
        """Validate rating is an integer between 1 and rating_max."""
        if not answer:
            if self.constr_mandatory and not self.survey_id.users_can_go_back:
                return {
                    self.id: self.constr_error_msg
                    or _("This question requires an answer.")
                }
            return {}
        try:
            val = int(answer)
        except ValueError, TypeError:
            return {self.id: _("Invalid rating value.")}
        if val < 1 or val > self.rating_max:
            return {self.id: _("Rating must be between 1 and %s.", self.rating_max)}
        return {}

    def _validate_ranking(self, answer: Any) -> dict[int, str]:
        """Validate ranking: answer is a dict {answer_id: rank_position}."""
        if not answer:
            if self.constr_mandatory and not self.survey_id.users_can_go_back:
                return {
                    self.id: self.constr_error_msg
                    or _("This question requires an answer.")
                }
            return {}
        if not isinstance(answer, dict):
            return {self.id: _("Invalid ranking answer format.")}
        if len(answer) != len(self.suggested_answer_ids):
            return {self.id: _("Please rank all items.")}
        return {}

    def _validate_constant_sum(self, answer: Any) -> dict[int, str]:
        """Validate that all values sum to the configured total."""
        if not answer:
            if self.constr_mandatory and not self.survey_id.users_can_go_back:
                return {
                    self.id: self.constr_error_msg
                    or _("This question requires an answer.")
                }
            return {}
        if not isinstance(answer, dict):
            return {self.id: _("Invalid answer format.")}
        try:
            total = sum(float(v) for v in answer.values())
        except ValueError, TypeError:
            return {self.id: _("All values must be numbers.")}
        if abs(total - self.constant_sum_total) > 0.01:
            return {
                self.id: _(
                    "Values must sum to %s (currently %s).",
                    self.constant_sum_total,
                    total,
                )
            }
        return {}

    def _validate_file_upload(self, answer: Any) -> dict[int, str]:
        """Validate file upload: mandatory constraint, file extension, and size.

        The *answer* value at validation time is either falsy (no file) or an
        ``ir.attachment`` id (integer) created by the upload controller.  Extension
        and size checks are performed against the stored attachment metadata so
        they cannot be bypassed by renaming the file on the client side.
        """
        if not answer:
            if self.constr_mandatory and not self.survey_id.users_can_go_back:
                return {
                    self.id: self.constr_error_msg
                    or _("This question requires an answer.")
                }
            return {}
        # Validate extension and size against the ir.attachment record
        try:
            attachment_id = int(answer)
        except ValueError, TypeError:
            return {self.id: _("Invalid file upload.")}
        attachment = self.env["ir.attachment"].sudo().browse(attachment_id).exists()
        if not attachment:
            return {self.id: _("Uploaded file not found.")}
        # Extension check
        if self.file_upload_types:
            allowed = {
                ext.strip().lower()
                for ext in self.file_upload_types.split(",")
                if ext.strip()
            }
            fname = (attachment.name or "").lower()
            if allowed and not any(fname.endswith(ext) for ext in allowed):
                return {
                    self.id: _(
                        "File type not allowed. Accepted: %s", self.file_upload_types
                    )
                }
        # Size check
        if self.file_upload_max_size and attachment.file_size:
            max_bytes = self.file_upload_max_size * 1024 * 1024
            if attachment.file_size > max_bytes:
                return {
                    self.id: _(
                        "File exceeds maximum size of %s MB.", self.file_upload_max_size
                    )
                }
        return {}

    def _get_displayed_suggested_answers(self, seed_token: str = "") -> Any:
        """Return suggested answers, shuffled deterministically if shuffle_answers is enabled.

        The shuffle is seeded by a combination of the respondent's access token
        and the question id, ensuring:
        - Each respondent sees a unique order
        - The same respondent always sees the same order (for back-navigation)
        - Different questions get different shuffle orders
        """
        self.ensure_one()
        answers = self.suggested_answer_ids
        if not self.shuffle_answers or not seed_token:
            return answers
        rng = random.Random(f"{seed_token}-{self.id}")
        answer_list = list(answers)
        rng.shuffle(answer_list)
        return self.env["survey.question.answer"].concat(*answer_list)

    def _index(self) -> int:
        """We would normally just use the 'sequence' field of questions BUT, if the pages and questions are
        created without ever moving records around, the sequence field can be set to 0 for all the questions.

        However, the order of the recordset is always correct so we can rely on the index method.
        """
        self.ensure_one()
        return list(self.survey_id.question_and_page_ids).index(self)

    # ------------------------------------------------------------
    # SPEED RATING
    # ------------------------------------------------------------

    def _update_time_limit_from_survey(
        self, is_time_limited: bool | None = None, time_limit: int | None = None
    ) -> None:
        """Update the speed rating values after a change in survey's speed rating configuration.

        * Questions that were not customized will take the new default values from the survey
        * Questions that were customized will not change their values, but this method will check
          and update the `is_time_customized` flag if necessary (to `False`) such that the user
          won't need to "actively" do it to make the question sensitive to change in survey values.

        This is not done with `_compute`s because `is_time_limited` (and `time_limit`) would depend
        on `is_time_customized` and vice versa.
        """
        write_vals = {}
        if is_time_limited is not None:
            write_vals["is_time_limited"] = is_time_limited
        if time_limit is not None:
            write_vals["time_limit"] = time_limit
        non_time_customized_questions = self.filtered(
            lambda s: not s.is_time_customized
        )
        non_time_customized_questions.write(write_vals)

        # Reset `is_time_customized` as necessary
        customized_questions = self - non_time_customized_questions
        back_to_default_questions = customized_questions.filtered(
            lambda q: (
                q.is_time_limited == q.survey_id.session_speed_rating
                and (
                    q.is_time_limited is False
                    or q.time_limit == q.survey_id.session_speed_rating_time_limit
                )
            )
        )
        back_to_default_questions.is_time_customized = False
