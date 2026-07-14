/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import {
    StateSelectionField,
    stateSelectionField,
} from "@web/fields/selection/state_selection/state_selection_field";
import { useCommand } from "@web/services/commands/command_hook";
import { formatSelection } from "@web/fields/formatters";

import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";

export class ProjectTaskStateSelection extends StateSelectionField {
    static template = "project.ProjectTaskStateSelection";

    static props = {
        ...stateSelectionField.component.props,
        isToggleMode: { type: Boolean, optional: true },
        viewType: { type: String },
    };

    setup() {
        this.state = useState({
            isStateButtonHighlighted: false,
        });
        // 'todo' is consumed by project_workflow_step_state (step.task_state='todo').
        // Removing it from any of icons/colorIcons/colorButton or from the unshift
        // list in get options() breaks 1,300+ active tasks — see t19628, t21386.
        // The Hoot test in tests/project_task_state_selection.test.js asserts the
        // dropdown still includes "To Do" — it is the primary safeguard.
        this.icons = {
            "todo": "o_status o_status_todo",
            "in_progress": "o_status",
            "approved": "o_status o_status_green",
            "changes_requested": "fa-solid fa-exclamation-circle fa-lg",
            "done": "fa-solid fa-check-circle fa-lg",
            "canceled": "fa-solid fa-times-circle fa-lg",
            "blocked": "fa-solid fa-hourglass fa-lg",
        };
        this.colorIcons = {
            "todo": "",
            "in_progress": "",
            "approved": "text-success",
            "changes_requested": "o_status_changes_requested",
            "done": "text-success",
            "canceled": "text-danger",
            "blocked": "btn-outline-info",
        };
        this.colorButton = {
            "todo": "btn-outline-info",
            "in_progress": "btn-outline-secondary",
            "approved": "btn-outline-success",
            "changes_requested": "btn-outline-warning",
            "done": "btn-outline-success",
            "canceled": "btn-outline-danger",
            "blocked": "btn-outline-info",
        };
        if (this.props.viewType != 'form') {
            super.setup();
        } else {
            const commandName = _t("Set state as...");
            useCommand(
                commandName,
                () => {
                    return {
                        placeholder: commandName,
                        providers: [
                            {
                                provide: () =>
                                    this.options.map(subarr => ({
                                        name: subarr[1],
                                        action: () => {
                                            this.updateRecord(subarr[0]);
                                        },
                                    })),
                            },
                        ],
                    };
                },
                {
                    category: "smart_action",
                    hotkey: "alt+f",
                    isAvailable: () => !this.props.readonly,
                }
            );
        }
    }

    get options() {
        const labels = new Map(super.options);
        const states = ["canceled", "done"];
        const currentState = this.props.record.data[this.props.name];
        if (currentState != "blocked") {
            states.unshift("todo", "in_progress", "changes_requested", "approved");
        }
        return states.map((state) => [state, labels.get(state)]);
    }

    get label() {
        const waitOption = super.options.findLast(([state]) => state === "blocked");
        const fullSelection = [...this.options, waitOption];
        return formatSelection(this.currentValue, {
            selection: fullSelection,
        });
    }

    stateIcon(value) {
        return this.icons[value] || "";
    }

    /**
     * @override
     */
    statusColor(value) {
        return this.colorIcons[value] || "";
    }

    /**
     * determine if a single click will trigger the toggleState() method
     * which will switch the state from in progress to done.
     * Either the isToggleMode is active on the record OR the task is_private
     */
    get isToggleMode() {
        return this.props.isToggleMode || !this.props.record.data.project_id;
    }

    isView(viewNames) {
        return viewNames.includes(this.props.viewType);
    }

    async toggleState() {
        const toggleVal = this.currentValue == "done" ? "in_progress" : "done";
        await this.updateRecord(toggleVal);
    }

    getDropdownPosition() {
        if (this.isView(['activity', 'kanban', 'list', 'calendar']) || this.env.isSmall) {
            return '';
        }
        return 'bottom-end';
    }

    getTogglerClass(currentValue) {
        if (this.isView(['activity', 'kanban', 'list', 'calendar']) || this.env.isSmall) {
            return 'btn btn-link d-flex p-0';
        }
        return 'o_state_button btn rounded-pill ' + this.colorButton[currentValue];
    }

    async updateRecord(value) {
        await super.updateRecord(value);
        this.state.isStateButtonHighlighted = false;
    }

    onMouseEnterStateButton() {
        if (!this.env.isSmall) {
            this.state.isStateButtonHighlighted = true;
        }
    }

    onMouseLeaveStateButton() {
        this.state.isStateButtonHighlighted = false;
    }
}

export const projectTaskStateSelection = {
    ...stateSelectionField,
    component: ProjectTaskStateSelection,
    fieldDependencies: [{ name: "project_id", type: "many2one" }],
    supportedOptions: [
        ...stateSelectionField.supportedOptions, {
            label: _t("Is toggle mode"),
            name: "is_toggle_mode",
            type: "boolean"
        }
    ],
    extractProps({ options, viewType }) {
        const props = stateSelectionField.extractProps(...arguments);
        props.isToggleMode = Boolean(options.is_toggle_mode);
        props.viewType = viewType;
        return props;
    },
}

registry.category("fields").add("project_task_state_selection", projectTaskStateSelection);
