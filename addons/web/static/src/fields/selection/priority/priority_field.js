// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/priority/priority_field - Star rating field for priority Selection columns */

import { Component, onWillRender, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { useCommand } from "@web/services/commands/command_hook";

export class PriorityField extends Component {
    static template = "web.PriorityField";
    static props = {
        ...standardFieldProps,
        withCommand: { type: Boolean, optional: true },
        autosave: { type: Boolean, optional: true },
    };

    /** @type {{ index: number }} */
    state;

    setup() {
        this.state = useState({
            index: -1,
        });
        // The selection is static: build the options list once.
        this.options = Array.from(this.props.record.fields[this.props.name].selection);
        // The template reads `index` twice per star: compute the selected
        // index once per render.
        onWillRender(() => {
            this._selectedIndex = this.options.findIndex(
                (o) => o[0] === this.props.record.data[this.props.name],
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
        return this.props.record.fields[this.props.name].string;
    }
    get index() {
        return this.state.index > -1 ? this.state.index : this._selectedIndex;
    }

    getTooltip(value) {
        return this.tooltipLabel && this.tooltipLabel !== value
            ? `${this.tooltipLabel}: ${value}`
            : value;
    }
    /**
     * @param {string} value
     */
    onStarClicked(value) {
        if (this.props.record.data[this.props.name] === value) {
            this.state.index = -1;
            this.updateRecord(this.options[0][0]);
        } else {
            this.updateRecord(value);
        }
    }

    async updateRecord(value) {
        await this.props.record.update(
            { [this.props.name]: value },
            { save: this.props.autosave },
        );
    }
}

export const priorityField = {
    component: PriorityField,
    displayName: _t("Priority"),
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
            readonly: dynamicInfo.readonly,
            autosave: "autosave" in options ? !!options.autosave : true,
        };
    },
};

registerField("priority", priorityField);
