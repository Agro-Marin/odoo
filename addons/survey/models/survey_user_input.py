import logging
import re
import textwrap
import uuid
from typing import Any, Self

import requests
from dateutil.relativedelta import relativedelta
from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.libs.json import dumps as json_dumps
from odoo.tools import float_is_zero
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class SurveyUser_Input(models.Model):
    """Metadata for a set of one user's answers to a particular survey"""

    _name = "survey.user_input"
    _description = "Survey User Input"
    _rec_name = "survey_id"
    _order = "create_date desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # answer description
    survey_id = fields.Many2one(
        "survey.survey",
        string="Survey",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
    )
    scoring_type = fields.Selection(string="Scoring", related="survey_id.scoring_type")
    start_datetime = fields.Datetime("Start date and time", readonly=True)
    end_datetime = fields.Datetime("End date and time", readonly=True)
    deadline = fields.Datetime(
        "Deadline",
        help="Datetime until customer can open the survey and submit answers",
    )
    lang_id = fields.Many2one("res.lang", string="Language")
    state = fields.Selection(
        [("new", "New"), ("in_progress", "In Progress"), ("done", "Completed")],
        string="Status",
        default="new",
        readonly=True,
    )
    test_entry = fields.Boolean(readonly=True)
    last_displayed_page_id = fields.Many2one(
        "survey.question", string="Last displayed question/page"
    )
    # attempts management
    is_attempts_limited = fields.Boolean(
        "Limited number of attempts", related="survey_id.is_attempts_limited"
    )
    attempts_limit = fields.Integer(
        "Number of attempts", related="survey_id.attempts_limit"
    )
    attempts_count = fields.Integer("Attempts Count", compute="_compute_attempts_info")
    attempts_number = fields.Integer("Attempt n°", compute="_compute_attempts_info")
    survey_time_limit_reached = fields.Boolean(
        "Survey Time Limit Reached", compute="_compute_survey_time_limit_reached"
    )
    # identification / access
    access_token = fields.Char(
        "Identification token",
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        required=True,
        copy=False,
    )
    invite_token = fields.Char(
        "Invite token", readonly=True, copy=False
    )  # no unique constraint, as it identifies a pool of attempts
    partner_id = fields.Many2one(
        "res.partner", string="Contact", readonly=True, index="btree_not_null"
    )
    email = fields.Char("Email", readonly=True)
    nickname = fields.Char(
        "Nickname",
        help="Attendee nickname, mainly used to identify them in the survey session leaderboard.",
    )
    ip_address = fields.Char(
        "IP Address",
        readonly=True,
        help="Respondent's IP address. Not stored if survey has 'Anonymize IP' enabled.",
    )
    # questions / answers
    user_input_line_ids = fields.One2many(
        "survey.user_input.line", "user_input_id", string="Answers", copy=True
    )
    predefined_question_ids = fields.Many2many(
        "survey.question", string="Predefined Questions", readonly=True
    )
    scoring_percentage = fields.Float(
        "Score (%)", compute="_compute_scoring_values", store=True, compute_sudo=True
    )  # stored for perf reasons
    scoring_total = fields.Float(
        "Total Score",
        compute="_compute_scoring_values",
        store=True,
        compute_sudo=True,
        digits=(10, 2),
    )  # stored for perf reasons
    scoring_success = fields.Boolean(
        "Quiz Passed", compute="_compute_scoring_success", store=True, compute_sudo=True
    )  # stored for perf reasons
    survey_first_submitted = fields.Boolean(string="Survey First Submitted")
    # response quality
    is_speeder = fields.Boolean(
        "Speeder",
        compute="_compute_quality_indicators",
        store=True,
        help="Respondent completed the survey in less than 1/3 of the median duration.",
    )
    is_straight_liner = fields.Boolean(
        "Straight-liner",
        compute="_compute_quality_indicators",
        store=True,
        help="Respondent selected the same answer for every choice/matrix question.",
    )
    quality_score = fields.Integer(
        "Quality Score",
        compute="_compute_quality_indicators",
        store=True,
        help="Response quality from 0 (worst) to 100 (best). Based on speed and answer variety.",
    )
    # live sessions
    is_session_answer = fields.Boolean(
        "Is in a Session", help="Is that user input part of a survey session or not."
    )
    question_time_limit_reached = fields.Boolean(
        "Question Time Limit Reached", compute="_compute_question_time_limit_reached"
    )

    _unique_token = models.Constraint(
        "UNIQUE (access_token)",
        "An access token must be unique!",
    )

    @api.depends(
        "user_input_line_ids.answer_score",
        "user_input_line_ids.question_id",
        "predefined_question_ids.answer_score",
    )
    def _compute_scoring_values(self) -> None:
        """Compute scoring_total and scoring_percentage from answered questions."""
        for user_input in self:
            # sum(multi-choice question scores) + sum(simple answer_type scores)
            total_possible_score = 0
            for question in user_input.predefined_question_ids:
                if question.question_type in ("simple_choice", "dropdown"):
                    total_possible_score += max(
                        [
                            score
                            for score in question.mapped(
                                "suggested_answer_ids.answer_score"
                            )
                            if score > 0
                        ],
                        default=0,
                    )
                elif question.question_type == "multiple_choice":
                    total_possible_score += sum(
                        score
                        for score in question.mapped(
                            "suggested_answer_ids.answer_score"
                        )
                        if score > 0
                    )
                elif question.is_scored_question:
                    total_possible_score += question.answer_score

            if total_possible_score == 0:
                user_input.scoring_percentage = 0
                user_input.scoring_total = 0
            else:
                score_total = sum(user_input.user_input_line_ids.mapped("answer_score"))
                user_input.scoring_total = score_total
                score_percentage = (score_total / total_possible_score) * 100
                user_input.scoring_percentage = (
                    round(score_percentage, 2) if score_percentage > 0 else 0
                )

    @api.depends("scoring_percentage", "survey_id")
    def _compute_scoring_success(self) -> None:
        """Determine whether the respondent passed the quiz threshold."""
        for user_input in self:
            user_input.scoring_success = (
                user_input.scoring_percentage
                >= user_input.survey_id.scoring_success_min
            )

    @api.depends(
        "state",
        "start_datetime",
        "end_datetime",
        "user_input_line_ids.suggested_answer_id",
    )
    def _compute_quality_indicators(self) -> None:
        """Detect speeders and straight-liners for response quality scoring.

        - **Speeder**: completed in < 1/3 of median duration for this survey
        - **Straight-liner**: same suggested_answer_id for all choice questions
        - **Quality score**: 100 minus penalties (50 for speeder, 50 for straight-liner)
        """
        # Pre-compute median duration per survey for speeder detection
        survey_medians = {}
        for user_input in self:
            if (
                user_input.state != "done"
                or not user_input.start_datetime
                or not user_input.end_datetime
            ):
                user_input.is_speeder = False
                user_input.is_straight_liner = False
                user_input.quality_score = 100
                continue

            survey = user_input.survey_id
            if survey.id not in survey_medians:
                durations = [
                    (other.end_datetime - other.start_datetime).total_seconds()
                    for other in survey.user_input_ids.filtered(
                        lambda ui: (
                            ui.state == "done"
                            and ui.start_datetime
                            and ui.end_datetime
                            and not ui.test_entry
                        )
                    )
                ]
                survey_medians[survey.id] = (
                    sorted(durations)[len(durations) // 2] if durations else 0
                )

            # Speeder detection
            duration = (
                user_input.end_datetime - user_input.start_datetime
            ).total_seconds()
            median = survey_medians[survey.id]
            user_input.is_speeder = bool(median and duration < median / 3)

            # Straight-liner detection: check if all choice answers are the same
            choice_lines = user_input.user_input_line_ids.filtered(
                lambda ln: (
                    ln.suggested_answer_id and not ln.skipped and not ln.matrix_row_id
                )
            )
            if len(choice_lines) >= 3:
                unique_answers = {ln.suggested_answer_id.id for ln in choice_lines}
                user_input.is_straight_liner = len(unique_answers) == 1
            else:
                user_input.is_straight_liner = False

            # Quality score
            score = 100
            if user_input.is_speeder:
                score -= 50
            if user_input.is_straight_liner:
                score -= 50
            user_input.quality_score = max(score, 0)

    @api.depends("start_datetime", "survey_id.is_time_limited", "survey_id.time_limit")
    def _compute_survey_time_limit_reached(self) -> None:
        """Checks that the user_input is not exceeding the survey's time limit."""
        for user_input in self:
            if not user_input.is_session_answer and user_input.start_datetime:
                start_time = user_input.start_datetime
                time_limit = user_input.survey_id.time_limit
                user_input.survey_time_limit_reached = (
                    user_input.survey_id.is_time_limited
                    and fields.Datetime.now()
                    >= start_time + relativedelta(minutes=time_limit)
                )
            else:
                user_input.survey_time_limit_reached = False

    @api.depends(
        "survey_id.session_question_id.time_limit",
        "survey_id.session_question_id.is_time_limited",
        "survey_id.session_question_start_time",
    )
    def _compute_question_time_limit_reached(self) -> None:
        """Checks that the user_input is not exceeding the question's time limit.
        Only used in the context of survey sessions."""
        for user_input in self:
            if (
                user_input.is_session_answer
                and user_input.survey_id.session_question_start_time
            ):
                start_time = user_input.survey_id.session_question_start_time
                time_limit = user_input.survey_id.session_question_id.time_limit
                user_input.question_time_limit_reached = (
                    user_input.survey_id.session_question_id.is_time_limited
                    and fields.Datetime.now()
                    >= start_time + relativedelta(seconds=time_limit)
                )
            else:
                user_input.question_time_limit_reached = False

    @api.depends(
        "state",
        "test_entry",
        "survey_id.is_attempts_limited",
        "partner_id",
        "email",
        "invite_token",
    )
    def _compute_attempts_info(self) -> None:
        """Compute attempts_count and attempts_number for limited-attempt surveys."""
        attempts_to_compute = self.filtered(
            lambda user_input: (
                user_input.state == "done"
                and not user_input.test_entry
                and user_input.survey_id.is_attempts_limited
            )
        )

        for user_input in self - attempts_to_compute:
            user_input.attempts_count = 1
            user_input.attempts_number = 1

        if attempts_to_compute:
            self.flush_model(
                [
                    "email",
                    "invite_token",
                    "partner_id",
                    "state",
                    "survey_id",
                    "test_entry",
                ]
            )

            self.env.cr.execute(
                """
                SELECT user_input.id,
                       COUNT(all_attempts_user_input.id) AS attempts_count,
                       COUNT(CASE WHEN all_attempts_user_input.id < user_input.id THEN all_attempts_user_input.id END) + 1 AS attempts_number
                FROM survey_user_input user_input
                LEFT OUTER JOIN survey_user_input all_attempts_user_input
                ON user_input.survey_id = all_attempts_user_input.survey_id
                AND all_attempts_user_input.state = 'done'
                AND all_attempts_user_input.test_entry IS NOT TRUE
                AND (user_input.invite_token IS NULL OR user_input.invite_token = all_attempts_user_input.invite_token)
                AND (user_input.partner_id = all_attempts_user_input.partner_id OR user_input.email = all_attempts_user_input.email)
                WHERE user_input.id = ANY(%s)
                GROUP BY user_input.id;
            """,
                (list(attempts_to_compute.ids),),
            )

            attempts_number_results = self.env.cr.dictfetchall()

            attempts_number_results = {
                attempts_number_result["id"]: {
                    "attempts_number": attempts_number_result["attempts_number"],
                    "attempts_count": attempts_number_result["attempts_count"],
                }
                for attempts_number_result in attempts_number_results
            }

            for user_input in attempts_to_compute:
                attempts_number_result = attempts_number_results.get(user_input.id, {})
                user_input.attempts_number = attempts_number_result.get(
                    "attempts_number", 1
                )
                user_input.attempts_count = attempts_number_result.get(
                    "attempts_count", 1
                )

    @api.model_create_multi
    def create(self, vals_list: list[dict[str, Any]]) -> Self:
        for vals in vals_list:
            if "predefined_question_ids" not in vals:
                survey_id = vals.get(
                    "survey_id", self.env.context.get("default_survey_id")
                )
                survey = self.env["survey.survey"].browse(survey_id)
                vals["predefined_question_ids"] = [
                    Command.set(survey._prepare_user_input_predefined_questions().ids)
                ]
        return super().create(vals_list)

    # ------------------------------------------------------------
    # ACTIONS / BUSINESS
    # ------------------------------------------------------------

    def action_resend(self) -> dict[str, Any]:
        """Re-send the survey invitation to the same respondents."""
        partners = self.env["res.partner"]
        emails = []
        for user_answer in self:
            if user_answer.partner_id:
                partners |= user_answer.partner_id
            elif user_answer.email:
                emails.append(user_answer.email)

        return self.survey_id.with_context(
            default_existing_mode="resend",
            default_partner_ids=partners.ids,
            default_emails=",".join(emails),
        ).action_send_survey()

    def action_print_answers(self) -> dict[str, Any]:
        """Open the website page with the survey form"""
        self.ensure_one()
        url = self.env["ir.http"]._url_for(
            f"/survey/print/{self.survey_id.access_token}?answer_token={self.access_token}",
            self.lang_id.code or None,
        )
        return {
            "type": "ir.actions.act_url",
            "name": "View Answers",
            "target": "self",
            "url": url,
        }

    def action_redirect_to_attempts(self) -> dict[str, Any]:
        """Open a list view of all attempts for the same survey and respondent."""
        self.ensure_one()

        action = self.env["ir.actions.act_window"]._for_xml_id(
            "survey.action_survey_user_input"
        )
        context = dict(self.env.context or {})

        context["create"] = False
        context["search_default_survey_id"] = self.survey_id.id
        context["search_default_group_by_survey"] = False
        if self.partner_id:
            context["search_default_partner_id"] = self.partner_id.id
        elif self.email:
            context["search_default_email"] = self.email

        action["context"] = context
        return action

    @api.model
    def _generate_invite_token(self) -> str:
        """Generate a UUID4 token for grouping invitation attempts."""
        return str(uuid.uuid4())

    def _mark_in_progress(self) -> None:
        """Mark state as 'in_progress', set start_datetime, and fire start webhook."""
        self.write({"start_datetime": fields.Datetime.now(), "state": "in_progress"})
        for user_input in self:
            if user_input.survey_id.webhook_url and not user_input.test_entry:
                user_input._fire_webhook("survey_started")

    def _mark_done(self) -> None:
        """This method will:
        1. Evaluate calculated/hidden fields
        2. Mark the state as 'done'
        3. Send the certification email with attached document if
        - The survey is a certification
        - It has a certification_mail_template_id set
        - The user succeeded the test
        4. Notify survey subtype subscribers of the newly completed input
        Will also run challenge Cron to give the certification badge if any."""
        self._evaluate_calculated_fields()
        self.write(
            {
                "end_datetime": fields.Datetime.now(),
                "state": "done",
            }
        )

        challenge_sudo = self.env["gamification.challenge"].sudo()
        badge_ids = []
        self._notify_new_participation_subscribers()
        for user_input in self:
            if user_input.survey_id.certification and user_input.scoring_success:
                if (
                    user_input.survey_id.certification_mail_template_id
                    and not user_input.test_entry
                ):
                    user_input.survey_id.certification_mail_template_id.send_mail(
                        user_input.id, email_layout_xmlid="mail.mail_notification_light"
                    )
                if user_input.survey_id.certification_give_badge:
                    badge_ids.append(user_input.survey_id.certification_badge_id.id)

            # Update predefined_question_id to remove inactive questions
            user_input.predefined_question_ids -= (
                user_input._get_inactive_conditional_questions()
            )

        if badge_ids:
            challenges = challenge_sudo.search([("reward_id", "in", badge_ids)])
            if challenges:
                challenge_sudo._cron_update(ids=challenges.ids, commit=False)

        # Fire completion webhooks (deferred until after transaction commit)
        for user_input in self:
            if user_input.survey_id.webhook_url and not user_input.test_entry:
                user_input._fire_completion_webhook()

        # Execute follow-up rules
        for user_input in self.filtered(lambda ui: not ui.test_entry):
            for rule in user_input.survey_id.followup_rule_ids.filtered("active"):
                rule._execute(user_input)

    def _fire_completion_webhook(self) -> None:
        """Fire the completion webhook (backward-compatible entry point)."""
        self._fire_webhook("survey_completed")

    def _fire_webhook(self, event: str) -> None:
        """POST survey event data to the configured webhook URL after commit.

        :param event: event type string (survey_started, page_submitted, survey_completed)

        Uses the postcommit hook pattern to ensure the webhook only fires
        after the transaction is successfully committed.
        """
        self.ensure_one()
        survey = self.survey_id
        webhook_url = survey.webhook_url
        if not webhook_url:
            return

        # Check if this event type should fire
        if survey.webhook_events == "completed" and event != "survey_completed":
            return

        payload = self._prepare_webhook_payload(event)
        json_payload = json_dumps(payload)

        def do_post():
            try:
                requests.post(
                    webhook_url,
                    data=json_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=5,
                )
            except requests.RequestException:
                _logger.warning(
                    "Survey webhook (%s) failed for input %s to %s",
                    event, self.id, webhook_url,
                    exc_info=True,
                )

        self.env.cr.postcommit.add(do_post)

    def _prepare_webhook_payload(self, event: str = "survey_completed") -> dict[str, Any]:
        """Build the JSON payload for a webhook event."""
        self.ensure_one()
        answers = []
        for line in self.user_input_line_ids:
            if line.skipped:
                continue
            answers.append(
                {
                    "question_id": line.question_id.id,
                    "question_title": line.question_id.title,
                    "question_type": line.question_id.question_type,
                    "answer_value": line._get_answer_value(),
                }
            )
        return {
            "event": event,
            "survey_id": self.survey_id.id,
            "survey_title": self.survey_id.title,
            "user_input_id": self.id,
            "respondent": {
                "email": self.email or "",
                "nickname": self.nickname or "",
                "partner_id": self.partner_id.id if self.partner_id else None,
            },
            "score_percentage": self.scoring_percentage,
            "scoring_success": self.scoring_success,
            "completed_at": str(self.end_datetime),
            "answers": answers,
        }

    def get_start_url(self) -> str:
        """Return the URL for a respondent to start/resume this survey attempt."""
        self.ensure_one()
        return f"{self.survey_id.get_start_url()}?answer_token={self.access_token}"

    def get_print_url(self) -> str:
        """Return the URL for a respondent to view/print their completed answers."""
        self.ensure_one()
        return f"{self.survey_id.get_print_url()}?answer_token={self.access_token}"

    # ------------------------------------------------------------
    # CALCULATED / HIDDEN FIELDS
    # ------------------------------------------------------------

    # Regex to extract Q<id> references from calculated expressions
    _CALC_REF_RE = re.compile(r"\bQ(\d+)\b")

    # Allowed names in calculated expressions (safe subset)
    _CALC_ALLOWED_NAMES = {
        "min": min, "max": max, "abs": abs, "round": round,
        "sum": sum, "len": len, "int": int, "float": float,
        "True": True, "False": False, "None": None,
    }

    def _evaluate_calculated_fields(self) -> None:
        """Evaluate all calculated/hidden fields and save their results.

        For each ``calculated`` question in the survey, resolves Q<id>
        references to the respondent's numerical answers, evaluates the
        arithmetic expression, and stores the result as a
        ``survey.user_input.line`` with ``answer_type='numerical_box'``.

        Uses ``safe_eval`` with a restricted namespace — only basic math
        functions are available, no builtins or module access.
        """
        for user_input in self:
            calculated_questions = user_input.survey_id.question_ids.filtered(
                lambda q: q.question_type == "calculated" and q.calculated_expression
            )
            if not calculated_questions:
                continue

            # Build Q<id> → numerical value mapping from existing answers
            answer_values = {}
            for line in user_input.user_input_line_ids.filtered(
                lambda ln: not ln.skipped
            ):
                qid = line.question_id.id
                if line.answer_type == "numerical_box":
                    answer_values[qid] = line.value_numerical_box
                elif line.answer_type == "scale":
                    answer_values[qid] = float(line.value_scale)
                elif line.answer_type == "suggestion" and line.suggested_answer_id:
                    answer_values[qid] = line.suggested_answer_id.answer_score

            for question in calculated_questions:
                expr = question.calculated_expression
                # Build local namespace: Q42 → value
                local_vars = dict(self._CALC_ALLOWED_NAMES)
                for match in self._CALC_REF_RE.finditer(expr):
                    ref_id = int(match.group(1))
                    local_vars[f"Q{ref_id}"] = answer_values.get(ref_id, 0)

                try:
                    result = safe_eval(expr, local_vars, nocopy=True)
                    result = float(result)
                except Exception:
                    _logger.warning(
                        "Failed to evaluate calculated field %s (expression: %s)",
                        question.id, expr,
                    )
                    continue

                # Save or update the computed value
                existing = user_input.user_input_line_ids.filtered(
                    lambda ln, q=question: ln.question_id == q
                )
                vals = {
                    "user_input_id": user_input.id,
                    "question_id": question.id,
                    "skipped": False,
                    "answer_type": "numerical_box",
                    "value_numerical_box": result,
                }
                if existing:
                    existing.write(vals)
                else:
                    self.env["survey.user_input.line"].create(vals)

    # ------------------------------------------------------------
    # RESPONSE PIPING
    # ------------------------------------------------------------

    # Matches both {{Q<id>}} (database ID, preferred) and legacy {{Q<index>}}
    # (1-based visible index).  The two forms are disambiguated at resolution
    # time: if the number matches a question id in the survey it is treated
    # as an id; otherwise it falls back to 1-based index for backward compat.
    _PIPING_RE = re.compile(r"\{\{Q(\d+)\}\}")

    def _resolve_piping(self, text: str | Markup) -> str | Markup:
        """Replace ``{{QN}}`` placeholders in *text* with this respondent's answers.

        ``N`` is resolved as follows:

        1. If ``N`` matches the database id of a question belonging to this
           survey, the answer for that question is used.  This is the preferred
           (stable) form — it survives question reordering.
        2. Otherwise, ``N`` is treated as a **1-based visible index** for
           backward compatibility with existing surveys that used the old
           positional syntax.

        For choice questions the selected answer label is inserted; for
        free-text/numeric questions the raw value is used.

        Unknown or unanswered references are replaced with an empty string so
        the respondent never sees raw placeholder syntax.

        When *text* is a :class:`~markupsafe.Markup` instance (e.g. an Html
        field value), substituted answer values are HTML-escaped and the return
        value preserves the ``Markup`` type so QWeb renders HTML correctly.
        """
        if not text or "{{Q" not in text:
            return text
        self.ensure_one()

        is_markup = isinstance(text, Markup)

        questions = self.survey_id.question_ids  # ordered by sequence
        question_ids = set(questions.ids)

        # Build both mappings: by database id and by 1-based index
        answer_by_id: dict[int, str] = {}
        answer_by_index: dict[int, str] = {}
        for idx, question in enumerate(questions, start=1):
            lines = self.user_input_line_ids.filtered(
                lambda l, q=question: l.question_id == q and not l.skipped
            )
            if not lines:
                continue
            if question.question_type == "multiple_choice":
                values = [
                    line._get_answer_value()
                    for line in lines
                    if line._get_answer_value() is not None
                ]
                raw_value = ", ".join(str(v) for v in values)
            else:
                raw_value = str(lines[0]._get_answer_value() or "")
            display = escape(raw_value) if is_markup else raw_value
            answer_by_id[question.id] = display
            answer_by_index[idx] = display

        def _replace(match):
            num = int(match.group(1))
            # Prefer database id lookup; fall back to 1-based index
            if num in question_ids:
                return answer_by_id.get(num, "")
            return answer_by_index.get(num, "")

        result = self._PIPING_RE.sub(_replace, text)
        return Markup(result) if is_markup else result

    # ------------------------------------------------------------
    # CREATE / UPDATE LINES FROM SURVEY FRONTEND INPUT
    # ------------------------------------------------------------

    def _save_lines(
        self,
        question: Any,
        answer: Any,
        comment: str | None = None,
        overwrite_existing: bool = True,
    ) -> None:
        """Save answers to questions, depending on question type.

        :param bool overwrite_existing: if an answer already exists for question and user_input_id
        it will be overwritten (or deleted for 'choice' questions) in order to maintain data consistency.
        :raises UserError: if line exists and overwrite_existing is False
        """
        # Statement and calculated questions have no direct user input
        if question.question_type in ("statement", "calculated"):
            return

        old_answers = self.env["survey.user_input.line"].search(
            [("user_input_id", "=", self.id), ("question_id", "=", question.id)]
        )
        if old_answers and not overwrite_existing:
            raise UserError(_("This answer cannot be overwritten."))

        if question.question_type in [
            "char_box",
            "text_box",
            "scale",
            "nps",
            "numerical_box",
            "slider",
            "rating",
            "date",
            "datetime",
        ]:
            self._save_line_simple_answer(question, old_answers, answer)
            if question.save_as_email and answer:
                self.write({"email": answer})
            if question.save_as_nickname and answer:
                self.write({"nickname": answer})

        elif question.question_type in ["simple_choice", "dropdown", "multiple_choice"]:
            self._save_line_choice(question, old_answers, answer, comment)
        elif question.question_type in ("matrix", "likert"):
            self._save_line_matrix(question, old_answers, answer, comment)
        elif question.question_type in ("ranking", "constant_sum"):
            self._save_line_per_answer(question, old_answers, answer)
        elif question.question_type == "file_upload":
            self._save_line_file_upload(question, old_answers, answer)
        else:
            raise ValueError(
                f"{question.question_type}: This type of question has no saving function"
            )

    def _save_line_simple_answer(
        self, question: Any, old_answers: Any, answer: Any
    ) -> Any:
        """Save or update a single-value answer (text, number, date, scale)."""
        vals = self._get_line_answer_values(question, answer, question.question_type)
        if old_answers:
            old_answers.write(vals)
            return old_answers
        else:
            return self.env["survey.user_input.line"].create(vals)

    def _save_line_choice(
        self, question: Any, old_answers: Any, answers: Any, comment: str | None
    ) -> Any:
        """Replace existing choice answers with new selection(s), optionally with a comment."""
        if not (isinstance(answers, list)):
            answers = [answers]

        if not answers and not (comment and question.comment_count_as_answer):
            # add a False answer to force saving a skipped line
            # this will make this question correctly considered as skipped in statistics
            answers = [False]

        vals_list = [
            self._get_line_answer_values(question, answer, "suggestion")
            for answer in answers
        ]

        if comment:
            vals_list.append(self._get_line_comment_values(question, comment))

        old_answers.sudo().unlink()
        return self.env["survey.user_input.line"].create(vals_list)

    def _save_line_matrix(
        self, question: Any, old_answers: Any, answers: dict | None, comment: str | None
    ) -> Any:
        """Replace existing matrix answers with new row/column selections."""
        vals_list = []

        if not answers and question.matrix_row_ids:
            # add a False answer to force saving a skipped line
            # this will make this question correctly considered as skipped in statistics
            answers = {question.matrix_row_ids[0].id: [False]}

        if answers:
            for row_key, row_answer in answers.items():
                for answer in row_answer:
                    vals = self._get_line_answer_values(question, answer, "suggestion")
                    vals["matrix_row_id"] = int(row_key)
                    vals_list.append(vals.copy())

        if comment:
            vals_list.append(self._get_line_comment_values(question, comment))

        old_answers.sudo().unlink()
        return self.env["survey.user_input.line"].create(vals_list)

    def _save_line_per_answer(
        self, question: Any, old_answers: Any, answers: dict | None
    ) -> Any:
        """Save per-answer values for ranking and constant_sum question types.

        :param answers: dict mapping ``{suggested_answer_id: value}`` where value
            is a rank position (ranking) or allocated points (constant_sum).
        """
        vals_list = []
        if not answers:
            vals_list.append(
                {
                    "user_input_id": self.id,
                    "question_id": question.id,
                    "skipped": True,
                    "answer_type": None,
                }
            )
        else:
            for answer_id, value in answers.items():
                vals_list.append(
                    {
                        "user_input_id": self.id,
                        "question_id": question.id,
                        "skipped": False,
                        "answer_type": "numerical_box",
                        "suggested_answer_id": int(answer_id),
                        "value_numerical_box": float(value),
                    }
                )
        old_answers.sudo().unlink()
        return self.env["survey.user_input.line"].create(vals_list)

    def _save_line_file_upload(
        self, question: Any, old_answers: Any, answer: Any
    ) -> Any:
        """Save file upload answer as an ir.attachment reference.

        :param answer: attachment ID (created by the upload controller).
        """
        vals = {
            "user_input_id": self.id,
            "question_id": question.id,
            "skipped": not answer,
            "answer_type": "char_box" if answer else None,
            "value_char_box": str(answer) if answer else False,
        }
        if old_answers:
            old_answers.write(vals)
            return old_answers
        return self.env["survey.user_input.line"].create(vals)

    def _get_line_answer_values(
        self, question: Any, answer: Any, answer_type: str
    ) -> dict[str, Any]:
        """Build field values for a survey.user_input.line record from raw answer data."""
        vals = {
            "user_input_id": self.id,
            "question_id": question.id,
            "skipped": False,
            "answer_type": answer_type,
        }
        if not answer or (isinstance(answer, str) and not answer.strip()):
            vals.update(answer_type=None, skipped=True)
            return vals

        if answer_type == "suggestion":
            vals["suggested_answer_id"] = int(answer)
        elif answer_type in ("numerical_box", "slider"):
            vals["answer_type"] = "numerical_box"
            vals["value_numerical_box"] = float(answer)
        elif answer_type in ("scale", "nps", "rating"):
            vals["answer_type"] = "scale"  # NPS and rating stored as scale
            vals["value_scale"] = int(answer)
        else:
            vals[f"value_{answer_type}"] = answer
        return vals

    def _get_line_comment_values(self, question: Any, comment: str) -> dict[str, Any]:
        """Build field values for a comment-type survey.user_input.line record."""
        return {
            "user_input_id": self.id,
            "question_id": question.id,
            "skipped": False,
            "answer_type": "char_box",
            "value_char_box": comment,
        }

    # ------------------------------------------------------------
    # STATISTICS / RESULTS
    # ------------------------------------------------------------

    def _prepare_statistics(self) -> dict[Any, dict[str, Any]]:
        """Prepares survey.user_input's statistics to display various charts on the frontend.
        Returns a structure containing answers statistics "by section" and "totals" for every input in self.

        e.g returned structure:
        {
            survey.user_input(1,): {
                'by_section': {
                    'Uncategorized': {
                        'question_count': 2,
                        'correct': 2,
                        'partial': 0,
                        'incorrect': 0,
                        'skipped': 0,
                    },
                    'Mathematics': {
                        'question_count': 3,
                        'correct': 1,
                        'partial': 1,
                        'incorrect': 0,
                        'skipped': 1,
                    },
                    'Geography': {
                        'question_count': 4,
                        'correct': 2,
                        'partial': 0,
                        'incorrect': 2,
                        'skipped': 0,
                    }
                },
                'totals' [{
                    'text': 'Correct',
                    'count': 5,
                }, {
                    'text': 'Partially',
                    'count': 1,
                }, {
                    'text': 'Incorrect',
                    'count': 2,
                }, {
                    'text': 'Unanswered',
                    'count': 1,
                }]
            }
        }"""
        res = {user_input: {"by_section": {}} for user_input in self}

        scored_questions = self.mapped("predefined_question_ids").filtered(
            lambda question: question.is_scored_question
        )

        for question in scored_questions:
            question_incorrect_scored_answers = self.env["survey.question.answer"]
            question_correct_suggested_answers = self.env["survey.question.answer"]
            if question.question_type in ("simple_choice", "dropdown"):
                question_incorrect_scored_answers = (
                    question.suggested_answer_ids.filtered(
                        lambda answer: not answer.is_correct and answer.answer_score > 0
                    )
                )
            if question.question_type in ["simple_choice", "dropdown", "multiple_choice"]:
                question_correct_suggested_answers = (
                    question.suggested_answer_ids.filtered(
                        lambda answer: answer.is_correct
                    )
                )

            question_section = question.page_id.title or _("Uncategorized")
            for user_input in self:
                user_input_lines = user_input.user_input_line_ids.filtered(
                    lambda line, q=question: (
                        line.question_id == q
                        and (
                            line.answer_type != "char_box" or q.comment_count_as_answer
                        )
                    )
                )
                if question.question_type in ("simple_choice", "dropdown"):
                    answer_result_key = self._simple_choice_question_answer_result(
                        user_input_lines,
                        question_correct_suggested_answers,
                        question_incorrect_scored_answers,
                    )
                elif question.question_type == "multiple_choice":
                    answer_result_key = self._multiple_choice_question_answer_result(
                        user_input_lines, question_correct_suggested_answers
                    )
                else:
                    answer_result_key = self._simple_question_answer_result(
                        user_input_lines
                    )

                if question_section not in res[user_input]["by_section"]:
                    res[user_input]["by_section"][question_section] = {
                        "question_count": 0,
                        "correct": 0,
                        "partial": 0,
                        "incorrect": 0,
                        "skipped": 0,
                    }

                res[user_input]["by_section"][question_section]["question_count"] += 1
                res[user_input]["by_section"][question_section][answer_result_key] += 1

        for user_input in self:
            res[user_input]["totals"] = self._aggregate_section_totals(
                res[user_input]["by_section"]
            )

        return res

    def _aggregate_section_totals(
        self,
        by_section: dict[str, dict[str, int]],
    ) -> list[dict[str, Any]]:
        """Sum per-section answer counts into a totals list for display."""
        correct = partial = incorrect = skipped = 0
        for section_counts in by_section.values():
            correct += section_counts.get("correct", 0)
            partial += section_counts.get("partial", 0)
            incorrect += section_counts.get("incorrect", 0)
            skipped += section_counts.get("skipped", 0)
        return [
            {"text": _("Correct"), "count": correct},
            {"text": _("Partially"), "count": partial},
            {"text": _("Incorrect"), "count": incorrect},
            {"text": _("Unanswered"), "count": skipped},
        ]

    def _multiple_choice_question_answer_result(
        self, user_input_lines: Any, question_correct_suggested_answers: Any
    ) -> str:
        """Classify a multiple-choice answer as correct, partial, incorrect, or skipped."""
        correct_user_input_lines = user_input_lines.filtered(
            lambda line: line.answer_is_correct and not line.skipped
        ).mapped("suggested_answer_id")
        incorrect_user_input_lines = user_input_lines.filtered(
            lambda line: not line.answer_is_correct and not line.skipped
        )
        if (
            question_correct_suggested_answers
            and correct_user_input_lines == question_correct_suggested_answers
            and not incorrect_user_input_lines
        ):
            return "correct"
        elif correct_user_input_lines:
            # Some correct answers selected (but not all, or also wrong ones selected)
            return "partial"
        elif incorrect_user_input_lines:
            return "incorrect"
        else:
            return "skipped"

    def _simple_choice_question_answer_result(
        self,
        user_input_line: Any,
        question_correct_suggested_answers: Any,
        question_incorrect_scored_answers: Any,
    ) -> str:
        """Classify a simple-choice answer as correct, partial, incorrect, or skipped."""
        user_answer = (
            user_input_line.suggested_answer_id
            if not user_input_line.skipped
            else self.env["survey.question.answer"]
        )
        if user_answer in question_correct_suggested_answers:
            return "correct"
        elif user_answer in question_incorrect_scored_answers:
            return "partial"
        elif user_answer:
            return "incorrect"
        else:
            return "skipped"

    def _simple_question_answer_result(self, user_input_line: Any) -> str:
        """Classify a non-choice answer as correct, incorrect, or skipped."""
        if user_input_line.skipped:
            return "skipped"
        elif user_input_line.answer_is_correct:
            return "correct"
        else:
            return "incorrect"

    # ------------------------------------------------------------
    # Conditional Questions Management
    # ------------------------------------------------------------

    def _get_conditional_values(self) -> tuple[dict, dict, Any]:
        """For survey containing conditional questions, we need a triggered_questions_by_answer map that contains
               {key: answer, value: the question that the answer triggers, if selected},
        The idea is to be able to verify, on every answer check, if this answer is triggering the display
        of another question.
        If answer is not in the conditional map:
           - nothing happens.
        If the answer is in the conditional map:
           - If we are in ONE PAGE survey : (handled at CLIENT side)
               -> display immediately the depending question
           - If we are in PAGE PER SECTION : (handled at CLIENT side)
               - If related question is on the same page :
                   -> display immediately the depending question
               - If the related question is not on the same page :
                   -> keep the answers in memory and check at next page load if the depending question is in there and
                      display it, if so.
           - If we are in PAGE PER QUESTION : (handled at SERVER side)
               -> During submit, determine which is the next question to display getting the next question
                  that is the next in sequence and that is either not triggered by another question's answer, or that
                  is triggered by an already selected answer.
        To do all this, we need to return:
           - triggering_answers_by_question: dict -> for a given question, the answers that triggers it
               Used mainly to ease template rendering
           - triggered_questions_by_answer: dict -> for a given answer, list of questions triggered by this answer;
               Used mainly for dynamic show/hide behaviour at client side
           - list of all selected answers: [answer_id1, answer_id2, ...] (for survey reloading, otherwise, this list is
             updated at client side)
        """
        triggering_answers_by_question = {}
        triggered_questions_by_answer = {}
        # Ignore conditional configuration if randomised questions selection
        if self.survey_id.questions_selection != "random":
            triggering_answers_by_question, triggered_questions_by_answer = (
                self.survey_id._get_conditional_maps()
            )
        selected_answers = self._get_selected_suggested_answers()

        return (
            triggering_answers_by_question,
            triggered_questions_by_answer,
            selected_answers,
        )

    def _get_selected_suggested_answers(self) -> Any:
        """
        For now, only simple and multiple choices question type are handled by the conditional questions feature.
        Mapping all the suggested answers selected by the user will also include answers from matrix question type,
        Those ones won't be used.
        Maybe someday, conditional questions feature will be extended to work with matrix question.
        :return: all the suggested answer selected by the user.
        """
        return self.mapped("user_input_line_ids.suggested_answer_id")

    def _clear_inactive_conditional_answers(self) -> None:
        """
        Clean eventual answers on conditional questions that should not have been displayed to user.
        This method is used mainly for page per question survey, a similar method does the same treatment
        at client side for the other survey layouts.
        E.g.: if depending answer was uncheck after answering conditional question, we need to clear answers
              of that conditional question, for two reasons:
              - ensure correct scoring
              - if the selected answer triggers another question later in the survey, if the answer is not cleared,
                a question that should not be displayed to the user will be.

        TODO DBE: Maybe this can be the only cleaning method, even for section_per_page or one_page where
        conditional questions are, for now, cleared in JS directly. But this can be annoying if user typed a long
        answer, changed their mind unchecking depending answer and changed again their mind by rechecking the depending
        answer -> For now, the long answer will be lost. If we use this as the master cleaning method,
        long answer will be cleared only during submit.
        """
        inactive_questions = self._get_inactive_conditional_questions()

        # delete user.input.line on question that should not be answered.
        answers_to_delete = self.user_input_line_ids.filtered(
            lambda answer: answer.question_id in inactive_questions
        )
        answers_to_delete.unlink()

    def _get_inactive_conditional_questions(self) -> Any:
        """Return survey.question records whose trigger conditions are not met.

        Evaluates both answer-based triggers (``triggering_answer_ids``) and
        value-based triggers (``triggering_question_id`` + operator + value).
        A question with *both* trigger types is shown if *either* is satisfied.
        """
        triggering_answers_by_question, _, selected_answers = (
            self._get_conditional_values()
        )

        inactive_questions = self.env["survey.question"]
        for question in self.sudo().survey_id.question_ids:
            has_answer_trigger = bool(question.triggering_answer_ids)
            has_value_trigger = bool(question.triggering_question_id)

            if not has_answer_trigger and not has_value_trigger:
                continue  # unconditional question — always shown

            answer_trigger_met = (
                has_answer_trigger
                and bool(question.triggering_answer_ids & selected_answers)
            )
            value_trigger_met = (
                has_value_trigger
                and self._evaluate_value_trigger(question)
            )

            # Question is inactive if ALL configured triggers are unmet
            if not answer_trigger_met and not value_trigger_met:
                inactive_questions |= question

        return inactive_questions

    def _evaluate_value_trigger(self, question: Any) -> bool:
        """Evaluate a value-based conditional trigger for a single question.

        Checks this respondent's answer to ``question.triggering_question_id``
        against ``question.triggering_operator`` and ``question.triggering_value``.
        """
        trigger_q = question.triggering_question_id
        op = question.triggering_operator
        threshold = question.triggering_value or ""

        # Find the respondent's answer line for the trigger question
        answer_line = self.user_input_line_ids.filtered(
            lambda ln, q=trigger_q: ln.question_id == q and not ln.skipped
        )
        if not answer_line:
            return op == "is_not_answered"
        if op == "is_answered":
            return True
        if op == "is_not_answered":
            return False

        # Get the actual value for comparison
        answer_value = answer_line[0]._get_answer_value()
        if answer_value is None:
            return op == "is_not_answered"

        # Numeric comparison for numeric-valued question types
        if trigger_q.question_type in ("numerical_box", "slider", "scale", "nps", "rating"):
            try:
                num_val = float(answer_value)
                num_threshold = float(threshold)
            except ValueError, TypeError:
                return False
            return {
                "eq": num_val == num_threshold,
                "neq": num_val != num_threshold,
                "gt": num_val > num_threshold,
                "gte": num_val >= num_threshold,
                "lt": num_val < num_threshold,
                "lte": num_val <= num_threshold,
            }.get(op, False)

        # String comparison for text-based question types
        str_val = str(answer_value).strip()
        str_threshold = threshold.strip()
        return {
            "eq": str_val.lower() == str_threshold.lower(),
            "neq": str_val.lower() != str_threshold.lower(),
            "gt": str_val > str_threshold,
            "gte": str_val >= str_threshold,
            "lt": str_val < str_threshold,
            "lte": str_val <= str_threshold,
            "contains": str_threshold.lower() in str_val.lower(),
        }.get(op, False)

    def _get_print_questions(self) -> Any:
        """Get the questions to display : the ones that should have been answered = active questions
            In case of session, active questions are based on most voted answers
        :return: active survey.question browse records
        """
        survey = self.survey_id
        if self.is_session_answer:
            most_voted_answers = survey._get_session_most_voted_answers()
            inactive_questions = (
                most_voted_answers._get_inactive_conditional_questions()
            )
        else:
            inactive_questions = self._get_inactive_conditional_questions()
        return survey.question_ids - inactive_questions

    def _get_next_skipped_page_or_question(self) -> Any:
        """Get next skipped question or page in case the option 'can_go_back' is set on the survey
        It loops to the first skipped question or page if 'last_displayed_page_id' is the last
        skipped question or page."""
        self.ensure_one()
        skipped_mandatory_answer_ids = self.user_input_line_ids.filtered(
            lambda answer: answer.skipped and answer.question_id.constr_mandatory
        )

        if not skipped_mandatory_answer_ids:
            return self.env["survey.question"]

        page_or_question_key = (
            "page_id"
            if self.survey_id.questions_layout == "page_per_section"
            else "question_id"
        )
        page_or_question_ids = skipped_mandatory_answer_ids.mapped(
            page_or_question_key
        ).sorted()

        if (
            self.last_displayed_page_id not in page_or_question_ids
            or self.last_displayed_page_id == page_or_question_ids[-1]
        ):
            return page_or_question_ids[0]

        current_page_index = page_or_question_ids.ids.index(
            self.last_displayed_page_id.id
        )
        return page_or_question_ids[current_page_index + 1]

    def _get_skipped_questions(self) -> Any:
        """Return mandatory questions that were skipped by the respondent."""
        self.ensure_one()

        return self.user_input_line_ids.filtered(
            lambda answer: answer.skipped and answer.question_id.constr_mandatory
        ).question_id

    def _is_last_skipped_page_or_question(self, page_or_question: Any) -> bool:
        """In case of a submitted survey tells if the question or page is the last
        skipped page or question.

        This is used to :

        - Display a Submit button if the actual question is the last skipped question.
        - Avoid displaying a Submit button on the last survey question if there are
          still skipped questions before.
        - Avoid displaying the next page if submitting the latest skipped question.

        :param page_or_question: page if survey's layout is page_per_section, question if page_per_question.
        """
        if self.survey_id.questions_layout == "one_page":
            return True
        skipped = self._get_skipped_questions()
        if not skipped:
            return True
        if self.survey_id.questions_layout == "page_per_section":
            skipped = skipped.page_id
        return skipped[-1:] == page_or_question

    # ------------------------------------------------------------
    # MESSAGING
    # ------------------------------------------------------------

    def _notify_new_participation_subscribers(self) -> None:
        """Post a chatter message to followers when a respondent completes the survey."""
        subtype_id = self.env.ref(
            "survey.mt_survey_survey_user_input_completed", raise_if_not_found=False
        )
        if not self.ids or not subtype_id:
            return
        author_id = (
            self.env.ref("base.partner_root").id
            if self.env.user.is_public
            else self.env.user.partner_id.id
        )
        # Only post if there are any followers
        recipients_data = self.env["mail.followers"]._get_recipient_data(
            self.survey_id, "notification", subtype_id.id
        )
        followed_survey_ids = [
            survey_id for survey_id, followers in recipients_data.items() if followers
        ]
        for user_input in self.filtered(
            lambda user_input_: user_input_.survey_id.id in followed_survey_ids
        ):
            survey_title = user_input.survey_id.title
            if user_input.partner_id:
                body = _(
                    '%(participant)s just participated in "%(survey_title)s".',
                    participant=user_input.partner_id.display_name,
                    survey_title=survey_title,
                )
            else:
                body = _(
                    'Someone just participated in "%(survey_title)s".',
                    survey_title=survey_title,
                )

            user_input.message_post(
                author_id=author_id,
                body=body,
                subtype_xmlid="survey.mt_survey_user_input_completed",
            )

    # ------------------------------------------------------------
    # DATA RETENTION CRON
    # ------------------------------------------------------------

    @api.model
    def _cron_cleanup_expired_responses(self) -> None:
        """Delete completed survey responses that exceed their survey's retention period.

        Called by the ``survey_cleanup_expired_responses`` cron job.
        Only acts on surveys with ``data_retention_days > 0``.
        """
        surveys_with_retention = self.env["survey.survey"].search(
            [
                ("data_retention_days", ">", 0),
            ]
        )
        for survey in surveys_with_retention:
            cutoff = fields.Datetime.now() - relativedelta(
                days=survey.data_retention_days
            )
            expired = self.search(
                [
                    ("survey_id", "=", survey.id),
                    ("state", "=", "done"),
                    ("end_datetime", "<", cutoff),
                    ("test_entry", "=", False),
                ]
            )
            if expired:
                _logger.info(
                    "Data retention: deleting %s expired responses for survey %s (id=%s)",
                    len(expired),
                    survey.title,
                    survey.id,
                )
                expired.sudo().unlink()


class SurveyUser_InputLine(models.Model):
    _name = "survey.user_input.line"
    _description = "Survey User Input Line"
    _rec_name = "user_input_id"
    _order = "question_sequence, id"

    # survey data
    user_input_id = fields.Many2one(
        "survey.user_input",
        string="User Input",
        ondelete="cascade",
        required=True,
        index=True,
    )
    survey_id = fields.Many2one(
        related="user_input_id.survey_id", string="Survey", store=True, readonly=False
    )
    question_id = fields.Many2one(
        "survey.question",
        string="Question",
        ondelete="cascade",
        required=True,
        index=True,
    )
    page_id = fields.Many2one(
        related="question_id.page_id", string="Section", readonly=False
    )
    question_sequence = fields.Integer(
        "Sequence", related="question_id.sequence", store=True
    )
    lang_id = fields.Many2one("res.lang", related="user_input_id.lang_id")
    # answer
    skipped = fields.Boolean("Skipped")
    answer_type = fields.Selection(
        [
            ("text_box", "Free Text"),
            ("char_box", "Text"),
            ("numerical_box", "Number"),
            ("scale", "Number"),
            ("date", "Date"),
            ("datetime", "Datetime"),
            ("suggestion", "Suggestion"),
        ],
        string="Answer Type",
    )
    value_char_box = fields.Char("Text answer")
    value_numerical_box = fields.Float("Numerical answer")
    value_scale = fields.Integer("Scale value")
    value_date = fields.Date("Date answer")
    value_datetime = fields.Datetime("Datetime answer")
    value_text_box = fields.Text("Free Text answer")
    suggested_answer_id = fields.Many2one(
        "survey.question.answer", string="Suggested answer"
    )
    matrix_row_id = fields.Many2one("survey.question.answer", string="Row answer")
    # scoring
    answer_score = fields.Float(
        "Score", compute="_compute_answer_score", precompute=True, store=True
    )
    answer_is_correct = fields.Boolean(
        "Correct", compute="_compute_answer_score", precompute=True, store=True
    )

    @api.depends(
        "answer_type",
        "value_text_box",
        "value_numerical_box",
        "value_char_box",
        "value_date",
        "value_datetime",
        "suggested_answer_id.value",
        "matrix_row_id.value",
    )
    def _compute_display_name(self) -> None:
        """Build a human-readable display name from the answer value."""
        for line in self:
            if line.answer_type == "char_box":
                line.display_name = line.value_char_box
            elif line.answer_type == "text_box" and line.value_text_box:
                line.display_name = textwrap.shorten(
                    line.value_text_box, width=50, placeholder=" [...]"
                )
            elif line.answer_type == "numerical_box":
                line.display_name = line.value_numerical_box
            elif line.answer_type == "date":
                line.display_name = fields.Date.to_string(line.value_date)
            elif line.answer_type == "datetime":
                line.display_name = fields.Datetime.to_string(
                    fields.Datetime.context_timestamp(
                        self.env.user, line.value_datetime
                    )
                )
            elif line.answer_type == "scale":
                line.display_name = line.value_scale
            elif line.answer_type == "suggestion":
                if line.matrix_row_id:
                    line.display_name = (
                        f"{line.suggested_answer_id.value}: {line.matrix_row_id.value}"
                    )
                else:
                    line.display_name = line.suggested_answer_id.value

            if not line.display_name:
                line.display_name = _("Skipped")

    @api.depends(
        "answer_type",
        "value_text_box",
        "value_numerical_box",
        "value_date",
        "value_datetime",
        "suggested_answer_id",
        "user_input_id",
    )
    def _compute_answer_score(self) -> None:
        """Get values for: answer_is_correct and associated answer_score.

        Calculates whether an answer_is_correct and its score based on 'answer_type' and
        corresponding question. Handles choice (answer_type == 'suggestion') questions
        separately from other question types. Each selected choice answer is handled as an
        individual answer.

        If score depends on the speed of the answer, it is adjusted as follows:
         - If the user answers in less than 2 seconds, they receive 100% of the possible points.
         - If user answers after that, they receive 50% of the possible points + the remaining
            50% scaled by the time limit and time taken to answer [i.e. a minimum of 50% of the
            possible points is given to all correct answers]

        Example of updated values:
            * {'answer_is_correct': False, 'answer_score': 0} (default)
            * {'answer_is_correct': True, 'answer_score': 2.0}
        """
        for line in self:
            answer_is_correct, answer_score = False, 0
            if line.answer_type:
                # record selected suggested choice answer_score (can be: pos, neg, or 0)
                if line.question_id.question_type in [
                    "simple_choice",
                    "dropdown",
                    "multiple_choice",
                ]:
                    if line.answer_type == "suggestion" and line.suggested_answer_id:
                        answer_score = line.suggested_answer_id.answer_score
                        answer_is_correct = line.suggested_answer_id.is_correct
                # for all other scored question cases, record question answer_score (can be: pos or 0)
                elif line.question_id.question_type in [
                    "date",
                    "datetime",
                    "numerical_box",
                ]:
                    answer = line[f"value_{line.answer_type}"]
                    if line.answer_type == "numerical_box":
                        answer = float(answer)
                    elif line.answer_type == "date":
                        answer = fields.Date.from_string(answer)
                    elif line.answer_type == "datetime":
                        answer = fields.Datetime.from_string(answer)
                    if (
                        answer is not None
                        and answer is not False
                        and answer == line.question_id[f"answer_{line.answer_type}"]
                    ):
                        answer_is_correct = True
                        answer_score = line.question_id.answer_score

            # Session speed rating
            if (
                answer_score > 0
                and line.user_input_id.survey_id.session_speed_rating
                and line.user_input_id.is_session_answer
                and line.question_id.is_time_limited
            ):
                max_score_delay = 2
                time_limit = line.question_id.time_limit
                now = fields.Datetime.now()
                seconds_to_answer = (
                    now - line.user_input_id.survey_id.session_question_start_time
                ).total_seconds()
                question_remaining_time = time_limit - seconds_to_answer
                # if answered within the max_score_delay => leave score as is
                if (
                    question_remaining_time < 0
                    or line.question_id
                    != line.user_input_id.survey_id.session_question_id
                ):
                    answer_score /= 2
                elif (
                    seconds_to_answer > max_score_delay
                ):  # linear decrease in score after 2 sec
                    score_proportion = (time_limit - seconds_to_answer) / (
                        time_limit - max_score_delay
                    )
                    answer_score = (answer_score / 2) * (1 + score_proportion)

            line.answer_is_correct = answer_is_correct
            line.answer_score = answer_score

    @api.constrains("skipped", "answer_type")
    def _check_answer_type_skipped(self) -> None:
        """Ensure a line is either skipped or answered, and its value field is populated."""
        for line in self:
            if line.skipped == bool(line.answer_type):
                raise ValidationError(
                    _("A question can either be skipped or answered, not both.")
                )

            # allow 0 for numerical box and scale
            if line.answer_type == "numerical_box" and float_is_zero(
                line["value_numerical_box"], precision_digits=6
            ):
                continue
            if line.answer_type == "scale" and line["value_scale"] == 0:
                continue

            if line.answer_type == "suggestion":
                field_name = "suggested_answer_id"
            elif line.answer_type:
                field_name = f"value_{line.answer_type}"
            else:  # skipped
                field_name = False

            if field_name and not line[field_name]:
                raise ValidationError(_("The answer must be in the right type"))

    def _get_answer_matching_domain(self) -> list[Any] | None:
        """Return a domain that matches other lines with the same answer value."""
        self.ensure_one()
        if self.answer_type in (
            "char_box",
            "text_box",
            "numerical_box",
            "scale",
            "date",
            "datetime",
        ):
            value_field = {
                "char_box": "value_char_box",
                "text_box": "value_text_box",
                "numerical_box": "value_numerical_box",
                "scale": "value_scale",
                "date": "value_date",
                "datetime": "value_datetime",
            }
            operators = {
                "char_box": "ilike",
                "text_box": "ilike",
                "numerical_box": "=",
                "scale": "=",
                "date": "=",
                "datetime": "=",
            }
            return [
                "&",
                ("question_id", "=", self.question_id.id),
                (
                    value_field[self.answer_type],
                    operators[self.answer_type],
                    self._get_answer_value(),
                ),
            ]
        elif self.answer_type == "suggestion":
            return self.suggested_answer_id._get_answer_matching_domain(
                self.matrix_row_id.id if self.matrix_row_id else False
            )
        return None

    def _get_answer_value(self) -> Any:
        """Return the typed answer value based on the answer_type, or None if skipped."""
        self.ensure_one()
        if self.answer_type == "char_box":
            return self.value_char_box
        elif self.answer_type == "text_box":
            return self.value_text_box
        elif self.answer_type == "numerical_box":
            return self.value_numerical_box
        elif self.answer_type == "scale":
            return self.value_scale
        elif self.answer_type == "date":
            return self.value_date
        elif self.answer_type == "datetime":
            return self.value_datetime
        elif self.answer_type == "suggestion":
            return self.suggested_answer_id.value
        return None
