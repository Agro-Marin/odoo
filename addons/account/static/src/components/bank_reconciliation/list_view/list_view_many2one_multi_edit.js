/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {
    buildM2OFieldDescription,
    computeM2OProps,
    Many2One,
    Many2OneField,
} from "@web/fields/relational/many2one";
import { useViewModel } from "@web/model/model";

export class BankRecMany2OneMultiID extends Component {
    static template = "account.BankRecMany2OneMultiID";
    static components = { Many2One };
    static props = { ...Many2OneField.props };

    setup() {
        super.setup();
        this.model = useViewModel();
    }

    get m2oProps() {
        const props = computeM2OProps(this.props);
        if (
            this.model &&
            this.props.record.selected &&
            this.props.record.model.multiEdit
        ) {
            props.context.active_ids = this.props.record.model.root.selection.map(
                (r) => r.resId,
            );
        }
        return props;
    }
}

registry.category("fields").add("bank_rec_list_many2one_multi_id", {
    ...buildM2OFieldDescription(BankRecMany2OneMultiID),
});
