/** @odoo-module native */
import { Component, useRef } from "@odoo/owl";
import { TagsList } from "@web/components/tags_list";
import { formatMonetary, formatPercentage } from "@web/core/formatters";
import { x2ManyCommands } from "@web/core/network";
import { _t } from "@web/core/translation";
import { roundDecimals } from "@web/core/utils/format/numbers";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/ui/popover";

import { useBankReconciliation } from "../bank_reconciliation_service.js";
import { BankRecFormDialog } from "../bankrec_form_dialog/bankrec_form_dialog.js";
import { BankRecLineInfoPopOver } from "../line_info_pop_over/line_info_pop_over.js";

export class BankRecLineToReconcile extends Component {
    static template = "account.BankRecLineToReconcile";

    static components = {
        TagsList,
    };

    static props = {
        line: Object,
        statementLine: Object,
    };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.dialogService = useService("dialog");
        this.ui = useService("ui");
        this.bankReconciliation = useBankReconciliation();

        this.lineInfoRef = useRef("line-info-ref");
        this.lineInfoPopOver = usePopover(BankRecLineInfoPopOver, {
            position: "left",
            closeOnClickAway: true,
        });
    }

    onClickLine() {
        if (this.ui.isSmall) {
            this.toggleEditLine();
        }
    }

    /**
     * Opens a `BankRecFormDialog` to edit the current `account.move.line`. On
     * save, calls `edit_reconcile_line` on the ORM, reloads the statement line
     * and refreshes the chatter of the related journal entry.
     */
    toggleEditLine() {
        this.dialogService.add(BankRecFormDialog, {
            title: _t("Edit Line"),
            resModel: "account.move.line",
            resId: this.lineData.id,
            context: {
                skip_analytic_sync: true,
                form_view_ref: "account.view_bank_rec_edit_line",
                is_reviewed: this.lineData.move_id.checked,
            },
            onRecordSave: async (record) => {
                const changes = await record.getChanges();
                await this.orm.call(
                    "account.bank.statement.line",
                    "edit_reconcile_line",
                    [this.statementLineData.id, this.lineData.id, changes],
                );
                if (Object.keys(changes?.analytic_distribution || {}).length) {
                    await this.bankReconciliation.checkAnalyticAccounts(
                        changes?.analytic_distribution,
                    );
                }
                this.props.statementLine.load();
                this.bankReconciliation.reloadChatter();
                return true;
            },
        });
    }

    /**
     * Deletes a line to reconcile via `remove_reconciled_line`, then reloads the
     * statement line and refreshes the chatter of the related journal entry.
     */
    async deleteLine() {
        await this.orm.call("account.bank.statement.line", "remove_reconciled_line", [
            this.statementLineData.id,
            this.lineData.id,
        ]);
        if (this.lineData.reconciled_lines_ids.records.length) {
            // Only update the line count per partner if we delete
            // a line which is reconciled to another move line
            // We don't use await here as it could be reloaded asynchronously.
            this.bankReconciliation.computeReconcileLineCountPerPartnerId(
                this.env.model.root.records,
            );
        }
        this.props.statementLine.load();
        this.bankReconciliation.reloadChatter();
    }

    get jsonToData() {
        const jsonFieldValue = this.lineData.analytic_distribution;
        const analyticAccountIds = jsonFieldValue
            ? Object.keys(jsonFieldValue)
                  .filter((key) => key !== "__update__")
                  .map((key) => key.split(","))
                  .flat()
                  .map((id) => parseInt(id))
            : [];

        const fetchedAnalyticAccounts = new Map(
            analyticAccountIds.map((id) => [
                id,
                this.bankReconciliation.availableAnalyticAccounts?.[id],
            ]),
        );
        return this.buildDistribution(jsonFieldValue, fetchedAnalyticAccounts);
    }

    buildDistribution(jsonFieldValue, analyticAccount) {
        const distribution = [];
        let id = 1;
        for (const [accountIds, percentage] of Object.entries(jsonFieldValue)) {
            if (accountIds === "__update__") {
                continue;
            }
            const defaultVals = []; // empty if the popup was not opened
            const ids = accountIds.split(",");

            for (const id of ids) {
                const account = analyticAccount.get(parseInt(id));
                if (!account) {
                    continue;
                }
                // since tags are displayed even though plans might not be retrieved (ie defaultVals is empty)
                // push the accounts anyway, as order doesn't matter
                // once the popup is opened, plans are fetched and the analyticAccounts list will be ordered
                Object.assign(
                    defaultVals.find(
                        (plan) => plan.planId === account.root_plan_id[0],
                    ) ||
                        (defaultVals.push({}) && defaultVals[defaultVals.length - 1]),
                    {
                        accountId: parseInt(id),
                        accountDisplayName: account.display_name,
                        accountColor: account.color,
                        accountRootPlanId: account.root_plan_id[0],
                    },
                );
            }
            distribution.push({
                analyticAccounts: defaultVals,
                percentage: percentage / 100,
                id: id++,
            });
        }
        return distribution;
    }

    planIsComplete(total) {
        return roundDecimals(total, 2) === 1;
    }

    /**
     * Computes the totals for each account, grouped by plan (primarily used in tags)
     * @returns {Object}
     */
    accountTotalsByPlan() {
        const accountTotals = {};
        this.jsonToData.map((line) => {
            line.analyticAccounts.map((column) => {
                if (column.accountId) {
                    let {
                        accId = column.accountId,
                        accName = column.accountDisplayName,
                        total = 0.0,
                        planId = column.accountRootPlanId,
                        planColor = column.accountColor,
                    } = accountTotals[column.accountRootPlanId]?.[column.accountId] ||
                    {};

                    total += roundDecimals(line.percentage, 2);

                    accountTotals[planId] = accountTotals[planId] || {};
                    accountTotals[planId][accId] = {
                        accId,
                        accName,
                        planId,
                        total,
                        planColor,
                    };
                }
            });
        });
        return accountTotals;
    }

    planSummaryTags() {
        const accountTotals = this.accountTotalsByPlan();
        return Object.values(accountTotals).map((planSummary) => {
            const accs = Object.values(planSummary);
            return {
                id: accs[0].planId,
                text: accs.reduce(
                    (p, n) =>
                        p +
                        (p.length ? " | " : "") +
                        (this.planIsComplete(n.total)
                            ? n.accName
                            : `${formatPercentage(n.total)} ${n.accName}`),
                    "",
                ),
                colorIndex: accs[0].planColor,
            };
        });
    }

    // ACTION METHODS
    openMove() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: this.moveData.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPartner() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: this.lineData.partner_id.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    hoverLineInfoPopOver() {
        const popoverConfig = {
            statementLineData: this.statementLineData,
            lineData: this.lineData,
            isPartiallyReconciled: this.isPartiallyReconciled,
        };
        if (this.exchangeMove) {
            popoverConfig.exchangeMove = this.exchangeMove;
        }
        if (!this.lineInfoPopOver.isOpen && this.showLineInfo) {
            this.lineInfoPopOver.open(this.lineInfoRef.el, popoverConfig);
        }
    }

    async deleteTax(taxIndex) {
        const taxChanged = this.lineDataTaxIds[taxIndex];
        await this.orm.call("account.bank.statement.line", "edit_reconcile_line", [
            this.statementLineData.id,
            this.lineData.id,
            { tax_ids: [x2ManyCommands.unlink(taxChanged.data.id)] },
        ]);
        this.props.statementLine.load();
        this.bankReconciliation.reloadChatter();
    }

    // GETTER METHODS
    get statementLineData() {
        return this.props.statementLine.data;
    }

    get lineData() {
        return this.props.line;
    }

    get reconciledLineId() {
        return this.lineData.reconciled_lines_ids.records.length === 1
            ? this.lineData.reconciled_lines_ids.records[0].data
            : null;
    }

    get reconciledLineExcludingExchangeDiffId() {
        return this.lineData.reconciled_lines_excluding_exchange_diff_ids.records
            .length === 1
            ? this.lineData.reconciled_lines_excluding_exchange_diff_ids.records[0].data
            : null;
    }

    get moveData() {
        return (
            this.reconciledLineId?.move_id ||
            this.reconciledLineExcludingExchangeDiffId?.move_id ||
            this.lineData.move_id
        );
    }

    get isPartiallyReconciled() {
        if (!this.reconciledLineId) {
            return false;
        }
        return !this.reconciledLineId.full_reconcile_id?.id;
    }

    get hasDifferentCurrencies() {
        return this.lineData.currency_id.id !== this.statementLineData.currency_id.id;
    }

    get formattedAmountCurrencyOfLine() {
        return formatMonetary(this.lineData.amount_currency, {
            currencyId: this.lineData.currency_id.id,
        });
    }

    get formattedAmountCurrencyOfStatementLine() {
        return formatMonetary(this.lineData.amount_currency, {
            currencyId: this.statementLineData.currency_id.id,
        });
    }

    get exchangeMove() {
        return (
            this.lineData.matched_debit_ids.records[0]?.data.exchange_move_id ||
            this.lineData.matched_credit_ids.records[0]?.data.exchange_move_id
        );
    }

    get showLineInfo() {
        return this.isPartiallyReconciled || this.exchangeMove?.id;
    }

    get isTaxLine() {
        return this.lineData.tax_line_id && !this.lineData.account_id.reconcile;
    }

    get lineDataTaxIds() {
        return this.lineData.tax_ids.records;
    }
}
