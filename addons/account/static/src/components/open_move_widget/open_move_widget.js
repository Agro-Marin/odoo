/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/fields/standard_field_props";

class OpenMoveWidget extends Component {
    static template = "account.OpenMoveWidget";
    static props = { ...standardFieldProps };

    setup() {
        this.accountMove = useService("account_move");
    }

    openMove() {
        return this.accountMove.openBusinessDoc({
            resModel: this.props.record.resModel,
            resId: this.props.record.resId,
        });
    }
}

registry.category("fields").add("open_move_widget", {
    component: OpenMoveWidget,
});
