/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { ProjectRelationalModel } from "../project_relational_model.js";
import { ProjectUpdateKanbanController } from "./project_update_kanban_controller.js";

export const projectUpdateKanbanView = {
    ...kanbanView,
    Controller: ProjectUpdateKanbanController,
    Model: ProjectRelationalModel,
};

registry.category("views").add("project_update_kanban", projectUpdateKanbanView);
