/** @odoo-module native */
import { ListRenderer } from "@web/views/list/list_renderer";
import { getRawValue } from "@web/views/kanban/kanban_record";
import { ProjectProjectGroupConfigMenu } from "../project_project_kanban/project_project_group_config_menu.js";

export class ProjectProjectListRenderer extends ListRenderer {
    static components = {
        ...ListRenderer.components,
        GroupConfigMenu: ProjectProjectGroupConfigMenu,
    };

    /**
     * This method prevents from computing the selection once for each cell when
     * rendering the list. Indeed, `selection` is a getter which browses all the
     * records, so computing it for each cell slows down the rendering a lot on
     * large tables. It also prevents from iterating over the selection to
     * compare the projects' companies for each cell.
     *
     * @returns {boolean} whether all selected projects share the same value for
     *      the given field.
     */
    haveAllSelectedProjectsSameField(field) {
        // Cache keyed by field (see project_task_list_renderer): a single
        // field-agnostic flag would return the first field's answer if called
        // for two different fields in the same render/microtask window.
        this._sameFieldCache ??= {};
        if (!(field in this._sameFieldCache)) {
            const selection = this.props.list.selection;
            const value = selection.length && getRawValue(selection[0], field);
            this._sameFieldCache[field] = selection.every(
                (project) => getRawValue(project, field) === value
            );
            Promise.resolve().then(() => {
                delete this._sameFieldCache;
            });
        }
        return this._sameFieldCache[field];
    }

    isCellReadonly(column, record) {
        let readonly = super.isCellReadonly(column, record);
        if (!readonly && column.name === "phase_id") {
            readonly = !this.haveAllSelectedProjectsSameField("company_id");
        }
        return readonly;
    }
}
