/** @odoo-module */
import { registry } from "@web/core/registry";

import { rottingKanbanView } from "@mail/js/rotting_mixin/rotting_kanban_view";
import { ProjectTaskKanbanController } from "./project_task_kanban_controller.js";
import { ProjectTaskKanbanModel } from "./project_task_kanban_model.js";
import { ProjectTaskKanbanRenderer } from './project_task_kanban_renderer.js';
import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";

export const projectTaskKanbanView = {
    ...rottingKanbanView,
    ControlPanel: ProjectTaskControlPanel,
    Model: ProjectTaskKanbanModel,
    Renderer: ProjectTaskKanbanRenderer,
    Controller: ProjectTaskKanbanController,
};

registry.category('views').add('project_task_kanban', projectTaskKanbanView);
