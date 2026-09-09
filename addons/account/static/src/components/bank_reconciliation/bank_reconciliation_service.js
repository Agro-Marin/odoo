/** @odoo-module native */
import { EventBus, reactive, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { Domain } from "@web/core/domain";

export class BankReconciliationService {
    constructor(env, services) {
        this.env = env;
        this.setup(env, services);
    }

    setup(env, services) {
        this.bus = new EventBus();
        this.orm = services["orm"];
        this.batchedOrm = services["batchedOrm"];

        // Chatter visibility is persisted across reloads in sessionStorage.
        // The read is deferred to the first widget mount (see
        // hydrateChatterState): this service sits in the global registry, so
        // its setup runs on every page, and reading storage here would leak a
        // getItem into unrelated tests that track sessionStorage I/O.
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

    /**
     * Lazy-load the persisted chatter visibility from sessionStorage on
     * first interaction with the bank reconciliation UI. Components that
     * use ``chatterState.visible`` should call this in their ``setup``.
     */
    hydrateChatterState() {
        if (this._chatterStateHydrated) {
            return;
        }
        this._chatterStateHydrated = true;
        // String compare instead of JSON.parse: a polluted literal such as
        // "undefined" would otherwise throw and corrupt UI initialisation.
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

    /**
     * Opens the chatter without toggling it closed, e.g. when the chatter icon
     * is clicked directly on a bank statement line.
     */
    openChatter() {
        this.hydrateChatterState();
        this.chatterState.visible = true;
    }

    selectStatementLine(statementLine) {
        this.chatterState.statementLine = statementLine;
    }

    reloadChatter() {
        this.bus.trigger("MAIL:RELOAD-THREAD", {
            model: "account.move",
            id: this.statementLineMoveId,
        });
    }

    async computeAvailableReconcileLines(records) {
        // Only a transaction with no partner ever consults this list, and only for an
        // entry whose amount equals its own. Both narrowings belong in the query: the
        // `limit` was applied by date over every open entry of the company and the amount
        // filter ran in JS afterwards, so an entry that matched exactly but sat at
        // position 101 by date was silently invisible. The domain itself is still built
        // from every record on the page -- it excludes the page's own transactions from
        // being offered, and dropping the partnered ones from it would offer theirs.
        const unassigned = records.filter((record) => !record.data.partner_id?.id);
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
     * The analytic account ids named by one or more analytic distributions.
     *
     * A distribution is keyed by a comma-joined list of account ids, plus the "__update__"
     * bookkeeping key the record model adds. Both readers below used to spell this out,
     * and they disagreed on `!=` versus `!==` for the same test.
     *
     * @param {Object[]} distributions
     * @returns {number[]} unique ids
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
        // Always an object, never `[]`: the other writer merges into this with a spread,
        // and an array would quietly change the shape its readers index into.
        this.availableAnalyticAccounts = analyticAccountIds.length
            ? await this.fetchAnalyticAccounts(analyticAccountIds)
            : {};
    }

    /**
     * @param {number[]} ids
     * @returns {Object} the fetched accounts, keyed by id
     */
    async fetchAnalyticAccounts(ids) {
        // Takes ids, and says so. It used to take a `domain`, build an `args` object
        // holding that domain plus a `context`, and then read `domain[0][2]` -- the ids
        // out of the first leaf -- ignoring the rest. The only domain it ever supported
        // was `[["id", "in", ids]]`, which is what both callers passed.
        const records = await this.batchedOrm.read(
            "account.analytic.account",
            ids,
            ["id", "display_name", "root_plan_id", "color"],
            {},
        );
        return Object.fromEntries(records.map(({ id, ...rest }) => [id, rest]));
    }

    async reloadRecords(records) {
        await Promise.all([...records.map((record) => record.load())]);
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
