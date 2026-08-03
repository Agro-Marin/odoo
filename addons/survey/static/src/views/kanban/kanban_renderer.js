/** @odoo-module native */
import { SurveySurveyActionHelper } from "@survey/views/components/survey_survey_action_helper/survey_survey_action_helper";
import { KanbanRenderer } from "@web/views/kanban";

export class SurveyKanbanRenderer extends KanbanRenderer {
    static template = "survey.SurveyKanbanRenderer";
    static components = {
        ...KanbanRenderer.components,
        SurveySurveyActionHelper,
    };
}
