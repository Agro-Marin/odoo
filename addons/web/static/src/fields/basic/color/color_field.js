// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/color/color_field */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { useFieldHandle } from "@web/fields/field_handle";
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

    /** @type {{ livePreview: string | null }} */
    state;

    setup() {
        this.field = useFieldHandle();
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
        this.props.record.update(
            { [this.props.name]: /** @type {HTMLInputElement} */ (ev.target).value },
            { save: this.props.autosave },
        );
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
