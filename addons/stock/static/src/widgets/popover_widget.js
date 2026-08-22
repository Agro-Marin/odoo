/** @odoo-module native */
import { Component } from "@odoo/owl";
import { readJsonField } from "@stock/utils/json_field";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { usePopover } from "@web/ui/popover";

export class PopoverComponent extends Component {
    static template = "stock.popoverContent";
    static props = ["record", "*"];
}

export class PopoverWidgetField extends Component {
    static template = "stock.popoverButton";
    static components = { Popover: PopoverComponent };
    static props = { ...standardFieldProps };
    static defaultColor = "text-primary";
    static defaultIcon = "fa-circle-info";

    setup() {
        this.popover = usePopover(this.constructor.components.Popover, {
            position: this.jsonValue.position || "top",
        });
    }

    get jsonValue() {
        return readJsonField(this);
    }

    get color() {
        return this.jsonValue.color || this.constructor.defaultColor;
    }

    get icon() {
        const rawIcon = this.jsonValue.icon || this.constructor.defaultIcon;
        return rawIcon.includes(" ") ? rawIcon : `fa-solid ${rawIcon}`;
    }

    get buttonLabel() {
        return this.jsonValue.title || _t("More information");
    }

    showPopup(ev) {
        this.popover.open(ev.currentTarget, {
            ...this.jsonValue,
            record: this.props.record,
        });
    }
}

export const popoverWidgetField = {
    component: PopoverWidgetField,
    supportedTypes: ["char"],
};

registry.category("fields").add("popover_widget", popoverWidgetField);
