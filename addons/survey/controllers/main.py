import csv
import io
import json
from collections import defaultdict
from datetime import timedelta
from typing import Any

import werkzeug
from dateutil.relativedelta import relativedelta
from werkzeug.wrappers import Response

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.http import content_disposition, request
from urllib.parse import quote

from odoo.tools import format_date, format_datetime, is_html_empty
from odoo.tools.urls import keep_query, urljoin


class Survey(http.Controller):
    # ------------------------------------------------------------
    # ACCESS
    # ------------------------------------------------------------

    def _fetch_from_access_token(
        self, survey_token: str, answer_token: str | bool
    ) -> tuple[Any, Any]:
        """Check that given token matches an answer from the given survey_id.
        Returns a sudo-ed browse record of survey in order to avoid access rights
        issues now that access is granted through token."""
        SurveySudo, UserInputSudo = (
            request.env["survey.survey"].sudo(),
            request.env["survey.user_input"].sudo(),
        )
        if not survey_token:
            return SurveySudo, UserInputSudo
        if answer_token:
            answer_sudo = UserInputSudo.search(
                Domain(
                    "survey_id",
                    "any",
                    Domain("access_token", "=", survey_token)
                    & Domain(
                        "active", "in", (True, False)
                    ),  # keeping active test for UserInput
                )
                & Domain("access_token", "=", answer_token),
                limit=1,
            )
            if answer_sudo:
                return answer_sudo.survey_id, answer_sudo

        return SurveySudo.with_context(active_test=False).search(
            [("access_token", "=", survey_token)]
        ), UserInputSudo

    def _check_validity(
        self,
        survey_sudo: Any,
        answer_sudo: Any,
        answer_token: str | None,
        ensure_token: bool = True,
        check_partner: bool = True,
    ) -> str | bool:
        """Check survey is open and can be taken. This does not check for
        security rules, only functional / business rules. It returns a string key
        allowing further manipulation of validity issues

         * survey_wrong: survey does not exist;
         * survey_auth: authentication is required;
         * survey_closed: survey is closed and does not accept input anymore;
         * survey_void: survey is void and should not be taken;
         * token_wrong: given token not recognized;
         * token_required: no token given, but it is required to access the survey;
         * answer_deadline: token linked to an expired answer;

        :param ensure_token: whether user input existence based on given access token
          should be enforced or not, depending on the route requesting a token or
          allowing external world calls;

        :param check_partner: Whether we must check that the partner associated to the target
          answer corresponds to the active user.
        """
        if not survey_sudo:
            return "survey_wrong"

        if answer_token and not answer_sudo:
            return "token_wrong"

        if not answer_sudo and ensure_token:
            return "token_required"
        if not answer_sudo and survey_sudo.access_mode == "token":
            return "token_required"

        if survey_sudo.users_login_required and request.env.user._is_public():
            return "survey_auth"

        if not survey_sudo.active and (not answer_sudo or not answer_sudo.test_entry):
            return "survey_closed"

        if (
            not survey_sudo.page_ids
            and survey_sudo.questions_layout == "page_per_section"
        ) or not survey_sudo.question_ids:
            return "survey_void"

        if (
            answer_sudo
            and answer_sudo.deadline
            and answer_sudo.deadline < fields.Datetime.now()
        ):
            return "answer_deadline"

        if answer_sudo and check_partner:
            if (
                request.env.user._is_public()
                and answer_sudo.partner_id
                and not answer_token
            ):
                # answers from public user should not have any partner_id; this indicates probably a cookie issue
                return "answer_wrong_user"
            if (
                not request.env.user._is_public()
                and answer_sudo.partner_id != request.env.user.partner_id
            ):
                # partner mismatch, probably a cookie issue
                return "answer_wrong_user"

        return True

    def _get_access_data(
        self,
        survey_token: str,
        answer_token: str | None,
        ensure_token: bool = True,
        check_partner: bool = True,
    ) -> dict[str, Any]:
        """Get back data related to survey and user input, given the ID and access
        token provided by the route.

         : param ensure_token: whether user input existence should be enforced or not(see ``_check_validity``)
         : param check_partner: whether the partner of the target answer should be checked (see ``_check_validity``)
        """
        survey_sudo, answer_sudo = self._fetch_from_access_token(
            survey_token, answer_token
        )
        has_survey_access, can_answer = False, False

        validity_code = self._check_validity(
            survey_sudo,
            answer_sudo,
            answer_token,
            ensure_token=ensure_token,
            check_partner=check_partner,
        )
        if validity_code != "survey_wrong":
            has_survey_access = survey_sudo.with_user(request.env.user).has_access(
                "read"
            )
            can_answer = bool(answer_sudo)
            if not can_answer:
                can_answer = survey_sudo.access_mode == "public"

        return {
            "survey_sudo": survey_sudo,
            "answer_sudo": answer_sudo,
            "has_survey_access": has_survey_access,
            "can_answer": can_answer,
            "validity_code": validity_code,
        }

    def _redirect_with_error(
        self, access_data: dict[str, Any], error_key: str
    ) -> Response:
        survey_sudo = access_data["survey_sudo"]
        answer_sudo = access_data["answer_sudo"]

        if error_key == "survey_void" and access_data["can_answer"]:
            return request.render(
                "survey.survey_void_content",
                {"survey": survey_sudo, "answer": answer_sudo},
            )
        elif error_key == "survey_closed" and access_data["can_answer"]:
            return request.render(
                "survey.survey_closed_expired", {"survey": survey_sudo}
            )
        elif error_key == "survey_auth":
            if not answer_sudo:  # survey is not even started
                redirect_url = (
                    f"/web/login?redirect=/survey/start/{survey_sudo.access_token}"
                )
            elif (
                answer_sudo.access_token
            ):  # survey is started but user is not logged in anymore.
                if answer_sudo.partner_id and (
                    answer_sudo.partner_id.user_ids or survey_sudo.users_can_signup
                ):
                    if answer_sudo.partner_id.user_ids:
                        answer_sudo.partner_id.signup_cancel()
                    else:
                        answer_sudo.partner_id.signup_prepare()
                    redirect_url = answer_sudo.partner_id._get_signup_url_for_action(
                        url=f"/survey/start/{survey_sudo.access_token}?answer_token={answer_sudo.access_token}"
                    )[answer_sudo.partner_id.id]
                else:
                    survey_url = f"/survey/start/{survey_sudo.access_token}?answer_token={answer_sudo.access_token}"
                    redirect_url = f"/web/login?redirect={quote(survey_url, safe='')}"
            return request.render(
                "survey.survey_auth_required",
                {"survey": survey_sudo, "redirect_url": redirect_url},
            )
        elif error_key == "answer_deadline" and answer_sudo.access_token:
            return request.render(
                "survey.survey_closed_expired", {"survey": survey_sudo}
            )
        elif error_key in ["answer_wrong_user", "token_wrong"]:
            return request.render("survey.survey_access_error", {"survey": survey_sudo})

        return request.redirect("/")

    # ------------------------------------------------------------
    # TEST / RETRY SURVEY ROUTES
    # ------------------------------------------------------------

    @http.route(
        "/survey/test/<string:survey_token>", type="http", auth="user", website=True
    )
    def survey_test(self, survey_token: str, **kwargs: Any) -> Response:
        """Test mode for surveys: create a test answer, only for managers or officers
        testing their surveys"""
        survey_sudo, _dummy = self._fetch_from_access_token(survey_token, False)
        try:
            answer_sudo = survey_sudo._create_answer(
                user=request.env.user, test_entry=True
            )
        except AccessError, UserError:
            return request.redirect("/")
        return request.redirect(
            f"/survey/start/{survey_sudo.access_token}?{keep_query('*', answer_token=answer_sudo.access_token)}"
        )

    @http.route(
        "/survey/retry/<string:survey_token>/<string:answer_token>",
        type="http",
        auth="public",
        website=True,
    )
    def survey_retry(
        self, survey_token: str, answer_token: str, **post: Any
    ) -> Response:
        """This route is called whenever the user has attempts left and hits the 'Retry' button
        after failing the survey."""
        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=True
        )
        if access_data["validity_code"] is not True:
            return self._redirect_with_error(access_data, access_data["validity_code"])

        survey_sudo, answer_sudo = (
            access_data["survey_sudo"],
            access_data["answer_sudo"],
        )
        if not answer_sudo:
            # attempts to 'retry' without having tried first
            return request.redirect("/")

        try:
            retry_answer_sudo = survey_sudo._create_answer(
                user=request.env.user,
                partner=answer_sudo.partner_id,
                email=answer_sudo.email,
                invite_token=answer_sudo.invite_token,
                test_entry=answer_sudo.test_entry,
                **self._prepare_retry_additional_values(answer_sudo),
            )
        except AccessError, UserError:
            return request.redirect("/")
        return request.redirect(
            f"/survey/start/{survey_sudo.access_token}?{keep_query('*', answer_token=retry_answer_sudo.access_token)}"
        )

    def _prepare_retry_additional_values(self, answer: Any) -> dict[str, Any]:
        return {
            "deadline": answer.deadline,
            "nickname": answer.nickname,
        }

    def _prepare_survey_finished_values(
        self, survey: Any, answer: Any, token: str | bool = False
    ) -> dict[str, Any]:
        values = {"survey": survey, "answer": answer}
        if token:
            values["token"] = token
        return values

    # ------------------------------------------------------------
    # TAKING SURVEY ROUTES
    # ------------------------------------------------------------

    @http.route(
        "/survey/start/<string:survey_token>", type="http", auth="public", website=True
    )
    def survey_start(
        self,
        survey_token: str,
        answer_token: str | None = None,
        email: str | bool = False,
        **post: Any,
    ) -> Response:
        """Start a survey by providing
        * a token linked to a survey;
        * a token linked to an answer or generate a new token if access is allowed;
        """
        # Get the current answer token from cookie
        answer_from_cookie = False
        if not answer_token:
            answer_token = request.cookies.get(f"survey_{survey_token}")
            answer_from_cookie = bool(answer_token)

        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=False
        )

        if answer_from_cookie and access_data["validity_code"] in (
            "answer_wrong_user",
            "token_wrong",
        ):
            # If the cookie had been generated for another user or does not correspond to any existing answer object
            # (probably because it has been deleted), ignore it and redo the check.
            # The cookie will be replaced by a legit value when resolving the URL, so we don't clean it further here.
            access_data = self._get_access_data(survey_token, None, ensure_token=False)

        if access_data["validity_code"] is not True:
            return self._redirect_with_error(access_data, access_data["validity_code"])

        survey_sudo, answer_sudo = (
            access_data["survey_sudo"],
            access_data["answer_sudo"],
        )
        if not answer_sudo:
            try:
                answer_sudo = survey_sudo._create_answer(
                    user=request.env.user, email=email
                )
            except UserError:
                answer_sudo = False

        if not answer_sudo:
            try:
                survey_sudo.with_user(request.env.user).check_access("read")
            except AccessError:
                return request.redirect("/")
            else:
                return request.render("survey.survey_403_page", {"survey": survey_sudo})

        # When resuming survey, restore language  + always enforce that the language is supported by the survey
        lang = self._get_lang_with_fallback(answer_sudo.sudo(False))
        url_from = f"/survey/{survey_sudo.access_token}/{answer_sudo.access_token}"
        return request.redirect(self.env["ir.http"]._url_for(url_from, lang.code))

    def _prepare_survey_data(
        self, survey_sudo: Any, answer_sudo: Any, **post: Any
    ) -> dict[str, Any]:
        """Prepare all data needed for survey template rendering based on user input state.

        :param post:
            - previous_page_id: from breadcrumb/back button, forces loading previous questions
            - next_skipped_page: forces display of next skipped question or page
        """
        data = self._prepare_survey_base_data(survey_sudo, answer_sudo)
        (
            triggering_answers_by_question,
            triggered_questions_by_answer,
            selected_answers,
        ) = answer_sudo._get_conditional_values()
        if survey_sudo.questions_layout not in ("page_per_question", "conversational"):
            data.update(
                {
                    "triggering_answers_by_question": {
                        question.id: triggering_answers.ids
                        for question, triggering_answers in triggering_answers_by_question.items()
                        if triggering_answers
                    },
                    "triggered_questions_by_answer": {
                        answer.id: triggered_questions.ids
                        for answer, triggered_questions in triggered_questions_by_answer.items()
                    },
                    "selected_answers": selected_answers.ids,
                }
            )

        page_or_question_key = (
            "question"
            if survey_sudo.questions_layout in ("page_per_question", "conversational")
            else "page"
        )

        # Breadcrumb / back button: jump to a specific page
        if "previous_page_id" in post:
            return self._prepare_survey_back_navigation_data(
                data, survey_sudo, answer_sudo, page_or_question_key, post
            )

        if answer_sudo.state == "in_progress":
            self._prepare_survey_in_progress_data(
                data,
                survey_sudo,
                answer_sudo,
                page_or_question_key,
                triggered_questions_by_answer,
                post,
            )
        elif answer_sudo.state == "done" or answer_sudo.survey_time_limit_reached:
            return self._prepare_survey_finished_values(survey_sudo, answer_sudo)

        return data

    def _prepare_survey_base_data(
        self, survey_sudo: Any, answer_sudo: Any
    ) -> dict[str, Any]:
        """Build the base rendering context shared by all survey states."""
        data = {
            "is_html_empty": is_html_empty,
            "survey": survey_sudo,
            "answer": answer_sudo,
            "skipped_questions": answer_sudo._get_skipped_questions(),
            "breadcrumb_pages": [
                {"id": page.id, "title": page.title} for page in survey_sudo.page_ids
            ],
            "format_datetime": lambda dt: format_datetime(
                request.env, dt, dt_format=False
            ),
            "format_date": lambda date: format_date(request.env, date),
        }
        if answer_sudo.state == "new":
            supported_lang_codes = survey_sudo._get_supported_lang_codes()
            data["languages"] = [
                (lang_code, self.env["res.lang"]._get_data(code=lang_code)["name"])
                for lang_code in supported_lang_codes
            ]
            data["lang_code"] = self._get_lang_with_fallback(
                answer_sudo.sudo(False)
            ).code

        if (
            not answer_sudo.is_session_answer
            and survey_sudo.is_time_limited
            and answer_sudo.start_datetime
        ):
            data.update(
                {
                    "server_time": fields.Datetime.now(),
                    "timer_start": answer_sudo.start_datetime.isoformat(),
                    "time_limit_minutes": survey_sudo.time_limit,
                }
            )
        return data

    def _prepare_survey_back_navigation_data(
        self,
        data: dict[str, Any],
        survey_sudo: Any,
        answer_sudo: Any,
        page_or_question_key: str,
        post: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle breadcrumb / back-button navigation to a previous page."""
        try:
            previous_page_or_question_id = int(post["previous_page_id"])
        except ValueError, TypeError:
            return data
        # Validate the question belongs to this survey before browsing
        if previous_page_or_question_id not in survey_sudo.question_and_page_ids.ids:
            return data
        new_previous_id = survey_sudo._get_next_page_or_question(
            answer_sudo, previous_page_or_question_id, go_back=True
        ).id
        page_or_question = (
            request.env["survey.question"].sudo().browse(previous_page_or_question_id)
        )
        data.update(
            {
                page_or_question_key: page_or_question,
                "previous_page_id": new_previous_id,
                "has_answered": answer_sudo.user_input_line_ids.filtered(
                    lambda line: line.question_id.id == new_previous_id
                ),
                "can_go_back": survey_sudo._can_go_back(answer_sudo, page_or_question),
            }
        )
        return data

    def _prepare_survey_in_progress_data(
        self,
        data: dict[str, Any],
        survey_sudo: Any,
        answer_sudo: Any,
        page_or_question_key: str,
        triggered_questions_by_answer: Any,
        post: dict[str, Any],
    ) -> None:
        """Populate rendering data for a survey that is currently in progress."""
        next_page_or_question = self._resolve_next_page_or_question(
            survey_sudo, answer_sudo, post
        )

        if next_page_or_question:
            if answer_sudo.survey_first_submitted:
                survey_last = answer_sudo._is_last_skipped_page_or_question(
                    next_page_or_question
                )
            else:
                survey_last = survey_sudo._is_last_page_or_question(
                    answer_sudo, next_page_or_question
                )
            data["survey_last"] = survey_last

            if (
                not answer_sudo.survey_first_submitted
                and survey_last
                and survey_sudo.questions_layout != "one_page"
            ):
                data["survey_last_triggering_answers"] = (
                    self._get_last_page_triggering_answers(
                        survey_sudo,
                        answer_sudo,
                        next_page_or_question,
                        triggered_questions_by_answer,
                    )
                )

        if answer_sudo.is_session_answer and next_page_or_question.is_time_limited:
            data.update(
                {
                    "timer_start": survey_sudo.session_question_start_time.isoformat(),
                    "time_limit_minutes": next_page_or_question.time_limit / 60,
                }
            )

        data.update(
            {
                page_or_question_key: next_page_or_question,
                "has_answered": answer_sudo.user_input_line_ids.filtered(
                    lambda line: line.question_id == next_page_or_question
                ),
                "can_go_back": survey_sudo._can_go_back(
                    answer_sudo, next_page_or_question
                ),
            }
        )
        if survey_sudo.questions_layout != "one_page":
            data["previous_page_id"] = survey_sudo._get_next_page_or_question(
                answer_sudo, next_page_or_question.id, go_back=True
            ).id

    def _resolve_next_page_or_question(
        self, survey_sudo: Any, answer_sudo: Any, post: dict[str, Any]
    ) -> Any:
        """Determine which page or question to show next during survey progression."""
        if answer_sudo.is_session_answer:
            return survey_sudo.session_question_id

        next_page_or_question = None
        if "next_skipped_page" in post:
            next_page_or_question = answer_sudo._get_next_skipped_page_or_question()
        if not next_page_or_question:
            next_page_or_question = survey_sudo._get_next_page_or_question(
                answer_sudo,
                answer_sudo.last_displayed_page_id.id
                if answer_sudo.last_displayed_page_id
                else 0,
            )
            if not next_page_or_question:
                next_page_or_question = answer_sudo._get_next_skipped_page_or_question()
        return next_page_or_question

    def _get_last_page_triggering_answers(
        self,
        survey_sudo: Any,
        answer_sudo: Any,
        next_page_or_question: Any,
        triggered_questions_by_answer: Any,
    ) -> list[int]:
        """Get answer IDs on the current page that trigger questions on following pages.

        Used on the last survey page to dynamically toggle the submit/continue button
        based on which conditional questions would be activated by the selected answers.
        """
        pages_or_questions = survey_sudo._get_pages_or_questions(answer_sudo)
        following_questions = pages_or_questions.filtered(
            lambda pq: pq.sequence > next_page_or_question.sequence
        )
        next_page_suggested_answers = next_page_or_question.suggested_answer_ids
        if survey_sudo.questions_layout == "page_per_section":
            following_questions = following_questions.question_ids
            next_page_suggested_answers = (
                next_page_or_question.question_ids.suggested_answer_ids
            )
        return [
            answer.id
            for answer in triggered_questions_by_answer
            if answer in next_page_suggested_answers
            and any(
                q in following_questions for q in triggered_questions_by_answer[answer]
            )
        ]

    def _prepare_question_html(
        self, survey_sudo: Any, answer_sudo: Any, **post: Any
    ) -> dict[str, Any]:
        """Survey page navigation is done in AJAX. This function prepare the 'next page' to display in html
        and send back this html to the survey_form widget that will inject it into the page.
        Background url must be given to the caller in order to process its refresh as we don't have the next question
        object at frontend side."""
        survey_data = self._prepare_survey_data(survey_sudo, answer_sudo, **post)

        IrQweb = request.env["ir.qweb"].with_context(
            lang=self.env["res.lang"]._get_data(id=answer_sudo.lang_id.id).code
            or self._get_lang_with_fallback(answer_sudo.sudo(False)).code
        )
        if answer_sudo.state == "done":
            survey_content = IrQweb._render("survey.survey_fill_form_done", survey_data)
        else:
            survey_content = IrQweb._render(
                "survey.survey_fill_form_in_progress", survey_data
            )

        survey_progress = False
        if (
            answer_sudo.state == "in_progress"
            and not survey_data.get("question", request.env["survey.question"]).is_page
        ):
            if survey_sudo.questions_layout == "page_per_section":
                page_ids = survey_sudo.page_ids.ids
                survey_progress = IrQweb._render(
                    "survey.survey_progression",
                    {
                        "survey": survey_sudo,
                        "page_ids": page_ids,
                        "page_number": page_ids.index(survey_data["page"].id)
                        + (1 if survey_sudo.progression_mode == "number" else 0),
                    },
                )
            elif survey_sudo.questions_layout in (
                "page_per_question",
                "conversational",
            ):
                page_ids = (
                    answer_sudo.predefined_question_ids.ids
                    if not answer_sudo.is_session_answer
                    and survey_sudo.questions_selection == "random"
                    else survey_sudo.question_ids.ids
                )
                survey_progress = IrQweb._render(
                    "survey.survey_progression",
                    {
                        "survey": survey_sudo,
                        "page_ids": page_ids,
                        "page_number": page_ids.index(survey_data["question"].id),
                    },
                )

        background_image_url = survey_sudo.background_image_url
        if "question" in survey_data:
            background_image_url = survey_data["question"].background_image_url
        elif "page" in survey_data:
            background_image_url = survey_data["page"].background_image_url

        return {
            "has_skipped_questions": any(answer_sudo._get_skipped_questions()),
            "survey_content": survey_content,
            "survey_progress": survey_progress,
            "survey_navigation": IrQweb._render(
                "survey.survey_navigation", survey_data
            ),
            "background_image_url": background_image_url,
        }

    def _apply_url_prefill(
        self, survey_sudo: Any, answer_sudo: Any, post: dict[str, Any]
    ) -> None:
        """Pre-fill survey answers from URL query parameters.

        Supports two formats:
        - ``?prefill_<question_id>=<value>`` — explicit prefill by question database ID
        - ``?Q<question_id>=<value>`` — shorthand form (same as piping syntax)

        For choice questions (simple_choice, dropdown, multiple_choice), the value
        should be the ``survey.question.answer`` id or the answer label text.
        For text/numerical/date questions, the value is used directly.

        Only questions that have no existing answer are prefilled (no overwriting).
        """
        question_ids = {q.id: q for q in survey_sudo.question_ids}
        existing_question_ids = set(
            answer_sudo.user_input_line_ids.mapped("question_id").ids
        )

        prefills = {}
        for key, value in post.items():
            if not value:
                continue
            question_id = None
            if key.startswith("prefill_"):
                try:
                    question_id = int(key.removeprefix("prefill_"))
                except ValueError:
                    continue
            elif key.startswith("Q") and key[1:].isdigit():
                question_id = int(key[1:])
            if question_id and question_id in question_ids and question_id not in existing_question_ids:
                prefills[question_id] = value

        for question_id, raw_value in prefills.items():
            question = question_ids[question_id]
            try:
                if question.question_type in ("simple_choice", "dropdown"):
                    # Try value as answer ID first, then as label text
                    answer = self._resolve_prefill_choice(question, raw_value)
                    if answer:
                        answer_sudo._save_lines(question, answer)
                elif question.question_type == "multiple_choice":
                    # Comma-separated answer IDs or labels
                    answers = []
                    for part in raw_value.split(","):
                        ans = self._resolve_prefill_choice(question, part.strip())
                        if ans:
                            answers.append(ans)
                    if answers:
                        answer_sudo._save_lines(question, answers)
                elif question.question_type in (
                    "char_box", "text_box", "numerical_box",
                    "date", "datetime", "scale", "nps", "slider", "rating",
                ):
                    answer_sudo._save_lines(question, raw_value)
            except Exception:
                # Silently skip invalid prefill values — don't block survey start
                continue

    @staticmethod
    def _resolve_prefill_choice(question: Any, raw_value: str) -> int | None:
        """Resolve a prefill value to a ``survey.question.answer`` id.

        Tries integer ID first, then exact label match (case-insensitive).
        Returns the answer id or ``None`` if not found.
        """
        # Try as numeric answer ID
        try:
            answer_id = int(raw_value)
            if question.suggested_answer_ids.filtered(lambda a: a.id == answer_id):
                return answer_id
        except ValueError:
            pass
        # Try as label text (case-insensitive match)
        for answer in question.suggested_answer_ids:
            if (answer.value or "").strip().lower() == raw_value.strip().lower():
                return answer.id
        return None

    @http.route(
        "/survey/<string:survey_token>/<string:answer_token>",
        type="http",
        auth="public",
        website=True,
    )
    def survey_display_page(
        self, survey_token: str, answer_token: str, **post: Any
    ) -> Response:
        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=True
        )
        if access_data["validity_code"] is not True:
            return self._redirect_with_error(access_data, access_data["validity_code"])

        answer_sudo = access_data["answer_sudo"]
        if answer_sudo.state != "done" and answer_sudo.survey_time_limit_reached:
            answer_sudo._mark_done()

        return request.render(
            "survey.survey_page_fill",
            self._prepare_survey_data(access_data["survey_sudo"], answer_sudo, **post),
        )

    # --------------------------------------------------------------------------
    # ROUTES to handle question images + survey background transitions + Tool
    # --------------------------------------------------------------------------

    @http.route(
        "/survey/<string:survey_token>/get_background_image",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def survey_get_background(self, survey_token: str) -> Response:
        survey_sudo, _dummy = self._fetch_from_access_token(survey_token, False)
        return (
            request.env["ir.binary"]
            ._get_image_stream_from(survey_sudo, "background_image")
            .get_response()
        )

    @http.route(
        "/survey/<string:survey_token>/<int:section_id>/get_background_image",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def survey_section_get_background(
        self, survey_token: str, section_id: int
    ) -> Response:
        survey_sudo, _dummy = self._fetch_from_access_token(survey_token, False)

        section = survey_sudo.page_ids.filtered(lambda q: q.id == section_id)
        if not section:
            # trying to access a question that is not in this survey
            raise werkzeug.exceptions.Forbidden

        return (
            request.env["ir.binary"]
            ._get_image_stream_from(section, "background_image")
            .get_response()
        )

    @http.route(
        "/survey/get_question_image/<string:survey_token>/<string:answer_token>/<int:question_id>/<int:suggested_answer_id>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def survey_get_question_image(
        self,
        survey_token: str,
        answer_token: str,
        question_id: int,
        suggested_answer_id: int,
    ) -> Response:
        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=True
        )
        if access_data["validity_code"] is not True:
            return werkzeug.exceptions.Forbidden()

        survey_sudo = access_data["survey_sudo"]

        suggested_answer = False
        if int(question_id) in survey_sudo.question_ids.ids:
            suggested_answer = (
                request.env["survey.question.answer"]
                .sudo()
                .search(
                    [
                        ("id", "=", int(suggested_answer_id)),
                        ("question_id", "=", int(question_id)),
                        ("question_id.survey_id", "=", survey_sudo.id),
                    ]
                )
            )

        if not suggested_answer:
            return werkzeug.exceptions.NotFound()

        return (
            request.env["ir.binary"]
            ._get_image_stream_from(suggested_answer, "value_image")
            .get_response()
        )

    # ----------------------------------------------------------------
    # SAVE & CONTINUE LATER
    # ----------------------------------------------------------------

    @http.route(
        "/survey/save_later/<string:survey_token>/<string:answer_token>",
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def survey_save_later(
        self, survey_token: str, answer_token: str, **post: Any
    ) -> dict[str, Any]:
        """Email the respondent a link to resume their in-progress survey."""
        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=True
        )
        if access_data["validity_code"] is not True:
            return {"error": access_data["validity_code"]}

        answer_sudo = access_data["answer_sudo"]
        survey_sudo = access_data["survey_sudo"]

        if not answer_sudo.email:
            return {"error": "no_email"}

        resume_url = urljoin(
            survey_sudo.get_base_url(),
            f"/survey/start/{survey_sudo.access_token}?answer_token={answer_sudo.access_token}",
        )

        # Send email with resume link
        template = self.env.ref("survey.mail_template_survey_save_later", raise_if_not_found=False)
        if template:
            template.sudo().send_mail(
                answer_sudo.id,
                email_values={"email_to": answer_sudo.email},
                force_send=True,
            )
        else:
            # Fallback: simple email via mail.mail
            self.env["mail.mail"].sudo().create({
                "subject": f"Continue your survey: {survey_sudo.title}",
                "email_to": answer_sudo.email,
                "body_html": f"<p>You can resume your survey at any time using this link:</p>"
                             f'<p><a href="{resume_url}">{resume_url}</a></p>',
                "auto_delete": True,
            }).send()

        return {"success": True, "email": answer_sudo.email}

    # ----------------------------------------------------------------
    # JSON ROUTES to begin / continue survey (ajax navigation) + Tools
    # ----------------------------------------------------------------

    @http.route(
        "/survey/begin/<string:survey_token>/<string:answer_token>",
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def survey_begin(
        self, survey_token: str, answer_token: str, **post: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Route used to start the survey user input and display the first survey page.
        Returns an empty dict for the correct answers and the first page html."""
        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=True
        )
        if access_data["validity_code"] is not True:
            return {}, {"error": access_data["validity_code"]}
        survey_sudo, answer_sudo = (
            access_data["survey_sudo"],
            access_data["answer_sudo"],
        )

        if answer_sudo.state != "new":
            return {}, {"error": _("The survey has already started.")}

        if "lang_code" in post:
            lang = request.env["res.lang"]._lang_get(post["lang_code"])
            if lang:
                answer_sudo.lang_id = lang
        answer_sudo._mark_in_progress()

        # Apply URL parameter prefill (e.g. ?Q42=value or ?prefill_42=value)
        self._apply_url_prefill(survey_sudo, answer_sudo, post)

        return {}, self._prepare_question_html(survey_sudo, answer_sudo, **post)

    @http.route(
        "/survey/next_question/<string:survey_token>/<string:answer_token>",
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def survey_next_question(
        self, survey_token: str, answer_token: str, **post: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Method used to display the next survey question in an ongoing session.
        Triggered on all attendees screens when the host goes to the next question."""
        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=True
        )
        if access_data["validity_code"] is not True:
            return {}, {"error": access_data["validity_code"]}
        survey_sudo, answer_sudo = (
            access_data["survey_sudo"],
            access_data["answer_sudo"],
        )

        if answer_sudo.state == "new" and answer_sudo.is_session_answer:
            answer_sudo._mark_in_progress()

        return {}, self._prepare_question_html(survey_sudo, answer_sudo, **post)

    def _check_time_limit_exceeded(self, survey_sudo: Any, answer_sudo: Any) -> bool:
        """Check if the time limit grace period has passed, preventing late submissions.

        Returns True if the submission should be rejected (cheating detected),
        False if submission is allowed (within grace period or no time limit).
        A small grace period (3s for questions, 10s for surveys) accounts for
        network latency between client timer and server check.
        """
        if not (
            answer_sudo.survey_time_limit_reached
            or answer_sudo.question_time_limit_reached
        ):
            return False
        if answer_sudo.question_time_limit_reached:
            time_limit = survey_sudo.session_question_start_time + relativedelta(
                seconds=survey_sudo.session_question_id.time_limit
            )
            time_limit += timedelta(seconds=3)
        else:
            time_limit = answer_sudo.start_datetime + timedelta(
                minutes=survey_sudo.time_limit
            )
            time_limit += timedelta(seconds=10)
        return fields.Datetime.now() > time_limit

    def _determine_next_page_after_submit(
        self,
        survey_sudo: Any,
        answer_sudo: Any,
        page_or_question_id: int,
        correct_answers: dict[str, Any],
        **post: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Determine navigation after a successful page submission.

        Handles four cases: going back via breadcrumb, advancing to next skipped
        question, advancing to the natural next page, or marking the survey done.
        """
        if "previous_page_id" in post:
            answer_sudo.last_displayed_page_id = post["previous_page_id"]
            return correct_answers, self._prepare_question_html(
                survey_sudo, answer_sudo, **post
            )

        if "next_skipped_page_or_question" in post:
            answer_sudo.last_displayed_page_id = page_or_question_id
            return correct_answers, self._prepare_question_html(
                survey_sudo, answer_sudo, next_skipped_page=True
            )

        if not answer_sudo.is_session_answer:
            # Check for skip actions on the most recently answered question(s)
            skip_result = self._check_skip_actions(
                survey_sudo, answer_sudo, page_or_question_id, correct_answers
            )
            if skip_result is not None:
                return skip_result

            if answer_sudo.survey_first_submitted:
                next_page = request.env["survey.question"]
            else:
                next_page = survey_sudo._get_next_page_or_question(
                    answer_sudo, page_or_question_id
                )
            if not next_page:
                if (
                    survey_sudo.users_can_go_back
                    and answer_sudo.user_input_line_ids.filtered(
                        lambda a: a.skipped and a.question_id.constr_mandatory
                    )
                ):
                    answer_sudo.write(
                        {
                            "last_displayed_page_id": page_or_question_id,
                            "survey_first_submitted": True,
                        }
                    )
                    return correct_answers, self._prepare_question_html(
                        survey_sudo, answer_sudo, next_skipped_page=True
                    )
                else:
                    answer_sudo._mark_done()

        answer_sudo.last_displayed_page_id = page_or_question_id
        return correct_answers, self._prepare_question_html(survey_sudo, answer_sudo)

    @http.route(
        "/survey/submit/<string:survey_token>/<string:answer_token>",
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def survey_submit(
        self, survey_token: str, answer_token: str, **post: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Submit a page from the survey.

        Validates access, enforces time/attempt limits, saves answers, and
        returns correct answers if scoring_type is 'scoring_with_answers_after_page'.
        """
        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=True
        )
        if access_data["validity_code"] is not True:
            return {}, {"error": access_data["validity_code"]}
        survey_sudo, answer_sudo = (
            access_data["survey_sudo"],
            access_data["answer_sudo"],
        )

        if answer_sudo.state == "done":
            return {}, {"error": "unauthorized"}

        questions, page_or_question_id = survey_sudo._get_survey_questions(
            answer=answer_sudo,
            page_id=post.get("page_id"),
            question_id=post.get("question_id"),
        )

        if not answer_sudo.test_entry and not survey_sudo._has_attempts_left(
            answer_sudo.partner_id, answer_sudo.email, answer_sudo.invite_token
        ):
            return {}, {"error": "unauthorized"}

        if self._check_time_limit_exceeded(survey_sudo, answer_sudo):
            return {}, {"error": "unauthorized"}

        # Validate and save answers per question
        errors = {}
        for question in questions:
            inactive_questions = (
                request.env["survey.question"]
                if answer_sudo.is_session_answer
                else answer_sudo._get_inactive_conditional_questions()
            )
            if question in inactive_questions:
                continue
            answer, comment = self._extract_comment_from_answers(
                question, post.get(str(question.id))
            )
            errors.update(question.validate_question(answer, comment))
            if not errors.get(question.id):
                # Enforce quotas on choice answers before saving
                if (
                    survey_sudo.quota_ids
                    and question.question_type
                    in ("simple_choice", "dropdown", "multiple_choice")
                    and answer
                ):
                    answer_ids = (
                        [int(a) for a in answer]
                        if isinstance(answer, list)
                        else [int(answer)]
                    )
                    full_quotas = survey_sudo.quota_ids._check_quota(answer_ids)
                    if full_quotas:
                        errors[question.id] = _(
                            "One or more selected answers have reached their response quota."
                        )
                        continue
                answer_sudo._save_lines(
                    question,
                    answer,
                    comment,
                    overwrite_existing=survey_sudo.users_can_go_back
                    or question.save_as_nickname
                    or question.save_as_email,
                )

        if errors and not (
            answer_sudo.survey_time_limit_reached
            or answer_sudo.question_time_limit_reached
        ):
            return {}, {"error": "validation", "fields": errors}

        if not answer_sudo.is_session_answer:
            answer_sudo._clear_inactive_conditional_answers()

        # Recompute calculated fields after saving answers
        answer_sudo._evaluate_calculated_fields()

        # Fire page_submitted webhook
        if survey_sudo.webhook_url and not answer_sudo.test_entry:
            answer_sudo._fire_webhook("page_submitted")

        correct_answers = {}
        if survey_sudo.scoring_type == "scoring_with_answers_after_page":
            scorable_questions = (
                questions - answer_sudo._get_inactive_conditional_questions()
            ).filtered("is_scored_question")
            correct_answers = scorable_questions._get_correct_answers()

        if (
            answer_sudo.survey_time_limit_reached
            or survey_sudo.questions_layout == "one_page"
        ):
            answer_sudo._mark_done()
            return correct_answers, self._prepare_question_html(
                survey_sudo, answer_sudo
            )

        return self._determine_next_page_after_submit(
            survey_sudo, answer_sudo, page_or_question_id, correct_answers, **post
        )

    def _check_skip_actions(
        self,
        survey_sudo: Any,
        answer_sudo: Any,
        page_or_question_id: int,
        correct_answers: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Check if any answer on the current page has a skip action.

        Examines the most recently saved answer lines for the submitted
        question(s) and returns a navigation override if a skip action
        (skip_to, end_survey, redirect) is configured.

        Returns ``None`` if normal navigation should proceed, otherwise
        returns the ``(correct_answers, response_data)`` tuple.
        """
        # Find the questions that were just submitted (use sudo env for ACL)
        Question = survey_sudo.env["survey.question"]
        if survey_sudo.questions_layout in ("page_per_question", "conversational"):
            submitted_questions = Question.browse(page_or_question_id)
        else:
            page = Question.browse(page_or_question_id)
            submitted_questions = page.question_ids if page.is_page else page

        # Check selected answers for skip actions
        for line in answer_sudo.user_input_line_ids.filtered(
            lambda ln: ln.question_id in submitted_questions and ln.suggested_answer_id
        ):
            answer = line.suggested_answer_id
            if answer.skip_action == "end_survey":
                answer_sudo._mark_done()
                return correct_answers, self._prepare_question_html(
                    survey_sudo, answer_sudo
                )
            elif answer.skip_action == "redirect" and answer.skip_redirect_url:
                answer_sudo._mark_done()
                return correct_answers, {
                    "redirect_url": answer.skip_redirect_url,
                }
            elif answer.skip_action == "skip_to" and answer.skip_target_id:
                target = answer.skip_target_id
                if target.id in survey_sudo.question_and_page_ids.ids:
                    # Set last_displayed_page_id to the question BEFORE the
                    # target so _get_next_page_or_question returns the target
                    # itself (its semantics is "what comes after this page?").
                    before_target = survey_sudo._get_next_page_or_question(
                        answer_sudo, target.id, go_back=True
                    )
                    answer_sudo.last_displayed_page_id = before_target or False
                    return correct_answers, self._prepare_question_html(
                        survey_sudo, answer_sudo
                    )
        return None

    def _extract_comment_from_answers(
        self, question: Any, answers: Any
    ) -> tuple[Any, str | None]:
        """Answers is a custom structure depending of the question type
        that can contain question answers but also comments that need to be
        extracted before validating and saving answers.
        If multiple answers, they are listed in an array, except for matrix
        where answers are structured differently. See input and output for
        more info on data structures.
        :param question: survey.question
        :param answers:
          * question_type: free_text, text_box, numerical_box, date, datetime
            answers is a string containing the value
          * question_type: simple_choice with no comment
            answers is a string containing the value ('question_id_1')
          * question_type: simple_choice with comment
            ['question_id_1', {'comment': str}]
          * question_type: multiple choice
            ['question_id_1', 'question_id_2'] + [{'comment': str}] if holds a comment
          * question_type: matrix
            {'matrix_row_id_1': ['question_id_1', 'question_id_2'],
             'matrix_row_id_2': ['question_id_1', 'question_id_2']
            } + {'comment': str} if holds a comment
        :return: tuple(
          same structure without comment,
          extracted comment for given question
        )"""
        comment = None
        answers_no_comment = []
        if answers:
            if question.question_type in ("matrix", "likert"):
                if "comment" in answers:
                    comment = answers["comment"].strip()
                    answers.pop("comment")
                answers_no_comment = answers
            else:
                if not isinstance(answers, list):
                    answers = [answers]
                for answer in answers:
                    if isinstance(answer, dict) and "comment" in answer:
                        comment = answer["comment"].strip()
                    else:
                        answers_no_comment.append(answer)
                if len(answers_no_comment) == 1:
                    answers_no_comment = answers_no_comment[0]
        return answers_no_comment, comment

    # ------------------------------------------------------------
    # COMPLETED SURVEY ROUTES
    # ------------------------------------------------------------

    @http.route(
        "/survey/print/<string:survey_token>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def survey_print(
        self,
        survey_token: str,
        review: bool = False,
        answer_token: str | None = None,
        **post: Any,
    ) -> Response:
        """Display an survey in printable view; if <answer_token> is set, it will
        grab the answers of the user_input_id that has <answer_token>."""
        access_data = self._get_access_data(
            survey_token, answer_token, ensure_token=False, check_partner=False
        )
        if access_data["validity_code"] is not True and (
            not access_data["has_survey_access"]
            or access_data["validity_code"]
            not in ["token_required", "survey_closed", "survey_void", "answer_deadline"]
        ):
            return self._redirect_with_error(access_data, access_data["validity_code"])

        survey_sudo, answer_sudo = (
            access_data["survey_sudo"],
            access_data["answer_sudo"],
        )
        return request.render(
            "survey.survey_page_print",
            {
                "is_html_empty": is_html_empty,
                "review": review,
                "survey": survey_sudo,
                "answer": answer_sudo
                if survey_sudo.scoring_type != "scoring_without_answers"
                else answer_sudo.browse(),
                "questions_to_display": answer_sudo._get_print_questions(),
                "scoring_display_correction": survey_sudo.scoring_type
                in ["scoring_with_answers", "scoring_with_answers_after_page"]
                and answer_sudo,
                "format_datetime": lambda dt: format_datetime(
                    request.env, dt, dt_format=False
                ),
                "format_date": lambda date: format_date(request.env, date),
                "graph_data": json.dumps(answer_sudo._prepare_statistics()[answer_sudo])
                if answer_sudo
                and survey_sudo.scoring_type
                in ["scoring_with_answers", "scoring_with_answers_after_page"]
                else False,
            },
        )

    @http.route(
        '/survey/<model("survey.survey"):survey>/certification_preview',
        type="http",
        auth="user",
        website=True,
    )
    def show_certification_pdf(self, survey: Any, **kwargs: Any) -> Response:
        preview_url = f"/survey/{survey.id}/get_certification_preview"
        return request.render(
            "survey.certification_preview",
            {
                "preview_url": preview_url,
                "page_title": survey.title,
            },
        )

    @http.route(
        ['/survey/<model("survey.survey"):survey>/get_certification_preview'],
        type="http",
        auth="user",
        methods=["GET"],
        website=True,
    )
    def survey_get_certification_preview(self, survey: Any, **kwargs: Any) -> Response:
        """Generate a preview of the certification PDF without persisting the attempt."""
        if not request.env.user.has_group("survey.group_survey_user"):
            raise werkzeug.exceptions.Forbidden

        fake_user_input = survey._create_answer(user=request.env.user, test_entry=True)
        try:
            response = self._generate_report(fake_user_input, download=False)
        finally:
            fake_user_input.sudo().unlink()
        return response

    @http.route(
        ["/survey/<int:survey_id>/get_certification"],
        type="http",
        auth="user",
        methods=["GET"],
        website=True,
    )
    def survey_get_certification(self, survey_id: int, **kwargs: Any) -> Response:
        """The certification document can be downloaded as long as the user has succeeded the certification"""
        survey = (
            request.env["survey.survey"]
            .sudo()
            .search([("id", "=", survey_id), ("certification", "=", True)])
        )

        if not survey:
            # no certification found
            return request.redirect("/")

        succeeded_attempt = (
            request.env["survey.user_input"]
            .sudo()
            .search(
                [
                    ("partner_id", "=", request.env.user.partner_id.id),
                    ("survey_id", "=", survey_id),
                    ("scoring_success", "=", True),
                ],
                limit=1,
            )
        )

        if not succeeded_attempt:
            raise UserError(_("The user has not succeeded the certification"))

        return self._generate_report(succeeded_attempt, download=True)

    # ------------------------------------------------------------
    # REPORTING SURVEY ROUTES AND TOOLS
    # ------------------------------------------------------------

    @http.route(
        '/survey/results/<model("survey.survey"):survey>',
        type="http",
        auth="user",
        website=True,
    )
    def survey_report(
        self, survey: Any, answer_token: str | None = None, **post: Any
    ) -> Response:
        """Display survey Results & Statistics for given survey.

        New structure: {
            'survey': current survey browse record,
            'question_and_page_data': see ``SurveyQuestion._prepare_statistics()``,
            'survey_data'= see ``SurveySurvey._prepare_statistics()``
            'search_filters': [],
            'search_finished': either filter on finished inputs only or not,
            'search_passed': either filter on passed inputs only or not,
            'search_failed': either filter on failed inputs only or not,
        }
        """
        user_input_lines, search_filters = self._extract_filters_data(survey, post)
        survey_data = survey._prepare_statistics(user_input_lines)
        question_and_page_data = survey.question_and_page_ids._prepare_statistics(
            user_input_lines
        )

        template_values = {
            # survey and its statistics
            "survey": survey,
            "question_and_page_data": question_and_page_data,
            "survey_data": survey_data,
            # search
            "search_filters": search_filters,
            "search_finished": post.get("finished") == "true",
            "search_failed": post.get("failed") == "true",
            "search_passed": post.get("passed") == "true",
        }

        if survey.session_show_leaderboard:
            template_values["leaderboard"] = survey._prepare_leaderboard_values()

        return request.render("survey.survey_page_statistics", template_values)

    @http.route(
        "/survey/results/<int:survey_id>/cross_tabulation",
        type="jsonrpc",
        auth="user",
    )
    def survey_cross_tabulation(
        self, survey_id: int, question_row_id: int, question_col_id: int
    ) -> dict[str, Any]:
        """Return a cross-tabulation (contingency table) between two questions.

        Called via JSON-RPC from the results page to generate on-demand
        cross-tab analysis between any pair of questions.
        """
        survey = request.env["survey.survey"].browse(survey_id)
        if not survey.exists():
            return {"error": "Survey not found"}
        return survey._prepare_cross_tabulation(question_row_id, question_col_id)

    def _generate_report(self, user_input: Any, download: bool = True) -> Response:
        report = (
            request.env["ir.actions.report"]
            .sudo()
            ._render_qweb_pdf(
                "survey.certification_report",
                [user_input.id],
                data={"report_type": "pdf"},
            )[0]
        )

        report_content_disposition = content_disposition("Certification.pdf")
        if not download:
            content_split = report_content_disposition.split(";")
            content_split[0] = "inline"
            report_content_disposition = ";".join(content_split)

        return request.make_response(
            report,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", len(report)),
                ("Content-Disposition", report_content_disposition),
            ],
        )

    def _get_results_page_user_input_domain(self, survey: Any, **post: Any) -> Domain:
        """Build the base domain for filtering survey results.

        Supports URL parameters:
        - ``finished``: only completed responses
        - ``failed`` / ``passed``: score-based filter
        - ``date_from`` / ``date_to``: date range (YYYY-MM-DD)
        - ``score_min`` / ``score_max``: score percentage range (0-100)
        - ``quality_min``: minimum quality score (0-100)
        """
        user_input_domains = []
        if post.get("finished"):
            user_input_domains.append(Domain("state", "=", "done"))
        else:
            user_input_domains.append(Domain("state", "!=", "new"))
        if post.get("failed"):
            user_input_domains.append(Domain("scoring_success", "=", False))
        elif post.get("passed"):
            user_input_domains.append(Domain("scoring_success", "=", True))

        # Date range filter
        if post.get("date_from"):
            user_input_domains.append(Domain("end_datetime", ">=", post["date_from"]))
        if post.get("date_to"):
            user_input_domains.append(Domain("end_datetime", "<=", post["date_to"]))

        # Score range filter
        if post.get("score_min"):
            try:
                user_input_domains.append(
                    Domain("scoring_percentage", ">=", float(post["score_min"]))
                )
            except ValueError:
                pass
        if post.get("score_max"):
            try:
                user_input_domains.append(
                    Domain("scoring_percentage", "<=", float(post["score_max"]))
                )
            except ValueError:
                pass

        # Quality score filter
        if post.get("quality_min"):
            try:
                user_input_domains.append(
                    Domain("quality_score", ">=", int(post["quality_min"]))
                )
            except ValueError:
                pass

        user_input_domains.extend(
            (Domain("test_entry", "=", False), Domain("survey_id", "=", survey.id))
        )
        return Domain.AND(user_input_domains)

    def _extract_filters_data(
        self, survey: Any, post: dict[str, Any]
    ) -> tuple[Any, list[dict[str, Any]]]:
        """Extracts the filters from the URL to returns the related user_input_lines and
        the parameters used to render/remove the filters on the results page (search_filters).

        The matching user_input_lines are all the lines tied to the user inputs which respect
        the survey base domain and which have lines matching all the filters.
        For example, with the filter 'Where do you live?|Brussels', we need to display ALL the lines
        of the survey user inputs which have answered 'Brussels' to this question.

        :return (recordset, List[dict]): all matching user input lines, each search filter data
        """
        user_input_line_subdomains = []
        search_filters = []

        answer_by_column, user_input_lines_ids = self._get_filters_from_post(post)

        # Matrix, Multiple choice, Simple choice filters
        if answer_by_column:
            answer_ids, row_ids = [], []
            for answer_column_id, answer_row_ids in answer_by_column.items():
                answer_ids.append(answer_column_id)
                row_ids += answer_row_ids

            answers_and_rows = request.env["survey.question.answer"].browse(
                answer_ids + row_ids
            )
            # For performance, accessing 'a.matrix_question_id' caches all useful fields of the
            # answers and rows records, avoiding unnecessary queries.
            answers = answers_and_rows.filtered(lambda a: not a.matrix_question_id)

            for answer in answers:
                if not answer_by_column[answer.id]:
                    # Simple/Multiple choice
                    user_input_line_subdomains.append(
                        answer._get_answer_matching_domain()
                    )
                    search_filters.append(self._prepare_search_filter_answer(answer))
                else:
                    # Matrix
                    for row_id in answer_by_column[answer.id]:
                        row = answers_and_rows.filtered(
                            lambda answer_or_row, rid=row_id: answer_or_row.id == rid
                        )
                        user_input_line_subdomains.append(
                            answer._get_answer_matching_domain(row_id)
                        )
                        search_filters.append(
                            self._prepare_search_filter_answer(answer, row)
                        )

        # Char_box, Text_box, Numerical_box, Date, Datetime filters
        if user_input_lines_ids:
            user_input_lines = request.env["survey.user_input.line"].browse(
                user_input_lines_ids
            )
            for input_line in user_input_lines:
                user_input_line_subdomains.append(
                    input_line._get_answer_matching_domain()
                )
                search_filters.append(
                    self._prepare_search_filter_input_line(input_line)
                )

        # Compute base domain
        user_input_domain = self._get_results_page_user_input_domain(survey, **post)

        # Add filters domain to the base domain
        if user_input_line_subdomains:
            all_required_lines_domains = [
                [
                    (
                        "user_input_line_ids",
                        "in",
                        request.env["survey.user_input.line"].sudo()._search(subdomain),
                    )
                ]
                for subdomain in user_input_line_subdomains
            ]
            user_input_domain = Domain.AND(
                [user_input_domain, *all_required_lines_domains]
            )

        # Get the matching user input lines
        user_inputs_query = (
            request.env["survey.user_input"].sudo()._search(user_input_domain)
        )
        user_input_lines = request.env["survey.user_input.line"].search(
            [("user_input_id", "in", user_inputs_query)]
        )

        return user_input_lines, search_filters

    def _get_filters_from_post(
        self, post: dict[str, Any]
    ) -> tuple[defaultdict[int, list[int]], list[int]]:
        """Extract the filters from post depending on the model that needs to be called to retrieve the filtered answer data.
        Simple choice and multiple choice question types are mapped onto empty row_id.
        Input/output example with respectively matrix, simple_choice and char_box filters:
            input: 'A,1,24|A,0,13|L,0,36'
            output:
                answer_by_column: {24: [1], 13: []}
                user_input_lines_ids: [36]

        * Model short key = 'A' : Match a `survey.question.answer` record (simple_choice, multiple_choice, matrix)
        * Model short key = 'L' : Match a `survey.user_input.line` record (char_box, text_box, numerical_box, date, datetime)
        :rtype: (collections.defaultdict[int, list[int]], list[int])
        """
        answer_by_column = defaultdict(list)
        user_input_lines_ids = []

        for data in post.get("filters", "").split("|"):
            if not data:
                break
            parts = data.split(",")
            if len(parts) != 3:
                continue
            model_short_key, row_id, answer_id = parts
            try:
                row_id, answer_id = int(row_id), int(answer_id)
            except ValueError, TypeError:
                continue
            if model_short_key == "A":
                if row_id:
                    answer_by_column[answer_id].append(row_id)
                else:
                    answer_by_column[answer_id] = []
            elif model_short_key == "L" and not row_id:
                user_input_lines_ids.append(answer_id)

        return answer_by_column, user_input_lines_ids

    def _prepare_search_filter_answer(
        self, answer: Any, row: Any = False
    ) -> dict[str, Any]:
        """Format parameters used to render/remove this filter on the results page."""
        return {
            "question_id": answer.question_id.id,
            "question": answer.question_id.title,
            "row_id": row.id if row else 0,
            "answer": f"{row.value} : {answer.value}" if row else answer.value,
            "model_short_key": "A",
            "record_id": answer.id,
        }

    def _prepare_search_filter_input_line(self, user_input_line: Any) -> dict[str, Any]:
        """Format parameters used to render/remove this filter on the results page."""
        return {
            "question_id": user_input_line.question_id.id,
            "question": user_input_line.question_id.title,
            "row_id": 0,
            "answer": user_input_line._get_answer_value(),
            "model_short_key": "L",
            "record_id": user_input_line.id,
        }

    def _get_lang_with_fallback(self, user_input: Any) -> Any:
        """:return: the most suitable language for the user that is supported by the survey."""
        user_input.ensure_one()
        user_input_sudo = user_input.sudo()
        if user_input_sudo.lang_id:
            return user_input_sudo.lang_id.sudo(False)
        lang_code = (
            self.env.context.get("lang") or self.env["ir.http"]._get_default_lang().code
        )
        ResLang = self.env["res.lang"]
        supported_lang_codes = user_input_sudo.survey_id._get_supported_lang_codes()
        supported_lang_codes_set = set(supported_lang_codes)
        if lang_code in supported_lang_codes_set:
            return ResLang._lang_get(lang_code)
        # Take the first frontend language supported by the survey and if there are none, the first survey language
        return ResLang._lang_get(
            next(
                (
                    lang.code
                    for lang in self.env["res.lang"]._get_frontend().values()
                    if lang["code"] in supported_lang_codes_set
                ),
                supported_lang_codes[0],
            )
        )

    # ------------------------------------------------------------
    # EXPORT
    # ------------------------------------------------------------

    @http.route(
        '/survey/results/<model("survey.survey"):survey>/export/csv',
        type="http",
        auth="user",
    )
    def survey_export_csv(self, survey: Any, **post: Any) -> Response:
        """Export all completed survey responses as a CSV file."""
        header, rows = self._build_export_data(survey)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)

        filename = f"{survey.title} - Responses.csv"
        return request.make_response(
            output.getvalue(),
            headers=[
                ("Content-Type", "text/csv;charset=utf-8"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )

    @http.route(
        '/survey/results/<model("survey.survey"):survey>/export/xlsx',
        type="http",
        auth="user",
    )
    def survey_export_xlsx(self, survey: Any, **post: Any) -> Response:
        """Export all completed survey responses as an XLSX file with formatting."""
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        header, rows = self._build_export_data(survey)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Responses"

        # Header styling
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="714B67", end_color="714B67", fill_type="solid")
        for col_idx, col_name in enumerate(header, 1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", wrap_text=True)

        # Data rows
        for row_idx, row_data in enumerate(rows, 2):
            for col_idx, value in enumerate(row_data, 1):
                ws.cell(row=row_idx, column=col_idx, value=value)

        # Auto-width columns (capped at 40)
        for col_idx in range(1, len(header) + 1):
            max_len = max(
                len(str(ws.cell(row=r, column=col_idx).value or ""))
                for r in range(1, min(len(rows) + 2, 50))  # sample first 50 rows
            )
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 40)

        # Freeze header row
        ws.freeze_panes = "A2"

        output = io.BytesIO()
        wb.save(output)

        filename = f"{survey.title} - Responses.xlsx"
        return request.make_response(
            output.getvalue(),
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )

    def _build_export_data(self, survey: Any) -> tuple[list[str], list[list]]:
        """Build header and data rows for CSV/XLSX export.

        Returns ``(header, rows)`` where header is a list of column names
        and rows is a list of lists with one entry per response.
        """
        user_inputs = request.env["survey.user_input"].search(
            [
                ("survey_id", "=", survey.id),
                ("state", "=", "done"),
                ("test_entry", "=", False),
            ]
        )
        questions = survey.question_ids

        header = [
            "Respondent",
            "Email",
            "Start Date",
            "End Date",
            "Duration (min)",
            "Score (%)",
        ]
        for question in questions:
            if question.question_type in ("matrix", "likert"):
                header.extend(
                    f"{question.title} [{row.value}]" for row in question.matrix_row_ids
                )
            else:
                header.append(question.title)

        rows = []
        for user_input in user_inputs:
            row = [
                user_input.nickname
                or (user_input.partner_id.name if user_input.partner_id else ""),
                user_input.email or "",
                str(user_input.start_datetime or ""),
                str(user_input.end_datetime or ""),
                round(
                    (
                        user_input.end_datetime - user_input.start_datetime
                    ).total_seconds()
                    / 60,
                    1,
                )
                if user_input.start_datetime and user_input.end_datetime
                else "",
                round(user_input.scoring_percentage, 1)
                if survey.scoring_type != "no_scoring"
                else "",
            ]

            lines = user_input.user_input_line_ids
            for question in questions:
                q_lines = lines.filtered(lambda ln, q=question: ln.question_id == q)
                if question.question_type in ("matrix", "likert"):
                    for matrix_row in question.matrix_row_ids:
                        row_lines = q_lines.filtered(
                            lambda ln, r=matrix_row: ln.matrix_row_id == r
                        )
                        row.append(
                            ", ".join(
                                ln.suggested_answer_id.value
                                for ln in row_lines
                                if ln.suggested_answer_id
                            )
                        )
                elif question.question_type in ("simple_choice", "dropdown", "multiple_choice"):
                    row.append(
                        ", ".join(
                            ln.suggested_answer_id.value
                            for ln in q_lines
                            if ln.suggested_answer_id
                        )
                    )
                elif question.question_type == "text_box":
                    row.append(q_lines[0].value_text_box if q_lines else "")
                elif question.question_type == "char_box":
                    row.append(q_lines[0].value_char_box if q_lines else "")
                elif question.question_type == "numerical_box":
                    row.append(q_lines[0].value_numerical_box if q_lines else "")
                elif question.question_type in ("scale", "nps", "rating"):
                    row.append(q_lines[0].value_scale if q_lines else "")
                elif question.question_type == "slider":
                    row.append(q_lines[0].value_numerical_box if q_lines else "")
                elif question.question_type in ("ranking", "constant_sum"):
                    row.append(
                        ", ".join(
                            f"{ln.suggested_answer_id.value}: {ln.value_numerical_box}"
                            for ln in q_lines
                            if ln.suggested_answer_id and not ln.skipped
                        )
                    )
                elif question.question_type == "file_upload":
                    row.append(q_lines[0].value_char_box if q_lines else "")
                elif question.question_type == "date":
                    row.append(
                        str(q_lines[0].value_date)
                        if q_lines and q_lines[0].value_date
                        else ""
                    )
                elif question.question_type == "datetime":
                    row.append(
                        str(q_lines[0].value_datetime)
                        if q_lines and q_lines[0].value_datetime
                        else ""
                    )
                else:
                    row.append("")
            rows.append(row)

        return header, rows

    # ------------------------------------------------------------
    # CROSS-TABULATION
    # ------------------------------------------------------------

    @http.route(
        '/survey/results/<model("survey.survey"):survey>/cross-tab',
        type="http",
        auth="user",
        website=True,
    )
    def survey_cross_tab(self, survey: Any, **post: Any) -> Response:
        """Display a cross-tabulation (contingency table) between two questions.

        The two question IDs are passed as ``q_row`` and ``q_col`` GET parameters.
        When absent, shows a selector form to pick the questions.
        """
        choice_questions = survey.question_ids.filtered(
            lambda q: (
                q.question_type
                in (
                    "simple_choice",
                    "dropdown",
                    "multiple_choice",
                    "scale",
                    "nps",
                    "rating",
                )
            )
        )

        cross_tab_data = {}
        q_row = int(post.get("q_row", 0))
        q_col = int(post.get("q_col", 0))
        if q_row and q_col and q_row != q_col:
            cross_tab_data = survey._prepare_cross_tabulation(q_row, q_col)

        return request.render(
            "survey.survey_page_cross_tab",
            {
                "survey": survey,
                "choice_questions": choice_questions,
                "cross_tab_data": cross_tab_data,
                "selected_row": q_row,
                "selected_col": q_col,
            },
        )

    # ------------------------------------------------------------
    # RESPONDENT SEGMENTATION
    # ------------------------------------------------------------

    @http.route(
        '/survey/results/<model("survey.survey"):survey>/segments',
        type="jsonrpc",
        auth="user",
    )
    def survey_segments(self, survey: Any, **post: Any) -> dict[str, Any]:
        """Return respondent segmentation data for the analytics dashboard.

        Segments respondents by:
        - Score bands (0-25%, 25-50%, 50-75%, 75-100%)
        - Completion time quartiles
        - Quality score tiers (Low/Medium/High)
        """
        request.env.cr.execute("""
            SELECT
                scoring_percentage,
                quality_score,
                EXTRACT(EPOCH FROM (end_datetime - start_datetime)) / 60.0 AS duration_min
            FROM survey_user_input
            WHERE survey_id = %s
              AND state = 'done'
              AND test_entry = FALSE
              AND end_datetime IS NOT NULL
              AND start_datetime IS NOT NULL
        """, [survey.id])
        rows = request.env.cr.fetchall()
        if not rows:
            return {"score_bands": [], "quality_tiers": [], "duration_buckets": [], "total": 0}

        # Score bands
        bands = {"0-25%": 0, "25-50%": 0, "50-75%": 0, "75-100%": 0}
        for score, _quality, _dur in rows:
            if score < 25:
                bands["0-25%"] += 1
            elif score < 50:
                bands["25-50%"] += 1
            elif score < 75:
                bands["50-75%"] += 1
            else:
                bands["75-100%"] += 1

        # Quality tiers
        tiers = {"Low (0-33)": 0, "Medium (34-66)": 0, "High (67-100)": 0}
        for _score, quality, _dur in rows:
            if quality <= 33:
                tiers["Low (0-33)"] += 1
            elif quality <= 66:
                tiers["Medium (34-66)"] += 1
            else:
                tiers["High (67-100)"] += 1

        # Duration buckets (based on quartiles of actual data)
        durations = sorted(d for _s, _q, d in rows if d and d > 0)
        if durations:
            q1 = durations[len(durations) // 4]
            median = durations[len(durations) // 2]
            q3 = durations[3 * len(durations) // 4]
            buckets = {
                f"< {q1:.0f} min": len([d for d in durations if d < q1]),
                f"{q1:.0f}-{median:.0f} min": len([d for d in durations if q1 <= d < median]),
                f"{median:.0f}-{q3:.0f} min": len([d for d in durations if median <= d < q3]),
                f"> {q3:.0f} min": len([d for d in durations if d >= q3]),
            }
        else:
            buckets = {}

        return {
            "score_bands": [{"label": k, "count": v} for k, v in bands.items()],
            "quality_tiers": [{"label": k, "count": v} for k, v in tiers.items()],
            "duration_buckets": [{"label": k, "count": v} for k, v in buckets.items()],
            "total": len(rows),
        }

    # ------------------------------------------------------------
    # COMPARISON REPORTS
    # ------------------------------------------------------------

    @http.route(
        '/survey/results/<model("survey.survey"):survey>/compare',
        type="jsonrpc",
        auth="user",
    )
    def survey_compare(
        self, survey: Any,
        period_a_from: str = "", period_a_to: str = "",
        period_b_from: str = "", period_b_to: str = "",
        **post: Any,
    ) -> dict[str, Any]:
        """Compare survey results between two time periods.

        Returns per-question statistics for each period (counts, averages,
        correct answer rates) and deltas between them.
        """
        def _get_lines_for_period(date_from, date_to):
            domain = [
                ("survey_id", "=", survey.id),
                ("state", "=", "done"),
                ("test_entry", "=", False),
            ]
            if date_from:
                domain.append(("end_datetime", ">=", date_from))
            if date_to:
                domain.append(("end_datetime", "<=", date_to))
            user_inputs = request.env["survey.user_input"].sudo().search(domain)
            return {
                "count": len(user_inputs),
                "avg_score": round(
                    sum(user_inputs.mapped("scoring_percentage")) / (len(user_inputs) or 1), 1
                ),
                "avg_quality": round(
                    sum(user_inputs.mapped("quality_score")) / (len(user_inputs) or 1), 1
                ),
                "success_rate": round(
                    len(user_inputs.filtered("scoring_success")) / (len(user_inputs) or 1) * 100, 1
                ) if survey.scoring_type != "no_scoring" else None,
            }

        period_a = _get_lines_for_period(period_a_from, period_a_to)
        period_b = _get_lines_for_period(period_b_from, period_b_to)

        # Compute deltas
        deltas = {}
        for key in ("count", "avg_score", "avg_quality", "success_rate"):
            a_val = period_a.get(key)
            b_val = period_b.get(key)
            if a_val is not None and b_val is not None:
                deltas[key] = round(b_val - a_val, 1)
            else:
                deltas[key] = None

        return {
            "period_a": period_a,
            "period_b": period_b,
            "deltas": deltas,
        }

    # ------------------------------------------------------------
    # TREND ANALYSIS
    # ------------------------------------------------------------

    @http.route(
        '/survey/results/<model("survey.survey"):survey>/trends',
        type="jsonrpc",
        auth="user",
    )
    def survey_trends(self, survey: Any, granularity: str = "day", **post: Any) -> dict[str, Any]:
        """Return time-series data for survey responses.

        :param granularity: 'day', 'week', or 'month'
        :returns: dict with ``labels`` (date strings), ``counts`` (response counts),
            and ``avg_scores`` (average score percentages, empty if no scoring).
        """
        if granularity not in ("day", "week", "month"):
            granularity = "day"

        trunc = {"day": "day", "week": "week", "month": "month"}[granularity]

        request.env.cr.execute("""
            SELECT
                date_trunc(%s, end_datetime) AS period,
                COUNT(*) AS cnt,
                AVG(scoring_percentage) AS avg_score
            FROM survey_user_input
            WHERE survey_id = %s
              AND state = 'done'
              AND test_entry = FALSE
              AND end_datetime IS NOT NULL
            GROUP BY period
            ORDER BY period
        """, [trunc, survey.id])

        results = request.env.cr.fetchall()
        has_scoring = survey.scoring_type != "no_scoring"

        date_fmt = {
            "day": "%Y-%m-%d",
            "week": "%Y-W%W",
            "month": "%Y-%m",
        }[granularity]

        return {
            "labels": [row[0].strftime(date_fmt) for row in results],
            "counts": [row[1] for row in results],
            "avg_scores": [round(row[2] or 0, 1) for row in results] if has_scoring else [],
            "granularity": granularity,
        }
