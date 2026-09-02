/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { TimeOffKanbanController } from "./kanban_controller.js";
import { TimeOffKanbanRenderer } from "./kanban_renderer.js";

const TimeOffKanbanView = {
    ...kanbanView,
    Renderer: TimeOffKanbanRenderer,
    Controller: TimeOffKanbanController,
};

registry.category("views").add("time_off_kanban_dashboard", TimeOffKanbanView);
