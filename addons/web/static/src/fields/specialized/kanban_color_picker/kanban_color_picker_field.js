// @ts-check
/** @odoo-module native */

import { ColorList } from "@web/components/colorlist/colorlist";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

class KanbanColorPickerField extends FieldComponent {
    static template = "web.KanbanColorPickerField";
    static props = standardFieldProps;

    /** @returns {number[]} */
    get colors() {
        return ColorList.COLORS;
    }

    /**
     * @param {number} colorIndex
     * @returns {Promise<any>}
     */
    selectColor(colorIndex) {
        return this.field.update(colorIndex, { save: true });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const kanbanColorPickerField = {
    component: KanbanColorPickerField,
    displayName: _t("Color Picker"),
    interactiveOutsideEdition: true,
    supportedTypes: ["integer"],
};

registerField("kanban_color_picker", kanbanColorPickerField);
