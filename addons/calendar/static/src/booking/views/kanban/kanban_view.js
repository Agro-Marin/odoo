/** @odoo-module native */
import { AppointmentTypeKanbanController } from "@calendar/booking/views/kanban/kanban_controller";
import { AppointmentTypeKanbanRenderer } from "@calendar/booking/views/kanban/kanban_renderer";
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

export const AppointmentTypeKanbanView = {
    ...kanbanView,
    Renderer: AppointmentTypeKanbanRenderer,
    Controller: AppointmentTypeKanbanController,
    buttonTemplate: "AppointmentTypeKanbanView.buttons",
};
registry.category("views").add("appointment_type_kanban", AppointmentTypeKanbanView);
