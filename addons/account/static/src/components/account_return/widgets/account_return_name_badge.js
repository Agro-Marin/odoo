/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class AccountReturnNameBadge extends Component {
    static template = "account.AccountReturnNameBadgeField";
    static props = {
        ...standardFieldProps,
        options: { type: Object, optional: true },
    };

    updateName(event) {
        const newName = event.target.value;
        this.props.record.update({ name: newName });
        this.props.record.save();
    }
}

export const accountReturnNameBadge = {
    supportedTypes: ["char"],
    component: AccountReturnNameBadge,
    extractProps: ({ options }) => ({ options }),
};

registry.category("fields").add("account_return_name_badge", accountReturnNameBadge);
