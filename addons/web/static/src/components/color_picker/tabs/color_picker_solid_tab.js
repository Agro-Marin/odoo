// @ts-check
/** @odoo-module native */

/** @module @web/components/color_picker/tabs/color_picker_solid_tab - Color picker tab rendering the preset solid color palette grid */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
export class ColorPickerSolidTab extends Component {
    static template = "web.ColorPickerSolidTab";
    static props = {
        colorPickerNavigation: Function,
        onColorClick: Function,
        onColorPointerOver: Function,
        onColorPointerOut: Function,
        onFocusin: Function,
        onFocusout: Function,
        currentCustomColor: { type: String, optional: true },
        defaultColorSet: { type: [String, Boolean], optional: true },
        cssVarColorPrefix: { type: String, optional: true },
        defaultColors: Array,
        defaultThemeColorVars: Array,
        "*": { optional: true },
    };
}

registry.category("color_picker_tabs").add(
    "web.solid",
    {
        id: "solid",
        name: _t("Solid"),
        component: ColorPickerSolidTab,
    },
    // Solid is the default tab and must render first so keyboard navigation
    // (Tab moves Solid -> Custom -> Gradient) starts on it. Custom registers at
    // the default sequence (50); pin Solid below it so ordering no longer
    // depends on module evaluation order (which the ESM bundling reshuffled).
    { sequence: 40 },
);
