/** @odoo-module */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";

import { AnalyticAccountListController } from "./analytic_account_list_controller.js";

export const AnalyticAccountListView = {
    ...listView,
    Controller: AnalyticAccountListController,
};

registry.category("views").add("analytic_account_list_view", AnalyticAccountListView);
