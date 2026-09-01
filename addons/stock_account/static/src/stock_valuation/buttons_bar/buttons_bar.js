/** @odoo-module native */
import { Component, useState } from "@odoo/owl";

export class StockValuationReportButtonsBar extends Component {
    static template = "stock_account.StockValuationReportButtonsBar";
    static props = {};

    setup() {
        this.state = useState({ generatingEntry: false });
    }

    async onClickGenerateEntry() {
        if (this.state.generatingEntry) {
            return;
        }
        this.state.generatingEntry = true;
        try {
            return await this.env.controller.actionGenerateEntry();
        } finally {
            this.state.generatingEntry = false;
        }
    }
}
