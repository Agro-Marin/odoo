/** @odoo-module native */
import { BuilderList } from "@html_builder/core/building_blocks/builder_list";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { BuilderButtonGroup } from "./building_blocks/builder_button_group.js";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { BuilderDateTimePicker } from "./building_blocks/builder_datetimepicker.js";
import { BuilderRow } from "./building_blocks/builder_row.js";
import { BuilderButton } from "./building_blocks/builder_button.js";
import { BuilderNumberInput } from "./building_blocks/builder_number_input.js";
import { BuilderSelect } from "./building_blocks/builder_select.js";
import { BuilderSelectItem } from "./building_blocks/builder_select_item.js";
import { BuilderColorPicker } from "./building_blocks/builder_colorpicker.js";
import { BuilderTextInput } from "./building_blocks/builder_text_input.js";
import { BuilderCheckbox } from "./building_blocks/builder_checkbox.js";
import { BuilderRange } from "./building_blocks/builder_range.js";
import { BuilderContext } from "./building_blocks/builder_context.js";
import { BasicMany2Many } from "./building_blocks/basic_many2many.js";
import { BuilderMany2Many } from "./building_blocks/builder_many2many.js";
import { BuilderMany2One } from "./building_blocks/builder_many2one.js";
import { ModelMany2Many } from "./building_blocks/model_many2many.js";
import { Plugin } from "@html_editor/plugin";
import { Img } from "./img.js";
import { BuilderUrlPicker } from "./building_blocks/builder_urlpicker.js";
import { BuilderFontFamilyPicker } from "./building_blocks/builder_fontfamilypicker.js";

/** @typedef {import("@odoo/owl").Component} Component */
/**
 * @typedef { Object } BuilderComponentShared
 * @property { BuilderComponentPlugin['getComponents'] } getComponents
 */

/** @typedef {Component[]} builder_components */

export class BuilderComponentPlugin extends Plugin {
    static id = "builderComponents";
    static shared = ["getComponents"];

    /** @type {import("plugins").BuilderResources} */
    resources = {
        builder_components: {
            BuilderContext,
            BuilderFontFamilyPicker,
            BuilderRow,
            BuilderUrlPicker,
            Dropdown,
            DropdownItem,
            BuilderButtonGroup,
            BuilderButton,
            BuilderTextInput,
            BuilderNumberInput,
            BuilderRange,
            BuilderColorPicker,
            BuilderSelect,
            BuilderSelectItem,
            BuilderCheckbox,
            BasicMany2Many,
            BuilderMany2Many,
            BuilderMany2One,
            ModelMany2Many,
            BuilderDateTimePicker,
            BuilderList,
            Img,
        },
    };

    setup() {
        this.Components = {};
        for (const r of this.getResource("builder_components")) {
            for (const C in r) {
                if (C in this.Components) {
                    throw new Error(`Duplicated builder component: ${C}`);
                }
                this.Components[C] = r[C];
            }
        }
    }

    getComponents() {
        return this.Components;
    }
}
