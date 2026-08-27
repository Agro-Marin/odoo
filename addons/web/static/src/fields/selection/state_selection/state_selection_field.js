// @ts-check
/** @odoo-module native */

import { CheckboxItem } from "@web/components/dropdown/checkbox_item";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { formatSelection } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { autosaveOption } from "@web/fields/field_options";
import { extractAutosave } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { useCommand } from "@web/ui/commands/command_hook";

export class StateSelectionField extends FieldComponent {
    static template = "web.StateSelectionField";
    static components = {
        Dropdown,
        CheckboxItem,
    };
    static props = {
        ...standardFieldProps,
        showLabel: { type: Boolean, optional: true },
        withCommand: { type: Boolean, optional: true },
        autosave: { type: Boolean, optional: true },
    };
    static defaultProps = {
        showLabel: true,
        autosave: true,
    };

    /** @type {Record<string, string>} */
    colors;

    setup() {
        this.colorPrefix = "o_status_";
        this.colors = {
            blocked: "red",
            done: "green",
        };
        if (this.props.withCommand) {
            const hotkeys = ["D", "F", "G"];
            for (const [index, [value, label]] of this.options.entries()) {
                useCommand(
                    _t("Set kanban state as %s", label),
                    () => {
                        this.updateRecord(value);
                    },
                    {
                        category: "smart_action",
                        hotkey: hotkeys[index] && `alt+${hotkeys[index]}`,
                        isAvailable: () =>
                            !this.props.readonly && this.field.value !== value,
                    },
                );
            }
        }
    }
    /** @returns {Array<[string, string]>} */
    get options() {
        return this.field.definition.selection.map(
            (/** @type {[any, any]} */ [state, label]) => [
                state,
                this.props.record.data[`legend_${state}`] || label,
            ],
        );
    }
    /** @returns {string} */
    get currentValue() {
        return this.field.value || this.options[0][0];
    }
    /** @returns {string} */
    get label() {
        const stateValue = this.field.value;
        if (stateValue && this.props.record.data[`legend_${stateValue}`]) {
            return this.props.record.data[`legend_${stateValue}`];
        }
        return formatSelection(this.currentValue, { selection: this.options });
    }

    /**
     * @param {string} value
     * @returns {string}
     */
    statusColor(value) {
        return this.colors[value] ? this.colorPrefix + this.colors[value] : "";
    }

    /** @param {string} value */
    async updateRecord(value) {
        await this.field.update(value, { save: this.props.autosave });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const stateSelectionField = {
    component: StateSelectionField,
    displayName: _t("State Selection"),
    interactiveOutsideEdition: true,
    supportedOptions: [
        autosaveOption(),
        {
            label: _t("Hide label"),
            name: "hide_label",
            type: "boolean",
        },
    ],
    supportedTypes: ["selection"],
    fieldDependencies: [
        { name: "legend_normal", type: "char", optional: true, readonly: true },
        { name: "legend_blocked", type: "char", optional: true, readonly: true },
        { name: "legend_done", type: "char", optional: true, readonly: true },
    ],
    extractProps({ options, viewType }, dynamicInfo) {
        return {
            showLabel:
                "hide_label" in options ? !options.hide_label : viewType !== "kanban",
            withCommand: viewType === "form",
            autosave: extractAutosave(options),
        };
    },
};

registerField("state_selection", stateSelectionField);
