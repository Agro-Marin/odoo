/** @odoo-module native */
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";

import { AnalyticAccountFormController } from "./analytic_account_form_controller.js";

export const AnalyticAccountFormView = {
    ...formView,
    Controller: AnalyticAccountFormController,
};

registry.category("views").add("analytic_account_form_view", AnalyticAccountFormView);
