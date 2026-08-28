/** @odoo-module native */
import { Component } from "@odoo/owl";

export class StockValuationReportButtonsBar extends Component {
    static template = "stock_account.StockValuationReportButtonsBar";
    static props = {};

    onClickGenerateEntry() {
        return this.env.controller.actionGenerateEntry();
    }
}
