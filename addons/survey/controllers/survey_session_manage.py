import datetime
import json
from datetime import UTC
from typing import Any

from dateutil.relativedelta import relativedelta
from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Response

from odoo import fields, http
from odoo.http import request
from odoo.tools import is_html_empty


class UserInputSession(http.Controller):
    # The host screen scrolls free-text answers live; past this many the display is
    # unusable anyway. The count of what was left out travels with the payload rather
    # than the slice being silent about it.
    MAX_LIVE_ANSWERS = 100

    def _fetch_from_token(self, survey_token: str) -> Any:
        return request.env["survey.survey"].search(
            [("access_token", "=", survey_token)]
        )

    def _fetch_from_session_code(
        self, session_code: str
    ) -> tuple[Any, dict[str, Any] | None]:
        if not session_code:
            return None, {"error": "survey_wrong"}
        survey = (
            request.env["survey.survey"]
            .sudo()
            .search([("session_code", "=", session_code)], limit=1)
        )
        if not survey or survey.certification:
            return None, {"error": "survey_wrong"}
        if survey.session_state in ["ready", "in_progress"]:
            return survey, None
        if request.env.user.has_group("survey.group_survey_user"):
            return None, {
                "error": "survey_session_not_launched",
                "survey_id": survey.id,
            }
        return None, {"error": "survey_session_not_launched"}

    @http.route(
        "/survey/session/manage/<string:survey_token>",
        type="http",
        auth="user",
        website=True,
    )
    def survey_session_manage(self, survey_token: str, **kwargs: Any) -> Response:
        survey = self._fetch_from_token(survey_token)

        if not survey:
            return NotFound()

        if survey.session_state == "ready":
            if not survey.question_ids:
                return request.render(
                    "survey.survey_void_content",
                    {
                        "survey": survey,
                        "answer": request.env["survey.user_input"],
                    },
                )
            return request.render("survey.user_input_session_open", {"survey": survey})
        return request.render(
            "survey.user_input_session_manage",
            self._prepare_manage_session_values(survey),
        )

    @http.route(
        "/survey/session/next_question/<string:survey_token>",
        type="jsonrpc",
        auth="user",
        website=True,
    )
    def survey_session_next_question(
        self, survey_token: str, go_back: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        survey = self._fetch_from_token(survey_token)

        if not survey or not survey.session_state:
            return {}

        if survey.session_state == "ready":
            survey._session_open()

        next_question = survey._get_session_next_question(go_back)

        if next_question:
            now = datetime.datetime.now(UTC)
            survey.sudo().write(
                {
                    "session_question_id": next_question.id,
                    "session_question_start_time": fields.Datetime.now()
                    + relativedelta(seconds=1),
                }
            )
            request.env["bus.bus"]._sendone(
                survey.access_token,
                "next_question",
                {"question_start": now.timestamp()},
            )

            template_values = self._prepare_manage_session_values(survey)
            template_values["is_rpc_call"] = True

            return {
                "background_image_url": survey.session_question_id.background_image_url,
                "question_html": request.env["ir.qweb"]._render(
                    "survey.user_input_session_manage_content", template_values
                ),
            }
        else:
            return {}

    @http.route(
        "/survey/session/results/<string:survey_token>",
        type="jsonrpc",
        auth="user",
        website=True,
    )
    def survey_session_results(
        self, survey_token: str, **kwargs: Any
    ) -> dict[str, Any] | bool:
        survey = self._fetch_from_token(survey_token)

        if not survey or survey.session_state != "in_progress":
            return False

        user_input_lines = request.env["survey.user_input.line"].search(
            [
                ("survey_id", "=", survey.id),
                ("question_id", "=", survey.session_question_id.id),
                ("create_date", ">=", survey.session_start_time),
            ]
        )

        return self._prepare_question_results_values(survey, user_input_lines)

    @http.route(
        "/survey/session/leaderboard/<string:survey_token>",
        type="jsonrpc",
        auth="user",
        website=True,
    )
    def survey_session_leaderboard(self, survey_token: str, **kwargs: Any) -> str:
        survey = self._fetch_from_token(survey_token)

        if not survey or survey.session_state != "in_progress":
            return ""

        return request.env["ir.qweb"]._render(
            "survey.user_input_session_leaderboard",
            {"animate": True, "leaderboard": survey._prepare_leaderboard_values()},
        )

    @http.route("/s", type="http", auth="public", website=True, sitemap=False)
    def survey_session_code(self, **post: Any) -> Response:
        return request.render("survey.survey_session_code")

    @http.route("/s/<string:session_code>", type="http", auth="public", website=True)
    def survey_start_short(self, session_code: str, **post) -> Response:
        survey, survey_error = self._fetch_from_session_code(session_code)
        if survey:
            return request.redirect(survey.get_start_url())

        SurveySudo = request.env["survey.survey"].sudo()
        # Same guard _resolve_short_token applies below: redirecting here hands the
        # survey's access_token -- a bearer secret -- to an anonymous visitor, and for
        # an invite-only survey they cannot answer with it anyway.
        survey = SurveySudo.search(
            [
                ("slug", "=", session_code),
                ("active", "=", True),
                ("access_mode", "=", "public"),
            ],
            limit=1,
        )
        if survey:
            return request.redirect(survey.get_start_url())

        survey = SurveySudo._resolve_short_token(session_code)
        if survey:
            return request.redirect(survey.get_start_url())

        if survey_error:
            return request.render(
                "survey.survey_session_code",
                dict(**survey_error, session_code=session_code),
            )
        return request.redirect("/")

    @http.route(
        "/survey/check_session_code/<string:session_code>",
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def survey_check_session_code(self, session_code: str) -> dict[str, Any]:
        survey, survey_error = self._fetch_from_session_code(session_code)
        if survey_error:
            return survey_error
        return {"survey_url": survey.get_start_url()}

    def _prepare_manage_session_values(self, survey: Any) -> dict[str, Any]:
        is_first_question, is_last_question = False, False
        if survey.question_ids:
            most_voted_answers = survey._get_session_most_voted_answers()
            is_first_question = survey._is_first_page_or_question(
                survey.session_question_id
            )
            is_last_question = survey._is_last_page_or_question(
                most_voted_answers, survey.session_question_id
            )

        values = {
            "survey": survey,
            "is_last_question": is_last_question,
            "is_first_question": is_first_question,
            "is_session_closed": not survey.session_state,
        }

        if is_last_question:
            _, triggered_questions_by_answer = survey._get_conditional_maps()
            next_question = survey.session_question_id
            values["survey_last_triggering_answers"] = [
                answer.id
                for answer in triggered_questions_by_answer
                if answer in next_question.suggested_answer_ids
                and any(
                    q.sequence > next_question.sequence
                    for q in triggered_questions_by_answer[answer]
                )
            ]

        values.update(
            self._prepare_question_results_values(
                survey, request.env["survey.user_input.line"]
            )
        )

        return values

    def _prepare_question_results_values(
        self, survey: Any, user_input_lines: Any
    ) -> dict[str, Any]:
        question = survey.session_question_id
        if not question:
            return {}
        answers_validity = []
        if any(answer.is_correct for answer in question.suggested_answer_ids):
            answers_validity = [
                answer.is_correct for answer in question.suggested_answer_ids
            ]
            if question.comment_count_as_answer:
                answers_validity.append(False)

        full_statistics = question._prepare_question_statistics(user_input_lines)[0]
        input_line_values = []
        omitted_line_count = 0
        if question.question_type in ["char_box", "date", "datetime"]:
            table_data = full_statistics.get(
                "table_data", request.env["survey.user_input.line"]
            )
            shown = table_data[: self.MAX_LIVE_ANSWERS]
            omitted_line_count = max(len(table_data) - len(shown), 0)
            input_line_values = [
                {"id": line.id, "value": line[f"value_{question.question_type}"]}
                for line in shown
            ]

        return {
            "is_html_empty": is_html_empty,
            "question_statistics_graph": full_statistics.get("graph_data"),
            "input_line_values": input_line_values,
            "omitted_line_count": omitted_line_count,
            "answers_validity": json.dumps(answers_validity),
            "answer_count": survey.session_question_answer_count,
            "attendees_count": survey.session_answer_count,
            "selected_answers": user_input_lines.suggested_answer_id.ids,
        }
