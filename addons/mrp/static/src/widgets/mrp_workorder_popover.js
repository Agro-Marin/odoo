/** @odoo-module native */
import {
    PopoverComponent,
    PopoverWidgetField,
    popoverWidgetField,
} from "@stock/widgets/popover_widget";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class WorkOrderPopover extends PopoverComponent {
    setup() {
        this.orm = useService("orm");
    }

    async onReplanClick() {
        await this.orm.call("mrp.workorder", "action_replan", [
            this.props.record.resId,
        ]);
        await this.props.record.model.load();
    }
}

class WorkOrderPopoverField extends PopoverWidgetField {
    static components = {
        Popover: WorkOrderPopover,
    };
}

registry.category("fields").add("mrp_workorder_popover", {
    ...popoverWidgetField,
    component: WorkOrderPopoverField,
});
