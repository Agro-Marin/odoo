// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/highlight_text/settings_radio_field - RadioField variant with search-term highlighting on option labels */

import { registerField } from "@web/fields/_registry";
import { RadioField, radioField } from "@web/fields/selection/radio/radio_field";

import { HighlightText } from "./highlight_text.js";
export class SettingsRadioField extends RadioField {
    static template = "web.SettingsRadioField";
    static components = {
        .../** @type {any} */ (RadioField).components,
        HighlightText,
    };
}

export const settingsRadioField = {
    ...radioField,
    component: SettingsRadioField,
};

registerField({ name: "radio", view: "base_settings" }, settingsRadioField);
