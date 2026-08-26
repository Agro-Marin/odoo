from odoo.tests import tagged
from odoo.tests.common import HttpCase, warmup

from odoo.addons.survey.tests import common


@tagged("post_install", "-at_install")
class SurveyPerformance(common.TestSurveyResultsCommon, HttpCase):
    @warmup
    def test_survey_results_with_multiple_filters_mixed_model(self):
        url = f"/survey/results/{self.survey.id}?filters=A,0,{self.gras_id}|L,0,{self.answer_pauline.id}"
        self.authenticate("survey_manager", "survey_manager")
        with self.assertQueryCount(default=26):
            self.url_open(url)

    @warmup
    def test_survey_results_with_multiple_filters_question_answer_model(self):
        url = f"/survey/results/{self.survey.id}?filters=A,0,{self.gras_id}|A,0,{self.cat_id}"
        self.authenticate("survey_manager", "survey_manager")
        with self.assertQueryCount(default=24):
            self.url_open(url)

    @warmup
    def test_survey_results_with_one_filter(self):
        url = f"/survey/results/{self.survey.id}?filters=A,0,{self.cat_id}"
        self.authenticate("survey_manager", "survey_manager")
        with self.assertQueryCount(default=24):
            self.url_open(url)
