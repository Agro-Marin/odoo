// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/boolean_favorite/boolean_favorite_field */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { extractAutosave } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BooleanFavoriteField extends Component {
    static template = "web.BooleanFavoriteField";
    static props = {
        ...standardFieldProps,
        noLabel: { type: Boolean, optional: true },
        autosave: { type: Boolean, optional: true },
    };
    static defaultProps = {
        noLabel: false,
        autosave: true,
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** @returns {string} */
    get iconClass() {
        return this.field.value ? "fa-solid fa-star me-1" : "fa-regular fa-star me-1";
    }

    /** @returns {string} */
    get label() {
        return this.field.value ? _t("Remove from Favorites") : _t("Add to Favorites");
    }

    /** @returns {Promise<void>} */
    async update() {
        if (this.props.readonly) {
            return;
        }
        await this.field.update(!this.field.value, { save: this.props.autosave });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const booleanFavoriteField = {
    component: BooleanFavoriteField,
    displayName: _t("Favorite"),
    supportedTypes: ["boolean"],
    isEmpty: () => false,
    interactiveOutsideEdition: true,
    listViewWidth: ({ hasLabel }) => (!hasLabel ? 20 : false),
    supportedOptions: [
        {
            label: _t("Autosave"),
            name: "autosave",
            type: "boolean",
            default: true,
            help: _t(
                "If checked, the record will be saved immediately when the field is modified.",
            ),
        },
    ],
    extractProps: ({ attrs, options }, dynamicInfo) => ({
        noLabel: exprToBoolean(attrs.nolabel),
        autosave: extractAutosave(options),
    }),
};

registerField("boolean_favorite", booleanFavoriteField);
