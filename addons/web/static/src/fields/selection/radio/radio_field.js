// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/radio/radio_field - Radio button group field for Selection and Many2one columns */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { isFalseEmpty } from "@web/fields/field_utils";
import { SelectionLikeField } from "@web/fields/selection/selection_like_field";
import { standardFieldProps } from "@web/fields/standard_field_props";

let nextId = 0;
/**
 * @typedef {import("@web/fields/standard_field_props").StandardFieldProps & {
 *     orientation?: string;
 *     label?: string;
 *     domain?: any[] | Function;
 * }} RadioFieldProps
 */
/** @extends {SelectionLikeField} */
export class RadioField extends SelectionLikeField {
    static template = "web.RadioField";
    static props = {
        ...standardFieldProps,
        orientation: { type: String, optional: true },
        label: { type: String, optional: true },
        domain: { type: [Array, Function], optional: true },
    };
    static defaultProps = {
        orientation: "vertical",
    };

    setup() {
        // Reuses type detection and the `name_search`-backed special data from
        // `SelectionLikeField` (shared with badge/selection). `name_search` is
        // bounded by the ORM's default limit, unlike the previous unbounded
        // `web_search_read` this field used to issue.
        super.setup();
        this.id = `radio_field_${nextId++}`;
    }

    /** @returns {Array<[any, string]>} Options as `[value, label]` pairs */
    get items() {
        switch (this.type) {
            case "selection":
                return this.props.record.fields[this.props.name].selection;
            case "many2one":
                return this.specialData.data;
            default:
                return [];
        }
    }

    /**
     * @param {[any, string]} value the clicked `[value, label]` option
     */
    onChange(value) {
        switch (this.type) {
            case "selection":
                this.props.record.update({ [this.props.name]: value[0] });
                break;
            case "many2one":
                this.props.record.update({
                    [this.props.name]: value && {
                        id: value[0],
                        display_name: value[1],
                    },
                });
                break;
        }
    }
}

export const radioField = {
    component: RadioField,
    displayName: _t("Radio"),
    supportedOptions: [
        {
            label: _t("Display horizontally"),
            name: "horizontal",
            type: "boolean",
        },
    ],
    supportedTypes: ["many2one", "selection"],
    isEmpty: isFalseEmpty,
    extractProps: ({ options, string }, dynamicInfo) => ({
        orientation: options.horizontal ? "horizontal" : "vertical",
        label: string,
        domain: dynamicInfo.domain,
    }),
};

registerField("radio", radioField);
