/** @odoo-module native */
import { registry } from "@web/core/registry";
import { AccrualListController } from "./accrual_list_controller.js";
import { AccrualListSearchModel } from "./accrual_list_search_model.js";
import { listView } from "@web/views/list";

export const accrualListView = {
    ...listView,
    buttonTemplate: "account.AccrualListView.Buttons",
    Controller: AccrualListController,
    SearchModel: AccrualListSearchModel,
};

registry.category("views").add("accrual_list_view", accrualListView);
