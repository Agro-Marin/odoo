from lxml import html

from odoo.tests import TransactionCase
from odoo.tools import is_html_empty


class TestEmbeddedPhone(TransactionCase):
    def test_only_main_phone_question_receives_explicit_prefill(self):
        questions = self.env["survey.question"].create(
            [
                {
                    "title": title,
                    "question_type": "char_box",
                    "char_box_type": "phone",
                }
                for title in ("Contact phone", "Alternative phone")
            ]
        )
        for phone in ("+525555551234", ""):
            with self.subTest(phone=phone):
                rendered = self.env["ir.qweb"]._render(
                    "survey.question_form_fields",
                    {
                        "questions": questions,
                        "phone_question": questions[0],
                        "phone_value": phone,
                        "is_html_empty": is_html_empty,
                    },
                )
                inputs = html.fromstring(rendered).xpath("//input[@type='tel']")
                self.assertEqual(len(inputs), 2)
                self.assertEqual(inputs[0].get("value", ""), phone)
                self.assertEqual(inputs[1].get("value", ""), "")
