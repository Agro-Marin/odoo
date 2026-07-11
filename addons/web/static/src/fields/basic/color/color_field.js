// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/color/color_field - Native color picker input field for Char columns */

import { Component, useState } from "@odoo/owl";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ColorField extends Component {
    static template = "web.ColorField";
    static props = {
        ...standardFieldProps,
        autosave: { type: Boolean, optional: true },
    };

    /** @type {{ livePreview: string | null }} */
    state;

    setup() {
        // Transient override so the swatch can live-preview while the user
        // drags inside the native color picker ("input" fires on every move,
        // the record is only updated on "change"). Kept null the rest of the
        // time so the swatch reads the record directly — external updates
        // (e.g. another field's onchange) then reflect synchronously instead
        // of lagging a frame behind a mirrored copy.
        this.state = useState({ livePreview: null });
    }

    /** @returns {string} */
    get color() {
        if (this.state.livePreview !== null) {
            return this.state.livePreview;
        }
        return this.props.record.data[this.props.name] || "";
    }

    /** @param {Event} ev */
    onInput(ev) {
        this.state.livePreview = /** @type {HTMLInputElement} */ (ev.target).value;
    }

    /** @param {Event} ev */
    onChange(ev) {
        // Stop previewing and commit: the swatch falls back to the record,
        // which now carries the chosen color.
        this.state.livePreview = null;
        this.props.record.update(
            { [this.props.name]: /** @type {HTMLInputElement} */ (ev.target).value },
            { save: this.props.autosave },
        );
    }
}

export const colorField = {
    component: ColorField,
    supportedTypes: ["char"],
    extractProps({ viewType, options }, dynamicInfo) {
        let autosave = false;
        if ("autosave" in options) {
            autosave = exprToBoolean(options.autosave);
        } else if (["list", "kanban"].includes(viewType)) {
            autosave = true;
        }
        return {
            readonly: dynamicInfo.readonly,
            autosave,
        };
    },
};

registerField("color", colorField);
