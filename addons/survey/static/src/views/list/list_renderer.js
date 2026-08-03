/** @odoo-module native */
import { SurveySurveyActionHelper } from "@survey/views/components/survey_survey_action_helper/survey_survey_action_helper";
import { ListRenderer } from "@web/views/list";

export class SurveyListRenderer extends ListRenderer {
    static template = "survey.SurveyListRenderer";
    static components = {
        ...ListRenderer.components,
        SurveySurveyActionHelper,
    };
}
