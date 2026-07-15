/** @odoo-module native */
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/fields/standard_field_props";

/**
 * Base for read-only display fields whose stored value is a JSON string blob.
 * Subclasses provide a `template`, any child `components`, and a `defaultValue`
 * getter used when the field is empty or contains an unparseable value.
 */
export class JsonBlobField extends Component {
    static props = { ...standardFieldProps };

    /** @returns {Object} value returned when the field is empty/unparseable */
    get defaultValue() {
        return {};
    }

    getValue() {
        const value = this.props.record.data[this.props.name];
        if (!value) {
            return this.defaultValue;
        }
        try {
            return JSON.parse(value);
        } catch {
            // A malformed blob should render as empty, not throw during render.
            return this.defaultValue;
        }
    }
}
