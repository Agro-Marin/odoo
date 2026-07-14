/** @odoo-module native */
import { ProjectTaskTemplateDropdown } from "../components/project_task_template_dropdown.js";
import { RottingKanbanController } from "@mail/js/rotting_mixin/rotting_kanban_controller";


export class ProjectTaskKanbanController extends RottingKanbanController {
    static template = "project.ProjectTaskKanbanView";
    static components = {
        ...RottingKanbanController.components,
        ProjectTaskTemplateDropdown,
    };

}
