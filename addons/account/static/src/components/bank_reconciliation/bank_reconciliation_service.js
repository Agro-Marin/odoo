/** @odoo-module native */
import { EventBus, reactive, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { Domain } from "@web/core/domain";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const log = makeLogger("account.bank_rec");

export class BankReconciliationService {
    constructor(env, services) {
        this.env = env;
        this.setup(env, services);
    }

    setup(env, services) {
        this.bus = new EventBus();
        this.orm = services["orm"];
        this.batchedOrm = services["batchedOrm"];

        this.chatterState = reactive({
            visible: false,
            statementLine: null,
        });
        this._chatterStateHydrated = false;
        this.reconcileCountPerPartnerId = reactive({});
        this.reconcileModelPerStatementLineId = reactive({});
        this.availableReconcileLines = reactive([]);
        this.availableAnalyticAccounts = reactive({});
    }

    hydrateChatterState() {
        if (this._chatterStateHydrated) {
            return;
        }
        this._chatterStateHydrated = true;
        const stored = browser.sessionStorage.getItem(
            "isBankReconciliationWidgetChatterOpened",
        );
        if (stored === "true") {
            this.chatterState.visible = true;
        }
    }

    toggleChatter() {
        this.hydrateChatterState();
        this.chatterState.visible = !this.chatterState.visible;
        browser.sessionStorage.setItem(
            "isBankReconciliationWidgetChatterOpened",
            String(this.chatterState.visible),
        );
    }

    openChatter() {
        this.hydrateChatterState();
        this.chatterState.visible = true;
    }

    selectStatementLine(statementLine) {
        log.logic("selectStatementLine", () => ({
            id: statementLine?.resId ?? statementLine?.id,
        }));
        this.chatterState.statementLine = statementLine;
    }

    reloadChatter() {
        this.bus.trigger("MAIL:RELOAD-THREAD", {
            model: "account.move",
            id: this.statementLineMoveId,
        });
    }

    async computeAvailableReconcileLines(records) {
        const unassigned = records.filter((record) => !record.data.partner_id?.id);
        log.pipeline("computeAvailableReconcileLines", () => ({
            records: records.length,
            unassigned: unassigned.length,
        }));
        if (!unassigned.length) {
            this.availableReconcileLines = [];
            return;
        }
        const amounts = [
            ...new Set(
                unassigned.map(
                    (record) => record.data.amount_currency || record.data.amount,
                ),
            ),
        ];
        this.availableReconcileLines = await this.orm.searchRead(
            "account.move.line",
            [
                ...this.getAvailableReconciledLinesDomain(records),
                ["amount_currency", "in", amounts],
            ],
            ["id", "amount_currency", "date"],
            { limit: 100, order: "date desc" },
        );
    }

    getAvailableReconciledLinesDomain(records) {
        return [
            ["parent_state", "in", ["draft", "posted"]],
            [
                "company_id",
                "child_of",
                records.map((record) => record.data.company_id.id),
            ],
            ["account_lookup_id.reconcile", "=", true],
            ["display_type", "not in", ["line_section", "line_note"]],
            ["reconciled", "=", false],
            "|",
            [
                "account_lookup_id.account_type",
                "not in",
                ["asset_receivable", "liability_payable"],
            ],
            ["payment_id", "=", false],
            ["statement_line_id", "not in", records.map((record) => record.data.id)],
        ];
    }

    async computeReconcileLineCountPerPartnerId(records) {
        const domain = this.getAvailableReconciledLinesDomain(records);
        const partnerIds = records
            .filter((record) => !!record.data.partner_id?.id)
            .map((record) => record.data.partner_id.id);
        const finalDomain = Domain.and([
            [["partner_id", "in", partnerIds]],
            domain,
        ]).toList();
        const groups = await this.orm.formattedReadGroup(
            "account.move.line",
            finalDomain,
            ["partner_id"],
            ["id:count"],
        );

        this.reconcileCountPerPartnerId = {};
        groups.forEach((group) => {
            this.reconcileCountPerPartnerId[group.partner_id[0]] = group["id:count"];
        });
    }

    async computeAvailableReconcileModels(records) {
        log.pipeline("computeAvailableReconcileModels", () => ({
            records: Object.keys(records).length,
        }));
        this.reconcileModelPerStatementLineId =
            Object.keys(records).length === 0
                ? {}
                : await this.orm.call(
                      "account.reconcile.model",
                      "get_available_reconcile_model_per_statement_line",
                      [records.map((record) => record.data.id)],
                  );
    }

    async updateAvailableReconcileModels(recordId) {
        const result = await this.orm.call(
            "account.reconcile.model",
            "get_available_reconcile_model_per_statement_line",
            [[recordId]],
        );
        this.reconcileModelPerStatementLineId[recordId] = result[recordId];
    }

    /**
     * @param {Object[]} distributions
     * @returns {number[]}
     */
    analyticAccountIdsOf(distributions) {
        return [
            ...new Set(
                distributions.flatMap((distribution) =>
                    Object.keys(distribution || {})
                        .filter((key) => key !== "__update__")
                        .flatMap((key) => key.split(","))
                        .map((id) => parseInt(id)),
                ),
            ),
        ].filter((id) => !isNaN(id));
    }

    async checkAnalyticAccounts(analyticAccounts) {
        const missingIds = this.analyticAccountIdsOf([analyticAccounts]).filter(
            (id) => !this.availableAnalyticAccounts[id],
        );
        if (missingIds.length) {
            this.availableAnalyticAccounts = {
                ...this.availableAnalyticAccounts,
                ...(await this.fetchAnalyticAccounts(missingIds)),
            };
        }
    }

    async computeAvailableAnalyticAccounts(records) {
        const analyticAccountIds = this.analyticAccountIdsOf(
            records
                .flatMap((record) => record.data.line_ids.records)
                .map((line) => line.data.analytic_distribution)
                .filter(Boolean),
        );
        this.availableAnalyticAccounts = analyticAccountIds.length
            ? await this.fetchAnalyticAccounts(analyticAccountIds)
            : {};
    }

    /**
     * @param {number[]} ids
     * @returns {Object}
     */
    async fetchAnalyticAccounts(ids) {
        const records = await this.batchedOrm.read(
            "account.analytic.account",
            ids,
            ["id", "display_name", "root_plan_id", "color"],
            {},
        );
        return Object.fromEntries(records.map(({ id, ...rest }) => [id, rest]));
    }

    async reloadRecords(records) {
        const endReload = log.perf("reloadRecords");
        await Promise.all([...records.map((record) => record.load())]);
        endReload({ records: records.length });
    }

    get statementLineMove() {
        return this.chatterState.statementLine?.data.move_id;
    }

    get statementLineMoveId() {
        return this.statementLineMove?.id;
    }

    get statementLine() {
        return this.chatterState.statementLine;
    }

    get statementLineId() {
        return this.statementLine?.data?.id;
    }
}

const bankReconciliationService = {
    dependencies: ["orm", "batchedOrm"],
    start(env, services) {
        return new BankReconciliationService(env, services);
    },
};

registry.category("services").add("bankReconciliation", bankReconciliationService);

export function useBankReconciliation() {
    return useState(useService("bankReconciliation"));
}
