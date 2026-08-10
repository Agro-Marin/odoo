/** @odoo-module native */
import { RottingKanbanController } from "@mail/views/web/rotting/rotting_kanban_controller";

import { ProjectTaskTemplateDropdown } from "../components/project_task_template_dropdown.js";

export class ProjectTaskKanbanController extends RottingKanbanController {
    static template = "project.ProjectTaskKanbanView";
    static components = {
        ...RottingKanbanController.components,
        ProjectTaskTemplateDropdown,
    };
}
