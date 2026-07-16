// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/boolean_icon/boolean_icon_field - Clickable icon field that toggles a Boolean value */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BooleanIconField extends Component {
    static template = "web.BooleanIconField";
    static props = {
        ...standardFieldProps,
        icon: { type: String, optional: true },
        label: { type: String, optional: true },
    };
    static defaultProps = {
        icon: "fa-regular fa-square-check",
    };

    /** Toggles the boolean value and updates the record. */
    update() {
        if (this.props.readonly) {
            return;
        }
        this.props.record.update({
            [this.props.name]: !this.props.record.data[this.props.name],
        });
    }
}

export const booleanIconField = {
    component: BooleanIconField,
    displayName: _t("Boolean Icon"),
    supportedOptions: [
        {
            label: _t("Icon"),
            name: "icon",
            type: "string",
        },
    ],
    supportedTypes: ["boolean"],
    extractProps: ({ options, string }, dynamicInfo) => ({
        icon: options.icon,
        label: string,
        // Extract the evaluated readonly (like boolean_favorite): otherwise
        // field.js defaults it to `readonly || !record.isInEdition`, so the
        // toggle silently no-ops on kanban cards and readonly lists even though
        // update() is meant to be clickable there.
        readonly: dynamicInfo.readonly,
    }),
};

registerField("boolean_icon", booleanIconField);
