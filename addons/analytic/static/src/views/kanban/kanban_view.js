/** @odoo-module native */
import { AnalyticSearchModel } from "@analytic/views/analytic_search_model";
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";

export const analyticKanbanView = {
    ...kanbanView,
    SearchModel: AnalyticSearchModel,
};

registry.category("views").add("analytic_kanban", analyticKanbanView);
