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
        const isAllowed = this.allowedValuePredicate;
        if (!isAllowed) {
            return super.options;
        }
        const current = this.value;
        return super.options.filter(
            (option) => option[0] === current || isAllowed(option[0]),
        );
    }

    /**
     * The whitelist field wins over the two literal lists, and a whitelist
     * over a blacklist; the current value always stays selectable.
     *
     * @returns {((value: string) => boolean) | null}
     */
    get allowedValuePredicate() {
        const { whitelistField, whitelistedValues, blacklistedValues } = this.props;
        if (whitelistField) {
            const whitelist = this.props.record.data[whitelistField] || [];
            return (value) => whitelist.includes(value);
        }
        if (whitelistedValues) {
            return (value) => whitelistedValues.includes(value);
        }
        if (blacklistedValues) {
            return (value) => !blacklistedValues.includes(value);
        }
        return null;
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
