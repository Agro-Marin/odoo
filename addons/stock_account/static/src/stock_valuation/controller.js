/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { serializeDate } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { useService } from "@web/core/utils/hooks";
const { DateTime } = luxon;

export class StockValuationReportController {
    constructor(action) {
        this.action = action;
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.state = reactive({
            date: DateTime.now(),
        });
        this.loadRequestId = 0;
    }

    async load() {
        await this.loadReportData();
        this.currencyId = this.data.currency_id;
        this.companyId = this.data.company_id;
    }

    async loadReportData() {
        const requestId = ++this.loadRequestId;
        const kwargs = {
            date: this.state.date.toISODate() || false,
        };
        const res = await this.orm.call(
            "stock_account.stock.valuation.report",
            "get_report_values",
            [],
            kwargs,
        );
        if (requestId !== this.loadRequestId) {
            // A more recent loadReportData() call started after this one; discard
            // this stale response so an out-of-order resolution can't overwrite
            // the data of the request the user is actually waiting on.
            return;
        }
        this.data = res.data;
        if (this.data.inventory_loss) {
            for (const line of this.data.inventory_loss.lines) {
                line.account = this.data.accounts_by_id[line.account_id];
            }
        }
        for (const line of this.data.stock_variation.lines) {
            line.account = this.data.accounts_by_id[line.account_id];
        }
        this.data.initial_balance.lines = [];
        for (const [accountId, data] of Object.entries(
            this.data.initial_balance.lines_by_account_id,
        )) {
            const account = this.data.accounts_by_id[accountId];
            this.data.initial_balance.lines.push({
                label: account.display_name,
                value: data.value,
                account_id: accountId,
            });
        }
        this.data.ending_stock.lines = [];
        for (const [accountId, data] of Object.entries(
            this.data.ending_stock.lines_by_account_id,
        )) {
            const account = this.data.accounts_by_id[accountId];
            this.data.ending_stock.lines.push({
                label: account?.display_name,
                value: data.value,
                account_id: accountId,
            });
        }
    }

    async setDate(date) {
        this.state.date = date;
        this.dateAsString = serializeDate(date);
        await this.loadReportData();
    }

    async actionGenerateEntry() {
        const args = [[this.companyId]];
        const date = serializeDate(this.state.date);
        if (date !== serializeDate(DateTime.now())) {
            args.push(date);
        }
        const action = await this.orm.call(
            "res.company",
            "action_close_stock_valuation",
            args,
        );
        if (action) {
            this.actionService.doAction(action);
        }
    }
}
