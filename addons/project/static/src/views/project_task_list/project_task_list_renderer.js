/** @odoo-module native */
import { ListRenderer } from "@web/views/list/list_renderer";
import { getRawValue } from "@web/views/kanban/kanban_record";
import { ProjectTaskGroupConfigMenu } from "../project_task_kanban/project_task_group_config_menu.js";

export class ProjectTaskListRenderer extends ListRenderer {
    static components = {
        ...ListRenderer.components,
        GroupConfigMenu: ProjectTaskGroupConfigMenu,
    };

    /**
     * This method prevents from computing the selection once for each cell when
     * rendering the list. Indeed, `selection` is a getter which browses all
     * records, so computing it for each cell slows down the rendering a lot on
     * large tables. Moreover, it also prevents from iterating over the selection
     * to compare tasks' projects or partners.
     *
     * Returns true if all selected tasks have the same value for the specified field.
     */
    haveAllSelectedTasksSameField(field) {
        // Cache keyed by field: a single field-agnostic flag would return the
        // first field's answer if this is called for two different fields in
        // the same render/microtask window.
        this._sameFieldCache ??= {};
        if (!(field in this._sameFieldCache)) {
            const selection = this.props.list.selection;
            const value = selection.length && getRawValue(selection[0], field);
            this._sameFieldCache[field] = selection.every(
                (task) => getRawValue(task, field) === value
            );
            Promise.resolve().then(() => {
                delete this._sameFieldCache;
            });
        }
        return this._sameFieldCache[field];
    }
    isCellReadonly(column, record) {
        let readonly = false;
        if (column.name === "step_id") {
            readonly = !this.haveAllSelectedTasksSameField('project_id');
        }
        return readonly || super.isCellReadonly(column, record);
    }
}
