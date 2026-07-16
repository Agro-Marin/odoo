/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class AccountBatchSendingSummary extends Component {
    static template = "account.BatchSendingSummary";
    static props = {
        ...standardFieldProps,
    };

    // Getter so the template re-reads the field on every render; a value cached in
    // setup() would go stale when the record reloads or the field changes.
    get data() {
        return this.props.record.data[this.props.name];
    }
}

export const accountBatchSendingSummary = {
    component: AccountBatchSendingSummary,
};

registry
    .category("fields")
    .add("account_batch_sending_summary", accountBatchSendingSummary);
