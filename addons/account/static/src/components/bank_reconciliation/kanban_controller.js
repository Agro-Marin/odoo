/** @odoo-module native */
import { onWillDestroy, onWillRender, useSubEnv } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { makeActiveField } from "@web/model/relational_model";
import { KanbanController } from "@web/views/kanban";

import { useBankReconciliation } from "./bank_reconciliation_service.js";

const ID_NAME = { id: "int", display_name: "char" };

/**
 * @param {Record<string, string>} types
 * @param {Record<string, object>} [nested]
 * @param {string[]} [active] the fields to read, when not all of `types`
 */
function relatedSpec(types, nested = {}, active = Object.keys(types)) {
    const fields = {};
    for (const [name, type] of Object.entries(types)) {
        fields[name] = { name, type };
    }
    const activeFields = {};
    for (const name of active) {
        activeFields[name] = makeActiveField();
        if (nested[name]) {
            activeFields[name].related = nested[name];
        }
    }
    return { fields, activeFields };
}

function relatedField(spec) {
    const field = makeActiveField();
    field.related = spec;
    return field;
}

function currencySpec() {
    return relatedSpec({ ...ID_NAME, decimal_places: "int" });
}

function matchedLinesSpec() {
    return relatedSpec(
        { ...ID_NAME, exchange_move_id: "many2one" },
        {
            exchange_move_id: relatedSpec(
                { ...ID_NAME, line_ids: "one2many" },
                { line_ids: relatedSpec({ ...ID_NAME, balance: "monetary" }) },
            ),
        },
    );
}

const log = makeLogger("account.bank_rec.controller");

export class BankRecKanbanController extends KanbanController {
    static template = "account.BankRecoKanbanController";

    async setup() {
        useLifecycleLog(log);
        super.setup();
        this.orm = useService("orm");
        this.bankReconciliation = useBankReconciliation();
        this.bankReconciliation.hydrateChatterState();
        useSubEnv({
            bus: this.bankReconciliation.bus,
        });
        useHotkey("alt+shift+c", () => this.bankReconciliation.toggleChatter(), {
            bypassEditableProtection: true,
            withOverlay: () => this.rootRef.el.querySelector(".bank-chatter-btn"),
        });
        onWillRender(() => {
            user.updateContext({ from_bank_reco: true });
        });
        onWillDestroy(() => {
            user.updateContext({ from_bank_reco: false });
        });
    }

    async createRecord() {
        this.env.bus.trigger("createRecordQuickCreate");
    }

    getCheckedField() {
        return {
            fields: {
                checked: { name: "checked", type: "char" },
            },
            activeFields: {
                checked: makeActiveField(),
            },
        };
    }

    get modelParams() {
        const params = super.modelParams;
        const active = params.config.activeFields;
        active.move_id = relatedField(
            relatedSpec(
                { ...ID_NAME, attachment_ids: "one2many", checked: "char" },
                {},
                ["attachment_ids", "checked"],
            ),
        );
        active.bank_statement_attachment_ids = relatedField(relatedSpec(ID_NAME));
        active.attachment_ids = makeActiveField();
        active.partner_id = relatedField(
            relatedSpec({
                ...ID_NAME,
                property_account_receivable_id: "many2one",
                property_account_payable_id: "many2one",
                customer_rank: "int",
                supplier_rank: "int",
            }),
        );
        active.currency_id = relatedField(currencySpec());
        active.foreign_currency_id.related = currencySpec();
        active.line_ids = relatedField(this._lineSpec());
        active.journal_id = relatedField(
            relatedSpec({
                id: "int",
                suspense_account_id: "many2one",
                default_account_id: "many2one",
                currency_id: "many2one",
            }),
        );
        active.company_id = relatedField(
            relatedSpec({ id: "int", currency_id: "many2one" }),
        );
        return params;
    }

    _lineSpec() {
        return relatedSpec(
            {
                ...ID_NAME,
                name: "char",
                balance: "monetary",
                amount_currency: "monetary",
                currency_id: "many2one",
                currency_rate: "float",
                is_same_currency: "boolean",
                company_currency_id: "many2one",
                account_id: "many2one",
                partner_id: "many2one",
                move_id: "many2one",
                move_attachment_ids: "one2many",
                reconciled_lines_ids: "many2many",
                reconciled_lines_excluding_exchange_diff_ids: "many2many",
                matched_debit_ids: "one2many",
                matched_credit_ids: "one2many",
                reconcile_model_id: "many2one",
                has_invalid_analytics: "boolean",
                analytic_distribution: "jsonb",
                tax_line_id: "many2one",
                tax_ids: "many2many",
            },
            {
                move_attachment_ids: relatedSpec(ID_NAME),
                matched_debit_ids: matchedLinesSpec(),
                matched_credit_ids: matchedLinesSpec(),
                reconciled_lines_ids: relatedSpec(
                    {
                        ...ID_NAME,
                        move_name: "char",
                        move_id: "many2one",
                        amount_currency: "monetary",
                        full_reconcile_id: "many2one",
                        currency_id: "many2one",
                        move_attachment_ids: "one2many",
                    },
                    { move_id: this.getCheckedField() },
                ),
                reconciled_lines_excluding_exchange_diff_ids: relatedSpec(
                    { id: "int", move_name: "char", move_id: "many2one" },
                    { move_id: this.getCheckedField() },
                ),
                move_id: this.getCheckedField(),
                tax_ids: relatedSpec(ID_NAME),
                partner_id: relatedSpec({
                    ...ID_NAME,
                    property_account_receivable_id: "many2one",
                    property_account_payable_id: "many2one",
                }),
                account_id: relatedSpec({
                    ...ID_NAME,
                    account_type: "char",
                    reconcile: "boolean",
                }),
            },
        );
    }
}
