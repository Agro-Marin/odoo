/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { DEFAULT_GRADIENT_COLORS } from "@web/core/colors/colors";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { applyOpacityToGradient, isColorGradient } from "@web/core/utils/format/colors";

import { GradientPicker } from "./gradient_picker/gradient_picker.js";

export class ColorPickerGradientTab extends Component {
    static template = "html_editor.ColorPickerGradientTab";
    static components = { GradientPicker };
    static props = {
        applyColor: Function,
        onColorClick: Function,
        onColorPreview: Function,
        onColorPointerOver: Function,
        onColorPointerOut: Function,
        onFocusin: Function,
        onFocusout: Function,
        setOnCloseCallback: { type: Function, optional: true },
        setOperationCallbacks: { type: Function, optional: true },
        defaultOpacity: { type: Number, optional: true },
        noTransparency: { type: Boolean, optional: true },
        selectedColor: { type: String, optional: true },
        "*": { optional: true },
    };
    setup() {
        this.state = useState({
            showGradientPicker: false,
        });
        this.applyOpacityToGradient = applyOpacityToGradient;
        this.DEFAULT_GRADIENT_COLORS = DEFAULT_GRADIENT_COLORS;
    }

    getCurrentGradientColor() {
        if (isColorGradient(this.props.selectedColor)) {
            return this.props.selectedColor;
        }
    }

    toggleGradientPicker() {
        this.state.showGradientPicker = !this.state.showGradientPicker;
    }
}

registry.category("color_picker_tabs").add(
    "html_editor.gradient",
    {
        id: "gradient",
        name: _t("Gradient"),
        component: ColorPickerGradientTab,
    },
    { sequence: 60 },
);
