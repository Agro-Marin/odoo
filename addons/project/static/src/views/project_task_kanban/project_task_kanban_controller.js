/** @odoo-module native */
import { RottingKanbanController } from "@mail/views/web/rotting/rotting_kanban_controller";
import { useService } from "@web/core/utils/hooks";

import { ProjectTaskTemplateDropdown } from "../components/project_task_template_dropdown.js";

export class ProjectTaskKanbanController extends RottingKanbanController {
    static template = "project.ProjectTaskKanbanView";
    static components = {
        ...RottingKanbanController.components,
        ProjectTaskTemplateDropdown,
    };

    setup() {
        super.setup();
        this.ui = useService("ui");
    }
}
