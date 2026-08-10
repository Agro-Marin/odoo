/** @odoo-module native */
import { rottingKanbanView } from "@mail/views/web/rotting/rotting_kanban_view";
import { registry } from "@web/core/registry";

import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskKanbanController } from "./project_task_kanban_controller.js";
import { ProjectTaskKanbanModel } from "./project_task_kanban_model.js";
import { ProjectTaskKanbanRenderer } from "./project_task_kanban_renderer.js";

export const projectTaskKanbanView = {
    ...rottingKanbanView,
    ControlPanel: ProjectTaskControlPanel,
    Model: ProjectTaskKanbanModel,
    Renderer: ProjectTaskKanbanRenderer,
    Controller: ProjectTaskKanbanController,
};

registry.category("views").add("project_task_kanban", projectTaskKanbanView);
