// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
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
    { sequence: 40 },
);
