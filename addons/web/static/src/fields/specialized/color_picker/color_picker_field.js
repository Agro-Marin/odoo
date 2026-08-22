// @ts-check
/** @odoo-module native */

import { ColorList } from "@web/components/colorlist/colorlist";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ColorPickerField extends FieldComponent {
    static template = "web.ColorPickerField";
    static components = {
        ColorList,
    };
    static props = {
        ...standardFieldProps,
        canToggle: { type: Boolean },
    };

    static RECORD_COLORS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

    /** @returns {boolean} */
    get isExpanded() {
        return !this.props.canToggle && !this.props.readonly;
    }

    /** @param {number} colorIndex */
    switchColor(colorIndex) {
        this.field.update(colorIndex);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const colorPickerField = {
    component: ColorPickerField,
    supportedTypes: ["integer"],
    extractProps: ({ viewType }) => ({
        canToggle: viewType !== "list",
    }),
};

registerField("color_picker", colorPickerField);
