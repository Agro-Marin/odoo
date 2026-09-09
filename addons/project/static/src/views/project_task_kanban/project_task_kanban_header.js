/** @odoo-module native */
import { RottingKanbanHeader } from "@mail/views/web/rotting/rotting_kanban_header";
import { _t } from "@web/core/translation";

import { ProjectTaskGroupConfigMenu } from "./project_task_group_config_menu.js";

export class ProjectTaskKanbanHeader extends RottingKanbanHeader {
    static template = "project.ProjectTaskKanbanHeader";
    static components = {
        ...RottingKanbanHeader.components,
        GroupConfigMenu: ProjectTaskGroupConfigMenu,
    };

    /** @returns {number} */
    get wipLimit() {
        const limits = this.props.list.model.wipLimits;
        return (limits && limits[this.props.group.value]) || 0;
    }

    /** @returns {boolean} */
    get isOverWipLimit() {
        return this.wipLimit > 0 && this.props.group.count > this.wipLimit;
    }

    /** @returns {string} */
    get wipLimitTitle() {
        return _t("%(count)s tasks in this step, over its WIP limit of %(limit)s.", {
            count: this.props.group.count,
            limit: this.wipLimit,
        });
    }
}
