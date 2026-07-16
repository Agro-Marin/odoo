/** @odoo-module native */
import { registry } from "@web/core/registry";
import { usePopover } from "@web/ui/popover/popover_hook";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/fields/standard_field_props";

/**
 * Extend this to add functionality to Popover (custom methods etc.)
 * need to extend PopoverWidgetField as well and set its Popover Component to new extension
 */
export class PopoverComponent extends Component {
    static template = "stock.popoverContent";
    static props = ["record", "*"];
}

/**
 * Widget Popover for JSON field (char), renders a popover above an icon button on click
 * {
 *  'msg': '<CONTENT OF THE POPOVER>' required if not 'popoverTemplate' is given,
 *  'icon': '<FONT AWESOME CLASS>' default='fa-circle-info',
 *  'color': '<COLOR CLASS OF ICON>' default='text-primary',
 *  'position': <POSITION OF THE POPOVER> default='top',
 *  'popoverTemplate': '<TEMPLATE OF THE POPOVER>' default='stock.popoverContent'
 *   pass a template for popover to use, other data passed in JSON field will be passed
 *   to popover template inside props (ex. props.someValue), must be owl template
 * }
 */

export class PopoverWidgetField extends Component {
    static template = "stock.popoverButton";
    static components = { Popover: PopoverComponent };
    static props = {...standardFieldProps};
    setup(){
        this.popover = usePopover(this.constructor.components.Popover, {
            position: this.jsonValue.position || "top",
        });
    }

    // Re-parse when the underlying char value changes (record reload / recompute)
    // instead of snapshotting once in setup — mirrors json_widget, so the button
    // icon/color and popover content never go stale. Memoized on the raw value.
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
        // Support full FA7 class strings ("fa-solid fa-x") and bare icon names ("fa-x")
        const rawIcon = this.jsonValue.icon || "fa-circle-info";
        return rawIcon.includes(" ") ? rawIcon : `fa-solid ${rawIcon}`;
    }

    showPopup(ev){
        this.popover.open(ev.currentTarget, { ...this.jsonValue, record: this.props.record });
    }
}

export const popoverWidgetField = {
    component: PopoverWidgetField,
    supportedTypes: ['char'],
};

registry.category("fields").add("popover_widget", popoverWidgetField);
