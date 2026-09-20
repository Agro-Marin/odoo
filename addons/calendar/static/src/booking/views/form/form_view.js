/** @odoo-module native */
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form";

import { AppointmentTypeFormController } from "./form_controller.js";

export const AppointmentTypeFormView = {
    ...formView,
    Controller: AppointmentTypeFormController,
};

registry.category("views").add("appointment_type_form_view", AppointmentTypeFormView);
