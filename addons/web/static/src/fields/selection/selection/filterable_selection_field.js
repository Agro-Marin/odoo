// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/selection/filterable_selection_field */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import {
    SelectionField,
    selectionField,
} from "@web/fields/selection/selection/selection_field";
export class FilterableSelectionField extends SelectionField {
    static props = {
        ...SelectionField.props,
        whitelist_fname: { type: String, optional: true },
        whitelisted_values: { type: Array, optional: true },
        blacklisted_values: { type: Array, optional: true },
    };

    /**
     * @override
     * @returns {Array<[string, string]>}
     */
    get options() {
        /** @type {Array<[string, string]>} */
        let options = super.options;
        if (this.props.whitelist_fname) {
            const whitelist = this.props.record.data[this.props.whitelist_fname] || [];
            options = options.filter(
                (option) => option[0] === this.value || whitelist.includes(option[0]),
            );
        } else if (this.props.whitelisted_values) {
            options = options.filter(
                (option) =>
                    option[0] === this.value ||
                    this.props.whitelisted_values.includes(option[0]),
            );
        } else if (this.props.blacklisted_values) {
            options = options.filter(
                (option) =>
                    option[0] === this.value ||
                    !this.props.blacklisted_values.includes(option[0]),
            );
        }
        return options;
    }
}

export const filterableSelectionField = {
    ...selectionField,
    component: FilterableSelectionField,
    supportedOptions: [
        {
            label: _t("Whitelisted Values"),
            name: "whitelisted_values",
            type: "string",
        },
        {
            label: _t("Blacklisted Values"),
            name: "blacklisted_values",
            type: "string",
        },
        {
            label: _t("Whitelisted field name"),
            name: "whitelist_fname",
            type: "string",
        },
    ],
    extractProps: (/** @type {any} */ fieldInfo, /** @type {any} */ dynamicInfo) => ({
        ...selectionField.extractProps(fieldInfo, dynamicInfo),
        whitelist_fname: fieldInfo.options.whitelist_fname,
        whitelisted_values: fieldInfo.options.whitelisted_values,
        blacklisted_values: fieldInfo.options.blacklisted_values,
    }),
};

registerField("filterable_selection", filterableSelectionField);
