// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/selection/filterable_selection_field - Selection dropdown field with whitelist/blacklist value filtering */

/**
 * Selection field that hides some values via whitelist/blacklist, so the
 * same model field can expose different option sets per view.
 */

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
     * @returns {Array<[string, string]>} Filtered selection options based on whitelist/blacklist
     */
    get options() {
        let options = super.options;
        if (this.props.whitelist_fname) {
            // The whitelist field is a fields.Json compute that reads ``false``
            // when unset (new record / conditional compute), so guard against
            // ``false.includes`` crashing the form render.
            const whitelist = this.props.record.data[this.props.whitelist_fname] || [];
            options = options.filter(
                (option) =>
                    option[0] === this.props.record.data[this.props.name] ||
                    whitelist.includes(option[0]),
            );
        } else if (this.props.whitelisted_values) {
            options = options.filter(
                (option) =>
                    option[0] === this.props.record.data[this.props.name] ||
                    this.props.whitelisted_values.includes(option[0]),
            );
        } else if (this.props.blacklisted_values) {
            options = options.filter(
                (option) =>
                    option[0] === this.props.record.data[this.props.name] ||
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
            label: "Whitelisted Values",
            name: "whitelisted_values",
            type: "string",
        },
        {
            label: "Blacklisted Values",
            name: "blacklisted_values",
            type: "string",
        },
        {
            label: "Whitelisted field name",
            name: "whitelist_fname",
            type: "string",
        },
    ],
    extractProps({ options }) {
        const props = selectionField.extractProps(...arguments);
        props.whitelist_fname = options.whitelist_fname;
        props.whitelisted_values = options.whitelisted_values;
        props.blacklisted_values = options.blacklisted_values;
        return props;
    },
};

registerField("filterable_selection", filterableSelectionField);
