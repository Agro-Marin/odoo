/** @odoo-module native */
import { RottingKanbanHeader } from "@mail/js/rotting_mixin/rotting_kanban_header";
import { _t } from "@web/core/translation";

import { ProjectTaskGroupConfigMenu } from "./project_task_group_config_menu.js";

export class ProjectTaskKanbanHeader extends RottingKanbanHeader {
    static template = "project.ProjectTaskKanbanHeader";
    static components = {
        ...RottingKanbanHeader.components,
        GroupConfigMenu: ProjectTaskGroupConfigMenu,
    };

    /**
     * The step's WIP limit, or 0 when the column has none.
     *
     * A limit of 0 means "no limit" (the field's own default), so it must read
     * as absent rather than as a limit of zero that every column exceeds.
     *
     * @returns {number}
     */
    get wipLimit() {
        const limits = this.props.list.model.wipLimits;
        return (limits && limits[this.props.group.value]) || 0;
    }

    /**
     * Whether this column holds more tasks than its step allows.
     *
     * Counted against `group.count`, i.e. the tasks the current search shows,
     * which on a project board with the default "open tasks" filter is exactly
     * the work in progress the limit is about.
     *
     * @returns {boolean}
     */
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
