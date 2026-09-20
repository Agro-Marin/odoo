/** @odoo-module native */
import { AppointmentTypeListController } from "@calendar/booking/views/list/list_controller";
import {
    AppointmentBookingListRenderer,
    AppointmentTypeListRenderer,
} from "@calendar/booking/views/list/list_renderer";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list";

export const AppointmentBookingListView = {
    ...listView,
    Renderer: AppointmentBookingListRenderer,
};

registry.category("views").add("appointment_booking_list", AppointmentBookingListView);

export const AppointmentTypeListView = {
    ...listView,
    Controller: AppointmentTypeListController,
    Renderer: AppointmentTypeListRenderer,
};

registry.category("views").add("appointment_type_list", AppointmentTypeListView);
