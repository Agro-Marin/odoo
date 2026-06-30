/** @odoo-module native */
import { ListRenderer } from "@web/views/list/list_renderer";
import { getRawValue } from "@web/views/kanban/kanban_record";
import { ProjectTaskGroupConfigMenu } from "../project_task_kanban/project_task_group_config_menu.js";

export class ProjectProjectListRenderer extends ListRenderer {
    static components = {
        ...ListRenderer.components,
        GroupConfigMenu: ProjectTaskGroupConfigMenu,
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
        if (this._areSelectedProjectsInSameCompany === undefined) {
            const selection = this.props.list.selection;
            const companyId = selection.length && getRawValue(selection[0], field);
            this._areSelectedProjectsInSameCompany = selection.every(
                (project) => getRawValue(project, field) === companyId
            );
            Promise.resolve().then(() => {
                delete this._areSelectedProjectsInSameCompany;
            });
        }
        return this._areSelectedProjectsInSameCompany;
    }

    isCellReadonly(column, record) {
        let readonly = super.isCellReadonly(column, record);
        if (!readonly && column.name === "phase_id") {
            readonly = !this.haveAllSelectedProjectsSameField("company_id");
        }
        return readonly;
    }
}
