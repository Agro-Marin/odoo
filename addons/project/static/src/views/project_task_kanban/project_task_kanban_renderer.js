/** @odoo-module native */
import { RottingKanbanRenderer } from "@mail/views/web/rotting/rotting_kanban_renderer";
import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";

import { ProjectTaskKanbanHeader } from "./project_task_kanban_header.js";
import { ProjectTaskKanbanRecord } from "./project_task_kanban_record.js";

export class ProjectTaskKanbanRenderer extends RottingKanbanRenderer {
    static components = {
        ...RottingKanbanRenderer.components,
        KanbanRecord: ProjectTaskKanbanRecord,
        KanbanHeader: ProjectTaskKanbanHeader,
    };

    setup() {
        super.setup();

        onWillStart(async () => {
            this.isProjectManager = await user.hasGroup(
                "project.group_project_manager",
            );
        });
    }

    canCreateGroup() {
        // This restrict the creation of project stages to the kanban view of a given project
        const { context, groupByField } = this.props.list;
        const isGroupedByStage = groupByField?.name === "step_id";
        return (
            super.canCreateGroup() &&
            ((!!context.default_project_id === isGroupedByStage &&
                this.isProjectManager) ||
                groupByField.name === "triage_id")
        );
    }
}
