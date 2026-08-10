// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/boolean/boolean_field */

import { Component, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { _t } from "@web/core/translation";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BooleanField extends Component {
    static template = "web.BooleanField";
    static components = { CheckBox };
    static props = {
        ...standardFieldProps,
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** @type {{ value?: boolean }} */
    state;

    setup() {
        useRenderCounter("fields.BooleanField");
        this.state = useState(/** @type {{ value?: boolean }} */ ({}));
        useRecordObserver((record) => {
            this.state.value = record.data[this.props.name];
        });
    }

    /**
     * @param {boolean} newValue
     */
    async onChange(newValue) {
        this.state.value = newValue;
        try {
            await this.field.update(newValue);
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
