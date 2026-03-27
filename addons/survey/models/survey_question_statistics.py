import collections
import itertools
import json
import operator
import re
from typing import Any

from odoo import _, models, tools


class SurveyQuestionStatistics(models.AbstractModel):
    """Statistics / reporting methods for survey questions.

    Provides chart data, summary aggregations, NPS scoring, text analysis,
    and correct-answer lookups.  Designed to be inherited by ``survey.question``.
    """

    _name = "survey.question.statistics"
    _description = "Survey Question Statistics Mixin"

    # ------------------------------------------------------------------
    # PUBLIC ENTRY POINTS
    # ------------------------------------------------------------------

    def _prepare_statistics(self, user_input_lines: Any) -> list[dict[str, Any]]:
        """Compute statistical data for each question by counting votes per choice.

        Returns a list of dicts, one per question/page in ``self``, containing
        table data, graph data, text analysis, and summary counts suitable for
        the results template.
        """
        all_questions_data = []
        for question in self:
            question_data = {"question": question, "is_page": question.is_page}

            if question.is_page:
                all_questions_data.append(question_data)
                continue

            # Separate real answers from comments
            all_lines = user_input_lines.filtered(
                lambda line, q=question: line.question_id == q
            )
            if question.question_type in ["simple_choice", "dropdown", "multiple_choice", "matrix", "likert"]:
                answer_lines = all_lines.filtered(
                    lambda line, q=question: (
                        line.answer_type == "suggestion"
                        or (line.skipped and not line.answer_type)
                        or (
                            line.answer_type == "char_box" and q.comment_count_as_answer
                        )
                    )
                )
                comment_line_ids = all_lines.filtered(
                    lambda line: line.answer_type == "char_box"
                )
            else:
                answer_lines = all_lines
                comment_line_ids = self.env["survey.user_input.line"]
            skipped_lines = answer_lines.filtered(lambda line: line.skipped)
            done_lines = answer_lines - skipped_lines
            question_data.update(
                answer_line_ids=answer_lines,
                answer_line_done_ids=done_lines,
                answer_input_done_ids=done_lines.mapped("user_input_id"),
                answer_input_ids=answer_lines.mapped("user_input_id"),
                comment_line_ids=comment_line_ids,
            )
            question_data.update(question._get_stats_summary_data(answer_lines))

            # Table and graph data
            table_data, graph_data, extra_data = question._get_stats_data(answer_lines)
            question_data["table_data"] = table_data
            question_data["graph_data"] = json.dumps(graph_data)
            if extra_data:
                question_data["extra_data"] = extra_data
            if question.question_type in [
                "text_box",
                "char_box",
                "numerical_box",
                "date",
                "datetime",
            ]:
                answers_data = [
                    [
                        input_line.id,
                        input_line._get_answer_value(),
                        input_line.user_input_id.get_print_url(),
                    ]
                    for input_line in table_data
                    if not input_line.skipped
                ]
                question_data["answers_data"] = json.dumps(answers_data, default=str)
            # Text analysis for open-text questions
            if question.question_type in ("text_box", "char_box"):
                question_data["text_analysis"] = question._get_text_analysis(
                    answer_lines
                )
            all_questions_data.append(question_data)
        return all_questions_data

    # ------------------------------------------------------------------
    # PER-TYPE STATISTICS DISPATCHERS
    # ------------------------------------------------------------------

    def _get_stats_data(
        self, user_input_lines: Any
    ) -> tuple[Any, list[dict[str, Any]], dict[str, Any] | None]:
        """Return ``(table_data, graph_data, extra)`` for chart/table rendering.

        Dispatches to a type-specific method.  The third element contains
        type-specific metadata (e.g. NPS summary) or ``None``.
        """
        if self.question_type in ("simple_choice", "dropdown"):
            table_data, graph_data = self._get_stats_data_answers(user_input_lines)
            return table_data, graph_data, None
        elif self.question_type == "multiple_choice":
            table_data, graph_data = self._get_stats_data_answers(user_input_lines)
            return table_data, [{"key": self.title, "values": graph_data}], None
        elif self.question_type in ("matrix", "likert"):
            table_data, graph_data = self._get_stats_graph_data_matrix(user_input_lines)
            return table_data, graph_data, None
        elif self.question_type == "scale":
            table_data, graph_data = self._get_stats_data_scale(user_input_lines)
            return table_data, [{"key": self.title, "values": graph_data}], None
        elif self.question_type == "nps":
            return self._get_stats_data_nps(user_input_lines)
        elif self.question_type == "slider":
            return list(user_input_lines), [], None
        elif self.question_type == "rating":
            table_data, graph_data = self._get_stats_data_rating(user_input_lines)
            return table_data, [{"key": self.title, "values": graph_data}], None
        elif self.question_type in ("ranking", "constant_sum"):
            return self._get_stats_data_per_answer(user_input_lines)
        return list(user_input_lines), [], None

    # ------------------------------------------------------------------
    # CHOICE / SUGGESTION-BASED STATISTICS
    # ------------------------------------------------------------------

    def _get_stats_data_answers(
        self, user_input_lines: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Statistics for choice-based questions (simple/multiple choice).

        A void ``survey.question.answer`` record is added when comments count
        as answers, keeping everything in one uniform structure.
        """
        suggested_answers = list(self.mapped("suggested_answer_ids"))
        if self.comment_count_as_answer:
            suggested_answers += [self.env["survey.question.answer"]]

        count_data = dict.fromkeys(suggested_answers, 0)
        for line in user_input_lines:
            if line.suggested_answer_id in count_data or (
                line.value_char_box and self.comment_count_as_answer
            ):
                count_data[line.suggested_answer_id] += 1

        table_data = [
            {
                "value": _("Other (see comments)")
                if not suggested_answer
                else suggested_answer.value_label,
                "suggested_answer": suggested_answer,
                "count": count_data[suggested_answer],
                "count_text": self.env._("%s Votes", count_data[suggested_answer]),
            }
            for suggested_answer in suggested_answers
        ]
        graph_data = [
            {
                "text": self.env._("Other (see comments)")
                if not suggested_answer
                else suggested_answer.value_label,
                "count": count_data[suggested_answer],
            }
            for suggested_answer in suggested_answers
        ]

        return table_data, graph_data

    def _get_stats_graph_data_matrix(
        self, user_input_lines: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Statistics for matrix questions: cross-tabulation of rows x columns."""
        suggested_answers = self.mapped("suggested_answer_ids")
        matrix_rows = self.mapped("matrix_row_ids")

        count_data = dict.fromkeys(itertools.product(matrix_rows, suggested_answers), 0)
        for line in user_input_lines:
            if line.matrix_row_id and line.suggested_answer_id:
                count_data[(line.matrix_row_id, line.suggested_answer_id)] += 1

        table_data = [
            {
                "row": row,
                "columns": [
                    {
                        "suggested_answer": suggested_answer,
                        "count": count_data[(row, suggested_answer)],
                    }
                    for suggested_answer in suggested_answers
                ],
            }
            for row in matrix_rows
        ]
        graph_data = [
            {
                "key": suggested_answer.value,
                "values": [
                    {"text": row.value, "count": count_data[(row, suggested_answer)]}
                    for row in matrix_rows
                ],
            }
            for suggested_answer in suggested_answers
        ]

        return table_data, graph_data

    # ------------------------------------------------------------------
    # SCALE / NPS / RATING STATISTICS
    # ------------------------------------------------------------------

    def _get_stats_data_scale(
        self, user_input_lines: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Statistics for scale questions: count per discrete value."""
        suggested_answers = range(self.scale_min, self.scale_max + 1)

        count_data = dict.fromkeys(suggested_answers, 0)
        for line in user_input_lines:
            if not line.skipped and line.value_scale in count_data:
                count_data[line.value_scale] += 1

        table_data = []
        graph_data = []
        for sug_answer in suggested_answers:
            table_data.append(
                {
                    "value": str(sug_answer),
                    "suggested_answer": self.env["survey.question.answer"],
                    "count": count_data[sug_answer],
                    "count_text": _("%s Votes", count_data[sug_answer]),
                }
            )
            graph_data.append(
                {"text": str(sug_answer), "count": count_data[sug_answer]}
            )

        return table_data, graph_data

    def _get_stats_data_nps(
        self, user_input_lines: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        """Compute NPS statistics: Detractor (0-6), Passive (7-8), Promoter (9-10).

        Returns scale-like table/graph data plus NPS-specific bucket counts.
        NPS score = %Promoters - %Detractors (range -100 to +100).
        """
        count_data = dict.fromkeys(range(11), 0)
        for line in user_input_lines:
            if not line.skipped and 0 <= line.value_scale <= 10:
                count_data[line.value_scale] += 1

        total = sum(count_data.values())
        detractors = sum(count_data[v] for v in range(7))
        passives = sum(count_data[v] for v in range(7, 9))
        promoters = sum(count_data[v] for v in range(9, 11))
        nps_score = round((promoters - detractors) / total * 100) if total else 0

        table_data = []
        graph_data = []
        for value in range(11):
            # Color: red for detractors, yellow for passives, green for promoters
            color = "#dc3545" if value <= 6 else "#ffc107" if value <= 8 else "#28a745"
            table_data.append(
                {
                    "value": str(value),
                    "suggested_answer": self.env["survey.question.answer"],
                    "count": count_data[value],
                    "count_text": _("%s Votes", count_data[value]),
                }
            )
            graph_data.append(
                {
                    "text": str(value),
                    "count": count_data[value],
                    "color": color,
                }
            )

        nps_graph_data = [{"key": self.title, "values": graph_data}]
        nps_summary = {
            "nps_score": nps_score,
            "detractors": detractors,
            "passives": passives,
            "promoters": promoters,
            "total": total,
            "detractors_pct": round(detractors / total * 100) if total else 0,
            "passives_pct": round(passives / total * 100) if total else 0,
            "promoters_pct": round(promoters / total * 100) if total else 0,
        }
        return table_data, nps_graph_data, nps_summary

    def _get_stats_data_rating(
        self, user_input_lines: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Statistics for rating questions: count per level (1 to rating_max)."""
        suggested_answers = range(1, self.rating_max + 1)
        count_data = dict.fromkeys(suggested_answers, 0)
        for line in user_input_lines:
            if not line.skipped and line.value_scale in count_data:
                count_data[line.value_scale] += 1

        table_data = []
        graph_data = []
        for value in suggested_answers:
            table_data.append(
                {
                    "value": str(value),
                    "suggested_answer": self.env["survey.question.answer"],
                    "count": count_data[value],
                    "count_text": _("%s Votes", count_data[value]),
                }
            )
            graph_data.append({"text": str(value), "count": count_data[value]})
        return table_data, graph_data

    # ------------------------------------------------------------------
    # PER-ANSWER STATISTICS (RANKING / CONSTANT SUM)
    # ------------------------------------------------------------------

    def _get_stats_data_per_answer(
        self, user_input_lines: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], None]:
        """Statistics for ranking/constant_sum: average value per suggested answer."""
        table_data = []
        graph_data = []
        for answer in self.suggested_answer_ids:
            lines = user_input_lines.filtered(
                lambda ln, a=answer: ln.suggested_answer_id == a and not ln.skipped
            )
            values = [ln.value_numerical_box for ln in lines]
            avg_val = sum(values) / len(values) if values else 0
            table_data.append(
                {
                    "value": answer.value,
                    "suggested_answer": answer,
                    "count": len(values),
                    "count_text": _("Avg: %s", round(avg_val, 1)),
                }
            )
            graph_data.append({"text": answer.value, "count": round(avg_val, 1)})
        return table_data, [{"key": self.title, "values": graph_data}], None

    # ------------------------------------------------------------------
    # TEXT ANALYSIS
    # ------------------------------------------------------------------

    # Common English stop words excluded from word frequency analysis
    _STOP_WORDS = frozenset(
        [
            "a",
            "an",
            "the",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "is",
            "it",
            "was",
            "be",
            "are",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "i",
            "me",
            "my",
            "we",
            "our",
            "you",
            "your",
            "he",
            "she",
            "they",
            "them",
            "their",
            "this",
            "that",
            "these",
            "those",
            "with",
            "from",
            "by",
            "not",
            "no",
            "so",
            "if",
            "as",
            "up",
            "out",
            "about",
            "into",
            "over",
            "after",
            "very",
            "much",
            "more",
            "most",
            "also",
            "just",
            "than",
            "too",
            "all",
            "any",
            "each",
            "every",
            "some",
            "both",
            "few",
            "many",
            "how",
            "what",
            "when",
            "where",
            "which",
            "who",
            "whom",
            "why",
            "its",
            "his",
            "her",
            "there",
            "here",
            "then",
            "now",
            "only",
            "still",
            "already",
            "even",
            "again",
        ]
    )

    def _get_text_analysis(
        self, user_input_lines: Any
    ) -> dict[str, list[dict[str, Any]]]:
        """Compute keyword frequency data for open-text questions.

        Returns a dict with ``word_cloud`` (list of ``{text, weight}`` for the
        top 50 words) and ``top_keywords`` (top 20 with counts).
        """
        self.ensure_one()
        field_name = (
            "value_text_box" if self.question_type == "text_box" else "value_char_box"
        )
        all_text = " ".join(
            getattr(line, field_name) or ""
            for line in user_input_lines
            if not line.skipped
        )
        if not all_text.strip():
            return {"word_cloud": [], "top_keywords": []}

        # Tokenize: lowercase, split on non-alphanumeric, filter stop words and short words
        words = re.findall(r"[a-záéíóúñüàèìòùâêîôû]{3,}", all_text.lower())
        words = [w for w in words if w not in self._STOP_WORDS]
        counter = collections.Counter(words)

        top_50 = counter.most_common(50)
        max_count = top_50[0][1] if top_50 else 1
        word_cloud = [
            {"text": word, "weight": round(count / max_count * 100)}
            for word, count in top_50
        ]
        top_keywords = [
            {"word": word, "count": count} for word, count in counter.most_common(20)
        ]
        return {
            "word_cloud": word_cloud,
            "top_keywords": top_keywords,
        }

    # ------------------------------------------------------------------
    # SUMMARY / AGGREGATION
    # ------------------------------------------------------------------

    def _get_stats_summary_data(self, user_input_lines: Any) -> dict[str, Any]:
        """Dispatch summary computation by question type."""
        stats = {}
        if self.question_type in ["simple_choice", "dropdown", "multiple_choice"]:
            stats.update(self._get_stats_summary_data_choice(user_input_lines))
        elif self.question_type in ("numerical_box", "slider"):
            stats.update(self._get_stats_summary_data_numerical(user_input_lines))
        elif self.question_type in ("scale", "nps", "rating"):
            stats.update(
                self._get_stats_summary_data_numerical(user_input_lines, "value_scale")
            )

        if self.question_type in [
            "numerical_box",
            "slider",
            "date",
            "datetime",
            "scale",
            "nps",
            "rating",
        ]:
            stats.update(self._get_stats_summary_data_scored(user_input_lines))
        return stats

    def _get_stats_summary_data_choice(self, user_input_lines: Any) -> dict[str, Any]:
        """Compute correct/partial answer counts for choice questions."""
        right_inputs, partial_inputs = (
            self.env["survey.user_input"],
            self.env["survey.user_input"],
        )
        right_answers = self.suggested_answer_ids.filtered(
            lambda label: label.is_correct
        )
        if self.question_type == "multiple_choice":
            for user_input, lines in tools.groupby(
                user_input_lines, operator.itemgetter("user_input_id")
            ):
                input_lines = self.env["survey.user_input.line"].concat(*lines)
                all_selected = input_lines.mapped("suggested_answer_id")
                correct_selected = input_lines.filtered(
                    lambda l: l.answer_is_correct
                ).mapped("suggested_answer_id")
                # Fully correct: selected exactly the right answers (no extra wrong ones)
                if (
                    correct_selected
                    and correct_selected == right_answers
                    and all_selected == right_answers
                ):
                    right_inputs += user_input
                elif correct_selected:
                    partial_inputs += user_input
        else:
            right_inputs = user_input_lines.filtered(
                lambda line: line.answer_is_correct
            ).mapped("user_input_id")
        return {
            "right_answers": right_answers,
            "right_inputs_count": len(right_inputs),
            "partial_inputs_count": len(partial_inputs),
        }

    def _get_stats_summary_data_numerical(
        self, user_input_lines: Any, fname: str = "value_numerical_box"
    ) -> dict[str, float]:
        """Compute min/max/average for numerical-valued answers."""
        all_values = user_input_lines.filtered(lambda line: not line.skipped).mapped(
            fname
        )
        lines_sum = sum(all_values)
        return {
            "numerical_max": max(all_values, default=0),
            "numerical_min": min(all_values, default=0),
            "numerical_average": round(lines_sum / (len(all_values) or 1), 2),
        }

    # Question types that reuse another type's value field for storage
    _VALUE_FIELD_ALIAS = {"nps": "scale", "slider": "numerical_box", "rating": "scale"}

    def _get_stats_summary_data_scored(self, user_input_lines: Any) -> dict[str, Any]:
        """Compute most-common answers and correct-answer counts for scored questions."""
        value_field_type = self._VALUE_FIELD_ALIAS.get(
            self.question_type, self.question_type
        )
        return {
            "common_lines": collections.Counter(
                user_input_lines.filtered(lambda line: not line.skipped).mapped(
                    f"value_{value_field_type}"
                )
            ).most_common(5),
            "right_inputs_count": len(
                user_input_lines.filtered(lambda line: line.answer_is_correct).mapped(
                    "user_input_id"
                )
            ),
        }

    # ------------------------------------------------------------------
    # CORRECT ANSWERS
    # ------------------------------------------------------------------

    def _get_correct_answers(self) -> dict[int, Any]:
        """Return a dict mapping scorable question ids to their correct answers.

        For choice questions the value is a list of ``survey.question.answer``
        ids; for numerical/date/datetime it is the formatted correct value.
        Questions without a configured correct answer are omitted.
        """
        correct_answers = {}

        # Simple and multiple choice
        choices_questions = self.filtered(
            lambda q: q.question_type in ["simple_choice", "dropdown", "multiple_choice"]
        )
        if choices_questions:
            suggested_answers_data = self.env["survey.question.answer"].search_read(
                [
                    ("question_id", "in", choices_questions.ids),
                    ("is_correct", "=", True),
                ],
                ["question_id", "id"],
                load="",  # prevent computing display_names
            )
            for data in suggested_answers_data:
                if not data.get("id"):
                    continue
                correct_answers.setdefault(data["question_id"], []).append(data["id"])

        # Numerical box, date, datetime
        for question in self - choices_questions:
            if question.question_type not in ["numerical_box", "date", "datetime"]:
                continue
            answer = question[f"answer_{question.question_type}"]
            if question.question_type == "date":
                answer = tools.format_date(self.env, answer)
            elif question.question_type == "datetime":
                answer = tools.format_datetime(
                    self.env, answer, tz="UTC", dt_format=False
                )
            correct_answers[question.id] = answer

        return correct_answers
