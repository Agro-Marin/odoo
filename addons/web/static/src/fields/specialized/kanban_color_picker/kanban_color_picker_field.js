// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/kanban_color_picker/kanban_color_picker_field */

import { Component } from "@odoo/owl";
import { ColorList } from "@web/components/colorlist/colorlist";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

class KanbanColorPickerField extends Component {
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
        return this.props.record.update(
            { [this.props.name]: colorIndex },
            { save: true },
        );
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const kanbanColorPickerField = {
    component: KanbanColorPickerField,
    displayName: _t("Color Picker"),
    interactiveOutsideEdition: true,
    supportedTypes: ["integer"],
};

registerField("kanban_color_picker", kanbanColorPickerField);
