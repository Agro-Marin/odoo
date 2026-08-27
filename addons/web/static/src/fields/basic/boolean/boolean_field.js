// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { _t } from "@web/core/translation";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { fieldHandleFor } from "@web/fields/field_handle";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BooleanField extends FieldComponent {
    static template = "web.BooleanField";
    static components = { CheckBox };
    static props = {
        ...standardFieldProps,
    };

    /** @type {{ value?: boolean }} */
    state;

    setup() {
        useRenderCounter("fields.BooleanField");
        this.state = useState(/** @type {{ value?: boolean }} */ ({}));
        useRecordObserver((record) => {
            this.state.value = fieldHandleFor(record, this.props.name).value;
        });
    }

    /**
     * The single override point for subclasses that save on toggle. Kept as a
     * getter rather than a duplicated `onChange`, which is what the toggle and
     * its list variant each used to carry.
     *
     * @returns {{ save?: boolean } | undefined}
     */
    get updateOptions() {
        return undefined;
    }

    /**
     * @param {boolean} newValue
     */
    async onChange(newValue) {
        this.state.value = newValue;
        try {
            await this.field.update(newValue, this.updateOptions);
        } catch (error) {
            this.state.value = this.field.value;
            throw error;
        }
    }
}

export const booleanField = {
    component: BooleanField,
    displayName: _t("Checkbox"),
    supportedTypes: ["boolean"],
    isEmpty: () => false,
};

registerField("boolean", /** @type {any} */ (booleanField));
