// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/color/color_field */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ColorField extends Component {
    static template = "web.ColorField";
    static props = {
        ...standardFieldProps,
        autosave: { type: Boolean, optional: true },
    };
    static defaultProps = {
        autosave: false,
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** @type {{ livePreview: string | null }} */
    state;

    setup() {
        this.state = useState({ livePreview: null });
    }

    /** @returns {string} */
    get color() {
        if (this.state.livePreview !== null) {
            return this.state.livePreview;
        }
        return this.field.value || "";
    }

    /** @param {Event} ev */
    onInput(ev) {
        this.state.livePreview = /** @type {HTMLInputElement} */ (ev.target).value;
    }

    /** @param {Event} ev */
    onChange(ev) {
        this.state.livePreview = null;
        this.field.update(/** @type {HTMLInputElement} */ (ev.target).value, {
            save: this.props.autosave,
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const colorField = {
    component: ColorField,
    interactiveOutsideEdition: true,
    supportedOptions: [
        {
            label: _t("Autosave"),
            name: "autosave",
            type: "boolean",
            help: _t(
                "Save the record as soon as a colour is picked. Defaults to true in list and kanban views.",
            ),
        },
    ],
    supportedTypes: ["char"],
    extractProps({ viewType, options }, dynamicInfo) {
        let autosave = false;
        if ("autosave" in options) {
            autosave = exprToBoolean(options.autosave);
        } else if (["list", "kanban"].includes(viewType)) {
            autosave = true;
        }
        return {
            autosave,
        };
    },
};

registerField("color", colorField);
