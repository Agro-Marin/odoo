/** @odoo-module native */
import { Component } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class MOListViewDropdown extends Component {
    static template = "mrp.MOViewListDropdown";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.colorIcons = {
            blocked: "bg-warning",
            ready: "bg-muted",
            progress: "bg-info",
            cancel: "bg-danger",
            done: "bg-success",
        };
    }

    async reload() {
        await this.env.model.root.load();
        this.env.model.notify();
    }

    get statusColor() {
        // Read the record's reactive state directly so the dot stays in sync.
        return this.colorIcons[this.props.record.data.state] || "";
    }

    async setState(state) {
        let selectedWorkorders = this.props.record.model.root.selection;
        if (!selectedWorkorders || selectedWorkorders.length === 0) {
            selectedWorkorders = [this.props.record];
        }
        const ids = selectedWorkorders
            .filter(
                (wo) =>
                    !(
                        [state, "done"].includes(wo.data.state) ||
                        wo.data.production_state === "done"
                    ),
            )
            .map((wo) => wo.resId);
        if (ids.length > 0) {
            await this.callOrm("set_state", [state], ids);
        }
    }

    async callOrm(functionName, args, ids = undefined) {
        if (!ids) {
            ids = this.props.record.model.root.selection?.map((wo) => wo.resId);
        }
        // if no records selected, take the current clicked one
        if (!ids || ids.length === 0) {
            ids = [this.props.record.resId];
        }
        if (args !== undefined) {
            await this.orm.call("mrp.workorder", functionName, [ids, ...args]);
        } else {
            await this.orm.call("mrp.workorder", functionName, [ids]);
        }
        await this.reload();
    }
}

export const moListViewDropdown = {
    listViewWidth: 20,
    component: MOListViewDropdown,
};

registry.category("view_widgets").add("mo_view_list_dropdown", moListViewDropdown);
