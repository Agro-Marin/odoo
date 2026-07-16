/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";

import { InventoryReportListModel } from "./inventory_report_list_model.js";

export const InventoryReportListView = {
    ...listView,
    Model: InventoryReportListModel,
};

registry.category("views").add("inventory_report_list", InventoryReportListView);
