// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/state_selection/state_selection_field */

import { Component } from "@odoo/owl";
import { CheckboxItem } from "@web/components/dropdown/checkbox_item";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { formatSelection } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { extractAutosave } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { useCommand } from "@web/ui/commands/command_hook";

export class StateSelectionField extends Component {
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
                            !this.props.readonly &&
                            this.props.record.data[this.props.name] !== value,
                    },
                );
            }
        }
    }
    /** @returns {Array<[string, string]>} */
    get options() {
        return this.props.record.fields[this.props.name].selection.map(
            (/** @type {[any, any]} */ [state, label]) => [
                state,
                this.props.record.data[`legend_${state}`] || label,
            ],
        );
    }
    /** @returns {string} */
    get currentValue() {
        return this.props.record.data[this.props.name] || this.options[0][0];
    }
    /** @returns {string} */
    get label() {
        const stateValue = this.props.record.data[this.props.name];
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
        await this.props.record.update(
            { [this.props.name]: value },
            { save: this.props.autosave },
        );
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const stateSelectionField = {
    component: StateSelectionField,
    displayName: _t("State Selection"),
    interactiveOutsideEdition: true,
    supportedOptions: [
        {
            label: _t("Autosave"),
            name: "autosave",
            type: "boolean",
            default: true,
            help: _t(
                "If checked, the record will be saved immediately when the field is modified.",
            ),
        },
        {
            label: _t("Hide label"),
            name: "hide_label",
            type: "boolean",
        },
    ],
    supportedTypes: ["selection"],
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
