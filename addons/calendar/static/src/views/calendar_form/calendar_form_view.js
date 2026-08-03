/** @odoo-module native */
import { CalendarFormController } from "@calendar/views/calendar_form/calendar_form_controller";
import { CalendarFormModel } from "@calendar/views/calendar_form/calendar_form_model";
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form";

export const CalendarFormView = {
    ...formView,
    Controller: CalendarFormController,
    Model: CalendarFormModel,
};

registry.category("views").add("calendar_form", CalendarFormView);
