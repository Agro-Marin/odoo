/** @odoo-module native */
import { AnalyticSearchModel } from "@analytic/views/analytic_search_model";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";

export const analyticListView = {
    ...listView,
    SearchModel: AnalyticSearchModel,
};

registry.category("views").add("analytic_list", analyticListView);
