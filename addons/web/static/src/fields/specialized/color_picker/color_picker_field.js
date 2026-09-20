// @ts-check
/** @odoo-module native */
import { ColorList } from "@web/components/colorlist/colorlist";
import { RECORD_COLOR_INDICES } from "@web/core/colors/colors";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { isFalseEmpty } from "@web/fields/field_utils";
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

    static RECORD_COLORS = RECORD_COLOR_INDICES;

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
    displayName: _t("Color Index"),
    isEmpty: isFalseEmpty,
    supportedTypes: ["integer"],
    extractProps: ({ viewType }) => ({
        canToggle: viewType !== "list",
    }),
};

registerField("color_picker", colorPickerField);
