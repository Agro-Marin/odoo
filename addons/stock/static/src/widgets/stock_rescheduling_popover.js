/** @odoo-module native */
import {
    PopoverComponent,
    PopoverWidgetField,
    popoverWidgetField,
} from "@stock/widgets/popover_widget";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class StockReschedulingPopoverComponent extends PopoverComponent {
    setup() {
        this.action = useService("action");
    }

    openElement(ev) {
        this.action.doAction({
            res_model: ev.currentTarget.getAttribute("element-model"),
            res_id: parseInt(ev.currentTarget.getAttribute("element-id"), 10),
            views: [[false, "form"]],
            type: "ir.actions.act_window",
            view_mode: "form",
        });
    }
}

export class StockReschedulingPopover extends PopoverWidgetField {
    static components = {
        Popover: StockReschedulingPopoverComponent,
    };

    // Getters, like the base class: the parent defines `color`/`icon` as
    // getter-only accessors, so assigning `this.color = ...` in setup() throws
    // a TypeError (strict-mode assignment through an inherited getter).
    get color() {
        return this.jsonValue.color || "text-danger";
    }

    get icon() {
        // Full FA7 class (family + name); the parent's bare-name normalization
        // applies the `fa-solid` family to bare icon names, and this override
        // only changes the default glyph.
        const rawIcon = this.jsonValue.icon || "fa-triangle-exclamation";
        return rawIcon.includes(" ") ? rawIcon : `fa-solid ${rawIcon}`;
    }

    showPopup(ev) {
        if (!this.jsonValue.late_elements) {
            return;
        }
        super.showPopup(ev);
    }
}

registry.category("fields").add("stock_rescheduling_popover", {
    ...popoverWidgetField,
    component: StockReschedulingPopover,
});
