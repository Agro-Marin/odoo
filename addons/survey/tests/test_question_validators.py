import base64

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.survey.tests import common


@tagged("post_install", "-at_install")
class TestQuestionValidators(common.TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form = cls.env["survey.survey"].create(
            {
                "title": "Validation survey",
                "access_mode": "public",
                "users_login_required": False,
                "users_can_go_back": False,
            }
        )

    def _question(self, qtype, **vals):
        return self.env["survey.question"].create(
            {
                "title": f"Q {qtype}",
                "survey_id": self.form.id,
                "question_type": qtype,
                "constr_mandatory": True,
                "constr_error_msg": "Answer required",
                **vals,
            }
        )

    def test_slider_accepts_value_inside_bounds(self):
        question = self._question("slider", slider_min=10, slider_max=20)
        self.assertFalse(question._check_answer_slider(15))
        self.assertFalse(question._check_answer_slider(10))
        self.assertFalse(question._check_answer_slider(20))

    def test_slider_rejects_value_outside_bounds(self):
        question = self._question("slider", slider_min=10, slider_max=20)
        self.assertTrue(question._check_answer_slider(9))
        self.assertTrue(question._check_answer_slider(21))

    def test_slider_rejects_non_numeric(self):
        question = self._question("slider", slider_min=0, slider_max=100)
        self.assertIn("numerical", str(question._check_answer_slider("abc")).lower())

    def test_slider_zero_is_an_answer(self):
        question = self._question("slider", slider_min=0, slider_max=10)
        self.assertFalse(question._check_answer_slider(0))
        self.assertTrue(question._check_answer_slider(None))

    def test_rating_accepts_value_within_scale(self):
        question = self._question("rating", rating_max=5)
        self.assertFalse(question._check_answer_rating(1))
        self.assertFalse(question._check_answer_rating(5))

    def test_rating_rejects_value_off_scale(self):
        question = self._question("rating", rating_max=5)
        self.assertTrue(question._check_answer_rating(6))
        self.assertTrue(question._check_answer_rating(-1))

    def test_rating_rejects_non_integer(self):
        question = self._question("rating", rating_max=5)
        self.assertIn("invalid", str(question._check_answer_rating("abc")).lower())

    def test_ranking_requires_every_item(self):
        question = self._question(
            "ranking",
            suggested_answer_ids=[
                Command.create({"value": "First"}),
                Command.create({"value": "Second"}),
            ],
        )
        answers = question.suggested_answer_ids
        self.assertTrue(question._check_answer_ranking({str(answers[0].id): 1}))
        self.assertFalse(
            question._check_answer_ranking(
                {
                    str(answers[0].id): 1,
                    str(answers[1].id): 2,
                }
            )
        )

    def test_ranking_rejects_wrong_shape(self):
        question = self._question(
            "ranking",
            suggested_answer_ids=[
                Command.create({"value": "Only"}),
            ],
        )
        self.assertTrue(question._check_answer_ranking(["1"]))

    def test_constant_sum_requires_the_exact_total(self):
        question = self._question("constant_sum", constant_sum_total=100)
        self.assertFalse(question._check_answer_constant_sum({"a": 60, "b": 40}))
        self.assertTrue(question._check_answer_constant_sum({"a": 60, "b": 30}))

    def test_constant_sum_tolerates_float_noise(self):
        question = self._question("constant_sum", constant_sum_total=100)
        self.assertFalse(question._check_answer_constant_sum({"a": 33.333, "b": 66.67}))

    def test_constant_sum_rejects_non_numeric_values(self):
        question = self._question("constant_sum", constant_sum_total=100)
        self.assertIn(
            "numbers",
            str(question._check_answer_constant_sum({"a": "x", "b": 100})).lower(),
        )

    def _attachment(self, name, size_mb=0):
        return self.env["ir.attachment"].create(
            {
                "name": name,
                "datas": base64.b64encode(b"x" * max(1, int(size_mb * 1024 * 1024))),
            }
        )

    def test_file_upload_accepts_allowed_extension(self):
        question = self._question(
            "file_upload",
            file_upload_types=".pdf,.png",
            file_upload_max_size=5,
        )
        self.assertFalse(
            question._check_answer_file_upload(self._attachment("report.pdf").id)
        )

    def test_file_upload_rejects_other_extension(self):
        question = self._question("file_upload", file_upload_types=".pdf")
        self.assertIn(
            "file type",
            str(
                question._check_answer_file_upload(self._attachment("payload.exe").id)
            ).lower(),
        )

    def test_file_upload_rejects_oversized_file(self):
        question = self._question("file_upload", file_upload_max_size=1)
        big = self._attachment("big.png", size_mb=2)
        self.assertIn(
            "maximum size",
            str(question._check_answer_file_upload(big.id)).lower(),
        )

    def test_file_upload_rejects_unknown_attachment(self):
        question = self._question("file_upload")
        self.assertIn(
            "not found", str(question._check_answer_file_upload(99999999)).lower()
        )

    def test_file_upload_default_types_are_enforced(self):
        question = self._question("file_upload")
        self.assertIn(".pdf", question.file_upload_types)
        self.assertIn(
            "file type",
            str(
                question._check_answer_file_upload(self._attachment("payload.bin").id)
            ).lower(),
        )
