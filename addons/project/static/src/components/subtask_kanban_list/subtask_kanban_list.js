/** @odoo-module native */
import { Component, useState } from "@odoo/owl";

import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

import { Field, getPropertyFieldInfo } from "@web/fields/field";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { SubtaskCreate } from "./subtask_kanban_create/subtask_kanban_create.js";

export class SubtaskKanbanList extends Component {
    static components = {
        Field,
        SubtaskCreate,
    };
    static props = {
        ...standardWidgetProps,
        isReadonly: {
            type: Boolean,
            optional: true,
        },
    };
    static template = "project.SubtaskKanbanList";

    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.subtaskCreate = useState({
            open: false,
            name: "",
        });
    }

    get list() {
        return this.props.record.data.child_ids;
    }

    get closedList() {
        // Recompute on every render: a subtask toggling to done/canceled does
        // not change the record count, so a count-keyed cache would keep the
        // now-closed subtask in the open list. `records`/`data.state` are
        // reactive, so OWL re-renders when a child's state changes.
        return this.list.records.filter(
            (subtask) => !["done", "canceled"].includes(subtask.data.state)
        );
    }

    get fieldInfo() {
        return {
            state: {
                ...getPropertyFieldInfo({
                    name: "state",
                    type: "selection",
                    widget: "project_task_state_selection",
                }),
                viewType: "kanban",
            },
        };
    }

    async goToSubtask(subtask_id) {
        return this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: this.list.resModel,
            res_id: subtask_id,
            views: [[false, "form"]],
            target: "current",
            context: {
                active_id: subtask_id,
            },
        });
    }

    async onSubTaskCreated(ev) {
        this.subtaskCreate.open = true;
    }

    async _onBlur() {
        this.subtaskCreate.open = false;
    }

    async _onSubtaskCreateNameChanged(name) {
        if (name.trim() === "") {
            this.notification.add(_t("Invalid Display Name"), {
                type: "danger",
            });
        } else {
            const sequences = this.list.records.map(r => r.data.sequence);
            const nextSequence = (sequences.length ? Math.max(...sequences) : 0) + 1;

            await this.orm.create("project.task", [{
                display_name: name,
                parent_id: this.props.record.resId,
                project_id: this.props.record.data.project_id.id,
                user_ids: this.props.record.data.user_ids.resIds,
                sequence: nextSequence,
            }]);
            this.subtaskCreate.open = false;
            this.subtaskCreate.name = "";
            await this.props.record.load();
        }
    }
}

const subtaskKanbanList = {
    component: SubtaskKanbanList,
};

registry.category("view_widgets").add("subtask_kanban_list", subtaskKanbanList);
