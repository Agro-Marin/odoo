/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Field } from "@web/fields/field";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class PartnerField extends Component {
    static components = { Field };
    static props = { ...standardFieldProps };
    static template = "account.PartnerField";

    get nameToDisplay() {
        if (this.props.record.data.partner_id) {
            return this.props.record.data.partner_id.display_name;
        }
        return this.props.record.data.invoice_partner_display_name;
    }
}

export const partnerField = { component: PartnerField };
registry.category("fields").add("partner_field", partnerField);
