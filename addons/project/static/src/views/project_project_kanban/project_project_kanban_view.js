/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { ProjectRelationalModel } from "../project_relational_model.js";
import { ProjectKanbanController } from "./project_project_kanban_controller.js";
import { ProjectProjectKanbanRenderer } from "./project_project_kanban_renderer.js";

export const projectProjectKanbanView = {
    ...kanbanView,
    Controller: ProjectKanbanController,
    Renderer: ProjectProjectKanbanRenderer,
    Model: ProjectRelationalModel,
};

registry.category("views").add("project_project_kanban", projectProjectKanbanView);
