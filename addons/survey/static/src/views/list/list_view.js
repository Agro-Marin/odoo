/** @odoo-module native */
import { SurveyListRenderer } from "@survey/views/list/list_renderer";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list";

export const SurveyListView = {
    ...listView,
    Renderer: SurveyListRenderer,
};

registry.category("views").add("survey_view_tree", SurveyListView);
