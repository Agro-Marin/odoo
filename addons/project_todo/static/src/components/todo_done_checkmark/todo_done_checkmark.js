/** @odoo-module native */
import { useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    StateSelectionField,
    stateSelectionField,
} from "@web/fields/selection/state_selection/state_selection_field";

export class TodoDoneCheckmark extends StateSelectionField {
    static template = "project_todo.TodoDoneCheckmark";

    setup() {
        super.setup();
        this.frozen = useState({ isDone: null });
        onMounted(() => {
            const value = this.props.record.data[this.props.name];
            this.notDoneState = value === "done" ? "in_progress" : value;
        });
    }

    get isDone() {
        return this.frozen.isDone ?? this.props.record.data[this.props.name] === "done";
    }

    get toggleTitle() {
        return this.isDone ? _t("Mark as to-do") : _t("Mark as done");
    }

    /** @private */
    actualizeDoneState() {
        this.frozen.isDone = null;
    }

    /** @private */
    freezeDoneState() {
        this.frozen.isDone = this.isDone;
    }

    /** @private */
    async onDoneToggled() {
        const value =
            this.props.record.data[this.props.name] !== "done"
                ? "done"
                : this.notDoneState;
        await this.updateRecord(value);
    }
}

export const todoDoneCheckmark = {
    ...stateSelectionField,
    component: TodoDoneCheckmark,
};

registry.category("fields").add("todo_done_checkmark", todoDoneCheckmark);
