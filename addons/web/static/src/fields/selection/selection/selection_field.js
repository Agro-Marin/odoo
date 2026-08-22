// @ts-check
/** @odoo-module native */

import { SelectMenu } from "@web/components/select_menu/select_menu";
import { hasTouch } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { placeholderFieldOption } from "@web/fields/field_options";
import { isFalseEmpty } from "@web/fields/field_utils";
import { SelectionLikeField } from "@web/fields/selection/selection_like_field";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class SelectionField extends SelectionLikeField {
    static components = {
        SelectMenu,
    };
    static template = "web.SelectionField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
        required: { type: Boolean, optional: true },
        domain: { type: [Array, Function], optional: true },
        context: { type: Object, optional: true },
        autosave: { type: Boolean, optional: true },
    };
    static defaultProps = {
        autosave: false,
    };

    get choices() {
        return this.options.map(([value, label]) => ({ value, label }));
    }
    get isBottomSheet() {
        return this.env.isSmall && hasTouch();
    }
    get options() {
        switch (this.type) {
            case "many2one":
                return this.specialData.data;
            case "selection":
                return this.field.definition.selection.filter(
                    (option) => option[1] !== "",
                );
            default:
                return [];
        }
    }

    onChange(value) {
        switch (this.type) {
            case "many2one":
                if (value === null) {
                    this.field.update(false, { save: this.props.autosave });
                } else {
                    const option = this.options.find((option) => option[0] === value);
                    if (!option) {
                        return;
                    }
                    this.field.update(
                        { id: option[0], display_name: option[1] },
                        { save: this.props.autosave },
                    );
                }
                break;
            case "selection":
                this.field.update(value ?? false, { save: this.props.autosave });
                break;
        }
    }
}

export const selectionField = {
    component: SelectionField,
    displayName: _t("Selection"),
    supportedOptions: [placeholderFieldOption()],
    supportedTypes: ["many2one", "selection"],
    isEmpty: isFalseEmpty,
    interactiveOutsideEdition: ({ viewType }) => viewType === "kanban",
    extractProps({ viewType, placeholder }, dynamicInfo) {
        return {
            autosave: viewType === "kanban",
            placeholder,
            required: dynamicInfo.required,
            domain: dynamicInfo.domain,
            context: dynamicInfo.context,
        };
    },
};

registerField("selection", /** @type {any} */ (selectionField));
