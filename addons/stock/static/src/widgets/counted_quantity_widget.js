/** @odoo-module native */
import { useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/fields/basic/float/float_field";

export class CountedQuantityWidgetField extends FloatField {
    // These blur/keydown listeners run *in addition to* the base FloatField's own
    // useInputField commit, and that duplication is deliberate: the base only
    // commits when the value actually changed (`hasValueChanged`), but counting a
    // quant to its current on-hand value (e.g. typing 0 when it is already 0) must
    // still fire the onchange so `inventory_quantity_set` flips and the diff is
    // recomputed. Do not collapse this into the base path — it would silently break
    // "set to the default value" counting. See the two counted_quantity tests.
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
        } catch {
            // Parse failure: the base FloatField commit runs on the same event and
            // already flags the field invalid (setInvalidField), so swallow here
            // rather than double-reporting.
        }
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
