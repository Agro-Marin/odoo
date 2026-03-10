/** @odoo-module */
import { listView } from '@web/views/list/list_view';
import { registry } from "@web/core/registry";
import { StockOrderpointListController as Controller } from './stock_orderpoint_list_controller.js';
import { StockOrderpointSearchPanel } from './search/stock_orderpoint_search_panel.js';
import { StockOrderpointSearchModel } from './search/stock_orderpoint_search_model.js';

export const StockOrderpointListView = {
    ...listView,
    Controller,
    SearchPanel: StockOrderpointSearchPanel,
    SearchModel: StockOrderpointSearchModel,
};

registry.category("views").add("stock_orderpoint_list", StockOrderpointListView);
