/** @odoo-module */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";

import { RottingKanbanController } from "./rotting_kanban_controller.js";
import { RottingKanbanRenderer } from "./rotting_kanban_renderer.js";

export const rottingKanbanView = {
    ...kanbanView,
    Controller: RottingKanbanController,
    Renderer: RottingKanbanRenderer,
};

registry.category("views").add("rotting_kanban", rottingKanbanView);
