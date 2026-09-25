/** @odoo-module native */
import { Component, onWillStart } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useViewModel } from "@web/model/model";
import { standardWidgetProps } from "@web/views/widgets";

export class WorkorderStateDropdown extends Component {
    static template = "mrp.WorkorderStateDropdown";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = { ...standardWidgetProps };

    setup() {
        this.model = useViewModel();
        this.orm = useService("orm");
        this.colorIcons = {
            blocked: "bg-warning",
            ready: "bg-muted",
            progress: "bg-info",
            cancel: "bg-danger",
            done: "bg-success",
        };
        onWillStart(async () => {
            this.canSetState = await user.hasGroup("mrp.group_mrp_user");
        });
    }

    get statusColor() {
        return this.colorIcons[this.props.record.data.state] || "";
    }

    targetIds() {
        const selection = this.props.record.model.root.selection;
        return selection?.length
            ? selection.map((workorder) => workorder.resId)
            : [this.props.record.resId];
    }

    async setState(state) {
        await this.orm.call("mrp.workorder", "set_state", [this.targetIds(), state]);
        await this.model.root.load();
        this.model.notify();
    }
}

export const workorderStateDropdown = {
    listViewWidth: 20,
    component: WorkorderStateDropdown,
};

registry.category("view_widgets").add("wo_list_view_dropdown", workorderStateDropdown);
