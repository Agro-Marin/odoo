/** @odoo-module native */
import { registry } from "@web/core/registry";
import { BooleanToggleField, booleanToggleField } from "@web/fields/basic/boolean_toggle/boolean_toggle_field";

export class TaskCheckMark extends BooleanToggleField {
    static template = "project.TaskCheckMark";

    get isReached() {
        return Boolean(this.props.record.data[this.props.name]);
    }

    async onToggle() {
        if (this.props.readonly) {
            return;
        }
        // Base onChange handles the update, the autosave option and the
        // optimistic-state rollback on a rejected save.
        await this.onChange(!this.isReached);
    }
}

export const taskCheckMark = {
    ...booleanToggleField,
    component: TaskCheckMark,
}

registry.category("fields").add("task_done_checkmark", taskCheckMark);
