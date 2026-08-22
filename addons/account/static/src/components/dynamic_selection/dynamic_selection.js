/** @odoo-module native */

import { registry } from "@web/core/registry";
import {
    SelectionField,
    selectionField,
} from "@web/fields/selection/selection/selection_field";

export class DynamicSelectionField extends SelectionField {
    static props = {
        ...SelectionField.props,
        available_field: { type: String },
    };

    get availableOptions() {
        return (
            this.props.record.data[this.props.available_field]?.split(/\s*,\s*/) || []
        );
    }

    /**
     * @override
     */
    get options() {
        const availableOptions = this.availableOptions;
        return super.options.filter((x) => availableOptions.includes(x[0]));
    }

    /**
     * @override
     */
    get string() {
        if (this.type === "selection") {
            return this.props.record.data[this.props.name] !== false
                ? (this.options.find(
                      (o) => o[0] === this.props.record.data[this.props.name],
                  )?.[1] ?? "")
                : "";
        }
        return super.string;
    }
}

registry.category("fields").add("dynamic_selection", {
    ...selectionField,
    component: DynamicSelectionField,
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...selectionField.extractProps(fieldInfo, dynamicInfo),
        available_field: fieldInfo.options.available_field,
    }),
});
