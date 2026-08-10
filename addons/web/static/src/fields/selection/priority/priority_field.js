// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/priority/priority_field */

import { Component, onWillRender, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { extractAutosave } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { useCommand } from "@web/ui/commands/command_hook";

export class PriorityField extends Component {
    static template = "web.PriorityField";
    static props = {
        ...standardFieldProps,
        withCommand: { type: Boolean, optional: true },
        autosave: { type: Boolean, optional: true },
    };
    static defaultProps = {
        autosave: true,
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** @type {{ index: number }} */
    state;
    /** @type {Array<[any, string]>} */
    options;

    setup() {
        this.state = useState({
            index: -1,
        });
        this.options = Array.from(this.field.definition.selection);
        onWillRender(() => {
            this._selectedIndex = this.options.findIndex(
                (o) => o[0] === this.field.value,
            );
        });
        if (this.props.withCommand) {
            for (const command of this.commands) {
                useCommand(/** @type {any} */ (command[0]), command[1], command[2]);
            }
        }
    }

    get commands() {
        const commandName = _t("Set priority...");
        return [
            [
                commandName,
                () => ({
                    placeholder: commandName,
                    providers: [
                        {
                            provide: () =>
                                this.options.map((value) => ({
                                    name: value[1],
                                    action: () => {
                                        this.updateRecord(value[0]);
                                    },
                                })),
                        },
                    ],
                }),
                {
                    category: "smart_action",
                    hotkey: "alt+r",
                    isAvailable: () => !this.props.readonly,
                },
            ],
        ];
    }

    get tooltipLabel() {
        return this.field.definition.string;
    }
    get index() {
        return this.state.index > -1 ? this.state.index : this._selectedIndex;
    }

    /** @param {any} value */
    getTooltip(value) {
        return this.tooltipLabel && this.tooltipLabel !== value
            ? `${this.tooltipLabel}: ${value}`
            : value;
    }
    /**
     * @param {string} value
     */
    onStarClicked(value) {
        if (this.field.value === value) {
            this.state.index = -1;
            this.updateRecord(this.options[0][0]);
        } else {
            this.updateRecord(value);
        }
    }

    /** @param {any} value */
    async updateRecord(value) {
        await this.props.record.update(
            { [this.props.name]: value },
            { save: this.props.autosave },
        );
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const priorityField = {
    component: PriorityField,
    displayName: _t("Priority"),
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
    ],
    supportedTypes: ["selection"],
    extractProps({ options, viewType }, dynamicInfo) {
        return {
            withCommand: viewType === "form",
            autosave: extractAutosave(options),
        };
    },
};

registerField("priority", priorityField);
