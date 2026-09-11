/** @odoo-module native */
import { KanbanRenderer } from "@web/views/kanban";
import { AppointmentTypeActionHelper } from "@calendar/booking/components/appointment_type_action_helper/appointment_type_action_helper";

export class AppointmentTypeKanbanRenderer extends KanbanRenderer {
    static template = "calendar.booking.AppointmentTypeKanbanRenderer";
    static components = {
        ...KanbanRenderer.components,
        AppointmentTypeActionHelper,
    };
}
