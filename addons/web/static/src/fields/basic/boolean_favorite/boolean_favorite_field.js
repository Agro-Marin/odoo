// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { archAttribute } from "@web/fields/field_options";
import { autosaveOption } from "@web/fields/field_options";
import { extractAutosave } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BooleanFavoriteField extends FieldComponent {
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
    supportedAttributes: [
        archAttribute("nolabel", _t("No label"), {
            type: "boolean",
            help: _t("Render the star without the field label beside it."),
        }),
    ],
    supportedTypes: ["boolean"],
    isEmpty: () => false,
    interactiveOutsideEdition: true,
    listViewWidth: ({ hasLabel }) => (!hasLabel ? 20 : false),
    supportedOptions: [autosaveOption()],
    extractProps: ({ attrs, options }, dynamicInfo) => ({
        noLabel: exprToBoolean(attrs.nolabel),
        autosave: extractAutosave(options),
    }),
};

registerField("boolean_favorite", booleanFavoriteField);
