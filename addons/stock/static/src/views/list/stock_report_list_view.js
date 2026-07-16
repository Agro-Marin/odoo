/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";

import { StockReportSearchModel } from "../search/stock_report_search_model.js";
import { StockReportSearchPanel } from "../search/stock_report_search_panel.js";

export const StockReportListView = {
    ...listView,
    SearchModel: StockReportSearchModel,
    SearchPanel: StockReportSearchPanel,
};

registry.category("views").add("stock_report_list_view", StockReportListView);
