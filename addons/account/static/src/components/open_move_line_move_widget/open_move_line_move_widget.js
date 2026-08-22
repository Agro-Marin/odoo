/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    buildM2OFieldDescription,
    computeM2OProps,
    Many2One,
    Many2OneField,
} from "@web/fields/relational/many2one";

class LineOpenMoveWidget extends Component {
    static template = "account.LineOpenMoveWidget";
    static components = { Many2One };
    static props = { ...Many2OneField.props };

    setup() {
        this.accountMove = useService("account_move");
    }

    get m2oProps() {
        return {
            ...computeM2OProps(this.props),
            openRecordAction: () => this.openAction(),
        };
    }

    openAction() {
        return this.accountMove.openBusinessDoc({
            // The field's own relation, rather than the one model this widget
            // happens to be used on today.
            resModel: this.props.record.fields[this.props.name].relation,
            resId: this.props.record.data[this.props.name].id,
        });
    }
}

registry.category("fields").add("line_open_move_widget", {
    ...buildM2OFieldDescription(LineOpenMoveWidget),
});
