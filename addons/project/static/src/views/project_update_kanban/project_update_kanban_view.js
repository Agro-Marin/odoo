/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { ProjectUpdateKanbanController } from './project_update_kanban_controller.js';
import { ProjectRelationalModel } from "../project_relational_model.js";

export const projectUpdateKanbanView = {
    ...kanbanView,
    Controller: ProjectUpdateKanbanController,
    Model: ProjectRelationalModel,
};

registry.category('views').add('project_update_kanban', projectUpdateKanbanView);
