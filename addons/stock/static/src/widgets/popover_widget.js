/** @odoo-module native */
import { Component } from "@odoo/owl";
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
    setup() {
        this.popover = usePopover(this.constructor.components.Popover, {
            position: this.jsonValue.position || "top",
        });
    }

    get jsonValue() {
        const raw = this.props.record.data[this.props.name];
        if (raw !== this._rawValue) {
            this._rawValue = raw;
            this._jsonValue = JSON.parse(raw || "{}");
        }
        return this._jsonValue;
    }

    get color() {
        return this.jsonValue.color || "text-primary";
    }

    get icon() {
        const rawIcon = this.jsonValue.icon || "fa-circle-info";
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
