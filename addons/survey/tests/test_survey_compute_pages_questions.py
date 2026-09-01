from odoo.addons.survey.tests import common


class TestSurveyComputePagesQuestions(common.TestSurveyCommon):
    def test_compute_pages_questions(self):
        with self.with_user("survey_manager"):
            survey = self.env["survey.survey"].create(
                {
                    "title": "Test compute survey",
                }
            )

            page_0 = self.env["survey.question"].create(
                {
                    "is_page": True,
                    "question_type": False,
                    "sequence": 1,
                    "title": "P1",
                    "survey_id": survey.id,
                }
            )
            page0_q0 = self._add_question(page_0, "Q1", "text_box", survey_id=survey.id)
            page0_q1 = self._add_question(page_0, "Q2", "text_box", survey_id=survey.id)
            page0_q2 = self._add_question(page_0, "Q3", "text_box", survey_id=survey.id)
            page0_q3 = self._add_question(page_0, "Q4", "text_box", survey_id=survey.id)
            page0_q4 = self._add_question(page_0, "Q5", "text_box", survey_id=survey.id)

            page_1 = self.env["survey.question"].create(
                {
                    "is_page": True,
                    "question_type": False,
                    "sequence": 7,
                    "title": "P2",
                    "survey_id": survey.id,
                }
            )
            page1_q0 = self._add_question(page_1, "Q6", "text_box", survey_id=survey.id)
            page1_q1 = self._add_question(page_1, "Q7", "text_box", survey_id=survey.id)
            page1_q2 = self._add_question(page_1, "Q8", "text_box", survey_id=survey.id)
            page1_q3 = self._add_question(page_1, "Q9", "text_box", survey_id=survey.id)

        self.assertEqual(len(survey.page_ids), 2, "Survey should have 2 pages")
        self.assertIn(
            page_0, survey.page_ids, "Page 1 should be contained in survey's page_ids"
        )
        self.assertIn(
            page_1, survey.page_ids, "Page 2 should be contained in survey's page_ids"
        )

        self.assertEqual(len(page_0.question_ids), 5, "Page 1 should have 5 questions")
        self.assertIn(page0_q0, page_0.question_ids, "Question 1 should be in page 1")
        self.assertIn(page0_q1, page_0.question_ids, "Question 2 should be in page 1")
        self.assertIn(page0_q2, page_0.question_ids, "Question 3 should be in page 1")
        self.assertIn(page0_q3, page_0.question_ids, "Question 4 should be in page 1")
        self.assertIn(page0_q4, page_0.question_ids, "Question 5 should be in page 1")

        self.assertEqual(len(page_1.question_ids), 4, "Page 2 should have 4 questions")
        self.assertIn(page1_q0, page_1.question_ids, "Question 6 should be in page 2")
        self.assertIn(page1_q1, page_1.question_ids, "Question 7 should be in page 2")
        self.assertIn(page1_q2, page_1.question_ids, "Question 8 should be in page 2")
        self.assertIn(page1_q3, page_1.question_ids, "Question 9 should be in page 2")

        self.assertEqual(page0_q0.page_id, page_0, "Question 1 should belong to page 1")
        self.assertEqual(page0_q1.page_id, page_0, "Question 2 should belong to page 1")
        self.assertEqual(page0_q2.page_id, page_0, "Question 3 should belong to page 1")
        self.assertEqual(page0_q3.page_id, page_0, "Question 4 should belong to page 1")
        self.assertEqual(page0_q4.page_id, page_0, "Question 5 should belong to page 1")

        self.assertEqual(page1_q0.page_id, page_1, "Question 6 should belong to page 2")
        self.assertEqual(page1_q1.page_id, page_1, "Question 7 should belong to page 2")
        self.assertEqual(page1_q2.page_id, page_1, "Question 8 should belong to page 2")
        self.assertEqual(page1_q3.page_id, page_1, "Question 9 should belong to page 2")

        page0_q2.write({"sequence": 12})
        page0_q2._compute_page_id()
        self.assertEqual(
            page0_q2.page_id, page_1, "Question 3 should now belong to page 2"
        )

    def test_compute_page_id_batch_create_out_of_sequence_order(self):
        """A One2many's in-cache order right after a batch create() is command
        order, not the model's (sequence, id) order — _compute_page_id must
        not assume the sort is already correct."""
        with self.with_user("survey_manager"):
            survey = self.env["survey.survey"].create(
                {
                    "title": "Out of order survey",
                    "question_and_page_ids": [
                        (
                            0,
                            0,
                            {
                                "is_page": True,
                                "question_type": False,
                                "title": "P1",
                                "sequence": 1,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "title": "Q1c",
                                "question_type": "text_box",
                                "sequence": 4,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "title": "Q1a",
                                "question_type": "text_box",
                                "sequence": 2,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "title": "Q1b",
                                "question_type": "text_box",
                                "sequence": 3,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "is_page": True,
                                "question_type": False,
                                "title": "P2",
                                "sequence": 5,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "title": "Q2a",
                                "question_type": "text_box",
                                "sequence": 6,
                            },
                        ),
                    ],
                }
            )
        questions = {q.title: q for q in survey.question_and_page_ids}
        for title in ("Q1c", "Q1a", "Q1b"):
            self.assertEqual(
                questions[title].page_id,
                questions["P1"],
                f"{title} should belong to P1, read right after batch create",
            )
        self.assertEqual(questions["Q2a"].page_id, questions["P2"])
