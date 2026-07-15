/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { formatMonetary } from "@web/fields/formatters";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

import { Component, onWillStart, useChildSubEnv, useState } from "@odoo/owl";

import { StockValuationReportButtonsBar } from "../stock_valuation/buttons_bar/buttons_bar.js"
import { StockValuationReportController } from "../stock_valuation/controller.js"
import { StockValuationReportFilters } from "../stock_valuation/filters/filters.js"
import { StockValuationReportLine } from "../stock_valuation/line/line.js"
import { StockValuationReportToggleLine } from "../stock_valuation/line/toggle_line.js"
import { serializeDate } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
const { DateTime } = luxon;


export class StockValuationReport extends Component {
    static template = "stock_account.StockValuationReport";
    static props = { ...standardActionServiceProps };
    static components = {
        ControlPanel,
        StockValuationReportButtonsBar,
        StockValuationReportFilters,
        StockValuationReportLine,
        StockValuationReportToggleLine,
    };

    setup() {
        this.controller = useState(new StockValuationReportController(this.props.action));
        this.actionService = useService("action");
        this._t = _t;

        onWillStart(async () => {
            await this.controller.load(this.data);
        })

        useChildSubEnv({
            _t,
            controller: this.controller,
            formatMonetary: this.formatMonetary.bind(this),
        });
    }

    formatMonetary(value) {
        return formatMonetary(value, {
            currencyId: this.data.currency_id,
        });
    }

    get accrual() {
        return { label: _t("Accrual"), lines: [], value: 0 };
    }

    // Getters -----------------------------------------------------------------
    get data() {
        return this.controller.data || {};
    }

    // On Click Methods --------------------------------------------------------
    async openAccountMoves(accountIds=false) {
        const action = await this.actionService.loadAction("account.action_account_moves_all");
        const domain = [...(action.domain || [])];
        if (accountIds) {
            domain.push(['account_id', 'in', accountIds]);
        }
        if (serializeDate(this.controller.state.date) !== serializeDate(DateTime.now())) {
            domain.push(['date', '<=', serializeDate(this.controller.state.date)]);
        }
        action.domain = domain;
        action.context = {
            ...action.context,
            search_default_group_by_account: 1,
            search_default_groupby_date: 'month',
        };
        return this.actionService.doAction(action);
    }

    openStockMoveView(title, usage) {
        const domain = [
            "|",
            ["location_id.usage", "=", usage],
            ["location_dest_id.usage", "=", usage],
        ];
        if (this.controller.dateAsString) {
            domain.unshift("&");
            domain.push(["date", "<=", this.controller.dateAsString]);
        }
        return this.actionService.doAction({
            name: title,
            type: "ir.actions.act_window",
            res_model: "stock.move",
            domain,
            views: [[false, 'list'], [false, 'form']],
            target: 'current',
        });
    }

    openInventoryLoss() {
        return this.openStockMoveView(_t("Inventory Loss"), "inventory");
    }

    openStockReport() {
        const additionalContext = {};
        if (this.controller.dateAsString) {
            additionalContext.to_date = this.controller.dateAsString;
        }
        return this.actionService.doAction(
            "stock.action_product_stock_view",
            { additionalContext }
        );
    }
}

registry.category("actions").add("stock_valuation_report", StockValuationReport);
