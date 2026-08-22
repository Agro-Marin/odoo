/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    SelectionField,
    selectionField,
} from "@web/fields/selection/selection/selection_field";

const SECTIONS = [
    { label: _t("Balance Sheet"), name: "balance_sheet" },
    { label: _t("Profit & Loss"), name: "profit_and_loss" },
];

const PREFIXED_GROUPS = [
    { label: _t("Assets"), prefix: "asset", section: "balance_sheet" },
    { label: _t("Liabilities"), prefix: "liability", section: "balance_sheet" },
    { label: _t("Equity"), prefix: "equity", section: "balance_sheet" },
    { label: _t("Income"), prefix: "income", section: "profit_and_loss" },
    { label: _t("Expense"), prefix: "expense", section: "profit_and_loss" },
];

const OTHER_GROUP = { label: _t("Other"), section: "profit_and_loss" };

export class AccountTypeSelection extends SelectionField {
    static template = "account.AccountTypeSelection";

    get sections() {
        return SECTIONS;
    }

    /**
     * Group the account types by the section of the report they land in.
     *
     * Getters, not fields built in `setup()`: `choices` derives from the record,
     * and buckets frozen at setup outlive the record they were computed from.
     *
     * `Other` takes whatever the prefixes do not claim — `off_balance` today —
     * because a type matching no prefix would otherwise be absent from the
     * selector with nothing said about it.
     *
     * @returns {Array<{label: string, choices: Array, section: string}>}
     */
    get groups() {
        // One read, and keyed by value: `choices` rebuilds its objects on every
        // access, so identities do not survive a second read.
        const choices = this.choices;
        const claimed = new Set();
        const groups = PREFIXED_GROUPS.map(({ label, prefix, section }) => {
            const groupChoices = choices.filter((choice) =>
                choice.value.startsWith(prefix),
            );
            for (const choice of groupChoices) {
                claimed.add(choice.value);
            }
            return { label, choices: groupChoices, section };
        });
        const unclaimed = choices.filter((choice) => !claimed.has(choice.value));
        return [...groups, { ...OTHER_GROUP, choices: unclaimed }];
    }
}

export const accountTypeSelection = {
    ...selectionField,
    component: AccountTypeSelection,
};

registry.category("fields").add("account_type_selection", accountTypeSelection);
