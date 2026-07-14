/** @odoo-module native */
import { RottingKanbanRenderer } from "@mail/js/rotting_mixin/rotting_kanban_renderer";
import { ProjectTaskKanbanRecord } from './project_task_kanban_record.js';
import { ProjectTaskKanbanHeader } from './project_task_kanban_header.js';
import { onWillStart } from "@odoo/owl";
import { user } from "@web/services/user";

export class ProjectTaskKanbanRenderer extends RottingKanbanRenderer {
    static components = {
        ...RottingKanbanRenderer.components,
        KanbanRecord: ProjectTaskKanbanRecord,
        KanbanHeader: ProjectTaskKanbanHeader,
    };

    setup() {
        super.setup();

        onWillStart(async () => {
            this.isProjectManager = await user.hasGroup('project.group_project_manager');
        });
    }

    canCreateGroup() {
        // This restrict the creation of project stages to the kanban view of a given project
        const { context, groupByField } = this.props.list;
        const isGroupedByStage = groupByField?.name === "step_id";
        return (
            super.canCreateGroup() &&
            ((!!context.default_project_id === isGroupedByStage && this.isProjectManager) ||
                groupByField.name === "triage_id")
        );
    }
}
