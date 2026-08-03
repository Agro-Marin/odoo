/** @odoo-module native */
import { SurveyKanbanRenderer } from "@survey/views/kanban/kanban_renderer";
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

export const SurveyKanbanView = {
    ...kanbanView,
    Renderer: SurveyKanbanRenderer,
};

registry.category("views").add("survey_view_kanban", SurveyKanbanView);
