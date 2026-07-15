/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import {
    PopoverComponent,
    PopoverWidgetField,
    popoverWidgetField,
} from "@stock/widgets/popover_widget";

export class StockReschedulingPopoverComponent extends PopoverComponent {
    setup(){
        this.action = useService("action");
    }

    openElement(ev){
        this.action.doAction({
            res_model: ev.currentTarget.getAttribute('element-model'),
            res_id: parseInt(ev.currentTarget.getAttribute("element-id"), 10),
            views: [[false, "form"]],
            type: "ir.actions.act_window",
            view_mode: "form",
        });
    }
}

export class StockReschedulingPopover extends PopoverWidgetField {
    static components = {
        Popover: StockReschedulingPopoverComponent
    };
    setup(){
        super.setup();
        this.color = this.jsonValue.color || 'text-danger';
        // Set the full FA7 class (family + name); the parent's bare-name
        // normalization only runs on the default, not on this override, so a
        // bare "fa-triangle-exclamation" here would render with no glyph.
        this.icon = this.jsonValue.icon
            ? (this.jsonValue.icon.includes(' ') ? this.jsonValue.icon : `fa-solid ${this.jsonValue.icon}`)
            : 'fa-solid fa-triangle-exclamation';
    }

    showPopup(ev){
        if (!this.jsonValue.late_elements){
            return;
        }
        super.showPopup(ev);
    }
}

registry.category("fields").add("stock_rescheduling_popover", {
    ...popoverWidgetField,
    component: StockReschedulingPopover,
});
