/** @odoo-module native */
import { useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/fields/basic/float/float_field";

export class CountedQuantityWidgetField extends FloatField {
    setup() {
        super.setup();

        const inputRef = useRef("numpadDecimal");

        useEffect(
            (inputEl) => {
                if (inputEl) {
                    const boundOnKeydown = this.onKeydown.bind(this);
                    const boundOnBlur = this.onBlur.bind(this);
                    inputEl.addEventListener("keydown", boundOnKeydown);
                    inputEl.addEventListener("blur", boundOnBlur);
                    return () => {
                        inputEl.removeEventListener("keydown", boundOnKeydown);
                        inputEl.removeEventListener("blur", boundOnBlur);
                    };
                }
            },
            () => [inputRef.el],
        );
    }

    updateValue(ev) {
        try {
            const val = this.parse(ev.target.value);
            this.props.record.update({
                [this.props.name]: val,
                inventory_quantity_set: true,
            });
        } catch {}
    }

    onBlur(ev) {
        this.updateValue(ev);
    }

    onKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        if (["enter", "tab", "shift+tab"].includes(hotkey)) {
            this.updateValue(ev);
        }
    }

    get formattedValue() {
        if (
            this.props.readonly &&
            !this.props.record.data[this.props.name] &&
            !this.props.record.data.inventory_quantity_set
        ) {
            return "";
        }
        return super.formattedValue;
    }
}

export const countedQuantityWidgetField = {
    ...floatField,
    component: CountedQuantityWidgetField,
};

registry.category("fields").add("counted_quantity_widget", countedQuantityWidgetField);
