// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import {
    SelectionField,
    selectionField,
} from "@web/fields/selection/selection/selection_field";
export class FilterableSelectionField extends SelectionField {
    static props = {
        ...SelectionField.props,
        whitelistField: { type: String, optional: true },
        whitelistedValues: { type: Array, optional: true },
        blacklistedValues: { type: Array, optional: true },
    };

    /**
     * @override
     * @returns {Array<[string, string]>}
     */
    get options() {
        /** @type {Array<[string, string]>} */
        let options = super.options;
        if (this.props.whitelistField) {
            const whitelist = this.props.record.data[this.props.whitelistField] || [];
            options = options.filter(
                (option) => option[0] === this.value || whitelist.includes(option[0]),
            );
        } else if (this.props.whitelistedValues) {
            options = options.filter(
                (option) =>
                    option[0] === this.value ||
                    this.props.whitelistedValues.includes(option[0]),
            );
        } else if (this.props.blacklistedValues) {
            options = options.filter(
                (option) =>
                    option[0] === this.value ||
                    !this.props.blacklistedValues.includes(option[0]),
            );
        }
        return options;
    }
}

const filterableSelectionField = {
    ...selectionField,
    component: FilterableSelectionField,
    supportedOptions: [
        {
            label: _t("Whitelisted values"),
            name: "whitelisted_values",
            type: "string",
            help: _t("List of selection values to keep, e.g. `['a', 'b']`."),
        },
        {
            label: _t("Blacklisted values"),
            name: "blacklisted_values",
            type: "string",
            help: _t("List of selection values to drop, e.g. `['a', 'b']`."),
        },
        {
            label: _t("Whitelist field"),
            name: "whitelist_field",
            type: "field",
            help: _t(
                "Field holding the list of selection values to keep. Takes precedence over the two lists above.",
            ),
        },
    ],
    extractProps: (/** @type {any} */ fieldInfo, /** @type {any} */ dynamicInfo) => ({
        ...selectionField.extractProps(fieldInfo, dynamicInfo),
        whitelistField: fieldInfo.options.whitelist_field,
        whitelistedValues: fieldInfo.options.whitelisted_values,
        blacklistedValues: fieldInfo.options.blacklisted_values,
    }),
};

registerField("filterable_selection", filterableSelectionField);
